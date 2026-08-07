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
    """Pontua a cobertura factual sem confundir execução concluída com certeza.

    Uma única evidência bem-sucedida produz confiança baixa/moderada; várias
    evidências independentes aumentam gradualmente a cobertura. Falhas e itens
    indisponíveis reduzem o valor. O objetivo é oferecer um piso determinístico
    quando a IA retorna 0, sem transformar sucesso operacional em 100% arbitrário.
    """
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
    """Calcula confiança validada usando IA + evidências persistidas.

    O valor devolvido pela IA é preservado quando existe, mas uma resposta 0 não
    apaga evidências reais já executadas. A crítica independente continua tendo
    poder de limitar o resultado. Casos inconclusivos nunca entram nas faixas de
    confiança média/alta apenas por terem comandos bem-sucedidos.
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
    factual_confidence = evidence_confidence(evidence)

    candidates = [value for value in (ai_confidence, round_confidence, factual_confidence) if value > 0]
    score = max(candidates) if candidates else 0

    critic = analysis.get("critic") if isinstance(analysis.get("critic"), dict) else {}
    critic_verdict = str(critic.get("verdict") or "").strip().casefold()
    critic_confidence = _percent(critic.get("confidence"))
    critic_coverage = _percent(critic.get("evidence_coverage"))

    if critic_verdict == "accept":
        limits = [value for value in (critic_confidence, critic_coverage) if value > 0]
        if limits and score > 0:
            score = min(score, *limits)
        elif limits:
            score = min(limits)
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
