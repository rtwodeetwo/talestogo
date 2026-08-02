"""
Analytics API endpoints.

Metric definitions live in app/services/metrics_core.py and populations are
resolved by app/services/metrics_query.py. Endpoints here shape those results
for the frontend; they do not compute rates themselves. See
docs/METRIC_DEFINITIONS.md.

Redis caching is used to significantly reduce database load and improve
response times for frequently accessed analytics data.

Date range filtering is available to limit data lookback window for improved
performance with large datasets. Default lookback is 180 days (configurable).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import case
from typing import Dict, List, Any, Optional
from datetime import datetime
from .. import analytics, models, config
from ..auth import get_current_user
from ..database import get_db
from ..services import metrics_core, metrics_query
from ..services.analytics_cache import AnalyticsCache
from ..services.metrics import calculate_share_of_voice, calculate_competitor_threats
from ..services.period_ranges import (
    brand_fiscal_start_month,
    fiscal_quarter_label,
    get_period_comparison_ranges,
    parse_period_start,
)
from ..services.redis_cache import get_redis_cache
from ..utils.brand_access import get_active_brand_id, get_data_owner_user_id
from ..services.llm_provider_manager import LLMProviderManager
from .. import schemas

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"]
)


@router.get("/platform-config", response_model=schemas.PlatformConfigResponse)
def get_platform_config(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Get configured LLM platforms for frontend charts.

    Returns the list of configured (or default) LLM providers with their
    display names, colors, and enabled status. This replaces hardcoded
    PLATFORM_COLORS in frontend components.
    """
    manager = LLMProviderManager(db, current_user.tenant_id)
    platforms = manager.get_platform_config()

    return schemas.PlatformConfigResponse(
        platforms=[
            schemas.PlatformConfig(
                key=p["key"],
                name=p["name"],
                color=p["color"],
                enabled=p["enabled"]
            )
            for p in platforms
        ]
    )


def _high_threat_count_for_range(
    db: Session, owner_user_id: int, brand_id: Optional[int],
    start: datetime, end: datetime
) -> int:
    """
    Count high-threat competitors within a date range, using the same
    share-of-voice / threat calculation as the /competitor-threats endpoint
    so the number matches what the Threats card displays.
    """
    query = db.query(models.Response).filter(models.Response.user_id == owner_user_id)
    if brand_id:
        query = query.filter(models.Response.brand_id == brand_id)
    query = query.filter(
        models.Response.timestamp >= start,
        models.Response.timestamp <= end
    )
    responses = query.all()
    if not responses:
        return 0

    queries_query = db.query(models.Query).filter(models.Query.user_id == owner_user_id)
    if brand_id:
        queries_query = queries_query.filter(models.Query.brand_id == brand_id)
    queries = queries_query.all()

    competitors_query = db.query(models.Competitor).filter(models.Competitor.user_id == owner_user_id)
    if brand_id:
        competitors_query = competitors_query.filter(models.Competitor.brand_id == brand_id)
    competitors = competitors_query.all()

    brand_query = db.query(models.BrandInfo).filter(models.BrandInfo.user_id == owner_user_id)
    if brand_id:
        brand_query = brand_query.filter(models.BrandInfo.id == brand_id)
    brand = brand_query.first()
    brand_name = brand.brand_name if brand else "Your Brand"

    sov_data = calculate_share_of_voice(responses, queries, competitors, brand_name)
    threats = calculate_competitor_threats(sov_data['competitor_sov'], responses, brand_name)
    return sum(1 for c in threats if c.get('threat_level') == 'High')


