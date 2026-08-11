from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


_PROVIDER_ENV_TEST_MODULES = {
    "test_ai_source_selection.py",
    "test_provider_preflight.py",
    "test_safe_autopilot.py",
}


@pytest.fixture(autouse=True)
def isolate_unit_tests_from_local_runtime(request, monkeypatch, tmp_path: Path):
    """Evita que .env e containers reais alterem testes unitários determinísticos."""
    filename = Path(str(request.fspath)).name

    if filename in _PROVIDER_ENV_TEST_MODULES:
        for name in (
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "DEEPSEEK_API_KEY",
            "OPENROUTER_API_KEY",
            "OMNIROUTE_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("AI_SETTINGS_ENV_PATH", str(tmp_path / "isolated-provider.env"))

    if filename == "test_portable_installer.py":
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir(exist_ok=True)
        monkeypatch.setenv("PATH", str(empty_bin))
