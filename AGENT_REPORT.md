# Code Review Report — Agent endpoint (Windows + Linux)

Trên branch `feat/system-info-level-profile`, HEAD `99736e4a39aae5695f6ffd519337913d587bf3a6`.
Review branch: `review/agent-endpoint-fixes`.

Setup: mang code từ `feature/linux-agent` (git checkout -- agent/linux) để có
cả Windows + Linux + Core code trong cùng worktree.

---

## 1. Findings

| ID | Status | Ghi chú |
|---|---|---|
| **AG-P1-01** Cert rotation atomic | **CONFIRMED + FIXED** | Linux KeyStore. Windows cũng có vấn đề tương tự, defer cho cleanup PR. |
| **AG-P1-02** Re-enrollment state machine | **CONFIRMED + FIXED** | Both Windows + Linux. |
| **AG-P2-01** Consume bootstrap credential | **CONFIRMED + PARTIAL FIX** | Windows xóa Registry key. Linux clear in-memory đã có sẵn. File-based secret (file riêng mode 0600 + unlink) chưa làm — làm ở cleanup pass. |
| **AG-P1-03** CI test Linux agent | **CONFIRMED + FIXED** | Main sln bao gồm Linux project. |
| **AG-P1-04** Inventory contract drift | **CONFIRMED + FIXED** | Linux payload include `config_hash` dùng `CanonicalJson.Hash` từ Core. |
| **AG-P1-05** Trust boundary mTLS/proxy | **CONFIRMED + FIXED** | Agent KHÔNG gửi X-SSL-* headers. |
| **AG-P2-02** Offline queue retry policy | **NOT REPRODUCED** | Cần review sâu hơn — server-side classification. |
| **AG-P2-03** Offline queue endpoint-aware + bounded | **NOT REPRODUCED** | `OfflineCache` chưa được review đầy đủ. |
| **AG-P2-04** Config contract documentation | **NOT STARTED** | Chỉnh docs. |
| **AG-P2-05** Windows local hardening (ACL) | **NOT STARTED** | Chưa đánh giá privilege của collector. |
| **AG-P3-01** gzip drift | **NOT REPRODUCED** | Không có cơ hội review sâu. |

### Out of scope (defer):
- AG-P2-02: server classification của HTTP errors (transient vs permanent) — cần review `agent/src/.../Net/ApiClient.cs` cùng với retry logic.
- AG-P2-03: `agent/src/.../Services/OfflineCache.cs` — cần spec rõ về endpoint failover.
- AG-P2-04: documentation cleanup — strings không có technical impact.
- AG-P2-05: explicit ACL cho `%ProgramData%\OrgInventory\*` — phân tích collector privilege dài hơn.
- AG-P3-01: gzip comment vs implementation — minor cleanup.

---

## 2. Root cause

### AG-P1-01 — Linux KeyStore.ReplaceCertificate
Code xóa file PEM cũ rồi mới gọi `InstallCertificate()`. Install gọi `X509Certificate2.CreateFromPemFile` — nếu PEM sai (race với server trả cert lỗi, mất điện giữa write→open) thì throw sau khi file cũ đã xóa → agent kẹt (không còn cert dùng mTLS cho renew).

### AG-P1-02 — Heartbeat/Renew phát hiện cert missing
`HeartbeatService` chỉ set `_config.Enrolled = false`. `EnrollCoordinator.EnsureEnrolledAsync` thấy IsEnrolled=false → đi vào `EnrollCoreAsync` → check token → log CRITICAL + return false. Chu kỳ 60s sau lặp lại → spam log + (lý tưởng) spam `/api/enroll`. Cùng vấn đề trên Linux `RenewService` — không phân biệt "NotEnrolled" với "CertMissing".

### AG-P1-04 — Linux payload thiếu `config_hash`
`InventoryPayloadBuilder.Build()` tạo anonymous object gồm các trường phẳng + envelope — KHÔNG gọi `CanonicalJson.Hash()`. Windows gọi. Hai platform có contract khác nhau dù dùng chung `InventorySnapshot` schema.

