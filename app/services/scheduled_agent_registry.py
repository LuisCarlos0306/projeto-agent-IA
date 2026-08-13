from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.agent_models import AgentRunHistoryORM, ScheduledAgentORM
from app.db.base import SessionLocal, ensure_database_schema
from app.services.custom_skill_registry import get_custom_skill


MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 10080


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_interval(value: int) -> int:
    interval = int(value)
    if interval < MIN_INTERVAL_MINUTES or interval > MAX_INTERVAL_MINUTES:
        raise ValueError(
            f"intervalo deve ficar entre {MIN_INTERVAL_MINUTES} e {MAX_INTERVAL_MINUTES} minutos"
        )
    return interval


def next_run(interval_minutes: int, *, base: datetime | None = None) -> datetime:
    return (base or now_utc()) + timedelta(minutes=normalize_interval(interval_minutes))


def _clean_name(value: str) -> str:
    name = " ".join(str(value or "").strip().split())
    if len(name) < 2 or len(name) > 120:
        raise ValueError("o nome do agente deve ter entre 2 e 120 caracteres")
    return name


def _clean_target(value: str) -> str:
    target = str(value or "").strip()
    if not target or len(target) > 255:
        raise ValueError("informe um IP ou servidor válido")
    return target


def require_skill(skill_id: str) -> dict[str, Any]:
    skill = get_custom_skill(str(skill_id or "").strip())
    if skill is None:
        raise ValueError("a Skill selecionada não existe mais")
    return skill


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    return now_utc()


def serialize_history(row: AgentRunHistoryORM) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "job_id": row.job_id,
        "status": row.status,
        "summary": row.summary,
        "error": row.error,
        "correction_status": row.correction_status,
        "correction_message": row.correction_message,
        "completed_at": _iso(row.completed_at),
    }


