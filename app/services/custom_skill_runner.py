from __future__ import annotations

from typing import Any

from app.core.policies import EnvironmentType, classify_command, evaluate_action
from app.core.settings import Settings, get_settings
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


def _pending_command(command: str, environment: EnvironmentType) -> dict[str, Any]:
    action = classify_command(command)
    decision = evaluate_action(action, environment)
    if decision.allowed:
        return {
            "command": command,
            "risk": "approval_required",
            "enabled": False,
            "status": "pending_approval",
            "policy_code": decision.policy_code,
            "reason": "Comando cadastrado na Skill, mas fora do conjunto comprovadamente somente leitura para execução automática.",
        }
    return {
        "command": command,
        "risk": "policy_blocked",
        "enabled": False,
        "status": "blocked_by_policy",
        "policy_code": decision.policy_code,
        "reason": decision.reason,
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
    configured_commands = [
        validate_custom_command(item, mode)
        for item in skill.get("commands") or []
    ]
    scripts = [validate_script_path(item) for item in skill.get("scripts") or []]
    if not configured_commands and not scripts:
        raise ValueError("skill personalizada sem comandos ou scripts configurados")

    target = resolve_target(reference, environment, ssh_port, settings=settings)
    executor = build_executor(target, settings=settings)
    results: list[dict[str, Any]] = []
    safe_commands: list[str] = []
    pending_commands: list[dict[str, Any]] = []

    for command in configured_commands:
        safe = _read_only_command(command)
        if safe is not None:
            safe_commands.append(safe)
        else:
            pending_commands.append(_pending_command(command, target.environment))

    report_progress(
        "custom_skill_started",
        detail=f"Executando {skill['name']} em {target.reference}.",
        percent=5,
        skill=f"custom:{skill_id}",
        host=target.host,
    )

    try:
        if safe_commands:
            executor.connect()
            total = max(1, len(safe_commands))
            for index, command in enumerate(safe_commands, start=1):
                result = executor.run(
                    command,
                    target.environment,
                    approved=False,
                    timeout=min(120, int(getattr(settings, "ssh_command_timeout", 60) or 60)),
                )
                results.append(
                    {
                        "command": command,
                        "exit_code": int(result.exit_code),
                        "stdout": _clip(result.stdout),
                        "stderr": _clip(result.stderr),
                        "status": "ok" if int(result.exit_code) == 0 else "error",
                    }
                )
                report_progress(
                    "custom_skill_command",
                    detail=f"Comando seguro {index}/{total} concluído.",
                    percent=min(90, 5 + int(index / total * 80)),
                    skill=f"custom:{skill_id}",
                    host=target.host,
                )

        failed = sum(1 for item in results if item["exit_code"] != 0)
        pending_scripts = [
            {
                "path": script,
                "risk": "approval_required",
                "enabled": False,
                "status": "pending_approval",
                "reason": "Script cadastrado na Skill e protegido por aprovação operacional.",
            }
            for script in scripts
        ]
        approval_pending = [
            item for item in pending_commands if item.get("status") == "pending_approval"
        ]
        blocked_commands = [
            item for item in pending_commands if item.get("status") == "blocked_by_policy"
        ]
        pending_total = len(approval_pending) + len(pending_scripts)

        if failed:
            status = "attention"
            summary = f"Skill {skill['name']} concluída com {failed} comando(s) seguro(s) retornando erro."
        elif pending_total or blocked_commands:
            status = "attention"
            details: list[str] = []
            if pending_total:
                details.append(f"{pending_total} ação(ões) aguardam aprovação")
            if blocked_commands:
                details.append(f"{len(blocked_commands)} comando(s) estão bloqueados pela política do ambiente")
            summary = f"Diagnóstico da Skill {skill['name']} concluído. " + "; ".join(details) + "."
        else:
            status = "healthy"
            summary = f"Skill {skill['name']} concluída sem erros."

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
            "pending_commands": pending_commands,
            "scripts": pending_scripts,
            "approval_required": bool(approval_pending or pending_scripts),
            "policy_blocked": bool(blocked_commands),
            "executed_actions": [],
        }
    finally:
        executor.close()
