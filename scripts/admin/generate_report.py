#!/usr/bin/env python3
"""
TALES Report Generation Script
Generates professional analysis reports from analyzed response data.

LLM provider is configured per-tenant via Admin → LLM Providers. The provider
flagged use_for_analysis=True writes the report prose. Providers flagged
supports_web_search=True (Gemini or Perplexity) ground the "State of the LLMs"
section in fresh web data; if no web-search provider is configured, that
section is gracefully omitted from the report.

Report Types:
- monthly: Focuses on the last complete calendar month of data, with historical context for trends
- quarterly: Analyzes data from the previous complete calendar quarter (Q1-Q4)
- annual: Comprehensive analysis of the previous complete calendar year
- all_data: Comprehensive analysis using all historical data (legacy behavior)

For scheduled reports, period_start, period_end, and period_label can be passed
to override the automatic date range calculation.
"""

import os
import json
import sys
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Dict, List, Any, Optional
from collections import Counter
from dotenv import load_dotenv

from app.database import SessionLocal
from app.utils.timezone import now_eastern, format_eastern, format_eastern_date
from app.models import Response, Query, Competitor, TargetDescriptor, Report, BrandInfo, User, TaskStatus, CollectionBatch, BatchAnalytics
from app import crud, schemas
from app.services.chart_generator import generate_all_charts
from app.services.llm_provider_manager import LLMProviderManager, ProviderConfig
from app.services.generic_llm_client import GenericLLMClient, LLMAPIError, LLMConfigurationError
from app.services.metrics import (
    calculate_mention_metrics,
    calculate_positioning_metrics,
    calculate_positioning_average,
    calculate_sentiment_metrics,
    calculate_positive_sentiment_rate,
    calculate_platform_metrics,
    analyze_descriptors,
    analyze_competitors,
    calculate_descriptor_match_rate,
    calculate_share_of_voice,
    calculate_competitor_threats,
    get_negative_sentiment_statements,
    normalize_organization_name,
)
from app.services.cached_metrics import (
    get_brand_mentions_trend_cached,
    get_positioning_trend_cached,
    get_sentiment_trend_cached,
    get_share_of_voice_trend_cached,
)

load_dotenv()


# ==================== LLM HELPER FUNCTIONS ====================

