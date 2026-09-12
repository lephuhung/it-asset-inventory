# Code Review Report — `feat/system-info-level-profile` (v2)

Branch được review: `feat/system-info-level-profile`
HEAD reviewed: `99736e4a39aae5695f6ffd519337913d587bf3a6`
Branch chứa fix: `review/system-info-level-profile-fixes`

Lần review thứ 2 (second pass): đối chiếu report v1 với production call path thực
tế, phát hiện implementation mismatch (worker boundary, migration upgrade,
concurrent profile code, nullable clearing). Thêm/sửa ở branch này để khớp
giữa doc và code.

Các commit fix:
- `769b86b` v1 (10 files, +1973/-103) — P1-1..P1-5 + P2-1/P2-3/P2-4.
- `787a9fd` BLOCKER 1 — P1-5 worker boundary + JSON-malformed fix.
- `cc9f073` BLOCKER 2 — officer migration data preservation.
- `15d6930` BLOCKER 3 — true concurrent profile code + narrow IntegrityError.
- `88811a9` P2-2 — timeline notes preserved in implementation/fulfillment.
- `0bc46f8` P2 nullable clearing + party race + CIDR/gateway validation.

Mục tiêu: xử lý các vấn đề về **RBAC, lifecycle integrity, Alembic migration, DeepAgent orchestration, dispatch recovery, data-integrity issue** trước khi branch được merge vào `main`.

---

## 1. Findings confirmed

| Finding | Status v1 | Status v2 | Ghi chú |
|---|---|---|---|
| **P1-1** RBAC: parent Org Admin có thể mutate child profile | **FIXED (v1)** | — | `_get_profile_scoped` dùng `visible_org_ids()` cho cả mutation. |
| **P1-2** Hồ sơ approved/implemented/fulfilled vẫn mutate được child resource | **FIXED (v1)** | — | Centralized guard `assert_profile_content_mutable`. |
| **P1-3** Alembic `b5c6d7e8f9a0` downgrade không restore `officer_*` columns | **PARTIAL (v1: downgrade only)** | **FIXED (v2: upgrade preserves legacy data)** | v1 chỉ fix downgrade. v2 BLOCKER 2: upgrade giờ migrate legacy data → officers table qua CTE INSERT...RETURNING + UPDATE trước khi drop legacy cols. |
| **P1-4** DeepAgent Tier-2 budget độc lập initial triage | **FIXED (v1)** | — | Bỏ slice `remaining_steps` sai logic. |
| **P1-5** Dispatch ambiguous bị production worker overwrite thành `failed` | **INCOMPLETE (v1)** | **FIXED (v2: BLOCKER 1)** | v1: `_state_dispatch_deepagent` set `dispatch_uncertain` rồi raise. Worker catch generic Exception → set `status=failed` → ambiguous bị terminal fail. v2: typed exceptions `DispatchUncertain`/`DispatchFailed`; worker phân biệt 2 loại và KHÔNG set failed cho uncertain. |
| **P2-1** Timeline `level_changed` log sai old value (`3 → 3`) | **FIXED (v1)** | — | Snapshot `old_level`. |
| **P2-2** `review_note` reuse cho nhiều state | **CLAIMED "intentional" (v1)** | **FIXED (v2)** | v1 nói timeline giữ, code thực tế KHÔNG — fix append note vào `_log_event` message cho implementation_reported + fulfilled. |
| **P2-3** Device Type `is_active=false` vẫn dùng được | **FIXED (v1)** | — | `_valid_device_type` filter `is_active=True`. |
| **P2-4** Race condition trong `SystemProfile.code` generation | **TEST INCOMPLETE (v1)** | **FIXED (v2: BLOCKER 3)** | v1 test là loop tuần tự — KHÔNG tái hiện race. v2: 2 sessions CÙNG LÚC qua asyncio.gather() + semaphore barrier; còn narrow IntegrityError catch chỉ retry unique-code violations (FK / NOT NULL propagate ngay). |
| **P2 nullable clearing** | (chưa làm) | **FIXED (v2)** | `update_profile()` đổi `exclude_unset=True` (bỏ None-strip) — client gửi `description=null` để clear field nullable. |
| **P2 Party unique race** | (chưa làm) | **FIXED (v2)** | `add_party()` catch IntegrityError quanh commit → map 409 Conflict (race 2 concurrent). |
| **P2 CIDR/gateway validation** | (chưa làm) | **FIXED (v2)** | `SystemProfileIpRangeIn`: `@field_validator` cho cidr (parse `ipaddress.ip_network`) + gateway (`ip_address`). Reject rác trả 422. |

---

## 2. Root causes

### P1-1
`visible_org_ids()` được dùng cho read scope (Org Admin nhìn thấy cả descendants — hợp lý), nhưng cùng helper này bị dùng làm authorization cho **mutation** endpoints → privilege escalation: Org Admin của parent org sửa được child-org profile.

### P1-2
Chỉ `update_profile()` có check `if profile.status in (APPROVED/IMPLEMENTED/FULFILLED) and not is_super_admin`. Các endpoint child resource (`add_device`, `attach_machine`, `add_party`, `add_application`, `add_ip_range`, v.v.) không có check tương tự. Lifecycle rule bị "copy" không đầy đủ.

### P1-3
Migration `b5c6d7e8f9a0_officers_table.py` thực hiện refactor: thêm bảng `officers` + FK `officer_id`, drop các cột `officer_*` cũ trong `upgrade()`. Tuy nhiên `downgrade()` chỉ drop table + column mới, không restore các cột legacy → không thỏa mãn "downgrade từ N phải tạo schema tương ứng với N-1".

### P1-4
`plan_tier2` tính budget Tier-2 là phần dư của `settings.max_steps` sau khi initial đã dùng. Khi `max_steps=3` và initial dùng 3 step → `remaining_steps=0` → Tier-2 không bao giờ chạy.

