from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.policies import EnvironmentType
from app.core.settings import get_settings
from app.services.custom_skill_jobs import enqueue_custom_skill
from app.services.custom_skill_registry import create_custom_skill, delete_custom_skill, get_custom_skill, list_custom_skills
from app.services.custom_skill_runner import run_custom_skill
from app.services.jobs import get_job
from app.web import _operator_name, _require_access, _require_mutation


router = APIRouter(prefix="/ui/api/custom-skills", tags=["interface-custom-skills"])


class CustomSkillCreatePayload(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)
    commands: list[str] = Field(min_length=1, max_length=20)


class CustomSkillRunPayload(BaseModel):
    target: str = Field(min_length=1, max_length=255)


@router.get("")
def list_skills(request: Request) -> dict[str, Any]:
    _require_access(request)
    return {"skills": list_custom_skills()}


@router.post("")
def create_skill(payload: CustomSkillCreatePayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        skill = create_custom_skill(payload.name, payload.commands, description=payload.description)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "created", "skill": skill, "operator": _operator_name()}


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        deleted = delete_custom_skill(skill_id)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="skill personalizada não encontrada")
    return {"status": "deleted", "skill_id": skill_id, "operator": _operator_name()}


@router.post("/{skill_id}/run")
def execute_skill(skill_id: str, payload: CustomSkillRunPayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    if get_custom_skill(skill_id) is None:
        raise HTTPException(status_code=404, detail="skill personalizada não encontrada")
    settings = get_settings()
    if settings.agent_execution_mode.strip().casefold() == "queue":
        try:
            return enqueue_custom_skill(
                skill_id,
                payload.target.strip(),
                metadata={"source": "web_ui_custom_skill", "operator": _operator_name()},
                settings=settings,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"fila indisponível: {type(exc).__name__}: {exc}") from exc
    try:
        result = run_custom_skill(
            skill_id,
            payload.target.strip(),
            environment=EnvironmentType.UNKNOWN,
            ssh_port=None,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"status": "completed", "job_type": "skill", "skill": f"custom:{skill_id}", "result": result}


@router.get("/jobs/{job_id}/status")
def skill_job(job_id: str, request: Request) -> dict[str, Any]:
    _require_access(request)
    try:
        result = get_job(job_id, settings=get_settings())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"fila indisponível: {type(exc).__name__}: {exc}") from exc
    if not result or result.get("job_type") != "skill" or not str(result.get("skill") or "").startswith("custom:"):
        raise HTTPException(status_code=404, detail="job de skill personalizada não encontrado ou expirado")
    return result
