from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from app.services.command_catalog import validate_command


DEFAULT_REGISTRY_PATH = Path("/opt/agent-ia/data/custom-skills.json")
DEFAULT_SCRIPT_ROOTS = ("/db/backup/scripts", "/opt/agent-ia/scripts")
SKILL_MODES = {"read_only", "diagnostic", "correction"}
_SAFE_BINARIES = {
    "uptime", "hostname", "hostnamectl", "uname", "nproc", "date", "timedatectl", "who", "w", "last",
    "free", "vmstat", "iostat", "mpstat", "sar", "lscpu", "lsmem", "ps",
    "df", "du", "lsblk", "findmnt", "stat", "ls",
    "ip", "ss", "netstat", "ping", "traceroute", "tracepath", "host", "dig", "nslookup",
    "journalctl", "dmesg", "systemctl", "service", "cmk-agent-ctl",
}
_FORBIDDEN_SYNTAX = (";", "&&", "||", "|", ">", "<", "`", "$(", "${", "\n", "\r")
_SAFE_SYSTEMCTL = {"status", "is-active", "is-enabled", "list-units", "list-unit-files", "show", "cat"}
_SAFE_HOSTNAME_FLAGS = {"-f", "--fqdn", "-s", "--short", "-d", "--domain", "-i", "--ip-address", "-I", "--all-ip-addresses"}
_SAFE_TIMEDATECTL = {"status", "show", "timesync-status", "show-timesync", "list-timezones"}
_IP_MUTATIONS = {"add", "del", "delete", "replace", "change", "set", "flush", "append", "prepend"}
_JOURNAL_MUTATIONS = ("--vacuum", "--rotate", "--flush", "--sync", "--relinquish-var", "--smart-relinquish-var")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def registry_path() -> Path:
    configured = os.getenv("AGENT_CUSTOM_SKILLS_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_REGISTRY_PATH


def allowed_script_roots() -> tuple[str, ...]:
    configured = os.getenv("AGENT_CUSTOM_SKILL_SCRIPT_ROOTS", "").strip()
    values = [item.strip() for item in configured.split(":") if item.strip()] if configured else list(DEFAULT_SCRIPT_ROOTS)
    roots: list[str] = []
    for value in values:
        normalized = posixpath.normpath(value)
        if not normalized.startswith("/") or normalized == "/":
            continue
        roots.append(normalized)
    return tuple(dict.fromkeys(roots)) or DEFAULT_SCRIPT_ROOTS


def _read(path: Path | None = None) -> dict[str, Any]:
    target = path or registry_path()
    if not target.exists():
        return {"schema_version": 2, "skills": []}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"não foi possível carregar as skills personalizadas: {exc}") from exc
    if not isinstance(payload.get("skills"), list):
        raise RuntimeError("registro de skills personalizadas inválido")
    # Migração compatível da v1 para v2.
    for skill in payload["skills"]:
        if not isinstance(skill, dict):
            continue
        skill.setdefault("mode", "read_only")
        skill.setdefault("scripts", [])
    payload["schema_version"] = 2
    return payload