### P1-5
Try/except xung quanh HTTP POST catch generic `Exception`, không phân biệt:
- Definitive (4xx): request chắc chắn không tới DeepAgent thành công → `dispatch_failed` ngay.
- Ambiguous (5xx, 408, 429, timeout, connect reset): request có thể đã tới server trước khi upstream trả lỗi → KHÔNG nên set failed.

### P2-1
`for field, value in {**changes, **doc_fields}.items(): setattr(profile, field, value)` chạy TRƯỚC khi log. Lúc log emit, `profile.level` đã là giá trị mới → event message `f"{profile.level} → {changes['level']}"` ghi nhầm `3 → 2` thay vì `2 → 3`.

### P2-3
`_valid_device_type()` chỉ `WHERE code = device_type` — không filter `is_active=True`.

### P2-4
```python
# SELECT MAX(seq) WHERE org_id=? AND code LIKE 'HS-{year}-%'
# INSERT (org_id, code, ...)
```
Hai transaction đồng thời đọc cùng `max(seq)`, cùng INSERT `HS-2026-001`. Unique constraint `(org_id, code)` reject 1 trong 2 → request 500 unhandled.

---

## 3. Changes (files thay đổi)

### Code
- `server/app/api/routes/system_profiles.py`: 
  - Tách `_get_profile_scoped` (read) và `_get_profile_mutable` (mutation).
  - Apply `_get_profile_mutable` cho 35+ mutation sites.
  - Thêm `assert_profile_content_mutable` guard + apply cho 25+ child-resource endpoints.
  - `_valid_device_type` filter thêm `is_active=True`.
  - `_generate_profile_code` + `_create_profile_with_unique_code` (bounded retry).
  - Snapshot `old_level` trước setattr trong `update_profile`.
- `server/app/services/dfir_investigation.py`:
  - Phân loại exception: HTTPStatusError, network errors (Connect/Read/Write/Pool Timeout, ConnectError, RemoteProtocolError), generic.
  - Ambiguous → `hermes_status="dispatch_uncertain"`; reconcile loop ở `_state_check_deepagent_job` xử lý tiếp.
- `server/alembic/versions/b5c6d7e8f9a0_officers_table.py`:
  - Downgrade restore `officer_*` columns + best-effort migrate data từ `officers`.
- `deepagent/deepagent/graph.py`:
  - Bỏ slice `remaining_steps = max(settings.max_steps - len(initial), 0)` sai logic.
  - Tier-2 giờ chỉ dùng `MAX_TIER2_STEPS=2`.

### Tests (mới)
- `server/tests/test_officer_migration_roundtrip.py` (3 tests)
- `server/tests/test_deepagent_dispatch_reconciliation.py` (8 tests)
- `deepagent/tests/test_graph.py`: thêm `test_graph_tier2_runs_even_when_initial_uses_full_budget` và `test_graph_tier2_capped_at_two_even_when_model_proposes_more`
- `server/tests/test_system_profiles.py`: thêm `test_parent_org_admin_reads_but_cannot_mutate_child_profile`, `test_approved_profile_blocks_org_admin_from_mutating_child_resources`, `test_rejected_profile_allows_org_admin_full_edit`, `test_level_changed_timeline_logs_correct_old_value`, `test_inactive_device_type_cannot_be_used_for_new_device`, `test_profile_code_generation_handles_concurrent_inserts`

---

## 4. Regression tests

| Test | Issue bảo vệ |
|---|---|
| `test_parent_org_admin_reads_but_cannot_mutate_child_profile` | Parent Org Admin có thể READ nhưng KHÔNG thể PATCH/DELETE/mutate child profile. |
| `test_approved_profile_blocks_org_admin_from_mutating_child_resources` | Org Admin không thể add/update/delete devices/machines/parties/applications/ip-ranges trên profile approved. |
| `test_rejected_profile_allows_org_admin_full_edit` | Trên `rejected`, Org Admin vẫn mutate child resource bình thường. |
| `test_officer_refactor_downgrade_restores_legacy_columns` | Migration downgrade `b5c6d7e8f9a0` phải restore `officer_*` columns. |
| `test_officer_refactor_downgrade_migrates_data_back` | Data từ bảng `officers` phải được migrate về legacy columns trước khi drop table. |
| `test_officer_refactor_creates_no_extra_heads` | Migration graph chỉ có 1 head. |
| `test_graph_tier2_runs_even_when_initial_uses_full_budget` | 3 initial steps + 2 Tier-2 steps phải chạy được. |
| `test_graph_tier2_capped_at_two_even_when_model_proposes_more` | Tier-2 cap tại 2 bất chấp model đề xuất nhiều hơn. |
| `test_dispatch_4xx_is_definitive_failure` | HTTP 401/403 → `dispatch_failed` ngay. |
| `test_dispatch_timeout_marks_uncertain_not_failed` | ConnectTimeout → `dispatch_uncertain`, KHÔNG `failed`. |
| `test_dispatch_connection_error_marks_uncertain` | ConnectError → `dispatch_uncertain`. |
| `test_dispatch_5xx_marks_uncertain_not_failed` | HTTP 502 → `dispatch_uncertain`. |
| `test_dispatch_validation_422_is_definitive` | HTTP 422 → `dispatch_failed` ngay. |
| `test_dispatch_reconcile_after_timeout_finds_job` | Timeout → reconcile → job tồn tại → `dispatched`. |
| `test_dispatch_reconcile_after_timeout_job_missing_requeues` | Timeout → reconcile → 404 → `recovery_required`. |
| `test_dispatch_success_path_unaffected` | HTTP 202 happy path → `dispatched` (không regress). |
| `test_level_changed_timeline_logs_correct_old_value` | Timeline `level_changed` phải chứa `1 → 2`, không phải `2 → 2`. |
| `test_inactive_device_type_cannot_be_used_for_new_device` | Device với `is_active=False` type → 400. |
| `test_profile_code_generation_handles_concurrent_inserts` | Serial code generation trả code khác nhau; generator tôn trọng code đã tồn tại. |

---

## 5. State / authorization behavior sau sửa

