from __future__ import annotations

from app.core.settings import Settings, get_settings
from app.db.agent_models import ScheduledAgentORM
from app.db.base import SessionLocal, ensure_database_schema
from app.services.scheduled_agent_registry import update_agent_runtime


def reconcile_agent_statuses(*, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    ensure_database_schema()
    from app.services.jobs import get_job

    with SessionLocal() as session:
        rows = session.query(ScheduledAgentORM).filter(
            ScheduledAgentORM.last_job_id.is_not(None),
            ScheduledAgentORM.last_status.in_(["queued", "running", "cancelling"]),
        ).all()
        pending = [(str(row.id), str(row.last_job_id)) for row in rows]

    updated = 0
    for agent_id, job_id in pending:
        job = get_job(job_id, settings=settings)
        if not job:
            continue
        state = str(job.get("status") or "")
        if state not in {"completed", "failed", "cancelled"}:
            if state and state != "queued":
                update_agent_runtime(agent_id, status=state)
            continue
        result = dict(job.get("result") or {})
        update_agent_runtime(
            agent_id,
            status=str(result.get("status") or state),
            summary=str(result.get("summary") or ""),
            error=str(job.get("error") or ""),
            mark_run=True,
        )
        updated += 1
    return updated
