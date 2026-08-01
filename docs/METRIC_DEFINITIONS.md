# Tales Metric Definitions

**Generated from `app/services/metrics_core.py`. Do not edit by hand.**
Run `python scripts/admin/generate_metric_definitions.py` to refresh.

Every number Tales reports is defined exactly once, here. If a dashboard
tile, a CSV export, a generated report and a highlights email disagree about
the same metric for the same period, one of them is not using these
definitions and that is a bug.

## Conventions

- Percentages are reported to one decimal place. Values are computed in full
  float and rounded once, at the presentation boundary.
- An empty denominator yields no value at all, rendered as a dash. It is never
  reported as `0.0`, because "no data" and "genuinely zero" are different facts.
- Every metric reports its numerator and denominator alongside the rate, so any
  figure can be checked against the underlying rows.

## Vocabularies

- **Mention values**: `Yes`, `Indirect`, `No`
- **Counted as mentioned**: `Yes`, `Indirect`
- **Sentiment values**: `Very Positive`, `Positive`, `Neutral`, `Mixed`, `Negative`, `Very Negative`
- **Positive sentiment**: `Very Positive`, `Positive`
- **Position values**: `Leader`, `Top 3`, `Featured`, `Listed`, `Not Mentioned`
- **Counted as leadership**: `Leader`, `Top 3`, `Featured`

### Positioning scores

| Position | Score |
|---|---|
| Leader | 5 |
| Top 3 | 4 |
| Featured | 3 |
| Listed | 2 |
| Not Mentioned | 1 |

## Population selection

Rows are loaded by `app/services/metrics_query.py` and tagged, not filtered.
Each metric applies its own documented selection, so what a metric excludes is
always visible rather than baked into the query.

| Selection | Meaning |
|---|---|
| analyzed rows | the classifier returned a valid verdict and the query resolves |
| organic rows | analyzed rows whose query does not contain the brand name |

Excluded rows are counted and reported by `data_quality`, never silently folded
into a negative result.

## Metrics

### `mention_rate`

Share of organic answers in which the brand appears at all.

Numerator   brand_mentioned in {Yes, Indirect}
Denominator all analyzed, valid-enum, non-branded answers
Excludes    branded queries, unanalyzed rows, off-enum rows, orphans

Supersedes all nine current implementations, which disagree on whether
Indirect counts (routers/analytics.py:739 drops it), on whether branded
queries are excluded (generate_report.py:394 and :2530 do not), and on
rounding (int, 1dp and 2dp all appear).

### `direct_mention_rate`

Share of organic answers naming the brand explicitly (Yes only).

Numerator   brand_mentioned == "Yes"
Denominator all analyzed, valid-enum, non-branded answers, the same
            population as mention_rate
Excludes    Indirect mentions

A legitimate, narrower metric. It exists so the call sites that currently
want a Yes-only rate (metrics.py:161, routers/analytics.py:739) have a
correct home instead of quietly redefining `mention_rate`.

### `positive_sentiment_rate`

Share of direct mentions whose tone is positive.

Numerator   sentiment in {Very Positive, Positive}
Denominator brand_mentioned == "Yes" AND sentiment is a valid, non-empty value
Includes    branded queries (per the rule stated at metrics.py:11-12: tone
            applies to every answer that names the brand, including ones
            where the question named it)
Excludes    Indirect mentions, which carry no attributable sentiment

Fixes the numerator/denominator mismatch at analytics_cache.py:208,
routers/analytics.py:262 and cached_metrics.py:97-102, where a Yes-only
numerator was divided by a Yes+Indirect denominator. That systematically
understated the rate and made the sentiment trend slices fail to sum to 100.

### `sentiment_distribution`

Full sentiment breakdown over the same population as positive_sentiment_rate.

Sharing the denominator is the point: the slices sum to 100.0, and the
"% positive" headline equals Very Positive + Positive. On the current
Dashboard those two disagree because analytics_cache.py:698 and :776 use
different bases within one response payload.

### `leadership_visibility`

Share of organic answers placing the brand at or near the top.

Numerator   brand_position in {Leader, Top 3, Featured}
Denominator all analyzed, valid-enum, non-branded answers

On the current Dashboard the tile's VALUE comes from this formula
(metrics.py:456-489, via the share-of-voice endpoint) while its trend ARROW
comes from leader_count/total at routers/analytics.py:266-268. The number and
its direction of travel are different metrics. One function now serves both.

### `positioning_distribution`

Share of organic answers at each position, on the full five-value scale.

"Top 3" is reported as itself. batch_analytics.py:98-103 drops it entirely
(so its position counts do not sum to the total), routers/analytics.py:801
drops it, and metrics.py:210-211 folds it into Featured. Three behaviors for
one enum value the analysis prompt actively produces.

### `positioning_average`

Mean positioning score on a 1-5 scale, over all organic answers.

Denominator is every organic answer, not just the ones where the brand was
mentioned. metrics.py:247-251 restricts to mentions, which makes the
"Not Mentioned = 1 point" tier nearly unreachable and inflates the score.

Unknown positions are excluded from both the sum and the count. The old code
scored them 1 via `.get(position, 1)`, which is how "Top 3" (a valid,
prompted value with no key in the map) came to be scored identically to
"Not Mentioned".

Returns a mean on the 1-5 scale in `value`, not a percentage.

### `share_of_voice`

The brand's share of all organization mentions across organic answers.

Numerator   answers where brand_mentioned in {Yes, Indirect}
Denominator that count, plus every normalized competitor mention across ALL
            organic answers

The critical correction is the competitor population. analytics_cache.py:327-336
counts competitors only within answers where the brand was already mentioned,
then labels the result as share of the whole corpus. A competitor named in an
answer the brand never appeared in is invisible, which structurally inflates
brand share. Here competitors are counted across every organic answer.

Returns (brand_share, {competitor_name: share}). No top-N truncation: that is
a display concern. metrics.py:563 truncates to the top 5 BEFORE threat
scoring, so a sixth-ranked competitor can never be flagged.

### `descriptor_match_rate`

Share of the brand's target descriptors that appear in any answer.

Numerator   distinct target descriptors found
Denominator target descriptors where is_target is True
Includes    branded queries and both Yes and Indirect mentions: the question
            is whether the language is being used about the brand at all
Matching    case-insensitive exact on comma-split tokens

Three current implementations disagree on all three axes: metrics.py:419 is
exact over Yes only, analytics_cache.py:283 is bidirectional-substring over
Yes and Indirect, and DescriptorAnalysis.tsx:78-95 reimplements exact
matching client-side in React. app/analytics.py:110 additionally forgets the
is_target filter, using every descriptor row as the denominator.

### `descriptor_frequency`

How often each descriptor is used about the brand, case-folded.

metrics.py:389, batch_analytics.py:134 and routers/analytics.py:999 all key
the counter on the raw string, so "high-temperature plasma" and
"High-Temperature Plasma" occupy two separate rows in every chart.

### `platform_mention_rates`

Per-platform mention rate, using the same definition as mention_rate.

Every current *-by-llm endpoint diverges from the headline metric it sits
under: routers/analytics.py:739 counts Yes only, and all of them add a
`batch_id IS NOT NULL` guard that silently drops imported rows from
denominators presented as platform totals.

### `data_quality`

Everything excluded from the metrics above, so it can be shown, not hidden.

A parse failure and a genuine "brand not mentioned" are arithmetically
identical in the current dashboard. Surfacing these counts is what makes the
difference visible.
