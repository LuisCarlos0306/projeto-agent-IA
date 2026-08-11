from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SKILL_CATALOG_PATH = Path(__file__).resolve().parents[1] / "ui" / "skills-catalog.json"


class SkillCatalogError(RuntimeError):
    """Raised when the local skill catalog is invalid."""


def load_skill_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = path or SKILL_CATALOG_PATH
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillCatalogError(f"não foi possível carregar o catálogo de skills: {exc}") from exc

    if payload.get("schema_version") != 1:
        raise SkillCatalogError("schema_version de skills não suportada")
    skills = payload.get("skills")
    if not isinstance(skills, list):
        raise SkillCatalogError("campo skills deve ser uma lista")

    seen: set[str] = set()
    for skill in skills:
        if not isinstance(skill, dict):
            raise SkillCatalogError("entrada de skill inválida")
        skill_id = str(skill.get("id") or "").strip()
        if not skill_id:
            raise SkillCatalogError("skill sem id")
        if skill_id in seen:
            raise SkillCatalogError(f"skill duplicada: {skill_id}")
        seen.add(skill_id)
        actions = skill.get("actions") or []
        if not isinstance(actions, list):
            raise SkillCatalogError(f"actions inválidas na skill {skill_id}")
        action_ids: set[str] = set()
        for action in actions:
            if not isinstance(action, dict):
                raise SkillCatalogError(f"ação inválida na skill {skill_id}")
            action_id = str(action.get("id") or "").strip()
            if not action_id:
                raise SkillCatalogError(f"ação sem id na skill {skill_id}")
            if action_id in action_ids:
                raise SkillCatalogError(f"ação duplicada na skill {skill_id}: {action_id}")
            action_ids.add(action_id)
            risk = action.get("risk")
            if risk not in {"read_only", "approval_required", "blocked"}:
                raise SkillCatalogError(f"risco inválido em {skill_id}.{action_id}: {risk}")

    return payload


def list_skills(*, include_planned: bool = True) -> list[dict[str, Any]]:
    skills = load_skill_catalog().get("skills") or []
    if include_planned:
        return list(skills)
    return [skill for skill in skills if skill.get("status") == "active"]


def get_skill(skill_id: str) -> dict[str, Any] | None:
    normalized = skill_id.strip()
    return next((skill for skill in list_skills() if skill.get("id") == normalized), None)


def get_skill_action(skill_id: str, action_id: str) -> dict[str, Any] | None:
    skill = get_skill(skill_id)
    if not skill:
        return None
    normalized = action_id.strip()
    return next((action for action in skill.get("actions") or [] if action.get("id") == normalized), None)


def action_requires_approval(skill_id: str, action_id: str) -> bool:
    action = get_skill_action(skill_id, action_id)
    if not action:
        raise LookupError(f"ação de skill não encontrada: {skill_id}.{action_id}")
    return action.get("risk") == "approval_required"


def action_is_read_only(skill_id: str, action_id: str) -> bool:
    action = get_skill_action(skill_id, action_id)
    if not action:
        raise LookupError(f"ação de skill não encontrada: {skill_id}.{action_id}")
    return action.get("risk") == "read_only" and bool(action.get("enabled"))
