# Tales Environment Variables Reference

This document lists all environment variables used by Tales. Variables marked as **Required** must be set for the application to function.

## Quick Start (Minimum Required)

For a basic deployment, you need at minimum:

```bash
JWT_SECRET_KEY=<random-string>
ENCRYPTION_KEY=<random-string>
DATABASE_URL=postgresql://user:pass@host:port/database

# LLM API keys — set at least one (required for data collection).
# Set them here for Docker, or in your platform's environment settings for Railway/Render.
# GEMINI_API_KEY=<your-gemini-key>
```

**Note:** LLM API keys must be provided as **environment variables** — in this `.env` file (Docker) or your hosting platform's environment settings (e.g., the Railway/Render dashboard). The Admin UI (Admin Menu > LLM Configuration) does **not** store API keys; it only configures provider display settings (name, model, color). At least one LLM key is required for data collection.

---

## Security Configuration

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `APP_SECRET` | **Yes*** | PPPL standard name for JWT signing secret | `Abc123XyzSecureRandomString` |
| `JWT_SECRET_KEY` | **Yes*** | Legacy name for JWT signing secret | `Abc123XyzSecureRandomString` |
| `ENCRYPTION_KEY` | **Yes** | Key for encrypting sensitive data (API keys) at rest. Must be a secure random string. | `DefGhi456AnotherSecureString` |

*`APP_SECRET` is the PPPL standard name. `JWT_SECRET_KEY` works as a fallback for backwards compatibility. Only one is required.

**Generate secure keys:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Security Notes:**
- Never commit these values to version control
- Use different values for each environment (dev, staging, production)
- Rotate keys periodically for enhanced security

---

## Authentication Configuration

### OIDC / Microsoft Entra ID (PPPL Standard)

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `OIDC_CLIENT_ID` | No* | PPPL standard: Azure AD application client ID | `12345-abcde-...` |
| `OIDC_CLIENT_SECRET` | No* | PPPL standard: Azure AD application client secret | `secret-value` |
| `OIDC_DISCOVERY_URL` | No | OIDC discovery endpoint for tenant-specific auth | See below |
| `MICROSOFT_CLIENT_ID` | No* | Legacy: Azure AD application client ID | `12345-abcde-...` |
| `MICROSOFT_CLIENT_SECRET` | No* | Legacy: Azure AD application client secret | `secret-value` |

*Required if using Microsoft/Entra ID authentication. `OIDC_*` variables take precedence over `MICROSOFT_*` for PPPL compliance.

**OIDC Discovery URL:**
- Default (common): `https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration`
- Tenant-specific: `https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration`

### Authentication Enable/Disable Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_LOCAL_AUTH` | `true` | Enable email/password authentication |
| `ENABLE_MICROSOFT_AUTH` | `true` | Enable Microsoft/Entra ID authentication |
| `ENABLE_GOOGLE_AUTH` | `false` | Enable Google OAuth authentication |

**How login methods appear:** The login page dynamically shows only the authentication methods that are both enabled AND configured. For OAuth methods (Google, Microsoft), the corresponding client ID must also be set for the button to appear. For email/password, no additional configuration is needed beyond the enable flag.

**Usage examples:**
```bash
# Default: email/password only (Google disabled, Microsoft needs client ID)
ENABLE_LOCAL_AUTH=true
ENABLE_MICROSOFT_AUTH=true
ENABLE_GOOGLE_AUTH=false

# SSO only (disable email/password)
ENABLE_LOCAL_AUTH=false
ENABLE_MICROSOFT_AUTH=true
ENABLE_GOOGLE_AUTH=true

# All three methods
ENABLE_LOCAL_AUTH=true
ENABLE_MICROSOFT_AUTH=true
ENABLE_GOOGLE_AUTH=true
```

**Important:** After changing OAuth settings, you must rebuild the container (`docker compose up -d --build`) for the frontend to pick up the new client IDs.

---

## Branding Configuration

Customize the appearance for your organization:

| Variable | Default | Description |
|----------|---------|-------------|
| `SITE_NAME` | `Tales` | Application name shown in UI |
| `SITE_LOGO_URL` | (none) | URL to organization logo |
| `SITE_PRIMARY_COLOR` | `#003e60` | Primary theme color (hex) |
| `SITE_SECONDARY_COLOR` | `#75c9c8` | Secondary theme color (hex) |

**Example:**
```bash
SITE_NAME=ORNL Tales
SITE_LOGO_URL=https://www.ornl.gov/themes/flavor_ornl/logo.svg
SITE_PRIMARY_COLOR=#00629B
```

---

## Database Configuration

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DATABASE_URL` | **Yes** | PostgreSQL connection string | `postgresql://user:pass@localhost:5432/tales` |
| `DB_POOL_SIZE` | No | Database connection pool size (default: 5) | `10` |
| `DB_MAX_OVERFLOW` | No | Maximum overflow connections (default: 10) | `20` |

**Connection String Format:**
```
postgresql://username:password@host:port/database_name
```

