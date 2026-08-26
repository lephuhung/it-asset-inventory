"""Test cấu hình heartbeat + /api/agent/config.

- Heartbeat response phải trả heartbeat_interval_seconds/jitter (agent đồng bộ).
- Enroll response trả agent_server_url + config.
- GET /api/agent/config yêu cầu mTLS header, trả đúng cấu hình.
- online_ttl tự tính = 2 × (interval + jitter) khi không override.
"""
from __future__ import annotations

from app.core.config import settings


async def _enroll_machine(client, seeded_env, fp=None):
    """Tiện ích: login → token → enroll → trả (machine_id, enroll_json)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    r = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = r.json()["access_token"]
    r = await client.post(
        "/api/tokens",
        headers={"Authorization": f"Bearer {tok}"},
        json={"org_id": seeded_env["org_id"], "full_name": "Config Test", "ttl_hours": 72},
    )
    etoken = r.json()["token"]

    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cfg")]))
        .sign(key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

    fp = fp or {"smbios_uuid": "UUID-CFG", "machine_guid": "G", "mainboard_serial": "S"}
    r = await client.post(
        "/api/enroll",
        json={"token": etoken, "csr_pem": csr_pem, "fingerprint": fp, "hostname": "PC-CFG"},
    )
    assert r.status_code == 200, r.text
    return r.json()["machine_id"], r.json()


async def test_enroll_returns_agent_config(client, seeded_env):
    _mid, ed = await _enroll_machine(client, seeded_env)
    assert ed["agent_server_url"] == settings.agent_server_url
    assert ed["heartbeat_interval_seconds"] == settings.heartbeat_interval_seconds
    assert ed["heartbeat_jitter_seconds"] == settings.heartbeat_jitter_seconds
    assert ed["inventory_interval_hours"] == settings.inventory_interval_hours


async def test_heartbeat_returns_interval(client, seeded_env):
    mid, _ = await _enroll_machine(client, seeded_env)
    r = await client.post(
        "/api/heartbeat",
        json={"logged_user": "u", "uptime_sec": 5},
        headers={"X-SSL-Client-CN": mid},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["heartbeat_interval_seconds"] == settings.heartbeat_interval_seconds
    assert data["heartbeat_jitter_seconds"] == settings.heartbeat_jitter_seconds


async def test_agent_config_endpoint_requires_mtls(client, seeded_env):
    # Không có X-SSL-Client-CN → 401
    r = await client.get("/api/agent/config")
    assert r.status_code == 401


async def test_agent_config_endpoint_returns_config(client, seeded_env):
    mid, _ = await _enroll_machine(client, seeded_env)
    r = await client.get("/api/agent/config", headers={"X-SSL-Client-CN": mid})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["server_url"] == settings.agent_server_url
    assert data["heartbeat_interval_seconds"] == settings.heartbeat_interval_seconds
    assert data["heartbeat_jitter_seconds"] == settings.heartbeat_jitter_seconds
    assert data["online_ttl_seconds"] == settings.effective_online_ttl_seconds
    assert data["inventory_interval_hours"] == settings.inventory_interval_hours
    assert data["renew_before_percent"] == 70
    assert data["server_time"]


async def test_online_ttl_auto_calculated(client, seeded_env):
    """online_ttl = 2 × (interval + jitter) khi KHÔNG override; nếu override thì tôn trọng
    giá trị operator đặt (≥ ngưỡng tối thiểu hợp lý)."""
    auto = 2 * (settings.heartbeat_interval_seconds + settings.heartbeat_jitter_seconds)
    if settings.online_ttl_seconds is None:
        assert settings.effective_online_ttl_seconds == auto
    else:
        # operator đặt override (VD: .env ONLINE_TTL_SECONDS=180) — tôn trọng
        assert settings.effective_online_ttl_seconds == settings.online_ttl_seconds
        # nhưng phải ≥ 2 × chu kỳ tối đa, nếu không máy bị "lost" oan
        assert settings.online_ttl_seconds >= auto - settings.heartbeat_jitter_seconds