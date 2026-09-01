# Alert Engine Redesign — Design Spec

| Field | Value |
|---|---|
| Date | 2026-09-01 |
| Status | Design (awaiting user review) |
| Scope | Redesign alert subsystem: tách **templates** + **scope** + **recipients** thành 3 trục rõ ràng. Hỗ trợ **backend notification (in-app bell)** + **Telegram** (không email, không Zalo). |
| Path classification | Architectural |
| Author | Brainstorming session với user |

---

## 1. Bối cảnh & vấn đề

Hệ thống IT Asset Inventory hiện có alert system rải rác:

### Những gì đang hoạt động (một phần)
- `portal/app/(portal)/notifications-alerts/page.tsx` — form tạo **AlertRule** với `rule_type` (machine_new, machine_lost, software_new, hardware_changed), `channels` checkbox (email / telegram / zalo), `notify_targets` (textarea nhập email).
- `server/app/services/monitor.py` — job quét 60s/lần: phát hiện máy mới / máy mất liên lạc → tạo `AlertEvent` + gọi `_deliver_alert()`.
- `server/app/services/notifications.py` — `create_notification()` tạo row `notifications` + push Redis pub/sub + best-effort gửi Telegram qua `user.telegram_chat_id` (qua `telegram_runtime.get_bot_config`).
- `server/app/api/routes/telegram_bot_admin.py` — Super Admin CRUD `telegram_bot_config` (token AES-GCM, webhook secret, enable/disable).
- `server/app/api/routes/notifications.py:me_router` — user link/unlink Telegram cá nhân (`/start <token>` qua webhook).

### Những gì sai / thiếu (root causes của bug bạn báo cáo)

1. **`monitor._deliver_alert()` không tích hợp `telegram_runtime`.** Dòng `monitor.py:172`:
   ```python
   if "telegram" in channels and settings.telegram_bot_token and settings.telegram_chat_id:
   ```
   → Đọc token + chat_id từ **env** thay vì DB. Nếu Super Admin set token qua portal (`telegram_bot_config`) mà `.env` không có `TELEGRAM_CHAT_ID`, **rule Telegram sẽ không bao giờ gửi được**.

2. **Form `notify_targets` chỉ nhập email** (`page.tsx:300-313`):
   ```tsx
   <Input value={targets} placeholder="it@example.gov.vn, admin@example.gov.vn" />
   <Field hint="Email … Telegram/Zalo dùng cấu hình bot ở server (.env)" />
   ```
   → Org Admin muốn nhận qua Telegram phải tự điền email, không thể chọn user đã link Telegram. UX vỡ khi không có SMTP server.

3. **Không có cấu hình "Org Admin của scope" auto-recipient.** Hiện rule với `org_id=X` chỉ lọc máy thuộc X; ai nhận thì admin phải gõ email tay. Không tự động gửi Org Admin của X.

4. **Không có opt-out per template.** Một Org Admin muốn mute "Máy mất liên lạc" nhưng vẫn muốn nhận "Máy mới" — không có cách.

5. **Template nội dung bị hardcode trong `monitor.py`.** Title/body alert do code Python dựng → Super Admin không sửa được (ví dụ muốn đổi `[IT Asset]` → `[Hệ thống ATSK]`).

6. **Trang Super Admin config bot đang ở URL sai:** `portal/app/(portal)/me/telegram/page.tsx` (URL cá nhân) thay vì `/admin/telegram-bot`. UI đúng, route sai.

### Mục tiêu redesign

Tách alert system thành **3 trục trực giao** mà bạn đã chốt:

| Trục | Vai trò | Ai quản lý |
|---|---|---|
| **Template** | Nội dung (title/body) + opt-out controls + severity mặc định | Super Admin |
| **Scope** | Máy/tổ chức nào kích hoạt | Org Admin / Super Admin |
| **Recipients** | Ai nhận (mặc định: Org Admin của scope + Super Admin; Org Admin có thể tự mute) | Org Admin (mute), Super Admin (luôn nhận) |

Chỉ hỗ trợ **2 delivery channel**: backend notification (in-app bell, đã có) + Telegram (qua bot đã có). Không email, không Zalo.

---

## 2. Goals & Non-goals

### 2.1. Goals

