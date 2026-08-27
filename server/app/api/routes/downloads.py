"""Route download — serve MSI installer + SHA256 cho agent.

Hỗ trợ 2 phương pháp cài đặt agent (xem `docs/OFFLINE_AGENT_SPEC.md` mục 2):

  1. Cài bằng lệnh (online):  `irm http://server/i/<token> | iex`
     → install.ps1 tải MSI từ `GET /download/agent.msi` → verify SHA256 → msiexec.

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

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse

from app.core.config import settings

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
