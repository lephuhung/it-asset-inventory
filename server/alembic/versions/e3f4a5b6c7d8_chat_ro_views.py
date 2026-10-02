"""chat_ro role, schema and minimized inventory views

Task 3 của Chat Assistant P1. Tạo role read-only `inventory_chat_ro` + schema
`chat_ro_views` + 6 view tối giản (loại PII) cho chat assistant truy vấn inventory.

Ranh giới quyền (fail-closed):
- Role `inventory_chat_ro`: `LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS`; không là member role khác, không sở hữu object.
- **Chỉ** `GRANT SELECT` trên **6 view đã duyệt** (manifest đóng). Không grant bảng
  gốc / `users` / `llm_config` / `velociraptor_config` / `api_keys` / `audit_log` /
  `chat_*`. Không dùng `GRANT ... ON ALL TABLES`/`ALTER DEFAULT PRIVILEGES` (sẽ tự
  động mở quyền cho object tương lai — phá manifest đóng).
- Nhánh role đã tồn tại: siết thuộc tính, thu hồi membership + mọi quyền
  relation-level **và column-level** trên schema `public`, và **fail closed** nếu
  role còn sở hữu object (mọi catalog: relation/schema/database/function/type/…) hoặc
  thuộc tính đặc quyền.
- `search_path` đặt khi tạo connection **và** reset lại mỗi lần checkout ở engine
  (`app/db/session.py`).
- Catalog/function isolation **không** DB-enforced (PostgreSQL cấp PUBLIC đọc
  `pg_catalog`) — tuyến chính là validator SQL ở T9 (spec V3-4/R5).

EOL: `portal/lib/eol.ts` là nguồn tham chiếu (backend chưa có field). View suy ra
`eol_flag` từ `os_name` + `os_version`/`os_build`: họ OS đã hết hỗ trợ → TRUE; Windows
11 chỉ FALSE khi build nằm trong cửa sổ còn hỗ trợ, thiếu/không nhận diện build →
NULL (unknown), **không đoán**.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-02 15:45:00.000000
"""
from __future__ import annotations

from alembic import op
from app.core.config import settings

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

CHAT_RO_ROLE = "inventory_chat_ro"
CHAT_RO_SCHEMA = "chat_ro_views"
CHAT_RO_SEARCH_PATH = f"{CHAT_RO_SCHEMA}, pg_catalog"


# ── SQL literal helpers ──────────────────────────────────────────────────────

def _pg_literal(value: str) -> str:
    """Sinh literal an toàn, khớp semantics `quote_literal` của PostgreSQL.

    Chuỗi chứa backslash → dùng `E'...'` (backslash + nháy đơn nhân đôi); ngược lại
    dùng `'...'` (chỉ nháy đơn nhân đôi). Nhờ vậy password chứa `$`, `$$`, nháy đơn,
    backslash hay dấu hai chấm đều không phá câu lệnh (không cần dollar-quote bao ngoài).
    """
    if "\\" in value:
        escaped = value.replace("\\", "\\\\").replace("'", "''")
        return "E'" + escaped + "'"
    return "'" + value.replace("'", "''") + "'"


def _dollar_tag(*values: str) -> str:
    """Chọn tag dollar-quote không xuất hiện trong bất kỳ `values` nào."""
    i = 0
    while True:
        tag = f"$chatro{i}$"
        if all(tag not in v for v in values):
            return tag
        i += 1


def role_ddl(password: str) -> str:
    """CREATE/ALTER role idempotent, siết thuộc tính, KHÔNG nhúng password thô.

    Password đi qua `_pg_literal` (literal chuẩn) — không dollar-quote bao ngoài nên
    `$$` trong password vô hại.
    """
    literal = _pg_literal(password)
    tag = _dollar_tag(literal)
    attrs = "LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
    return (
        f"DO {tag} BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{CHAT_RO_ROLE}') THEN "
        f"CREATE ROLE {CHAT_RO_ROLE} WITH {attrs} PASSWORD {literal}; "
        f"ELSE ALTER ROLE {CHAT_RO_ROLE} WITH {attrs} PASSWORD {literal}; "
        f"END IF; END {tag};"
    )


# ── Role hardening (nhánh role đã tồn tại) ───────────────────────────────────

