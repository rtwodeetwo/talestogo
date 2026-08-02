"""
Auto-triggered investigations.

After a collection finishes, this asks one question: did anything move far
enough to be worth explaining? If so it opens an investigation for the period
that just closed.

Three rules keep it from crying wolf.

**Never fire on an empty window.** A month with no collection reads as a total
collapse in every metric. scope.py already refuses to build such a comparison,
and that refusal is treated here as "nothing to say", not as an error.

**Dedupe on the period.** The first batch of a new month is what closes out the
previous one, so that is when a month trigger fires. Later batches re-check, and
must not produce a second investigation for a period that already has one.

**Measure the same way the investigation will.** The deltas come from
evidence.compare_scopes, so the threshold that fired and the figures in the
write-up cannot disagree.

A failure in here must never fail a collection. Callers use
`check_after_collection`, which swallows everything.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ... import models
from . import evidence, service
from .scope import ScopeError, apply_scope_to_record, build_scope

logger = logging.getLogger(__name__)

#: Absolute movement, in percentage points, that is worth explaining.
#:
#: These are deployment-wide defaults, overridable per deployment by environment
#: variable (see `threshold_for`). Per-brand thresholds are the natural next
#: step; the resolution already goes through one function so that when a brand
#: setting arrives there is a single place to read it.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "mention_rate": 10.0,
    "positive_sentiment_rate": 15.0,
    "leadership_visibility": 15.0,
    "share_of_voice": 10.0,
}

#: Human wording for the trigger record, which is shown to the agent.
METRIC_LABELS = {
    "mention_rate": "mention rate",
    "positive_sentiment_rate": "positive sentiment",
    "leadership_visibility": "leadership visibility",
    "share_of_voice": "share of voice",
}

#: The comparison an auto-trigger opens. A single batch is too noisy to raise an
#: investigation over; a month is the unit the dashboard defaults to.
TRIGGER_MODE = "month"

_ENABLED_ENV = "INVESTIGATIONS_AUTO_TRIGGER"


def auto_trigger_enabled() -> bool:
    """On by default. Labs get auto-investigations without opting in."""
    value = os.getenv(_ENABLED_ENV)
    if value is None:
        return True
    return value.strip().lower() not in ("0", "false", "no", "off")


def threshold_for(metric: str) -> float:
    """The movement that counts as significant for one metric.

    Environment overrides are read per call rather than cached, so a deployment
    can retune without a restart.
    """
    default = DEFAULT_THRESHOLDS[metric]
    raw = os.getenv(f"INVESTIGATION_THRESHOLD_{metric.upper()}")
    if raw is None:
        return default
    try:
        return abs(float(raw))
    except ValueError:
        logger.warning(
            "Ignoring INVESTIGATION_THRESHOLD_%s=%r: not a number. Using %s.",
            metric.upper(), raw, default)
        return default


def find_crossings(db: Session, scope) -> List[Dict[str, Any]]:
    """Every metric that moved past its threshold, with the numbers behind it.

    Uses the same comparison the investigation itself will run, so the trigger
    and the write-up cannot quote different figures for the same movement.
    """
    comparison = evidence.compare_scopes(db, scope)
    deltas = comparison["deltas"]
    crossings: List[Dict[str, Any]] = []

    for metric in ("mention_rate", "positive_sentiment_rate",
                   "leadership_visibility", "share_of_voice"):
        change = deltas.get(metric)
        if change is None:
            continue
        threshold = threshold_for(metric)
        if abs(change) >= threshold:
            crossings.append({
                "metric": metric,
                "label": METRIC_LABELS[metric],
                "subject": "brand",
                "change": change,
                "threshold": threshold,
                "current": comparison["current"][metric]["value"],
                "previous": comparison["previous"][metric]["value"],
            })

    # Share of voice is shared out across every organization named, so a
    # competitor can surge without the brand's own share moving much. That is
    # exactly the case worth explaining, and it is invisible in the brand-level
    # delta above.
    competitor_threshold = threshold_for("share_of_voice")
    for row in evidence.competitor_changes(db, scope)["competitors"]:
        change = row.get("change")
        if change is None or abs(change) < competitor_threshold:
            continue
        crossings.append({
            "metric": "share_of_voice",
            "label": f"share of voice for {row['organization']}",
            "subject": row["organization"],
            "change": change,
            "threshold": competitor_threshold,
            "current": row["current"].get("value"),
            "previous": row["previous"].get("value"),
        })

    return crossings


def already_investigated(db: Session, brand_id: int, mode: str, scope) -> bool:
    """Has this brand already had an investigation for this exact period?

    Backed by idx_investigation_brand_mode_period. Any status counts, including
    a failed one: re-running automatically would fail the same way and fill the
    list with noise. The manual trigger stays available.
    """
    return db.query(models.Investigation.id).filter(
        models.Investigation.brand_id == brand_id,
        models.Investigation.comparison_mode == mode,
        models.Investigation.current_period_start == scope.current.start,
    ).first() is not None


def describe(crossings: List[Dict[str, Any]]) -> str:
    """One line per crossing, for the agent's opening message."""
    return "; ".join(
        f"{c['label']} moved {c['change']:+.1f} points "
        f"({c['previous']} to {c['current']}, threshold {c['threshold']})"
        for c in crossings
    )


def maybe_trigger(db: Session, owner_user_id: int, brand_id: int,
                  mode: str = TRIGGER_MODE,
                  period_start: Optional[Any] = None) -> Optional[int]:
    """Open an investigation if the period that just closed moved enough.

    period_start pins which period is examined; omitted means the last complete
    one, which is what the pipeline wants.

    Returns the new investigation id, or None if nothing warranted one.
    """
    if not auto_trigger_enabled():
        return None

    try:
        scope = build_scope(db, owner_user_id, brand_id, mode=mode,
                            period_start=period_start)
    except ScopeError as exc:
        # An empty or unpaired window is the normal state of a young brand, not
        # a problem to report.
        logger.debug("No auto-investigation for brand %s: %s", brand_id, exc)
        return None

    if already_investigated(db, brand_id, mode, scope):
        return None

    crossings = find_crossings(db, scope)
    if not crossings:
        return None

    investigation = models.Investigation(
        user_id=owner_user_id,
        brand_id=brand_id,
        trigger_type='auto',
        status='pending',
        trigger_metrics=json.dumps(crossings),
    )
    apply_scope_to_record(investigation, scope)
    db.add(investigation)
    db.commit()
    db.refresh(investigation)

    logger.info("Auto-triggered investigation %s for brand %s (%s vs %s): %s",
                investigation.id, brand_id, scope.current_label,
                scope.previous_label, describe(crossings))

    service.submit(investigation.id)
    return investigation.id


def check_after_collection(db: Session, owner_user_id: int, brand_id: int) -> None:
    """The pipeline's entry point. Cannot raise.

    A collection that succeeded must not be reported as failed because the
    follow-up analysis of it could not start.
    """
    try:
        maybe_trigger(db, owner_user_id, brand_id)
    except Exception:  # noqa: BLE001 - a trigger must never fail a collection
        logger.exception(
            "Auto-investigation check failed for brand %s; the collection itself "
            "was unaffected.", brand_id)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("Could not roll back after a failed trigger check.")
