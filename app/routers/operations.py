"""
Operations API Endpoints
Provides endpoints for triggering background tasks and operations including:
- Data collection
- Analysis tasks
- Report generation
- Task management (status, cancellation)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Literal, Optional
import datetime
import os
import subprocess
import threading

# Use timezone-aware datetime to ensure proper timezone handling in frontend
def utcnow():
    """Returns current UTC time with timezone info (Python 3.11+ compatible)"""
    return datetime.datetime.now(datetime.UTC)
import signal

from .. import models, schemas, crud
from ..auth import get_current_user
from ..database import SessionLocal, get_db
from ..utils.brand_access import get_active_brand_id, get_data_owner_user_id

router = APIRouter(
    prefix="/tasks",
    tags=["Operations"]
)


# --- Collection and Analysis Triggers ---
# Note: Celery has been removed. All tasks now use APScheduler + threading model.
@router.post("/run-collection/", status_code=202)
async def run_collection(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Trigger response collection followed by automatic analysis for the active brand.
    Uses the shared data pipeline service.
    """
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand found. Please select a brand first.")

    # Use shared data pipeline service
    from app.services.data_pipeline import run_collection_and_analysis

    result = run_collection_and_analysis(
        user_id=current_user.id,
        brand_id=brand_id,
        triggered_by="manual"
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "message": result["message"],
        "status": "running",
        "task_id": result["task_id"],
        "note": "Collection will run first, then analysis will automatically start. Check the task status banner for progress."
    }