**Notes:**
- PostgreSQL is recommended for production
- SQLite (`sqlite:///./tales.db`) works for development only
- The application auto-converts `postgres://` URLs to `postgresql://` format

---

## LLM API Keys

Tales is LLM-provider-agnostic. Configure at least one provider; the one you flag `use_for_analysis=True` in **Admin → LLM Providers** handles response analysis and brand auto-generation. The "State of the LLMs" report section requires a provider with web search (Gemini, Perplexity, or Bing); if none is configured, that section is omitted but the rest of the report works.

| Variable | Description | Get Key From |
|----------|-------------|--------------|
| `OPENAI_API_KEY` | OpenAI (GPT models) | https://platform.openai.com/api-keys |
| `ANTHROPIC_API_KEY` | Anthropic (Claude models) | https://console.anthropic.com/settings/keys |
| `GEMINI_API_KEY` | Google Gemini (supports web search) | https://makersuite.google.com/app/apikey |
| `PERPLEXITY_API_KEY` | Perplexity (supports web search) | https://www.perplexity.ai/settings/api |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI (resource URL, api_version, deployment name configured in the UI) | Azure Portal → your OpenAI resource → Keys |
| `BING_SEARCH_V7_API_KEY` | Bing Search v7 (web search retrieval; pairs with the analysis provider). Optional — only needed for the State of the LLMs section in an Azure/OpenAI-only deployment. | Azure Portal → Bing Search v7 resource → Keys |
| `AZURE_AI_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint for the `azure_foundry_agents` api_type. Auth is via `DefaultAzureCredential` — no API key needed. Optional; requires `pip install talestogo[azure-foundry]` server-side. | `https://foundry-xyz.services.ai.azure.com/api/projects/tales` |
| `AZURE_AI_BING_CONNECTION_NAME` | Foundry project connection name for Grounding with Bing Search. Used by `azure_foundry_agents` if not configured per-provider in the Admin UI. | `bing-grounding` |
| `AZURE_CLIENT_ID` | (Optional) Client ID for user-assigned managed identity or service principal auth. Standard Azure Identity env var read by `DefaultAzureCredential`. | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_TENANT_ID` | (Optional, service principal only) Azure AD tenant ID. | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_CLIENT_SECRET` | (Optional, service principal only) Azure AD client secret. | (secret string) |

At least one provider env var must be set. The provider is then enabled and configured in **Admin → LLM Providers** in the UI.

**Admin UI Configuration:**
After deployment, configure providers via Admin Menu > LLM Configuration. This is where you:
- Add/remove providers without restarting the application
- Set the resource URL, api_version, and deployment name for Azure OpenAI
- Test API connections before saving
- Customize chart colors per provider
- Designate which LLM to use for analysis (`use_for_analysis`)
- Mark which providers support web search (`supports_web_search`)

**Defaults Behavior:**
On a fresh install with no provider records in the database, Tales auto-discovers OpenAI/Anthropic/Gemini/Perplexity from env vars and creates corresponding provider entries. Azure OpenAI is not auto-created (it requires UI configuration for endpoint/version/deployment). Once you add or edit any provider in the UI, the database becomes the source of truth.

**Azure-only deployment:** Set `AZURE_OPENAI_API_KEY` in env, then in the UI add a new provider with api_type=Azure OpenAI, your Azure resource URL (e.g., `https://my-resource.openai.azure.com/`), api_version (e.g., `2024-10-21`), and deployment name. Mark `use_for_analysis=True`. By default the "State of the LLMs" report section will be omitted.

**Azure-only + State of the LLMs:** add `BING_SEARCH_V7_API_KEY` (and configure a Bing Search v7 provider in the UI), or for a fully Azure-native story set `AZURE_AI_PROJECT_ENDPOINT` + `AZURE_AI_BING_CONNECTION_NAME` (requires `pip install talestogo[azure-foundry]` and configuring an Azure AI Foundry Agents provider). See `IT_DEPLOYMENT_GUIDE.md` for the full recipe.

**Key Formats:**
- OpenAI: `sk-proj-...` or `sk-...`
- Anthropic: `sk-ant-api03-...`
- Gemini: Alphanumeric string
- Perplexity: `pplx-...`
- Azure OpenAI: Alphanumeric string (from Azure Portal)

---

## OAuth Configuration (Optional)

OAuth is optional. Users can always log in with email/password when `ENABLE_LOCAL_AUTH=true` (the default). For an OAuth button to appear on the login page, you must set both the enable flag (see Authentication Enable/Disable Flags above) AND the client ID below.

### Google OAuth

Requires `ENABLE_GOOGLE_AUTH=true` in addition to the variables below.

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret |

**Setup:** https://console.cloud.google.com/apis/credentials

### Microsoft OAuth

Requires `ENABLE_MICROSOFT_AUTH=true` (default) in addition to the variables below.

| Variable | Required | Description |
|----------|----------|-------------|
| `MICROSOFT_CLIENT_ID` | No | Azure AD application client ID |
| `MICROSOFT_CLIENT_SECRET` | No | Azure AD application secret |

**Setup:** https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade

**Note:** The frontend reads OAuth client IDs from the backend's `/auth/config` endpoint at runtime, so `VITE_GOOGLE_CLIENT_ID` and `VITE_MICROSOFT_CLIENT_ID` build-time variables are no longer needed.

---

## Email Configuration (Optional)

Email is used for sending user invitations. If not configured, admins can share credentials directly.

### Resend (Recommended)

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `RESEND_API_KEY` | No | Resend API key | `re_abc123...` |
| `FROM_EMAIL` | No | Sender email address | `admin@yourdomain.com` |

**Setup:** https://resend.com

### SMTP (Alternative)

| Variable | Required | Description |
|----------|----------|-------------|
| `SMTP_HOST` | No | SMTP server hostname |
| `SMTP_PORT` | No | SMTP server port (usually 587) |
| `SMTP_USER` | No | SMTP username |
| `SMTP_PASSWORD` | No | SMTP password |

**Note:** SMTP may not work on some cloud platforms (ports blocked). Resend is recommended.

---

## Application Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ENVIRONMENT` | No | Environment name | `development` |
| `FRONTEND_URL` | No | Frontend URL for CORS | `http://localhost:5173` |
| `ADMIN_EMAIL` | No | Bootstrap admin email (OAuth only). If a user logs in via OAuth with this email, they are auto-promoted to admin. Leave unset to require explicit admin creation via `setup_initial_admin.py`. | `admin@yourlab.gov` |
| `PORT` | No | Application port | `8000` |

---

## Redis Configuration (Optional)

Redis enables caching for improved performance. Not required for basic operation.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `REDIS_URL` | No | Redis connection URL | `redis://localhost:6379/0` |
| `REDIS_CACHE_TTL_DASHBOARD` | No | Dashboard cache TTL (seconds) | `900` (15 min) |
| `REDIS_CACHE_TTL_TRENDS` | No | Trends cache TTL (seconds) | `3600` (1 hour) |
| `REDIS_CACHE_TTL_BATCH` | No | Batch cache TTL (seconds) | `86400` (24 hours) |

---

## Scheduler Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ENABLE_SCHEDULER` | No | Enable background task scheduler | `false` |

**Note:** Only set to `true` in production. Running multiple instances with scheduler enabled can cause duplicate tasks.

---

## Analytics Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ANALYTICS_DEFAULT_LOOKBACK_DAYS` | No | Default date range for analytics | `180` |

---

## Frontend Build Variables

These are optional and only used when building the frontend (during Docker build).

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Backend API URL (only needed if frontend is hosted separately from backend) |

**Note:** OAuth client IDs (`GOOGLE_CLIENT_ID`, `MICROSOFT_CLIENT_ID`) do not need `VITE_` prefixed variants. The frontend fetches them at runtime from the backend's `/auth/config` endpoint.

---

## Example .env File

```bash
# Security (REQUIRED - generate unique values)
JWT_SECRET_KEY=your-secure-random-jwt-key-here
ENCRYPTION_KEY=your-secure-random-encryption-key-here

# Database (REQUIRED)
DATABASE_URL=postgresql://tales:password@db:5432/tales

# LLM API Keys — set at least one. Provider details (model, endpoint,
# Azure resource URL, etc.) are configured in Admin → LLM Providers.
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
PERPLEXITY_API_KEY=
AZURE_OPENAI_API_KEY=

# Optional: OAuth (for Google/Microsoft login)
# GOOGLE_CLIENT_ID=your-google-client-id
# GOOGLE_CLIENT_SECRET=your-google-secret
# MICROSOFT_CLIENT_ID=your-microsoft-client-id
# MICROSOFT_CLIENT_SECRET=your-microsoft-secret

# Optional: Email (for sending invitations)
# RESEND_API_KEY=re_your-resend-key
# FROM_EMAIL=admin@yourdomain.com

# Optional: Performance
# REDIS_URL=redis://localhost:6379/0

# Environment
ENVIRONMENT=production
FRONTEND_URL=http://localhost:8080
```

---

## Troubleshooting

### "JWT_SECRET_KEY not set"
Generate a secure key: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

### "Database connection failed"
- Verify DATABASE_URL format: `postgresql://user:pass@host:port/database`
- Check that the database server is running and accessible
- Verify credentials are correct

### "API key invalid"
- Verify the key is copied correctly (no extra spaces)
- Check that billing/credits are set up with the provider
- Ensure the key has the necessary permissions

### "Azure AI Foundry Agents (azure_foundry_agents) connection error"
- This provider uses `DefaultAzureCredential` — no API key env var required
- Ensure `az login` has been run (local dev) or managed identity is configured (production)
- Verify the `AZURE_AI_PROJECT_ENDPOINT` and `AZURE_AI_BING_CONNECTION_NAME` are set (or configured per-provider in the Admin UI)
- Verify the Bing Search connection exists in your Foundry project (AI Foundry → Project → Connections tab)
- Requires `pip install talestogo[azure-foundry]` (installs `azure-ai-projects` + `azure-identity`)

### "CORS error"
- Add your frontend URL to FRONTEND_URL
- Restart the application after changing the value
