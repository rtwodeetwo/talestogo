"""
Batch Analytics Caching Service

Materializes per-batch metrics so trend charts and reports do not reprocess
every response. The numbers themselves come from metrics_core, so a stored row
and a live computation agree by construction; this module only decides what to
persist. See docs/METRIC_DEFINITIONS.md.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import Optional, Dict, Any
import json
import datetime
from .. import models
from . import metrics_core, metrics_query

#: Bump when a stored column's definition changes, so a row written by an older
#: implementation can be told apart from a recomputed one. Rows written before
#: the August 2026 metric audit have this as NULL.
METRICS_VERSION = "2026.08"


def compute_batch_analytics(
    db: Session,
    batch_id: int,
    user_id: int,
    brand_id: int
) -> Optional[models.BatchAnalytics]:
    """
    Compute analytics for a specific batch and cache them in batch_analytics table.

    Args:
        db: Database session
        batch_id: ID of the collection batch
        user_id: User ID (for data isolation)
        brand_id: Brand ID

    Returns:
        BatchAnalytics model instance or None if no responses found
    """
    # Get the batch to get the collection date
    batch = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.id == batch_id,
        models.CollectionBatch.user_id == user_id,
        models.CollectionBatch.brand_id == brand_id
    ).first()

    if not batch:
        return None

    population = metrics_query.resolve(
        db, metrics_query.MetricScope.for_batch(user_id, brand_id, batch_id))

    if not population.rows:
        return None

    mention = metrics_core.mention_rate(population)
    direct = metrics_core.direct_mention_rate(population)
    positions = metrics_core.positioning_distribution(population)
    sentiment = metrics_core.sentiment_distribution(population)
    quality = metrics_core.data_quality(population)

    # total_responses is the metric denominator, not a row count for the batch.
    # Rows outside it are reported in analyzed/unanalyzed/invalid rather than
    # being folded into not_mentioned_count, which is what used to make a failed
    # analysis pass look like a drop in brand visibility.
    total_responses = int(mention.denominator)

    def position(label: str) -> int:
        return int(positions[label].numerator)

    def sentiment_count(label: str) -> int:
        return int(sentiment[label].numerator)

    # Competitor counts across ALL organic responses, not only those where the
    # brand was already mentioned. The old restriction made a competitor named
    # in an answer the brand never appeared in invisible, which inflated the
    # brand's share of voice.
    _, competitor_shares = metrics_core.share_of_voice(population)
    sov_counts: Dict[str, int] = {
        name: int(value.numerator) for name, value in competitor_shares.items()
    }

    # Case-folded, so "high-temperature plasma" and "High-Temperature Plasma"
    # stop occupying separate rows in every chart built from this data.
    descriptor_counts: Dict[str, int] = metrics_core.descriptor_frequency(population)

    values = dict(
        collection_date=batch.started_at,
        total_responses=total_responses,
        analyzed_count=quality['counted'],
        unanalyzed_count=quality['unanalyzed_excluded'],
        invalid_count=quality['invalid_enum_excluded'],
        mention_count=int(mention.numerator),
        direct_mention_count=int(direct.numerator),
        mention_rate=mention.value if mention.value is not None else 0.0,
        # The sentiment counts below divide by this, not by mention_count.
        sentiment_base_count=int(sentiment['Very Positive'].denominator),
        leader_count=position('Leader'),
        top3_count=position('Top 3'),
        featured_count=position('Featured'),
        listed_count=position('Listed'),
        not_mentioned_count=position('Not Mentioned'),
        very_positive_count=sentiment_count('Very Positive'),
        positive_count=sentiment_count('Positive'),
        neutral_count=sentiment_count('Neutral'),
        negative_count=sentiment_count('Negative'),
        very_negative_count=sentiment_count('Very Negative'),
        mixed_count=sentiment_count('Mixed'),
        sov_data=json.dumps(sov_counts) if sov_counts else None,
        descriptor_data=json.dumps(descriptor_counts) if descriptor_counts else None,
        metrics_version=METRICS_VERSION,
    )

    existing = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.batch_id == batch_id
    ).first()

    if existing:
        for field, value in values.items():
            setattr(existing, field, value)
        existing.updated_at = datetime.datetime.utcnow()
        analytics = existing
    else:
        analytics = models.BatchAnalytics(
            user_id=user_id, brand_id=brand_id, batch_id=batch_id, **values)
        db.add(analytics)

    db.commit()
    db.refresh(analytics)
    return analytics


def get_or_compute_batch_analytics(
    db: Session,
    batch_id: int,
    user_id: int,
    brand_id: int,
    force_recompute: bool = False
) -> Optional[models.BatchAnalytics]:
    """
    Get cached batch analytics or compute them if they don't exist.

    Args:
        db: Database session
        batch_id: ID of the collection batch
        user_id: User ID
        brand_id: Brand ID
        force_recompute: If True, recompute even if cache exists

    Returns:
        BatchAnalytics instance or None
    """
    if not force_recompute:
        # Try to get existing cached analytics
        existing = db.query(models.BatchAnalytics).filter(
            models.BatchAnalytics.batch_id == batch_id,
            models.BatchAnalytics.user_id == user_id,
            models.BatchAnalytics.brand_id == brand_id
        ).first()

        # A row written by an older definition is not a cache hit. Without this
        # check, rows computed before the August 2026 audit would be served
        # indefinitely: they count unanalyzed responses as "not mentioned", drop
        # 'Top 3' entirely, and divide sentiment by the wrong denominator.
        if existing and existing.metrics_version == METRICS_VERSION:
            return existing

    # Compute and cache
    return compute_batch_analytics(db, batch_id, user_id, brand_id)


def backfill_all_batch_analytics(
    db: Session,
    user_id: int,
    brand_id: int
) -> int:
    """
    Backfill analytics for all batches that don't have cached analytics.

    Args:
        db: Database session
        user_id: User ID
        brand_id: Brand ID

    Returns:
        Number of batches processed
    """
    # Get all batches for this user/brand
    batches = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.user_id == user_id,
        models.CollectionBatch.brand_id == brand_id,
        models.CollectionBatch.status == 'completed'
    ).all()

    processed = 0
    for batch in batches:
        # Check if analytics already exist
        existing = db.query(models.BatchAnalytics).filter(
            models.BatchAnalytics.batch_id == batch.id
        ).first()

        if not existing:
            result = compute_batch_analytics(db, batch.id, user_id, brand_id)
            if result:
                processed += 1
                print(f"Cached analytics for batch {batch.id}: {batch.batch_name}")

    return processed
