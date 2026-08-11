from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.settings import PROJECT_ROOT


def _safe_location(value: str, *, kind: str) -> dict[str, Any]:
    try:
        url = make_url(value)
    except Exception:
        return {"host": None, "port": None, "database": None}
    if kind == "redis":
        return {
            "host": url.host,
            "port": url.port,
            "database": (url.database or "0").lstrip("/") if isinstance(url.database, str) else url.database,
        }
    return {
        "host": url.host,
        "port": url.port,
        "database": url.database,
    }


def _postgres_health(dsn: str) -> dict[str, Any]:
    if not dsn:
        return {
            "state": "not_configured",
            "detail": "POSTGRES_DSN não está configurado no .env.",
            "location": {},
        }

    engine = None
    try:
        url = make_url(dsn)
        connect_args = {"connect_timeout": 5} if url.drivername.startswith("postgresql") else {}
        engine = create_engine(dsn, pool_pre_ping=True, connect_args=connect_args)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
        return {
            "state": "available",
            "detail": "Credenciais do .env aceitaram conexão e SELECT 1 no PostgreSQL.",
            "location": _safe_location(dsn, kind="postgres"),
        }
    except Exception as exc:
        return {
            "state": "unavailable",
            "detail": f"{type(exc).__name__}: falha ao validar o PostgreSQL com POSTGRES_DSN do .env.",
            "location": _safe_location(dsn, kind="postgres"),
        }
    finally:
        if engine is not None:
            engine.dispose()


def _redis_health(url: str) -> dict[str, Any]:
    if not url:
        return {
            "state": "not_configured",
            "detail": "REDIS_URL não está configurado no .env.",
            "location": {},
        }

    client = None
    try:
        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
        return {
            "state": "available",
            "detail": "Credenciais do .env aceitaram PING no Redis.",
            "location": _safe_location(url, kind="redis"),
        }
    except Exception as exc:
        return {
            "state": "unavailable",
            "detail": f"{type(exc).__name__}: falha ao validar o Redis com REDIS_URL do .env.",
            "location": _safe_location(url, kind="redis"),
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def validate_runtime_infrastructure_from_env(env_path: Path | None = None) -> dict[str, Any]:
    """Valida somente a persistência interna do Agent IA usando o .env atual.

    O arquivo é relido a cada chamada. Nenhuma credencial é retornada e nenhuma
    conexão com banco de cliente é aberta por este diagnóstico.
    """
    path = Path(env_path or (PROJECT_ROOT / ".env")).expanduser()
    checked_at = datetime.now(timezone.utc).isoformat()

    if not path.is_file():
        return {
            "status": "critical",
            "source": ".env",
            "checked_at": checked_at,
            "postgres": {
                "state": "not_configured",
                "detail": "Arquivo .env não encontrado para validar POSTGRES_DSN.",
                "location": {},
            },
            "redis": {
                "state": "not_configured",
                "detail": "Arquivo .env não encontrado para validar REDIS_URL.",
                "location": {},
            },
        }

    values = dotenv_values(path)
    postgres = _postgres_health(str(values.get("POSTGRES_DSN") or "").strip())
    redis = _redis_health(str(values.get("REDIS_URL") or "").strip())

    states = {postgres["state"], redis["state"]}
    status = "healthy" if states == {"available"} else "critical" if "unavailable" in states else "attention"
    return {
        "status": status,
        "source": ".env",
        "checked_at": checked_at,
        "postgres": postgres,
        "redis": redis,
    }
