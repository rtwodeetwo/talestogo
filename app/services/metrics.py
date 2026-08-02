"""
TALES Metrics Calculation Module
=================================
Single source of truth for ALL metric calculations.
Used by both analytics cache service and report generation.

FILTERING RULES:
---------------
1. Positioning/SOV/Mentions: EXCLUDE brand_in_query=True queries
   Rationale: When brand is in the query, it's not a fair test of organic visibility

2. Sentiment/Descriptors: INCLUDE all queries (applies to ALL mentions)
   Rationale: Sentiment and descriptors apply to all mentions regardless of query type

3. Direct mentions only: brand_mentioned == 'Yes'
   Use for: Sentiment analysis, Descriptor analysis (descriptors tied to direct mentions)

4. Direct + Indirect: brand_mentioned in ['Yes', 'Indirect']
   Use for: Positioning analysis (includes all forms of brand presence)

IMPORTANT: All functions accept Response and Query objects as parameters.
They do NOT make database calls - that's handled by the calling layer.
"""

from typing import List, Dict, Any
from collections import Counter


# ==================== CONSTANTS ====================

POSITION_SCORES = {
    "Leader": 4,
    "Featured": 3,
    "Listed": 2,
    "Not Mentioned": 1,
}

THREAT_WEIGHTS = {
    "mention_weight": 0.7,
    "negative_weight": 2.0,
    "positive_weight": 1.5,
}

THREAT_THRESHOLDS = {
    "high": 50,
    "medium": 20,
}


# ==================== UTILITY FUNCTIONS ====================

def normalize_organization_name(name: str) -> str:
    """
    SINGLE SOURCE OF TRUTH for organization name normalization.

    Normalize organization names for consistent grouping across the entire application.
    This function combines variations of the same organization into a canonical name.

    IMPORTANT: This is imported by:
    - app.analytics
    - app.services.batch_analytics
    - frontend (via API responses)

    When adding new normalization rules, add them to this function ONLY.

    Examples:
    - "STEP", "MAST-U", "UKAEA" -> "UKAEA"
    - "ST40", "Tokamak Energy" -> "Tokamak Energy"
    - "OpenAI", "Open AI" -> "OpenAI"
    - "Google Cloud", "Google" -> "Google"
    """
    if not name:
        return name

    name_lower = name.strip().lower()

    # UKAEA variants (STEP and MAST-U are machines/projects made by UKAEA)
    if any(variant in name_lower for variant in ['step', 'mast-u', 'mast u', 'ukaea']):
        return "UKAEA"

    # Tokamak Energy variants (ST40 is a machine made by Tokamak Energy)
    if any(variant in name_lower for variant in ['st40', 'st-40', 'tokamak energy']):
        return "Tokamak Energy"

    # Tech company normalizations (dictionary-based for exact matches)
    normalizations = {
        # OpenAI variations
        'open ai': 'OpenAI',
        'openai': 'OpenAI',

        # Google variations
        'google': 'Google',
        'google cloud': 'Google',
        'google workspace': 'Google',

        # Microsoft variations
        'microsoft': 'Microsoft',
        'microsoft azure': 'Microsoft',
        'microsoft 365': 'Microsoft',

        # Amazon variations
        'aws': 'AWS',
        'amazon web services': 'AWS',
        'amazon aws': 'AWS',
    }

    # Check dictionary for exact match (case-insensitive)
    normalized = normalizations.get(name_lower)
    if normalized:
        return normalized

    # Return original name if no normalization rule matched
    return name.strip()


def filter_exclude_branded_queries(responses: List[Any], queries: List[Any]) -> List[Any]:
    """
    Filter out responses from queries where brand is in the query text.

    Use this for: Positioning, Share of Voice, Mention Rate calculations.
    Don't use for: Sentiment, Descriptors (which apply to all mentions).

    Args:
        responses: List of Response objects
        queries: List of Query objects

    Returns:
        Filtered list of responses excluding branded queries
    """
    branded_query_ids = {q.query_id for q in queries if q.brand_in_query}
    return [r for r in responses if r.query_id not in branded_query_ids]


# ==================== CORE METRIC CALCULATIONS ====================