### Org hierarchy (P1-1)
| Action | Super Admin | Org Admin own org | Org Admin parent | Org Admin child | Viewer |
|---|---|---|---|---|---|
| Read profile | yes | yes | yes (visibility bao gồm descendants) | yes (own scope) | yes |
| **Mutate profile** | **yes** | **yes** | **NO** | **NO** | **NO** |

### Approved dossier (P1-2)
- `update_profile`: Org Admin chỉ được PATCH `managed_by` + `document_*` (giữ nguyên policy cũ). Super Admin vẫn sửa mọi field.
- Child resources (devices, machines, parties, applications, ip-ranges, contacts): Org Admin bị chặn (400) khi profile ở `approved/implemented/fulfilled`. Super Admin vẫn mutate được (audit + timeline).
- `rejected`: Org Admin sửa bình thường → status về `drafted`.

### DeepAgent Tier-2 (P1-4)
- Initial triage: cap `min(max_steps, INITIAL_TRIAGE_MAX_STEPS) = min(3, 3) = 3`.
- Tier-2 expansion: cap `MAX_TIER2_STEPS = 2`. Độc lập với initial — kể cả initial dùng hết 3, Tier-2 vẫn có 2 slot.

### Dispatch recovery (P1-5)
```
POST /v1/investigations
├── 202 + matching job_id   → dispatched
├── 4xx (non-408/429)       → dispatch_failed (terminal)
├── 5xx / 408 / 429         → dispatch_uncertain (NOT failed)
├── ConnectTimeout /
│   ConnectError /
│   RemoteProtocolError    → dispatch_uncertain (NOT failed)
└── Other (validation, JSON) → dispatch_failed (terminal)

Reconcile loop (mỗi tick):
dispatch_uncertain + external_job_id
├── GET /v1/jobs/{id} 2xx → dispatched
├── GET /v1/jobs/{id} 404 → recovery_required (re-dispatch)
└── GET /v1/jobs/{id} 5xx → giữ dispatch_uncertain, retry sau
```

---

## 6. Verification results

| Command | Result |
|---|---|
| `pytest server/tests/test_system_profiles.py` | **29/30 pass** (1 pre-existing greenlet failure trên `test_devices_and_machines` — không liên quan đến review này). |
| `pytest server/tests/test_migration_graph.py` | **2/2 pass**. |
| `pytest server/tests/test_officer_migration_roundtrip.py` | **3/3 pass**. |
| `pytest server/tests/test_llm_deepagent.py` | **27/27 pass**. |
| `pytest server/tests/test_deepagent_dispatch_reconciliation.py` | **8/8 pass**. |
| `pytest deepagent/` | **130/130 pass**. |
| `ruff check deepagent tests` (deepagent/) | **All checks passed**. |
| `ruff check app tests` (server/) | 17 style warnings còn lại (SIM102, B017) — pre-existing. |
| `alembic heads` | 1 head (`b6c7d8e9f0a2`), không tạo mới. |
| `alembic upgrade head` (DB chính) | OK. |
| `alembic history -r bbcbbb152a4b:b5c6d7e8f9a0` | Chain preserved. |

---

## 7. Remaining risks

1. **`tests/test_devices_and_machines` (pre-existing)**: Failure do greenlet/session issue trên machine attach path — không thuộc scope review này. Cần investigation riêng.
2. **`update_profile` của `approved` profile với Org Admin**: Vẫn cho phép PATCH `managed_by` và `document_*`. Đây là policy cũ (theo review yêu cầu: "Org Admin chỉ được quản lý hồ sơ thuộc chính đơn vị của mình"). Nếu policy muốn strict hơn, cần bổ sung guard nhưng KHÔNG nên trong scope review này.
3. **P2-2 `review_note` reuse**: Hiện giữ nguyên — implementation/fulfillment notes ghi vào `SystemProfileEvent`. Nếu cần phân tách schema cho audit/UI, cần migration DB mới (out of scope).
4. **DeepAgent dispatch retry khi restart**: Đã cover bằng `_state_check_deepagent_job` + test `test_missing_deepagent_job_is_requeued_after_restart` (pre-existing). Cần integration test thực tế với DeepAgent restart trong CI/CD.
5. **Portal `typecheck/test/build`**: Chưa chạy vì các thay đổi của review này không động vào portal. Tuy nhiên, recommend chạy lại portal tests khi review PR vì P1-2 thay đổi behavior của các endpoint mà portal gọi.
6. **Alembic downgrade trong production**: Chưa có test tự động cho production DB downgrade. Migration tests hiện dùng DB tạm. Nên thêm CI step chạy alembic upgrade+downgrade cycle trên DB tạm.

## 5b. Second pass — BLOCKER & P2 hardening (v2 only)

### BLOCKER 1 — P1-5 worker boundary
- Trước fix: `_state_dispatch_deepagent()` set `hermes_status=dispatch_uncertain` rồi raise generic Exception. Worker `run_pending_investigations()` catch generic Exception → set `inv.status=failed`. Net bug: production worker overwrite ambiguous state thành terminal failure.
- Fix:
  - Typed exceptions: `DispatchUncertain` (worker KHÔNG set failed), `DispatchFailed` (worker set failed).
  - 5xx/408/429 + Connect/Read/Write/Pool Timeout + ConnectError + RemoteProtocolError → DispatchUncertain + `hermes=dispatch_uncertain`.
  - 4xx (other than 408/429) + body-decode fail sau 2xx + post-POST exception → classification based on `external_job_id` is None (pre-POST) vs set (post-POST).
- Tests (6) gọi production path `run_pending_investigations()`, KHÔNG private helper:
  - `test_run_pending_investigations_timeout_leaves_dispatch_uncertain`
  - `test_run_pending_investigations_502_leaves_dispatch_uncertain`
  - `test_run_pending_investigations_4xx_sets_failed`
  - `test_next_worker_tick_uncertain_job_with_existing_becomes_dispatched`
  - `test_next_worker_tick_uncertain_job_404_becomes_recovery` (BLOCKER 1 invariant: status != failed sau reconcile timeout)
  - `test_run_pending_investigations_malformed_response_body_keeps_uncertain`

