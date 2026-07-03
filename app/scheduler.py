"""
Background scheduler service for automated tasks

SCHEDULING SYSTEM (Updated - January 2026):
- Collection + Analysis: On the 1st, 7th, 14th, and 21st of each month at 6:30 AM UTC
  - Analysis runs immediately after each collection (silently, no email)
- Reports: Generated on fixed schedules:
  - Monthly: 1st of each month at 6:00 AM UTC (previous month)
  - Quarterly: Apr 1, Jul 1, Oct 1, Jan 1 at 7:00 AM UTC (previous quarter)
  - Annual: Jan 1 at 8:00 AM UTC (previous year)

KEY BEHAVIORS:
- Collection and analysis run silently (no email notifications)
- Email notifications ONLY sent when reports are generated
- Manual runs still available with immediate analysis and report
- On Jan 1: Both Q4 quarterly and annual reports are generated

FIXED ISSUES:
- Uses direct data_pipeline calls instead of broken subprocess scripts
- Thread pool limits concurrent scheduled runs (max 50)
- Better error handling and logging
"""
import asyncio
import time
import os
import calendar
from concurrent.futures import ThreadPoolExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pytz
import logging

from .database import SessionLocal
from .models import ScheduledTask, ScheduledTaskHistory, User, BrandInfo, CollectionBatch
from .services.site_config import get_site_url
from .services.email_notifications import send_email

logger = logging.getLogger(__name__)

# Check if scheduler should be enabled (controlled by environment variable)
def is_scheduler_enabled() -> bool:
    """
    Check if the scheduler should be enabled based on ENABLE_SCHEDULER environment variable.

    Returns:
        bool: True if scheduler should run, False otherwise (e.g., on localhost)
    """
    enable_scheduler = os.getenv('ENABLE_SCHEDULER', 'false').lower()
    return enable_scheduler in ('true', '1', 'yes')


# === Schedule Calculation Helpers ===

def calculate_next_collection(frequency: str, timezone_str: str) -> datetime:
    """
    Calculate the next collection time based on frequency.

    Args:
        frequency: 'weekly' or 'monthly'
        timezone_str: User's timezone (e.g., 'America/New_York')

    Returns:
        datetime: Next collection time in UTC
    """
    try:
        tz = pytz.timezone(timezone_str)
    except:
        tz = pytz.UTC

    now = datetime.now(tz)

    if frequency == 'weekly':
        # Next Monday at 3:30 AM
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            # Today is Monday
            if now.hour < 3 or (now.hour == 3 and now.minute < 30):
                # Haven't reached 3:30 AM yet
                next_run = now.replace(hour=3, minute=30, second=0, microsecond=0)
            else:
                # Already past 3:30 AM, go to next Monday
                next_run = (now + timedelta(days=7)).replace(hour=3, minute=30, second=0, microsecond=0)
        else:
            next_run = (now + timedelta(days=days_until_monday)).replace(hour=3, minute=30, second=0, microsecond=0)

    elif frequency == 'monthly':
        # 1st of next month at 3:30 AM
        if now.day == 1 and (now.hour < 3 or (now.hour == 3 and now.minute < 30)):
            next_run = now.replace(hour=3, minute=30, second=0, microsecond=0)
        else:
            # Go to 1st of next month
            if now.month == 12:
                next_run = now.replace(year=now.year + 1, month=1, day=1, hour=3, minute=30, second=0, microsecond=0)
            else:
                next_run = now.replace(month=now.month + 1, day=1, hour=3, minute=30, second=0, microsecond=0)

    else:
        raise ValueError(f"Invalid frequency: {frequency}")

    # Convert to UTC for storage
    return next_run.astimezone(pytz.UTC).replace(tzinfo=None)


