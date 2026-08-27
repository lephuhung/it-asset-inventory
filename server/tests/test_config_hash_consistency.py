"""Test: hash inventory phải nhất quán giữa server và agent.

C# (agent) dùng `DefaultIgnoreCondition.WhenWritingNull` → bỏ field null khi serialize.
Python server dùng `model_dump(exclude_none=True)` để khớp.

Test này đảm bảo nếu agent không gửi `config_hash`, server fallback `_config_hash()`
cho ra kết quả tương đương với việc tính hash từ payload đã strip null.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from app.api.routes.inventory import _config_hash
from app.schemas import InventoryRequest


def _python_canonical_hash(payload: dict) -> str:
    """Mô phỏng đúng C# `CanonicalJson.Hash(snapshot, excludeProperty="config_hash")`."""
    payload = {k: v for k, v in payload.items() if v is not None and k != "config_hash"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def test_server_config_hash_matches_python_canonical_hash_minimal():
    """Payload tối thiểu → server hash phải trùng với hash tính thủ công."""
    body = InventoryRequest.model_validate({
        "os_name": "Windows 11 Pro",
        "os_version": "10.0.22631",
        "os_build": "22631",
    })
    h_server = _config_hash(body)
    h_manual = _python_canonical_hash(body.model_dump(exclude={"config_hash"}, exclude_none=True))
    assert h_server == h_manual


async def test_server_config_hash_excludes_null_fields():
    """Server PHẢI loại bỏ null fields trước khi hash (giống C# WhenWritingNull).

    Trước đây dùng `body.model_dump(exclude={...})` không có exclude_none=True → null
    fields bị tính vào hash, gây mismatch với agent. Test này chống regression.
    """
    # Payload 1: chỉ có os_name
    body1 = InventoryRequest.model_validate({"os_name": "Windows 11"})
    h1 = _config_hash(body1)

    # Payload 2: thêm cpu=null — null không được tính vào hash
    body2 = InventoryRequest.model_validate({"os_name": "Windows 11", "cpu": None})
    h2 = _config_hash(body2)
    assert h1 == h2, (
        f"Hash phải ignore null: payload1={h1}, payload2={h2}. "
        "Có thể server đã quên exclude_none=True trong _config_hash."
    )


async def test_server_config_hash_changes_when_optional_field_changes():
    """Hash phải đổi khi trường optional thay đổi."""
    body_a = InventoryRequest.model_validate({"os_name": "Windows 11", "ram_gb": 16.0})
    body_b = InventoryRequest.model_validate({"os_name": "Windows 11", "ram_gb": 32.0})
    assert _config_hash(body_a) != _config_hash(body_b)


async def test_server_config_hash_excludes_config_hash_property():
    """Field `config_hash` PHẢI bị loại khỏi hash (vì nó chính là hash)."""
    body = InventoryRequest.model_validate({
        "os_name": "Windows 11",
        "config_hash": "fake_hash_will_be_ignored",
    })
    # Tính 2 lần với config_hash khác nhau → cùng kết quả
    h1 = _config_hash(body)
    body2 = InventoryRequest.model_validate({
        "os_name": "Windows 11",
        "config_hash": "totally_different_fake_hash",
    })
    h2 = _config_hash(body2)
    assert h1 == h2


async def test_server_config_hash_handles_unicode():
    """Hash phải xử lý đúng ký tự Unicode (tiếng Việt) — ensure_ascii=False."""
    body = InventoryRequest.model_validate({
        "os_name": "Windows 11 Pro",
        "logged_user": r"DESKTOP\Nguyễn Văn A",
    })
    # Không throw, là deterministic
    h1 = _config_hash(body)
    h2 = _config_hash(body)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


async def test_server_config_hash_matches_client_payload_shape():
    """Mô phỏng payload client gửi (đã bỏ field null sẵn) → server hash phải khớp
    với hash client tính."""
    # Client payload (đã strip null)
    client_payload = {
        "os_name": "Microsoft Windows 11 Pro",
        "os_version": "10.0.26200",
        "os_build": "26200",
        "os_arch": "X64",
        "ram_gb": 31.7,
        "cpu": {"model": "Intel i7", "cores": 14},
        "disks": [{"model": "NVMe", "size_bytes": 1024}],
        "config_hash": "client_self_hash",
    }
    body = InventoryRequest.model_validate(client_payload)
    server_hash = _config_hash(body)

    # Client tính canonical JSON của payload không có config_hash
    client_payload_no_hash = {k: v for k, v in client_payload.items() if k != "config_hash"}
    canonical = json.dumps(client_payload_no_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert server_hash == expected