@router.post("/run-analysis/", status_code=202)
async def run_analysis(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Analyze responses from the most recent collection date for the active brand."""
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand found. Please select a brand first.")

    # Find the most recent collection date for this brand
    most_recent_response = db.query(models.Response).filter(
        models.Response.user_id == current_user.id,
        models.Response.brand_id == brand_id
    ).order_by(models.Response.timestamp.desc()).first()

    if not most_recent_response:
        raise HTTPException(status_code=404, detail="No responses found for active brand.")

    # Get the date of the most recent collection (just the date part)
    latest_date = most_recent_response.timestamp.date()

    # Find all responses from that date
    latest_date_start = datetime.datetime.combine(latest_date, datetime.time.min)
    latest_date_end = latest_date_start + datetime.timedelta(days=1)

    responses_to_analyze = db.query(models.Response).filter(
        models.Response.user_id == current_user.id,
        models.Response.brand_id == brand_id,
        models.Response.timestamp >= latest_date_start,
        models.Response.timestamp < latest_date_end
    ).all()

    if not responses_to_analyze:
        raise HTTPException(status_code=404, detail="No responses found for the most recent collection date.")

    # Reset analysis fields for these responses
    for response in responses_to_analyze:
        response.analyzed_at = None
        response.brand_mentioned = None
        response.brand_position = None
        response.sentiment = None
        response.descriptors = None
        response.competitors = None
        response.sources = None

    db.commit()

    # Create task status for analysis
    task_status = models.TaskStatus(
        user_id=current_user.id,
        brand_id=brand_id,
        task_type="analysis",
        status="running",
        total_items=len(responses_to_analyze),
        processed_items=0,
        message=f"Analyzing {len(responses_to_analyze)} responses from {latest_date.strftime('%Y-%m-%d')}...",
        started_at=utcnow()
    )
    db.add(task_status)
    db.commit()
    db.refresh(task_status)

    # Get the project root directory (parent of app directory)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    analysis_script = os.path.join(project_root, "scripts", "admin", "analyze_responses.py")

    try:

        # Run analysis in the background with a task-id so progress is trackable
        analysis_cmd = [
            "python3", analysis_script,
            "--all",
            "--user-id", str(current_user.id),
            "--brand-id", str(brand_id),
            "--task-id", str(task_status.id)
        ]

        # Create a background task to monitor the subprocess
        def run_analysis_task():
            """Run analysis, updating task status on completion."""
            db_task = SessionLocal()
            try:
                # Run analysis script using Popen so we can track the PID
                # Add PYTHONPATH to subprocess environment so script can import from app module
                env = os.environ.copy()
                env['PYTHONPATH'] = project_root
                analysis_process = subprocess.Popen(
                    analysis_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=project_root,
                    env=env
                )

                # Store the process ID
                task = db_task.query(models.TaskStatus).filter(
                    models.TaskStatus.id == task_status.id
                ).first()
                if task:
                    task.process_id = analysis_process.pid
                    db_task.commit()

                # Wait for process to complete with timeout
                try:
                    stdout, stderr = analysis_process.communicate(timeout=3600)  # 1 hour timeout
                except subprocess.TimeoutExpired:
                    analysis_process.kill()
                    stdout, stderr = analysis_process.communicate()
                    raise

                if analysis_process.returncode != 0:
                    # Analysis failed
                    task = db_task.query(models.TaskStatus).filter(
                        models.TaskStatus.id == task_status.id
                    ).first()
                    if task:
                        task.status = "failed"
                        task.error_message = f"Analysis script failed: {stderr[-500:] if stderr else 'Unknown error'}"
                        db_task.commit()
                    return

                # Both succeeded
                task = db_task.query(models.TaskStatus).filter(
                    models.TaskStatus.id == task_status.id
                ).first()
                if task:
                    task.status = "completed"
                    task.message = "Analysis completed successfully"
                    db_task.commit()

            except subprocess.TimeoutExpired as e:
                task = db_task.query(models.TaskStatus).filter(
                    models.TaskStatus.id == task_status.id
                ).first()
                if task:
                    task.status = "failed"
                    task.error_message = f"Task timed out: {str(e)}"
                    db_task.commit()
            except Exception as e:
                task = db_task.query(models.TaskStatus).filter(
                    models.TaskStatus.id == task_status.id
                ).first()
                if task:
                    task.status = "failed"
                    task.error_message = f"Unexpected error: {str(e)}"
                    db_task.commit()
            finally:
                db_task.close()

        # Start the background thread
        thread = threading.Thread(target=run_analysis_task, daemon=True)
        thread.start()

        return {
            "message": f"Analysis started for {len(responses_to_analyze)} responses from {latest_date.strftime('%Y-%m-%d')}.",
            "status": "running",
            "task_id": task_status.id,
            "count": len(responses_to_analyze),
            "note": "Analyzing the latest data. This will update all analytics pages."
        }
    except Exception as e:
        task_status.status = "failed"
        task_status.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start analysis: {str(e)}")

@router.post("/rerun-analysis/", status_code=202)
async def rerun_analysis(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Reset and re-run analysis on responses for the active brand, optionally filtered by date range."""
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand found. Please select a brand first.")

    # Build query for responses
    query = db.query(models.Response).filter(
        models.Response.user_id == current_user.id,
        models.Response.brand_id == brand_id
    )

    # Apply date filters if provided
    date_description = "all"
    if start_date:
        try:
            start_dt = datetime.datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(models.Response.timestamp >= start_dt)
            date_description = f"from {start_date[:10]}"
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO format (YYYY-MM-DD).")

    if end_date:
        try:
            end_dt = datetime.datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            # Add one day to include the entire end date
            end_dt = end_dt + datetime.timedelta(days=1)
            query = query.filter(models.Response.timestamp < end_dt)
            if start_date:
                date_description = f"from {start_date[:10]} to {end_date[:10]}"
            else:
                date_description = f"through {end_date[:10]}"
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use ISO format (YYYY-MM-DD).")

    all_responses = query.all()

    if not all_responses:
        raise HTTPException(status_code=404, detail=f"No responses found for active brand {date_description}.")

    # Collect response IDs before resetting (so we only analyze these specific responses)
    response_ids = [response.id for response in all_responses]

    # Reset analyzed_at to NULL for filtered responses (marks them as unanalyzed)
    for response in all_responses:
        response.analyzed_at = None
        # Clear existing analysis fields so they get fresh analysis
        response.brand_mentioned = None
        response.brand_position = None
        response.sentiment = None
        response.descriptors = None
        response.competitors = None
        response.sources = None

    db.commit()

    # Create task status for re-analysis
    message = f"Re-analyzing {len(all_responses)} responses {date_description}..."
    task_status = models.TaskStatus(
        user_id=current_user.id,
        brand_id=brand_id,
        task_type="analysis",
        status="running",
        total_items=len(all_responses),
        processed_items=0,
        message=message,
        started_at=utcnow()
    )
    db.add(task_status)
    db.commit()
    db.refresh(task_status)

    # Get the project root directory (parent of app directory)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    analysis_script = os.path.join(project_root, "scripts", "admin", "analyze_responses.py")

    try:
        # Run re-analysis in the background
        # Use separate commands to capture which step fails
        # Pass specific response IDs instead of --all to only analyze date-filtered responses
        response_ids_str = ','.join(map(str, response_ids))
        analysis_cmd = [
            "python3", analysis_script,
            "--response-ids", response_ids_str,
            "--user-id", str(current_user.id),
            "--brand-id", str(brand_id),
            "--task-id", str(task_status.id)
        ]

        # Create a background task to monitor the subprocess
        def run_reanalysis_task():
            """Run re-analysis, updating task status on completion."""
            db_task = SessionLocal()
            try:
                # Run analysis script
                # Add PYTHONPATH to subprocess environment so script can import from app module
                env = os.environ.copy()
                env['PYTHONPATH'] = project_root
                analysis_process = subprocess.run(
                    analysis_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=project_root,
                    timeout=3600,  # 1 hour timeout
                    env=env
                )

                if analysis_process.returncode != 0:
                    # Analysis failed
                    task = db_task.query(models.TaskStatus).filter(
                        models.TaskStatus.id == task_status.id
                    ).first()
                    if task:
                        task.status = "failed"
                        task.error_message = f"Analysis script failed: {analysis_process.stderr[-500:]}"
                        db_task.commit()
                    return

                # Both succeeded
                task = db_task.query(models.TaskStatus).filter(
                    models.TaskStatus.id == task_status.id
                ).first()
                if task:
                    task.status = "completed"
                    task.message = "Re-analysis completed successfully"
                    db_task.commit()

            except subprocess.TimeoutExpired as e:
                task = db_task.query(models.TaskStatus).filter(
                    models.TaskStatus.id == task_status.id
                ).first()
                if task:
                    task.status = "failed"
                    task.error_message = f"Task timed out: {str(e)}"
                    db_task.commit()
            except Exception as e:
                task = db_task.query(models.TaskStatus).filter(
                    models.TaskStatus.id == task_status.id
                ).first()
                if task:
                    task.status = "failed"
                    task.error_message = f"Unexpected error: {str(e)}"
                    db_task.commit()
            finally:
                db_task.close()

        # Start the background thread
        thread = threading.Thread(target=run_reanalysis_task, daemon=True)
        thread.start()

        return {
            "message": f"Re-analysis started for {len(all_responses)} responses {date_description}.",
            "status": "running",
            "task_id": task_status.id,
            "count": len(all_responses),
            "date_range": date_description,
            "note": "Re-analyzing responses. Analytics will update when complete."
        }
    except Exception as e:
        task_status.status = "failed"
        task_status.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start re-analysis: {str(e)}")

@router.get("/status/", response_model=Optional[schemas.TaskStatus])
def get_task_status(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Get the status of the most recent task for the active brand."""
    if not brand_id:
        return None

    # Get the most recent task for this user and brand
    task = db.query(models.TaskStatus).filter(
        models.TaskStatus.user_id == current_user.id,
        models.TaskStatus.brand_id == brand_id
    ).order_by(models.TaskStatus.started_at.desc()).first()

    if not task:
        return None

    # Check if the task is still running by checking unanalyzed responses
    if task.status == "running":
        unanalyzed = crud.get_unanalyzed_responses(db, user_id=current_user.id, brand_id=brand_id, limit=1)
        if not unanalyzed and task.task_type == "analysis":
            # Analysis is complete
            # For simplicity, mark as completed if no unanalyzed responses
            task.status = "completed"
            task.completed_at = utcnow()
            task.message = "Analysis and report generation completed"
            db.commit()
            db.refresh(task)

    return task


@router.post("/cancel/{task_id}")
def cancel_task(
    task_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a running task by task ID."""
    # Get the task
    task = db.query(models.TaskStatus).filter(
        models.TaskStatus.id == task_id,
        models.TaskStatus.user_id == current_user.id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "running":
        raise HTTPException(status_code=400, detail="Task is not running")

    if not task.process_id:
        raise HTTPException(status_code=400, detail="Task has no process ID to cancel")

    try:
        # Try to terminate the process gracefully first
        os.kill(task.process_id, signal.SIGTERM)

        # Update task status
        task.status = "cancelled"
        task.message = "Task cancelled by user"
        task.completed_at = utcnow()
        db.commit()

        return {
            "message": "Task cancelled successfully",
            "task_id": task_id
        }
    except ProcessLookupError:
        # Process doesn't exist anymore, just mark as cancelled
        task.status = "cancelled"
        task.message = "Task process not found (may have already completed)"
        task.completed_at = utcnow()
        db.commit()

        return {
            "message": "Task process not found, marked as cancelled",
            "task_id": task_id
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="No permission to kill this process")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(e)}")


@router.post("/backfill-batch-analytics/", status_code=200)
async def backfill_batch_analytics(
    force: bool = False,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Backfill batch analytics for all completed batches.
    This recomputes cached analytics for trend charts.

    Args:
        force: If True, recomputes analytics even if they already exist (default: False)
    """
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand found. Please select a brand first.")

    from app.services.batch_analytics import compute_batch_analytics

    try:
        # Get all completed batches for this user/brand
        batches = db.query(models.CollectionBatch).filter(
            models.CollectionBatch.user_id == current_user.id,
            models.CollectionBatch.brand_id == brand_id,
            models.CollectionBatch.status == 'completed'
        ).all()

        processed = 0
        for batch in batches:
            if force:
                # Force recompute even if analytics exist
                result = compute_batch_analytics(db, batch.id, current_user.id, brand_id)
                if result:
                    processed += 1
            else:
                # Only compute if analytics don't exist
                existing = db.query(models.BatchAnalytics).filter(
                    models.BatchAnalytics.batch_id == batch.id
                ).first()

                if not existing:
                    result = compute_batch_analytics(db, batch.id, current_user.id, brand_id)
                    if result:
                        processed += 1

        return {
            "message": f"Successfully {'recomputed' if force else 'backfilled'} analytics for {processed} batches",
            "processed_batches": processed,
            "total_batches": len(batches),
            "forced": force
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to backfill batch analytics: {str(e)}")


@router.get("/debug/batch-analytics-status/", status_code=200)
async def debug_batch_analytics_status(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Debug endpoint to check BatchAnalytics status.
    Shows how many batches exist, how many have analytics, and sample data.
    """
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand found. Please select a brand first.")

    # Count batches
    total_batches = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.user_id == current_user.id,
        models.CollectionBatch.brand_id == brand_id
    ).count()

    completed_batches = db.query(models.CollectionBatch).filter(
        models.CollectionBatch.user_id == current_user.id,
        models.CollectionBatch.brand_id == brand_id,
        models.CollectionBatch.status == 'completed'
    ).count()

    # Count BatchAnalytics records
    total_analytics = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.user_id == current_user.id,
        models.BatchAnalytics.brand_id == brand_id
    ).count()

    # Get sample BatchAnalytics data
    sample_analytics = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.user_id == current_user.id,
        models.BatchAnalytics.brand_id == brand_id
    ).order_by(models.BatchAnalytics.collection_date.desc()).limit(5).all()

    sample_data = []
    for analytics in sample_analytics:
        sample_data.append({
            "batch_id": analytics.batch_id,
            "collection_date": analytics.collection_date.isoformat() if analytics.collection_date else None,
            "total_responses": analytics.total_responses,
            "mention_count": analytics.mention_count,
            "mention_rate": analytics.mention_rate,
            "leader_count": analytics.leader_count,
            "featured_count": analytics.featured_count,
            "listed_count": analytics.listed_count,
            "not_mentioned_count": analytics.not_mentioned_count,
            "sov_data": analytics.sov_data,
            "descriptor_data": analytics.descriptor_data
        })

    # Count responses with batch_id
    responses_with_batch = db.query(models.Response).filter(
        models.Response.user_id == current_user.id,
        models.Response.brand_id == brand_id,
        models.Response.batch_id.isnot(None)
    ).count()

    # Count total responses
    total_responses = db.query(models.Response).filter(
        models.Response.user_id == current_user.id,
        models.Response.brand_id == brand_id
    ).count()

    return {
        "batches": {
            "total": total_batches,
            "completed": completed_batches
        },
        "batch_analytics": {
            "total_records": total_analytics,
            "sample_data": sample_data
        },
        "responses": {
            "total": total_responses,
            "with_batch_id": responses_with_batch,
            "without_batch_id": total_responses - responses_with_batch
        }
    }