- **G1.** Tách rõ 3 trục: `alert_templates` (nội dung), `alert_rules` (scope + binding với template), `user_notification_prefs` (opt-out).
- **G2.** Pipeline alert thống nhất: `monitor / DFIR / tương lai` → `alert_engine.trigger_alert(code, org_id, context)` → render template → resolve recipients → fan-out notification + Telegram.
- **G3.** Default recipients = Org Admin (role IN `org_admin`) của scope + Super Admin (`super_admin`, `admin_global`). Super Admin **luôn** nhận, không mute được. Org Admin mute được per template, **opt-out controls do template định nghĩa** (không fix cứng).
- **G4.** `monitor._deliver_alert()` bị xoá; thay bằng `alert_engine.trigger_alert()`.
- **G5.** Di chuyển `portal/app/(portal)/me/telegram/page.tsx` → `portal/app/(portal)/admin/telegram-bot/page.tsx`. Logic file giữ nguyên 100%, chỉ đổi path.
- **G6.** 7 template seed sẵn cho toàn bộ trigger points hiện có + 2 chỗ sẽ bật ở Phase 3.
- **G7.** UI `/notifications-alerts` chia 3 tab: **Subscriptions / Templates / History**. Super Admin thấy cả 3; Org Admin chỉ thấy Subscriptions + History.

### 2.2. Non-goals (out of scope cho spec này)

- **N1.** Không hỗ trợ **email channel** (đã xác nhận với user). Field `channels` bị xoá khỏi `alert_rules`; delivery cố định = in-app + Telegram (nếu user link).
- **N2.** Không hỗ trợ **Zalo / Slack / Webhook** channel.
- **N3.** Không migrate data từ `alert_rules` / `alert_events` cũ. Approach = clean replace (xác nhận với user). Data cũ mất.
- **N4.** Không cho phép user tự tạo template — chỉ Super Admin edit trên bảng `alert_templates`.
- **N5.** Không hỗ trợ template versioning / A-B testing.
- **N6.** Không multi-language template (chỉ tiếng Việt).
- **N7.** Không đổi `Notification` / `NotificationDelivery` schema hiện có (tận dụng).

---

## 3. Quyết định kiến trúc (decisions log)

| # | Câu hỏi | Quyết định | Lý do |
|---|---|---|---|
| D1 | Templates là gì? | **A: Template nội dung** — title_template/body_template có biến `{var}` được whitelist qua `allowed_vars` | User xác nhận |
| D2 | Scope options? | **3 mode**: `org_only` (1 org), `org_tree` (org + descendants), `system` (toàn hệ thống, Super Admin only) | Org Admin cấp Sở cần bao phòng ban con |
| D3 | Recipients mặc định? | **Org Admin của scope + Super Admin**. Org Admin mute được qua `user_notification_prefs`; Super Admin không mute được | User xác nhận |
| D4 | Opt-out controls? | **Per-template**: `opt_out_controls JSONB = ["template"] / ["severity"] / ["template","severity"] / []`. Template author (Super Admin) quyết định mute knobs nào hợp lý với loại alert đó | User yêu cầu "không fix cứng" |
| D5 | Approach? | **A: Clean replace** — drop `alert_rules` + `alert_events`, recreate với schema mới, KHÔNG migrate data cũ | User xác nhận |
| D6 | Templates seed ban đầu? | **7 templates**: machine_new, machine_lost, machine_offline, investigation_completed, investigation_failed, software_new, hardware_changed | User xác nhận "tất cả" |
| D7 | Đặt tên bảng mới? | **Giữ tên cũ** `alert_rules` + `alert_events` (đổi schema bên trong, không rename) | User xác nhận |
| D8 | `/me/telegram` xử lý? | **Move** sang `/admin/telegram-bot`. File code giữ nguyên 100%, chỉ `git mv` | User xác nhận |

---

## 4. Kiến trúc tổng thể

### 4.1. Sơ đồ luồng

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  monitor.py      │    │  DFIR services   │    │  Future triggers │
│  (60s scan)      │    │  (investigation) │    │  (software etc)  │
└────────┬─────────┘    └─────────┬────────┘    └─────────┬────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  ▼
                    ┌──────────────────────────┐
                    │  alert_engine.py         │
                    │  trigger_alert(code,     │
                    │    org_id, context)      │
                    └────────────┬─────────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
        ┌──────────────┐ ┌──────────────┐ ┌─────────────────┐
        │ Load template│ │ Find subs    │ │ Render context  │
        │ by code      │ │ match scope  │ │ via allowed_vars│
        └──────┬───────┘ └──────┬───────┘ └────────┬────────┘
               │                │                  │
               └────────────────┼──────────────────┘
                                ▼
                  ┌──────────────────────────┐
                  │ Resolve recipients       │
                  │  • Org Admin of scope    │
                  │  • Super Admin (always)  │
                  │  • Apply user prefs      │
                  │    (Org Admins only)     │
                  └────────────┬─────────────┘
                               ▼
                  ┌──────────────────────────┐
                  │ Fan-out                  │
                  │  • create_notification() │  ← backend bell
                  │  • deliver_telegram()    │  ← if user linked
                  │  • NotificationDelivery  │  ← audit per channel
                  └──────────────────────────┘