def _get_period_over_period_dashboard(
    db: Session, owner_user_id: int, brand_id: Optional[int], period: str,
    period_start: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Build the dashboard payload comparing a period (month or quarter) against the
    one before it, aggregating ALL responses in each period (not batch-by-batch).
    If period_start is given, that specific period is used; otherwise the last
    complete period.
    """
    (cur_start, cur_end, cur_label,
     prev_start, prev_end, prev_label) = get_period_comparison_ranges(
        db, owner_user_id, brand_id, period, period_start)

    cur_cache = AnalyticsCache(
        db, user_id=owner_user_id, brand_id=brand_id,
        date_from=cur_start, date_to=cur_end
    )
    prev_cache = AnalyticsCache(
        db, user_id=owner_user_id, brand_id=brand_id,
        date_from=prev_start, date_to=prev_end
    )
    cur = cur_cache.get_dashboard_data()
    prev = prev_cache.get_dashboard_data()

    def delta(key: str) -> int:
        return round((cur.get(key, 0) or 0) - (prev.get(key, 0) or 0))

    def brand_leadership_visibility(cache: AnalyticsCache) -> float:
        sov = cache.get_share_of_voice_data()
        brand_row = next((row for row in sov if row.get('is_brand')), None)
        return brand_row.get('leadership_visibility', 0) if brand_row else 0

    change_leadership_visibility = round(
        brand_leadership_visibility(cur_cache) - brand_leadership_visibility(prev_cache)
    )

    # High-threat competitor delta (headline period vs baseline period)
    cur_high_threats = _high_threat_count_for_range(db, owner_user_id, brand_id, cur_start, cur_end)
    prev_high_threats = _high_threat_count_for_range(db, owner_user_id, brand_id, prev_start, prev_end)
    change_high_threats = cur_high_threats - prev_high_threats

    return {
        'mention_rate': cur.get('mention_rate', 0),
        'mention_count': cur.get('mention_count', 0),
        'total_responses': cur.get('total_responses', 0),
        'positive_sentiment': cur.get('positive_sentiment', 0),
        'descriptor_match': cur.get('descriptor_match', 0),
        'share_of_voice': cur.get('share_of_voice', 0),
        'change_mention_rate': delta('mention_rate'),
        'change_sentiment': delta('positive_sentiment'),
        'change_descriptor': delta('descriptor_match'),
        'change_share_of_voice': delta('share_of_voice'),
        'change_high_threats': change_high_threats,
        'change_leadership_visibility': change_leadership_visibility,
        'leading_position': cur.get('leading_position', 'N/A'),
        'comparison_mode': period,
        'period_label': cur_label,
        'previous_period_label': prev_label,
        'collection_date': None,
        'previous_collection_date': None,
    }


@router.get("/dashboard", response_model=Dict[str, Any])
def get_dashboard_analytics(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id),
    batch_id: Optional[int] = None,
    period: Optional[str] = None,
    period_start: Optional[str] = None
):
    """
    Get key metrics for the dashboard for the active brand.

    Every figure comes from app/services/metrics_core.py, so this endpoint, the
    exports, the generated reports and the highlights email all use one set of
    definitions. See docs/METRIC_DEFINITIONS.md.

    Previously this payload was assembled from two different generations of data
    at once: mention_rate, sentiment and positioning were read from the stored
    BatchAnalytics row while descriptor_match and share_of_voice were recomputed
    live by AnalyticsCache. Because BatchAnalytics is only written at batch
    completion and never refreshed when a query is edited or a response is
    re-analyzed, the two halves of one card row could disagree indefinitely.

    Optionally filter by batch_id for specific collection batches, or pass
    period="month" / period="quarter" for a period-over-period comparison.
    period_start ("YYYY-MM-DD") picks a specific month/quarter; if omitted, the
    last complete period is used.
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Period-over-period mode: aggregate a whole period (month or quarter) vs the
    # one before it, instead of the batch-over-batch default.
    if period in ('month', 'quarter'):
        return _get_period_over_period_dashboard(
            db, owner_user_id, brand_id, period, parse_period_start(period_start))

    # Resolve the batch from collection_batches rather than batch_analytics, so
    # the dashboard works for a batch whose cached analytics were never written.
    batch_query = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.user_id == owner_user_id,
        models.CollectionBatch.brand_id == brand_id,
    )
    if batch_id:
        current_batch = batch_query.filter(
            models.CollectionBatch.id == batch_id).first()
    else:
        current_batch = batch_query.order_by(
            models.CollectionBatch.started_at.desc()).first()

    if not current_batch:
        return _empty_dashboard_payload()

    previous_batch = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.user_id == owner_user_id,
        models.CollectionBatch.brand_id == brand_id,
        models.CollectionBatch.started_at < current_batch.started_at,
    ).order_by(models.CollectionBatch.started_at.desc()).first()

    current = _canonical_dashboard_metrics(db, owner_user_id, brand_id, current_batch.id)
    previous = (
        _canonical_dashboard_metrics(db, owner_user_id, brand_id, previous_batch.id)
        if previous_batch else None
    )

    def delta(key):
        """Difference of two unrounded values, rounded once.

        The old code rounded each operand and then subtracted, so a real change
        of 0.4 points could surface as 0 or as 1 depending on where the operands
        fell. Both sides are None-safe: with no previous batch, or with an empty
        population on either side, there is no change to report.
        """
        if previous is None:
            return 0
        before, after = previous.get(key), current.get(key)
        if before is None or after is None:
            return 0
        return round(after - before, 1)

    payload = dict(current)
    payload.update({
        'change_mention_rate': delta('mention_rate'),
        'change_sentiment': delta('positive_sentiment'),
        'change_descriptor': delta('descriptor_match'),
        'change_share_of_voice': delta('share_of_voice'),
        'change_high_threats': None,
        # Same formula as the value it sits next to. Previously the tile showed
        # Leader + Top 3 + Featured while this arrow tracked Leader alone.
        'change_leadership_visibility': delta('leadership_visibility'),
        'collection_date': current_batch.started_at.isoformat() if current_batch.started_at else None,
        'previous_collection_date': (
            previous_batch.started_at.isoformat()
            if previous_batch and previous_batch.started_at else None
        ),
    })
    return payload


