from __future__ import annotations

import shlex
from typing import Any

from app.core.policies import EnvironmentType, environment_allows_correction
from app.core.settings import Settings, get_settings
from app.services.approvals import create_approval_token, token_digest, verify_approval_token
from app.services.correction_policy import STANDARD_MOUNT_SCRIPT, validate_correction
from app.services.custom_skill_registry import get_custom_skill, validate_custom_command
from app.services.redaction import redact_text
from app.services.reviewer import review_corrections
from app.services.runner import build_executor, resolve_target
from app.services.scheduled_agent_registry import (
    get_agent,
    update_agent_history_result,
    update_agent_runtime,
)
from app.services.scheduled_agent_run_log import record_run_detail
from app.services.tool_registry import execute_tool


class CustomSkillCorrectionError(RuntimeError):
    pass


def _mount_point_from_command(command: str) -> str | None:
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        return None
    if len(parts) == 2 and parts[0] == "mount" and parts[1].startswith("/"):
        return parts[1]
    return None


def _mount_point_from_findmnt(command: str) -> str | None:
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        return None
    if not parts or parts[0] != "findmnt":
        return None
    for index, value in enumerate(parts[:-1]):
        if value in {"-M", "--mountpoint"} and parts[index + 1].startswith("/"):
            return parts[index + 1]
    return None


def _structured_action(skill: dict[str, Any]) -> dict[str, Any]:
    condition = dict(skill.get("condition") or {})
    if not condition or not condition.get("enabled"):
        raise CustomSkillCorrectionError("a correção aprovada exige uma Skill com fluxo condicional")
    action = dict(condition.get("action") or {})
    action_type = str(action.get("type") or "command").strip().casefold()
    value = str(action.get("value") or "").strip()

    if action_type == "script" and value == STANDARD_MOUNT_SCRIPT:
        mount_point = (
            _mount_point_from_findmnt(str(condition.get("post_validation") or ""))
            or _mount_point_from_findmnt(str(condition.get("validation") or ""))
        )
        if not mount_point:
            raise CustomSkillCorrectionError("não foi possível determinar o ponto de montagem pela validação da Skill")
        return {
            "tool": "backup.mount_standard",
            "arguments": {"mount_point": mount_point},
            "configured_action": value,
            "label": f"Executar {STANDARD_MOUNT_SCRIPT} e confirmar {mount_point}",
        }

    if action_type == "command":
        mount_point = _mount_point_from_command(value)
        if mount_point:
            return {
                "tool": "backup.mount_standard",
                "arguments": {"mount_point": mount_point},
                "configured_action": value,
                "label": f"Montar {mount_point} usando {STANDARD_MOUNT_SCRIPT}",
            }
        try:
            parts = shlex.split(value)
        except ValueError as exc:
            raise CustomSkillCorrectionError("ação corretiva possui sintaxe inválida") from exc
        if len(parts) >= 3 and parts[0] == "systemctl":
            action_name = " ".join(parts[1:-1])
            unit = parts[-1]
            if action_name in {"start", "restart", "reload", "enable --now"}:
                return {
                    "tool": "systemd.recover_unit",
                    "arguments": {"unit": unit, "action": action_name},
                    "configured_action": value,
                    "label": value,
                }

    raise CustomSkillCorrectionError(
        "a ação configurada ainda não possui executor estruturado; permaneceu apenas como proposta"
    )


def _run_read_only(executor: Any, command: str, environment: EnvironmentType, settings: Settings) -> dict[str, Any]:
    safe = validate_custom_command(command, "read_only")
    result = executor.run(
        safe,
        environment,
        approved=False,
        timeout=min(120, int(getattr(settings, "ssh_command_timeout", 60) or 60)),
    )
    return {
        "command": safe,
        "exit_code": int(result.exit_code),
        "stdout": redact_text(str(result.stdout or ""))[:8000],
        "stderr": redact_text(str(result.stderr or ""))[:4000],
        "ok": int(result.exit_code) == 0,
    }


