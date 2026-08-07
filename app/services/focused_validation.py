from __future__ import annotations

import os
import shlex
from dataclasses import replace
from typing import Any, Callable

import httpx

from app.services import adaptive_tools, ai_providers, dynamic_agent, intelligent_agent, investigation_budget
from app.services.progress import report_progress


_INSTALLED = False


def _enabled() -> bool:
    value = os.getenv("AGENT_FAST_VALIDATION_ENABLED", "true")
    return value.strip().casefold() in {"1", "true", "yes", "on", "sim"}


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _seconds(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


class _FocusedSettings:
    """Proxy somente de leitura que reduz o trabalho sem alterar o .env do operador."""

    def __init__(self, base: Any):
        self._base = base

    def __getattr__(self, name: str) -> Any:
        if name == "agent_max_rounds":
            return min(
                int(getattr(self._base, name)),
                _integer("AGENT_FAST_MAX_ROUNDS", 2, minimum=1, maximum=5),
            )
        if name == "agent_max_commands":
            return min(
                int(getattr(self._base, name)),
                _integer("AGENT_FAST_MAX_COMMANDS", 10, minimum=5, maximum=30),
            )
        if name == "agent_tool_recommendation_limit":
            return min(
                int(getattr(self._base, name)),
                _integer("AGENT_FAST_RECOMMENDATION_LIMIT", 6, minimum=3, maximum=10),
            )
        if name == "agent_reasoning_max_provider_attempts":
            return min(
                int(getattr(self._base, name)),
                _integer("AGENT_FAST_PROVIDER_ATTEMPTS", 2, minimum=1, maximum=3),
            )
        return getattr(self._base, name)


def _focused_settings(getter: Callable[[], Any]) -> Callable[[], Any]:
    def wrapped() -> Any:
        settings = getter()
        return _FocusedSettings(settings) if _enabled() else settings

    return wrapped


def _focused_budget(getter: Callable[[], Any]) -> Callable[[], Any]:
    def wrapped() -> Any:
        config = getter()
        if not _enabled():
            return config
        return replace(
            config,
            max_total_commands=min(
                config.max_total_commands,
                _integer("AGENT_FAST_TOTAL_COMMANDS", 10, minimum=5, maximum=30),
            ),
            max_total_ai_calls=min(
                config.max_total_ai_calls,
                _integer("AGENT_FAST_AI_CALLS", 8, minimum=3, maximum=20),
            ),
            max_investigation_seconds=min(
                config.max_investigation_seconds,
                _integer("AGENT_FAST_INVESTIGATION_SECONDS", 240, minimum=60, maximum=900),
            ),
            max_host_seconds=min(
                config.max_host_seconds,
                _integer("AGENT_FAST_HOST_SECONDS", 180, minimum=30, maximum=600),
            ),
        )

    return wrapped


def _compact_snapshot_command() -> str:
    return r'''
set +e
printf 'SNAPSHOT_VERSION=2\n'
printf 'KERNEL=%s\n' "$(uname -srmo 2>/dev/null || uname -a 2>/dev/null)"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  printf 'OS_ID=%s\n' "${ID:-unknown}"
  printf 'OS_NAME=%s\n' "${PRETTY_NAME:-${NAME:-unknown}}"
fi
if command -v systemctl >/dev/null 2>&1; then printf 'INIT=systemd\n';
elif command -v rc-service >/dev/null 2>&1; then printf 'INIT=openrc\n';
else printf 'INIT=unknown\n'; fi
for bin in systemctl service rc-status journalctl ss netstat ps top free vmstat iostat df du find grep awk sed curl wget nc telnet ping traceroute tracepath docker podman rpm dpkg-query python3 java nginx apachectl httpd; do
  command -v "$bin" >/dev/null 2>&1 && printf 'BIN=%s\n' "$bin"
done
if command -v systemctl >/dev/null 2>&1; then
  systemctl list-units --type=service --state=running,failed --no-legend --no-pager 2>/dev/null |
    awk '{print "SERVICE=" $1 "|" $3 "|" $4}' | head -n 100
elif command -v rc-status >/dev/null 2>&1; then
  rc-status -a 2>/dev/null | sed 's/^[[:space:]]*/SERVICE=/' | head -n 100
fi
if command -v ss >/dev/null 2>&1; then
  ss -H -lntup 2>/dev/null | sed 's/^/LISTENER=/' | head -n 100
elif command -v netstat >/dev/null 2>&1; then
  netstat -lntup 2>/dev/null | sed '1,2d;s/^/LISTENER=/' | head -n 100
fi
if command -v docker >/dev/null 2>&1; then
  printf 'CONTAINER_RUNTIME=docker\n'
  docker ps --format 'CONTAINER=docker|{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null | head -n 80
elif command -v podman >/dev/null 2>&1; then
  printf 'CONTAINER_RUNTIME=podman\n'
  podman ps --format 'CONTAINER=podman|{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null | head -n 80
fi
df -PT 2>/dev/null | sed '1d;s/^/FILESYSTEM=/' | head -n 60
'''.strip()


def _focused_tool_resolver(base: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(name: str, arguments: dict[str, Any] | None = None):
        if not _enabled():
            return base(name, arguments)
        if name == "runtime.snapshot":
            return _compact_snapshot_command(), False, 15, "descobrir rapidamente as capacidades essenciais do alvo"
        if name == "service.search":
            query = adaptive_tools._text((arguments or {}).get("query"), "query")
            quoted = shlex.quote(query)
            command = (
                "if command -v systemctl >/dev/null 2>&1; then "
                f"result=\"$(systemctl list-units --type=service --all --no-pager --plain 2>/dev/null | grep -Fi -- {quoted} | head -n 30)\"; "
                "if [ -n \"$result\" ]; then printf '%s\\n' \"$result\"; else "
                f"systemctl list-unit-files --type=service --no-pager 2>/dev/null | grep -Fi -- {quoted} | head -n 30; fi; "
                "elif command -v rc-status >/dev/null 2>&1; then "
                f"rc-status -a 2>/dev/null | grep -Fi -- {quoted} | head -n 30; "
                "else "
                f"ps -ef | grep -Fi -- {quoted} | grep -v grep | head -n 30; fi"
            )
            return command, False, 12, f"localizar objetivamente o serviço {query}"
        return base(name, arguments)

    return wrapped


def _focused_openai_generate(self: Any, prompt: str):
    timeout = _seconds("AGENT_AI_REQUEST_TIMEOUT_SECONDS", 25.0, minimum=5.0, maximum=90.0)
    response = httpx.post(
        f"{self.base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {self.api_key}", **(self.headers or {})},
        json={
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
        },
        timeout=httpx.Timeout(timeout, connect=min(8.0, timeout)),
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"] or ""
    return ai_providers.parse_json(text), {
        "response_chars": len(text),
        "status_code": response.status_code,
        "timeout_seconds": timeout,
    }


def _focused_ollama_generate(self: Any, prompt: str):
    timeout = _seconds("AGENT_OLLAMA_REQUEST_TIMEOUT_SECONDS", 60.0, minimum=10.0, maximum=180.0)
    response = httpx.post(
        f"{self.base_url.rstrip('/')}/api/generate",
        json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
        timeout=httpx.Timeout(timeout, connect=min(8.0, timeout)),
    )
    response.raise_for_status()
    text = response.json().get("response") or ""
    return ai_providers.parse_json(text), {
        "response_chars": len(text),
        "status_code": response.status_code,
        "timeout_seconds": timeout,
    }


def _reasoning_percent(purpose: str) -> int:
    if purpose == "mission_interpretation":
        return 50
    if purpose.startswith("planning_round_"):
        return 52 + (int(purpose.rsplit("_", 1)[-1]) - 1) * 12
    if purpose.startswith("analysis_round_"):
        return 58 + (int(purpose.rsplit("_", 1)[-1]) - 1) * 12
    if purpose == "final_analysis":
        return 78
    if purpose == "final_critic":
        return 84
    return 76


def _focused_reasoning(base: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(prompt: str, purpose: str, provider_name: str | None = None):
        percent = min(84, _reasoning_percent(purpose))
        report_progress(
            "ai_reasoning",
            detail=f"IA processando etapa objetiva: {purpose}.",
            reasoning_purpose=purpose,
            percent=percent,
        )
        result, diagnostics = base(prompt, purpose, provider_name)
        if result and purpose.startswith("planning_round_"):
            max_tools = _integer("AGENT_FAST_TOOLS_PER_ROUND", 3, minimum=1, maximum=5)
            if isinstance(result.get("tools"), list):
                result["tools"] = result["tools"][:max_tools]
            if isinstance(result.get("commands"), list):
                result["commands"] = result["commands"][:max_tools]
        report_progress(
            "ai_reasoning",
            status="completed" if result else "failed",
            detail=(
                f"Etapa {purpose} concluída."
                if result
                else f"Etapa {purpose} não retornou decisão válida; usando fallback seguro."
            ),
            reasoning_purpose=purpose,
            percent=min(86, percent + 3),
        )
        return result, diagnostics

    return wrapped


def install_focused_validation() -> None:
    """Ativa coleta focada no processo web e, principalmente, no worker Redis."""
    global _INSTALLED
    if _INSTALLED:
        return

    dynamic_agent.get_settings = _focused_settings(dynamic_agent.get_settings)
    intelligent_agent.get_settings = _focused_settings(intelligent_agent.get_settings)
    investigation_budget.get_performance_config = _focused_budget(
        investigation_budget.get_performance_config
    )

    adaptive_tools.resolve_adaptive_tool = _focused_tool_resolver(
        adaptive_tools.resolve_adaptive_tool
    )

    ai_providers.OpenAICompatibleProvider.generate_json = _focused_openai_generate
    ai_providers.OllamaProvider.generate_json = _focused_ollama_generate

    focused_reasoning = _focused_reasoning(intelligent_agent.resilient_model_call)
    intelligent_agent.resilient_model_call = focused_reasoning
    dynamic_agent._model_call = focused_reasoning

    _INSTALLED = True