def list_agent_history(agent_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    ensure_database_schema()
    try:
        identifier = uuid.UUID(str(agent_id))
    except ValueError:
        return []
    safe_limit = max(1, min(20, int(limit)))
    with SessionLocal() as session:
        rows = session.scalars(
            select(AgentRunHistoryORM)
            .where(AgentRunHistoryORM.agent_id == identifier)
            .order_by(AgentRunHistoryORM.completed_at.desc())
            .limit(safe_limit)
        ).all()
        return [serialize_history(row) for row in rows]


def record_agent_history(
    agent_id: str,
    *,
    job_id: str,
    status: str,
    summary: str = "",
    error: str = "",
    correction_status: str = "not_needed",
    correction_message: str = "",
    completed_at: datetime | str | None = None,
) -> None:
    ensure_database_schema()
    try:
        identifier = uuid.UUID(str(agent_id))
    except ValueError:
        return
    row = AgentRunHistoryORM(
        agent_id=identifier,
        job_id=str(job_id)[:64],
        status=str(status or "completed")[:40],
        summary=str(summary or "")[:4000] or None,
        error=str(error or "")[:4000] or None,
        correction_status=str(correction_status or "not_needed")[:40],
        correction_message=str(correction_message or "")[:4000] or None,
        completed_at=_parse_datetime(completed_at),
    )
    with SessionLocal() as session:
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()


def serialize_agent(row: ScheduledAgentORM) -> dict[str, Any]:
    skill = get_custom_skill(row.skill_id)
    return {
        "id": str(row.id),
        "name": row.name,
        "skill_id": row.skill_id,
        "skill_name": skill.get("name") if skill else "Skill removida",
        "skill_mode": skill.get("mode") if skill else None,
        "skill_missing": skill is None,
        "target": row.target,
        "interval_minutes": int(row.interval_minutes),
        "enabled": bool(row.enabled),
        "last_job_id": row.last_job_id,
        "last_status": row.last_status,
        "last_error": row.last_error,
        "last_summary": row.last_summary,
        "last_run_at": _iso(row.last_run_at),
        "next_run_at": _iso(row.next_run_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "automatic_correction": False,
        "history": list_agent_history(str(row.id), limit=5),
    }


def list_agents() -> list[dict[str, Any]]:
    ensure_database_schema()
    with SessionLocal() as session:
        rows = session.scalars(select(ScheduledAgentORM).order_by(ScheduledAgentORM.name.asc())).all()
        return [serialize_agent(row) for row in rows]


def get_agent(agent_id: str) -> dict[str, Any] | None:
    ensure_database_schema()
    try:
        identifier = uuid.UUID(str(agent_id))
    except ValueError:
        return None
    with SessionLocal() as session:
        row = session.get(ScheduledAgentORM, identifier)
        return serialize_agent(row) if row else None


def create_agent(
    name: str,
    skill_id: str,
    target: str,
    interval_minutes: int,
    *,
    enabled: bool = True,
    created_by: str | None = None,
) -> dict[str, Any]:
    ensure_database_schema()
    interval = normalize_interval(interval_minutes)
    skill = require_skill(skill_id)
    row = ScheduledAgentORM(
        name=_clean_name(name),
        skill_id=str(skill["id"]),
        target=_clean_target(target),
        interval_minutes=interval,
        enabled=bool(enabled),
        next_run_at=next_run(interval) if enabled else None,
        created_by=str(created_by or "").strip() or None,
    )
    with SessionLocal() as session:
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("já existe um agente com esse nome") from exc
        session.refresh(row)
        return serialize_agent(row)


def update_agent(
    agent_id: str,
    *,
    name: str,
    skill_id: str,
    target: str,
    interval_minutes: int,
    enabled: bool,
) -> dict[str, Any]:
    ensure_database_schema()
    identifier = uuid.UUID(str(agent_id))
    interval = normalize_interval(interval_minutes)
    skill = require_skill(skill_id)
    with SessionLocal() as session:
        row = session.get(ScheduledAgentORM, identifier)
        if row is None:
            raise LookupError("agente não encontrado")
        was_enabled = bool(row.enabled)
        interval_changed = int(row.interval_minutes) != interval
        row.name = _clean_name(name)
        row.skill_id = str(skill["id"])
        row.target = _clean_target(target)
        row.interval_minutes = interval
        row.enabled = bool(enabled)
        if not row.enabled:
            row.next_run_at = None
        elif not was_enabled or interval_changed or row.next_run_at is None:
            row.next_run_at = next_run(interval)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("já existe um agente com esse nome") from exc
        session.refresh(row)
        return serialize_agent(row)


def set_agent_enabled(agent_id: str, enabled: bool) -> dict[str, Any]:
    ensure_database_schema()
    identifier = uuid.UUID(str(agent_id))
    with SessionLocal() as session:
        row = session.get(ScheduledAgentORM, identifier)
        if row is None:
            raise LookupError("agente não encontrado")
        row.enabled = bool(enabled)
        row.next_run_at = next_run(row.interval_minutes) if row.enabled else None
        session.commit()
        session.refresh(row)
        return serialize_agent(row)


def delete_agent(agent_id: str) -> bool:
    ensure_database_schema()
    try:
        identifier = uuid.UUID(str(agent_id))
    except ValueError:
        return False
    with SessionLocal() as session:
        row = session.get(ScheduledAgentORM, identifier)
        if row is None:
            return False
        session.query(AgentRunHistoryORM).filter(AgentRunHistoryORM.agent_id == identifier).delete()
        session.delete(row)
        session.commit()
        return True


def update_agent_runtime(
    agent_id: str,
    *,
    job_id: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    error: str | None = None,
    mark_run: bool = False,
    advance_schedule: bool = False,
) -> None:
    ensure_database_schema()
    try:
        identifier = uuid.UUID(str(agent_id))
    except ValueError:
        return
    with SessionLocal() as session:
        row = session.get(ScheduledAgentORM, identifier)
        if row is None:
            return
        if job_id is not None:
            row.last_job_id = str(job_id)[:64]
        if status is not None:
            row.last_status = str(status)[:40]
        if summary is not None:
            row.last_summary = str(summary)[:4000] or None
        if error is not None:
            row.last_error = str(error)[:4000] or None
        if mark_run:
            row.last_run_at = now_utc()
        if advance_schedule and row.enabled:
            row.next_run_at = next_run(row.interval_minutes)
        session.commit()
