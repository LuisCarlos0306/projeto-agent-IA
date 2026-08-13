from __future__ import annotations

import os
import threading
import time
from typing import Any

from sqlalchemy import select

from app.core.settings import Settings, get_settings
from app.db.agent_models import ScheduledAgentORM
from app.db.base import SessionLocal, ensure_database_schema
from app.services.custom_skill_jobs import enqueue_custom_skill
from app.services.custom_skill_registry import get_custom_skill
from app.services.scheduled_agent_registry import now_utc, next_run, update_agent_runtime


_scheduler_guard = threading.Lock()
_scheduler_started = False


def enqueue_agent_job(
    agent_id: str,
    *,
    source: str,
    advance_schedule: bool,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    ensure_database_schema()
    with SessionLocal() as session:
        row = session.get(ScheduledAgentORM, agent_id)
        if row is None:
            raise LookupError("agente não encontrado")
        skill = get_custom_skill(row.skill_id)
        if skill is None:
            raise ValueError("a Skill vinculada ao agente não existe mais")
        target = row.target
        name = row.name
        skill_id = row.skill_id

    queued = enqueue_custom_skill(
        skill_id,
        target,
        metadata={
            "source": "scheduled_agent" if source == "schedule" else "agent_run_now",
            "agent_id": agent_id,
            "agent_name": name,
            "automatic": source == "schedule",
        },
        settings=settings,
    )
    update_agent_runtime(
        agent_id,
        job_id=str(queued["job_id"]),
        status="queued",
        error="",
        advance_schedule=advance_schedule,
    )
    return queued


def run_due_agents(*, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    ensure_database_schema()
    current = now_utc()
    with SessionLocal() as session:
        rows = session.scalars(
            select(ScheduledAgentORM).where(
                ScheduledAgentORM.enabled.is_(True),
                ScheduledAgentORM.next_run_at.is_not(None),
                ScheduledAgentORM.next_run_at <= current,
            )
        ).all()
        candidates = [(str(row.id), int(row.interval_minutes), row.skill_id) for row in rows]

    if not candidates:
        return 0

    from app.services import jobs

    client = jobs._redis(settings)
    queued_count = 0
    for agent_id, interval_minutes, skill_id in candidates:
        lock_key = f"{settings.agent_result_prefix}scheduled-agent:{agent_id}:lock"
        if not client.set(lock_key, "1", nx=True, ex=max(60, min(300, interval_minutes * 60))):
            continue
        if get_custom_skill(skill_id) is None:
            with SessionLocal() as session:
                row = session.get(ScheduledAgentORM, agent_id)
                if row is not None:
                    row.enabled = False
                    row.next_run_at = None
                    row.last_status = "invalid_skill"
                    row.last_error = "A Skill vinculada foi removida; agente desabilitado automaticamente."
                    session.commit()
            continue
        try:
            enqueue_agent_job(agent_id, source="schedule", advance_schedule=True, settings=settings)
            queued_count += 1
        except Exception as exc:
            with SessionLocal() as session:
                row = session.get(ScheduledAgentORM, agent_id)
                if row is not None:
                    row.last_status = "schedule_error"
                    row.last_error = f"{type(exc).__name__}: {exc}"[:4000]
                    row.next_run_at = next_run(row.interval_minutes)
                    session.commit()
    return queued_count


def _scheduler_loop(settings: Settings) -> None:
    from app.services.scheduled_agent_status import reconcile_agent_statuses

    poll_seconds = max(5, min(300, int(os.getenv("AGENT_SCHEDULER_POLL_SECONDS", "15") or 15)))
    while True:
        try:
            reconcile_agent_statuses(settings=settings)
            run_due_agents(settings=settings)
        except Exception:
            pass
        time.sleep(poll_seconds)


def start_agent_scheduler(*, settings: Settings | None = None) -> bool:
    global _scheduler_started
    settings = settings or get_settings()
    with _scheduler_guard:
        if _scheduler_started:
            return False
        threading.Thread(
            target=_scheduler_loop,
            args=(settings,),
            name="agent-ia-scheduler",
            daemon=True,
        ).start()
        _scheduler_started = True
        return True