def _empty_dashboard_payload() -> Dict[str, Any]:
    """Shape returned when the brand has no batches at all."""
    return {
        'mention_rate': None,
        'mention_count': 0,
        'total_responses': 0,
        'positive_sentiment': None,
        'descriptor_match': None,
        'share_of_voice': None,
        'leadership_visibility': None,
        'positioning_average': None,
        'change_mention_rate': 0,
        'change_sentiment': 0,
        'change_descriptor': 0,
        'change_share_of_voice': 0,
        'change_high_threats': None,
        'change_leadership_visibility': 0,
        'leading_position': 'N/A',
        'data_quality': {
            'total_rows': 0, 'counted': 0, 'branded_excluded': 0,
            'unanalyzed_excluded': 0, 'invalid_enum_excluded': 0,
            'orphan_query_excluded': 0,
        },
    }


def _canonical_dashboard_metrics(
    db: Session, owner_user_id: int, brand_id: Optional[int], batch_id: int
) -> Dict[str, Any]:
    """Every dashboard figure for one batch, from the canonical definitions."""
    population = metrics_query.resolve(
        db, metrics_query.MetricScope.for_batch(owner_user_id, brand_id, batch_id))

    mention = metrics_core.mention_rate(population)
    sentiment = metrics_core.positive_sentiment_rate(population)
    descriptor = metrics_core.descriptor_match_rate(population)
    leadership = metrics_core.leadership_visibility(population)
    brand_share, _ = metrics_core.share_of_voice(population)
    positioning = metrics_core.positioning_distribution(population)

    ranked = [(label, value.numerator) for label, value in positioning.items()]
    leading_position = (
        max(ranked, key=lambda item: item[1])[0]
        if any(count for _, count in ranked) else 'N/A'
    )

    return {
        'mention_rate': mention.value,
        'mention_count': int(mention.numerator),
        'total_responses': int(mention.denominator),
        'positive_sentiment': sentiment.value,
        'descriptor_match': descriptor.value,
        'share_of_voice': brand_share.value,
        'leadership_visibility': leadership.value,
        'positioning_average': metrics_core.positioning_average(population).value,
        'leading_position': leading_position,
        # What was left out and why. Without this a failed collection and a real
        # drop in visibility look identical on screen.
        'data_quality': metrics_core.data_quality(population),
    }


