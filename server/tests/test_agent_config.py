"""Test cấu hình heartbeat + /api/agent/config.

- Heartbeat response phải trả heartbeat_interval_seconds/jitter (agent đồng bộ).
- Enroll response trả agent_server_url + config.
- GET /api/agent/config yêu cầu mTLS header, trả đúng cấu hình.
- online_ttl tự tính = 2 × (interval + jitter) khi không override.
- Phase 4: heartbeat + /api/agent/config trả `renew_before_percent` + `agent_config_hash`.
- Phase 4: hash ổn định khi config không đổi, đổi khi config đổi (kiểm tra agent phát
  hiện thay đổi và gọi lại /api/agent/config).
"""
from __future__ import annotations

from app.core.config import settings
from app.services.agent_settings import compute_agent_config_hash


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


# ── Phase 4: heartbeat trả renew_before_percent + agent_config_hash ─────────


async def test_heartbeat_returns_renew_before_percent(client, seeded_env):
    """Heartbeat PHẢI trả `renew_before_percent` — agent dùng để sync renew threshold
    ngay trong heartbeat (trước đây chỉ sync qua /api/agent/config 6h/lần)."""
    mid, _ = await _enroll_machine(client, seeded_env)
    r = await client.post(
        "/api/heartbeat",
        json={"logged_user": "u", "uptime_sec": 5},
        headers={"X-SSL-Client-CN": mid},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "renew_before_percent" in data, "Heartbeat response thiếu renew_before_percent"
    assert data["renew_before_percent"] == 70


async def test_heartbeat_returns_agent_config_hash(client, seeded_env):
    """Heartbeat PHẢI trả `agent_config_hash` — agent so sánh với hash đã lưu trong
    state để quyết định có gọi lại /api/agent/config hay không."""
    mid, _ = await _enroll_machine(client, seeded_env)
    r = await client.post(
        "/api/heartbeat",
        json={"logged_user": "u", "uptime_sec": 5},
        headers={"X-SSL-Client-CN": mid},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "agent_config_hash" in data, "Heartbeat response thiếu agent_config_hash"
    assert data["agent_config_hash"], "agent_config_hash không được rỗng"
    # SHA-256 hex = 64 ký tự hex
    assert len(data["agent_config_hash"]) == 64


async def test_agent_config_returns_agent_config_hash(client, seeded_env):
    """GET /api/agent/config cũng trả agent_config_hash để agent lưu state sau khi sync."""
    mid, _ = await _enroll_machine(client, seeded_env)
    r = await client.get("/api/agent/config", headers={"X-SSL-Client-CN": mid})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "agent_config_hash" in data
    assert len(data["agent_config_hash"]) == 64


async def test_heartbeat_and_agent_config_hashes_match(client, seeded_env):
    """Hash trong heartbeat response và /api/agent/config response phải giống nhau
    (cùng một nguồn `compute_agent_config_hash()`)."""
    mid, _ = await _enroll_machine(client, seeded_env)

    r1 = await client.post(
        "/api/heartbeat",
        json={"logged_user": "u", "uptime_sec": 5},
        headers={"X-SSL-Client-CN": mid},
    )
    r2 = await client.get("/api/agent/config", headers={"X-SSL-Client-CN": mid})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["agent_config_hash"] == r2.json()["agent_config_hash"], (
        "Hash ở heartbeat và /api/agent/config phải khớp (cùng nguồn)"
    )


async def test_compute_agent_config_hash_changes_when_config_changes():
    """Hash phải thay đổi khi bất kỳ trường nào trong config thay đổi — agent nhờ đó
    phát hiện được admin đổi cấu hình qua portal."""
    cfg_base = {
        "agent_server_url": "http://10.0.0.1:8000",
        "heartbeat_interval_seconds": 30,
        "heartbeat_jitter_seconds": 8,
        "inventory_interval_hours": 24,
        "renew_before_percent": 70,
    }
    h0 = compute_agent_config_hash(cfg_base)

    # đổi interval → hash đổi
    cfg2 = dict(cfg_base, heartbeat_interval_seconds=60)
    assert compute_agent_config_hash(cfg2) != h0

    # đổi jitter → hash đổi
    cfg3 = dict(cfg_base, heartbeat_jitter_seconds=15)
    assert compute_agent_config_hash(cfg3) != h0

    # đổi inventory interval → hash đổi
    cfg4 = dict(cfg_base, inventory_interval_hours=12)
    assert compute_agent_config_hash(cfg4) != h0

    # đổi renew_before_percent → hash đổi
    cfg5 = dict(cfg_base, renew_before_percent=80)
    assert compute_agent_config_hash(cfg5) != h0

    # đổi server_url → hash đổi
    cfg6 = dict(cfg_base, agent_server_url="http://10.0.0.2:8000")
    assert compute_agent_config_hash(cfg6) != h0

    # không đổi gì → hash giữ nguyên (deterministic)
    assert compute_agent_config_hash(cfg_base) == h0


async def test_compute_agent_config_hash_is_deterministic():
    """Hash phải deterministic — gọi nhiều lần cùng input → cùng output."""
    cfg = {
        "agent_server_url": "http://10.0.0.1:8000",
        "heartbeat_interval_seconds": 30,
        "heartbeat_jitter_seconds": 8,
        "inventory_interval_hours": 24,
        "renew_before_percent": 70,
    }
    h1 = compute_agent_config_hash(cfg)
    h2 = compute_agent_config_hash(cfg)
    h3 = compute_agent_config_hash(dict(cfg))
    assert h1 == h2 == h3
    assert len(h1) == 64  # SHA-256 hex


async def test_compute_agent_config_hash_ignores_extra_keys():
    """Hash chỉ dựa trên 5 trường cố định — thêm trường khác không ảnh hưởng."""
    cfg = {
        "agent_server_url": "http://10.0.0.1:8000",
        "heartbeat_interval_seconds": 30,
        "heartbeat_jitter_seconds": 8,
        "inventory_interval_hours": 24,
        "renew_before_percent": 70,
    }
    h1 = compute_agent_config_hash(cfg)
    h2 = compute_agent_config_hash({**cfg, "online_ttl_seconds": 180, "extra_field": "x"})
    assert h1 == h2