def calculate_mention_metrics(responses: List[Any]) -> Dict[str, Any]:
    """
    Calculate mention breakdown (Yes/Indirect/No).

    NOTE: This function does NOT filter by brand_in_query internally.
    The caller should pre-filter responses if needed.

    Args:
        responses: List of Response objects

    Returns:
        Dict with counts and percentages for each mention type
    """
    total = len(responses)
    if total == 0:
        return {"total": 0, "yes": 0, "indirect": 0, "no": 0}

    mentions = Counter([r.brand_mentioned for r in responses])

    return {
        "total": total,
        "yes": mentions.get("Yes", 0),
        "indirect": mentions.get("Indirect", 0),
        "no": mentions.get("No", 0),
        "yes_pct": round((mentions.get("Yes", 0) / total) * 100),
        "indirect_pct": round((mentions.get("Indirect", 0) / total) * 100),
        "no_pct": round((mentions.get("No", 0) / total) * 100),
    }


def calculate_positioning_metrics(responses: List[Any], queries: List[Any]) -> Dict[str, Any]:
    """
    Calculate brand positioning metrics.

    FILTERS APPLIED:
    - Excludes responses from queries where brand_in_query=True
    - Only counts responses where brand_mentioned in ['Yes', 'Indirect']

    This matches dashboard logic for fair positioning analysis.

    Args:
        responses: List of Response objects
        queries: List of Query objects

    Returns:
        Dict with counts and percentages for each position level
    """
    # Build set of query_ids where brand_in_query=True to exclude
    branded_query_ids = {q.query_id for q in queries if q.brand_in_query}

    # Filter responses: exclude branded queries and only count mentions
    filtered_responses = [
        r for r in responses
        if r.query_id not in branded_query_ids
        and r.brand_mentioned in ['Yes', 'Indirect']
    ]

    total = len(filtered_responses)
    if total == 0:
        return {
            "total": 0,
            "leader": 0,
            "featured": 0,
            "listed": 0,
            "not_mentioned": 0,
            "leader_pct": 0,
            "featured_pct": 0,
            "listed_pct": 0,
            "not_mentioned_pct": 0,
        }

    positions = Counter([r.brand_position for r in filtered_responses])

    # Combine "Top 3" and "Featured" into single "Featured" category
    featured_count = positions.get("Featured", 0) + positions.get("Top 3", 0)

    return {
        "total": total,
        "leader": positions.get("Leader", 0),
        "featured": featured_count,
        "listed": positions.get("Listed", 0),
        "not_mentioned": positions.get("Not Mentioned", 0),
        "leader_pct": round((positions.get("Leader", 0) / total) * 100),
        "featured_pct": round((featured_count / total) * 100),
        "listed_pct": round((positions.get("Listed", 0) / total) * 100),
        "not_mentioned_pct": round((positions.get("Not Mentioned", 0) / total) * 100),
    }


def calculate_positioning_average(responses: List[Any], queries: List[Any]) -> float:
    """
    Calculate average positioning score.

    Scoring: Leader=4, Featured=3, Listed=2, Not Mentioned=1

    FILTERS APPLIED:
    - Excludes responses from queries where brand_in_query=True
    - Only counts responses where brand_mentioned in ['Yes', 'Indirect']

    Args:
        responses: List of Response objects
        queries: List of Query objects

    Returns:
        Average positioning score (0.0 to 5.0)
    """
    # Build set of query_ids where brand_in_query=True to exclude
    branded_query_ids = {q.query_id for q in queries if q.brand_in_query}

    # Filter responses: exclude branded queries and only count mentions
    filtered_responses = [
        r for r in responses
        if r.query_id not in branded_query_ids
        and r.brand_mentioned in ['Yes', 'Indirect']
    ]

    if not filtered_responses:
        return 0

    total_score = sum(POSITION_SCORES.get(r.brand_position, 1) for r in filtered_responses)
    return round(total_score / len(filtered_responses))


