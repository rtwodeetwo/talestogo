# Tales IT Deployment Guide

This guide is for IT teams deploying Tales at their organization. Tales is an AI reputation monitoring platform that tracks how your organization is represented across major AI platforms (ChatGPT, Claude, Gemini, Perplexity).

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [Initial Admin Setup](#initial-admin-setup)
5. [Verification](#verification)
6. [Optional: OAuth Configuration](#optional-oauth-configuration)
7. [Maintenance](#maintenance)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

- **Docker** (version 20.10 or later)
- **Docker Compose** (version 2.0 or later)

### Required API Keys

You will need API keys from at least one LLM provider. Tales is provider-agnostic — any one of the supported providers can run the full pipeline. **API keys are set exclusively as environment variables** — in a `.env` file (Docker Compose) or your hosting platform's environment settings (e.g., the Railway or Render dashboard). The **Admin → LLM Providers** page does **not** store API keys; it only configures non-key settings (name, model, color, Azure resource URL, deployment name, web-search flag) after first login.

| Provider | Environment Variable | Get API Key |
|----------|---------------------|-------------|
| OpenAI (GPT) | `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys |
| Google Gemini | `GEMINI_API_KEY` | https://makersuite.google.com/app/apikey |
| Perplexity | `PERPLEXITY_API_KEY` | https://www.perplexity.ai/settings/api |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | Azure Portal → your OpenAI resource → Keys |

**Note:** Configure any combination of providers. The one flagged `use_for_analysis=True` in the UI handles response analysis and brand auto-generation. The "State of the LLMs" report section needs a provider with web search (Gemini, Perplexity, or Bing); if none is configured, that section is omitted but the rest of the report works.

**Azure-only deployment:** Set `AZURE_OPENAI_API_KEY` in `.env`. After first login, open **Admin → LLM Providers**, add a new provider with `api_type = Azure OpenAI`, your Azure resource URL (e.g., `https://my-resource.openai.azure.com/`), `api_version` (e.g., `2024-10-21`), and the deployment name from Azure OpenAI Studio. Mark `use_for_analysis=True`. By default the "State of the LLMs" section will be omitted; everything else works.

**Azure-only deployment WITH the State of the LLMs section:** add a second provider after the Azure one — either:
- **Bing Search v7**: set `BING_SEARCH_V7_API_KEY` in `.env`, add a provider with `api_type = Bing Search v7`, endpoint `https://api.bing.microsoft.com/`. Bing v7 fetches search results; your Azure OpenAI provider (flagged `use_for_analysis=True`) writes the section's prose from those results.
- **Azure AI Foundry Agents** (single-vendor Azure story): run `pip install talestogo[azure-foundry]` server-side, set `AZURE_AI_PROJECT_ENDPOINT` and `AZURE_AI_BING_CONNECTION_NAME` in your environment, then add a provider with `api_type = Azure AI Foundry Agents`, your AI Foundry project endpoint, deployment name (e.g., `gpt-5-4`), and Bing connection name (from AI Foundry → Project → Connections tab). Auth is via `DefaultAzureCredential` (managed identity, `az login`, or service principal env vars) — no API key is stored.

  **Required RBAC role for the managed identity (or service principal):**

  | Role | Role ID | Scope | Grants |
  |------|---------|-------|--------|
  | **Foundry User** (minimum) | `53ca6127-db72-4b80-b1b0-d745d6d5456d` | Foundry resource | All data actions (`Microsoft.CognitiveServices/*`): read connections, create agent versions, call Responses API |

  Assign via Azure Portal (Foundry resource → Access control (IAM) → Add role assignment) or CLI:
  ```bash
  # Assign Foundry User to a user-assigned managed identity
  az role assignment create \
    --assignee <managed-identity-client-id> \
    --role "53ca6127-db72-4b80-b1b0-d745d6d5456d" \
    --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<foundry-resource>
  ```

  **Note:** The role must be assigned on the **Foundry resource** scope (the `Microsoft.CognitiveServices/accounts` level), not on the project or subscription. After assigning, wait 5-10 minutes for RBAC propagation, then restart the container to force a fresh token acquisition (cached managed identity tokens won't reflect new roles until refreshed).

**Partial Configuration:** You do not need API keys for all providers. Tales automatically detects which API keys are present and only makes those providers available.

### Network Requirements

- Outbound HTTPS access to LLM provider APIs
- Port 8080 (or your chosen port) available for the web interface

---

## Quick Start

### 1. Download the Deployment Kit

Download the Tales deployment kit to your server.

### 2. Create Environment File

Copy the template and edit with your values:

```bash
cp .env.template .env
nano .env  # or use your preferred editor
```

**Minimum required variables:**

```bash
# Security (generate unique values for your deployment)
APP_SECRET=<generate-random-string>
ENCRYPTION_KEY=<generate-random-string>

# LLM API Keys — set at least one. Configure provider details in the Admin UI
# after first login (Admin → LLM Providers).
OPENAI_API_KEY=<optional>
ANTHROPIC_API_KEY=<optional>
GEMINI_API_KEY=<optional>
PERPLEXITY_API_KEY=<optional>
AZURE_OPENAI_API_KEY=<optional>
```

**Generate secure random keys:**

```bash
# Run this twice to generate APP_SECRET and ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Start the Application

```bash
docker compose up -d
```

This will:
- Pull the Tales application container from Docker Hub
- Start a PostgreSQL database container
- Initialize the database schema
- Start the web server on port 8080

### 4. Create Initial Admin

Run the admin setup script inside the container:

```bash
docker compose exec app python scripts/admin/setup_initial_admin.py
```

Follow the prompts to create your first admin user. **Save the generated password securely.**

### 5. Access Tales

Open your browser to: `http://localhost:8080`

Log in with the admin credentials created in step 4.

---

## Configuration

### Environment Variables

See `.env.template` for a complete list of environment variables.

### Key Configuration Options

| Variable | Description |
|----------|-------------|
| `APP_SECRET` | JWT signing secret (required) |
| `ENCRYPTION_KEY` | Key for encrypting stored API keys (required) |
| `OIDC_CLIENT_ID` | Azure AD / Entra ID client ID |
| `OIDC_CLIENT_SECRET` | Azure AD / Entra ID client secret |
| `SITE_NAME` | Your organization's name for the UI |
| `SITE_PRIMARY_COLOR` | Primary theme color (hex) |

### Authentication Flags

Control which login methods are available:

```bash
ENABLE_LOCAL_AUTH=true       # Email/password login
ENABLE_MICROSOFT_AUTH=true   # Microsoft/Entra ID login
ENABLE_GOOGLE_AUTH=false     # Google login (disabled by default)
```

### Branding

Customize the appearance for your organization:

```bash
SITE_NAME=Your Organization Tales
SITE_LOGO_URL=https://your-org.gov/logo.png
SITE_PRIMARY_COLOR=#003e60
SITE_SECONDARY_COLOR=#75c9c8
```

### Changing the Port

To run on a different port, set it via environment variable:

```bash
APP_PORT=3000 docker compose up -d
```

### Using an External Database

To use your own PostgreSQL server instead of the bundled container:

1. Comment out or remove the `db` service in `docker-compose.yml`
2. Set `DATABASE_URL` in your `.env` file:

```bash
DATABASE_URL=postgresql://username:password@your-db-host:5432/tales_db
```

### Persistent Data

Database data is stored in a Docker volume named `tales_postgres_data`. This persists across container restarts.

To back up the database:

```bash
docker compose exec db pg_dump -U tales tales > backup.sql
```

To restore:

```bash
docker compose exec -T db psql -U tales tales < backup.sql
```

---

## Initial Admin Setup

The initial admin is created using a CLI script that runs inside the container.

### Running the Setup Script

```bash
docker compose exec app python scripts/admin/setup_initial_admin.py
```

The script will:
1. Verify database connection
2. Check for existing admin users
3. Prompt for admin email, name, and organization
4. Generate a secure temporary password
5. Create the admin user
6. Display the credentials (one time only)

### What the Admin Can Do

Once logged in, the admin can:
- **Configure Site Settings** - Set your organization's URL and contact email for notifications (Admin Menu > Site Settings)
- **Configure LLM Providers** - Set up which AI platforms to query (Admin Menu > LLM Configuration)
- Access the Admin Panel to manage users
- Invite new users (they will receive credentials to log in)
- Create and manage brands to monitor
- Run data collection queries
- View analytics and generate reports

---

## Site Settings Configuration

After initial setup, configure site-wide settings to customize email notifications and branding for your organization.

### Accessing Site Settings

1. Log in as an admin
2. Click your profile icon in the top right
3. Select **Site Settings** from the dropdown menu

### Configurable Settings

| Setting | Description | Default Behavior |
|---------|-------------|------------------|
| **Site URL** | Base URL for all email links (e.g., `https://mycompany.com/tales`) | Falls back to `FRONTEND_URL` environment variable |
| **Admin Email** | Contact email shown in notification emails | Falls back to `FROM_EMAIL` environment variable |
| **Site Name** | Application name used in email subjects and headers | Defaults to "TALES" |

### When to Configure

Configure these settings:
- **Before inviting users** - so invitation emails contain correct URLs
- **After changing domains** - if you move to a new URL
- **For white-labeling** - to customize the application name in emails

---

## Authentication

Tales supports multiple authentication methods. **Email/password authentication works out of the box with no additional setup.**

The login page dynamically adapts based on your configuration. It shows only the authentication methods you have enabled, in any combination:

- **Email/password only** (default) - a simple email and password form
- **OAuth only** - Google and/or Microsoft sign-in buttons
- **Both** - OAuth buttons at the top, an "or" divider, then the email/password form below

### Default: Email/Password

This is the simplest option and requires no additional configuration:

1. Create the initial admin using the setup script (see above)
2. Admin logs in with the generated email/password credentials
3. Admin invites users via the Admin Panel
4. New users receive credentials (via email if Resend is configured, or manually shared)

### Optional: OIDC (Microsoft Entra ID)

For enterprise single sign-on, configure OIDC:

```bash
OIDC_CLIENT_ID=<from-IT>
OIDC_CLIENT_SECRET=<from-IT>
ENABLE_MICROSOFT_AUTH=true  # enabled by default

# Optional: For tenant-specific authentication
OIDC_DISCOVERY_URL=https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration
```

| Auth Method | Setup Required | Best For |
|-------------|----------------|----------|
| Email/Password | None (works immediately) | Quick deployments, small teams |
| Microsoft/Entra ID | OIDC credentials from IT | Organizations using Microsoft 365 |
| Google OAuth | Google Cloud Console setup | Organizations using Google Workspace |
| Multiple methods | Configure each individually | Maximum flexibility for users |

### How Login Methods Are Controlled

Each authentication method requires two things to appear on the login page:

1. **Enable flag** set to `true` in your `.env` file
2. **Credentials configured** (client ID for OAuth methods)

| Method | Enable Flag | Also Requires |
|--------|------------|---------------|
| Email/Password | `ENABLE_LOCAL_AUTH=true` | Nothing else (works immediately) |
| Google | `ENABLE_GOOGLE_AUTH=true` | `GOOGLE_CLIENT_ID` set |
| Microsoft | `ENABLE_MICROSOFT_AUTH=true` | `OIDC_CLIENT_ID` or `MICROSOFT_CLIENT_ID` set |

If all methods are disabled or no credentials are provided, the login page displays: "No authentication methods configured. Please contact your administrator."

---

## LLM Provider Configuration

Tales supports up to 6 LLM providers: 4 default providers (ChatGPT, Claude, Gemini, Perplexity) plus up to 2 custom providers.

### Important: Two-Part Setup Required

Setting up each LLM provider requires completing BOTH parts:

| Part | Where | What |
|------|-------|------|
| **Part 1** | Server `.env` file | Add the API key (e.g., `GEMINI_API_KEY=AIzaSy...`) |
| **Part 2** | Admin UI | Configure display settings (name, model, color) |

**The Admin UI does NOT have an API key input field.** API keys are read from environment variables only. Both parts must be completed for a provider to work.

### Step-by-Step: Adding an LLM Provider

**Part 1: Configure API Key in Environment**

Add the API key to your `.env` file:

```bash
# Example: Adding Gemini
GEMINI_API_KEY=AIzaSy...your-key-here

# Example: Adding Claude
ANTHROPIC_API_KEY=sk-ant-...your-key-here
```

**Restart the Application** (required after `.env` changes):

```bash
docker compose restart app
```

**Part 2: Add LLM in Admin UI**

1. Log in as an admin
2. Go to LLM Configuration (profile menu > LLM Configuration)
3. Click "Add LLM"
4. Fill in the form fields (NO API key field exists):
   - **Display Name** - Human-readable name (e.g., "Gemini", "Claude")
   - **Provider Key** - Auto-generated unique ID (e.g., "gemini", "claude")
   - **API Type** - Select: OpenAI, Anthropic, Google, or OpenAI Compatible
   - **Model Name** - Model identifier (e.g., "gemini-2.0-flash", "claude-3-haiku-20240307")
   - **Chart Color** - Color for analytics charts
5. Configure options (Enabled, Use for Analysis, Supports Web Search)
6. Click "Add LLM"
7. Click "Test" to verify the connection works

### Environment Variable Mapping

Each API type reads from a specific environment variable:

| API Type | Environment Variable | Example Providers |
|----------|---------------------|-------------------|
| OpenAI | `OPENAI_API_KEY` | ChatGPT (gpt-4o, gpt-3.5-turbo) |
| Anthropic | `ANTHROPIC_API_KEY` | Claude (claude-3-haiku, claude-3-sonnet) |
| Google | `GEMINI_API_KEY` | Gemini (gemini-2.0-flash, gemini-pro) |
| Azure | `AZURE_OPENAI_API_KEY` | Azure OpenAI (your-deployment-name) |
| OpenAI Compatible | `PERPLEXITY_API_KEY` | Perplexity (sonar) |

Only providers whose environment variable is set will work. If an API key is missing, the "Test" button will show an error.

### Provider Capabilities

Tales is provider-agnostic — pick whichever provider(s) fit your environment. The one you flag `use_for_analysis=True` handles response analysis and brand auto-generation. The "State of the LLMs" report section needs a provider with web search:

| Provider | Web Search Capable | Notes |
|----------|--------------------|-------|
| Google Gemini | Yes (Google Search grounding) | Excellent for analysis and web search |
| Perplexity | Yes (built-in search via sonar model) | Good for web search; analysis works too |
| OpenAI (ChatGPT) | No | Good for analysis and data collection |
| Anthropic (Claude) | No | Good for analysis and data collection |
| Azure OpenAI | No (directly) | Good for analysis and data collection. Pair with **Bing** for web search. |
| **Bing Search v7** | Yes (retrieval only) | Pairs with the configured analysis provider for synthesis. Microsoft retired v7 in Aug 2025 — still operational for existing resources. |
| **Azure AI Foundry Agents** | Yes (single-vendor Azure story) | Requires `pip install talestogo[azure-foundry]`. Uses Foundry Prompt Agents + Grounding with Bing Search. Auth via Azure Entra ID. |

If no web-search-capable provider is configured (e.g., an OpenAI-only deployment without Bing), the "State of the LLMs" section will be omitted from generated reports. **All other report sections will work normally.**

---

## Verification

After deployment, verify everything is working:

### 1. Check Container Status

```bash
docker compose ps
```

Both `app` and `db` should show as "Up".

### 2. Check Application Logs

```bash
docker compose logs app
```

Look for: `Uvicorn running on http://0.0.0.0:8000`

### 3. Test the API

```bash
curl http://localhost:8080/
```

Should return a JSON response.

### 4. Test Login

1. Open `http://localhost:8080` in a browser
2. Verify the login page shows the expected authentication methods (email/password form, OAuth buttons, or both, depending on your configuration)
3. Log in with the admin credentials created in the setup step
4. Verify you can access the dashboard

### 5. Test Data Collection

1. Create a brand in the dashboard
2. Add a test query
3. Run collection for one platform
4. Verify responses are recorded

---

## Optional: OAuth Configuration

Tales supports Google and Microsoft OAuth for user authentication. This is optional; email/password login is always available when `ENABLE_LOCAL_AUTH=true` (the default).

For each OAuth provider, you need to: (1) set the enable flag, (2) add the credentials, and (3) rebuild the container so the frontend picks up the client IDs.

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new OAuth 2.0 Client ID (Application type: Web application)
3. Set authorized JavaScript origins: `http://your-tales-url` (e.g., `http://localhost:8080`)
4. Set authorized redirect URIs: `http://your-tales-url` (same as origins)
5. Add to your `.env`:

```bash
# Enable Google login
ENABLE_GOOGLE_AUTH=true

# Google OAuth credentials
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret
```

### Microsoft OAuth Setup

1. Go to [Azure Portal App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Create a new App Registration
3. Under "Authentication", add a Single-page application redirect URI: `http://your-tales-url` (e.g., `http://localhost:8080`)
4. Create a client secret under Certificates & secrets
5. Add to your `.env`:

```bash
# Enable Microsoft login (enabled by default)
ENABLE_MICROSOFT_AUTH=true

# Microsoft OAuth credentials (OIDC naming)
OIDC_CLIENT_ID=your-app-client-id
OIDC_CLIENT_SECRET=your-secret
```

### After Adding OAuth Credentials

Rebuild the container so the frontend is built with the OAuth client IDs:

```bash
docker compose up -d --build
```

After rebuilding, the login page will automatically show the new OAuth sign-in buttons alongside (or instead of) the email/password form, depending on your enable flags.

---

## Security

Tales includes built-in security hardening that requires no additional configuration.

### Security Headers

All responses include the following security headers:

| Header | Value | Purpose |
|--------|-------|---------|
| `Content-Security-Policy` | Nonce-based policy | Prevents XSS by restricting script and style sources |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Enforces HTTPS connections (HSTS) |
| `X-Frame-Options` | `DENY` | Prevents clickjacking |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Controls referrer information |
| `X-XSS-Protection` | `1; mode=block` | XSS protection for older browsers |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Restricts browser feature access |

### Additional Protections

- **Content Security Policy (CSP)**: Nonce-based CSP for style-src, compatible with MUI/Material-UI
- **Path traversal protection**: Frontend file serving validates paths stay within the expected directory
- **Cloud metadata blocking**: Requests to cloud provider metadata endpoints (AWS, GCP, Azure) are blocked
- **Self-hosted fonts**: All fonts are served locally, eliminating external CDN dependencies
- **Rate limiting**: API endpoints are rate-limited to prevent abuse

---

## Maintenance

### Updating Tales

```bash
# Pull latest image
docker compose pull

# Restart with new image
docker compose up -d
```

### Viewing Logs

```bash
# All logs
docker compose logs

# Just application logs
docker compose logs app

# Follow logs in real-time
docker compose logs -f app
```

### Restarting Services

```bash
# Restart everything
docker compose restart

# Restart just the app
docker compose restart app
```

### Stopping Tales

```bash
# Stop but keep data
docker compose down

# Stop and remove data (WARNING: deletes database)
docker compose down -v
```

---

## Troubleshooting

### Container won't start

Check logs for errors:
```bash
docker compose logs app
```

Common issues:
- Missing required environment variables
- Database connection failed
- Port already in use

### Database connection errors

Verify the database is running:
```bash
docker compose ps db
docker compose logs db
```

### "Account is not active" error

The user needs to be activated by an admin. Log in as admin and activate the user in the Admin Panel.

### OAuth buttons not showing on login page

For an OAuth button to appear, both conditions must be met:
1. The enable flag is set (e.g., `ENABLE_GOOGLE_AUTH=true`)
2. The client ID is configured (e.g., `GOOGLE_CLIENT_ID=...`)

After changing OAuth settings in `.env`, you must rebuild the container:
```bash
docker compose up -d --build
```

### Login page shows "No authentication methods configured"

This means no authentication methods are available. Check that at least one of the following is true:
- `ENABLE_LOCAL_AUTH=true` (default)
- `ENABLE_GOOGLE_AUTH=true` with `GOOGLE_CLIENT_ID` set
- `ENABLE_MICROSOFT_AUTH=true` with `OIDC_CLIENT_ID` or `MICROSOFT_CLIENT_ID` set

### Forgot admin password

Create a new admin user:
```bash
docker compose exec app python scripts/admin/setup_initial_admin.py
```

### LLM API errors

1. Check that API keys are correctly set in `.env`
2. Verify environment variables are loaded (restart the container after `.env` changes)
3. Use the "Test" button in Admin > LLM Configuration to verify connections
4. Ensure you have billing/credits set up with each provider

### Performance issues

Consider:
- Increasing Docker memory allocation
- Using an external PostgreSQL database
- Adding Redis for caching (set `REDIS_URL` in `.env`)

---

## Support

For issues or questions:
- Check the [User Guide](USER_GUIDE.md) for usage help
- Review `.env.template` for configuration options
- Contact your Tales administrator
