# Tales

Tales tracks how your organization is represented by AI assistants.

It asks the major AI platforms (ChatGPT, Claude, Gemini, Perplexity, Azure OpenAI) the
questions real people ask about your brand, records the answers on a schedule, and
analyzes them for mentions, sentiment, positioning, competitors, and descriptive
language. The result is a dashboard, a set of reports, and a record of how your AI
reputation changes over time.

Tales is provider-agnostic. Any one LLM API key is enough to run the full pipeline.

## Features

- **Multi-brand monitoring**, with brand sharing between users
- **Scheduled collection** on the 1st, 7th, 14th, and 21st of each month
- **Response analysis** extracting mentions, sentiment, positioning, competitors, and descriptors
- **Investigations** that explain *why* a metric moved between two periods, rather than just
  reporting that it did. See [docs/INVESTIGATIONS_DESIGN.md](docs/INVESTIGATIONS_DESIGN.md)
- **Reports** generated monthly, quarterly, and annually, with AI-written summaries
- **Analytics dashboard** covering trends, share of voice, sentiment breakdown, and competitor threats
- **Configurable branding and authentication** for white-labeled, self-hosted deployment

## Quick Start (Docker)

Prerequisites: Docker 20.10+ and Docker Compose 2.0+, plus an API key for at least one
LLM provider.

```bash
git clone https://github.com/rtwodeetwo/talestogo.git
cd talestogo
cp .env.template .env
```

Edit `.env` and set, at minimum:

- `APP_SECRET` and `ENCRYPTION_KEY` (the file has the generator commands inline)
- `DB_PASSWORD`
- at least one LLM API key

Then start it and create your admin account:

```bash
docker compose up -d
```

```bash
docker compose exec app python scripts/admin/setup_initial_admin.py
```

The setup script prints a generated password once. Save it, then log in at
`http://localhost:8080`.

After first login, go to **Admin > LLM Providers** to enable the providers whose keys you
set, and flag one with `use_for_analysis=True` to handle response analysis.

## Local Development

Backend:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

```bash
python3 -m uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend && npm install && npm run dev
```

Tests:

```bash
pytest
```

```bash
cd frontend && npm test
```

The Docker image builds on Python 3.14 and Node 20.

## Documentation

| Document | For |
|---|---|
| [docs/IT_DEPLOYMENT_GUIDE.md](docs/IT_DEPLOYMENT_GUIDE.md) | Full deployment: prerequisites, network requirements, OIDC, verification, maintenance, troubleshooting |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | End users: brands, collection, analytics, reports |
| [docs/ENV_VARS_REFERENCE.md](docs/ENV_VARS_REFERENCE.md) | Every environment variable |
| [docs/METRIC_DEFINITIONS.md](docs/METRIC_DEFINITIONS.md) | How each metric is calculated |
| [docs/INVESTIGATIONS_DESIGN.md](docs/INVESTIGATIONS_DESIGN.md) | How investigations work |
| [deployment-kit/](deployment-kit/) | Self-contained bundle for handing to another organization |

## Architecture

- **Backend:** Python / FastAPI with SQLAlchemy
- **Frontend:** React / TypeScript with Vite and Material-UI
- **Database:** PostgreSQL
- **Auth:** Email/password, with optional Microsoft Entra ID and Google OAuth

## Security

See [SECURITY.md](SECURITY.md) for the security policy, SAST and dependency-audit
results (Tales 2.0, scanned 2026-07-31), accepted findings, and CycloneDX SBOMs.

The scan suite is committed, so you can reproduce it yourself:

```bash
pip install bandit semgrep pip-audit && ./scripts/run_sast.sh
```

## License

MIT. See [LICENSE](LICENSE).
