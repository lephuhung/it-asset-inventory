# Compose-Managed DeepAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run DeepAgent as an internal Docker Compose service and let the Portal test its read-only MCP connection using the already-stored Velociraptor configuration.

**Architecture:** Compose provides the stable `deepagent` DNS name and shares the service token only between API and DeepAgent. The backend reads encrypted Velociraptor YAML, forwards it only on the authenticated Docker-network request, and DeepAgent uses it in a temporary MCP bridge process. The Portal retains only enablement and the diagnostic button.

**Tech Stack:** Docker Compose, FastAPI, SQLAlchemy, Pydantic, FastMCP bridge, Next.js, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-compose-managed-deepagent-design.md`

## Global Constraints

- DeepAgent is internal-only at `http://deepagent:8090`; do not publish port 8090.
- Do not return service tokens or Velociraptor private keys from any API response.
- MCP diagnostic invokes only `list_clients` with `limit=1` and forces `ENABLE_DANGEROUS_TOOLS=false`.
- `api_client.yaml` remains configured only in the existing Velociraptor settings workflow.

---

### Task 1: Bundle and configure the internal DeepAgent service

**Files:**
- Modify: `deepagent/Dockerfile`, `deepagent/deepagent/api.py`, `deepagent/deepagent/models.py`
- Modify: `server/deploy/docker-compose.yml`, `server/.env.example`, `deepagent/.env.example`
- Test: `deepagent/tests/test_mcp_client.py`

**Interfaces:**
- Produces `POST /v1/mcp/test` accepting an authenticated request body with `velociraptor_api_client_yaml`.
- Produces Compose service DNS name `deepagent` and non-public port `8090`.

- [ ] **Step 1: Write a failing test for YAML-scoped MCP diagnostic**

```python
async def test_mcp_test_uses_request_yaml_and_removes_temp_file():
    # endpoint hands request YAML to a Settings copy for the MCP bridge
    # and never persists it in the job store
```

- [ ] **Step 2: Run the focused test to verify failure**

Run: `pytest -q deepagent/tests/test_mcp_client.py`

Expected: FAIL because `/v1/mcp/test` has no YAML input contract.

- [ ] **Step 3: Implement request-scoped YAML and Compose service**

```python
class McpTestRequest(BaseModel):
    velociraptor_api_client_yaml: str = Field(min_length=32, max_length=256_000)
```

The endpoint writes the YAML to a `NamedTemporaryFile`, injects the path into a copied `Settings`, calls `VelociraptorMCP.test_connection()`, and removes the file in `finally`. The Docker image installs bridge requirements at a pinned commit; Compose passes internal backend URL, shared token and bridge command/args.

- [ ] **Step 4: Run focused DeepAgent tests and Compose validation**

Run: `docker build -t asset-inventory-deepagent:latest deepagent && docker run --rm -v "$PWD/deepagent:/app" -w /app asset-inventory-deepagent:latest sh -c 'pip install -q -e ".[dev]" && pytest -q tests' && docker compose -f server/deploy/docker-compose.yml config`

Expected: all DeepAgent tests pass and Compose renders a non-public `deepagent` service.

- [ ] **Step 5: Commit**

```bash
git add deepagent server/deploy/docker-compose.yml server/.env.example
git commit -m "feat(deepagent): run mcp bridge in compose"
```

### Task 2: Make backend use internal service and existing Velociraptor configuration

**Files:**
- Modify: `server/app/api/routes/llm_dfir.py`, `server/app/schemas/__init__.py`, `server/app/services/dfir_investigation.py`
- Test: `server/tests/test_llm_deepagent.py`

**Interfaces:**
- Consumes `McpTestRequest` from Task 1.
- Produces `DeepAgentTestOut` without URL/token fields and with safe stage diagnostics.

- [ ] **Step 1: Write failing backend test**

```python
async def test_deepagent_test_sends_saved_velociraptor_yaml(client, seeded_env, monkeypatch):
    # Seed encrypted YAML; fake internal DeepAgent verifies request JSON.
    # Assert API response has no raw YAML or token.
```

- [ ] **Step 2: Run it to verify failure**

Run: `pytest -q server/tests/test_llm_deepagent.py::test_deepagent_test_sends_saved_velociraptor_yaml`

Expected: FAIL because backend requires portal URL/token and sends no YAML test payload.

- [ ] **Step 3: Implement internal lookup and request forwarding**

Use environment fallback `DEEPAGENT_URL=http://deepagent:8090` and `DEEPAGENT_API_KEY` only. Read `VelociraptorConfig.client_config_encrypted`, decrypt only while constructing the authenticated request, and return a missing-YAML diagnostic if unavailable.

- [ ] **Step 4: Run focused backend tests**

Run: `docker run --rm --network asset-inventory-network -e POSTGRES_TEST_HOST=postgres -e REDIS_URL=redis://redis:6379/0 -v "$PWD/server:/app" -w /app asset-inventory-api:latest sh -c 'pip install -q -e ".[dev]" && pytest -q tests/test_llm_deepagent.py tests/test_velociraptor.py'`

Expected: tests pass and no response includes credentials.

- [ ] **Step 5: Commit**

```bash
git add server/app server/tests server/.env.example
git commit -m "feat(dfir): inherit velociraptor config for deepagent"
```

### Task 3: Simplify Portal to enablement and MCP diagnostic

**Files:**
- Modify: `portal/app/(portal)/admin/llm-dfir/settings/page.tsx`, `portal/lib/types.ts`
- Test: Portal production build

**Interfaces:**
- Consumes `deepagent_enabled` and `DeepAgentTestOut` from Task 2.
- Produces a button labelled `Kiểm tra MCP → Velociraptor`.

- [ ] **Step 1: Remove URL/token fields and write state expectations**

The component retains `deepAgentEnabled`, `deepAgentTest`, and `testingDeepAgent`; it removes `deepAgentUrl` and `deepAgentToken` and never submits these fields.

- [ ] **Step 2: Implement the status card**

Show service, MCP and one-client sample status. The button calls the existing backend diagnostic route only after enablement has been saved.

- [ ] **Step 3: Build Portal**

Run: `docker compose -f server/deploy/docker-compose.yml build portal`

Expected: Next.js TypeScript build succeeds.

- [ ] **Step 4: Commit**

```bash
git add portal
git commit -m "feat(portal): use compose managed deepagent"
```

### Task 4: End-to-end Compose verification and documentation

**Files:**
- Modify: `deepagent/README.md`, `docs/DEEPAGENT_CONTRACT.md`

- [ ] **Step 1: Document the internal-only topology and operator prerequisites**

Describe one required deployment secret (`DEEPAGENT_SERVICE_TOKEN`) and the fact that the MCP check uses uploaded Velociraptor YAML.

- [ ] **Step 2: Build and run Compose**

Run: `docker compose -f server/deploy/docker-compose.yml build api portal deepagent && docker compose -f server/deploy/docker-compose.yml up -d --force-recreate api portal deepagent && docker compose -f server/deploy/docker-compose.yml ps`

Expected: API, Portal and DeepAgent are running; DeepAgent has no host port.

- [ ] **Step 3: Run all automated tests**

Run: DeepAgent `pytest -q`; backend `pytest -q`; Portal production build.

Expected: zero failures.

- [ ] **Step 4: Commit**

```bash
git add deepagent/README.md docs/DEEPAGENT_CONTRACT.md
git commit -m "docs: document compose deepagent operation"
```
