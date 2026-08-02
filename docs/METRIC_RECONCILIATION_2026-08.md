# Tales Metric Reconciliation, August 2026

**Status:** Phase 0-2 complete. Export fixes landed. Metric formulas unchanged so far.
**Branch:** `audit/metrics-reconciliation`
**Scope:** TalesToGo only, which holds no data. See "There is nothing here to restate".
**Reproduce:** `python scripts/admin/metric_baseline.py` and `pytest tests/ -q`

---

## Summary

The distrust was justified. Tales computes the same conceptual metric in many
different places, and those places disagree with each other on the same data.

| Metric | Distinct implementations found |
|---|---|
| Mention rate | 9 |
| Positive sentiment | 9 |
| Share of voice | 4 |
| Descriptor match | 4 (three different matchers, one of them in React) |
| Brand positioning | 6 |

On a controlled 57-row batch where every correct answer is known by hand, the
implementations spread by **29 percentage points** on mention rate, **23 points**
on positive sentiment, and **27 points** on share of voice.

One finding matters more than the arithmetic: **the divergences are largest when
the data is messy.** On the clean batch in the fixture, where nothing failed to
analyze and no query was malformed, most implementations agree. The gaps open up
in the presence of unanalyzed rows, branded queries, off-enum values and orphaned
queries, because that is where the implementations' hidden assumptions differ.
Real collection runs are messy. The numbers you have been reading are the ones
most affected.

This phase did not change any of it. It built the canonical definition, proved
what disagrees and by how much, and put guards in place so the duplication cannot
grow back. What to actually change is the next decision, and it is yours.

---

## The reconciliation matrix

One brand, one batch, one set of 57 responses. Six surfaces, four answers.

```
Mention rate for brand 1 / batch 1, by surface:

    dashboard endpoint       48.0
    stored BatchAnalytics    48.0
    highlights email         47.8
    legacy app/analytics.py    48
    generated report         60.8
    CANONICAL metrics_core   55.0

    SPREAD                   13.0 percentage points
```

Reproduce with:

```bash
python -m pytest tests/test_metric_reconciliation.py -q --runxfail -s
```

The 40-row canonical population is every response that a human would agree
should count: 57 rows in the batch, minus 9 branded queries (the question named
the brand), 6 unanalyzed rows (no classifier verdict), 1 off-enum row, and 1
orphan whose query no longer exists. 22 of those 40 mention the brand, so the
mention rate is 55.0%.

Every other surface arrives somewhere else, for a different reason each time.

---

## Implementation spread, batch 1

From `python scripts/admin/metric_baseline.py`. Identical rows in every row of
every table.

### Mention rate

| Implementation | Value | Why it differs |
|---|---|---|
| `app/analytics.py:78` | 48.0 | counts unanalyzed rows in the denominator; rounds to int |
| `metrics.py:161` as `generate_report.py:2214` calls it | 37.0 | `Yes` only, and branded queries never filtered |
| `metrics.py:161` called correctly | 26.0 | `Yes` only |
| `batch_analytics.py:139` (stored) | 48.0 | unanalyzed rows counted as not-mentioned |
| `analytics_cache.py:179` | 48.0 | same, plus a 180-day default window |
| `highlights.py:152` | 47.8 | closest to correct; still no `analyzed_at` filter |
| `routers/analytics.py:739` (per-LLM) | 26.1 | drops `Indirect` |
| **canonical** | **55.0** | |
| | **spread 29.0 pts** | |

### Positive sentiment

| Implementation | Value | Why it differs |
|---|---|---|
| `app/analytics.py:98` | 62.0 | integer rounding |
| `metrics.py:317` | 62.0 | integer rounding |
| `analytics_cache.py:208` | 41.9 | `Yes`-only numerator over a `Yes`+`Indirect` denominator |
| **canonical** | **65.0** | |
| | **spread 23.1 pts** | |

The `analytics_cache` mismatch is the one behind the Dashboard's sentiment card.
Because the numerator and denominator come from different populations, the
headline "% positive" and the pie chart directly beneath it cannot agree, and the
sentiment trend slices never sum to 100%.

