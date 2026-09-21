"""
API endpoints for scheduled task management

SCHEDULING SYSTEM (Simplified - January 2026):
- Collection: On the 1st, 7th, 14th, and 21st of each month at 6:30 AM UTC (fixed)
- Analysis: Only on specific dates:
  - Monthly: 1st of each month (analyzes previous month)
  - Quarterly: Apr 1, Jul 1, Oct 1, Jan 1 (analyzes previous quarter)
  - Annual: Jan 1 (analyzes previous year)

NOTE: The collection_frequency field is kept for backward compatibility
but is no longer used for scheduling. All brands collect on fixed monthly dates.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import calendar
import pytz

from ..database import get_db
from ..models import User, ScheduledTask, ScheduledTaskHistory
from ..auth import get_current_user

router = APIRouter(prefix="/scheduled-tasks", tags=["scheduling"])


# === Pydantic Schemas ===

class ScheduleCreate(BaseModel):
    brand_id: int
    collection_frequency: str = 'monthly'  # 'weekly' or 'monthly'
    # Legacy field for backward compatibility
    schedule_type: Optional[str] = None  # 'first_day', 'middle', 'last_day' (deprecated)
    timezone: Optional[str] = 'UTC'
    send_email_notification: Optional[bool] = True
    notification_email: Optional[str] = None


class ScheduleUpdate(BaseModel):
    collection_frequency: Optional[str] = None  # 'weekly' or 'monthly'
    schedule_type: Optional[str] = None  # Legacy, deprecated
    is_enabled: Optional[bool] = None
    timezone: Optional[str] = None
    send_email_notification: Optional[bool] = None
    notification_email: Optional[str] = None


class ScheduleResponse(BaseModel):
    id: int
    user_id: int
    brand_id: int
    collection_frequency: str
    schedule_type: Optional[str]  # Legacy field
    is_enabled: bool
    timezone: str
    # New collection tracking fields
    last_collection_at: Optional[datetime]
    next_collection_at: Optional[datetime]
    # Analysis tracking fields
    last_monthly_analysis_at: Optional[datetime]
    last_quarterly_analysis_at: Optional[datetime]
    last_annual_analysis_at: Optional[datetime]
    # Legacy fields for backward compatibility
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    last_batch_id: Optional[int]
    send_email_notification: bool
    notification_email: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HistoryResponse(BaseModel):
    id: int
    scheduled_task_id: int
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    batch_id: Optional[int]
    collection_responses: int
    analysis_responses: int
    error_message: Optional[str]

    model_config = {"from_attributes": True}


class SchedulePreview(BaseModel):
    """Preview of upcoming scheduled events"""
    next_collections: List[datetime]
    next_monthly_analysis: Optional[datetime]
    next_quarterly_analysis: Optional[datetime]
    next_annual_analysis: Optional[datetime]


# === Helper Functions ===

COLLECTION_DAYS = [1, 7, 14, 21]  # Days of each month for data collection


def calculate_next_collection(frequency: str = None, timezone_str: str = 'UTC') -> datetime:
    """
    Calculate the next collection time (1st, 7th, 14th, or 21st of month at 6:30 AM UTC).

    Args:
        frequency: Ignored (kept for backward compatibility). All brands use fixed schedule.
        timezone_str: User's timezone (e.g., 'America/New_York')

    Returns:
        datetime: Next collection time in UTC (timezone-naive for DB storage)
    """
    try:
        tz = pytz.timezone(timezone_str)
    except:
        tz = pytz.UTC

    now = datetime.now(tz)

    # Find the next collection day (1st, 7th, 14th, or 21st)
    for day in COLLECTION_DAYS:
        if day > now.day:
            # This month, future day
            next_run = now.replace(day=day, hour=6, minute=30, second=0, microsecond=0)
            return next_run.astimezone(pytz.UTC).replace(tzinfo=None)
        elif day == now.day:
            # Today - check if time has passed
            potential = now.replace(hour=6, minute=30, second=0, microsecond=0)
            if now < potential:
                return potential.astimezone(pytz.UTC).replace(tzinfo=None)

    # All collection days this month have passed, go to 1st of next month
    if now.month == 12:
        next_run = now.replace(year=now.year + 1, month=1, day=1, hour=6, minute=30, second=0, microsecond=0)
    else:
        next_run = now.replace(month=now.month + 1, day=1, hour=6, minute=30, second=0, microsecond=0)

    # Convert to UTC for storage (remove tzinfo for SQLAlchemy compatibility)
    return next_run.astimezone(pytz.UTC).replace(tzinfo=None)


def calculate_next_run(schedule_type: str, timezone_str: str) -> datetime:
    """
    LEGACY: Calculate the next run time based on schedule type.
    Kept for backward compatibility. New code should use calculate_next_collection().
    """
    try:
        tz = pytz.timezone(timezone_str)
    except:
        tz = pytz.UTC

    now = datetime.now(tz)

    if schedule_type == 'first_day':
        # Next first day of month at 3:30 AM
        if now.day == 1 and (now.hour < 3 or (now.hour == 3 and now.minute < 30)):
            next_run = now.replace(hour=3, minute=30, second=0, microsecond=0)
        else:
            # Go to next month
            if now.month == 12:
                next_run = now.replace(year=now.year + 1, month=1, day=1, hour=3, minute=30, second=0, microsecond=0)
            else:
                next_run = now.replace(month=now.month + 1, day=1, hour=3, minute=30, second=0, microsecond=0)

    elif schedule_type == 'middle':
        # 15th of month at 3:30 AM
        if now.day < 15 or (now.day == 15 and (now.hour < 3 or (now.hour == 3 and now.minute < 30))):
            next_run = now.replace(day=15, hour=3, minute=30, second=0, microsecond=0)
        else:
            # Go to 15th of next month
            if now.month == 12:
                next_run = now.replace(year=now.year + 1, month=1, day=15, hour=3, minute=30, second=0, microsecond=0)
            else:
                next_run = now.replace(month=now.month + 1, day=15, hour=3, minute=30, second=0, microsecond=0)

    elif schedule_type == 'last_day':
        # Last day of month at 3:30 AM
        last_day = calendar.monthrange(now.year, now.month)[1]

        if now.day < last_day or (now.day == last_day and (now.hour < 3 or (now.hour == 3 and now.minute < 30))):
            next_run = now.replace(day=last_day, hour=3, minute=30, second=0, microsecond=0)
        else:
            # Go to last day of next month
            if now.month == 12:
                next_year = now.year + 1
                next_month = 1
            else:
                next_year = now.year
                next_month = now.month + 1

            last_day = calendar.monthrange(next_year, next_month)[1]
            next_run = now.replace(year=next_year, month=next_month, day=last_day, hour=3, minute=30, second=0, microsecond=0)

    else:
        raise ValueError(f"Invalid schedule_type: {schedule_type}")

    # Convert to UTC for storage
    return next_run.astimezone(pytz.UTC).replace(tzinfo=None)


def get_upcoming_analysis_dates(frequency: str, timezone_str: str) -> dict:
    """
    Calculate the next analysis dates based on collection frequency.

    Returns dict with:
    - next_monthly_analysis: First collection after start of next month
    - next_quarterly_analysis: First collection of next quarter start month
    - next_annual_analysis: First collection of next January
    """
    try:
        tz = pytz.timezone(timezone_str)
    except:
        tz = pytz.UTC

    now = datetime.now(tz)

    # Helper to get first collection date of a specific month
    def first_collection_of_month(year: int, month: int) -> datetime:
        if frequency == 'weekly':
            # First Monday of the month at 3:30 AM
            first_day = datetime(year, month, 1, 3, 30, 0)
            first_day = tz.localize(first_day)
            days_until_monday = (7 - first_day.weekday()) % 7
            return (first_day + timedelta(days=days_until_monday)).astimezone(pytz.UTC).replace(tzinfo=None)
        else:  # monthly
            # 1st of the month at 3:30 AM
            return tz.localize(datetime(year, month, 1, 3, 30, 0)).astimezone(pytz.UTC).replace(tzinfo=None)

    # Next monthly analysis: first collection of next month
    if now.month == 12:
        next_month_year, next_month = now.year + 1, 1
    else:
        next_month_year, next_month = now.year, now.month + 1
    next_monthly = first_collection_of_month(next_month_year, next_month)

    # Next quarterly analysis: first collection of next quarter start month (Jan/Apr/Jul/Oct)
    current_quarter = (now.month - 1) // 3 + 1
    if current_quarter == 4:
        next_quarter_month = 1
        next_quarter_year = now.year + 1
    else:
        next_quarter_month = (current_quarter * 3) + 1
        next_quarter_year = now.year
    next_quarterly = first_collection_of_month(next_quarter_year, next_quarter_month)

    # Next annual analysis: first collection of next January
    next_jan_year = now.year + 1 if now.month >= 1 else now.year
    next_annual = first_collection_of_month(next_jan_year, 1)

    return {
        "next_monthly_analysis": next_monthly,
        "next_quarterly_analysis": next_quarterly,
        "next_annual_analysis": next_annual
    }


# === Endpoints ===

@router.get("/", response_model=Optional[ScheduleResponse])
async def get_schedule(
    brand_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get the current schedule for a brand"""
    schedule = db.query(ScheduledTask).filter_by(
        user_id=current_user.id,
        brand_id=brand_id
    ).first()

    return schedule


