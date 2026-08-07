from __future__ import annotations

import re
from typing import Any, Callable

from app.services import dynamic_agent, intelligent_agent, persistence, result_presentation


_INSTALLED = False
_LANGUAGE_DIRECTIVE = """
REGRA DE IDIOMA OBRIGATÓRIA:
- Todos os valores textuais destinados ao operador devem ser escritos em português do Brasil.
- Nunca escreva explicações, conclusões, causas, resumos, recomendações ou justificativas em inglês.
- Preserve sem tradução apenas nomes técnicos, comandos, parâmetros, IPs, hostnames, produtos, provedores, modelos e chaves JSON exigidas pelo contrato.
- Se uma evidência técnica estiver em inglês, explique o significado dela em português do Brasil.
""".strip()

_USER_TEXT_FIELDS = {
    "summary",
    "facts",
    "hypotheses",
    "confirmed_hypotheses",
    "discarded_hypotheses",
    "missing_information",
    "probable_cause",
    "conclusion",
    "recommendations",
    "next_safe_step",
    "reason",
    "risks",
    "supported_claims",
    "unsupported_claims",
    "contradictions",
    "missing_evidence",
    "statement",
    "round_summary",
    "reasoning_summary",
    "detail",
    "description",
    "evidence_reason",
    "recommendation",
}
_PRESERVE_FIELDS = {
    "command",
    "tool",
    "provider",
    "model",
    "hostname",
    "target",
    "vpn_ip",
    "id",
    "status",
    "verdict",
    "environment",
}
_ENGLISH_MARKERS = {
    "the", "this", "that", "with", "from", "because", "investigation", "evidence",
    "mission", "claim", "conclusion", "summary", "likely", "cause", "missing", "failed",
    "failure", "request", "client", "closed", "timeout", "timed", "available", "verified",
    "however", "overall", "remains", "insufficient", "coverage", "broad", "never", "executed",
}
_PORTUGUESE_MARKERS = {
    "o", "a", "os", "as", "com", "sem", "porque", "investigação", "evidência", "missão",
    "conclusão", "resumo", "causa", "falha", "solicitação", "cliente", "encerrado", "tempo",
    "disponível", "validada", "permanece", "insuficiente", "cobertura", "executado", "porém",
}


def _looks_english(text: str) -> bool:
    words = re.findall(r"[a-záàâãéêíóôõúç]+", text.casefold())
    if not words:
        return False
    english = sum(word in _ENGLISH_MARKERS for word in words)
    portuguese = sum(word in _PORTUGUESE_MARKERS for word in words)
    return english >= 3 and english > portuguese


def _translate_known_errors(text: str) -> str:
    replacements = (
        ("ReadTimeout: timed out", "tempo limite excedido ao consultar o provedor de IA"),
        ("ReadTimeout", "tempo limite de leitura excedido"),
        ("timed out", "tempo limite excedido"),
        (
            "Cannot send a request, as the client has been closed.",
            "não foi possível enviar a solicitação porque o cliente HTTP do provedor estava encerrado.",
        ),
        ("Cannot send a request", "não foi possível enviar a solicitação"),
        ("RuntimeError:", "erro de execução:"),
        ("planning_round_1", "planejamento da rodada 1"),
        ("planning_round_2", "planejamento da rodada 2"),
        ("analysis_round_1", "análise da rodada 1"),
        ("analysis_round_2", "análise da rodada 2"),
        ("final_analysis", "análise final"),
        ("final_critic", "revisão crítica final"),
        ("The investigation did not complete the mission because", "A investigação não concluiu a missão porque"),
        ("the 'nouuid' option was never verified", "a opção 'nouuid' não foi verificada"),
        ("However, the executed runtime snapshot evidence does prove that", "Porém, a evidência do snapshot executado comprova que"),
        ("is currently mounted", "está atualmente montado"),
        ("contradicting the broad claim that no sufficient evidence existed", "o que contradiz a afirmação ampla de que não havia evidência suficiente"),
        ("The final overall result remains inconclusive", "O resultado final permanece inconclusivo"),
        ("but the reasoning and evidence coverage are insufficient and partially inconsistent", "mas o raciocínio e a cobertura de evidências são insuficientes e parcialmente inconsistentes"),
    )
    output = text
    for source, target in replacements:
        output = output.replace(source, target)
    return output