def call_report_llm(
    prompt: str,
    provider: Optional[ProviderConfig] = None,
    max_tokens: int = 8000,
    temperature: float = 0.7
) -> str:
    """
    Call the report-writing LLM. Requires an explicitly configured provider —
    legacy env-var fallbacks were removed when the codebase went fully
    provider-agnostic (see CLAUDE.md, strip-to-tales-only branch).
    """
    if provider is None:
        raise ValueError(
            "No analysis LLM configured. Configure one in Admin → LLM Providers "
            "(set use_for_analysis=True)."
        )

    return provider.call(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def call_web_search_llm(
    prompt: str,
    web_search_providers: List[ProviderConfig] = None,
    analysis_provider: Optional[ProviderConfig] = None,
) -> Optional[str]:
    """
    Call a web-search-capable LLM for the "State of the LLMs" section.

    Tries each configured provider with supports_web_search=True in order.
    Returns None if none are configured or all fail; the caller
    (research_llm_state_changes) interprets None as "skip the section
    entirely", which the report orchestrator already handles.

    Supported web-search providers:
    - Gemini (Google Search grounding) — single round-trip
    - Perplexity sonar (built-in search) — single round-trip
    - Bing Search v7 — retrieves, then synthesizes with analysis_provider
    - Azure AI Foundry Grounding with Bing — single round-trip (agent does both)

    Deployments without any of these get the graceful-skip behavior.
    """
    if not web_search_providers:
        return None

    for provider in web_search_providers:
        try:
            if provider.api_type in ("google", "bing_grounded", "azure_foundry_agents"):
                # Single-provider grounded calls. Bing-grounded uses an Azure AI
                # Foundry agent that has the Grounding-with-Bing tool attached.
                return provider.call_with_web_search(prompt=prompt)
            elif provider.api_type == "bing_v7":
                # Retrieve via Bing v7, synthesize with the analysis provider.
                if analysis_provider is None:
                    print(
                        f"    Skipping {provider.display_name}: bing_v7 requires "
                        "an analysis LLM (mark one provider use_for_analysis=True)"
                    )
                    continue
                return provider.call_with_web_search(
                    prompt=prompt, analysis_provider=analysis_provider
                )
            elif (
                provider.api_type == "openai_compatible"
                and provider.api_endpoint
                and "perplexity" in provider.api_endpoint.lower()
            ):
                return provider.call(prompt=prompt, max_tokens=4000, temperature=0.7)
        except (LLMAPIError, LLMConfigurationError) as e:
            print(f"    Web search provider {provider.display_name} failed: {e}")
            continue

    return None


# ==================== DATA COLLECTION ====================

def get_brand_analyzed_responses(
    db,
    user_id: int,
    brand_id: int,
    days_back: Optional[int] = None,
    batch_ids: Optional[List[int]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> List[Response]:
    """
    Fetch analyzed responses for specific brand.

    Args:
        db: Database session
        user_id: User ID
        brand_id: Brand ID
        days_back: If set, only return responses from the last N days
        batch_ids: If set, only return responses from these batch IDs
        start_date: If set, only return responses on or after this date
        end_date: If set, only return responses before this date

    Returns:
        List of Response objects
    """
    query = db.query(Response).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.analyzed_at.isnot(None)
    )

    # Filter by date range if specified
    if start_date is not None:
        query = query.filter(Response.timestamp >= start_date)
    if end_date is not None:
        query = query.filter(Response.timestamp < end_date)

    # Filter by days_back if specified (legacy support)
    if days_back is not None:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        query = query.filter(Response.timestamp >= cutoff_date)

    # Filter by batch IDs if specified
    if batch_ids:
        query = query.filter(Response.batch_id.in_(batch_ids))

    return query.all()


def get_last_calendar_month_range() -> tuple[datetime, datetime, str]:
    """
    Get the date range for the last complete calendar month.

    Returns:
        Tuple of (start_date, end_date, month_name)
        - start_date: First day of last month at 00:00:00
        - end_date: First day of current month at 00:00:00 (exclusive)
        - month_name: Name of the month (e.g., "December 2024")
    """
    today = datetime.utcnow()

    # Get first day of current month
    first_of_current_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Get first day of last month
    if today.month == 1:
        # January -> go back to December of previous year
        first_of_last_month = first_of_current_month.replace(year=today.year - 1, month=12)
    else:
        first_of_last_month = first_of_current_month.replace(month=today.month - 1)

    # Format month name
    month_name = first_of_last_month.strftime("%B %Y")

    return first_of_last_month, first_of_current_month, month_name


def get_last_quarter_range() -> tuple[datetime, datetime, str]:
    """
    Get the date range for the last complete calendar quarter.

    Calendar quarters:
    - Q1: January 1 - March 31
    - Q2: April 1 - June 30
    - Q3: July 1 - September 30
    - Q4: October 1 - December 31

    Returns:
        Tuple of (start_date, end_date, quarter_label)
        - start_date: First day of the quarter at 00:00:00
        - end_date: First day of next quarter at 00:00:00 (exclusive)
        - quarter_label: e.g., "Q4 2025"
    """
    today = datetime.utcnow()
    current_quarter = (today.month - 1) // 3 + 1
    current_year = today.year

    # Get previous quarter
    if current_quarter == 1:
        prev_quarter = 4
        prev_year = current_year - 1
    else:
        prev_quarter = current_quarter - 1
        prev_year = current_year

    # Quarter start month (1, 4, 7, or 10)
    quarter_start_month = (prev_quarter - 1) * 3 + 1

    # Quarter end month (3, 6, 9, or 12)
    quarter_end_month = prev_quarter * 3

    # Calculate dates
    start_date = datetime(prev_year, quarter_start_month, 1, 0, 0, 0)

    # End date is first day of next quarter
    if quarter_end_month == 12:
        end_date = datetime(prev_year + 1, 1, 1, 0, 0, 0)
    else:
        end_date = datetime(prev_year, quarter_end_month + 1, 1, 0, 0, 0)

    quarter_label = f"Q{prev_quarter} {prev_year}"

    return start_date, end_date, quarter_label


def get_last_year_range() -> tuple[datetime, datetime, str]:
    """
    Get the date range for the last complete calendar year.

    Returns:
        Tuple of (start_date, end_date, year_label)
        - start_date: January 1 of last year at 00:00:00
        - end_date: January 1 of current year at 00:00:00 (exclusive)
        - year_label: e.g., "2025 Annual Report"
    """
    today = datetime.utcnow()
    prev_year = today.year - 1

    start_date = datetime(prev_year, 1, 1, 0, 0, 0)
    end_date = datetime(today.year, 1, 1, 0, 0, 0)

    year_label = f"{prev_year} Annual Report"

    return start_date, end_date, year_label


def get_last_month_batch_ids(db, user_id: int, brand_id: int) -> tuple[List[int], str]:
    """
    Get batch IDs for collections from the last complete calendar month.

    Args:
        db: Database session
        user_id: User ID
        brand_id: Brand ID

    Returns:
        Tuple of (batch_ids, month_name)
    """
    start_date, end_date, month_name = get_last_calendar_month_range()

    batches = db.query(CollectionBatch).filter(
        CollectionBatch.user_id == user_id,
        CollectionBatch.brand_id == brand_id,
        CollectionBatch.status == 'completed',
        CollectionBatch.started_at >= start_date,
        CollectionBatch.started_at < end_date
    ).all()

    return [batch.id for batch in batches], month_name


# ==================== TREND BREAKDOWN FUNCTIONS ====================

def calculate_period_metrics(db, user_id: int, brand_id: int, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """
    Calculate key metrics for a specific time period.

    Used by trend breakdown functions to calculate metrics for each sub-period.

    Args:
        db: Database session
        user_id: User ID
        brand_id: Brand ID
        start_date: Start of period (inclusive)
        end_date: End of period (exclusive)

    Returns:
        Dict with metrics: total_responses, mentions, mention_rate, sentiment breakdown, etc.
    """
    from sqlalchemy import func, case

    # Get responses in this period
    responses = db.query(Response).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.timestamp >= start_date,
        Response.timestamp < end_date,
        Response.analyzed_at.isnot(None)
    ).all()

    total = len(responses)
    if total == 0:
        return {
            'total_responses': 0,
            'mentions': 0,
            'mention_rate': 0,
            'sentiment': {'positive': 0, 'neutral': 0, 'negative': 0},
            'positioning': {'leader': 0, 'featured': 0, 'listed': 0}
        }

    # Count mentions
    mentions = sum(1 for r in responses if r.brand_mentioned == 'Yes')
    indirect = sum(1 for r in responses if r.brand_mentioned == 'Indirect')

    # Sentiment breakdown
    very_positive = sum(1 for r in responses if r.sentiment == 'Very Positive')
    positive = sum(1 for r in responses if r.sentiment == 'Positive')
    neutral = sum(1 for r in responses if r.sentiment == 'Neutral')
    negative = sum(1 for r in responses if r.sentiment == 'Negative')
    mixed = sum(1 for r in responses if r.sentiment == 'Mixed')

    # Positioning breakdown
    leader = sum(1 for r in responses if r.brand_position == 'Leader')
    top3 = sum(1 for r in responses if r.brand_position == 'Top 3')
    featured = sum(1 for r in responses if r.brand_position == 'Featured')
    listed = sum(1 for r in responses if r.brand_position == 'Listed')

    return {
        'total_responses': total,
        'mentions': mentions,
        'indirect': indirect,
        'mention_rate': round((mentions + indirect) / total * 100, 1) if total > 0 else 0,
        'direct_mention_rate': round(mentions / total * 100, 1) if total > 0 else 0,
        'sentiment': {
            'very_positive': very_positive,
            'positive': positive,
            'neutral': neutral,
            'negative': negative,
            'mixed': mixed,
            'positive_rate': round((very_positive + positive) / (mentions + indirect) * 100, 1) if (mentions + indirect) > 0 else 0
        },
        'positioning': {
            'leader': leader,
            'top3': top3,
            'featured': featured,
            'listed': listed
        }
    }


def get_weekly_breakdown(db, user_id: int, brand_id: int, month_start: datetime, month_end: datetime) -> List[Dict[str, Any]]:
    """
    Get week-by-week metrics breakdown for monthly reports.

    Divides the month into weeks and calculates metrics for each week.
    Used to show trends within a monthly report.

    Args:
        db: Database session
        user_id: User ID
        brand_id: Brand ID
        month_start: First day of the month
        month_end: First day of next month (exclusive)

    Returns:
        List of weekly metrics, each containing start, end, week_number, and metrics
    """
    weeks = []
    current = month_start
    week_num = 1

    while current < month_end:
        # Each week is 7 days, but last week may be shorter
        week_end = min(current + timedelta(days=7), month_end)

        metrics = calculate_period_metrics(db, user_id, brand_id, current, week_end)

        weeks.append({
            'week_number': week_num,
            'start': current,
            'end': week_end,
            'start_label': current.strftime('%b %d'),
            'end_label': (week_end - timedelta(days=1)).strftime('%b %d'),
            'metrics': metrics
        })

        current = week_end
        week_num += 1

    return weeks


def get_monthly_breakdown(db, user_id: int, brand_id: int, quarter_start: datetime, quarter_end: datetime) -> List[Dict[str, Any]]:
    """
    Get month-by-month metrics breakdown for quarterly reports.

    Divides the quarter into months and calculates metrics for each month.
    Used to show trends within a quarterly report.

    Args:
        db: Database session
        user_id: User ID
        brand_id: Brand ID
        quarter_start: First day of the quarter
        quarter_end: First day of next quarter (exclusive)

    Returns:
        List of monthly metrics, each containing month name, dates, and metrics
    """
    months = []
    current = quarter_start

    while current < quarter_end:
        # Calculate end of month
        if current.month == 12:
            month_end = datetime(current.year + 1, 1, 1)
        else:
            month_end = datetime(current.year, current.month + 1, 1)

        # Don't go past quarter end
        month_end = min(month_end, quarter_end)

        metrics = calculate_period_metrics(db, user_id, brand_id, current, month_end)

        months.append({
            'month_name': current.strftime('%B'),
            'month_short': current.strftime('%b'),
            'start': current,
            'end': month_end,
            'metrics': metrics
        })

        current = month_end

    return months


def get_quarterly_breakdown(db, user_id: int, brand_id: int, year_start: datetime, year_end: datetime) -> List[Dict[str, Any]]:
    """
    Get quarter-by-quarter metrics breakdown for annual reports.

    Divides the year into quarters and calculates metrics for each quarter.
    Used to show trends within an annual report.

    Args:
        db: Database session
        user_id: User ID
        brand_id: Brand ID
        year_start: January 1 of the year
        year_end: January 1 of next year (exclusive)

    Returns:
        List of quarterly metrics, each containing quarter label, dates, and metrics
    """
    quarters = []
    year = year_start.year

    for q in range(1, 5):
        # Quarter start month (1, 4, 7, or 10)
        quarter_start_month = (q - 1) * 3 + 1
        quarter_start = datetime(year, quarter_start_month, 1)

        # Quarter end (first day of next quarter)
        if q == 4:
            quarter_end = datetime(year + 1, 1, 1)
        else:
            quarter_end = datetime(year, quarter_start_month + 3, 1)

        metrics = calculate_period_metrics(db, user_id, brand_id, quarter_start, quarter_end)

        quarters.append({
            'quarter_number': q,
            'quarter_label': f'Q{q}',
            'start': quarter_start,
            'end': quarter_end,
            'start_label': quarter_start.strftime('%b'),
            'end_label': (quarter_end - timedelta(days=1)).strftime('%b'),
            'metrics': metrics
        })

    return quarters


def format_trend_summary(breakdown: List[Dict], period_type: str) -> str:
    """
    Format trend data into a readable summary for LLM prompts.

    Args:
        breakdown: List of period metrics from get_weekly/monthly/quarterly_breakdown
        period_type: 'weekly', 'monthly', or 'quarterly'

    Returns:
        Formatted string describing the trends
    """
    if not breakdown:
        return "No data available for trend analysis."

    lines = []

    if period_type == 'weekly':
        lines.append("Week-by-Week Breakdown:")
        for week in breakdown:
            m = week['metrics']
            if m['total_responses'] > 0:
                lines.append(
                    f"  - Week {week['week_number']} ({week['start_label']}-{week['end_label']}): "
                    f"{m['total_responses']} responses, {m['mention_rate']}% mention rate, "
                    f"{m['sentiment']['positive_rate']}% positive sentiment"
                )
            else:
                lines.append(f"  - Week {week['week_number']}: No data collected")

    elif period_type == 'monthly':
        lines.append("Month-by-Month Breakdown:")
        for month in breakdown:
            m = month['metrics']
            if m['total_responses'] > 0:
                lines.append(
                    f"  - {month['month_name']}: "
                    f"{m['total_responses']} responses, {m['mention_rate']}% mention rate, "
                    f"{m['sentiment']['positive_rate']}% positive sentiment"
                )
            else:
                lines.append(f"  - {month['month_name']}: No data collected")

    elif period_type == 'quarterly':
        lines.append("Quarter-by-Quarter Breakdown:")
        for quarter in breakdown:
            m = quarter['metrics']
            if m['total_responses'] > 0:
                lines.append(
                    f"  - {quarter['quarter_label']} ({quarter['start_label']}-{quarter['end_label']}): "
                    f"{m['total_responses']} responses, {m['mention_rate']}% mention rate, "
                    f"{m['sentiment']['positive_rate']}% positive sentiment"
                )
            else:
                lines.append(f"  - {quarter['quarter_label']}: No data collected")

    # Add trend analysis
    if len(breakdown) >= 2:
        first = breakdown[0]['metrics']
        last = breakdown[-1]['metrics']

        if first['total_responses'] > 0 and last['total_responses'] > 0:
            mention_change = last['mention_rate'] - first['mention_rate']
            sentiment_change = last['sentiment']['positive_rate'] - first['sentiment']['positive_rate']

            lines.append("")
            lines.append("Trend Summary:")
            if mention_change > 0:
                lines.append(f"  - Mention rate increased by {mention_change:.1f} percentage points")
            elif mention_change < 0:
                lines.append(f"  - Mention rate decreased by {abs(mention_change):.1f} percentage points")
            else:
                lines.append(f"  - Mention rate remained stable")

            if sentiment_change > 0:
                lines.append(f"  - Positive sentiment increased by {sentiment_change:.1f} percentage points")
            elif sentiment_change < 0:
                lines.append(f"  - Positive sentiment decreased by {abs(sentiment_change):.1f} percentage points")
            else:
                lines.append(f"  - Positive sentiment remained stable")

    return "\n".join(lines)


def get_historical_metrics_summary(db, user_id: int, brand_id: int, brand_name: str) -> Dict[str, Any]:
    """
    Get historical metrics from BatchAnalytics for trend comparison.

    Returns a summary of all-time performance to compare against monthly metrics.
    """
    all_analytics = db.query(BatchAnalytics).filter(
        BatchAnalytics.user_id == user_id,
        BatchAnalytics.brand_id == brand_id
    ).order_by(BatchAnalytics.collection_date).all()

    if not all_analytics:
        return None

    # Calculate averages across all time
    total_responses = sum(a.total_responses for a in all_analytics)
    total_mentions = sum(a.mention_count for a in all_analytics)

    # Weighted average mention rate
    avg_mention_rate = round((total_mentions / total_responses * 100)) if total_responses > 0 else 0

    # Average sentiment (weighted by mentions)
    total_positive = sum(a.very_positive_count + a.positive_count for a in all_analytics)
    avg_positive_rate = round((total_positive / total_mentions * 100)) if total_mentions > 0 else 0

    # Get earliest and latest dates
    earliest_date = all_analytics[0].collection_date
    latest_date = all_analytics[-1].collection_date

    return {
        'total_batches': len(all_analytics),
        'total_responses': total_responses,
        'total_mentions': total_mentions,
        'avg_mention_rate': avg_mention_rate,
        'avg_positive_rate': avg_positive_rate,
        'earliest_date': earliest_date,
        'latest_date': latest_date,
        'date_range_days': (latest_date - earliest_date).days if earliest_date and latest_date else 0
    }


def get_brand_queries(db, user_id: int, brand_id: int) -> List[Query]:
    """Fetch all queries for specific brand."""
    return db.query(Query).filter(
        Query.user_id == user_id,
        Query.brand_id == brand_id
    ).all()


def get_brand_competitors(db, user_id: int, brand_id: int) -> List[Competitor]:
    """Fetch all competitors for specific brand."""
    return db.query(Competitor).filter(
        Competitor.user_id == user_id,
        Competitor.brand_id == brand_id
    ).all()


def get_brand_descriptors(db, user_id: int, brand_id: int) -> List[TargetDescriptor]:
    """Fetch all target descriptors for specific brand."""
    return db.query(TargetDescriptor).filter(
        TargetDescriptor.user_id == user_id,
        TargetDescriptor.brand_id == brand_id
    ).all()


def get_brand_info(db, brand_id: int) -> Optional[BrandInfo]:
    """Fetch brand information."""
    return db.query(BrandInfo).filter(BrandInfo.id == brand_id).first()


# ==================== LLM BREAKDOWN DATA COLLECTION ====================

def get_llm_breakdown_data(db, user_id: int, brand_id: int, brand_name: str) -> Dict[str, Any]:
    """
    Collect all LLM-specific breakdown data for the report.
    This mirrors the analytics endpoints used in the UI.
    """
    from sqlalchemy import func, case

    llm_data = {
        'brand_mentions': [],
        'positioning': [],
        'sentiment': [],
        'share_of_voice': [],
        'descriptors': [],
        'threats': []
    }

    # 1. Brand Mentions by LLM
    platform_stats = db.query(
        Response.platform,
        func.count(Response.id).label('total'),
        func.sum(
            case(
                (Response.brand_mentioned == 'Yes', 1),
                else_=0
            )
        ).label('mentioned')
    ).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.platform.isnot(None)
    ).group_by(
        Response.platform
    ).all()

    for platform, total, mentioned in platform_stats:
        mention_rate = (mentioned / total * 100) if total > 0 else 0
        llm_data['brand_mentions'].append({
            'platform': platform,
            'total_responses': total,
            'mentions': mentioned,
            'mention_rate': round(mention_rate, 1)
        })

    # 2. Positioning by LLM
    platform_positioning = db.query(
        Response.platform,
        Response.brand_position,
        func.count(Response.id).label('count')
    ).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.platform.isnot(None),
        Response.brand_position.isnot(None)
    ).group_by(
        Response.platform,
        Response.brand_position
    ).all()

    platforms_positioning = {}
    for platform, position, count in platform_positioning:
        if platform not in platforms_positioning:
            platforms_positioning[platform] = {
                'platform': platform,
                'Leader': 0,
                'Featured': 0,
                'Listed': 0,
                'Not Mentioned': 0,
                'total': 0
            }
        if position in ['Leader', 'Featured', 'Listed', 'Not Mentioned']:
            platforms_positioning[platform][position] = count
            platforms_positioning[platform]['total'] += count

    llm_data['positioning'] = list(platforms_positioning.values())

    # 3. Sentiment by LLM
    platform_sentiment = db.query(
        Response.platform,
        Response.sentiment,
        func.count(Response.id).label('count')
    ).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.platform.isnot(None),
        Response.sentiment.isnot(None),
        Response.brand_mentioned == 'Yes'
    ).group_by(
        Response.platform,
        Response.sentiment
    ).all()

    platforms_sentiment = {}
    for platform, sentiment, count in platform_sentiment:
        if platform not in platforms_sentiment:
            platforms_sentiment[platform] = {
                'platform': platform,
                'Very Positive': 0,
                'Positive': 0,
                'Neutral': 0,
                'Negative': 0,
                'Very Negative': 0,
                'Mixed': 0,
                'total': 0
            }
        if sentiment in ['Very Positive', 'Positive', 'Neutral', 'Negative', 'Very Negative', 'Mixed']:
            platforms_sentiment[platform][sentiment] = count
            platforms_sentiment[platform]['total'] += count

    llm_data['sentiment'] = list(platforms_sentiment.values())

    # 4. Share of Voice by LLM
    brand_mentions = db.query(
        Response.platform,
        func.count(Response.id).label('brand_mentions')
    ).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.platform.isnot(None),
        Response.brand_mentioned == 'Yes'
    ).group_by(
        Response.platform
    ).all()

    competitor_mentions = db.query(
        Response.platform,
        func.count(Response.id).label('competitor_mentions')
    ).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.platform.isnot(None),
        Response.competitors.isnot(None),
        Response.competitors != ''
    ).group_by(
        Response.platform
    ).all()

    platforms_sov = {}
    for platform, count in brand_mentions:
        if platform not in platforms_sov:
            platforms_sov[platform] = {'platform': platform, 'brand': 0, 'competitors': 0}
        platforms_sov[platform]['brand'] = count

    for platform, count in competitor_mentions:
        if platform not in platforms_sov:
            platforms_sov[platform] = {'platform': platform, 'brand': 0, 'competitors': 0}
        platforms_sov[platform]['competitors'] = count

    llm_data['share_of_voice'] = list(platforms_sov.values())

    # 5. Descriptors by LLM
    responses_descriptors = db.query(
        Response.platform,
        Response.descriptors
    ).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.platform.isnot(None),
        Response.descriptors.isnot(None),
        Response.descriptors != ''
    ).all()

    platform_descriptors = {}
    for platform, descriptors_str in responses_descriptors:
        if platform not in platform_descriptors:
            platform_descriptors[platform] = {}
        if descriptors_str:
            descriptors = [d.strip() for d in descriptors_str.split(',') if d.strip()]
            for descriptor in descriptors:
                if descriptor not in platform_descriptors[platform]:
                    platform_descriptors[platform][descriptor] = 0
                platform_descriptors[platform][descriptor] += 1

    for platform, descriptors in platform_descriptors.items():
        top_descriptors = sorted(descriptors.items(), key=lambda x: x[1], reverse=True)[:5]
        llm_data['descriptors'].append({
            'platform': platform,
            'descriptors': [{'descriptor': d, 'count': c} for d, c in top_descriptors],
            'total_mentions': sum(descriptors.values())
        })

    # 6. Competitor Threats by LLM
    responses_threats = db.query(
        Response.platform,
        Response.competitors,
        Response.sentiment
    ).filter(
        Response.user_id == user_id,
        Response.brand_id == brand_id,
        Response.platform.isnot(None),
        Response.competitors.isnot(None),
        Response.competitors != ''
    ).all()

    platform_competitors = {}
    for platform, competitors_str, sentiment in responses_threats:
        if platform not in platform_competitors:
            platform_competitors[platform] = {}
        if competitors_str:
            competitors = [c.strip() for c in competitors_str.split(',') if c.strip()]
            for competitor in competitors:
                if competitor not in platform_competitors[platform]:
                    platform_competitors[platform][competitor] = {'count': 0, 'negative_overlap': 0}
                platform_competitors[platform][competitor]['count'] += 1
                if sentiment in ['Negative', 'Very Negative']:
                    platform_competitors[platform][competitor]['negative_overlap'] += 1

    for platform, competitors in platform_competitors.items():
        top_competitors = sorted(
            competitors.items(),
            key=lambda x: (x[1]['count'], x[1]['negative_overlap']),
            reverse=True
        )[:5]
        llm_data['threats'].append({
            'platform': platform,
            'competitors': [
                {'name': name, 'mentions': data['count'], 'negative_overlap': data['negative_overlap']}
                for name, data in top_competitors
            ],
            'total_competitor_mentions': sum(c['count'] for c in competitors.values())
        })

    return llm_data


