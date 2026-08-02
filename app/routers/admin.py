"""
Admin API endpoints for managing all users' data.

Only accessible to admin users (is_admin=True).
Allows admins to view and manage all brands, queries, descriptors, and competitors
across all users for support and troubleshooting purposes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from .. import crud, models, schemas
from ..auth import get_current_admin_user
from ..database import get_db

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)]  # Require admin for all endpoints
)


# === User Management ===

@router.get("/users", response_model=List[schemas.User])
def get_all_users(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get all users in the system."""
    users = db.query(models.User).all()
    return users


@router.get("/users/{user_id}", response_model=schemas.User)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get a specific user by ID."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# === Brand Management ===

@router.get("/brands", response_model=List[schemas.BrandInfo])
def get_all_brands(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get all brands across all users."""
    brands = db.query(models.BrandInfo).all()
    return brands


@router.get("/users/{user_id}/brands", response_model=List[schemas.BrandInfo])
def get_user_brands(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get all brands for a specific user."""
    brands = db.query(models.BrandInfo).filter(
        models.BrandInfo.user_id == user_id
    ).all()
    return brands


@router.get("/brands/{brand_id}", response_model=schemas.BrandInfo)
def get_brand(
    brand_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get a specific brand by ID."""
    brand = db.query(models.BrandInfo).filter(models.BrandInfo.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    return brand


@router.put("/brands/{brand_id}", response_model=schemas.BrandInfo)
def update_brand(
    brand_id: int,
    brand_update: schemas.BrandInfoUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Update a brand (admin can modify any user's brand)."""
    brand = db.query(models.BrandInfo).filter(models.BrandInfo.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    update_data = brand_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(brand, key, value)

    db.commit()
    db.refresh(brand)
    return brand


# === Query Management ===

@router.get("/users/{user_id}/brands/{brand_id}/queries", response_model=List[schemas.Query])
def get_user_brand_queries(
    user_id: int,
    brand_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get all queries for a specific user and brand."""
    queries = crud.get_queries(db, user_id=user_id, brand_id=brand_id, limit=1000)
    return queries


@router.post("/users/{user_id}/brands/{brand_id}/queries", response_model=schemas.Query)
def create_query_for_user(
    user_id: int,
    brand_id: int,
    query: schemas.QueryCreate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Create a query for a specific user and brand."""
    return crud.create_query(db, query=query, user_id=user_id, brand_id=brand_id)


@router.put("/users/{user_id}/brands/{brand_id}/queries/{query_id}", response_model=schemas.Query)
def update_user_query(
    user_id: int,
    brand_id: int,
    query_id: str,
    query_update: schemas.QueryUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Update a query for a specific user and brand."""
    updated_query = crud.update_query(
        db, query_id=query_id, query_update=query_update,
        user_id=user_id, brand_id=brand_id
    )
    if not updated_query:
        raise HTTPException(status_code=404, detail="Query not found")
    return updated_query


@router.delete("/users/{user_id}/brands/{brand_id}/queries/{query_id}")
def delete_user_query(
    user_id: int,
    brand_id: int,
    query_id: str,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Delete a query for a specific user and brand."""
    deleted = crud.delete_query(db, query_id=query_id, user_id=user_id, brand_id=brand_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Query not found")
    return {"message": "Query deleted successfully"}


# === Descriptor Management ===

@router.get("/users/{user_id}/brands/{brand_id}/descriptors", response_model=List[schemas.TargetDescriptor])
def get_user_brand_descriptors(
    user_id: int,
    brand_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get all descriptors for a specific user and brand."""
    descriptors = crud.get_target_descriptors(db, user_id=user_id, brand_id=brand_id, limit=1000)
    return descriptors


@router.post("/users/{user_id}/brands/{brand_id}/descriptors", response_model=schemas.TargetDescriptor)
def create_descriptor_for_user(
    user_id: int,
    brand_id: int,
    descriptor: schemas.TargetDescriptorCreate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Create a descriptor for a specific user and brand."""
    return crud.create_target_descriptor(db, descriptor=descriptor, user_id=user_id, brand_id=brand_id)


@router.put("/users/{user_id}/brands/{brand_id}/descriptors/{descriptor_id}", response_model=schemas.TargetDescriptor)
def update_user_descriptor(
    user_id: int,
    brand_id: int,
    descriptor_id: int,
    descriptor_update: schemas.TargetDescriptorUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Update a descriptor for a specific user and brand."""
    updated = crud.update_target_descriptor(
        db, descriptor_id=descriptor_id, descriptor_update=descriptor_update,
        user_id=user_id, brand_id=brand_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Descriptor not found")
    return updated


@router.delete("/users/{user_id}/brands/{brand_id}/descriptors/{descriptor_id}")
def delete_user_descriptor(
    user_id: int,
    brand_id: int,
    descriptor_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Delete a descriptor for a specific user and brand."""
    deleted = crud.delete_target_descriptor(db, descriptor_id=descriptor_id, user_id=user_id, brand_id=brand_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Descriptor not found")
    return {"message": "Descriptor deleted successfully"}


# === Competitor Management ===

@router.get("/users/{user_id}/brands/{brand_id}/competitors", response_model=List[schemas.Competitor])
def get_user_brand_competitors(
    user_id: int,
    brand_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Get all competitors for a specific user and brand."""
    competitors = crud.get_competitors(db, user_id=user_id, brand_id=brand_id, limit=1000)
    return competitors


@router.post("/users/{user_id}/brands/{brand_id}/competitors", response_model=schemas.Competitor)
def create_competitor_for_user(
    user_id: int,
    brand_id: int,
    competitor: schemas.CompetitorCreate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Create a competitor for a specific user and brand."""
    return crud.create_competitor(db, competitor=competitor, user_id=user_id, brand_id=brand_id)


@router.put("/users/{user_id}/brands/{brand_id}/competitors/{competitor_id}", response_model=schemas.Competitor)
def update_user_competitor(
    user_id: int,
    brand_id: int,
    competitor_id: int,
    competitor_update: schemas.CompetitorUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Update a competitor for a specific user and brand."""
    updated = crud.update_competitor(
        db, competitor_id=competitor_id, competitor_update=competitor_update,
        user_id=user_id, brand_id=brand_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Competitor not found")
    return updated


@router.delete("/users/{user_id}/brands/{brand_id}/competitors/{competitor_id}")
def delete_user_competitor(
    user_id: int,
    brand_id: int,
    competitor_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Delete a competitor for a specific user and brand."""
    deleted = crud.delete_competitor(db, competitor_id=competitor_id, user_id=user_id, brand_id=brand_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Competitor not found")
    return {"message": "Competitor deleted successfully"}


# === Scheduler Monitoring ===

@router.get("/scheduler/dashboard")
def get_scheduler_dashboard(
    days: int = 30,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
) -> Dict[str, Any]:
    """
    Get comprehensive scheduler dashboard data.
    Shows recent activity, active schedules, and health status.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Get recent task history
    recent_history = db.query(models.ScheduledTaskHistory).filter(
        models.ScheduledTaskHistory.started_at >= cutoff_date
    ).order_by(models.ScheduledTaskHistory.started_at.desc()).all()

    # Get all active scheduled tasks
    active_schedules = db.query(models.ScheduledTask).filter(
        models.ScheduledTask.is_enabled == True
    ).all()

    # Get all scheduled tasks (including disabled)
    all_schedules = db.query(models.ScheduledTask).all()

    # Build history data with user/brand info
    history_data = []
    for history in recent_history:
        user = db.query(models.User).filter_by(id=history.user_id).first()
        brand = db.query(models.BrandInfo).filter_by(id=history.brand_id).first()
        schedule = db.query(models.ScheduledTask).filter_by(id=history.scheduled_task_id).first()

        duration = None
        if history.completed_at and history.started_at:
            duration = (history.completed_at - history.started_at).total_seconds()

        history_data.append({
            "id": history.id,
            "scheduled_task_id": history.scheduled_task_id,
            "status": history.status,
            "user_email": user.email if user else None,
            "user_name": user.full_name if user else None,
            "brand_name": brand.brand_name if brand else None,
            "brand_id": history.brand_id,
            "started_at": history.started_at.isoformat() if history.started_at else None,
            "completed_at": history.completed_at.isoformat() if history.completed_at else None,
            "duration_seconds": duration,
            "collection_responses": history.collection_responses,
            "analysis_responses": history.analysis_responses,
            "error_message": history.error_message,
            "schedule_type": schedule.schedule_type if schedule else None
        })

    # Build active schedules data
    schedules_data = []
    for schedule in all_schedules:
        user = db.query(models.User).filter_by(id=schedule.user_id).first()
        brand = db.query(models.BrandInfo).filter_by(id=schedule.brand_id).first()

        # Get latest history for this schedule
        latest_run = db.query(models.ScheduledTaskHistory).filter(
            models.ScheduledTaskHistory.scheduled_task_id == schedule.id
        ).order_by(models.ScheduledTaskHistory.started_at.desc()).first()

        # Check if overdue
        is_overdue = False
        if schedule.is_enabled and schedule.next_run_at:
            is_overdue = schedule.next_run_at < datetime.utcnow()

        schedules_data.append({
            "id": schedule.id,
            "user_email": user.email if user else None,
            "user_name": user.full_name if user else None,
            "user_id": schedule.user_id,
            "brand_name": brand.brand_name if brand else None,
            "brand_id": schedule.brand_id,
            "schedule_type": schedule.schedule_type,
            "is_enabled": schedule.is_enabled,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            "last_status": latest_run.status if latest_run else None,
            "send_email_notification": schedule.send_email_notification,
            "notification_email": schedule.notification_email,
            "timezone": schedule.timezone,
            "is_overdue": is_overdue
        })

    # Calculate summary statistics
    total_runs = len(recent_history)
    success_count = len([h for h in recent_history if h.status == 'success'])
    failed_count = len([h for h in recent_history if h.status == 'failed'])
    partial_count = len([h for h in recent_history if h.status == 'partial'])
    running_count = len([h for h in recent_history if h.status == 'running'])

    # Identify issues
    failed_tasks = [h for h in history_data if h['status'] in ['failed', 'partial']]
    overdue_tasks = [s for s in schedules_data if s['is_overdue']]
    stalled_tasks = [h for h in history_data if h['status'] == 'running' and h['started_at']]

    # Check for stalled (running for > 2 hours)
    stalled_threshold = datetime.utcnow() - timedelta(hours=2)
    actual_stalled = []
    for task in stalled_tasks:
        if task['started_at']:
            started = datetime.fromisoformat(task['started_at'])
            if started < stalled_threshold:
                actual_stalled.append(task)

    return {
        "summary": {
            "total_runs_last_{}_days".format(days): total_runs,
            "success": success_count,
            "failed": failed_count,
            "partial": partial_count,
            "running": running_count,
            "success_rate": round((success_count / total_runs * 100) if total_runs > 0 else 0, 1),
            "total_active_schedules": len([s for s in schedules_data if s['is_enabled']]),
            "total_schedules": len(schedules_data)
        },
        "recent_activity": history_data,
        "active_schedules": [s for s in schedules_data if s['is_enabled']],
        "all_schedules": schedules_data,
        "health": {
            "failed_tasks": failed_tasks,
            "overdue_tasks": overdue_tasks,
            "stalled_tasks": actual_stalled,
            "has_issues": len(failed_tasks) > 0 or len(overdue_tasks) > 0 or len(actual_stalled) > 0
        }
    }


@router.get("/scheduler/history")
def get_scheduler_history(
    days: int = 7,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
) -> List[Dict[str, Any]]:
    """Get detailed scheduler history with filtering options."""
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    query = db.query(models.ScheduledTaskHistory).filter(
        models.ScheduledTaskHistory.started_at >= cutoff_date
    )

    if status:
        query = query.filter(models.ScheduledTaskHistory.status == status)

    if user_id:
        query = query.filter(models.ScheduledTaskHistory.user_id == user_id)

    history = query.order_by(models.ScheduledTaskHistory.started_at.desc()).all()

    result = []
    for h in history:
        user = db.query(models.User).filter_by(id=h.user_id).first()
        brand = db.query(models.BrandInfo).filter_by(id=h.brand_id).first()

        result.append({
            "id": h.id,
            "scheduled_task_id": h.scheduled_task_id,
            "status": h.status,
            "user_email": user.email if user else None,
            "brand_name": brand.brand_name if brand else None,
            "started_at": h.started_at.isoformat() if h.started_at else None,
            "completed_at": h.completed_at.isoformat() if h.completed_at else None,
            "collection_responses": h.collection_responses,
            "analysis_responses": h.analysis_responses,
            "error_message": h.error_message
        })

    return result


@router.post("/scheduler/clear-overdue/{schedule_id}")
def clear_overdue_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
) -> Dict[str, Any]:
    """
    Clear an overdue schedule by updating its next_run_at to the next scheduled time.
    This marks the schedule as having been manually handled.
    """
    from dateutil.relativedelta import relativedelta

    schedule = db.query(models.ScheduledTask).filter(
        models.ScheduledTask.id == schedule_id
    ).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if not schedule.next_run_at:
        raise HTTPException(status_code=400, detail="Schedule has no next_run_at set")

    # Check if actually overdue
    if schedule.next_run_at >= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Schedule is not overdue")

    # Calculate the next run time based on schedule_type
    now = datetime.utcnow()
    old_next_run = schedule.next_run_at

    if schedule.schedule_type == "first_day":
        # First day of each month - move to first day of next month
        if now.day == 1:
            # If today is the 1st, schedule for next month's 1st
            new_next_run = (now + relativedelta(months=1)).replace(
                day=1, hour=old_next_run.hour, minute=old_next_run.minute, second=0, microsecond=0
            )
        else:
            # Schedule for the 1st of the following month
            new_next_run = (now + relativedelta(months=1)).replace(
                day=1, hour=old_next_run.hour, minute=old_next_run.minute, second=0, microsecond=0
            )
    elif schedule.schedule_type == "middle":
        # Middle of each month (15th)
        if now.day <= 15:
            # Schedule for the 15th of this month
            new_next_run = now.replace(
                day=15, hour=old_next_run.hour, minute=old_next_run.minute, second=0, microsecond=0
            )
        else:
            # Schedule for the 15th of next month
            new_next_run = (now + relativedelta(months=1)).replace(
                day=15, hour=old_next_run.hour, minute=old_next_run.minute, second=0, microsecond=0
            )
    elif schedule.schedule_type == "weekly":
        # Weekly - schedule for next week same time
        new_next_run = now + timedelta(days=7)
        new_next_run = new_next_run.replace(
            hour=old_next_run.hour, minute=old_next_run.minute, second=0, microsecond=0
        )
    elif schedule.schedule_type == "biweekly":
        # Biweekly - schedule for 2 weeks from now
        new_next_run = now + timedelta(days=14)
        new_next_run = new_next_run.replace(
            hour=old_next_run.hour, minute=old_next_run.minute, second=0, microsecond=0
        )
    else:
        # Default: monthly from now
        new_next_run = now + relativedelta(months=1)
        new_next_run = new_next_run.replace(
            hour=old_next_run.hour, minute=old_next_run.minute, second=0, microsecond=0
        )

    # Update the schedule
    schedule.next_run_at = new_next_run
    schedule.last_run_at = now  # Mark as if it ran now
    db.commit()

    # Get brand name for response
    brand = db.query(models.BrandInfo).filter_by(id=schedule.brand_id).first()

    return {
        "message": f"Cleared overdue schedule for {brand.brand_name if brand else 'Unknown'}",
        "schedule_id": schedule_id,
        "old_next_run": old_next_run.isoformat(),
        "new_next_run": new_next_run.isoformat()
    }


@router.post("/run-collection-for-user")
def admin_run_collection_for_user(
    user_id: int,
    brand_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
) -> Dict[str, Any]:
    """
    Admin endpoint to manually trigger collection & analysis for any user/brand.
    Uses the shared data pipeline service.
    """
    # Use shared data pipeline service
    from app.services.data_pipeline import run_collection_and_analysis

    result = run_collection_and_analysis(
        user_id=user_id,
        brand_id=brand_id,
        triggered_by="admin"
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "message": result["message"],
        "task_id": result["task_id"]
    }


@router.post("/login-as-user/{user_id}")
def admin_login_as_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
) -> Dict[str, Any]:
    """
    Admin endpoint to generate a JWT token for any user.
    This allows admins to "log in as" another user to troubleshoot issues.

    Returns a token that can be used to authenticate as the target user.
    """
    from ..auth import create_access_token

    # Verify target user exists
    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate JWT token for the target user
    access_token = create_access_token(data={"sub": target_user.id})

    return {
        "access_token": access_token,
        # OAuth2 token_type value, not a credential
        "token_type": "bearer",  # nosec B105
        "user_email": target_user.email,
        "user_name": target_user.full_name
    }


@router.get("/active-users")
def get_active_users(
    minutes: int = 15,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
) -> Dict[str, Any]:
    """
    Get users who have been active in the last N minutes.
    Activity is determined by running tasks or recent data operations.

    Returns count and list of active users (excluding the current admin).
    """
    from datetime import datetime, timedelta

    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)

    # Find users with recent task activity
    active_user_ids = set()

    # Check for running or recently completed tasks
    recent_tasks = db.query(models.TaskStatus).filter(
        models.TaskStatus.started_at >= cutoff_time
    ).all()

    for task in recent_tasks:
        active_user_ids.add(task.user_id)

    # Check for recent collection batches
    recent_batches = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.started_at >= cutoff_time
    ).all()

    for batch in recent_batches:
        active_user_ids.add(batch.user_id)

    # Exclude current admin from the list
    active_user_ids.discard(current_admin.id)

    # Get user details
    active_users = []
    for user_id in active_user_ids:
        user = db.query(models.User).filter_by(id=user_id).first()
        if user:
            # Get most recent activity
            latest_task = db.query(models.TaskStatus).filter(
                models.TaskStatus.user_id == user_id
            ).order_by(models.TaskStatus.started_at.desc()).first()

            latest_batch = db.query(models.CollectionBatch).filter(
                models.CollectionBatch.user_id == user_id
            ).order_by(models.CollectionBatch.started_at.desc()).first()

            last_activity = None
            activity_type = None

            if latest_task and latest_batch:
                if latest_task.started_at > latest_batch.started_at:
                    last_activity = latest_task.started_at
                    activity_type = f"{latest_task.task_type} ({latest_task.status})"
                else:
                    last_activity = latest_batch.started_at
                    activity_type = "collection"
            elif latest_task:
                last_activity = latest_task.started_at
                activity_type = f"{latest_task.task_type} ({latest_task.status})"
            elif latest_batch:
                last_activity = latest_batch.started_at
                activity_type = "collection"

            active_users.append({
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "last_activity": last_activity.isoformat() if last_activity else None,
                "activity_type": activity_type
            })

    # Sort by most recent activity
    active_users.sort(key=lambda x: x["last_activity"] or "", reverse=True)

    return {
        "count": len(active_users),
        "active_users": active_users,
        "minutes_threshold": minutes,
        "current_admin_id": current_admin.id
    }


# === Batch Management ===

@router.put("/batches/{batch_id}/date")
def update_batch_date(
    batch_id: int,
    new_date: str,  # ISO format: "2025-11-01T23:25:00"
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Update the started_at date for a collection batch.

    Args:
        batch_id: The batch ID to update
        new_date: New date in ISO format (e.g., "2025-11-01T23:25:00")
    """
    batch = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.id == batch_id
    ).first()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    try:
        new_datetime = datetime.fromisoformat(new_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format: YYYY-MM-DDTHH:MM:SS")

    old_date = batch.started_at

    # Update batch
    batch.started_at = new_datetime

    # Also shift completed_at if it exists
    if batch.completed_at and old_date:
        delta = new_datetime - old_date
        batch.completed_at = batch.completed_at + delta

    # Update BatchAnalytics collection_date if exists
    batch_analytics = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.batch_id == batch_id
    ).first()

    if batch_analytics:
        batch_analytics.collection_date = new_datetime

    db.commit()

    return {
        "message": "Batch date updated successfully",
        "batch_id": batch_id,
        "old_date": old_date.isoformat() if old_date else None,
        "new_date": new_datetime.isoformat(),
        "batch_name": batch.batch_name
    }


@router.get("/batches")
def list_all_batches(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """List all collection batches across all users with response counts and brand info."""
    batches = db.query(models.CollectionBatch).order_by(
        models.CollectionBatch.started_at.desc()
    ).limit(limit).all()

    result = []
    for b in batches:
        # Get response count for this batch
        response_count = db.query(func.count(models.Response.id)).filter(
            models.Response.batch_id == b.id
        ).scalar() or 0

        # Get brand info
        brand = db.query(models.BrandInfo).filter(
            models.BrandInfo.id == b.brand_id
        ).first()

        # Get user info
        user = db.query(models.User).filter(
            models.User.id == b.user_id
        ).first()

        result.append({
            "id": b.id,
            "batch_name": b.batch_name,
            "user_id": b.user_id,
            "user_email": user.email if user else None,
            "brand_id": b.brand_id,
            "brand_name": brand.brand_name if brand else None,
            "started_at": b.started_at.isoformat() if b.started_at else None,
            "completed_at": b.completed_at.isoformat() if b.completed_at else None,
            "status": b.status,
            "response_count": response_count
        })

    return result


# === Debug Endpoints ===

@router.get("/debug/batch-analytics")
def debug_batch_analytics(
    brand_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Debug endpoint to view BatchAnalytics data and trend calculations.
    Shows the two most recent batches and the calculated change values.
    """
    import json

    # Get batch analytics for the admin's user account or filter by brand
    batch_analytics_query = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.user_id == current_admin.id
    )
    if brand_id:
        batch_analytics_query = batch_analytics_query.filter(
            models.BatchAnalytics.brand_id == brand_id
        )

    recent_batches = batch_analytics_query.order_by(
        models.BatchAnalytics.collection_date.desc()
    ).limit(5).all()

    if len(recent_batches) < 2:
        return {
            "error": "Need at least 2 batches to compare",
            "batches_found": len(recent_batches),
            "batches": [
                {
                    "batch_id": ba.batch_id,
                    "collection_date": ba.collection_date.isoformat() if ba.collection_date else None,
                    "mention_rate": ba.mention_rate,
                    "mention_count": ba.mention_count,
                    "total_responses": ba.total_responses
                }
                for ba in recent_batches
            ]
        }

    recent = recent_batches[0]
    previous = recent_batches[1]

    # Calculate the same way as analytics_cache.py
    mention_rate_change = (recent.mention_rate or 0) - (previous.mention_rate or 0)

    return {
        "most_recent_batch": {
            "batch_id": recent.batch_id,
            "collection_date": recent.collection_date.isoformat() if recent.collection_date else None,
            "mention_rate": recent.mention_rate,
            "mention_count": recent.mention_count,
            "total_responses": recent.total_responses,
            "brand_id": recent.brand_id,
            "user_id": recent.user_id
        },
        "previous_batch": {
            "batch_id": previous.batch_id,
            "collection_date": previous.collection_date.isoformat() if previous.collection_date else None,
            "mention_rate": previous.mention_rate,
            "mention_count": previous.mention_count,
            "total_responses": previous.total_responses,
            "brand_id": previous.brand_id,
            "user_id": previous.user_id
        },
        "calculated_change": {
            "mention_rate_change": mention_rate_change,
            "formula": f"recent({recent.mention_rate}) - previous({previous.mention_rate}) = {mention_rate_change}"
        },
        "all_batches": [
            {
                "batch_id": ba.batch_id,
                "collection_date": ba.collection_date.isoformat() if ba.collection_date else None,
                "mention_rate": ba.mention_rate,
                "brand_id": ba.brand_id
            }
            for ba in recent_batches
        ]
    }


@router.post("/debug/recompute-batch-analytics/{batch_id}")
def recompute_batch_analytics(
    batch_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Recompute BatchAnalytics for a specific batch.
    Use this when batch analytics data appears to be incorrect.
    """
    from ..services.batch_analytics import compute_batch_analytics

    # Get the batch to find user_id and brand_id
    batch = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.id == batch_id
    ).first()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Recompute analytics
    result = compute_batch_analytics(db, batch_id, batch.user_id, batch.brand_id)

    if result:
        return {
            "message": "Batch analytics recomputed successfully",
            "batch_id": batch_id,
            "mention_rate": result.mention_rate,
            "mention_count": result.mention_count,
            "total_responses": result.total_responses
        }
    else:
        return {
            "message": "No responses found for batch",
            "batch_id": batch_id
        }


# === Cache Management ===

@router.post("/cache/clear")
def clear_cache(
    user_id: Optional[int] = None,
    brand_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Clear Redis cache for analytics data.

    Args:
        user_id: Optional - clear cache for specific user only
        brand_id: Optional - clear cache for specific brand only (requires user_id)

    If no parameters provided, clears ALL analytics cache.
    """
    from ..services.redis_cache import get_redis_cache

    cache = get_redis_cache()

    if not cache.is_available:
        return {
            "message": "Redis cache is not available",
            "cleared": 0
        }

    if user_id and brand_id:
        # Clear cache for specific user/brand
        count = cache.invalidate_user(user_id, brand_id)
        return {
            "message": f"Cache cleared for user {user_id}, brand {brand_id}",
            "cleared": count
        }
    elif user_id:
        # Clear cache for specific user (all brands)
        count = cache.invalidate_user(user_id)
        return {
            "message": f"Cache cleared for user {user_id}",
            "cleared": count
        }
    else:
        # Clear ALL analytics cache
        count = cache.invalidate_pattern("*")
        return {
            "message": "All analytics cache cleared",
            "cleared": count
        }


# === Data Deduplication ===

@router.get("/debug/december-duplicates")
def investigate_december_duplicates(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Investigate duplicate responses in December 2025 data.
    Shows batch info and identifies duplicate prompt/platform combinations.
    """
    from sqlalchemy import extract

    # Get all December 2025 batches
    december_batches = db.query(models.CollectionBatch).filter(
        extract('month', models.CollectionBatch.started_at) == 12,
        extract('year', models.CollectionBatch.started_at) == 2025
    ).order_by(models.CollectionBatch.started_at).all()

    result = {
        "december_batches": [],
        "total_december_responses": 0,
        "duplicates": [],
        "summary": {}
    }

    for batch in december_batches:
        # Count responses for this batch
        response_count = db.query(func.count(models.Response.id)).filter(
            models.Response.batch_id == batch.id
        ).scalar()

        result["total_december_responses"] += response_count

        # Get unique prompts and platforms
        unique_prompts = db.query(func.count(func.distinct(models.Response.prompt_id))).filter(
            models.Response.batch_id == batch.id
        ).scalar()

        platforms = db.query(func.distinct(models.Response.platform)).filter(
            models.Response.batch_id == batch.id
        ).all()
        platform_list = [p[0] for p in platforms]

        result["december_batches"].append({
            "batch_id": batch.id,
            "batch_name": batch.batch_name,
            "user_id": batch.user_id,
            "brand_id": batch.brand_id,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "status": batch.status,
            "response_count": response_count,
            "unique_prompts": unique_prompts,
            "platforms": platform_list,
            "expected_count": unique_prompts * len(platform_list)
        })

    # Find duplicate prompt/platform combinations within December batches
    december_batch_ids = [b.id for b in december_batches]

    if december_batch_ids:
        duplicate_check = db.query(
            models.Response.batch_id,
            models.Response.prompt_id,
            models.Response.platform,
            func.count(models.Response.id).label('count')
        ).filter(
            models.Response.batch_id.in_(december_batch_ids)
        ).group_by(
            models.Response.batch_id,
            models.Response.prompt_id,
            models.Response.platform
        ).having(
            func.count(models.Response.id) > 1
        ).all()

        for dup in duplicate_check:
            prompt = db.query(models.Prompt).filter(models.Prompt.id == dup.prompt_id).first()
            result["duplicates"].append({
                "batch_id": dup.batch_id,
                "prompt_id": dup.prompt_id,
                "prompt_text": prompt.prompt_text[:100] if prompt else "Unknown",
                "platform": dup.platform,
                "duplicate_count": dup.count
            })

    result["summary"] = {
        "total_batches": len(december_batches),
        "total_responses": result["total_december_responses"],
        "expected_responses": sum(b["expected_count"] for b in result["december_batches"]),
        "duplicate_groups": len(result["duplicates"]),
        "excess_responses": result["total_december_responses"] - sum(b["expected_count"] for b in result["december_batches"])
    }

    return result


@router.post("/fix/remove-duplicate-responses")
def remove_duplicate_responses(
    batch_id: Optional[int] = None,
    dry_run: bool = True,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Remove duplicate responses (same prompt_id + platform within same batch).
    Keeps the FIRST response (lowest ID) and removes duplicates.

    Args:
        batch_id: Specific batch to clean (or None for all December 2025 batches)
        dry_run: If True, only report what would be deleted (default: True)

    Returns:
        Count of responses that would be/were deleted
    """
    from sqlalchemy import extract

    # Determine which batches to clean
    if batch_id:
        batch_ids = [batch_id]
    else:
        # Get all December 2025 batches
        december_batches = db.query(models.CollectionBatch).filter(
            extract('month', models.CollectionBatch.started_at) == 12,
            extract('year', models.CollectionBatch.started_at) == 2025
        ).all()
        batch_ids = [b.id for b in december_batches]

    if not batch_ids:
        return {"message": "No batches to process", "deleted": 0}

    # Find all duplicate groups
    duplicate_groups = db.query(
        models.Response.batch_id,
        models.Response.prompt_id,
        models.Response.platform,
        func.count(models.Response.id).label('count'),
        func.min(models.Response.id).label('keep_id')
    ).filter(
        models.Response.batch_id.in_(batch_ids)
    ).group_by(
        models.Response.batch_id,
        models.Response.prompt_id,
        models.Response.platform
    ).having(
        func.count(models.Response.id) > 1
    ).all()

    # Collect IDs to delete
    ids_to_delete = []
    for group in duplicate_groups:
        # Get all response IDs for this prompt/platform combination
        response_ids = db.query(models.Response.id).filter(
            models.Response.batch_id == group.batch_id,
            models.Response.prompt_id == group.prompt_id,
            models.Response.platform == group.platform
        ).order_by(models.Response.id).all()

        # Keep the first one (lowest ID), mark rest for deletion
        for rid in response_ids[1:]:  # Skip the first (keep it)
            ids_to_delete.append(rid[0])

    result = {
        "dry_run": dry_run,
        "batches_processed": batch_ids,
        "duplicate_groups_found": len(duplicate_groups),
        "responses_to_delete": len(ids_to_delete),
        "sample_deletions": ids_to_delete[:20]  # Show first 20 IDs
    }

    if not dry_run and ids_to_delete:
        # Actually delete the duplicates
        deleted_count = db.query(models.Response).filter(
            models.Response.id.in_(ids_to_delete)
        ).delete(synchronize_session=False)

        db.commit()
        result["deleted"] = deleted_count
        result["message"] = f"Successfully deleted {deleted_count} duplicate responses"

        # Clear cache after deletion
        from ..services.redis_cache import get_redis_cache
        cache = get_redis_cache()
        if cache.is_available:
            cache.invalidate_pattern("*")
            result["cache_cleared"] = True
    else:
        result["message"] = "Dry run - no changes made. Set dry_run=false to actually delete duplicates."

    return result


@router.delete("/batches/{batch_id}")
def delete_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Delete an entire collection batch and all its associated responses.

    This is a destructive operation - use with caution!
    """
    # Find the batch
    batch = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.id == batch_id
    ).first()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch_name = batch.batch_name

    # Count responses before deletion
    response_count = db.query(func.count(models.Response.id)).filter(
        models.Response.batch_id == batch_id
    ).scalar()

    # Delete all responses for this batch
    db.query(models.Response).filter(
        models.Response.batch_id == batch_id
    ).delete(synchronize_session=False)

    # Delete BatchAnalytics if exists
    db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.batch_id == batch_id
    ).delete(synchronize_session=False)

    # Delete the batch itself
    db.delete(batch)
    db.commit()

    # Clear cache
    from ..services.redis_cache import get_redis_cache
    cache = get_redis_cache()
    if cache.is_available:
        cache.invalidate_pattern("*")

    return {
        "message": f"Batch '{batch_name}' deleted successfully",
        "batch_id": batch_id,
        "responses_deleted": response_count,
        "cache_cleared": True
    }


# === Site Configuration ===

@router.get("/site-config", response_model=schemas.SiteConfig)
def get_site_config(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Get current site configuration settings.

    Returns site_url, admin_email, and site_name settings.
    Values may be None if not configured (will fall back to environment variables).
    """
    config = crud.get_site_config(db)
    return schemas.SiteConfig(**config)


@router.put("/site-config", response_model=schemas.SiteConfig)
def update_site_config(
    config_update: schemas.SiteConfigUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """
    Update site configuration settings.

    Configurable values:
    - site_url: Base URL for email links (e.g., https://mycompany.com/tales)
    - admin_email: Contact email shown in notification emails
    - site_name: Application name used in email subjects and headers

    Only provided values will be updated. To clear a value, set it to empty string.
    """
    updated_config = crud.update_site_config(db, config_update)
    return schemas.SiteConfig(**updated_config)
