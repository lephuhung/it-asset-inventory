"""Tests for /download/* endpoints — serve MSI + SHA256 + offline install script."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def msi_dir(tmp_path, monkeypatch):
    """Tạo thư mục MSI giả + 2 file, monkeypatch `settings.agent_msi_dir` trỏ vào đó."""
    d = tmp_path / "agent_dist"
    d.mkdir()
    (d / "OrgInventoryAgent.msi").write_bytes(b"MSI-FAKE-CONTENT")
    (d / "OrgInventoryAgent.msi.sha256").write_text(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef  OrgInventoryAgent.msi\n"
    )
    # Module-level singleton đã được import và bind ở app start → monkeypatch trực tiếp
    from app.core import config as config_module
    monkeypatch.setattr(config_module.settings, "agent_msi_dir", str(d))
    yield d


async def test_download_agent_msi_ok(client, msi_dir):
    r = await client.get("/download/agent.msi")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-msi")
    assert r.content == b"MSI-FAKE-CONTENT"
    # Content-Disposition để browser tải về đúng tên file
    assert "OrgInventoryAgent.msi" in r.headers.get("content-disposition", "")


async def test_download_agent_msi_sha256(client, msi_dir):
    r = await client.get("/download/agent.msi.sha256")
    assert r.status_code == 200
    body = r.text.strip()
    assert body.startswith("0123456789abcdef")
    assert "OrgInventoryAgent.msi" in body


async def test_download_install_offline_script_ok(client):
    """install-offline.ps1 đọc từ template, không phụ thuộc AGENT_MSI_DIR."""
    r = await client.get("/download/install-offline.ps1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "install-offline.ps1" in r.text
    # Phải có hướng dẫn cho máy cách ly
    assert "--enroll-offline" in r.text or "OFFLINE" in r.text.upper()


async def test_download_msi_not_found_when_file_missing(client, tmp_path, monkeypatch):
    """Nếu AGENT_MSI_DIR không có file MSI → 404 với hướng dẫn."""
    empty = tmp_path / "empty"
    empty.mkdir()
    from app.core import config as config_module
    monkeypatch.setattr(config_module.settings, "agent_msi_dir", str(empty))

    r = await client.get("/download/agent.msi")
    assert r.status_code == 404
    assert "Build MSI" in r.json()["detail"] or "Không tìm thấy" in r.json()["detail"]


async def test_download_blocks_path_traversal(client, msi_dir, monkeypatch):
    """Filename có `..` không được thoát ra khỏi AGENT_MSI_DIR."""
    # FastAPI routing không cho phép `..` trong URL (404 trước khi vào handler).
    # Kiểm tra thêm ở handler: nếu filename có dấu phân cách path → từ chối.
    from app.api.routes.downloads import _safe_resolve
    with pytest.raises(Exception):
        _safe_resolve("../etc/passwd")
    with pytest.raises(Exception):
        _safe_resolve("subdir/../../../etc/passwd")


async def test_downloads_require_no_auth(client, msi_dir):
    """Endpoint /download/* public — không cần Authorization header."""
    r1 = await client.get("/download/agent.msi")
    r2 = await client.get("/download/agent.msi.sha256")
    r3 = await client.get("/download/install-offline.ps1")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200
