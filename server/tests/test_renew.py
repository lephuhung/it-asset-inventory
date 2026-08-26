"""Test route /api/renew — gia hạn client cert (mục 7.1 tài liệu gốc)."""
from __future__ import annotations

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.api.routes.renew import RenewResponse
from app.db.models import Machine


def _make_csr(machine_id, cn_override: str | None = None) -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    cn = cn_override or f"machine-{machine_id}"
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(str(machine_id))]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")


async def test_issued_cert_cn_is_machine_id(client, seeded_env):
    """Cert cấp ra PHẢI có CN = machine-<machine_id> dù CSR gửi CN tạm khác —
    đảm bảo heartbeat mTLS (X-SSL-Client-CN từ nginx) khớp lookup machine."""
    import uuid

    # Login + tạo token
    login = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    assert login.status_code == 200, login.text
    tok_resp = await client.post(
        "/api/tokens",
        json={"org_id": seeded_env["org_id"], "full_name": "Test CN"},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    token = tok_resp.json()["token"]

    # CSR với CN tạm "temp-machine-xyz" (agent chưa biết machine_id lúc enroll)
    csr = _make_csr(uuid.uuid4(), cn_override="temp-machine-xyz")
    resp = await client.post(
        "/api/enroll",
        json={
            "token": token,
            "fingerprint": {
                "smbios_uuid": "4C4C4544-0000-1000-8000-BBBBBBBBBBBB",
                "machine_guid": "cn-test-guid",
                "mainboard_serial": "MB-CN-TEST",
            },
            "csr_pem": csr,
            "hostname": "PC-CN-TEST",
        },
    )
    assert resp.status_code == 200, resp.text
    machine_id = resp.json()["machine_id"]
    cert_pem = resp.json()["client_cert_pem"]

    cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == f"machine-{machine_id}", f"CN sai: {cn}"


async def _enroll(client, seed_env) -> tuple[str, str]:
    """Enroll 1 máy → trả (machine_id, client_cert_pem)."""
    # Login admin để lấy token portal
    login = await client.post(
        "/api/auth/login",
        json={"email": seed_env["email"], "password": seed_env["password"]},
    )
    assert login.status_code == 200, login.text
    admin_token = login.json()["access_token"]

    token_resp = await client.post(
        "/api/tokens",
        json={
            "org_id": seed_env["org_id"],
            "full_name": "Nguyễn Văn A",
            "department": "Kế toán",
            "email": "a@example.gov.vn",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert token_resp.status_code == 200, token_resp.text
    token = token_resp.json()["token"]

    machine_csr_cn = "11111111-2222-3333-4444-555555555555"
    csr = _make_csr(machine_csr_cn)
    resp = await client.post(
        "/api/enroll",
        json={
            "token": token,
            "fingerprint": {
                "smbios_uuid": "4C4C4544-0000-1000-8000-AAAAAAAAAAAA",
                "machine_guid": "abc123",
                "mainboard_serial": "MB-SERIAL-1",
            },
            "csr_pem": csr,
            "hostname": "PC-RENEW-01",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["machine_id"], resp.json()["client_cert_pem"]


async def test_renew_requires_mtls(client, seeded_env, monkeypatch):
    """Không có header mTLS (verify != SUCCESS) → 401 (khi bật require_agent_mtls_header)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "require_agent_mtls_header", True)
    resp = await client.post(
        "/api/renew",
        json={"csr_pem": _make_csr("11111111-2222-3333-4444-555555555555")},
        headers={
            "X-SSL-Client-Verify": "FAILED",
            "X-SSL-Client-CN": "machine-11111111-2222-3333-4444-555555555555",
            "X-SSL-Client-Serial": "0xDEAD",
        },
    )
    assert resp.status_code == 401


async def test_renew_issues_new_cert(client, seeded_env, session_factory):
    """Renew hợp lệ → cert mới khác cert cũ, máy vẫn tồn tại."""
    machine_id, old_cert = await _enroll(client, seeded_env)

    new_csr = _make_csr(machine_id)
    resp = await client.post(
        "/api/renew",
        json={"csr_pem": new_csr},
        headers={
            "X-SSL-Client-Verify": "SUCCESS",
            "X-SSL-Client-CN": f"machine-{machine_id}",
            "X-SSL-Client-Serial": "0xAB12",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["client_cert_pem"] != old_cert
    assert "BEGIN CERTIFICATE" in body["client_cert_pem"]
    assert body["renew_after"]

    # Audit ghi nhận cert.renew
    async with session_factory() as s:
        from app.db.models import AuditLog

        rows = (
            await s.execute(select(AuditLog).where(AuditLog.action == "cert.renew"))
        ).scalars().all()
        assert len(rows) >= 1

    # Máy vẫn tồn tại
    async with session_factory() as s:
        m = (
            await s.execute(select(Machine).where(Machine.id == machine_id))
        ).scalar_one_or_none()
        assert m is not None
