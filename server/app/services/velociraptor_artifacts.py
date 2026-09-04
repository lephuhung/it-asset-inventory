"""Quản trị Velociraptor artifact tuỳ chỉnh (`Custom.*`).

Super Admin nạp artifact definition (YAML) từ portal; backend validate, đẩy lên
Velociraptor server qua VQL `artifact_set()` (server-side, chạy trên gRPC/mTLS) và
lưu bản ghi vào DB để re-push khi server Velociraptor được dựng lại.

Ràng buộc an toàn:
  - Chỉ namespace `Custom.*` — không bao giờ ghi đè artifact built-in.
  - Không chấp nhận section `tools:` (tránh artifact kéo binary ngoài về endpoint).
  - YAML truyền qua VQL env binding, không nội suy vào query string.
  - YAML definition không bao giờ xuất hiện trong log/audit.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

import yaml

from app.services.velociraptor import VelociraptorClient, VelociraptorError

logger = logging.getLogger("velociraptor.artifacts")

MAX_DEFINITION_BYTES = 262_144  # 256 KiB
CUSTOM_PREFIX = "Custom."
_NAME_RE = re.compile(r"^Custom\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")
_ALLOWED_TYPES = {"CLIENT", "CLIENT_EVENT", "SERVER", "SERVER_EVENT"}


class ArtifactValidationError(ValueError):
    """Artifact definition không hợp lệ — message an toàn để trả về client."""


class ArtifactPushError(RuntimeError):
    """Push artifact lên Velociraptor thất bại — message an toàn."""


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    artifact_type: str
    definition_yaml: str
    sha256: str


def validate_artifact_definition(text: str) -> ArtifactSpec:
    """Validate YAML artifact definition, trả ArtifactSpec đã chuẩn hoá.

    Raises ArtifactValidationError với message ngắn gọn, không chứa nội dung YAML.
    """
    raw = text.encode("utf-8", errors="strict")
    if not raw or len(raw) > MAX_DEFINITION_BYTES:
        raise ArtifactValidationError(
            f"Artifact YAML phải có kích thước 1 byte đến {MAX_DEFINITION_BYTES // 1024}KB"
        )
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ArtifactValidationError(f"Artifact YAML không parse được: {type(exc).__name__}") from exc
    if not isinstance(doc, dict):
        raise ArtifactValidationError("Artifact YAML phải là một mapping (key: value)")

    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ArtifactValidationError("Artifact thiếu trường `name`")
    name = name.strip()
    if not _NAME_RE.fullmatch(name):
        raise ArtifactValidationError(
            "Tên artifact phải thuộc namespace Custom.* và chỉ gồm chữ, số, gạch dưới, dấu chấm"
        )

    raw_type = doc.get("type", "CLIENT")
    if not isinstance(raw_type, str) or raw_type.strip().upper() not in _ALLOWED_TYPES:
        raise ArtifactValidationError(
            "Trường `type` phải là CLIENT, CLIENT_EVENT, SERVER hoặc SERVER_EVENT"
        )
    artifact_type = raw_type.strip().upper()

    if "tools" in doc:
        raise ArtifactValidationError(
            "Artifact có section `tools:` (tải binary ngoài) không được chấp nhận"
        )

    sources = doc.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ArtifactValidationError("Artifact phải có ít nhất một `sources` entry")
    for source in sources:
        if not isinstance(source, dict):
            raise ArtifactValidationError("Mỗi `sources` entry phải là mapping")
        queries = source.get("queries")
        query = source.get("query")
        if queries is None and query is None:
            raise ArtifactValidationError("Mỗi `sources` entry phải có `query` hoặc `queries`")
        if queries is not None and (
            not isinstance(queries, list) or not all(isinstance(q, str) for q in queries)
        ):
            raise ArtifactValidationError("`queries` phải là danh sách chuỗi VQL")
        if query is not None and not isinstance(query, str):
            raise ArtifactValidationError("`query` phải là chuỗi VQL")

    return ArtifactSpec(
        name=name,
        artifact_type=artifact_type,
        definition_yaml=text,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


async def list_server_artifacts(
    client: VelociraptorClient, *, prefix: str = CUSTOM_PREFIX
) -> set[str]:
    """Tên artifact hiện có trên server (mặc định chỉ namespace Custom.*)."""
    rows = await client.vql(
        "SELECT name FROM artifact_definitions() WHERE name =~ Prefix",
        env={"Prefix": f"^{prefix}"},
    )
    return {str(row["name"]) for row in rows if isinstance(row.get("name"), str)}


async def push_artifact(client: VelociraptorClient, spec: ArtifactSpec) -> None:
    """Đẩy artifact lên server bằng `artifact_set()` rồi verify lại.

    Pre-check chặn ghi đè artifact không thuộc Custom.* (defense-in-depth — tên đã
    qua validate). Verify sau push bằng `artifact_definitions()`.
    """
    # artifact_definitions(name=...) không lọc exact-match (probe thực nghiệm trên
    # server dev trả rỗng kể cả khi artifact tồn tại) → lọc bằng WHERE name = Name.
    existing = await client.vql(
        "SELECT name FROM artifact_definitions() WHERE name = Name", env={"Name": spec.name}
    )
    if existing and not spec.name.startswith(CUSTOM_PREFIX):
        raise ArtifactPushError(f"Artifact {spec.name} tồn tại và không thuộc namespace Custom.*")

    try:
        await client.vql(
            "SELECT artifact_set(definition=Definition) AS Name FROM scope()",
            env={"Definition": spec.definition_yaml},
        )
    except VelociraptorError as exc:
        raise ArtifactPushError(f"Velociraptor từ chối artifact: {exc}") from exc

    verified = await client.vql(
        "SELECT name FROM artifact_definitions() WHERE name = Name", env={"Name": spec.name}
    )
    if not verified:
        raise ArtifactPushError(
            f"Velociraptor không nạp artifact {spec.name} sau khi push"
        )
