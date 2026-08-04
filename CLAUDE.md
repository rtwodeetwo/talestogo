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

## 📍 Two Destinations: ALWAYS ASK WHICH ONE

TalesToGo has **two** legitimate remotes, and they do different jobs. Which one a
given piece of work belongs on is Rachel's call, not something to infer.

| Remote | Where | Role |
|---|---|---|
| `origin` | `github.com/rtwodeetwo/talestogo` | Canonical source. Development, PRs, releases, the version shared with PNNL and other U.S. National Labs. |
| `pppl` | `git.pppl.gov/rkremen/talestogo` | **One possible deployment line.** PPPL's own instance builds from here. |

### ⚠️ Ask every time, before every push

**Before pushing, committing to a shared branch, opening a PR or MR, or tagging,
ask Rachel explicitly: GitHub or GitLab?** Confirm it each time, even if the
answer was obvious last time.

Do NOT infer the destination from:

- where the previous push in this session went,
- the branch name or what the branch contains,
- which remote happens to be configured, or which one `git push` would default to,
- the fact that Rachel just approved a push to the other one.

Approval for one destination is never approval for the other. If she has not said
which in this exchange, ask before doing anything that writes to a remote.

### Why the distinction has teeth

Pushing to GitLab's **default branch is a live deployment**. `.gitlab-ci.yml`
builds an image with Kaniko and then fires a Portainer webhook, which redeploys
`tales.pppl.gov`. Pushing to any **other** branch on GitLab only builds an image
tagged with the branch slug; the deploy job is not even created, so it is safe.

GitHub has no such side effect. A push there changes what labs will clone, but
nothing restarts.

So the two are not interchangeable even when the code is identical, and "push
this" is ambiguous until she says where.

### State of both remotes (as of 2026-08-04)

**They have drifted, deliberately.** GitHub `main` carries 2.0.1 and is tagged
`v2.0.0` and `v2.0.1`. GitLab `main` is still at `7aec4940` (2.0.0), 11 commits
behind, and that is what `tales.pppl.gov` is running.

The drift is fine to leave for now. Of the 11 commits, the only functional change
is the `/health` version stamp; the rest is documentation, the Docker Hub
description, and the GitHub image-publishing workflow, none of which affects a
PPPL deployment. GitLab is 0 ahead, so the eventual sync is a **fast-forward** and
needs none of the force-push dance below.

**Provenance is wired into GitLab CI.** `.gitlab-ci.yml` passes `APP_VERSION`,
`GIT_SHA` and `BUILD_DATE` to Kaniko, so `GET /health` on tales.pppl.gov reports
the commit the running container was built from. That is now the check to use
after a deploy, in place of counting routes in `/openapi.json`. It only works for
images built after this was added; anything older answers `"unknown"`.

**`deploy_to_portainer` can fail now.** It was `curl -s ... || echo "Warning"`,
which reported success whether the webhook fired, 404'd, or the variable was
empty. It now exits non-zero on an unset `PORTAINER_WEBHOOK_URL` and on any HTTP
error. A green deploy job means the webhook was accepted, which is still not the
same as the new container serving: the swarm restart is rolling, so confirm with
`/health`.

- GitLab `main` was `aa54b1b8` (26 February 2026, pre-strip, still carrying the 8
  removed products) until it was force-pushed to 2.0 on 2026-08-02.
- The histories ARE related, common ancestor `021952da`, contrary to an earlier
  note in this file that said otherwise.
- Local tag `archive/pppl-main-2026-02-26` anchors the old GitLab `main`. It is
  deliberately not pushed, because a tag push would trigger a CI build of the
  February codebase.
- `main` on GitLab is protected with `allow_force_push=False`. For a
  non-fast-forward push, PATCH it true via the API, push, PATCH it back, all in
  the same minute. A fast-forward needs none of that.

### Verifying a PPPL deploy

**HTTP 200 does not mean the new build is live.** The swarm restart is rolling,
so the old container answers 200 perfectly well while the new one is still
coming up. This produced a false "deploy complete" during the 2.0 release.

Check for a capability that only the new build has. The route count in
`/openapi.json` is the cheapest signal (2.0 = 124 routes), or grep the frontend
bundle at `/assets/index-*.js` for a new string. The bundle filename hash changes
on every build, which also distinguishes one deploy from the next.

### The third place, which is never a destination

**`tales_project`**: see the Critical Rule at the top of this file. Private dev
repo, never read from or written to from this working tree. Its production
*database* may legitimately be read for a data migration (that is a database, not
the codebase), but the repo itself is off limits.

## Session Log: 2026-08-02 — Deployment kit accuracy, and the image nobody was rebuilding

### Context

Started as "grab the latest code" and became an audit of whether the deployment
kit told the truth. It did not, in two ways that mattered.

### The image was five months stale, and nothing was rebuilding it

