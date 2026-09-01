"""Sync hostname ↔ Velociraptor client_id — chạy trong background monitor.

Logic mỗi 5 phút:
  1. Lấy cấu hình Velociraptor từ DB (`velociraptor_config`).
     - Bỏ qua nếu enabled=False hoặc thiếu URL/token.
  2. Lấy toàn bộ clients từ Velociraptor `SearchClients` API.
  3. Build map {normalized_hostname: client_id mới nhất} (nếu hostname trùng →
     chọn client có `last_seen_at` gần nhất).
  4. Lấy toàn bộ máy từ DB có hostname.
  5. Đối chiếu: máy nào có hostname khớp → upsert `velociraptor_links`. Máy
     không có client nào khớp → giữ nguyên link cũ (không tự xoá — tránh race
     với Velociraptor client mới enroll trong khoảng giữa 2 sync).
  6. Ghi `last_sync_at`, `last_sync_linked`, `last_sync_total`, `last_sync_error`.

Sync KHÔNG phụ thuộc agent inventory — không cần thay đổi agent.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.security import decrypt_aes_gcm
from app.db import session as db_session
from app.db.models import Machine, VelociraptorConfig, VelociraptorLink
from app.services.velociraptor import (
    VelociraptorClient,
    VelociraptorError,
    normalize_hostname,
    parse_client_config_yaml,
)

logger = logging.getLogger("velociraptor.sync")


async def _load_config_row() -> tuple[VelociraptorConfig | None, dict, str | None]:
    """Đọc cấu hình Velociraptor + giải mã credentials.

    Returns:
        (None, {}, None)   nếu chưa cấu hình / disabled
        (None, {}, error)  nếu có lỗi (vd giải mã fail)
        (config, creds, None) nếu OK. creds là dict với keys:
          - username, password (HTTP Basic), hoặc
          - client_cert_pem, client_key_pem, ca_cert_pem, api_connection_string (mTLS)
    """
    async with db_session.AsyncSessionLocal() as db:
        cfg = (
            await db.execute(
                select(VelociraptorConfig).where(VelociraptorConfig.id == 1)
            )
        ).scalar_one_or_none()

        if cfg is None or not cfg.enabled:
            return None, None, None
        if not cfg.server_url:
            return None, None, None

        # Mở khoá credentials — ưu tiên mTLS, fallback Basic, cuối cùng Bearer legacy.
        username = password = None
        client_cert_pem = client_key_pem = ca_cert_pem = api_connection_string = None

        if cfg.client_config_encrypted:
            try:
                yaml_content = decrypt_aes_gcm(cfg.client_config_encrypted)
                parsed_yaml = parse_client_config_yaml(yaml_content)
                client_cert_pem = parsed_yaml["client_cert"]
                client_key_pem = parsed_yaml["client_private_key"]
                ca_cert_pem = parsed_yaml["ca_cert"]
                api_connection_string = parsed_yaml["api_connection_string"]
            except Exception as e:  # noqa: BLE001

                return None, None, f"Giải mã client_config thất bại: {e}"
        elif cfg.basic_auth_encrypted:
            try:
                import json as _json
                creds_json = decrypt_aes_gcm(cfg.basic_auth_encrypted)
                creds = _json.loads(creds_json)
                username = creds["username"]
                password = creds["password"]
            except Exception as e:  # noqa: BLE001

                return None, None, f"Giải mã Basic auth thất bại: {e}"
        elif cfg.api_token_encrypted:
            # Legacy: API token (Bearer). Velociraptor mặc định KHÔNG chấp nhận
            # Bearer cho REST API, nhưng giữ fallback cho cấu hình cũ.
            try:
                _token = decrypt_aes_gcm(cfg.api_token_encrypted)
                # API token giờ không được wrapper hỗ trợ trực tiếp — bỏ qua.
                return None, None, "API token (Bearer) đã deprecated — chuyển sang HTTP Basic."
            except Exception as e:  # noqa: BLE001

                return None, None, f"Giải mã API token thất bại: {e}"

        if not (client_cert_pem or (username and password)):
            return None, None, None

        # Detach để dùng ngoài session
        cfg_id = cfg.id
        cfg_url = cfg.server_url
        cfg_enabled = cfg.enabled
        # Tạo object rỗng chỉ chứa các field cần thiết để cập nhật sau
        config_ref = VelociraptorConfig(
            id=cfg_id,
            enabled=cfg_enabled,
            server_url=cfg_url,
            api_token_encrypted=cfg.api_token_encrypted,
            allowlist=list(cfg.allowlist or []),
            last_sync_at=cfg.last_sync_at,
            last_sync_error=cfg.last_sync_error,
            last_sync_linked=cfg.last_sync_linked,
            last_sync_total=cfg.last_sync_total,
            updated_at=cfg.updated_at,
            updated_by=cfg.updated_by,
        )
        return config_ref, {
            "username": username,
            "password": password,
            "client_cert_pem": client_cert_pem,
            "client_key_pem": client_key_pem,
            "ca_cert_pem": ca_cert_pem,
            "api_connection_string": api_connection_string,
        }, None


async def _record_sync_result(
    config_id: int,
    *,
    success: bool,
    error: str | None = None,
    linked_count: int | None = None,
    total_count: int | None = None,
) -> None:
    """Ghi trạng thái sync vừa rồi vào DB (last_sync_at, last_sync_*)."""
    now = datetime.now(UTC)
    async with db_session.AsyncSessionLocal() as db:
        cfg = (
            await db.execute(
                select(VelociraptorConfig).where(VelociraptorConfig.id == config_id)
            )
        ).scalar_one_or_none()
        if cfg is None:
            return
        cfg.last_sync_at = now
        cfg.last_sync_error = error if not success else None
        if linked_count is not None:
            cfg.last_sync_linked = linked_count
        if total_count is not None:
            cfg.last_sync_total = total_count
        await db.commit()


async def sync_velociraptor_links() -> dict:
    """Hàm chính — gọi từ background monitor.

    Returns dict với thống kê (debug + log):
        {skipped, linked, total_clients, error}
    """
    config, creds, err = await _load_config_row()
    if err:
        logger.warning("Velociraptor sync bỏ qua: %s", err)
        return {"skipped": True, "reason": err}
    if config is None:
        return {"skipped": True, "reason": "disabled_or_unconfigured"}

    config_id = config.id
    linked_count = 0
    total_count = 0
    try:
        async with VelociraptorClient(
            config.server_url,
            username=creds.get("username"),
            password=creds.get("password"),
            client_cert_pem=creds.get("client_cert_pem"),
            client_key_pem=creds.get("client_key_pem"),
            ca_cert_pem=creds.get("ca_cert_pem"),
            api_connection_string=creds.get("api_connection_string"),
            timeout=settings.velociraptor_api_timeout_seconds,
        ) as velo:
            clients = await velo._vql_query(
                "SELECT client_id, os_info.hostname AS hostname, last_seen_at, os_info "
                "FROM clients() LIMIT 1000"
            )
            total_count = len(clients)

            # Build map hostname → client_id (chọn client có last_seen mới nhất)
            # VQL `SELECT ... os_info.hostname AS hostname` trả flat — đọc trực tiếp c["hostname"].
            by_hostname: dict[str, dict] = {}
            for c in clients:
                # Đọc hostname từ flat VQL output (đã alias)
                raw_host = c.get("hostname") or ""
                hostname = normalize_hostname(raw_host)
                if not hostname:
                    continue
                client_id = c.get("client_id") or ""
                if not client_id:
                    continue
                existing = by_hostname.get(hostname)
                if existing is None:
                    by_hostname[hostname] = c
                else:
                    # So sánh last_seen — chọn mới hơn
                    cur_seen = (c.get("last_seen_at") or "")
                    ex_seen = (existing.get("last_seen_at") or "")
                    if cur_seen > ex_seen:
                        by_hostname[hostname] = c

        # Lấy tất cả máy có hostname (case-insensitive normalize).
        # Cần thêm machine_uuid + enrolled_at + last_seen_at để dedup các bản
        # ghi trùng (cùng máy vật lý bị enroll nhiều lần do cert hết hạn / agent
        # bị gỡ cài đặt rồi cài lại — tạo 2 row DB cùng machine_uuid).
        async with db_session.AsyncSessionLocal() as db:
            machines = (
                (
                    await db.execute(
                        select(
                            Machine.id,
                            Machine.hostname,
                            Machine.machine_uuid,
                            Machine.enrolled_at,
                            Machine.last_seen_at,
                        ).where(
                            Machine.hostname.is_not(None),
                            Machine.hostname != "",
                        )
                    )
                )
                .all()
            )

            # Dedup các bản ghi máy trùng TRƯỚC KHI link Velociraptor — tránh
            # IntegrityError "ix_velociraptor_links_client_id" khi nhiều row DB
            # claim cùng Velociraptor client_id (unique constraint).
            # Quy tắc:
            #   - Key = uuid (nếu có) → cùng machine_uuid = cùng máy vật lý,
            #     giữ row có last_seen mới nhất (fallback enrolled_at).
            #   - Key = "host:{normalized}" (fallback khi uuid rỗng) → trùng
            #     hostname + không có fingerprint coi như cùng máy.
            dedup: dict[str, tuple[uuid.UUID, str, datetime | None]] = {}
            for m_id, m_hostname, m_uuid, m_enrolled, m_last_seen in machines:
                norm = normalize_hostname(m_hostname)
                if not norm:
                    continue
                ts = m_last_seen or m_enrolled
                key = m_uuid if m_uuid else f"host:{norm}"
                cur = dedup.get(key)
                if cur is None:
                    dedup[key] = (m_id, m_hostname, ts)
                elif ts is not None and (cur[2] is None or ts > cur[2]):
                    dedup[key] = (m_id, m_hostname, ts)

            # Upsert links từ danh sách đã dedup (mỗi key đúng 1 row).
            for m_id, m_hostname, _ts in dedup.values():
                norm = normalize_hostname(m_hostname)
                if not norm:
                    continue
                client = by_hostname.get(norm)
                if client is None:
                    continue
                client_id = client["client_id"]
                last_seen_raw = client.get("last_seen_at") or ""
                try:
                    last_seen = (
                        datetime.fromisoformat(last_seen_raw)
                        if last_seen_raw
                        else None
                    )
                except (ValueError, TypeError):
                    last_seen = None

                os_info = client.get("os_info") or {}
                hostname_keep = os_info.get("hostname") or m_hostname

                stmt = (
                    pg_insert(VelociraptorLink)
                    .values(
                        machine_id=m_id,
                        client_id=client_id,
                        hostname=hostname_keep,
                        os_info=os_info,
                        last_seen_at=last_seen,
                        synced_at=datetime.now(UTC),
                    )
                    .on_conflict_do_update(
                        index_elements=[VelociraptorLink.machine_id],
                        set_={
                            "client_id": client_id,
                            "hostname": hostname_keep,
                            "os_info": os_info,
                            "last_seen_at": last_seen,
                            "synced_at": datetime.now(UTC),
                        },
                    )
                )
                await db.execute(stmt)
                linked_count += 1

            await db.commit()

        await _record_sync_result(
            config_id,
            success=True,
            linked_count=linked_count,
            total_count=total_count,
        )
        logger.info(
            "Velociraptor sync OK: %d/%d clients linked", linked_count, total_count
        )
        return {"linked": linked_count, "total_clients": total_count}

    except VelociraptorError as e:
        err_msg = f"VelociraptorError: {e}"
        logger.warning("Velociraptor sync lỗi: %s", e)
        await _record_sync_result(config_id, success=False, error=err_msg)
        return {"error": err_msg}
    except Exception as e:  # noqa: BLE001

        err_msg = f"{type(e).__name__}: {e}"
        logger.exception("Velociraptor sync lỗi không mong đợi")
        await _record_sync_result(config_id, success=False, error=err_msg)
        return {"error": err_msg}
