from __future__ import annotations

import shlex
from typing import Any

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.backup_storage_registry import DEFAULT_MOUNT_SCRIPT, get_mapping
from app.services.backup_validation import run_backup_validation as run_discovered_backup_validation
from app.services.command_catalog import validate_command
from app.services.progress import report_progress
from app.services.runner import build_executor, resolve_target


def _command(command: str) -> str:
    allowed, reason, _spec = validate_command(command)
    if not allowed:
        raise RuntimeError(f"comando interno da skill rejeitado: {reason}")
    return command


def _parse_mount(stdout: str) -> dict[str, str] | None:
    line = next((row.strip() for row in stdout.splitlines() if row.strip()), "")
    if not line:
        return None
    parts = line.split(None, 3)
    return {
        "source": parts[0] if len(parts) > 0 else "",
        "target": parts[1] if len(parts) > 1 else "",
        "fstype": parts[2] if len(parts) > 2 else "",
        "options": parts[3] if len(parts) > 3 else "",
    }


def _parse_df(stdout: str) -> dict[str, Any] | None:
    rows = [row.strip() for row in stdout.splitlines() if row.strip()]
    if len(rows) < 2:
        return None
    parts = rows[-1].split()
    if len(parts) < 6:
        return None
    try:
        use_percent = int(parts[-2].rstrip("%"))
        available_kb = int(parts[-3])
    except ValueError:
        return None
    return {
        "filesystem": " ".join(parts[:-5]),
        "available_kb": available_kb,
        "use_percent": use_percent,
        "free_percent": max(0, 100 - use_percent),
        "mounted_on": parts[-1],
    }


def _overall(units: list[dict[str, Any]]) -> str:
    states = [str(row.get("status") or "inconclusive") for row in units]
    if "critical" in states:
        return "critical"
    if "attention" in states:
        return "attention"
    if states and all(state == "healthy" for state in states):
        return "healthy"
    return "inconclusive"