`rtwodeetwo/tales:latest` on Docker Hub had not been pushed since **2026-02-26**.
`main` was 151 commits ahead. Nothing in the repository built or pushed it: the
only workflow was `dast.yml`, and the GitLab pipeline pushes to the *GitLab*
registry, not Docker Hub. So the image was a manual push that happened once.

That image predated the strip-to-Tales-only cleanup, so it still shipped the 8
non-Tales products, the 18 npm advisories, and the `setup_initial_admin.py`
crash. **Step 3 of the kit's own quick start could not have worked on it.**

Now fixed: `.github/workflows/publish-image.yml` publishes on merge to `main`
and on `v*.*.*` tags. `latest` moves only on a version tag, so pinning it gets a
release rather than the tip of `main`. Released **v2.0.1** (commit `5fc7c064`).

### Image provenance

The image could not identify itself: no labels, and `/health` returned only
`{"status": "healthy"}`. Now the Dockerfile stamps `APP_VERSION`, `GIT_SHA` and
`BUILD_DATE` into OCI labels and env, and `/health` reports them. To ask a
registry which commit an image came from, without pulling it:

```bash
docker buildx imagetools inspect rtwodeetwo/tales:latest
```

### amd64 only — a decision, with evidence

The February image was multi-arch. v2.0.1 is amd64 only.

The only arm64 activity ever recorded against the old image was a crawler
enumerating the manifest index: the arm64 entry and both attestation manifests
were fetched **within 2.7 milliseconds of each other**, which no real pull of a
198 MB image looks like. Rachel confirmed no lab had deployed at all.

**To restore arm64, do NOT add `linux/arm64` to the existing build.** That builds
it under QEMU, where `npm ci` for the frontend ran **46 minutes without
finishing** before we cancelled it. Use a native `ubuntu-24.04-arm` runner plus a
manifest merge. Those runners were **verified working and free on this repo**
(probe returned `aarch64`, 4 CPUs, Ubuntu 24.04.4).

The constraint is stated in both IT guides ("Supported Platform"), the kit
README prerequisites, and the Docker Hub overview, so an ARM deployer is told
before they hit an opaque manifest error.

### Real bug found: `setup.sh` could never have worked

`deployment-kit/setup.sh` generated `ENCRYPTION_KEY` with
`secrets.token_urlsafe(32)`, which returns 43 characters. `app/auth.py:84` builds
`Fernet(ENCRYPTION_KEY.encode())` at import, and Fernet requires exactly 44 with
the trailing `=`. **Every deployment set up with that script failed at startup**
with `ValueError: Fernet key must be 32 url-safe base64-encoded bytes`. The
openssl fallback was broken the same way by `tr -d '='`.

`APP_SECRET` and `ENCRYPTION_KEY` now use different generators everywhere, and
the distinction is documented in both IT guides, `ENV_VARS_REFERENCE.md`, the kit
README, and both `.env.template` files.

### Docs brought in line with the code

- **README.md** was 6 lines still titled "tales_project". Rewritten as a real
  front door.
- **Root `.env.template` did not exist**, so the documented `cp .env.template .env`
  failed on a fresh clone. Added. Note `.gitignore`'s `.env.*` rule would have
  silently swallowed it; there is now a `!.env.template` negation.
- **Investigations were documented nowhere user-facing** despite shipping in 2.0.
  Now in both user guides and both IT guides, leading with the fact that
  auto-triggers spend LLM tokens without anyone asking.
- **Root `SECURITY.md` was behind the kit's copy.** Carried the 2026-07-31 Tales
  2.0 scan results (semgrep added, two accepted advisories) into it.
- **Deployment kit IT guide** brought to parity with the canonical one.

### Docker Hub overview page

`docs/dockerhub-overview.md` is the source. **It is pasted by hand.** Editing a
Docker Hub description requires a `repo:admin` token; the publish workflow holds
only `repo:write`, and widening it so prose can sync itself is not a trade worth
making in a repo the labs audit. An automated sync was tried and removed.

### Gotchas worth not rediscovering