def get_period_date_range(period_type: str, reference_date: datetime) -> tuple:
    """
    Get the date range for an analysis period.

    Args:
        period_type: 'monthly', 'quarterly', or 'annual'
        reference_date: The date to calculate the period from (typically the collection date)

    Returns:
        tuple: (start_date, end_date, period_label)
            - For monthly: previous complete month
            - For quarterly: previous complete quarter
            - For annual: previous complete year
    """
    if period_type == 'monthly':
        # Previous complete month
        first_of_this_month = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = first_of_this_month - timedelta(seconds=1)  # Last moment of previous month
        start_date = (first_of_this_month - relativedelta(months=1))
        label = start_date.strftime('%B %Y')  # e.g., "December 2025"

    elif period_type == 'quarterly':
        # Calendar quarters: Q1 (Jan-Mar), Q2 (Apr-Jun), Q3 (Jul-Sep), Q4 (Oct-Dec)
        current_quarter = (reference_date.month - 1) // 3 + 1
        current_year = reference_date.year

        # Previous quarter
        if current_quarter == 1:
            prev_quarter = 4
            prev_year = current_year - 1
        else:
            prev_quarter = current_quarter - 1
            prev_year = current_year

        # Quarter start/end months
        quarter_start_month = (prev_quarter - 1) * 3 + 1
        quarter_end_month = prev_quarter * 3

        start_date = datetime(prev_year, quarter_start_month, 1, 0, 0, 0)
        # Last day of quarter end month
        last_day = calendar.monthrange(prev_year, quarter_end_month)[1]
        end_date = datetime(prev_year, quarter_end_month, last_day, 23, 59, 59)

        label = f"Q{prev_quarter} {prev_year}"  # e.g., "Q4 2025"

    elif period_type == 'annual':
        # Previous complete year
        prev_year = reference_date.year - 1
        start_date = datetime(prev_year, 1, 1, 0, 0, 0)
        end_date = datetime(prev_year, 12, 31, 23, 59, 59)
        label = f"{prev_year} Annual Report"  # e.g., "2025 Annual Report"

    else:
        raise ValueError(f"Invalid period_type: {period_type}")

    return start_date, end_date, label


def is_first_collection_of_month(db: Session, schedule: ScheduledTask, collection_date: datetime) -> bool:
    """
    Check if this is the first collection of the current month.

    Args:
        db: Database session
        schedule: The scheduled task
        collection_date: The date of the collection

    Returns:
        bool: True if this is the first collection of the month
    """
    # Get the start of the current month
    month_start = collection_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Check for any completed collections this month before this date
    previous_collections = db.query(CollectionBatch).filter(
        CollectionBatch.brand_id == schedule.brand_id,
        CollectionBatch.started_at >= month_start,
        CollectionBatch.started_at < collection_date,
        CollectionBatch.status == 'completed'
    ).count()

    return previous_collections == 0


def check_analysis_triggers(db: Session, schedule: ScheduledTask, collection_date: datetime) -> list:
    """
    Determine which analyses should run after this collection.

    Args:
        db: Database session
        schedule: The scheduled task
        collection_date: The date of the collection

    Returns:
        list: List of analysis types to run ('monthly', 'quarterly', 'annual')
    """
    triggers = []

    # Only trigger analysis on first collection of the month
    if not is_first_collection_of_month(db, schedule, collection_date):
        return triggers

    # Monthly analysis: Always runs on first collection of any month
    triggers.append('monthly')

    # Quarterly analysis: First collection of Jan, Apr, Jul, Oct
    if collection_date.month in [1, 4, 7, 10]:
        triggers.append('quarterly')

    # Annual analysis: First collection of January
    if collection_date.month == 1:
        triggers.append('annual')

    return triggers

# Global scheduler instance
scheduler = AsyncIOScheduler()

# Thread pool for scheduled tasks (limits concurrent runs to prevent overload)
_executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="scheduled_task_")

# Track currently running schedules to prevent duplicates
_running_schedules = set()

# Track currently running brand collections to prevent duplicates
_running_brands = set()


# === NEW SYSTEM-WIDE COLLECTION AND ANALYSIS FUNCTIONS ===

async def run_scheduled_collection_all_brands():
    """
    Run data collection AND analysis for ALL enabled brands.

    This runs on the 1st, 7th, 14th, and 21st of each month at 6:30 AM UTC.
    Collection runs first, then analysis runs on the collected responses.
    Email notifications are NOT sent (silent collection + analysis).
    Reports are generated separately on scheduled dates.
    """
    logger.info("=" * 60)
    logger.info("SCHEDULED COLLECTION + ANALYSIS: Starting for all enabled brands")
    logger.info("=" * 60)

    db = SessionLocal()

    try:
        # Get all enabled scheduled tasks
        enabled_tasks = db.query(ScheduledTask).filter(
            ScheduledTask.is_enabled == True
        ).all()

        logger.info(f"Found {len(enabled_tasks)} enabled brands for collection + analysis")

        for task in enabled_tasks:
            # Skip if already running
            brand_key = (task.user_id, task.brand_id)
            if brand_key in _running_brands:
                logger.debug(f"Brand {task.brand_id} already running, skipping")
                continue

            # Check minimum gap (1 hour since last collection)
            if task.last_collection_at:
                time_since_last = datetime.utcnow() - task.last_collection_at
                if time_since_last < timedelta(hours=1):
                    logger.debug(f"Brand {task.brand_id} collected recently, skipping")
                    continue

            logger.info(f"Queuing collection + analysis for brand {task.brand_id} (user {task.user_id})")

            # Execute in thread pool
            def run_collection_analysis_wrapper(schedule_id, user_id, brand_id):
                asyncio.run(execute_collection_and_analysis(schedule_id, user_id, brand_id))

            _executor.submit(run_collection_analysis_wrapper, task.id, task.user_id, task.brand_id)

        logger.info("Scheduled collection + analysis jobs submitted to thread pool")

    except Exception as e:
        logger.error(f"Error in scheduled collection + analysis: {str(e)}", exc_info=True)

    finally:
        db.close()