# ==================== METRIC CALCULATIONS ====================
# All metric calculation functions have been moved to app/services/metrics.py
# for single source of truth across dashboard, analytics pages, and reports.
# Import functions from metrics module (see imports at top of file).


# ==================== CONTEXT BUILDERS FOR ENHANCED PROMPTS ====================

def build_brand_context(brand_info: Optional[BrandInfo], brand_name: str) -> str:
    """Build rich brand context string for prompts."""
    if not brand_info:
        return f"Brand Name: {brand_name}"

    context = f"Brand Name: {brand_name}\n"
    if brand_info.industry:
        context += f"Industry: {brand_info.industry}\n"
    if brand_info.description:
        context += f"Description: {brand_info.description}\n"
    if brand_info.strategic_messages:
        context += f"Strategic Messages: {brand_info.strategic_messages}\n"
    if brand_info.website_url:
        context += f"Website: {brand_info.website_url}\n"

    return context.strip()


def build_competitor_context(competitors: List[Competitor]) -> str:
    """Build detailed competitor context for prompts."""
    if not competitors:
        return "No competitors configured."

    context = ""
    for comp in competitors:
        context += f"\n- {comp.organization}"
        if comp.type:
            context += f" (Type: {comp.type})"
        if comp.focus_area:
            context += f"\n  Focus Area: {comp.focus_area}"
        if comp.key_descriptors:
            context += f"\n  Key Descriptors: {comp.key_descriptors}"
        if comp.notes:
            context += f"\n  Notes: {comp.notes}"
        context += "\n"

    return context.strip()


def build_descriptor_context(descriptors: List[TargetDescriptor], descriptor_analysis: Dict[str, int]) -> str:
    """Build detailed descriptor context showing targets vs actual performance."""
    if not descriptors:
        return "No target descriptors configured."

    context = ""
    for desc in descriptors:
        actual_count = descriptor_analysis.get(desc.descriptor, 0)
        context += f"\n- '{desc.descriptor}'"
        if desc.priority:
            context += f" [Priority: {desc.priority}]"
        context += f"\n  Times associated with brand: {actual_count}"
        if desc.current_ownership:
            context += f"\n  Current owner: {desc.current_ownership}"
        if desc.notes:
            context += f"\n  Strategic notes: {desc.notes}"
        context += "\n"

    return context.strip()


def get_best_performing_responses(responses: List[Response], limit: int = 5) -> List[Response]:
    """Get responses where brand performed best (Leader position, positive sentiment)."""
    best_responses = [
        r for r in responses
        if r.brand_mentioned == "Yes"
        and r.brand_position in ["Leader", "Top 3"]
        and r.sentiment in ["Positive", "Very Positive"]
    ]

    # Sort by position (Leader first) then by sentiment
    position_rank = {"Leader": 0, "Top 3": 1}
    sentiment_rank = {"Very Positive": 0, "Positive": 1}

    best_responses.sort(
        key=lambda r: (position_rank.get(r.brand_position, 10), sentiment_rank.get(r.sentiment, 10))
    )

    return best_responses[:limit]


def get_worst_performing_responses(responses: List[Response], limit: int = 5) -> List[Response]:
    """Get responses where brand performed worst (not mentioned, competitors mentioned instead)."""
    worst_responses = [
        r for r in responses
        if r.brand_mentioned == "No"
        and r.competitors  # Competitors were mentioned instead
    ]

    return worst_responses[:limit]


def get_competitive_loss_examples(responses: List[Response], limit: int = 5) -> List[Response]:
    """Get examples where brand and competitors both mentioned, but competitors positioned better."""
    competitive_losses = [
        r for r in responses
        if r.brand_mentioned in ["Yes", "Indirect"]
        and r.competitors
        and r.brand_position in ["Listed", "Featured", "Not Mentioned"]  # Not leader
    ]

    return competitive_losses[:limit]


def build_response_examples_context(
    best: List[Response],
    worst: List[Response],
    competitive_losses: List[Response],
    brand_name: str
) -> str:
    """Build formatted response examples for prompts."""
    context = ""

    # Best performing examples
    if best:
        context += "\n=== BEST PERFORMING RESPONSES ===\n"
        for i, resp in enumerate(best[:3], 1):
            context += f"\nExample {i}:\n"
            context += f"Query: \"{resp.query_text}\"\n"
            context += f"Platform: {resp.platform}\n"
            context += f"Position: {resp.brand_position}\n"
            context += f"Sentiment: {resp.sentiment}\n"
            if resp.descriptors:
                context += f"Descriptors: {resp.descriptors}\n"
            # Truncate response text
            excerpt = resp.response_text[:400] + "..." if len(resp.response_text) > 400 else resp.response_text
            context += f"Response excerpt: \"{excerpt}\"\n"

    # Worst performing examples
    if worst:
        context += "\n\n=== WORST PERFORMING RESPONSES (Brand Not Mentioned) ===\n"
        for i, resp in enumerate(worst[:3], 1):
            context += f"\nExample {i}:\n"
            context += f"Query: \"{resp.query_text}\"\n"
            context += f"Platform: {resp.platform}\n"
            context += f"Competitors mentioned instead: {resp.competitors}\n"
            excerpt = resp.response_text[:400] + "..." if len(resp.response_text) > 400 else resp.response_text
            context += f"Response excerpt: \"{excerpt}\"\n"

    # Competitive loss examples
    if competitive_losses:
        context += "\n\n=== COMPETITIVE CHALLENGES (Brand + Competitors Mentioned) ===\n"
        for i, resp in enumerate(competitive_losses[:3], 1):
            context += f"\nExample {i}:\n"
            context += f"Query: \"{resp.query_text}\"\n"
            context += f"Platform: {resp.platform}\n"
            context += f"{brand_name} Position: {resp.brand_position}\n"
            context += f"Competitors also mentioned: {resp.competitors}\n"
            excerpt = resp.response_text[:400] + "..." if len(resp.response_text) > 400 else resp.response_text
            context += f"Response excerpt: \"{excerpt}\"\n"

    return context.strip()


def build_platform_performance_context(platform_metrics: Dict[str, Dict[str, Any]]) -> str:
    """Build platform-by-platform performance summary."""
    context = ""
    for platform, metrics in platform_metrics.items():
        if metrics['total'] > 0:
            context += f"\n{platform} (n={metrics['total']}):\n"
            context += f"  - Mention Rate: {metrics['mention']['yes_pct']}%\n"
            context += f"  - Positive Sentiment: {metrics['sentiment']['positive_pct'] + metrics['sentiment']['very_positive_pct']}%\n"
            context += f"  - Leader/Featured: {metrics['positioning']['leader_pct'] + metrics['positioning']['featured_pct']}%\n"

    return context.strip()


# ==================== AI-POWERED ANALYSIS ====================

def generate_competitor_threat_analysis(
    top_threats: List[Dict[str, Any]],
    competitor_sov: Dict[str, Dict[str, Any]],
    responses: List[Response],
    competitors_list: List[Competitor],
    brand_name: str,
    brand_context_str: str,
    competitor_context: str,
    worst_responses: List[Response],
    competitive_losses: List[Response],
    provider: Optional[ProviderConfig] = None
) -> str:
    """
    Generate enhanced competitor threat analysis.
    Focuses on the top 3 threats as calculated by calculate_competitor_threats().
    Uses the configured LLM provider (analysis_provider).
    """

    # Prepare SOV data for top 3 threats
    sov_summary = f"{brand_name}: {competitor_sov.get('brand_sov', 0)}%\n"
    for threat in top_threats[:3]:
        sov_summary += f"{threat['name']}: {threat['share_of_voice']}% ({threat['mention_count']} mentions, Threat Score: {threat['threat_score']} - {threat['threat_level']})\n"

    # Build examples of competitive losses - filter to focus on top 3 threats
    top_threat_names = [threat['name'].lower() for threat in top_threats[:3]]

    # Filter worst_responses to only include top 3 threats
    relevant_worst = [
        r for r in worst_responses
        if r.competitors and any(threat_name in r.competitors.lower() for threat_name in top_threat_names)
    ][:5]

    # Filter competitive_losses to only include top 3 threats
    relevant_losses = [
        r for r in competitive_losses
        if r.competitors and any(threat_name in r.competitors.lower() for threat_name in top_threat_names)
    ][:5]

    competitive_examples = ""
    for i, resp in enumerate(relevant_worst, 1):
        competitive_examples += f"\nExample {i} - Brand Absent, Competitors Mentioned:\n"
        competitive_examples += f"Query: \"{resp.query_text}\"\n"
        competitive_examples += f"Platform: {resp.platform}\n"
        competitive_examples += f"Competitors mentioned: {resp.competitors}\n"
        excerpt = resp.response_text[:350] + "..." if len(resp.response_text) > 350 else resp.response_text
        competitive_examples += f"Response: \"{excerpt}\"\n"

    offset = len(relevant_worst)
    for i, resp in enumerate(relevant_losses, 1):
        competitive_examples += f"\nExample {offset+i} - Head-to-Head Loss:\n"
        competitive_examples += f"Query: \"{resp.query_text}\"\n"
        competitive_examples += f"Platform: {resp.platform}\n"
        competitive_examples += f"{brand_name} position: {resp.brand_position}\n"
        competitive_examples += f"Competitors also mentioned: {resp.competitors}\n"
        excerpt = resp.response_text[:350] + "..." if len(resp.response_text) > 350 else resp.response_text
        competitive_examples += f"Response: \"{excerpt}\"\n"

    # Get names of top 3 threats for the prompt
    top_3_names = [threat['name'] for threat in top_threats[:3]]

    prompt = f"""You are a competitive intelligence analyst for {brand_name}.

{brand_context_str}

YOUR COMPETITORS (with strategic context):
{competitor_context}

TOP 3 COMPETITIVE THREATS (based on quantitative threat analysis):
The following competitors have been identified as the top 3 threats based on their mention frequency, share of voice, and sentiment patterns:

1. {top_3_names[0] if len(top_3_names) > 0 else 'N/A'}
2. {top_3_names[1] if len(top_3_names) > 1 else 'N/A'}
3. {top_3_names[2] if len(top_3_names) > 2 else 'N/A'}

SHARE OF VOICE PERFORMANCE:
{sov_summary}

ACTUAL COMPETITIVE EXAMPLES FROM AI RESPONSES:
{competitive_examples}

Based on this detailed competitive intelligence, analyze each of the THREE identified competitive threats to {brand_name} listed above.

For each threat, provide:

### [Competitor Name]: [Specific Threat Title]

**Threat Analysis** (3-4 sentences with CONCRETE EXAMPLES from the data above)
- What specific queries are they winning?
- What descriptors or positioning are they owning?
- Quote or reference specific AI responses showing their advantage
- Explain why this matters strategically

**Strategic Implications** (2 sentences on why this threatens {brand_name}'s goals)

**Recommended Actions** (4-5 SPECIFIC, tactical recommendations)
- Each action must reference specific platforms, query types, descriptors, or positioning strategies
- Include measurable targets (e.g., "Increase mentions in X category by Y%")
- Be tactical and immediately actionable

Format your response using **bold headers** for each threat (not ### headings). Use bullet points for sub-items.
Be ruthlessly specific. Use actual data and examples. No generic advice like "improve visibility" - every recommendation must be tailored to the specific competitive threat shown in the data.
Do NOT use emojis or icons.
Do NOT use numbered lists (1., 2., 3.).
Do NOT use ### headings or multiple pound signs as decorative elements."""

    return call_report_llm(prompt, provider)