### Share of voice

| Implementation | Value | Why it differs |
|---|---|---|
| `metrics.py:559` | 49.0 | positioning-based; only the top 5 competitors |
| `app/analytics.py:566` | 62.0 | different population again |
| `analytics_cache.py:391` | 75.9 | counts competitors **only inside answers where the brand was already mentioned** |
| **canonical** | **55.0** | |
| | **spread 26.9 pts** | |

`analytics_cache.py:391` is what the Dashboard tile serves. A competitor named in
an answer where Tales was absent is invisible to it, so the brand's share is
structurally inflated: 75.9% against a true 55.0%.

### Positioning

| Implementation | Value | Note |
|---|---|---|
| `metrics.py:257` average | `2` | 1-4 scale, integer, `Top 3` scored as 1 |
| `metrics.py:489` leadership visibility | 19.0 | the Dashboard tile's **value** |
| `routers/analytics.py:268` | 7.0 | the same tile's **trend arrow** |
| `chart_generator.py:143` | `KeyError: 'top_3'` | |
| **canonical** average (1-5) | **1.8** | |
| **canonical** leadership visibility | **22.5** | |

The tile and its own arrow are computed by different formulas. The value counts
Leader plus Top 3 plus Featured; the arrow counts Leader alone.

---

## Direct answers to the questions you asked

**Are API answers similar to what a human sees on the web page?**
The query text is sent verbatim on all four platforms, with no wrapper or
persona, which is right. Three things work against fidelity. Ungrounded
collection caps at `max_tokens=1000` (`collect_responses.py:123`) while grounded
uses 4096, and no `finish_reason` is ever inspected, so a truncated answer is
analyzed as if complete. Temperature 0.7 is silently dropped for `gpt-5.5` and
`claude-opus-4-8` but honored for Gemini and Perplexity, so two platforms run at
API defaults and two do not. Perplexity's grounded path is byte-identical to its
ungrounded one (`generic_llm_client.py:263-270`). Beyond that, consumer apps add
vendor system prompts, memory and location that an API cannot reproduce; that gap
is inherent.

**Are we targeting the most popular models?**
The built-in defaults are current. But they only apply when the `llm_providers`
table is empty. `models.py:318` defaults `supports_web_search` to `False` with no
backfill migration, and `docs/IT_DEPLOYMENT_GUIDE.md:442` still tells operators to
configure `gpt-4o` and `gemini-2.0-flash`. An admin following the documentation
creates a two-generation-old, ungrounded provider that silently overrides the
defaults. Nothing on the `Response` row records which model or mode produced it,
so grounded and ungrounded data pool invisibly in every trend line.

**Is each data point calculated logically and consistently?**
No. See above.

**Does the dashboard match the spreadsheets?**
It cannot, structurally. Neither export includes `batch_id`, and the batch
selector is the Dashboard's primary scoping control. There is no column in either
spreadsheet that lets you reproduce what the Dashboard is showing. The Excel
export also omits the query text, so a row identifies its question only by id.

**Are answers cut off when saved to the spreadsheet?**
Yes. Confirmed by execution: the harness writes a 40,000-character answer and
reads back 32,767. openpyxl slices at the Excel cell limit with no error, no
warning and no ellipsis (`responses.py:206`). Separately, a single control
character anywhere in the data raises `IllegalCharacterError` at cell assignment
and fails the **entire** export, not one row.

**Do webpage numbers differ from what appears in an investigation?**
Yes, and the code says so. `generate_report.py:2529` carries the comment "unlike
the dashboard, this does not exclude branded queries." A single report contains
three mutually inconsistent mention rates, none matching the Dashboard or the
emailed highlights.

---

## Additional findings not in the original scope

