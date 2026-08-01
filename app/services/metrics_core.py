"""
Canonical metric arithmetic. One definition per metric, and only one.

WHY THIS FILE EXISTS
--------------------
The August 2026 audit found the same conceptual metric computed 4 to 9 different
ways across the codebase (9 mention rates, 9 positive-sentiment rates, 4 share of
voice, 4 descriptor match, 6 positioning), with different denominators, different
filters, and different rounding. Surfaces that are supposed to agree could not
agree, by construction. This module is the single arbiter.

DESIGN RULES (enforced by tests/test_metrics_core_purity.py)
------------------------------------------------------------
1. Pure. No Session, no ORM models, no sqlalchemy, no clock. Input is a
   MetricPopulation of plain records; output is a MetricValue. That makes every
   number here reproducible from literals and testable without a database.
2. Population selection is explicit, per metric, and stated in the docstring.
   The old code hid this: metrics.py:138-139 required the CALLER to pre-filter
   branded queries, and generate_report.py:2214 simply did not, with nothing to
   catch it. Here the selection is applied inside the function.
3. Every result carries its numerator and denominator, not just a rate, so any
   dashboard tile can be hand-checked against the underlying rows.
4. Compute in full float. Round only at the presentation boundary, to one
   decimal place. Never round an already-rounded value.
5. An empty denominator yields value=None, never 0.0. "No data" and "genuinely
   zero" are different facts and the UI must be able to tell them apart.

See docs/METRIC_DEFINITIONS.md, which is generated from these docstrings.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ============================================================== vocabularies

#: The only values `brand_mentioned` may legitimately hold. Anything else is a
#: classifier failure and is excluded from BOTH numerator and denominator rather
#: than being silently folded into "No" the way every current consumer does.
MENTION_VALUES = ("Yes", "Indirect", "No")

#: Values that count as the brand having been mentioned.
MENTIONED_VALUES = ("Yes", "Indirect")

#: A direct, by-name mention. Sentiment is only ever attributed to these.
DIRECT_MENTION_VALUE = "Yes"

#: The only legitimate `sentiment` values.
#:
#: "Very Negative" is included because six consumers already count it, but note
#: that the analysis prompt (scripts/admin/analyze_responses.py:194-200) never
#: offers it to the model, so it is currently unreachable. Negative has one
#: gradation while positive has two, which biases every sentiment distribution.
SENTIMENT_VALUES = (
    "Very Positive", "Positive", "Neutral", "Mixed", "Negative", "Very Negative",
)
POSITIVE_SENTIMENTS = ("Very Positive", "Positive")
NEGATIVE_SENTIMENTS = ("Negative", "Very Negative")

#: The only legitimate `brand_position` values, best to worst.
POSITION_VALUES = ("Leader", "Top 3", "Featured", "Listed", "Not Mentioned")

#: Positions that count as the brand being visible near the top of an answer.
LEADERSHIP_POSITIONS = ("Leader", "Top 3", "Featured")

#: Positioning scores on a 1-5 scale.
#:
#: This corrects two defects at once. The old map (app/services/metrics.py:31-36)
#: ran 1-4 AND had no "Top 3" key, so `.get(position, 1)` scored a Top 3 response
#: identically to Not Mentioned. The 1-5 scale is what the app already publishes
#: to users at app/routers/reports.py:426-433.
POSITION_SCORES = {
    "Leader": 5,
    "Top 3": 4,
    "Featured": 3,
    "Listed": 2,
    "Not Mentioned": 1,
}

#: Percentages are reported to one decimal place, everywhere, always.
PERCENT_DP = 1

_WHITESPACE = re.compile(r"\s+")


# ================================================================== records

@dataclass(frozen=True)
class ResponseRecord:
    """
    One analyzed answer, flattened out of the ORM.

    `is_branded_query` and `query_known` are resolved by metrics_query when it
    joins responses to queries, so no metric function has to re-derive them (and
    therefore no metric function can derive them differently, which is exactly
    how the current code ended up with three different branded-query rules).
    """
    response_id: int
    query_id: str
    platform: str
    brand_mentioned: Optional[str]
    brand_position: Optional[str]
    sentiment: Optional[str]
    descriptors: Tuple[str, ...] = ()
    competitors: Tuple[str, ...] = ()
    analyzed: bool = True
    is_branded_query: bool = False
    query_known: bool = True

    @property
    def has_valid_mention(self) -> bool:
        return self.brand_mentioned in MENTION_VALUES

    @property
    def is_mentioned(self) -> bool:
        return self.brand_mentioned in MENTIONED_VALUES

    @property
    def is_direct_mention(self) -> bool:
        return self.brand_mentioned == DIRECT_MENTION_VALUE


@dataclass
class MetricPopulation:
    """
    Every row in scope, tagged but unfiltered, plus the reference data the
    metrics need. Each metric applies its own documented selection to `rows`.

    Holding one population and selecting per metric (rather than pre-filtering
    per caller) is the structural fix: it makes the differences between metrics
    visible in one file instead of scattered across nine call sites.
    """
    rows: List[ResponseRecord] = field(default_factory=list)
    target_descriptors: Tuple[str, ...] = ()
    tracked_competitors: Tuple[str, ...] = ()
    brand_name: str = ""
    label: str = ""

    # -- selections -------------------------------------------------------

    def analyzed_rows(self) -> List[ResponseRecord]:
        """Rows the classifier actually produced a valid verdict for."""
        return [r for r in self.rows
                if r.analyzed and r.has_valid_mention and r.query_known]

    def organic_rows(self) -> List[ResponseRecord]:
        """Analyzed rows from queries that do NOT contain the brand name.

        This is the denominator for every visibility metric. Asking "what is
        PPPL known for" and then counting that PPPL was mentioned measures
        nothing.
        """
        return [r for r in self.analyzed_rows() if not r.is_branded_query]

    # -- data quality -----------------------------------------------------

    @property
    def unanalyzed_count(self) -> int:
        """Rows the classifier never returned a verdict for.

        Today these are counted as "brand not mentioned" (app/analytics.py:53-55
        and app/services/batch_analytics.py:104-105 apply no analyzed_at filter),
        so every parse failure silently lowers the mention rate. Here they are
        excluded and surfaced instead.
        """
        return sum(1 for r in self.rows if not r.analyzed or r.brand_mentioned is None)

    @property
    def invalid_enum_count(self) -> int:
        """Rows carrying a `brand_mentioned` value outside MENTION_VALUES.

        There is no validation between the analysis LLM and the database
        (scripts/admin/analyze_responses.py:293-299), and every consumer filters
        with an exact-match .in_([...]), so these currently vanish into the
        negative bucket uncounted.
        """
        return sum(1 for r in self.rows
                   if r.analyzed and r.brand_mentioned is not None
                   and not r.has_valid_mention)

    @property
    def orphan_count(self) -> int:
        """Rows whose query_id has no matching Query row.

        Branded-ness cannot be determined without the query, so these are
        excluded and reported rather than guessed at. The current code guesses
        three different ways: analytics_cache.py:91 drops them via an INNER JOIN,
        highlights.py:152 drops them via set membership, and
        generate_report.py:394 keeps them.
        """
        return sum(1 for r in self.rows if not r.query_known)

    @property
    def branded_count(self) -> int:
        return sum(1 for r in self.analyzed_rows() if r.is_branded_query)


@dataclass(frozen=True)
class MetricValue:
    """A metric result that can be audited without re-running the query."""
    value: Optional[float]
    numerator: float
    denominator: float
    definition_id: str
    detail: Mapping[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.value is None:
            return f"{self.definition_id}: no data (0 denominator)"
        return (f"{self.definition_id}: {self.value} "
                f"({self.numerator:g}/{self.denominator:g})")


def _rate(numerator: float, denominator: float, definition_id: str,
          detail: Optional[Mapping[str, object]] = None) -> MetricValue:
    """Percentage helper. Rounds once, at the boundary, and never fakes a zero."""
    if denominator <= 0:
        return MetricValue(None, numerator, denominator, definition_id, detail or {})
    value = round(100.0 * numerator / denominator, PERCENT_DP)
    return MetricValue(value, numerator, denominator, definition_id, detail or {})


# ============================================================ normalization

def normalize_descriptor(descriptor: str) -> str:
    """Case-fold and collapse internal whitespace for descriptor comparison.

    Deliberately NOT substring matching. app/services/analytics_cache.py:283
    matches bidirectionally (`target in resp or resp in target`), under which a
    target of "AI" matches a response descriptor of "explainable AI" and vice
    versa, inflating the match rate.

    Also deliberately NOT punctuation-folding: "high-temperature plasma" and
    "high temperature plasma" remain distinct here. Merging them is a defensible
    product decision but it is a decision, not a bug fix, so it is reported in
    the reconciliation doc rather than applied silently.
    """
    return _WHITESPACE.sub(" ", (descriptor or "").strip()).casefold()


def normalize_organization(name: str,
                           aliases: Optional[Mapping[str, str]] = None) -> str:
    """Group organization-name variants using an EXPLICIT alias map.

    The map is exact-match on the case-folded name. This replaces
    app/services/metrics.py:65-114, which used unanchored substring tests
    (`'step' in name_lower` rewrote anything containing "step" to "UKAEA", so
    "Stepwise Analytics" became a UKAEA mention) and hardcoded PPPL's fusion
    competitors globally for every tenant.

    With no alias map, names group case-insensitively and nothing else happens.
    """
    cleaned = _WHITESPACE.sub(" ", (name or "").strip())
    if not cleaned:
        return ""
    if aliases:
        canonical = aliases.get(cleaned.casefold())
        if canonical:
            return canonical
    return cleaned


def _count_names(rows: Iterable[ResponseRecord], attr: str,
                 aliases: Optional[Mapping[str, str]] = None) -> Counter:
    """Count organization mentions across rows, grouping variant spellings.

    Display uses the most frequent original spelling so the UI shows "UKAEA",
    not "ukaea".
    """
    groups: Dict[str, Counter] = {}
    for row in rows:
        for raw in getattr(row, attr):
            canonical = normalize_organization(raw, aliases)
            if not canonical:
                continue
            groups.setdefault(canonical.casefold(), Counter())[canonical] += 1
    counts: Counter = Counter()
    for spellings in groups.values():
        display = spellings.most_common(1)[0][0]
        counts[display] = sum(spellings.values())
    return counts


# ================================================================== metrics

def mention_rate(pop: MetricPopulation) -> MetricValue:
    """Share of organic answers in which the brand appears at all.

    Numerator   brand_mentioned in {Yes, Indirect}
    Denominator all analyzed, valid-enum, non-branded answers
    Excludes    branded queries, unanalyzed rows, off-enum rows, orphans

    Supersedes all nine current implementations, which disagree on whether
    Indirect counts (routers/analytics.py:739 drops it), on whether branded
    queries are excluded (generate_report.py:394 and :2530 do not), and on
    rounding (int, 1dp and 2dp all appear).
    """
    rows = pop.organic_rows()
    mentioned = sum(1 for r in rows if r.is_mentioned)
    return _rate(mentioned, len(rows), "mention_rate",
                 {"excluded_unanalyzed": pop.unanalyzed_count,
                  "excluded_invalid": pop.invalid_enum_count,
                  "excluded_orphan": pop.orphan_count})


def direct_mention_rate(pop: MetricPopulation) -> MetricValue:
    """Share of organic answers naming the brand explicitly (Yes only).

    A legitimate, narrower metric. It exists so the call sites that currently
    want a Yes-only rate (metrics.py:161, routers/analytics.py:739) have a
    correct home instead of quietly redefining `mention_rate`.
    """
    rows = pop.organic_rows()
    direct = sum(1 for r in rows if r.is_direct_mention)
    return _rate(direct, len(rows), "direct_mention_rate")


def positive_sentiment_rate(pop: MetricPopulation) -> MetricValue:
    """Share of direct mentions whose tone is positive.

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
    """
    rows = [r for r in pop.analyzed_rows()
            if r.is_direct_mention and r.sentiment in SENTIMENT_VALUES]
    positive = sum(1 for r in rows if r.sentiment in POSITIVE_SENTIMENTS)
    return _rate(positive, len(rows), "positive_sentiment_rate")


def sentiment_distribution(pop: MetricPopulation) -> Dict[str, MetricValue]:
    """Full sentiment breakdown over the same population as positive_sentiment_rate.

    Sharing the denominator is the point: the slices sum to 100.0, and the
    "% positive" headline equals Very Positive + Positive. On the current
    Dashboard those two disagree because analytics_cache.py:698 and :776 use
    different bases within one response payload.
    """
    rows = [r for r in pop.analyzed_rows()
            if r.is_direct_mention and r.sentiment in SENTIMENT_VALUES]
    counts = Counter(r.sentiment for r in rows)
    return {
        label: _rate(counts.get(label, 0), len(rows), f"sentiment.{label}")
        for label in SENTIMENT_VALUES
    }


def leadership_visibility(pop: MetricPopulation) -> MetricValue:
    """Share of organic answers placing the brand at or near the top.

    Numerator   brand_position in {Leader, Top 3, Featured}
    Denominator all analyzed, valid-enum, non-branded answers

    On the current Dashboard the tile's VALUE comes from this formula
    (metrics.py:456-489, via the share-of-voice endpoint) while its trend ARROW
    comes from leader_count/total at routers/analytics.py:266-268. The number and
    its direction of travel are different metrics. One function now serves both.
    """
    rows = pop.organic_rows()
    visible = sum(1 for r in rows if r.brand_position in LEADERSHIP_POSITIONS)
    return _rate(visible, len(rows), "leadership_visibility")


def positioning_distribution(pop: MetricPopulation) -> Dict[str, MetricValue]:
    """Share of organic answers at each position, on the full five-value scale.

    "Top 3" is reported as itself. batch_analytics.py:98-103 drops it entirely
    (so its position counts do not sum to the total), routers/analytics.py:801
    drops it, and metrics.py:210-211 folds it into Featured. Three behaviors for
    one enum value the analysis prompt actively produces.
    """
    rows = pop.organic_rows()
    counts = Counter(r.brand_position for r in rows)
    return {
        label: _rate(counts.get(label, 0), len(rows), f"positioning.{label}")
        for label in POSITION_VALUES
    }


def positioning_average(pop: MetricPopulation) -> MetricValue:
    """Mean positioning score on a 1-5 scale, over all organic answers.

    Denominator is every organic answer, not just the ones where the brand was
    mentioned. metrics.py:247-251 restricts to mentions, which makes the
    "Not Mentioned = 1 point" tier nearly unreachable and inflates the score.

    Unknown positions are excluded from both the sum and the count. The old code
    scored them 1 via `.get(position, 1)`, which is how "Top 3" (a valid,
    prompted value with no key in the map) came to be scored identically to
    "Not Mentioned".

    Returns a mean on the 1-5 scale in `value`, not a percentage.
    """
    rows = [r for r in pop.organic_rows() if r.brand_position in POSITION_SCORES]
    if not rows:
        return MetricValue(None, 0, 0, "positioning_average")
    total = sum(POSITION_SCORES[r.brand_position] for r in rows)
    return MetricValue(round(total / len(rows), PERCENT_DP), total, len(rows),
                       "positioning_average", {"scale": "1-5"})


def share_of_voice(pop: MetricPopulation,
                   aliases: Optional[Mapping[str, str]] = None
                   ) -> Tuple[MetricValue, Dict[str, MetricValue]]:
    """The brand's share of all organization mentions across organic answers.

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
    """
    rows = pop.organic_rows()
    brand_mentions = sum(1 for r in rows if r.is_mentioned)
    competitor_counts = _count_names(rows, "competitors", aliases)
    total = brand_mentions + sum(competitor_counts.values())

    brand_share = _rate(brand_mentions, total, "share_of_voice",
                        {"brand": pop.brand_name})
    competitor_shares = {
        name: _rate(count, total, f"share_of_voice.{name}")
        for name, count in competitor_counts.most_common()
    }
    return brand_share, competitor_shares


def descriptor_match_rate(pop: MetricPopulation) -> MetricValue:
    """Share of the brand's target descriptors that appear in any answer.

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
    """
    targets = {normalize_descriptor(d) for d in pop.target_descriptors}
    targets.discard("")
    seen = set()
    for row in pop.analyzed_rows():
        if not row.is_mentioned:
            continue
        for descriptor in row.descriptors:
            normalized = normalize_descriptor(descriptor)
            if normalized in targets:
                seen.add(normalized)
    return _rate(len(seen), len(targets), "descriptor_match_rate",
                 {"matched": sorted(seen), "unmatched": sorted(targets - seen)})


def descriptor_frequency(pop: MetricPopulation) -> Dict[str, int]:
    """How often each descriptor is used about the brand, case-folded.

    metrics.py:389, batch_analytics.py:134 and routers/analytics.py:999 all key
    the counter on the raw string, so "high-temperature plasma" and
    "High-Temperature Plasma" occupy two separate rows in every chart.
    """
    counts: Counter = Counter()
    display: Dict[str, Counter] = {}
    for row in pop.analyzed_rows():
        if not row.is_mentioned:
            continue
        for descriptor in row.descriptors:
            normalized = normalize_descriptor(descriptor)
            if not normalized:
                continue
            counts[normalized] += 1
            display.setdefault(normalized, Counter())[descriptor.strip()] += 1
    return {display[key].most_common(1)[0][0]: count
            for key, count in counts.most_common()}


def platform_mention_rates(pop: MetricPopulation) -> Dict[str, MetricValue]:
    """Per-platform mention rate, using the same definition as mention_rate.

    Every current *-by-llm endpoint diverges from the headline metric it sits
    under: routers/analytics.py:739 counts Yes only, and all of them add a
    `batch_id IS NOT NULL` guard that silently drops imported rows from
    denominators presented as platform totals.
    """
    by_platform: Dict[str, List[ResponseRecord]] = {}
    for row in pop.organic_rows():
        by_platform.setdefault(row.platform or "Unknown", []).append(row)
    return {
        platform: _rate(sum(1 for r in rows if r.is_mentioned), len(rows),
                        f"mention_rate.{platform}")
        for platform, rows in sorted(by_platform.items())
    }


def data_quality(pop: MetricPopulation) -> Dict[str, int]:
    """Everything excluded from the metrics above, so it can be shown, not hidden.

    A parse failure and a genuine "brand not mentioned" are arithmetically
    identical in the current dashboard. Surfacing these counts is what makes the
    difference visible.
    """
    return {
        "total_rows": len(pop.rows),
        "counted": len(pop.organic_rows()),
        "branded_excluded": pop.branded_count,
        "unanalyzed_excluded": pop.unanalyzed_count,
        "invalid_enum_excluded": pop.invalid_enum_count,
        "orphan_query_excluded": pop.orphan_count,
    }


#: Percentage metrics, for the reconciliation harness to iterate over.
RATE_METRICS = {
    "mention_rate": mention_rate,
    "direct_mention_rate": direct_mention_rate,
    "positive_sentiment_rate": positive_sentiment_rate,
    "leadership_visibility": leadership_visibility,
    "descriptor_match_rate": descriptor_match_rate,
}


def summary(pop: MetricPopulation,
            aliases: Optional[Mapping[str, str]] = None) -> Dict[str, object]:
    """Every canonical metric for one population, in one call."""
    brand_share, competitor_shares = share_of_voice(pop, aliases)
    result: Dict[str, object] = {name: fn(pop) for name, fn in RATE_METRICS.items()}
    result.update({
        "share_of_voice": brand_share,
        "competitor_share_of_voice": competitor_shares,
        "positioning_average": positioning_average(pop),
        "positioning_distribution": positioning_distribution(pop),
        "sentiment_distribution": sentiment_distribution(pop),
        "descriptor_frequency": descriptor_frequency(pop),
        "platform_mention_rates": platform_mention_rates(pop),
        "data_quality": data_quality(pop),
    })
    return result
