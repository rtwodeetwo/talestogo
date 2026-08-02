"""
Periodic Highlights Email endpoints.

Emails a short, verified-metrics highlights summary for a brand:

- POST /highlights/monthly-check: checks that the previous month's report
  exists, computes verified metrics from the database, and emails a
  monthly highlights summary.
- POST /highlights/quarterly-check: aggregates the previous complete
  quarter's response data directly (no Report row required) and emails a
  quarterly highlights summary.

Every number in the email comes straight from the database; the LLM only
writes prose around a verified fact sheet and is instructed to quote the
numbers verbatim.

Triggering: both endpoints require an X-Cron-Secret header matching the
HIGHLIGHTS_CRON_SECRET environment variable, so they can be driven by any
external cron (see docs). Alternatively, set HIGHLIGHTS_ENABLED=true to have
the built-in scheduler run them automatically (see app/scheduler.py).

Configuration (environment variables):
- HIGHLIGHTS_CRON_SECRET: shared secret for the HTTP endpoints (required
  for HTTP triggering; the built-in scheduler does not need it)
- HIGHLIGHTS_RECIPIENT: email address to send highlights to (falls back
  to the configured admin email)
- HIGHLIGHTS_BRAND_ID or HIGHLIGHTS_BRAND_NAME: which brand to report on
  (optional when exactly one brand exists)

Quarter labels follow the brand's fiscal_year_start_month setting, e.g.
"Q2 2026" for calendar-year brands or "FY2026 Q3" for a brand on the US
federal fiscal year.
"""
import os
import hmac
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException, Header
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Report, BrandInfo, Response, BatchAnalytics, Query
from app.services import metrics_core, metrics_query
from app.services.email_notifications import send_email
from app.services.llm_provider_manager import get_llm_provider_manager
from app.services.period_ranges import get_period_comparison_ranges
from app.services.site_config import get_site_url, get_admin_email

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/highlights",
    tags=["Highlights"]
)