async def run_monthly_report_all_brands():
    """
    Generate monthly reports for ALL enabled brands.

    This runs on the 1st of each month at 6:00 AM UTC.
    Generates reports from the previous month's already-analyzed data.
    Email notifications ARE sent when reports are ready.
    """
    logger.info("=" * 60)
    logger.info("MONTHLY REPORT GENERATION: Starting for all enabled brands")
    logger.info("=" * 60)

    reference_date = datetime.utcnow()
    await run_report_generation_all_brands('monthly', reference_date)


async def run_quarterly_report_all_brands():
    """
    Generate quarterly reports for ALL enabled brands.

    This runs on Apr 1, Jul 1, Oct 1, Jan 1 at 7:00 AM UTC.
    Generates reports from the previous quarter's already-analyzed data.
    Email notifications ARE sent when reports are ready.
    """
    logger.info("=" * 60)
    logger.info("QUARTERLY REPORT GENERATION: Starting for all enabled brands")
    logger.info("=" * 60)

    reference_date = datetime.utcnow()
    await run_report_generation_all_brands('quarterly', reference_date)


async def run_annual_report_all_brands():
    """
    Generate annual reports for ALL enabled brands.

    This runs on January 1 at 8:00 AM UTC.
    Generates reports from the previous year's already-analyzed data.
    Email notifications ARE sent when reports are ready.
    """
    logger.info("=" * 60)
    logger.info("ANNUAL REPORT GENERATION: Starting for all enabled brands")
    logger.info("=" * 60)

    reference_date = datetime.utcnow()
    await run_report_generation_all_brands('annual', reference_date)


async def run_report_generation_all_brands(period_type: str, reference_date: datetime):
    """
    Generate reports for all enabled brands (report-only, no analysis).

    This uses already-analyzed response data to generate periodic reports.
    Analysis is done separately during weekly collection runs.

    Args:
        period_type: 'monthly', 'quarterly', or 'annual'
        reference_date: Reference date for calculating the period
    """
    db = SessionLocal()

    try:
        # Get all enabled scheduled tasks
        enabled_tasks = db.query(ScheduledTask).filter(
            ScheduledTask.is_enabled == True
        ).all()

        logger.info(f"Found {len(enabled_tasks)} enabled brands for {period_type} report generation")

        # Calculate period dates once (same for all brands)
        start_date, end_date, period_label = get_period_date_range(period_type, reference_date)
        logger.info(f"Report period: {period_label} ({start_date} to {end_date})")

        for task in enabled_tasks:
            try:
                logger.info(f"Generating {period_type} report for brand {task.brand_id}")
                await execute_report_generation(task.id, period_type, reference_date)
            except Exception as e:
                logger.error(f"Failed {period_type} report for brand {task.brand_id}: {e}")
                continue

        logger.info(f"Completed {period_type} report generation for all brands")

    except Exception as e:
        logger.error(f"Error in {period_type} report generation: {str(e)}", exc_info=True)

    finally:
        db.close()


async def execute_collection_only(schedule_id: int, user_id: int, brand_id: int):
    """
    Execute data collection ONLY (no analysis or report).

    Used by weekly scheduled collection.
    Does NOT send email notifications.
    """
    brand_key = (user_id, brand_id)

    # Prevent duplicate runs
    if brand_key in _running_brands:
        logger.warning(f"Brand {brand_id} is already running, skipping")
        return

    _running_brands.add(brand_key)
    db = SessionLocal()

    try:
        schedule = db.query(ScheduledTask).filter_by(id=schedule_id).first()
        if not schedule or not schedule.is_enabled:
            logger.info(f"Schedule {schedule_id} not found or not enabled, skipping")
            return

        collection_date = datetime.utcnow()
        logger.info(f"Starting collection-only for brand {brand_id} (schedule {schedule_id})")

        # Update last_collection_at immediately
        schedule.last_collection_at = collection_date
        schedule.last_run_at = collection_date  # Legacy field
        db.commit()

        # Create history entry
        history = ScheduledTaskHistory(
            scheduled_task_id=schedule.id,
            user_id=user_id,
            brand_id=brand_id,
            started_at=collection_date,
            status='running'
        )
        db.add(history)
        db.commit()
        db.refresh(history)

        # Run collection only using the data pipeline
        from app.services.data_pipeline import run_collection_only

        result = run_collection_only(
            user_id=user_id,
            brand_id=brand_id,
            triggered_by="scheduled"
        )

        if result.get("success"):
            history.status = 'success'
            history.collection_responses = result.get("responses_collected", 0)
            logger.info(f"Collection completed for brand {brand_id}: {history.collection_responses} responses")
        else:
            history.status = 'failed'
            history.error_message = result.get("error", "Unknown error")
            logger.warning(f"Collection failed for brand {brand_id}: {history.error_message}")

        history.completed_at = datetime.utcnow()
        db.commit()

        # NOTE: No email notification for collection-only runs

    except Exception as e:
        logger.error(f"Error in collection-only for brand {brand_id}: {str(e)}", exc_info=True)
        if 'history' in locals():
            try:
                history.status = 'failed'
                history.error_message = f"Unexpected error: {str(e)}"
                history.completed_at = datetime.utcnow()
                db.commit()
            except:
                pass

    finally:
        db.close()
        _running_brands.discard(brand_key)


