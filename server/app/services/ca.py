"""CA service — cấp/renew/revoke client cert cho mTLS.

Hai implementation:
- `StepCaService` — gọi step-ca HTTP API (prod).
- `LocalCaService` — sinh cert self-signed cục bộ (dev/test).

Chọn backend qua `settings.ca_mode`.
"""
from __future__ import annotations

import abc
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.config import settings


class BaseCAService(abc.ABC):
    """Interface chung cho CA service."""

    @abc.abstractmethod
    async def sign_csr(self, csr_pem: str, machine_id: uuid.UUID) -> str:
        """Ký CSR, trả client cert PEM."""
        ...

    @abc.abstractmethod
    async def renew_cert(self, old_csr_pem: str, machine_id: uuid.UUID) -> str:
        """Gia hạn cert (có thể kiểm tra identity cũ trước khi ký lại)."""
        ...

    @abc.abstractmethod
    async def revoke(self, serial_number: str) -> None:
        """Thu hồi cert theo serial."""
        ...


class StepCaService(BaseCAService):
    """Gọi step-ca HTTP API (dùng provisioner token OIDC/JWK)."""

    def __init__(self) -> None:
        self.base_url = settings.step_ca_url.rstrip("/")
        # Trong prod: authenticate với step-ca bằng provisioner password → lấy token
        self._token: str | None = None

    async def _get_token(self) -> str:
        # TODO: authenticate với step-ca, cache token
        return settings.step_ca_provisioner_password

    async def sign_csr(self, csr_pem: str, machine_id: uuid.UUID) -> str:
        token = await self._get_token()
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.post(
                f"{self.base_url}/1.0/sign",
                json={"csr": csr_pem},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["crt"]

    async def renew_cert(self, old_csr_pem: str, machine_id: uuid.UUID) -> str:
        return await self.sign_csr(old_csr_pem, machine_id)

    async def revoke(self, serial_number: str) -> None:
        token = await self._get_token()
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.post(
                f"{self.base_url}/1.0/revoke",
                json={"serial": serial_number},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            r.raise_for_status()


class LocalCaService(BaseCAService):
    """CA local — sinh cert self-signed cho dev/test.

    CA tự sinh 1 lần và cache trong memory. Không dùng cho prod.
    """

    def __init__(self) -> None:
        self._ca_key: ec.EllipticCurvePrivateKey | None = None
        self._ca_cert: x509.Certificate | None = None

    def _get_or_create_ca(self) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
        if self._ca_key is not None and self._ca_cert is not None:
            return self._ca_key, self._ca_cert
        key = ec.generate_private_key(ec.SECP256R1())
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Local CA Dev")])
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(1)
            .not_valid_before(now - timedelta(hours=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        self._ca_key = key
        self._ca_cert = cert
        return key, cert

    async def sign_csr(self, csr_pem: str, machine_id: uuid.UUID) -> str:
        ca_key, ca_cert = self._get_or_create_ca()
        csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
        now = datetime.now(UTC)
        # CN bắt buộc = machine-<machine_id> (khớp X-SSL-Client-CN khi heartbeat qua nginx)
        # — ghi đè subject CSR vì agent chưa biết machine_id lúc enroll.
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"machine-{machine_id}")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(int.from_bytes(os.urandom(8), "big"))
            .not_valid_before(now - timedelta(hours=1))
            .not_valid_after(now + timedelta(days=settings.client_cert_valid_days))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName(str(machine_id)), x509.DNSName(f"machine-{machine_id}")]
                ),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    async def renew_cert(self, old_csr_pem: str, machine_id: uuid.UUID) -> str:
        return await self.sign_csr(old_csr_pem, machine_id)

    async def revoke(self, serial_number: str) -> None:
        # Local CA không hỗ trợ CRL — chỉ log
        pass


def get_ca_service() -> BaseCAService:
    if settings.ca_mode == "stepca":
        return StepCaService()
    return LocalCaService()