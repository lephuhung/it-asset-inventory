"""chat_ro role, schema and minimized inventory views

Task 3 của Chat Assistant P1. Tạo role read-only `inventory_chat_ro` + schema
`chat_ro_views` + 6 view tối giản (loại PII) cho chat assistant truy vấn inventory.

- Role: `inventory_chat_ro`, `LOGIN NOINHERIT`, không là member role khác, không
  sở hữu object. Chỉ có `USAGE` trên schema `chat_ro_views` + `SELECT` trên các view
  đã duyệt; **không** grant bảng gốc / `users` / `llm_config` / `api_client.yaml` /
  `api_keys` / `audit_log` / `chat_*`.
- `search_path` do engine đặt (`chat_ro_views, pg_catalog`).
- Catalog/function isolation **không** DB-enforced (PostgreSQL cấp PUBLIC đọc
  `pg_catalog`) — tuyến chính là validator SQL ở T9 (spec V3-4/R5).

EOL: `portal/lib/eol.ts` là nguồn tham chiếu (backend chưa có field). View suy ra
`eol_flag` từ `os_name` theo họ OS đã biết hết hỗ trợ; thiếu dữ liệu → NULL (unknown),
**không đoán**.

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

# EOL heuristic — cùng tập họ OS với `portal/lib/eol.ts`. TRUE = đã hết hỗ trợ,
# FALSE = còn hỗ trợ, NULL = không đủ dữ liệu. Thứ tự CASE quan trọng: "Windows 11"
# phải đứng trước "Windows 1" nếu dùng prefix ngắn; ở đây dùng chuỗi đầy đủ.
_EOL_CASE = """CASE
        WHEN mc.os_name IS NULL THEN NULL
        WHEN mc.os_name ILIKE '%Windows 11%' THEN FALSE
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
            COALESCE(mc.cpu->>'model', mc.cpu->>'brand', mc.cpu->>'name') AS cpu,
            CASE WHEN mc.ram_gb IS NULL THEN NULL
                 ELSE round(mc.ram_gb * 1024)::integer END AS ram_mb,
            CASE WHEN jsonb_typeof(mc.disks) = 'array' THEN (
                SELECT sum((d->>'capacity_gb')::numeric)::integer
                FROM jsonb_array_elements(mc.disks) AS d
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
               COALESCE(mc.cpu->>'model', mc.cpu->>'brand', mc.cpu->>'name') AS value
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
                   || COALESCE(d->>'capacity_gb', '?') || 'GB'
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

# Tạo/ALTER role idempotent. Password được escape ở Python (không log).
def role_ddl(password: str) -> str:
    literal = password.replace("'", "''")
    return (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{CHAT_RO_ROLE}') THEN "
        f"  CREATE ROLE {CHAT_RO_ROLE} LOGIN PASSWORD '{literal}' NOINHERIT; "
        f"ELSE ALTER ROLE {CHAT_RO_ROLE} LOGIN PASSWORD '{literal}' NOINHERIT; "
        "END IF; END $$;"
    )


SCHEMA_DDL = f"CREATE SCHEMA IF NOT EXISTS {CHAT_RO_SCHEMA}"

VIEW_DDL: list[str] = list(_VIEWS.values())

GRANT_DDL: list[str] = [
    f"REVOKE ALL ON SCHEMA {CHAT_RO_SCHEMA} FROM PUBLIC",
    f"GRANT USAGE ON SCHEMA {CHAT_RO_SCHEMA} TO {CHAT_RO_ROLE}",
    f"GRANT SELECT ON ALL TABLES IN SCHEMA {CHAT_RO_SCHEMA} TO {CHAT_RO_ROLE}",
    (
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {CHAT_RO_SCHEMA} "
        f"GRANT SELECT ON TABLES TO {CHAT_RO_ROLE}"
    ),
]

DROP_DDL: list[str] = [f"DROP SCHEMA IF EXISTS {CHAT_RO_SCHEMA} CASCADE"]


def upgrade() -> None:
    op.execute(role_ddl(settings.chat_ro_password))
    for stmt in [SCHEMA_DDL, *VIEW_DDL, *GRANT_DDL]:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROP_DDL:
        op.execute(stmt)
    op.execute(f"DROP ROLE IF EXISTS {CHAT_RO_ROLE}")
