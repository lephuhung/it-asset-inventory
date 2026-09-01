# DeepAgent MCP Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Super Admin configure DeepAgent from the LLM-DFIR portal and run a safe end-to-end DeepAgent → MCP → Velociraptor connectivity check.

**Architecture:** Store the DeepAgent URL, enable flag, and encrypted service token on the existing `llm_config` singleton. The backend proxies health/MCP checks to DeepAgent with that token. DeepAgent owns its stdio MCP command and Velociraptor credential file in deployment environment; its new test endpoint only loads tools and invokes `list_clients` with `limit=1`.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, httpx, LangChain MCP adapter, Next.js/React, Tailwind, pytest.

**Spec:** Approved in chat on 2026-09-01.

## Global Constraints

- Never return, log, or render the DeepAgent service token, MCP environment, api_client YAML, or private keys.
- MCP test is read-only: it may load tools and call `list_clients` with a maximum of one row; it must not run collect or hunt.
- DeepAgent runtime deployment configuration remains environment-owned; the portal stores only its URL, enable state, and service token.
- An LLM runtime is sent to DeepAgent only when an investigation is dispatched.

---

### Task 1: Persist and expose safe DeepAgent settings

**Files:**
- Modify: `server/app/db/models.py`, `server/app/schemas/__init__.py`, `server/app/api/routes/llm_dfir.py`, `server/app/services/dfir_investigation.py`
- Create: `server/alembic/versions/<revision>_deepagent_config.py`
- Test: `server/tests/test_llm_dfir.py`

**Interfaces:**
- Produces `LlmConfig.deepagent_enabled`, `deepagent_url`, `deepagent_service_token_encrypted`.
- Produces masked fields in `LlmConfigOut` and accepts `LlmConfigUpdate` values.

- [ ] Write a failing API test that saves enabled DeepAgent settings, verifies token masking, and proves dispatch selects DB settings over environment defaults.
- [ ] Run the focused pytest test and confirm it fails because fields do not exist.
- [ ] Add nullable columns/migration, encrypt token at write, mask token in response, and prefer DB DeepAgent settings while retaining environment fallback for existing deployments.
- [ ] Run focused tests and migration graph test.

### Task 2: Add a DeepAgent MCP health endpoint

**Files:**
- Modify: `deepagent/deepagent/mcp_client.py`, `deepagent/deepagent/api.py`, `deepagent/deepagent/models.py`
- Test: `deepagent/tests/test_mcp_client.py`, `deepagent/tests/test_api.py`

**Interfaces:**
- Produces `GET /health` status and `POST /v1/mcp/test` authenticated by the existing service token.
- Returns `{ok, tools, client_count_sampled, error}` without evidence payloads.

- [ ] Write failing tests with a fake MCP tool registry: missing `list_clients` fails; a read-only `list_clients` call returns one sampled client and no collect invocation.
- [ ] Run focused DeepAgent tests and confirm the new endpoint/method is absent.
- [ ] Implement `VelociraptorMCP.test_connection()` and protected `/v1/mcp/test`; cap search at one client and convert failures into safe diagnostics.
- [ ] Run the focused DeepAgent suite.

### Task 3: Proxy DeepAgent health and MCP status through backend

**Files:**
- Modify: `server/app/api/routes/llm_dfir.py`, `server/app/schemas/__init__.py`
- Test: `server/tests/test_llm_dfir.py`

**Interfaces:**
- Produces `POST /api/admin/llm-dfir/deepagent/test` for Super Admins.
- Calls DeepAgent health then MCP test using the encrypted service token; returns stage-specific status.

- [ ] Write a failing API test for a mocked DeepAgent health/MCP response and another for an unavailable service.
- [ ] Run focused pytest tests and confirm the route is absent.
- [ ] Implement the route with a bounded timeout, no secret logging, and response fields suitable for the portal.
- [ ] Run focused backend tests.

### Task 4: Add a dedicated DeepAgent & MCP portal card

**Files:**
- Modify: `portal/lib/types.ts`, `portal/app/(portal)/admin/llm-dfir/settings/page.tsx`
- Test: frontend production build

**Interfaces:**
- Consumes the LLM config’s masked DeepAgent fields and backend test response.
- Saves enable flag, URL, token, and `external_orchestrator=deepagent` without exposing existing token.

- [ ] Add DeepAgent form state and a visual card separating service settings from LLM settings.
- [ ] Add connection test status that distinguishes service health from MCP/Velociraptor readiness.
- [ ] Build `portal` in Docker and confirm TypeScript and static generation pass.

### Task 5: End-to-end verification and handoff

**Files:**
- Modify: `server/.env.example`, `deepagent/.env.example`, `deepagent/README.md`

- [ ] Document environment-owned MCP bridge configuration and the portal-managed DeepAgent service settings.
- [ ] Run backend focused tests, DeepAgent tests, Docker frontend build, Compose config validation, and diff checks.
- [ ] Commit the completed implementation with a focused message.
