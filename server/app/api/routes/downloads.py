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

import hashlib

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
AGENT_LINUX_FILENAME = "OrgInventoryAgent-linux-x64"
VELOCIRAPTOR_ZIP_FILENAME = "velociraptor-agent-windows.zip"
VELOCIRAPTOR_MSI_FILENAME = "velociraptor-windows-amd64.msi"
VELOCIRAPTOR_CONFIG_FILENAME = "velociraptor-client.config.yaml"
VELOCIRAPTOR_INSTALL_BAT = "install-velociraptor.bat"
VELOCIRAPTOR_CONFIG_ONLY_ZIP = "velociraptor-config-only.zip"
VELOCIRAPTOR_DEB_FILENAME = "velociraptor_client_amd64.deb"
VELOCIRAPTOR_RPM_FILENAME = "velociraptor_client_amd64.rpm"
INSTALL_BOTH_PS1 = "install-both.ps1"
INSTALL_BOTH_SH = "install-both.sh"


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


@router.get("/agent-linux-x64", response_class=FileResponse)
async def download_agent_linux():
    """Binary OrgInventoryAgent cho Linux amd64 (self-contained single-file).

    Build (trên máy có .NET 8 SDK):
      cd agent && dotnet publish src/OrgInventoryAgent -c Release -r linux-x64 \
          --self-contained -p:PublishSingleFile=true -p:DebugType=none -o publish/linux-x64
    → copy `OrgInventoryAgent` vào `agent_msi_dir` với tên `OrgInventoryAgent-linux-x64`.
    Script `install-both.sh` (Linux) tải file này khi có `--portal-url`.
    """
    path = _safe_resolve(AGENT_LINUX_FILENAME)
    _ensure_exists(path)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=AGENT_LINUX_FILENAME,
    )


@router.get("/install-offline.ps1", response_class=PlainTextResponse)
async def download_install_offline_script():
    """Trả về `install-offline.ps1` — wrapper cài cho máy cách ly (KHÔNG cần mạng).

    Script này chạy local trên USB, không gọi lại server — phù hợp máy air-gapped.
    So với `install.ps1` (online): script này bỏ qua bước tải MSI (đã có sẵn trên USB)
    và bỏ qua bước verify qua server. BOM UTF-8 có sẵn trong file template.
    """
    template_path = Path(__file__).resolve().parents[2] / "templates" / "install-offline.ps1"
    if not template_path.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Thiếu template install-offline.ps1")
    return PlainTextResponse(
        content=template_path.read_bytes().decode("utf-8"),
        media_type="text/plain; charset=utf-8",
    )


@router.get("/install-offline.cmd", response_class=PlainTextResponse)
async def download_install_offline_launcher():
    """Trả về `install-offline.cmd` — launcher nháy đúp chuột 1-click cho máy cách ly."""
    template_path = Path(__file__).resolve().parents[2] / "templates" / "install-offline.cmd"
    if not template_path.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Thiếu template install-offline.cmd")
    return PlainTextResponse(content=template_path.read_text(encoding="utf-8"))


# ── Velociraptor DFIR Agent (DFIR — Digital Forensics & Incident Response) ────
# Serve các file cài Velociraptor Client + config cho admin test nhanh.
# File được build sẵn bởi Velociraptor Server container (ghcr.io/velocidex/velociraptor-server),
# sau đó copy vào agent_dist/. Admin chỉ cần click link download từ portal → copy sang
# Windows → cài + chạy.


