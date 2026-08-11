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
REMOTE_FS = {"nfs", "nfs4", "cifs", "smb3", "sshfs", "fuse.sshfs", "glusterfs", "ceph", "davfs"}
PSEUDO_FS = {
    "proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "cgroup", "cgroup2", "overlay", "squashfs",
    "nsfs", "securityfs", "tracefs", "debugfs", "pstore", "bpf", "hugetlbfs", "mqueue", "autofs",
    "rpc_pipefs", "fusectl", "configfs", "efivarfs", "binfmt_misc", "selinuxfs",
}
REDUNDANCY_HINTS = (
    "backup", "bkp", "nas", "storage", "externo", "external", "hd", "cifs", "nfs", "redund", "red1",
    "red2", "2cs", "backup_check", "backup_storage", "backup_nas",
)


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


def _parse_mount_line(line: str) -> dict[str, str] | None:
    parts = line.strip().split(None, 2)
    if len(parts) < 2:
        return None
    return {
        "source": parts[0],
        "target": parts[1],
        "fstype": parts[2] if len(parts) > 2 else "",
    }


def _parse_mounts(stdout: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in stdout.splitlines():
        parsed = _parse_mount_line(line)
        if parsed:
            rows.append(parsed)
    return rows


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


def _latest_command(path: str, *, maxdepth: int = 2) -> str:
    quoted = shlex.quote(path)
    depth = max(1, min(8, int(maxdepth)))
    return _command(
        f"find {quoted} -maxdepth {depth} -type f -printf '%T@|%s|%p\\n' | sort -t'|' -k1,1nr | head -n 1"
    )


def _action_for_mount_failure(targets: list[str]) -> dict[str, Any]:
    unique = list(dict.fromkeys(item for item in targets if item))
    detail = "A execução do script permanece bloqueada até a etapa de aprovação operacional da skill."
    if unique:
        detail = f"Unidade(s) que precisam de montagem: {', '.join(unique)}. {detail}"
    return {
        "id": "execute_mount_script",
        "label": "Solicitar montagem",
        "command": MOUNT_SCRIPT,
        "risk": "approval_required",
        "enabled": False,
        "detail": detail,
    }


def _is_remote(entry: dict[str, str]) -> bool:
    fstype = entry.get("fstype", "").casefold()
    source = entry.get("source", "")
    return fstype in REMOTE_FS or source.startswith("//") or (":" in source and not source.startswith("/dev/"))


def _redundancy_score(entry: dict[str, str]) -> int:
    target = entry.get("target", "").casefold()
    source = entry.get("source", "").casefold()
    fstype = entry.get("fstype", "").casefold()
    if not target or target == "/" or fstype in PSEUDO_FS:
        return -1000
    score = 0
    if _is_remote(entry):
        score += 100
    if target.startswith(("/mnt/", "/media/", "/backup/")):
        score += 20
    for hint in REDUNDANCY_HINTS:
        if hint in target:
            score += 18
        if hint in source:
            score += 8
    return score


def _discover_storage_topology(executor: Any, environment: EnvironmentType, backup_path: str, max_backup_age_hours: int) -> dict[str, Any]:
    mounted_result = executor.run(
        _command("findmnt -rn -o SOURCE,TARGET,FSTYPE"),
        environment,
        approved=False,
        timeout=20,
    )
    mounted = _parse_mounts(mounted_result.stdout) if mounted_result.exit_code == 0 else []

    configured_result = executor.run(
        _command("findmnt -s -rn -o SOURCE,TARGET,FSTYPE"),
        environment,
        approved=False,
        timeout=20,
    )
    configured = _parse_mounts(configured_result.stdout) if configured_result.exit_code == 0 else []

    q_backup = shlex.quote(backup_path)
    actual_result = executor.run(
        _command(f"findmnt -rn -T {q_backup} -o SOURCE,TARGET,FSTYPE"),
        environment,
        approved=False,
        timeout=20,
    )
    actual_rows = _parse_mounts(actual_result.stdout) if actual_result.exit_code == 0 else []
    actual = actual_rows[0] if actual_rows else None

    mounted_by_target = {item["target"]: item for item in mounted}
    configured_ancestors = sorted(
        [item for item in configured if item.get("target") and _is_inside(backup_path, item["target"])],
        key=lambda item: len(item["target"]),
        reverse=True,
    )
    expected = next((item for item in configured_ancestors if item["target"] != "/"), None)

    primary_state = "mounted"
    underlay = None
    if expected and expected["target"] not in mounted_by_target:
        primary = expected
        primary_state = "configured_unmounted"
        underlay = actual
    else:
        primary = actual or expected
        if primary and primary.get("target") not in mounted_by_target:
            primary_state = "configured_unmounted"

    primary_target = primary.get("target") if primary else None

    mounted_candidates: list[dict[str, Any]] = []
    for item in mounted:
        if item.get("target") == primary_target:
            continue
        score = _redundancy_score(item)
        if score < 20:
            continue
        candidate: dict[str, Any] = {**item, "state": "mounted", "score": score}
        mounted_candidates.append(candidate)

    mounted_candidates.sort(key=lambda item: int(item["score"]), reverse=True)
    inspected: list[dict[str, Any]] = []
    for candidate in mounted_candidates[:5]:
        latest_result = executor.run(
            _latest_command(candidate["target"], maxdepth=5),
            environment,
            approved=False,
            timeout=30,
        )
        latest = _parse_latest(latest_result.stdout) if latest_result.exit_code == 0 else None
        row = dict(candidate)
        row["latest"] = latest
        row["rank"] = int(row["score"]) + (30 if latest else 0)
        if latest and float(latest["age_hours"]) <= max_backup_age_hours:
            row["rank"] += 20
        inspected.append(row)

    configured_unmounted: list[dict[str, Any]] = []
    for item in configured:
        if item.get("target") in mounted_by_target or item.get("target") == primary_target:
            continue
        score = _redundancy_score(item)
        if score < 20:
            continue
        configured_unmounted.append({**item, "state": "configured_unmounted", "score": score, "rank": score})
    configured_unmounted.sort(key=lambda item: int(item["rank"]), reverse=True)

    selected_redundancy: dict[str, Any] | None = None
    if inspected:
        selected_redundancy = max(inspected, key=lambda item: int(item["rank"]))
    elif configured_unmounted:
        selected_redundancy = configured_unmounted[0]

    return {
        "primary": {**(primary or {}), "state": primary_state} if primary else None,
        "underlay": underlay,
        "redundancy": selected_redundancy,
        "redundancy_candidates": inspected,
        "configured_unmounted": configured_unmounted,
        "mounted_filesystems": len(mounted),
        "configured_filesystems": len(configured),
        "method": "findmnt -T + topologia montada/configurada",
    }


def run_backup_validation(
    reference: str,
    *,
    backup_path: str,
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
    """Valida backup descobrindo automaticamente o mount principal e a redundância.

    ``mount_point`` e ``redundancy_path`` são mantidos apenas por compatibilidade de API
    com versões anteriores. A seleção operacional é sempre feita pela descoberta do
    servidor a partir de ``backup_path``.
    """
    del mount_point, redundancy_path
    settings = settings or get_settings()
    backup_path = _safe_path(backup_path, "diretório do backup")

    min_free_percent = max(1, min(99, int(min_free_percent)))
    max_backup_age_hours = max(1, min(24 * 90, int(max_backup_age_hours)))
    retention_days = max(1, min(365, int(retention_days)))
    min_restore_points = max(1, min(500, int(min_restore_points)))

    target = resolve_target(reference, environment, ssh_port, settings=settings)
    executor = build_executor(target, settings=settings)
    checks: dict[str, dict[str, Any]] = {}

    report_progress(
        "skill_started",
        detail=f"Backup Validation iniciada para {target.reference}; descobrindo topologia de storage.",
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

        discovery = _discover_storage_topology(executor, target.environment, backup_path, max_backup_age_hours)
        primary = discovery.get("primary") or {}
        primary_target = str(primary.get("target") or "")
        primary_mounted = primary.get("state") == "mounted" and bool(primary_target)

        report_progress(
            "skill_storage_discovered",
            detail=(
                f"Filesystem principal detectado em {primary_target}."
                if primary_target
                else "Não foi possível determinar o filesystem principal."
            ),
            percent=28,
            skill="backup_validation",
            host=target.host,
        )

        if not primary:
            checks["mount"] = _status(
                "Montagem principal",
                "critical",
                f"Não foi possível descobrir qual filesystem sustenta {backup_path}.",
                path=backup_path,
            )
        elif primary_mounted:
            checks["mount"] = _status(
                "Montagem principal",
                "healthy",
                (
                    f"Detectado automaticamente: {primary_target} ({primary.get('fstype') or 'tipo desconhecido'}) "
                    f"a partir de {primary.get('source') or 'origem desconhecida'}."
                ),
                **primary,
            )
        else:
            underlay = discovery.get("underlay") or {}
            fallback = underlay.get("target")
            detail = f"{primary_target} está configurado para atender {backup_path}, mas não está montado."
            if fallback:
                detail += f" Sem a montagem, o caminho cairia no filesystem {fallback}; a Skill não aceita esse conteúdo como backup válido."
            checks["mount"] = _status("Montagem principal", "critical", detail, **primary)

        q_backup = shlex.quote(backup_path)
        path_accessible = False
        if primary_mounted:
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
                checks["filesystem"] = _status(
                    "Filesystem",
                    "healthy",
                    f"Diretório {backup_path} acessível no filesystem detectado {primary_target} ({fs_type}).",
                    fstype=fs_type,
                    path=backup_path,
                    mount_point=primary_target,
                )
            else:
                checks["filesystem"] = _status(
                    "Filesystem",
                    "critical",
                    f"O mount {primary_target} está ativo, mas não foi possível acessar {backup_path}.",
                    path=backup_path,
                    mount_point=primary_target,
                    stderr=stat_result.stderr[-1000:],
                )
        else:
            checks["filesystem"] = _status(
                "Filesystem",
                "critical" if primary else "inconclusive",
                "Acesso ao diretório não foi testado para evitar validar o filesystem local por baixo de uma unidade desmontada.",
                path=backup_path,
            )

        if primary_mounted:
            df_result = executor.run(
                _command(f"df -P {shlex.quote(primary_target)}"),
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
                    f"{free_percent}% livre em {primary_target}; mínimo configurado: {min_free_percent}%.",
                    threshold_percent=min_free_percent,
                    **df_info,
                )
            else:
                checks["space"] = _status("Espaço livre", "inconclusive", "Não foi possível interpretar a saída do df.")
        else:
            checks["space"] = _status(
                "Espaço livre",
                "inconclusive",
                "Validação ignorada porque o filesystem principal detectado não está montado.",
            )

        if not primary_mounted:
            checks["retention"] = _status("Retenção", "inconclusive", "Validação não executada porque a unidade principal está desmontada.")
            checks["last_backup"] = _status("Último backup", "inconclusive", "Validação não executada porque a unidade principal está desmontada.")
        elif not path_accessible:
            checks["retention"] = _status("Retenção", "inconclusive", "Diretório principal do backup não está acessível.")
            checks["last_backup"] = _status("Último backup", "critical", "Diretório principal do backup não está acessível.")
        else:
            recent_count_result = executor.run(
                _command(f"find {q_backup} -maxdepth 2 -type f -newermt '-{retention_days} days' -printf '.' | wc -c"),
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
                    f"Último arquivo em {backup_path} possui {age:.1f}h; limite configurado: {max_backup_age_hours}h.",
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

        redundancy = discovery.get("redundancy")
        if redundancy and redundancy.get("state") == "mounted":
            latest = redundancy.get("latest")
            if latest:
                age = float(latest["age_hours"])
                redundancy_status = "healthy" if age <= max_backup_age_hours else "attention"
                checks["redundancy"] = _status(
                    "Redundância",
                    redundancy_status,
                    (
                        f"Unidade redundante detectada automaticamente em {redundancy.get('target')} "
                        f"({redundancy.get('fstype') or 'tipo desconhecido'}); cópia mais recente possui {age:.1f}h."
                    ),
                    mount_point=redundancy.get("target"),
                    source=redundancy.get("source"),
                    fstype=redundancy.get("fstype"),
                    maximum_age_hours=max_backup_age_hours,
                    **latest,
                )
            else:
                checks["redundancy"] = _status(
                    "Redundância",
                    "attention",
                    f"Unidade redundante detectada em {redundancy.get('target')}, mas nenhum arquivo foi encontrado na varredura limitada.",
                    mount_point=redundancy.get("target"),
                    source=redundancy.get("source"),
                    fstype=redundancy.get("fstype"),
                )
        elif redundancy and redundancy.get("state") == "configured_unmounted":
            checks["redundancy"] = _status(
                "Redundância",
                "attention",
                f"Unidade de redundância detectada na configuração em {redundancy.get('target')}, porém está desmontada.",
                mount_point=redundancy.get("target"),
                source=redundancy.get("source"),
                fstype=redundancy.get("fstype"),
            )
        else:
            checks["redundancy"] = _status(
                "Redundância",
                "attention",
                "Nenhuma unidade de redundância pôde ser identificada automaticamente entre os mounts do servidor.",
            )

        mount_targets: list[str] = []
        if primary and not primary_mounted:
            mount_targets.append(str(primary.get("target") or ""))
        if redundancy and redundancy.get("state") == "configured_unmounted":
            mount_targets.append(str(redundancy.get("target") or ""))

        overall = _overall(checks)
        action_available = _action_for_mount_failure(mount_targets) if mount_targets else None
        result = {
            "skill": "backup_validation",
            "version": "1.2.0",
            "status": overall,
            "target": target.reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "backup_path": backup_path,
            "mount_point": primary_target or None,
            "redundancy_path": redundancy.get("target") if redundancy else None,
            "discovery": discovery,
            "checks": checks,
            "action_available": action_available,
            "executed_actions": [],
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        report_progress(
            "skill_completed",
            status="completed",
            detail=f"Backup Validation concluída com status {overall} e descoberta automática de storage.",
            percent=100,
            skill="backup_validation",
            host=target.host,
        )
        return result
    finally:
        executor.close()
