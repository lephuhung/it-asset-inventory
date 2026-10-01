# TODO - Review/fix `feat/system-info-level-profile`

## Baseline
- Worktree: `.worktrees/review-system-info-level-profile` on branch `review/system-info-level-profile-fixes`
- Baseline test của `server/tests/test_system_profiles.py`: 23/24 pass; 1 pre-existing greenlet failure trên machine attach (không thuộc scope review).
- Migration graph tests: 2/2 pass.

## Findings confirmed (Phase 1: verification)
- [x] **P1-1** RBAC mutation scope CONFIRMED.
- [x] **P1-2** Approved dossier immutability CONFIRMED.
- [x] **P1-3** Alembic downgrade restore CONFIRMED.
- [x] **P1-4** DeepAgent budget split CONFIRMED.
- [x] **P1-5** Dispatch reconciliation CONFIRMED.
- [x] **P2-1** Timeline old level CONFIRMED.
- [x] **P2-3** Active device type CONFIRMED.
- [x] **P2-4** Profile code race CONFIRMED.

## Fixes implemented (Phase 2)

### P1-1 RBAC: split read vs mutation
- [x] Add `_get_profile_mutable(db, profile_id, user)` — admin only of own org, super admin of all.
- [x] Replace 35+ mutation callers with new helper (preserve 1 read site).
- [x] Regression test: `test_parent_org_admin_reads_but_cannot_mutate_child_profile`.

### P1-2 Immutability of approved dossier
- [x] Add `assert_profile_content_mutable(profile, user, *, action)` guard.
- [x] Apply guard to: device add/update/delete, machine attach/detach, party CRUD, application CRUD, ip-range CRUD, contacts attach/detach.
- [x] Super Admin bypass + timeline audit preserved.
- [x] Regression tests:
  - `test_approved_profile_blocks_org_admin_from_mutating_child_resources`
  - `test_rejected_profile_allows_org_admin_full_edit`

### P1-3 Alembic downgrade restore
- [x] Updated `b5c6d7e8f9a0` downgrade to restore `officer_*` columns + best-effort data migration back.
- [x] Migration tests: `test_officer_refactor_creates_no_extra_heads`, `test_officer_refactor_downgrade_restores_legacy_columns`, `test_officer_refactor_downgrade_migrates_data_back`.

### P1-4 DeepAgent budget split
- [x] Removed buggy `remaining_steps = max(max_steps - len(initial), 0)` slice — Tier-2 now uses `MAX_TIER2_STEPS` constant only.
- [x] Regression tests:
  - `test_graph_tier2_runs_even_when_initial_uses_full_budget`
  - `test_graph_tier2_capped_at_two_even_when_model_proposes_more`

### P1-5 Dispatch reconciliation
- [x] Classify errors: 4xx (non-408/429) → definitive; 5xx/408/429/timeout/connect-error → ambiguous.
- [x] On ambiguous: `hermes_status = "dispatch_uncertain"`, do NOT set `status = "failed"`.
- [x] `_state_check_deepagent_job` extended to reconcile: GET job on `dispatch_uncertain` → 2xx → `dispatched`; 404 → `recovery_required`.
- [x] Regression tests in `tests/test_deepagent_dispatch_reconciliation.py` (8 cases).

### P2-1 Timeline old level
- [x] Snapshot `old_level = profile.level` BEFORE setattr; emit using snapshot.
- [x] Regression test: `test_level_changed_timeline_logs_correct_old_value`.

### P2-3 Active device type
- [x] `_valid_device_type` → `is_active=True` filter (applied to all create/update).
- [x] Regression test: `test_inactive_device_type_cannot_be_used_for_new_device`.

### P2-4 Profile code race
- [x] New helper `_create_profile_with_unique_code`: bounded retry (5 attempts) on IntegrityError.
- [x] POST endpoint uses helper.
- [x] Regression test: `test_profile_code_generation_handles_concurrent_inserts`.

### P2-2 review_note reuse — keep as-is
- Field `review_note` được dùng cho approval/rejection. Implementation/fulfillment notes ghi vào `SystemProfileEvent` (timeline). Không cần migration DB để tách — API/UI có thể đọc từ timeline. Document hóa trong report.

## Verification results
- `server/tests/test_system_profiles.py`: 29/30 pass (1 pre-existing greenlet failure không liên quan).
- `server/tests/test_migration_graph.py`: 2/2 pass.
- `server/tests/test_officer_migration_roundtrip.py`: 3/3 pass.
- `server/tests/test_llm_deepagent.py`: 27/27 pass.
- `server/tests/test_deepagent_dispatch_reconciliation.py`: 8/8 pass.
- `deepagent/tests/`: 130/130 pass.
- `ruff check`: clean cho các file thay đổi.
- `alembic heads`: 1 head (`b6c7d8e9f0a2`), không tạo head mới.

## Remaining risks
- `tests/test_devices_and_machines` — pre-existing greenlet failure (machine attach path) — không nằm trong scope review này.
- Pre-existing `ruff` warnings (DTZ005, F841, etc.) trong test files — không thuộc scope.
- `tests/test_deepagent_dispatch_reconciliation.py` đã cover reconcile flow; cần integration test thực tế khi DeepAgent restart (đã có sẵn `test_missing_deepagent_job_is_requeued_after_restart`).