@router.get("/trends/mentions", response_model=List[Dict[str, Any]])
def get_mention_trends(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get mention rate trends over time for the active brand.
    Query parameter: days (default: 30)
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    return analytics.get_mention_trend(db, user_id=owner_user_id, days=days, brand_id=brand_id)


@router.get("/sentiment/breakdown", response_model=Dict[str, Any])
def get_sentiment_analysis(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id),
    batch_id: Optional[int] = None,
    period: Optional[str] = None,
    period_start: Optional[str] = None
):
    """
    Get sentiment distribution for brand mentions.
    Uses centralized AnalyticsCache to avoid redundant calculations.
    Redis caching with 15-minute TTL for improved performance.
    Optionally filter by batch_id for specific collection batches, or pass
    period="month" / period="quarter" (with optional period_start) to view a
    whole period.
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Period mode: return the windowed result directly. The Redis cache keys are
    # batch-scoped, so period mode must bypass both cache read and write.
    if period in ('month', 'quarter'):
        cur_start, cur_end, *_ = get_period_comparison_ranges(
            db, owner_user_id, brand_id, period, parse_period_start(period_start))
        cache = AnalyticsCache(db, user_id=owner_user_id, brand_id=brand_id,
                               date_from=cur_start, date_to=cur_end)
        return cache.get_sentiment_data()

    # Try Redis cache first
    redis_cache = get_redis_cache()
    cached_data = redis_cache.get_sentiment_breakdown(owner_user_id, brand_id, batch_id)
    if cached_data is not None:
        return cached_data

    # Cache miss - calculate from database
    cache = AnalyticsCache(db, user_id=owner_user_id, brand_id=brand_id, batch_id=batch_id)
    data = cache.get_sentiment_data()

    # Store in Redis for next time
    redis_cache.set_sentiment_breakdown(owner_user_id, brand_id, data, batch_id, ttl_seconds=900)

    return data


@router.get("/descriptors/insights", response_model=Dict[str, Any])
def get_descriptor_insights_endpoint(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get AI-generated insights about descriptor usage patterns.
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    return analytics.get_descriptor_insights(db, user_id=owner_user_id, brand_id=brand_id)


@router.get("/positioning/breakdown", response_model=Dict[str, Any])
def get_positioning_analysis(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id),
    batch_id: Optional[int] = None,
    period: Optional[str] = None,
    period_start: Optional[str] = None
):
    """
    Get brand positioning distribution across responses.
    Uses centralized AnalyticsCache to avoid redundant calculations.
    Redis caching with 15-minute TTL for improved performance.
    Optionally filter by batch_id for specific collection batches, or pass
    period="month" / period="quarter" (with optional period_start) to view a
    whole period.
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Period mode bypasses the batch-scoped Redis cache entirely.
    if period in ('month', 'quarter'):
        cur_start, cur_end, *_ = get_period_comparison_ranges(
            db, owner_user_id, brand_id, period, parse_period_start(period_start))
        cache = AnalyticsCache(db, user_id=owner_user_id, brand_id=brand_id,
                               date_from=cur_start, date_to=cur_end)
        return cache.get_positioning_data()

    # Try Redis cache first
    redis_cache = get_redis_cache()
    cached_data = redis_cache.get_positioning_breakdown(owner_user_id, brand_id, batch_id)
    if cached_data is not None:
        return cached_data

    # Cache miss - calculate from database
    cache = AnalyticsCache(db, user_id=owner_user_id, brand_id=brand_id, batch_id=batch_id)
    data = cache.get_positioning_data()

    # Store in Redis for next time
    redis_cache.set_positioning_breakdown(owner_user_id, brand_id, data, batch_id, ttl_seconds=900)

    return data


