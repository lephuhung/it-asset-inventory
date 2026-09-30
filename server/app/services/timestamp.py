"""Dấu thời gian tin cậy (trusted timestamp) cho báo cáo PDF — RFC 3161.

Nhúng Document Timestamp (DocTS, PDF 2.0) vào cuối file bằng incremental update:
nội dung báo cáo không đổi, server chỉ gửi SHA-256 của tài liệu lên TSA (không
gửi nội dung). DocTS chứng minh "file này đã tồn tại trước `genTime` do TSA cấp".

Verify: POST /api/reports/verify, Adobe Reader (hiển thị document timestamp),
hoặc pyHanko. `intact` = chữ ký TSA khớp dữ liệu; `valid` cần cấu hình trust root
của TSA (prod). Mặc định dùng FreeTSA (dev) — cấu hình qua `settings.tsa_url`.
"""
from __future__ import annotations

import hashlib
import io
from typing import Any

from app.core.config import settings


class TimestampError(RuntimeError):
    """TSA không phản hồi / trả token lỗi — route map sang HTTP 502."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _default_stamper():
    """RFC 3161 client trỏ tới TSA cấu hình trong settings."""
    from pyhanko.sign.timestamps.aiohttp_client import HTTPTimeStamper

    auth = (settings.tsa_username, settings.tsa_password) if settings.tsa_username else None
    return HTTPTimeStamper(settings.tsa_url, timeout=settings.tsa_timeout_seconds, auth=auth)


def timestamp_pdf(pdf_bytes: bytes, *, stamper: Any | None = None) -> bytes:
    """Nhúng DocTS (RFC 3161) vào PDF, trả về bytes file mới.

    HÀM SYNC — pyhanko tự chạy event loop riêng (asyncio.run) → route async PHẢI
    gọi qua asyncio.to_thread. `stamper` cho phép test truyền DummyTimeStamper
    (không cần mạng); mặc định dùng HTTPTimeStamper từ settings.
    """
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.signers.pdf_signer import PdfTimeStamper

    writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
    try:
        out = PdfTimeStamper(timestamper=stamper or _default_stamper()).timestamp_pdf(
            writer, "sha256"
        )
    except Exception as exc:
        raise TimestampError(f"TSA {settings.tsa_url} không phản hồi: {exc}") from exc
    return out.getvalue()


async def read_pdf_timestamps(pdf_bytes: bytes) -> list[dict]:
    """Đọc các DocTS nhúng trong PDF.

    Trả list [{gen_time, tsa_subject, intact, valid}] — gen_time là thời điểm TSA
    cấp dấu (UTC). `intact` = chữ ký TSA khớp nội dung (đủ chứng minh tồn tại);
    `valid` chỉ True khi chain TSA được tin cậy (cần trust root của TSA — dev bỏ qua).
    """
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import async_validate_pdf_timestamp

    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    results = []
    for sig in reader.embedded_timestamp_signatures:
        status = await async_validate_pdf_timestamp(sig)
        cert = status.signing_cert
        subject = cert.subject.human_friendly if cert is not None else ""
        results.append(
            {
                "gen_time": status.timestamp.isoformat() if status.timestamp else None,
                "tsa_subject": subject,
                "intact": bool(status.intact),
                "valid": bool(status.valid),
            }
        )
    return results