@router.get("/velociraptor-agent.zip", response_class=FileResponse)
async def download_velociraptor_agent_zip():
    """Bundle Velociraptor Client MSI + config YAML (tiện copy 1 lần sang Windows).

    File `velociraptor-agent-windows.zip` chứa:
      - velociraptor-windows-amd64.msi  (~27 MB — Windows installer)
      - client.config.yaml              (~3 KB — config đã chỉnh `wss://<host>:8888/`)

    Đặt trong `settings.agent_msi_dir` (mặc định `./agent_dist`).
    SHA256 đi kèm trong response header `X-Content-SHA256` để admin verify.
    """

    path = _safe_resolve(VELOCIRAPTOR_ZIP_FILENAME)
    _ensure_exists(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return FileResponse(
        path,
        media_type="application/zip",
        filename=VELOCIRAPTOR_ZIP_FILENAME,
        headers={"X-Content-SHA256": digest},
    )


@router.get("/velociraptor-windows-amd64.msi", response_class=FileResponse)
async def download_velociraptor_msi():
    """Velociraptor Client MSI (Windows x64) — chỉ MSI, không kèm config."""
    path = _safe_resolve(VELOCIRAPTOR_MSI_FILENAME)
    _ensure_exists(path)
    return FileResponse(
        path,
        media_type="application/x-msi",
        filename=VELOCIRAPTOR_MSI_FILENAME,
    )


@router.get("/velociraptor-client.config.yaml", response_class=PlainTextResponse)
async def download_velociraptor_client_config():
    """Velociraptor Client config YAML — copy sang Windows trước khi cài MSI.

    URL `server_urls` đã được ch�nh thành `wss://<host>:8888/` (host port Velociraptor
    Frontend — KHÔNG phải port 8000 vì host 8000 đã bị Inventory backend chiếm).
    Nếu copy sang máy Windows ở mạng khác, phải sửa `server_urls` trong file này
    sang FQDN/IP mà máy Windows resolve được.
    """
    path = _safe_resolve(VELOCIRAPTOR_CONFIG_FILENAME)
    _ensure_exists(path)
    return PlainTextResponse(
        content=path.read_text(encoding="utf-8"),
        media_type="application/x-yaml",
    )


@router.get("/velociraptor-config-only.zip", response_class=FileResponse)
async def download_velociraptor_config_only_zip():
    """ZIP nhỏ (~5KB) chỉ chứa client.config.yaml — dùng cho Smart Update.

    Khi máy đã cài Velociraptor, script install-both chỉ cần update URL enrollment.
    Bundle đầy đủ (~50MB) không cần thiết — chỉ cần file config này.

    File build bằng ``server/agent_dist/build-config-zip.sh`` — chạy lại khi
    Velociraptor URL/CA cert thay đổi.
    """
    path = _safe_resolve(VELOCIRAPTOR_CONFIG_ONLY_ZIP)
    _ensure_exists(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return FileResponse(
        path,
        media_type="application/zip",
        filename=VELOCIRAPTOR_CONFIG_ONLY_ZIP,
        headers={"X-Content-SHA256": digest, "X-Bundle-Type": "config-only"},
    )


@router.get("/install-velociraptor.bat", response_class=PlainTextResponse)
async def download_velociraptor_install_bat():
    """`install-velociraptor.bat` — script tự động copy config + restart Velociraptor service.

    Đặt file này cạnh `client.config.yaml` trong cùng thư mục giải nén ZIP.
    Chuột phải → "Run as administrator" → script sẽ:
      1. Dừng Velociraptor service
      2. Copy config của ta đè lên config mặc định của MSI
      3. Khởi động lại service
      4. Hiển thị log để verify enroll thành công
    """
    path = _safe_resolve(VELOCIRAPTOR_INSTALL_BAT)
    _ensure_exists(path)
    return PlainTextResponse(
        content=path.read_text(encoding="utf-8"),
        media_type="text/plain",
    )


@router.get("/velociraptor-linux-amd64.deb", response_class=FileResponse)
async def download_velociraptor_linux_deb():
    """Velociraptor Client .deb (Linux amd64) — gói đã nhúng client.config.yaml.

    Tạo trên Velociraptor Server bằng artifact `Server.Utils.CreateLinuxPackages`
    (hoặc lệnh `velociraptor debian client --config client.config.yaml`), copy vào
    `agent_msi_dir` với tên `velociraptor_client_amd64.deb`. Cài: `sudo dpkg -i ...`.
    """
    path = _safe_resolve(VELOCIRAPTOR_DEB_FILENAME)
    _ensure_exists(path)
    return FileResponse(
        path,
        media_type="application/vnd.debian.binary-package",
        filename=VELOCIRAPTOR_DEB_FILENAME,
    )


@router.get("/velociraptor-linux-amd64.rpm", response_class=FileResponse)
async def download_velociraptor_linux_rpm():
    """Velociraptor Client .rpm (Linux amd64) — gói đã nhúng client.config.yaml.

    Tạo trên Velociraptor Server bằng artifact `Server.Utils.CreateLinuxPackages`
    (hoặc lệnh `velociraptor rpm client --config client.config.yaml`), copy vào
    `agent_msi_dir` với tên `velociraptor_client_amd64.rpm`. Cài: `sudo rpm -i ...`.
    """
    path = _safe_resolve(VELOCIRAPTOR_RPM_FILENAME)
    _ensure_exists(path)
    return FileResponse(
        path,
        media_type="application/x-rpm",
        filename=VELOCIRAPTOR_RPM_FILENAME,
    )


# ── Script cài đặt kết hợp (install-both) — cài OrgInventory + Velociraptor bằng 1 lệnh ──
# File gốc đặt ở app/templates/ (cùng chỗ install-offline.ps1); bản dev ở agent/.
#   Windows (1 lệnh):  $env:ORGINVENTORY_TOKEN='t_xxx'; $env:ORGINVENTORY_PORTAL_URL='<portal>';
#                      irm <portal>/download/install-both.ps1 | iex
#   Linux (1 lệnh):    curl -fsSL <portal>/download/install-both.sh | sudo bash -s -- \
#                      --token t_xxx --endpoint https://agent.gov.vn --portal-url <portal>


@router.get("/install-both.ps1", response_class=PlainTextResponse)
async def download_install_both_ps1():
    """`install-both.ps1` — cài cùng lúc OrgInventory Agent + Velociraptor Client trên Windows.

    File template có sẵn BOM UTF-8 ở đầu để PowerShell trên Windows nhận diện đúng
    encoding. Nếu thiếu BOM, các ký tự Unicode (─, ≤, ≥, ...) sẽ bị corrupt →
    parse error như "Try statement is missing its Catch or Finally block".
    """
    template_path = Path(__file__).resolve().parents[2] / "templates" / INSTALL_BOTH_PS1
    if not template_path.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Thiếu template install-both.ps1")
    # BOM đã có sẵn trong file template (thêm bằng `printf '\xEF\xBB\xBF'`)
    return PlainTextResponse(
        content=template_path.read_bytes().decode("utf-8"),
        media_type="text/plain; charset=utf-8",
    )


@router.get("/install-both.sh", response_class=PlainTextResponse)
async def download_install_both_sh():
    """`install-both.sh` — cài cùng lúc OrgInventory Agent + Velociraptor Client trên Linux."""
    template_path = Path(__file__).resolve().parents[2] / "templates" / INSTALL_BOTH_SH
    if not template_path.exists():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Thiếu template install-both.sh")
    return PlainTextResponse(
        content=template_path.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )


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