def _fallback_ptbr(field: str) -> str:
    if field == "probable_cause":
        return (
            "A causa provável não pôde ser confirmada com segurança. "
            "Houve falha ou tempo limite em uma etapa da IA; as evidências técnicas coletadas devem ser consideradas antes de uma nova tentativa."
        )
    if field == "conclusion":
        return (
            "A investigação permanece inconclusiva porque a cobertura de evidências não foi suficiente para validar a conclusão com segurança."
        )
    if field == "summary":
        return "A investigação foi concluída sem evidência suficiente para uma conclusão segura."
    if field in {"reason", "round_summary", "reasoning_summary", "statement", "detail"}:
        return "A etapa não pôde ser apresentada integralmente em português; o resultado técnico foi mantido como inconclusivo."
    return "Informação técnica não apresentada porque não foi possível convertê-la com segurança para português do Brasil."


def _sanitize_text(value: str, field: str) -> str:
    translated = _translate_known_errors(value.strip())
    if not translated:
        return translated
    if _looks_english(translated):
        return _fallback_ptbr(field)
    return translated


def _sanitize_value(value: Any, field: str = "") -> Any:
    if field in _PRESERVE_FIELDS:
        return value
    if isinstance(value, str):
        return _sanitize_text(value, field) if field in _USER_TEXT_FIELDS else value
    if isinstance(value, list):
        return [_sanitize_value(item, field) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_value(item, str(key)) for key, item in value.items()}
    return value


def ensure_ptbr_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    output = _sanitize_value(dict(analysis))
    output["language"] = "pt-BR"
    return output


def ensure_ptbr_result(result: dict[str, Any]) -> dict[str, Any]:
    output = dict(result)
    analysis = ensure_ptbr_analysis(dict(output.get("analysis") or {}))
    analysis["ticket_report"] = result_presentation.build_ticket_report_ptbr(analysis)
    output["analysis"] = analysis
    if isinstance(output.get("review"), dict):
        output["review"] = _sanitize_value(dict(output["review"]), "review")
    if isinstance(output.get("corrections"), list):
        output["corrections"] = _sanitize_value(list(output["corrections"]), "corrections")
    output["status"] = analysis.get("status") or output.get("status")
    output["confidence"] = analysis.get("confidence") if analysis.get("confidence") is not None else output.get("confidence")
    return output


def _wrap_reasoning(base: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(prompt: str, purpose: str, provider_name: str | None = None):
        if _LANGUAGE_DIRECTIVE not in prompt:
            prompt = _LANGUAGE_DIRECTIVE + "\n\n" + prompt
        return base(prompt, purpose, provider_name)

    return wrapped


def _wrap_inconclusive(base: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return ensure_ptbr_analysis(base(*args, **kwargs))

    return wrapped


def _localize_without_external_ai(
    analysis: dict[str, Any],
    _result: dict[str, Any],
    _settings: Any,
) -> dict[str, Any]:
    """Evita uma segunda chamada de IA apenas para tradução e nunca devolve inglês ao operador."""
    return ensure_ptbr_analysis(analysis)


def _wrap_finalizer(base: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def wrapped(result: dict[str, Any], *, settings=None) -> dict[str, Any]:
        finalized = ensure_ptbr_result(base(result, settings=settings))
        result_presentation._sync_investigation(finalized, finalized["analysis"])
        return finalized

    return wrapped


def _wrap_history_reader(base: Callable[..., dict[str, Any] | None]) -> Callable[..., dict[str, Any] | None]:
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        result = base(*args, **kwargs)
        return ensure_ptbr_result(result) if isinstance(result, dict) else result

    return wrapped


def install_ptbr_guard() -> None:
    """Força pt-BR nos prompts, resultados atuais e histórico exibido ao operador."""
    global _INSTALLED
    if _INSTALLED:
        return

    reasoning = _wrap_reasoning(intelligent_agent.resilient_model_call)
    intelligent_agent.resilient_model_call = reasoning
    dynamic_agent._model_call = reasoning
    dynamic_agent._inconclusive = _wrap_inconclusive(dynamic_agent._inconclusive)
    result_presentation._translate_user_fields = _localize_without_external_ai
    result_presentation.finalize_result_presentation = _wrap_finalizer(
        result_presentation.finalize_result_presentation
    )
    persistence.get_investigation = _wrap_history_reader(persistence.get_investigation)
    _INSTALLED = True