def _execute_standard_mount(
    executor: Any,
    environment: EnvironmentType,
    mount_point: str,
    settings: Settings,
) -> dict[str, Any]:
    decision = validate_correction(STANDARD_MOUNT_SCRIPT)
    if not decision.allowed:
        raise CustomSkillCorrectionError(decision.reason)

    quoted = shlex.quote(mount_point)
    before = _run_read_only(executor, f"findmnt -M {quoted}", environment, settings)
    result = executor.run_sudo(
        STANDARD_MOUNT_SCRIPT,
        environment,
        approved=True,
        timeout=max(120, int(getattr(settings, "ssh_command_timeout", 60) or 60)),
    )
    after = _run_read_only(executor, f"findmnt -M {quoted}", environment, settings)
    validated = int(result.exit_code) == 0 and bool(after["ok"])
    return {
        "tool": "backup.mount_standard",
        "arguments": {"mount_point": mount_point},
        "command": STANDARD_MOUNT_SCRIPT,
        "status": "validated" if validated else "failed",
        "exit_code": int(result.exit_code),
        "stdout": redact_text(str(result.stdout or ""))[:8000],
        "stderr": redact_text(str(result.stderr or ""))[:4000],
        "pre_validation": before,
        "post_validation": after,
        "validated": validated,
    }


def _remove_executed_pending(result: dict[str, Any], configured_action: str) -> None:
    result["pending_commands"] = [
        item
        for item in result.get("pending_commands") or []
        if str(item.get("command") or "") != configured_action
    ]
    result["scripts"] = [
        item
        for item in result.get("scripts") or []
        if str(item.get("path") or "") != configured_action
    ]
    result["approval_required"] = any(
        str(item.get("status") or "") == "pending_approval"
        for item in [*(result.get("pending_commands") or []), *(result.get("scripts") or [])]
    )