def calculate_sentiment_metrics(responses: List[Any]) -> Dict[str, Any]:
    """
    Calculate sentiment distribution for DIRECT brand mentions only.

    FILTERS APPLIED:
    - Only counts responses where brand_mentioned == 'Yes' (direct mentions)
    - NO brand_in_query filtering (sentiment applies to ALL queries)

    Rationale: Sentiment analysis should focus on direct mentions where
    sentiment can be clearly attributed to the brand.

    Args:
        responses: List of Response objects

    Returns:
        Dict with counts and percentages for each sentiment category
    """
    # Filter to only direct brand mentions
    brand_responses = [r for r in responses if r.brand_mentioned == "Yes"]
    total = len(brand_responses)

    if total == 0:
        return {
            "total": 0,
            "very_positive": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "mixed": 0,
            "very_negative": 0,
            "very_positive_pct": 0,
            "positive_pct": 0,
            "neutral_pct": 0,
            "negative_pct": 0,
            "mixed_pct": 0,
            "very_negative_pct": 0,
        }

    sentiments = Counter([r.sentiment for r in brand_responses])

    return {
        "total": total,
        "very_positive": sentiments.get("Very Positive", 0),
        "positive": sentiments.get("Positive", 0),
        "neutral": sentiments.get("Neutral", 0),
        "negative": sentiments.get("Negative", 0),
        "mixed": sentiments.get("Mixed", 0),
        "very_negative": sentiments.get("Very Negative", 0),
        "very_positive_pct": round((sentiments.get("Very Positive", 0) / total) * 100),
        "positive_pct": round((sentiments.get("Positive", 0) / total) * 100),
        "neutral_pct": round((sentiments.get("Neutral", 0) / total) * 100),
        "negative_pct": round((sentiments.get("Negative", 0) / total) * 100),
        "mixed_pct": round((sentiments.get("Mixed", 0) / total) * 100),
        "very_negative_pct": round((sentiments.get("Very Negative", 0) / total) * 100),
    }


def calculate_positive_sentiment_rate(responses: List[Any]) -> float:
    """
    Calculate percentage of responses with positive or very positive sentiment.

    FILTERS APPLIED:
    - Only counts direct mentions (brand_mentioned == 'Yes')

    Args:
        responses: List of Response objects

    Returns:
        Percentage of positive responses (0.0 to 100.0)
    """
    brand_responses = [r for r in responses if r.brand_mentioned == "Yes"]
    if not brand_responses:
        return 0.0

    positive_count = sum(1 for r in brand_responses if r.sentiment in ["Positive", "Very Positive"])
    return round((positive_count / len(brand_responses)) * 100)


def calculate_platform_metrics(responses: List[Any], queries: List[Any]) -> Dict[str, Dict[str, Any]]:
    """
    Calculate metrics broken down by platform.

    Returns positioning, mention, and sentiment metrics for each platform.

    Args:
        responses: List of Response objects
        queries: List of Query objects

    Returns:
        Dict with platform names as keys, each containing full metrics
    """
    platforms = {}

    for platform in ["ChatGPT", "Claude", "Gemini", "Perplexity"]:
        platform_responses = [r for r in responses if r.platform == platform]

        platforms[platform] = {
            "total": len(platform_responses),
            "mention": calculate_mention_metrics(platform_responses),
            "positioning": calculate_positioning_metrics(platform_responses, queries),
            "sentiment": calculate_sentiment_metrics(platform_responses),
        }

    return platforms


def analyze_descriptors(responses: List[Any]) -> Dict[str, int]:
    """
    Count occurrences of descriptors in responses where brand is directly mentioned.

    FILTERS APPLIED:
    - Only counts direct mentions (brand_mentioned == 'Yes')
    - NO brand_in_query filtering (descriptors apply to all mentions)

    Rationale: Descriptors are typically associated with direct brand mentions
    where the descriptor can be clearly attributed to the brand.

    Args:
        responses: List of Response objects

    Returns:
        Dict mapping descriptor -> count
    """
    descriptor_counts = Counter()

    for response in responses:
        # Only count descriptors from responses where brand is directly mentioned
        if response.brand_mentioned == "Yes" and hasattr(response, 'descriptors') and response.descriptors:
            # Descriptors are stored as comma-separated strings
            descriptors = [d.strip() for d in response.descriptors.split(',') if d.strip()]
            for descriptor in descriptors:
                descriptor_counts[descriptor] += 1

    return dict(descriptor_counts)


