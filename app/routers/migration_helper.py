"""
Admin-only database maintenance endpoints.

Schema-altering migrations are not exposed over HTTP; run the scripts in
migrations/ against the database directly instead.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import re

from ..database import get_db
from ..auth import get_current_user
from .. import models

router = APIRouter(
    prefix="/migration",
    tags=["Migration Helper"]
)

# Hardcoded whitelist of valid table names (prevents SQL injection)
VALID_TABLES = {
    'users', 'queries', 'responses', 'target_descriptors', 'competitors',
    'brand_info', 'brand_shares', 'task_status', 'reports',
    'collection_batches', 'scheduled_tasks', 'tenants'
}

def validate_table_name(table: str) -> str:
    """Validate and sanitize table name to prevent SQL injection."""
    if table not in VALID_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    return table

def validate_sequence_name(sequence_name: str) -> str:
    """Validate PostgreSQL sequence name format to prevent SQL injection."""
    if not sequence_name:
        raise ValueError("Empty sequence name")

    # PostgreSQL sequence names follow pattern: schema.sequence_name or sequence_name
    # Allow only alphanumeric, underscore, and dot (for schema.table format)
    if not re.match(r'^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)?$', sequence_name):
        raise ValueError(f"Invalid sequence name format: {sequence_name}")

    return sequence_name


@router.post("/reset-sequences")
def reset_sequences(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reset auto-increment sequences for all tables to match current max IDs.
    This fixes "duplicate key value" errors when sequences get out of sync.
    Admin only.
    """
    # Only admin can run this
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    tables = [
        'users',
        'queries',
        'responses',
        'target_descriptors',
        'competitors',
        'brand_info',
        'brand_shares',
        'task_status',
        'reports',
        'collection_batches',
        'scheduled_tasks',
        'tenants'
    ]

    results = {}

    try:
        for table in tables:
            try:
                # Validate table name against whitelist
                validated_table = validate_table_name(table)

                # Get the sequence name for this table's id column
                # Use parameterized query where possible
                result = db.execute(
                    text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                    {"table_name": validated_table}
                )
                sequence_name = result.scalar()

                if sequence_name:
                    # Validate sequence name format
                    validated_sequence = validate_sequence_name(sequence_name)

                    # Reset the sequence to max(id) + 1
                    # Note: PostgreSQL doesn't allow parameterized identifiers in setval.
                    # Both identifiers are format-validated above before use.
                    reset_sql = f"SELECT setval('{validated_sequence}', COALESCE((SELECT MAX(id) FROM {validated_table}), 1), true)"  # nosec B608
                    # Admin-only. Identifiers come from VALID_TABLES and from
                    # pg_get_serial_sequence, both format-validated above.
                    # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                    db.execute(text(reset_sql))
                    results[table] = "reset"
                else:
                    results[table] = "no sequence"
            except ValueError as e:
                results[table] = f"validation error: {str(e)}"
            except Exception as e:
                results[table] = f"error: {str(e)}"

        db.commit()

        return {
            "success": True,
            "message": "Sequences reset successfully",
            "results": results
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to reset sequences: {str(e)}")


@router.get("/debug-brand-shares")
def debug_brand_shares(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Debug endpoint to check brand_shares table state.
    Admin only.
    """
    # Only admin can run this
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        # Get all shares
        shares_result = db.execute(text("SELECT * FROM brand_shares ORDER BY id"))
        shares = [dict(row._mapping) for row in shares_result]

        # Get max ID and current sequence value
        max_id_result = db.execute(text("SELECT MAX(id) FROM brand_shares"))
        max_id = max_id_result.scalar()

        seq_result = db.execute(text("SELECT pg_get_serial_sequence('brand_shares', 'id')"))
        sequence_name = seq_result.scalar()

        seq_value = None
        if sequence_name:
            # Validate sequence name format before using in query
            validated_sequence = validate_sequence_name(sequence_name)
            # PostgreSQL doesn't allow parameterized identifiers for FROM clause
            # But we've validated the format, so this is safe
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            seq_val_result = db.execute(text(f"SELECT last_value FROM {validated_sequence}"))  # nosec B608: validated_sequence is format-validated above
            seq_value = seq_val_result.scalar()

        return {
            "shares": shares,
            "max_id": max_id,
            "sequence_name": sequence_name,
            "sequence_current_value": seq_value,
            "total_shares": len(shares)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")