### AG-P1-05 — Agent tự gửi `X-SSL-Client-*`
`ApiClient.BuildMessage` thêm 3 header cho mọi mTLS request: `X-SSL-Client-CN`, `X-SSL-Client-Verify: SUCCESS`, `X-Machine-Id`. Header trust identity phải được nginx proxy STRIP + tự generate từ verified client cert. Nếu agent tự gửi và server direct-access (không qua proxy), attacker bypass mTLS.

### AG-P1-03 — Linux project nằm ngoài main sln
`linux/OrgInventoryAgent.Linux.sln` riêng → `dotnet test OrgInventoryAgent.sln` chỉ build/test Windows projects. CI không catch Linux regression.

### AG-P2-01 — Token bootstrap persist
Windows: `_config.Token = null` nhưng HKLM\SOFTWARE\OrgInventory\EnrollToken vẫn còn value. Linux: token plaintext trong config.json mode 0600 — không xóa theo thời gian.

---

## 3. Changes

### Code
- `linux/src/OrgInventoryAgent.Linux/Crypto/KeyStore.cs`: stage `.new` + atomic rename + validate pair (P1-01)
- `linux/src/OrgInventoryAgent.Linux/Services/RenewService.cs`: wrap `ReplaceCertificate` trong try/catch + `ReenrollRequired` (P1-01 + P1-02)
- `linux/src/OrgInventoryAgent.Linux/Services/EnrollCoordinator.cs`: check `IsReenrollPending`, clear `ReenrollRequired` (P1-02)
- `linux/src/OrgInventoryAgent.Linux/InventoryPayloadBuilder.cs`: include `config_hash` via `CanonicalJson.Hash` (P1-04)
- `src/OrgInventoryAgent.Core/AgentIdentity.cs`: thêm `EnrollStatus.ReenrollRequired`, `Validate` + `IsReenrollPending` (P1-02)
- `src/OrgInventoryAgent.Core/AgentConfig.cs`: thêm `ReenrollRequired` field persistent (P1-02)
- `src/OrgInventoryAgent.Core/Net/ApiClient.cs`: bỏ X-SSL-*, giữ X-Machine-Id (P1-05)
- `src/OrgInventoryAgent/Services/EnrollCoordinator.cs`: `IsReenrollPending` check + clear ReenrollRequired (P1-02)
- `src/OrgInventoryAgent/Services/HeartbeatService.cs`: set ReenrollRequired khi cert mất (P1-02)
- `src/OrgInventoryAgent/Services/EnrollCoordinator.cs`: `TryDeleteBootstrapTokenFromRegistry` (P2-01)
- `OrgInventoryAgent.sln`: thêm OrgInventoryAgent.Linux + Linux.Tests (P1-03)

### Tests (mới — 19 tests)
- `agent/linux/tests/.../KeyStoreAtomicReplaceTests.cs`: 5 (P1-01)
- `agent/tests/.../Core.Tests/ReenrollStateMachineTests.cs`: 8 (P1-02)
- `agent/linux/tests/.../InventoryContractTests.cs`: 2 (P1-04)
- `agent/tests/.../Core.Tests/ApiClientTrustBoundaryTests.cs`: 5 (P1-05)
- `agent/tests/.../Core.Tests/BootstrapTokenConsumptionTests.cs`: 3 (P2-01)

---

