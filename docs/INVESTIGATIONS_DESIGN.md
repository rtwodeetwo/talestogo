# Investigations: design and remaining work

**Status:** Phases A and B are built, tested and merged. Phases C, D and E are
specified here and not yet started.

An investigation explains **why** the metrics moved between two comparable
windows. The dashboard says the mention rate fell twelve points; an
investigation works out whether that is one platform re-ranking, a competitor's
PR push, a single query flipping, or a collection that partly failed.

This document is the working spec. It exists so the remaining phases can be
picked up without re-deriving any of the decisions.

---

## What is already built

| Piece | File | Notes |
|---|---|---|
| Models | `app/models.py` | `Investigation`, `InvestigationToolInvocation` |
| Schemas | `app/schemas.py` | `InvestigationCreate/Summary/Detail`, tool invocation |
| Scope resolution | `app/services/investigation/scope.py` | batch / month / quarter, all as `MetricScope` |
| Evidence pack | `app/services/investigation/evidence.py` | 8 deterministic tools |
| API | `app/routers/investigations.py` | trigger, list, detail, tool-invocations, evidence, delete |
| Tests | `tests/test_investigation_evidence.py`, `tests/test_investigations_router.py` | 55 tests |

No LLM is called anywhere in the above. `GET /api/investigations/{id}/evidence`
returns the complete evidence pack for a comparison with no model involved, and
is useful on its own.

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

## Decisions already made

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

## Phase C: the agent loop

**New file:** `app/services/investigation/service.py`

### Shape

1. Mark `running`, set `started_at` and `last_heartbeat_at`.
2. Rebuild the comparison with `scope_from_investigation`.
3. Build the tool list from `evidence.EVIDENCE_TOOLS` plus the search tool.
4. Call the model with tools; loop while `stop_reason == "tool_use"`, capped at
   **15 iterations**.
5. Persist one `InvestigationToolInvocation` per call: input JSON, output JSON
   (truncate at ~10,000 chars), status, `duration_ms`, sequence.
6. Touch `last_heartbeat_at` each iteration so the reaper can tell a live run
   from an orphaned one.
7. Parse the final text, store `title`, `summary`, `key_findings`,
   `recommended_actions`, `limitations`, token totals.

### Things that must not be got wrong

- **A failed tool must be marked as an error in the tool result.** Without
  `"is_error": true`, the model reads a failure payload as an ordinary answer,
  and a dead search becomes "no news found".
- **Roll back the session on a tool exception** before re-raising, or every
  later tool in the run gets an unusable session. Do not swallow the exception
  into a success-shaped payload; a broken tool and an empty result must be
  distinguishable.
- **Do not send `temperature`.** Current Claude models (Opus 4.7/4.8, Sonnet 5)
  reject it with a 400. See `_anthropic_rejects_sampling` in
  `app/services/generic_llm_client.py`, which already encodes this.
- **`max_tokens` must fit the whole final synthesis.** Title, summary, findings
  and actions arrive in one response. Too low and the write-up is cut off
  mid-findings and stored as though complete. 12288 is a known-good figure.
  Detect truncation and record it as a limitation rather than pretending the
  run succeeded.

### Model

Read `docs/METRIC_DEFINITIONS.md` conventions but pick the model from the
existing provider configuration rather than hardcoding it. `LLMProviderManager`
already resolves providers and keys; do not introduce a second mechanism.

### The search tool

One tool with a scope argument (brand / industry / competitor) rather than three
near-identical tools.

- Providers come from `LLMProviderManager.get_web_search_providers()`, which
  returns rows with `supports_web_search AND is_enabled`.
- Try providers in order, cheapest and most recency-reliable first. Gemini
  grounding is a good default first choice; leave the Anthropic key with
  headroom because the agent loop itself is spending it.
- An empty string counts as a failure. Google grounding can return one without
  raising.
- If every provider fails, or none is configured: **do not fail the run.**
  Append to `limitations`:
  `{"limitation": "External news search unavailable (no grounded provider configured)",
    "impact": "External causes could not be checked. Conclusions rest on internal data only."}`

### Prompt rules that matter

