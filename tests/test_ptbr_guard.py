from __future__ import annotations

from app.services.ptbr_guard import _LANGUAGE_DIRECTIVE, _wrap_reasoning, ensure_ptbr_analysis, ensure_ptbr_result


def test_ptbr_guard_converts_timeout_diagnostics_from_operator_result() -> None:
    analysis = {
        "status": "inconclusive",
        "confidence": 0,
        "summary": "A IA não conseguiu concluir a investigação com evidência suficiente.",
        "probable_cause": (
            "planning_round_1: omniroute: ReadTimeout: timed out | "
            "gemini: RuntimeError: Cannot send a request, as the client has been closed."
        ),
        "conclusion": (
            "The investigation did not complete the mission because the 'nouuid' option was never verified. "
            "However, the executed runtime snapshot evidence does prove that /mnt/backup_check is currently mounted. "
            "The final overall result remains inconclusive, but the reasoning and evidence coverage are insufficient and partially inconsistent."
        ),
        "recommendations": ["Executar novamente após estabilizar o provedor de IA."],
    }

    localized = ensure_ptbr_analysis(analysis)

    assert localized["language"] == "pt-BR"
    assert "ReadTimeout" not in localized["probable_cause"]
    assert "Cannot send a request" not in localized["probable_cause"]
    assert "tempo limite" in localized["probable_cause"].lower()
    assert "The investigation" not in localized["conclusion"]
    assert "However" not in localized["conclusion"]
    assert "The final" not in localized["conclusion"]
    assert "investigação" in localized["conclusion"].lower()


def test_ptbr_guard_uses_safe_portuguese_fallback_for_unknown_english_message() -> None:
    localized = ensure_ptbr_analysis(
        {
            "status": "inconclusive",
            "confidence": 10,
            "summary": "The investigation failed because this evidence was missing and the service was unavailable.",
            "probable_cause": "The likely cause is unavailable because the request failed with missing evidence.",
            "conclusion": "This conclusion remains insufficient because the evidence coverage is missing.",
        }
    )

    assert "The investigation" not in localized["summary"]
    assert "likely cause" not in localized["probable_cause"]
    assert "This conclusion" not in localized["conclusion"]
    assert localized["summary"].startswith("A investigação")
    assert localized["probable_cause"].startswith("A causa provável")
    assert localized["conclusion"].startswith("A investigação permanece")


def test_ptbr_guard_sanitizes_review_and_corrections() -> None:
    result = ensure_ptbr_result(
        {
            "status": "inconclusive",
            "confidence": 20,
            "analysis": {
                "status": "inconclusive",
                "confidence": 20,
                "summary": "Resumo já em português.",
                "probable_cause": "Causa ainda não confirmada.",
                "conclusion": "Conclusão ainda não confirmada.",
            },
            "review": {
                "reason": "The review failed because this evidence was missing and the conclusion is insufficient."
            },
            "corrections": [
                {
                    "description": "This recommendation should restart the service because the issue was verified.",
                    "tool": "systemd.recover_unit",
                }
            ],
        }
    )

    assert "The review" not in result["review"]["reason"]
    assert "This recommendation" not in result["corrections"][0]["description"]
    assert result["corrections"][0]["tool"] == "systemd.recover_unit"


def test_reasoning_wrapper_prepends_mandatory_language_rule() -> None:
    received = {}

    def fake(prompt: str, purpose: str, provider_name: str | None = None):
        received["prompt"] = prompt
        received["purpose"] = purpose
        received["provider"] = provider_name
        return {"ok": True}, {"success": True}

    wrapped = _wrap_reasoning(fake)
    wrapped("PROMPT ORIGINAL", "final_analysis", "omniroute")

    assert received["prompt"].startswith(_LANGUAGE_DIRECTIVE)
    assert "PROMPT ORIGINAL" in received["prompt"]
    assert received["purpose"] == "final_analysis"
    assert received["provider"] == "omniroute"