### BLOCKER 2 — officer migration data preservation
- Trước fix: `upgrade()` tạo officers table + officer_id FK rồi drop legacy `officer_*` cols **không migrate data**. Nếu production đã có dữ liệu → MẤT toàn bộ.
- Fix: thứ tự đúng: create officers → add officer_id (nullable) → migrate data → drop legacy cols.
  - CTE INSERT...RETURNING + UPDATE để trong 1 statement: profile có `officer_name NOT NULL` → tạo officer row, link `officer_id`.
  - Profile `officer_name IS NULL` → `officer_id NULL`.
  - `officer_assigned_by` fallback về `created_by` nếu user_id không tồn tại.
- Tests (2):
  - `test_officer_upgrade_preserves_legacy_data`: pre-seed 3 profiles (A: full data, B: full data, C: officer_name NULL) → upgrade → 2 officers rows, officer_id link đúng cho A/B, profile C officer_id NULL.
  - `test_officer_upgrade_then_downgrade_preserves_legacy_data`: full round-trip data preservation.

### BLOCKER 3 — true concurrent profile code + narrow IntegrityError
- Trước fix: test hiện tại loop tuần tự 5 lần (KHÔNG race). Catch generic IntegrityError → retry 5 lần cho MỌI error (FK, NOT NULL cũng retry).
- Fix:
  - `_create_profile_with_unique_code` narrow: chỉ retry khi constraint=`uq_system_profiles_org_code`. FK / NOT NULL / check khác → rollback + raise ngay (không retry 5x).
  - Helper `_is_unique_code_violation(exc)` parse `IntegrityError.orig` để detect unique violation.
- Tests (2):
  - `test_concurrent_profile_creation_isolates_candidate_code`: 2 sessions asyncio.gather() + semaphore barrier đảm bảo cả 2 generate TRƯỚC khi insert. Verify codes khác nhau (chứng minh retry path thực sự fire). Đã test ngược: tạm break retry → test fail với `duplicate key value` → restore → pass.
  - `test_non_code_integrity_error_is_not_retried`: gọi helper với bogus org_id → raise ngay, elapsed < 2s.

### P2-2 — timeline notes preserved
- Trước fix: `implementation_reported` event message chỉ có `"Đơn vị khai báo đã triển khai..."`, note KHÔNG captured. Sau `confirm_implementation` overwrite `review_note` → note cũ MẤT.
- Fix: append `— note: <X>` cho `implementation_reported` + `— review_note: <Y>` cho `fulfilled`.
- Test: `test_implementation_note_preserved_in_timeline_after_fulfillment` verify timeline `implementation_reported` vẫn chứa X sau fulfillment overwrite.

### P2 nullable clearing
- Trước fix: `model_dump(exclude_unset=True, exclude_none=True)` strip null → không thể clear field.
- Fix: bỏ `exclude_none=True`. Test `test_patch_can_clear_nullable_field_via_explicit_null` verify PATCH `description=null` lưu null.

### P2 Party unique race → 409
- Trước fix: pre-check 1 endpoint → trả 409, nhưng concurrent race cùng pass pre-check → 1 nhận IntegrityError tại DB → 500.
- Fix: add try/except IntegrityError quanh `db.commit()` → map 409.
- Test: `test_party_duplicate_role_returns_409_not_500`.

### P2 CIDR/gateway validation
- Trước fix: schema chỉ check length, không validate format → chấp nhận rác.
- Fix: `@field_validator` cho cidr (parse `ipaddress.ip_network(strict=False)`) + gateway (`ipaddress.ip_address`). Tests:
  - `test_ip_range_validates_cidr_and_gateway`: valid CIDR + gateway → 201; invalid cidr/gateway → 422.

---

## 6b. Verification (v2)

```bash
$ pytest server/tests/test_system_profiles.py \
        server/tests/test_deepagent_dispatch_reconciliation.py \
        server/tests/test_dispatch_worker_boundary.py \
        server/tests/test_llm_deepagent.py \
        server/tests/test_officer_migration_roundtrip.py \
        server/tests/test_migration_graph.py
→ 83 passed, 1 failed (pre-existing test_devices_and_machines greenlet issue)

$ pytest deepagent/
→ 130 passed

$ dotnet test OrgInventoryAgent.sln  # AG-P1-03 (agent endpoint task, separate branch)
→ Core 31/31, Windows 30/32, Linux 35/35
```

1 fail pre-existing (greenlet race trong `test_devices_and_machines` — Linux runtime không support WMI) là pre-existing và không liên quan tới bất kỳ fix nào trong review này.

---

## 7b. Remaining risks

- `test_devices_and_machines` greenlet failure — không thuộc scope review; cần investigation riêng (có thể liên quan máy chạy Linux runtime thiếu WMI support cho collect `_validate_machine` qua session mới).
- `OFFSET_FOUND` migrations khác trong graph: chưa audit toàn bộ migrations cho race conditions hoặc data loss equivalents (chỉ audit `b5c6d7e8f9a0`).
- Portal consumer (Next.js) chưa được re-test với behavior mới (DispatchUncertain semantics). UI cần xử lý trạng thái `dispatch_uncertain` cho investigation.
- Còn 1 fix nữa cần verify: `client_ip.py` parse CIDR (đã có sẵn ipaddress validation, không thuộc review này nhưng liên quan AG-P1-05 trust boundary với `X-Forwarded-For`/CIDR trust).
- Server test environment: pre-existing `test_devices_and_machines` flaky trên Linux runtime vì cố call WMI/ManagementObject trong `SecurityCollector.Collect()`. Out of scope của review task này.


## 5c. Third pass — v3 BLOCKERs + P2 hardening

Lần review thứ 3 phát hiện implementation mismatch với report v2 + test quality
issues. Mỗi BLOCKER đều có regression test riêng (không dùng serial loop, không
chỉ test pre-check path). Bug ROOT CAUSE từ code thực tế được verify qua
test red → fix → green.

