"""
Resolving what an investigation compares.

An investigation always compares exactly two windows. Both are expressed as
metrics_query.MetricScope, which is the same type the dashboard and the exports
use, so an investigation measures precisely what the screen it was launched from
measures.

That matters more than it sounds. The reference implementation this feature is
modelled on kept two parallel comparison paths, one for batches and one for
periods, and they used different sentiment denominators. Two investigations of
the same brand could quote different numbers, and neither matched the dashboard.
Here there is one scope type and one set of definitions.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from ... import models
from ..metrics_query import MetricScope, month_bounds, quarter_bounds
from ..period_ranges import (
    brand_fiscal_start_month,
    fiscal_quarter_label,
    get_period_comparison_ranges,
)

#: A single collection batch is a noisy comparison, so a whole month is the
#: default. Matches the dashboard's own comparison dropdown.
DEFAULT_COMPARISON_MODE = "month"
COMPARISON_MODES = ("batch", "month", "quarter")


class ScopeError(ValueError):
    """The requested comparison cannot be built (no data, unknown batch, ...)."""


@dataclass(frozen=True)
class ComparisonScope:
    """The two windows an investigation compares, plus how to describe them."""
    mode: str
    current: MetricScope
    previous: MetricScope
    current_label: str
    previous_label: str

    @property
    def unit(self) -> str:
        return {"batch": "collection", "month": "month", "quarter": "quarter"}[self.mode]

    def side(self, which: str) -> MetricScope:
        if which == "current":
            return self.current
        if which == "previous":
            return self.previous
        raise ScopeError(f"Unknown side {which!r}; expected 'current' or 'previous'")


def _window_has_responses(db: Session, owner_user_id: int, brand_id: int,
                          start, end, batch_id=None) -> bool:
    query = db.query(models.Response.id).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
    )
    if batch_id is not None:
        query = query.filter(models.Response.batch_id == batch_id)
    if start is not None:
        query = query.filter(models.Response.timestamp >= start)
    if end is not None:
        query = query.filter(models.Response.timestamp < end)
    return query.first() is not None


def build_batch_scope(db: Session, owner_user_id: int, brand_id: int,
                      batch_id: Optional[int] = None) -> ComparisonScope:
    """Compare a collection batch against the one immediately before it."""
    batches = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.user_id == owner_user_id,
        models.CollectionBatch.brand_id == brand_id,
    )

    if batch_id is None:
        current = batches.order_by(models.CollectionBatch.started_at.desc()).first()
        if current is None:
            raise ScopeError("No collection batches found for this brand.")
    else:
        current = batches.filter(models.CollectionBatch.id == batch_id).first()
        if current is None:
            raise ScopeError(f"Batch {batch_id} not found for this brand.")

    # Explicitly the batch BEFORE this one. Ordering by started_at alone would
    # pick a newer batch whenever an older batch_id is passed, and compare the
    # two windows backwards.
    previous = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.user_id == owner_user_id,
        models.CollectionBatch.brand_id == brand_id,
        models.CollectionBatch.started_at < current.started_at,
    ).order_by(models.CollectionBatch.started_at.desc()).first()

    if previous is None:
        raise ScopeError(
            f"'{current.batch_name}' is the earliest collection for this brand, "
            "so there is nothing to compare it against.")

    return ComparisonScope(
        mode="batch",
        current=MetricScope.for_batch(owner_user_id, brand_id, current.id),
        previous=MetricScope.for_batch(owner_user_id, brand_id, previous.id),
        current_label=current.batch_name,
        previous_label=previous.batch_name,
    )


def build_period_scope(db: Session, owner_user_id: int, brand_id: int, mode: str,
                       period_start: Optional[datetime.datetime] = None
                       ) -> ComparisonScope:
    """Compare a calendar month or quarter against the one before it.

    Windows come from period_ranges, which is what the dashboard's Month over
    Month and Quarter over Quarter modes use, so an investigation covers exactly
    the days the dashboard was showing.
    """
    (cur_start, cur_end, cur_label,
     prev_start, prev_end, prev_label) = get_period_comparison_ranges(
        db, owner_user_id, brand_id, mode, period_start)

    for label, start, end in ((cur_label, cur_start, cur_end),
                              (prev_label, prev_start, prev_end)):
        if not _window_has_responses(db, owner_user_id, brand_id, start, end):
            raise ScopeError(
                f"No response data for {label}, so there is nothing to compare. "
                "A period with no collection in it would otherwise read as a "
                "total collapse in every metric.")

    return ComparisonScope(
        mode=mode,
        current=MetricScope(owner_user_id, brand_id, start=cur_start, end=cur_end,
                            label=cur_label),
        previous=MetricScope(owner_user_id, brand_id, start=prev_start, end=prev_end,
                             label=prev_label),
        current_label=cur_label,
        previous_label=prev_label,
    )


def build_scope(db: Session, owner_user_id: int, brand_id: int, mode: str,
                period_start: Optional[datetime.datetime] = None,
                batch_id: Optional[int] = None) -> ComparisonScope:
    """Resolve any comparison mode into two windows."""
    if mode not in COMPARISON_MODES:
        raise ScopeError(
            f"Invalid comparison_mode {mode!r}. Expected one of: "
            f"{', '.join(COMPARISON_MODES)}.")
    if mode == "batch":
        return build_batch_scope(db, owner_user_id, brand_id, batch_id)
    return build_period_scope(db, owner_user_id, brand_id, mode, period_start)


def scope_from_investigation(investigation: models.Investigation) -> ComparisonScope:
    """Rebuild the comparison from a stored record.

    The window is re-read from the columns rather than recomputed, so an
    investigation always reports on the period it was created for even if the
    period helpers change afterwards.
    """
    owner_user_id = investigation.user_id
    brand_id = investigation.brand_id

    if investigation.comparison_mode == "batch":
        if investigation.current_batch_id is None or investigation.previous_batch_id is None:
            raise ScopeError("Batch investigation is missing one of its batch ids.")
        return ComparisonScope(
            mode="batch",
            current=MetricScope.for_batch(owner_user_id, brand_id,
                                          investigation.current_batch_id),
            previous=MetricScope.for_batch(owner_user_id, brand_id,
                                           investigation.previous_batch_id),
            current_label=investigation.current_period_label or
            f"Batch {investigation.current_batch_id}",
            previous_label=investigation.previous_period_label or
            f"Batch {investigation.previous_batch_id}",
        )

    bounds = (investigation.current_period_start, investigation.current_period_end,
              investigation.previous_period_start, investigation.previous_period_end)
    if any(bound is None for bound in bounds):
        raise ScopeError(
            "Period investigation is missing one of its window bounds.")

    return ComparisonScope(
        mode=investigation.comparison_mode,
        current=MetricScope(owner_user_id, brand_id,
                            start=investigation.current_period_start,
                            end=investigation.current_period_end,
                            label=investigation.current_period_label or ""),
        previous=MetricScope(owner_user_id, brand_id,
                             start=investigation.previous_period_start,
                             end=investigation.previous_period_end,
                             label=investigation.previous_period_label or ""),
        current_label=investigation.current_period_label or "current period",
        previous_label=investigation.previous_period_label or "previous period",
    )


def apply_scope_to_record(investigation: models.Investigation,
                          scope: ComparisonScope) -> None:
    """Persist a resolved comparison onto a new Investigation record."""
    investigation.comparison_mode = scope.mode
    investigation.current_period_label = scope.current_label
    investigation.previous_period_label = scope.previous_label

    if scope.mode == "batch":
        investigation.current_batch_id = scope.current.batch_id
        investigation.previous_batch_id = scope.previous.batch_id
    else:
        investigation.current_period_start = scope.current.start
        investigation.current_period_end = scope.current.end
        investigation.previous_period_start = scope.previous.start
        investigation.previous_period_end = scope.previous.end


def recent_windows(db: Session, owner_user_id: int, brand_id: int, mode: str,
                   count: int) -> Tuple[Tuple[datetime.datetime, datetime.datetime, str], ...]:
    """The last `count` windows of `mode`, oldest first, for trend context."""
    count = max(2, min(count, 8))

    if mode == "batch":
        batches = db.query(models.CollectionBatch).filter(
            models.CollectionBatch.user_id == owner_user_id,
            models.CollectionBatch.brand_id == brand_id,
        ).order_by(models.CollectionBatch.started_at.desc()).limit(count).all()
        return tuple(reversed([(b.started_at, b.started_at, b.batch_name) for b in batches]))

    today = datetime.datetime.utcnow()
    windows = []
    if mode == "month":
        year, month = today.year, today.month
        for _ in range(count):
            month -= 1
            if month == 0:
                month, year = 12, year - 1
            start, end = month_bounds(year, month)
            windows.append((start, end, datetime.datetime(year, month, 1).strftime("%B %Y")))
    else:
        fiscal_start = brand_fiscal_start_month(db, brand_id)
        quarter = (today.month - 1) // 3 + 1
        year = today.year
        for _ in range(count):
            quarter -= 1
            if quarter == 0:
                quarter, year = 4, year - 1
            start, end = quarter_bounds(year, quarter)
            label = fiscal_quarter_label(fiscal_start, 3 * (quarter - 1) + 1, year)
            windows.append((start, end, label))

    return tuple(reversed(windows))
