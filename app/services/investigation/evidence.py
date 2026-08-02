"""
The evidence pack: everything an investigation can look at.

Each function here answers one question about the two windows being compared,
and every number it returns comes from app/services/metrics_core.py. There is no
arithmetic in this module that is not delegated.

That is deliberate. An investigation's whole value is that its conclusions can be
trusted, and the fastest way to lose that is for the investigator to compute its
own version of the mention rate. These functions are pure with respect to the
database: given the same rows they return the same output, so they are tested
against the golden fixture with hand-derived expectations exactly like
metrics_core itself.

The agent loop in service.py wraps these as tools. Nothing here calls an LLM,
which means the expensive, non-deterministic part of an investigation is only
ever narration over numbers that were already proven correct.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ... import models
from .. import metrics_core, metrics_query
from .scope import ComparisonScope, recent_windows

#: Response bodies are long. The agent needs enough to see what an answer said
#: about the brand, not the whole thing.
RESPONSE_TEXT_LIMIT = 1500

#: How many full response bodies one call may return.
MAX_RESPONSE_DETAILS = 20


def _population(db: Session, scope: ComparisonScope, side: str):
    return metrics_query.resolve(db, scope.side(side))


def _metric(value) -> Dict[str, Any]:
    """A MetricValue as JSON, keeping the numerator and denominator.

    The agent is told to cite evidence; handing it "55.0" alone invites vague
    claims, while "55.0 (22/40)" lets it say what the number is made of.
    """
    return {
        "value": value.value,
        "numerator": value.numerator,
        "denominator": value.denominator,
    }


def _delta(current, previous) -> Optional[float]:
    if current.value is None or previous.value is None:
        return None
    return round(current.value - previous.value, 1)


# ================================================================ the tools

def brand_context(db: Session, scope: ComparisonScope) -> Dict[str, Any]:
    """What is being tracked: the brand, its queries, competitors, descriptors."""
    brand = db.query(models.BrandInfo).filter(
        models.BrandInfo.id == scope.current.brand_id).first()

    queries = db.query(models.Query).filter(
        models.Query.user_id == scope.current.owner_user_id,
        models.Query.brand_id == scope.current.brand_id,
    ).order_by(models.Query.query_id).all()

    competitors = db.query(models.Competitor).filter(
        models.Competitor.user_id == scope.current.owner_user_id,
        models.Competitor.brand_id == scope.current.brand_id,
    ).order_by(models.Competitor.organization).all()

    descriptors = db.query(models.TargetDescriptor).filter(
        models.TargetDescriptor.user_id == scope.current.owner_user_id,
        models.TargetDescriptor.brand_id == scope.current.brand_id,
        models.TargetDescriptor.is_target == True,  # noqa: E712
    ).order_by(models.TargetDescriptor.descriptor).all()

    return {
        "brand_name": brand.brand_name if brand else "",
        "industry": brand.industry if brand else None,
        "description": brand.description if brand else None,
        "comparison": {
            "mode": scope.mode,
            "unit": scope.unit,
            "current": scope.current_label,
            "previous": scope.previous_label,
        },
        "queries": [
            {"query_id": q.query_id, "text": q.query_text,
             # Branded queries name the brand in the question, so they are
             # excluded from visibility metrics. The agent needs to know which
             # ones those are before drawing conclusions from query-level data.
             "brand_in_query": bool(q.brand_in_query)}
            for q in queries
        ],
        "competitors": [c.organization for c in competitors],
        "target_descriptors": [d.descriptor for d in descriptors],
    }


def compare_scopes(db: Session, scope: ComparisonScope) -> Dict[str, Any]:
    """Every canonical metric for both windows, with deltas.

    This is the starting point of any investigation: what actually moved.
    """
    current = _population(db, scope, "current")
    previous = _population(db, scope, "previous")

    def side(population) -> Dict[str, Any]:
        brand_share, _ = metrics_core.share_of_voice(population)
        return {
            "mention_rate": _metric(metrics_core.mention_rate(population)),
            "direct_mention_rate": _metric(metrics_core.direct_mention_rate(population)),
            "positive_sentiment_rate": _metric(
                metrics_core.positive_sentiment_rate(population)),
            "leadership_visibility": _metric(
                metrics_core.leadership_visibility(population)),
            "descriptor_match_rate": _metric(
                metrics_core.descriptor_match_rate(population)),
            "share_of_voice": _metric(brand_share),
            "positioning_average": _metric(metrics_core.positioning_average(population)),
            "positioning_distribution": {
                label: _metric(value)
                for label, value in metrics_core.positioning_distribution(population).items()
            },
            "sentiment_distribution": {
                label: _metric(value)
                for label, value in metrics_core.sentiment_distribution(population).items()
            },
            # What was left out of the numbers above, and why.
            "data_quality": metrics_core.data_quality(population),
        }

    current_side = side(current)
    previous_side = side(previous)

    deltas = {
        name: _delta(getattr(metrics_core, name)(current),
                     getattr(metrics_core, name)(previous))
        for name in ("mention_rate", "direct_mention_rate", "positive_sentiment_rate",
                     "leadership_visibility", "descriptor_match_rate")
    }
    deltas["share_of_voice"] = _delta(
        metrics_core.share_of_voice(current)[0], metrics_core.share_of_voice(previous)[0])
    deltas["positioning_average"] = _delta(
        metrics_core.positioning_average(current),
        metrics_core.positioning_average(previous))

    return {
        "current": {"label": scope.current_label, **current_side},
        "previous": {"label": scope.previous_label, **previous_side},
        "deltas": deltas,
        "notes": [
            "Deltas are percentage points, current minus previous, except "
            "positioning_average which is a mean on a 1-5 scale.",
            "Collection volume can differ between the two windows. Compare rates, "
            "not raw counts, when judging whether something really changed.",
            # This is the check no other surface can offer, and it should be the
            # first thing considered before concluding that visibility fell.
            "Check data_quality on both sides before attributing a change to "
            "reputation. Rows excluded as unanalyzed are collection or analysis "
            "failures, not evidence that the brand went unmentioned.",
            # A window collected with web search and one collected without are
            # answering different questions, and the difference between them is
            # usually larger than anything reputation does in a month.
            "data_quality.grounding says how each window was collected. If the "
            "two differ, the comparison is not like for like and any movement is "
            "most likely method rather than reputation. 'unknown' means it was "
            "not recorded, which is not the same as ungrounded.",
        ],
    }


def query_level_deltas(db: Session, scope: ComparisonScope,
                       limit: int = 10) -> Dict[str, Any]:
    """Which individual queries moved most, ranked by absolute change."""
    def per_query(population) -> Dict[str, Dict[str, Any]]:
        return {
            query_id: {
                "query_id": query_id,
                "query_text": value.detail.get("query_text", ""),
                "total": int(value.denominator),
                "mentioned": int(value.numerator),
                "mention_rate": value.value,
            }
            for query_id, value in metrics_core.query_mention_rates(population).items()
        }

    current = per_query(_population(db, scope, "current"))
    previous = per_query(_population(db, scope, "previous"))

    rows = []
    for query_id in sorted(set(current) | set(previous)):
        cur = current.get(query_id)
        prev = previous.get(query_id)
        change = (round(cur["mention_rate"] - prev["mention_rate"], 1)
                  if cur and prev and cur["mention_rate"] is not None
                  and prev["mention_rate"] is not None else None)
        rows.append({
            "query_id": query_id,
            "query_text": (cur or prev)["query_text"],
            "current": {"total": cur["total"], "mentioned": cur["mentioned"],
                        "mention_rate": cur["mention_rate"]} if cur else None,
            "previous": {"total": prev["total"], "mentioned": prev["mentioned"],
                         "mention_rate": prev["mention_rate"]} if prev else None,
            "change": change,
        })

    rows.sort(key=lambda r: (r["change"] is None, -abs(r["change"] or 0)))
    return {
        "queries": rows[:limit],
        "total_queries": len(rows),
        "note": "Branded queries are excluded; they measure nothing about "
                "organic visibility.",
    }


def platform_breakdown(db: Session, scope: ComparisonScope) -> Dict[str, Any]:
    """Per-platform mention rates on both sides, to separate a platform-specific
    shift from a universal one."""
    def side(population):
        return {
            platform: _metric(value)
            for platform, value in metrics_core.platform_mention_rates(population).items()
        }

    current = side(_population(db, scope, "current"))
    previous = side(_population(db, scope, "previous"))

    changes = {}
    for platform in sorted(set(current) | set(previous)):
        cur = current.get(platform, {}).get("value")
        prev = previous.get(platform, {}).get("value")
        changes[platform] = (round(cur - prev, 1)
                             if cur is not None and prev is not None else None)

    return {
        "current": {"label": scope.current_label, "platforms": current},
        "previous": {"label": scope.previous_label, "platforms": previous},
        "changes": changes,
        "note": "A change confined to one platform is usually that platform "
                "re-ranking; a change across all of them suggests something "
                "external.",
    }


def response_details(db: Session, scope: ComparisonScope, side: str,
                     query_id: str, platform: Optional[str] = None) -> Dict[str, Any]:
    """What the AI platforms actually said, for one query.

    The point at which an investigation stops being about numbers.
    """
    population = _population(db, scope, side)
    matches = [
        row for row in population.organic_rows()
        if row.query_id == query_id
        and (platform is None or row.platform == platform)
    ]

    ids = [row.response_id for row in matches[:MAX_RESPONSE_DETAILS]]
    bodies = {
        r.id: r for r in db.query(models.Response).filter(models.Response.id.in_(ids)).all()
    } if ids else {}

    results = []
    for row in matches[:MAX_RESPONSE_DETAILS]:
        body = bodies.get(row.response_id)
        text = (body.response_text or "") if body else ""
        results.append({
            "response_id": row.response_id,
            "platform": row.platform,
            "brand_mentioned": row.brand_mentioned,
            "brand_position": row.brand_position,
            "sentiment": row.sentiment,
            "descriptors": list(row.descriptors),
            "competitors": list(row.competitors),
            "collected_at": body.timestamp.isoformat() if body and body.timestamp else None,
            "response_text": text[:RESPONSE_TEXT_LIMIT],
            "response_text_truncated": len(text) > RESPONSE_TEXT_LIMIT,
        })

    return {
        "side": side,
        "label": scope.current_label if side == "current" else scope.previous_label,
        "query_id": query_id,
        "platform": platform,
        "responses": results,
        "returned": len(results),
        "total_matching": len(matches),
        "truncated": len(matches) > MAX_RESPONSE_DETAILS,
    }


def competitor_changes(db: Session, scope: ComparisonScope) -> Dict[str, Any]:
    """Share of voice per organization on both sides."""
    def side(population):
        brand_share, competitors = metrics_core.share_of_voice(population)
        return brand_share, {
            name: _metric(value) for name, value in competitors.items()
        }

    cur_brand, cur_comp = side(_population(db, scope, "current"))
    prev_brand, prev_comp = side(_population(db, scope, "previous"))

    # A competitor absent from one window was mentioned zero times there, which
    # is a real change rather than an unknown. Reporting None would hide exactly
    # the case worth investigating: a competitor appearing from nowhere, or
    # dropping out entirely.
    cur_has_data = cur_brand.denominator > 0
    prev_has_data = prev_brand.denominator > 0

    rows = []
    for name in sorted(set(cur_comp) | set(prev_comp)):
        cur = cur_comp.get(name, {}).get("value", 0.0 if cur_has_data else None)
        prev = prev_comp.get(name, {}).get("value", 0.0 if prev_has_data else None)
        rows.append({
            "organization": name,
            "current": cur_comp.get(name) or {"value": cur, "numerator": 0,
                                              "denominator": cur_brand.denominator},
            "previous": prev_comp.get(name) or {"value": prev, "numerator": 0,
                                                "denominator": prev_brand.denominator},
            "change": round(cur - prev, 1) if cur is not None and prev is not None else None,
        })
    rows.sort(key=lambda r: (r["change"] is None, -abs(r["change"] or 0)))

    return {
        "brand": {
            "current": _metric(cur_brand),
            "previous": _metric(prev_brand),
            "change": _delta(cur_brand, prev_brand),
        },
        "competitors": rows,
        "note": "Share of voice counts every organization named across all "
                "organic answers, so competitor gains can move the brand's share "
                "without the brand itself being mentioned less often.",
    }


def descriptor_changes(db: Session, scope: ComparisonScope) -> Dict[str, Any]:
    """Which words are being used about the brand, and how that shifted."""
    def side(population):
        return metrics_core.descriptor_frequency(population)

    current = side(_population(db, scope, "current"))
    previous = side(_population(db, scope, "previous"))

    rows = []
    for descriptor in sorted(set(current) | set(previous)):
        cur = current.get(descriptor, 0)
        prev = previous.get(descriptor, 0)
        rows.append({"descriptor": descriptor, "current": cur,
                     "previous": prev, "change": cur - prev})
    rows.sort(key=lambda r: -abs(r["change"]))

    cur_pop = _population(db, scope, "current")
    prev_pop = _population(db, scope, "previous")
    cur_match = metrics_core.descriptor_match_rate(cur_pop)
    prev_match = metrics_core.descriptor_match_rate(prev_pop)

    return {
        "descriptors": rows,
        "target_match_rate": {
            "current": _metric(cur_match),
            "previous": _metric(prev_match),
            "change": _delta(cur_match, prev_match),
        },
        "unmatched_targets": cur_match.detail.get("unmatched", []),
        "note": "Counts are case-folded, so spelling variants of the same "
                "descriptor are one row.",
    }


def historical_trend(db: Session, scope: ComparisonScope,
                     count: int = 5) -> Dict[str, Any]:
    """The same metric across several consecutive windows, oldest first.

    Distinguishes a one-off shift from a sustained direction of travel.
    """
    windows = recent_windows(
        db, scope.current.owner_user_id, scope.current.brand_id, scope.mode, count)

    points = []
    for start, end, label in windows:
        if scope.mode == "batch":
            batch = db.query(models.CollectionBatch).filter(
                models.CollectionBatch.user_id == scope.current.owner_user_id,
                models.CollectionBatch.brand_id == scope.current.brand_id,
                models.CollectionBatch.batch_name == label,
            ).first()
            if batch is None:
                continue
            window_scope = metrics_query.MetricScope.for_batch(
                scope.current.owner_user_id, scope.current.brand_id, batch.id)
        else:
            window_scope = metrics_query.MetricScope(
                scope.current.owner_user_id, scope.current.brand_id,
                start=start, end=end)

        population = metrics_query.resolve(db, window_scope)
        mention = metrics_core.mention_rate(population)
        sentiment = metrics_core.positive_sentiment_rate(population)
        points.append({
            "label": label,
            "mention_rate": mention.value,
            "positive_sentiment_rate": sentiment.value,
            "counted_responses": int(mention.denominator),
        })

    return {
        "unit": scope.unit,
        "points": points,
        "note": "Oldest first. A window with 0 counted_responses had no usable "
                "collection and must not be read as a metric collapse.",
    }


#: Everything the agent may call, by name. service.py maps these to tool
#: definitions; keeping the registry here means a tool cannot be exposed to the
#: model without a deterministic implementation behind it.
EVIDENCE_TOOLS = {
    "brand_context": brand_context,
    "compare_scopes": compare_scopes,
    "query_level_deltas": query_level_deltas,
    "platform_breakdown": platform_breakdown,
    "response_details": response_details,
    "competitor_changes": competitor_changes,
    "descriptor_changes": descriptor_changes,
    "historical_trend": historical_trend,
}
