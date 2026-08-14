from __future__ import annotations

from typing import Any

from app.core.policies import EnvironmentType, classify_command, evaluate_action
from app.core.settings import Settings, get_settings
from app.services.custom_skill_condition import build_condition_result
from app.services.custom_skill_registry import get_custom_skill, validate_custom_command, validate_script_path
from app.services.progress import report_progress
from app.services.redaction import redact_text
from app.services.runner import build_executor, resolve_target


_MAX_OUTPUT = 16000


def _clip(value: str) -> str:
    text = redact_text(str(value or ""))
    if len(text) <= _MAX_OUTPUT:
        return text
    return text[:_MAX_OUTPUT] + "\n...[saída truncada]"


def _read_only_command(command: str) -> str | None:
    try:
        return validate_custom_command(command, "read_only")
    except ValueError:
        return None


def _pending_command(command: str, environment: EnvironmentType, *, conditional: bool = False) -> dict[str, Any]:
    action = classify_command(command)
    decision = evaluate_action(action, environment)
    prefix = "A condição da Skill identificou necessidade de atuação. " if conditional else ""
    if decision.allowed:
        return {
            "command": command,
            "risk": "approval_required",
            "enabled": False,
            "status": "pending_approval",
            "policy_code": decision.policy_code,
            "reason": prefix + "A ação corretiva exige aprovação operacional antes da execução.",
            "conditional": conditional,
        }
    return {
        "command": command,
        "risk": "policy_blocked",
        "enabled": False,
        "status": "blocked_by_policy",
        "policy_code": decision.policy_code,
        "reason": prefix + decision.reason,
        "conditional": conditional,
    }


def _pending_script(path: str, *, conditional: bool = False) -> dict[str, Any]:
    prefix = "A condição da Skill identificou necessidade de atuação. " if conditional else ""
    return {
        "path": path,
        "risk": "approval_required",
        "enabled": False,
        "status": "pending_approval",
        "reason": prefix + "O script está protegido por aprovação operacional.",
        "conditional": conditional,
    }


def _run_read_only(executor: Any, command: str, target: Any, settings: Settings) -> dict[str, Any]:
    result = executor.run(
        command,
        target.environment,
        approved=False,
        timeout=min(120, int(getattr(settings, "ssh_command_timeout", 60) or 60)),
    )
    return {
        "command": command,
        "exit_code": int(result.exit_code),
        "stdout": _clip(result.stdout),
        "stderr": _clip(result.stderr),
        "status": "ok" if int(result.exit_code) == 0 else "error",
    }