def _validate_mapping(reference: str, mapping: dict[str, Any], *, environment: EnvironmentType, ssh_port: int | None, settings: Settings) -> dict[str, Any]:
    target = resolve_target(reference, environment, ssh_port, settings=settings)
    if mapping is None:
        mapping = get_mapping(target.host)
    if mapping is None:
        raise ValueError(f"servidor {reference} ainda não possui unidades mapeadas na Backup Validation")

    executor = build_executor(target, settings=settings)
    results: list[dict[str, Any]] = []
    missing: list[str] = []

    report_progress(
        "skill_started",
        detail=f"Validando {len(mapping['units'])} unidade(s) mapeada(s) para {target.reference}.",
        percent=5,
        skill="backup_validation",
        host=target.host,
    )

    try:
        executor.connect()
        total = max(1, len(mapping["units"]))
        for index, unit in enumerate(mapping["units"], start=1):
            mount_point = str(unit["mount_point"])
            quoted = shlex.quote(mount_point)
            mount_result = executor.run(
                _command(f"findmnt -rn -M {quoted} -o SOURCE,TARGET,FSTYPE,OPTIONS"),
                target.environment,
                approved=False,
                timeout=20,
            )
            mount = _parse_mount(mount_result.stdout) if mount_result.exit_code == 0 else None
            row: dict[str, Any] = {
                "label": unit["label"],
                "role": unit["role"],
                "mount_point": mount_point,
                "min_free_percent": unit["min_free_percent"],
            }
            if not mount:
                row.update(
                    status="critical",
                    mounted=False,
                    detail=f"{mount_point} não está montado.",
                )
                missing.append(mount_point)
                results.append(row)
                continue

            df_result = executor.run(
                _command(f"df -P {quoted}"),
                target.environment,
                approved=False,
                timeout=20,
            )
            df_info = _parse_df(df_result.stdout) if df_result.exit_code == 0 else None
            if not df_info:
                row.update(
                    status="inconclusive",
                    mounted=True,
                    source=mount.get("source"),
                    fstype=mount.get("fstype"),
                    detail=f"{mount_point} está montado, mas não foi possível interpretar o espaço livre.",
                )
            else:
                free_percent = int(df_info["free_percent"])
                status = "healthy" if free_percent >= int(unit["min_free_percent"]) else "attention"
                row.update(
                    status=status,
                    mounted=True,
                    source=mount.get("source"),
                    fstype=mount.get("fstype"),
                    free_percent=free_percent,
                    use_percent=df_info["use_percent"],
                    detail=(
                        f"{mount_point} montado e acessível; {free_percent}% livre."
                        if status == "healthy"
                        else f"{mount_point} montado, porém com apenas {free_percent}% livre; mínimo mapeado: {unit['min_free_percent']}%."
                    ),
                )
            results.append(row)
            report_progress(
                "skill_unit_checked",
                detail=f"Unidade {mount_point} validada.",
                percent=min(92, 10 + int(index / total * 80)),
                skill="backup_validation",
                host=target.host,
            )

        status = _overall(results)
        action_required = bool(missing)
        if action_required:
            operator_message = "Atuação necessária. Solicite a validação da montagem antes de qualquer ação operacional."
            action = {
                "id": "request_mount_validation",
                "label": "Solicitar validação da montagem",
                "command": mapping.get("mount_script") or DEFAULT_MOUNT_SCRIPT,
                "risk": "approval_required",
                "enabled": False,
                "targets": missing,
                "detail": (
                    f"Unidade(s) não montada(s): {', '.join(missing)}. "
                    "Neste primeiro momento o Agent apenas solicita validação; o script não é executado automaticamente."
                ),
            }
        else:
            operator_message = "Nenhuma necessidade de atuação. Todas as unidades mapeadas estão montadas e acessíveis."
            action = None

        result = {
            "skill": "backup_validation",
            "version": "1.3.0",
            "mode": "mapped_storage",
            "status": status,
            "target": target.reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "mapping": {
                "target": mapping["target"],
                "mount_script": mapping.get("mount_script") or DEFAULT_MOUNT_SCRIPT,
                "units_count": len(mapping["units"]),
            },
            "units": results,
            "action_required": action_required,
            "operator_message": operator_message,
            "action_available": action,
            "executed_actions": [],
        }
        report_progress(
            "skill_completed",
            status="completed",
            detail=operator_message,
            percent=100,
            skill="backup_validation",
            host=target.host,
        )
        return result
    finally:
        executor.close()


def run_backup_validation(
    reference: str,
    *,
    backup_path: str = "",
    mount_point: str | None = None,
    redundancy_path: str | None = None,
    environment: EnvironmentType = EnvironmentType.UNKNOWN,
    ssh_port: int | None = None,
    min_free_percent: int = 20,
    max_backup_age_hours: int = 30,
    retention_days: int = 7,
    min_restore_points: int = 1,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    mapping = get_mapping(reference)
    if mapping is not None or not str(backup_path or "").strip():
        return _validate_mapping(
            reference,
            mapping,
            environment=environment,
            ssh_port=ssh_port,
            settings=settings,
        )

    # Compatibilidade para chamadas antigas: se ainda houver backup_path e o
    # servidor não estiver mapeado, preserva a descoberta automática da v1.2.
    return run_discovered_backup_validation(
        reference,
        backup_path=backup_path,
        mount_point=mount_point,
        redundancy_path=redundancy_path,
        environment=environment,
        ssh_port=ssh_port,
        min_free_percent=min_free_percent,
        max_backup_age_hours=max_backup_age_hours,
        retention_days=retention_days,
        min_restore_points=min_restore_points,
        settings=settings,
    )


def install_mapped_backup_validation() -> None:
    """Faz o worker usar o modo mapeado sem alterar o motor genérico de jobs."""
    from app.services import jobs

    jobs.run_backup_validation = run_backup_validation
