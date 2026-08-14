from types import SimpleNamespace

from app.services.provider_registry import _builtin_specs, builtin_env_updates


def _settings(tmp_path):
    return SimpleNamespace(
        ai_settings_env_path=str(tmp_path / "missing.env"),
        ai_provider_registry_path=str(tmp_path / "providers.json"),
        gemini_model="gemini-test",
        gemini_free_models="gemini-test",
        groq_base_url="https://groq.invalid/openai/v1",
        groq_model="groq-test",
        deepseek_base_url="https://deepseek.invalid",
        deepseek_model="deepseek-test",
        deepseek_models="deepseek-test",
        openrouter_base_url="https://openrouter.invalid/api/v1",
        openrouter_model="openrouter/free",
        openrouter_app_name="Agent IA",
        openrouter_site_url=None,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="qwen-test",
        ollama_preferred_models="qwen-test",
        omniroute_base_url="http://127.0.0.1:20128/v1",
        omniroute_default_route="",
        omniroute_model="",
        omniroute_routes="",
    )


def test_native_catalog_contains_requested_cloud_and_local_providers(tmp_path) -> None:
    specs = {item.id: item for item in _builtin_specs(_settings(tmp_path))}
    expected = {
        "ollama", "groq", "gemini", "mistral", "sambanova", "openrouter",
        "cloudflare", "cohere", "huggingface", "vllm", "llamacpp", "cerebras",
    }
    assert expected.issubset(specs)
    assert specs["vllm"].source == "local"
    assert specs["llamacpp"].source == "local"
    assert specs["mistral"].base_url.endswith("/v1")
    assert specs["cloudflare"].credential_env == "CLOUDFLARE_API_TOKEN"
    assert specs["huggingface"].credential_env == "HF_TOKEN"


def test_native_providers_can_be_configured_without_secrets_in_git(tmp_path) -> None:
    settings = _settings(tmp_path)
    updates = builtin_env_updates(
        "mistral",
        api_key="runtime-only-key",
        default_model="mistral-small-latest",
        settings=settings,
    )
    assert updates["MISTRAL_API_KEY"] == "runtime-only-key"
    assert updates["MISTRAL_MODEL"] == "mistral-small-latest"

    local = builtin_env_updates(
        "vllm",
        base_url="http://127.0.0.1:8000/v1",
        default_model="local-model",
        settings=settings,
    )
    assert "VLLM_API_KEY" not in local
    assert local["VLLM_MODEL"] == "local-model"
