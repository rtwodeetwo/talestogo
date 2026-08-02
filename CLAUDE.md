# Tales To Go

Tales is an AI reputation monitoring platform that tracks how brands are represented across major AI platforms (ChatGPT, Claude, Gemini, Perplexity).

## ⚠️ Critical Rule: Do Not Touch tales_project

This repository (`talestogo`, local path `/Users/rkremen/Documents/Code/TalesToGo/`) is the **public, sanitized version** of Tales — the one shared with U.S. National Labs (PPPL, PNNL, Argonne, LLNL, etc.) for self-deployment. It is intentionally a separate codebase from Rachel's private dev repo.

The private dev repo is `tales_project` (local path `/Users/rkremen/Documents/Code/tales_project/`, GitHub `rtwodeetwo/tales_project`). It contains Rachel's keys, the front door, and unsanitized features.

**Any work done in this repo (TalesToGo / talestogo) must NEVER:**
- Read from, write to, or modify `/Users/rkremen/Documents/Code/tales_project/`
- Push to or pull from `github.com/rtwodeetwo/tales_project`
- Be confused with `tales_project` in commit messages, PR descriptions, or documentation

If a change is needed in both repos, treat them as two separate, independent commits in two separate working trees.

## 📍 Canonical Source: GitHub

The single source of truth for TalesToGo is **`github.com/rtwodeetwo/talestogo`**. This is the version shared with PNNL and other U.S. National Labs for self-deployment.

- **All new work lands here.** Commits, branches, PRs, and merges happen on `rtwodeetwo/talestogo`.
- **`origin` remote = GitHub** in this working tree. Pushes default to GitHub.

### Other places `talestogo` exists — do NOT confuse for canonical

- **`git.pppl.gov/rkremen/talestogo`** — an older PPPL GitLab sister repo that predates the May 2026 strip-to-Tales-only cleanup. It still has the pre-strip codebase (the 8 removed products, `deployment-kit-pppl/`, ~200 stripped files). It is **NOT** the canonical source and is **NOT** kept in sync. Do not push new work there assuming it's a mirror — its `main` is on a different history line from GitHub's `main` and force-pushing would destroy work that may still be referenced by something. If a future operation needs to update it, treat it as a separate codebase that needs a thought-out migration, not a quick `git push`.
- **`tales_project`** — see the Critical Rule above. Private dev repo, never touched from this working tree.

If you find yourself about to push TalesToGo work to anywhere other than `origin` / `rtwodeetwo/talestogo`, stop and confirm with Rachel first.

## Session Log: 2026-05-08 — Strip-to-Tales-Only Cleanup

### Context

Rachel sent the talestogo deployment kit to PNNL (Pacific Northwest National Laboratory) on Feb 2, 2026. PNNL responded in early May 2026 wanting a meeting before deploying. Their main asks: solidify repo location/access, establish contribution guidelines, and confirm scope.

While preparing for that meeting, we discovered the talestogo repo still contained code for **8 non-Tales products** (Heads, Canon, Big Idea, NSTXView, Vision, Pulse, Voice, Guardian) — vestiges of the broader "Solstice AI Suite" architecture, plus dozens of personal/historical files that didn't belong in a public deployment repo. PNNL only needs Tales. So we created a `strip-to-tales-only` branch to clean it all up.

### Pre-branch work

1. **Discovered the local TalesToGo folder was not a git clone.** Grafted `.git` from `github.com/rtwodeetwo/talestogo` into the local folder, ran `git checkout HEAD -- .` to bring local files in line with GitHub (12 files were ~4 days behind; 11 GitHub files including the `frontend/src/pages/heads/` directory were missing locally).

2. **Pushed an MIT LICENSE** to `github.com/rtwodeetwo/talestogo` via the GitHub API (commit `3e8b170`). Copyright: "Rachel Kremen" (confirmed legal copyright holder after checking with PPPL legal).

