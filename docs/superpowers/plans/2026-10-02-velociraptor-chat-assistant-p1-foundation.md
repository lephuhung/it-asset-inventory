# Chat Assistant — P1 Security/Integration Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend + `chatagent` container foundation for the in-system chat assistant: durable turn lifecycle, audited read-only inventory access, fail-closed Velociraptor read tools, HMAC capabilities, and shared crash-safe token budget — without the portal UI.

**Architecture:** A new `chatagent` FastAPI/LangGraph container runs a bounded ReAct loop. It holds no DB credentials; inventory queries are mediated by the backend via internal endpoints, Velociraptor runs read-only over `mcp-velociraptor`, and every query is audited by the backend. The backend owns conversation/turn state, HMAC turn capabilities, budget reservations, and the audit hash-chain.

**Tech Stack:** FastAPI, SQLAlchemy async/PostgreSQL, Alembic, Redis, pytest/pytest-asyncio, httpx; `chatagent`: FastAPI, uvicorn, langgraph, langchain-openai, langchain-mcp-adapters, mcp, pydantic-settings.

**Spec:** `docs/superpowers/specs/2026-10-02-velociraptor-chat-assistant-design.md`

## Global Constraints

- Read-only only: no kill/quarantine/YARA/upload/`collect_file`, no DDL/DML, no state-changing tools.
- Only SuperAdmin; internal endpoints require the service token; capability is HS256, `aud="chat-internal"`, expiry ≤300s, turn-scoped.
- `machine_id` is never hash-bound; `machine_ref` (immutable) is. `audit_log.id` is INTEGER — chat audit refs are INTEGER.
- Audit is append-only hash-chain; no raw SQL/secret in audit or logs; `append_audit` callers must commit.
- Every budget reserve/settle takes `pg_advisory_xact_lock(hash('budget:'||budget_date))`.
- Error format: `[<category>] <hint> [HTTP <code>]`, no raw exception/prompt/evidence.
- `chatagent` receives only `CHATAGENT_*` env; never the root `.env`.
- mcp-velociraptor is pinned to `9b3c4b3a590029390e88049896a473d7f909c0ce`; its runtime behavior must be verified before enabling its tools.
- Platform: Python 3.12; PostgreSQL 16; Redis 7.

---

## File Structure

**Backend (create):**
- `server/app/core/chat_capability.py` — HS256 capability + completion token sign/verify.
- `server/app/core/egress.py` — private-host validation + pinned-IP transport helper.
- `server/app/services/budget.py` — `token_reservations` reserve/settle.
- `server/app/services/chat_turns.py` — turn state machine + completion winner.
- `server/app/services/chat_inventory.py` — structured inventory tools + read-only SQL guardrail.
- `server/app/schemas/chat.py` — chat DTOs.
- `server/app/api/routes/chat.py` — public `/api/chat` routes + SSE.
- `server/app/api/routes/chat_internal.py` — `/api/internal/chat` routes.
- `server/alembic/versions/<rev>_chat_assistant.py` — chat tables + audit_log changes.
- `server/alembic/versions/<rev>_chat_ro_views.py` — `chat_ro` role, engine pool, minimized views.

**Backend (modify):**
- `server/app/db/models.py` — 6 models + `AuditLog.details/hash_version`.
- `server/app/core/audit.py` — advisory serialization + versioned hash + `details`.
- `server/app/services/llm.py`, `server/app/api/routes/llm_dfir.py` — egress validator.
- `server/app/services/dfir_investigation.py` — shared budget adoption.
- `server/app/services/velociraptor.py` — `search_clients_page`.
- `server/app/main.py` — include routers.

**ChatAgent (create):**
- `chatagent/pyproject.toml`, `chatagent/Dockerfile`
- `chatagent/chatagent/{__init__,config,api,agent,tools,backend_client,vql_policy}.py`
- `chatagent/tests/...`

**Infra (modify):** `docker-compose.yml`, `.env.example`, `scripts/gen-env-example.py`, `build-all.sh`.

---

## Task 1: Harden the audit hash-chain (serialize + version + details)

