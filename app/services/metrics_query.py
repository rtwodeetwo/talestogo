"""
The single population resolver: (user, brand, window) -> MetricPopulation.

WHY THIS FILE EXISTS
--------------------
Duplication in Tales was never only in the arithmetic. It was in the row
selection. Five surfaces build five different populations for what they all call
"this month's responses":

  * app/services/analytics_cache.py:91-99  INNER JOIN Query, so rows whose
    query_id no longer resolves vanish; window defaults to the last 180 days
    (:50-52) even when the caller asked for "all data"
  * app/routers/highlights.py:139-152      set membership on non-branded query
    ids, which also drops orphans; no analyzed_at filter; no user_id filter
  * scripts/admin/generate_report.py:394   no branded-query filter at all, and
    the report scopes by BATCH (:2154-2161) while its own CSV export scopes by
    response timestamp (app/routers/reports.py:295)
  * app/services/batch_analytics.py:56-68  organic-only, frozen at batch
    completion and never recomputed when a query's brand_in_query flag changes
  * app/analytics.py:53-55                 no analyzed_at filter, so unanalyzed
    rows sit in the denominator as "not mentioned"

A shared calculator fixes nothing while nine call sites still assemble different
denominators. Everything above resolves here, once.

TIMEZONE
--------
Response.timestamp is naive UTC (app/models.py:82) and every period boundary in
the app is computed in naive UTC (app/services/period_ranges.py:87-91), but the
UI renders every date in America/New_York (frontend/src/utils/dateUtils.ts:19).
A response at 2026-02-01T02:30Z displays as "Jan 31, 9:30 PM" and counts in
February everywhere. `month_bounds` and `quarter_bounds` below take an explicit
timezone, build the boundary in local time, and convert to UTC for the query, so
"February" means the same 28 days the user saw on screen.

Windows are half-open, [start, end). period_ranges.month_bounds ends at 23:59:59
and its callers use <=, which drops the final sub-second of every period;
generate_report.py:178 uses an exclusive <. Two conventions, both live.
"""
from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import models
from app.services.metrics_core import MetricPopulation, ResponseRecord

#: Matches what the UI has always displayed, so adopting this changes no dates.
DEFAULT_REPORTING_TZ = "America/New_York"

UTC = datetime.timezone.utc


# ============================================================ window helpers

def _to_naive_utc(aware: datetime.datetime) -> datetime.datetime:
    """Response.timestamp is naive UTC, so comparisons must be too."""
    return aware.astimezone(UTC).replace(tzinfo=None)


def month_bounds(year: int, month: int,
                 tz: str = DEFAULT_REPORTING_TZ
                 ) -> Tuple[datetime.datetime, datetime.datetime]:
    """Half-open [start, end) for a calendar month in `tz`, as naive UTC."""
    zone = ZoneInfo(tz)
    start = datetime.datetime(year, month, 1, tzinfo=zone)
    if month == 12:
        end = datetime.datetime(year + 1, 1, 1, tzinfo=zone)
    else:
        end = datetime.datetime(year, month + 1, 1, tzinfo=zone)
    return _to_naive_utc(start), _to_naive_utc(end)


def quarter_bounds(year: int, quarter: int,
                   tz: str = DEFAULT_REPORTING_TZ
                   ) -> Tuple[datetime.datetime, datetime.datetime]:
    """Half-open [start, end) for a calendar quarter (1-4) in `tz`, as naive UTC."""
    if not 1 <= quarter <= 4:
        raise ValueError(f"quarter must be 1-4, got {quarter}")
    start_month = 3 * (quarter - 1) + 1
    start, _ = month_bounds(year, start_month, tz)
    end_month = start_month + 2
    _, end = month_bounds(year, end_month, tz)
    return start, end


def utc_month_bounds(year: int, month: int
                     ) -> Tuple[datetime.datetime, datetime.datetime]:
    """Half-open [start, end) for a month in UTC.

    Kept explicit so the reconciliation harness can show the same batch producing
    a different "February" under each rule.
    """
    start = datetime.datetime(year, month, 1)
    if month == 12:
        return start, datetime.datetime(year + 1, 1, 1)
    return start, datetime.datetime(year, month + 1, 1)


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


# ==================================================================== scope