@router.get("/share-of-voice", response_model=List[Dict[str, Any]])
def get_share_of_voice_analysis(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id),
    batch_id: Optional[int] = None,
    period: Optional[str] = None,
    period_start: Optional[str] = None
):
    """
    Get share of voice comparison between brand and competitors.
    Uses centralized AnalyticsCache to avoid redundant calculations.
    Redis caching with 15-minute TTL for improved performance.
    Optionally filter by batch_id for specific collection batches, or pass
    period="month" / period="quarter" (with optional period_start) to view a
    whole period.
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Period mode bypasses the batch-scoped Redis cache entirely.
    if period in ('month', 'quarter'):
        cur_start, cur_end, *_ = get_period_comparison_ranges(
            db, owner_user_id, brand_id, period, parse_period_start(period_start))
        cache = AnalyticsCache(db, user_id=owner_user_id, brand_id=brand_id,
                               date_from=cur_start, date_to=cur_end)
        return cache.get_share_of_voice_data()

    # Try Redis cache first
    redis_cache = get_redis_cache()
    cached_data = redis_cache.get_share_of_voice(owner_user_id, brand_id, batch_id)
    if cached_data is not None:
        return cached_data

    # Cache miss - calculate from database
    cache = AnalyticsCache(db, user_id=owner_user_id, brand_id=brand_id, batch_id=batch_id)
    data = cache.get_share_of_voice_data()

    # Store in Redis for next time
    redis_cache.set_share_of_voice(owner_user_id, brand_id, data, batch_id, ttl_seconds=900)

    return data


@router.get("/competitor-threats", response_model=List[Dict[str, Any]])
def get_competitor_threats_analysis(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id),
    batch_id: Optional[int] = None,
    period: Optional[str] = None,
    period_start: Optional[str] = None
):
    """
    Get competitor threat analysis with threat scores.
    Optionally filter by batch_id for specific collection batches, or pass
    period="month" / period="quarter" (with optional period_start) to view a
    whole period.

    Returns a list of competitors sorted by threat level (highest first).
    Each competitor includes:
    - mention_count: Number of times mentioned
    - share_of_voice: Percentage of total mentions
    - negative_overlap: Times competitor mentioned with negative brand sentiment
    - positive_competitor: Times competitor mentioned with positive sentiment
    - threat_score: Calculated threat score
    - threat_level: High/Medium/Low threat classification
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    # Fetch all responses for the user/brand/batch
    query = db.query(models.Response).filter(models.Response.user_id == owner_user_id)
    if brand_id:
        query = query.filter(models.Response.brand_id == brand_id)
    if period in ('month', 'quarter'):
        cur_start, cur_end, *_ = get_period_comparison_ranges(
            db, owner_user_id, brand_id, period, parse_period_start(period_start))
        query = query.filter(
            models.Response.timestamp >= cur_start,
            models.Response.timestamp <= cur_end
        )
    elif batch_id:
        query = query.filter(models.Response.batch_id == batch_id)

    responses = query.all()

    # Fetch all queries for the user/brand (needed for filtering)
    queries_query = db.query(models.Query).filter(models.Query.user_id == owner_user_id)
    if brand_id:
        queries_query = queries_query.filter(models.Query.brand_id == brand_id)

    queries = queries_query.all()

    # Fetch competitors list
    competitors_query = db.query(models.Competitor).filter(models.Competitor.user_id == owner_user_id)
    if brand_id:
        competitors_query = competitors_query.filter(models.Competitor.brand_id == brand_id)

    competitors = competitors_query.all()

    # Get brand name
    brand_query = db.query(models.BrandInfo).filter(models.BrandInfo.user_id == owner_user_id)
    if brand_id:
        brand_query = brand_query.filter(models.BrandInfo.id == brand_id)

    brand = brand_query.first()
    brand_name = brand.brand_name if brand else "Your Brand"

    # Use metrics module to calculate share of voice
    sov_data = calculate_share_of_voice(responses, queries, competitors, brand_name)

    # Use metrics module to calculate competitor threats
    competitor_threats = calculate_competitor_threats(
        sov_data['competitor_sov'],
        responses,
        brand_name
    )

    return competitor_threats


