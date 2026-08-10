from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Any

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.correction_policy import MOUNT_RECOVERY_SCRIPT
from app.services.redaction import redact_text
from app.services.runner import build_executor, resolve_target
from app.services.ssh import SSHExecutor


_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9_./@:+-]*$")
_SAFE_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_RECOVERY_ENVIRONMENTS = {
    EnvironmentType.PRODUCTION,
    EnvironmentType.STANDBY,
    EnvironmentType.MONITORING,
    EnvironmentType.TRAINING,
}


class MountOperationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CronDiscovery:
    found: bool
    user: str | None
    source: str | None
    schedule: str | None
    entry_count: int
    ambiguous: bool
    inspection_error: str | None = None


@dataclass(frozen=True)
class MountProbe:
    path: str
    mounted: bool
    source: str | None
    fstype: str | None
    options: str | None
    filesystem: str | None
    health: str
    access_ok: bool
    access_timeout: bool
    access_exit_code: int | None
    usage_percent: int | None
    script_present: bool
    script_owner: str | None
    script_group: str | None
    script_mode: str | None
    script_executable: bool
    script_safe: bool
    cron_found: bool
    cron_user: str | None
    cron_source: str | None
    cron_schedule: str | None
    cron_entry_count: int
    cron_ambiguous: bool
    cron_inspection_error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mounted": self.mounted,
            "source": self.source,
            "fstype": self.fstype,
            "options": self.options,
            "filesystem": self.filesystem,
            "health": self.health,
            "access_ok": self.access_ok,
            "access_timeout": self.access_timeout,
            "access_exit_code": self.access_exit_code,
            "usage_percent": self.usage_percent,
            "script": MOUNT_RECOVERY_SCRIPT,
            "script_present": self.script_present,
            "script_owner": self.script_owner,
            "script_group": self.script_group,
            "script_mode": self.script_mode,
            "script_executable": self.script_executable,
            "script_safe": self.script_safe,
            "cron_found": self.cron_found,
            "cron_user": self.cron_user,
            "cron_source": self.cron_source,
            "cron_schedule": self.cron_schedule,
            "cron_entry_count": self.cron_entry_count,
            "cron_ambiguous": self.cron_ambiguous,
            "cron_inspection_error": self.cron_inspection_error,
        }


def _allowed_prefixes() -> tuple[str, ...]:
    raw = os.getenv("AGENT_MOUNT_ALLOWED_PREFIXES", "/mnt,/backup,/db/backup")
    result: list[str] = []
    for item in raw.split(","):
        value = item.strip().rstrip("/") or "/"
        if value and value not in result:
            result.append(value)
    return tuple(result)


def validate_mount_path(path: str) -> str:
    value = str(path or "").strip()
    if not value or not _SAFE_PATH_RE.fullmatch(value):
        raise MountOperationError("ponto de montagem inválido")
    if ".." in value.split("/"):
        raise MountOperationError("ponto de montagem inválido")
    if value == "/":
        raise MountOperationError("o filesystem raiz não pode ser usado nesta operação")
    prefixes = _allowed_prefixes()
    if prefixes and not any(value == prefix or value.startswith(prefix + "/") for prefix in prefixes):
        raise MountOperationError(
            "ponto de montagem fora dos prefixos autorizados: " + ", ".join(prefixes)
        )
    return value