**Files:**
- Modify: `server/app/db/models.py` (`AuditLog`: add `details: JSONB`, `hash_version: SmallInteger default 1`)
- Modify: `server/app/core/audit.py`
- Create: `server/alembic/versions/<rev>_audit_hash_version_details.py`
- Test: `server/tests/test_audit_chain.py`

**Interfaces:**
- Produces: `_content_hash_v1(action, target, actor, ts) -> str`, `_content_hash_v2(action, target, actor, ts, request_id, machine_ref, details) -> str`, `verify_chain(db) -> bool` dispatch by `hash_version`; `append_audit(..., details: dict | None = None)`.

- [ ] **Step 1: Write failing tests** — mixed v1/v2 verification and concurrency.

```python
# server/tests/test_audit_chain.py
import asyncio
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.audit import append_audit, verify_chain, _content_hash_v1, _content_hash_v2

@pytest.mark.asyncio
async def test_v1_row_still_verifies(db_session):
    # Insert a legacy row manually with hash_version=1 and the v1 formula.
    from app.db.models import AuditLog
    from datetime import UTC, datetime
    ts = datetime.now(UTC)
    row = AuditLog(action="legacy.action", target="t", actor="a", ts=ts,
                   content_hash=_content_hash_v1("legacy.action", "t", "a", ts),
                   hash_version=1)
    db_session.add(row)
    await db_session.commit()
    assert await verify_chain(db_session) is True

@pytest.mark.asyncio
async def test_v2_hashes_details_and_machine_ref(db_session):
    await append_audit(db_session, action="chat.query.inventory", actor="u",
                       target="mc", details={"tool": "inventory_search", "machine_ref": "WS-01"})
    await db_session.commit()
    assert await verify_chain(db_session) is True

@pytest.mark.asyncio
async def test_concurrent_appends_stay_linear(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def one(i):
        async with maker() as s:
            await append_audit(s, action=f"x{i}", actor="u", target="t")
            await s.commit()

    await asyncio.gather(*(one(i) for i in range(8)))
    async with maker() as s:
        assert await verify_chain(s) is True
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd server && .venv/bin/pytest tests/test_audit_chain.py -v`
Expected: FAIL (`details`/`hash_version` attribute or v2 helpers missing).

- [ ] **Step 3: Add model columns**

```python
# server/app/db/models.py (AuditLog)
details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
hash_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
```

- [ ] **Step 4: Implement versioned hash + advisory serialization in `audit.py`**

```python
def _content_hash_v1(action, target, actor, ts) -> str:
    payload = {"action": action, "target": target, "actor": actor, "ts": ts.isoformat()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _machine_ref(details: dict | None) -> str:
    return str((details or {}).get("machine_ref") or "")

def _content_hash_v2(action, target, actor, ts, request_id, details) -> str:
    payload = {
        "v": 2, "action": action, "target": target, "actor": actor, "ts": ts.isoformat(),
        "request_id": request_id, "machine_ref": _machine_ref(details), "details": details or {},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

async def append_audit(db, *, action, actor=None, target=None, ip=None, request_id=None,
                       machine_id=None, details=None) -> AuditLog:
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK_KEY})
    ts = datetime.now(UTC)
    prev = await get_last_hash(db)
    ch = _content_hash_v2(action, target, actor, ts, request_id, details)
    entry = AuditLog(actor=actor, action=action, target=target, ts=ts, ip=ip,
                     prev_hash=prev, content_hash=ch, request_id=request_id,
                     machine_id=machine_id, details=details, hash_version=2)
    db.add(entry)
    await db.flush()
    return entry
```

`verify_chain` recomputes each row using its own `hash_version` and checks `prev_hash` linkage.

- [ ] **Step 5: Migration**

```python
op.add_column("audit_log", sa.Column("details", postgresql.JSONB(), nullable=True))
op.add_column("audit_log", sa.Column("hash_version", sa.SmallInteger(), nullable=False, server_default="1"))
```

- [ ] **Step 6: Run tests, verify pass**

Run: `cd server && .venv/bin/pytest tests/test_audit_chain.py tests/test_audit.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add server/app/core/audit.py server/app/db/models.py server/alembic/versions/<rev>_audit_hash_version_details.py server/tests/test_audit_chain.py
git commit -m "feat(audit): serialize appends, versioned hash, structured details"
```

---

