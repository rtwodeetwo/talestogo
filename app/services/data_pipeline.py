"""
Shared data pipeline service for collection, analysis, and report generation.
Used by manual runs, scheduled tasks, and admin operations.

WORKFLOW:
- Collection: Query LLMs and analyze individual responses
- Period Analysis: Generate aggregated reports for monthly/quarterly/annual periods
"""
import os
import subprocess
import threading
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app import models
from app.services.email_notifications import send_email_sync
from app.services.site_config import get_site_url, get_site_name, get_admin_email


def utcnow():
    """Get current UTC time."""
    return datetime.utcnow()


async def run_period_report_only(
    user_id: int,
    brand_id: int,
    period_type: str,
    period_start: datetime,
    period_end: datetime,
    period_label: str,
    triggered_by: str = "scheduled"
) -> dict:
    """
    Generate a report for a specific time period (report-only, no analysis).

    This function generates a report aggregating already-analyzed data within
    the specified period. It does NOT run analysis or data collection.

    Args:
        user_id: ID of the user
        brand_id: ID of the brand
        period_type: 'monthly', 'quarterly', or 'annual'
        period_start: Start of the report period
        period_end: End of the report period
        period_label: Display label for the period (e.g., "Q1 2026")
        triggered_by: How this was triggered ("scheduled", "manual")

    Returns:
        dict with status information
    """
    db = SessionLocal()

    try:
        # Verify user and brand exist
        user = db.query(models.User).filter_by(id=user_id).first()
        if not user:
            return {"success": False, "error": f"User {user_id} not found"}

        brand = db.query(models.BrandInfo).filter_by(id=brand_id).first()
        if not brand:
            return {"success": False, "error": f"Brand {brand_id} not found"}

        # Get the brand owner's user_id (for shared brands)
        data_owner_user_id = brand.user_id

        # Check for analyzed responses in the period
        response_count = db.query(models.Response).filter(
            models.Response.user_id == data_owner_user_id,
            models.Response.brand_id == brand_id,
            models.Response.timestamp >= period_start,
            models.Response.timestamp <= period_end,
            models.Response.analyzed_at.isnot(None)
        ).count()

        if response_count == 0:
            return {"success": False, "error": f"No analyzed responses found for {period_label}"}

        brand_name = brand.brand_name

    finally:
        db.close()

    # Run report generation in background
    def generate_period_report():
        """Generate report for the specified period."""
        db_thread = SessionLocal()

        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            env = os.environ.copy()
            env['PYTHONPATH'] = project_root

            # Run report generation script with period parameters
            report_script = os.path.join(project_root, "scripts", "admin", "generate_report.py")
            report_cmd = [
                "python3", report_script,
                "--user-id", str(data_owner_user_id),
                "--brand-id", str(brand_id),
                "--report-type", period_type,
                "--period-start", period_start.isoformat(),
                "--period-end", period_end.isoformat(),
                "--period-label", period_label
            ]

            report_process = subprocess.Popen(
                report_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            # Wait for report generation (timeout after 60 minutes)
            report_stdout, report_stderr = report_process.communicate(timeout=3600)

            if report_process.returncode != 0:
                print(f"{period_type} report generation failed: {report_stderr}")
                return False

            print(f"{period_type} report generated successfully for {period_label}")
            return True

        except subprocess.TimeoutExpired as e:
            print(f"{period_type} report generation timed out: {e}")
            return False
        except Exception as e:
            print(f"Error generating {period_type} report: {e}")
            return False
        finally:
            db_thread.close()

    # Run in thread and wait for completion
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(generate_period_report)
        success = future.result(timeout=3700)  # Slightly longer than subprocess timeout

    return {
        "success": success,
        "message": f"{period_type.capitalize()} report generated for {period_label}" if success else f"Failed to generate {period_type} report",
        "period_type": period_type,
        "period_label": period_label,
        "triggered_by": triggered_by
    }


def run_analysis_only(
    user_id: int,
    brand_id: int,
    batch_id: int,
    triggered_by: str = "scheduled"
) -> dict:
    """
    Run ONLY response analysis (no collection, no report, no email).

    This is used by weekly scheduled runs to analyze newly collected responses.

    Args:
        user_id: ID of the user
        brand_id: ID of the brand
        batch_id: ID of the collection batch to analyze
        triggered_by: How this was triggered ("scheduled", "manual")

    Returns:
        dict with status information including responses_analyzed count
    """
    db = SessionLocal()

    try:
        # Verify user and brand exist
        user = db.query(models.User).filter_by(id=user_id).first()
        if not user:
            return {"success": False, "error": f"User {user_id} not found"}

        brand = db.query(models.BrandInfo).filter_by(id=brand_id).first()
        if not brand:
            return {"success": False, "error": f"Brand {brand_id} not found"}

        # Get the brand owner's user_id (for shared brands)
        data_owner_user_id = brand.user_id

        # Get responses from this batch that haven't been analyzed yet
        unanalyzed_count = db.query(models.Response).filter(
            models.Response.user_id == data_owner_user_id,
            models.Response.brand_id == brand_id,
            models.Response.batch_id == batch_id,
            models.Response.analyzed_at.is_(None)
        ).count()

        if unanalyzed_count == 0:
            return {
                "success": True,
                "message": "No unanalyzed responses in this batch",
                "responses_analyzed": 0,
                "triggered_by": triggered_by
            }

    finally:
        db.close()

    # Run analysis synchronously (blocking)
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        env = os.environ.copy()
        env['PYTHONPATH'] = project_root

        # Run analysis script
        script_path = os.path.join(project_root, "scripts", "admin", "analyze_responses.py")
        cmd = [
            "python3", script_path,
            "--all",
            "--user-id", str(data_owner_user_id),
            "--brand-id", str(brand_id)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for analysis (timeout after 60 minutes)
        try:
            stdout, stderr = process.communicate(timeout=3600)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return {
                "success": False,
                "error": "Analysis timed out after 60 minutes",
                "responses_analyzed": 0
            }

        if process.returncode != 0:
            error_preview = stderr[-500:] if stderr else 'Unknown error'
            return {
                "success": False,
                "error": f"Analysis failed: {error_preview}",
                "responses_analyzed": 0
            }

        # Count how many were actually analyzed
        db = SessionLocal()
        try:
            analyzed_count = db.query(models.Response).filter(
                models.Response.user_id == data_owner_user_id,
                models.Response.brand_id == brand_id,
                models.Response.batch_id == batch_id,
                models.Response.analyzed_at.isnot(None)
            ).count()

            # Recompute batch analytics after analysis
            try:
                from app.services.batch_analytics import compute_batch_analytics
                compute_batch_analytics(
                    db=db,
                    batch_id=batch_id,
                    user_id=data_owner_user_id,
                    brand_id=brand_id
                )
            except Exception as e:
                print(f"Warning: Failed to recompute batch analytics: {e}")

            return {
                "success": True,
                "message": f"Analysis completed",
                "responses_analyzed": analyzed_count,
                "triggered_by": triggered_by
            }
        finally:
            db.close()

    except Exception as e:
        return {
            "success": False,
            "error": f"Analysis error: {str(e)}",
            "responses_analyzed": 0
        }


def run_collection_only(
    user_id: int,
    brand_id: int,
    triggered_by: str = "scheduled"
) -> dict:
    """
    Run ONLY data collection (no analysis, no report, no email).

    This is used by the weekly scheduled collection.
    For manual runs that need immediate analysis, use run_collection_analysis_report() instead.

    Args:
        user_id: ID of the user
        brand_id: ID of the brand
        triggered_by: How this was triggered ("scheduled", "manual")

    Returns:
        dict with status information including responses_collected count
    """
    db = SessionLocal()

    try:
        # Verify user and brand exist
        user = db.query(models.User).filter_by(id=user_id).first()
        if not user:
            return {"success": False, "error": f"User {user_id} not found"}

        from app import crud

        # Check if user has access to brand
        if not crud.user_has_brand_access(db, brand_id, user_id):
            return {"success": False, "error": f"Brand {brand_id} not found"}

        brand = db.query(models.BrandInfo).filter_by(id=brand_id).first()
        if not brand:
            return {"success": False, "error": f"Brand {brand_id} not found"}

        # Get the brand owner's user_id (for shared brands)
        data_owner_user_id = brand.user_id

        # Check for active queries
        query_count = db.query(models.Query).filter(
            models.Query.user_id == data_owner_user_id,
            models.Query.brand_id == brand_id,
            models.Query.active == True
        ).count()

        if query_count == 0:
            return {"success": False, "error": "No active queries found"}

        brand_name = brand.brand_name

    finally:
        db.close()

    # Run collection synchronously (blocking)
    db = SessionLocal()

    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        env = os.environ.copy()
        env['PYTHONPATH'] = project_root

        # Run collection script
        script_path = os.path.join(project_root, "scripts", "admin", "collect_responses.py")
        cmd = [
            "python3", script_path,
            str(data_owner_user_id),
            "--brand-id", str(brand_id)
        ]

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for collection (send "1" to auto-select all queries)
        # Timeout after 90 minutes
        try:
            stdout, stderr = process.communicate(input="1\n", timeout=5400)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return {
                "success": False,
                "error": "Collection timed out after 90 minutes",
                "responses_collected": 0
            }

        if process.returncode != 0:
            error_preview = stderr[-500:] if stderr else 'Unknown error'
            return {
                "success": False,
                "error": f"Collection failed: {error_preview}",
                "responses_collected": 0
            }

        # Get the latest batch to count responses
        latest_batch = db.query(models.CollectionBatch).filter(
            models.CollectionBatch.user_id == data_owner_user_id,
            models.CollectionBatch.brand_id == brand_id
        ).order_by(models.CollectionBatch.started_at.desc()).first()

        responses_collected = latest_batch.total_responses if latest_batch else 0

        return {
            "success": True,
            "message": f"Collection completed for {brand_name}",
            "responses_collected": responses_collected,
            "batch_id": latest_batch.id if latest_batch else None,
            "triggered_by": triggered_by
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Collection error: {str(e)}",
            "responses_collected": 0
        }

    finally:
        db.close()


def run_collection_analysis_report(
    user_id: int,
    brand_id: int,
    triggered_by: str = "manual"
) -> dict:
    """
    Run the complete data pipeline: collection → analysis → report → email.

    This is the single source of truth for the data collection workflow.
    Used by:
    - Manual "Run Collection & Analysis" button
    - Scheduled automated runs
    - Admin "Run Now" button

    Args:
        user_id: ID of the user
        brand_id: ID of the brand
        triggered_by: How this was triggered ("manual", "scheduled", "admin")

    Returns:
        dict with status information
    """
    db = SessionLocal()

    try:
        # Verify user and brand exist
        user = db.query(models.User).filter_by(id=user_id).first()
        if not user:
            return {"success": False, "error": f"User {user_id} not found"}

        # Import crud here to access user_has_brand_access
        from app import crud

        # Check if user has access to brand (owns it or has it shared)
        if not crud.user_has_brand_access(db, brand_id, user_id):
            return {"success": False, "error": f"Brand {brand_id} not found"}

        # Get the brand (we know it exists from the access check)
        brand = db.query(models.BrandInfo).filter_by(id=brand_id).first()
        if not brand:
            return {"success": False, "error": f"Brand {brand_id} not found"}

        # Get the brand owner's user_id (for shared brands, we need the owner's data)
        data_owner_user_id = brand.user_id

        # Check for active queries (use data owner's user_id for shared brands)
        query_count = db.query(models.Query).filter(
            models.Query.user_id == data_owner_user_id,
            models.Query.brand_id == brand_id,
            models.Query.active == True
        ).count()

        if query_count == 0:
            return {"success": False, "error": "No active queries found"}

        # Create task status for collection
        collection_task = models.TaskStatus(
            user_id=user_id,
            brand_id=brand_id,
            task_type="collection",
            status="running",
            total_items=query_count * 4,
            processed_items=0,
            message=f"Starting {triggered_by} collection...",
            started_at=utcnow()
        )
        db.add(collection_task)
        db.commit()
        db.refresh(collection_task)

        task_id = collection_task.id

        # Extract values we'll need for the return message before closing session
        user_email = user.email
        brand_name = brand.brand_name

    finally:
        db.close()

    # Run the pipeline in a background thread
    def run_pipeline():
        """Execute collection → analysis → report → email pipeline."""
        db_thread = SessionLocal()

        try:
            # Get project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

            # Set up environment
            env = os.environ.copy()
            env['PYTHONPATH'] = project_root

            # === STEP 1: COLLECTION ===
            script_path = os.path.join(project_root, "scripts", "admin", "collect_responses.py")
            # Use data_owner_user_id for shared brands (data belongs to the brand owner)
            cmd = [
                "python3", script_path,
                str(data_owner_user_id),
                "--brand-id", str(brand_id),
                "--task-id", str(task_id)
            ]

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            # Store process ID
            task = db_thread.query(models.TaskStatus).filter_by(id=task_id).first()
            if task:
                task.process_id = process.pid
                db_thread.commit()

            # Wait for collection (send "1" to auto-select all queries)
            # Timeout after 90 minutes for collection (20 queries * 4 platforms * ~30s + buffer)
            try:
                stdout, stderr = process.communicate(input="1\n", timeout=5400)
            except subprocess.TimeoutExpired:
                # Kill the process if it times out
                process.kill()
                stdout, stderr = process.communicate()
                task = db_thread.query(models.TaskStatus).filter_by(id=task_id).first()
                if task:
                    task.status = "failed"
                    task.error_message = f"Collection timed out after 90 minutes. This usually indicates API timeouts or rate limits. Check error_message for specific platform errors."
                    task.completed_at = utcnow()
                    db_thread.commit()

                # Send failure email
                from app.services.email_notifications import send_task_completion_email
                send_task_completion_email(
                    db=db_thread,
                    user_id=user_id,
                    task_type='collection',
                    task_id=task_id,
                    status='failed',
                    brand_id=brand_id,
                    error_message=task.error_message if task else "Collection timed out"
                )
                return

            if process.returncode != 0:
                # Collection failed
                task = db_thread.query(models.TaskStatus).filter_by(id=task_id).first()
                if task:
                    task.status = "failed"
                    error_preview = stderr[-500:] if stderr else 'Unknown error'
                    task.error_message = f"Collection script failed with exit code {process.returncode}: {error_preview}"
                    task.completed_at = utcnow()
                    db_thread.commit()

                # Send failure email
                from app.services.email_notifications import send_task_completion_email
                send_task_completion_email(
                    db=db_thread,
                    user_id=user_id,
                    task_type='collection',
                    task_id=task_id,
                    status='failed',
                    brand_id=brand_id,
                    error_message=task.error_message if task else "Collection failed"
                )
                return

            # Collection succeeded
            task = db_thread.query(models.TaskStatus).filter_by(id=task_id).first()
            if task:
                task.status = "completed"
                task.completed_at = utcnow()
                db_thread.commit()

            # === STEP 2: ANALYSIS ===
            # Get the latest collection batch (use data owner for shared brands)
            latest_batch = db_thread.query(models.CollectionBatch).filter(
                models.CollectionBatch.user_id == data_owner_user_id,
                models.CollectionBatch.brand_id == brand_id
            ).order_by(models.CollectionBatch.started_at.desc()).first()

            if not latest_batch:
                # No batch found (shouldn't happen after collection)
                return

            # Only analyze responses from the latest batch that haven't been analyzed yet
            responses_to_analyze = db_thread.query(models.Response).filter(
                models.Response.user_id == data_owner_user_id,
                models.Response.brand_id == brand_id,
                models.Response.batch_id == latest_batch.id,
                models.Response.analyzed_at.is_(None)
            ).all()

            if not responses_to_analyze:
                # No new responses to analyze
                return

            # Create analysis task
            analysis_task = models.TaskStatus(
                user_id=user_id,
                brand_id=brand_id,
                task_type="analysis",
                status="running",
                total_items=len(responses_to_analyze),
                processed_items=0,
                message=f"Analyzing {len(responses_to_analyze)} newly collected responses...",
                started_at=utcnow()
            )
            db_thread.add(analysis_task)
            db_thread.commit()
            db_thread.refresh(analysis_task)

            # Run analysis script (use data owner for shared brands)
            analysis_script = os.path.join(project_root, "scripts", "admin", "analyze_responses.py")
            analysis_cmd = [
                "python3", analysis_script,
                "--all",
                "--user-id", str(data_owner_user_id),
                "--brand-id", str(brand_id),
                "--task-id", str(analysis_task.id)
            ]

            analysis_process = subprocess.Popen(
                analysis_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            # Store process ID
            task = db_thread.query(models.TaskStatus).filter_by(id=analysis_task.id).first()
            if task:
                task.process_id = analysis_process.pid
                db_thread.commit()

            # Wait for analysis (timeout after 60 minutes)
            try:
                stdout, stderr = analysis_process.communicate(timeout=3600)
            except subprocess.TimeoutExpired:
                # Kill the process if it times out
                analysis_process.kill()
                stdout, stderr = analysis_process.communicate()
                task = db_thread.query(models.TaskStatus).filter_by(id=analysis_task.id).first()
                if task:
                    task.status = "failed"
                    task.error_message = f"Analysis timed out after 60 minutes. This usually indicates API timeouts or processing errors."
                    task.completed_at = utcnow()
                    db_thread.commit()

                # Send failure email
                send_task_completion_email(
                    db=db_thread,
                    user_id=user_id,
                    task_type='analysis',
                    task_id=analysis_task.id,
                    status='failed',
                    brand_id=brand_id,
                    error_message=task.error_message if task else "Analysis timed out"
                )
                return

            if analysis_process.returncode != 0:
                # Analysis failed
                task = db_thread.query(models.TaskStatus).filter_by(id=analysis_task.id).first()
                if task:
                    task.status = "failed"
                    error_preview = stderr[-500:] if stderr else 'Unknown error'
                    task.error_message = f"Analysis script failed with exit code {analysis_process.returncode}: {error_preview}"
                    task.completed_at = utcnow()
                    db_thread.commit()

                # Send failure email
                send_task_completion_email(
                    db=db_thread,
                    user_id=user_id,
                    task_type='analysis',
                    task_id=analysis_task.id,
                    status='failed',
                    brand_id=brand_id,
                    error_message=task.error_message if task else "Analysis failed"
                )
                return

            # Analysis script completed, but verify responses were actually analyzed
            analyzed_count = db_thread.query(models.Response).filter(
                models.Response.user_id == data_owner_user_id,
                models.Response.brand_id == brand_id,
                models.Response.batch_id == latest_batch.id,
                models.Response.analyzed_at.isnot(None)
            ).count()

            if analyzed_count == 0:
                # Analysis script ran but failed to analyze any responses
                task = db_thread.query(models.TaskStatus).filter_by(id=analysis_task.id).first()
                if task:
                    task.status = "failed"
                    task.error_message = "Analysis script completed but no responses were analyzed. Check LLM provider configuration."
                    task.completed_at = utcnow()
                    db_thread.commit()

                # Send failure email
                from app.services.email_notifications import send_task_completion_email
                send_task_completion_email(
                    db=db_thread,
                    user_id=user_id,
                    task_type='analysis',
                    task_id=analysis_task.id,
                    status='failed',
                    brand_id=brand_id,
                    error_message="Analysis failed: No responses were analyzed. Please check the LLM provider configuration."
                )
                return

            # Analysis actually succeeded
            task = db_thread.query(models.TaskStatus).filter_by(id=analysis_task.id).first()
            if task:
                task.status = "completed"
                task.completed_at = utcnow()
                db_thread.commit()

            # === STEP 2.5: RECOMPUTE BATCH ANALYTICS ===
            # After analysis, brand_mentioned values are populated, so we need to recompute
            # the batch analytics to get accurate mention_rate and mention_count
            try:
                from app.services.batch_analytics import compute_batch_analytics
                analytics = compute_batch_analytics(
                    db=db_thread,
                    batch_id=latest_batch.id,
                    user_id=data_owner_user_id,
                    brand_id=brand_id
                )
                if analytics:
                    print(f"Batch analytics recomputed: mention_rate={analytics.mention_rate}%")
            except Exception as e:
                print(f"Warning: Failed to recompute batch analytics: {e}")
                # Don't fail the pipeline if analytics recompute fails

            # === STEP 3: REPORT GENERATION ===
            report_script = os.path.join(project_root, "scripts", "admin", "generate_report.py")
            report_cmd = [
                "python3", report_script,
                "--user-id", str(data_owner_user_id),
                "--brand-id", str(brand_id)
            ]

            report_process = subprocess.Popen(
                report_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            # Wait for report generation
            report_stdout, report_stderr = report_process.communicate(timeout=3600)

            report_generated = report_process.returncode == 0
            if not report_generated:
                print(f"Report generation failed: {report_stderr}")

            # === STEP 4: SEND COMPLETION EMAIL ===
            user_obj = db_thread.query(models.User).filter_by(id=user_id).first()
            brand_obj = db_thread.query(models.BrandInfo).filter_by(id=brand_id).first()

            # Get collection stats
            latest_batch = db_thread.query(models.CollectionBatch).filter(
                models.CollectionBatch.user_id == data_owner_user_id,
                models.CollectionBatch.brand_id == brand_id
            ).order_by(models.CollectionBatch.started_at.desc()).first()

            responses_collected = latest_batch.total_responses if latest_batch else len(responses_to_analyze)

            # Get site configuration for email
            site_url = get_site_url(db_thread)
            site_name = get_site_name(db_thread)
            admin_email = get_admin_email(db_thread)
            contact_line = f"Questions? Reach out to {admin_email}." if admin_email else ""

            # Email content depends on whether report was generated
            if report_generated:
                subject = f'Your {brand_obj.brand_name} Report is Ready'
                body = f"""Hi {user_obj.full_name or user_obj.email},

Great news! Your AI reputation analysis for {brand_obj.brand_name} is complete.

We've collected and analyzed {responses_collected} responses from ChatGPT, Claude, Gemini, and Perplexity. Your fresh insights are waiting for you at {site_url}/analytics.

Want to see the full story? Check out your detailed report at {site_url}/reports.

{contact_line}

Best regards,
The {site_name} Team"""
            else:
                subject = f'{brand_obj.brand_name} Data Collection Complete'
                contact_note = f", or contact {admin_email} if the issue persists" if admin_email else ""
                body = f"""Hi {user_obj.full_name or user_obj.email},

Your data collection for {brand_obj.brand_name} is complete.

We've collected and analyzed {responses_collected} responses from ChatGPT, Claude, Gemini, and Perplexity. Your analytics dashboard has been updated at {site_url}/analytics.

Note: There was an issue generating the detailed report. Please try generating a new report from the Reports page{contact_note}.

Best regards,
The {site_name} Team"""

            # Send the email
            send_email_sync(user_obj.email, subject, body)

        except subprocess.TimeoutExpired as e:
            # Timeout - mark task as failed
            task = db_thread.query(models.TaskStatus).filter_by(id=task_id).first()
            if task and task.status == "running":
                task.status = "failed"
                task.error_message = f"Process timed out. Check individual platform errors in error log. Timeout details: {str(e)}"
                task.completed_at = utcnow()
                db_thread.commit()

            # Send failure email
            from app.services.email_notifications import send_task_completion_email
            send_task_completion_email(
                db=db_thread,
                user_id=user_id,
                task_type='collection',
                task_id=task_id,
                status='failed',
                brand_id=brand_id,
                error_message=task.error_message if task else "Process timed out"
            )
        except Exception as e:
            # General error - log full exception details
            import traceback
            error_trace = traceback.format_exc()

            task = db_thread.query(models.TaskStatus).filter_by(id=task_id).first()
            if task and task.status == "running":
                task.status = "failed"
                # Include exception type and traceback for debugging
                task.error_message = f"{type(e).__name__}: {str(e)}\n\nTraceback:\n{error_trace[-1000:]}"
                task.completed_at = utcnow()
                db_thread.commit()

            # Send failure email
            from app.services.email_notifications import send_task_completion_email
            send_task_completion_email(
                db=db_thread,
                user_id=user_id,
                task_type='collection',
                task_id=task_id,
                status='failed',
                brand_id=brand_id,
                error_message=f"{type(e).__name__}: {str(e)}"
            )
        finally:
            db_thread.close()

    # Start background thread
    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    return {
        "success": True,
        "message": f"Collection started for {user_email} - {brand_name}",
        "task_id": task_id,
        "triggered_by": triggered_by
    }


# Backward-compatible alias for run_period_report_only
# (was previously called run_period_analysis)
run_period_analysis = run_period_report_only
