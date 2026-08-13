from __future__ import annotations

from typing import Any

from app.core.settings import Settings, get_settings
from app.db.agent_models import ScheduledAgentORM
from app.db.base import SessionLocal, ensure_database_schema
from app.services.scheduled_agent_registry import record_agent_history, update_agent_runtime


def _action_text(action: dict[str, Any]) -> str:
    return " ".join(
        str(action.get(key) or "")
        for key in ("command", "path", "action", "description", "name")
    ).strip().casefold()


def _is_mount_action(action: dict[str, Any]) -> bool:
    text = _action_text(action)
    return "mount " in f" {text} " or "mount.sh" in text or "montagem" in text


def _action_succeeded(action: dict[str, Any]) -> bool:
    if action.get("success") is True:
        return True
    exit_code = action.get("exit_code")
    if exit_code is not None:
        try:
            return int(exit_code) == 0
        except (TypeError, ValueError):
            return False
    return str(action.get("status") or "").casefold() in {
        "success",
        "succeeded",
        "completed",
        "healthy",
        "ok",
    }


def _post_validation_confirmed(action: dict[str, Any]) -> bool:
    for key in ("post_validation", "validation"):
        value = action.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            if value.get("success") is True or value.get("ok") is True or value.get("validated") is True:
                return True
            if str(value.get("status") or "").casefold() in {"success", "healthy", "ok", "confirmed"}:
                return True
    return action.get("validated") is True or action.get("verified") is True


def correction_outcome(result: dict[str, Any], terminal_state: str = "completed") -> tuple[str, str]:
    """Resume o resultado corretivo sem inferir sucesso sem evidência de pós-validação."""
    executed = [item for item in result.get("executed_actions") or [] if isinstance(item, dict)]
    if executed:
        mount_actions = [item for item in executed if _is_mount_action(item)]
        relevant = mount_actions or executed
        failures = [item for item in relevant if not _action_succeeded(item)]
        if failures:
            if mount_actions:
                return "executed_failed", "A montagem foi executada, mas retornou falha."
            return "executed_failed", "A correção foi executada, mas retornou falha."
        confirmed = all(_post_validation_confirmed(item) for item in relevant)
        if confirmed:
            if mount_actions:
                return "executed_success", "Montagem executada com sucesso e confirmada pela pós-validação."
            return "executed_success", "Correção executada com sucesso e confirmada pela pós-validação."
        if mount_actions:
            return "executed_unverified", "O comando de montagem executou sem erro, mas a pós-validação ainda não confirmou que o ponto está montado."
        return "executed_unverified", "A correção executou sem erro, mas ainda não foi confirmada pela pós-validação."

    pending_commands = [item for item in result.get("pending_commands") or [] if isinstance(item, dict)]
    pending_scripts = [item for item in result.get("scripts") or [] if isinstance(item, dict)]
    awaiting = [
        item for item in [*pending_commands, *pending_scripts]
        if str(item.get("status") or "") == "pending_approval"
    ]
    blocked = [
        item for item in pending_commands
        if str(item.get("status") or "") == "blocked_by_policy"
    ]
    if awaiting:
        mount_pending = any(_is_mount_action(item) for item in awaiting)
        suffix = f" {len(blocked)} ação(ões) adicional(is) estão bloqueadas pela política." if blocked else ""
        if mount_pending:
            return "pending_approval", "Montagem não executada: aguardando aprovação operacional." + suffix
        return "pending_approval", f"{len(awaiting)} ação(ões) corretiva(s) aguardam aprovação operacional." + suffix
    if blocked:
        mount_blocked = any(_is_mount_action(item) for item in blocked)
        if mount_blocked:
            return "blocked", "Montagem não executada: ação bloqueada pela política do ambiente."
        return "blocked", f"{len(blocked)} ação(ões) corretiva(s) foram bloqueadas pela política do ambiente."
    if terminal_state in {"failed", "cancelled"}:
        return "not_evaluated", "A execução terminou antes de confirmar necessidade ou resultado de correção."
    return "not_needed", "Nenhuma correção foi necessária nesta validação."


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
        final_status = str(result.get("status") or state)
        summary = str(result.get("summary") or "")
        error = str(job.get("error") or "")
        correction_status, correction_message = correction_outcome(result, state)
        update_agent_runtime(
            agent_id,
            status=final_status,
            summary=summary,
            error=error,
            mark_run=True,
        )
        record_agent_history(
            agent_id,
            job_id=job_id,
            status=final_status,
            summary=summary,
            error=error,
            correction_status=correction_status,
            correction_message=correction_message,
            completed_at=job.get("completed_at"),
        )
        updated += 1
    return updated