@router.post("/", response_model=ScheduleResponse)
async def create_or_update_schedule(
    schedule_data: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create or update a schedule"""
    # Validate collection_frequency
    if schedule_data.collection_frequency not in ['weekly', 'monthly']:
        raise HTTPException(
            status_code=400,
            detail="Invalid collection_frequency. Must be 'weekly' or 'monthly'"
        )

    timezone = schedule_data.timezone or 'UTC'
    next_collection = calculate_next_collection(schedule_data.collection_frequency, timezone)

    # Check if schedule already exists
    existing = db.query(ScheduledTask).filter_by(
        user_id=current_user.id,
        brand_id=schedule_data.brand_id
    ).first()

    if existing:
        # Update existing
        existing.collection_frequency = schedule_data.collection_frequency
        existing.timezone = timezone
        existing.is_enabled = True
        existing.send_email_notification = schedule_data.send_email_notification
        existing.notification_email = schedule_data.notification_email
        existing.next_collection_at = next_collection
        # Keep legacy fields updated for backward compatibility
        existing.next_run_at = next_collection
        existing.schedule_type = 'first_day' if schedule_data.collection_frequency == 'monthly' else None
        existing.updated_at = datetime.utcnow()
        schedule = existing
    else:
        # Create new
        schedule = ScheduledTask(
            user_id=current_user.id,
            brand_id=schedule_data.brand_id,
            collection_frequency=schedule_data.collection_frequency,
            schedule_type='first_day' if schedule_data.collection_frequency == 'monthly' else None,
            timezone=timezone,
            is_enabled=True,
            send_email_notification=schedule_data.send_email_notification,
            notification_email=schedule_data.notification_email,
            next_collection_at=next_collection,
            next_run_at=next_collection  # Legacy field
        )
        db.add(schedule)

    # Collections fire from one fixed cron for every brand, whatever frequency
    # or timezone is saved here, so the date shown must come from that cron.
    from ..scheduler import next_fixed_collection
    schedule.next_collection_at = next_fixed_collection(datetime.utcnow())
    schedule.next_run_at = schedule.next_collection_at  # Legacy field

    db.commit()
    db.refresh(schedule)
    return schedule


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    schedule_data: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an existing schedule"""
    schedule = db.query(ScheduledTask).filter_by(
        id=schedule_id,
        user_id=current_user.id
    ).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Update collection_frequency
    if schedule_data.collection_frequency is not None:
        if schedule_data.collection_frequency not in ['weekly', 'monthly']:
            raise HTTPException(status_code=400, detail="Invalid collection_frequency. Must be 'weekly' or 'monthly'")
        schedule.collection_frequency = schedule_data.collection_frequency
        schedule.next_collection_at = calculate_next_collection(
            schedule_data.collection_frequency,
            schedule.timezone
        )
        # Keep legacy fields updated
        schedule.next_run_at = schedule.next_collection_at
        schedule.schedule_type = 'first_day' if schedule_data.collection_frequency == 'monthly' else None

    # Legacy: Update schedule_type if provided (for backward compatibility)
    if schedule_data.schedule_type is not None:
        if schedule_data.schedule_type not in ['first_day', 'middle', 'last_day']:
            raise HTTPException(status_code=400, detail="Invalid schedule_type")
        schedule.schedule_type = schedule_data.schedule_type
        # Convert legacy schedule_type to collection_frequency
        schedule.collection_frequency = 'monthly'
        schedule.next_run_at = calculate_next_run(
            schedule_data.schedule_type,
            schedule.timezone
        )
        schedule.next_collection_at = schedule.next_run_at

    if schedule_data.is_enabled is not None:
        schedule.is_enabled = schedule_data.is_enabled

    if schedule_data.timezone is not None:
        schedule.timezone = schedule_data.timezone
        # Recalculate next collection with new timezone
        frequency = schedule.collection_frequency or 'monthly'
        schedule.next_collection_at = calculate_next_collection(frequency, schedule.timezone)
        schedule.next_run_at = schedule.next_collection_at

    if schedule_data.send_email_notification is not None:
        schedule.send_email_notification = schedule_data.send_email_notification

    if schedule_data.notification_email is not None:
        schedule.notification_email = schedule_data.notification_email

    schedule.updated_at = datetime.utcnow()

    # Collections fire from one fixed cron for every brand, whatever frequency
    # or timezone is saved here, so the date shown must come from that cron.
    from ..scheduler import next_fixed_collection
    schedule.next_collection_at = next_fixed_collection(datetime.utcnow())
    schedule.next_run_at = schedule.next_collection_at  # Legacy field

    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a schedule"""
    schedule = db.query(ScheduledTask).filter_by(
        id=schedule_id,
        user_id=current_user.id
    ).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    db.delete(schedule)
    db.commit()
    return {"message": "Schedule deleted successfully"}


@router.get("/{schedule_id}/history", response_model=List[HistoryResponse])
async def get_schedule_history(
    schedule_id: int,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get execution history for a schedule"""
    schedule = db.query(ScheduledTask).filter_by(
        id=schedule_id,
        user_id=current_user.id
    ).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    history = db.query(ScheduledTaskHistory).filter_by(
        scheduled_task_id=schedule_id
    ).order_by(desc(ScheduledTaskHistory.started_at)).limit(limit).all()

    return history


@router.get("/preview", response_model=SchedulePreview)
async def preview_schedule(
    collection_frequency: str,
    timezone: str = 'UTC',
    current_user: User = Depends(get_current_user)
):
    """
    Preview the schedule for a given frequency.
    Shows next 6 collection dates and upcoming analysis dates.
    """
    if collection_frequency not in ['weekly', 'monthly']:
        raise HTTPException(
            status_code=400,
            detail="Invalid collection_frequency. Must be 'weekly' or 'monthly'"
        )

    # Calculate next 6 collection dates (1st, 7th, 14th, 21st of each month)
    next_collections = []
    current_next = calculate_next_collection(collection_frequency, timezone)
    next_collections.append(current_next)

    for _ in range(5):
        # Find the next collection day after current_next
        current_day = current_next.day
        current_day_idx = COLLECTION_DAYS.index(current_day) if current_day in COLLECTION_DAYS else -1

        if current_day_idx < len(COLLECTION_DAYS) - 1:
            # Move to next collection day this month
            next_day = COLLECTION_DAYS[current_day_idx + 1]
            current_next = current_next.replace(day=next_day)
        else:
            # Move to 1st of next month
            if current_next.month == 12:
                current_next = current_next.replace(year=current_next.year + 1, month=1, day=1)
            else:
                current_next = current_next.replace(month=current_next.month + 1, day=1)
        next_collections.append(current_next)

    # Get upcoming analysis dates
    analysis_dates = get_upcoming_analysis_dates(collection_frequency, timezone)

    return SchedulePreview(
        next_collections=next_collections,
        next_monthly_analysis=analysis_dates["next_monthly_analysis"],
        next_quarterly_analysis=analysis_dates["next_quarterly_analysis"],
        next_annual_analysis=analysis_dates["next_annual_analysis"]
    )


class SystemScheduleResponse(BaseModel):
    """Fixed system-wide schedule information"""
    collection: dict
    analysis: dict
    next_collection: datetime
    next_monthly_analysis: datetime
    next_quarterly_analysis: datetime
    next_annual_analysis: datetime


@router.get("/system-schedule", response_model=SystemScheduleResponse)
async def get_system_schedule():
    """
    Get the fixed system-wide schedule for all brands.

    This endpoint returns the automated schedule that applies to ALL brands:
    - Data collection + analysis: 1st, 7th, 14th, 21st of each month at 6:30 AM UTC (silent, no email)
    - Monthly report: 1st of each month at 6:00 AM UTC (email sent)
    - Quarterly report: Apr 1, Jul 1, Oct 1, Jan 1 at 7:00 AM UTC (email sent)
    - Annual report: January 1 at 8:00 AM UTC (email sent)

    Individual brand schedules can only control:
    - is_enabled: Whether to participate in automated collection
    - send_email_notification: Whether to receive report notifications
    - notification_email: Where to send notifications
    """
    now = datetime.utcnow()

    # Calculate next collection date (1st, 7th, 14th, or 21st at 6:30 AM UTC)
    next_collection_date = None
    for day in COLLECTION_DAYS:
        if day > now.day:
            next_collection_date = now.replace(day=day, hour=6, minute=30, second=0, microsecond=0)
            break
        elif day == now.day and (now.hour < 6 or (now.hour == 6 and now.minute < 30)):
            next_collection_date = now.replace(hour=6, minute=30, second=0, microsecond=0)
            break

    if next_collection_date is None:
        # Move to 1st of next month
        if now.month == 12:
            next_collection_date = datetime(now.year + 1, 1, 1, 6, 30, 0)
        else:
            next_collection_date = datetime(now.year, now.month + 1, 1, 6, 30, 0)

    # Calculate next 1st of month at 6:00 AM UTC (monthly report)
    if now.day == 1 and now.hour < 6:
        next_first = now.replace(hour=6, minute=0, second=0, microsecond=0)
    elif now.month == 12:
        next_first = datetime(now.year + 1, 1, 1, 6, 0, 0)
    else:
        next_first = datetime(now.year, now.month + 1, 1, 6, 0, 0)

    # Calculate next quarter start (Jan, Apr, Jul, Oct) at 7:00 AM UTC (quarterly report)
    quarter_months = [1, 4, 7, 10]
    current_quarter_idx = (now.month - 1) // 3
    next_quarter_month = quarter_months[(current_quarter_idx + 1) % 4]
    next_quarter_year = now.year if next_quarter_month > now.month else now.year + 1
    # Check if we're on quarter start day before 7 AM
    if now.month in quarter_months and now.day == 1 and now.hour < 7:
        next_quarter = now.replace(hour=7, minute=0, second=0, microsecond=0)
    else:
        next_quarter = datetime(next_quarter_year, next_quarter_month, 1, 7, 0, 0)

    # Calculate next January 1 at 8:00 AM UTC (annual report)
    if now.month == 1 and now.day == 1 and now.hour < 8:
        next_annual = now.replace(hour=8, minute=0, second=0, microsecond=0)
    else:
        next_annual = datetime(now.year + 1, 1, 1, 8, 0, 0)

    return SystemScheduleResponse(
        collection={
            "frequency": "monthly",
            "days": [1, 7, 14, 21],
            "time_utc": "06:30"
        },
        analysis={
            "monthly": {"day": 1, "time_utc": "06:00"},
            "quarterly": {"months": [1, 4, 7, 10], "day": 1, "time_utc": "07:00"},
            "annual": {"month": 1, "day": 1, "time_utc": "08:00"}
        },
        next_collection=next_collection_date,
        next_monthly_analysis=next_first,
        next_quarterly_analysis=next_quarter,
        next_annual_analysis=next_annual
    )