- **`continue-on-error` rewrites a step's `conclusion` to `success`** and keeps
  the truth only in `outcome`. A 403 was reported green. Twice tonight a green
  signal masked a failure (the other: piping `gh run watch` into `tail` captures
  `tail`'s exit code). **Verify the artifact, not the status reporting it.**
- **Docker Hub's `hub.docker.com/v2` API lags badly.** It showed 1 tag while the
  registry had 5. Query `registry-1.docker.io` for the truth.
- **`Usage → Pulls` on a personal account measures your outbound pulls**, not
  pulls of your repositories by others. It cannot answer "did anyone pull my
  image", and no Docker Hub surface exposes puller identity on a free plan.
- Local `main` had no upstream tracking (a legacy of `.git` being grafted rather
  than cloned). Fixed with `git branch --set-upstream-to=origin/main main`.

### PNNL status

**Ross Lanes is an active contributor, not a prospective adopter.** 42 commits on
`main`, most recently 2026-07-20, largely the MSAL PKCE refactor, redirect-mode
auth, and auto-login for Entra ID, plus the CVE remediation PR. Any older note
about offering him collaborator access is long overtaken.

A short note was **sent** to Ross this session: the kit link, that the image is
amd64, and an offer to publish arm64 if needed.

---

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

Phases A and B were merged this session: the record, its lifecycle, and a
deterministic evidence pack of 8 tools over `metrics_core`. No LLM was called
yet. Phases C, D and E were completed in session 5, below.

### Session 5: 2026-08-01 — Investigations C/D/E, SAST that tells the truth

Same branch, `audit/metrics-reconciliation`. Tests: **337 passing** (up from
284). Backend imports at 170 routes, frontend builds, all scans clean.

#### Investigations, Phases C, D and E

Full spec, as built, is in `docs/INVESTIGATIONS_DESIGN.md`.

- **Phase C, the agent loop.** `app/services/investigation/service.py`, plus
  `agent_client.py` (tool-use adapters for the Anthropic, OpenAI and Google
  dialects) and `search.py` (one scoped web-search tool over whatever grounded
  provider is configured). The reasoning model is chosen from
  `LLMProviderManager` by api_type, never hardcoded, and Perplexity's `sonar`
  models are excluded because they cannot call tools. Runs on a
  `ThreadPoolExecutor` capped at 4, following `app/scheduler.py`.
- **Phase D, the frontend.** `frontend/src/pages/analytics/Investigations.tsx`
  at `/analytics/investigations`, indented under Analytics. Polls only while
  something is running. Limitations render as information, not as an error.
  `**bold**` becomes React nodes; no `dangerouslySetInnerHTML`, because
  summaries are model-written from collected AI responses.
- **Phase E, auto-triggers.** `app/services/investigation/triggers.py`, hooked
  into `data_pipeline.py` after the batch-analytics recompute through
  `check_after_collection`, which cannot raise. Thresholds are env-overridable
  (see `docs/ENV_VARS_REFERENCE.md`); dedupe is on
  `(brand_id, comparison_mode, current_period_start)`; it never fires on an
  empty window.

The through-line of the whole feature is keeping "the tool failed" distinct from
"the tool found nothing". They are the same shape in a JSON payload and opposite
in meaning, and conflating them turns a dead web search into a confident finding
that there was no external news. Every dialect adapter marks failures in the way
that dialect supports, the prompt says what an error means, and there are tests
for each.

#### Test isolation fix

`tests/conftest.py` now stubs `service.submit` for the whole suite. Without it a
test that triggers an investigation spawns a worker that opens its own
`SessionLocal` against the configured `DATABASE_URL`, which is how test runs came
to be writing database files into the repo root.

#### SAST: "could not run" is now separate from "found something"

`./scripts/run_sast.sh` reports `COULD NOT RUN:` and `FINDINGS:` separately and
says which happened in its summary. Both still fail the run. The old script
reported semgrep's rule-download failure as "semgrep reported findings in app/",
which is exactly backwards, and a gate that conflates the two teaches everyone
to ignore it.

Two working remedies for the download failure, both now in
`docs/SECURITY_NOTES.md`. The certifi one from the previous handover note is
confirmed correct, with one trap worth naming: the chain must be taken **off the
wire** with `openssl s_client`, not pulled from the system keychain by name. The
keychain's Zscaler root is rejected by OpenSSL 3 ("Basic Constraints of CA cert
not marked critical"), which produces a different verification error that looks
like the same problem and is not. The second remedy is new:
`scripts/fetch_semgrep_rules.sh` downloads the packs with curl and
`SEMGREP_RULES_DIR=.semgrep-rules ./scripts/run_sast.sh` scans against them,
which needs no per-machine trust setup and is the only option that works for a
lab with no access to semgrep.dev at all. Rule ids gain a path prefix when
loaded from files, so any rule named in the script or in a `# nosemgrep:`
comment carries both spellings.

Result with local rules: bandit 0, semgrep 0 (one pre-existing raw-SQL finding
in `app/migrations/run_migrations.py` suppressed inline with its reason: the
table name comes from a hardcoded whitelist and a table name cannot be a bound
parameter), pip-audit 0 unaccepted, npm audit 0 unaccepted.

### Session 6: 2026-08-02, shipped 2.0 and what deploying taught us

**Tales 2.0 is released.** GitHub `main` = `7aec4940` (PR #25), tagged `v2.0.0`.
GitLab `main` is the same commit and is live on `tales.pppl.gov` with PPPL's data
imported. 365 tests, 171 routes, all scans clean.

#### PPPL data migration, done

2044 responses, 22 queries, 17 competitors, 14 descriptors, 28 batches, exported
from the Tales-Production Railway database and imported against
`rkremen@pppl.gov`. Grounding recorded for every row, zero unknown.

The source already recorded grounding as `web_search_enabled`, so
`--grounded-from` was not needed. That mattered: PPPL's July 2026 switch is
132 grounded against 44 ungrounded, a mid-month changeover no single date
describes. **The `sources` column is NOT a proxy for grounding**; measured on the
real data it points the wrong way (8% of grounded responses cite sources against
14% of ungrounded ones). An earlier version of the migration doc recommended it
and was wrong.

#### Four bugs that only appear when you deploy

None were findable from the code alone. All are fixed.

1. **Schema drift.** `create_all()` never ALTERs existing tables, so PPPL's
   February database was missing 8 columns. It broke the LLM Configuration page,
   Brand Mentions, and every investigation, with no visible connection between
   them. `app/main.py` now reconciles the models against the live schema on
   startup and adds any missing nullable column. This replaced a hand-maintained
   ALTER list that had fallen behind twice. **Any migration shipped only as a
   script in `migrations/` will recreate this, because nobody runs those.**
2. **Env vars documented but not passed through** `docker-compose.yml`, so
   setting `INVESTIGATIONS_AUTO_TRIGGER=false` in Portainer did nothing.
3. **A 500 rendered as "Failed to save provider"**, sending everyone to inspect
   the form instead of the server. `frontend/src/utils/apiError.ts` now always
   includes the status code, flattens FastAPI's validation arrays, and
   distinguishes a request that never completed.
4. **The frontend test gate was always red**, because vitest was collecting the
   Playwright specs in `e2e/`. A suite that is always red cannot report a
   regression.

#### Notes for working on the PPPL deployment

- The container images are `python:3.14-slim`: **no `curl`, no `wget`, no
  `gunzip`**. Use Python's `urllib` and `gzip`, which is what the Dockerfile's
  own HEALTHCHECK does.
- Portainer CE has no file upload. Large files go via the GitLab generic package
  registry (the project is private) or `docker cp` with a shell on the host.
- PPPL's OHMIC gateway routes by model name, so `gpt-5.5` and Gemini really are
  those models and both ground correctly. **Every Anthropic model on OHMIC
  silently fails to ground**: the gateway forwards the `web_search` tool but
  never executes it, and the model then answers from memory opening "Based on my
  search". `scripts/admin/probe_llm_gateway.py` proves this by running the same
  question with and without the tool. PPPL uses direct vendor keys instead.

### NEXT SESSION

1. **No CI runs tests or SAST on either remote.** GitLab CI only builds and
   deploys; GitHub has only `dast.yml`. Every green result during the 2.0
   release came from running `pytest` and `./scripts/run_sast.sh` by hand, so
   the gate is a habit rather than a gate. A GitHub Actions workflow on PRs plus
   a `test` stage before `build` in `.gitlab-ci.yml` would fix it. Semgrep needs
   the local-rules path there; `scripts/fetch_semgrep_rules.sh` already handles
   it.
2. **`deploy_to_portainer` cannot fail.** Its script is
   `curl ... || echo "Warning"`, so the job reports success whether the webhook
   fired, 404'd, or the variable was empty. Same conflation of *tried* and
   *succeeded* that this release spent its time removing.
3. **Investigations follow-ups, both deliberately deferred:** per-brand
   thresholds (deployment-wide today, and `threshold_for` is the single place a
   per-brand setting would land), and batch-mode auto-triggers (only
   month-over-month fires automatically; a single batch is too noisy).
4. **Send the PNNL/labs update email.** It now has a release page to point at:
   `https://github.com/rtwodeetwo/talestogo/releases/tag/v2.0.0`. The two things
   a lab most needs are that their numbers will change, and that upgrading now
   works.

### Earlier: session 3 handover

Web search grounding + latest models merged to `main` (PR #15). PNNL/labs update email drafted, awaiting recipients + send from Rachel's work account.

### Outstanding follow-ups (outside this branch)

- **Send the PNNL/labs update email** about the web-search-grounding change (drafted this session; needs recipient addresses + the second lab's name; send from `rkremen@pppl.gov`, not the connected personal Gmail). The repo is **public**, so no collaborator setup is needed — the GitHub URL just works.
- **Add LICENSE to `tales_project`** if Rachel wants the same MIT license there (separate task, separate repo)
- **Remove "Generate Report All Data" button from `tales_project`** if Rachel wants it gone from production (separate task, separate repo)
- **Contributing guidelines** still absent. The GitHub repo *description* is set, and the README was rewritten 2026-08-02, so that half is done. This is the last thing PNNL explicitly asked for in May 2026 that has not been delivered.

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