# DO block cố định (không nhúng input) → tag `$chh$` an toàn.
_HARDEN_TAG = "$chh$"

# 1) Thu hồi mọi membership — NOINHERIT không tước quyền SET ROLE.
MEMBERSHIP_REVOKE_DDL = f"""DO {_HARDEN_TAG}
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT parent.rolname AS parent_role
    FROM pg_auth_members m
    JOIN pg_roles parent ON parent.oid = m.roleid
    JOIN pg_roles member ON member.oid = m.member
    WHERE member.rolname = '{CHAT_RO_ROLE}'
  LOOP
    EXECUTE format('REVOKE %I FROM {CHAT_RO_ROLE}', r.parent_role);
  END LOOP;
END {_HARDEN_TAG}"""

# 2) Thu hồi mọi quyền **relation-level** trên schema `public` (bảng/view/sequence).
RELATION_REVOKE_DDL = f"""DO {_HARDEN_TAG}
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT c.relname, c.relkind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r','v','m','p','S','f')
  LOOP
    IF r.relkind = 'S' THEN
      EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM {CHAT_RO_ROLE}', r.relname);
    ELSE
      EXECUTE format('REVOKE ALL ON TABLE public.%I FROM {CHAT_RO_ROLE}', r.relname);
    END IF;
  END LOOP;
END {_HARDEN_TAG}"""

# 3) Thu hồi mọi quyền **column-level** (`GRANT SELECT(email)` không bị `REVOKE ALL
# ON TABLE` gỡ). Quét `pg_attribute.attacl` + `aclexplode`, gỡ đúng privilege/column.
# Áp cho cả `public` lẫn `chat_ro_views` (phòng object cũ ngoài manifest).
COLUMN_REVOKE_DDL = f"""DO {_HARDEN_TAG}
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT n.nspname AS sch, c.relname AS rel, a.attname AS col, x.privilege_type AS priv
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_roles ro ON ro.rolname = '{CHAT_RO_ROLE}'
    CROSS JOIN LATERAL aclexplode(a.attacl) AS x
    WHERE n.nspname IN ('public', '{CHAT_RO_SCHEMA}')
      AND a.attacl IS NOT NULL
      AND x.grantee = ro.oid
  LOOP
    EXECUTE format('REVOKE %s (%I) ON TABLE %I.%I FROM {CHAT_RO_ROLE}',
                   r.priv, r.col, r.sch, r.rel);
  END LOOP;
END {_HARDEN_TAG}"""

# 4) Fail closed nếu role còn SỞ HỮU object thuộc bất kỳ catalog nào (chủ sở hữu có
# quyền DROP/ALTER → leo thang). Không chỉ `pg_class`.
OWNERSHIP_CHECK_DDL = f"""DO {_HARDEN_TAG}
DECLARE offenders integer;
BEGIN
  SELECT count(*) INTO offenders FROM (
    SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_type t JOIN pg_roles r ON r.oid = t.typowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_language l JOIN pg_roles r ON r.oid = l.lanowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_collation co JOIN pg_roles r ON r.oid = co.collowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_conversion cv JOIN pg_roles r ON r.oid = cv.conowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_operator o JOIN pg_roles r ON r.oid = o.oprowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_opclass oc JOIN pg_roles r ON r.oid = oc.opcowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_opfamily of2 JOIN pg_roles r ON r.oid = of2.opfowner WHERE r.rolname = '{CHAT_RO_ROLE}'
    UNION ALL
    SELECT 1 FROM pg_extension e JOIN pg_roles r ON r.oid = e.extowner WHERE r.rolname = '{CHAT_RO_ROLE}'
  ) AS owned;
  IF offenders > 0 THEN
    RAISE EXCEPTION 'chat_ro role {CHAT_RO_ROLE} owns % object(s); refusing to continue', offenders;
  END IF;
END {_HARDEN_TAG}"""

# 5) Fail closed nếu role còn thuộc tính đặc quyền.
ATTRS_CHECK_DDL = f"""DO {_HARDEN_TAG}
DECLARE r RECORD;
BEGIN
  SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
  INTO r FROM pg_roles WHERE rolname = '{CHAT_RO_ROLE}';
  IF r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls THEN
    RAISE EXCEPTION 'chat_ro role {CHAT_RO_ROLE} retains elevated attributes';
  END IF;
END {_HARDEN_TAG}"""

