from __future__ import annotations

from datetime import datetime, timezone
import posixpath
import shlex
from typing import Any

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.command_catalog import validate_command
from app.services.progress import report_progress
from app.services.runner import build_executor, resolve_target


MOUNT_SCRIPT = "/db/backup/scripts/mount.sh"


def _safe_path(value: str, field: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field} é obrigatório")
    if any(char in raw for char in ("\x00", "\n", "\r")):
        raise ValueError(f"{field} contém caracteres inválidos")
    if not raw.startswith("/"):
        raise ValueError(f"{field} deve ser um caminho absoluto")
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/"):
        raise ValueError(f"{field} deve permanecer dentro de um caminho absoluto")
    return normalized


def _optional_path(value: str | None, field: str) -> str | None:
    raw = str(value or "").strip()
    return _safe_path(raw, field) if raw else None


def _is_inside(path: str, parent: str) -> bool:
    if parent == "/":
        return path.startswith("/")
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def _command(command: str) -> str:
    allowed, reason, _spec = validate_command(command)
    if not allowed:
        raise RuntimeError(f"comando interno da skill rejeitado: {reason}")
    return command


def _status(label: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"label": label, "status": status, "detail": detail, **extra}


def _parse_mount(stdout: str) -> dict[str, str] | None:
    line = next((item.strip() for item in stdout.splitlines() if item.strip()), "")
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
    rows = [line.strip() for line in stdout.splitlines() if line.strip()]
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
        "blocks_kb": int(parts[-5]) if parts[-5].isdigit() else None,
        "used_kb": int(parts[-4]) if parts[-4].isdigit() else None,
        "available_kb": available_kb,
        "use_percent": use_percent,
        "free_percent": max(0, 100 - use_percent),
        "mounted_on": parts[-1],
    }


def _parse_latest(stdout: str) -> dict[str, Any] | None:
    line = next((item.strip() for item in stdout.splitlines() if item.strip()), "")
    if not line:
        return None
    parts = line.split("|", 2)
    if len(parts) != 3:
        return None
    try:
        mtime = float(parts[0])
        size = int(parts[1])
    except ValueError:
        return None
    changed_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
    age_hours = max(0.0, (datetime.now(timezone.utc) - changed_at).total_seconds() / 3600)
    return {
        "path": parts[2],
        "size_bytes": size,
        "modified_at": changed_at.isoformat(),
        "age_hours": round(age_hours, 2),
    }


def _overall(checks: dict[str, dict[str, Any]]) -> str:
    statuses = [str(item.get("status") or "inconclusive") for item in checks.values()]
    if "critical" in statuses:
        return "critical"
    if "attention" in statuses:
        return "attention"
    if any(status == "healthy" for status in statuses):
        return "healthy"
    return "inconclusive"


def _latest_command(path: str) -> str:
    quoted = shlex.quote(path)
    return _command(
        f"find {quoted} -maxdepth 2 -type f -printf '%T@|%s|%p\\n' | sort -t'|' -k1,1nr | head -n 1"
    )


def _action_for_mount_failure() -> dict[str, Any]:
    return {
        "id": "execute_mount_script",
        "label": "Solicitar montagem",
        "command": MOUNT_SCRIPT,
        "risk": "approval_required",
        "enabled": False,
        "detail": "A execução do script permanece bloqueada até a etapa de aprovação operacional da skill.",
    }


