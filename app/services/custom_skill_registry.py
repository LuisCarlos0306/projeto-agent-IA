from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.command_catalog import validate_command


DEFAULT_REGISTRY_PATH = Path("/opt/agent-ia/data/custom-skills.json")
_SAFE_BINARIES = {
    "uptime", "hostname", "hostnamectl", "uname", "nproc", "date", "timedatectl", "who", "w", "last",
    "free", "vmstat", "iostat", "mpstat", "sar", "lscpu", "lsmem", "ps",
    "df", "du", "lsblk", "blkid", "findmnt", "stat", "ls",
    "ip", "ss", "netstat", "route", "arp", "ping", "traceroute", "tracepath", "ethtool", "resolvectl",
    "host", "dig", "nslookup", "journalctl", "dmesg", "systemctl", "service", "cmk-agent-ctl",
}
_FORBIDDEN_SYNTAX = (";", "&&", "||", "|", ">", "<", "`", "$(", "${", "\n", "\r")
_SAFE_SYSTEMCTL = {"status", "is-active", "is-enabled", "list-units", "list-unit-files", "show", "cat"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def registry_path() -> Path:
    configured = os.getenv("AGENT_CUSTOM_SKILLS_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_REGISTRY_PATH


def _read(path: Path | None = None) -> dict[str, Any]:
    target = path or registry_path()
    if not target.exists():
        return {"schema_version": 1, "skills": []}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"não foi possível carregar as skills personalizadas: {exc}") from exc
    if payload.get("schema_version") != 1 or not isinstance(payload.get("skills"), list):
        raise RuntimeError("registro de skills personalizadas inválido")
    return payload


def _write(payload: dict[str, Any], path: Path | None = None) -> None:
    target = path or registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
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


def validate_custom_command(command: str) -> str:
    raw = str(command or "").strip()
    if not raw:
        raise ValueError("comando vazio")
    if len(raw) > 500:
        raise ValueError("comando excede 500 caracteres")
    if any(token in raw for token in _FORBIDDEN_SYNTAX):
        raise ValueError("pipes, redirecionamentos, substituições e encadeamentos não são permitidos")
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"sintaxe inválida: {exc}") from exc
    if not parts:
        raise ValueError("comando vazio")
    binary = parts[0]
    if binary not in _SAFE_BINARIES:
        raise ValueError(f"comando não permitido em skill personalizada: {binary}")
    if binary == "systemctl":
        if len(parts) < 2 or parts[1] not in _SAFE_SYSTEMCTL:
            raise ValueError("systemctl em skill personalizada aceita somente consultas de status")
    if binary == "service":
        if len(parts) != 3 or parts[2] != "status":
            raise ValueError("service em skill personalizada aceita somente: service <nome> status")
    allowed, reason, spec = validate_command(raw)
    if not allowed or spec is None or not spec.read_only:
        raise ValueError(reason or "comando fora do catálogo seguro")
    return raw


def list_custom_skills(path: Path | None = None) -> list[dict[str, Any]]:
    return list(_read(path).get("skills") or [])


def get_custom_skill(skill_id: str, path: Path | None = None) -> dict[str, Any] | None:
    sid = str(skill_id or "").strip()
    return next((item for item in list_custom_skills(path) if item.get("id") == sid), None)


def create_custom_skill(name: str, commands: list[str], *, description: str = "", path: Path | None = None) -> dict[str, Any]:
    clean_name = _clean_name(name)
    clean_commands = [validate_custom_command(item) for item in commands if str(item or "").strip()]
    if not clean_commands:
        raise ValueError("informe pelo menos um comando")
    if len(clean_commands) > 20:
        raise ValueError("cada skill pode ter no máximo 20 comandos")
    payload = _read(path)
    if any(str(item.get("name") or "").casefold() == clean_name.casefold() for item in payload["skills"]):
        raise ValueError("já existe uma skill personalizada com esse nome")
    skill = {
        "id": uuid.uuid4().hex,
        "name": clean_name,
        "description": str(description or "").strip()[:300],
        "commands": clean_commands,
        "mode": "read_only",
        "created_at": _now(),
        "updated_at": _now(),
    }
    payload["skills"].append(skill)
    _write(payload, path)
    return skill


def delete_custom_skill(skill_id: str, *, path: Path | None = None) -> bool:
    payload = _read(path)
    before = len(payload["skills"])
    payload["skills"] = [item for item in payload["skills"] if item.get("id") != skill_id]
    if len(payload["skills"]) == before:
        return False
    _write(payload, path)
    return True