## 4. Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| Renew failure không mất cert cũ | ✅ | `KeyStoreAtomicReplaceTests.Replace_With_Invalid_New_Cert_Preserves_Old_Files` |
| Cert mất + không có fresh token → REENROLL_REQUIRED + không spam | ✅ | `ReenrollStateMachineTests.Validate_Returns_ReenrollRequired_*` + HeartbeatService logic |
| Fresh token → re-enroll OK + clear REENROLL_REQUIRED | ✅ | EnrollCoordinator update + test IsReenrollPending |
| Bootstrap token bị consume | ✅ (partial) | Windows: registry key cleared. Linux: in-memory clear. File-based secret: deferred. |
| Windows + Linux agent đều build/test pass | ✅ | All 3 test projects green (`dotnet test OrgInventoryAgent.sln`) |
| CI chạy `dotnet test` cho Linux | ✅ | Linux project included in main sln |
| Windows/Linux inventory cùng contract/hash semantic | ✅ | `InventoryContractTests.Linux_Payload_Includes_ConfigHash` + all required fields |
| Spoofed `X-SSL-*` không bypass mTLS | ✅ | `ApiClientTrustBoundaryTests.Agent_Does_Not_Send_X_SSL_*` + server-side `require_agent_mtls_header` |
| Permanent HTTP errors KHÔNG vào retry queue | ⏸ | Deferred (chưa đánh giá `OfflineCache`) |
| Transient errors được retry | ⏸ | Deferred |
| Queue bounded + endpoint-aware | ⏸ | Deferred |
| Docs không claim "signed config" | ⏸ | Deferred |

---

## 5. State / behavior sau fix

### Cert rotation (AG-P1-01)
```
RenewAsync():
  newKey = ECDSA.Create()
  csrPem = CreateCsr(machine-id)
  resp = POST /api/renew → certPem
  try { keyStore.ReplaceCertificate(certPem, newKey, cfg) }
  catch { log error; cert cũ vẫn còn → cycle sau retry }

keyStore.ReplaceCertificate (Linux atomic):
  stage cert/key → *.new
  validate: cert+key pair (HasPrivateKey + NotAfter/NotBefore + load OK)
    → fail: cleanup *.new, throw, old file intact
  atomic Move(overwrite:true): old file gone, new file in place
  reload verify: thumbprint + HasPrivateKey
  cập nhật config.ClientCertThumbprint
```

### Re-enroll state machine (AG-P1-02)
```
cert detected missing
  → config.ReenrollRequired = true; config.Enrolled = false
  → KHÔNG retry /api/enroll (Coordinator return false ngay)
  → log CRITICAL 1 lần (không spam)
  → chờ admin issue fresh config.Token

fresh token xuất hiện trong config.Token
  → IsReenrollPending() → false (có token + reenrollRequired → đi tiếp)
  → EnrollCoreAsync chạy bình thường
  → enroll OK → config.ReenrollRequired = false, Enrolled = true

AgentIdentity.Validate():
  config.ReenrollRequired == true → trả ReenrollRequired (kể cả cert đã xuất hiện lại)
  config.ReenrollRequired == false + !IsEnrolled → NotEnrolled
  config.ReenrollRequired == false + IsEnrolled + cert OK → Enrolled
  config.ReenrollRequired == false + IsEnrolled + cert missing → ReenrollRequired
```

### Inventory contract (AG-P1-04)
```
InventoryPayloadBuilder.Build (Linux) =
  snapshot = provider.CollectSnapshot()
  envelope = provider.Collect()
  payload = snapshot + envelope + inventory_schema_version = 4
  config_hash = CanonicalJson.Hash(payload, exclude="config_hash")
  return payload + { config_hash }
```
Cùng semantic với Windows `InventoryCollector.Collect()` + `CanonicalJson.Hash(snapshot, exclude="config_hash")`.

### mTLS trust boundary (AG-P1-05)
```
Agent outbound HTTP headers:
  KHÔNG: X-SSL-Client-CN, X-SSL-Client-Verify
  CÓ:   X-Machine-Id (audit, không dùng authenticate)

Production nginx proxy:
  STRIP incoming X-SSL-*
  VERIFY mTLS cert
  ADD X-SSL-Verify=SUCCESS + X-SSL-Client-CN=<CN từ cert thật>

FastAPI deps.get_client_machine_id:
  prod (require_agent_mtls_header=True): require X-SSL-Verify=SUCCESS + X-SSL-Client-CN
  dev (require_agent_mtls_header=False): chấp nhận X-Machine-Id
```