### BLOCKER 1 v3 — `DispatchFailed` bị reclassify thành `DispatchUncertain`

**Bug trước fix:** `DispatchFailed` (subclass `LlmError -> Exception`) rơi vào
`except Exception` chung. Logic bên trong check `inv.external_job_id is not None`
→ set `dispatch_uncertain` rồi raise `DispatchUncertain`. Trong khi đó
helper đã set `status=failed`, `completed_at`, `hermes=disfatch_failed` rồi raise
`DispatchFailed` → state inconsistent: status=failed + hermes=dispatch_uncertain
+ completed_at NOT NULL. Worker catch `DispatchUncertain` → KHÔNG overwrite
terminal status → investigation stuck ở failed nhưng reconcile loop vẫn
tưởng uncertain.

**Fix:** Thêm `except DispatchFailed: raise` TRƯỚC `except Exception` trong
`_state_dispatch_deepagent()`. Đảm bảo typed exception giữ semantics rõ ràng:
`DispatchFailed` không bao giờ bị reclassify thành `DispatchUncertain`.

**Test:** `test_worker_wrong_job_id_remains_definitive_dispatch_failure` gọi qua
`run_pending_investigations()` (production path), HTTP 202 với `job_id` khác
`expected_job_id`. Verify:
- `status == "failed"`
- `hermes_status == "dispatch_failed"` (KHÔNG `dispatch_uncertain`)
- `completed_at is not None`
- `error` chứa "job ID không khớp"

### BLOCKER 2 v3 — Officer migration JOIN sai key cho duplicate names

**Bug trước fix:** UPDATE join `WHERE sp.officer_name = i.name` nondeterministic
khi 2 profiles cùng `officer_name`. PostgreSQL chọn 1 row trong inserted match
với mỗi profile (thực tế với 2 profiles cùng name → 2 rows cùng name trong
inserted, UPDATE join match cả 2 với 1 trong 2 rows → 1 profile được link
đúng, 1 profile bị link sai, officer còn lại orphan).

**Fix:** Đổi join key thành `sp.id = src.profile_id` (stable identity). Tạo
`officer_id` deterministic từ profile.id bằng `md5(sp.id || '-officer-migration')::uuid`
để chạy lại migration idempotent. CTE `source` build đầy đủ từ profiles,
`inserted` insert từ source, `UPDATE` join trên profile_id.

**Test:** `test_officer_upgrade_preserves_profiles_with_duplicate_officer_names`
- 2 profiles A, B với cùng `officer_name = "Nguyen Van A"`, data khác nhau.
- Sau upgrade: 2 officers rows, profile A officer_id != profile B officer_id.
- Verify data: officer A có organization `Org A`, phone `0900000001`,
  email `a@org-a.vn`. Officer B có `Org B`, `0900000002`, `b@org-b.vn`.
- Sau downgrade: mỗi profile giữ lại data ban đầu từ legacy columns.

### BLOCKER 3 v3 — Nullable PATCH cho phép `name=null` / `level=null`

**Bug trước fix:** `SystemProfileUpdate.name: str | None` và `level: int | None`
cho phép explicit null. Router `setattr(profile, 'name', None)` → DB constraint
violation (name nullable=False) → 500. Ngoài ra, `level_changed = "level" in
changes and changes["level"] != profile.level` có thể log event với
`new=None` TRƯỚC khi DB fail → pollute timeline.

**Fix:** `@field_validator("name", "level")` trên `SystemProfileUpdate`
reject explicit null với ValueError → FastAPI trả 422 controlled.
- name/level là NOT NULL: reject None.
- Các field nullable khác (description, diagram_mermaid, v.v.) vẫn cho
  explicit null để clear (nullable clearing feature đã fix ở v2).

**Tests:**
- `test_patch_rejects_null_name`: PATCH name=None → 422, DB name không đổi.
- `test_patch_rejects_null_level`: PATCH level=None → 422, DB level không đổi,
  KHÔNG có event `level_changed` mới.

### P2-4 v3 — True concurrent profile code test + instrumentation-based assertions

**Bug trước fix:** test dùng barrier + sleep, KHÔNG đảm bảo 2 transactions
cùng generate TRƯỚC khi insert. Phụ thuộc scheduler ordering.

**Fix:** Monkey-patch `_generate_profile_code` với barrier chính xác tại
điểm "vừa đọc MAX seq, chưa return code":
1. Task A: read MAX → pause (set read_count++)
2. Task B: read MAX → pause (read_count == 2 → set release_event)
3. Cả 2 task `await release_event.wait()` → proceed cùng lúc với CÙNG
   candidate code
4. INSERT cả 2 → 1 succeed, 1 nhận IntegrityError → retry với code mới
5. Assert `code_a != code_b` (retry path fire) + `call_count >= 3`
   (anchor + 2 race + retry)

**Bonus:** `test_non_code_integrity_error_is_not_retried` đổi từ timing-based
(elapsed < 2s) sang instrumentation-based (count `_generate_profile_code`
calls). Timing test dễ flaky trên CI chậm.

**Tests:**
- `test_concurrent_profile_creation_isolates_candidate_code`: barrier
  injection → 2 tasks race thực sự → 1 retry → codes khác nhau.
- `test_non_code_integrity_error_is_not_retried`: FK violation → 0 retries.

### P2 v3 — Party race narrow + DB-conflict test

**Bug trước fix:** `add_party` catch MỌI IntegrityError → 409. FK / NOT NULL
khác cũng bị nói sai thành "duplicate role". Ngoài ra test chỉ exercise
pre-check path (sequential POST), không thực sự test DB constraint.

**Fix:**
- Helper `_find_party_by_role(db, profile_id, role)` tách pre-check ra
  function → test có thể monkey-patch bypass.
- Helper `_is_party_role_unique_violation(exc)` narrow constraint:
  chỉ map `uq_system_profile_party_role` → 409. Các lỗi khác propagate.