def _write(payload: dict[str, Any], path: Path | None = None) -> None:
    target = path or registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "schema_version": 2}
    fd, tmp_name = tempfile.mkstemp(prefix="custom-skills-", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
        os.chmod(target, 0o600)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _clean_name(value: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if len(name) < 2 or len(name) > 80:
        raise ValueError("o nome da skill deve ter entre 2 e 80 caracteres")
    return name


def _clean_mode(value: str) -> str:
    mode = str(value or "read_only").strip().casefold()
    if mode not in SKILL_MODES:
        raise ValueError("modo da skill deve ser leitura, diagnóstico ou correção")
    return mode


def _clean_configured_command(command: str) -> str:
    raw = str(command or "").strip()
    if not raw:
        raise ValueError("comando vazio")
    if len(raw) > 1000:
        raise ValueError("comando excede 1000 caracteres")
    if "\x00" in raw or "\n" in raw or "\r" in raw:
        raise ValueError("o comando deve ser informado em uma única linha")
    return raw


def _validate_read_only_args(parts: list[str]) -> None:
    binary = parts[0]
    lowered = [item.casefold() for item in parts[1:]]
    if binary == "hostname" and any(item not in _SAFE_HOSTNAME_FLAGS for item in parts[1:]):
        raise ValueError("hostname aceita apenas consultas de nome/FQDN/IP")
    if binary == "hostnamectl" and len(parts) > 1 and parts[1].casefold() != "status":
        raise ValueError("hostnamectl aceita somente status")
    if binary == "date" and any(item in {"-s", "--set"} or item.startswith("--set=") for item in lowered):
        raise ValueError("date não pode alterar data/hora")
    if binary == "timedatectl" and len(parts) > 1 and parts[1].casefold() not in _SAFE_TIMEDATECTL:
        raise ValueError("timedatectl aceita somente consultas de status")
    if binary == "ip" and _IP_MUTATIONS.intersection(lowered):
        raise ValueError("ip aceita somente consultas; alterações de rede são bloqueadas")
    if binary == "journalctl" and any(any(item.startswith(prefix) for prefix in _JOURNAL_MUTATIONS) for item in lowered):
        raise ValueError("journalctl aceita somente leitura; manutenção de journal é bloqueada")
    if binary == "dmesg" and any(item in {"-c", "--clear", "--read-clear"} for item in lowered):
        raise ValueError("dmesg não pode limpar o buffer do kernel")
    if binary == "systemctl" and (len(parts) < 2 or parts[1].casefold() not in _SAFE_SYSTEMCTL):
        raise ValueError("systemctl em Skill de Leitura aceita somente consultas de status")
    if binary == "service" and (len(parts) != 3 or parts[2].casefold() != "status"):
        raise ValueError("service em Skill de Leitura aceita somente: service <nome> status")


def validate_custom_command(command: str, mode: str = "read_only") -> str:
    """Valida uma ação cadastrada de acordo com a permissão da Skill.

    Diagnóstico e Correção podem registrar comandos livres em uma única linha. Isso
    não significa autorização de execução: o runner separa comandos comprovadamente
    somente leitura das ações que devem permanecer aguardando aprovação/política.
    """
    raw = _clean_configured_command(command)
    clean_mode = _clean_mode(mode)
    if clean_mode != "read_only":
        return raw

    if any(token in raw for token in _FORBIDDEN_SYNTAX):
        raise ValueError("pipes, redirecionamentos, substituições e encadeamentos não são permitidos em Skill de Leitura")
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"sintaxe inválida: {exc}") from exc
    if not parts:
        raise ValueError("comando vazio")
    binary = parts[0]
    if binary not in _SAFE_BINARIES:
        raise ValueError(f"comando não permitido em Skill de Leitura: {binary}")
    _validate_read_only_args(parts)
    allowed, reason, spec = validate_command(raw)
    if not allowed or spec is None or not spec.read_only:
        raise ValueError(reason or "comando fora do catálogo seguro")
    return raw


def validate_script_path(script: str) -> str:
    raw = str(script or "").strip()
    if not raw:
        raise ValueError("script vazio")
    if len(raw) > 1024:
        raise ValueError("caminho do script excede 1024 caracteres")
    if any(token in raw for token in _FORBIDDEN_SYNTAX) or any(char.isspace() for char in raw):
        raise ValueError("o script deve ser informado apenas como caminho absoluto, sem argumentos ou shell")
    path = PurePosixPath(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("o script deve usar caminho absoluto sem ..")
    normalized = posixpath.normpath(raw)
    if not any(normalized == root or normalized.startswith(root + "/") for root in allowed_script_roots()):
        raise ValueError(
            "script fora dos diretórios permitidos; configure AGENT_CUSTOM_SKILL_SCRIPT_ROOTS se necessário"
        )
    return normalized


def _normalized_payload(name: str, commands: list[str], scripts: list[str], description: str, mode: str) -> dict[str, Any]:
    clean_name = _clean_name(name)
    clean_mode = _clean_mode(mode)
    clean_commands = [validate_custom_command(item, clean_mode) for item in commands if str(item or "").strip()]
    clean_scripts = [validate_script_path(item) for item in scripts if str(item or "").strip()]
    if not clean_commands and not clean_scripts:
        raise ValueError("informe pelo menos um comando ou script")
    if len(clean_commands) > 20:
        raise ValueError("cada skill pode ter no máximo 20 comandos")
    if len(clean_scripts) > 10:
        raise ValueError("cada skill pode ter no máximo 10 scripts")
    if clean_mode == "read_only" and clean_scripts:
        raise ValueError("Skills de leitura não aceitam scripts; use Diagnóstico ou Correção")
    return {
        "name": clean_name,
        "description": str(description or "").strip()[:300],
        "commands": list(dict.fromkeys(clean_commands)),
        "scripts": list(dict.fromkeys(clean_scripts)),
        "mode": clean_mode,
    }


def list_custom_skills(path: Path | None = None) -> list[dict[str, Any]]:
    return list(_read(path).get("skills") or [])


def get_custom_skill(skill_id: str, path: Path | None = None) -> dict[str, Any] | None:
    sid = str(skill_id or "").strip()
    return next((item for item in list_custom_skills(path) if item.get("id") == sid), None)


def create_custom_skill(
    name: str,
    commands: list[str],
    *,
    scripts: list[str] | None = None,
    description: str = "",
    mode: str = "read_only",
    path: Path | None = None,
) -> dict[str, Any]:
    data = _normalized_payload(name, commands, scripts or [], description, mode)
    payload = _read(path)
    if any(str(item.get("name") or "").casefold() == data["name"].casefold() for item in payload["skills"]):
        raise ValueError("já existe uma skill personalizada com esse nome")
    now = _now()
    skill = {"id": uuid.uuid4().hex, **data, "created_at": now, "updated_at": now}
    payload["skills"].append(skill)
    _write(payload, path)
    return skill


def update_custom_skill(
    skill_id: str,
    *,
    name: str,
    commands: list[str],
    scripts: list[str] | None = None,
    description: str = "",
    mode: str = "read_only",
    path: Path | None = None,
) -> dict[str, Any]:
    data = _normalized_payload(name, commands, scripts or [], description, mode)
    payload = _read(path)
    skill = next((item for item in payload["skills"] if item.get("id") == skill_id), None)
    if skill is None:
        raise LookupError("skill personalizada não encontrada")
    if any(
        item.get("id") != skill_id and str(item.get("name") or "").casefold() == data["name"].casefold()
        for item in payload["skills"]
    ):
        raise ValueError("já existe uma skill personalizada com esse nome")
    skill.update(data)
    skill["updated_at"] = _now()
    _write(payload, path)
    return dict(skill)


def delete_custom_skill(skill_id: str, *, path: Path | None = None) -> bool:
    payload = _read(path)
    before = len(payload["skills"])
    payload["skills"] = [item for item in payload["skills"] if item.get("id") != skill_id]
    if len(payload["skills"]) == before:
        return False
    _write(payload, path)
    return True