@router.get("/available-periods", response_model=Dict[str, Any])
def get_available_periods(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id),
):
    """
    List the complete months and quarters that have response data for the active
    brand, most recent first, for the dashboard's period dropdown. Each entry has
    a period_start ("YYYY-MM-DD", first day of the period) and a display label.
    Quarter labels respect the brand's fiscal-year start month. The current
    in-progress period is excluded (it is incomplete).
    """
    from sqlalchemy import func

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    fiscal_start_month = brand_fiscal_start_month(db, brand_id)

    q = db.query(
        func.extract('year', models.Response.timestamp).label('y'),
        func.extract('month', models.Response.timestamp).label('m'),
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.timestamp.isnot(None),
    )
    if brand_id:
        q = q.filter(models.Response.brand_id == brand_id)
    month_pairs = {(int(y), int(m)) for y, m in q.distinct().all()}

    now = datetime.utcnow()
    cur_month_abs = now.year * 12 + (now.month - 1)
    cur_quarter_abs = now.year * 4 + (now.month - 1) // 3

    months = []
    for (year, month) in month_pairs:
        if year * 12 + (month - 1) >= cur_month_abs:
            continue  # skip the in-progress current month (and any future)
        start = datetime(year, month, 1)
        months.append({'period_start': start.strftime('%Y-%m-%d'),
                       'label': start.strftime('%B %Y')})
    months.sort(key=lambda d: d['period_start'], reverse=True)

    quarter_abs = {year * 4 + (month - 1) // 3 for (year, month) in month_pairs}
    quarters = []
    for q_abs in quarter_abs:
        if q_abs >= cur_quarter_abs:
            continue  # skip the in-progress current quarter
        year, qi = q_abs // 4, q_abs % 4
        start_month = qi * 3 + 1
        start = datetime(year, start_month, 1)
        quarters.append({'period_start': start.strftime('%Y-%m-%d'),
                         'label': fiscal_quarter_label(fiscal_start_month, start_month, year)})
    quarters.sort(key=lambda d: d['period_start'], reverse=True)

    return {'months': months, 'quarters': quarters}


@router.get("/trends/brand-mentions", response_model=List[Dict[str, Any]])
def get_brand_mentions_over_time(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get brand mention percentage over time, grouped by collection batches.
    Uses cached batch analytics for fast performance.
    """
    from ..services.cached_metrics import get_brand_mentions_trend_cached

    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    return get_brand_mentions_trend_cached(db, owner_user_id, brand_id)


@router.get("/trends/positioning", response_model=List[Dict[str, Any]])
def get_positioning_over_time(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get positioning distribution over time, grouped by collection batches.
    Uses cached batch analytics for fast performance.
    """
    from ..services.cached_metrics import get_positioning_trend_cached

    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    return get_positioning_trend_cached(db, owner_user_id, brand_id)


@router.get("/trends/share-of-voice", response_model=List[Dict[str, Any]])
def get_share_of_voice_over_time(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get share of voice over time for brand and top competitors, grouped by collection batches.
    Uses cached batch analytics for fast performance.
    """
    from ..services.cached_metrics import get_share_of_voice_trend_cached

    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    # Get brand name
    brand_query = db.query(models.BrandInfo).filter(models.BrandInfo.user_id == owner_user_id)
    if brand_id:
        brand_query = brand_query.filter(models.BrandInfo.id == brand_id)
    brand = brand_query.first()
    brand_name = brand.brand_name if brand else "Your Brand"

    return get_share_of_voice_trend_cached(db, owner_user_id, brand_id, brand_name)


@router.get("/trends/sentiment", response_model=List[Dict[str, Any]])
def get_sentiment_over_time(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get sentiment distribution over time, grouped by collection batches.
    Uses cached batch analytics for fast performance.
    """
    from ..services.cached_metrics import get_sentiment_trend_cached

    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    return get_sentiment_trend_cached(db, owner_user_id, brand_id)


@router.get("/brand-mentions-by-llm")
def get_brand_mentions_by_llm(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get brand mention rates broken down by LLM platform.
    Returns mention rate for each platform (ChatGPT, Claude, Gemini, Perplexity).
    Only includes organic queries (brand_in_query=False) for accurate visibility metrics.
    """
    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Query responses grouped by platform, joining with Query to filter for organic queries only
    from sqlalchemy import func, case

    platform_stats = db.query(
        models.Response.platform,
        func.count(models.Response.id).label('total'),
        func.sum(
            case(
                (models.Response.brand_mentioned == 'Yes', 1),
                else_=0
            )
        ).label('mentioned')
    ).join(
        models.Query,
        (models.Response.query_id == models.Query.query_id) &
        (models.Response.user_id == models.Query.user_id) &
        (models.Response.brand_id == models.Query.brand_id)
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
        models.Response.platform.isnot(None),
        models.Response.batch_id.isnot(None),  # Only include responses with batch_id for consistency with trend data
        models.Query.brand_in_query == False  # Only organic queries
    ).group_by(
        models.Response.platform
    ).all()

    # Calculate mention rate for each platform
    results = []
    for platform, total, mentioned in platform_stats:
        mention_rate = (mentioned / total * 100) if total > 0 else 0
        results.append({
            'platform': platform,
            'total_responses': total,
            'mentions': mentioned,
            'mention_rate': round(mention_rate, 1)
        })

    return results


@router.get("/positioning-by-llm")
def get_positioning_by_llm(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get brand positioning breakdown by LLM platform.
    Returns positioning counts (Leader, Featured, Listed, Not Mentioned) for each platform.
    Excludes brand_in_query responses for consistency with main positioning breakdown.
    """
    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Query responses grouped by platform and position
    # Exclude brand_in_query responses for consistency with positioning/breakdown endpoint
    from sqlalchemy import func

    platform_positioning = db.query(
        models.Response.platform,
        models.Response.brand_position,
        func.count(models.Response.id).label('count')
    ).join(
        models.Query,
        (models.Response.query_id == models.Query.query_id) &
        (models.Response.user_id == models.Query.user_id) &
        (models.Response.brand_id == models.Query.brand_id)
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
        models.Response.platform.isnot(None),
        models.Response.brand_position.isnot(None),
        models.Response.batch_id.isnot(None),  # Only include responses with batch_id for consistency with trend data
        models.Query.brand_in_query == False  # Exclude branded queries for organic positioning
    ).group_by(
        models.Response.platform,
        models.Response.brand_position
    ).all()

    # Organize data by platform
    platforms = {}
    for platform, position, count in platform_positioning:
        if platform not in platforms:
            platforms[platform] = {
                'platform': platform,
                'Leader': 0,
                'Featured': 0,
                'Listed': 0,
                'Not Mentioned': 0,
                'total': 0
            }

        # Map the position to our standard categories
        if position in ['Leader', 'Featured', 'Listed', 'Not Mentioned']:
            platforms[platform][position] = count
            platforms[platform]['total'] += count

    return list(platforms.values())


@router.get("/sentiment-by-llm")
def get_sentiment_by_llm(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get sentiment analysis breakdown by LLM platform.
    Returns sentiment distribution (Very Positive, Positive, Neutral, Negative, Very Negative, Mixed) for each platform.
    """
    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Query responses grouped by platform and sentiment
    from sqlalchemy import func

    platform_sentiment = db.query(
        models.Response.platform,
        models.Response.sentiment,
        func.count(models.Response.id).label('count')
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
        models.Response.platform.isnot(None),
        models.Response.sentiment.isnot(None),
        models.Response.brand_mentioned == 'Yes',  # Only analyze sentiment where brand is mentioned
        models.Response.batch_id.isnot(None)  # Only include responses with batch_id for consistency with trend data
    ).group_by(
        models.Response.platform,
        models.Response.sentiment
    ).all()

    # Organize data by platform
    platforms = {}
    for platform, sentiment, count in platform_sentiment:
        if platform not in platforms:
            platforms[platform] = {
                'platform': platform,
                'Very Positive': 0,
                'Positive': 0,
                'Neutral': 0,
                'Negative': 0,
                'Very Negative': 0,
                'Mixed': 0,
                'total': 0
            }

        # Map the sentiment to our standard categories
        if sentiment in ['Very Positive', 'Positive', 'Neutral', 'Negative', 'Very Negative', 'Mixed']:
            platforms[platform][sentiment] = count
            platforms[platform]['total'] += count

    return list(platforms.values())


@router.get("/share-of-voice-by-llm")
def get_share_of_voice_by_llm(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get share of voice breakdown by LLM platform.
    Returns mention counts for brand and competitors by platform.
    """
    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Get brand name
    brand = db.query(models.BrandInfo).filter(
        models.BrandInfo.user_id == owner_user_id,
        models.BrandInfo.id == brand_id
    ).first()

    if not brand:
        return []

    brand_name = brand.brand_name

    # Get all responses grouped by platform
    from sqlalchemy import func, case

    # Count brand mentions by platform
    brand_mentions = db.query(
        models.Response.platform,
        func.count(models.Response.id).label('brand_mentions')
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
        models.Response.platform.isnot(None),
        models.Response.brand_mentioned == 'Yes',
        models.Response.batch_id.isnot(None)  # Only include responses with batch_id for consistency with trend data
    ).group_by(
        models.Response.platform
    ).all()

    # Count competitor mentions by platform
    competitor_mentions = db.query(
        models.Response.platform,
        func.count(models.Response.id).label('competitor_mentions')
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
        models.Response.platform.isnot(None),
        models.Response.competitors.isnot(None),
        models.Response.competitors != '',
        models.Response.batch_id.isnot(None)  # Only include responses with batch_id for consistency with trend data
    ).group_by(
        models.Response.platform
    ).all()

    # Combine the data
    platforms = {}

    # Add brand mentions
    for platform, count in brand_mentions:
        if platform not in platforms:
            platforms[platform] = {
                'platform': platform,
                'brand': 0,
                'competitors': 0
            }
        platforms[platform]['brand'] = count

    # Add competitor mentions
    for platform, count in competitor_mentions:
        if platform not in platforms:
            platforms[platform] = {
                'platform': platform,
                'brand': 0,
                'competitors': 0
            }
        platforms[platform]['competitors'] = count

    return list(platforms.values())


@router.get("/descriptors-by-llm")
def get_descriptors_by_llm(
    batch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get top descriptors breakdown by LLM platform.
    Returns the most common descriptors used by each platform.

    Counts only responses where the brand is mentioned, and (when batch_id is
    given) only the selected collection batch, so the numbers line up with the
    Target Descriptors table on the Descriptor Analysis page.
    """
    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Get all descriptors by platform
    query = db.query(
        models.Response.platform,
        models.Response.descriptors
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
        models.Response.platform.isnot(None),
        models.Response.descriptors.isnot(None),
        models.Response.descriptors != '',
        models.Response.brand_mentioned == 'Yes',
        models.Response.batch_id.isnot(None)  # Only include responses with batch_id for consistency with trend data
    )
    if batch_id is not None:
        query = query.filter(models.Response.batch_id == batch_id)
    responses = query.all()

    # Process descriptors by platform
    platform_descriptors = {}

    for platform, descriptors_str in responses:
        if platform not in platform_descriptors:
            platform_descriptors[platform] = {}

        # Split descriptors by comma and count
        if descriptors_str:
            descriptors = [d.strip() for d in descriptors_str.split(',') if d.strip()]
            for descriptor in descriptors:
                if descriptor not in platform_descriptors[platform]:
                    platform_descriptors[platform][descriptor] = 0
                platform_descriptors[platform][descriptor] += 1

    # Format results - get top 5 descriptors per platform
    results = []
    for platform, descriptors in platform_descriptors.items():
        # Sort by count and get top 5
        top_descriptors = sorted(descriptors.items(), key=lambda x: x[1], reverse=True)[:5]

        results.append({
            'platform': platform,
            'descriptors': [{'descriptor': d, 'count': c} for d, c in top_descriptors],
            'total_mentions': sum(descriptors.values())
        })

    return results


@router.get("/threats-by-llm")
def get_threats_by_llm(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Get competitor threat analysis breakdown by LLM platform.
    Returns top competitors mentioned by each platform.
    """
    if not brand_id:
        return []

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    # Get all responses with competitors by platform
    responses = db.query(
        models.Response.platform,
        models.Response.competitors,
        models.Response.sentiment
    ).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
        models.Response.platform.isnot(None),
        models.Response.competitors.isnot(None),
        models.Response.competitors != '',
        models.Response.batch_id.isnot(None)  # Only include responses with batch_id for consistency with trend data
    ).all()

    # Process competitors by platform
    platform_competitors = {}

    for platform, competitors_str, sentiment in responses:
        if platform not in platform_competitors:
            platform_competitors[platform] = {}

        # Split competitors by comma and count
        if competitors_str:
            competitors = [c.strip() for c in competitors_str.split(',') if c.strip()]
            for competitor in competitors:
                if competitor not in platform_competitors[platform]:
                    platform_competitors[platform][competitor] = {
                        'count': 0,
                        'negative_overlap': 0
                    }
                platform_competitors[platform][competitor]['count'] += 1

                # Track negative overlap
                if sentiment in ['Negative', 'Very Negative']:
                    platform_competitors[platform][competitor]['negative_overlap'] += 1

    # Format results - get top 5 competitors per platform
    results = []
    for platform, competitors in platform_competitors.items():
        # Sort by count and get top 5
        top_competitors = sorted(
            competitors.items(),
            key=lambda x: (x[1]['count'], x[1]['negative_overlap']),
            reverse=True
        )[:5]

        results.append({
            'platform': platform,
            'competitors': [
                {
                    'name': name,
                    'mentions': data['count'],
                    'negative_overlap': data['negative_overlap']
                }
                for name, data in top_competitors
            ],
            'total_competitor_mentions': sum(c['count'] for c in competitors.values())
        })

    return results


@router.post("/invalidate-cache", response_model=Dict[str, Any])
def invalidate_analytics_cache(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Invalidate all cached analytics data for the current user/brand.
    Use this to force recalculation of metrics from the database.
    """
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    redis_cache = get_redis_cache()
    deleted_count = redis_cache.invalidate_user(owner_user_id, brand_id)

    return {
        "success": True,
        "message": f"Invalidated {deleted_count} cache entries for user {owner_user_id}, brand {brand_id}",
        "deleted_count": deleted_count
    }
