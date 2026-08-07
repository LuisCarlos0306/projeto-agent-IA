from __future__ import annotations

from pathlib import Path

from app.web_fast_validation import ASSET_VERSION, _enhanced_index, focused_validation_payload


ROOT = Path(__file__).resolve().parents[1]


def test_enhanced_index_loads_versioned_assets_and_disables_stale_page_cache() -> None:
    html = _enhanced_index()

    assert f"/ui/assets/fast-validation-ui.css?v={ASSET_VERSION}" in html
    assert f"/ui/assets/fast-validation-ui.js?v={ASSET_VERSION}" in html
    assert f"/ui/assets/cyber-theme.css?v={ASSET_VERSION}" in html
    assert html.count("fast-validation-ui.css") == 1
    assert html.count("fast-validation-ui.js") == 1
    assert 'id="agent-cyber-theme-inline"' in html
    assert 'class="brand-ai-logo"' in html
    assert '>AI</div>' not in html


def test_fast_validation_payload_uses_objective_defaults(monkeypatch) -> None:
    for name in (
        "AGENT_FAST_VALIDATION_ENABLED",
        "AGENT_FAST_MAX_ROUNDS",
        "AGENT_FAST_TOOLS_PER_ROUND",
        "AGENT_FAST_TOTAL_COMMANDS",
        "AGENT_FAST_AI_CALLS",
        "AGENT_FAST_INVESTIGATION_SECONDS",
        "AGENT_FAST_HOST_SECONDS",
        "AGENT_AI_REQUEST_TIMEOUT_SECONDS",
        "AGENT_JOB_HARD_TIMEOUT_SECONDS",
        "AGENT_JOB_HARD_TIMEOUT_GRACE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    payload = focused_validation_payload()

    assert payload == {
        "enabled": True,
        "ui_version": ASSET_VERSION,
        "max_rounds": 2,
        "tools_per_round": 3,
        "max_commands": 10,
        "max_ai_calls": 8,
        "max_investigation_seconds": 240,
        "hard_timeout_seconds": 255,
        "max_host_seconds": 180,
        "ai_request_timeout_seconds": 25.0,
    }


def test_fast_validation_payload_clamps_unsafe_values(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_FAST_MAX_ROUNDS", "99")
    monkeypatch.setenv("AGENT_FAST_TOOLS_PER_ROUND", "0")
    monkeypatch.setenv("AGENT_FAST_INVESTIGATION_SECONDS", "9999")
    monkeypatch.setenv("AGENT_JOB_HARD_TIMEOUT_SECONDS", "99999")
    monkeypatch.setenv("AGENT_AI_REQUEST_TIMEOUT_SECONDS", "1")

    payload = focused_validation_payload()

    assert payload["max_rounds"] == 5
    assert payload["tools_per_round"] == 1
    assert payload["max_investigation_seconds"] == 900
    assert payload["hard_timeout_seconds"] == 1800
    assert payload["ai_request_timeout_seconds"] == 5.0


def test_web_registers_enhanced_ui_before_base_interface() -> None:
    source = (ROOT / "app" / "web_main.py").read_text(encoding="utf-8")

    assert "from app.web_fast_validation import register_fast_validation_ui" in source
    assert source.index("register_fast_validation_ui(app)") < source.index("register_ui(app)")


def test_frontend_translates_reasoning_and_shows_real_limits() -> None:
    script = (ROOT / "app" / "ui" / "fast-validation-ui.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "app" / "ui" / "fast-validation-ui.css").read_text(encoding="utf-8")

    assert 'planning_round_1: "Planejando a coleta essencial"' in script
    assert 'final_critic: "Validando a conclusão com a IA revisora"' in script
    assert 'fetch("/ui/api/fast-validation", { cache: "no-store" })' in script
    assert "Modo rápido ativo" in script
    assert "Limite restante" in script
    assert ".fast-validation-status" in stylesheet
    assert '[data-state="warning"]' in stylesheet
    assert '[data-state="limit"]' in stylesheet
