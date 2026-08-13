from __future__ import annotations

from typing import Any

from app.core.settings import Settings, get_settings
from app.services.scheduled_agent_run_log import run_detail_map

_BUSY = {"queued", "running", "cancelling"}


def _current_execution(agent: dict[str, Any], *, settings: Settings) -> dict[str, Any] | None:
    job_id = str(agent.get("last_job_id") or "")
    if not job_id or str(agent.get("last_status") or "") not in _BUSY:
        return None
    from app.services.jobs import get_job

    job = get_job(job_id, settings=settings)
    if not job:
        return None
    state = str(job.get("status") or "")
    if state not in _BUSY:
        return None
    phase = dict(job.get("current_phase") or {})
    return {
        "job_id": job_id,
        "status": state,
        "percent": int(job.get("percent") or 0),
        "stage": phase.get("stage"),
        "detail": phase.get("detail") or "Execução em andamento.",
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
    }


def enrich_agent(agent: dict[str, Any], *, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    payload = dict(agent)
    history = [dict(item) for item in payload.get("history") or []]
    details = run_detail_map([str(item.get("job_id") or "") for item in history])
    for item in history:
        item.update(details.get(str(item.get("job_id") or ""), {}))
    payload["history"] = history
    payload["current_execution"] = _current_execution(payload, settings=settings)
    if payload["current_execution"]:
        payload["display_state"] = payload["current_execution"]["status"]
    elif not payload.get("last_job_id"):
        payload["display_state"] = "pending"
    else:
        payload["display_state"] = payload.get("last_status") or "pending"
    payload["last_result"] = history[0] if history else None
    return payload


def enrich_agents(agents: list[dict[str, Any]], *, settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    return [enrich_agent(item, settings=settings) for item in agents]
