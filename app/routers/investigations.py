"""
Investigations API.

An investigation explains WHY the metrics moved between two comparable windows.
The dashboard says the mention rate fell; an investigation drills into which
queries and platforms moved, reads the answers, and writes up findings.

Endpoints here own the record and its lifecycle. The agent loop that fills in
the findings lives in app/services/investigation/; until it is wired up, a
triggered investigation stays 'pending' and its evidence can be inspected
through the preview endpoint.
"""
import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..services.investigation import evidence
from ..services.investigation.scope import (
    DEFAULT_COMPARISON_MODE,
    ScopeError,
    apply_scope_to_record,
    build_scope,
    scope_from_investigation,
)
from ..services.period_ranges import parse_period_start
from ..utils.brand_access import (
    get_active_brand_id,
    get_data_owner_user_id,
    get_user_brand_or_404,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/investigations",
    tags=["investigations"]
)

#: A run whose heartbeat is older than this was orphaned by a restart or a
#: crash. Without a reaper such records sit in 'running' forever, which is a
#: known failure mode of the implementation this feature is modelled on.
STALE_RUN_MINUTES = 30


def _resolve_brand(db: Session, body_brand_id: Optional[int],
                   active_brand_id: Optional[int], current_user_id: int):
    brand_id = body_brand_id or active_brand_id
    if not brand_id:
        raise HTTPException(
            status_code=400, detail="No brand specified and no active brand set")
    brand = get_user_brand_or_404(db, brand_id, current_user_id)
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user_id)
    return brand, brand_id, owner_user_id


def reap_stale_runs(db: Session, brand_id: int) -> int:
    """Fail any investigation whose run was orphaned.

    Called on list, so a crashed run cannot sit in 'running' indefinitely and
    block the UI's polling forever.
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=STALE_RUN_MINUTES)
    stale = db.query(models.Investigation).filter(
        models.Investigation.brand_id == brand_id,
        models.Investigation.status == 'running',
        models.Investigation.last_heartbeat_at.isnot(None),
        models.Investigation.last_heartbeat_at < cutoff,
    ).all()
    for investigation in stale:
        investigation.status = 'failed'
        investigation.completed_at = datetime.datetime.utcnow()
        investigation.error_message = (
            f"The run stopped reporting progress for more than {STALE_RUN_MINUTES} "
            "minutes and was marked failed. This usually means the server "
            "restarted mid-investigation. Re-run to try again.")
    if stale:
        db.commit()
    return len(stale)


@router.post("/trigger", response_model=Dict[str, Any], status_code=202)
def trigger_investigation(
    body: schemas.InvestigationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    active_brand_id: Optional[int] = Depends(get_active_brand_id),
):
    """Start an investigation.

    comparison_mode 'month' (the default) or 'quarter' compares whole calendar
    periods, exactly as the dashboard's comparison modes do. 'batch' compares
    the most recent collection against the one before it, which is a noisier
    signal. period_start ("YYYY-MM-DD") pins a specific period; omitted means
    the last complete one.
    """
    brand, brand_id, owner_user_id = _resolve_brand(
        db, body.brand_id, active_brand_id, current_user.id)

    try:
        scope = build_scope(
            db, owner_user_id, brand_id,
            mode=body.comparison_mode or DEFAULT_COMPARISON_MODE,
            period_start=parse_period_start(body.period_start),
            batch_id=body.batch_id,
        )
    except ScopeError as exc:
        # These messages explain what is wrong with the request (an empty
        # period, an unknown batch), so they are worth surfacing verbatim.
        raise HTTPException(status_code=400, detail=str(exc))

    investigation = models.Investigation(
        user_id=owner_user_id,
        brand_id=brand_id,
        trigger_type='manual',
        status='pending',
    )
    apply_scope_to_record(investigation, scope)
    db.add(investigation)
    db.commit()
    db.refresh(investigation)

    logger.info(
        "Investigation %s queued for brand %s: %s vs %s",
        investigation.id, brand_id, scope.current_label, scope.previous_label)

    return {
        "investigation_id": investigation.id,
        "status": investigation.status,
        "comparison_mode": scope.mode,
        "message": (f"Investigation started for {brand.brand_name}: "
                    f"{scope.current_label} vs {scope.previous_label}"),
    }


@router.get("/", response_model=List[schemas.InvestigationSummary])
def list_investigations(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    brand_id: Optional[int] = Depends(get_active_brand_id),
):
    """Investigations for the active brand, most recent first."""
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand set")
    owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    reap_stale_runs(db, brand_id)

    rows = db.query(models.Investigation).filter(
        models.Investigation.user_id == owner_user_id,
        models.Investigation.brand_id == brand_id,
    ).order_by(models.Investigation.created_at.desc()).limit(limit).all()

    return [
        schemas.InvestigationSummary(
            id=r.id, title=r.title, status=r.status, trigger_type=r.trigger_type,
            comparison_mode=r.comparison_mode,
            current_period_label=r.current_period_label,
            previous_period_label=r.previous_period_label,
            current_batch_id=r.current_batch_id,
            previous_batch_id=r.previous_batch_id,
            total_tool_calls=r.total_tool_calls or 0,
            has_limitations=bool(r.limitations and r.limitations != '[]'),
            started_at=r.started_at, completed_at=r.completed_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _get_investigation(db: Session, investigation_id: int,
                       current_user_id: int) -> models.Investigation:
    investigation = db.query(models.Investigation).filter(
        models.Investigation.id == investigation_id).first()
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    # Access is brand-scoped: anyone who can see the brand can see its
    # investigations, including users the brand is shared with.
    get_user_brand_or_404(db, investigation.brand_id, current_user_id)
    return investigation


@router.get("/{investigation_id}", response_model=schemas.InvestigationDetail)
def get_investigation(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Full detail for one investigation."""
    return _get_investigation(db, investigation_id, current_user.id)


@router.get("/{investigation_id}/tool-invocations",
            response_model=List[schemas.InvestigationToolInvocationSchema])
def get_tool_invocations(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Every piece of evidence the agent looked at, in order.

    Exposed deliberately: an investigation's conclusions are only checkable if
    its inputs are visible.
    """
    investigation = _get_investigation(db, investigation_id, current_user.id)
    return db.query(models.InvestigationToolInvocation).filter(
        models.InvestigationToolInvocation.investigation_id == investigation.id
    ).order_by(models.InvestigationToolInvocation.sequence).all()


@router.get("/{investigation_id}/evidence", response_model=Dict[str, Any])
def get_investigation_evidence(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """The deterministic evidence for this comparison, without any agent run.

    Every number an investigation can cite, computed from metrics_core. Useful
    on its own, and it means the expensive part of the feature can be reviewed
    before any model is called.
    """
    investigation = _get_investigation(db, investigation_id, current_user.id)
    try:
        scope = scope_from_investigation(investigation)
    except ScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "comparison": {
            "mode": scope.mode,
            "current": scope.current_label,
            "previous": scope.previous_label,
        },
        "context": evidence.brand_context(db, scope),
        "metrics": evidence.compare_scopes(db, scope),
        "queries": evidence.query_level_deltas(db, scope),
        "platforms": evidence.platform_breakdown(db, scope),
        "competitors": evidence.competitor_changes(db, scope),
        "descriptors": evidence.descriptor_changes(db, scope),
        "trend": evidence.historical_trend(db, scope),
    }


@router.delete("/{investigation_id}", status_code=204)
def delete_investigation(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete an investigation and its audit trail."""
    investigation = _get_investigation(db, investigation_id, current_user.id)
    db.delete(investigation)
    db.commit()