def generate_strategic_priorities(
    metrics_summary: Dict[str, Any],
    brand_name: str,
    brand_info: Optional[BrandInfo],
    brand_context_str: str,
    descriptor_context: str,
    competitor_context: str,
    platform_performance: str,
    best_responses: List[Response],
    worst_responses: List[Response],
    llm_state_data: Dict[str, Any] = None,
    provider: Optional[ProviderConfig] = None,
    web_search_providers: List[ProviderConfig] = None
) -> str:
    """Generate enhanced strategic priorities with rich context.
    Uses the configured LLM provider (analysis_provider).
    """

    # Build strengths and weaknesses from actual responses
    strengths = ""
    for i, resp in enumerate(best_responses[:3], 1):
        strengths += f"\n{i}. Query: \"{resp.query_text}\" ({resp.platform})\n"
        strengths += f"   Position: {resp.brand_position}, Sentiment: {resp.sentiment}\n"
        if resp.descriptors:
            strengths += f"   Descriptors: {resp.descriptors}\n"

    weaknesses = ""
    for i, resp in enumerate(worst_responses[:3], 1):
        weaknesses += f"\n{i}. Query: \"{resp.query_text}\" ({resp.platform})\n"
        weaknesses += f"   Brand mentioned: {resp.brand_mentioned}\n"
        if resp.competitors:
            weaknesses += f"   Competitors mentioned instead: {resp.competitors}\n"

    # Fetch recent industry news AND AI citation trends using Gemini
    industry = brand_info.industry if brand_info and brand_info.industry else "the industry"

    # Query 1: Recent industry news
    news_query = f"Recent news and developments in {industry} in the last 30 days, particularly related to {brand_name} or its competitors"

    # Query 2: AI citation trends and source preferences
    citation_query = f"""Research the latest trends (2025-2026) about what sources and publications AI platforms (ChatGPT, Claude, Gemini, Perplexity) are reading and citing when answering questions about {industry}.

Consider:
- What types of publications are LLMs prioritizing? (Academic journals, news outlets, industry blogs, government sites, Reddit discussions, etc.)
- What sources have high authority and visibility in AI training data and retrieval systems?
- What recent media trends affect AI visibility? (e.g., Muck Rack data on journalist engagement, publication reach)
- Which content formats get cited most? (Research papers, case studies, press releases, technical documentation)
- Platform-specific preferences (e.g., Perplexity's real-time search vs. ChatGPT's training data cutoff)

Provide specific, actionable insights about WHERE organizations in {industry} should publish content to maximize AI platform visibility."""

    try:
        # Use web search providers for fresh news/trend data if available
        recent_news = call_web_search_llm(news_query, web_search_providers, provider)
        if not recent_news:
            recent_news = "No recent news data available."

        citation_trends = call_web_search_llm(citation_query, web_search_providers, provider)
        if not citation_trends:
            citation_trends = "No citation trend data available."
    except Exception as e:
        print(f"Warning: Could not fetch recent news or citation trends: {e}")
        recent_news = "No recent news data available."
        citation_trends = "No citation trend data available."

    # Build LLM state context if available
    llm_state_context = ""
    if llm_state_data and llm_state_data.get('raw_research'):
        llm_state_context = f"""

RECENT LLM PLATFORM CHANGES:
The following recent changes to AI platform behavior should inform your recommendations:
{llm_state_data['raw_research'][:2000]}

Consider how these changes affect:
- Which content types and sources the brand should prioritize
- How to adapt content strategy for evolving LLM preferences
- Opportunities or risks from platform-specific changes
"""

    prompt = f"""You are a strategic communications consultant analyzing AI-generated responses about a brand.

CRITICAL CONTEXT: This analysis examines how Large Language Models (LLMs like ChatGPT, Claude, Perplexity, Gemini) describe {brand_name} when users ask questions. Brands CANNOT directly publish content to LLMs. Instead, LLMs generate responses based on the authoritative sources they reference.

IMPORTANT: Different LLMs prioritize different source types. Your recommendations must be data-driven and strategic:
- Analyze the PLATFORM-BY-PLATFORM PERFORMANCE data below to identify which LLMs perform well vs. poorly for {brand_name}
- Look at the actual response examples to understand what sources those LLMs are likely citing
- Consider that different LLMs may favor different sources:
  * Academic/research-focused LLMs may prioritize peer-reviewed papers, .edu domains, research institutions
  * Search-augmented LLMs (like Perplexity) may prioritize recent news articles, authoritative websites, Reddit discussions
  * Some may favor Wikipedia, government sources (.gov), or technical documentation
- If {brand_name} performs poorly on a specific platform, diagnose WHY by examining the queries and recommend targeted strategies for the SOURCE TYPES that platform likely values

Your recommendations should be specific about:
1. WHAT content to create (research papers vs. blog posts vs. technical docs vs. media outreach)
2. WHERE to publish it (academic journals, tech blogs, Reddit, news outlets, .gov partnerships, etc.)
3. WHY that approach targets the specific LLMs where {brand_name} underperforms

DO NOT give generic advice like "improve online presence" - every recommendation must be tied to specific patterns in the data

{brand_context_str}

CURRENT PERFORMANCE METRICS:
- Brand Mention Rate: {metrics_summary['mention_metrics']['yes_pct']}%
- Positive Sentiment: {metrics_summary['positive_sentiment_rate']}%
- Share of Voice: {metrics_summary['share_of_voice']['brand_sov']}%
- Positioning Average: {metrics_summary['positioning_average']}/5.0
- Descriptor Match Rate: {metrics_summary['descriptor_match_rate']}%

PLATFORM-BY-PLATFORM PERFORMANCE:
{platform_performance}

TARGET DESCRIPTORS PERFORMANCE:
{descriptor_context}

COMPETITIVE LANDSCAPE:
{competitor_context}

KEY STRENGTHS (Queries where {brand_name} excels):
{strengths}

KEY WEAKNESSES (Queries where {brand_name} is absent):
{weaknesses}

RECENT INDUSTRY NEWS & DEVELOPMENTS (Last 30 Days):
{recent_news}

AI CITATION TRENDS & SOURCE PREFERENCES (2025-2026):
{citation_trends}
{llm_state_context}
Based on this comprehensive analysis, generate EXACTLY FIVE strategic priorities for {brand_name}.

IMPORTANT: Your recommendations MUST be informed by current AI citation trends and source preferences:
- Reference the specific publication types and sources that LLMs are prioritizing (from the citation trends data above)
- Recommend WHERE to publish based on which sources have demonstrated high AI visibility
- Consider platform-specific source preferences when making recommendations
- Use data from Muck Rack and media intelligence sources when available to inform publication strategy
- Prioritize content formats and channels that are proven to get cited by AI platforms

IMPORTANT: Consider how recent industry news creates opportunities or threats:
- If there's a major development, breakthrough, or trend in the industry, recommend how {brand_name} can position itself in relation to it
- If competitors made news, identify opportunities to counter-program or claim related positioning
- If there are emerging topics or conversations, recommend getting ahead of them with authoritative content
- Consider whether recent events change the urgency or approach for any communications goals

CRITICAL: Your priorities must focus on achieving {brand_name}'s strategic messaging goals:
- Identify TARGET DESCRIPTORS that are underperforming (low match rate, absent from responses, or competitors own them)
- Recommend specific content strategies to associate {brand_name} with those missing descriptors
- If a descriptor appears frequently for competitors but not {brand_name}, explain how to claim that positioning
- Address platform-specific weaknesses with targeted source strategies for those LLMs
- Connect every recommendation back to increasing the presence of specific target descriptors in AI responses

For each priority:

**[Priority Number]. [Priority Title]** (6-10 words, specific to {brand_name}'s situation)

**Strategic Rationale** (3-4 sentences explaining WHY this matters based on SPECIFIC DATA from above)
- Reference actual metrics, query examples, competitors, or platform performance
- MUST identify which target descriptor(s) this addresses and current vs. desired state
- Connect to the brand's strategic messages and positioning goals
- Explain the opportunity cost of not acting

**Key Actions** (4-5 SPECIFIC, measurable actions)
- Each action must specify which target descriptor(s) to emphasize
- Include target metrics (e.g., "Increase 'innovative' descriptor association from 12% to 35% by creating...")
- Specify WHAT content to create, WHERE to publish it (using insights from AI citation trends), and HOW it reinforces target descriptors
- Reference specific platforms, query categories, competitors, or source types that LLMs prioritize
- Explicitly cite which publication types/sources from the citation trends data you're recommending (e.g., "Publish in [specific journal type] because Gemini prioritizes academic sources")
- Be tactical and immediately actionable

Format using bullet points (- ) for each recommendation, with bold headers for each main point.
Be data-driven and specific. No generic advice like "improve SEO" or "create more content" - every recommendation must be tailored to {brand_name}'s specific situation shown in the data above.
Do NOT use emojis or icons.
Do NOT use numbered lists (1., 2., 3.).
Do NOT use multiple pound signs (###) or asterisks (***) as decorative elements or dividers.

IMPORTANT - Citations: DO NOT include any citations, references, or external sources. Base all analysis solely on the data provided above. Do NOT add a "References" section at the end."""

    return call_report_llm(prompt, provider)


def research_llm_state_changes(
    report_type: str = 'monthly',
    web_search_providers: List[ProviderConfig] = None,
    analysis_provider: Optional[ProviderConfig] = None
) -> Dict[str, Any]:
    """
    Research recent changes to how LLMs source and prioritize information.
    Uses configurable web search providers or falls back to env vars.

    Args:
        report_type: 'monthly', 'quarterly', or 'annual' - determines research window
        web_search_providers: List of providers that support web search
        analysis_provider: Provider to use for analysis/synthesis

    Returns:
        dict with:
        - bullets: List of bullet points (or empty if no changes)
        - has_changes: bool
        - platform_notes: Dict of any platform-specific issues/refusals
        - raw_research: Full research text for use in other prompts
        - trend_analysis: (quarterly/annual only) Analysis of trends over the period
    """
    results = {
        'has_changes': False,
        'bullets': [],
        'platform_notes': {},
        'raw_research': '',
        'trend_analysis': ''
    }

    # Determine research window based on report type
    if report_type == 'quarterly':
        time_window = "90 days"
        period_desc = "this quarter"
    elif report_type == 'annual':
        time_window = "12 months"
        period_desc = "this year"
    else:
        time_window = "30 days"
        period_desc = "the last month"

    # Build research query (combined for efficiency)
    research_query = f"""Search for and summarize recent changes (in the last {time_window}) to how AI platforms ChatGPT, Claude, Gemini, and Perplexity operate. Focus on:

1. INFORMATION SOURCING CHANGES:
- What sources they cite or reference
- Integration with search engines or real-time data
- Changes to their knowledge cutoff dates
- New partnerships with content providers or publishers

2. ANSWER PRIORITIZATION CHANGES:
- How they rank or prioritize information in responses
- Changes to citation or source attribution
- Updates to their response formatting or structure
- New features affecting how they present competitive comparisons

Focus on official announcements, blog posts, and documented changes from these companies. Do not speculate."""

    # === WEB SEARCH FOR FRESH DATA ===
    # Requires a configured provider with supports_web_search=True (Gemini or
    # Perplexity). If none is configured, the section is omitted from the report.
    print("    - Researching LLM platform changes...")
    web_research = call_web_search_llm(research_query, web_search_providers, analysis_provider)

    if not web_research:
        print(f"    - No web-search-capable provider available; skipping State of the LLMs section")
        results['platform_notes']['Status'] = "Skipped - no web search provider configured"
        return results

    results['raw_research'] = web_research
    print("    - Research completed successfully")

    # For quarterly/annual reports, add trend analysis (also uses multi-LLM fallback)
    if report_type in ['quarterly', 'annual']:
        print("    - Analyzing LLM platform trends...")
        if report_type == 'quarterly':
            trend_query = """Search for information about how ChatGPT, Claude, Gemini, and Perplexity have evolved over the last 90 days:
- Have they shifted which sources they prioritize?
- Have response patterns or citation styles changed?
- Any notable differences in how they handle brand-related queries?

Identify directional trends, not just individual announcements."""
        else:
            trend_query = """Search for information about the major changes to AI platforms (ChatGPT, Claude, Gemini, Perplexity) over the past year:
1. How have they changed what information to include in responses?
2. How have they changed ranking and prioritizing sources?
3. How have they changed handling queries about brands and products?

What patterns emerged? What should brands expect going forward?"""

        # Use web search for trend analysis
        trend_result = call_web_search_llm(trend_query, web_search_providers, analysis_provider)
        if trend_result:
            results['trend_analysis'] = trend_result
        else:
            print(f"    - Trend analysis skipped (APIs unavailable)")

    # Process research into bullet points using Gemini
    print("    - Processing research into bullet points...")
    try:
        synthesis_prompt = f"""Based on the following research about recent LLM platform changes, create 3-15 bullet points summarizing notable changes.

Focus on:
1. Changes to information sourcing (what sources LLMs prefer/cite)
2. Changes to answer prioritization (how LLMs decide what to show)

If no significant changes are found, respond with exactly:
NO_NOTABLE_CHANGES

Research:
{web_research}

Format each bullet as a complete sentence starting with the platform name or "All platforms".
Example: "- ChatGPT now prioritizes academic sources over news articles."

Do not add explanatory text before or after the bullets. Just provide the bullet list or NO_NOTABLE_CHANGES."""

        bullets_text = call_report_llm(synthesis_prompt, analysis_provider).strip()

        if bullets_text == "NO_NOTABLE_CHANGES" or "no notable changes" in bullets_text.lower():
            results['has_changes'] = False
            results['bullets'] = []
        else:
            # Parse bullets from the response
            bullets = []
            for line in bullets_text.split('\n'):
                line = line.strip()
                if line.startswith('-') or line.startswith('•'):
                    bullets.append(line)
                elif line and not line.startswith('#'):
                    # Include lines that look like bullet content
                    if any(platform in line for platform in ['ChatGPT', 'Claude', 'Gemini', 'Perplexity', 'All platforms']):
                        bullets.append(f"- {line}")

            if bullets:
                results['has_changes'] = True
                results['bullets'] = bullets[:15]  # Cap at 15 bullets
            else:
                results['has_changes'] = False
                results['bullets'] = []

    except Exception as e:
        error_str = str(e)
        if '429' in error_str or 'quota' in error_str.lower():
            print(f"    - Bullet synthesis skipped (rate limited)")
            results['platform_notes']['Status'] = "Skipped due to API rate limits"
        else:
            print(f"    - Warning: Bullet synthesis failed: {e}")
            results['platform_notes']['Status'] = "Skipped due to processing error"

    return results


