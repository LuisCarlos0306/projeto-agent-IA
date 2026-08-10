from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Any

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.redaction import redact_text
from app.services.runner import build_executor, resolve_target
from app.services.ssh import SSHExecutor


MOUNT_RECOVERY_SCRIPT = "/db/backup/scripts/mount.sh"
_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9_./@:+-]*$")
_RECOVERY_ENVIRONMENTS = {
    EnvironmentType.PRODUCTION,
    EnvironmentType.STANDBY,
    EnvironmentType.MONITORING,
    EnvironmentType.TRAINING,
}


class MountOperationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MountProbe:
    path: str
    mounted: bool
    source: str | None
    fstype: str | None
    options: str | None
    filesystem: str | None
    script_present: bool
    script_owner: str | None
    script_mode: str | None
    script_safe: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mounted": self.mounted,
            "source": self.source,
            "fstype": self.fstype,
            "options": self.options,
            "filesystem": self.filesystem,
            "script": MOUNT_RECOVERY_SCRIPT,
            "script_present": self.script_present,
            "script_owner": self.script_owner,
            "script_mode": self.script_mode,
            "script_safe": self.script_safe,
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
        "if command -v mountpoint >/dev/null 2>&1 && mountpoint -q -- \"$path\"; then mounted=1; "
        "elif command -v findmnt >/dev/null 2>&1 && findmnt -rn -M \"$path\" >/dev/null 2>&1; then mounted=1; fi; "
        "printf 'MOUNTED=%s\\n' \"$mounted\"; "
        "if [ \"$mounted\" -eq 1 ]; then "
        "findmnt -rn -M \"$path\" -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null | head -n 1 | sed 's/^/FINDMNT=/'; "
        "df -hP \"$path\" 2>/dev/null | tail -n 1 | sed 's/^/DF=/' || true; "
        "fi; "
        "if [ -f \"$script\" ]; then "
        "printf 'SCRIPT_PRESENT=1\\n'; "
        "stat -c 'SCRIPT_META=%U|%a' \"$script\" 2>/dev/null || true; "
        "else printf 'SCRIPT_PRESENT=0\\n'; fi"
    )


def _parse_probe(path: str, stdout: str) -> MountProbe:
    mounted = False
    source = None
    fstype = None
    options = None
    filesystem = None
    script_present = False
    script_owner = None
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
        elif line == "SCRIPT_PRESENT=1":
            script_present = True
        elif line.startswith("SCRIPT_META="):
            meta = line.removeprefix("SCRIPT_META=").split("|", 1)
            script_owner = meta[0].strip() or None
            script_mode = meta[1].strip() if len(meta) > 1 else None

    script_safe = False
    if script_present and script_owner == "root" and script_mode:
        try:
            mode = int(script_mode, 8)
            script_safe = (mode & 0o022) == 0
        except ValueError:
            script_safe = False

    return MountProbe(
        path=path,
        mounted=mounted,
        source=source,
        fstype=fstype,
        options=options,
        filesystem=filesystem,
        script_present=script_present,
        script_owner=script_owner,
        script_mode=script_mode,
        script_safe=script_safe,
    )


def probe_mount(executor: SSHExecutor, environment: EnvironmentType, path: str) -> MountProbe:
    safe_path = validate_mount_path(path)
    result = executor.run(_probe_command(safe_path), environment, timeout=30)
    if result.exit_code != 0:
        detail = redact_text(result.stderr or result.stdout or "falha ao validar mount")
        raise MountOperationError(detail)
    return _parse_probe(safe_path, result.stdout)


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

    can_request_mount = (
        not probe.mounted
        and probe.script_present
        and probe.script_safe
        and target.environment in _RECOVERY_ENVIRONMENTS
    )
    reason = None
    if probe.mounted:
        reason = "unidade já está montada"
    elif target.environment == EnvironmentType.UNKNOWN:
        reason = "ambiente precisa estar classificado antes da montagem"
    elif not probe.script_present:
        reason = f"script padrão não encontrado: {MOUNT_RECOVERY_SCRIPT}"
    elif not probe.script_safe:
        reason = "script padrão precisa pertencer ao root e não pode ser gravável por grupo/outros"

    return {
        "operation": "mount_validation",
        "target": reference,
        "resolved_host": target.host,
        "ssh_port": target.port,
        "environment": target.environment.value,
        **probe.as_dict(),
        "can_request_mount": can_request_mount,
        "reason": reason,
    }


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
                "status": "already_mounted",
                "mounted": True,
                "before": before.as_dict(),
                "after": before.as_dict(),
                "script_exit_code": None,
                "script_stdout": "",
                "script_stderr": "",
            }
        if not before.script_present or not before.script_safe:
            raise MountOperationError(
                "script padrão ausente ou com permissões inseguras; montagem bloqueada"
            )

        script_result = executor.run_sudo(
            MOUNT_RECOVERY_SCRIPT,
            target.environment,
            approved=True,
            timeout=180,
        )
        after = probe_mount(executor, target.environment, safe_path)
        success = bool(after.mounted)
        return {
            "operation": "mount_recovery",
            "target": reference,
            "resolved_host": target.host,
            "ssh_port": target.port,
            "environment": target.environment.value,
            "path": safe_path,
            "script": MOUNT_RECOVERY_SCRIPT,
            "status": "mounted" if success else "failed",
            "mounted": success,
            "before": before.as_dict(),
            "after": after.as_dict(),
            "script_exit_code": script_result.exit_code,
            "script_stdout": redact_text(script_result.stdout),
            "script_stderr": redact_text(script_result.stderr),
        }
    finally:
        executor.close()