```

### 4.2. Schema mới

```sql
-- (1) Alert templates — Super Admin manages content + opt-out controls
CREATE TABLE alert_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code VARCHAR(64) UNIQUE NOT NULL,
    -- "machine_new", "machine_lost", "machine_offline",
    -- "investigation_completed", "investigation_failed",
    -- "software_new", "hardware_changed"
  name VARCHAR(255) NOT NULL,
  description TEXT,
  category VARCHAR(32) NOT NULL,
    -- "machine" | "investigation" | "security" | "system"
  default_severity VARCHAR(16) DEFAULT 'info'
    CHECK (default_severity IN ('info','success','warning','error','critical')),
  title_template TEXT NOT NULL,
    -- VD: "[{org_name}] Máy mới: {hostname}"
  body_template TEXT,
    -- multi-line; cho phép biến whitelisted trong allowed_vars
  opt_out_controls JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- ["template"] | ["severity"] | ["template","severity"] | []
    -- (validate ở app layer: chỉ chấp nhận 2 giá trị này)
  allowed_vars JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- ["hostname","ip","org_name","enrolled_at","os","machine_id",...]
    -- whitelist biến dùng trong title_template/body_template
  default_config JSONB,
    -- {"threshold_days": 7} — gợi ý mặc định cho subscription
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_by UUID REFERENCES users(id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- (2) User notification preferences — opt-out per (user, template)
CREATE TABLE user_notification_prefs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  template_code VARCHAR(64) NOT NULL REFERENCES alert_templates(code)
    ON UPDATE CASCADE,
  muted BOOLEAN NOT NULL DEFAULT FALSE,
    -- chỉ ý nghĩa nếu template.opt_out_controls chứa "template"
  min_severity VARCHAR(16)
    CHECK (min_severity IN ('info','success','warning','error','critical')),
    -- chỉ ý nghĩa nếu template.opt_out_controls chứa "severity"
    -- NULL = nhận tất cả severity của template này
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, template_code)
);
CREATE INDEX ix_user_notification_prefs_user ON user_notification_prefs(user_id);

-- (3) alert_rules — DROP cũ, RECREATE với schema mới
DROP TABLE alert_events;
DROP TABLE alert_rules;

CREATE TABLE alert_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
    -- VD: "Org Admin nhận khi máy mới enroll tại Sở Công an"
  template_code VARCHAR(64) NOT NULL REFERENCES alert_templates(code)
    ON UPDATE CASCADE,
  org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    -- NULL chỉ khi scope_mode = 'system'
  scope_mode VARCHAR(32) NOT NULL DEFAULT 'org_only'
    CHECK (scope_mode IN ('org_only','org_tree','system')),
  recipient_mode VARCHAR(32) NOT NULL DEFAULT 'org_admins_and_super'
    -- future-proof: nếu sau này muốn thêm 'manual_users' / 'super_only'
    -- hiện tại chỉ chấp nhận 'org_admins_and_super'
    CHECK (recipient_mode IN ('org_admins_and_super')),
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- per-subscription override default_config (VD threshold_days = 3)
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_alert_rules_org ON alert_rules(org_id);
CREATE INDEX ix_alert_rules_template ON alert_rules(template_code);

-- (4) alert_events — DROP cũ, RECREATE
CREATE TABLE alert_events (
  id BIGSERIAL PRIMARY KEY,
  rule_id UUID NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
  template_code VARCHAR(64) NOT NULL,
    -- snapshot tại thời điểm trigger, không FK (template có thể bị xoá)
  machine_id UUID REFERENCES machines(id) ON DELETE SET NULL,
  org_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    -- snapshot scope org tại thời điểm trigger
  fingerprint VARCHAR(128) NOT NULL,
    -- sha256(rule_id + machine_id + template_code + YYYY-MM-DD) — chống trùng
  severity VARCHAR(16) NOT NULL,
    -- severity thực tế đã render (có thể khác default nếu sau này có override)
  title TEXT NOT NULL,
    -- title đã render — lưu lại để hiển thị history không cần re-render
  body TEXT,
    -- body đã render
  context JSONB,
    -- context đã dùng để render — debug khi user báo nội dung lỗi
  recipient_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- array UUID user_id đã nhận (kết quả sau khi apply prefs)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(rule_id, machine_id, fingerprint)
);
CREATE INDEX ix_alert_events_created ON alert_events(created_at DESC);
CREATE INDEX ix_alert_events_org ON alert_events(org_id);
```

### 4.3. Service layer

```python
# app/services/alert_engine.py

ALLOWED_OPT_OUT_CONTROLS = {"template", "severity"}
SEVERITY_RANK = {"info": 0, "success": 1, "warning": 2, "error": 3, "critical": 4}