async def execute_collection_and_analysis(schedule_id: int, user_id: int, brand_id: int):
    """
    Execute data collection followed by analysis (no report, no email).

    Used by weekly scheduled collection.
    Does NOT send email notifications - those only go out with reports.

    Steps:
    1. Run collection to gather responses from LLM platforms
    2. Run analysis on the newly collected responses
    """
    brand_key = (user_id, brand_id)

    # Prevent duplicate runs
    if brand_key in _running_brands:
        logger.warning(f"Brand {brand_id} is already running, skipping")
        return

    _running_brands.add(brand_key)
    db = SessionLocal()

    try:
        schedule = db.query(ScheduledTask).filter_by(id=schedule_id).first()
        if not schedule or not schedule.is_enabled:
            logger.info(f"Schedule {schedule_id} not found or not enabled, skipping")
            return

        collection_date = datetime.utcnow()
        logger.info(f"Starting collection + analysis for brand {brand_id} (schedule {schedule_id})")

        # Update last_collection_at immediately
        schedule.last_collection_at = collection_date
        schedule.last_run_at = collection_date  # Legacy field
        db.commit()

        # Create history entry
        history = ScheduledTaskHistory(
            scheduled_task_id=schedule.id,
            user_id=user_id,
            brand_id=brand_id,
            started_at=collection_date,
            status='running'
        )
        db.add(history)
        db.commit()
        db.refresh(history)

        # STEP 1: Run collection
        from app.services.data_pipeline import run_collection_only

        collection_result = run_collection_only(
            user_id=user_id,
            brand_id=brand_id,
            triggered_by="scheduled"
        )

        if not collection_result.get("success"):
            history.status = 'failed'
            history.error_message = collection_result.get("error", "Collection failed")
            history.completed_at = datetime.utcnow()
            db.commit()
            logger.warning(f"Collection failed for brand {brand_id}: {history.error_message}")
            return

        history.collection_responses = collection_result.get("responses_collected", 0)
        db.commit()
        logger.info(f"Collection completed for brand {brand_id}: {history.collection_responses} responses")

        # STEP 2: Run analysis on the collected responses
        from app.services.data_pipeline import run_analysis_only

        batch_id = collection_result.get("batch_id")
        if batch_id:
            analysis_result = run_analysis_only(
                user_id=user_id,
                brand_id=brand_id,
                batch_id=batch_id,
                triggered_by="scheduled"
            )

            if analysis_result.get("success"):
                history.analysis_responses = analysis_result.get("responses_analyzed", 0)
                history.status = 'success'
                logger.info(f"Analysis completed for brand {brand_id}: {history.analysis_responses} responses analyzed")
            else:
                # Analysis failed but collection succeeded - partial success
                history.status = 'partial'
                history.error_message = f"Collection OK, analysis failed: {analysis_result.get('error', 'Unknown')}"
                logger.warning(f"Analysis failed for brand {brand_id}: {history.error_message}")
        else:
            # No batch ID means no responses collected
            history.status = 'success'
            logger.info(f"No new responses to analyze for brand {brand_id}")

        history.completed_at = datetime.utcnow()
        db.commit()

        # NOTE: No email notification - collection + analysis runs silently
        logger.info(f"Completed collection + analysis for brand {brand_id}")

    except Exception as e:
        logger.error(f"Error in collection + analysis for brand {brand_id}: {str(e)}", exc_info=True)
        if 'history' in locals():
            try:
                history.status = 'failed'
                history.error_message = f"Unexpected error: {str(e)}"
                history.completed_at = datetime.utcnow()
                db.commit()
            except:
                pass

    finally:
        db.close()
        _running_brands.discard(brand_key)


