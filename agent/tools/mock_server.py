#!/usr/bin/env python3
"""Mock server — kiểm tra agent end-to-end trên Linux.

- Nhận request từ agent, VALIDATE payload bằng schema Pydantic thật của server
  (import app.schemas từ /home/windowsId/server nếu được).
- Trả response cố định khớp server thật (enroll/heartbeat/inventory/renew/agent-config).
- In mọi request ra file log để review shape.

Cách chạy:
  python3 tools/mock_server.py --port 8787 [--schema-dir /home/windowsId/server]
"""
import argparse
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT_PLACEHOLDER = "__PORT__"

# ── CA local (giống LocalCaService của server) ────────────────────────────────
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_CA_KEY = ec.generate_private_key(ec.SECP256R1())
_NOW = datetime.now(UTC)
_CA_CERT = (
    x509.CertificateBuilder()
    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mock CA Dev")]))
    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mock CA Dev")]))
    .public_key(_CA_KEY.public_key())
    .serial_number(1)
    .not_valid_before(_NOW - timedelta(hours=1))
    .not_valid_after(_NOW + timedelta(days=3650))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .sign(_CA_KEY, hashes.SHA256())
)
_CA_PEM = _CA_CERT.public_bytes(serialization.Encoding.PEM).decode()


def sign_csr(csr_pem: str, machine_id: str) -> str:
    csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(_CA_CERT.subject)
        .public_key(csr.public_key())
        .serial_number(int.from_bytes(__import__("os").urandom(8), "big"))
        .not_valid_before(_NOW - timedelta(hours=1))
        .not_valid_after(_NOW + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(machine_id), x509.DNSName(f"machine-{machine_id}")]),
            critical=False,
        )
        .sign(_CA_KEY, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


ENROLL_RESPONSE = {
    "machine_id": "3c2f1a4b-9d6e-4f8a-b2c1-0a1b2c3d4e5f",
    "client_cert_pem": "__SIGNED_CERT__",
    "ca_cert_pem": _CA_PEM,
    "renew_after": (datetime.now(UTC) + timedelta(days=255)).isoformat().replace("+00:00", "Z"),
    "is_new_machine": True,
    "status": "online",
    "agent_server_url": f"http://{HOST}:{PORT_PLACEHOLDER}",
    "heartbeat_interval_seconds": 30,
    "heartbeat_jitter_seconds": 8,
    "inventory_interval_hours": 24,
}

HEARTBEAT_RESPONSE = {
    "ok": True,
    "server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "renew_after": (datetime.now(UTC) + timedelta(days=255)).isoformat().replace("+00:00", "Z"),
    "rescan_requested": False,
    "notice_version": None,
    "heartbeat_interval_seconds": 30,
    "heartbeat_jitter_seconds": 8,
    "server_url": f"http://{HOST}:{PORT_PLACEHOLDER}",
    "agent_server_url": f"http://{HOST}:{PORT_PLACEHOLDER}",
    "inventory_interval_hours": 24,
    "agent_config_hash": "mock_cfg_hash_v1",
}

INVENTORY_RESPONSE = {"ok": True, "config_changed": False}
RENEW_RESPONSE = {
    "client_cert_pem": "__SIGNED_CERT__",
    "ca_cert_pem": _CA_PEM,
    "cert_serial": None,
    "renew_after": (datetime.now(UTC) + timedelta(days=255)).isoformat().replace("+00:00", "Z"),
}
AGENT_CONFIG_RESPONSE = {
    "server_url": f"http://{HOST}:{PORT_PLACEHOLDER}",
    "heartbeat_interval_seconds": 30,
    "heartbeat_jitter_seconds": 8,
    "online_ttl_seconds": 76,
    "inventory_interval_hours": 24,
    "renew_before_percent": 70,
    "agent_config_hash": "mock_cfg_hash_v1",
    "server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
}


def load_schemas(schema_dir: str):
    """Cố import schema thật từ server; nếu không được thì dùng bản inline."""
    if schema_dir:
        sys.path.insert(0, str(Path(schema_dir).resolve()))
        try:
            from app.schemas import EnrollRequest, HeartbeatRequest, InventoryRequest  # noqa: F401
            from app.api.routes.renew import RenewRequest  # noqa: F401

            return EnrollRequest, HeartbeatRequest, InventoryRequest, RenewRequest, "real-server"
        except Exception as e:  # noqa: BLE001
            print(f"[mock] không import được schema server thật ({e}) — dùng inline", file=sys.stderr)

    from pydantic import BaseModel, Field

    class F(BaseModel):
        smbios_uuid: str | None = None
        machine_guid: str | None = None
        mainboard_serial: str | None = None

    class EnrollRequest(BaseModel):
        token: str = Field(min_length=8, max_length=64)
        fingerprint: F
        csr_pem: str
        hostname: str | None = None

    class HeartbeatRequest(BaseModel):
        logged_user: str | None = None
        uptime_sec: int | None = None
        ip: str | None = None

    class NetIf(BaseModel):
        name: str | None = None
        ip: str | None = None
        mac: str | None = None
        is_dual_homed: bool = False

    class Security(BaseModel):
        antivirus: list[dict] | None = None
        windows_update_status: str | None = None
        bitlocker: str | None = None
        rdp_enabled: bool | None = None
        local_accounts: list[dict] | None = None
        smarts: list[dict] | None = None

    class InventoryRequest(BaseModel):
        os_name: str | None = None
        os_version: str | None = None
        os_build: str | None = None
        os_arch: str | None = None
        os_installed_at: datetime | None = None
        activation_status: str | None = None
        cpu: dict | None = None
        ram_gb: float | None = None
        disks: list[dict] | None = None
        gpu: dict | None = None
        mainboard: dict | None = None
        bios: dict | None = None
        network: list[NetIf] | None = None
        logged_user: str | None = None
        installed_software: list[dict] | None = None
        security: Security | None = None
        is_vm: bool | None = None
        config_hash: str | None = None

    class RenewRequest(BaseModel):
        csr_pem: str

    return EnrollRequest, HeartbeatRequest, InventoryRequest, RenewRequest, "inline"


def make_handler(models, log_file, server_url):
    EnrollRequest, HeartbeatRequest, InventoryRequest, RenewRequest, src = models
    validators = {
        "/api/enroll": EnrollRequest,
        "/api/heartbeat": HeartbeatRequest,
        "/api/inventory": InventoryRequest,
        "/api/renew": RenewRequest,
    }
    responses = {
        "/api/enroll": ENROLL_RESPONSE,
        "/api/heartbeat": HEARTBEAT_RESPONSE,
        "/api/inventory": INVENTORY_RESPONSE,
        "/api/renew": RENEW_RESPONSE,
        "/api/agent/config": AGENT_CONFIG_RESPONSE,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _handle(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            encoding = self.headers.get("Content-Encoding", "")
            if "gzip" in encoding:
                import gzip

                raw = gzip.decompress(raw)
            body_text = raw.decode("utf-8", errors="replace")

            path = self.path.split("?")[0]
            entry = {
                "method": self.command,
                "path": path,
                "ua": self.headers.get("User-Agent"),
                "body": json.loads(body_text) if body_text else None,
            }

            if path in validators:
                try:
                    validators[path].model_validate(entry["body"])
                    entry["schema"] = f"VALID ({src})"
                except Exception as e:  # noqa: BLE001
                    entry["schema"] = f"INVALID: {e}"

            resp = responses.get(path)
            status_code = 200 if resp is not None else 404
            schema_status = entry.get("schema", "N/A")
            print(f"[mock] {datetime.now(UTC).strftime('%H:%M:%S')} {self.command} {path} -> {status_code} [{schema_status}]")

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, indent=2) + "\n---\n")

            if resp is None:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"detail":"not found"}')
                return

            # Ký CSR thật cho enroll/renew (giống LocalCaService)
            payload = resp
            if path in ("/api/enroll", "/api/renew") and entry["body"] is not None:
                csr_pem = entry["body"].get("csr_pem", "")
                try:
                    signed = sign_csr(csr_pem, "3c2f1a4b-9d6e-4f8a-b2c1-0a1b2c3d4e5f")
                    payload = dict(resp)
                    payload["client_cert_pem"] = signed
                except Exception as e:  # noqa: BLE001
                    entry["schema"] = f"CSR SIGN FAILED: {e}"

            payload_json = json.dumps(payload).replace(PORT_PLACEHOLDER, str(self.server.server_port))
            data = payload_json.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self._handle()

        def do_GET(self):
            self._handle()

    return Handler


def main():
    import tempfile

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    server_dir = repo_root / "server"
    default_schema_dir = str(server_dir) if server_dir.exists() else ""
    default_log = str(Path(tempfile.gettempdir()) / "mock_agent_requests.jsonl")

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--schema-dir", default=default_schema_dir)
    ap.add_argument("--log", default=default_log)
    args = ap.parse_args()

    models = load_schemas(args.schema_dir)
    print(f"[mock] schema nguồn: {models[4]}")
    server = ThreadingHTTPServer((HOST, args.port), make_handler(models, args.log, f"http://{HOST}:{args.port}"))
    print(f"[mock] listening http://{HOST}:{args.port} — log: {args.log}")
    server.serve_forever()


if __name__ == "__main__":
    main()
