from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services import focused_validation
from app.services.performance_config import get_performance_config


ROOT = Path(__file__).resolve().parents[1]


def test_focused_settings_caps_rounds_commands_and_provider_attempts(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_FAST_VALIDATION_ENABLED", "true")
    base = SimpleNamespace(
        agent_max_rounds=5,
        agent_max_commands=20,
        agent_tool_recommendation_limit=10,
        agent_reasoning_max_provider_attempts=3,
        untouched="ok",
    )

    settings = focused_validation._FocusedSettings(base)

    assert settings.agent_max_rounds == 2
    assert settings.agent_max_commands == 10
    assert settings.agent_tool_recommendation_limit == 6
    assert settings.agent_reasoning_max_provider_attempts == 2
    assert settings.untouched == "ok"


def test_focused_budget_has_short_global_and_host_limits(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_FAST_VALIDATION_ENABLED", "true")
    wrapped = focused_validation._focused_budget(get_performance_config)

    config = wrapped()

    assert config.max_total_commands <= 10
    assert config.max_total_ai_calls <= 8
    assert config.max_investigation_seconds <= 240
    assert config.max_host_seconds <= 180


def test_compact_snapshot_avoids_full_binary_and_container_inventory(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_FAST_VALIDATION_ENABLED", "true")
    resolver = focused_validation._focused_tool_resolver(lambda name, arguments=None: (name, False, 99, "base"))

    command, sudo, timeout, purpose = resolver("runtime.snapshot", {})

    assert sudo is False
    assert timeout == 15
    assert "for d in /usr/local/sbin" not in command
    assert "docker ps -a" not in command
    assert "--state=running,failed" in command
    assert "capacidades essenciais" in purpose


def test_service_search_uses_short_output_and_fallback_only_when_needed(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_FAST_VALIDATION_ENABLED", "true")
    resolver = focused_validation._focused_tool_resolver(lambda name, arguments=None: (name, False, 99, "base"))

    command, sudo, timeout, purpose = resolver("service.search", {"query": "nouuid"})

    assert sudo is False
    assert timeout == 12
    assert "head -n 30" in command
    assert 'if [ -n "$result" ]' in command
    assert "list-unit-files" in command
    assert "nouuid" in purpose


def test_openai_compatible_timeout_is_bounded(monkeypatch) -> None:
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"done": true}'}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setenv("AGENT_AI_REQUEST_TIMEOUT_SECONDS", "17")
    monkeypatch.setattr(focused_validation.httpx, "post", fake_post)
    provider = SimpleNamespace(
        base_url="http://127.0.0.1:20128/v1",
        api_key="test",
        headers=None,
        model="auto/coding",
    )

    result, metadata = focused_validation._focused_openai_generate(provider, "teste")

    assert result == {"done": True}
    assert metadata["timeout_seconds"] == 17.0
    assert captured["timeout"].read == 17.0
    assert captured["timeout"].connect == 8.0


def test_worker_and_web_install_focus_before_ai_instrumentation() -> None:
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_main.py").read_text(encoding="utf-8")

    for source in (worker, web):
        assert "install_focused_validation()" in source
        assert source.index("install_focused_validation()") < source.index("install_ai_instrumentation()")
