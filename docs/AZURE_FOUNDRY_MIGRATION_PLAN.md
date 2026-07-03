# Migration Plan: `bing_grounded` → `azure_foundry_agents`

## Resume Prompt

To resume this work in a new Claude Code session, use:

```
Implement the azure_foundry_agents migration plan documented in docs/AZURE_FOUNDRY_MIGRATION_PLAN.md on branch fix/test-connection-bing-grounded. Read that file first, then execute phases 0-4 in order. Run tests after each phase. Do not invent SDK methods — the plan documents exact verified signatures from azure-ai-projects==2.2.0.
```

---

## Context

The `bing_grounded` provider currently uses the `azure-ai-agents` Assistants SDK. The Azure OpenAI classic Assistants API is deprecated and Foundry Agents are the forward path. This migration replaces it with **Azure AI Foundry Prompt Agents** invoked via the **OpenAI Responses API** with `extra_body={"agent_reference": ...}`.

This deployment avoids direct `tools=[{"type": "web_search_preview"}]` because some tenants/subscriptions block it via admin policy. The architecture instead attaches Grounding with Bing Search to a Foundry Prompt Agent definition, which the Responses API invokes by agent reference.

---

## SDK Discovery (verified against installed `azure-ai-projects==2.2.0`)

```python
# AIProjectClient — NO credential_scopes parameter
from azure.ai.projects import AIProjectClient
AIProjectClient(endpoint: str, credential: TokenCredential, *, allow_preview: bool = False, **kwargs)

# Sub-clients
client.connections.get(name: str, *, include_credentials: bool = False) -> Connection
client.agents.get(agent_name: str) -> AgentDetails
client.agents.list_versions(agent_name: str, *, limit: int = None, order = None) -> ItemPaged[AgentVersionDetails]
client.agents.create_version(agent_name: str, *, definition: AgentDefinition, metadata: dict[str,str] = None, description: str = None) -> AgentVersionDetails
client.get_openai_client() -> OpenAI

# Models (all from azure.ai.projects.models)
PromptAgentDefinition(model=str, instructions=str, tools=[...])  # produces {'kind': 'prompt', ...}
BingGroundingTool(bing_grounding=BingGroundingSearchToolParameters(...))  # produces {'type': 'bing_grounding', ...}
BingGroundingSearchToolParameters(search_configurations=[BingGroundingSearchConfiguration(...)])
BingGroundingSearchConfiguration(project_connection_id=str)

# Connection.id is the full ARM resource ID string, used as project_connection_id
# AgentVersionDetails has: name, version, status, metadata, definition, created_at
# azure.core.exceptions.ResourceNotFoundError raised for missing agents (404)
```

### Response shape from `openai.responses.create(input=..., extra_body={"agent_reference": {...}})`

- `response.output_text` — concatenated text (primary extraction path)
- `response.output` items include types: `bing_grounding_call`, `bing_grounding_call_output`, `message`
- Message content item type: `ResponseOutputText` with `.text` and `.annotations`
- Annotations are `AnnotationURLCitation` objects with: `url`, `title`, `start_index`, `end_index`, `type="url_citation"`

### Live-verified working call pattern

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint='https://your-foundry.services.ai.azure.com/api/projects/your-project',
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()
response = openai.responses.create(
    input='What are the latest AI announcements?',
    tool_choice='required',
    max_output_tokens=4000,
    extra_body={
        'agent_reference': {
            'name': 'tales-bing-grounding',  # pre-created agent name
            'type': 'agent_reference',
        }
    },
)
# Do NOT pass model= or tools= — they live on the agent definition.
print(response.output_text)  # Grounded text with citations
```

---

## Provider Identity

- Old api_type: `bing_grounded`
- New api_type: `azure_foundry_agents`

Backward compatibility:
- Accept both `"bing_grounded"` and `"azure_foundry_agents"` everywhere
- Router rewrites `"bing_grounded"` → `"azure_foundry_agents"` on create/update
- `API_TYPE_TO_ENV_VAR` has entries for both
- Single implementation: `_call_azure_foundry_agents()`

---

## Required Configuration (per-provider)

| Field | DB Column | Env Var Fallback | Example |
|-------|-----------|------------------|---------|
| Project endpoint | `api_endpoint` | `AZURE_AI_PROJECT_ENDPOINT` | `https://your-foundry.services.ai.azure.com/api/projects/your-project` |
| Deployment name | `model_name` | — | `gpt-5-4` |
| Bing connection name | `bing_connection_name` (NEW) | `AZURE_AI_BING_CONNECTION_NAME` | `bing-grounding` |

