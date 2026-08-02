# Investigations: design and how it works

**Status:** built. Phases A to E are complete and tested.

An investigation explains **why** the metrics moved between two comparable
windows. The dashboard says the mention rate fell twelve points; an
investigation works out whether that is one platform re-ranking, a competitor's
PR push, a single query flipping, or a collection that partly failed.

This document is the working spec. It records the decisions so they do not have
to be re-derived.

---

## What is built

| Piece | File | Notes |
|---|---|---|
| Models | `app/models.py` | `Investigation`, `InvestigationToolInvocation` |
| Schemas | `app/schemas.py` | `InvestigationCreate/Summary/Detail`, tool invocation |
| Scope resolution | `app/services/investigation/scope.py` | batch / month / quarter, all as `MetricScope` |
| Evidence pack | `app/services/investigation/evidence.py` | 8 deterministic tools |
| Tool-use adapters | `app/services/investigation/agent_client.py` | Anthropic, OpenAI, Google dialects |
| External search | `app/services/investigation/search.py` | one tool, scoped, degrades cleanly |
| Agent loop | `app/services/investigation/service.py` | bounded worker pool, audit trail |
| Auto-triggers | `app/services/investigation/triggers.py` | thresholds, dedupe, never fails a collection |
| API | `app/routers/investigations.py` | trigger, list, detail, tool-invocations, evidence, delete |
| Frontend | `frontend/src/pages/analytics/Investigations.tsx` | `/analytics/investigations` |
| Tests | `tests/test_investigation_*.py` | 108 tests, no live model calls |

`GET /api/investigations/{id}/evidence` returns the complete evidence pack for a
comparison with no model involved, and is useful on its own.

### The load-bearing decision

Every figure an investigation quotes comes from `app/services/metrics_core.py`,
the same definitions the dashboard and the exports use. There is one scope type
(`metrics_query.MetricScope`) covering batch, month and quarter, so there are no
parallel comparison paths that can drift apart and quote different numbers for
the same brand.

`compare_scopes` reports `data_quality` for **both** windows, and the agent is
instructed to check it before attributing any change to reputation. Six
unanalyzed rows is a collection failure, not a reputation drop. This check is
the single most valuable thing the feature offers and it is only possible
because metric populations report their own exclusions.

---

## Decisions

Confirmed by the product owner, 2026-08-01:

1. **Both triggers.** Manual from the UI, and automatic when a threshold is
   crossed.
2. **Thresholds on by default.** Labs get auto-investigations without opting in.
3. **Degrade, and say so.** With no grounded provider key, an investigation
   still runs on internal data and records what it could not check and what that
   means for its conclusions. The `Investigation.limitations` column exists for
   exactly this: a JSON array of `{"limitation": ..., "impact": ...}`. It is
   deliberately separate from `error_message`, because a missing search key
   degrades a run without failing it and showing it as an error would mislead.

---

## The agent loop

`app/services/investigation/service.py`

1. Mark `running`, set `started_at` and `last_heartbeat_at`.
2. Rebuild the comparison with `scope_from_investigation`.
3. Build the tool list from `evidence.EVIDENCE_TOOLS`, plus the search tool if,
   and only if, a grounded provider is configured. A tool that cannot work is
   not offered, so the model does not spend a turn discovering that.
4. Call the model with tools; loop while the turn asks for tools, capped at
   **15 iterations** (`MAX_ITERATIONS`).
5. Persist one `InvestigationToolInvocation` per call: input JSON, output JSON
   (truncated at 10,000 characters), status, `duration_ms`, sequence.
6. Touch `last_heartbeat_at` each iteration so the reaper in the router can tell
   a live run from an orphaned one.
7. Parse the final text into `title`, `summary`, `key_findings`,
   `recommended_actions`; store `limitations` and token totals.

### Things that must not be got wrong

These are the reasons the code looks the way it does. Each has a test.

