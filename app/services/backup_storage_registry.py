from __future__ import annotations

import json
import os
from pathlib import Path
import posixpath
import tempfile
from typing import Any

from app.core.settings import PROJECT_ROOT


DEFAULT_MOUNT_SCRIPT = "/db/backup/scripts/mount.sh"
_ALLOWED_ROLES = {"principal", "redundancia", "externa", "outro"}


def _registry_path() -> Path:
    configured = os.getenv("AGENT_BACKUP_STORAGE_MAP_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    install_root = os.getenv("AGENT_INSTALL_ROOT", "").strip()
    if install_root:
        return Path(install_root).expanduser() / "data" / "backup-storage-map.json"
    return PROJECT_ROOT / "data" / "backup-storage-map.json"


def _safe_absolute_path(value: str, field: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field} é obrigatório")
    if any(char in raw for char in ("\x00", "\n", "\r")):
        raise ValueError(f"{field} contém caracteres inválidos")
    if not raw.startswith("/"):
        raise ValueError(f"{field} deve ser um caminho absoluto")
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/"):
        raise ValueError(f"{field} inválido")
    return normalized


def _normalize_target(value: str) -> str:
    target = str(value or "").strip()
    if not target:
        raise ValueError("servidor/IP é obrigatório")
    if any(char in target for char in ("\x00", "\n", "\r", "/", "\\")):
        raise ValueError("servidor/IP contém caracteres inválidos")
    return target


def _normalize_unit(row: dict[str, Any], index: int) -> dict[str, Any]:
    mount_point = _safe_absolute_path(str(row.get("mount_point") or ""), f"unidade {index}: ponto de montagem")
    role = str(row.get("role") or "outro").strip().casefold()
    if role not in _ALLOWED_ROLES:
        raise ValueError(f"unidade {index}: função inválida")
    label = str(row.get("label") or mount_point).strip()[:120] or mount_point
    min_free_percent = max(1, min(99, int(row.get("min_free_percent") or 20)))
    return {
        "mount_point": mount_point,
        "role": role,
        "label": label,
        "min_free_percent": min_free_percent,
    }


def normalize_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    target = _normalize_target(str(payload.get("target") or ""))
    mount_script = _safe_absolute_path(str(payload.get("mount_script") or DEFAULT_MOUNT_SCRIPT), "script de montagem")
    if mount_script != DEFAULT_MOUNT_SCRIPT:
        raise ValueError(f"nesta etapa o único script permitido é {DEFAULT_MOUNT_SCRIPT}")

    raw_units = payload.get("units") or []
    if not isinstance(raw_units, list) or not raw_units:
        raise ValueError("informe pelo menos uma unidade para o servidor")
    units = [_normalize_unit(dict(row), index + 1) for index, row in enumerate(raw_units) if isinstance(row, dict)]
    if not units:
        raise ValueError("informe pelo menos uma unidade válida para o servidor")
    points = [row["mount_point"] for row in units]
    if len(points) != len(set(points)):
        raise ValueError("não repita o mesmo ponto de montagem")

    aliases = []
    for value in payload.get("aliases") or []:
        alias = str(value or "").strip()
        if alias and alias.casefold() != target.casefold() and alias.casefold() not in {item.casefold() for item in aliases}:
            aliases.append(alias[:255])

    return {
        "target": target,
        "aliases": aliases,
        "mount_script": mount_script,
        "units": units,
    }


def _load_payload() -> dict[str, Any]:
    path = _registry_path()
    if not path.is_file():
        return {"version": 1, "servers": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "servers": []}
    if not isinstance(payload, dict):
        return {"version": 1, "servers": []}
    rows = payload.get("servers")
    return {"version": 1, "servers": rows if isinstance(rows, list) else []}


def _atomic_write(payload: dict[str, Any]) -> Path:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def list_mappings() -> list[dict[str, Any]]:
    output = []
    for row in _load_payload().get("servers", []):
        if not isinstance(row, dict):
            continue
        try:
            output.append(normalize_mapping(row))
        except (TypeError, ValueError):
            continue
    return output


def get_mapping(reference: str) -> dict[str, Any] | None:
    needle = str(reference or "").strip().casefold()
    if not needle:
        return None
    for row in list_mappings():
        names = [row["target"], *(row.get("aliases") or [])]
        if needle in {str(name).casefold() for name in names}:
            return row
    return None


def save_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    mapping = normalize_mapping(payload)
    rows = list_mappings()
    key = mapping["target"].casefold()
    rows = [row for row in rows if str(row.get("target") or "").casefold() != key]
    rows.append(mapping)
    rows.sort(key=lambda row: str(row.get("target") or "").casefold())
    _atomic_write({"version": 1, "servers": rows})
    return mapping
