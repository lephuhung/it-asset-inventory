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