## Task 2: Chat database schema

**Files:**
- Modify: `server/app/db/models.py` (add `ChatConversation`, `ChatTurn`, `ChatMessage`, `ChatToolCall`, `ChatAuditIntent`, `TokenReservation`)
- Create: `server/alembic/versions/<rev>_chat_assistant.py`
- Test: `server/tests/test_chat_models.py`

**Interfaces:**
- Produces ORM classes with the exact columns/FKs from spec §§"Hợp đồng dữ liệu"; partial unique index `uq_chat_turn_active`.

- [ ] **Step 1: Write failing constraint tests**

```python
# server/tests/test_chat_models.py
import pytest
from sqlalchemy.exc import IntegrityError
from app.db.models import ChatConversation, ChatTurn

@pytest.mark.asyncio
async def test_only_one_active_turn_per_conversation(db_session, make_conversation):
    conv = await make_conversation()
    db_session.add(ChatTurn(conversation_id=conv.id, actor_id=conv.created_by, request_id=uuid4()))
    await db_session.commit()
    db_session.add(ChatTurn(conversation_id=conv.id, actor_id=conv.created_by, request_id=uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

- [ ] **Step 2: Run test, verify it fails** (`cd server && .venv/bin/pytest tests/test_chat_models.py -v`).

- [ ] **Step 3: Add models** per spec DDL (use `BigInteger` for `audit_intent_id/audit_outcome_id`? No — `Integer` to match `audit_log.id`; use `Integer` + FK).

```python
class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String(200))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # message_count, last_message_at, archived, created_at, updated_at
```

`ChatTurn` includes `completion_token_hash`, `completion_committed_at`; add `Index("uq_chat_turn_active", "conversation_id", unique=True, postgresql_where=text("status IN ('pending','streaming')"))`.

`ChatMessage` has the composite FK `(conversation_id, turn_id) -> chat_turns(conversation_id, id) ON DELETE CASCADE` and `ck_chat_msg_turn`.
`ChatAuditIntent` has `UNIQUE(turn_id, tool_call_id)`, no FK to chat tables.
`TokenReservation` has `UNIQUE(scope, operation_id)`.

- [ ] **Step 4: Migration** creates the 6 tables in order with indexes/FKs.

- [ ] **Step 5: Run tests, verify pass.**

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(db): chat assistant schema (conversations, turns, messages, tool_calls, audit_intents, token_reservations)"
```

---

## Task 3: Read-only inventory pool + minimized views

**Files:**
- Create: `server/alembic/versions/<rev>_chat_ro_views.py`
- Modify: `server/app/db/session.py` (add `chat_ro_engine`, `get_chat_ro_session`)
- Test: `server/tests/test_chat_ro_views.py`

**Interfaces:**
- Produces: `get_chat_ro_session()` async generator using role `inventory_chat_ro`; views `v_chat_machines`, `v_chat_machine_detail`, `v_chat_org_stats`, `v_chat_software`, `v_chat_hardware`, `v_chat_alerts`.

- [ ] **Step 1: Write failing test** — the role cannot read `users` and can read `v_chat_machines`; PII columns absent from `v_chat_*`.

```python
@pytest.mark.asyncio
async def test_chat_ro_cannot_read_users(chat_ro_session):
    with pytest.raises(Exception):
        await chat_ro_session.execute(text("SELECT email FROM users LIMIT 1"))

@pytest.mark.asyncio
async def test_chat_ro_machines_view_has_no_pii(chat_ro_session):
    cols = (await chat_ro_session.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='v_chat_machines'"))).scalars().all()
    assert not {"email", "phone", "id_number", "password_hash"} & set(cols)
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Migration** — create role + schema + views with minimized projections (resolve `MachineCurrent`/`MachineSoftware` JSONB; EOL derived or `NULL AS eol_flag`; alert source chosen from `DfirAlert.resolved`). Grant only `USAGE` on `chat_ro_views` + `SELECT` on those views; `NOINHERIT`; no membership.

```sql
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='inventory_chat_ro') THEN
  CREATE ROLE inventory_chat_ro LOGIN PASSWORD :'ro_password' NOINHERIT; END IF; END $$;