async def execute_scheduled_collection(schedule_id: int):
    """
    Execute a full data collection pipeline (collection + analysis + report).

    LEGACY FUNCTION: In the new scheduling system (Jan 2026), weekly scheduled
    collections use execute_collection_only() instead. This function is kept for:
    - Manual runs from the admin panel
    - Backward compatibility

    After collection completes, check if any analyses should be triggered
    (monthly, quarterly, annual) based on whether this is the first collection
    of the relevant period.
    """
    # Prevent duplicate runs
    if schedule_id in _running_schedules:
        logger.warning(f"Schedule {schedule_id} is already running, skipping duplicate execution")
        return

    _running_schedules.add(schedule_id)
    db = SessionLocal()

    try:
        schedule = db.query(ScheduledTask).filter_by(id=schedule_id).first()
        if not schedule or not schedule.is_enabled:
            logger.info(f"Schedule {schedule_id} not found or not enabled, skipping")
            return

        # Safety check: Don't run if last collection was less than 1 hour ago
        last_collection = schedule.last_collection_at or schedule.last_run_at  # Fallback for legacy
        if last_collection:
            time_since_last = datetime.utcnow() - last_collection
            if time_since_last < timedelta(hours=1):
                logger.warning(f"Schedule {schedule_id} collected {time_since_last.total_seconds()/60:.1f} minutes ago, skipping (minimum 1 hour gap)")
                return

        collection_date = datetime.utcnow()
        logger.info(f"Starting scheduled collection {schedule_id} for user {schedule.user_id}, brand {schedule.brand_id}")

        # CRITICAL: Update timestamps IMMEDIATELY to prevent re-triggering
        frequency = schedule.collection_frequency or 'monthly'  # Fallback for legacy
        schedule.last_collection_at = collection_date
        schedule.last_run_at = collection_date  # Keep legacy field updated
        schedule.next_collection_at = calculate_next_collection(frequency, schedule.timezone)
        schedule.next_run_at = schedule.next_collection_at  # Keep legacy field updated
        db.commit()
        logger.info(f"Updated schedule {schedule_id}: next collection at {schedule.next_collection_at}")

        # Create history entry
        history = ScheduledTaskHistory(
            scheduled_task_id=schedule.id,
            user_id=schedule.user_id,
            brand_id=schedule.brand_id,
            started_at=collection_date,
            status='running'
        )
        db.add(history)
        db.commit()
        db.refresh(history)

        # Run collection + individual response analysis using the data pipeline
        from app.services.data_pipeline import run_collection_analysis_report

        result = run_collection_analysis_report(
            user_id=schedule.user_id,
            brand_id=schedule.brand_id,
            triggered_by="scheduled"
        )

        if not result["success"]:
            error_msg = result.get("error", "Failed to start pipeline")

            if "No active queries found" in error_msg:
                logger.warning(f"Schedule {schedule_id}: {error_msg} - not retrying")

            history.status = 'failed'
            history.error_message = error_msg
            history.completed_at = datetime.utcnow()
            db.commit()

            if schedule.send_email_notification:
                await send_completion_email(schedule, history, db, "collection")

            logger.error(f"Schedule {schedule_id} collection failed: {error_msg}")
            return

        task_id = result["task_id"]
        logger.info(f"Started collection pipeline with task_id {task_id}")

        # Wait for the pipeline to complete
        pipeline_success = await wait_for_pipeline_completion(task_id, db, timeout=7200)

        if pipeline_success:
            history.status = 'success'
            logger.info(f"Collection completed successfully for schedule {schedule_id}")

            # Check if any period analyses should be triggered
            analysis_triggers = check_analysis_triggers(db, schedule, collection_date)

            if analysis_triggers:
                logger.info(f"Triggering analyses for schedule {schedule_id}: {analysis_triggers}")

                for analysis_type in analysis_triggers:
                    try:
                        await execute_period_analysis(schedule_id, analysis_type, collection_date)
                    except Exception as e:
                        logger.error(f"Failed to run {analysis_type} analysis for schedule {schedule_id}: {e}")
        else:
            history.status = 'failed'
            history.error_message = 'Collection pipeline failed or timed out'
            logger.warning(f"Collection pipeline failed for schedule {schedule_id}")

        history.completed_at = datetime.utcnow()
        db.commit()

        if schedule.send_email_notification:
            await send_completion_email(schedule, history, db, "collection")

        logger.info(f"Completed scheduled collection {schedule_id} with status {history.status}")
        logger.info(f"Next collection scheduled for: {schedule.next_collection_at}")

    except Exception as e:
        logger.error(f"Error executing scheduled collection {schedule_id}: {str(e)}", exc_info=True)
        if 'history' in locals():
            try:
                history.status = 'failed'
                history.error_message = f"Unexpected error: {str(e)}"
                history.completed_at = datetime.utcnow()
                db.commit()

                if 'schedule' in locals() and schedule.send_email_notification:
                    await send_completion_email(schedule, history, db, "collection")
            except Exception as commit_error:
                logger.error(f"Failed to save error status: {str(commit_error)}")

    finally:
        db.close()
        _running_schedules.discard(schedule_id)


