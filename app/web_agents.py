from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.settings import get_settings
from app.services.scheduled_agent_presenter import enrich_agent, enrich_agents
from app.services.scheduled_agent_registry import (
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    set_agent_enabled,
    update_agent,
)
from app.services.scheduled_agent_scheduler import enqueue_agent_job
from app.services.scheduled_agent_status import reconcile_agent_statuses
from app.web import _operator_name, _require_access, _require_mutation


router = APIRouter(prefix="/ui/api/agents", tags=["interface-agents"])
_BUSY_STATES = {"queued", "running", "cancelling"}


class AgentPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    skill_id: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=255)
    interval_minutes: int = Field(default=30, ge=1, le=10080)
    enabled: bool = True


class AgentTogglePayload(BaseModel):
    enabled: bool


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=503, detail=f"serviço de agentes indisponível: {type(exc).__name__}: {exc}")


def _current_agent(agent_id: str) -> dict[str, Any]:
    settings = get_settings()
    reconcile_agent_statuses(settings=settings)
    item = get_agent(agent_id)
    if item is None:
        raise HTTPException(status_code=404, detail="agente não encontrado")
    return enrich_agent(item, settings=settings)


@router.get("")
def agents(request: Request) -> dict[str, Any]:
    _require_access(request)
    try:
        settings = get_settings()
        reconcile_agent_statuses(settings=settings)
        return {"agents": enrich_agents(list_agents(), settings=settings)}
    except Exception as exc:
        raise _service_error(exc) from exc


@router.get("/{agent_id}")
def agent(agent_id: str, request: Request) -> dict[str, Any]:
    _require_access(request)
    try:
        return _current_agent(agent_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _service_error(exc) from exc


@router.post("")
def create(payload: AgentPayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        item = create_agent(
            payload.name,
            payload.skill_id,
            payload.target,
            payload.interval_minutes,
            enabled=payload.enabled,
            created_by=_operator_name(),
        )
        item = enrich_agent(item, settings=get_settings())
    except Exception as exc:
        raise _service_error(exc) from exc
    return {"status": "created", "agent": item}


@router.put("/{agent_id}")
def edit(agent_id: str, payload: AgentPayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        item = update_agent(
            agent_id,
            name=payload.name,
            skill_id=payload.skill_id,
            target=payload.target,
            interval_minutes=payload.interval_minutes,
            enabled=payload.enabled,
        )
        item = enrich_agent(item, settings=get_settings())
    except Exception as exc:
        raise _service_error(exc) from exc
    return {"status": "updated", "agent": item}


@router.post("/{agent_id}/toggle")
def toggle(agent_id: str, payload: AgentTogglePayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        item = set_agent_enabled(agent_id, payload.enabled)
        item = enrich_agent(item, settings=get_settings())
    except Exception as exc:
        raise _service_error(exc) from exc
    return {"status": "enabled" if payload.enabled else "disabled", "agent": item}


@router.post("/{agent_id}/start")
def start(agent_id: str, request: Request) -> dict[str, Any]:
    """Ativa o agendamento e dispara uma execução imediata pelo Play."""
    _require_mutation(request)
    try:
        current = _current_agent(agent_id)
        if str(current.get("display_state") or "") in _BUSY_STATES:
            raise HTTPException(status_code=409, detail="o agente já possui uma execução em andamento")
        set_agent_enabled(agent_id, True)
        queued = enqueue_agent_job(
            agent_id,
            source="manual",
            advance_schedule=False,
            settings=get_settings(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _service_error(exc) from exc
    return {
        **queued,
        "status": "queued",
        "scheduled": True,
        "agent": _current_agent(agent_id),
    }


@router.post("/{agent_id}/stop")
def stop(agent_id: str, request: Request) -> dict[str, Any]:
    """Para somente os próximos ciclos; uma execução já iniciada não é abortada."""
    _require_mutation(request)
    try:
        item = set_agent_enabled(agent_id, False)
        item = enrich_agent(item, settings=get_settings())
    except Exception as exc:
        raise _service_error(exc) from exc
    return {
        "status": "stopped",
        "agent": item,
        "running_execution_continues": str(item.get("display_state") or "") in _BUSY_STATES,
    }


@router.post("/{agent_id}/run-now")
def run_now(agent_id: str, request: Request) -> dict[str, Any]:
    """Execução única sem alterar o agendamento."""
    _require_mutation(request)
    try:
        current = _current_agent(agent_id)
        if str(current.get("display_state") or "") in _BUSY_STATES:
            raise HTTPException(status_code=409, detail="o agente já possui uma execução em andamento")
        queued = enqueue_agent_job(
            agent_id,
            source="manual",
            advance_schedule=False,
            settings=get_settings(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _service_error(exc) from exc
    return queued


@router.delete("/{agent_id}")
def remove(agent_id: str, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        deleted = delete_agent(agent_id)
    except Exception as exc:
        raise _service_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="agente não encontrado")
    return {"status": "deleted", "agent_id": agent_id}