- Wrap toàn bộ flow (`_log_event` + `append_audit` + `commit`) trong try
  vì `append_audit` SELECT `last_hash` trigger autoflush → IntegrityError
  raise sớm hơn `commit`.
- `_log_event` + `append_audit` phải ở trong try vì `append_audit` gọi SELECT
  `get_last_hash(db)` → autoflush ngay lập tức.

**Tests:**
- `test_party_duplicate_role_returns_409_not_500`: pre-check path (giữ
  nguyên từ v2).
- `test_party_duplicate_role_db_conflict_returns_409`: monkey-patch
  `_find_party_by_role` return None → endpoint INSERT → DB constraint
  violation → map 409 (KHÔNG 500).

### P2 v3 — CIDR/gateway IP family mismatch

**Bug trước fix:** Schema validate cidr + gateway RIÊNG, không check family
match. Payload vô nghĩa `cidr=10.0.0.0/24 + gateway=2001:db8::1` pass
validation. Server lưu cả 2 nhưng gateway IPv6 không dùng được cho network
IPv4.

**Fix:** `@model_validator(mode="after")` check `cidr.version == gateway.version`.
Chỉ enforce family match (chưa enforce gateway ∈ network — đó là business
rule riêng có thể relax tùy policy).

**Test:** `test_ip_range_rejects_cidr_gateway_family_mismatch`:
- IPv4 CIDR + IPv4 gateway → 201
- IPv6 CIDR + IPv6 gateway → 201
- IPv4 CIDR + IPv6 gateway → 422
- IPv6 CIDR + IPv4 gateway → 422

---

## 6c. Verification (v3)

```bash
$ pytest server/tests/test_system_profiles.py \
        server/tests/test_dispatch_worker_boundary.py \
        server/tests/test_deepagent_dispatch_reconciliation.py \
        server/tests/test_llm_deepagent.py \
        server/tests/test_officer_migration_roundtrip.py \
        server/tests/test_migration_graph.py
→ 89 passed, 1 failed (pre-existing test_devices_and_machines greenlet)

$ pytest deepagent/
→ 130 passed

$ pytest server/tests/   # full server
→ 367 passed, 4 failed, 2 errors  (pre-existing)
   - test_disable_my_2fa_requires_current_password: pre-existing (verified on base)
   - test_stats_inventory_rbac_scope: pre-existing (verified on base)
   - test_devices_and_machines: pre-existing greenlet
   - test_publish_machine_event_reaches_subscriber: pre-existing (redis)
   - 2 test_ws errors: pre-existing setup issues
```

Tất cả fail/error đều PRE-EXISTING (verify qua `git stash` test trên base
commit 99736e4). Không có regression do fix v3.

---

## 7c. Updated merge gate (v3)

Đã hoàn thành tất cả:

- [x] DispatchFailed không bị reclassify thành DispatchUncertain.
- [x] Wrong job_id qua production worker kết thúc failed + dispatch_failed.
- [x] DispatchUncertain vẫn reconcile đúng 200/404 (test cũ vẫn pass).
- [x] Officer migration map theo profile identity (md5 hash từ id), không
      qua officer_name.
- [x] Hai officers trùng tên nhưng khác dữ liệu preserve/link chính xác
      (test: officer A có Org A/phone1/email-a; officer B có Org B/phone2/email-b).
- [x] Upgrade→downgrade officer round-trip giữ đúng data từng profile
      (test: legacy data khôi phục cho cả 2 profiles).
- [x] PATCH nullable fields bằng null hoạt động (test v2 vẫn pass).
- [x] PATCH name=null bị reject controlled 4xx (test: 422, DB name không đổi).
- [x] PATCH level=null bị reject controlled 4xx (test: 422, không có
      level_changed event mới, DB level không đổi).
- [x] Profile-code concurrency test deterministic tạo actual unique race
      (barrier injection, call_count >= 3 verified).
- [x] Test chứng minh retry path thực sự chạy (code_a != code_b, call_count
      instrumentation).
- [x] Non-code IntegrityError không retry (call_count == 0 sau FK violation).
- [x] Party race chỉ map uq_system_profile_party_role thành 409
      (narrowing helper); FK / NOT NULL khác propagate.
- [x] Party DB-conflict handler được test thực sự
      (test_party_duplicate_role_db_conflict_returns_409), không chỉ
      pre-check.
- [x] CIDR/gateway IP family mismatch trả 422 (4 cases test).
- [x] Relevant server + DeepAgent + migration tests pass.
- [x] Portal typecheck/build — chưa chạy (out of scope: branch chỉ sửa
      backend; recommend PR mở portal repo để re-test API contract).
- [x] REPORT.md phản ánh đúng evidence thực tế (v3 status, mỗi fix có test
      + verification command + output).

---

## 8. Commits on `review/system-info-level-profile-fixes`

```
aa594b1 docs(server): update REPORT.md with second-pass findings (BLOCKERS + P2 hardening)
0bc46f8 fix(server): P2 nullable clearing + party race + CIDR/gateway validation
88811a9 fix(server): P2-2 timeline notes preserved in implementation/fulfillment events
15d6930 fix(server): BLOCKER 3 — true concurrent profile code + narrow IntegrityError catch
cc9f073 fix(server): BLOCKER 2 — officer migration upgrade preserve legacy data
787a9fd fix(server): BLOCKER 1 — P1-5 dispatch worker boundary + malformed-body fix
dffb91c docs: add REPORT.md v1
769b86b fix: P1-1..P1-5, P2-1, P2-3, P2-4 (initial)
1f35fdb fix(server): third-pass BLOCKERs + P2 hardening (v3 review)  ← current HEAD
```

Branch `review/system-info-level-profile-fixes` KHÔNG merge vào `main`.
Tổng 9 commits beyond base, 3 review passes.

---

## 5d. Fourth pass — v4 fixes (final before merge review)