def get_llm_state_header(report_type: str) -> str:
    """Get the appropriate header for the State of the LLMs section based on report type."""
    if report_type == 'quarterly':
        return "**LLM platform changes this quarter:**\n\n"
    elif report_type == 'annual':
        return "**Year in review: How AI platforms evolved:**\n\n"
    else:
        return "**Recent changes affecting AI reputation management:**\n\n"


def generate_executive_summary(
    metrics_summary: Dict[str, Any],
    brand_name: str,
    brand_info: Optional[BrandInfo],
    total_responses: int,
    brand_context_str: str,
    platform_performance: str,
    response_examples: str,
    descriptor_context: str,
    competitor_context: str,
    report_type: str = 'monthly',
    historical_summary: Dict[str, Any] = None,
    period_name: str = None,
    provider: Optional[ProviderConfig] = None,
    trend_summary: str = ""
) -> str:
    """Generate an enhanced executive summary with rich context.
    Uses the configured LLM provider (analysis_provider).
    """

    # Build period context based on report type
    if report_type == 'monthly':
        month_label = period_name if period_name else "the last calendar month"
        period_context = f"This analysis covers {month_label} data collection."
        if historical_summary:
            historical_context = f"""
HISTORICAL COMPARISON (for context):
- All-time average mention rate: {historical_summary['avg_mention_rate']}%
- All-time average positive sentiment: {historical_summary['avg_positive_rate']}%
- Total data collection batches: {historical_summary['total_batches']}
- Data collection period: {historical_summary['date_range_days']} days
"""
        else:
            historical_context = ""
        analysis_focus = """
Focus your analysis on:
- Current month's performance and what's driving the numbers
- How this month compares to historical averages (better, worse, or stable)
- Week-to-week trends within this month
- Immediate actionable insights for the coming month"""

    elif report_type == 'quarterly':
        period_context = f"This analysis covers {period_name if period_name else 'the last calendar quarter'}."
        historical_context = ""
        analysis_focus = """
Focus your analysis on:
- Quarter's overall performance relative to prior periods
- Month-to-month trends within this quarter
- Seasonal patterns or notable shifts
- Strategic recommendations for the coming quarter"""

    elif report_type == 'annual':
        period_context = f"This comprehensive annual analysis covers {period_name if period_name else 'the last calendar year'}."
        historical_context = ""
        analysis_focus = """
Focus your analysis on:
- Year-over-year performance and growth
- Quarter-to-quarter trends within the year
- Long-term strategic positioning
- Strategic priorities for the coming year"""

    else:
        period_context = "This comprehensive analysis covers ALL historical data to date."
        historical_context = ""
        analysis_focus = """
Focus your analysis on:
- Long-term performance patterns and trends
- Overall strategic positioning across time
- Cumulative strengths and persistent challenges
- Strategic recommendations for sustained improvement"""

    # Add trend data if available
    trend_context = ""
    if trend_summary:
        trend_context = f"""

PERIOD TREND BREAKDOWN:
{trend_summary}
"""

    prompt = f"""You are a strategic communications analyst writing an executive summary for a major client.

{brand_context_str}

{period_context}

CURRENT PERIOD PERFORMANCE METRICS:
- Total Responses Analyzed: {total_responses}
- Brand Mention Rate: {metrics_summary['mention_metrics']['yes_pct']}% (explicit mentions)
- Positive Sentiment Rate: {metrics_summary['positive_sentiment_rate']}%
- Share of Voice: {metrics_summary['share_of_voice']['brand_sov']}%
- Average Positioning Score: {metrics_summary['positioning_average']} out of 5.0
- Target Descriptor Match Rate: {metrics_summary['descriptor_match_rate']}%
{historical_context}{trend_context}

PLATFORM-BY-PLATFORM PERFORMANCE:
{platform_performance}

TARGET DESCRIPTORS PERFORMANCE:
{descriptor_context}

COMPETITIVE LANDSCAPE:
{competitor_context}

{response_examples}

Based on this comprehensive analysis, write a 4-6 sentence executive summary that:
- Assesses {brand_name}'s overall AI reputation performance with SPECIFIC EVIDENCE from the data
- Identifies the MOST SIGNIFICANT finding - be specific about which queries/platforms/contexts
- Compares performance against the brand's stated strategic messages and goals
- Provides strategic context about competitive positioning with concrete examples
- Highlights ONE concrete opportunity and ONE concrete risk based on actual response data
{analysis_focus}

Be specific, cite examples from the data above, and focus on actionable insights NOT generic observations.
Write in a professional, analytical tone.
Do NOT use emojis or icons.
Do NOT use numbered lists (1., 2., 3.) or bullet points in your output - write flowing sentences.
Do NOT use phrases like "This report" or "This analysis" - write directly about the findings.
Do NOT use multiple pound signs (###) or asterisks (***) as decorative elements or dividers."""

    return call_report_llm(prompt, provider)


def generate_positioning_insights(
    positioning_metrics: Dict[str, Any],
    positioning_average: float,
    platform_metrics: Dict[str, Dict[str, Any]],
    brand_name: str,
    provider: Optional[ProviderConfig] = None
) -> str:
    """Generate AI-powered insights about brand positioning.
    Uses the configured LLM provider (analysis_provider).
    """

    prompt = f"""You are analyzing brand positioning performance for {brand_name} in AI platform responses.

POSITIONING DATA:
- Leader: {positioning_metrics['leader']} responses ({positioning_metrics['leader_pct']}%)
- Featured: {positioning_metrics['featured']} responses ({positioning_metrics['featured_pct']}%)
- Listed: {positioning_metrics['listed']} responses ({positioning_metrics['listed_pct']}%)
- Not Mentioned: {positioning_metrics['not_mentioned']} responses ({positioning_metrics['not_mentioned_pct']}%)
- Average Positioning Score: {positioning_average} out of 5.0

PLATFORM BREAKDOWN:
{chr(10).join([f"- {platform}: Leader/Featured = {metrics['positioning']['leader_pct'] + metrics['positioning']['featured_pct']}%" for platform, metrics in platform_metrics.items() if metrics['total'] > 0])}

Write 3-10 sentences analyzing {brand_name}'s positioning performance. Address these topics:
- Overall positioning strength (is the brand typically leading, featured, or just listed?)
- Which positioning tiers are most common and what that means
- Platform-specific patterns (which platforms position the brand better/worse)
- The significance of the positioning average score
- Key opportunities or concerns based on this data

Be specific and data-driven. Write in a professional, analytical tone.
Do NOT use emojis or icons.
Do NOT use numbered lists (1., 2., 3.) in your output.
Do NOT use multiple pound signs or asterisks as decorative elements."""

    return call_report_llm(prompt, provider)


def generate_share_of_voice_insights(
    share_of_voice: Dict[str, Any],
    brand_name: str,
    competitor_analysis: Dict[str, int],
    provider: Optional[ProviderConfig] = None
) -> str:
    """Generate AI-powered insights about share of voice.
    Uses the configured LLM provider (analysis_provider).
    """

    top_competitors = sorted(competitor_analysis.items(), key=lambda x: x[1], reverse=True)[:5]
    competitor_summary = "\n".join([f"- {comp}: {count} mentions" for comp, count in top_competitors])

    prompt = f"""You are analyzing share of voice performance for {brand_name} in AI platform responses.

SHARE OF VOICE DATA:
- {brand_name} Share of Voice: {share_of_voice['brand_sov']}%
- {brand_name} Mentions: {share_of_voice['brand_mentions']}
- Total Organization Mentions: {share_of_voice['total_mentions']}

TOP COMPETITORS MENTIONED:
{competitor_summary}

Write 3-10 sentences analyzing {brand_name}'s share of voice. Address these topics:
- Is the brand's SOV strong, moderate, or weak compared to the competitive landscape?
- How does the brand compare to its top competitors?
- What does this SOV tell us about brand awareness and visibility?
- Are there concerning gaps where competitors dominate?
- The strategic implications of this SOV positioning

Be specific and data-driven. Write in a professional, analytical tone.
Do NOT use emojis or icons.
Do NOT use numbered lists (1., 2., 3.) in your output.
Do NOT use multiple pound signs or asterisks as decorative elements."""

    return call_report_llm(prompt, provider)


def generate_descriptor_insights(
    descriptor_analysis: Dict[str, int],
    descriptor_match_rate: float,
    brand_name: str,
    target_descriptors: List[TargetDescriptor],
    provider: Optional[ProviderConfig] = None
) -> str:
    """Generate AI-powered insights about descriptor performance.
    Uses the configured LLM provider (analysis_provider).
    """

    top_descriptors = sorted(descriptor_analysis.items(), key=lambda x: x[1], reverse=True)[:10]
    descriptor_summary = "\n".join([f"- '{desc}': {count} mentions" for desc, count in top_descriptors])

    target_desc_list = [d.descriptor for d in target_descriptors] if target_descriptors else []
    target_summary = ", ".join([f"'{d}'" for d in target_desc_list[:10]]) if target_desc_list else "None configured"

    prompt = f"""You are analyzing descriptor association performance for {brand_name} in AI platform responses.

DESCRIPTOR PERFORMANCE:
- Overall Match Rate: {descriptor_match_rate}% of brand mentions included at least one target descriptor

TOP DESCRIPTORS ASSOCIATED WITH {brand_name}:
{descriptor_summary}

TARGET DESCRIPTORS (what we want to be associated with):
{target_summary}

Write 3-10 sentences analyzing {brand_name}'s descriptor performance. Address these topics:
- Is the descriptor match rate strong? Are we successfully associated with key terms?
- Which descriptors are performing well (mentioned frequently)?
- Are there gaps between target descriptors and actual associations?
- What does this tell us about how AI platforms characterize the brand?
- Strategic opportunities to strengthen descriptor associations

Be specific and data-driven. Write in a professional, analytical tone.
Do NOT use emojis or icons.
Do NOT use numbered lists (1., 2., 3.) in your output.
Do NOT use multiple pound signs or asterisks as decorative elements."""

    return call_report_llm(prompt, provider)


