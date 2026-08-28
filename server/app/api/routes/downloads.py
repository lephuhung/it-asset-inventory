"""Route download — serve MSI installer + SHA256 cho agent.

Hỗ trợ 2 phương pháp cài đặt agent (xem `docs/OFFLINE_AGENT_SPEC.md` mục 2):

  1. Cài bằng lệnh (online):  lệnh do server sinh = tải MSI từ `GET /download/agent.msi`
     → verify SHA256 (so với `/download/agent.msi.sha256`) → msiexec /qn.
     (KHÔNG dùng `irm ... | iex` — Defender gắn cờ pattern download-and-execute.)

  2. Cài bằng tải file (offline / máy cách ly):
     → Admin tải MSI + SHA256 từ 2 endpoint này, copy qua USB, chạy
       `install-offline.ps1` wrapper đi kèm (KHÔNG cần mạng ra server lúc cài).

File MSI + SHA256 đặt trong thư mục `settings.agent_msi_dir`. Cấu trúc:
  <agent_msi_dir>/OrgInventoryAgent.msi
  <agent_msi_dir>/OrgInventoryAgent.msi.sha256

Build (chỉ trên Windows, cần WiX):
  cd agent && dotnet publish -c Release -r win-x64
  powershell installer/build-msi.ps1 -CertificateThumbprint \"<EV code signing thumbprint>\"
  → copy OrgInventoryAgent.msi + .sha256 vào server.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.services.agent_settings import effective_agent_config

router = APIRouter(prefix="/download", tags=["download"])

MSI_FILENAME = "OrgInventoryAgent.msi"
SHA256_FILENAME = "OrgInventoryAgent.msi.sha256"


def _safe_resolve(filename: str) -> Path:
    """Trả về absolute path tới file, đảm bảo nằm trong `agent_msi_dir` (chống path traversal)."""
    base = Path(settings.agent_msi_dir).resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Đường dẫn không hợp lệ")
    return target


def _ensure_exists(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=(
                f"Không tìm thấy {path.name}. "
                f"Build MSI trên Windows (installer/build-msi.ps1) rồi copy vào "
                f"{settings.agent_msi_dir}/."
            ),
        )


@router.get("/agent.msi", response_class=FileResponse)
async def download_agent_msi():
    """Trả về file MSI — verify SHA256 trước khi cài (xem install.ps1)."""
    path = _safe_resolve(MSI_FILENAME)
    _ensure_exists(path)
    return FileResponse(
        path,
        media_type="application/x-msi",
        filename=MSI_FILENAME,
    )


@router.get("/agent.msi.sha256", response_class=PlainTextResponse)
async def download_agent_msi_sha256():
    """Trả về chuỗi SHA-256 hex của file MSI (để PowerShell verify trước khi cài)."""
    path = _safe_resolve(SHA256_FILENAME)
    _ensure_exists(path)
    return PlainTextResponse(content=path.read_text(encoding="utf-8").strip())


@router.get("/install-offline.ps1", response_class=PlainTextResponse)
async def download_install_offline_script():
    """Trả về `install-offline.ps1` — wrapper cài cho máy cách ly (KHÔNG cần mạng).

    Script này chạy local trên USB, không gọi lại server — phù hợp máy air-gapped.
    So với `install.ps1` (online): script này bỏ qua bước tải MSI (đã có sẵn trên USB)
    và bỏ qua bước verify qua server.
    """
    template_path = Path(__file__).resolve().parents[2] / "templates" / "install-offline.ps1"
    if not template_path.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Thiếu template install-offline.ps1")
    return PlainTextResponse(content=template_path.read_text(encoding="utf-8"))


@router.get("/install-offline.cmd", response_class=PlainTextResponse)
async def download_install_offline_launcher():
    """Trả về `install-offline.cmd` — launcher nháy đúp chuột 1-click cho máy cách ly."""
    template_path = Path(__file__).resolve().parents[2] / "templates" / "install-offline.cmd"
    if not template_path.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Thiếu template install-offline.cmd")
    return PlainTextResponse(content=template_path.read_text(encoding="utf-8"))


@router.get("/server_public_key.pem", response_class=PlainTextResponse)
async def download_server_public_key():
    """Trả về khóa công khai của Server để máy cách ly mã hóa gói ZIP trước khi lưu vào USB."""
    from app.services.server_crypto import get_server_public_key_pem
    return PlainTextResponse(content=get_server_public_key_pem(), media_type="text/plain")


@router.get("/offline-package.zip")
async def download_offline_package(db: AsyncSession = Depends(get_db)):
    """Tạo và tải về gói bundle ZIP trọn gói cho máy cách ly (Admin copy vào USB).

    Bao gồm:
    - install-offline.cmd (launcher nháy đúp chuột)
    - install-offline.ps1 (script thu thập & đóng gói)
    - server_public_key.pem (khóa công khai của Server)
    - OrgInventoryAgent.msi & .sha256 (nếu có sẵn trên server)
    - offline_config.json (cấu hình mẫu)
    """
    import io
    import json
    import zipfile
    from fastapi.responses import Response
    from app.services.server_crypto import get_server_public_key_pem

    agent_cfg = await effective_agent_config(db)
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    zip_buf = io.BytesIO()

    # ⚠️ ZIP này KHÔNG đặt password (yêu cầu nghiệp vụ — operator copy qua USB không
    # cần nhập password; tính bí mật dựa vào mã hóa RSA-OAEP của file ZIP do agent
    # sinh ra SAU, không phải ZIP tải về này). Tuyệt đối KHÔNG gọi zf.setpassword().
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        assert not hasattr(zf, "_password") or zf._password is None, "ZIP tải về phải KHÔNG có password"

        cmd_path = template_dir / "install-offline.cmd"
        if cmd_path.exists():
            zf.writestr("install-offline.cmd", cmd_path.read_text(encoding="utf-8"))

        ps1_path = template_dir / "install-offline.ps1"
        if ps1_path.exists():
            zf.writestr("install-offline.ps1", ps1_path.read_text(encoding="utf-8"))

        zf.writestr("server_public_key.pem", get_server_public_key_pem())

        sample_cfg = {
            "token": "",
            "endpoints": agent_cfg["agent_server_url"],
            "note": "Cấu hình offline tạo bởi IT Asset Inventory Portal",
        }
        zf.writestr("offline_config.json", json.dumps(sample_cfg, indent=2, ensure_ascii=False))

        # Đính kèm MSI và SHA256 nếu có sẵn trong thư mục agent_msi_dir
        base = Path(settings.agent_msi_dir).resolve()
        msi_p = base / MSI_FILENAME
        if msi_p.exists():
            zf.write(msi_p, arcname=MSI_FILENAME)
        sha_p = base / SHA256_FILENAME
        if sha_p.exists():
            zf.write(sha_p, arcname=SHA256_FILENAME)

    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="offline-package.zip"'},
    )