class AlertEngine:
    """Singleton — pipeline render → scope → recipients → notify."""

    async def trigger_alert(
        self,
        db: AsyncSession,
        *,
        template_code: str,
        org_id: UUID | None,
        machine_id: UUID | None = None,
        context: dict | None = None,
    ) -> list[AlertEvent]:
        """Điểm vào duy nhất cho mọi trigger (monitor, DFIR, future).

        Trả về list AlertEvent đã tạo (1 / subscription match).
        """
        template = await self._load_template(db, template_code)
        if not template or not template.enabled:
            return []

        ctx = dict(context or {})
        ctx.setdefault("org_id", str(org_id) if org_id else None)
        if org_id:
            ctx.setdefault("org_name", await self._org_name(db, org_id))
        if machine_id:
            machine = await self._machine_snapshot(db, machine_id)
            ctx.update(machine)  # hostname, ip, os, enrolled_at, last_seen_at

        title = render_template(template.title_template, template.allowed_vars, ctx)
        body = render_template(template.body_template or "", template.allowed_vars, ctx)

        subs = await self._find_subscriptions(db, template_code, org_id)
        events: list[AlertEvent] = []
        for sub in subs:
            if not sub.enabled:
                continue
            recipients = await self._resolve_recipients(db, sub, template)
            if not recipients:
                continue
            fingerprint = self._fingerprint(sub.id, machine_id, template_code, ctx)
            event = await self._create_event(
                db, sub, template, machine_id, org_id, fingerprint,
                title, body, ctx, recipients,
            )
            await self._deliver(db, event, recipients)
            events.append(event)
        await db.commit()
        return events

    async def _resolve_recipients(
        self, db, sub: AlertRule, template: AlertTemplate,
    ) -> list[User]:
        """Resolve user nhận cho 1 subscription.

        - org_admins: WHERE role='org_admin' AND org_id IN scope_orgs
        - super_admins: WHERE role IN ('super_admin','admin_global')
        - Apply user_notification_prefs (mute + min_severity) cho org_admins
        - Super Admin KHÔNG bị filter prefs (luôn nhận)
        """
        scope_orgs = await self._scope_orgs(db, sub)
        org_admin_ids = await users_with_role_in_orgs(db, "org_admin", scope_orgs)
        super_admin_ids = await users_with_roles(db, ["super_admin", "admin_global"])

        severity_rank = SEVERITY_RANK[template.default_severity]

        accepted: list[User] = []
        # Org Admins — apply prefs
        for uid in org_admin_ids:
            pref = await self._get_pref(db, uid, template.code)
            if pref and pref.muted:
                continue
            if pref and pref.min_severity:
                if SEVERITY_RANK[pref.min_severity] > severity_rank:
                    continue
            accepted.append(uid)
        # Super Admins — always
        accepted.extend(super_admin_ids)
        # Dedup, preserve order
        seen, out = set(), []
        for uid in accepted:
            if uid not in seen:
                seen.add(uid); out.append(uid)
        return out

    async def _scope_orgs(self, db, sub: AlertRule) -> list[UUID]:
        """Return list org_id mà subscription bao phủ.

        - system:  [tất cả org active]
        - org_only: [sub.org_id]
        - org_tree: [sub.org_id] + mọi descendants
        """
        if sub.scope_mode == "system":
            return await all_org_ids(db)
        if sub.scope_mode == "org_only":
            return [sub.org_id]
        # org_tree
        return await descendants_of(db, sub.org_id)
```

### 4.4. Module / file mới

```
server/app/services/alert_engine.py          # mới — AlertEngine + trigger_alert()
server/app/services/alert_templates.py       # mới — CRUD template + render helper
server/app/services/user_notification_prefs.py  # mới — CRUD prefs
server/app/services/org_scope.py             # mới — descendants_of(org_id) helper
server/app/api/routes/alert_templates_admin.py  # mới — Super Admin CRUD templates
server/app/api/routes/alert_rules.py         # SỬA — schema mới, validation
server/app/api/routes/alert_events.py        # tách từ alert_rules.py
server/app/api/routes/user_notification_prefs.py  # mới — /api/me/notification-prefs
server/app/services/monitor.py               # SỬA — gọi alert_engine.trigger_alert()
server/app/services/notifications.py         # SỬA — bỏ notify_investigation_completed/failed
                                              # chuyển sang dùng alert_engine
