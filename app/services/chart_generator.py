"""
Chart generation service for TALES reports.
Generates PNG charts for inclusion in markdown reports.
"""

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server-side rendering
import matplotlib.pyplot as plt
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

# Set style for professional-looking charts
plt.style.use('seaborn-v0_8-whitegrid')

# Modern, professional color palette inspired by data visualization best practices
COLORS = {
    'primary': '#5B8DEE',      # Professional blue
    'secondary': '#7C5CDB',    # Purple
    'success': '#00C48C',      # Emerald green (Very Positive sentiment)
    'positive': '#4ECB71',     # Light green (Positive sentiment)
    'warning': '#FFA26B',      # Soft orange
    'danger': '#FF6B9D',       # Soft red (Negative sentiment)
    'very_negative': '#E74C3C', # Bright red (Very Negative sentiment)
    'neutral': '#95AAC9',      # Soft blue-gray (Neutral sentiment)
    'mixed': '#C5A3FF',        # Light purple (Mixed sentiment)
    'palette': ['#5B8DEE', '#7C5CDB', '#00C48C', '#4ECB71', '#FFA26B', '#FF6B9D', '#95AAC9', '#FFD93D']
}

# Chart styling configuration
CHART_CONFIG = {
    'figure_facecolor': '#FFFFFF',
    'axes_facecolor': '#F8F9FA',
    'grid_color': '#E1E8ED',
    'grid_alpha': 0.6,
    'title_size': 18,
    'label_size': 13,
    'tick_size': 11,
    'legend_size': 11,
    'dpi': 300
}


def ensure_charts_directory():
    """Ensure the charts output directory exists."""
    charts_dir = "frontend/public/report_charts"
    if not os.path.exists(charts_dir):
        os.makedirs(charts_dir)
    return charts_dir


def check_for_uploaded_charts(user_id: int, brand_id: int, max_age_minutes: int = 60) -> Dict[str, str]:
    """
    Check for uploaded chart images from frontend.
    Returns a dictionary of chart_name -> filepath for any uploaded charts found.

    Args:
        user_id: User ID who generated the charts
        brand_id: Brand ID for the charts
        max_age_minutes: Maximum age of charts in minutes (default 60)

    Returns:
        Dict mapping chart names to file paths
    """
    uploaded_charts = {}
    charts_dir = Path("frontend/public/report_charts")

    if not charts_dir.exists():
        return uploaded_charts

    # Mapping from chart names used in frontend to chart names used in report generation
    # Frontend uses: dashboard, sentiment, positioning, share_of_voice
    # Report uses: mention_rate (for dashboard), sentiment, positioning, share_of_voice
    chart_mappings = {
        'dashboard': 'mention_rate',  # Dashboard chart maps to mention_rate in reports
        'sentiment': 'sentiment',
        'positioning': 'positioning',
        'share_of_voice': 'share_of_voice'
    }

    for frontend_name, report_name in chart_mappings.items():
        # Look for uploaded chart with pattern: {user_id}_{brand_id}_latest_{chart_name}.png
        filename = f"{user_id}_{brand_id}_latest_{frontend_name}.png"
        filepath = charts_dir / filename

        if filepath.exists():
            # Check file age
            file_age_seconds = (datetime.now().timestamp() - filepath.stat().st_mtime)
            file_age_minutes = file_age_seconds / 60

            if file_age_minutes <= max_age_minutes:
                # Use relative path for markdown
                uploaded_charts[report_name] = str(filepath)
                print(f"  - Using uploaded {report_name} chart from frontend (age: {file_age_minutes:.1f} minutes)")

    return uploaded_charts