def correction_preview(agent_id: str, *, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    agent = get_agent(agent_id)
    if not agent:
        raise CustomSkillCorrectionError("agente não encontrado")
    job_id = str(agent.get("last_job_id") or "")
    if not job_id:
        raise CustomSkillCorrectionError("o agente ainda não possui execução para corrigir")

    from app.services.jobs import get_job

    job = get_job(job_id, settings=settings)
    if not job or str(job.get("status") or "") != "completed":
        raise CustomSkillCorrectionError("a última execução ainda não terminou ou não está mais disponível")
    result = dict(job.get("result") or {})
    if not result.get("action_needed"):
        raise CustomSkillCorrectionError("a última validação não identificou necessidade de correção")
    if str(result.get("correction_status") or "") != "pending_approval":
        raise CustomSkillCorrectionError(
            str(result.get("correction_message") or "a correção não está aguardando aprovação")
        )

    skill = get_custom_skill(str(agent.get("skill_id") or ""))
    if not skill:
        raise CustomSkillCorrectionError("a Skill vinculada não existe mais")
    action = _structured_action(skill)
    target = resolve_target(str(agent.get("target") or ""), EnvironmentType.UNKNOWN, settings=settings)
    if not environment_allows_correction(target.environment):
        raise CustomSkillCorrectionError(
            f"ambiente {target.environment.value} não permite execução corretiva pelo Agente; somente proposta"
        )
    return {
        "agent_id": agent_id,
        "job_id": job_id,
        "skill_id": skill["id"],
        "skill_name": skill["name"],
        "target": target.reference,
        "resolved_host": target.host,
        "environment": target.environment.value,
        "ssh_port": target.port,
        "action": action,
        "condition": dict(result.get("condition") or {}),
    }


def execute_approved_agent_correction(
    agent_id: str,
    *,
    requested_by: str | None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    preview = correction_preview(agent_id, settings=settings)
    agent = get_agent(agent_id) or {}
    skill = get_custom_skill(str(preview["skill_id"])) or {}
    action = dict(preview["action"])
    condition = dict(skill.get("condition") or {})

    proposal = {
        "tool": action["tool"],
        "arguments": dict(action["arguments"]),
        "status": "proposed",
        "reason": "A condição configurada na Skill identificou necessidade de correção.",
    }
    condition_result = dict(preview.get("condition") or {})
    validation = dict(condition_result.get("validation") or {})
    review = review_corrections(
        {
            "status": "attention",
            "confidence": 100,
            "probable_cause": "A validação condicional da Skill indicou que a ação corretiva configurada é necessária.",
            "conclusion": str((condition.get("messages") or {}).get("failure") or "A condição de correção foi atendida."),
            "root_cause": {"source": "custom_skill_condition", "action_needed": True},
        },
        [proposal],
        [validation] if validation else [],
        settings=settings,
    )
    if not review.get("approved"):
        raise CustomSkillCorrectionError(
            "a segunda IA não aprovou a correção: " + str(review.get("reason") or review.get("status") or "revisão recusada")
        )

    approval_id = f"agent:{agent_id}:{preview['job_id']}"
    actions = [proposal]
    token = create_approval_token(
        approval_id,
        str(preview["target"]),
        actions,
        ssh_port=int(preview["ssh_port"]),
        settings=settings,
    )
    if not token:
        raise CustomSkillCorrectionError("APPROVAL_SECRET não configurado; não foi possível assinar a aprovação")
    verified = verify_approval_token(token, actions, settings=settings)
    if verified.get("investigation_id") != approval_id or verified.get("target") != preview["target"]:
        raise CustomSkillCorrectionError("a aprovação assinada não corresponde ao agente/alvo atual")

    target = resolve_target(str(preview["target"]), EnvironmentType.UNKNOWN, int(preview["ssh_port"]), settings=settings)
    if target.environment.value != preview["environment"] or not environment_allows_correction(target.environment):
        raise CustomSkillCorrectionError("a classificação do ambiente mudou; gere uma nova aprovação")

    executor = build_executor(target, settings=settings)
    try:
        executor.connect()
        if action["tool"] == "backup.mount_standard":
            execution = _execute_standard_mount(
                executor,
                target.environment,
                str(action["arguments"]["mount_point"]),
                settings,
            )
        else:
            execution = execute_tool(
                executor,
                target.environment,
                str(action["tool"]),
                dict(action["arguments"]),
                approved=True,
            )
            configured_post = str(condition.get("post_validation") or "").strip()
            if configured_post:
                post = _run_read_only(executor, configured_post, target.environment, settings)
                execution["post_validation"] = post
                execution["validated"] = execution.get("status") == "validated" and post["ok"]
                if not execution["validated"]:
                    execution["status"] = "failed"
    finally:
        executor.close()

    succeeded = str(execution.get("status") or "") == "validated" and bool(execution.get("validated", True))
    messages = dict(condition.get("messages") or {})
    if succeeded:
        if action["tool"] == "backup.mount_standard":
            correction_message = str(messages.get("success") or "Montagem executada com sucesso e confirmada pela pós-validação.")
        else:
            correction_message = str(messages.get("success") or "Correção executada com sucesso e confirmada pela pós-validação.")
        correction_status = "executed_success"
    else:
        correction_message = str(messages.get("failure") or "A correção foi executada, mas a pós-validação não confirmou o resultado esperado.")
        correction_status = "executed_failed"

    from app.services import jobs

    job = jobs.get_job(str(preview["job_id"]), settings=settings) or {}
    result = dict(job.get("result") or {})
    executed = dict(execution)
    executed["configured_action"] = action["configured_action"]
    executed["approval"] = {
        "approved_by": str(requested_by or "operador"),
        "reviewer_provider": review.get("provider"),
        "reviewer_model": review.get("model"),
        "review_confidence": review.get("confidence"),
        "token_digest": token_digest(token),
    }
    result.setdefault("executed_actions", []).append(executed)
    _remove_executed_pending(result, str(action["configured_action"]))
    result["correction_status"] = correction_status
    result["correction_message"] = correction_message
    result["summary"] = correction_message
    result["status"] = "healthy" if succeeded else "attention"
    job["result"] = result
    job["correction_completed_at"] = jobs._now()
    jobs._store(jobs._redis(settings), settings, str(preview["job_id"]), job)

    final_state = "completed_success" if succeeded else "completed_error"
    update_agent_runtime(
        agent_id,
        status=final_state,
        summary=correction_message,
        error="" if succeeded else str(execution.get("stderr") or "correção não confirmada"),
    )
    update_agent_history_result(
        agent_id,
        job_id=str(preview["job_id"]),
        status=final_state,
        summary=correction_message,
        error="" if succeeded else str(execution.get("stderr") or "correção não confirmada"),
        correction_status=correction_status,
        correction_message=correction_message,
    )
    record_run_detail(agent_id, job, result)

    return {
        "status": correction_status,
        "success": succeeded,
        "message": correction_message,
        "agent_id": agent_id,
        "job_id": preview["job_id"],
        "target": preview["target"],
        "environment": preview["environment"],
        "action": action,
        "execution": execution,
        "review": {
            "status": review.get("status"),
            "provider": review.get("provider"),
            "model": review.get("model"),
            "confidence": review.get("confidence"),
        },
    }
