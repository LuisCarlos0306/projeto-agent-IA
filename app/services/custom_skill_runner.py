from __future__ import annotations

from typing import Any

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.custom_skill_registry import get_custom_skill, validate_custom_command
from app.services.progress import report_progress
from app.services.redaction import redact_text
from app.services.runner import build_executor, resolve_target


_MAX_OUTPUT = 16000


def _clip(value: str) -> str:
    text = redact_text(str(value or ""))
    if len(text) <= _MAX_OUTPUT:
        return text
    return text[:_MAX_OUTPUT] + "\n...[saída truncada]"


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

    commands = [validate_custom_command(item) for item in skill.get("commands") or []]
    if not commands:
        raise ValueError("skill personalizada sem comandos executáveis")

    target = resolve_target(reference, environment, ssh_port, settings=settings)
    executor = build_executor(target, settings=settings)
    results: list[dict[str, Any]] = []

    report_progress(
        "custom_skill_started",
        detail=f"Executando {skill['name']} em {target.reference}.",
        percent=5,
        skill=f"custom:{skill_id}",
        host=target.host,
    )

    try:
        executor.connect()
        total = max(1, len(commands))
        for index, command in enumerate(commands, start=1):
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
                detail=f"Comando {index}/{total} concluído.",
                percent=min(95, 5 + int(index / total * 90)),
                skill=f"custom:{skill_id}",
                host=target.host,
            )

        failed = sum(1 for item in results if item["exit_code"] != 0)
        status = "healthy" if failed == 0 else "attention"
        summary = (
            f"Skill {skill['name']} concluída sem erros."
            if failed == 0
            else f"Skill {skill['name']} concluída com {failed} comando(s) retornando erro."
        )
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
            "mode": "read_only",
            "status": status,
            "target": target.reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "summary": summary,
            "commands": results,
            "executed_actions": [],
        }
    finally:
        executor.close()