def generate_mention_rate_pie_chart(mention_metrics: Dict[str, Any], brand_name: str, output_path: str) -> str:
    """
    Generate a pie chart showing brand mention rates.
    Returns the file path of the generated chart.
    """
    labels = ['Explicit Mention', 'Indirect Mention', 'Not Mentioned']
    sizes = [mention_metrics['yes'], mention_metrics['indirect'], mention_metrics['no']]
    colors = [COLORS['success'], COLORS['warning'], COLORS['danger']]
    explode = (0.05, 0, 0)  # Explode the first slice

    fig, ax = plt.subplots(figsize=(10, 7))
    wedges, texts, autotexts = ax.pie(
        sizes,
        explode=explode,
        labels=labels,
        colors=colors,
        autopct='%1.1f%%',
        startangle=90,
        textprops={'fontsize': 12, 'weight': 'bold'}
    )

    # Make percentage text white and bold
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontsize(14)
        autotext.set_weight('bold')

    ax.set_title(f'{brand_name} Mention Rate in AI Responses', fontsize=16, weight='bold', pad=20)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_positioning_bar_chart(positioning_metrics: Dict[str, Any], brand_name: str, output_path: str) -> str:
    """
    Generate a bar chart showing brand positioning distribution.
    Returns the file path of the generated chart.
    """
    # `top_3` is optional: metrics.calculate_positioning_metrics folds Top 3 into
    # `featured` and never emits the key, which used to raise KeyError here. The
    # exception was swallowed by the caller, so the positioning bar chart was
    # silently absent from every generated report.
    positions = ['Leader', 'Top 3', 'Featured', 'Listed', 'Not Mentioned']
    counts = [
        positioning_metrics.get('leader', 0),
        positioning_metrics.get('top_3', 0),
        positioning_metrics.get('featured', 0),
        positioning_metrics.get('listed', 0),
        positioning_metrics.get('not_mentioned', 0)
    ]

    colors_map = [COLORS['success'], COLORS['primary'], COLORS['secondary'], COLORS['warning'], COLORS['danger']]

    fig, ax = plt.subplots(figsize=(12, 7), facecolor=CHART_CONFIG['figure_facecolor'])
    ax.set_facecolor(CHART_CONFIG['axes_facecolor'])

    bars = ax.bar(positions, counts, color=colors_map, edgecolor='white', linewidth=2.5, alpha=0.9)

    # Add value labels on top of bars with better styling
    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}',
                    ha='center', va='bottom', fontsize=CHART_CONFIG['label_size'],
                    weight='bold', color='#2C3E50')

    ax.set_ylabel('Number of Responses', fontsize=CHART_CONFIG['label_size'], weight='bold', color='#2C3E50')
    ax.set_xlabel('Positioning Category', fontsize=CHART_CONFIG['label_size'], weight='bold', color='#2C3E50')
    ax.set_title(f'{brand_name} Positioning in AI Responses',
                fontsize=CHART_CONFIG['title_size'], weight='bold', pad=20, color='#2C3E50')

    # Improve grid styling
    ax.grid(axis='y', alpha=CHART_CONFIG['grid_alpha'], linestyle='--',
           color=CHART_CONFIG['grid_color'], linewidth=1)
    ax.set_axisbelow(True)

    # Style tick labels
    ax.tick_params(axis='both', labelsize=CHART_CONFIG['tick_size'], colors='#2C3E50')
    plt.xticks(rotation=15, ha='right')

    # Remove top and right spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#D1D8E0')
    ax.spines['bottom'].set_color('#D1D8E0')

    plt.tight_layout()
    plt.savefig(output_path, dpi=CHART_CONFIG['dpi'], bbox_inches='tight')
    plt.close()

    return output_path


def generate_sentiment_pie_chart(sentiment_metrics: Dict[str, Any], brand_name: str, output_path: str) -> str:
    """
    Generate a modern donut chart showing sentiment distribution.
    Returns the file path of the generated chart.
    """
    labels = ['Very Positive', 'Positive', 'Neutral', 'Negative', 'Mixed']
    sizes = [
        sentiment_metrics['very_positive'],
        sentiment_metrics['positive'],
        sentiment_metrics['neutral'],
        sentiment_metrics['negative'],
        sentiment_metrics['mixed']
    ]

    # Filter out zero values
    filtered_data = [(label, size) for label, size in zip(labels, sizes) if size > 0]
    if not filtered_data:
        return None

    labels, sizes = zip(*filtered_data)
    colors = [COLORS['success'], COLORS['positive'], COLORS['neutral'], COLORS['danger'], COLORS['mixed']][:len(labels)]

    # Create modern donut chart
    fig, ax = plt.subplots(figsize=(10, 8), facecolor=CHART_CONFIG['figure_facecolor'])
    ax.set_facecolor(CHART_CONFIG['axes_facecolor'])

    # Create donut chart
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        autopct='%1.1f%%',
        startangle=90,
        textprops={'fontsize': CHART_CONFIG['label_size'], 'weight': 'bold'},
        pctdistance=0.85,
        wedgeprops=dict(width=0.5, edgecolor='white', linewidth=3)  # Donut style with white borders
    )

    # Style the labels
    for text in texts:
        text.set_fontsize(CHART_CONFIG['label_size'])
        text.set_weight('bold')
        text.set_color('#2C3E50')

    # Style the percentage labels
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontsize(CHART_CONFIG['label_size'])
        autotext.set_weight('bold')

    # Add center circle for donut effect with total count
    total = sum(sizes)
    centre_circle = plt.Circle((0, 0), 0.35, fc=CHART_CONFIG['axes_facecolor'], linewidth=0)
    ax.add_artist(centre_circle)
    ax.text(0, 0, f'{total}\nResponses', ha='center', va='center',
            fontsize=16, weight='bold', color='#2C3E50')

    ax.set_title(f'{brand_name} Sentiment Distribution',
                fontsize=CHART_CONFIG['title_size'], weight='bold', pad=20, color='#2C3E50')

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()

    return output_path


