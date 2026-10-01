# TODO - Review/fix agent endpoint trên `feat/system-info-level-profile`

## Setup
- Worktree: `.worktrees/feat-agent-endpoint-review` trên branch `review/agent-endpoint-fixes`
- Bring in code từ `feature/linux-agent` (git checkout, không merge) — Windows + Linux + Core đều có
- Baseline: Linux 28/28 pass, Core 15/15 pass, builds clean.

## Findings đã verify (Phase 1)
- [ ] **AG-P1-01** Cert rotation atomic (Windows + Linux)
- [ ] **AG-P1-02** Re-enrollment state machine
- [ ] **AG-P2-01** Consume bootstrap credential
- [ ] **AG-P1-03** CI test Linux agent
- [ ] **AG-P1-04** Inventory contract Windows/Linux drift + config_hash semantic
- [ ] **AG-P1-05** mTLS trust boundary (agent KHÔNG tự gửi X-SSL-*)
- [ ] **AG-P2-02** Offline queue retry policy (chỉ transient)
- [ ] **AG-P2-03** Offline queue endpoint-aware + bounded
- [ ] **AG-P2-04** Config contract documentation
- [ ] **AG-P2-05** Windows local hardening (ACL)
- [ ] **AG-P3-01** gzip drift

## Thứ tự fix (theo request):
`AG-P1-01 → AG-P1-02 + AG-P2-01 → AG-P1-03 → AG-P1-04 → AG-P1-05 → offline queue/hardening → cleanup`

## Acceptance criteria:
- [ ] Renew failure không mất cert cũ
- [ ] Cert mất + không có fresh token → REENROLL_REQUIRED + không gọi /api/enroll liên tục
- [ ] Fresh token → re-enroll OK + clear REENROLL_REQUIRED
- [ ] Bootstrap token bị consume (Windows Registry / Linux file)
- [ ] Windows + Linux agent đều build/test pass
- [ ] CI chạy `dotnet test` cho Linux
- [ ] Windows/Linux inventory cùng contract/hash semantic
- [ ] Spoofed `X-SSL-*` không bypass mTLS
- [ ] Permanent HTTP errors KHÔNG vào retry queue
- [ ] Transient errors được retry
- [ ] Queue bounded + endpoint-aware (path + EndpointManager)
- [ ] Docs không claim "signed config"

Không merge vào main — chỉ là base cho review.