def _verify_secret(x_cron_secret: str = Header(None)):
    cron_secret = os.getenv("HIGHLIGHTS_CRON_SECRET", "")
    if not cron_secret:
        raise HTTPException(status_code=503, detail="HIGHLIGHTS_CRON_SECRET not configured")
    # Constant-time compare so response latency does not leak the secret.
    # Encode explicitly: compare_digest rejects str with non-ASCII characters.
    if not hmac.compare_digest(
        (x_cron_secret or "").encode("utf-8"), cron_secret.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Invalid cron secret")


def _get_recipient(db: Session) -> Optional[str]:
    """The highlights recipient: HIGHLIGHTS_RECIPIENT env, else the admin email."""
    return os.getenv("HIGHLIGHTS_RECIPIENT") or get_admin_email(db) or None


def _get_highlights_brand(db: Session) -> Tuple[Optional[BrandInfo], Optional[str]]:
    """
    Resolve which brand highlights are about.

    Priority: HIGHLIGHTS_BRAND_ID env, then HIGHLIGHTS_BRAND_NAME env, then
    the only brand in the database when exactly one exists.

    Returns (brand, error_reason). Exactly one of the two is set.
    """
    brand_id_env = os.getenv("HIGHLIGHTS_BRAND_ID")
    if brand_id_env:
        try:
            brand_id = int(brand_id_env)
        except ValueError:
            return None, f"HIGHLIGHTS_BRAND_ID is not an integer: {brand_id_env!r}"
        brand = db.query(BrandInfo).filter(BrandInfo.id == brand_id).first()
        if not brand:
            return None, f"No brand found with id {brand_id}"
        return brand, None

    brand_name_env = os.getenv("HIGHLIGHTS_BRAND_NAME")
    if brand_name_env:
        brand = db.query(BrandInfo).filter(BrandInfo.brand_name == brand_name_env).first()
        if not brand:
            return None, f"No brand found named {brand_name_env!r}"
        return brand, None

    brands = db.query(BrandInfo).limit(2).all()
    if len(brands) == 1:
        return brands[0], None
    if not brands:
        return None, "No brands exist in the database"
    return None, "Multiple brands exist; set HIGHLIGHTS_BRAND_ID or HIGHLIGHTS_BRAND_NAME"


def _get_previous_month_range(now: Optional[datetime] = None):
    """Return (period_label, start_date, end_date) for last month."""
    today = now if now is not None else datetime.utcnow()
    first_of_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_date = first_of_this_month - timedelta(seconds=1)
    start_date = end_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    period_label = start_date.strftime("%B %Y")
    return period_label, start_date, end_date


def _get_month_before_range(start_date):
    """Return (start, end) for the month before the given start_date."""
    prev_end = start_date - timedelta(seconds=1)
    prev_start = prev_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return prev_start, prev_end


def _find_monthly_report(db: Session, brand: BrandInfo, period_label: str):
    """Find the monthly report for the brand matching the given period label."""
    return db.query(Report).filter(
        Report.brand_id == brand.id,
        Report.report_type == "monthly",
        Report.period_label == period_label,
    ).order_by(Report.created_at.desc()).first()


def _resolve_population(db: Session, brand, start_date, end_date):
    """Load the rows behind an emailed figure.

    Windowing, branded-query exclusion and the analyzed_at filter all happen in
    metrics_query, so the email measures exactly what the dashboard measures.
    These endpoints previously did their own filtering and, among other things,
    omitted user_id and counted unanalyzed rows in the denominator.
    """
    return metrics_query.resolve(db, metrics_query.MetricScope(
        owner_user_id=brand.user_id,
        brand_id=brand.id,
        start=start_date,
        end=end_date,
    ))


def _compute_mention_rate(population):
    """(counted, mentioned, rate) for the emailed headline."""
    result = metrics_core.mention_rate(population)
    return (int(result.denominator), int(result.numerator),
            result.value if result.value is not None else 0.0)


def _compute_platform_rates(population):
    """Per-platform mention rates, using the headline definition."""
    rates = metrics_core.platform_mention_rates(population)
    ordered = sorted(rates.items(), key=lambda item: -item[1].numerator)
    return {
        platform: {
            "total": int(value.denominator),
            "mentioned": int(value.numerator),
            "rate": value.value if value.value is not None else 0,
        }
        for platform, value in ordered
    }


def _compute_sentiment(population):
    """Sentiment breakdown over direct mentions carrying a sentiment value."""
    distribution = metrics_core.sentiment_distribution(population)
    total = int(distribution["Very Positive"].denominator)
    if not total:
        return {}, 0
    result = {}
    for label in ["Very Positive", "Positive", "Neutral", "Mixed", "Negative"]:
        value = distribution[label]
        if value.numerator > 0:
            result[label] = {"count": int(value.numerator), "pct": value.value}
    return result, total


def _compute_descriptors(population):
    """Top descriptors used about the brand, case-folded.

    Previously counted raw strings, so "high-temperature plasma" and
    "High-Temperature Plasma" competed for slots in the same top-10 list.
    """
    frequency = metrics_core.descriptor_frequency(population)
    return list(frequency.items())[:10]


def _compute_query_rates(population):
    """Per-query mention rates."""
    queries = {}
    for row in population.organic_rows():
        entry = queries.setdefault(row.query_id, {
            "total": 0, "mentioned": 0, "text": row.query_text or row.query_id,
        })
        entry["total"] += 1
        if row.is_mentioned:
            entry["mentioned"] += 1

    for data in queries.values():
        data["rate"] = (round(100.0 * data["mentioned"] / data["total"], 1)
                        if data["total"] else 0)
    return queries


def _compute_monthly_breakdown(population):
    """Per-month mention rates within a multi-month window.

    Months are keyed off the stored UTC timestamp, which is what every other
    period boundary in the app currently uses. Note this can differ by a day
    from the Eastern dates the UI displays for rows near a month boundary; that
    discrepancy is tracked separately as the timezone work.
    """
    months = {}
    for row in population.organic_rows():
        if row.timestamp is None:
            continue
        key = row.timestamp.strftime("%B %Y")
        entry = months.setdefault(key, {"total": 0, "mentioned": 0})
        entry["total"] += 1
        if row.is_mentioned:
            entry["mentioned"] += 1

    result = {
        key: {**data,
              "rate": round(100.0 * data["mentioned"] / data["total"], 1) if data["total"] else 0}
        for key, data in months.items()
    }
    # Sort chronologically by parsing the month string
    return dict(sorted(result.items(), key=lambda x: datetime.strptime(x[0], "%B %Y")))


def _build_verified_fact_sheet(
    period_label: str,
    total: int, mentioned: int, mention_rate: float,
    prev_label: str, prev_rate: float,
    platform_rates: dict,
    sentiment: dict, sentiment_total: int,
    prev_sentiment: dict,
    descriptors: list,
    query_rates: dict,
    batch_trends: list,
) -> str:
    """Build a structured fact sheet of verified metrics."""
    lines = [
        f"=== VERIFIED METRICS FOR {period_label.upper()} ===",
        f"(All numbers below are computed directly from the database. Use ONLY these numbers.)",
        "",
        f"OVERALL MENTION RATE: {mention_rate}% ({mentioned} mentions out of {total} responses, excluding branded queries)",
        f"PREVIOUS MONTH ({prev_label}): {prev_rate}%",
        f"CHANGE: {mention_rate - prev_rate:+.1f} percentage points",
        "",
        "PLATFORM MENTION RATES:",
    ]
    for p, data in platform_rates.items():
        lines.append(f"  {p}: {data['rate']}% ({data['mentioned']}/{data['total']})")

    lines.append("")
    lines.append(f"SENTIMENT (based on {sentiment_total} directly-mentioned responses):")
    for s, data in sentiment.items():
        lines.append(f"  {s}: {data['pct']}% ({data['count']})")
    neg_mixed = sum(sentiment.get(s, {}).get("count", 0) for s in ["Negative", "Mixed"])
    lines.append(f"  Negative + Mixed: {neg_mixed}")

    if prev_sentiment:
        lines.append("PREVIOUS MONTH SENTIMENT:")
        for s, data in prev_sentiment.items():
            lines.append(f"  {s}: {data['pct']}% ({data['count']})")

    lines.append("")
    lines.append("TOP DESCRIPTORS (by mention count):")
    for desc, count in descriptors:
        lines.append(f"  {desc}: {count}")

    lines.append("")
    lines.append("WEEKLY BATCH TRENDS:")
    for bt in batch_trends:
        lines.append(f"  {bt['date']}: mention_rate={bt['rate']}%, responses={bt['total']}")

    lines.append("")
    lines.append("QUERY MENTION RATES (highest to lowest):")
    sorted_queries = sorted(query_rates.items(), key=lambda x: -x[1]["rate"])
    for qid, data in sorted_queries[:8]:
        lines.append(f"  {qid} ({data['text'][:60]}): {data['rate']}%")
    lines.append("  ...")
    for qid, data in sorted_queries[-4:]:
        lines.append(f"  {qid} ({data['text'][:60]}): {data['rate']}%")

    return "\n".join(lines)


def _build_quarterly_fact_sheet(
    quarter_label: str, prev_quarter_label: str,
    total: int, mentioned: int, mention_rate: float, prev_rate: float,
    monthly_breakdown: dict,
    platform_rates: dict,
    sentiment: dict, sentiment_total: int,
    prev_sentiment: dict,
    descriptors: list,
    query_rates: dict,
) -> str:
    lines = [
        f"=== VERIFIED METRICS FOR {quarter_label.upper()} ===",
        f"(All numbers below are computed directly from the database. Use ONLY these numbers.)",
        "",
        f"OVERALL QUARTERLY MENTION RATE: {mention_rate}% ({mentioned} mentions out of {total} responses, excluding branded queries)",
        f"PREVIOUS QUARTER ({prev_quarter_label}): {prev_rate}%",
        f"CHANGE: {mention_rate - prev_rate:+.1f} percentage points",
        "",
        "MONTHLY BREAKDOWN WITHIN QUARTER:",
    ]
    for month_label, data in monthly_breakdown.items():
        lines.append(f"  {month_label}: {data['rate']}% ({data['mentioned']}/{data['total']})")

    lines.append("")
    lines.append("PLATFORM MENTION RATES (quarterly aggregate):")
    for p, data in platform_rates.items():
        lines.append(f"  {p}: {data['rate']}% ({data['mentioned']}/{data['total']})")

    lines.append("")
    lines.append(f"SENTIMENT (based on {sentiment_total} directly-mentioned responses):")
    for s, data in sentiment.items():
        lines.append(f"  {s}: {data['pct']}% ({data['count']})")
    neg_mixed = sum(sentiment.get(s, {}).get("count", 0) for s in ["Negative", "Mixed"])
    lines.append(f"  Negative + Mixed: {neg_mixed}")

    if prev_sentiment:
        lines.append(f"PREVIOUS QUARTER ({prev_quarter_label}) SENTIMENT:")
        for s, data in prev_sentiment.items():
            lines.append(f"  {s}: {data['pct']}% ({data['count']})")

    lines.append("")
    lines.append("TOP DESCRIPTORS (by mention count across quarter):")
    for desc, count in descriptors:
        lines.append(f"  {desc}: {count}")

    lines.append("")
    lines.append("QUERY MENTION RATES (highest to lowest, quarterly aggregate):")
    sorted_queries = sorted(query_rates.items(), key=lambda x: -x[1]["rate"])
    for qid, data in sorted_queries[:8]:
        lines.append(f"  {qid} ({data['text'][:60]}): {data['rate']}%")
    lines.append("  ...")
    for qid, data in sorted_queries[-4:]:
        lines.append(f"  {qid} ({data['text'][:60]}): {data['rate']}%")

    return "\n".join(lines)


def _call_analysis_llm(db: Session, prompt: str) -> str:
    """Write highlights prose with the configured analysis provider."""
    manager = get_llm_provider_manager(db)
    provider = manager.get_analysis_provider()
    if not provider:
        raise HTTPException(
            status_code=503,
            detail="No analysis LLM configured. Configure one in Admin settings and set use_for_analysis on it."
        )
    return provider.call(prompt, max_tokens=2048)


def _generate_highlights_text(db: Session, fact_sheet: str, period_label: str, brand_name: str) -> str:
    """Use the analysis LLM to write monthly highlights from verified metrics only."""
    prompt = f"""Write a concise executive highlights report about {brand_name}'s reputation
in AI platforms for {period_label}.

CRITICAL RULES:
1. Use ONLY the verified numbers provided below. Do not calculate, estimate, or
   infer any numbers not explicitly stated in the fact sheet.
2. Every percentage or count you cite must appear verbatim in the fact sheet.
3. If a comparison is not provided, do not invent one.

Format:
- Title line: "{brand_name}'s Reputation in AIs: {period_label} Report"
- Then 4-6 concise analytical bullets using * characters
- Each bullet: 1-3 sentences with specific numbers from the fact sheet
- Cover: overall mention rate and month-over-month change, platform-specific
  differences, sentiment distribution, descriptor highlights, notable query
  patterns or gaps
- Style: analytical but accessible, as if briefing a communications director

Do NOT use markdown formatting. Plain text only.

{fact_sheet}

Write only the highlights report. Nothing else."""

    return _call_analysis_llm(db, prompt)


def _generate_quarterly_highlights_text(db: Session, fact_sheet: str, quarter_label: str, brand_name: str) -> str:
    """Use the analysis LLM to write quarterly highlights from verified metrics only."""
    prompt = f"""Write a concise executive quarterly highlights report about {brand_name}'s reputation
in AI platforms for {quarter_label}.

CRITICAL RULES:
1. Use ONLY the verified numbers provided below. Do not calculate, estimate, or
   infer any numbers not explicitly stated in the fact sheet.
2. Every percentage or count you cite must appear verbatim in the fact sheet.
3. If a comparison is not provided, do not invent one.

Format:
- Title line: "{brand_name}'s Reputation in AIs: {quarter_label} Quarterly Report"
- Then 5-7 concise analytical bullets using * characters
- Each bullet: 1-3 sentences with specific numbers from the fact sheet
- Cover: overall quarterly mention rate and quarter-over-quarter change, monthly
  trend within the quarter (improving / declining / flat), platform-specific
  differences, sentiment distribution and any shift from prior quarter, top
  descriptors, notable query patterns or gaps
- Style: analytical but accessible, as if briefing a communications director at
  a quarterly review. Reference the period with the exact quarter label given
  (e.g. "{quarter_label}"); do not rename it.

Do NOT use markdown formatting. Plain text only.

{fact_sheet}

Write only the highlights report. Nothing else."""

    return _call_analysis_llm(db, prompt)


async def run_quarterly_highlights(db: Session) -> dict:
    """
    Aggregate the previous complete quarter's response data for the configured
    brand and email a highlights summary. Shared by the HTTP endpoint and the
    built-in scheduler.
    """
    recipient = _get_recipient(db)
    if not recipient:
        logger.warning("Quarterly highlights skipped: no recipient configured")
        return {"status": "skipped", "reason": "no_recipient_configured"}

    brand, brand_error = _get_highlights_brand(db)
    if not brand:
        await send_email(
            to_email=recipient,
            subject="[Tales Alert] Highlights brand not resolved",
            body=(
                f"The quarterly highlights check ran on {datetime.utcnow().strftime('%B %d, %Y')} "
                f"but could not resolve a brand: {brand_error}"
            ),
        )
        return {"status": "alert_sent", "reason": "brand_not_resolved", "detail": brand_error}

    # Last complete quarter vs the one before it; labels follow the brand's
    # fiscal_year_start_month (calendar "Q2 2026" or fiscal "FY2026 Q3").
    (start_date, end_date, quarter_label,
     prev_start, prev_end, prev_label) = get_period_comparison_ranges(
        db, brand.user_id, brand.id, 'quarter')
    logger.info(f"Quarterly highlights check for {quarter_label}")

    population = _resolve_population(db, brand, start_date, end_date)

    if not population.rows:
        await send_email(
            to_email=recipient,
            subject=f"[Tales Alert] No responses found for {quarter_label}",
            body=(
                f"The quarterly highlights check for {brand.brand_name} ({quarter_label}) found no "
                f"response data for {start_date.strftime('%B %d')} to "
                f"{end_date.strftime('%B %d, %Y')}.\n\n"
                f"Dashboard: {get_site_url(db)}"
            ),
        )
        return {"status": "alert_sent", "reason": "no_responses", "period": quarter_label}

    total, mentioned_count, mention_rate = _compute_mention_rate(population)
    platform_rates = _compute_platform_rates(population)
    sentiment, sentiment_total = _compute_sentiment(population)
    descriptors = _compute_descriptors(population)
    query_rates = _compute_query_rates(population)
    monthly_breakdown = _compute_monthly_breakdown(population)

    prev_population = _resolve_population(db, brand, prev_start, prev_end)
    _, _, prev_rate = _compute_mention_rate(prev_population)
    prev_sentiment, _ = _compute_sentiment(prev_population)

    fact_sheet = _build_quarterly_fact_sheet(
        quarter_label, prev_label,
        total, mentioned_count, mention_rate, prev_rate,
        monthly_breakdown, platform_rates,
        sentiment, sentiment_total, prev_sentiment,
        descriptors, query_rates,
    )

    highlights = _generate_quarterly_highlights_text(db, fact_sheet, quarter_label, brand.brand_name)

    await send_email(
        to_email=recipient,
        subject=f"{brand.brand_name}'s Reputation in AIs: {quarter_label} Quarterly Report",
        body=highlights,
    )

    logger.info(f"Quarterly highlights email sent for {quarter_label}")
    return {
        "status": "highlights_sent",
        "period": quarter_label,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "total_responses": len(responses),
    }


async def run_monthly_highlights(db: Session) -> dict:
    """
    Check for the previous month's report for the configured brand and email a
    highlights summary. Shared by the HTTP endpoint and the built-in scheduler.
    """
    recipient = _get_recipient(db)
    if not recipient:
        logger.warning("Monthly highlights skipped: no recipient configured")
        return {"status": "skipped", "reason": "no_recipient_configured"}

    period_label, start_date, end_date = _get_previous_month_range()
    logger.info(f"Highlights check for {period_label}")

    brand, brand_error = _get_highlights_brand(db)
    if not brand:
        await send_email(
            to_email=recipient,
            subject="[Tales Alert] Highlights brand not resolved",
            body=(
                f"The monthly highlights check ran on {datetime.utcnow().strftime('%B %d, %Y')} "
                f"but could not resolve a brand: {brand_error}"
            ),
        )
        return {"status": "alert_sent", "reason": "brand_not_resolved", "detail": brand_error}

    report = _find_monthly_report(db, brand, period_label)
    if not report:
        await send_email(
            to_email=recipient,
            subject=f"[Tales Alert] No monthly report for {period_label}",
            body=(
                f"The scheduled monthly report for {brand.brand_name} ({period_label}) has not been "
                f"generated yet.\n\n"
                f"Please check the Tales platform to ensure the report generation "
                f"completed successfully.\n\n"
                f"Dashboard: {get_site_url(db)}"
            ),
        )
        logger.info(f"Alert sent: no report found for {period_label}")
        return {"status": "alert_sent", "reason": "no_report", "period": period_label}

    # --- Compute verified metrics from the database ---
    brand_id = brand.id

    # Current month responses (the report's own window)
    population = _resolve_population(db, brand, report.start_date, report.end_date)

    total, mentioned_count, mention_rate = _compute_mention_rate(population)
    platform_rates = _compute_platform_rates(population)
    sentiment, sentiment_total = _compute_sentiment(population)
    descriptors = _compute_descriptors(population)
    query_rates = _compute_query_rates(population)

    # Previous month for comparison
    prev_start, prev_end = _get_month_before_range(report.start_date)
    prev_label = prev_start.strftime("%B %Y")
    prev_population = _resolve_population(db, brand, prev_start, prev_end)
    _, _, prev_rate = _compute_mention_rate(prev_population)
    prev_sentiment, _ = _compute_sentiment(prev_population)

    # Batch-level weekly trends
    batch_analytics = db.query(BatchAnalytics).filter(
        BatchAnalytics.brand_id == brand_id,
        BatchAnalytics.collection_date >= report.start_date,
        BatchAnalytics.collection_date <= report.end_date,
    ).order_by(BatchAnalytics.collection_date).all()

    batch_trends = [
        {"date": ba.collection_date.strftime("%b %d"), "rate": ba.mention_rate, "total": ba.total_responses}
        for ba in batch_analytics
    ]

    # Build fact sheet and generate highlights
    fact_sheet = _build_verified_fact_sheet(
        period_label, total, mentioned_count, mention_rate,
        prev_label, prev_rate,
        platform_rates, sentiment, sentiment_total, prev_sentiment,
        descriptors, query_rates, batch_trends,
    )

    highlights = _generate_highlights_text(db, fact_sheet, period_label, brand.brand_name)

    await send_email(
        to_email=recipient,
        subject=f"{brand.brand_name}'s Reputation in AIs: {period_label} Highlights",
        body=highlights,
    )

    logger.info(f"Highlights email sent for {period_label}")
    return {
        "status": "highlights_sent",
        "period": period_label,
        "report_id": report.id,
    }


@router.post("/quarterly-check")
async def quarterly_highlights_check(x_cron_secret: str = Header(None)):
    """
    Aggregate the previous complete quarter's response data and email highlights.

    Does not require a quarterly Report record; queries Response rows directly.
    Requires X-Cron-Secret header matching the HIGHLIGHTS_CRON_SECRET env var.
    """
    _verify_secret(x_cron_secret)

    db = SessionLocal()
    try:
        return await run_quarterly_highlights(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quarterly highlights check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/monthly-check")
async def monthly_highlights_check(x_cron_secret: str = Header(None)):
    """
    Check for the previous month's report and email highlights.

    Requires X-Cron-Secret header matching the HIGHLIGHTS_CRON_SECRET env var.
    """
    _verify_secret(x_cron_secret)

    db = SessionLocal()
    try:
        return await run_monthly_highlights(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Highlights check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