def calculate_descriptor_match_rate(responses: List[Any], descriptors: List[Any]) -> float:
    """
    Calculate percentage of target descriptors that appear in AI responses.

    FILTERS APPLIED:
    - Only counts direct mentions (brand_mentioned == 'Yes')
    - NO brand_in_query filtering

    This matches the 'Target Descriptor Adoption' metric on the dashboard.

    Args:
        responses: List of Response objects
        descriptors: List of TargetDescriptor objects with 'descriptor' and 'is_target' attributes

    Returns:
        Percentage of target descriptors found (0.0 to 100.0)
    """
    # Get only direct brand mentions
    brand_responses = [r for r in responses if r.brand_mentioned == "Yes"]
    if not brand_responses:
        return 0.0

    # Build set of target descriptor names (case-insensitive)
    target_descriptors_set = {td.descriptor.lower().strip() for td in descriptors if td.is_target}
    if not target_descriptors_set:
        return 0.0

    # Find which target descriptors actually appear in responses
    found_target_descriptors = set()
    for response in brand_responses:
        if response.descriptors and response.descriptors.strip():
            desc_list = [d.lower().strip() for d in response.descriptors.split(',') if d.strip()]
            for desc in desc_list:
                if desc in target_descriptors_set:
                    found_target_descriptors.add(desc)

    # Calculate percentage of target descriptors found
    return round((len(found_target_descriptors) / len(target_descriptors_set)) * 100)


def analyze_competitors(responses: List[Any]) -> Dict[str, int]:
    """
    Count occurrences of competitors in all responses.

    FILTERS APPLIED:
    - None (counts all competitor mentions across all responses)

    Args:
        responses: List of Response objects

    Returns:
        Dict mapping competitor name -> count
    """
    competitor_counts = Counter()

    for response in responses:
        if response.competitors:
            # Competitors are stored as comma-separated strings
            competitors = [c.strip() for c in response.competitors.split(',') if c.strip()]
            for competitor in competitors:
                # Apply normalization for consistent grouping
                normalized_name = normalize_organization_name(competitor)
                competitor_counts[normalized_name] += 1

    return dict(competitor_counts)


def calculate_leadership_visibility(responses: List[Any], queries: List[Any]) -> float:
    """
    Calculate leadership visibility percentage.

    Leadership visibility = (Leader + Featured positions) / total_responses * 100

    FILTERS APPLIED:
    - Excludes responses from queries where brand_in_query=True
    - Counts all responses (not just brand mentions) as denominator

    Note: Since we combined "Top 3" into "Featured", we now count Leader + Featured.
    The old calculation used Leader + Top 3, which is equivalent.

    Args:
        responses: List of Response objects
        queries: List of Query objects

    Returns:
        Leadership visibility percentage (0-100)
    """
    # Build set of query_ids where brand_in_query=True to exclude
    branded_query_ids = {q.query_id for q in queries if q.brand_in_query}

    # Filter responses: exclude branded queries
    filtered_responses = [
        r for r in responses
        if r.query_id not in branded_query_ids
    ]

    total = len(filtered_responses)
    if total == 0:
        return 0.0

    # Count Leader and Featured positions (Featured now includes old "Top 3")
    leadership_count = sum(
        1 for r in filtered_responses
        if r.brand_position in ['Leader', 'Top 3', 'Featured']
    )

    return round((leadership_count / total) * 100)


def calculate_share_of_voice(
    responses: List[Any],
    queries: List[Any],
    competitors: List[Any],
    brand_name: str
) -> Dict[str, Any]:
    """
    Calculate share of voice for brand vs competitors.

    FILTERS APPLIED:
    - Excludes responses from queries where brand_in_query=True
    - Counts brand by POSITIONING (Leader, Featured, Listed), not just 'Yes' mentions

    This provides a more accurate measure of brand visibility vs competitors.

    Args:
        responses: List of Response objects
        queries: List of Query objects
        competitors: List of Competitor objects (not currently used, kept for compatibility)
        brand_name: Name of the brand being analyzed

    Returns:
        Dict with brand_mentions, total_mentions, brand_sov, competitor_sov
    """
    # Build set of query_ids where brand_in_query=True to exclude
    branded_query_ids = {q.query_id for q in queries if q.brand_in_query}

    # Count total mentions across all organizations (excluding branded queries)
    total_mentions = 0
    brand_mentions = 0
    competitor_mentions = Counter()

    for response in responses:
        # Skip responses from queries where brand name is in the query
        if response.query_id in branded_query_ids:
            continue

        # Count brand mentions by positioning (not just "Yes")
        # This counts any response where brand appears in a meaningful position
        # Note: "Top 3" is treated as "Featured" for display purposes
        if response.brand_position in ['Leader', 'Top 3', 'Featured', 'Listed']:
            brand_mentions += 1
            total_mentions += 1

        # Count competitor mentions
        if response.competitors:
            comp_list = [c.strip() for c in response.competitors.split(',') if c.strip()]
            for comp in comp_list:
                # Apply normalization for consistent grouping
                normalized_name = normalize_organization_name(comp)
                competitor_mentions[normalized_name] += 1
                total_mentions += 1

    # Calculate brand share of voice
    brand_sov = round((brand_mentions / total_mentions) * 100) if total_mentions > 0 else 0.0

    # Build competitor SOV data (top 5 by default for compatibility)
    competitor_sov = {}
    for comp_name, count in competitor_mentions.most_common(5):
        sov = round((count / total_mentions) * 100) if total_mentions > 0 else 0.0
        competitor_sov[comp_name] = {"count": count, "sov": sov}

    return {
        "brand_mentions": brand_mentions,
        "total_mentions": total_mentions,
        "brand_sov": brand_sov,
        "competitor_sov": competitor_sov,
    }