server/app/api/routes/dfir_requests.py       # SỬA — thay notify_investigation_* bằng trigger_alert
server/app/alembic/versions/<rev>_alert_engine.py  # mới — migration
```

---

## 5. Cấu trúc file (Portal)

### 5.1. File MỚI

```
portal/app/(portal)/admin/telegram-bot/page.tsx       # move từ /me/telegram (code giữ nguyên)
portal/app/(portal)/notifications-alerts/TemplatesTab.tsx  # tab Templates (Super Admin)
portal/app/(portal)/notifications-alerts/SubscriptionsTab.tsx  # tab Subscriptions (refactor từ page.tsx hiện tại)
portal/app/(portal)/me/notification-prefs/page.tsx    # trang opt-out per template
portal/app/(portal)/admin/alert-templates/[code]/page.tsx  # (optional) edit template detail; tab dùng modal là đủ
portal/lib/types.ts                                  # SỬA — thêm AlertTemplate, UserNotificationPref
```

### 5.2. File SỬA

```
portal/app/(portal)/notifications-alerts/page.tsx     # refactor thành 3 tab layout
portal/app/(portal)/layout.tsx                         # thêm nav link /me/notification-prefs
portal/app/(portal)/me/telegram/page.tsx               # XOÁ — đã move sang admin/telegram-bot
```

### 5.3. File XOÁ

```
portal/app/(portal)/me/telegram/                       # toàn bộ dir
```

### 5.4. File KHÔNG đổi

```
server/app/api/routes/telegram_bot_admin.py           # backend endpoint đã đúng
server/app/api/routes/notifications.py:me_router       # user link Telegram (giữ nguyên)
server/app/services/telegram_runtime.py                # runtime đã ổn
```

---

## 6. Template seed ban đầu

7 templates sẽ được insert qua Alembic data migration:

| code | name | category | default_severity | opt_out_controls | allowed_vars | default_config |
|---|---|---|---|---|---|---|
| `machine_new` | Máy mới enroll trong tổ chức | machine | info | `["template"]` | `["hostname","ip","os","org_name","enrolled_at","machine_id"]` | `{}` |
| `machine_lost` | Mất liên lạc > N ngày | machine | warning | `["template"]` | `["hostname","ip","org_name","last_seen_at","threshold_days","machine_id"]` | `{"threshold_days":7}` |
| `machine_offline` | Máy chuyển offline | machine | warning | `["severity"]` | `["hostname","ip","org_name","last_seen_at","machine_id"]` | `{}` |
| `investigation_completed` | Điều tra DFIR hoàn thành | investigation | info | `["severity"]` | `["hostname","findings_count","severity","llm_model","investigation_id","machine_id"]` | `{}` |
| `investigation_failed` | Điều tra DFIR thất bại | investigation | error | `["severity"]` | `["hostname","error","investigation_id","machine_id"]` | `{}` |
| `software_new` | Phần mềm lạ xuất hiện | security | warning | `["template","severity"]` | `["hostname","software_name","version","publisher","machine_id"]` | `{}` |
| `hardware_changed` | Phần cứng thay đổi | security | warning | `["template","severity"]` | `["hostname","component","old_value","new_value","machine_id"]` | `{}` |

Title/body mặc định (ví dụ):

```python
{
  "machine_new": {
    "title": "[{org_name}] Máy mới: {hostname}",
    "body": (
      "Hostname: {hostname}\n"
      "OS: {os}\n"
      "IP: {ip}\n"
      "Enrolled: {enrolled_at}"
    ),
  },
  "machine_lost": {
    "title": "[{org_name}] Mất liên lạc > {threshold_days} ngày: {hostname}",
    "body": (
      "Hostname: {hostname}\n"
      "IP: {ip}\n"
      "Last seen: {last_seen_at}"
    ),
  },
  "investigation_completed": {
    "title": "Điều tra hoàn thành · {severity}",
    "body": (
      "**Máy:** {hostname}\n"
      "**Phát hiện:** {findings_count}\n"
      "**Mức độ:** {severity}\n"
      "**Model:** {llm_model}"
    ),
  },
  # ...
}
```

---

## 7. API endpoints

### 7.1. Super Admin — templates

```
GET    /api/admin/alert-templates              # list (filter: enabled, category)
GET    /api/admin/alert-templates/{code}      # detail
PATCH  /api/admin/alert-templates/{code}      # edit name, description,
                                                #  title_template, body_template,
                                                #  opt_out_controls, allowed_vars,
                                                #  default_severity, default_config,
                                                #  enabled
POST   /api/admin/alert-templates/{code}/preview
        # body: {"context": {...}}
        # response: {"title": "...", "body": "...", "warnings": [...]}
        # dùng để live-preview trong editor
```

### 7.2. Subscriptions (refactor từ `/api/alert-rules`)

```
GET    /api/alert-rules                        # list (scope theo admin role)
POST   /api/alert-rules                        # tạo subscription mới
PATCH  /api/alert-rules/{id}                   # update
DELETE /api/alert-rules/{id}                   # delete
POST   /api/alert-rules/{id}/test              # dry-run: render + resolve recipients
                                                #  trả preview + danh sách user sẽ nhận
                                                #  KHÔNG gửi notification thật