def _probe_command(path: str) -> str:
    quoted_path = shlex.quote(path)
    quoted_script = shlex.quote(MOUNT_RECOVERY_SCRIPT)
    return (
        f"path={quoted_path}; script={quoted_script}; "
        "mounted=0; "
        "if command -v findmnt >/dev/null 2>&1 && findmnt -rn -M \"$path\" >/dev/null 2>&1; then mounted=1; "
        "elif [ -r /proc/self/mountinfo ] && awk -v p=\"$path\" '$5 == p {found=1} END {exit found ? 0 : 1}' /proc/self/mountinfo >/dev/null 2>&1; then mounted=1; fi; "
        "printf 'MOUNTED=%s\\n' \"$mounted\"; "
        "if [ \"$mounted\" -eq 1 ]; then "
        "findmnt -rn -M \"$path\" -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null | head -n 1 | sed 's/^/FINDMNT=/'; "
        "access_rc=125; "
        "if command -v timeout >/dev/null 2>&1; then timeout 6 stat -L -- \"$path\" >/dev/null 2>&1; access_rc=$?; fi; "
        "printf 'ACCESS_RC=%s\\n' \"$access_rc\"; "
        "if [ \"$access_rc\" -eq 124 ]; then printf 'ACCESS_TIMEOUT=1\\n'; else printf 'ACCESS_TIMEOUT=0\\n'; fi; "
        "if [ \"$access_rc\" -eq 0 ] && command -v timeout >/dev/null 2>&1; then "
        "timeout 6 df -hP \"$path\" 2>/dev/null | tail -n 1 | sed 's/^/DF=/' || true; "
        "fi; "
        "fi; "
        "if [ -f \"$script\" ]; then "
        "printf 'SCRIPT_PRESENT=1\\n'; "
        "stat -c 'SCRIPT_META=%U|%G|%a' \"$script\" 2>/dev/null || true; "
        "else printf 'SCRIPT_PRESENT=0\\n'; fi"
    )


def _cron_probe_command() -> str:
    script = shlex.quote(MOUNT_RECOVERY_SCRIPT)
    return (
        f"script={script}; "
        "for f in /etc/crontab /etc/cron.d/*; do "
        "[ -f \"$f\" ] || continue; "
        "while IFS= read -r line; do "
        "set -f; set -- $line; set +f; [ \"$#\" -gt 0 ] || continue; case \"$1\" in \\#*) continue;; esac; "
        "if [ \"${1#@}\" != \"$1\" ]; then "
        "[ \"$#\" -ge 3 ] || continue; schedule=\"$1\"; user=\"$2\"; shift 2; "
        "else [ \"$#\" -ge 7 ] || continue; schedule=\"$1 $2 $3 $4 $5\"; user=\"$6\"; shift 6; fi; "
        "found=0; for token in \"$@\"; do [ \"$token\" = \"$script\" ] && found=1; done; "
        "[ \"$found\" -eq 1 ] || continue; "
        "printf 'CRON_ENTRY=%s|%s|%s\\n' \"$user\" \"$f\" \"$schedule\"; "
        "done < \"$f\"; done; "
        "for d in /var/spool/cron /var/spool/cron/crontabs; do "
        "[ -d \"$d\" ] || continue; "
        "for f in \"$d\"/*; do [ -f \"$f\" ] || continue; user=$(basename \"$f\"); "
        "while IFS= read -r line; do "
        "set -f; set -- $line; set +f; [ \"$#\" -gt 0 ] || continue; case \"$1\" in \\#*) continue;; esac; "
        "if [ \"${1#@}\" != \"$1\" ]; then "
        "[ \"$#\" -ge 2 ] || continue; schedule=\"$1\"; shift 1; "
        "else [ \"$#\" -ge 6 ] || continue; schedule=\"$1 $2 $3 $4 $5\"; shift 5; fi; "
        "found=0; for token in \"$@\"; do [ \"$token\" = \"$script\" ] && found=1; done; "
        "[ \"$found\" -eq 1 ] || continue; "
        "printf 'CRON_ENTRY=%s|%s|%s\\n' \"$user\" \"$f\" \"$schedule\"; "
        "done < \"$f\"; done; done"
    )


def _parse_cron(stdout: str) -> CronDiscovery:
    entries: list[tuple[str, str, str]] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith("CRON_ENTRY="):
            continue
        fields = line.removeprefix("CRON_ENTRY=").split("|", 2)
        if len(fields) != 3:
            continue
        user, source, schedule = (field.strip() for field in fields)
        if not _SAFE_USER_RE.fullmatch(user):
            continue
        item = (user, source, schedule)
        if item not in entries:
            entries.append(item)

    users = list(dict.fromkeys(item[0] for item in entries))
    ambiguous = len(users) > 1
    selected = entries[0] if entries and not ambiguous else None
    return CronDiscovery(
        found=bool(entries),
        user=selected[0] if selected else None,
        source=selected[1] if selected else None,
        schedule=selected[2] if selected else None,
        entry_count=len(entries),
        ambiguous=ambiguous,
    )


