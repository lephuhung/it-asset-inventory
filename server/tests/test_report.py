"""Test báo cáo Excel — sinh file hợp lệ, mask SĐT, filter theo RBAC."""
from __future__ import annotations

import io
import uuid

import pytest
from openpyxl import load_workbook

from app.db.models import Machine, MachineSpec, UserRole


async def _seed_machine_with_user(
    session_factory,
    org_id,
    *,
    hostname="PC-EXPORT-01",
    status="online",
    phone="0987654321",
    email="export@test.gov.vn",
):
    """Tạo org owner + user + máy có spec (dùng cho test export)."""
    from app.core.security import encrypt_aes_gcm, hash_password
    from app.db.models import User

    async with session_factory() as s:
        admin = User(
            org_id=org_id,
            full_name="Quản trị export",
            email="exp_admin@test.gov.vn",
            role=UserRole.ADMIN_GLOBAL.value,
            password_hash=hash_password("x"),
        )
        s.add(admin)
        await s.flush()

        user = User(
            org_id=org_id,
            full_name="Nguyễn Văn Export",
            email=email,
            phone_encrypted=encrypt_aes_gcm(phone),
            role=UserRole.VIEWER.value,
        )
        s.add(user)
        await s.flush()

        m = Machine(
            org_id=org_id,
            machine_uuid="UUID-EXPORT-001",
            hostname=hostname,
            fingerprint={"smbios_uuid": "U-1"},
            status=status,
            assigned_user_id=user.id,
        )
        s.add(m)
        await s.flush()
        s.add(
            MachineSpec(
                machine_id=m.id,
                os_name="Windows 11",
                os_build="22631",
                cpu={"model": "Intel i7", "cores": 8},
                ram_gb=32.0,
                disks=[{"model": "NVMe", "capacity_gb": 512}],
            )
        )
        await s.commit()
        mid = m.id
    return mid


async def test_export_creates_valid_xlsx(client, seeded_env, session_factory):
    admin_token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]
    await _seed_machine_with_user(session_factory, uuid.UUID(org_id))

    r = await client.post(
        "/api/reports/export",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    assert "application/vnd.openxmlformats" in r.headers["content-type"]
    assert ".xlsx" in r.headers["content-disposition"]

    # Parse Excel và kiểm tra nội dung
    wb = load_workbook(io.BytesIO(r.content))
    assert "Máy tính" in wb.sheetnames
    assert "Thống kê" in wb.sheetnames

    ws = wb["Máy tính"]
    headers = [c.value for c in ws[1]]
    assert "Hostname" in headers and "Số điện thoại" in headers and "Trạng thái" in headers

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 1
    row = rows[0]
    assert "PC-EXPORT-01" in row  # hostname
    # Máy online + spec đầy đủ
    assert "Windows 11" in row
    assert 32.0 in row

    # SĐT phải được MASK mặc định theo format 0987•••321 (giữ đầu+cuối, giấu giữa)
    phone_idx = headers.index("Số điện thoại")
    phone_val = str(row[phone_idx])
    assert phone_val == "0987•••321", f"SĐT phải mask đúng format: {phone_val}"

    # Người dùng + email
    name_idx = headers.index("Người dùng")
    assert row[name_idx] == "Nguyễn Văn Export"


async def test_export_unauthorized(client):
    r = await client.post("/api/reports/export")
    assert r.status_code == 401


async def test_export_invalid_status(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/reports/export?status=bogus",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


async def test_export_with_phone_full_permission(client, seeded_env, session_factory):
    """Admin có quyền → include_phone_full=true hiện SĐT đầy đủ."""
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]
    await _seed_machine_with_user(session_factory, uuid.UUID(org_id), phone="0987654321")

    r = await client.post(
        "/api/reports/export?include_phone_full=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Máy tính"]
    headers = [c.value for c in ws[1]]
    phone_idx = headers.index("Số điện thoại")
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert rows and rows[0][phone_idx] == "0987654321"


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ── Timestamp RFC 3161 (DocTS) ────────────────────────────────

def _dummy_tsa_stamper():
    """TSA giả lập (self-signed) — test timestamp không cần mạng."""
    from datetime import UTC, datetime, timedelta

    from asn1crypto import keys
    from asn1crypto import x509 as ax509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    from pyhanko.sign.timestamps import DummyTimeStamper

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test TSA")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test TSA")]))
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(key, hashes.SHA256())
    )
    return DummyTimeStamper(
        tsa_cert=ax509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
        tsa_key=keys.PrivateKeyInfo.load(
            key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        ),
    )


@pytest.fixture
def dummy_tsa(monkeypatch):
    """Patch _default_stamper → DummyTimeStamper để export-pdf chạy offline."""
    import app.services.timestamp as ts_mod

    monkeypatch.setattr(ts_mod, "_default_stamper", lambda: _dummy_tsa_stamper())


async def test_export_pdf_with_timestamp(client, seeded_env, session_factory, dummy_tsa):
    """Export PDF → nhúng DocTS; /verify đọc lại gen_time + intact."""
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    await _seed_machine_with_user(session_factory, uuid.UUID(seeded_env["org_id"]))

    r = await client.post(
        "/api/reports/export-pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "x-report-sha256" in r.headers
    assert "x-report-timestamp" in r.headers
    assert r.content.startswith(b"%PDF")

    # Kiểm chứng qua endpoint /verify
    rv = await client.post(
        "/api/reports/verify",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("bao-cao.pdf", r.content, "application/pdf")},
    )
    assert rv.status_code == 200, rv.text
    data = rv.json()
    assert data["timestamped"] is True
    assert data["timestamps"][0]["intact"] is True
    assert data["timestamps"][0]["gen_time"]
    assert data["sha256"] == r.headers["x-report-sha256"]


async def test_export_pdf_without_timestamp(client, seeded_env, session_factory):
    """timestamp=false → PDF thường, không header timestamp."""
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    await _seed_machine_with_user(session_factory, uuid.UUID(seeded_env["org_id"]))

    r = await client.post(
        "/api/reports/export-pdf?timestamp=false",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "x-report-sha256" not in r.headers

    rv = await client.post(
        "/api/reports/verify",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("bao-cao.pdf", r.content, "application/pdf")},
    )
    assert rv.status_code == 200
    assert rv.json()["timestamped"] is False


async def test_verify_rejects_non_pdf(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    rv = await client.post(
        "/api/reports/verify",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("x.txt", b"not a pdf", "text/plain")},
    )
    assert rv.status_code == 400


async def test_export_pdf_tsa_failure_fails_closed(client, seeded_env, session_factory, monkeypatch):
    """TSA lỗi → 502, không xuất file thiếu dấu thời gian."""
    import app.services.timestamp as ts_mod

    def _boom(*a, **kw):
        raise ts_mod.TimestampError("TSA timeout")

    monkeypatch.setattr(ts_mod, "timestamp_pdf", _boom)
    import app.api.routes.reports as reports_mod

    monkeypatch.setattr(reports_mod, "timestamp_pdf", _boom)

    token = await _login(client, seeded_env["email"], seeded_env["password"])
    await _seed_machine_with_user(session_factory, uuid.UUID(seeded_env["org_id"]))
    r = await client.post(
        "/api/reports/export-pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 502