def generate_sentiment_insights(
    sentiment_metrics: Dict[str, Any],
    positive_sentiment_rate: float,
    negative_statements: List[Dict[str, str]],
    brand_name: str,
    platform_metrics: Dict[str, Dict[str, Any]],
    provider: Optional[ProviderConfig] = None
) -> str:
    """Generate AI-powered insights about sentiment distribution.
    Uses the configured LLM provider (analysis_provider).
    """

    prompt = f"""You are analyzing sentiment performance for {brand_name} in AI platform responses.

SENTIMENT DATA:
- Very Positive: {sentiment_metrics['very_positive']} ({sentiment_metrics['very_positive_pct']}%)
- Positive: {sentiment_metrics['positive']} ({sentiment_metrics['positive_pct']}%)
- Neutral: {sentiment_metrics['neutral']} ({sentiment_metrics['neutral_pct']}%)
- Negative: {sentiment_metrics['negative']} ({sentiment_metrics['negative_pct']}%)
- Mixed: {sentiment_metrics['mixed']} ({sentiment_metrics['mixed_pct']}%)
- Combined Positive Rate: {positive_sentiment_rate}%

PLATFORM SENTIMENT BREAKDOWN:
{chr(10).join([f"- {platform}: {metrics['sentiment']['positive_pct'] + metrics['sentiment']['very_positive_pct']}% positive" for platform, metrics in platform_metrics.items() if metrics['total'] > 0])}

NUMBER OF NEGATIVE/MIXED EXAMPLES: {len(negative_statements)}

Write 3-10 sentences analyzing {brand_name}'s sentiment performance. Address these topics:
- Overall sentiment health - is it predominantly positive, neutral, or concerning?
- The balance between very positive, positive, and neutral responses
- Any negative or mixed sentiment patterns that need attention
- Platform-specific sentiment differences
- What this sentiment profile reveals about brand perception

Be specific and data-driven. Write in a professional, analytical tone.
Do NOT use emojis or icons.
Do NOT use numbered lists (1., 2., 3.) in your output.
Do NOT use multiple pound signs or asterisks as decorative elements.
Do NOT include any additional sections, headers, tables, or lists of AI statements.
Do NOT include an appendix section.
Do NOT list individual AI responses or statements.
ONLY provide the paragraph analysis - nothing else after your analysis."""

    return call_report_llm(prompt, provider)


# ==================== REPORT GENERATION ====================