CREATE SCHEMA IF NOT EXISTS chat_ro_views;
CREATE OR REPLACE VIEW chat_ro_views.v_chat_machines AS
  SELECT id, hostname, org_name, os_name, os_version, status, last_seen, NULL::boolean AS eol_flag
  FROM machine_current;  -- final projection fixed during implementation
GRANT USAGE ON SCHEMA chat_ro_views TO inventory_chat_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA chat_ro_views TO inventory_chat_ro;
```

- [ ] **Step 4: Add engine** reading `CHAT_RO_DATABASE_URL`, `SET search_path = chat_ro_views, pg_catalog`, `RESET ALL` per checkout, `statement_timeout` enforced by service layer.

- [ ] **Step 5: Run tests, verify pass.**

- [ ] **Step 6: Commit** `feat(db): chat_ro role, pool and minimized inventory views`.

---

## Task 4: Capability + completion token

**Files:**
- Create: `server/app/core/chat_capability.py`
- Test: `server/tests/test_chat_capability.py`

**Interfaces:**
- `sign_capability(actor_id, conversation_id, turn_id, request_id, ttl=300) -> str`
- `verify_capability(token) -> CapabilityClaims` (raises `CapabilityError`)
- `hash_completion_token(token) -> str`, `new_completion_token() -> str`
- `CapabilityClaims` fields: `actor_id`, `conversation_id`, `turn_id`, `request_id`.

- [ ] **Step 1: Write failing tests** — round-trip, wrong audience, expired, tampered, wrong secret.

```python
def test_round_trip():
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4())
    c = verify_capability(tok)
    assert c.conversation_id and c.turn_id

def test_expired_rejected(monkeypatch):
    tok = sign_capability(uuid4(), uuid4(), uuid4(), uuid4(), ttl=-1)
    with pytest.raises(CapabilityError):
        verify_capability(tok)
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** with `PyJWT` HS256, `aud="chat-internal"`, `iss="backend"`, key `settings.chat_context_secret`; `hash_completion_token = sha256(token).hexdigest()`. DB checks (turn status, conversation owner) live in the route dependency, not here.

- [ ] **Step 4: Add settings** `chat_context_secret`, `chat_completion_grace_seconds=120`, `resolver_consistency_window_seconds=5`.

- [ ] **Step 5: Run tests, verify pass.**

- [ ] **Step 6: Commit** `feat(chat): HS256 turn capability + completion token`.

---

## Task 5: Private-host egress validation at every executor

**Files:**
- Create: `server/app/core/egress.py`
- Modify: `server/app/services/llm.py`, `server/app/api/routes/llm_dfir.py`, `deepagent/deepagent/analysis_model.py`
- Test: `server/tests/test_egress.py`

**Interfaces:**
- `resolve_private_host(url: str) -> tuple[str, str]` returns `(host, pinned_ip)`; raises `EgressError` for public hosts.
- `assert_llm_egress(base_url: str, allow_cloud: bool) -> None`.

- [ ] **Step 1: Write failing tests** — `localhost.attacker.example` rejected when `allow_cloud=False`; private IP accepted; redirect to public rejected; IPv6 loopback accepted.

```python
def test_substring_host_not_treated_private():
    with pytest.raises(EgressError):
        assert_llm_egress("http://localhost.attacker.example/v1", allow_cloud=False)

def test_private_ip_allowed():
    assert_llm_egress("http://10.0.0.5:11434/v1", allow_cloud=False)

def test_public_rejected_when_cloud_off():
    with pytest.raises(EgressError):
        assert_llm_egress("https://api.openai.com/v1", allow_cloud=False)
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** using `urllib.parse`, `socket.getaddrinfo`, `ipaddress`; accept loopback/private/link-local/CGNAT v4+v6; return pinned IP; `allow_cloud=True` bypasses but still records it.

- [ ] **Step 4: Integrate** — call `assert_llm_egress` in `LlmClient` setup (`llm.py`), replace `_is_private_host` in `llm_dfir.py`, and add the same check in `deepagent/analysis_model.py` before `ChatOpenAI`. Pass pinned IP via a custom `http_client`/`transport` preserving Host/SNI.

- [ ] **Step 5: Run tests, verify pass** (`server/tests/test_egress.py` + existing llm tests).

- [ ] **Step 6: Commit** `feat(security): private-host egress validation at all executors`.

---

## Task 6: Shared crash-safe token budget

**Files:**
- Create: `server/app/services/budget.py`
- Modify: `server/app/services/dfir_investigation.py`
- Test: `server/tests/test_budget.py`

**Interfaces:**
- `reserve(db, *, scope, operation_id, association_id, envelope, budget) -> Reservation | None` (None = over budget)
- `settle(db, *, scope, operation_id, actual=None) -> None`
- `charged(db, budget_date) -> int`

- [ ] **Step 1: Write failing tests** — concurrent distinct-key admissions at the limit; unknown charges full envelope; settle idempotent; rollover by date.

```python
@pytest.mark.asyncio
async def test_admission_never_exceeds_budget(engine):
    budget = 100
    results = await asyncio.gather(*[
        reserve_for(engine, op=uuid4(), envelope=30, budget=budget) for _ in range(5)])
    assert sum(r is not None for r in results) <= 3  # never > 100/30

