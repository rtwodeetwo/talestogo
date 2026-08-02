"""
Centralized analytics calculation and caching service.

This module calculates all analytics metrics once and caches them, preventing
redundant calculations across different endpoints (dashboard, analysis pages, reports).
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, case
from typing import Dict, List, Any, Optional, Tuple
import datetime
import json
from datetime import timedelta
from .. import models
from . import metrics, metrics_core, metrics_query


class AnalyticsCache:
    """
    Centralized analytics calculation service that computes all metrics once
    and provides them to different parts of the application.
    """

    def __init__(self, db: Session, user_id: int, brand_id: Optional[int] = None, batch_id: Optional[int] = None,
                 date_from: Optional[datetime.datetime] = None, date_to: Optional[datetime.datetime] = None,
                 default_days: int = 180):
        """
        Initialize AnalyticsCache with optional date filtering.

        Args:
            db: Database session
            user_id: User ID for multi-tenancy
            brand_id: Optional brand ID for multi-brand support
            batch_id: Optional batch ID to filter specific collection
            date_from: Optional start date for filtering (inclusive)
            date_to: Optional end date for filtering (inclusive)
            default_days: Default lookback period in days if no dates specified (default: 180)
        """
        self.db = db
        self.user_id = user_id
        self.brand_id = brand_id
        self.batch_id = batch_id
        self._cache: Dict[str, Any] = {}
        self._calculated = False
        self._resolved_population = None

        # Date filtering with configurable default window
        if date_to is None:
            self.date_to = datetime.datetime.utcnow()
        else:
            self.date_to = date_to

        if date_from is None and default_days > 0:
            # Default to looking back N days from date_to
            self.date_from = self.date_to - timedelta(days=default_days)
        else:
            self.date_from = date_from

    def _population(self):
        """Resolve this cache's scope as a canonical MetricPopulation.

        Memoized: several calculations need it and resolving is a query.
        """
        if getattr(self, '_resolved_population', None) is None:
            if self.batch_id is not None:
                scope = metrics_query.MetricScope.for_batch(
                    self.user_id, self.brand_id, self.batch_id)
            else:
                scope = metrics_query.MetricScope(
                    owner_user_id=self.user_id,
                    brand_id=self.brand_id,
                    start=self.date_from,
                    end=self.date_to,
                )
            self._resolved_population = metrics_query.resolve(self.db, scope)
        return self._resolved_population

    def _apply_filters(self, query, include_brand_in_query: bool = True):
        """
        Apply user, brand, batch, and date filters to a query.

        Args:
            query: SQLAlchemy query to filter
            include_brand_in_query: If False, exclude queries where brand_in_query=True
        """
        # Apply user, brand, and batch filters first
        query = query.filter(models.Response.user_id == self.user_id)
        if self.brand_id:
            query = query.filter(models.Response.brand_id == self.brand_id)
        if self.batch_id:
            query = query.filter(models.Response.batch_id == self.batch_id)

        # Apply date range filtering (if not filtering by specific batch)
        # Batch filtering takes precedence over date filtering
        if not self.batch_id:
            if self.date_from:
                query = query.filter(models.Response.timestamp >= self.date_from)
            if self.date_to:
                query = query.filter(models.Response.timestamp <= self.date_to)

        # Only try to filter by brand_in_query if Query table has data
        if not include_brand_in_query:
            # Check if any queries exist for this user/brand
            query_count = self.db.query(func.count(models.Query.id)).filter(
                models.Query.user_id == self.user_id
            )
            if self.brand_id:
                query_count = query_count.filter(models.Query.brand_id == self.brand_id)

            if query_count.scalar() > 0:
                # Queries exist, so we can filter by brand_in_query
                query = query.join(
                    models.Query,
                    (models.Response.query_id == models.Query.query_id) &
                    (models.Response.user_id == models.Query.user_id) &
                    (models.Response.brand_id == models.Query.brand_id),
                    isouter=False  # INNER JOIN
                ).filter(
                    models.Query.brand_in_query == False
                )
            # If no queries exist, don't filter - show all responses

        return query

    def calculate_all(self) -> Dict[str, Any]:
        """
        Calculate all analytics metrics at once and cache the results.

        Returns a comprehensive dictionary containing:
        - Basic counts (total responses, mentions, etc.)
        - Mention metrics (rate, trend, positioning breakdown)
        - Sentiment metrics (breakdown, positive rate, etc.)
        - Descriptor metrics (match rate, top performers)
        - Share of voice metrics
        - Competitive metrics
        - Trend data (30-day trends)
        """
        if self._calculated:
            return self._cache

        # Calculate all base counts
        self._calculate_base_counts()

        # Calculate mention metrics
        self._calculate_mention_metrics()

        # Calculate sentiment metrics
        self._calculate_sentiment_metrics()

        # Calculate descriptor metrics
        self._calculate_descriptor_metrics()

        # Calculate share of voice
        self._calculate_share_of_voice()

        # Calculate positioning breakdown
        self._calculate_positioning_breakdown()

        # Calculate trend data
        self._calculate_trends()

        self._calculated = True
        return self._cache

    def _calculate_base_counts(self):
        """Calculate base counts that are used across multiple metrics."""
        # Total responses (excluding brand_in_query for mention-based metrics)
        self._cache['total_responses_for_mentions'] = self._apply_filters(
            self.db.query(func.count(models.Response.id)),
            include_brand_in_query=False
        ).scalar() or 0

        # Total responses (including all for sentiment/descriptor metrics)
        self._cache['total_responses_all'] = self._apply_filters(
            self.db.query(func.count(models.Response.id)),
            include_brand_in_query=True
        ).scalar() or 0

        # Total mentions (excluding brand_in_query)
        self._cache['total_mentions_for_positioning'] = self._apply_filters(
            self.db.query(func.count(models.Response.id)).filter(
                models.Response.brand_mentioned.in_(['Yes', 'Indirect'])
            ),
            include_brand_in_query=False
        ).scalar() or 0

        # Total mentions (including all)
        self._cache['total_mentions_all'] = self._apply_filters(
            self.db.query(func.count(models.Response.id)).filter(
                models.Response.brand_mentioned.in_(['Yes', 'Indirect'])
            ),
            include_brand_in_query=True
        ).scalar() or 0

    def _calculate_mention_metrics(self):
        """Calculate mention-related metrics (excludes brand_in_query)."""
        total = self._cache['total_responses_for_mentions']
        mentions = self._cache['total_mentions_for_positioning']

        self._cache['mention_rate'] = round((mentions / total * 100)) if total > 0 else 0
        self._cache['mention_count'] = mentions

    def _calculate_sentiment_metrics(self):
        """Sentiment metrics, from the canonical definition.

        The rate previously divided a Yes-only numerator by a Yes+Indirect
        denominator (total_mentions_all), which systematically understated it:
        Indirect mentions carry no sentiment, so they inflated the denominator
        without ever contributing to the numerator. On the golden fixture that
        read 41.9% where the true figure is 65.0%.

        This path feeds the month-over-month and quarter-over-quarter dashboard
        modes, so leaving it would have meant the same brand and period showing
        one sentiment in batch mode and another in period mode.
        """
        population = self._population()

        positive = metrics_core.positive_sentiment_rate(population)
        distribution = metrics_core.sentiment_distribution(population)

        self._cache['positive_sentiment_rate'] = (
            positive.value if positive.value is not None else 0.0)
        self._cache['positive_sentiment_count'] = int(positive.numerator)
        self._cache['sentiment_breakdown'] = {
            label: int(value.numerator)
            for label, value in distribution.items()
            if value.numerator
        }

    def _calculate_descriptor_metrics(self):
        """Descriptor match metrics, from the canonical definition.

        Two corrections over the previous implementation:

        * Matching was bidirectional substring, so a target of "AI" matched a
          response descriptor of "explainable AI" and vice versa. The canonical
          rule is case-insensitive exact on comma-split tokens.
        * Per-descriptor counts were keyed on the raw string, so
          "high-temperature plasma" and "High-Temperature Plasma" occupied
          separate rows. They are case-folded now.

        The old per-descriptor match_rate could also exceed 100%: it summed
        response_count once per matching target, double-counting a response that
        matched two targets. It is now the share of mentioning answers that used
        the descriptor.
        """
        population = self._population()

        match = metrics_core.descriptor_match_rate(population)
        total_target_descriptors = int(match.denominator)

        if total_target_descriptors == 0:
            self._cache['descriptor_match_rate'] = 0.0
            self._cache['matched_descriptors_count'] = 0
            self._cache['total_target_descriptors'] = 0
            self._cache['top_descriptors'] = []
            self._cache['descriptor_counts'] = {}
            return

        descriptor_counts = metrics_core.descriptor_frequency(population)
        mentioning = sum(1 for row in population.analyzed_rows() if row.is_mentioned)

        top_descriptors = [
            {
                'descriptor': name,
                'count': count,
                'match_rate': round(count / mentioning * 100, 1) if mentioning else 0,
            }
            for name, count in list(descriptor_counts.items())[:10]
        ]

        self._cache['descriptor_match_rate'] = match.value if match.value is not None else 0.0
        self._cache['matched_descriptors_count'] = int(match.numerator)
        self._cache['total_target_descriptors'] = total_target_descriptors
        self._cache['top_descriptors'] = top_descriptors
        self._cache['descriptor_counts'] = descriptor_counts

    def _calculate_share_of_voice(self):
        """Share of voice, from the canonical definition.

        Delegates to metrics_core so the Share of Voice page and the Dashboard
        tile cannot disagree. The previous implementation counted competitors
        only inside answers where the brand was already mentioned, then labelled
        the result as a share of the whole corpus: a competitor named in an
        answer the brand never appeared in was invisible, which structurally
        inflated the brand's share. On the golden fixture that read 75.9% where
        the true figure is 55.0%. It also skipped organization-name
        normalization, so the same competitor could appear as several rows here
        while being merged everywhere else.
        """
        population = self._population()
        brand_name = population.brand_name or "Your Brand"

        brand_share, competitor_shares = metrics_core.share_of_voice(population)
        leadership = metrics_core.leadership_visibility(population)
        positions = metrics_core.positioning_distribution(population)

        sov_list = [{
            'organization': brand_name,
            'mention_count': int(brand_share.numerator),
            'total_mentions': int(brand_share.numerator),
            'percentage': brand_share.value if brand_share.value is not None else 0.0,
            'share_of_voice': brand_share.value if brand_share.value is not None else 0.0,
            'leadership_visibility': leadership.value if leadership.value is not None else 0.0,
            'leader_count': int(positions['Leader'].numerator),
            # Top 3 is reported with Featured here because the page has no
            # separate column for it; it is stored and charted separately.
            'featured_count': int(positions['Featured'].numerator
                                  + positions['Top 3'].numerator),
            'is_brand': True,
        }]

        for name, value in competitor_shares.items():
            if name == brand_name:
                continue
            sov_list.append({
                'organization': name,
                'mention_count': int(value.numerator),
                'total_mentions': int(value.numerator),
                'percentage': value.value if value.value is not None else 0.0,
                'share_of_voice': value.value if value.value is not None else 0.0,
                # Competitor positioning is not captured during analysis.
                'leadership_visibility': 0.0,
                'leader_count': 0,
                'featured_count': 0,
                'is_brand': False,
            })

        sov_list.sort(key=lambda x: x['percentage'], reverse=True)

        self._cache['share_of_voice'] = brand_share.value if brand_share.value is not None else 0.0
        self._cache['share_of_voice_breakdown'] = sov_list

    def _calculate_positioning_breakdown(self):
        """Calculate positioning breakdown (excludes brand_in_query)."""
        positioning_data = self._apply_filters(
            self.db.query(
                models.Response.brand_position,
                func.count(models.Response.id).label('count')
            ).filter(
                models.Response.brand_mentioned.in_(['Yes', 'Indirect'])
            ).group_by(models.Response.brand_position),
            include_brand_in_query=False
        ).all()

        positioning_breakdown = {position: count for position, count in positioning_data if position}

        # Most common positioning
        leading_position = max(positioning_breakdown.items(), key=lambda x: x[1])[0] if positioning_breakdown else "N/A"

        self._cache['positioning_breakdown'] = positioning_breakdown
        self._cache['leading_position'] = leading_position

    def _calculate_trends(self):
        """
        Calculate trend data by comparing the two most recent collection batches.

        IMPORTANT: This calculates metrics directly from Response data (not BatchAnalytics)
        to ensure values match the current dashboard metrics and avoid stale data issues.
        """
        # Get the two most recent CollectionBatch records for this user/brand
        batch_query = self.db.query(models.CollectionBatch).filter(
            models.CollectionBatch.user_id == self.user_id,
            models.CollectionBatch.status == 'completed'
        )
        if self.brand_id:
            batch_query = batch_query.filter(
                models.CollectionBatch.brand_id == self.brand_id
            )

        # Order by started_at descending to get most recent first
        recent_batches = batch_query.order_by(
            models.CollectionBatch.started_at.desc()
        ).limit(2).all()

        if len(recent_batches) < 2:
            # Not enough batches for comparison
            self._cache['trends'] = {
                'mention_rate_change': 0,
                'sentiment_change': 0,
                'descriptor_change': 0,
                'share_of_voice_change': 0,
                'high_threat_change': None,
                'leadership_visibility_change': 0
            }
            return

        # Helper function to calculate metrics for a specific batch directly from Response data
        def calculate_batch_metrics(batch_id: int) -> dict:
            """Calculate all trend metrics for a batch directly from Response data."""
            # Base query for this batch
            base_query = self.db.query(models.Response).filter(
                models.Response.batch_id == batch_id,
                models.Response.user_id == self.user_id
            )
            if self.brand_id:
                base_query = base_query.filter(models.Response.brand_id == self.brand_id)

            # Check if Query table has data for brand_in_query filtering
            query_count = self.db.query(func.count(models.Query.id)).filter(
                models.Query.user_id == self.user_id
            )
            if self.brand_id:
                query_count = query_count.filter(models.Query.brand_id == self.brand_id)
            has_queries = query_count.scalar() > 0

            # For mention rate: exclude brand_in_query responses
            if has_queries:
                mention_base = base_query.join(
                    models.Query,
                    (models.Response.query_id == models.Query.query_id) &
                    (models.Response.user_id == models.Query.user_id) &
                    (models.Response.brand_id == models.Query.brand_id),
                    isouter=False
                ).filter(models.Query.brand_in_query == False)
            else:
                mention_base = base_query

            # Total responses for mention calculation
            total_responses = mention_base.count()

            # Mentions (Yes or Indirect)
            mentions = mention_base.filter(
                models.Response.brand_mentioned.in_(['Yes', 'Indirect'])
            ).count()

            mention_rate = (mentions / total_responses * 100) if total_responses > 0 else 0

            # For sentiment: include all responses
            all_responses = base_query.filter(
                models.Response.brand_mentioned == 'Yes'
            ).all()

            # Sentiment counts
            sentiment_counts = {'Very Positive': 0, 'Positive': 0, 'Neutral': 0,
                              'Mixed': 0, 'Negative': 0, 'Very Negative': 0}
            for r in all_responses:
                if r.sentiment in sentiment_counts:
                    sentiment_counts[r.sentiment] += 1

            total_with_sentiment = sum(sentiment_counts.values())
            positive_count = sentiment_counts['Very Positive'] + sentiment_counts['Positive']
            sentiment_rate = (positive_count / total_with_sentiment * 100) if total_with_sentiment > 0 else 0

            # Descriptor match rate
            target_descriptors_query = self.db.query(models.TargetDescriptor).filter(
                models.TargetDescriptor.user_id == self.user_id,
                models.TargetDescriptor.is_target == True
            )
            if self.brand_id:
                target_descriptors_query = target_descriptors_query.filter(
                    models.TargetDescriptor.brand_id == self.brand_id
                )
            target_descriptors = target_descriptors_query.all()
            total_target_descriptors = len(target_descriptors)

            descriptor_rate = 0.0
            if total_target_descriptors > 0:
                target_desc_lower = {td.descriptor.lower(): td.descriptor for td in target_descriptors}
                matched_descriptors = set()

                # Get responses with descriptors for this batch
                responses_with_desc = base_query.filter(
                    models.Response.brand_mentioned.in_(['Yes', 'Indirect']),
                    models.Response.descriptors.isnot(None),
                    models.Response.descriptors != ''
                ).all()

                for r in responses_with_desc:
                    if r.descriptors:
                        response_descriptors = [d.strip().lower() for d in r.descriptors.split(',')]
                        for target_lower, target_original in target_desc_lower.items():
                            if any(target_lower in resp_desc or resp_desc in target_lower
                                   for resp_desc in response_descriptors):
                                matched_descriptors.add(target_original)

                descriptor_rate = (len(matched_descriptors) / total_target_descriptors * 100)

            # Share of voice calculation
            brand = self.db.query(models.BrandInfo).filter(
                models.BrandInfo.user_id == self.user_id
            )
            if self.brand_id:
                brand = brand.filter(models.BrandInfo.id == self.brand_id)
            brand = brand.first()
            brand_name = brand.brand_name if brand else "Your Brand"

            # Get responses with mentions for SOV (excluding brand_in_query)
            sov_responses = mention_base.filter(
                models.Response.brand_mentioned.in_(['Yes', 'Indirect'])
            ).all()

            # Count brand mentions
            brand_mentions = len(sov_responses)

            # Count competitor mentions
            competitor_counts = {}
            for r in sov_responses:
                if r.competitors:
                    competitors = [c.strip() for c in r.competitors.split(',')]
                    for comp in competitors:
                        if comp and comp != brand_name:
                            competitor_counts[comp] = competitor_counts.get(comp, 0) + 1

            total_mentions = brand_mentions + sum(competitor_counts.values())
            share_of_voice = (brand_mentions / total_mentions * 100) if total_mentions > 0 else 0

            # High threat count
            high_threat_count = 0
            for comp_name, comp_mention_count in competitor_counts.items():
                # Get responses where this competitor is mentioned
                competitive_responses = [
                    r for r in sov_responses
                    if r.competitors and comp_name.lower() in r.competitors.lower()
                ]

                # Count sentiment-based threat components
                negative_when_competitor = sum(
                    1 for r in competitive_responses
                    if r.sentiment in ['Negative', 'Very Negative']
                )
                positive_competitor = sum(
                    1 for r in competitive_responses
                    if r.sentiment in ['Positive', 'Very Positive']
                )

                # Calculate threat score
                threat_score = (
                    (comp_mention_count * 0.7) +
                    (negative_when_competitor * 2.0) +
                    (positive_competitor * 1.5)
                )

                if threat_score > 50:  # High threat threshold
                    high_threat_count += 1

            # Leadership visibility calculation
            # Get all queries for brand_in_query filtering
            queries = self.db.query(models.Query).filter(
                models.Query.user_id == self.user_id
            )
            if self.brand_id:
                queries = queries.filter(models.Query.brand_id == self.brand_id)
            queries = queries.all()

            # Build set of query_ids where brand_in_query=True to exclude
            branded_query_ids = {q.query_id for q in queries if q.brand_in_query}

            # Get all responses for this batch (not just mentions)
            all_batch_responses = base_query.all()

            # Filter responses: exclude branded queries
            filtered_responses = [
                r for r in all_batch_responses
                if r.query_id not in branded_query_ids
            ]

            total_for_lv = len(filtered_responses)
            if total_for_lv > 0:
                # Count Leader and Featured positions
                leadership_count = sum(
                    1 for r in filtered_responses
                    if r.brand_position in ['Leader', 'Top 3', 'Featured']
                )
                leadership_visibility = (leadership_count / total_for_lv) * 100
            else:
                leadership_visibility = 0.0

            return {
                'mention_rate': mention_rate,
                'sentiment_rate': sentiment_rate,
                'descriptor_rate': descriptor_rate,
                'share_of_voice': share_of_voice,
                'high_threat_count': high_threat_count,
                'leadership_visibility': leadership_visibility
            }

        # Calculate metrics for both batches
        recent_metrics = calculate_batch_metrics(recent_batches[0].id)
        prev_metrics = calculate_batch_metrics(recent_batches[1].id)

        # Calculate changes (recent - previous)
        mention_rate_change = recent_metrics['mention_rate'] - prev_metrics['mention_rate']
        sentiment_change = recent_metrics['sentiment_rate'] - prev_metrics['sentiment_rate']
        descriptor_change = recent_metrics['descriptor_rate'] - prev_metrics['descriptor_rate']
        share_of_voice_change = recent_metrics['share_of_voice'] - prev_metrics['share_of_voice']
        high_threat_change = recent_metrics['high_threat_count'] - prev_metrics['high_threat_count']
        leadership_visibility_change = recent_metrics['leadership_visibility'] - prev_metrics['leadership_visibility']

        self._cache['trends'] = {
            'mention_rate_change': round(mention_rate_change),
            'sentiment_change': round(sentiment_change),
            'descriptor_change': round(descriptor_change),
            'share_of_voice_change': round(share_of_voice_change),
            'high_threat_change': high_threat_change,
            'leadership_visibility_change': round(leadership_visibility_change)
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data specifically formatted for the dashboard."""
        if not self._calculated:
            self.calculate_all()

        return {
            'mention_rate': round(self._cache.get('mention_rate', 0), 2),
            'mention_count': self._cache.get('mention_count', 0),
            'total_responses': self._cache.get('total_responses_for_mentions', 0),
            'positive_sentiment': round(self._cache.get('positive_sentiment_rate', 0), 2),
            'descriptor_match': round(self._cache.get('descriptor_match_rate', 0), 2),
            'share_of_voice': round(self._cache.get('share_of_voice', 0), 2),
            'change_mention_rate': self._cache.get('trends', {}).get('mention_rate_change', 0),
            'change_sentiment': self._cache.get('trends', {}).get('sentiment_change', 0),
            'change_descriptor': self._cache.get('trends', {}).get('descriptor_change', 0),
            'change_share_of_voice': self._cache.get('trends', {}).get('share_of_voice_change', 0),
            'change_high_threats': self._cache.get('trends', {}).get('high_threat_change'),
            'change_leadership_visibility': self._cache.get('trends', {}).get('leadership_visibility_change', 0),
            'leading_position': self._cache.get('leading_position', 'N/A')
        }

    def get_sentiment_data(self) -> Dict[str, Any]:
        """Get data specifically formatted for sentiment analysis page."""
        if not self._calculated:
            self.calculate_all()

        breakdown = self._cache.get('sentiment_breakdown', {})
        total = sum(breakdown.values())

        # Get negative statements for detailed review
        negative_responses = self._apply_filters(
            self.db.query(models.Response).filter(
                models.Response.brand_mentioned == 'Yes',
                models.Response.sentiment.in_(['Negative', 'Very Negative'])
            ),
            include_brand_in_query=True
        ).all()

        negative_statements = [
            {
                'query': resp.query_text or 'Unknown',
                'platform': resp.platform,
                'text': resp.response_text
            }
            for resp in negative_responses
        ]

        # Generate insights for each sentiment category
        sentiment_insights = {}
        for sentiment_name, count in breakdown.items():
            percentage = round((count / total * 100) if total > 0 else 0)

            # Create contextual insights based on sentiment type and percentage
            if sentiment_name == 'Very Positive':
                if percentage > 30:
                    insight = f"Strong positive sentiment: {count} mentions ({percentage}%) show your brand is being described in highly favorable terms. This indicates strong brand reputation."
                elif percentage > 10:
                    insight = f"Good positive sentiment: {count} mentions ({percentage}%) are very positive. Continue reinforcing the narratives that generate this strong response."
                else:
                    insight = f"{count} mentions ({percentage}%) are very positive. Consider amplifying the factors that drive this exceptional sentiment."

            elif sentiment_name == 'Positive':
                if percentage > 40:
                    insight = f"Dominant positive sentiment: {count} mentions ({percentage}%) are positive. Your brand messaging is resonating well."
                elif percentage > 20:
                    insight = f"Healthy positive sentiment: {count} mentions ({percentage}%) show favorable brand perception."
                else:
                    insight = f"{count} mentions ({percentage}%) are positive. Opportunity to increase positive sentiment through targeted messaging."

            elif sentiment_name == 'Neutral':
                if percentage > 50:
                    insight = f"High neutral sentiment: {count} mentions ({percentage}%) are neutral. This suggests opportunities to strengthen brand differentiation and emotional connection."
                elif percentage > 30:
                    insight = f"Moderate neutral sentiment: {count} mentions ({percentage}%). Consider emphasizing unique value propositions to shift sentiment more positive."
                else:
                    insight = f"{count} mentions ({percentage}%) are neutral. Relatively low neutral sentiment suggests clear brand perception."

            elif sentiment_name == 'Mixed':
                if percentage > 20:
                    insight = f"High mixed sentiment: {count} mentions ({percentage}%) contain both positive and negative elements. Review these for nuanced brand positioning opportunities."
                else:
                    insight = f"{count} mentions ({percentage}%) show mixed sentiment, indicating both strengths and areas for improvement are being recognized."

            elif sentiment_name == 'Negative':
                if percentage > 15:
                    insight = f"Concerning negative sentiment: {count} mentions ({percentage}%) are negative. Priority action needed to address perception issues. Review negative statements below for specific concerns."
                elif percentage > 5:
                    insight = f"Moderate negative sentiment: {count} mentions ({percentage}%). Monitor and address the specific issues mentioned in these responses."
                else:
                    insight = f"Low negative sentiment: {count} mentions ({percentage}%). While concerning, this represents a small portion of overall mentions."

            elif sentiment_name == 'Very Negative':
                if count > 0:
                    insight = f"Critical: {count} mentions ({percentage}%) are very negative. Immediate attention required. Review these statements to identify and address serious perception issues."
                else:
                    insight = "No very negative mentions detected."
            else:
                insight = f"{count} mentions ({percentage}%)"

            # Use lowercase with underscores for the key (matching frontend expectations)
            key = sentiment_name.lower().replace(' ', '_')
            sentiment_insights[key] = insight

        return {
            'positive_rate': round(self._cache.get('positive_sentiment_rate', 0), 2),
            'breakdown': breakdown,
            'total_mentions': self._cache.get('total_mentions_all', 0),
            # Total count
            'total': total,
            # Raw counts (for SentimentAnalysis.tsx)
            'very_positive': breakdown.get('Very Positive', 0),
            'positive': breakdown.get('Positive', 0),
            'neutral': breakdown.get('Neutral', 0),
            'mixed': breakdown.get('Mixed', 0),
            'negative': breakdown.get('Negative', 0),
            'very_negative': breakdown.get('Very Negative', 0),
            # Percentage fields (for Dashboard.tsx)
            'very_positive_pct': round((breakdown.get('Very Positive', 0) / total * 100) if total > 0 else 0, 2),
            'positive_pct': round((breakdown.get('Positive', 0) / total * 100) if total > 0 else 0, 2),
            'neutral_pct': round((breakdown.get('Neutral', 0) / total * 100) if total > 0 else 0, 2),
            'mixed_pct': round((breakdown.get('Mixed', 0) / total * 100) if total > 0 else 0, 2),
            'negative_pct': round((breakdown.get('Negative', 0) / total * 100) if total > 0 else 0, 2),
            'very_negative_pct': round((breakdown.get('Very Negative', 0) / total * 100) if total > 0 else 0, 2),
            # Additional data for Sentiment Analysis page
            'sentiment_insights': sentiment_insights,
            'negative_statements': negative_statements,
        }

    def get_descriptor_data(self) -> List[Dict[str, Any]]:
        """Get data specifically formatted for descriptor performance page."""
        if not self._calculated:
            self.calculate_all()

        return self._cache.get('top_descriptors', [])

    def get_share_of_voice_data(self) -> List[Dict[str, Any]]:
        """Get data specifically formatted for share of voice page."""
        if not self._calculated:
            self.calculate_all()

        return self._cache.get('share_of_voice_breakdown', [])

    def get_positioning_data(self) -> Dict[str, Any]:
        """Get data specifically formatted for positioning breakdown page."""
        if not self._calculated:
            self.calculate_all()

        breakdown = self._cache.get('positioning_breakdown', {})
        total = sum(breakdown.values())

        # Combine "Top 3" into "Featured" for consistent display
        # This matches the Leadership Visibility calculation which counts Leader + Featured + Top 3
        featured_combined = breakdown.get('Featured', 0) + breakdown.get('Top 3', 0)

        # Return format expected by dashboard
        return {
            'total': total,
            'leader': breakdown.get('Leader', 0),
            'top_3': breakdown.get('Top 3', 0),  # Keep for backward compatibility
            'featured': featured_combined,  # Combined Featured + Top 3
            'listed': breakdown.get('Listed', 0),
            'not_mentioned': breakdown.get('Not Mentioned', 0),
            # Also include the detailed breakdown for other pages
            'breakdown': {
                position: {
                    'count': count,
                    'percentage': round((count / total * 100) if total > 0 else 0)
                }
                for position, count in breakdown.items()
            }
        }

    def invalidate(self):
        """Clear the cache to force recalculation."""
        self._cache = {}
        self._calculated = False
