from __future__ import annotations

from typing import Any


_TERMINAL_SUCCESS = {"executed", "success", "completed", "ok", "healthy", "available"}
_TERMINAL_FAILURE = {"failed", "error", "blocked", "unavailable", "timeout", "cancelled"}
_CONCLUSIVE = {"healthy", "attention", "critical"}


def _percent(value: Any) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


def _evidence_counts(evidence: list[dict[str, Any]]) -> tuple[int, int, int]:
    successful = 0
    failed = 0
    for item in evidence:
        status = str(item.get("status") or "").strip().casefold()
        exit_code = item.get("exit_code")
        if status in _TERMINAL_SUCCESS or exit_code == 0:
            successful += 1
        elif status in _TERMINAL_FAILURE or (isinstance(exit_code, int) and exit_code != 0):
            failed += 1
    return len(evidence), successful, failed


def evidence_confidence(evidence: list[dict[str, Any]]) -> int:
    """Pontua a cobertura factual sem confundir execução concluída com certeza."""
    total, successful, failed = _evidence_counts(evidence)
    if total == 0 or successful == 0:
        return 0
    base = 20 + min(successful, 5) * 15
    ratio = successful / max(1, successful + failed)
    score = round(base * (0.65 + 0.35 * ratio))
    return max(1, min(90, score))


def validated_confidence(
    *,
    status: str | None,
    analysis: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None,
    assessments: list[dict[str, Any]] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Calcula confiança validada usando raciocínio da IA e cobertura factual.

    A confiança cognitiva é ponderada pela evidência executada. Uma IA muito
    confiante sem evidência permanece na faixa baixa. Quando a IA retorna zero,
    evidências reais ainda podem produzir um valor útil. A crítica independente
    continua podendo limitar o resultado final.
    """
    analysis = dict(analysis or {})
    evidence = list(evidence or [])
    assessments = list(assessments or [])
    normalized_status = str(status or analysis.get("status") or "inconclusive").strip().casefold()

    ai_confidence = _percent(analysis.get("confidence"))
    assessment_confidences = [
        _percent(item.get("confidence"))
        for item in assessments
        if isinstance(item, dict) and _percent(item.get("confidence")) > 0
    ]
    round_confidence = assessment_confidences[-1] if assessment_confidences else 0
    cognitive_confidence = max(ai_confidence, round_confidence)
    factual_confidence = evidence_confidence(evidence)

    if cognitive_confidence > 0 and factual_confidence > 0:
        score = round((cognitive_confidence * 0.55) + (factual_confidence * 0.45))
    elif factual_confidence > 0:
        score = factual_confidence
    elif cognitive_confidence > 0:
        # Sem evidência, a confiança da IA ainda é informativa, mas não validada.
        score = min(cognitive_confidence, 39)
    else:
        score = 0

    critic = analysis.get("critic") if isinstance(analysis.get("critic"), dict) else {}
    critic_verdict = str(critic.get("verdict") or "").strip().casefold()
    critic_confidence = _percent(critic.get("confidence"))
    critic_coverage = _percent(critic.get("evidence_coverage"))

    if critic_verdict == "accept":
        limits = [value for value in (critic_confidence, critic_coverage) if value > 0]
        if limits and score > 0:
            score = min(score, *limits)
        elif limits and factual_confidence > 0:
            score = min(factual_confidence, *limits)
    elif critic_verdict in {"insufficient", "contradictory"}:
        limits = [39]
        if critic_confidence > 0:
            limits.append(critic_confidence)
        if critic_coverage > 0:
            limits.append(critic_coverage)
        score = min(score or factual_confidence, *limits)

    if normalized_status not in _CONCLUSIVE:
        score = min(score, 39)

    total, successful, failed = _evidence_counts(evidence)
    basis = {
        "version": 1,
        "ai_confidence": ai_confidence,
        "round_confidence": round_confidence,
        "cognitive_confidence": cognitive_confidence,
        "evidence_confidence": factual_confidence,
        "evidence_total": total,
        "evidence_successful": successful,
        "evidence_failed": failed,
        "critic_verdict": critic_verdict or None,
        "critic_confidence": critic_confidence,
        "critic_coverage": critic_coverage,
        "validated_confidence": int(score),
    }
    return int(score), basis