def run_backup_validation(
    reference: str,
    *,
    mount_point: str,
    backup_path: str,
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
    mount_point = _safe_path(mount_point, "ponto de montagem")
    backup_path = _safe_path(backup_path, "diretório do backup")
    redundancy_path = _optional_path(redundancy_path, "diretório de redundância")
    if not _is_inside(backup_path, mount_point):
        raise ValueError("o diretório do backup deve estar dentro do ponto de montagem informado")

    min_free_percent = max(1, min(99, int(min_free_percent)))
    max_backup_age_hours = max(1, min(24 * 90, int(max_backup_age_hours)))
    retention_days = max(1, min(365, int(retention_days)))
    min_restore_points = max(1, min(500, int(min_restore_points)))

    target = resolve_target(reference, environment, ssh_port, settings=settings)
    executor = build_executor(target, settings=settings)
    checks: dict[str, dict[str, Any]] = {}

    report_progress(
        "skill_started",
        detail=f"Backup Validation iniciada para {target.reference}.",
        percent=5,
        skill="backup_validation",
        host=target.host,
    )

    try:
        executor.connect()
        report_progress(
            "skill_connected",
            detail=f"SSH conectado em {target.host}:{target.port}.",
            percent=12,
            skill="backup_validation",
            host=target.host,
        )

        q_mount = shlex.quote(mount_point)
        q_backup = shlex.quote(backup_path)
        mount_result = executor.run(
            _command(f"findmnt -rn -M {q_mount} -o SOURCE,TARGET,FSTYPE,OPTIONS"),
            target.environment,
            approved=False,
            timeout=20,
        )
        mount_info = _parse_mount(mount_result.stdout) if mount_result.exit_code == 0 else None
        if mount_info:
            checks["mount"] = _status("Montagem", "healthy", f"{mount_point} está montado.", **mount_info)
        else:
            checks["mount"] = _status(
                "Montagem",
                "critical",
                f"{mount_point} não está montado como ponto de montagem dedicado.",
                target=mount_point,
            )

        stat_result = executor.run(
            _command(f"stat -f -c '%T|%a|%s' {q_backup}"),
            target.environment,
            approved=False,
            timeout=20,
        )
        path_accessible = stat_result.exit_code == 0 and bool(stat_result.stdout.strip())
        if path_accessible:
            stat_parts = stat_result.stdout.strip().split("|", 2)
            fs_type = stat_parts[0] if stat_parts else "desconhecido"
            fs_status = "healthy" if mount_info else "critical"
            detail = (
                f"Filesystem acessível em {backup_path} ({fs_type})."
                if mount_info
                else f"O caminho {backup_path} responde, mas {mount_point} está desmontado; a skill não aceitará esse conteúdo como backup válido."
            )
            checks["filesystem"] = _status("Filesystem", fs_status, detail, fstype=fs_type, path=backup_path)
        else:
            checks["filesystem"] = _status(
                "Filesystem",
                "critical",
                f"Não foi possível acessar {backup_path}.",
                path=backup_path,
                stderr=stat_result.stderr[-1000:],
            )

        if mount_info:
            df_result = executor.run(
                _command(f"df -P {q_mount}"),
                target.environment,
                approved=False,
                timeout=20,
            )
            df_info = _parse_df(df_result.stdout) if df_result.exit_code == 0 else None
            if df_info:
                free_percent = int(df_info["free_percent"])
                space_status = "healthy" if free_percent >= min_free_percent else "attention"
                checks["space"] = _status(
                    "Espaço livre",
                    space_status,
                    f"{free_percent}% livre; mínimo configurado: {min_free_percent}%.",
                    threshold_percent=min_free_percent,
                    **df_info,
                )
            else:
                checks["space"] = _status("Espaço livre", "inconclusive", "Não foi possível interpretar a saída do df.")
        else:
            checks["space"] = _status(
                "Espaço livre",
                "inconclusive",
                "Validação ignorada para evitar medir o filesystem local com a unidade desmontada.",
            )

        if not mount_info:
            checks["retention"] = _status(
                "Retenção",
                "inconclusive",
                "Validação não executada porque a unidade de backup está desmontada.",
            )
            checks["last_backup"] = _status(
                "Último backup",
                "inconclusive",
                "Validação não executada porque a unidade de backup está desmontada.",
            )
            checks["redundancy"] = _status(
                "Redundância",
                "inconclusive",
                "Validação não executada nesta etapa porque a origem principal está desmontada.",
            )
        elif not path_accessible:
            checks["retention"] = _status("Retenção", "inconclusive", "Diretório principal do backup não está acessível.")
            checks["last_backup"] = _status("Último backup", "critical", "Diretório principal do backup não está acessível.")
            checks["redundancy"] = _status(
                "Redundância",
                "inconclusive",
                "Validação adiada enquanto o diretório principal do backup estiver inacessível.",
            )
        else:
            recent_count_result = executor.run(
                _command(
                    f"find {q_backup} -maxdepth 2 -type f -newermt '-{retention_days} days' -printf '.' | wc -c"
                ),
                target.environment,
                approved=False,
                timeout=30,
            )
            try:
                recent_count = int(recent_count_result.stdout.strip()) if recent_count_result.exit_code == 0 else 0
            except ValueError:
                recent_count = 0
            retention_status = "healthy" if recent_count >= min_restore_points else "attention"
            checks["retention"] = _status(
                "Retenção",
                retention_status,
                (
                    f"{recent_count} arquivo(s) recente(s) encontrado(s) nos últimos {retention_days} dia(s); "
                    f"mínimo configurado: {min_restore_points}."
                ),
                recent_files=recent_count,
                retention_days=retention_days,
                minimum_expected=min_restore_points,
                note="Validação genérica por quantidade de arquivos recentes; políticas por posição podem ser especializadas por cliente.",
            )

            latest_result = executor.run(
                _latest_command(backup_path),
                target.environment,
                approved=False,
                timeout=30,
            )
            latest = _parse_latest(latest_result.stdout) if latest_result.exit_code == 0 else None
            if latest:
                age = float(latest["age_hours"])
                latest_status = "healthy" if age <= max_backup_age_hours else "critical"
                checks["last_backup"] = _status(
                    "Último backup",
                    latest_status,
                    f"Último arquivo possui {age:.1f}h; limite configurado: {max_backup_age_hours}h.",
                    maximum_age_hours=max_backup_age_hours,
                    **latest,
                )
            else:
                checks["last_backup"] = _status(
                    "Último backup",
                    "critical",
                    f"Nenhum arquivo de backup foi encontrado em {backup_path}.",
                    path=backup_path,
                )

            if redundancy_path:
                redundancy_result = executor.run(
                    _latest_command(redundancy_path),
                    target.environment,
                    approved=False,
                    timeout=30,
                )
                redundancy = _parse_latest(redundancy_result.stdout) if redundancy_result.exit_code == 0 else None
                if redundancy:
                    age = float(redundancy["age_hours"])
                    redundancy_status = "healthy" if age <= max_backup_age_hours else "attention"
                    checks["redundancy"] = _status(
                        "Redundância",
                        redundancy_status,
                        f"Cópia redundante mais recente possui {age:.1f}h.",
                        maximum_age_hours=max_backup_age_hours,
                        **redundancy,
                    )
                else:
                    checks["redundancy"] = _status(
                        "Redundância",
                        "attention",
                        f"Nenhum arquivo foi encontrado em {redundancy_path}.",
                        path=redundancy_path,
                    )
            else:
                checks["redundancy"] = _status(
                    "Redundância",
                    "inconclusive",
                    "Diretório de redundância não informado para esta execução.",
                )

        overall = _overall(checks)
        action_available = _action_for_mount_failure() if checks["mount"]["status"] == "critical" else None
        result = {
            "skill": "backup_validation",
            "version": "1.1.0",
            "status": overall,
            "target": target.reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "mount_point": mount_point,
            "backup_path": backup_path,
            "redundancy_path": redundancy_path,
            "checks": checks,
            "action_available": action_available,
            "executed_actions": [],
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        report_progress(
            "skill_completed",
            status="completed",
            detail=f"Backup Validation concluída com status {overall}.",
            percent=100,
            skill="backup_validation",
            host=target.host,
        )
        return result
    finally:
        executor.close()