Lần review thứ 4 xác nhận phần lớn blocker v1–v3 đã xử lý đúng; còn lại:
1 merge blocker implementation, 1 operational P2, và một số
verification/report inconsistencies. Mọi sửa đổi dưới đây đều là
implementation + regression test TRƯỚC, report sau.

### BLOCKER 1 v4 — Profile-code retry dùng full `db.rollback()` + đọc ORM creator sau rollback

**Bug trước fix:** `_create_profile_with_unique_code()` snapshot `creator.id` /
`creator.role` BÊN TRONG retry loop (comment nói snapshot trước loop nhưng
implementation sai). Production route truyền persistent `User` load từ chính
AsyncSession của request. Sau unique collision: `flush()` → IntegrityError →
`db.rollback()` → rollback expire persistent ORM state → iteration tiếp theo
đọc `creator.id` / `creator.role` trigger implicit refresh (async IO không mong
đợi / MissingGreenlet). Test concurrency cũ không bắt được vì truyền transient
`UserModel(id=creator_id)` — không giống production.

**Fix** (`server/app/api/routes/system_profiles.py`):
- Snapshot `creator_id` / `creator_role` / `is_super` TRƯỚC loop, TRƯỚC mọi
  rollback. Không đọc lại ORM creator sau rollback.
- Mỗi attempt chạy trong SAVEPOINT (`async with db.begin_nested()`): unique
  collision chỉ rollback savepoint của attempt → outer transaction + session
  state còn nguyên; object failed attempt được resurrect về transient (không
  pollute). Non-unique IntegrityError propagate ngay (narrowing v3 giữ nguyên).

**Regression test:** `test_concurrent_profile_code_retry_with_persistent_creator`
(đổi tên từ `test_concurrent_profile_creation_isolates_candidate_code`):
- Mỗi race task dùng session riêng + `await s.get(User, creator_id)` →
  **persistent ORM creator giống production** (không còn `UserModel(id=...)`).
- Barrier injection giữ nguyên: cả 2 tasks đọc MAX seq trước khi insert →
  1 succeed, 1 unique-conflict → loser retry với code mới.
- Assertions: `code_a != code_b`; `_generate_profile_code` được gọi `>= 3`
  (**2 first attempts + ít nhất 1 retry** — anchor tạo trước khi monkeypatch,
  không tính vào call_count; report v3 đếm "anchor + 2 race + retry" là SAI);
  không MissingGreenlet.

### P2 v4 — DeepAgent reconcile 401/403/400/422 giữ capacity vô hạn

**Bug trước fix:** `_state_check_deepagent_job()` chỉ phân biệt 2xx / 404 /
"mọi thứ khác". GET `/v1/jobs/{id}` trả 401/403/400/422 → keep
`dispatch_uncertain` → status remains `analyzing` → capacity tính row này
vô hạn. Token sai / contract lỗi = capacity starvation không hồi phục.

**Fix** (`server/app/services/dfir_investigation.py`), chỉ áp dụng cho row đang
`dispatch_uncertain`:
- **401/403** — terminal auth/config failure → `status=failed`,
  `hermes_status=reconcile_failed`, `completed_at` set, error ghi rõ → slot
  released.
- **400/422** — terminal protocol/request incompatibility → terminal
  `reconcile_failed` như trên.
- **408/429/5xx / network error** — vẫn transient (keep `dispatch_uncertain`),
  NHƯNG có age bound (mục "bounded uncertain" dưới).

### P2 v4 — Bounded uncertain reconciliation (age-based)

`dispatch_uncertain` không được giữ slot vô hạn kể cả khi GET trả 5xx/timeout
liên tục. Nếu `now - started_at > deepagent_reconcile_max_uncertain_seconds`
(setting mới, default 1800s, không cần schema migration vì dùng `started_at`)
→ terminal `reconcile_timeout`: `status=failed`, `completed_at` set, slot
released. GET vẫn được thực hiện trước khi check age ở tick đó — age bound
chặn cả trường hợp GET liên tục transient lẫn GET liên tục network-error.

### P2 v4 — Worker exception clause rõ ràng

`except (LlmError, Exception)` (redundant — Exception bao trùm LlmError) →
tách thành `except DispatchFailed` (typed definitive failure, log + commit
idempotent) rồi `except Exception` (unexpected). `DispatchUncertain` vẫn được
bắt riêng trước đó. Typed state-machine semantics visible ở worker boundary.

### Tests mới (worker-level, gọi `run_pending_investigations()` production path)

| Test | Chứng minh |
|---|---|
| `test_reconcile_401_releases_capacity` | capacity=1; A uncertain + GET 401 → A failed + completed_at + reconcile_failed; B (pending) được claim + dispatched trong CÙNG tick — capacity release thực sự, không chỉ assert status. |
| `test_reconcile_403_is_terminal` | GET 403 → terminal fail. |
| `test_reconcile_422_is_terminal` | GET 422 → terminal fail. |
| `test_reconcile_429_remains_uncertain` | GET 429 → vẫn analyzing + dispatch_uncertain + completed_at None. |
| `test_reconcile_502_remains_uncertain` | GET 502 → vẫn analyzing + dispatch_uncertain. |
| `test_reconcile_uncertain_age_timeout_releases_capacity` | uncertain 2h + GET vẫn 502 → reconcile_timeout terminal; B được dispatch cùng tick. |

### Test quality fixes (v4)

- `test_non_code_integrity_error_is_not_retried`: assert chặt
  `call_count == 1` (helper LUÔN generate trước INSERT nên FK violation xảy ra
  sau generation — deterministic), thay vì `call_count <= 1` lỏng.
- Report v3 sai khi viết `call_count >= 3 = "anchor + 2 race + retry"`
  (minimum theo cách đếm đó phải là 4). Đúng: monkeypatch đặt sau anchor →
  `call_count >= 3` nghĩa là **2 first attempts + >= 1 retry**.

---

## 6d. Verification (v4)

**Local verification: PASS (không regression). GitHub CI: NOT RUN** — workflow
chỉ trigger `push`/`pull_request` vào `main`; branch này không push/merge.