**No API key stored in DB. No API key env var required.** Auth is via `DefaultAzureCredential`:
- Local dev: `az login`
- Azure-hosted system-assigned managed identity: no extra config needed
- User-assigned managed identity: set `AZURE_CLIENT_ID` in environment
- Service principal: set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` in environment

These are standard Azure Identity env vars read by `DefaultAzureCredential` at runtime — never stored in the database.

---

## Agent Creation Strategy

**Deterministic persistent agents — no ephemeral creation/deletion per request.**

Naming: `tales-bing-{hash8}` where hash8 = first 8 chars of SHA-256(`"{deployment_name}:{bing_connection_id}"`). Always ≤ 63 chars, lowercase alphanumeric + hyphens.

Metadata on agent version:
```python
{
    "provider": "tales",
    "purpose": "bing-grounding",
    "schema_version": "1",
    "model": deployment_name,
    "bing_conn_hash": sha256(bing_connection_id)[:16],
}
```

Lookup/create logic:
1. Try `project.agents.get(agent_name=name)`.
   - `ResourceNotFoundError` → go to step 4.
2. List versions: `project.agents.list_versions(agent_name=name, order="desc", limit=10)`.
3. Find newest where `status == "active"` AND metadata matches (same model, bing_conn_hash, schema_version). If found → return `name`.
4. Create: `project.agents.create_version(agent_name=name, definition=defn, metadata=meta, description="...")`.
5. On conflict (race condition: another request created it simultaneously), catch error and re-list versions to find the compatible one.
6. Return `name`.

---

## Phase 0: Database Schema

### 0.1 `app/models.py`
Add to `LLMProvider` class after `api_version` (line ~309):
```python
bing_connection_name = Column(String(200), nullable=True)  # Foundry project connection name for Bing Grounding
```

### 0.2 `app/schemas.py`
Add `bing_connection_name: Optional[str] = None` to LLMProvider create/update Pydantic schemas.

### 0.3 New file: `migrations/add_llm_provider_bing_connection_name.py`
Follow existing pattern from `migrations/add_llm_provider_api_version.py`:
- Check if column exists
- `ALTER TABLE llm_providers ADD COLUMN bing_connection_name VARCHAR(200)`
- Supports rollback

---

## Phase 1: Backend Core

### 1.1 `pyproject.toml`
- Rename optional extra from `bing-grounded` to `azure-foundry`
- Replace `azure-ai-agents>=1.0.0,<2.0.0` with `azure-ai-projects>=2.2.0`
- Keep `azure-identity>=1.15.0`

### 1.2 `app/services/generic_llm_client.py`

**Imports (lines 33-44):** Replace `azure.ai.agents` block:
```python
try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import (
        PromptAgentDefinition,
        BingGroundingTool,
        BingGroundingSearchToolParameters,
        BingGroundingSearchConfiguration,
    )
    from azure.identity import DefaultAzureCredential
    from azure.core.exceptions import ResourceNotFoundError
    AZURE_AI_FOUNDRY_AVAILABLE = True
except ImportError:
    AZURE_AI_FOUNDRY_AVAILABLE = False