3. **Created a Google Doc with PNNL meeting Q&A:** "PNNL Tales Deployment - Meeting Prep & Q&A" (https://docs.google.com/document/d/1NlOGu-8YmWOkGeue36GlcefuzxyGok3WdzJGQBdUYBI/edit). Covers: how PNNL gets updates, build-locally vs. Docker Hub, how to access the full source code, registry-mirror requirements.

4. **Drafted a reply to Ross Lanes at PNNL** confirming the GitHub URL is the canonical source and offering to add `ross-lanes` and `domskurka-pnnl` as collaborators.

### Key decision: KEEP multi-tenancy

Rachel initially asked to strip multi-tenancy entirely. After investigation we found:
- Only 91 `tenant_id` references across 10 files (heavily concentrated in tenants.py, llm_providers.py)
- Pages do NOT load tenant_id — data is scoped by `user_id`
- `tenant_id` is mostly used for: brand-sharing scope, LLM provider scoping, tenant management API
- The actually-problematic part (the "Solstice HC" hardcoded mapping, product-tenant config) was already gone after Phase 1b

We chose **Option D: keep multi-tenancy infrastructure.** Each lab can be a tenant if they want, or ignore the feature entirely (`tenant_id` is nullable). What was removed: `Solstice HC` config, `solsticehc.net` email-domain mapping, the `TENANT_PRODUCTS` product-tenant access map.

### What was done — `strip-to-tales-only` branch (21 local commits)

| Phase | Scope | Net diff |
|---|---|---|
| **1a** | Delete non-Tales backend routers (heads, personas, canon, bigidea) and Heads-only services (persona_generator, pptx_generator) | +146 −3,344 |
| **1b** | Strip non-Tales code from shared backend files: removed `PersonaType` / `PersonaGeneration` / `Persona` models, `allowed_products` column, all persona schemas/CRUD, `_Settings` and `TenantConfig`, `check_product_access` middleware (deleted `app/dependencies.py`), `perplexity_service.py` | +23 −846 |
| **2a** | Delete non-Tales frontend pages, services, types, public assets (heads/, canon/, bigidea/, HowHeadsWorks, HowCanonWorks, headsService, bigideaService, types/heads, types/bigidea, 4 product logo files) | 35 files deleted |
| **2b** | Remove multi-product abstraction from frontend: deleted `ProductContext`, `ProductSwitcher`; rewrote `AppContent.tsx`; cleaned `Layout.tsx`, `UserManagement.tsx`, `api.ts`, `AuthContext.tsx`, `types/index.ts` | +294 −1,229 |
| **3** | Delete obsolete migrations (`add_heads_tables`, `add_solstice_tenant`, `add_allowed_products`) | −429 |
| **4** | Docs cleanup + `auth.py` Solstice/RobotRachel fix (default tenant changed `RobotRachel` → `Default`) | +44 −3,244 |
| **4.5** | Sanitize hardcoded personal infrastructure: env-var-configurable CORS, `is_admin` flag everywhere instead of `email == 'robotrachel@gmail.com'`, FRONTEND_URL in scheduler emails, removed RobotRachel/solstice logos and "Made by RobotRachel" footer | +105 −230 |
| **4.6** | Expose `admin_email` publicly via `/site/branding` so the "contact your administrator" note in the UI can render a real mailto link; clean up doc examples | +49 −21 |
| **4.7** | **Critical fix** — `setup_initial_admin.py` would have crashed on first run (left over `allowed_products="tales,heads,canon"` kwarg). PNNL's documented first deployment step now works. Also deleted 6 stale Rachel-specific scripts. | −558 |
| **4.8** | Fix `scheduler.py` email URL bug introduced in 4.5: was rendering as broken relative path `/analytics`; now uses canonical `get_site_url(db)` helper | +5 −4 |
| **4.9** | Audit follow-ups: unify `BrandingConfig` TypeScript type, switch `users.py` invitation flow to `get_site_url(db)` | +16 −15 |
| **5** | Remove "Generate Report All Data" button from `ReportsPage.tsx` (frontend only; backend endpoint preserved per Rachel's instruction) | −41 |
| **6 fixup** | Fix Login.tsx fallback `BrandingConfig` to include `admin_email: null` (caught by TypeScript build) | +1 |
| **6.1** | Major repo cleanup — ~200 files removed (sample reports, debug scripts, historical dev docs, tracked binaries, old distributions, Word docs, PPPL bundle, branding assets, Rachel-specific platform configs). `.gitignore` updated to prevent recurrence. | massive |
| **6.2** | Fix the broken pytest suite (was 33 broken since the initial commit). 32 passing now. Bonus: **caught a real production bug** — `app/crud.py:get_target_descriptors` was filtering on the long-renamed `target_for_pppl` column; would have crashed at runtime when admins viewed target descriptors | +102 −624 |
| **6.3** | Migrate `google.generativeai` → `google-genai` SDK (the old package is end-of-life). Updated `app/ai_generator.py`, `app/services/generic_llm_client.py`, `app/services/llm_service.py`, and `requirements.txt`. | +54 −46 |
| **6.4** | Resolve all 18 npm vulnerabilities (9 moderate, 8 high, 1 critical) → 0. Non-breaking transitive bumps got us to 2; uninstalling unused `jspdf` and `xlsx` packages eliminated the rest. | +369 −526 (mostly package-lock) |

**Cumulative diff vs. start of branch:** ~115 files removed, ~12,000 lines deleted, ~610 added.

### Repo state at end of session

- **Branch:** `strip-to-tales-only` (local-only, 21 commits, NOT yet pushed to GitHub)
- **Backend:** imports cleanly (169 routes), no deprecation warnings from removed/migrated code, all 32 tests pass
- **Frontend:** TypeScript builds clean, 0 vulnerabilities, no orphan imports
- **Repo root:** minimal and PNNL-ready — `AGENTS.md`, `CLAUDE.md`, `Dockerfile`, `LICENSE`, `README.md`, `app/`, `deployment-kit/`, `docker-compose.yml`, `docs/`, `frontend/`, `migrations/`, `pyproject.toml`, `requirements.txt`, `scripts/`, `start_tales.sh`, `tests/`

### What's left in the original 8-phase plan

- **Phase 7** — Fresh SAST + dependency audit. Run `bandit`, `semgrep`, `pip-audit`, `npm audit`. Diff against the old reports (deleted in Phase 6.1) to confirm we made things better, not worse. **No DAST.**
- **Phase 8** — Push `strip-to-tales-only` to GitHub and merge to `main`.

### Session 2: 2026-05-09 — Deprecation fixes, test suite, exit-code investigation

Work done in worktree `keen-murdock-97b708` (branch `claude/keen-murdock-97b708`), off of main. Changes need to be cherry-picked or merged into `strip-to-tales-only`.

#### Item 1: Deferred deprecations — ✅ DONE

- **Pydantic v2 migration**: Replaced `class Config: from_attributes = True` with `model_config = ConfigDict(from_attributes=True)` in `app/routers/batches.py` (`BatchResponse`) and `app/routers/scheduled_tasks.py` (`ScheduleResponse`, `HistoryResponse`).
- **FastAPI lifespan migration**: Replaced `@app.on_event("startup")` and `@app.on_event("shutdown")` in `app/main.py` with an `@asynccontextmanager` lifespan function passed to `FastAPI(lifespan=...)`. Startup logic (stale task cleanup + scheduler start) and shutdown logic (scheduler stop) preserved identically.
- Zero `class Config` or `on_event` deprecation patterns remain in the codebase.

#### Test suite fixes — ✅ DONE (discovered while verifying item 1)

- **Deleted 4 broken test files**: `tests/test_api.py` (imported non-existent `get_db`), `tests/test_celery_tasks.py` and `tests/test_tasks.py` (imported removed `celery_app`), `tests/test_main.py` (empty).
- **Rewrote `tests/test_crud.py`**: Added `user_id=TEST_USER_ID` to all 64 CRUD call sites; updated descriptor tests from old `target_for_pppl`/`category` fields to current `is_target` schema.
- **Fixed production bug in `app/crud.py:315`**: `get_target_descriptors()` was filtering on `models.TargetDescriptor.target_for_pppl` (column renamed long ago to `is_target`). Would crash at runtime. Changed to `models.TargetDescriptor.is_target`.
- **Result: 32 tests passing, 0 failing.**

#### Item 2: Exit code 144 — ✅ RESOLVED (cosmetic, no action needed)

Exit code 144 is from the Claude Code process manager. When a background process is externally killed via `pkill`, Claude Code reports 144 to mean "this process was terminated." The smoke test had already completed successfully. No bug, no action needed.

#### Fix: google.generativeai FutureWarning in generic_llm_client.py — ✅ DONE

Phase 6.3 on `strip-to-tales-only` migrated all three files, but `generic_llm_client.py` on this worktree's branch still had the old import. Applied the same migration: `google.generativeai` → `google.genai` (new SDK client pattern). Backend now loads with zero FutureWarnings from `generic_llm_client.py`. (`llm_service.py:41` also still has the old import on this branch — not yet fixed.)

#### Item 3: Manual feature testing — ✅ COMPLETE

**Bugs found and fixed during testing (sessions 1-2):**

1. **Dashboard infinite spinner when no brands exist** — `Dashboard.tsx` line 190: `isLoading` included `!activeBrand`, so with zero brands the loading spinner displayed forever. Fixed: added an early return before the loading check that shows a "Welcome to TALES" onboarding page with an "Add Your First Brand" button when `brands.length === 0`.

2. **"Add Your First Brand" button navigated to wrong route** — Button used `/manage-brand` (doesn't exist). Fixed: changed to `/manage/brand-info?new=true` (matches the existing "+ Add Brand" button in the header).

3. **ProductSwitcher (app switcher grid icon) still visible** — `Layout.tsx` still imported and rendered `ProductSwitcher` from the old multi-product Solstice suite. Tales is the only product in this repo. Fixed: removed the `<ProductSwitcher />` component and its import from `Layout.tsx`.

**API feature test suite — 39/39 passing:**
- ✅ Auth: Login, profile, invalid login rejection, unauthenticated rejection
- ✅ Brand CRUD: Create, read, update, list, activate, get active (6/6)
- ✅ Query CRUD: Create, read, list, update, delete (5/5)
- ✅ Competitor CRUD: Create, list, update, delete (4/4)
- ✅ Descriptor CRUD: Create, list, update, delete (4/4)
- ✅ Analytics: dashboard, platform-config, trends/mentions, sentiment/breakdown, descriptors/insights, positioning/breakdown, share-of-voice, recommendations, competitor-threats, brand-mentions-by-llm, positioning-by-llm (11/11)
- ✅ Reports: list reports
- ✅ Admin: list users, list all brands
- ✅ Scheduling: get schedule
- ✅ Tasks: task status
- ✅ Brand-info: get brand info

**Note:** Data collection and analysis endpoints (`/tasks/run-collection/`, `/tasks/run-analysis/`) require live LLM API keys and were not tested locally. These are integration-test-only features.

#### Phase 7: SAST + dependency audit — ✅ COMPLETE

| Tool | Before | After | Action |
|------|--------|-------|--------|
| bandit (medium+) | 3 findings | 0 | All false positives (SQL uses validated/whitelisted identifiers). Added `# nosec B608` |
| pip-audit | 0 vulns | 0 | Clean |
| npm audit | 18 vulns (1 critical, 8 high, 9 moderate) | 0 | Removed dead `jspdf` + `xlsx`, `npm audit fix` for transitive deps |
| pytest | 32/32 | 32/32 | Still passing |
| Frontend build | ✓ | ✓ | Still passing |

**Also fixed:** Migrated `app/services/llm_service.py` from deprecated `google.generativeai` to new `google.genai` client SDK (same migration previously done in `generic_llm_client.py`).

### Session 3: 2026-07-05 — Web search grounding for all providers + latest models

Merged via [PR #15](https://github.com/rtwodeetwo/talestogo/pull/15) (branch `feature/web-search-grounding` → `main`, merge commit `376e9d13`).

**Goal:** collect responses with fresh web search grounding on every AI platform, and query each provider's latest flagship model, so Tales reflects what real users see in the consumer apps rather than stale training data.

**What changed:**

- **`app/services/generic_llm_client.py`** — added grounded call paths for OpenAI (`_call_openai_with_web_search`, Responses API `web_search` tool) and Anthropic (`_call_anthropic_with_web_search`, server-side `web_search` tool; concatenates the multiple content blocks a grounded response returns instead of reading `content[0]`). Threaded `max_tokens`/`temperature` through the Google and Perplexity grounded paths. Added `_anthropic_rejects_sampling` / `_openai_rejects_sampling` helpers so the call paths adapt to modern models: Claude Opus 4.7/4.8 + Sonnet 5 and OpenAI GPT-5 reject `temperature` (400), and GPT-5 needs `max_completion_tokens`. This keeps both collection and the admin Test Connection button working on new and old models.
- **`app/services/llm_provider_manager.py`** — `supports_web_search=True` on all four `DEFAULT_PROVIDERS`; models bumped to each provider's latest GA flagship: ChatGPT `gpt-5.5`, Claude `claude-opus-4-8`, Gemini `gemini-3.5-flash`, Perplexity `sonar-pro`. (GPT-5.6 was limited-preview only at the time.)
- **`scripts/admin/collect_responses.py`** — `query_with_provider` routes to `call_with_web_search` when `supports_web_search` is set, with an ungrounded fallback if the api_type can't ground.
- **`generate_report.py`** — unchanged; its web-search loop already safely skips the newly-grounded `openai`/`anthropic` types.
- Documented the switch, the DB opt-in, and the trend-line comparability break in the **LLM Configuration** section above.

**Deploy note:** grounding is gated per provider on the `supports_web_search` DB flag. Fresh deployments (empty `llm_providers` table) get it from `DEFAULT_PROVIDERS` automatically; existing deployments must run `UPDATE llm_providers SET supports_web_search = true WHERE provider_key IN ('chatgpt','claude','gemini','perplexity')`. Enabling grounding is a **structural break in all trend lines** — annotate the switch date; expect auto-investigations to fire on the first grounded batch.

**Verification:** 96/96 tests pass. SAST clean — bandit 0 High / 0 Medium (16 B608 false positives in admin/migration scripts annotated `# nosec`), pip-audit 0, npm audit 0, semgrep run as a second engine (26 findings, all triaged as false positives already mitigated by whitelist validation / bound parameters). Grounded API round-trips were not exercised locally (need live API keys); the SDK surfaces (`responses.create`, Anthropic server tools, `google-genai` grounding `Tool`) were verified present.

**Follow-up:** drafted a PNNL/labs update email describing the grounding switch, the latest models, the DB opt-in, and the comparability caveat (not yet sent).

### Session 4: 2026-08-01 — Metric audit, reports removal, investigations

Branch `audit/metrics-reconciliation`, cut from `release/2.0`. **14 commits, not
yet pushed.** All tests pass (284), backend imports at 170 routes, frontend
builds.

#### Why this happened

Rachel had lost confidence in Tales' statistics after many rounds of changes. An
audit found the same conceptual metric computed 4 to 9 different ways: 9 mention
rates, 9 positive-sentiment rates, 4 share of voice, 6 positioning. On a
controlled dataset the implementations spread by **29 percentage points** on
mention rate. Surfaces that were meant to agree could not, by construction.

Crucially, the gaps were largest where the data was messy (unanalyzed rows,
branded queries, malformed values), which is exactly what real collection runs
look like.

#### What was built

- **`app/services/metrics_core.py`** — one definition per metric, pure (no
  Session, no ORM, no clock), every result carrying its numerator and
  denominator. **This is now the only place a rate may be computed.**
- **`app/services/metrics_query.py`** — the single population resolver.
  `MetricScope` covers batch, month and quarter. Windows are half-open
  `[start, end)` and timezone-aware.
- **`tests/fixtures/golden_dataset.py`** + **`tests/golden_expected.py`** — 83
  deterministic rows and hand-derived constants with the arithmetic written out.
  The expectations were never computed from the code under test.
- **`tests/test_metric_reconciliation.py`** — cross-surface matrix. Was a 13
  point spread across four values; now **0.0**.
- **`tests/test_metrics_guards.py`** — AST purity check, an inline-math
  allowlist that may only shrink (23 → 12 entries), and invariants.
- **`docs/METRIC_RECONCILIATION_2026-08.md`** — the findings report.
- **`docs/METRIC_DEFINITIONS.md`** — generated from docstrings so the published
  methodology cannot drift from the code again.

#### Defects fixed along the way

Unanalyzed responses counted as "brand not mentioned" (so a failed collection
looked like a reputation drop); Excel silently truncating answers at 32,767
characters; one control character killing an entire export; shared brands 404ing
on export; sentiment dividing a Yes-only numerator by a Yes+Indirect
denominator; `Top 3` dropped by the storage layer and scored as `Not Mentioned`;
the Leadership Visibility tile and its own trend arrow using different formulas;
the positioning bar chart silently absent from every report for want of a dict
key; Redis cache entries for the default view being uninvalidatable; and a
test-suite isolation bug that had been writing real database files into the repo
root.

#### Product changes (Rachel's direction)

- **Reports removed entirely**, ~3,700 lines. Replaced by period-scoped data
  exports at `/exports/responses.csv`, which carry `Counted In Metrics` and
  `Excluded Because` columns so any dashboard figure can be reproduced from the
  spreadsheet.
- **Month/quarter comparison fixed**: an empty baseline no longer reports a
  spurious full-value jump, precision matches batch mode, and windows are
  Eastern-local rather than naive UTC.
- **Monthly highlights email removed.** Quarterly retained.

#### Investigations (new feature, partially built)

Phases A and B are merged: the record, its lifecycle, and a deterministic
evidence pack of 8 tools over `metrics_core`. No LLM is called yet.
**Phases C (agent loop), D (frontend) and E (auto-triggers) remain — the full
spec is in `docs/INVESTIGATIONS_DESIGN.md`.**

### NEXT SESSION

1. **Investigations Phases C, D, E.** Spec: `docs/INVESTIGATIONS_DESIGN.md`.
   Decisions already made: both manual and auto triggers; thresholds on by
   default; with no grounded provider key, degrade and record the limitation
   rather than failing the run.
2. **Re-run SAST** (`./scripts/run_sast.sh`). Note: semgrep currently reports a
   FAILURE that is actually a *rule-download* failure, not a finding. Zscaler
   intercepts semgrep.dev transparently (even with the proxy env unset) and
   Python's certifi does not trust its CA, while curl does. Verified fix:
   point `REQUESTS_CA_BUNDLE` at certifi's bundle concatenated with the Zscaler
   root. The script should also distinguish "scan could not run" from "scan
   found problems" — a security gate that conflates them is worse than none.
3. **Merge plan for 2.0.** `release/2.0` was already merged to `main` via PR #23,
   and `release/2.0` is a direct ancestor of this branch, so this is a clean
   fast-forward with no force-push. Suggested: fast-forward `release/2.0` onto
   this work, PR to `main`, then tag `v2.0.0` (the only tag today is `v1.0.0`).
   Do **not** force-push over the existing 2.0 commits; they are public and may
   have been cloned.

### Earlier: session 3 handover

Web search grounding + latest models merged to `main` (PR #15). PNNL/labs update email drafted, awaiting recipients + send from Rachel's work account.

### Outstanding follow-ups (outside this branch)

- **Send the PNNL/labs update email** about the web-search-grounding change (drafted this session; needs recipient addresses + the second lab's name; send from `rkremen@pppl.gov`, not the connected personal Gmail). The repo is **public**, so no collaborator setup is needed — the GitHub URL just works.
- **Add LICENSE to `tales_project`** if Rachel wants the same MIT license there (separate task, separate repo)
- **Remove "Generate Report All Data" button from `tales_project`** if Rachel wants it gone from production (separate task, separate repo)
- **Consider GitHub repo description / contributing guidelines** before PNNL clones

### Known Issues — pre-existing or deferred

These were discovered during the strip-to-Tales cleanup. The first three groups have been **resolved on this branch** (Phase 6.1 - 6.4). The remaining group is genuinely deferred. None block PNNL deployment.

#### ✅ Fixed in Phase 6.2: pytest test suite

  Was: 33 broken tests (3 collection-error files, 32 stale-signature failures in test_crud.py).
  Now: 32 passing, 0 failing.
  - `tests/test_api.py`, `tests/test_celery_tasks.py`, `tests/test_tasks.py`, `tests/test_main.py` deleted (all referenced removed modules / outdated API assumptions).
  - `tests/test_crud.py` updated to seed a TEST_USER_ID and pass `user_id=TEST_USER_ID` through all 64 CRUD call sites; descriptor schema updated from old `category`/`target_for_pppl` fields to current `is_target`.
  - Production bug found and fixed: `app/crud.py:get_target_descriptors` was filtering on `models.TargetDescriptor.target_for_pppl == True`, but that column was renamed to `is_target` long ago. Would have raised AttributeError at runtime when admins viewed target descriptors.

#### ✅ Fixed in Phase 6.3: google.generativeai end-of-life

  Migrated `app/ai_generator.py`, `app/services/generic_llm_client.py`, and `app/services/llm_service.py` from the deprecated `google.generativeai` SDK to the supported `google-genai` SDK. `requirements.txt` updated. The "All support for google.generativeai has ended" FutureWarning that was logged on every backend startup is gone.

#### ✅ Fixed in Phase 6.4: npm vulnerabilities

  Was: 18 vulnerabilities (9 moderate, 8 high, 1 critical).
  Now: 0 vulnerabilities.
  - `npm audit fix` upgraded transitive deps with safe patches.
  - The remaining critical (jspdf) and high (xlsx) were both packages declared in `package.json` but not actually used: `jspdf` had zero imports anywhere, `xlsx` had three import-but-never-used statements. Both packages uninstalled and the dead imports removed. Bundle size unchanged.

#### ✅ Fixed in Phase 6.1: repo cleanliness

  ~200 files removed from the repo root: ~18 sample `report_*.md` files, ~36 personal debug/admin scripts, ~45 historical dev-doc markdowns, tracked binary artifacts (`file:crudtest`, `tales.db`, `tales.db.backup_*`, `celerybeat-schedule.db`, etc.), old distribution archives, exports, Word docs, the `deployment-kit-pppl/` PPPL bundle, the `images/` and `report_charts/` directories, and Rachel-specific platform configs (`apprunner.yaml`, `nixpacks.toml`, `Procfile`, `render.yaml`, `railway_build.sh`, `docker-compose.{nstxview,pppl}.yml`). `.gitignore` updated to prevent these patterns from sneaking back in.

  Repo root is now AGENTS.md, CLAUDE.md, Dockerfile, LICENSE, README.md, app/, deployment-kit/, docker-compose.yml, docs/, frontend/, migrations/, pyproject.toml, requirements.txt, scripts/, start_tales.sh, tests/.

#### ✅ Fixed in Session 2: deprecation warnings from upstream library upgrades

- **Pydantic v2**: `class Config` → `model_config = ConfigDict(from_attributes=True)` in `batches.py`, `scheduled_tasks.py`.
- **FastAPI lifespan**: `@app.on_event("startup"/"shutdown")` → `@asynccontextmanager` lifespan in `main.py`.

#### ✅ Fixed in Session 2: `generic_llm_client.py` deprecated `google.generativeai` import

Phase 6.3 migrated `ai_generator.py` and `llm_service.py` but missed `app/services/generic_llm_client.py:26`. Fixed: migrated to `google-genai` SDK. No more FutureWarning on startup.

#### ⏳ Deferred — frontend bundle size

- `npm run build` warns: "Some chunks are larger than 500 kB after minification" (main bundle ~2.18 MB / 613 KB gzipped). Suggestion is dynamic `import()` for code-splitting or `manualChunks`. Pre-existing; Tales loads fine, just a slow first-paint. Out of scope for cleanup.

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

Tales supports up to 6 LLM providers for data collection and analysis:
- **ChatGPT** (OpenAI) - via `OPENAI_API_KEY`
- **Claude** (Anthropic) - via `ANTHROPIC_API_KEY`
- **Gemini** (Google) - via `GEMINI_API_KEY` (recommended for analysis and web search)
- **Perplexity** - via `PERPLEXITY_API_KEY` (supports web search)
- Up to 2 custom OpenAI-compatible providers

### Web search grounding (all providers, as of 2026-07-05)

All four default providers now collect responses with **fresh web search grounding
enabled**, so answers reflect what real users see in the consumer apps (which
search the web) rather than the model's stale training data. Grounding is used
for regular data collection, not just the State-of-the-LLMs report section.

- ChatGPT grounds via the OpenAI Responses API `web_search` tool.
- Claude grounds via the Anthropic server-side `web_search` tool.
- Gemini grounds via Google Search grounding.
- Perplexity `sonar-pro` searches natively.

Grounding is gated per-provider on the `supports_web_search` flag. For the built-in
`DEFAULT_PROVIDERS` (used when the `llm_providers` table is empty) it is on for all
four. **Deployments that already have `llm_providers` DB rows must opt in explicitly:**

```sql
SELECT provider_key, model_name, is_enabled, supports_web_search FROM llm_providers;
UPDATE llm_providers SET supports_web_search = true
 WHERE provider_key IN ('chatgpt', 'claude', 'gemini', 'perplexity');
```

The flag is also the per-provider off-switch if grounded collection misbehaves.

**Default models (latest generally-available flagship per provider, July 2026):**
ChatGPT `gpt-5.5`, Claude `claude-opus-4-8`, Gemini `gemini-3.5-flash`,
Perplexity `sonar-pro`. Note: modern Claude (Opus 4.7/4.8, Sonnet 5) and OpenAI
GPT-5 models reject `temperature` (and GPT-5 needs `max_completion_tokens`); the
call paths in `generic_llm_client.py` adapt to the configured model, so admins
can still set an older model that accepts sampling params.

**⚠️ Data comparability:** enabling grounding is a **structural break in every trend
line** (mention rate, sentiment, share of voice) at the first grounded batch — the
data before and after is not directly comparable. Annotate this break in monthly/
quarterly analyses. Expect auto-triggered investigations to fire on the first
grounded batch (mention-rate deltas exceed thresholds); that is expected, not a bug.
The closed-book (training-data-only) signal is no longer collected from this date.

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
- `JWT_SECRET_KEY` - For authentication tokens
- `ENCRYPTION_KEY` - Fernet key for API key storage
- `GEMINI_API_KEY` - Required for analysis (other LLM keys optional)

Optional:
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PERPLEXITY_API_KEY` - For querying those platforms
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` - For Google OAuth
- `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` - For Microsoft OAuth
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
