# Tales To Go

Tales is an AI reputation monitoring platform that tracks how brands are represented across major AI platforms (ChatGPT, Codex, Gemini, Perplexity).

## Tech Stack

- **Backend**: Python/FastAPI with SQLAlchemy ORM
- **Frontend**: React/TypeScript with Vite, Material-UI
- **Database**: PostgreSQL
- **Auth**: Email/password + optional Google/Microsoft OAuth

## Project Structure

```
TalesToGo/
├── app/                    # FastAPI backend
│   ├── main.py            # App entry point
│   ├── models.py          # SQLAlchemy models
│   ├── schemas.py         # Pydantic schemas
│   ├── crud.py            # Database operations
│   ├── routers/           # API endpoints
│   └── services/          # Business logic
│       ├── llm_service.py # LLM API calls
│       └── data_pipeline.py # Collection/analysis workflow
├── frontend/              # React frontend
│   └── src/
│       ├── pages/         # Page components
│       ├── components/    # Reusable components
│       └── services/api.ts # API client
├── scripts/admin/         # Admin scripts
│   ├── collect_responses.py
│   ├── analyze_responses.py
│   └── generate_report.py
├── docs/                  # Documentation
│   ├── USER_GUIDE.md     # End user documentation
│   ├── IT_DEPLOYMENT_GUIDE.md # IT deployment instructions
│   └── ENV_VARS_REFERENCE.md # Environment variable reference
├── docker-compose.yml    # Docker deployment config
└── Dockerfile            # Container build config
```

## LLM Configuration

Tales is provider-agnostic. Five `api_type` values are built in; you can add custom OpenAI-compatible providers up to 6 total. Configure provider details (model, endpoint, web-search flag, and for Azure: resource URL + api_version + deployment name) in **Admin → LLM Providers** after first login.
- **ChatGPT** (OpenAI) - via `OPENAI_API_KEY`
- **Claude** (Anthropic) - via `ANTHROPIC_API_KEY`
- **Gemini** (Google) - via `GEMINI_API_KEY` (supports web search)
- **Perplexity** - via `PERPLEXITY_API_KEY` (supports web search)
- **Azure OpenAI** - via `AZURE_OPENAI_API_KEY` (resource URL, api_version, deployment name set in the UI)
- Plus custom OpenAI-compatible providers (Mistral, local models, etc.)

## Development Commands

```bash
# Start backend locally
python3 -m uvicorn app.main:app --reload --port 8000

# Start frontend locally
cd frontend && npm run dev

# Run with Docker
docker compose up -d
```

## Deployment

See [docs/IT_DEPLOYMENT_GUIDE.md](docs/IT_DEPLOYMENT_GUIDE.md) for detailed deployment instructions.

### Quick Start (Docker)

```bash
# 1. Copy and configure environment
cp .env.template .env
# Edit .env with your API keys and secrets

# 2. Start application
docker compose up -d

# 3. Create initial admin
docker compose exec app python scripts/admin/setup_initial_admin.py
```

## Environment Variables

Required for deployment:
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET_KEY` (or `APP_SECRET`) - For authentication tokens
- `ENCRYPTION_KEY` - Fernet key for API key storage
- At least ONE LLM provider env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, or `AZURE_OPENAI_API_KEY`)

Optional:
- Additional LLM provider env vars beyond your primary one
- `GOOGLE_CLIENT_ID` - For Google OAuth
- `MICROSOFT_CLIENT_ID` (or `OIDC_CLIENT_ID`) - For Microsoft OAuth
- `RESEND_API_KEY` - For sending invitation emails
- `FROM_EMAIL` - Email address for sending
- `FRONTEND_URL` - For CORS and email links

See [docs/ENV_VARS_REFERENCE.md](docs/ENV_VARS_REFERENCE.md) for complete list.

## Key Features

- Multi-brand support (users can track up to 20 brands)
- Brand sharing between users
- Automated data collection with scheduling
- Response analysis extracting: mentions, sentiment, positioning, competitors, descriptors
- Report generation with AI-written summaries
- Analytics dashboard with charts
- Configurable site settings for white-labeling