async def execute_report_generation(schedule_id: int, period_type: str, reference_date: datetime):
    """
    Generate a report for a specific period (report-only, no analysis).

    This is called by monthly/quarterly/annual report jobs.
    Uses already-analyzed response data to generate the report.
    Email notifications ARE sent when reports are ready.

    Args:
        schedule_id: The scheduled task ID
        period_type: 'monthly', 'quarterly', or 'annual'
        reference_date: The reference date for calculating the period
    """
    db = SessionLocal()

    try:
        schedule = db.query(ScheduledTask).filter_by(id=schedule_id).first()
        if not schedule:
            logger.warning(f"Schedule {schedule_id} not found for {period_type} report")
            return

        # Get the period date range
        start_date, end_date, period_label = get_period_date_range(period_type, reference_date)

        logger.info(f"Generating {period_type} report for schedule {schedule_id}: {period_label} ({start_date} to {end_date})")

        # Run report generation (report-only, uses existing analyzed data)
        from app.services.data_pipeline import run_period_report_only

        result = await run_period_report_only(
            user_id=schedule.user_id,
            brand_id=schedule.brand_id,
            period_type=period_type,
            period_start=start_date,
            period_end=end_date,
            period_label=period_label,
            triggered_by="scheduled"
        )

        if result.get("success"):
            # Update the appropriate last report timestamp
            if period_type == 'monthly':
                schedule.last_monthly_analysis_at = datetime.utcnow()
            elif period_type == 'quarterly':
                schedule.last_quarterly_analysis_at = datetime.utcnow()
            elif period_type == 'annual':
                schedule.last_annual_analysis_at = datetime.utcnow()
            db.commit()

            logger.info(f"Completed {period_type} report for schedule {schedule_id}: {period_label}")

            # Send email notification when reports are ready
            # (This is the ONLY time users receive emails)
            if schedule.send_email_notification:
                await send_report_email(schedule, period_type, period_label, db)
        else:
            logger.error(f"Failed {period_type} report for schedule {schedule_id}: {result.get('error')}")

            # Send failure notification if enabled
            if schedule.send_email_notification:
                await send_report_failure_email(schedule, period_type, period_label, result.get('error', 'Unknown error'), db)

    except Exception as e:
        logger.error(f"Error generating {period_type} report for schedule {schedule_id}: {str(e)}", exc_info=True)

    finally:
        db.close()


async def send_report_failure_email(schedule: ScheduledTask, period_type: str, period_label: str, error_message: str, db: Session):
    """Send email notification about failed report generation"""
    try:
        user = db.query(User).filter_by(id=schedule.user_id).first()
        brand = db.query(BrandInfo).filter_by(id=schedule.brand_id).first()

        if not user or not brand:
            logger.warning(f"Could not find user or brand for report failure notification")
            return

        email_to = schedule.notification_email or user.email

        period_type_display = period_type.capitalize()
        subject = f"TALES Alert: {period_type_display} Report Issue - {brand.brand_name}"
        body = f"""Your {period_type} report encountered an issue.

Brand: {brand.brand_name}
Report Period: {period_label}
Error: {error_message}

The system will automatically retry during the next scheduled run.
You can also manually generate a report from the Reports page.

View your dashboard: {get_site_url(db).rstrip('/')}/analytics

--
TALES - AI Reputation Intelligence & Optimization
"""

        await send_email(email_to, subject, body)
        logger.info(f"{period_type_display} report failure notification sent to {email_to}")

    except Exception as e:
        logger.error(f"Failed to send {period_type} report failure notification: {str(e)}")


# Legacy function for backward compatibility
async def execute_scheduled_task(schedule_id: int):
    """
    Legacy function - redirects to execute_scheduled_collection.
    Kept for backward compatibility during migration.
    """
    await execute_scheduled_collection(schedule_id)