def calculate_competitor_threats(
    competitor_sov: Dict[str, Dict[str, Any]],
    responses: List[Any],
    brand_name: str
) -> List[Dict[str, Any]]:
    """
    Calculate competitor threat scores using standardized formula.

    THREAT SCORE FORMULA:
    threatScore = (total_mentions * 0.7) + (negative_when_competitor_present * 2) + (positive_competitor * 1.5)

    THREAT LEVELS:
    - High: score > 50 (requires immediate strategic attention)
    - Medium: score 20-50 (requires monitoring)
    - Low: score < 20 (minimal competitive pressure)

    This is the SINGLE SOURCE OF TRUTH for threat calculations.
    Used by: Dashboard, Competitor Threats page, and Report generation.

    Args:
        competitor_sov: Dict from calculate_share_of_voice() with competitor SOV data
        responses: List of Response objects
        brand_name: Name of the brand being analyzed (not currently used)

    Returns:
        List of dicts sorted by threat_score (highest first), each containing:
        - name, mention_count, share_of_voice, competitive_responses,
          negative_overlap, positive_competitor, threat_score, threat_level
    """
    competitor_threats = []

    for comp_name, comp_data in competitor_sov.items():
        # Get all responses where this competitor is mentioned
        competitive_responses = [
            r for r in responses
            if r.competitors and comp_name.lower() in r.competitors.lower()
        ]

        # Count negative sentiment when competitor is present
        # This indicates the competitor is being mentioned in negative contexts
        negative_when_competitor_present = sum(
            1 for r in competitive_responses
            if r.sentiment in ['Negative', 'Very Negative']
        )

        # Count positive sentiment for competitor
        # This indicates the competitor is being recommended positively
        positive_competitor = sum(
            1 for r in competitive_responses
            if r.sentiment in ['Positive', 'Very Positive']
        )

        # Calculate threat score using standardized formula
        mention_count = comp_data.get('count', 0)
        threat_score = (
            (mention_count * THREAT_WEIGHTS["mention_weight"]) +
            (negative_when_competitor_present * THREAT_WEIGHTS["negative_weight"]) +
            (positive_competitor * THREAT_WEIGHTS["positive_weight"])
        )
        threat_score = round(threat_score)

        # Determine threat level based on thresholds
        if threat_score > THREAT_THRESHOLDS["high"]:
            threat_level = 'High'
        elif threat_score > THREAT_THRESHOLDS["medium"]:
            threat_level = 'Medium'
        else:
            threat_level = 'Low'

        competitor_threats.append({
            'name': comp_name,
            'mention_count': mention_count,
            'share_of_voice': comp_data.get('sov', 0.0),
            'competitive_responses': len(competitive_responses),
            'negative_overlap': negative_when_competitor_present,
            'positive_competitor': positive_competitor,
            'threat_score': threat_score,
            'threat_level': threat_level
        })

    # Sort by threat score (highest first)
    competitor_threats.sort(key=lambda x: x['threat_score'], reverse=True)

    return competitor_threats