def _discover_cron(executor: SSHExecutor, environment: EnvironmentType) -> CronDiscovery:
    try:
        result = executor.run_sudo(_cron_probe_command(), environment, timeout=30)
    except Exception as exc:
        return CronDiscovery(False, None, None, None, 0, False, redact_text(str(exc)))
    if result.exit_code != 0:
        detail = redact_text(result.stderr or result.stdout or "não foi possível consultar o crontab")
        return CronDiscovery(False, None, None, None, 0, False, detail)
    return _parse_cron(result.stdout)


def _parse_usage_percent(filesystem: str | None) -> int | None:
    if not filesystem:
        return None
    for token in filesystem.split():
        if re.fullmatch(r"\d{1,3}%", token):
            try:
                return max(0, min(100, int(token[:-1])))
            except ValueError:
                return None
    return None


def _parse_probe(path: str, stdout: str, cron: CronDiscovery) -> MountProbe:
    mounted = False
    source = None
    fstype = None
    options = None
    filesystem = None
    access_exit_code = None
    access_timeout = False
    script_present = False
    script_owner = None
    script_group = None
    script_mode = None

    for raw in stdout.splitlines():
        line = raw.strip()
        if line == "MOUNTED=1":
            mounted = True
        elif line.startswith("FINDMNT="):
            fields = line.removeprefix("FINDMNT=").split(None, 3)
            if len(fields) >= 2:
                source = fields[1]
            if len(fields) >= 3:
                fstype = fields[2]
            if len(fields) >= 4:
                options = fields[3]
        elif line.startswith("DF="):
            filesystem = line.removeprefix("DF=").strip() or None
        elif line.startswith("ACCESS_RC="):
            try:
                access_exit_code = int(line.removeprefix("ACCESS_RC=").strip())
            except ValueError:
                access_exit_code = None
        elif line == "ACCESS_TIMEOUT=1":
            access_timeout = True
        elif line == "SCRIPT_PRESENT=1":
            script_present = True
        elif line.startswith("SCRIPT_META="):
            meta = line.removeprefix("SCRIPT_META=").split("|", 2)
            script_owner = meta[0].strip() or None
            script_group = meta[1].strip() if len(meta) > 1 else None
            script_mode = meta[2].strip() if len(meta) > 2 else None

    script_executable = False
    script_safe = False
    if script_present and script_mode:
        try:
            mode = int(script_mode, 8)
            script_executable = bool(mode & 0o111)
            script_safe = script_executable and (mode & 0o022) == 0
        except ValueError:
            pass

    if not mounted:
        health = "unmounted"
    elif access_timeout or access_exit_code == 124:
        health = "hanging"
    elif access_exit_code == 0:
        health = "healthy"
    else:
        health = "degraded"

    return MountProbe(
        path=path,
        mounted=mounted,
        source=source,
        fstype=fstype,
        options=options,
        filesystem=filesystem,
        health=health,
        access_ok=bool(mounted and access_exit_code == 0),
        access_timeout=access_timeout,
        access_exit_code=access_exit_code,
        usage_percent=_parse_usage_percent(filesystem),
        script_present=script_present,
        script_owner=script_owner,
        script_group=script_group,
        script_mode=script_mode,
        script_executable=script_executable,
        script_safe=script_safe,
        cron_found=cron.found,
        cron_user=cron.user,
        cron_source=cron.source,
        cron_schedule=cron.schedule,
        cron_entry_count=cron.entry_count,
        cron_ambiguous=cron.ambiguous,
        cron_inspection_error=cron.inspection_error,
    )


def probe_mount(executor: SSHExecutor, environment: EnvironmentType, path: str) -> MountProbe:
    safe_path = validate_mount_path(path)
    result = executor.run(_probe_command(safe_path), environment, timeout=30)
    if result.exit_code != 0:
        detail = redact_text(result.stderr or result.stdout or "falha ao validar mount")
        raise MountOperationError(detail)
    cron = _discover_cron(executor, environment)
    return _parse_probe(safe_path, result.stdout, cron)