async def wait_for_pipeline_completion(task_id: int, db: Session, timeout: int = 7200):
    """
    Wait for the data pipeline task to complete (collection + analysis + report).

    Args:
        task_id: The TaskStatus ID to monitor
        db: Database session
        timeout: Maximum seconds to wait

    Returns:
        bool: True if completed successfully, False otherwise
    """
    from .models import TaskStatus

    start_time = time.time()
    last_status = None

    while True:
        # Refresh session to get latest data
        db.expire_all()

        task = db.query(TaskStatus).filter_by(id=task_id).first()

        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        # Log status changes
        if task.status != last_status:
            logger.info(f"Task {task_id} status: {task.status} - {task.message}")
            last_status = task.status

        if task.status == 'completed':
            logger.info(f"Task {task_id} completed successfully")
            return True

        if task.status in ['failed', 'cancelled']:
            logger.warning(f"Task {task_id} finished with status: {task.status}")
            if task.error_message:
                logger.warning(f"Task {task_id} error: {task.error_message}")
            return False

        if time.time() - start_time > timeout:
            logger.warning(f"Task {task_id} timed out after {timeout}s")
            return False

        # Wait before polling again
        await asyncio.sleep(15)  # Poll every 15 seconds


async def send_completion_email(schedule: ScheduledTask, history: ScheduledTaskHistory, db: Session, task_type: str = "collection"):
    """Send email notification about completed collection task"""
    try:
        user = db.query(User).filter_by(id=schedule.user_id).first()
        brand = db.query(BrandInfo).filter_by(id=schedule.brand_id).first()

        if not user or not brand:
            logger.warning(f"Could not find user or brand for notification")
            return

        email_to = schedule.notification_email or user.email
        next_collection = schedule.next_collection_at or schedule.next_run_at

        if history.status == 'success':
            subject = f"TALES Data Collection Complete - {brand.brand_name}"
            body = f"""Your scheduled data collection has completed successfully!

Brand: {brand.brand_name}
Collection Date: {history.started_at.strftime('%B %d, %Y')}
Responses Collected: {history.collection_responses or 'Processing'}
Responses Analyzed: {history.analysis_responses or 'Processing'}

View your results: {get_site_url(db).rstrip('/')}/analytics

Next scheduled collection: {next_collection.strftime('%B %d, %Y at %I:%M %p') if next_collection else 'Not scheduled'}

--
TALES - AI Reputation Intelligence & Optimization
"""
        else:
            subject = f"TALES Alert: Collection Issue - {brand.brand_name}"
            body = f"""Your scheduled data collection encountered an issue.

Brand: {brand.brand_name}
Status: {history.status.upper()}
Started: {history.started_at.strftime('%B %d, %Y at %I:%M %p')}
Error: {history.error_message or 'Unknown error'}

Responses Collected: {history.collection_responses or 0}
Responses Analyzed: {history.analysis_responses or 0}

Please log in to review and manually re-run if needed: {get_site_url(db).rstrip('/')}/data

Next scheduled collection: {next_collection.strftime('%B %d, %Y at %I:%M %p') if next_collection else 'Not scheduled'}

--
TALES - AI Reputation Intelligence & Optimization
"""

        await send_email(email_to, subject, body)
        logger.info(f"Collection notification email sent to {email_to}")

    except Exception as e:
        logger.error(f"Failed to send collection notification email: {str(e)}")


async def send_report_email(schedule: ScheduledTask, period_type: str, period_label: str, db: Session):
    """Send email notification about completed report generation"""
    try:
        user = db.query(User).filter_by(id=schedule.user_id).first()
        brand = db.query(BrandInfo).filter_by(id=schedule.brand_id).first()

        if not user or not brand:
            logger.warning(f"Could not find user or brand for report notification")
            return

        email_to = schedule.notification_email or user.email

        period_type_display = period_type.capitalize()
        subject = f"TALES {period_type_display} Report Ready - {brand.brand_name}"
        body = f"""Your {period_type} report is ready!

Brand: {brand.brand_name}
Report Period: {period_label}
Report Type: {period_type_display} Report

View your report: {get_site_url(db).rstrip('/')}/reports

This report contains comprehensive analysis of all data collected during {period_label}.

--
TALES - AI Reputation Intelligence & Optimization
"""

        await send_email(email_to, subject, body)
        logger.info(f"{period_type_display} report notification email sent to {email_to}")

    except Exception as e:
        logger.error(f"Failed to send {period_type} report notification email: {str(e)}")


