from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.agent_run_models import AgentRunDetailORM
from app.db.base import SessionLocal, engine
from app.services.redaction import redact_object


def _ensure_schema() -> None:
    AgentRunDetailORM.__table__.create(bind=engine, checkfirst=True)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_json(value: Any, limit: int = 24000) -> str:
    text = json.dumps(redact_object(value), ensure_ascii=False, default=str)
    return text[:limit]


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def execution_outcome(job: dict[str, Any], result: dict[str, Any]) -> str:
    state = str(job.get("status") or "").casefold()
    if state == "cancelled":
        return "cancelled"
    if state == "failed":
        return "completed_error"
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    if any(int(item.get("exit_code") or 0) != 0 for item in commands):
        return "completed_error"
    if str(result.get("correction_status") or "") == "executed_failed":
        return "completed_error"
    return "completed_success"


def _failure_stage(job: dict[str, Any], result: dict[str, Any]) -> str | None:
    if execution_outcome(job, result) != "completed_error":
        return None
    if str(result.get("correction_status") or "") == "executed_failed":
        return "pós-validação da correção"
    phase = dict(job.get("current_phase") or {})
    if phase.get("stage"):
        return str(phase["stage"])[:120]
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    if any(int(item.get("exit_code") or 0) != 0 for item in commands):
        return "execução de comando da Skill"
    return "execução do Agente"


def _error_code(job: dict[str, Any], result: dict[str, Any]) -> str | None:
    executed = [item for item in result.get("executed_actions") or [] if isinstance(item, dict)]
    failed_action = next((item for item in reversed(executed) if str(item.get("status") or "") == "failed"), None)
    if failed_action is not None and failed_action.get("exit_code") is not None:
        return f"exit_code={int(failed_action.get('exit_code') or 0)}"
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    failed = next((item for item in commands if int(item.get("exit_code") or 0) != 0), None)
    if failed is not None:
        return f"exit_code={int(failed.get('exit_code') or 0)}"
    text = str(job.get("error") or result.get("error") or "")
    match = re.search(r"\b(?:code|código|status)\s*[:=]?\s*([0-9]{3,5})\b", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _recommendation(job: dict[str, Any], result: dict[str, Any]) -> str | None:
    if execution_outcome(job, result) != "completed_error":
        return None
    if str(result.get("correction_status") or "") == "executed_failed":
        return "Revisar a saída da ação corretiva e a pós-validação antes de aprovar nova tentativa."
    phase = str((job.get("current_phase") or {}).get("stage") or "").casefold()
    error = str(job.get("error") or "").casefold()
    if "ssh" in phase or "connect" in phase or "connection" in error:
        return "Verificar conectividade, resolução do alvo, porta SSH e credenciais autorizadas antes de tentar novamente."
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    if any(int(item.get("exit_code") or 0) != 0 for item in commands):
        return "Revisar o comando que falhou e a saída de erro registrada antes de executar novamente."
    return "Revisar o detalhe técnico e a etapa da falha antes de executar novamente."


def _actions(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in result.get("commands") or []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "type": "command",
            "value": item.get("command"),
            "status": "success" if int(item.get("exit_code") or 0) == 0 else "error",
            "exit_code": item.get("exit_code"),
            "stdout": str(item.get("stdout") or "")[:4000],
            "stderr": str(item.get("stderr") or "")[:4000],
        })
    for item in result.get("executed_actions") or []:
        if isinstance(item, dict):
            rows.append({"type": "correction", **item})
    for item in result.get("pending_commands") or []:
        if isinstance(item, dict):
            rows.append({
                "type": "pending",
                "value": item.get("command"),
                "status": item.get("status"),
                "reason": item.get("reason"),
            })
    for item in result.get("scripts") or []:
        if isinstance(item, dict):
            rows.append({
                "type": "script",
                "value": item.get("path"),
                "status": item.get("status"),
                "reason": item.get("reason"),
            })
    return rows


def record_run_detail(agent_id: str, job: dict[str, Any], result: dict[str, Any]) -> None:
    """Cria ou atualiza o detalhe da execução, inclusive após correção aprovada."""
    _ensure_schema()
    try:
        identifier = uuid.UUID(str(agent_id))
    except ValueError:
        return
    job_id = str(job.get("job_id") or "")[:64]
    if not job_id:
        return
    started = _parse_datetime(job.get("started_at"))
    completed = _parse_datetime(job.get("completed_at")) or datetime.now(timezone.utc)
    duration_ms = None
    if started and completed:
        duration_ms = max(0, int((completed - started).total_seconds() * 1000))
    outcome = execution_outcome(job, result)
    result_summary = {
        "skill": result.get("name") or result.get("skill"),
        "target": result.get("target"),
        "resolved_host": result.get("resolved_host"),
        "environment": result.get("environment"),
        "status": result.get("status"),
        "summary": result.get("summary"),
        "approval_required": bool(result.get("approval_required")),
        "policy_blocked": bool(result.get("policy_blocked")),
        "correction_status": result.get("correction_status"),
        "correction_message": result.get("correction_message"),
        "error": job.get("error"),
    }
    with SessionLocal() as session:
        row = session.scalar(select(AgentRunDetailORM).where(AgentRunDetailORM.job_id == job_id))
        if row is None:
            row = AgentRunDetailORM(agent_id=identifier, job_id=job_id)
            session.add(row)
        row.started_at = started
        row.completed_at = completed
        row.duration_ms = duration_ms
        row.final_state = outcome
        row.failure_stage = _failure_stage(job, result)
        row.error_code = _error_code(job, result)
        row.actions_json = _safe_json(_actions(result))
        row.result_json = _safe_json(result_summary)
        row.recommendation = _recommendation(job, result)
        session.commit()


def run_detail_map(job_ids: list[str]) -> dict[str, dict[str, Any]]:
    _ensure_schema()
    safe_ids = [str(item)[:64] for item in job_ids if item]
    if not safe_ids:
        return {}
    with SessionLocal() as session:
        rows = session.scalars(select(AgentRunDetailORM).where(AgentRunDetailORM.job_id.in_(safe_ids))).all()
    return {
        row.job_id: {
            "started_at": _iso(row.started_at),
            "completed_at": _iso(row.completed_at),
            "duration_ms": row.duration_ms,
            "execution_state": row.final_state,
            "failure_stage": row.failure_stage,
            "error_code": row.error_code,
            "actions": _loads(row.actions_json, []),
            "result": _loads(row.result_json, {}),
            "recommendation": row.recommendation,
        }
        for row in rows
    }
