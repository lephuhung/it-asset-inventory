"""API endpoints AI cho sơ đồ mạng của hồ sơ:

  - POST /api/system-profiles/{id}/diagram/ai-generate → nhờ LLM vẽ layout JSON
  - POST /api/system-profiles/{id}/diagram/ai-review   → nhờ LLM rà soát sơ đồ

Dùng chung cấu hình LLM singleton của DFIR (`llm_config` id=1 — cùng base_url/
model/api_key mà LLM-DFIR đã cấu hình). Không mutate hồ sơ: endpoint chỉ gọi
LLM và trả kết quả; việc lưu layout là trách nhiệm của PATCH thường.
"""
from __future__ import annotations

import json
import logging
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.core.security import decrypt_aes_gcm
from app.db.models import DeviceType, SystemProfile, User
from app.services.llm import LlmClient, LlmError, LlmMessage

logger = logging.getLogger("system_profile.diagram_ai")

router = APIRouter(prefix="/api/system-profiles", tags=["system-profile-diagram-ai"])

# Node mặc định luôn hiện trên canvas (không thuộc danh mục thiết bị)
INTERNET_NODE_ID = "__internet__"
WORKSTATION_NODE_ID = "__workstation__"

LAYER_ORDER = ["firewall", "router", "switch", "server", "workstation", "storage", "ups", "other"]

DIAGRAM_SCHEMA_DOC = """{
  "version": 1,
  "nodes": { "<nodeId>": { "x": 280, "y": 0 } },
  "edges": [ { "source": "<nodeId>", "target": "<nodeId>", "label": "VLAN 10 — trunk" } ],
  "customNodes": [ { "id": "custom-1", "name": "Tên node mới", "deviceType": "other" } ],
  "notes": { "<nodeId>": "ghi chú hiển thị trên node (IP, dải IP, vlan...)" }
}"""


class DiagramAiGenerateIn(BaseModel):
    variant: str = Field(default="logic", pattern="^(logic|physical)$")


class DiagramAiGenerateOut(BaseModel):
    layout: dict
    model: str
    total_tokens: int = 0


class DiagramFindingOut(BaseModel):
    severity: str  # "high" | "medium" | "low"
    title: str
    detail: str


class DiagramAiReviewIn(BaseModel):
    variant: str = Field(default="logic", pattern="^(logic|physical)$")
    layout: dict | None = None


class DiagramAiReviewOut(BaseModel):
    findings: list[DiagramFindingOut]
    model: str
    total_tokens: int = 0


async def _load_llm_config(db: AsyncSession):
    """Load cấu hình LLM singleton (chung với DFIR); 400 nếu chưa bật."""
    from app.db.models import LlmConfig

    cfg = (await db.execute(select(LlmConfig).where(LlmConfig.id == 1))).scalar_one_or_none()
    if cfg is None or not cfg.enabled:
        raise HTTPException(400, "AI/LLM chưa được cấu hình hoặc chưa bật (quản trị cấu hình ở phần LLM-DFIR).")
    return cfg