def embed_chart_as_base64(chart_path: str) -> str:
    """Convert a chart image to base64 for embedding in Markdown."""
    import base64
    try:
        with open(chart_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
            return f"data:image/png;base64,{encoded}"
    except Exception as e:
        print(f"Warning: Could not embed chart {chart_path}: {e}")
        return ""


def generate_markdown_report(
    mention_metrics: Dict[str, Any],
    positioning_metrics: Dict[str, Any],
    sentiment_metrics: Dict[str, Any],
    platform_metrics: Dict[str, Dict[str, Any]],
    descriptor_analysis: Dict[str, int],
    competitor_analysis: Dict[str, int],
    positive_sentiment_rate: float,
    descriptor_match_rate: float,
    share_of_voice: Dict[str, Any],
    positioning_average: float,
    negative_statements: List[Dict[str, str]],
    competitor_threats: str,
    strategic_priorities: str,
    executive_summary: str,
    brand_name: str,
    brand_info: Optional[BrandInfo],
    report_date: str,
    period: str,
    responses: List[Any] = None,
    chart_paths: Dict[str, str] = None,
    positioning_insights: str = "",
    sov_insights: str = "",
    descriptor_insights: str = "",
    sentiment_insights: str = "",
    queries: List[Any] = None,
    descriptors: List[Any] = None,
    competitors: List[Any] = None,
    competitor_threats_data: List[Dict[str, Any]] = None,
    llm_breakdown_data: Dict[str, Any] = None,
    report_type: str = 'monthly',
    historical_summary: Dict[str, Any] = None,
    llm_state_data: Dict[str, Any] = None,
) -> str:
    """Generate a complete markdown report with embedded charts and insights."""

    # Build report title based on type
    if report_type == 'monthly':
        report_title = f"# {brand_name} - Monthly AI Reputation Analysis"
        period_note = f"**Analysis Period:** {period} | **Generated:** {report_date}"
    else:
        report_title = f"# {brand_name} - Comprehensive AI Reputation Analysis"
        period_note = f"**Analysis Period:** All Data to Date | **Generated:** {report_date}"

    # Add historical context note for monthly reports
    historical_context_note = ""
    if report_type == 'monthly' and historical_summary:
        historical_context_note = f"""
> **Historical Context:** This monthly report analyzes {period} data. For comparison, your all-time average mention rate is {historical_summary['avg_mention_rate']}% across {historical_summary['total_batches']} data collection batches spanning {historical_summary['date_range_days']} days.
"""

    report = f"""{report_title}

{period_note}
{historical_context_note}

## Executive Summary

{executive_summary}

---

"""

    # === STATE OF THE LLMS SECTION ===
    # Skip section entirely if research was rate-limited or unavailable
    if llm_state_data and not llm_state_data.get('platform_notes', {}).get('Status', '').startswith('Skipped'):
        report += "\n## State of the LLMs\n\n"
        if llm_state_data.get('has_changes') and llm_state_data.get('bullets'):
            report += get_llm_state_header(report_type)
            for bullet in llm_state_data['bullets']:
                report += f"{bullet}\n"

            # Add trend analysis for quarterly/annual reports
            if report_type in ['quarterly', 'annual'] and llm_state_data.get('trend_analysis'):
                report += "\n### Emerging Trends\n\n"
                report += llm_state_data['trend_analysis']
                report += "\n"
        else:
            report += "*No notable changes to LLM information sourcing or prioritization since the last reporting period.*\n"

        # Add platform notes if any (filter out internal status notes)
        display_notes = {k: v for k, v in llm_state_data.get('platform_notes', {}).items()
                        if k not in ['Status', 'Search Grounding']}
        if display_notes:
            report += "\n**Platform notes:**\n"
            for platform, note in display_notes.items():
                report += f"- {platform}: {note}\n"

        report += "\n---\n"

    report += f"""
<h2 style="color: #003e60;">Key Metrics Overview</h2>

| Metric | Value |
|--------|-------|
| **Brand Mention Rate** | {mention_metrics['yes_pct']}% |
| **Positive Sentiment Rate** | {positive_sentiment_rate}% |
| **Share of Voice** | {share_of_voice['brand_sov']}% |
| **Average Positioning Score** | {positioning_average}/5.0 |
| **Descriptor Match Rate** | {descriptor_match_rate}% |

"""

    if chart_paths and 'share_of_voice' in chart_paths:
        base64_data = embed_chart_as_base64(chart_paths['share_of_voice'])
        if base64_data:
            report += f'\n<img src="{base64_data}" alt="Share of Voice" style="max-width: 800px; margin: 20px auto;" />\n\n'
        else:
            report += f"\n![Share of Voice]({chart_paths['share_of_voice']})\n\n"

    report += f"""
---

<h2 style="color: #003e60;">Detailed Analysis with Insights</h2>

<h3 style="color: #0066a2;">Positioning Analysis</h3>

| Position | Count | Percentage |
|----------|-------|------------|
| Leader | {positioning_metrics['leader']} | {positioning_metrics['leader_pct']}% |
| Featured | {positioning_metrics['featured']} | {positioning_metrics['featured_pct']}% |
| Listed | {positioning_metrics['listed']} | {positioning_metrics['listed_pct']}% |
| Not Mentioned | {positioning_metrics['not_mentioned']} | {positioning_metrics['not_mentioned_pct']}% |

**Average Positioning Score:** {positioning_average} out of 5.0
"""

    # Add positioning chart (embedded as base64)
    if chart_paths and 'positioning' in chart_paths:
        base64_data = embed_chart_as_base64(chart_paths['positioning'])
        if base64_data:
            report += f'\n<img src="{base64_data}" alt="Positioning Distribution" style="max-width: 800px; margin: 20px auto;" />\n'
        else:
            report += f"\n![Positioning Distribution]({chart_paths['positioning']})\n"

    # Add positioning insights
    report += f"\n**Insights:**\n\n{positioning_insights}\n"

    report += f"""
---

<h3 style="color: #0066a2;">Share of Voice Analysis</h3>

**{brand_name} Share of Voice:** {share_of_voice['brand_sov']}%
**{brand_name} Mentions:** {share_of_voice['brand_mentions']} out of {share_of_voice['total_mentions']} total organization mentions

**Share of Voice Distribution:**

| Organization | Mentions | Share of Voice % |
|-------------|----------|------------------|"""

    # Add competitor breakdown in table format
    if competitor_analysis:
        sorted_competitors = sorted(competitor_analysis.items(), key=lambda x: x[1], reverse=True)
        for competitor, count in sorted_competitors[:10]:  # Top 10
            sov_data = share_of_voice['competitor_sov'].get(competitor, {})
            sov = sov_data.get('sov', 0)
            report += f"\n| {competitor} | {count} | {sov}% |"
    else:
        report += "\n| No data | - | - |"

    # Add share of voice chart (embedded as base64)
    if chart_paths and 'share_of_voice' in chart_paths:
        base64_data = embed_chart_as_base64(chart_paths['share_of_voice'])
        if base64_data:
            report += f'\n\n<img src="{base64_data}" alt="Share of Voice" style="max-width: 800px; margin: 20px auto;" />\n'
        else:
            report += f"\n\n![Share of Voice]({chart_paths['share_of_voice']})\n"

    # Add SOV insights
    report += f"\n**Insights:**\n\n{sov_insights}\n"

    report += f"""
---

<h3 style="color: #0066a2;">Descriptor Analysis</h3>

**Target Descriptor Adoption:** {descriptor_match_rate}% of your target descriptors appeared in AI responses where the brand was directly mentioned

**Top Descriptors Used by AI Platforms When Mentioning {brand_name}:**

*Note: Counts reflect direct brand mentions only (indirect mentions excluded)*
"""

    # Add descriptor breakdown in list format (not table) to avoid truncation of long names
    if descriptor_analysis:
        sorted_descriptors = sorted(descriptor_analysis.items(), key=lambda x: x[1], reverse=True)
        for descriptor, count in sorted_descriptors[:10]:  # Top 10
            report += f"\n- **{descriptor}**: {count} mentions"
    else:
        report += "\n- No data available"

    # Add descriptor performance chart (embedded as base64)
    if chart_paths and 'descriptor_performance' in chart_paths:
        base64_data = embed_chart_as_base64(chart_paths['descriptor_performance'])
        if base64_data:
            report += f'\n\n<img src="{base64_data}" alt="Descriptor Performance" style="max-width: 800px; margin: 20px auto;" />\n'
        else:
            report += f"\n\n![Descriptor Performance]({chart_paths['descriptor_performance']})\n"

    # Add descriptor insights
    report += f"\n**Insights:**\n\n{descriptor_insights}\n"

    report += f"""
---

<h3 style="color: #0066a2;">Sentiment Analysis</h3>

| Sentiment | Count | Percentage |
|-----------|-------|------------|
| Very Positive | {sentiment_metrics['very_positive']} | {sentiment_metrics['very_positive_pct']}% |
| Positive | {sentiment_metrics['positive']} | {sentiment_metrics['positive_pct']}% |
| Neutral | {sentiment_metrics['neutral']} | {sentiment_metrics['neutral_pct']}% |
| Negative | {sentiment_metrics['negative']} | {sentiment_metrics['negative_pct']}% |
| Mixed | {sentiment_metrics['mixed']} | {sentiment_metrics['mixed_pct']}% |

**Combined Positive Rate:** {positive_sentiment_rate}%
"""

    # Add sentiment chart (embedded as base64)
    if chart_paths and 'sentiment' in chart_paths:
        base64_data = embed_chart_as_base64(chart_paths['sentiment'])
        if base64_data:
            report += f'\n<img src="{base64_data}" alt="Sentiment Distribution" style="max-width: 800px; margin: 20px auto;" />\n'
        else:
            report += f"\n![Sentiment Distribution]({chart_paths['sentiment']})\n"

    # Add sentiment insights
    report += f"\n**Insights:**\n\n{sentiment_insights}\n"

    report += """
---

<h3 style="color: #0066a2;">LLM Platform Analysis</h3>

This section breaks down brand performance by individual LLM platforms (ChatGPT, Claude, Gemini, Perplexity) to identify platform-specific strengths and opportunities.

"""

    # Add LLM breakdown sections if data is available
    if llm_breakdown_data:
        # Sort platforms alphabetically for consistency
        platforms_order = ['ChatGPT', 'Claude', 'Gemini', 'Perplexity']

        # Brand Mentions by LLM
        report += '<h4 style="color: #2196F3;">Brand Mention Rates by LLM Platform</h4>\n\n'
        report += "| Platform | Total Responses | Brand Mentions | Mention Rate |\n"
        report += "|----------|----------------|----------------|-------------|\n"

        mentions_by_platform = {item['platform']: item for item in llm_breakdown_data.get('brand_mentions', [])}
        for platform in platforms_order:
            if platform in mentions_by_platform:
                data = mentions_by_platform[platform]
                report += f"| {data['platform']} | {data['total_responses']} | {data['mentions']} | {data['mention_rate']}% |\n"

        # Positioning by LLM
        report += '\n<h4 style="color: #2196F3;">Brand Positioning by LLM Platform</h4>\n\n'
        report += "| Platform | Leader | Featured | Listed | Not Mentioned | Total |\n"
        report += "|----------|--------|----------|--------|---------------|-------|\n"

        positioning_by_platform = {item['platform']: item for item in llm_breakdown_data.get('positioning', [])}
        for platform in platforms_order:
            if platform in positioning_by_platform:
                data = positioning_by_platform[platform]
                report += f"| {data['platform']} | {data['Leader']} | {data['Featured']} | {data['Listed']} | {data['Not Mentioned']} | {data['total']} |\n"

        # Sentiment by LLM
        report += '\n<h4 style="color: #2196F3;">Sentiment Distribution by LLM Platform</h4>\n\n'
        report += "*For responses where brand was mentioned*\n\n"
        report += "| Platform | Very Positive | Positive | Neutral | Negative | Very Negative | Mixed | Total |\n"
        report += "|----------|---------------|----------|---------|----------|---------------|-------|-------|\n"

        sentiment_by_platform = {item['platform']: item for item in llm_breakdown_data.get('sentiment', [])}
        for platform in platforms_order:
            if platform in sentiment_by_platform:
                data = sentiment_by_platform[platform]
                report += f"| {data['platform']} | {data['Very Positive']} | {data['Positive']} | {data['Neutral']} | {data['Negative']} | {data['Very Negative']} | {data['Mixed']} | {data['total']} |\n"

        # Share of Voice by LLM
        report += '\n<h4 style="color: #2196F3;">Share of Voice by LLM Platform</h4>\n\n'
        report += "| Platform | Brand Mentions | Competitor Mentions |\n"
        report += "|----------|----------------|--------------------|\n"

        sov_by_platform = {item['platform']: item for item in llm_breakdown_data.get('share_of_voice', [])}
        for platform in platforms_order:
            if platform in sov_by_platform:
                data = sov_by_platform[platform]
                report += f"| {data['platform']} | {data['brand']} | {data['competitors']} |\n"

        # Top Descriptors by LLM
        report += '\n<h4 style="color: #2196F3;">Top Descriptors by LLM Platform</h4>\n\n'

        descriptors_by_platform = {item['platform']: item for item in llm_breakdown_data.get('descriptors', [])}
        for platform in platforms_order:
            if platform in descriptors_by_platform:
                data = descriptors_by_platform[platform]
                report += f"\n**{data['platform']}** (Total descriptor mentions: {data['total_mentions']})\n\n"
                for desc in data['descriptors']:
                    report += f"- **{desc['descriptor']}**: {desc['count']} mentions\n"

        # Top Competitor Threats by LLM
        report += '\n<h4 style="color: #2196F3;">Competitor Mentions by LLM Platform</h4>\n\n'

        threats_by_platform = {item['platform']: item for item in llm_breakdown_data.get('threats', [])}
        for platform in platforms_order:
            if platform in threats_by_platform:
                data = threats_by_platform[platform]
                report += f"\n**{data['platform']}** (Total competitor mentions: {data['total_competitor_mentions']})\n\n"
                report += "| Competitor | Mentions | Negative Overlap |\n"
                report += "|-----------|----------|------------------|\n"
                for comp in data['competitors']:
                    report += f"| {comp['name']} | {comp['mentions']} | {comp['negative_overlap']} |\n"

    report += """

---

<h3 style="color: #0066a2;">Threat Analysis</h3>

**Competitor Threat Summary:**

Threats are calculated based on three factors: mention frequency (weight: 0.7), negative sentiment when competitor is present (weight: 2.0), and positive sentiment for competitor (weight: 1.5). Threat levels: High (score > 50), Medium (20-50), Low (< 20).

| Rank | Competitor | Threat Level | Threat Score | Mentions | Share of Voice |
|------|-----------|--------------|--------------|----------|----------------|"""

    # Add threat table data
    if competitor_threats_data:
        for i, threat in enumerate(competitor_threats_data[:10], 1):  # Top 10
            report += f"\n| {i} | {threat['name']} | {threat['threat_level']} | {threat['threat_score']} | {threat['mention_count']} | {threat['share_of_voice']}% |"
    else:
        report += "\n| - | No data | - | - | - | - |"

    report += "\n\n**Detailed Threat Analysis:**\n\n"
    report += competitor_threats

    report += """

---

<h3 style="color: #0066a2;">Recommendations</h3>
"""
    report += strategic_priorities

    report += """

---

<h2 style="color: #003e60;">Methodology</h2>

This report analyzes AI platform responses (ChatGPT, Claude, Gemini, Perplexity) to strategic queries.
Each response was analyzed for:
- Brand mention type and positioning
- Sentiment and tone
- Target descriptor usage
- Competitor mentions
- Source citations

All metrics are based on actual AI platform responses collected during the analysis period.

---

"""

    return report


# ==================== MAIN FUNCTION ====================

def generate_report_main(
    user_id: int,
    brand_id: int,
    report_type: str = 'monthly',
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    period_label: Optional[str] = None
):
    """
    Main function to generate the complete report for a specific brand.

    Args:
        user_id: User ID
        brand_id: Brand ID
        report_type: 'monthly', 'quarterly', 'annual', or 'all_data'
        period_start: Optional custom period start date (overrides automatic calculation)
        period_end: Optional custom period end date (overrides automatic calculation)
        period_label: Optional custom period label (e.g., "Q1 2026", "2025 Annual Report")
    """
    print(f"Starting TALES Report Generation for Brand ID {brand_id}...")
    print(f"Report Type: {report_type}")
    if period_label:
        print(f"Period: {period_label}")

    db = SessionLocal()
    task = None  # Initialize to avoid UnboundLocalError

    try:
        # Get the most recent task for this user and brand
        task = db.query(TaskStatus).filter(
            TaskStatus.user_id == user_id,
            TaskStatus.brand_id == brand_id,
            TaskStatus.task_type == "analysis_and_report"
        ).order_by(TaskStatus.started_at.desc()).first()

        # Get brand info
        brand_info = get_brand_info(db, brand_id)
        if not brand_info:
            print(f"Error: Brand ID {brand_id} not found")
            if task:
                task.status = "failed"
                task.error_message = f"Brand ID {brand_id} not found"
                db.commit()
            return

        brand_name = brand_info.brand_name
        print(f"Generating report for: {brand_name}")

        # Load LLM providers from database (or fall back to env vars)
        analysis_provider = None
        web_search_providers = []
        try:
            user = db.query(User).filter(User.id == user_id).first()
            tenant_id = user.tenant_id if user else None
            provider_manager = LLMProviderManager(db, tenant_id)

            analysis_provider = provider_manager.get_analysis_provider()
            web_search_providers = provider_manager.get_web_search_providers()

            if analysis_provider:
                print(f"  - Using {analysis_provider.display_name} for report writing")
            else:
                # Fail fast: no provider means every downstream LLM call will raise.
                # Doing it here avoids burning DB queries / web searches and ensures
                # the task is marked failed so the UI doesn't hang in "running".
                error_msg = (
                    "No analysis LLM configured. Configure one in Admin → LLM Providers "
                    "and set use_for_analysis=True on the provider you want."
                )
                print(f"  - ERROR: {error_msg}")
                if task:
                    task.status = "failed"
                    task.error_message = error_msg
                    db.commit()
                return

            if web_search_providers:
                print(f"  - Web search providers: {', '.join(p.display_name for p in web_search_providers)}")
            else:
                print(f"  - No web search providers configured (State of the LLMs section will be omitted)")

        except Exception as e:
            print(f"  - Warning: Could not load LLM providers from database: {e}")

        # Update task status: starting report generation
        if task:
            task.message = "Generating report..."
            task.processed_items = task.total_items  # Analysis is complete
            db.commit()

        # Step 1: Collect data based on report type
        print("\nCollecting data from database...")

        historical_summary = None
        report_period_description = ""
        start_date = None
        end_date = None

        # Use custom period dates if provided, otherwise calculate based on report_type
        if period_start and period_end:
            # Custom period provided (e.g., from scheduled analysis)
            start_date = period_start
            end_date = period_end
            report_period_description = period_label or f"{start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"
            print(f"  - Using custom period: {report_period_description}")
            responses = get_brand_analyzed_responses(db, user_id, brand_id, start_date=start_date, end_date=end_date)

        elif report_type == 'monthly':
            # Get batch IDs from last complete calendar month
            batch_ids, month_name = get_last_month_batch_ids(db, user_id, brand_id)
            print(f"  - Found {len(batch_ids)} collection batches for {month_name}")

            if batch_ids:
                responses = get_brand_analyzed_responses(db, user_id, brand_id, batch_ids=batch_ids)
            else:
                # Fallback: use date-based filtering if no batches found
                print(f"  - No batches found for {month_name}, using date range filtering")
                start_date, end_date, _ = get_last_calendar_month_range()
                responses = get_brand_analyzed_responses(db, user_id, brand_id, start_date=start_date, end_date=end_date)

            # Get historical summary for context
            historical_summary = get_historical_metrics_summary(db, user_id, brand_id, brand_name)
            if historical_summary:
                print(f"  - Historical context: {historical_summary['total_batches']} batches spanning {historical_summary['date_range_days']} days")

            report_period_description = period_label or month_name

        elif report_type == 'quarterly':
            # Get data from last complete calendar quarter
            start_date, end_date, quarter_label = get_last_quarter_range()
            print(f"  - Quarterly report for {quarter_label}")
            responses = get_brand_analyzed_responses(db, user_id, brand_id, start_date=start_date, end_date=end_date)
            report_period_description = period_label or quarter_label

            # Get historical summary for context
            historical_summary = get_historical_metrics_summary(db, user_id, brand_id, brand_name)

        elif report_type == 'annual':
            # Get data from last complete calendar year
            start_date, end_date, year_label = get_last_year_range()
            print(f"  - Annual report for {year_label}")
            responses = get_brand_analyzed_responses(db, user_id, brand_id, start_date=start_date, end_date=end_date)
            report_period_description = period_label or year_label

        else:
            # all_data mode: get all responses
            responses = get_brand_analyzed_responses(db, user_id, brand_id)
            report_period_description = period_label or "All Data to Date"

        queries = get_brand_queries(db, user_id, brand_id)
        competitors = get_brand_competitors(db, user_id, brand_id)
        descriptors = get_brand_descriptors(db, user_id, brand_id)

        if not responses:
            print("Error: No analyzed responses found for this brand. Please run data collection and analysis first.")
            return

        print(f"Found {len(responses)} analyzed responses")
        print(f"Found {len(queries)} queries")
        print(f"Found {len(competitors)} competitors")
        print(f"Found {len(descriptors)} descriptors")

        # Step 2: Calculate metrics
        print("\nCalculating metrics...")
        mention_metrics = calculate_mention_metrics(responses)
        positioning_metrics = calculate_positioning_metrics(responses, queries)
        sentiment_metrics = calculate_sentiment_metrics(responses)
        platform_metrics = calculate_platform_metrics(responses, queries)
        descriptor_analysis = analyze_descriptors(responses)
        competitor_analysis = analyze_competitors(responses)
        positive_sentiment_rate = calculate_positive_sentiment_rate(responses)
        descriptor_match_rate = calculate_descriptor_match_rate(responses, descriptors)
        share_of_voice = calculate_share_of_voice(responses, queries, competitors, brand_name)
        positioning_average = calculate_positioning_average(responses, queries)
        negative_statements = get_negative_sentiment_statements(responses)

        print("All metrics calculated")

        # Step 2b: Calculate trend breakdown based on report type
        print("\nCalculating period trend breakdown...")
        trend_breakdown = None
        trend_summary_text = ""

        if report_type == 'monthly' and start_date and end_date:
            print("  - Calculating weekly breakdown for monthly report")
            trend_breakdown = get_weekly_breakdown(db, user_id, brand_id, start_date, end_date)
            trend_summary_text = format_trend_summary(trend_breakdown, 'weekly')
            print(f"  - Generated {len(trend_breakdown)} weekly data points")

        elif report_type == 'quarterly' and start_date and end_date:
            print("  - Calculating monthly breakdown for quarterly report")
            trend_breakdown = get_monthly_breakdown(db, user_id, brand_id, start_date, end_date)
            trend_summary_text = format_trend_summary(trend_breakdown, 'monthly')
            print(f"  - Generated {len(trend_breakdown)} monthly data points")

        elif report_type == 'annual' and start_date and end_date:
            print("  - Calculating quarterly breakdown for annual report")
            trend_breakdown = get_quarterly_breakdown(db, user_id, brand_id, start_date, end_date)
            trend_summary_text = format_trend_summary(trend_breakdown, 'quarterly')
            print(f"  - Generated {len(trend_breakdown)} quarterly data points")

        # Prepare metrics summary for AI generation
        metrics_summary = {
            "brand_name": brand_name,
            "mention_metrics": mention_metrics,
            "positioning_metrics": positioning_metrics,
            "sentiment_metrics": sentiment_metrics,
            "positive_sentiment_rate": positive_sentiment_rate,
            "descriptor_match_rate": descriptor_match_rate,
            "share_of_voice": share_of_voice,
            "positioning_average": positioning_average,
            "trend_breakdown": trend_breakdown,
            "trend_summary": trend_summary_text,
        }

        # Step 3: Build rich context for enhanced prompts
        print("\nBuilding enhanced context for AI analysis...")

        brand_context_str = build_brand_context(brand_info, brand_name)
        competitor_context = build_competitor_context(competitors)
        descriptor_context = build_descriptor_context(descriptors, descriptor_analysis)
        platform_performance = build_platform_performance_context(platform_metrics)

        best_responses = get_best_performing_responses(responses)
        worst_responses = get_worst_performing_responses(responses)
        competitive_losses = get_competitive_loss_examples(responses)

        response_examples = build_response_examples_context(
            best_responses, worst_responses, competitive_losses, brand_name
        )

        print("Context building complete")

        # Step 3b: Calculate competitor threats using CompetitorThreats page logic
        print("\nCalculating competitor threat scores...")
        competitor_threats_data = calculate_competitor_threats(
            competitor_sov=share_of_voice['competitor_sov'],
            responses=responses,
            brand_name=brand_name
        )
        print(f"  - {len(competitor_threats_data)} competitors analyzed")
        if competitor_threats_data:
            print(f"  - Top 3 threats: {', '.join([t['name'] for t in competitor_threats_data[:3]])}")

        # Step 3c: Research LLM platform state changes
        print("\nResearching current LLM platform state...")
        try:
            llm_state_data = research_llm_state_changes(
                report_type=report_type,
                web_search_providers=web_search_providers,
                analysis_provider=analysis_provider
            )
            if llm_state_data.get('has_changes'):
                print(f"  - Found {len(llm_state_data.get('bullets', []))} notable changes")
            else:
                print("  - No notable changes found")
            if llm_state_data.get('platform_notes'):
                for platform, note in llm_state_data['platform_notes'].items():
                    print(f"  - {platform}: {note}")
        except Exception as e:
            print(f"  - Warning: LLM state research failed: {e}")
            llm_state_data = {
                'has_changes': False,
                'bullets': [],
                'platform_notes': {'Research': f'Failed to fetch: {str(e)}'},
                'raw_research': '',
                'trend_analysis': ''
            }

        # Step 4: Generate AI insights with enhanced prompts
        provider_name = analysis_provider.display_name if analysis_provider else "<no provider — will fail>"
        print(f"\nGenerating AI-powered insights with {provider_name}...")
        print("  - Executive summary...")
        executive_summary = generate_executive_summary(
            metrics_summary=metrics_summary,
            brand_name=brand_name,
            brand_info=brand_info,
            total_responses=len(responses),
            brand_context_str=brand_context_str,
            platform_performance=platform_performance,
            response_examples=response_examples,
            descriptor_context=descriptor_context,
            competitor_context=competitor_context,
            report_type=report_type,
            historical_summary=historical_summary,
            period_name=report_period_description,
            provider=analysis_provider,
            trend_summary=trend_summary_text
        )

        print("  - Competitor threat analysis (top 3 threats)...")
        competitor_threats = generate_competitor_threat_analysis(
            top_threats=competitor_threats_data,
            competitor_sov=share_of_voice['competitor_sov'],
            responses=responses,
            competitors_list=competitors,
            brand_name=brand_name,
            brand_context_str=brand_context_str,
            competitor_context=competitor_context,
            worst_responses=worst_responses,
            competitive_losses=competitive_losses,
            provider=analysis_provider
        )

        print("  - Strategic recommendations...")
        strategic_priorities = generate_strategic_priorities(
            metrics_summary=metrics_summary,
            brand_name=brand_name,
            brand_info=brand_info,
            brand_context_str=brand_context_str,
            descriptor_context=descriptor_context,
            competitor_context=competitor_context,
            platform_performance=platform_performance,
            best_responses=best_responses,
            worst_responses=worst_responses,
            llm_state_data=llm_state_data,
            provider=analysis_provider,
            web_search_providers=web_search_providers
        )

        print("AI insights generated")

        # Step 4b: Generate section-specific insights
        print("\nGenerating section insights...")
        print("  - Positioning insights...")
        positioning_insights = generate_positioning_insights(
            positioning_metrics=positioning_metrics,
            positioning_average=positioning_average,
            platform_metrics=platform_metrics,
            brand_name=brand_name,
            provider=analysis_provider
        )

        print("  - Share of voice insights...")
        sov_insights = generate_share_of_voice_insights(
            share_of_voice=share_of_voice,
            brand_name=brand_name,
            competitor_analysis=competitor_analysis,
            provider=analysis_provider
        )

        print("  - Descriptor insights...")
        descriptor_insights = generate_descriptor_insights(
            descriptor_analysis=descriptor_analysis,
            descriptor_match_rate=descriptor_match_rate,
            brand_name=brand_name,
            target_descriptors=descriptors,
            provider=analysis_provider
        )

        print("  - Sentiment insights...")
        sentiment_insights = generate_sentiment_insights(
            sentiment_metrics=sentiment_metrics,
            positive_sentiment_rate=positive_sentiment_rate,
            negative_statements=negative_statements,
            brand_name=brand_name,
            platform_metrics=platform_metrics,
            provider=analysis_provider
        )

        print("Section insights generated")

        # Step 4c: Collect LLM breakdown data
        print("\nCollecting LLM platform breakdown data...")
        llm_breakdown_data = get_llm_breakdown_data(db, user_id, brand_id, brand_name)
        print(f"  - Brand mention data for {len(llm_breakdown_data['brand_mentions'])} platforms")
        print(f"  - Positioning data for {len(llm_breakdown_data['positioning'])} platforms")
        print(f"  - Sentiment data for {len(llm_breakdown_data['sentiment'])} platforms")
        print(f"  - Share of voice data for {len(llm_breakdown_data['share_of_voice'])} platforms")
        print(f"  - Descriptor data for {len(llm_breakdown_data['descriptors'])} platforms")
        print(f"  - Threat data for {len(llm_breakdown_data['threats'])} platforms")

        # Step 5: Collect trend data for charts
        print("\nCollecting trend data for visualization...")
        trend_data = None
        try:
            brand_mentions_trend = get_brand_mentions_trend_cached(db, user_id, brand_id)
            positioning_trend = get_positioning_trend_cached(db, user_id, brand_id)
            sentiment_trend = get_sentiment_trend_cached(db, user_id, brand_id)
            sov_trend = get_share_of_voice_trend_cached(db, user_id, brand_id, brand_name)

            # Format trend data for chart generator
            if brand_mentions_trend:
                trend_data = {
                    'brand_mentions': [
                        {
                            'date': str(item['date']),
                            'mention_percentage': item['mention_rate']
                        }
                        for item in brand_mentions_trend
                    ] if brand_mentions_trend else None,
                    'positioning': positioning_trend if positioning_trend else None,
                    'sentiment': sentiment_trend if sentiment_trend else None,
                    'share_of_voice': [
                        {
                            'date': str(item['date']),
                            'brand_sov': item.get(brand_name, 0),
                            'competitors': {k: v for k, v in item.items() if k != 'date' and k != brand_name}
                        }
                        for item in sov_trend
                    ] if sov_trend else None
                }
                print(f"  - Collected trend data for {len(brand_mentions_trend)} time periods")
        except Exception as e:
            print(f"  - Could not collect trend data: {e}")
            print("  - Charts will be generated without trend lines")
            trend_data = None

        # Step 6: Generate charts
        print("\nGenerating visualization charts...")
        timestamp = now_eastern().strftime('%Y%m%d_%H%M%S')
        chart_paths = generate_all_charts(
            mention_metrics=mention_metrics,
            positioning_metrics=positioning_metrics,
            sentiment_metrics=sentiment_metrics,
            platform_metrics=platform_metrics,
            share_of_voice=share_of_voice,
            descriptor_analysis=descriptor_analysis,
            brand_name=brand_name,
            timestamp=timestamp,
            user_id=user_id,
            brand_id=brand_id,
            trend_data=trend_data,
            competitor_threats=competitor_threats_data
        )
        print(f"Total charts available: {len(chart_paths)}")

        # Step 6: Generate report
        print("\nGenerating markdown report...")
        report_date = format_eastern(now_eastern(), "%B %d, %Y at %I:%M %p EST")
        period = report_period_description

        markdown_report = generate_markdown_report(
            mention_metrics=mention_metrics,
            positioning_metrics=positioning_metrics,
            sentiment_metrics=sentiment_metrics,
            platform_metrics=platform_metrics,
            descriptor_analysis=descriptor_analysis,
            competitor_analysis=competitor_analysis,
            positive_sentiment_rate=positive_sentiment_rate,
            descriptor_match_rate=descriptor_match_rate,
            share_of_voice=share_of_voice,
            positioning_average=positioning_average,
            negative_statements=negative_statements,
            competitor_threats=competitor_threats,
            strategic_priorities=strategic_priorities,
            executive_summary=executive_summary,
            brand_name=brand_name,
            brand_info=brand_info,
            report_date=report_date,
            period=period,
            responses=responses,
            chart_paths=chart_paths,
            positioning_insights=positioning_insights,
            sov_insights=sov_insights,
            descriptor_insights=descriptor_insights,
            sentiment_insights=sentiment_insights,
            queries=queries,
            descriptors=descriptors,
            competitors=competitors,
            competitor_threats_data=competitor_threats_data,
            llm_breakdown_data=llm_breakdown_data,
            report_type=report_type,
            historical_summary=historical_summary,
            llm_state_data=llm_state_data,
        )

        # Step 5: Save to database
        print("\nSaving report to database...")

        # Update task status: saving report
        if task:
            task.message = "Saving report to database..."
            db.commit()

        # Create title based on report type
        if report_type == 'monthly':
            report_title = f"{brand_name} Monthly AI Reputation Analysis - {report_period_description}"
        elif report_type == 'quarterly':
            report_title = f"{brand_name} Quarterly AI Reputation Analysis - {report_period_description}"
        elif report_type == 'annual':
            report_title = f"{brand_name} Annual AI Reputation Analysis - {report_period_description}"
        else:
            report_title = f"{brand_name} Comprehensive AI Reputation Analysis - {format_eastern_date(now_eastern())}"

        report_obj = Report(
            user_id=user_id,
            brand_id=brand_id,
            title=report_title,
            report_type=report_type,
            period_label=report_period_description,
            start_date=start_date,
            end_date=end_date,
            report_content=markdown_report,
            total_responses=len(responses),
            mention_rate=metrics_summary.get('mention_rate', 0),
        )

        db.add(report_obj)
        db.commit()
        db.refresh(report_obj)

        print(f"Report saved to database (ID: {report_obj.id})")

        # Step 6: Save to file
        filename = f"report_{brand_name.replace(' ', '_')}_{now_eastern().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, 'w') as f:
            f.write(markdown_report)

        print(f"Report saved to file: {filename}")
        print("\nReport generation complete!")

        # Update task status: completed
        if task:
            task.status = "completed"
            task.completed_at = datetime.now()
            task.message = "Analysis and report generation completed"
            db.commit()

        print(f"\nReport Preview (first 500 chars):")
        print("-" * 60)
        print(markdown_report[:500] + "...")
        print("-" * 60)

    except Exception as e:
        print(f"\nError generating report: {e}")
        import traceback
        traceback.print_exc()

        # Update task status: failed
        if task:
            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.now()
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='TALES Report Generation Tool')
    parser.add_argument('--user-id', type=int, required=True, help='User ID to generate report for')
    parser.add_argument('--brand-id', type=int, required=True, help='Brand ID to generate report for')
    parser.add_argument('--report-type', type=str, default='monthly',
                        choices=['monthly', 'quarterly', 'annual', 'all_data'],
                        help='Report type: monthly, quarterly, annual, or all_data')
    parser.add_argument('--period-start', type=str, default=None,
                        help='Custom period start date (ISO format: 2026-01-01T00:00:00)')
    parser.add_argument('--period-end', type=str, default=None,
                        help='Custom period end date (ISO format: 2026-03-31T23:59:59)')
    parser.add_argument('--period-label', type=str, default=None,
                        help='Custom period label (e.g., "Q1 2026", "January 2026")')
    args = parser.parse_args()

    # Parse period dates if provided
    period_start = None
    period_end = None
    if args.period_start:
        period_start = datetime.fromisoformat(args.period_start)
    if args.period_end:
        period_end = datetime.fromisoformat(args.period_end)

    generate_report_main(
        args.user_id,
        args.brand_id,
        args.report_type,
        period_start=period_start,
        period_end=period_end,
        period_label=args.period_label
    )