**Unanalyzed rows are counted as "brand not mentioned."** No `analyzed_at` filter
exists in `app/analytics.py:53-55` or `batch_analytics.py:104-105`. Every analysis
parse failure, timeout and API error mechanically lowers the mention rate, and
the scheduled path discards the error detail entirely (`data_pipeline.py:351-355`
does not pass `--task-id`). A bad collection night is indistinguishable from a
reputation decline. This is the single most consequential defect found.

**No validation between the analysis LLM and the database.**
`analyze_responses.py:293-299` writes whatever the model returned. Every consumer
filters with exact-match `.in_(['Yes','Indirect'])`, so any off-list value
disappears into the negative bucket uncounted. `brand_mentioned` is
`String(10)`, so a chatty value raises `StringDataRightTruncation` on Postgres.

**"Very Negative" is unreachable.** It is absent from the analysis prompt
(`analyze_responses.py:194-200`) but counted by six consumers. Negative sentiment
has one gradation while positive has two, which biases every distribution.

**Analysis is not reproducible, and re-running it is destructive.**
`temperature=0.2` with no structured-output schema means re-analyzing the same
stored text can yield different verdicts. `operations.py:106-112` and `:600-607`
null out all analysis fields and **commit** before launching the subprocess, so
if it dies the prior analysis is permanently gone.

**Competitor normalization corrupts names.** `metrics.py:79` uses an unanchored
substring test: any organization whose name contains "step" is rewritten to
"UKAEA", globally, for every tenant. The rule is also applied by some surfaces
and not others, so the same screen can show merged and split competitor rows.

**Descriptors are counted case-sensitively.** "high-temperature plasma" and
"High-Temperature Plasma" occupy separate rows in every chart
(`metrics.py:389`, `batch_analytics.py:134`, `routers/analytics.py:999`).

**The positioning bar chart is missing from every generated report.**
`chart_generator.py:143` reads a `top_3` key that `calculate_positioning_metrics`
never returns; the `KeyError` is swallowed at `:693-699`.

**Redis cache entries for the default view can never be invalidated.**
`redis_cache._make_key` omits the `batch:` segment when `batch_id` is `None`, but
the invalidation globs at `:189` and `:207` require it. The latest-batch entries,
which are the ones the Dashboard actually hits, only expire on TTL.
`invalidate_analytics_cache()` at `:313` has zero call sites.

**The test suite was not isolated.** Every test module used a SQLite URI form
that SQLAlchemy took as a literal filename, so each run wrote a persistent
database into the repo root and runs shared state. Fixed in this phase; the
suite is now genuinely in-memory.

**Two scripts write randomized backdated data to whatever `DATABASE_URL` points
at.** `scripts/generate_fake_trend_data.py` and
`scripts/data/seed_historical_data.py`. Flagged separately for follow-up, since
a lab could pollute real history irreversibly.

---

## What Phase 0-2 delivered

| Artifact | Purpose |
|---|---|
| `app/services/metrics_core.py` | One definition per metric. Pure: no database, no ORM, no clock. Every result carries its numerator and denominator. |
| `app/services/metrics_query.py` | The single population resolver. Timezone-aware, half-open windows, always filters both `user_id` and `brand_id`. |
| `tests/fixtures/golden_dataset.py` | 83 deterministic rows containing every edge case the audit found. |
| `tests/golden_expected.py` | Hand-derived constants with the arithmetic written out. Never computed from the code under test. |
| `tests/test_metrics_core.py` | 44 tests binding the implementation to that contract. |
| `tests/test_metric_reconciliation.py` | The cross-surface matrix. 21 known disagreements marked `xfail` with the responsible `file:line`. |
| `tests/test_metrics_guards.py` | Purity check, inline-math allowlist, and invariants that hold for any population. |
| `scripts/admin/metric_baseline.py` | Runs every competing implementation side by side. Strictly read-only, safe against production with `--db`. |
| `docs/METRIC_DEFINITIONS.md` | Generated from the docstrings, so published methodology cannot drift from code again. |

**219 tests pass, 21 xfail, zero unexpected passes.** Every xfail matches an audit
prediction. An unexpected pass would have meant a finding was wrong.