GET    /api/alert-rules/events                 # history (refactor từ alert_rules.py)
```

### 7.3. User notification prefs

```
GET    /api/me/notification-prefs              # list prefs của user hiện tại
                                                #  kèm template metadata (name, opt_out_controls)
PATCH  /api/me/notification-prefs              # bulk update: {prefs: [{template_code, muted, min_severity}]}
                                                #  validate theo template.opt_out_controls
```

### 7.4. Bot config (đã có, không đổi path)

```
GET    /api/admin/telegram-bot                 # đã có — Super Admin
PUT    /api/admin/telegram-bot
POST   /api/admin/telegram-bot/test
GET    /api/admin/telegram-bot/linked-users
DELETE /api/admin/telegram-bot/linked-users/{user_id}
```

---

## 8. Portal UI

### 8.1. `/notifications-alerts` — 3 tab

**Tab 1: Subscriptions** (Org Admin + Super Admin)
- List subscriptions: name, template badge, scope (org tree), enabled toggle
- Form tạo/sửa:
  - Tên rule
  - Template (dropdown lọc theo `category`)
  - Scope mode (radio): `org_only` / `org_tree` / `system` (chỉ Super Admin chọn system)
  - Scope org (cây tổ chức — `flattenOrgTree`); disable nếu scope_mode=system
  - Config override (VD threshold_days) — render động theo `template.default_config`
  - Recipients: read-only display "Org Admin của scope + Super Admin" (per user direction)
  - Enable toggle

**Tab 2: Templates** (Super Admin only)
- List 7 templates: code, name, category, severity badge, opt_out_controls chips
- Edit modal/page:
  - Name, description
  - Title template + body template (textarea) — hiển thị `allowed_vars` chips
  - Live preview panel: form nhập sample context → render title/body real-time (gọi `/preview`)
  - Opt-out controls multi-select: `template`, `severity` (validate 0-2 lựa chọn)
  - Default severity dropdown
  - Default config JSON (cho admin edit threshold_days, …)
  - Enabled toggle

**Tab 3: History** (giữ nguyên)
- Bảng `alert_events` — columns: time, template, severity, machine, scope org, recipients count, content preview

### 8.2. `/me/notification-prefs` (mới)

Layout chia section theo `category`:

```
┌─ Máy (machine) ──────────────────────────────────────┐
│                                                       │
│  Máy mới enroll trong tổ chức         [info badge]  │
│  🔕 Tắt nhận "Máy mới"                [☐ checkbox]  │
│                                                       │
│  Mất liên lạc > N ngày                [warning]    │
│  🔕 Tắt nhận "Mất liên lạc"           [☐ checkbox]  │
│                                                       │
│  Máy chuyển offline                    [warning]    │
│  Chỉ nhận từ mức: [warning ▼]         [dropdown]    │
│                                                       │
└───────────────────────────────────────────────────────┘
┌─ Điều tra (investigation) ───────────────────────────┐
│  Điều tra hoàn thành                  [info]       │
│  Chỉ nhận từ mức: [info ▼]                          │
│  ...                                                  │
└───────────────────────────────────────────────────────┘
```

- Super Admin: hiển thị banner xám "Bạn là Super Admin — luôn nhận mọi alert, không thể tắt." + disable tất cả controls
- Empty state nếu user không có role admin (chỉ viewer) — không có gì để cấu hình

### 8.3. `/admin/telegram-bot` (move từ `/me/telegram`)

Code giữ nguyên 100%. Path mới: `portal/app/(portal)/admin/telegram-bot/page.tsx`.

---

## 9. Trigger points migrate

| Nơi gọi cũ | Gọi mới |
|---|---|
| `monitor._scan_alerts` rule `machine_new` | `await alert_engine.trigger_alert(db, template_code='machine_new', org_id=machine.org_id, machine_id=machine.id, context={...})` |
| `monitor._scan_alerts` rule `machine_lost` | `await alert_engine.trigger_alert(db, template_code='machine_lost', org_id=machine.org_id, machine_id=machine.id, context={'threshold_days': sub.config.get('threshold_days', 7), ...})` |
| `notify_investigation_completed` | `await alert_engine.trigger_alert(db, template_code='investigation_completed', org_id=inv.org_id, machine_id=inv.machine_id, context={'findings_count': inv.findings_count, 'severity': inv.severity, 'llm_model': inv.llm_model, 'investigation_id': str(inv.id)})` |
| `notify_investigation_failed` | `await alert_engine.trigger_alert(db, template_code='investigation_failed', org_id=inv.org_id, machine_id=inv.machine_id, context={'error': error, 'investigation_id': str(inv.id)})` |
| `_sweep_offline` (mỗi máy offline) | `await alert_engine.trigger_alert(db, template_code='machine_offline', org_id=machine.org_id, machine_id=machine.id, context={...})` |

`monitor._deliver_alert()` bị **xoá hoàn toàn**. `alert_rules.channels` và `alert_rules.notify_targets` cũng bị xoá (không còn cần — delivery cố định = in-app + Telegram qua user prefs).

---

## 10. Validation & error handling

### 10.1. Server-side validation

- **PATCH `/api/admin/alert-templates/{code}`**: validate `opt_out_controls` ⊆ `{"template", "severity"}`; validate biến trong title/body ⊆ `allowed_vars` (regex parse `{(\w+)}`).
- **POST `/api/alert-rules`**: nếu `scope_mode='system'` mà admin không phải super_admin → 403. `org_id` required khi scope != system.
- **PATCH `/api/me/notification-prefs`**: validate `muted=true` chỉ được set nếu template có `template` trong opt_out_controls; tương tự cho `min_severity`.
- **`alert_engine.trigger_alert`**: nếu template không tồn tại → log warning + skip (không raise). Nếu render thiếu biến trong context → substitute `[MISSING: varname]` + log.

### 10.2. Delivery error handling

- **Telegram**: best-effort, lỗi log warning. `NotificationDelivery.status='failed'`. **Không retry** — user phải vào portal xem in-app notification.
- **In-app notification**: lỗi DB → raise, transaction rollback. Alert event không được tạo nếu notification thất bại (giữ invariant: alert event ↔ ít nhất 1 notification row).
- **Telegram bot not configured** (`cfg.can_send=False`): skip Telegram, chỉ gửi in-app. `NotificationDelivery` không tạo row cho telegram (channel='telegram', status='skipped').

### 10.3. Idempotency

- Alert event dùng `fingerprint = sha256(rule_id + machine_id + template_code + YYYY-MM-DD)` — cùng rule + máy + ngày chỉ tạo 1 event (kế thừa logic hiện tại của monitor).
- Notification row dùng `idempotency_key = f"alert-event:{event.id}:user:{user_id}"` — chống duplicate khi retry.

---

## 11. Testing

### 11.1. Unit tests (pytest)

```
tests/test_alert_engine.py
  - test_trigger_alert_creates_event_with_correct_recipients
  - test_org_admin_opt_out_via_prefs_is_respected
  - test_super_admin_always_receives_even_if_pref_muted
  - test_org_tree_scope_includes_descendants
  - test_org_only_scope_excludes_descendants
  - test_min_severity_filters_out_lower_severity
  - test_disabled_template_does_not_trigger
  - test_disabled_subscription_does_not_trigger
  - test_fingerprint_dedup_prevents_duplicate_events_same_day

