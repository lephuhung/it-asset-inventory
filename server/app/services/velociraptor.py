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
  - gRPC/VQL cho **search_clients / get_all_clients** và collect — chạy trực tiếp
    trên Velociraptor Server qua mTLS, parse JSON streaming response.

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

import httpx
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

logger = logging.getLogger("velociraptor")


class VelociraptorError(Exception):
    """Lỗi khi gọi Velociraptor API."""


class VelociraptorClient:
    """Wrapper Velociraptor Server — REST compatibility + gRPC/VQL mTLS.

    Dùng như context manager:
        async with VelociraptorClient(url, username="admin", password="…",
                                      api_connection_string="veloci.example:8001") as client:
            clients = await client.get_all_clients()
            hunt_id = await client.create_hunt("Hunt", ["Generic.Client.Info"])

    VQL và collect dùng gRPC; không cần Docker daemon hay container name.
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
        api_connection_string: str | None = None,
        grpc_target_name: str = "VelociraptorServer",
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
        self.api_connection_string = (api_connection_string or "").strip()
        self.grpc_target_name = grpc_target_name
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
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

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
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
        """Test gRPC/mTLS, giữ nguyên contract response cũ của portal."""
        try:
            clients = await self._vql_query("SELECT client_id FROM clients() LIMIT 1")
            return {"ok": True, "client_count_sampled": len(clients)}
        except VelociraptorError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"Không kết nối Velociraptor: {e}"}

    async def collect_artifact(
        self, client_id: str, artifacts: list[str], env: dict | None = None
    ) -> str:
        """Collect artifact bằng VQL qua gRPC/mTLS, trả ``flow_id``.

        ``collect_client`` chạy ở Velociraptor Server. Không tạo file tạm hay
        thực thi lệnh trong container, nên backend và Velociraptor có thể ở hai
        máy hoàn toàn độc lập.
        """
        if not artifacts:
            raise VelociraptorError("artifacts list rỗng")
        # Truyền client_id + artifact dạng literal trong VQL (không qua env) —
        # env biến không resolve được khi làm tham số của hàm collect_client().
        vql = (
            "SELECT collect_client("
            f"client_id={_vql_str_literal(client_id)}, "
            f"artifacts={_vql_str_literal(artifacts[0])}) "
            "AS Collection FROM scope()"
        )
        rows = await self._vql_query(vql, env=env)
        for row in rows:
            collection = row.get("Collection") or row
            if isinstance(collection, dict) and collection.get("flow_id"):
                return str(collection["flow_id"])
            download = row.get("Download")
            if isinstance(download, list) and len(download) >= 3:
                return str(download[2])
        raise VelociraptorError("Velociraptor không trả flow_id sau khi collect artifact")

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
        """Trả status của 1 hunt qua gRPC/VQL."""
        vql = f"SELECT * FROM hunts() WHERE hunt_id = \"{hunt_id}\" LIMIT 1"
        items = await self._vql_query(vql)
        return items[0] if items else {"hunt_id": hunt_id, "error": "not found"}

    async def get_hunt(self, hunt_id: str) -> dict:
        """Trả metadata hunt qua gRPC/VQL."""
        vql = f"SELECT * FROM hunts() WHERE hunt_id = \"{hunt_id}\" LIMIT 1"
        items = await self._vql_query(vql)
        return items[0] if items else {"hunt_id": hunt_id, "error": "not found"}

    async def list_client_flows(
        self, client_id: str, limit: int = 50
    ) -> list[dict]:
        """List flows (hunts/collections/interrogations) cho 1 client.

        Dùng gRPC VQL `flows()`.
        Returns: list dict — mỗi dict là flow metadata.
        """
        # Velociraptor VQL: session_id = flow_id, create_time/start_time ở dạng int µs
        vql = (
            f"SELECT session_id AS FlowId, state AS State, "
            f"request.artifacts AS Artifacts, create_time AS Created, "
            f"active_time AS LastActive, total_uploaded_bytes AS Mb, "
            f"total_collected_rows AS Rows, request.creator AS Creator "
            f"FROM flows(client_id=\"{client_id}\") "
            f"ORDER BY create_time DESC LIMIT {int(limit)}"
        )
        return await self._vql_query(vql)

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

        Velociraptor external automation dùng gRPC VQL
        thay vì `GET /api/v1/GetClient/{client_id}`.
        """
        vql = (
            f"SELECT client_id, os_info, last_seen_at, last_ip, agent_information "
            f"FROM clients() WHERE client_id = \"{client_id}\" LIMIT 1"
        )
        items = await self._vql_query(vql)
        if not items:
            return {"client_id": client_id, "error": "client not found"}
        item = items[0]
        # VQL trả timestamp dạng int (microseconds since epoch) → convert sang ISO string
        if isinstance(item.get("last_seen_at"), int):
            try:
                ts = item["last_seen_at"] / 1_000_000  # µs → seconds
                item["last_seen_at"] = datetime.fromtimestamp(ts, tz=UTC).isoformat()
            except (ValueError, OSError):
                pass
        # first_seen_at + last_seen_at ở dạng int seconds (since epoch) - convert sang ISO
        for k in ("first_seen_at", "last_seen_at"):
            v = item.get(k)
            if isinstance(v, int):
                try:
                    # Velociraptor trả int seconds (không phải ns/µs) - thử cả 3 đơn vị
                    for divisor in (1, 1_000_000, 1_000_000_000):
                        try:
                            ts = v / divisor
                            if 1_000_000_000 < ts < 4_102_444_800:  # giữa 1970 và 2100
                                item[k] = datetime.fromtimestamp(ts, tz=UTC).isoformat()
                                break
                        except (ValueError, OSError):
                            continue
                except (ValueError, OSError):
                    pass
        return item

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

        Dùng gRPC VQL `flows()`.
        Returns: {"context": {"state": "RUNNING"|"FINISHED"|"ERROR"}, ...}
        """
        vql = (
            f"SELECT state, status, request FROM flows(client_id=\"{client_id}\") "
            f"WHERE session_id = \"{flow_id}\" LIMIT 1"
        )
        items = await self._vql_query(vql)
        if not items:
            return {"context": {"state": "RUNNING", "status": ""}}
        item = items[0]
        return {
            "context": {
                "state": item.get("state", "RUNNING"),
                "status": item.get("status", ""),
                "request": item.get("request") or {},
            }
        }

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

        Dùng gRPC VQL `source()` — bắt buộc truyền đủ client_id + flow_id + artifact;
        thiếu client_id thì Velociraptor `source()` trả rỗng (không có cell scope).
        """
        # VQL: SELECT * FROM source(client_id=..., flow_id=..., artifact=...) LIMIT N
        vql = (
            f"SELECT * FROM source("
            f"client_id=\"{client_id}\", flow_id=\"{flow_id}\", artifact=\"{artifact}\") "
            f"LIMIT {int(rows)}"
        )
        return await self._vql_query(vql)

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

    # ── VQL: gRPC/mTLS remote API ──────────────────────────────

    async def _vql_query(self, vql: str, env: dict[str, str] | None = None) -> list[dict]:
        """Chạy server-side VQL qua gRPC API, không phụ thuộc Docker.

        Các bindings gRPC là synchronous; chạy chúng trong executor để không chặn
        event loop FastAPI. Dữ liệu biến được truyền qua VQL environment thay vì
        nội suy vào query string.
        """
        if not self.api_connection_string:
            raise VelociraptorError(
                "Thiếu api_connection_string trong api_client.yaml; hãy sinh lại cấu hình "
                "API client cho Velociraptor remote."
            )
        if not (self.ca_cert_pem and self.client_cert_pem and self.client_key_pem):
            raise VelociraptorError("VQL gRPC yêu cầu api_client.yaml với đầy đủ certificate mTLS")

        def _query() -> list[dict]:
            try:
                import grpc
                from pyvelociraptor import api_pb2, api_pb2_grpc
            except ImportError as exc:
                raise VelociraptorError(
                    "Thiếu dependency gRPC Velociraptor; cài pyvelociraptor và grpcio."
                ) from exc

            credentials = grpc.ssl_channel_credentials(
                root_certificates=self.ca_cert_pem.encode("utf-8"),
                private_key=self.client_key_pem.encode("utf-8"),
                certificate_chain=self.client_cert_pem.encode("utf-8"),
            )
            options = (("grpc.ssl_target_name_override", self.grpc_target_name),)
            request = api_pb2.VQLCollectorArgs(
                max_wait=1,
                max_row=1000,
                timeout=self.timeout,
                Query=[api_pb2.VQLRequest(Name="inventory-backend", VQL=vql)],
                env=[{"key": key, "value": value} for key, value in (env or {}).items()],
            )
            rows: list[dict] = []
            try:
                with grpc.secure_channel(self.api_connection_string, credentials, options) as channel:
                    for response in api_pb2_grpc.APIStub(channel).Query(request, timeout=self.timeout):
                        if not response.Response:
                            continue
                        payload = json.loads(response.Response)
                        if isinstance(payload, list):
                            rows.extend(item for item in payload if isinstance(item, dict))
            except Exception as exc:  # grpc errors are optional dependency types
                code = getattr(exc, "code", lambda: None)()
                details_method = getattr(exc, "details", None)
                details = details_method() if callable(details_method) else str(exc)
                raise VelociraptorError(f"Velociraptor gRPC lỗi ({code or 'unknown'}): {details}") from exc
            return rows

        return await asyncio.get_running_loop().run_in_executor(None, _query)

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

        Dùng gRPC VQL `clients()`.
        """
        vql = (
            f"SELECT client_id, os_info FROM clients() LIMIT {int(page_size)}"
        )
        return await self._vql_query(vql)


def _shell_quote(s: str) -> str:
    """Quote 1 chuỗi để chạy an toàn trong shell single-quoted."""
    return "'" + s.replace("'", "'\\''") + "'"


def _vql_str_literal(s: str) -> str:
    """Bọc 1 chuỗi thành VQL string literal (double-quoted, escape an toàn).

    Dùng khi nội suy giá trị (client_id, artifact…) trực tiếp vào VQL — tránh
    chèn ký tự lạ / phá hỏng cú pháp VQL.
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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

    Trả về dict với keys: ca_cert, client_cert, client_private_key,
    api_connection_string, name (optional).
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

    connection = data.get("api_connection_string")
    if not connection or not isinstance(connection, str) or ":" not in connection:
        raise ValueError(
            "YAML thiếu hoặc sai 'api_connection_string' (ví dụ velociraptor.example.gov.vn:8001)"
        )

    return {
        "ca_cert": ca_cert,
        "client_cert": data["client_cert"],
        "client_private_key": data["client_private_key"],
        "api_connection_string": connection.strip(),
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