Also removed as confirmed dead: `metrics_service.py` and `report_service.py`
(both 0 bytes) and `report_export._generate_chart_images` (289 lines, never
called).

---

## Decisions needed before Phase 3

**1. Confirm the canonical definitions.** They are in the table in
`docs/METRIC_DEFINITIONS.md`. Three are judgment calls, not bug fixes:

- *Positioning is a 1-5 scale.* The analysis prompt emits five categories and
  `app/routers/reports.py:426-433` already publishes a 1-5 scale to users. The
  code's 1-4 map is the outlier. This moves every Leader response from 4 to 5.
- *Share of voice counts competitors across all organic answers*, not only
  those where the brand appeared. This lowers reported brand share, materially.
- *Descriptor matching folds case but not punctuation.* So
  "High-Temperature Plasma" merges with "high-temperature plasma", but
  "High Temperature Plasma" stays separate. Merging punctuation variants too is
  defensible, but it is a product decision rather than a bug fix, so it is
  raised here instead of applied silently.

One deviation from the approved plan worth flagging: the plan said orphaned-query
rows would be **re-included**. On reflection they are **excluded and counted**
instead. Branded-ness cannot be determined without the query, so including them
would be a guess. They are reported in `data_quality` rather than hidden. Say if
you would rather they be included.

**2. Order of the fixes.** The export fixes have landed. Remaining, highest
value first:

1. The `analyzed_at` filter, plus surfacing excluded-row counts in the UI. This
   is what stops a collection failure from looking like a reputation drop.
2. The sentiment denominator mismatch, which makes the Dashboard card agree with
   its own pie chart.
3. The stored `BatchAnalytics` write path, which needs `Top 3` and a recompute.
4. The rest of the surface migration.

**3. The timezone decision.** The recommendation stands: store timezone-aware
UTC, add a per-brand reporting timezone defaulting to `America/New_York`. That
matches what the UI has always displayed, so no date visibly moves, but month
boundaries stop disagreeing with what is read on screen. The harness already
demonstrates the problem: the same 20 responses give a February mention rate of
57.9% (Eastern), 63.2% (UTC) or 60.0% (by batch).

---

## There is nothing here to restate

An earlier draft of this document treated the number changes as a restatement
problem, and recommended running the baseline against a copy of the real
database before changing anything. That was wrong, and it is worth being
explicit about why.

**TalesToGo holds no data.** It is the sanitized deployment kit that labs
self-host, not a running instance. The local `tales.db` is empty: zero users,
zero brands, zero responses. No batch has ever been collected here, no report
has ever been generated from it, and no number produced by this code has ever
been published.

So the fixes below do not restate anything. They change what a lab's *first*
collection will report, which is strictly an improvement: PNNL and anyone else
who deploys this gets correct arithmetic from the start rather than inheriting
nine implementations and a documented restatement.

This also removes the gate. The `analyzed_at` filter was sequenced behind a
real-data baseline in order to size the restatement. With nothing to size, the
remaining fixes can be worked straight through.

**The separate question this raises.** Tales' real PPPL reporting history lives
in the private `tales_project` repository, not here. The two codebases share
ancestry, so the defects catalogued in this document very likely exist there
too, against data that *has* been published. This audit deliberately did not
look: `CLAUDE.md` forbids touching `tales_project` from this working tree, and
that rule was followed throughout. Whether to port these fixes there, and
whether doing so warrants a restatement note on past monthly and quarterly
reports, is a separate decision requiring a separate working tree. Nothing in
this document should be read as a claim about `tales_project`'s numbers, in
either direction.

---

## Reproducing any number here

```bash
pytest tests/ -q                                              # full suite
pytest tests/test_metric_reconciliation.py -q --runxfail -s   # the matrix
python scripts/admin/metric_baseline.py                       # spread tables
python scripts/admin/generate_metric_definitions.py --check    # docs current
```

Every canonical value traces to a literal in `tests/golden_expected.py` with the
arithmetic in a comment above it. Nothing in this document requires trusting the
code that produced it.