```

**`call_with_web_search()` (line 217):** Both `"azure_foundry_agents"` and `"bing_grounded"` route to `_call_azure_foundry_agents()`. Pass `bing_connection_name` through.

**New method signature:**
```python
@staticmethod
def _call_azure_foundry_agents(
    api_key: str,                     # unused — auth via DefaultAzureCredential
    deployment_name: str,             # model_name
    prompt: str,
    api_endpoint: str,
    api_version: Optional[str],       # unused — kept for interface compat
    timeout: float,
    bing_connection_name: Optional[str] = None,
) -> str:
```

Implementation steps:
1. Validate `api_endpoint`, `deployment_name`.
2. Resolve `bing_connection_name` from param or `os.getenv("AZURE_AI_BING_CONNECTION_NAME")`. Raise `LLMConfigurationError` if missing.
3. `project = AIProjectClient(endpoint=api_endpoint, credential=DefaultAzureCredential())`
4. `bing_conn = project.connections.get(bing_connection_name)`
5. `agent_name = _get_or_create_bing_grounded_agent(project, deployment_name, bing_conn.id)`
6. `openai_client = project.get_openai_client()`
7. Call Responses API:
   ```python
   response = openai_client.responses.create(
       input=prompt,
       tool_choice="required",
       max_output_tokens=4000,
       extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
   )
   ```
8. Return `response.output_text` (primary). Fallback: iterate `response.output` for items with `.content`, collect `.text` from each content block.
9. Wrap exceptions in `LLMAPIError` with clear error messages.

**`_get_or_create_bing_grounded_agent()` helper (new static method):**
- Compute deterministic name: `tales-bing-{sha256(f"{deployment_name}:{bing_connection_id}")[:8]}`
- Compute metadata dict with hashes
- Try `project.agents.get(agent_name)` → `ResourceNotFoundError` means create
- List versions, find active+matching → reuse
- Else create_version with `PromptAgentDefinition(model=deployment_name, instructions="...", tools=[BingGroundingTool(...)])`
- On create conflict, re-list to find the version that won the race

**`test_connection()` (line 710):** Accept both api_type names. Add `bing_connection_name` parameter.

### 1.3 `app/services/llm_provider_manager.py`

**`API_TYPE_TO_ENV_VAR`:**
```python
"azure_foundry_agents": "AZURE_AI_PROJECT_ENDPOINT",
"bing_grounded": "AZURE_AI_PROJECT_ENDPOINT",  # backward compat
```

**`ProviderConfig` dataclass:** Add `bing_connection_name: Optional[str] = None`.

**`has_api_key()`:** For `azure_foundry_agents`/`bing_grounded`, return `True` if `self.api_endpoint` is set.

**`call_with_web_search()`:** Skip API key check for both names. Pass `bing_connection_name` through.

**Provider loading from DB:** Read `bing_connection_name` column into `ProviderConfig`.

### 1.4 `app/routers/llm_providers.py`

- Add `"azure_foundry_agents"` to valid_api_types lists
- Keep `"bing_grounded"` accepted; silently rewrite to `"azure_foundry_agents"` on create/update
- Validation: require `api_endpoint`, require `model_name`. `bing_connection_name` from request or env. No `api_key` or `api_version` required.
- Read/write `bing_connection_name` from request into provider model
- API-key bypass in test-connection for both names
- use_for_analysis rejection for both names

### 1.5 `scripts/admin/generate_report.py`
- Line 115: Add `"azure_foundry_agents"` to condition alongside `"bing_grounded"`

---

## Phase 2: Frontend

### 2.1 `frontend/src/pages/admin/LLMConfiguration.tsx`

**LLMProvider interface:** Add `bing_connection_name?: string | null`.

**API_TYPE_OPTIONS:** Replace `bing_grounded` entry:
```typescript
{ value: 'azure_foundry_agents', label: 'Azure AI Foundry Agents',
  description: 'Azure-native grounded web search using Foundry Agents + Grounding with Bing Search. Auth via Azure Entra ID.',
  envVar: 'AZURE_AI_PROJECT_ENDPOINT' },
