"""
Cached Metrics Service

Provides fast trend calculations using pre-computed batch_analytics data.
Falls back to real-time calculation if cache is missing.
"""
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import json
from .. import models
from .batch_analytics import get_or_compute_batch_analytics


def get_brand_mentions_trend_cached(
    db: Session,
    user_id: int,
    brand_id: int
) -> List[Dict[str, Any]]:
    """
    Get brand mention rate trend using cached batch analytics.

    Returns:
        List of data points with date, mention_count, total, mention_rate
    """
    # Get all batch analytics for this brand, ordered by collection date
    analytics = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.user_id == user_id,
        models.BatchAnalytics.brand_id == brand_id
    ).order_by(models.BatchAnalytics.collection_date).all()

    trend_data = []
    for batch_analytics in analytics:
        trend_data.append({
            'date': batch_analytics.collection_date,
            'mention_count': batch_analytics.mention_count,
            'total': batch_analytics.total_responses,
            'mention_rate': batch_analytics.mention_rate
        })

    return trend_data


def get_positioning_trend_cached(
    db: Session,
    user_id: int,
    brand_id: int
) -> List[Dict[str, Any]]:
    """
    Get positioning distribution trend using cached batch analytics.

    Returns:
        List of data points with date and positioning percentages
    """
    analytics = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.user_id == user_id,
        models.BatchAnalytics.brand_id == brand_id
    ).order_by(models.BatchAnalytics.collection_date).all()

    trend_data = []
    for batch_analytics in analytics:
        total = batch_analytics.total_responses
        if total > 0:
            # 'Top 3' is reported as its own series. It used to be dropped
            # entirely at the storage layer, so these percentages did not sum to
            # 100 and a Top 3 placement simply vanished from the trend.
            trend_data.append({
                'date': batch_analytics.collection_date,
                'leader': round((batch_analytics.leader_count / total) * 100, 1),
                'top_3': round(((batch_analytics.top3_count or 0) / total) * 100, 1),
                'featured': round((batch_analytics.featured_count / total) * 100, 1),
                'listed': round((batch_analytics.listed_count / total) * 100, 1),
                'not_mentioned': round((batch_analytics.not_mentioned_count / total) * 100, 1)
            })

    return trend_data


def get_sentiment_trend_cached(
    db: Session,
    user_id: int,
    brand_id: int
) -> List[Dict[str, Any]]:
    """
    Get sentiment distribution trend using cached batch analytics.

    Returns:
        List of data points with date and sentiment percentages
    """
    analytics = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.user_id == user_id,
        models.BatchAnalytics.brand_id == brand_id
    ).order_by(models.BatchAnalytics.collection_date).all()

    trend_data = []
    for batch_analytics in analytics:
        # Divide by the population the sentiment counts were taken from, not by
        # mention_count. mention_count includes Indirect mentions, which carry no
        # sentiment, so using it meant these slices never summed to 100 even
        # though they are charted as a 100% stacked distribution.
        base = batch_analytics.sentiment_base_count
        if base:
            trend_data.append({
                'date': batch_analytics.collection_date,
                'very_positive': round((batch_analytics.very_positive_count / base) * 100, 1),
                'positive': round((batch_analytics.positive_count / base) * 100, 1),
                'neutral': round((batch_analytics.neutral_count / base) * 100, 1),
                'negative': round((batch_analytics.negative_count / base) * 100, 1),
                'very_negative': round((batch_analytics.very_negative_count / base) * 100, 1),
                'mixed': round((batch_analytics.mixed_count / base) * 100, 1)
            })

    return trend_data


def get_share_of_voice_trend_cached(
    db: Session,
    user_id: int,
    brand_id: int,
    brand_name: str,
    top_n_competitors: int = 5
) -> List[Dict[str, Any]]:
    """
    Get share of voice trend using cached batch analytics.

    Returns:
        List of data points with date and SOV percentages for brand + top competitors
    """
    analytics = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.user_id == user_id,
        models.BatchAnalytics.brand_id == brand_id
    ).order_by(models.BatchAnalytics.collection_date).all()

    # First, identify top competitors across all time periods
    all_competitors = {}
    for batch_analytics in analytics:
        if batch_analytics.sov_data:
            sov_counts = json.loads(batch_analytics.sov_data)
            for org, count in sov_counts.items():
                all_competitors[org] = all_competitors.get(org, 0) + count

    # Get top N competitors
    top_competitors = sorted(all_competitors.items(), key=lambda x: x[1], reverse=True)[:top_n_competitors]
    top_competitor_names = [comp[0] for comp in top_competitors]

    # Build trend data
    trend_data = []
    for batch_analytics in analytics:
        data_point = {
            'date': batch_analytics.collection_date,
            brand_name: batch_analytics.mention_count  # Brand's mention count
        }

        # Add competitor counts
        if batch_analytics.sov_data:
            sov_counts = json.loads(batch_analytics.sov_data)
            for comp_name in top_competitor_names:
                data_point[comp_name] = sov_counts.get(comp_name, 0)

        # Calculate total mentions
        total_mentions = sum(data_point[k] for k in data_point if k != 'date')

        # Convert to percentages
        if total_mentions > 0:
            for key in data_point:
                if key != 'date':
                    data_point[key] = round((data_point[key] / total_mentions) * 100)

        trend_data.append(data_point)

    return trend_data