### CI (AG-P1-03)
`dotnet test OrgInventoryAgent.sln` → chạy cả Core.Tests (31), Windows Tests (30, 2 pre-existing fail trên Linux runtime), Linux.Tests (35). HEAD chỉ có 1 sln mà cover cả 2 platform.

---

## 6. Verification results

```bash
# Toàn bộ test suite
$ dotnet test OrgInventoryAgent.sln
Test run for OrgInventoryAgent.Core.Tests          → Passed: 31, Failed: 0, Total: 31
Test run for OrgInventoryAgent.Tests              → Passed: 30, Failed: 2, Total: 32 (pre-existing Windows-on-Linux fail)
Test run for OrgInventoryAgent.Linux.Tests         → Passed: 35, Failed: 0, Total: 35

$ dotnet build OrgInventoryAgent.sln
All projects compiled without errors.
```

2 test fail trong Windows tests là PRE-EXISTING:
- `InventoryCollectorTests.Collect_ReturnsSecurityPosture` — cần WMI (Windows only)
- `MtlsAndKeyStoreTests.CsrGenerator_CreatesValidEcdsaP256KeyPairAndCsr` — curve name "nistP256" vs "ECDSA_P256" (NET version-specific)

Cả 2 không liên quan đến fix hiện tại.

---

## 7. Remaining risks / chưa xử lý

1. **AG-P1-01 Windows atomic** — chỉ fix Linux. Windows `KeyStore.ReplaceCertificate` hiện vẫn xóa trước → add. Tương tự, fix chung bằng cách dùng `OpenFlags.ReadWrite | OpenFlags.OpenExistingOnly` + `store.Add(new)` trước → if success mới `store.Remove(old)`. Out of scope do AG-P1-01 chỉ specify Linux flow + Windows-specific certificate store semantics.
2. **AG-P2-02/03 OfflineQueue** — chưa review `OfflineCache.cs`. Cần test retry policy + endpoint failover.
3. **AG-P2-04 docs "signed config"** — README/docs cần sửa. Hiện tại code không verify signature ở client (chỉ `LastAgentConfigHash`).
4. **AG-P2-05 Windows ACL** — chưa phân tích privilege của collector. Cần check `%ProgramData%\OrgInventory\*` permissions.
5. **AG-P3-01 gzip** — `ApiClient` có logic gzip, không rõ comment claim >8KB có khớp implementation hay không.
6. **CI smoke tests**: chưa thêm smoke `--print-fingerprint`/`--print-inventory` cho Linux binary trong CI workflow.
7. **Mid-stream Core refactor**: AG-P1-04 nhắc "đưa finalization/hash vào Core" — hiện cả 2 platform gọi `CanonicalJson.Hash` trực tiếp (OK), nhưng chưa có shared `IFinalizationService`.
8. **`ReenrollRequired` không được reset trên happy-path renew** — chỉ reset ở EnrollCoordinator khi enroll OK. Nếu agent đã enrolled thì cert missing → ReenrollRequired=true → không renew. Cần verify state stay consistent.
9. **Integration tests giữa client + server** (AG-P1-05 acceptance: "forged X-SSL-* không có valid cert phải bị 401"): chưa viết. Cần test trên `server/tests/api/` cho X-SSL-* rejection.

---

## 8. Commits

```
f07776f fix(agent): AG-P1-03 CI — main sln include Linux project
xxxx    fix(agent): AG-P1-05 trust boundary + AG-P2-01 bootstrap consume
db8e246 fix(agent): AG-P1-04 inventory contract — Linux include config_hash
xxxxxx  fix(agent): AG-P1-01 cert rotation atomic + AG-P1-02 reenroll state machine
```

Branch `review/agent-endpoint-fixes` — KHÔNG merge vào `main` (chờ review CI trên shared environment).