The system prompt must state, in some form:

- A search flagged as an error means the search **did not run**. That is not
  evidence that there was no news. Say the external check could not be
  completed; do not attribute the change to an absence of external events.
- If a search runs and finds nothing relevant, say so rather than speculating.
- Do not retry a failed search more than once; it is failing for infrastructure
  reasons and retries waste the budget.
- Cite specific numbers, query ids, platform names and response excerpts.
- **Check `data_quality` on both sides before concluding anything about
  reputation.** Rows excluded as unanalyzed are collection or analysis failures.
- Compare rates, not raw counts: collection volume can differ between windows.

Required output shape, parsed by the service:

```
TITLE: <one line>

KEY_FINDINGS:
- <finding with evidence>

RECOMMENDED_ACTIONS:
- <action>

SUMMARY:
<2-4 paragraphs of markdown, with specific numbers>
```

Tolerate `**bold**` variants of the headers when parsing.

### Concurrency

Use a small bounded worker pool, not a bare thread per request. Unbounded thread
spawning means N simultaneous triggers hold N database connections for minutes
each. Reuse the pattern in `app/scheduler.py`, which already caps concurrent
scheduled runs.

---

## Phase D: the frontend

**New file:** `frontend/src/pages/analytics/Investigations.tsx`
**Route:** `/analytics/investigations`, added to `AppContent.tsx`
**Nav:** indented under Analytics in `Layout.tsx`

- List of investigation cards, newest first. Poll every 5s **only while
  something is pending or running**, then stop.
- Header button runs the default comparison (month) directly; a dropdown arrow
  offers quarter and latest-collection. Mirror the dashboard's comparison
  options so a question raised by a dashboard card can be investigated on the
  same footing.
- Card collapsed: title, status chip, trigger-type chip, a period chip reading
  "February 2026 vs January 2026", created date, tool-call count.
- Card expanded: summary, key findings (numbered), recommended actions
  (bulleted), a **limitations** panel styled as information rather than error,
  and a "Show agent trace" toggle revealing the tool-invocation table.
- Surface the backend's `detail` message on a failed trigger. The backend
  rejects an empty comparison window with a useful explanation; a bare "Request
  failed" throws that away.

**Security:** investigation summaries are model-written from query text and
collected responses, both of which can carry attacker-supplied markup. Render
`**bold**` as React nodes; never use `dangerouslySetInnerHTML`.

---

## Phase E: auto-triggers

**New file:** `app/services/investigation/triggers.py`

Hook into the collection pipeline after batch analytics are recomputed
(`app/services/data_pipeline.py`), wrapped so a failure here can never fail a
collection.

Default thresholds, in percentage points, all absolute:

| Metric | Threshold |
|---|---|
| mention rate | 10.0 |
| positive sentiment | 15.0 |
| leadership visibility | 15.0 |
| share of voice (any competitor) | 10.0 |

Rules:

- Compute deltas through `evidence.compare_scopes` so the trigger and the
  investigation agree on what moved.
- **Never fire when either window is empty.** A period with no collection would
  read as a total collapse in every metric. `scope.py` already refuses this.
- **Dedupe on `(brand_id, comparison_mode, current_period_start)`.** The index
  `idx_investigation_brand_mode_period` exists for this. The first batch of a
  new month closes out the previous one, so that is when a period trigger fires;
  later batches re-check but must not produce a second investigation for a
  period that already has one.
- Store the deltas that fired it in `trigger_metrics`, and set
  `trigger_type='auto'`.
- Make the thresholds configurable per brand or per deployment before shipping
  to labs; hardcoded constants are fine to start but should not stay that way.

---

## Verification

```bash
pytest tests/test_investigation_evidence.py tests/test_investigations_router.py -q
```

Phase C should add a test that the agent loop records a failed tool as
`status='failed'` with `is_error` set, and that a missing search provider
produces a `limitations` entry rather than a failed run. Neither needs a real
model: stub the client.

The evidence pack is deterministic, so anything built on top of it can be tested
against the golden fixture in `tests/fixtures/golden_dataset.py` with
hand-derived expectations, the same way `metrics_core` is.