tests/test_alert_templates.py
  - test_render_substitutes_allowed_vars
  - test_render_substitutes_missing_var_with_placeholder
  - test_render_raises_if_unknown_var_in_template
  - test_opt_out_controls_validated_to_allowed_values

tests/test_user_notification_prefs_api.py
  - test_get_returns_prefs_for_user
  - test_patch_validates_against_template_opt_out_controls
  - test_super_admin_prefs_endpoint_disables_all_controls
```

### 11.2. Integration tests

```
tests/integration/test_alert_flow.py
  - test_machine_enroll_triggers_notification_to_org_admin
  - test_machine_enroll_triggers_telegram_to_linked_admin
  - test_machine_enroll_skips_telegram_for_unlinked_admin
  - test_org_admin_can_mute_machine_new_via_prefs
  - test_investigation_completion_triggers_alert_with_severity_threshold
```

### 11.3. Manual smoke checklist

- [ ] Vào `/admin/telegram-bot`, set token → test getMe OK
- [ ] Vào `/me`, link Telegram cá nhân → confirm chat_id hiển thị
- [ ] Vào `/notifications-alerts` → tab Subscriptions → tạo rule `machine_new` cho 1 org → enable
- [ ] Enroll 1 agent mới vào org đó (qua token enroll)
- [ ] Trong vòng 60s: Org Admin (active, link Telegram) nhận được cả in-app bell + Telegram message
- [ ] Org Admin (active, KHÔNG link Telegram) nhận được in-app bell, KHÔNG có Telegram
- [ ] Org Admin mute "Máy mới" qua `/me/notification-prefs` → enroll agent mới → KHÔNG nhận
- [ ] Super Admin KHÔNG mute được → enroll agent mới → vẫn nhận
- [ ] Vào tab Templates (Super Admin) → edit `machine_new` title → save → trigger alert mới → render dùng title mới

---

## 12. Migration plan

**Single Alembic migration** `2026_09_01_alert_engine.py`:

1. `CREATE TABLE alert_templates (...)` (idempotent với IF NOT EXISTS)
2. `CREATE TABLE user_notification_prefs (...)`
3. `DROP TABLE alert_events CASCADE;` (cascade vì FK từ notification_deliveries — check trước)
4. `DROP TABLE alert_rules CASCADE;`
5. `CREATE TABLE alert_rules (...)` (schema mới)
6. `CREATE TABLE alert_events (...)` (schema mới)
7. Insert 7 templates qua `op.execute()` với data Python dict (xem section 6)

**Quan trọng:** vì user chọn approach A (clean replace, không migrate data), KHÔNG có script copy từ bảng cũ. Dữ liệu cũ mất.

**Downgrade:** `DROP TABLE alert_events; DROP TABLE alert_rules; DROP TABLE user_notification_prefs; DROP TABLE alert_templates;` — không khôi phục được data cũ (đã drop).

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Mất alert rules cũ (user chọn clean replace) | Ghi rõ trong release notes; admin cần recreate rule. Nếu user đổi ý sau, có thể xuất CSV rule cũ từ backup DB trước khi migrate |
| `template_code` không có FK cascade khi xoá template | `ON UPDATE CASCADE` cho code rename; `RESTRICT` cho delete (phải xoá subscription trước) |
| Alert event không sync nếu monitor chạy 2 lần cùng phút | Fingerprint dedup (đã có logic tương tự trong monitor cũ) |
| Telegram gửi chậm gây block pipeline | Best-effort, fire-and-forget qua `asyncio.gather`; lỗi chỉ log warning |
| Template author đặt biến không có trong allowed_vars | Server validate lúc PATCH; client preview hiển thị warning nếu biến không match |
| Org Admin không link Telegram → không nhận alert | UX: banner "Bạn chưa liên kết Telegram — sẽ chỉ nhận qua cổng bell trên portal" trong `/me` |

---

## 14. Out-of-scope (ghi nhớ cho tương lai)

- **Per-org email digest** (VD: gửi 1 email tổng hợp cuối ngày)
- **Slack / Microsoft Teams webhook** channel
- **Custom user-defined templates** (chỉ Super Admin hiện tại)
- **Template A/B testing / versioning**
- **Multi-language template** (i18n)
- **Per-org custom default severity** (override template's default)
- **Alert rule "test mode"** gửi cho 1 user chỉ định
- **Recipient = "manual list of user IDs"** (chỉ Org Admin + Super Admin hiện tại)

---

## 15. Workflow triển khai

1. **Migration Alembic** tạo schema mới + seed 7 templates (server chạy 1 lần).
2. **Server services**: viết `alert_engine.py`, `alert_templates.py`, `user_notification_prefs.py`, `org_scope.py`. Sửa `monitor.py` + `notifications.py` + `dfir_requests.py` gọi `alert_engine.trigger_alert`. Xoá `monitor._deliver_alert`.
3. **Server routes**: viết `alert_templates_admin.py`, `user_notification_prefs.py`. Refactor `alert_rules.py` (xoá events route ra file riêng).
4. **Portal — move page**: `git mv portal/app/(portal)/me/telegram portal/app/(portal)/admin/telegram-bot`.
5. **Portal — types**: thêm `AlertTemplate`, `UserNotificationPref`, `AlertRule` (mới) vào `lib/types.ts`.
6. **Portal — API helpers**: thêm helper gọi các endpoint mới trong `lib/api.ts`.
7. **Portal — notifications-alerts refactor**: tách page.tsx thành 3 tab components. Thêm form template editor với live preview.
8. **Portal — `/me/notification-prefs`**: trang mới, render động theo `opt_out_controls`.
9. **Tests**: viết unit + integration tests. Smoke test thủ công theo checklist section 11.3.
10. **Docs**: cập nhật `docs/API_CONTRACT.md` + `docs/RUNBOOK.md` với section alert engine mới.

---

## 16. Self-review

### 16.1. Placeholder scan
Không có TBD/TODO trong spec. Tất cả decisions đã chốt.

### 16.2. Internal consistency
- ✅ Schema section 4.2 nhất quán với API endpoints section 7 (cùng field names).
- ✅ `trigger_alert` signature section 4.3 khớp với trigger points section 9.
- ✅ Template seed section 6 dùng đúng `opt_out_controls` và `allowed_vars` schema section 4.2.
- ✅ UI section 8 dùng đúng endpoint paths section 7.

### 16.3. Scope check
Spec đủ nhỏ để 1 implementation plan (~10-15 tasks) cover được. Không cần decompose.

### 16.4. Ambiguity check
- `opt_out_controls=[]` → không có mute nào → rõ ràng.
- `recipient_mode` chỉ chấp nhận 1 giá trị hiện tại (`org_admins_and_super`) — check constraint rõ ràng, future-proof.
- `scope_mode='system'` yêu cầu `org_id=NULL` — check ở app layer (Pydantic validator).
- Telegram delivery khi user chưa link: đã spec rõ — skip silently, `NotificationDelivery` không tạo row.
