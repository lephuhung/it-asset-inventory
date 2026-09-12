"""Round-trip test for officer migration downgrade.

Migration `b5c6d7e8f9a0_officers_table` refactor từ các cột `officer_*` trên
`system_profiles` sang bảng `officers` + FK `officer_id`. Alembic invariant:

> downgrade từ revision N phải tạo schema tương ứng với revision N-1.

Revision N-1 = `bbcbbb152a4b` (merge), trạng thái schema có:
- `system_profiles.officer_*` columns (do `a5b6c7d8e9f1` thêm)
- KHÔNG có `officers` table, `officer_id` (do `b5c6d7e8f9a0` thêm/xóa)

Test này:
1. Tạo DB tạm
2. Chạy `alembic upgrade` tới `b5c6d7e8f9a0` (head của branch officer refactor)
3. Chạy `alembic downgrade -1` → phải về `bbcbbb152a4b`
4. Verify schema tại `bbcbbb152a4b` có `officer_*` columns và không có `officer_id`
5. Chạy tiếp `alembic downgrade -1` → về `a5b6c7d8e9f1` (vẫn có columns)
6. Verify `alembic heads` chỉ ra 1 head, không phát sinh head mới
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import asyncpg
import pytest

# Head của branch officer refactor (sau merge).
OFFICER_REFACTOR_REV = "b5c6d7e8f9a0"
PRIOR_REV = "bbcbbb152a4b"  # merge — schema trước khi refactor
PRIOR_TO_MERGE_REV = "a5b6c7d8e9f1"  # migration thêm officer_* columns

OFFICER_LEGACY_COLUMNS = (
    "officer_name",
    "officer_organization",
    "officer_title",
    "officer_phone",
    "officer_email",
    "officer_note",
    "officer_assigned_at",
    "officer_assigned_by",
)


@pytest.fixture
async def temp_db():
    """Tạo DB PostgreSQL tạm cho migration round-trip test."""
    admin_url = (
        os.environ.get(
            "TEST_DATABASE_ADMIN_URL",
            "postgresql://inventory:inventory@127.0.0.1:5432/postgres",
        )
    )

    db_name = f"alembic_roundtrip_{uuid.uuid4().hex[:8]}"

    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    # Build asyncpg URL for tests to introspect schema
    asyncpg_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"

    yield db_name, asyncpg_url

    conn = await asyncpg.connect(admin_url)
    try:
        # Terminate any remaining sessions then drop
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


def _alembic_url(asyncpg_url: str) -> str:
    """Convert asyncpg URL sang scheme async cho alembic env.py.

    `alembic/env.py` dùng `async_engine_from_config` nên bắt buộc scheme async.
    """
    if asyncpg_url.startswith("postgresql+asyncpg://"):
        return asyncpg_url
    return asyncpg_url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _run_alembic(cmd: list[str], db_url: str) -> subprocess.CompletedProcess:
    """Chạy alembic CLI với DATABASE_URL override."""
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env.setdefault("SECRET_KEY", "x" * 32)
    env.setdefault("DATA_ENCRYPTION_KEY", "x" * 32)
    env.setdefault("APP_ENV", "test")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *cmd],
        cwd=".",
        env=env,
        capture_output=True,
        text=True,
    )


async def _columns_of(conn, table: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
        table,
    )
    return {r["column_name"] for r in rows}


async def _tables_in(conn) -> set[str]:
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {r["table_name"] for r in rows}


@pytest.mark.asyncio
async def test_officer_refactor_downgrade_restores_legacy_columns(temp_db):
    """`b5c6d7e8f9a0` downgrade phải khôi phục `officer_*` columns.

    BUG trước fix: downgrade chỉ drop `officer_id` + `officers` table mà KHÔNG
    restore `officer_*` columns → vi phạm Alembic invariant.
    """
    db_name, asyncpg_url = temp_db
    sync_url = _alembic_url(asyncpg_url)

    # 1. Upgrade tới b5c6d7e8f9a0
    result = _run_alembic(["upgrade", OFFICER_REFACTOR_REV], sync_url)
    assert result.returncode == 0, (
        f"alembic upgrade failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    conn = await asyncpg.connect(asyncpg_url)
    try:
        cols_after_upgrade = await _columns_of(conn, "system_profiles")
        tables_after_upgrade = await _tables_in(conn)
        assert "officer_id" in cols_after_upgrade
        assert "officers" in tables_after_upgrade
        # Các cột cũ đã bị drop sau upgrade
        assert not any(c.startswith("officer_") and c != "officer_id" for c in cols_after_upgrade)
    finally:
        await conn.close()

    # 2. Downgrade -1 → bbcbbb152a4b
    result = _run_alembic(["downgrade", "-1"], sync_url)
    assert result.returncode == 0, (
        f"alembic downgrade failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    conn = await asyncpg.connect(asyncpg_url)
    try:
        cols = await _columns_of(conn, "system_profiles")
        tables = await _tables_in(conn)
        # `officer_id` đã được drop
        assert "officer_id" not in cols
        # Bảng `officers` đã được drop
        assert "officers" not in tables
        # Quan trọng: các cột legacy phải được khôi phục
        missing = [c for c in OFFICER_LEGACY_COLUMNS if c not in cols]
        assert not missing, (
            f"downgrade b5c6d7e8f9a0 KHÔNG khôi phục các cột: {missing}. "
            "Đây là vi phạm Alembic invariant."
        )
    finally:
        await conn.close()

    # Lưu ý: KHÔNG downgrade thêm — `bbcbbb152a4b` là merge revision với 2
    # down_revisions (`a5b6c7d8e9f1` và `c7d8e9f0a1b2`) nên `-1` từ merge
    # là ambiguous. Mục tiêu của fix là khôi phục schema của merge; mọi
    # branch hợp lệ phía dưới merge đều kế thừa các cột này.


@pytest.mark.asyncio
async def test_officer_refactor_downgrade_migrates_data_back(temp_db):
    """Best-effort: downgrade cố gắng migrate data từ `officers` về legacy cols."""
    db_name, asyncpg_url = temp_db
    sync_url = _alembic_url(asyncpg_url)

    # 1. Upgrade tới b5c6d7e8f9a0 (officer refactor). Tại revision này có
    # `officers` table + `officer_id` FK. Cần upgrade qua `a5b6c7d8e9f1` +
    # merge để có các cột legacy tồn tại trước đó.
    result = _run_alembic(["upgrade", OFFICER_REFACTOR_REV], sync_url)
    assert result.returncode == 0, (
        f"alembic upgrade failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # 2. Insert sample user, officer, then assign to profile
    conn = await asyncpg.connect(asyncpg_url)
    try:
        # Cần một organization + user trước
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        officer_id = uuid.uuid4()

        await conn.execute(
            "INSERT INTO organizations (id, name, type) "
            "VALUES ($1, 'test-org', 'ubnd_xa')",
            org_id,
        )
        await conn.execute(
            "INSERT INTO users (id, org_id, full_name, email, role, password_hash, is_active, is_2fa_enabled, created_at) "
            "VALUES ($1, $2, 'Test User', 'tu@test.vn', 'super_admin', 'x', true, false, now())",
            user_id, org_id,
        )
        # Create profile first
        await conn.execute(
            "INSERT INTO system_profiles (id, org_id, code, name, level, status, created_by, created_at, updated_at) "
            "VALUES ($1, $2, 'TEST-001', 'Test', 1, 'drafted', $3, now(), now())",
            profile_id, org_id, user_id,
        )
        # Now create officer
        await conn.execute(
            "INSERT INTO officers (id, name, organization, title, phone, email, note, created_by, created_at, updated_at) "
            "VALUES ($1, 'Nguyen Van A', 'Org X', 'Manager', '0901234567', 'a@x.vn', 'note text', $2, now(), now())",
            officer_id, user_id,
        )
        # Assign to profile
        await conn.execute(
            "UPDATE system_profiles SET officer_id = $1 WHERE id = $2",
            officer_id, profile_id,
        )
    finally:
        await conn.close()

    # 3. Downgrade -1 → bbcbbb152a4b (trigger migration b5c6d7e8f9a0 downgrade)
    result = _run_alembic(["downgrade", "-1"], sync_url)
    assert result.returncode == 0, result.stderr

    # 4. Verify data was migrated back
    conn = await asyncpg.connect(asyncpg_url)
    try:
        row = await conn.fetchrow(
            "SELECT officer_name, officer_organization, officer_title, officer_phone, "
            "officer_email, officer_note, officer_assigned_by "
            "FROM system_profiles WHERE id = $1",
            profile_id,
        )
        assert row is not None
        assert row["officer_name"] == "Nguyen Van A"
        assert row["officer_organization"] == "Org X"
        assert row["officer_title"] == "Manager"
        assert row["officer_phone"] == "0901234567"
        assert row["officer_email"] == "a@x.vn"
        assert row["officer_note"] == "note text"
        assert row["officer_assigned_by"] == user_id
    finally:
        await conn.close()


def test_officer_refactor_creates_no_extra_heads():
    """Migration fix không được tạo head mới (chỉ sửa downgrade)."""
    from pathlib import Path

    from alembic.script import ScriptDirectory

    migrations_dir = Path(__file__).parents[1] / "alembic"
    script = ScriptDirectory(str(migrations_dir))
    heads = script.get_heads()
    assert len(heads) == 1, f"Phải đúng 1 head, hiện có {len(heads)}: {heads}"


# ── BLOCKER 2 — upgrade() phải bảo toàn legacy officer data ─────────

import json as _json
from datetime import UTC as _UTC, datetime as _dt


async def _ensure_users_for_officer(conn, uuids, email_prefix: str) -> None:
    """Migration yêu cầu officers.created_by FK → users.id. Test helper này
    tạo trước admin user cho từng UUID nếu cần."""
    for uid in uuids:
        # idempotent: insert or ignore
        await conn.execute(
            """
            INSERT INTO users (id, org_id, full_name, email, role,
                password_hash, is_active, is_2fa_enabled, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'super_admin', 'x', true, false, now(), now())
            ON CONFLICT (id) DO NOTHING
            """,
            uid,
            "00000000-0000-0000-0000-000000000001",  # dummy org id
            f"Test Admin {uid.hex[:8]}",
            f"{email_prefix}-{uid.hex[:8]}@test.vn",
        )


@pytest.mark.asyncio
async def test_officer_upgrade_preserves_legacy_data(temp_db):
    """BLOCKER 2: migration upgrade() bỏ sót legacy officer data.

    Trước fix, upgrade tạo officers table + officer_id column rồi drop các
    officer_* legacy columns KHÔNG migrate data. Nếu production DB đã có
    dữ liệu cán bộ thì upgrade sẽ MẤT toàn bộ.

    Acceptance:
      1. Pre-condition: revision trước có system_profiles với officer_* data.
      2. Sau upgrade: officers row tồn tại, officer_id link đúng, fields giữ nguyên.
      3. Multiple profiles, null/partial officer_* cũng xử lý được.
      4. Sau downgrade: legacy data vẫn giữ nguyên (round-trip preserved).
    """
    db_name, asyncpg_url = temp_db
    sync_url = _alembic_url(asyncpg_url)

    # Step 1: upgrade tới revision TRƯỚC (bbcbbb152a4b) — schema có officer_* cols
    result = _run_alembic(["upgrade", PRIOR_REV], sync_url)
    assert result.returncode == 0, (
        f"alembic upgrade prior failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    conn = await asyncpg.connect(asyncpg_url)

    # Tạo users trước (FK từ system_profiles.created_by và officers.created_by)
    user_ids = [uuid.uuid4() for _ in range(3)]
    org_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO organizations (id, name, type)
        VALUES ($1, 'test-org', 'ubnd_xa')
        ON CONFLICT (id) DO NOTHING
        """,
        org_id,
    )
    for uid in user_ids:
        await conn.execute(
            """
            INSERT INTO users (id, org_id, full_name, email, role,
                password_hash, is_active, is_2fa_enabled, created_at)
            VALUES ($1, $2, $3, $4, 'super_admin', 'x', true, false, now())
            ON CONFLICT (id) DO NOTHING
            """,
            uid, org_id,
            f"Admin {uid.hex[:6]}",
            f"{uid.hex[:6]}@test.vn",
        )

    # Tạo system_profiles với legacy officer_* data
    profile_a = uuid.uuid4()
    profile_b = uuid.uuid4()
    profile_c = uuid.uuid4()  # sẽ có null officer_name
    await conn.execute(
        """
        INSERT INTO system_profiles (
            id, org_id, code, name, level, status,
            officer_name, officer_organization, officer_title,
            officer_phone, officer_email, officer_note,
            officer_assigned_at, officer_assigned_by,
            created_by, created_at, updated_at
        ) VALUES (
            $1, $2, 'HS-A', 'Profile A', 1, 'drafted',
            'Nguyen Van A', 'Org X', 'Manager',
            '0901234567', 'a@x.vn', 'note about A',
            now(), $3,
            $4, now(), now()
        )
        """,
        profile_a, org_id, user_ids[0], user_ids[0],
    )
    await conn.execute(
        """
        INSERT INTO system_profiles (
            id, org_id, code, name, level, status,
            officer_name, officer_organization, officer_title,
            officer_phone, officer_email, officer_note,
            officer_assigned_at, officer_assigned_by,
            created_by, created_at, updated_at
        ) VALUES (
            $1, $2, 'HS-B', 'Profile B', 1, 'drafted',
            'Tran Thi B', 'Org Y', 'Director',
            '0907654321', 'b@y.vn', 'note about B',
            now(), $3,
            $4, now(), now()
        )
        """,
        profile_b, org_id, user_ids[1], user_ids[1],
    )
    # Profile C: null officer_name — edge case
    await conn.execute(
        """
        INSERT INTO system_profiles (
            id, org_id, code, name, level, status,
            officer_name, officer_organization, officer_title,
            officer_phone, officer_email, officer_note,
            officer_assigned_at, officer_assigned_by,
            created_by, created_at, updated_at
        ) VALUES (
            $1, $2, 'HS-C', 'Profile C', 1, 'drafted',
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            $3, now(), now()
        )
        """,
        profile_c, org_id, user_ids[2],
    )
    await conn.close()

    # Step 2: upgrade tới b5c6d7e8f9a0 — phải migrate data
    result = _run_alembic(["upgrade", OFFICER_REFACTOR_REV], sync_url)
    assert result.returncode == 0, (
        f"alembic upgrade refactor failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Step 3: verify data preserved
    conn = await asyncpg.connect(asyncpg_url)
    try:
        # Cần officers rows cho profile A và B (không cho C vì officer_name NULL)
        officers_a = await conn.fetchrow(
            "SELECT * FROM officers WHERE name = 'Nguyen Van A'"
        )
        officers_b = await conn.fetchrow(
            "SELECT * FROM officers WHERE name = 'Tran Thi B'"
        )
        assert officers_a is not None, (
            "BLOCKER 2 BUG: officers row cho 'Nguyen Van A' không tồn tại "
            "sau upgrade — data đã bị mất."
        )
        assert officers_b is not None, (
            "BLOCKER 2 BUG: officers row cho 'Tran Thi B' không tồn tại "
            "sau upgrade — data đã bị mất."
        )

        # Verify fields preserved
        assert officers_a["organization"] == "Org X"
        assert officers_a["title"] == "Manager"
        assert officers_a["phone"] == "0901234567"
        assert officers_a["email"] == "a@x.vn"
        assert officers_a["note"] == "note about A"

        assert officers_b["organization"] == "Org Y"
        assert officers_b["title"] == "Director"
        assert officers_b["phone"] == "0907654321"
        assert officers_b["email"] == "b@y.vn"

        # Verify officer_id link
        profile_a_row = await conn.fetchrow(
            "SELECT officer_id FROM system_profiles WHERE id = $1", profile_a
        )
        assert profile_a_row["officer_id"] == officers_a["id"], (
            f"Profile A phải có officer_id trỏ tới officer Nguyen Van A. "
            f"actual={profile_a_row['officer_id']}, expected={officers_a['id']}"
        )

        profile_b_row = await conn.fetchrow(
            "SELECT officer_id FROM system_profiles WHERE id = $1", profile_b
        )
        assert profile_b_row["officer_id"] == officers_b["id"]

        # Profile C: officer_name NULL → không tạo officer row,
        # officer_id phải NULL (không bị sai FK).
        profile_c_row = await conn.fetchrow(
            "SELECT officer_id FROM system_profiles WHERE id = $1", profile_c
        )
        assert profile_c_row["officer_id"] is None, (
            "Profile C có officer_name NULL → officer_id phải NULL."
        )

        # Verify legacy columns dropped (không còn trên schema)
        cols = await _columns_of(conn, "system_profiles")
        for legacy_col in (
            "officer_name", "officer_organization", "officer_title",
            "officer_phone", "officer_email", "officer_note",
            "officer_assigned_at", "officer_assigned_by",
        ):
            assert legacy_col not in cols, (
                f"Upgrade chưa drop legacy column {legacy_col}? "
                "(cần drop sau khi migrate xong)."
            )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_officer_upgrade_then_downgrade_preserves_legacy_data(temp_db):
    """BLOCKER 2 follow-up: round-trip upgrade → downgrade phải giữ data.

    Sau upgrade (officers table), rollback → bbcbbb152a4b. Các system_profiles
    phải có lại officer_* columns với giá trị gốc (không bị migrate-and-lost).
    """
    db_name, asyncpg_url = temp_db
    sync_url = _alembic_url(asyncpg_url)

    # Step 1: upgrade tới PRIOR_REV
    result = _run_alembic(["upgrade", PRIOR_REV], sync_url)
    assert result.returncode == 0, result.stderr

    conn = await asyncpg.connect(asyncpg_url)
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO organizations (id, name, type) VALUES ($1, 'roundtrip', 'ubnd_xa')",
        org_id,
    )
    await conn.execute(
        """INSERT INTO users (id, org_id, full_name, email, role,
           password_hash, is_active, is_2fa_enabled, created_at)
           VALUES ($1, $2, 'Admin', 'admin@rt.vn', 'super_admin', 'x', true, false, now())""",
        user_id, org_id,
    )

    profile_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO system_profiles (
            id, org_id, code, name, level, status,
            officer_name, officer_organization, officer_title,
            officer_phone, officer_email, officer_note,
            officer_assigned_at, officer_assigned_by,
            created_by, created_at, updated_at
        ) VALUES (
            $1, $2, 'HS-RT', 'Roundtrip Profile', 1, 'drafted',
            'Le Van C', 'Org Z', 'Lead',
            '0909999999', 'c@z.vn', 'roundtrip note',
            '2026-01-15T00:00:00+00:00'::timestamptz, $3,
            $3, now(), now()
        )""",
        profile_id, org_id, user_id,
    )
    await conn.close()

    # Step 2: upgrade tới b5c6d7e8f9a0
    result = _run_alembic(["upgrade", OFFICER_REFACTOR_REV], sync_url)
    assert result.returncode == 0, result.stderr

    # Step 3: downgrade
    result = _run_alembic(["downgrade", "-1"], sync_url)
    assert result.returncode == 0, result.stderr

    # Step 4: verify legacy data restored về system_profiles
    conn = await asyncpg.connect(asyncpg_url)
    try:
        row = await conn.fetchrow(
            """SELECT officer_name, officer_organization, officer_title,
               officer_phone, officer_email, officer_note,
               officer_assigned_by
               FROM system_profiles WHERE id = $1""",
            profile_id,
        )
        assert row is not None, "Profile phải còn sau downgrade."
        assert row["officer_name"] == "Le Van C", (
            f"Round-trip MẤT data: officer_name phải là 'Le Van C'. "
            f"actual={row['officer_name']!r}"
        )
        assert row["officer_organization"] == "Org Z"
        assert row["officer_title"] == "Lead"
        assert row["officer_phone"] == "0909999999"
        assert row["officer_email"] == "c@z.vn"
        assert row["officer_note"] == "roundtrip note"
        assert row["officer_assigned_by"] == user_id
    finally:
        await conn.close()

# ── BLOCKER 2 v3 — duplicate officer_name phải map đúng theo profile_id ─


@pytest.mark.asyncio
async def test_officer_upgrade_preserves_profiles_with_duplicate_officer_names(temp_db):
    """BLOCKER 2 v3: hai profiles có CÙNG officer_name nhưng khác data phải
    map sang 2 officer rows khác nhau, link đúng theo profile_id.

    Trước fix: UPDATE join `WHERE sp.officer_name = i.name` nondeterministic
    khi nhiều profiles cùng tên. Có thể: cả 2 profiles link về 1 officer,
    officer còn lại orphan → mất data.

    Acceptance:
      - Pre: 2 profiles (A, B) với officer_name giống nhau, data khác.
      - Sau upgrade: 2 officers rows, profile A officer_id != profile B
        officer_id; data của mỗi officer khớp với profile tương ứng.
    """
    db_name, asyncpg_url = temp_db
    sync_url = _alembic_url(asyncpg_url)

    # Step 1: upgrade tới revision TRƯỚC (schema có officer_* legacy cols)
    result = _run_alembic(["upgrade", PRIOR_REV], sync_url)
    assert result.returncode == 0, result.stderr

    conn = await asyncpg.connect(asyncpg_url)
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO organizations (id, name, type) VALUES ($1, 'dup-test', 'ubnd_xa')",
        org_id,
    )
    await conn.execute(
        """INSERT INTO users (id, org_id, full_name, email, role,
           password_hash, is_active, is_2fa_enabled, created_at)
           VALUES ($1, $2, 'Admin', 'admin@dup.vn', 'super_admin', 'x', true, false, now())""",
        user_id, org_id,
    )

    # CÙNG officer_name, khác data
    profile_a = uuid.uuid4()
    profile_b = uuid.uuid4()
    for prof_id, label in [(profile_a, "A"), (profile_b, "B")]:
        org_label = f"Org {label}"
        phone = f"090000000{ord(label) - ord('A') + 1}"  # "A" → 1, "B" → 2
        email = f"{label.lower()}@org-{label.lower()}.vn"
        await conn.execute(
            """INSERT INTO system_profiles (
                id, org_id, code, name, level, status,
                officer_name, officer_organization, officer_title,
                officer_phone, officer_email, officer_note,
                officer_assigned_at, officer_assigned_by,
                created_by, created_at, updated_at
            ) VALUES (
                $1, $2, $3, 'Profile', 1, 'drafted',
                'Nguyen Van A', $4, 'Manager',
                $5, $6, $7,
                now(), $8, $8, now(), now()
            )""",
            prof_id, org_id, f"HS-DUP-{label}", org_label, phone, email,
            f"note for {label}", user_id,
        )
    await conn.close()

    # Step 2: upgrade → 2 officers rows phải được tạo với data khác nhau
    result = _run_alembic(["upgrade", OFFICER_REFACTOR_REV], sync_url)
    assert result.returncode == 0, result.stderr

    conn = await asyncpg.connect(asyncpg_url)
    try:
        # Phải có đúng 2 officer rows
        officers = await conn.fetch(
            "SELECT * FROM officers ORDER BY created_at"
        )
        assert len(officers) == 2, (
            f"BLOCKER 2 v3 BUG: expected 2 officer rows (one per profile), "
            f"got {len(officers)}. Nondeterministic mapping có thể merge rows."
        )
        officer_ids = {o["id"] for o in officers}
        assert len(officer_ids) == 2, (
            f"BLOCKER 2 v3 BUG: officers phải có ID unique, got {officer_ids}"
        )

        # Verify profile → officer mapping
        row_a = await conn.fetchrow(
            "SELECT officer_id FROM system_profiles WHERE id = $1", profile_a
        )
        row_b = await conn.fetchrow(
            "SELECT officer_id FROM system_profiles WHERE id = $1", profile_b
        )
        assert row_a["officer_id"] is not None, "Profile A phải có officer_id"
        assert row_b["officer_id"] is not None, "Profile B phải có officer_id"
        assert row_a["officer_id"] != row_b["officer_id"], (
            f"BLOCKER 2 v3 BUG: 2 profiles cùng officer_name bị map về cùng "
            f"officer_id={row_a['officer_id']}. Mỗi profile phải có officer "
            f"riêng (officer_name là business data, không phải identity)."
        )

        # Verify data của mỗi officer khớp với profile tương ứng
        officer_a = await conn.fetchrow(
            "SELECT * FROM officers WHERE id = $1", row_a["officer_id"]
        )
        officer_b = await conn.fetchrow(
            "SELECT * FROM officers WHERE id = $1", row_b["officer_id"]
        )
        assert officer_a["organization"] == "Org A", (
            f"Profile A phải link officer Org A, got {officer_a['organization']}"
        )
        assert officer_a["phone"] == "0900000001", (
            f"Profile A phone: {officer_a['phone']}"
        )
        assert officer_a["email"] == "a@org-a.vn", (
            f"Profile A email: {officer_a['email']}"
        )
        assert officer_b["organization"] == "Org B", (
            f"Profile B phải link officer Org B, got {officer_b['organization']}"
        )
        assert officer_b["phone"] == "0900000002"
        assert officer_b["email"] == "b@org-b.vn"

        # Legacy columns đã drop
        cols = await _columns_of(conn, "system_profiles")
        for legacy_col in (
            "officer_name", "officer_organization", "officer_title",
            "officer_phone", "officer_email", "officer_note",
            "officer_assigned_at", "officer_assigned_by",
        ):
            assert legacy_col not in cols
    finally:
        await conn.close()

    # Step 3: downgrade → legacy data khôi phục đúng cho từng profile
    result = _run_alembic(["downgrade", "-1"], sync_url)
    assert result.returncode == 0, result.stderr

    conn = await asyncpg.connect(asyncpg_url)
    try:
        row_a = await conn.fetchrow(
            "SELECT officer_organization, officer_phone, officer_email, officer_note "
            "FROM system_profiles WHERE id = $1", profile_a,
        )
        row_b = await conn.fetchrow(
            "SELECT officer_organization, officer_phone, officer_email, officer_note "
            "FROM system_profiles WHERE id = $1", profile_b,
        )
        assert row_a["officer_organization"] == "Org A"
        assert row_a["officer_phone"] == "0900000001"
        assert row_a["officer_email"] == "a@org-a.vn"
        assert row_a["officer_note"] == "note for A"
        assert row_b["officer_organization"] == "Org B"
        assert row_b["officer_phone"] == "0900000002"
        assert row_b["officer_email"] == "b@org-b.vn"
        assert row_b["officer_note"] == "note for B"
    finally:
        await conn.close()