- **A failed tool must be marked as an error in the tool result.** Without it,
  the model reads a failure payload as an ordinary answer, and a dead search
  becomes "no news found". Anthropic has an `is_error` flag on `tool_result`;
  Google has an `error` key in the function response; chat completions has
  neither, so the adapter states the failure in words instead.
- **Roll back the session on a tool exception** before recording the failure, or
  every later tool in the run gets an unusable session. The exception is never
  swallowed into a success-shaped payload; a broken tool and an empty result
  must stay distinguishable.
- **Do not send `temperature`.** Current Claude models (Opus 4.7/4.8, Sonnet 5)
  reject it with a 400, as do GPT-5 and the o-series, which additionally want
  `max_completion_tokens`. No adapter sends a sampling parameter at all.
- **`max_tokens` must fit the whole final synthesis.** Title, summary, findings
  and actions arrive in one response. 12288 is a known-good figure. A turn that
  stops on `max_tokens` is recorded as a limitation rather than stored as a
  completed investigation.

### Model selection

`select_agent_provider` picks from the configured providers by `api_type`,
preferring Anthropic, then OpenAI, then Azure, then Google, then any
OpenAI-compatible endpoint. Nothing is hardcoded: an admin who upgrades the
model under Admin, LLM Providers upgrades investigations at the same time, and
`LLMProviderManager` remains the only place that resolves providers and keys.

Perplexity's `sonar` models are excluded by model name rather than by api_type.
They speak an OpenAI-shaped API but do not do function calling, while an
internal LiteLLM-style gateway is also `openai_compatible` and does.

Three dialects are supported rather than one because a lab may realistically
have only one key, and `GEMINI_API_KEY` is the only required one.

### The search tool

One tool with a scope argument (brand / industry / competitor) rather than three
near-identical tools.

- Providers come from `LLMProviderManager.get_web_search_providers()`, which
  returns rows with `supports_web_search AND is_enabled`.
- Tried in order, cheapest and most recency-reliable first. Google grounding
  goes first; Anthropic is last so a search does not compete with the reasoning
  budget the agent loop is already spending.
- An empty string counts as a failure. Google grounding can return one without
  raising.
- Failure is raised, not returned, so the loop flags it `is_error`. After every
  provider has failed once the tool refuses to retry: it is failing for
  infrastructure reasons and retries waste the budget.
- If every provider fails, or none is configured, the run does **not** fail. It
  appends to `limitations`, distinguishing "no provider configured" from
  "configured and failed", both with the impact spelled out.

### Prompt rules that matter

The system prompt states, and the code enforces where it can:

- A search flagged as an error means the search **did not run**. That is not
  evidence that there was no news.
- If a search runs and finds nothing relevant, say so rather than speculating.
- Do not retry a failed search more than once.
- Cite specific numbers, query ids, platform names and response excerpts.
- **Check `data_quality` on both sides before concluding anything about
  reputation.** Rows excluded as unanalyzed are collection or analysis failures.
- Compare rates, not raw counts: collection volume can differ between windows.

Output shape, parsed by `parse_final_output`:

```
TITLE: <one line>

KEY_FINDINGS:
- <finding with evidence>

RECOMMENDED_ACTIONS:
- <action>

SUMMARY:
<2-4 paragraphs of markdown, with specific numbers>
```

`**bold**` variants of the headers are tolerated, as are numbered lists and
wrapped lines. Output that matches nothing is kept whole as the summary: a badly
formatted investigation is worth more than an empty one.

### Concurrency

A `ThreadPoolExecutor` capped at 4, following `app/scheduler.py`. An
investigation holds a database connection for minutes, so a thread per request
would mean N simultaneous triggers holding N connections.

---

## The frontend

`frontend/src/pages/analytics/Investigations.tsx`, route
`/analytics/investigations`, indented under Analytics in the nav.

- Cards newest first. Polls every 5s **only while something is pending or
  running**, then stops.
