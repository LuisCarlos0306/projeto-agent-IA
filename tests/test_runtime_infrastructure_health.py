from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.runtime_infrastructure_health import validate_runtime_infrastructure_from_env
from app.web_fast_validation import ASSET_VERSION, _enhanced_index


class FakeRedis:
    def ping(self):
        return True

    def close(self):
        return None


def write_env(path: Path, postgres_dsn: str | None = "sqlite+pysqlite:///:memory:") -> None:
    rows = []
    if postgres_dsn is not None:
        rows.append(f"POSTGRES_DSN={postgres_dsn}")
    rows.append("REDIS_URL=redis://:segredo-redis@127.0.0.1:6379/1")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_runtime_validation_reads_env_and_never_returns_credentials(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    write_env(env_path)

    with patch(
        "app.services.runtime_infrastructure_health.Redis.from_url",
        return_value=FakeRedis(),
    ):
        result = validate_runtime_infrastructure_from_env(env_path)

    assert result["status"] == "healthy"
    assert result["source"] == ".env"
    assert result["postgres"]["state"] == "available"
    assert result["redis"]["state"] == "available"
    rendered = repr(result)
    assert "segredo-redis" not in rendered
    assert "POSTGRES_DSN" not in rendered or "não está configurado" in rendered


def test_runtime_validation_reloads_env_on_every_request(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    write_env(env_path)

    with patch(
        "app.services.runtime_infrastructure_health.Redis.from_url",
        return_value=FakeRedis(),
    ):
        first = validate_runtime_infrastructure_from_env(env_path)
        write_env(env_path, postgres_dsn=None)
        second = validate_runtime_infrastructure_from_env(env_path)

    assert first["postgres"]["state"] == "available"
    assert second["postgres"]["state"] == "not_configured"
    assert second["redis"]["state"] == "available"


def test_runtime_health_ui_is_versioned_and_manual() -> None:
    html = _enhanced_index()
    script = (Path(__file__).resolve().parents[1] / "app" / "ui" / "runtime-health.js").read_text(encoding="utf-8")

    assert f"/ui/assets/runtime-health.js?v={ASSET_VERSION}" in html
    assert "Validar acesso pelo .env" in script
    assert "/ui/api/health/infrastructure-access" in script
    assert 'method: "POST"' in script
    assert '"X-Agent-UI": "1"' in script
    assert "Nenhuma senha, token ou DSN completo" in script