def _recovery_prerequisite_reason(probe: MountProbe, environment: EnvironmentType) -> str | None:
    if environment == EnvironmentType.UNKNOWN:
        return "ambiente precisa estar classificado antes da alteração"
    if not probe.script_present:
        return f"script padrão não encontrado: {MOUNT_RECOVERY_SCRIPT}"
    if not probe.script_executable:
        return "script padrão não possui permissão de execução"
    if not probe.script_safe:
        return "script padrão possui permissão de escrita para grupo/outros"
    if probe.cron_inspection_error:
        return f"não foi possível validar o crontab: {probe.cron_inspection_error}"
    if not probe.cron_found:
        return "script padrão não foi localizado no crontab do servidor"
    if probe.cron_ambiguous:
        return "script padrão aparece no crontab com mais de um usuário de execução"
    if not probe.cron_user:
        return "não foi possível identificar o usuário que executa o script no cron"
    return None


def _mount_block_reason(probe: MountProbe, environment: EnvironmentType) -> str | None:
    if probe.mounted:
        return "unidade já está montada"
    return _recovery_prerequisite_reason(probe, environment)


def _remount_block_reason(probe: MountProbe, environment: EnvironmentType) -> str | None:
    if not probe.mounted:
        return "a unidade precisa estar montada para solicitar remontagem"
    if probe.health != "hanging":
        return "remontagem só é oferecida quando a validação detecta estado Hanging"
    return _recovery_prerequisite_reason(probe, environment)


