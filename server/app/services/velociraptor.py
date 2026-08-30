"""Wrapper Velociraptor Server — phục vụ DFIR.

Velociraptor (https://github.com/velocidex/velociraptor) là nền tảng DFIR endpoint
agent (điều tra số, thu thập bằng chứng từ xa). Có 2 cách giao tiếp:

  1. **REST API** (port 8889 — cùng GUI) — HTTP Basic auth (username:password).
     Hỗ trợ: CreateHunt, ModifyHunt, GetHuntStatus, CollectArtifact...
     KHÔNG HỖ TRỢ list clients trực tiếp (SearchClients chỉ trả autocomplete
     data cho GUI search box — không phải full client list).

  2. **gRPC streaming + VQL** (Velociraptor-native) — Velociraptor Client dùng gRPC
     + mTLS + CA pin để enroll. Từ phía server, VQL qua CLI
     (`velociraptor --config server.config.yaml query "..."`) cho phép liệt kê
     clients, hosts, flows... đầy đủ.

Cách ta dùng:
  - REST API (HTTP Basic) cho **hunt/collect** — CreateHunt, ModifyHunt, v.v.
    (chỉ cần vài endpoint, không cần list).
  - VQL qua `docker exec` cho **search_clients / get_all_clients** — chạy
    `SELECT * FROM clients()` trong container Velociraptor, parse JSON output.

Lý do dùng docker exec thay vì gRPC thuần Python:
  - Velociraptor CLI đã wrap sẵn auth (dùng server.config.yaml) — ta không phải
    generate cert/key, build protobuf, handle gRPC streaming.
  - Đơn giản cho use case sync hostname ↔ client_id mỗi 5 phút.

Authentication chi tiết:
  - HTTP Basic (default authenticator của Velociraptor). User + password tạo
    bằng `velociraptor user add` hoặc admin mặc định qua env
    VELOCIRAPTOR_INITIAL_ADMIN_PASSWORD lúc khởi động container.
  - mTLS với client cert (`velociraptor config api_client`) cũng work NHƯNG
    cần đổi Velociraptor authenticator sang `type: Certs` (mặc định là Basic).
    Không mặc định vì setup phức tạp hơn.

API docs: https://docs.velociraptor.app/docs/server-automation/
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import docker
import httpx
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from docker.errors import APIError, NotFound

logger = logging.getLogger("velociraptor")


class VelociraptorError(Exception):
    """Lỗi khi gọi Velociraptor API."""


class VelociraptorClient:
    """Wrapper Velociraptor Server — REST API (Basic auth) + VQL (docker exec).

    Dùng như context manager:
        async with VelociraptorClient(url, username="admin", password="…",
                                      container="velociraptor") as client:
            clients = await client.get_all_clients()
            hunt_id = await client.create_hunt("Hunt", ["Generic.Client.Info"])

    `container` chỉ cần cho search_clients (VQL exec). Hunt/Collect qua REST API
    thì không cần.
    """

    BASE_PATH = "/api/v1"

    def __init__(
        self,
        server_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        client_cert_pem: str | None = None,
        client_key_pem: str | None = None,
        ca_cert_pem: str | None = None,
        container: str | None = None,
        timeout: int = 30,
        verify_ssl: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        url = server_url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("server_url phải bắt đầu bằng http:// hoặc https://")

        has_basic = bool(username and password)
        has_mtls = bool(client_cert_pem and client_key_pem and ca_cert_pem)
        if not has_basic and not has_mtls:
            raise ValueError(
                "Cần (username + password) HOẶC (client_cert_pem + client_key_pem + ca_cert_pem) "
                "— Velociraptor default authenticator = Basic; mTLS cần config Certs"
            )

        self.server_url = url
        self.username = username
        self.password = password
        self.client_cert_pem = client_cert_pem
        self.client_key_pem = client_key_pem
        self.ca_cert_pem = ca_cert_pem
        self.container = container
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._docker: docker.DockerClient | None = None
        self._temp_files: list[str] = []
        self._temp_dirs: list[str] = []

    async def __aenter__(self) -> Self:
        headers: dict[str, str] = {}
        ssl_ctx: ssl.SSLContext | None = None

        if self.client_cert_pem and self.client_key_pem and self.ca_cert_pem:
            ssl_ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
            tmp_dir = tempfile.mkdtemp(prefix="velo-mtls-")
            ca_path = Path(tmp_dir) / "ca.pem"
            cert_path = Path(tmp_dir) / "client.pem"
            key_path = Path(tmp_dir) / "client.key"
            ca_path.write_text(self.ca_cert_pem)
            cert_path.write_text(self.client_cert_pem)
            key_path.write_text(self.client_key_pem)
            self._temp_files.extend([str(ca_path), str(cert_path), str(key_path)])
            self._temp_dirs.append(tmp_dir)
            ssl_ctx.load_verify_locations(cafile=str(ca_path))
            ssl_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
            ssl_ctx.check_hostname = False  # cert CN cố định, không match hostname
        elif self.username and self.password:
            import base64
            credentials = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode("ascii")
            headers["Authorization"] = f"Basic {credentials}"

        # Referer required for CSRF (Velociraptor 0.77+). Nếu CSRF disabled
        # bằng VELOCIRAPTOR_DISABLE_CSRF=1 thì không cần — nhưng set luôn cho
        # an toàn (không ảnh hưởng request).
        headers["Referer"] = f"{self.server_url}/"

        self._client = httpx.AsyncClient(
            base_url=self.server_url + self.BASE_PATH,
            headers=headers,
            timeout=self.timeout,
            verify=ssl_ctx if ssl_ctx else self.verify_ssl,
            transport=self._transport,
        )

        # Docker client (sync — wrap với run_in_executor khi cần gọi từ async)
        # Chỉ khởi tạo khi cần (search_clients qua VQL).
        # Lazy init trong _vql_query().
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._docker:
            try:
                self._docker.close()
            except Exception:
                logger.debug("Docker client close failed", exc_info=True)
            self._docker = None
        for path_str in self._temp_files:
            try:
                Path(path_str).unlink(missing_ok=True)
            except OSError:
                pass
        self._temp_files.clear()
        import shutil
        for path_str in list(self._temp_dirs):
            try:
                shutil.rmtree(path_str, ignore_errors=True)
            except OSError:
                pass
        self._temp_dirs.clear()

    # ── HTTP helpers ──────────────────────────────────────────

    def _check_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("VelociraptorClient phải dùng qua `async with`")
        return self._client

    async def _post(self, path: str, body: dict | None = None) -> dict:
        client = self._check_client()
        try:
            r = await client.post(path, json=body or {})
            r.raise_for_status()
            return r.json() if r.content else {}
        except httpx.HTTPStatusError as e:
            raise VelociraptorError(
                f"Velociraptor POST {path} thất bại: HTTP {e.response.status_code} — "
                f"{e.response.text[:300]}"
            ) from e
        except httpx.RequestError as e:
            raise VelociraptorError(f"Không kết nối Velociraptor: {e}") from e

    async def _get(self, path: str) -> dict:
        client = self._check_client()
        try:
            r = await client.get(path)
            r.raise_for_status()
            return r.json() if r.content else {}
        except httpx.HTTPStatusError as e:
            raise VelociraptorError(
                f"Velociraptor GET {path} thất bại: HTTP {e.response.status_code} — "
                f"{e.response.text[:300]}"
            ) from e
        except httpx.RequestError as e:
            raise VelociraptorError(f"Không kết nối Velociraptor: {e}") from e

    # ── REST API: test_connection + hunt/collect ───────────

    async def test_connection(self) -> dict[str, Any]:
        """Test kết nối — gọi SearchClients autocomplete.

        200 = OK; 401/403 = auth fail; 5xx/connect-refused = server unreachable.
        """
        try:
            client = self._check_client()
            r = await client.get("/SearchClients", params={"name_only": "true", "limit": 1})
            r.raise_for_status()
            return {"ok": True}
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except VelociraptorError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"Không kết nối Velociraptor: {e}"}

    async def collect_artifact(
        self, client_id: str, artifacts: list[str], env: dict | None = None
    ) -> str:
        """POST /api/v1/CollectArtifact — trả flow_id (string)."""
        body: dict[str, Any] = {"client_id": client_id, "artifacts": artifacts}
        if env:
            body["env"] = env
        data = await self._post("/CollectArtifact", body)
        return str(data.get("flow_id", ""))

    async def create_hunt(
        self, name: str, artifacts: list[str], description: str = "",
        timeout_seconds: int = 0,
    ) -> str:
        """POST /api/v1/CreateHunt — trả hunt_id (string)."""
        body = {
            "name": name,
            "description": description or f"Hunt for {', '.join(artifacts)}",
            "artifacts": artifacts,
            "timeout": timeout_seconds,
        }
        data = await self._post("/CreateHunt", body)
        return str(data.get("hunt_id", ""))

    async def modify_hunt(
        self,
        hunt_id: str,
        *,
        add_client_ids: list[str] | None = None,
        remove_client_ids: list[str] | None = None,
        start: bool = False,
        stop: bool = False,
    ) -> dict:
        """POST /api/v1/ModifyHunt — add/remove clients + start/stop."""
        body: dict[str, Any] = {"hunt_id": hunt_id}
        if add_client_ids:
            body["add_client_ids"] = add_client_ids
        if remove_client_ids:
            body["remove_client_ids"] = remove_client_ids
        if start:
            body["start"] = True
        if stop:
            body["stop"] = True
        return await self._post("/ModifyHunt", body)

    async def get_hunt_status(self, hunt_id: str) -> dict:
        return await self._get(f"/GetHuntStatus/{hunt_id}")

    async def get_hunt(self, hunt_id: str) -> dict:
        return await self._get(f"/GetHunt/{hunt_id}")

    async def get_flow_results(self, flow_id: str, limit: int = 100) -> dict:
        """Lấy rows data cho 1 flow (hunt/collection/interrogation).

        Velociraptor API: POST /api/v1/GetTable?table=NotebookCells&flow_id=...
        Đơn giản hơn: POST /api/v1/GetFlowResults (một số version).
        Response: {"columns": [...], "rows": [...], "total_rows": N}
        Mỗi row có format giống GetClientFlows.

        Args:
          flow_id: ID của flow (F.xxxx...) — lấy từ VelociraptorClientFlowOut.FlowId.
          limit: số rows tối đa (mặc định 100, cap cứng 1000).
        """
        # Velociraptor 0.77: dùng POST /api/v1/GetTable với table=NotebookCells
        data = await self._post(
            "/GetTable",
            {"table": "NotebookCells", "flow_id": flow_id, "limit": int(limit)},
        )
        return data

    async def list_client_flows(
        self, client_id: str, limit: int = 50
    ) -> list[dict]:
        """List flows (hunts/collections/interrogations) cho 1 client.

        Velociraptor API: GET /api/v1/GetClientFlows?client_id=...&rows=...
        ⚠️ Tham số là `rows` — `limit` bị Velociraptor bỏ qua (default rows=1
        → chỉ trả flow mới nhất!). Response (Velociraptor 0.77):
        {"columns": [...], "rows": [...], "total_rows": N} — mỗi row có format
        {"State", "FlowId", "Artifacts", "Created", "Last Active", ...}
        → convert thành dict dễ dùng cho portal.
        """
        data = await self._get(f"/GetClientFlows?client_id={client_id}&rows={int(limit)}")

        columns = data.get("columns", [])
        rows = data.get("rows", [])
        out: list[dict] = []
        for r in rows:
            item = dict(zip(columns, r.get("json") if isinstance(r.get("json"), list) else [r.get(c) for c in columns]))
            # Nếu row có key "json" chứa JSON array → parse
            if isinstance(r.get("json"), str):
                import json as _json
                try:
                    parsed = _json.loads(r["json"])
                    if isinstance(parsed, list):
                        item = dict(zip(columns, parsed))
                except Exception:
                    pass
            out.append(item)
        return out

    async def list_artifacts(self) -> list[dict]:
        """Liệt kê artifacts Velociraptor có (admin chọn trong Collect dialog).

        Velociraptor API: POST /api/v1/ListAvailableEventResults
        """
        try:
            data = await self._post("/ListAvailableEventResults", {})
            items = data.get("artifacts", [])
            return [
                {
                    "name": a.get("name"),
                    "description": a.get("description", ""),
                    "category": a.get("category", ""),
                }
                for a in items
                if a.get("name")
            ]
        except VelociraptorError:
            return []

    async def get_client_metadata(self, client_id: str) -> dict:
        """Lấy metadata của 1 client (hostname, OS, last seen, IP, agent version...).

        Velociraptor API: GET /api/v1/GetClient/{client_id}
        GetClientMetadata/{client_id} trả near-empty (chỉ client_id).
        """
        return await self._get(f"/GetClient/{client_id}")

    # ── REST API: DFIR Top-N events (flows → tables) ──────────

    async def find_latest_finished_flow(
        self, client_id: str, artifact_name: str, limit: int = 50
    ) -> dict | None:
        """Tìm flow FINISHED gần nhất đã chạy artifact trên 1 client.

        Dùng lại dữ liệu đã thu thập (không collect lại) — chính là logic
        `get_latest_flow_for_artifact` trong script Top10. Velociraptor trả
        flows mới nhất trước (GetClientFlows), nên phần tử đầu tiên match
        artifact + FINISHED chính là flow gần nhất.

        Returns: dict flow (có FlowId, State, Artifacts, Created, Rows, Mb…)
        hoặc None nếu chưa từng chạy artifact này.
        """
        flows = await self.list_client_flows(client_id, limit=limit)
        for f in flows:
            artifacts = f.get("Artifacts") or []
            if artifact_name in artifacts and f.get("State") == "FINISHED":
                return f
        return None

    async def get_flow_details(self, client_id: str, flow_id: str) -> dict:
        """Lấy trạng thái chi tiết 1 flow (polling khi collect).

        Velociraptor API: GET /api/v1/GetFlowDetails?client_id=...&flow_id=...
        Response: {"context": {"state": "RUNNING"|"FINISHED"|"ERROR", ...}, ...}
        """
        return await self._get(
            f"/GetFlowDetails?client_id={client_id}&flow_id={flow_id}"
        )

    async def get_flow_status(self, client_id: str, flow_id: str) -> dict:
        """Trạng thái flow (dạng dễ dùng cho orchestrator).

        Returns:
            {"state": "RUNNING"|"FINISHED"|"ERROR", "is_running": bool,
             "error": str|None, "raw": <full GetFlowDetails response>}
        """
        details = await self.get_flow_details(client_id, flow_id)
        ctx = details.get("context") or {}
        state = str(ctx.get("state") or "").upper()
        is_running = state in ("RUNNING", "PENDING", "IN_PROGRESS", "")
        err: str | None = None
        if state == "ERROR":
            err = str(ctx.get("status") or "flow kết thúc với trạng thái ERROR")
        return {"state": state, "is_running": is_running, "error": err, "raw": details}

    async def get_flow_results(
        self,
        client_id: str,
        flow_id: str,
        artifact: str | None = None,
        max_rows: int = 5000,
    ) -> list[dict]:
        """Lấy kết quả flow — wrapper quanh get_table.

        Args:
            client_id: Velociraptor client_id
            flow_id: Velociraptor flow_id
            artifact: tên artifact (None = lấy artifact đầu tiên trong flow request)
            max_rows: số rows tối đa (default 5000, cap cứng trong Velociraptor)

        Returns:
            list[dict] — rows từ GetTable (mỗi row là dict theo schema artifact)
        """
        if not artifact:
            # Lấy artifact đầu tiên từ flow details
            details = await self.get_flow_details(client_id, flow_id)
            request = (details.get("context") or {}).get("request") or {}
            artifacts = request.get("artifacts") or []
            if not artifacts:
                return []
            artifact = str(artifacts[0])
        return await self.get_table(client_id, flow_id, artifact, rows=max_rows)

    async def get_table(
        self,
        client_id: str,
        flow_id: str,
        artifact: str,
        rows: int = 100,
    ) -> list[dict]:
        """Đọc bảng kết quả của 1 artifact trong 1 flow (rows → list dict).

        Velociraptor API: GET /api/v1/GetTable?client_id=...&flow_id=...&artifact=...&rows=...
        Response: {"columns": [...], "rows": [{"json": "[...]"}, ...], "total_rows": N}
        Mỗi row là 1 array JSON theo đúng thứ tự `columns` → zip thành dict.
        """
        data = await self._get(
            f"/GetTable?client_id={client_id}&flow_id={flow_id}"
            f"&artifact={_url_quote(artifact)}&rows={int(rows)}"
        )
        return _rows_to_dicts(data)

    async def collect_artifact_and_wait(
        self,
        client_id: str,
        artifact: str,
        *,
        timeout_seconds: int = 90,
        poll_interval: float = 1.5,
    ) -> str:
        """Collect artifact + poll GetFlowDetails cho tới khi FINISHED/ERROR.

        Giống `collect_artifact_sync` trong script Top10: gửi CollectArtifact,
        rồi poll mỗi `poll_interval` giây cho tới khi flow kết thúc hoặc quá
        `timeout_seconds`. Trả flow_id; raise VelociraptorError nếu timeout
        hoặc flow kết thúc với trạng thái lỗi.
        """
        flow_id = await self.collect_artifact(client_id, [artifact])
        if not flow_id:
            raise VelociraptorError(
                f"CollectArtifact không trả về flow_id cho artifact '{artifact}'"
            )

        deadline = time.monotonic() + timeout_seconds
        last_state = "RUNNING"
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)
            try:
                details = await self.get_flow_details(client_id, flow_id)
            except VelociraptorError:
                # Flow vừa tạo có thể chưa visible — retry tới deadline
                continue
            state = (details.get("context") or {}).get("state") or ""
            last_state = state
            if state == "FINISHED":
                return flow_id
            if state == "ERROR":
                err = (details.get("context") or {}).get("status") or "unknown error"
                raise VelociraptorError(
                    f"Flow {flow_id} ({artifact}) kết thúc lỗi: {err}"
                )

        raise VelociraptorError(
            f"Timeout sau {timeout_seconds}s chờ flow {flow_id} ({artifact}) "
            f"— trạng thái cuối: {last_state}"
        )

    # ── VQL: search_clients (qua docker exec) ──────────────────

    async def _vql_query(self, vql: str, container: str | None = None) -> list[dict]:
        """Chạy VQL trong Velociraptor container qua docker exec.

        Output Velociraptor CLI có dạng:
            [
             { "client_id": "...", "os_info": {...} },
             ...
            ]

        Args:
            vql: Velociraptor Query Language string
            container: container name (vd 'velociraptor'). Mặc định dùng self.container.
        """
        cname = container or self.container
        if not cname:
            raise VelociraptorError(
                "VQL query cần `container` (Velociraptor Docker container name). "
                "Cấu hình qua VelociraptorConfig hoặc truyền khi tạo client."
            )

        if self._docker is None:
            # Lazy init Docker client (sync SDK). Dùng unix socket mặc định.
            self._docker = docker.from_env()

        def _exec() -> str:
            try:
                container_obj = self._docker.containers.get(cname)
            except NotFound:
                raise VelociraptorError(
                    f"Docker container '{cname}' không tồn tại — kiểm tra `docker ps`."
                )
            cmd_str = (
                f"velociraptor --config /etc/velociraptor/server.config.yaml query "
                f"{_shell_quote(vql)}"
            )
            exec_result = container_obj.exec_run(
                ["sh", "-c", cmd_str],
                demux=True,
            )
            stdout, stderr = exec_result.output
            if exec_result.exit_code != 0:
                err = stderr.decode("utf-8", errors="replace") if stderr else ""
                raise VelociraptorError(
                    f"VQL exec thất bại (exit={exec_result.exit_code}): {err[:500]}"
                )
            return stdout.decode("utf-8", errors="replace") if stdout else ""

        loop = asyncio.get_event_loop()
        try:
            stdout = await loop.run_in_executor(None, _exec)
        except VelociraptorError:
            raise
        except APIError as e:
            raise VelociraptorError(f"Docker API lỗi: {e}") from e

        if not stdout.strip():
            return []
        try:
            data = json.loads(stdout)
            if isinstance(data, list):
                return data
            # Velociraptor đôi khi trả [[{...}]] (array lồng nhau) — flatten 1 cấp.
            if isinstance(data, list) and data and isinstance(data[0], list):
                return data[0]
            return []
        except json.JSONDecodeError as e:
            raise VelociraptorError(
                f"VQL output không phải JSON hợp lệ: {stdout[:300]}"
            ) from e

    async def search_clients(
        self, query: str = "", limit: int = 1000, offset: int = 0
    ) -> list[dict]:
        """Liệt kê clients qua REST API `GET /api/v1/SearchClients?query=&limit=`.

        Velociraptor REST API SearchClients trả JSON:
          {"items": [client1, client2, ...], "names": [...], "total": N,
           "search_term": {...}}
        `items` chứa full client metadata (client_id, os_info, last_seen_at...).
        Cũ: dùng VQL `SELECT * FROM clients()` — trả 0 vì VQL `clients()`
        đọc từ datastore khác (không pick up client mới enroll ngay).

        Args:
          query: VQL filter (vd "host:DEMO*"). Rỗng = list all.
          limit: số client tối đa (Velociraptor max ~1000/page).
          offset: hiện không dùng — Velociraptor phân trang theo `total` qua VQL.

        Returns: list dict — mỗi dict là ApiClient:
          {
            "client_id": "C.abc123...",
            "os_info": {"hostname": "DESKTOP-X", "system": "windows", ...},
            "agent_information": {...},
            "last_seen_at": 1787971375489683,   # Unix timestamp ns
            "last_ip": "10.10.0.150:65385",
            ...
          }
        """
        # Velociraptor 0.77+: query= (empty) trả full list dạng {"items": [...], "total": N}.
        # Dùng params rõ ràng để chắc chắn response có items[] (không phải autocomplete).
        client = self._check_client()
        params = {
            "query": query,
            "limit": int(limit),
            "name_only": "false",
        }
        r = await client.get("/SearchClients", params=params)
        r.raise_for_status()
        data = r.json() if r.content else {}
        return data.get("items", [])

    async def get_all_clients(self, page_size: int = 1000) -> list[dict]:
        """Lấy TOÀN BỘ clients (cho sync hostname mỗi 5 phút).

        Velociraptor 0.77 SearchClients API: query= (empty) + limit=1000 → trả
        đủ client trong 1 request (response có total field để check overflow).
        """
        return await self.search_clients(query="", limit=page_size)


def _shell_quote(s: str) -> str:
    """Quote 1 chuỗi để chạy an toàn trong shell single-quoted."""
    return "'" + s.replace("'", "'\\''") + "'"


def _url_quote(s: str) -> str:
    """Quote 1 đoạn URL query value (artifact name chứa dấu chấm là an toàn)."""
    from urllib.parse import quote

    return quote(s, safe="")


def _rows_to_dicts(data: dict) -> list[dict]:
    """Parse response GetClientFlows / GetTable → list dict.

    Velociraptor trả {"columns": [...], "rows": [{"json": "[v1,v2,...]"}, ...]}.
    Mỗi row có thể có `json` là string (array) hoặc list đã parse sẵn.
    """
    columns = data.get("columns") or []
    rows = data.get("rows") or []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        raw = r.get("json")
        values: list[Any] | None = None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    values = parsed
            except (json.JSONDecodeError, TypeError):
                values = None
        elif isinstance(raw, list):
            values = raw
        if values is not None:
            item = dict(zip(columns, values))
        else:
            # Fallback: row đã là dict phẳng (client_id, hostname...)
            item = {c: r.get(c) for c in columns}
        out.append(item)
    return out


# ── Client config helpers ───────────────────────────────────────


def parse_client_config_yaml(content: str) -> dict[str, str]:
    """Parse YAML từ `velociraptor config api_client` (Velociraptor 0.7+).

    Đầu ra Velociraptor có dạng:
        ca_certificate: |     # Velociraptor 0.77+ dùng 'ca_certificate'
          -----BEGIN CERTIFICATE-----
          ...
        client_cert: |
          -----BEGIN CERTIFICATE-----
          ...
        client_private_key: |
          -----BEGIN RSA PRIVATE KEY-----
          ...

    Cũng chấp nhận alias `ca_cert` (một số tool phiên bản cũ / fork).

    Trả về dict với keys: ca_cert, client_cert, client_private_key, name (optional).
    Raise ValueError nếu thiếu trường hoặc YAML lỗi.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML không hợp lệ: {e}") from e

    if not isinstance(data, dict):
        raise TypeError("YAML phải chứa 1 object (Velociraptor api_client config)")

    ca_cert = data.get("ca_cert") or data.get("ca_certificate")
    if not ca_cert or not isinstance(ca_cert, str):
        raise ValueError(
            "YAML thiếu trường 'ca_cert' hoặc 'ca_certificate' "
            "(sinh từ `velociraptor config api_client --name <name> --role <role>`)"
        )

    required = ("client_cert", "client_private_key")
    for k in required:
        if k not in data or not data[k]:
            raise ValueError(f"YAML thiếu trường bắt buộc: '{k}'")
        if not isinstance(data[k], str):
            raise TypeError(f"Trường '{k}' phải là string PEM")

    return {
        "ca_cert": ca_cert,
        "client_cert": data["client_cert"],
        "client_private_key": data["client_private_key"],
        "name": data.get("name", ""),
    }