# 6) Thu hồi quyền trên schema `public` (least privilege).
SCHEMA_REVOKE_DDL = f"REVOKE ALL ON SCHEMA public FROM {CHAT_RO_ROLE}"

ROLE_HARDEN_DDL: list[str] = [
    MEMBERSHIP_REVOKE_DDL,
    RELATION_REVOKE_DDL,
    COLUMN_REVOKE_DDL,
    OWNERSHIP_CHECK_DDL,
    ATTRS_CHECK_DDL,
    SCHEMA_REVOKE_DDL,
]


# ── View projections ─────────────────────────────────────────────────────────

# Build (Windows) — ưu tiên thành phần thứ 3 của `os_version` ("10.0.22631" → 22631),
# fallback `os_build` khi **toàn bộ** là 1–5 chữ số. Validate TRƯỚC khi cast:
#   - `os_build` phi số/nhiều thành phần ("26100.1") → NULL (không nối thành 261001);
#   - giá trị quá dài ("9999999999") → NULL (không tràn `int`);
#   - thiếu dữ liệu → NULL (không đoán).
# Hàm nhận `alias` để test gọi thẳng trên `public.machine_current`.
def build_expr(alias: str = "mc") -> str:
    version_component = f"split_part(COALESCE({alias}.os_version, ''), '.', 3)"
    build_col = f"COALESCE({alias}.os_build, '')"
    return (
        "COALESCE("
        f"CASE WHEN {version_component} ~ '^[0-9]{{1,5}}$' THEN {version_component}::int END, "
        f"CASE WHEN {build_col} ~ '^[0-9]{{1,5}}$' THEN {build_col}::int END"
        ")"
    )


_BUILD_EXPR = build_expr("mc")

# Mốc build Windows 11 + ngày EOL tham chiếu (đồng bộ `portal/lib/eol.ts`). Export để
# test tính kỳ vọng từ chính hằng số này → không phụ thuộc ngày chạy.
WIN11_21H2_BUILD = 22000
WIN11_22H2_BUILD = 22621
WIN11_23H2_BUILD = 22631
WIN11_24H2_BUILD = 26100
WIN11_24H2_EOL_DATE = "2026-10-13"
WIN11_NEWER_EOL_DATE = "2027-10-12"

# EOL heuristic — cùng tập họ OS + cửa sổ hỗ trợ với `portal/lib/eol.ts`.
# TRUE = đã hết hỗ trợ, FALSE = còn hỗ trợ, NULL = không đủ dữ liệu (không đoán).
# Windows 11 phụ thuộc build: 21H2/22H2/23H2 đã hết hạn; 24H2 (26100) và mới hơn theo
# ngày EOL tham chiếu; thiếu/không nhận diện build → NULL.
_EOL_CASE = f"""CASE
        WHEN mc.os_name IS NULL THEN NULL
        WHEN mc.os_name ILIKE '%Windows 11%' THEN
            CASE
                WHEN {_BUILD_EXPR} IS NULL THEN NULL
                WHEN {_BUILD_EXPR} IN ({WIN11_21H2_BUILD}, {WIN11_22H2_BUILD}, {WIN11_23H2_BUILD}) THEN TRUE
                WHEN {_BUILD_EXPR} = {WIN11_24H2_BUILD} THEN (DATE '{WIN11_24H2_EOL_DATE}' < CURRENT_DATE)
                WHEN {_BUILD_EXPR} > {WIN11_24H2_BUILD} THEN (DATE '{WIN11_NEWER_EOL_DATE}' < CURRENT_DATE)
                ELSE NULL
            END
        WHEN mc.os_name ILIKE '%Windows 10%' THEN TRUE
        WHEN mc.os_name ILIKE '%Windows 8%'  THEN TRUE
        WHEN mc.os_name ILIKE '%Windows 7%'  THEN TRUE
        WHEN mc.os_name ILIKE '%Windows XP%' THEN TRUE
        WHEN mc.os_name ILIKE '%Windows Server 2008%' THEN TRUE
        WHEN mc.os_name ILIKE '%Windows Server 2012%' THEN TRUE
        WHEN mc.os_name ILIKE '%Windows Server 2016%' THEN FALSE
        WHEN mc.os_name ILIKE '%Windows Server 2019%' THEN FALSE
        WHEN mc.os_name ILIKE '%Windows Server 2022%' THEN FALSE
        WHEN mc.os_name ILIKE '%Windows Server 2025%' THEN FALSE
        ELSE NULL
    END"""