def get_negative_sentiment_statements(responses: List[Any]) -> List[Dict[str, str]]:
    """
    Extract responses with negative or mixed sentiment about the brand.

    Used for detailed analysis and reporting.

    Args:
        responses: List of Response objects

    Returns:
        List of dicts with query, platform, sentiment, and response text
    """
    negative_responses = [
        r for r in responses
        if r.brand_mentioned in ["Yes", "Indirect"]
        and r.sentiment in ["Negative", "Mixed"]
    ]

    return [
        {
            "query": r.query_text,
            "platform": r.platform,
            "sentiment": r.sentiment,
            "response": r.response_text[:500] + "..." if len(r.response_text) > 500 else r.response_text
        }
        for r in negative_responses[:10]  # Limit to top 10
    ]


# ==================== TIME-SERIES CALCULATIONS ====================

def calculate_brand_mentions_over_time(collections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculate brand mention percentage for each collection over time.

    FILTERS APPLIED:
    - Excludes responses from queries where brand_in_query=True
    - Counts responses where brand_mentioned in ['Yes', 'Indirect']

    Args:
        collections: List of dicts with keys:
            - date: Collection date (string or date object)
            - responses: List of Response objects for that collection
            - queries: List of Query objects for that collection

    Returns:
        List of dicts sorted by date, each containing:
        - date: Collection date (ISO format string)
        - mention_percentage: Percentage of responses mentioning brand (0-100)
        - mention_count: Number of responses mentioning brand
        - total_responses: Total number of responses (excluding branded queries)
    """
    trend_data = []

    for collection in collections:
        date = collection.get('date')
        responses = collection.get('responses', [])
        queries = collection.get('queries', [])

        # Filter out responses from branded queries
        filtered_responses = filter_exclude_branded_queries(responses, queries)

        total = len(filtered_responses)
        if total == 0:
            continue

        # Count mentions (Yes or Indirect)
        mentions = sum(1 for r in filtered_responses if r.brand_mentioned in ['Yes', 'Indirect'])
        mention_percentage = round((mentions / total) * 100) if total > 0 else 0

        trend_data.append({
            'date': date.isoformat() if hasattr(date, 'isoformat') else str(date),
            'mention_percentage': mention_percentage,
            'mention_count': mentions,
            'total_responses': total
        })

    # Sort by date
    trend_data.sort(key=lambda x: x['date'])
    return trend_data


def calculate_positioning_over_time(collections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculate positioning distribution for each collection over time.

    FILTERS APPLIED:
    - Excludes responses from queries where brand_in_query=True
    - Only counts responses where brand_mentioned in ['Yes', 'Indirect']

    Args:
        collections: List of dicts with keys:
            - date: Collection date (string or date object)
            - responses: List of Response objects for that collection
            - queries: List of Query objects for that collection

    Returns:
        List of dicts sorted by date, each containing:
        - date: Collection date (ISO format string)
        - leader: Percentage of Leader positions
        - featured: Percentage of Featured positions
        - listed: Percentage of Listed positions
        - not_mentioned: Percentage of Not Mentioned
        - total_mentions: Total responses counted
    """
    trend_data = []

    for collection in collections:
        date = collection.get('date')
        responses = collection.get('responses', [])
        queries = collection.get('queries', [])

        # Use the same positioning metrics calculation
        positioning = calculate_positioning_metrics(responses, queries)

        if positioning['total'] == 0:
            continue

        trend_data.append({
            'date': date.isoformat() if hasattr(date, 'isoformat') else str(date),
            'leader': positioning['leader_pct'],
            'featured': positioning['featured_pct'],
            'listed': positioning['listed_pct'],
            'not_mentioned': positioning['not_mentioned_pct'],
            'total_mentions': positioning['total']
        })

    # Sort by date
    trend_data.sort(key=lambda x: x['date'])
    return trend_data


def calculate_share_of_voice_over_time(
    collections: List[Dict[str, Any]],
    brand_name: str,
    top_n_competitors: int = 5
) -> List[Dict[str, Any]]:
    """
    Calculate share of voice over time for brand and top competitors.

    FILTERS APPLIED:
    - Excludes responses from queries where brand_in_query=True
    - Counts brand by POSITIONING (Leader, Featured, Listed)

    Args:
        collections: List of dicts with keys:
            - date: Collection date (string or date object)
            - responses: List of Response objects for that collection
            - queries: List of Query objects for that collection
        brand_name: Name of the brand being analyzed
        top_n_competitors: Number of top competitors to include

    Returns:
        List of dicts sorted by date, each containing:
        - date: Collection date (ISO format string)
        - brand_sov: Brand's share of voice percentage
        - competitors: Dict mapping competitor name -> SOV percentage
        - total_mentions: Total mentions counted
    """
    # First pass: identify top N competitors across all time periods
    all_competitor_counts = Counter()

    for collection in collections:
        responses = collection.get('responses', [])
        queries = collection.get('queries', [])

        branded_query_ids = {q.query_id for q in queries if q.brand_in_query}

        for response in responses:
            if response.query_id in branded_query_ids:
                continue

            if response.competitors:
                comp_list = [c.strip() for c in response.competitors.split(',') if c.strip()]
                for comp in comp_list:
                    normalized_name = normalize_organization_name(comp)
                    all_competitor_counts[normalized_name] += 1

    # Get top N competitors
    top_competitors = [name for name, _ in all_competitor_counts.most_common(top_n_competitors)]

    # Second pass: calculate SOV for each time period
    trend_data = []

    for collection in collections:
        date = collection.get('date')
        responses = collection.get('responses', [])
        queries = collection.get('queries', [])

        branded_query_ids = {q.query_id for q in queries if q.brand_in_query}

        total_mentions = 0
        brand_mentions = 0
        competitor_mentions = Counter()

        for response in responses:
            if response.query_id in branded_query_ids:
                continue

            # Count brand mentions by positioning
            if response.brand_position in ['Leader', 'Top 3', 'Featured', 'Listed']:
                brand_mentions += 1
                total_mentions += 1

            # Count competitor mentions (only top N)
            if response.competitors:
                comp_list = [c.strip() for c in response.competitors.split(',') if c.strip()]
                for comp in comp_list:
                    normalized_name = normalize_organization_name(comp)
                    if normalized_name in top_competitors:
                        competitor_mentions[normalized_name] += 1
                        total_mentions += 1

        if total_mentions == 0:
            continue

        # Calculate percentages
        brand_sov = round((brand_mentions / total_mentions) * 100) if total_mentions > 0 else 0

        competitors_sov = {}
        for comp_name in top_competitors:
            count = competitor_mentions.get(comp_name, 0)
            sov = round((count / total_mentions) * 100) if total_mentions > 0 else 0
            competitors_sov[comp_name] = sov

        trend_data.append({
            'date': date.isoformat() if hasattr(date, 'isoformat') else str(date),
            'brand_sov': brand_sov,
            'competitors': competitors_sov,
            'total_mentions': total_mentions
        })

    # Sort by date
    trend_data.sort(key=lambda x: x['date'])
    return trend_data


def calculate_sentiment_over_time(collections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculate sentiment distribution for each collection over time.

    FILTERS APPLIED:
    - Only counts direct mentions (brand_mentioned == 'Yes')
    - NO brand_in_query filtering (sentiment applies to all mentions)

    Args:
        collections: List of dicts with keys:
            - date: Collection date (string or date object)
            - responses: List of Response objects for that collection

    Returns:
        List of dicts sorted by date, each containing:
        - date: Collection date (ISO format string)
        - very_positive: Percentage
        - positive: Percentage
        - neutral: Percentage
        - negative: Percentage
        - very_negative: Percentage
        - mixed: Percentage
        - total_mentions: Total direct mentions counted
    """
    trend_data = []

    for collection in collections:
        date = collection.get('date')
        responses = collection.get('responses', [])

        # Use the same sentiment metrics calculation
        sentiment = calculate_sentiment_metrics(responses)

        if sentiment['total'] == 0:
            continue

        trend_data.append({
            'date': date.isoformat() if hasattr(date, 'isoformat') else str(date),
            'very_positive': sentiment['very_positive_pct'],
            'positive': sentiment['positive_pct'],
            'neutral': sentiment['neutral_pct'],
            'negative': sentiment['negative_pct'],
            'very_negative': sentiment['very_negative_pct'],
            'mixed': sentiment['mixed_pct'],
            'total_mentions': sentiment['total']
        })

    # Sort by date
    trend_data.sort(key=lambda x: x['date'])
    return trend_data