def generate_platform_comparison_chart(platform_metrics: Dict[str, Dict[str, Any]], brand_name: str, output_path: str) -> str:
    """
    Generate a grouped bar chart comparing performance across platforms.
    Returns the file path of the generated chart.
    """
    platforms = [p for p, m in platform_metrics.items() if m['total'] > 0]

    if not platforms:
        return None

    mention_rates = [platform_metrics[p]['mention']['yes_pct'] for p in platforms]
    positive_sentiment = [
        platform_metrics[p]['sentiment']['positive_pct'] + platform_metrics[p]['sentiment']['very_positive_pct']
        for p in platforms
    ]
    leader_positioning = [
        platform_metrics[p]['positioning']['leader_pct'] + platform_metrics[p]['positioning']['featured_pct']
        for p in platforms
    ]

    x = range(len(platforms))
    width = 0.25

    fig, ax = plt.subplots(figsize=(14, 8))

    bars1 = ax.bar([i - width for i in x], mention_rates, width, label='Mention Rate (%)',
                    color=COLORS['primary'], edgecolor='white', linewidth=1.5)
    bars2 = ax.bar(x, positive_sentiment, width, label='Positive Sentiment (%)',
                    color=COLORS['success'], edgecolor='white', linewidth=1.5)
    bars3 = ax.bar([i + width for i in x], leader_positioning, width, label='Leader/Featured (%)',
                    color=COLORS['secondary'], edgecolor='white', linewidth=1.5)

    # Add value labels on bars
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.1f}%',
                        ha='center', va='bottom', fontsize=10, weight='bold')

    ax.set_ylabel('Percentage (%)', fontsize=13, weight='bold')
    ax.set_xlabel('Platform', fontsize=13, weight='bold')
    ax.set_title(f'{brand_name} Performance by Platform', fontsize=16, weight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(platforms, fontsize=12)
    ax.legend(fontsize=11, loc='upper right')
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_ylim(0, min(100, max(mention_rates + positive_sentiment + leader_positioning) * 1.15))

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_share_of_voice_chart(share_of_voice: Dict[str, Any], brand_name: str, output_path: str) -> str:
    """
    Generate a horizontal bar chart showing share of voice.
    Returns the file path of the generated chart.
    """
    # Prepare data: brand + top 5 competitors
    organizations = [brand_name]
    sov_percentages = [share_of_voice['brand_sov']]

    for comp_name, data in list(share_of_voice['competitor_sov'].items())[:5]:
        organizations.append(comp_name)
        sov_percentages.append(data['sov'])

    # Sort by SOV descending
    sorted_data = sorted(zip(organizations, sov_percentages), key=lambda x: x[1], reverse=True)
    organizations, sov_percentages = zip(*sorted_data)

    # Color brand differently
    colors = [COLORS['primary'] if org == brand_name else COLORS['neutral'] for org in organizations]

    fig, ax = plt.subplots(figsize=(12, 8))
    bars = ax.barh(organizations, sov_percentages, color=colors, edgecolor='white', linewidth=2)

    # Add value labels
    for i, (bar, sov) in enumerate(zip(bars, sov_percentages)):
        width = bar.get_width()
        ax.text(width + 0.5, bar.get_y() + bar.get_height()/2.,
                f'{sov:.1f}%',
                ha='left', va='center', fontsize=12, weight='bold')

    ax.set_xlabel('Share of Voice (%)', fontsize=13, weight='bold')
    ax.set_title('Share of Voice: Brand vs. Competitors', fontsize=16, weight='bold', pad=20)
    ax.grid(axis='x', alpha=0.3, linestyle='--')

    # Highlight brand name in bold
    ylabels = [f'**{org}**' if org == brand_name else org for org in organizations]
    ax.set_yticks(range(len(organizations)))
    ax.set_yticklabels(organizations, fontsize=11, weight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_descriptor_performance_chart(descriptor_analysis: Dict[str, int], brand_name: str, output_path: str, top_n: int = 10) -> str:
    """
    Generate a horizontal bar chart showing top descriptors associated with the brand.
    Returns the file path of the generated chart.
    """
    if not descriptor_analysis:
        return None

    # Get top N descriptors
    sorted_descriptors = sorted(descriptor_analysis.items(), key=lambda x: x[1], reverse=True)[:top_n]

    if not sorted_descriptors:
        return None

    descriptors, counts = zip(*sorted_descriptors)

    fig, ax = plt.subplots(figsize=(12, 8))
    bars = ax.barh(range(len(descriptors)), counts, color=COLORS['primary'], edgecolor='white', linewidth=2)

    # Add value labels
    for bar, count in zip(bars, counts):
        width = bar.get_width()
        ax.text(width + 0.3, bar.get_y() + bar.get_height()/2.,
                f'{int(count)}',
                ha='left', va='center', fontsize=11, weight='bold')

    ax.set_yticks(range(len(descriptors)))
    ax.set_yticklabels(descriptors, fontsize=11)
    ax.set_xlabel('Number of Mentions', fontsize=13, weight='bold')
    ax.set_title(f'Top Descriptors Associated with {brand_name}', fontsize=16, weight='bold', pad=20)
    ax.grid(axis='x', alpha=0.3, linestyle='--')
    ax.invert_yaxis()  # Highest at top

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_brand_mentions_trend_chart(trend_data: List[Dict[str, Any]], brand_name: str, output_path: str) -> str:
    """
    Generate a line chart showing brand mention percentage over time.
    Returns the file path of the generated chart.
    """
    if not trend_data or len(trend_data) < 2:
        return None

    dates = [item['date'][:10] for item in trend_data]  # Extract date (YYYY-MM-DD)
    percentages = [item['mention_percentage'] for item in trend_data]

    fig, ax = plt.subplots(figsize=(12, 7))
    ax.plot(dates, percentages, marker='o', linewidth=3, markersize=8,
            color=COLORS['primary'], markerfacecolor=COLORS['success'])

    ax.set_ylabel('Mention Rate (%)', fontsize=13, weight='bold')
    ax.set_xlabel('Collection Date', fontsize=13, weight='bold')
    ax.set_title(f'{brand_name} Brand Mention Rate Over Time', fontsize=16, weight='bold', pad=20)
    ax.grid(axis='both', alpha=0.3, linestyle='--')
    ax.set_ylim(0, 100)

    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_positioning_trend_chart(trend_data: List[Dict[str, Any]], brand_name: str, output_path: str) -> str:
    """
    Generate a stacked area chart showing positioning distribution over time.
    Returns the file path of the generated chart.
    """
    if not trend_data or len(trend_data) < 2:
        return None

    dates = [item['date'][:10] for item in trend_data]
    leader = [item['leader'] for item in trend_data]
    featured = [item['featured'] for item in trend_data]
    listed = [item['listed'] for item in trend_data]
    not_mentioned = [item['not_mentioned'] for item in trend_data]

    fig, ax = plt.subplots(figsize=(12, 7))

    ax.stackplot(range(len(dates)), leader, featured, listed, not_mentioned,
                 labels=['Leader', 'Featured', 'Listed', 'Not Mentioned'],
                 colors=[COLORS['success'], COLORS['primary'], COLORS['secondary'], COLORS['danger']],
                 alpha=0.8)

    ax.set_ylabel('Percentage (%)', fontsize=13, weight='bold')
    ax.set_xlabel('Collection Date', fontsize=13, weight='bold')
    ax.set_title(f'{brand_name} Positioning Distribution Over Time', fontsize=16, weight='bold', pad=20)
    ax.legend(loc='upper left', fontsize=11)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_ylim(0, 100)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(dates, rotation=45, ha='right')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_share_of_voice_trend_chart(trend_data: List[Dict[str, Any]], brand_name: str, output_path: str) -> str:
    """
    Generate a multi-line chart showing share of voice trends for brand and competitors.
    Returns the file path of the generated chart.
    """
    if not trend_data or len(trend_data) < 2:
        return None

    dates = [item['date'][:10] for item in trend_data]
    brand_sov = [item['brand_sov'] for item in trend_data]

    # Get all competitor names
    all_competitors = set()
    for item in trend_data:
        all_competitors.update(item.get('competitors', {}).keys())

    fig, ax = plt.subplots(figsize=(12, 7))

    # Plot brand line (thicker, highlighted)
    ax.plot(dates, brand_sov, marker='o', linewidth=3, markersize=8,
            color=COLORS['success'], label=brand_name, zorder=10)

    # Plot competitor lines
    colors_cycle = COLORS['palette'][1:]  # Skip first color (used for brand)
    for i, competitor in enumerate(sorted(all_competitors)):
        competitor_sov = [item.get('competitors', {}).get(competitor, 0) for item in trend_data]
        ax.plot(dates, competitor_sov, marker='s', linewidth=2, markersize=6,
                color=colors_cycle[i % len(colors_cycle)], label=competitor, alpha=0.7)

    ax.set_ylabel('Share of Voice (%)', fontsize=13, weight='bold')
    ax.set_xlabel('Collection Date', fontsize=13, weight='bold')
    ax.set_title('Share of Voice: Brand vs. Competitors Over Time', fontsize=16, weight='bold', pad=20)
    ax.legend(loc='best', fontsize=10)
    ax.grid(axis='both', alpha=0.3, linestyle='--')
    ax.set_ylim(0, 100)

    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_sentiment_trend_chart(trend_data: List[Dict[str, Any]], brand_name: str, output_path: str) -> str:
    """
    Generate a stacked area chart showing sentiment distribution over time.
    Returns the file path of the generated chart.
    """
    if not trend_data or len(trend_data) < 2:
        return None

    dates = [item['date'][:10] for item in trend_data]
    very_positive = [item['very_positive'] for item in trend_data]
    positive = [item['positive'] for item in trend_data]
    neutral = [item['neutral'] for item in trend_data]
    negative = [item['negative'] for item in trend_data]
    very_negative = [item['very_negative'] for item in trend_data]

    fig, ax = plt.subplots(figsize=(12, 7))

    ax.stackplot(range(len(dates)), very_positive, positive, neutral, negative, very_negative,
                 labels=['Very Positive', 'Positive', 'Neutral', 'Negative', 'Very Negative'],
                 colors=[COLORS['success'], COLORS['primary'], COLORS['neutral'], COLORS['warning'], COLORS['very_negative']],
                 alpha=0.8)

    ax.set_ylabel('Percentage (%)', fontsize=13, weight='bold')
    ax.set_xlabel('Collection Date', fontsize=13, weight='bold')
    ax.set_title(f'{brand_name} Sentiment Distribution Over Time', fontsize=16, weight='bold', pad=20)
    ax.legend(loc='upper left', fontsize=11)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_ylim(0, 100)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(dates, rotation=45, ha='right')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    return output_path


def generate_competitor_threats_chart(threats_data: List[Dict[str, Any]], brand_name: str, output_path: str, top_n: int = 10) -> str:
    """
    Generate a horizontal bar chart showing top competitor threats.
    Returns the file path of the generated chart.

    Args:
        threats_data: List of dictionaries with keys: name, threat_score, threat_level, mention_count, share_of_voice
        brand_name: Name of the brand
        output_path: Path to save the chart
        top_n: Number of top competitors to display (default: 10)
    """
    if not threats_data or len(threats_data) == 0:
        return None

    # Take top N competitors (data should already be sorted by threat_score)
    top_threats = threats_data[:top_n]

    # Extract data for chart
    names = [threat['name'] for threat in top_threats]
    threat_scores = [threat['threat_score'] for threat in top_threats]
    threat_levels = [threat['threat_level'] for threat in top_threats]

    # Reverse order so highest threat is at top
    names = names[::-1]
    threat_scores = threat_scores[::-1]
    threat_levels = threat_levels[::-1]

    # Color mapping for threat levels
    threat_colors = {
        'High': '#75C9C8',     # TALES teal
        'Medium': '#80A1D4',   # TALES blue
        'Low': '#665775'       # TALES purple
    }
    colors = [threat_colors.get(level, COLORS['primary']) for level in threat_levels]

    # Modern styling with clean backgrounds
    fig, ax = plt.subplots(figsize=(12, max(8, len(names) * 0.6)), facecolor=CHART_CONFIG['figure_facecolor'])
    ax.set_facecolor(CHART_CONFIG['axes_facecolor'])

    # Create horizontal bar chart
    bars = ax.barh(range(len(names)), threat_scores, color=colors, edgecolor='white', linewidth=2, alpha=0.9)

    # Customize axes
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=CHART_CONFIG['tick_size'])
    ax.set_xlabel('Threat Score', fontsize=CHART_CONFIG['label_size'], weight='bold')
    ax.set_title(f'Top {len(names)} Competitor Threats to {brand_name}',
                fontsize=CHART_CONFIG['title_size'], weight='bold', pad=20, color='#2C3E50')

    # Improve grid styling
    ax.grid(axis='x', alpha=CHART_CONFIG['grid_alpha'], linestyle='--',
           color=CHART_CONFIG['grid_color'], linewidth=1)
    ax.set_axisbelow(True)

    # Remove top and right spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#D1D8E0')
    ax.spines['bottom'].set_color('#D1D8E0')

    # Add value labels on bars
    for i, (bar, score, level) in enumerate(zip(bars, threat_scores, threat_levels)):
        width = bar.get_width()
        ax.text(width + 0.5, bar.get_y() + bar.get_height()/2,
                f'{score:.0f} ({level})',
                ha='left', va='center', fontsize=10, weight='bold', color='#2C3E50')

    # Add legend for threat levels
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#75C9C8', label='High Threat'),
        Patch(facecolor='#80A1D4', label='Medium Threat'),
        Patch(facecolor='#665775', label='Low Threat')
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=CHART_CONFIG['legend_size'])

    plt.tight_layout()
    plt.savefig(output_path, dpi=CHART_CONFIG['dpi'], bbox_inches='tight', facecolor='white')
    plt.close()

    return output_path


