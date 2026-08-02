# Security Policy

## Overview

This document describes the security practices, testing methodology, and vulnerability disclosure policy for Tales — an AI reputation monitoring platform designed for self-hosted deployment at research institutions.

Tales is maintained by RobotRachel and shared with U.S. Department of Energy national laboratories (PPPL, PNNL, Argonne, LLNL) under an MIT license for self-hosted, air-gappable deployment.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security concerns directly to the maintainer:

- **Email**: robotrachel@gmail.com
- **Subject line**: `[SECURITY] Tales — <brief description>`
- **Expected response time**: Within 72 hours

Please include:
- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested mitigations

You will receive acknowledgement within 72 hours and a resolution plan within 14 days for confirmed vulnerabilities.

---

## Security Testing

Tales undergoes static analysis and dependency auditing before each release. The results below reflect the **2.0 release, scanned 2026-07-31** on Python 3.13.13.

### Static Application Security Testing (SAST)

| Scan | Tool | Result |
|------|------|--------|
| Python static analysis | [Bandit](https://bandit.readthedocs.io/) 1.9.4 | **0** findings |
| Pattern static analysis, `app/` | [semgrep](https://semgrep.dev/) 1.172.0 | **0** findings |
| Pattern static analysis, offline scripts | semgrep 1.172.0 | **0** findings |
| Shell-injection guard | grep | no `shell=True`, no `os.system()` |
| Committed credentials | pattern scan over tracked files | none found |

Two numbers are worth stating plainly, because "0 findings" is only meaningful alongside what the tools reported before anything was configured:

- **bandit** reports 67 findings with no configuration at all, and every one of them is severity LOW. There are **no MEDIUM or HIGH findings** in this codebase whether or not you apply the project's configuration.
- **semgrep** reports 30 findings with no scoping, and **none of them are in `app/`**. All 30 are the `avoid-sqlalchemy-text` rule firing on offline database migration scripts, which have to issue raw DDL because the ORM cannot express `ALTER TABLE`.

The suppressions that take those to zero are narrow and individually justified. `app/`, the code that actually handles web requests, is scanned with every rule and no exclusions at all. Full methodology and the reasoning behind every suppression are in [`docs/SECURITY_NOTES.md`](docs/SECURITY_NOTES.md).

### Dependency Vulnerability Scanning

| Tool | Scope | Findings |
|------|-------|----------|
| [pip-audit](https://pypi.org/project/pip-audit/) 2.10.0 | Python packages | **0** unaccepted (1 accepted, below) |
| [npm audit](https://docs.npmjs.com/cli/commands/npm-audit) (npm 11.13.0) | npm packages | **0** unaccepted (1 accepted, below) |

### Accepted findings

Both are dependency advisories with no fixed release available. Both were checked for reachability rather than waved through, and both were re-verified on 2026-07-31 as still having no fix published.

**ecdsa 0.19.2 ([PYSEC-2026-1325](https://osv.dev/vulnerability/PYSEC-2026-1325), Minerva timing attack) — not reachable.** `ecdsa` is pulled in indirectly by `python-jose`. The advisory affects ECDSA signing, key generation and ECDH; signature verification is unaffected. Tales signs and verifies its own sessions with HS256 (HMAC-SHA256) and validates Microsoft/Entra ID tokens with RS256 through `pyjwt` backed by `cryptography`. No code path in Tales performs an ECDSA operation. Upstream has published no fix and considers the affected API inherently timing-sensitive.

**react-router ([GHSA-qwww-vcr4-c8h2](https://github.com/advisories/GHSA-qwww-vcr4-c8h2), RSC mode CSRF bypass) — not reachable.** The advisory applies to React Router's RSC mode, where a server action can run before a 400 response is returned. The Tales frontend is a browser-only single-page application: no server runtime, no RSC mode, no server actions. The vulnerable code path is not present in the shipped build. The advisory covers 7.12.0 through 8.2.0; npm's only remediations are a downgrade to 7.11.0, which loses functionality, or a major upgrade to 8.x. Tales holds at the latest 7.x patch release and will resolve this when it moves to React Router 8.

### Reproducing the audit

The full suite is committed to the repository, so you can verify the code yourself rather than take this document's word for it:

```bash
pip install bandit semgrep pip-audit
```

```bash
./scripts/run_sast.sh
```

It exits non-zero if anything fails, so it can gate a pipeline.

If your network runs a TLS-intercepting proxy, semgrep's rule download may fail certificate verification. The script already works around this by bypassing the proxy for that one call.

### Audit log

| Date | Branch / commit | bandit | pip-audit | npm audit | Notes |
|------|-----------------|--------|-----------|-----------|-------|
| 2026-07-31 | `main`, Tales 2.0 release | 0 findings | 0 unaccepted (1 accepted) | 0 unaccepted (1 accepted) | Tales 2.0 release scan, run on Python 3.13.13. Adds semgrep 1.172.0 to the suite, plus a shell-injection guard and a committed-credential scan. Two dependency advisories accepted as unreachable after review (`ecdsa`, `react-router`); see "Accepted findings" above. **This is the state a new deployer pulls from `main`.** |
| 2026-06-09 | `main` @ `ea4c2e2c` | 0 medium/high | 0 CVEs | 0 vulns | Post-merge re-audit after PR #7 (second round of Bing review fixes — enabled-check invariant, multi-block message accumulation). 88/88 pytest passing. **This is the state PNNL (and any new deployer) will pull from `main` today.** |
| 2026-06-09 | `bing-review-fixes-2` (pre-merge) | 0 medium/high | 0 CVEs | 0 vulns | Second round of review fixes on PR #6: (a) analysis-provider invariant now requires is_enabled=True at create+update (previously a misconfigured provider would silently fall back to whichever other provider was first enabled, defeating the user's intent); (b) bing_grounded message extraction accumulates all non-empty text blocks joined by \n\n (previously returned the first block, truncating multi-block responses). 88/88 pytest passing. |
| 2026-06-09 | `main` @ `a6f04712` | 0 medium/high | 0 CVEs | 0 vulns | Post-merge re-audit after PR #6 (review fixes for the Bing additions). 84/84 pytest passing. This is the state PNNL (and any new deployer) will pull from `main` today. |
| 2026-06-09 | `bing-review-fixes` (pre-merge) | 0 medium/high | 0 CVEs | 0 vulns | Applies Gemini Code Assist review feedback on PR #5: search-only providers (Bing) rejected as analysis provider at create/update; update endpoint mirrors create-time field validation; Bing v7 distills the report prompt via the analysis LLM before searching (huge quality improvement — raw paragraph prompts had been passed to Bing as q=); endpoint normalization handles full /v7.0/search paths; Bing Grounded now uses AzureKeyCredential when AZURE_FOUNDRY_API_KEY is set, falls back to DefaultAzureCredential; agent run status check verifies completion positively; risky str(MessageText) fallback dropped. 84/84 pytest passing. |
| 2026-06-09 | `bing-web-search` (pre-merge) | 0 medium/high | 0 CVEs | 0 vulns | Adds Bing as a web-search provider (`bing_v7` retrieval + analysis-LLM synthesis; `bing_grounded` via Azure AI Foundry, gated behind `pip install talestogo[bing-grounded]` optional extra). 64/64 pytest passing. The Azure AI Foundry SDK is NOT a base dependency — non-Bing deployers see no install-size or runtime impact. |
| 2026-06-08 | `main` @ `7536ceaf` | 0 medium/high | 0 CVEs | 0 vulns | Post-merge re-audit covering PRs #1 (Azure provider-agnostic refactor — new `_call_azure` codepath, `api_version` plumbing) and #3 (`/responses/` defensive limit clamp). 53/53 pytest passing. Confirms the merged state is still clean. |
| 2026-06-08 | `main` @ `f77ee3a8` | 0 medium/high | 0 CVEs | 0 vulns | Initial 2026-06-08 audit. Bumped `vitest` / `@vitest/ui` from 4.0.8 → 4.1.8 to clear [GHSA-5xrq-8626-4rwp](https://github.com/advisories/GHSA-5xrq-8626-4rwp) (critical, dev-only). Added `[tool.bandit]` exclusions for offline ops scripts. |
| 2026-05-09 | `strip-to-tales-only` | 0 medium/high (after 3 `# nosec B608`) | 0 CVEs | 0 vulns | Initial post-strip baseline. Established the SBOMs below. |

### Software Bill of Materials (SBOM)

SBOMs are provided in [CycloneDX 1.6](https://cyclonedx.org/) JSON format, as recommended under [Executive Order 14028](https://www.whitehouse.gov/briefing-room/presidential-actions/2021/05/12/executive-order-on-improving-the-nations-cybersecurity/) (Improving the Nation's Cybersecurity).

| File | Contents |
|------|----------|
| [`docs/security/sbom-python.cdx.json`](docs/security/sbom-python.cdx.json) | 31 Python runtime dependencies |
| [`docs/security/sbom-npm.cdx.json`](docs/security/sbom-npm.cdx.json) | 520 JavaScript dependencies (direct + transitive) |

SBOMs are regenerated with each release using:
- Python: [`cyclonedx-bom`](https://pypi.org/project/cyclonedx-bom/)
- JavaScript: [`@cyclonedx/cyclonedx-npm`](https://www.npmjs.com/package/@cyclonedx/cyclonedx-npm)

---

## Secure Development Practices

### Authentication & Authorization

- JWT-based authentication with configurable expiry
- Passwords hashed with bcrypt (cost factor 12)
- All API endpoints require authentication except `/health`, `/auth/login`, `/auth/config`, and `/site/branding`
- Admin-only endpoints enforce `is_admin` flag; no email-based role hardcoding
- Optional OAuth 2.0 / OIDC via Microsoft Entra ID or Google

### API Keys

- LLM provider API keys are stored encrypted at rest using Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256)
- Keys are never returned in API responses; only masked previews are exposed

### Transport Security

- HTTPS is enforced at the reverse proxy / load balancer layer (see `docs/IT_DEPLOYMENT_GUIDE.md`)
- HSTS, X-Frame-Options, X-Content-Type-Options, and Referrer-Policy headers are set by the application
- Content Security Policy (CSP) is applied with a per-request nonce for inline styles
- Fonts are self-hosted; no external CDN calls from the browser

### Rate Limiting

- Login and registration endpoints are rate-limited via [SlowAPI](https://pypi.org/project/slowapi/) (default: 5 requests/minute per IP)

### Input Validation

- All API request bodies are validated with Pydantic v2 schemas before reaching business logic
- Email addresses validated with `email-validator` (RFC-compliant)
- File uploads (query bulk import) are restricted to `.xlsx` format with column validation

### Database

- All user-facing queries use SQLAlchemy ORM with parameterized queries
- Raw SQL is used only in migration utilities, with identifier allowlisting
- Row-level data isolation: all queries are scoped by `user_id`; users cannot access other users' data

### Docker Hardening

- Multi-stage build — build tools are not present in the runtime image
- Application runs as a non-root user (`appuser`)
- Only `libpq5` runtime library added to the slim base image
- Health check configured for container orchestration

---

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` branch | ✅ Active |
| Older branches | ❌ Not maintained |

PNNL and other deploying institutions are encouraged to pull from `main` and report any issues through the channel above.

---

## Known Limitations

- **Frontend bundle size**: The main JavaScript bundle is ~2.2 MB uncompressed / 613 KB gzipped. This is a performance concern (slow first paint), not a security issue. Code splitting is tracked as a future improvement.
- **No DAST**: Dynamic Application Security Testing (e.g., OWASP ZAP) has not been performed against a live deployment. Institutions with strict DAST requirements may wish to run their own scan post-deployment.
- **Scheduler**: The built-in APScheduler runs in-process. For high-security environments, consider setting `ENABLE_SCHEDULER=false` and triggering collection/analysis via the API from an external cron job.
