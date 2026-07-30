"""
Period range helpers for period-over-period comparisons.

Shared by the analytics dashboard (Month over Month / Quarter over Quarter
modes) and any other feature that needs "this period vs the one before it"
date windows, such as periodic highlights emails.

Quarter boundaries are always calendar-aligned (Jan/Apr/Jul/Oct 1). A brand's
fiscal_year_start_month only changes the LABEL of a quarter, never its dates:
fiscal years that start in April, July, or October share the same quarter
boundaries as the calendar year.
"""
import calendar
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .. import models


def fiscal_quarter_label(fiscal_start_month: int, cal_month: int, cal_year: int) -> str:
    """
    Label a quarter given the brand's fiscal-year start month.

    cal_month is the first calendar month of the quarter (1, 4, 7, or 10).
    fiscal_start_month == 1 -> calendar quarters, e.g. "Q2 2026".
    fiscal_start_month  > 1 -> fiscal quarters named by the calendar year the
    fiscal year ends in (federal convention), e.g. an Oct 1 fiscal year start
    labels Apr-Jun 2026 as "FY2026 Q3".
    """
    offset = (cal_month - fiscal_start_month) % 12
    q = offset // 3 + 1
    if fiscal_start_month == 1:
        return f"Q{q} {cal_year}"
    fy = cal_year + 1 if cal_month >= fiscal_start_month else cal_year
    return f"FY{fy} Q{q}"


def brand_fiscal_start_month(db: Session, brand_id: Optional[int]) -> int:
    """The brand's fiscal-year start month (1 = calendar year, the default)."""
    if brand_id:
        brand = db.query(models.BrandInfo).filter(models.BrandInfo.id == brand_id).first()
        if brand and getattr(brand, 'fiscal_year_start_month', None):
            return brand.fiscal_year_start_month
    return 1


def parse_period_start(period_start: Optional[str]) -> Optional[datetime]:
    """Parse a 'YYYY-MM-DD' period-start string; return None if absent/invalid."""
    if not period_start:
        return None
    try:
        return datetime.strptime(period_start[:10], '%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def get_period_comparison_ranges(
    db: Session, owner_user_id: int, brand_id: Optional[int], period: str,
    period_start: Optional[datetime] = None,
    now: Optional[datetime] = None
) -> Tuple[datetime, datetime, str, datetime, datetime, str]:
    """
    Compute the two date ranges for a period-over-period comparison.

    period="month"   compares a calendar month to the month before it.
    period="quarter" compares a calendar quarter to the quarter before it.

    If period_start is given, that specific period (the month/quarter containing
    period_start) is the headline; otherwise the last COMPLETE period is used
    (the current in-progress period is skipped, matching the monthly/quarterly
    reports). Quarter labels respect the brand's fiscal-year start month;
    fiscal and calendar quarters share the same boundaries, so only labels differ.

    now is injectable for tests; it defaults to the current UTC time.

    Returns:
        (current_start, current_end, current_label,
         previous_start, previous_end, previous_label)
    """
    if now is None:
        now = datetime.utcnow()

    def month_bounds(year: int, month: int) -> Tuple[datetime, datetime]:
        start = datetime(year, month, 1, 0, 0, 0)
        last_day = calendar.monthrange(year, month)[1]
        end = datetime(year, month, last_day, 23, 59, 59)
        return start, end

    if period == 'quarter':
        fiscal_start_month = brand_fiscal_start_month(db, brand_id)

        if period_start is not None:
            cur_q_abs = period_start.year * 4 + (period_start.month - 1) // 3
        else:
            # last complete quarter = current in-progress quarter minus one
            cur_q_abs = (now.year * 4 + (now.month - 1) // 3) - 1

        def quarter_bounds(q_abs: int) -> Tuple[datetime, datetime, str]:
            year, q = q_abs // 4, q_abs % 4
            start_month = q * 3 + 1
            start, _ = month_bounds(year, start_month)
            _, end = month_bounds(year, start_month + 2)
            return start, end, fiscal_quarter_label(fiscal_start_month, start_month, year)

        cur_start, cur_end, cur_label = quarter_bounds(cur_q_abs)
        prev_start, prev_end, prev_label = quarter_bounds(cur_q_abs - 1)
        return cur_start, cur_end, cur_label, prev_start, prev_end, prev_label

    # Month
    if period_start is not None:
        cur_m_abs = period_start.year * 12 + (period_start.month - 1)
    else:
        # last complete month = current month minus one
        cur_m_abs = (now.year * 12 + (now.month - 1)) - 1

    def month_period(m_abs: int) -> Tuple[datetime, datetime, str]:
        year, month = m_abs // 12, m_abs % 12 + 1
        start, end = month_bounds(year, month)
        return start, end, start.strftime('%B %Y')

    cur_start, cur_end, cur_label = month_period(cur_m_abs)
    prev_start, prev_end, prev_label = month_period(cur_m_abs - 1)
    return cur_start, cur_end, cur_label, prev_start, prev_end, prev_label