def validate_mount(
    reference: str,
    path: str,
    *,
    environment: EnvironmentType = EnvironmentType.UNKNOWN,
    ssh_port: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    safe_path = validate_mount_path(path)
    target = resolve_target(reference, environment, ssh_port, settings=settings)
    executor = build_executor(target, settings=settings)
    try:
        executor.connect()
        probe = probe_mount(executor, target.environment, safe_path)
    finally:
        executor.close()

    mount_reason = _mount_block_reason(probe, target.environment)
    remount_reason = _remount_block_reason(probe, target.environment)
    can_request_mount = mount_reason is None and target.environment in _RECOVERY_ENVIRONMENTS
    can_request_remount = remount_reason is None and target.environment in _RECOVERY_ENVIRONMENTS
    return {
        "operation": "mount_validation",
        "target": reference,
        "resolved_host": target.host,
        "ssh_port": target.port,
        "environment": target.environment.value,
        **probe.as_dict(),
        "can_request_mount": can_request_mount,
        "can_request_remount": can_request_remount,
        "reason": mount_reason,
        "remount_reason": remount_reason,
    }


def _mount_execution_command(cron_user: str) -> str:
    if not _SAFE_USER_RE.fullmatch(cron_user):
        raise MountOperationError("usuário de execução do cron inválido")
    if cron_user == "root":
        return MOUNT_RECOVERY_SCRIPT
    return f"sudo -u {cron_user} -- {MOUNT_RECOVERY_SCRIPT}"


def _unmount_execution_command(path: str) -> str:
    safe_path = validate_mount_path(path)
    return f"timeout 30 umount -- {safe_path}"


def _validate_cron_user(executor: SSHExecutor, environment: EnvironmentType, cron_user: str) -> None:
    user_check = executor.run_sudo(
        f"id -u {shlex.quote(cron_user)}",
        environment,
        timeout=10,
    )
    if user_check.exit_code != 0:
        raise MountOperationError(f"usuário do cron não existe ou não está acessível: {cron_user}")


def recover_mount(
    reference: str,
    path: str,
    *,
    environment: EnvironmentType,
    ssh_port: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    safe_path = validate_mount_path(path)
    target = resolve_target(reference, environment, ssh_port, settings=settings)
    if target.environment not in _RECOVERY_ENVIRONMENTS:
        raise MountOperationError("ambiente não autorizado para solicitação de montagem")

    executor = build_executor(target, settings=settings)
    try:
        executor.connect()
        before = probe_mount(executor, target.environment, safe_path)
        if before.mounted:
            return {
                "operation": "mount_recovery",
                "target": reference,
                "resolved_host": target.host,
                "ssh_port": target.port,
                "environment": target.environment.value,
                "path": safe_path,
                "script": MOUNT_RECOVERY_SCRIPT,
                "execution_user": before.cron_user,
                "status": "already_mounted",
                "mounted": True,
                "health": before.health,
                "before": before.as_dict(),
                "after": before.as_dict(),
                "script_exit_code": None,
                "script_stdout": "",
                "script_stderr": "",
            }

        reason = _mount_block_reason(before, target.environment)
        if reason:
            raise MountOperationError(reason)
        cron_user = str(before.cron_user or "")
        _validate_cron_user(executor, target.environment, cron_user)

        execution_command = _mount_execution_command(cron_user)
        script_result = executor.run_sudo(
            execution_command,
            target.environment,
            approved=True,
            timeout=180,
        )
        after = probe_mount(executor, target.environment, safe_path)
        healthy = bool(after.mounted and after.health == "healthy")
        return {
            "operation": "mount_recovery",
            "target": reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "path": safe_path,
            "script": MOUNT_RECOVERY_SCRIPT,
            "execution_user": cron_user,
            "cron_source": before.cron_source,
            "cron_schedule": before.cron_schedule,
            "status": "mounted" if healthy else ("hanging" if after.mounted and after.health == "hanging" else "failed"),
            "mounted": bool(after.mounted),
            "health": after.health,
            "healthy": healthy,
            "before": before.as_dict(),
            "after": after.as_dict(),
            "script_exit_code": script_result.exit_code,
            "script_stdout": redact_text(script_result.stdout),
            "script_stderr": redact_text(script_result.stderr),
        }
    finally:
        executor.close()


def remount_mount(
    reference: str,
    path: str,
    *,
    environment: EnvironmentType,
    ssh_port: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    safe_path = validate_mount_path(path)
    target = resolve_target(reference, environment, ssh_port, settings=settings)
    if target.environment not in _RECOVERY_ENVIRONMENTS:
        raise MountOperationError("ambiente não autorizado para solicitação de remontagem")

    executor = build_executor(target, settings=settings)
    try:
        executor.connect()
        before = probe_mount(executor, target.environment, safe_path)
        reason = _remount_block_reason(before, target.environment)
        if reason:
            raise MountOperationError(reason)

        cron_user = str(before.cron_user or "")
        _validate_cron_user(executor, target.environment, cron_user)

        unmount_command = _unmount_execution_command(safe_path)
        unmount_result = executor.run_sudo(
            unmount_command,
            target.environment,
            approved=True,
            timeout=40,
        )
        after_unmount = probe_mount(executor, target.environment, safe_path)
        if unmount_result.exit_code != 0 or after_unmount.mounted:
            return {
                "operation": "mount_remount",
                "target": reference,
                "resolved_host": target.host,
                "ssh_port": target.port,
                "environment": target.environment.value,
                "path": safe_path,
                "script": MOUNT_RECOVERY_SCRIPT,
                "execution_user": cron_user,
                "status": "unmount_failed",
                "mounted": bool(after_unmount.mounted),
                "health": after_unmount.health,
                "healthy": False,
                "before": before.as_dict(),
                "after_unmount": after_unmount.as_dict(),
                "after": after_unmount.as_dict(),
                "unmount_exit_code": unmount_result.exit_code,
                "unmount_stdout": redact_text(unmount_result.stdout),
                "unmount_stderr": redact_text(unmount_result.stderr),
                "script_exit_code": None,
                "script_stdout": "",
                "script_stderr": "",
            }

        execution_command = _mount_execution_command(cron_user)
        script_result = executor.run_sudo(
            execution_command,
            target.environment,
            approved=True,
            timeout=180,
        )
        after = probe_mount(executor, target.environment, safe_path)
        healthy = bool(after.mounted and after.health == "healthy")
        status = "remounted" if healthy else ("still_hanging" if after.mounted and after.health == "hanging" else "failed")
        return {
            "operation": "mount_remount",
            "target": reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "path": safe_path,
            "script": MOUNT_RECOVERY_SCRIPT,
            "execution_user": cron_user,
            "cron_source": before.cron_source,
            "cron_schedule": before.cron_schedule,
            "status": status,
            "mounted": bool(after.mounted),
            "health": after.health,
            "healthy": healthy,
            "before": before.as_dict(),
            "after_unmount": after_unmount.as_dict(),
            "after": after.as_dict(),
            "unmount_exit_code": unmount_result.exit_code,
            "unmount_stdout": redact_text(unmount_result.stdout),
            "unmount_stderr": redact_text(unmount_result.stderr),
            "script_exit_code": script_result.exit_code,
            "script_stdout": redact_text(script_result.stdout),
            "script_stderr": redact_text(script_result.stderr),
        }
    finally:
        executor.close()