@dataclass(frozen=True)
class MetricScope:
    """What to measure over.

    Exactly one of `batch_id` or (`start`, `end`) should be set. With neither,
    the scope is every response for the brand, which is the honest reading of
    "all data" (analytics_cache.py:50-52 silently truncates it to 180 days).

    `owner_user_id` must be the brand OWNER, resolved with
    app/utils/brand_access.get_data_owner_user_id, not the requesting user. The
    Excel export uses current_user.id (app/routers/responses.py:159) and
    therefore 404s on shared brands that the UI happily displays.
    """
    owner_user_id: int
    brand_id: int
    batch_id: Optional[int] = None
    start: Optional[datetime.datetime] = None
    end: Optional[datetime.datetime] = None
    tz: str = DEFAULT_REPORTING_TZ
    label: str = ""

    @classmethod
    def for_month(cls, owner_user_id: int, brand_id: int, year: int, month: int,
                  tz: str = DEFAULT_REPORTING_TZ) -> "MetricScope":
        start, end = month_bounds(year, month, tz)
        label = f"{calendar.month_name[month]} {year}"
        return cls(owner_user_id, brand_id, start=start, end=end, tz=tz, label=label)

    @classmethod
    def for_quarter(cls, owner_user_id: int, brand_id: int, year: int, quarter: int,
                    tz: str = DEFAULT_REPORTING_TZ) -> "MetricScope":
        start, end = quarter_bounds(year, quarter, tz)
        return cls(owner_user_id, brand_id, start=start, end=end, tz=tz,
                   label=f"Q{quarter} {year}")

    @classmethod
    def for_batch(cls, owner_user_id: int, brand_id: int, batch_id: int,
                  tz: str = DEFAULT_REPORTING_TZ) -> "MetricScope":
        return cls(owner_user_id, brand_id, batch_id=batch_id, tz=tz,
                   label=f"Batch {batch_id}")


# ================================================================= resolver

def _split_csv(value: Optional[str]) -> Tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def resolve(db: Session, scope: MetricScope) -> MetricPopulation:
    """Load every row in scope, tagged, without filtering any of them away.

    Nothing is dropped here. Branded, unanalyzed, off-enum and orphan rows all
    come back tagged, and each metric in metrics_core applies its own documented
    selection. That is what allows data_quality() to report exactly what was
    excluded and why, instead of the current behavior where an unanalyzed row is
    arithmetically indistinguishable from "brand not mentioned".

    Both user_id AND brand_id are always filtered. Several current call sites
    filter on brand_id alone (app/analytics.py:146-148,
    analytics_cache.py:379-381, highlights.py:139-142/:467-471/:588-592).
    """
    query = db.query(models.Response).filter(
        models.Response.user_id == scope.owner_user_id,
        models.Response.brand_id == scope.brand_id,
    )
    if scope.batch_id is not None:
        query = query.filter(models.Response.batch_id == scope.batch_id)
    if scope.start is not None:
        query = query.filter(models.Response.timestamp >= scope.start)
    if scope.end is not None:
        # Half-open: [start, end). See the module docstring.
        query = query.filter(models.Response.timestamp < scope.end)

    responses = query.order_by(models.Response.id).all()

    queries = db.query(models.Query).filter(
        models.Query.user_id == scope.owner_user_id,
        models.Query.brand_id == scope.brand_id,
    ).all()
    branded_query_ids = {q.query_id for q in queries if q.brand_in_query}
    known_query_ids = {q.query_id for q in queries}

    rows: List[ResponseRecord] = [
        ResponseRecord(
            response_id=r.id,
            query_id=r.query_id,
            platform=r.platform or "Unknown",
            brand_mentioned=r.brand_mentioned,
            brand_position=r.brand_position,
            sentiment=r.sentiment,
            descriptors=_split_csv(r.descriptors),
            competitors=_split_csv(r.competitors),
            analyzed=r.analyzed_at is not None,
            is_branded_query=r.query_id in branded_query_ids,
            query_known=r.query_id in known_query_ids,
            query_text=r.query_text or "",
            timestamp=r.timestamp,
        )
        for r in responses
    ]

    descriptors = db.query(models.TargetDescriptor).filter(
        models.TargetDescriptor.user_id == scope.owner_user_id,
        models.TargetDescriptor.brand_id == scope.brand_id,
        models.TargetDescriptor.is_target == True,  # noqa: E712 - SQL boolean
    ).all()

    competitors = db.query(models.Competitor).filter(
        models.Competitor.user_id == scope.owner_user_id,
        models.Competitor.brand_id == scope.brand_id,
        models.Competitor.track == True,  # noqa: E712 - SQL boolean
    ).all()

    brand = db.query(models.BrandInfo).filter(
        models.BrandInfo.id == scope.brand_id
    ).first()

    return MetricPopulation(
        rows=rows,
        target_descriptors=tuple(d.descriptor for d in descriptors),
        tracked_competitors=tuple(c.organization for c in competitors),
        brand_name=brand.brand_name if brand else "",
        label=scope.label,
    )
