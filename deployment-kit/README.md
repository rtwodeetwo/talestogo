# Tales Deployment Kit

This kit contains everything you need to deploy Tales at your organization.

## What's Included

| File | Description |
|------|-------------|
| `README.md` | This file - quick start guide |
| `.env.template` | Environment variables template |
| `docker-compose.yml` | Docker configuration |
| `setup.sh` | Helper script for initial setup |
| `IT_DEPLOYMENT_GUIDE.md` | Complete IT deployment instructions |
| `USER_GUIDE.md` | End-user documentation |

---

## Quick Start (5 Minutes)

### Prerequisites

- Docker (version 20.10+)
- Docker Compose (version 2.0+)
- An API key for at least one LLM provider (OpenAI, Anthropic, Google Gemini, Azure OpenAI, or Perplexity) — Tales is provider-agnostic
- OIDC credentials from IT (if using Entra ID authentication)

### Step 1: Configure Environment

Copy the template and add your values:

```bash
cp .env.template .env
```

Edit `.env` and add at minimum:

```bash
# REQUIRED: Security keys (generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))")
APP_SECRET=your-random-secret-key
ENCRYPTION_KEY=your-random-encryption-key

# REQUIRED: At least one LLM API key — pick whichever you have.
# Configure the provider's details (model, endpoint, etc.) in the Admin UI
# after first login: Admin → LLM Providers.
OPENAI_API_KEY=          # ChatGPT (gpt-4o, etc.)
ANTHROPIC_API_KEY=       # Claude
GEMINI_API_KEY=          # Google Gemini (supports web search)
PERPLEXITY_API_KEY=      # Perplexity sonar (supports web search)
AZURE_OPENAI_API_KEY=    # Azure OpenAI (set this if your IT runs OpenAI on Azure)

# OIDC Configuration (IT provides this — no secret needed)
OIDC_CLIENT_ID=from-it-department
```

### Step 2: Start Tales

```bash
docker compose up -d
```

Wait for containers to start (about 30 seconds).

### Step 3: Create Admin Account

```bash
docker compose exec app python scripts/admin/setup_initial_admin.py
```

Follow the prompts. **Save the generated password - it's shown only once.**

### Step 4: Log In

Open your browser to: `http://localhost:8080`

Log in with the admin credentials from Step 3.

---

## Organization-Specific Configuration

Each organization deploys their own instance with custom configuration:

### Branding Variables

```bash
# Branding for your organization
SITE_NAME=Your Organization Tales
SITE_LOGO_URL=https://your-org.gov/logo.png
SITE_PRIMARY_COLOR=#003e60
SITE_SECONDARY_COLOR=#75c9c8
```

### Authentication Variables

```bash
# Your organization's Entra ID app registration (from IT — no secret needed)
OIDC_CLIENT_ID=your-client-id

# Optional: Tenant-specific OIDC endpoint
OIDC_DISCOVERY_URL=https://login.microsoftonline.com/{your-tenant-id}/v2.0/.well-known/openid-configuration
```

### Authentication Flags

Control which login methods are available:

```bash
ENABLE_LOCAL_AUTH=true       # Email/password
ENABLE_MICROSOFT_AUTH=true   # Entra ID / Microsoft
ENABLE_GOOGLE_AUTH=false     # Google OAuth
```

---

## What's Next?

After logging in:

1. **Configure LLM Providers** (optional) - Go to Profile > LLM Configuration to customize provider names/colors
2. **Create a Brand** - Go to Manage > Brands and add your first brand to monitor
3. **Add Queries** - Add questions that users might ask AI platforms about your brand
4. **Run Collection** - Go to Data > Collect & Analyze to gather AI responses

**Automated Collection:** Once configured, Tales automatically collects data on the 1st, 7th, 14th, and 21st of each month. Reports are generated monthly, quarterly, and annually.

---

## Authentication Options

| Method | Setup Required | Variables |
|--------|----------------|-----------|
| Email/Password | None | `ENABLE_LOCAL_AUTH=true` (default) |
| Microsoft/Entra ID | App registration from IT (no secret needed) | `OIDC_CLIENT_ID` |
| Google OAuth | Optional | `GOOGLE_CLIENT_ID`, `ENABLE_GOOGLE_AUTH=true` |

---

## LLM Provider Configuration

Tales auto-detects which API keys you've configured and makes those providers available. After first login, finalize provider details (model, color, web-search flag — and for Azure, the resource URL + api_version + deployment name) in **Admin → LLM Providers**.

| Provider | Environment Variable | Get API Key | Web Search |
|----------|---------------------|-------------|------------|
| OpenAI (ChatGPT) | `OPENAI_API_KEY` | https://platform.openai.com/api-keys | No |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys | No |
| Google Gemini | `GEMINI_API_KEY` | https://makersuite.google.com/app/apikey | Yes |
| Perplexity | `PERPLEXITY_API_KEY` | https://www.perplexity.ai/settings/api | Yes |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | Azure Portal → your OpenAI resource → Keys | No |

**Minimum requirement:** at least one of these env vars set. Tales is provider-agnostic — any one of them can run the full pipeline (collection, analysis, reports). The one you flag `use_for_analysis=True` in the UI handles response analysis and brand auto-generation.

**About the "State of the LLMs" report section:** it needs a provider with web search (Gemini or Perplexity). If neither is configured (e.g., an Azure-only or OpenAI-only deployment), that one section is omitted; everything else works.

**Azure-only deployment:** set `AZURE_OPENAI_API_KEY`, then in **Admin → LLM Providers** add a provider with api_type = Azure OpenAI, your Azure resource URL (e.g., `https://my-resource.openai.azure.com/`), api_version (e.g., `2024-10-21`), and the deployment name from Azure OpenAI Studio. Mark `use_for_analysis=True`.

---

## Environment Variable Reference

| Variable | Legacy Name | Description |
|----------|-------------|-------------|
| `APP_SECRET` | `JWT_SECRET_KEY` | JWT signing secret |
| `OIDC_CLIENT_ID` | `MICROSOFT_CLIENT_ID` | Azure AD client ID |
| `OIDC_DISCOVERY_URL` | - | OIDC discovery endpoint |

Legacy variable names are supported for backwards compatibility. No client secret is needed for OAuth — the app uses MSAL's client-side PKCE flow.

---

## Troubleshooting

### Container won't start

```bash
docker compose logs app
```

Check for missing environment variables or database connection issues.

### Can't log in

Verify you're using the correct credentials from the setup script. If you forgot the password, create a new admin:

```bash
docker compose exec app python scripts/admin/setup_initial_admin.py
```

### LLM features not working

1. Check that API keys are set in `.env`
2. Restart the container: `docker compose restart app`
3. Go to LLM Configuration and click "Test" on each provider

---

## Support

- Full IT documentation: `IT_DEPLOYMENT_GUIDE.md`
- User documentation: `USER_GUIDE.md`