def generate_all_charts(
    mention_metrics: Dict[str, Any],
    positioning_metrics: Dict[str, Any],
    sentiment_metrics: Dict[str, Any],
    platform_metrics: Dict[str, Dict[str, Any]],
    share_of_voice: Dict[str, Any],
    descriptor_analysis: Dict[str, int],
    brand_name: str,
    timestamp: str = None,
    user_id: Optional[int] = None,
    brand_id: Optional[int] = None,
    trend_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    competitor_threats: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, str]:
    """
    Generate all charts for the report.
    First checks for uploaded charts from frontend, then generates missing charts.
    Returns a dictionary mapping chart names to file paths.

    Args:
        mention_metrics: Mention statistics
        positioning_metrics: Positioning statistics
        sentiment_metrics: Sentiment statistics
        platform_metrics: Platform-specific statistics
        share_of_voice: Share of voice data
        descriptor_analysis: Descriptor analysis data
        brand_name: Name of the brand
        timestamp: Optional timestamp for filenames
        user_id: Optional user ID to check for uploaded charts
        brand_id: Optional brand ID to check for uploaded charts
        trend_data: Optional dictionary with trend data for various metrics
        competitor_threats: Optional list of competitor threat data
    """
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    charts_dir = ensure_charts_directory()
    brand_slug = brand_name.replace(' ', '_').replace('/', '_')

    # First, check for uploaded charts from frontend
    chart_paths = {}
    if user_id and brand_id:
        print("Checking for uploaded charts from frontend...")
        chart_paths = check_for_uploaded_charts(user_id, brand_id)
        if chart_paths:
            print(f"Found {len(chart_paths)} uploaded chart(s)")
        else:
            print("No uploaded charts found, will generate all charts")

    # Generate each chart only if not already uploaded
    if 'mention_rate' not in chart_paths:
        try:
            chart_paths['mention_rate'] = generate_mention_rate_pie_chart(
                mention_metrics, brand_name,
                f"{charts_dir}/{brand_slug}_mention_rate_{timestamp}.png"
            )
        except Exception as e:
            print(f"Warning: Could not generate mention rate chart: {e}")

    if 'positioning' not in chart_paths:
        try:
            chart_paths['positioning'] = generate_positioning_bar_chart(
                positioning_metrics, brand_name,
                f"{charts_dir}/{brand_slug}_positioning_{timestamp}.png"
            )
        except Exception as e:
            # Print the traceback, not just the message. A bare KeyError('top_3')
            # rendered as "Warning: Could not generate positioning chart: 'top_3'",
            # which is why this went unnoticed across every report.
            import traceback
            print(f"Warning: Could not generate positioning chart: {e}")
            traceback.print_exc()

    if 'sentiment' not in chart_paths:
        try:
            chart_paths['sentiment'] = generate_sentiment_pie_chart(
                sentiment_metrics, brand_name,
                f"{charts_dir}/{brand_slug}_sentiment_{timestamp}.png"
            )
        except Exception as e:
            print(f"Warning: Could not generate sentiment chart: {e}")

    if 'platform_comparison' not in chart_paths:
        try:
            chart_paths['platform_comparison'] = generate_platform_comparison_chart(
                platform_metrics, brand_name,
                f"{charts_dir}/{brand_slug}_platform_comparison_{timestamp}.png"
            )
        except Exception as e:
            print(f"Warning: Could not generate platform comparison chart: {e}")

    if 'share_of_voice' not in chart_paths:
        try:
            chart_paths['share_of_voice'] = generate_share_of_voice_chart(
                share_of_voice, brand_name,
                f"{charts_dir}/{brand_slug}_share_of_voice_{timestamp}.png"
            )
        except Exception as e:
            print(f"Warning: Could not generate share of voice chart: {e}")

    if 'descriptor_performance' not in chart_paths:
        try:
            chart_paths['descriptor_performance'] = generate_descriptor_performance_chart(
                descriptor_analysis, brand_name,
                f"{charts_dir}/{brand_slug}_descriptor_performance_{timestamp}.png"
            )
        except Exception as e:
            print(f"Warning: Could not generate descriptor performance chart: {e}")

    # Generate competitor threats chart if data is provided
    if competitor_threats and 'competitor_threats' not in chart_paths:
        try:
            chart_paths['competitor_threats'] = generate_competitor_threats_chart(
                competitor_threats, brand_name,
                f"{charts_dir}/{brand_slug}_competitor_threats_{timestamp}.png"
            )
        except Exception as e:
            print(f"Warning: Could not generate competitor threats chart: {e}")

    # Generate time-series charts if trend data is provided
    if trend_data:
        if 'brand_mentions_trend' not in chart_paths and trend_data.get('brand_mentions'):
            try:
                chart_paths['brand_mentions_trend'] = generate_brand_mentions_trend_chart(
                    trend_data['brand_mentions'], brand_name,
                    f"{charts_dir}/{brand_slug}_brand_mentions_trend_{timestamp}.png"
                )
            except Exception as e:
                print(f"Warning: Could not generate brand mentions trend chart: {e}")

        if 'positioning_trend' not in chart_paths and trend_data.get('positioning'):
            try:
                chart_paths['positioning_trend'] = generate_positioning_trend_chart(
                    trend_data['positioning'], brand_name,
                    f"{charts_dir}/{brand_slug}_positioning_trend_{timestamp}.png"
                )
            except Exception as e:
                print(f"Warning: Could not generate positioning trend chart: {e}")

        if 'share_of_voice_trend' not in chart_paths and trend_data.get('share_of_voice'):
            try:
                chart_paths['share_of_voice_trend'] = generate_share_of_voice_trend_chart(
                    trend_data['share_of_voice'], brand_name,
                    f"{charts_dir}/{brand_slug}_share_of_voice_trend_{timestamp}.png"
                )
            except Exception as e:
                print(f"Warning: Could not generate share of voice trend chart: {e}")

        if 'sentiment_trend' not in chart_paths and trend_data.get('sentiment'):
            try:
                chart_paths['sentiment_trend'] = generate_sentiment_trend_chart(
                    trend_data['sentiment'], brand_name,
                    f"{charts_dir}/{brand_slug}_sentiment_trend_{timestamp}.png"
                )
            except Exception as e:
                print(f"Warning: Could not generate sentiment trend chart: {e}")

    # Filter out None values (charts that couldn't be generated)
    chart_paths = {k: v for k, v in chart_paths.items() if v is not None}

    # Convert filesystem paths to web-relative paths
    # frontend/public/report_charts/file.png -> report_charts/file.png
    web_paths = {}
    for key, path in chart_paths.items():
        if path.startswith('frontend/public/'):
            web_paths[key] = path.replace('frontend/public/', '')
        else:
            web_paths[key] = path

    print(f"Generated {len(web_paths)} charts in {charts_dir}/")

    return web_paths