def run_custom_skill(
    skill_id: str,
    reference: str,
    *,
    environment: EnvironmentType = EnvironmentType.UNKNOWN,
    ssh_port: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    skill = get_custom_skill(skill_id)
    if skill is None:
        raise LookupError("skill personalizada não encontrada")

    mode = str(skill.get("mode") or "read_only")
    configured_commands = [validate_custom_command(item, mode) for item in skill.get("commands") or []]
    scripts = [validate_script_path(item) for item in skill.get("scripts") or []]
    condition = dict(skill.get("condition") or {}) if skill.get("condition") else None
    if not configured_commands and not scripts and not condition:
        raise ValueError("skill personalizada sem ações configuradas")

    target = resolve_target(reference, environment, ssh_port, settings=settings)
    executor = build_executor(target, settings=settings)
    results: list[dict[str, Any]] = []
    safe_commands: list[str] = []
    pending_commands: list[dict[str, Any]] = []
    pending_scripts: list[dict[str, Any]] = []
    condition_result: dict[str, Any] | None = None
    correction_status = "not_needed"
    correction_message = "Nenhuma correção foi necessária nesta validação."

    for command in configured_commands:
        safe = _read_only_command(command)
        if safe is not None:
            safe_commands.append(safe)
        else:
            pending_commands.append(_pending_command(command, target.environment))
    pending_scripts.extend(_pending_script(script) for script in scripts)

    report_progress(
        "custom_skill_started",
        detail=f"Executando {skill['name']} em {target.reference}.",
        percent=5,
        skill=f"custom:{skill_id}",
        host=target.host,
    )

    try:
        if condition or safe_commands:
            executor.connect()

        if condition:
            validation_command = validate_custom_command(str(condition.get("validation") or ""), "read_only")
            report_progress(
                "custom_skill_validation",
                detail="Executando validação da condição.",
                percent=12,
                skill=f"custom:{skill_id}",
                host=target.host,
            )
            validation = _run_read_only(executor, validation_command, target, settings)
            condition_result = build_condition_result(condition, validation)
            messages = dict(condition.get("messages") or {})
            if condition_result["action_needed"]:
                action = dict(condition.get("action") or {})
                action_type = str(action.get("type") or "command")
                action_value = str(action.get("value") or "")
                if action_type == "script":
                    pending_scripts.append(_pending_script(validate_script_path(action_value), conditional=True))
                else:
                    pending_commands.append(_pending_command(validate_custom_command(action_value, mode), target.environment, conditional=True))
                correction_status = "pending_approval"
                correction_message = "A validação identificou necessidade de correção; a ação está protegida por aprovação operacional."
                report_progress(
                    "custom_skill_condition_matched",
                    detail="Condição atendida: ação corretiva necessária.",
                    percent=28,
                    skill=f"custom:{skill_id}",
                    host=target.host,
                )
            else:
                correction_status = "not_needed"
                correction_message = str(messages.get("no_action") or "Validação concluída. Nenhuma ação necessária.")
                report_progress(
                    "custom_skill_condition_clear",
                    detail=correction_message,
                    percent=28,
                    skill=f"custom:{skill_id}",
                    host=target.host,
                )

        if safe_commands:
            total = max(1, len(safe_commands))
            for index, command in enumerate(safe_commands, start=1):
                row = _run_read_only(executor, command, target, settings)
                results.append(row)
                report_progress(
                    "custom_skill_command",
                    detail=f"Comando seguro {index}/{total} concluído.",
                    percent=min(88, 30 + int(index / total * 55)),
                    skill=f"custom:{skill_id}",
                    host=target.host,
                )

        failed = sum(1 for item in results if item["exit_code"] != 0)
        approval_pending = [item for item in pending_commands if item.get("status") == "pending_approval"]
        approval_scripts = [item for item in pending_scripts if item.get("status") == "pending_approval"]
        blocked_commands = [item for item in pending_commands if item.get("status") == "blocked_by_policy"]
        pending_total = len(approval_pending) + len(approval_scripts)
        action_needed = bool(condition_result and condition_result.get("action_needed"))

        if failed:
            status = "attention"
            summary = f"Skill {skill['name']} concluída com {failed} comando(s) de leitura retornando erro."
        elif action_needed:
            status = "attention"
            if blocked_commands and not pending_total:
                correction_status = "blocked"
                correction_message = "A correção foi identificada, mas está bloqueada pela política do ambiente."
                summary = f"Validação da Skill {skill['name']} identificou necessidade de correção, bloqueada pela política do ambiente."
            else:
                summary = f"Validação da Skill {skill['name']} identificou necessidade de ação corretiva."
        elif pending_total or blocked_commands:
            status = "attention"
            details: list[str] = []
            if pending_total:
                details.append(f"{pending_total} ação(ões) adicionais aguardam aprovação")
            if blocked_commands:
                details.append(f"{len(blocked_commands)} comando(s) adicionais estão bloqueados pela política")
            summary = f"Diagnóstico da Skill {skill['name']} concluído. " + "; ".join(details) + "."
        elif condition_result:
            status = "healthy"
            summary = correction_message
        else:
            status = "healthy"
            summary = f"Skill {skill['name']} concluída sem erros. Nenhuma ação corretiva foi necessária."
            correction_message = "Validação concluída. Nenhuma ação necessária."

        report_progress(
            "custom_skill_completed",
            status="completed",
            detail=summary,
            percent=100,
            skill=f"custom:{skill_id}",
            host=target.host,
        )
        return {
            "skill": f"custom:{skill_id}",
            "skill_id": skill_id,
            "name": skill["name"],
            "mode": mode,
            "status": status,
            "target": target.reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "summary": summary,
            "commands": results,
            "condition": condition_result,
            "action_needed": action_needed,
            "post_validation": condition.get("post_validation") if condition else None,
            "correction_status": correction_status,
            "correction_message": correction_message,
            "pending_commands": pending_commands,
            "scripts": pending_scripts,
            "approval_required": bool(approval_pending or approval_scripts),
            "policy_blocked": bool(blocked_commands),
            "executed_actions": [],
        }
    finally:
        executor.close()