# Dung lượng đĩa — payload thật dùng `size_bytes`/`size` (bytes) hoặc legacy `size_gb`.
# NULL khi không có trường nào được biết.
_DISK_GB_BYTES = (
    "(d->>'size_bytes')::numeric / 1073741824"
)
_DISK_CAPACITY = (
    "COALESCE("
    f"{_DISK_GB_BYTES}, "
    "(d->>'size')::numeric / 1073741824, "
    "(d->>'size_gb')::numeric"
    ")"
)

_VIEWS: dict[str, str] = {
    "v_chat_machines": f"""
        CREATE OR REPLACE VIEW {CHAT_RO_SCHEMA}.v_chat_machines AS
        SELECT
            m.id           AS id,
            m.hostname     AS hostname,
            o.name         AS org_name,
            mc.os_name     AS os_name,
            mc.os_version  AS os_version,
            m.status       AS status,
            m.last_seen_at AS last_seen,
            {_EOL_CASE} AS eol_flag
        FROM public.machines m
        LEFT JOIN public.machine_current mc ON mc.machine_id = m.id
        LEFT JOIN public.organizations o   ON o.id = m.org_id
    """,
    "v_chat_machine_detail": f"""
        CREATE OR REPLACE VIEW {CHAT_RO_SCHEMA}.v_chat_machine_detail AS
        SELECT
            m.id           AS id,
            m.hostname     AS hostname,
            o.name         AS org_name,
            mc.os_name     AS os_name,
            mc.os_version  AS os_version,
            COALESCE(mc.cpu->>'model', mc.cpu->>'brand') AS cpu,
            CASE WHEN mc.ram_gb IS NULL THEN NULL
                 ELSE round(mc.ram_gb * 1024)::integer END AS ram_mb,
            CASE WHEN jsonb_typeof(mc.disks) = 'array' THEN (
                SELECT sum(cap)::integer FROM (
                    SELECT {_DISK_CAPACITY} AS cap
                    FROM jsonb_array_elements(mc.disks) AS d
                ) AS disks_x
            ) ELSE NULL END AS disk_gb,
            m.status       AS status,
            m.last_seen_at AS last_seen
        FROM public.machines m
        LEFT JOIN public.machine_current mc ON mc.machine_id = m.id
        LEFT JOIN public.organizations o   ON o.id = m.org_id
    """,
    # Tái dùng eol_flag từ v_chat_machines (không lặp heuristic EOL). Join theo
    # machine id (unique) — KHÔNG join theo org_name vì tên tổ chức không unique.
    # GROUP BY o.id để hai org trùng tên vẫn tách dòng.
    "v_chat_org_stats": f"""
        CREATE OR REPLACE VIEW {CHAT_RO_SCHEMA}.v_chat_org_stats AS
        SELECT
            o.name AS org_name,
            count(m.id)                                      AS machine_count,
            count(m.id) FILTER (WHERE m.status = 'online')   AS online_count,
            count(vm.id) FILTER (WHERE vm.eol_flag IS TRUE)  AS eol_count
        FROM public.organizations o
        LEFT JOIN public.machines m ON m.org_id = o.id
        LEFT JOIN {CHAT_RO_SCHEMA}.v_chat_machines vm ON vm.id = m.id
        GROUP BY o.id, o.name
    """,
    "v_chat_software": f"""
        CREATE OR REPLACE VIEW {CHAT_RO_SCHEMA}.v_chat_software AS
        SELECT
            ms.machine_id AS machine_id,
            m.hostname    AS hostname,
            ms.name       AS software_name,
            ms.version    AS version,
            ms.install_date AS install_date
        FROM public.machine_software ms
        JOIN public.machines m ON m.id = ms.machine_id
    """,
    "v_chat_hardware": f"""
        CREATE OR REPLACE VIEW {CHAT_RO_SCHEMA}.v_chat_hardware AS
        SELECT mc.machine_id, m.hostname, 'cpu'::text AS component,
               COALESCE(mc.cpu->>'model', mc.cpu->>'brand') AS value
        FROM public.machine_current mc
        JOIN public.machines m ON m.id = mc.machine_id
        UNION ALL
        SELECT mc.machine_id, m.hostname, 'ram_gb'::text, mc.ram_gb::text
        FROM public.machine_current mc
        JOIN public.machines m ON m.id = mc.machine_id
        WHERE mc.ram_gb IS NOT NULL
        UNION ALL
        SELECT mc.machine_id, m.hostname, 'gpu'::text,
               COALESCE(mc.gpu->>'model', mc.gpu->>'name')
        FROM public.machine_current mc
        JOIN public.machines m ON m.id = mc.machine_id
        WHERE mc.gpu IS NOT NULL
        UNION ALL
        SELECT mc.machine_id, m.hostname, 'mainboard'::text,
               COALESCE(mc.mainboard->>'model', mc.mainboard->>'product')
        FROM public.machine_current mc
        JOIN public.machines m ON m.id = mc.machine_id
        WHERE mc.mainboard IS NOT NULL
        UNION ALL
        SELECT mc.machine_id, m.hostname, 'disk'::text,
               COALESCE(d->>'model', d->>'name', 'disk') || ' '
                   || COALESCE(
                          round((d->>'size_bytes')::numeric / 1073741824)::text,
                          round((d->>'size')::numeric / 1073741824)::text,
                          d->>'size_gb',
                          '?'
                      ) || 'GB'
        FROM public.machine_current mc
        JOIN public.machines m ON m.id = mc.machine_id
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(mc.disks) = 'array' THEN mc.disks ELSE '[]'::jsonb END
        ) AS d
    """,
    # Nguồn alert: DfirAlert (AlertEvent thiếu cột `status`). `resolved` → status.
    # `category`: DfirAlert không có cột category → gán nhãn nguồn 'dfir'.
    "v_chat_alerts": f"""
        CREATE OR REPLACE VIEW {CHAT_RO_SCHEMA}.v_chat_alerts AS
        SELECT
            da.id         AS id,
            da.machine_id AS machine_id,
            m.hostname    AS hostname,
            da.severity   AS severity,
            'dfir'::text  AS category,
            da.created_at AS created_at,
            CASE WHEN da.resolved THEN 'resolved' ELSE 'open' END AS status
        FROM public.dfir_alerts da
        LEFT JOIN public.machines m ON m.id = da.machine_id
    """,
}