def check_and_schedule_tasks():
    """
    DEPRECATED (Jan 2026): This function is no longer used by the scheduler.

    The new scheduling system uses fixed cron jobs instead:
    - run_weekly_collection_all_brands() - Mondays at 3:30 AM UTC
    - run_monthly_analysis_all_brands() - 1st of month at 4:00 AM UTC
    - run_quarterly_analysis_all_brands() - Apr/Jul/Oct/Jan 1st at 5:00 AM UTC
    - run_annual_analysis_all_brands() - Jan 1 at 6:00 AM UTC

    This function is kept for backward compatibility and potential manual triggering.
    """
    db = SessionLocal()

    try:
        now = datetime.utcnow()

        # Find tasks ready to run
        # Check both new field (next_collection_at) and legacy field (next_run_at)
        from sqlalchemy import or_
        tasks = db.query(ScheduledTask).filter(
            and_(
                ScheduledTask.is_enabled == True,
                or_(
                    ScheduledTask.next_collection_at <= now,
                    and_(
                        ScheduledTask.next_collection_at.is_(None),
                        ScheduledTask.next_run_at <= now
                    )
                )
            )
        ).all()

        for task in tasks:
            # Skip if already running
            if task.id in _running_schedules:
                logger.debug(f"Task {task.id} already running, skipping")
                continue

            # Safety: Skip if collected very recently
            last_collection = task.last_collection_at or task.last_run_at
            if last_collection and (now - last_collection) < timedelta(minutes=55):
                logger.debug(f"Task {task.id} collected recently, skipping")
                continue

            next_time = task.next_collection_at or task.next_run_at
            logger.info(f"Found task {task.id} ready for collection (next_collection: {next_time})")

            # Execute the collection in thread pool
            def run_scheduled_collection(schedule_id):
                """Wrapper to run scheduled collection in thread pool"""
                asyncio.run(execute_scheduled_collection(schedule_id))

            # Submit to thread pool (max 50 concurrent tasks)
            _executor.submit(run_scheduled_collection, task.id)
            logger.info(f"Submitted task {task.id} to thread pool for collection")

    except Exception as e:
        logger.error(f"Error checking scheduled tasks: {str(e)}", exc_info=True)

    finally:
        db.close()


def start_scheduler():
    """
    Start the background scheduler with fixed cron jobs.

    Only runs if ENABLE_SCHEDULER=true.

    Schedule:
    - Weekly collection + analysis: Every Monday at 6:30 AM UTC
    - Monthly report: 1st of each month at 6:00 AM UTC
    - Quarterly report: Apr 1, Jul 1, Oct 1, Jan 1 at 7:00 AM UTC
    - Annual report: January 1 at 8:00 AM UTC
    """
    # Check if scheduler should be enabled
    if not is_scheduler_enabled():
        logger.info("Scheduler DISABLED (ENABLE_SCHEDULER=false) - scheduled tasks will not run")
        logger.info("This is expected on localhost. Set ENABLE_SCHEDULER=true in production to enable scheduled tasks.")
        return

    try:
        # Data collection + analysis: 1st, 7th, 14th, and 21st of each month at 6:30 AM UTC
        scheduler.add_job(
            lambda: asyncio.run(run_scheduled_collection_all_brands()),
            CronTrigger(day='1,7,14,21', hour=6, minute=30),
            id='scheduled_collection_analysis',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Scheduled: Data collection + analysis - 1st, 7th, 14th, 21st of each month at 6:30 AM UTC")

        # Monthly report: 1st of each month at 6:00 AM UTC
        scheduler.add_job(
            lambda: asyncio.run(run_monthly_report_all_brands()),
            CronTrigger(day=1, hour=6, minute=0),
            id='monthly_report',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Scheduled: Monthly report - 1st of each month at 6:00 AM UTC")

        # Quarterly report: Apr 1, Jul 1, Oct 1, Jan 1 at 7:00 AM UTC
        scheduler.add_job(
            lambda: asyncio.run(run_quarterly_report_all_brands()),
            CronTrigger(month='1,4,7,10', day=1, hour=7, minute=0),
            id='quarterly_report',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Scheduled: Quarterly report - Apr 1, Jul 1, Oct 1, Jan 1 at 7:00 AM UTC")

        # Annual report: January 1 at 8:00 AM UTC
        scheduler.add_job(
            lambda: asyncio.run(run_annual_report_all_brands()),
            CronTrigger(month=1, day=1, hour=8, minute=0),
            id='annual_report',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Scheduled: Annual report - January 1 at 8:00 AM UTC")

        scheduler.start()
        logger.info("=" * 60)
        logger.info("SCHEDULER ENABLED - Fixed cron jobs active")
        logger.info("  - Data collection + analysis: 1st/7th/14th/21st of month 6:30 AM UTC")
        logger.info("  - Monthly report: 1st of month 6:00 AM UTC")
        logger.info("  - Quarterly report: Apr/Jul/Oct/Jan 1st 7:00 AM UTC")
        logger.info("  - Annual report: Jan 1 8:00 AM UTC")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Failed to start scheduler: {str(e)}")


def stop_scheduler():
    """Stop the background scheduler"""
    try:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {str(e)}")