- Header button runs the month comparison; the dropdown arrow offers quarter and
  latest collection, mirroring the dashboard so a question raised by a dashboard
  card can be investigated on the same footing.
- Collapsed: title, status chip, trigger-type chip, a period chip reading
  "February 2026 vs January 2026", created date, tool-call count.
- Expanded: summary, numbered key findings, bulleted recommended actions, a
  limitations panel styled as **information rather than error**, and a "Show
  agent trace" toggle revealing the tool-invocation table with failed calls in
  red.
- A failed trigger surfaces the backend's `detail` message. The backend rejects
  an empty comparison window with a useful explanation, and a bare "Request
  failed" would throw that away.

**Security:** investigation summaries are model-written from query text and
collected responses, both of which can carry attacker-supplied markup.
`**bold**` is rendered as React nodes; there is no `dangerouslySetInnerHTML`
anywhere on the page.

---

## Auto-triggers

`app/services/investigation/triggers.py`, called from
`app/services/data_pipeline.py` after batch analytics are recomputed, through
`check_after_collection`, which cannot raise.

Default thresholds, in percentage points, all absolute:

| Metric | Threshold | Environment override |
|---|---|---|
| mention rate | 10.0 | `INVESTIGATION_THRESHOLD_MENTION_RATE` |
| positive sentiment | 15.0 | `INVESTIGATION_THRESHOLD_POSITIVE_SENTIMENT_RATE` |
| leadership visibility | 15.0 | `INVESTIGATION_THRESHOLD_LEADERSHIP_VISIBILITY` |
| share of voice (brand or any competitor) | 10.0 | `INVESTIGATION_THRESHOLD_SHARE_OF_VOICE` |

`INVESTIGATIONS_AUTO_TRIGGER=false` switches the whole thing off. Overrides are
read per call, so retuning does not need a restart.

Rules:

- Deltas come from `evidence.compare_scopes`, so the trigger and the
  investigation cannot quote different figures for the same movement.
- Competitor share of voice is checked per organization as well as for the
  brand. A competitor can surge without the brand's own share moving much, and
  that is exactly the case worth explaining.
- **Never fires when either window is empty.** A period with no collection would
  read as a total collapse in every metric. `scope.py` refuses to build such a
  comparison and the trigger treats that refusal as "nothing to say".
- **Dedupes on `(brand_id, comparison_mode, current_period_start)`**, backed by
  `idx_investigation_brand_mode_period`. The first batch of a new month closes
  out the previous one, so that is when a period trigger fires; later batches
  re-check but must not produce a second investigation for the same period. Any
  status counts, including failed: re-running automatically would fail the same
  way and fill the list with noise. The manual trigger stays available.
- The deltas that fired it are stored in `trigger_metrics` and set
  `trigger_type='auto'`.

---

## Still to do

- **Per-brand thresholds.** Today they are deployment-wide. The resolution
  already goes through one function (`threshold_for`), so a per-brand setting
  has a single place to land.
- **Batch-mode auto-triggers.** Only month-over-month fires automatically. A
  single batch is a noisy signal to raise an investigation over.

---

## Verification

```bash
pytest tests/test_investigation_evidence.py tests/test_investigations_router.py \
       tests/test_investigation_agent.py tests/test_investigation_agent_client.py \
       tests/test_investigation_triggers.py -q
```

No test calls a live model. The evidence pack is deterministic, so everything
built on top of it is tested against the golden fixture in
`tests/fixtures/golden_dataset.py` with hand-derived expectations, the same way
`metrics_core` is. The trigger tests set thresholds through the environment
rather than relying on the fixture happening to move by more than ten points, so
they stay about the trigger logic.

`tests/conftest.py` stubs `service.submit` for the whole suite. Without that, a
test that triggers an investigation would spawn a worker that opens its own
`SessionLocal` against the configured `DATABASE_URL`, which is how test runs
came to be writing database files into the repo root.