@pytest.mark.asyncio
async def test_unknown_charges_envelope(db_session):
    r = await reserve(db_session, scope="chat_turn", operation_id=uuid4(), association_id=None,
                      envelope=30, budget=1000)
    await settle(db_session, scope="chat_turn", operation_id=r.operation_id, actual=None)
    assert await charged(db_session, date.today()) == 30
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** with advisory lock, charged invariant, `INSERT ... ON CONFLICT (scope, operation_id)`.

```python
async def reserve(db, *, scope, operation_id, association_id, envelope, budget):
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('budget:' || :d))"), {"d": str(_utc_today())})
    if await charged(db, _utc_today()) + envelope > budget:
        return None
    r = TokenReservation(scope=scope, operation_id=operation_id, association_id=association_id,
                         budget_date=_utc_today(), reserved=envelope, state="reserved")
    db.add(r)
    await db.flush()
    return r
```

- [ ] **Step 4: Adopt in investigation** — reserve before local analysis (`:1087`), before DeepAgent dispatch (`:664-682`), and for each `chat_with_llm` Q&A (`:1120-1169`) with a fresh `operation_id`; settle on success/failure/cancel; remove direct `tokens_used_today` read-modify-write.

- [ ] **Step 5: Run tests, verify pass** (new + existing investigation tests that don't require live services).

- [ ] **Step 6: Commit** `feat(budget): shared crash-safe token reservations for chat and investigations`.

---

## Task 7: Completeness-preserving SearchClients adapter

**Files:**
- Modify: `server/app/services/velociraptor.py`
- Test: `server/tests/test_velociraptor_search.py`

**Interfaces:**
- `async def search_clients_exact(self, hostname: str) -> list[str]` — returns all matching `client_id`s, or raises `VelociraptorError` if `total` unknown/incomplete.

- [ ] **Step 1: Write failing tests** — duplicate across pages; unknown total fails; premature empty page fails.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** by iterating `SearchClients` pages (offset += page size) until offset >= total; normalize both operands with the same function; raise on inconsistency.

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Commit** `feat(velociraptor): completeness-preserving exact client search`.

---

## Task 8: Turn lifecycle service

**Files:**
- Create: `server/app/services/chat_turns.py`
- Test: `server/tests/test_chat_turns.py`

**Interfaces:**
- `create_turn(db, conversation, actor, machine_id, machine_ref, idempotency_key) -> ChatTurn`
- `claim_turn(db, turn_id) -> ChatTurn | None`
- `complete_turn(db, turn_id, *, content, usage, finish_reason, content_digest) -> CompletionResult`
- `cancel_turn(db, turn_id, actor) -> TurnStatus`
- `recover_stale_turns(db) -> int`

- [ ] **Step 1: Write failing tests** — active-turn 409; idempotent same content; conflicting content; `error→failed`; `canceled→canceled`; late output within grace keeps terminal status; late output after grace rejected.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** CAS on `completion_committed_at`, single transaction (message + status + audit + budget settle).

```python
async def complete_turn(db, turn_id, *, content, usage, finish_reason, content_digest):
    turn = await _lock_turn(db, turn_id)
    if turn is None:
        return CompletionResult(status="not_found")
    if turn.completion_committed_at is None:
        if turn.status in ("pending", "streaming"):
            turn.status = {"stop": "completed", "length": "completed",
                           "canceled": "canceled", "error": "failed"}[finish_reason]
        elif _within_grace(turn):
            pass  # keep terminal status; late output still persisted
        else:
            return CompletionResult(status="late_expired")
        db.add(ChatMessage(conversation_id=turn.conversation_id, turn_id=turn.id, role="assistant",
                           content=content, output_tokens=usage.get("output_tokens")))
        turn.completion_committed_at = datetime.now(UTC)
        await settle(db, scope="chat_turn", operation_id=turn.id, actual=usage.get("total_tokens"))
        return CompletionResult(status="ok")
    if turn.content_digest == content_digest:
        return CompletionResult(status="idempotent")
    return CompletionResult(status="conflict")
```

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Commit** `feat(chat): durable turn lifecycle with completion winner`.

---

## Task 9: Inventory tools + SQL guardrail service

**Files:**
- Create: `server/app/services/chat_inventory.py`
- Test: `server/tests/test_chat_inventory.py`

**Interfaces:**
- `async def run_tool(session, tool: str, params: dict) -> ToolResult`
- `async def run_sql(session, sql: str, max_rows: int) -> ToolResult`
- `validate_sql(sql: str) -> str` (returns normalized SQL; raises `SqlGuardrailError`)

- [ ] **Step 1: Write failing tests** — reject DML/DDL/multi-statement/`pg_catalog`/function not in registry; alias cannot expose PII; timeout/row cap.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** allowlist of tools → fixed parameterized queries over `v_chat_*`; SQL validator + single statement, `SET TRANSACTION READ ONLY`, `statement_timeout`, row/byte caps, `sha256(normalized_sql)` for audit.

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Commit** `feat(chat): inventory tool service with read-only SQL guardrail`.

---

## Task 10: Internal chat routes (inventory + audit + complete)

**Files:**
- Create: `server/app/api/routes/chat_internal.py`
- Modify: `server/app/main.py`
- Test: `server/tests/test_chat_internal.py`

**Interfaces:**
- Endpoints from spec §"Nội bộ"; `deps.require_service_token`, `deps.require_capability` (active turn), `deps.require_intent` (outcome/reconcile).

- [ ] **Step 1: Write failing tests** — capability required for query/intent; outcome works with expired capability but valid intent; duplicate intent does not authorize re-execution; different identity → 409; reconcile closes to `unknown`.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** routes; audit intent/outcome via `append_audit` with `details`; return `executed: true` on duplicate intent.

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Commit** `feat(chat): internal inventory/audit/completion routes`.

---

## Task 11: Public chat routes + SSE

**Files:**
- Create: `server/app/schemas/chat.py`, `server/app/api/routes/chat.py`
- Modify: `server/app/main.py`
- Test: `server/tests/test_chat_routes.py`

**Interfaces:**
- Endpoints from spec §"Public"; SSE streamer proxies `chatagent /v1/chat` and writes audit per tool event.

- [ ] **Step 1: Write failing tests** — ownership 404; create/list/detail/patch/delete; send returns `text/event-stream` and persists assistant message on completion; second send 409; cancel.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** routes + `StreamingResponse`, iterating agent SSE and relaying while persisting audit; delegate final persistence to Task 8.

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Commit** `feat(chat): public chat API with SSE streaming`.

---

## Task 12: ChatAgent skeleton + config

**Files:**
- Create: `chatagent/pyproject.toml`, `chatagent/chatagent/{__init__,config,api}.py`
- Test: `chatagent/tests/test_api.py`

**Interfaces:**
- `Settings` (env prefix `CHATAGENT_`), `GET /healthz`, `POST /v1/chat` (501 stub until Task 15).

- [ ] **Step 1: Write failing test** — `GET /healthz` returns 200 `{"status":"ok"}`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** FastAPI app + pydantic-settings (`service_token`, `backend_url`, `backend_api_key`, timeouts, `max_tool_calls`).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(chatagent): service skeleton and settings`.

---

## Task 13: Fail-closed VQL validator

**Files:**
- Create: `chatagent/chatagent/vql_policy.py`
- Test: `chatagent/tests/test_vql_policy.py`

**Interfaces:**
- `validate_vql(query: str) -> None` raises `VqlPolicyError`.

- [ ] **Step 1: Write failing tests** — `SELECT collect_client(...) FROM scope()` rejected; nested side-effect rejected; alias/comment obfuscation rejected; `SELECT * FROM clients()` accepted.

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** closed tokenizer/AST: one `SELECT`/`WITH`, allowlisted server-side plugins, allowlisted functions, reject side-effect functions anywhere.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(chatagent): fail-closed VQL validator`.

---

## Task 14: ChatAgent tool registry + backend client

**Files:**
- Create: `chatagent/chatagent/backend_client.py`, `chatagent/chatagent/tools.py`
- Test: `chatagent/tests/test_tools.py`

**Interfaces:**
- `BackendClient.inventory_query/tool`, `.sql`, `.audit_intent`, `.audit_outcome`, `.complete`
- `build_tools(...)` returns typed tools with code-owned arguments; startup schema check vs bridge.

- [ ] **Step 1: Write failing tests** — every Velociraptor collection call writes intent before execution and outcome after; no model-supplied artifact parameters; alias/schema mismatch fails startup.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** httpx client with service token + capability headers; tool registry mapping to bridge names; VQL validator gate.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(chatagent): tool registry and audited backend client`.

---

## Task 15: ChatAgent ReAct loop + SSE + cancel/status/complete

**Files:**
- Create: `chatagent/chatagent/agent.py`
- Modify: `chatagent/chatagent/api.py`
- Test: `chatagent/tests/test_agent.py`

**Interfaces:**
- `POST /v1/chat` streams `start|tool_start|tool_result|token|usage|done|error`; `GET /v1/chat/{turn_id}/status`; `POST /v1/chat/{turn_id}/cancel`.

- [ ] **Step 1: Write failing tests** — bounded ≤ max tool calls; tool output wrapped `<untrusted_tool_output>`; cancel aborts loop; always calls `.complete` on terminal (including error); SSE event order.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** LangGraph/ReAct loop with per-tool timeout, truncation, `llm_runtime` egress validation, cancel registry.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(chatagent): bounded ReAct loop with SSE and lifecycle endpoints`.

---

## Task 16: Deployment wiring

**Files:**
- Create: `chatagent/Dockerfile`
- Modify: `docker-compose.yml`, `.env.example`, `scripts/gen-env-example.py`, `build-all.sh`
- Test: `server/tests/test_compose_chatagent.py` (config assertions)

**Interfaces:**
- Compose service `chatagent` (no published port) with only `CHATAGENT_*` env; Dockerfile clones mcp-velociraptor at pinned SHA.

- [ ] **Step 1: Write failing test** — parse `docker-compose.yml`, assert `chatagent` has no `ports:` and no `env_file` referencing root `.env`, and `MCP_VELOCIRAPTOR_REF` is the pinned SHA.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** Dockerfile, compose service on `inventory-net`, env entries + generator.
- [ ] **Step 4: Run test, verify pass.**
- [ ] **Step 5: Commit** `feat(deploy): chatagent container wiring with isolated env`.

---

## Self-Review

- **Spec coverage:** Audit F2/F6/R2/R3 → T1,T10; DB F12/R1/R2 → T2; SQL F4/R5 → T3,T9; capability F3/complete V3-3 → T4,T8,T15; egress R7/V3-6 → T5; budget R8/V3-7 → T6; target resolution V3-5/V6 → T7; VQL F1 → T13; collection F9/R6 → T14; turn F7/R4 → T8,T11,T15; admission F11 → T6,T11; env F5 → T16. P2 (portal) deliberately excluded; write a separate plan.
- **Placeholders:** none intentionally; implementers read the spec for exact projection/view and route field lists.
- **Type consistency:** `operation_id` (budget) vs `turn_id`; `completion_committed_at` used consistently; audit refs are `Integer`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-02-velociraptor-chat-assistant-p1-foundation.md`.

Two execution options:
1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute tasks in this session with checkpoints.

Which approach? (A separate P2 plan for the portal `ChatRail` + streaming proxy should be written before P2 execution.)