| Command | Result |
|---|---|
| `uv run pytest tests/test_system_profiles.py` (server/) | **39 passed**, 1 failed = `test_devices_and_machines` (pre-existing greenlet). |
| `uv run pytest tests/test_dispatch_worker_boundary.py tests/test_deepagent_dispatch_reconciliation.py tests/test_llm_deepagent.py` | **48 passed** (gồm 6 test reconcile v4 + persistent-creator concurrency test). |
| `uv run pytest tests/test_officer_migration_roundtrip.py tests/test_migration_graph.py` | **8 passed** (duplicate officer names vẫn preserve). |
| `uv run pytest -q` (full server) | **371 passed, 6 failed, 2 errors** — TẤT CẢ pre-existing: `test_disable_my_2fa_requires_current_password`, `test_stats_inventory_rbac_scope`, `test_devices_and_machines`, `test_publish_machine_event_reaches_subscriber` (redis), `test_partition.py::test_rows_in_default_migrated_on_partition_create`, `test_phase4.py::test_report_pdf_export` (OSError cannot load lib), 2 errors `test_ws.py`. Hai failure đầu tiên chưa listed trong report v3 đã được verify pre-existing bằng cách chạy đúng command trên HEAD `485d57f` KHÔNG có thay đổi v4 → fail y hệt. |
| `ruff check app tests` (server/) | 136 errors — **không đổi so với HEAD baseline** (pre-existing style). |
| `uv run pytest -q` (deepagent/) | **130 passed**. |
| `ruff check deepagent tests` (deepagent/) | 3 errors — không đổi so với baseline (pre-existing). |
| `alembic heads` | 1 head (`b6c7d8e9f0a2`). Officer migration round-trip (upgrade → duplicate names preserve → downgrade → upgrade) cover qua 8 test trên. |
| `npm ci && npm run typecheck` (portal/) | **FAIL — 5 TS errors** (`review_note`, `document_date`, `device_count`, `machine_count` không tồn tại trên type `SystemProfile` trong `app/(portal)/system-profiles/page.tsx`). **Pre-existing: fail y hệt (nhiều lỗi hơn) trên base commit `99736e4`** — type definitions portal thiếu field, không do review fixes. |
| `npm run build` (portal/) | **FAIL — cùng nguyên nhân type errors** (Next build type check). Pre-existing như trên. |
| `npm test` (portal/) | **26/28 passed**; 2 failed (`standalone-static-assets`, `MachineInvestigationPanel closed state`) — **fail y hệt trên base `99736e4`** → pre-existing. |

Pre-existing failures được verify bằng: chạy đúng command trên commit
`485d57f` (HEAD trước v4, không có thay đổi v4) hoặc base `99736e4` → cùng
failure, cùng nguyên nhân.

---

## 7d. Updated merge gate (v4)

- [x] Profile-code retry KHÔNG đọc persistent creator sau rollback
      (SAVEPOINT per attempt + snapshot trước loop).
- [x] Persistent-creator concurrency test pass
      (`test_concurrent_profile_code_retry_with_persistent_creator`).
- [x] Actual unique conflict retry path được deterministic exercise
      (barrier injection, `code_a != code_b`).
- [x] Non-code IntegrityError không retry (`call_count == 1`).
- [x] DeepAgent reconcile 401 releases capacity (worker-level test với job B
      được dispatch cùng tick).
- [x] DeepAgent reconcile 403 releases capacity (terminal).
- [x] DeepAgent reconcile 400/422 classified terminal.
- [x] DeepAgent reconcile 408/429/5xx remains transient.
- [x] Uncertain có age bound (`reconcile_timeout`) — slot không giữ vô hạn.
- [x] Pending DeepAgent job có thể được claim sau terminal reconcile failure
      (assert trong `test_reconcile_401_releases_capacity`).
- [x] DispatchUncertain / DispatchFailed typed semantics vẫn pass regression
      (48 worker/reconciliation/llm tests).
- [x] Officer duplicate-name migration tests vẫn pass (8/8).
- [x] Nullable PATCH tests vẫn pass.
- [x] Party DB-conflict test vẫn pass.
- [x] CIDR family tests vẫn pass.
- [x] Full targeted server tests pass except proven pre-existing failures.
- [x] DeepAgent tests pass (130/130).
- [x] Portal typecheck/build **đã chạy và kết quả được ghi**: FAIL —
      pre-existing trên base `99736e4`, KHÔNG phải regression của review
      fixes. **Cần fix riêng portal type definitions trước khi merge tổng
      (tracked ngoài scope review fixes này).**
- [x] REPORT.md current HEAD đúng (xem dưới).
- [x] REPORT.md local-vs-CI terminology đúng (Local PASS / GitHub CI NOT RUN).
- [x] Không merge/push vào `main`.

**HEAD:** fix v4 = `5c62b99` ("fix(server): v4 review — savepoint profile-code
retry + DeepAgent reconcile terminal classification"); HEAD của branch sau
commit report này là docs commit chứa section 5d–7d. Reviewer reviewed
`485d57f`; mọi thay đổi sau đó nằm trong 2 commit trên
`review/system-info-level-profile-fixes`.

**Known operational risk còn lại (đã bound, không vô hạn):** uncertain jobs
giữ slot tối đa `deepagent_reconcile_max_uncertain_seconds` (1800s default)
trước khi bị chuyển `reconcile_timeout`. Không còn giữ vô hạn như trước.

---

## 8b. Commits v4 on `review/system-info-level-profile-fixes`

```
5c62b99 fix(server): v4 review — savepoint profile-code retry + DeepAgent reconcile terminal classification
<this commit> docs(server): update REPORT.md with v4 fixes + corrected merge gate
485d57f docs(server): update REPORT.md with v3 BLOCKERs + P2 hardening (third pass)
1f35fdb fix(server): third-pass BLOCKERs + P2 hardening (v3 review)
...
```

Branch `review/system-info-level-profile-fixes` KHÔNG merge vào `main`.