def inspect_client_cert(cert_pem: str) -> dict[str, Any]:
    """Trích metadata từ client cert PEM — hiển thị portal xác nhận."""
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
    except Exception as e:
        raise ValueError(f"PEM cert không hợp lệ: {e}") from e

    def _format_name(name: x509.Name) -> str:
        return ", ".join(f"{attr.oid._name}={attr.value}" for attr in name)

    digest = hashes.Hash(hashes.SHA256())
    digest.update(cert.public_bytes(serialization.Encoding.DER))
    fp = digest.finalize().hex()
    fp_colon = ":".join(fp[i : i + 2] for i in range(0, len(fp), 2))

    def _to_iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()

    return {
        "subject": _format_name(cert.subject),
        "issuer": _format_name(cert.issuer),
        "not_valid_before": _to_iso(cert.not_valid_before_utc),
        "not_valid_after": _to_iso(cert.not_valid_after_utc),
        "sha256_fingerprint": fp_colon,
        "serial_number": str(cert.serial_number),
    }


# ── Hostname helpers ────────────────────────────────────────────


def normalize_hostname(hostname: str | None) -> str:
    """Chuẩn hoá hostname để so sánh (lowercase + strip FQDN)."""
    if not hostname:
        return ""
    h = hostname.strip().lower()
    if not h:
        return ""
    return h.split(".", 1)[0]


def hostname_from_velociraptor_client(client: dict) -> str:
    """Tách hostname chuẩn hoá từ client JSON trả về bởi VQL `SELECT * FROM clients()`."""
    os_info = client.get("os_info") or {}
    return normalize_hostname(os_info.get("hostname"))