```

**Model name field:** Label "Deployment Name", helper "Model deployment name in the Foundry project (must support Grounding with Bing Search)."

**Conditional form fields for `azure_foundry_agents`:**
1. Azure AI Foundry Project Endpoint (required, maps to `api_endpoint`)
2. Bing Connection Name (required, new field mapping to `bing_connection_name`)
   - Helper: "Foundry project connection name for Grounding with Bing Search (AI Foundry → Project → Connections tab)."
3. No API Version field
4. Info Alert explaining DefaultAzureCredential auth:
   - Local dev: `az login`
   - System-assigned managed identity: no extra config needed
   - User-assigned managed identity: set `AZURE_CLIENT_ID`
   - Service principal: set `AZURE_CLIENT_ID` + `AZURE_TENANT_ID` + `AZURE_CLIENT_SECRET`

**Provider card:** Replace "API key detected/not found" chip with "Auth: Azure Entra ID" for this type.

**handleApiTypeChange / handleEndpointChange:** Replace `'bing_grounded'` with `'azure_foundry_agents'`.

**formData:** Add `bing_connection_name`, wire to create/update/display.

---

## Phase 3: Tests

### 3.1 `tests/test_generic_llm_client.py`
Rename `TestBingGrounded*` → `TestAzureFoundryAgents*`. Replace old SDK mocks with:
- `AIProjectClient` mock (no `credential_scopes`)
- `DefaultAzureCredential` mock
- `project.connections.get()` mock
- `project.agents.get()` / `list_versions()` / `create_version()` mocks
- `project.get_openai_client().responses.create()` mock

Test cases per acceptance criteria (see main list above).

### 3.2 `tests/test_llm_provider_manager.py`
- `API_TYPE_TO_ENV_VAR["azure_foundry_agents"] == "AZURE_AI_PROJECT_ENDPOINT"`
- Backward compat alias
- No API key needed, endpoint required
- `bing_connection_name` from config/env

### 3.3 `tests/test_llm_providers_router.py`
New tests:
- `test_create_azure_foundry_agents_requires_endpoint`
- `test_create_azure_foundry_agents_requires_model_name`
- `test_create_azure_foundry_agents_requires_bing_connection_name`
- `test_create_azure_foundry_agents_does_not_require_api_key`
- `test_create_azure_foundry_agents_does_not_require_api_version`
- `test_update_rewrites_bing_grounded_to_azure_foundry_agents`
- `test_use_for_analysis_rejects_azure_foundry_agents`

---

## Phase 4: Documentation & Config

### 4.1 `docs/ENV_VARS_REFERENCE.md`
Replace `AZURE_FOUNDRY_API_KEY` references with:
- `AZURE_AI_PROJECT_ENDPOINT` — Foundry project endpoint
- `AZURE_AI_BING_CONNECTION_NAME` — Bing Grounding connection name
- `AZURE_CLIENT_ID` (optional) — user-assigned MI or SP
- `AZURE_TENANT_ID` (optional, SP only)
- `AZURE_CLIENT_SECRET` (optional, SP only)

### 4.2 `docker-compose.yml` and `deployment-kit/docker-compose.yml`
```yaml
- AZURE_AI_PROJECT_ENDPOINT=${AZURE_AI_PROJECT_ENDPOINT:-}
- AZURE_AI_BING_CONNECTION_NAME=${AZURE_AI_BING_CONNECTION_NAME:-}
# - AZURE_CLIENT_ID=${AZURE_CLIENT_ID:-}
# - AZURE_TENANT_ID=${AZURE_TENANT_ID:-}
# - AZURE_CLIENT_SECRET=${AZURE_CLIENT_SECRET:-}
```

### 4.3 Deployment guides
Update `docs/IT_DEPLOYMENT_GUIDE.md` and `deployment-kit/IT_DEPLOYMENT_GUIDE.md`:
- Install: `pip install talestogo[azure-foundry]`
- Setup: Create Bing resource → connect to Foundry project → configure provider

---

## Verification Commands

```bash
# Run migration
python migrations/add_llm_provider_bing_connection_name.py

# Run tests
python -m pytest tests/ -v

# Live connection test
python -c "
from app.services.generic_llm_client import GenericLLMClient
import os
success, msg, preview = GenericLLMClient.test_connection(
    api_type='azure_foundry_agents', api_key='',
    model_name='gpt-5-4',
    api_endpoint=os.environ['AZURE_AI_PROJECT_ENDPOINT'],
    bing_connection_name=os.environ['AZURE_AI_BING_CONNECTION_NAME'],
)
print(success, msg, preview[:100] if preview else None)
"

# Frontend build
cd frontend && npm run build
```

---

## Files Modified (summary)

| File | Change |
|------|--------|
| `app/models.py` | Add `bing_connection_name` column |
| `app/schemas.py` | Add field to create/update schemas |
| `migrations/add_llm_provider_bing_connection_name.py` | NEW — migration script |
| `pyproject.toml` | Rename extra, swap dependency |
| `app/services/generic_llm_client.py` | Replace imports + rewrite implementation |
| `app/services/llm_provider_manager.py` | Update mappings, add field, fix auth gating |
| `app/routers/llm_providers.py` | Add type, validation, rewrite logic |
| `scripts/admin/generate_report.py` | Add type to condition |
| `frontend/src/pages/admin/LLMConfiguration.tsx` | New type, fields, auth chip |
| `tests/test_generic_llm_client.py` | Rewrite test classes |
| `tests/test_llm_provider_manager.py` | Update assertions |
| `tests/test_llm_providers_router.py` | Add new tests |
| `docs/ENV_VARS_REFERENCE.md` | Replace env var docs |
| `docker-compose.yml` | Update env vars |
| `deployment-kit/docker-compose.yml` | Update env vars |
| `docs/IT_DEPLOYMENT_GUIDE.md` | Update provider setup |
| `deployment-kit/IT_DEPLOYMENT_GUIDE.md` | Update provider setup |
