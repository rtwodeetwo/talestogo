"""
Data exports.

Tales does not generate written reports. What it produces is the underlying
response data, exported as a spreadsheet for a chosen period, plus the flags
needed to reproduce any number the dashboard shows from the rows themselves.

Exports are scoped by PERIOD rather than by a stored report record. The previous
design keyed the CSV to a Report row, so exporting depended on a report having
been generated first, and the report's window and the CSV's window were resolved
by different code that did not agree.

Period boundaries come from app/services/metrics_query.py, so "January 2026"
means the same 31 days here, on the dashboard and in the highlights email.
"""
import csv
import datetime
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..database import get_db
from ..services import metrics_core, metrics_query
from ..services.period_ranges import brand_fiscal_start_month, fiscal_quarter_label
from ..utils.brand_access import get_active_brand_id, get_data_owner_user_id

router = APIRouter(
    prefix="/exports",
    tags=["Exports"]
)

CSV_COLUMNS = [
    'ID',
    # The dashboard scopes by batch, so without this a spreadsheet cannot be
    # reconciled against anything shown on screen.
    'Batch ID',
    'Query ID',
    'Query Text',
    'Platform',
    'Response Text',
    'Timestamp (UTC)',
    'Brand Mentioned',
    'Brand Position',
    'Sentiment',
    'Descriptors',
    'Competitors',
    'Sources',
    'Notes',
    'Analyzed At (UTC)',
    # Whether this row is behind the published numbers, and if not, why not.
    'Brand In Query',
    'Counted In Metrics',
    'Excluded Because',
]


def resolve_period(
    db: Session, brand_id: Optional[int], period: str, period_start: Optional[str]
):
    """Turn a period selection into (start, end, label).

    Returns (None, None, "All Data") when period is 'all', which exports
    everything for the brand.
    """
    if period == 'all':
        return None, None, "All Data"

    if not period_start:
        raise HTTPException(
            status_code=400,
            detail="period_start is required unless period is 'all'")
    try:
        start_date = datetime.datetime.strptime(period_start, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="period_start must be YYYY-MM-DD")

    if period == 'month':
        start, end = metrics_query.month_bounds(start_date.year, start_date.month)
        return start, end, start_date.strftime("%B %Y")

    if period == 'quarter':
        quarter = (start_date.month - 1) // 3 + 1
        start, end = metrics_query.quarter_bounds(start_date.year, quarter)
        label = fiscal_quarter_label(
            brand_fiscal_start_month(db, brand_id), start_date.month, start_date.year)
        return start, end, label

    raise HTTPException(
        status_code=400, detail="period must be one of: month, quarter, all")


def build_response_rows(db: Session, owner_user_id: int, brand_id: Optional[int],
                        start, end):
    """Rows for the export, each labelled with whether it counts and why not.

    A data export should show every row, not silently hide the ones the metrics
    excluded. Filtering on "Counted In Metrics" reproduces the population behind
    the published number, and "Excluded Because" says what happened to the rest.
    That is what lets a failed collection be told apart from a real drop in
    visibility without opening the database.
    """
    query = db.query(models.Response).filter(
        models.Response.user_id == owner_user_id,
        models.Response.brand_id == brand_id,
    )
    if start is not None:
        query = query.filter(models.Response.timestamp >= start)
    if end is not None:
        # Half-open [start, end), matching metrics_query.
        query = query.filter(models.Response.timestamp < end)

    responses = query.order_by(models.Response.timestamp.desc()).all()

    brand_queries = db.query(models.Query).filter(
        models.Query.user_id == owner_user_id,
        models.Query.brand_id == brand_id,
    ).all()
    branded_query_ids = {q.query_id for q in brand_queries if q.brand_in_query}
    known_query_ids = {q.query_id for q in brand_queries}

    def exclusion_reason(response) -> str:
        """Why this row is not in the metrics, matching metrics_core exactly."""
        if response.query_id not in known_query_ids:
            # Branded-ness cannot be determined without the query, so the row
            # cannot be correctly placed either way.
            return 'Query no longer exists'
        if response.query_id in branded_query_ids:
            return 'Brand named in the question'
        if response.analyzed_at is None:
            return 'Not analyzed'
        if response.brand_mentioned not in metrics_core.MENTION_VALUES:
            return 'Unrecognized analysis result'
        return ''

    for response in responses:
        reason = exclusion_reason(response)
        yield [
            response.id,
            response.batch_id if response.batch_id is not None else '',
            response.query_id,
            response.query_text or '',
            response.platform,
            response.response_text,
            response.timestamp.isoformat() if response.timestamp else '',
            response.brand_mentioned or '',
            response.brand_position or '',
            response.sentiment or '',
            response.descriptors or '',
            response.competitors or '',
            response.sources or '',
            response.notes or '',
            response.analyzed_at.isoformat() if response.analyzed_at else '',
            'Yes' if response.query_id in branded_query_ids else 'No',
            'No' if reason else 'Yes',
            reason,
        ]


@router.get("/responses.csv")
def export_responses_csv(
    period: str = Query('all', description="month, quarter, or all"),
    period_start: Optional[str] = Query(
        None, description="YYYY-MM-DD, first day of the period"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id),
):
    """Export the response data for a period as a spreadsheet."""
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand selected")

    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)
    start, end, label = resolve_period(db, brand_id, period, period_start)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    row_count = 0
    for row in build_response_rows(db, owner_user_id, brand_id, start, end):
        writer.writerow(row)
        row_count += 1

    if row_count == 0:
        raise HTTPException(
            status_code=404, detail=f"No responses found for {label}")

    brand = db.query(models.BrandInfo).filter(
        models.BrandInfo.id == brand_id).first()
    brand_name = brand.brand_name if brand else "Brand"

    # utf-8-sig, not utf-8. Without the byte-order mark Excel opens the file in
    # the system codepage, so every curly quote, dash and accented character in
    # an AI-written answer arrives as mojibake.
    content = output.getvalue().encode('utf-8-sig')

    safe = "".join(
        c for c in f"{brand_name} {label}" if c.isalnum() or c in (' ', '-', '_')
    ).strip().replace(' ', '_')

    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={safe}_data.csv"}
    )