SCHEMA_DDL = f"CREATE SCHEMA IF NOT EXISTS {CHAT_RO_SCHEMA}"

VIEW_DDL: list[str] = list(_VIEWS.values())

# Manifest đóng: chỉ 6 GRANT SELECT tường minh; gỡ mọi grant/default-privilege cũ.
GRANT_DDL: list[str] = [
    f"REVOKE ALL ON SCHEMA {CHAT_RO_SCHEMA} FROM PUBLIC",
    f"REVOKE ALL ON ALL TABLES IN SCHEMA {CHAT_RO_SCHEMA} FROM {CHAT_RO_ROLE}",
    (
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {CHAT_RO_SCHEMA} "
        f"REVOKE SELECT ON TABLES FROM {CHAT_RO_ROLE}"
    ),
    f"GRANT USAGE ON SCHEMA {CHAT_RO_SCHEMA} TO {CHAT_RO_ROLE}",
    *[f"GRANT SELECT ON {CHAT_RO_SCHEMA}.{name} TO {CHAT_RO_ROLE}" for name in _VIEWS],
]

DROP_DDL: list[str] = [f"DROP SCHEMA IF EXISTS {CHAT_RO_SCHEMA} CASCADE"]


def upgrade() -> None:
    # exec_driver_sql: tránh `text()` diễn giải dấu `:` trong literal password.
    bind = op.get_bind()
    bind.exec_driver_sql(role_ddl(settings.chat_ro_password))
    for stmt in ROLE_HARDEN_DDL:
        bind.exec_driver_sql(stmt)
    bind.exec_driver_sql(SCHEMA_DDL)
    for stmt in VIEW_DDL:
        bind.exec_driver_sql(stmt)
    for stmt in GRANT_DDL:
        bind.exec_driver_sql(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    for stmt in DROP_DDL:
        bind.exec_driver_sql(stmt)
    bind.exec_driver_sql(f"DROP ROLE IF EXISTS {CHAT_RO_ROLE}")
