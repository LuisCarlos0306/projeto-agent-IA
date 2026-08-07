from __future__ import annotations

import uuid
from functools import wraps
from typing import Any, Callable

from app.db.base import SessionLocal
from app.db.models import InvestigationORM
from app.services.confidence_scoring import validated_confidence


_INSTALLED = False


def _persist_validated_analysis(investigation_id: str, analysis: dict[str, Any]) -> bool:
    try:
        identifier = uuid.UUID(str(investigation_id))
    except (TypeError, ValueError):
        return False

    with SessionLocal() as session:
        row = session.get(InvestigationORM, identifier)
        if not row:
            return False
        payload = dict(analysis or {})
        status = str(payload.get("status") or row.status or "inconclusive")
        confidence, basis = validated_confidence(
            status=status,
            analysis=payload,
            evidence=list(row.evidence or []),
            assessments=list(row.assessments or []),
        )
        payload["confidence"] = confidence
        payload["validated_confidence_basis"] = basis
        row.analysis = payload
        row.status = status
        row.confidence = confidence
        session.commit()
        return True


def _wrap_save(save_fn: Callable[..., str]) -> Callable[..., str]:
    @wraps(save_fn)
    def wrapped(*args: Any, **kwargs: Any) -> str:
        analysis = dict(kwargs.get("analysis") or {})
        status = str(kwargs.get("status") or analysis.get("status") or "inconclusive")
        confidence, basis = validated_confidence(
            status=status,
            analysis=analysis,
            evidence=list(kwargs.get("evidence") or []),
            assessments=list(kwargs.get("assessments") or []),
        )
        analysis["confidence"] = confidence
        analysis["validated_confidence_basis"] = basis
        kwargs["analysis"] = analysis
        kwargs["status"] = status
        kwargs["confidence"] = confidence
        return save_fn(*args, **kwargs)

    setattr(wrapped, "__agent_confidence_save__", True)
    return wrapped


def _wrap_update(update_fn: Callable[[str, dict[str, Any]], bool]) -> Callable[[str, dict[str, Any]], bool]:
    @wraps(update_fn)
    def wrapped(investigation_id: str, analysis: dict[str, Any]) -> bool:
        # Faz a atualização original primeiro para manter o contrato atual e,
        # em seguida, sincroniza as colunas indexadas com o JSON final.
        updated = update_fn(investigation_id, analysis)
        if not updated:
            return False
        return _persist_validated_analysis(investigation_id, analysis)

    setattr(wrapped, "__agent_confidence_update__", True)
    return wrapped


def install_confidence_instrumentation() -> None:
    """Mantém a confiança do resultado, histórico e análise sempre sincronizada."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import dynamic_agent, intelligent_agent

    if not getattr(dynamic_agent.save_investigation, "__agent_confidence_save__", False):
        dynamic_agent.save_investigation = _wrap_save(dynamic_agent.save_investigation)

    original_update = intelligent_agent.update_investigation_analysis
    if not getattr(original_update, "__agent_confidence_update__", False):
        wrapped_update = _wrap_update(original_update)
        intelligent_agent.update_investigation_analysis = wrapped_update
        # dynamic_agent importou a mesma função diretamente; atualize também a
        # referência local para aprovações e atualizações posteriores.
        dynamic_agent.update_investigation_analysis = wrapped_update

    _INSTALLED = True