async def _load_profile(db: AsyncSession, profile_id) -> SystemProfile:
    profile = (
        await db.execute(
            select(SystemProfile).where(SystemProfile.id == profile_id).options(
                sa.orm.selectinload(SystemProfile.devices),
                sa.orm.selectinload(SystemProfile.org),
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(404, "Không tìm thấy hồ sơ.")
    return profile


async def _device_type_catalog(db: AsyncSession) -> dict[str, str]:
    """Map code → label từ catalog loại thiết bị (bổ sung cho fallback chuẩn)."""
    rows = (await db.execute(select(DeviceType.code, DeviceType.label).where(DeviceType.is_active.is_(True)))).all()
    return {code: label for code, label in rows}


def _device_lines(profile: SystemProfile, catalog: dict[str, str]) -> str:
    devices = sorted(profile.devices, key=lambda d: d.sort_order)
    if not devices:
        return "(hồ sơ chưa khai thiết bị nào)"
    lines = []
    for d in devices:
        type_label = catalog.get(d.device_type, d.device_type)
        lines.append(
            f"- id: {d.id} | tên: {d.name} | loại: {type_label} ({d.device_type}) |"
            f" mã: {d.device_code or '—'} | IP: {d.ip or '—'} | model: {d.model or '—'} |"
            f" vị trí: {d.location or '—'} | mục đích: {d.purpose or '—'}"
        )
    return "\n".join(lines)


def _system_context(profile: SystemProfile, variant: str, catalog: dict[str, str]) -> str:
    """Ngữ cảnh hệ thống dùng chung cho generate/review."""
    devices = sorted(profile.devices, key=lambda d: d.sort_order)
    types = ", ".join(f"{code}=\"{label}\"" for code, label in catalog.items()) or "(trống)"
    return (
        f"Hồ sơ: {profile.name} (mã {profile.code}, cấp độ {profile.level}).\n"
        f"Loại sơ đồ: {'lô-gic' if variant == 'logic' else 'vật lý'}.\n"
        f"Số thiết bị đã khai: {len(devices)}.\n"
        f"Catalog loại thiết bị hợp lệ: {types}\n"
        f"Danh sách thiết bị (id phải giữ nguyên khi tham chiếu):\n{_device_lines(profile, catalog)}\n"
        f"Node mặc định luôn hiện: \"{INTERNET_NODE_ID}\" (Internet — đầu nguồn) và "
        f"\"{WORKSTATION_NODE_ID}\" (Máy trạm — chỉ khi danh sách chưa có thiết bị loại workstation).\n"
    )


def _extract_json(content: str) -> dict:
    """Bóc JSON từ câu trả lời LLM: bỏ markdown fence, lấy từ { đầu đến } cuối."""
    text = content.strip()
    if "```" in text:
        parts = text.split("```")
        # ưu tiên khối có đánh dấu json, nếu không lấy khối dài nhất chứa '{'
        candidates = [p for p in parts if "{" in p]
        if candidates:
            block = candidates[0]
            block = block.split("\n", 1)[-1] if block.lower().startswith("json") else block
            text = block
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Câu trả lời của AI không chứa JSON.")
    return json.loads(text[start : end + 1])


async def _chat_json(cfg, system_prompt: str, user_prompt: str) -> tuple[dict, str, int]:
    api_key = decrypt_aes_gcm(cfg.api_key_encrypted) if cfg.api_key_encrypted else None
    try:
        async with LlmClient(
            cfg.base_url, api_key, cfg.model, timeout=cfg.request_timeout,
            max_tokens=cfg.max_tokens, temperature=float(cfg.temperature),
        ) as llm:
            resp = await llm.chat([LlmMessage(role="system", content=system_prompt), LlmMessage(role="user", content=user_prompt)])
    except LlmError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Lỗi khi gọi AI: {exc}") from exc
    try:
        data = _extract_json(resp.content)
    except ValueError as exc:
        raise HTTPException(502, f"AI trả về không đúng định dạng: {exc}") from exc
    return data, cfg.model, resp.total_tokens


def _validate_layout_payload(data: dict) -> None:
    """Validate tối thiểu layout AI trả về trước khi trả cho client."""
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict) or not data["nodes"]:
        raise HTTPException(502, 'Layout AI trả về thiếu "nodes" (map nodeId → {x, y}).')
    for node_id, pos in data["nodes"].items():
        if not isinstance(pos, dict):
            raise HTTPException(502, f'Node "{node_id}" thiếu tọa độ.')
        try:
            float(pos.get("x")), float(pos.get("y"))
        except (TypeError, ValueError):
            raise HTTPException(502, f'Tọa độ node "{node_id}" không phải số.')
    edges = data.get("edges")
    if edges is not None:
        if not isinstance(edges, list):
            raise HTTPException(502, '"edges" phải là mảng.')
        node_ids = set(data["nodes"].keys())
        for e in edges:
            if not isinstance(e, dict) or e.get("source") not in node_ids or e.get("target") not in node_ids:
                raise HTTPException(502, "Có edge trỏ tới node không tồn tại trong layout AI trả về.")


@router.post("/{profile_id}/diagram/ai-generate", response_model=DiagramAiGenerateOut)
async def ai_generate_diagram(
    profile_id: uuid.UUID,
    body: DiagramAiGenerateIn,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    profile = await _load_profile(db, profile_id)
    cfg = await _load_llm_config(db)
    catalog = await _device_type_catalog(db)

    system_prompt = (
        "Bạn là chuyên gia thiết kế mạng và trực quan hóa sơ đồ kỹ thuật. "
        "Bạn LUÔN trả về đúng một JSON hợp lệ, không thêm chữ nào ngoài JSON."
    )
    user_prompt = (
        f"{_system_context(profile, body.variant, catalog)}\n"
        "Nhiệm vụ: vẽ sơ đồ mạng dưới dạng JSON layout theo đúng quy cách dưới đây.\n\n"
        f"## Quy cách JSON\n{DIAGRAM_SCHEMA_DOC}\n\n"
        "## Quy tắc\n"
        f'1. "nodes" phải chứa đủ MỌI id thiết bị ở trên (copy nguyên xi) và "{INTERNET_NODE_ID}".\n'
        f'2. "{WORKSTATION_NODE_ID}" chỉ thêm khi danh sách chưa có thiết bị loại workstation.\n'
        '3. Node mới (nhóm/DMZ/dịch vụ) khai trong "customNodes" với id dạng "custom-..." và có tọa độ trong "nodes".\n'
        "4. \"edges\" nối giữa các id TỒN TẠI, không self-loop; một node nối được nhiều cạnh; dùng \"label\" cho vlan/trunk.\n"
        "5. Bố cục: Internet bên trái, luồng sang phải theo tầng firewall → router → switch → server → workstation; "
        "storage/UPS/website xếp tầng phụ; cách nhau ~280px ngang, ~120px dọc; không chồng node.\n"
        '6. "notes": ghi chú IP/dải IP/vlan cho các node quan trọng.\n\n'
        "Chỉ trả về JSON hoàn chỉnh theo quy cách."
    )
    data, model, total = await _chat_json(cfg, system_prompt, user_prompt)
    _validate_layout_payload(data)
    return DiagramAiGenerateOut(layout=data, model=model, total_tokens=total)


@router.post("/{profile_id}/diagram/ai-review", response_model=DiagramAiReviewOut)
async def ai_review_diagram(
    profile_id: uuid.UUID,
    body: DiagramAiReviewIn,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin()),
):
    profile = await _load_profile(db, profile_id)
    cfg = await _load_llm_config(db)
    catalog = await _device_type_catalog(db)

    layout_json = json.dumps(body.layout, ensure_ascii=False, indent=2) if body.layout else "(sơ đồ chưa có — chỉ có node mặc định, chưa lưu bố cục)"

    system_prompt = (
        "Bạn là chuyên gia an ninh mạng và kiến trúc hệ thống thông tin Việt Nam. "
        "Bạn LUÔN trả về đúng một JSON hợp lệ, không thêm chữ nào ngoài JSON."
    )
    user_prompt = (
        f"{_system_context(profile, body.variant, catalog)}\n"
        "## Layout sơ đồ hiện tại\n"
        f"{layout_json}\n\n"
        "Nhiệm vụ: rà soát sơ đồ mạng ở HAI khía cạnh:\n"
        "A. An toàn mô hình: thiếu firewall biên, máy chủ đặt trước router/switch mà không qua firewall, "
        "thiếu phân vùng DMZ cho dịch vụ public, đường kết nối bất hợp lý, thiết bị quan trọng không có dự phòng khi cấp độ yêu cầu...\n"
        "B. Ghi chú: node quan trọng (firewall, router, switch, server) đã có ghi chú IP/dải IP chưa, "
        "đường nối quan trọng thiếu nhãn vlan, node nào còn thiếu thông tin khai báo (IP/model/vị trí) so với danh sách thiết bị.\n\n"
        "Trả về JSON duy nhất: "
        '{"findings": [ {"severity": "high"|"medium"|"low", "title": "tóm tắt ngắn", "detail": "giải thích + đề xuất sửa"} ]}\n'
        "Chỉ nêu ra vấn đề thực sự có căn cứ từ dữ liệu trên; nếu sơ đồ ổn thì findings là mảng rỗng. Tối đa 8 findings."
    )
    data, model, total = await _chat_json(cfg, system_prompt, user_prompt)
    findings_raw = data.get("findings")
    if not isinstance(findings_raw, list):
        raise HTTPException(502, 'AI trả về thiếu "findings".')
    findings: list[DiagramFindingOut] = []
    for f in findings_raw[:8]:
        if not isinstance(f, dict):
            continue
        severity = str(f.get("severity", "medium")).lower()
        if severity not in ("high", "medium", "low"):
            severity = "medium"
        title = str(f.get("title", "")).strip() or "Ghi chú từ AI"
        detail = str(f.get("detail", "")).strip()
        if detail:
            findings.append(DiagramFindingOut(severity=severity, title=title, detail=detail))
    return DiagramAiReviewOut(findings=findings, model=model, total_tokens=total)
