from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from redis import Redis
from sqlalchemy import text

from app.core.settings import Settings, get_settings
from app.db.base import SessionLocal


_POSTGRES_METRICS_QUERY = text(
    """
    SELECT
        current_database() AS database_name,
        current_setting('server_version') AS server_version,
        pg_database_size(current_database()) AS database_size_bytes,
        (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS active_connections,
        current_setting('max_connections')::integer AS max_connections,
        stats.xact_commit,
        stats.xact_rollback,
        stats.blks_read,
        stats.blks_hit,
        stats.temp_files,
        stats.temp_bytes,
        stats.deadlocks,
        stats.tup_returned,
        stats.tup_fetched
    FROM pg_stat_database AS stats
    WHERE stats.datname = current_database()
    """
)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _percent(numerator: Any, denominator: Any) -> float | None:
    total = _as_float(denominator)
    if total <= 0:
        return None
    return round((_as_float(numerator) / total) * 100, 2)


def _postgres_state(connection_percent: float | None, cache_hit_percent: float | None) -> str:
    if connection_percent is not None and connection_percent >= 90:
        return "degraded"
    if cache_hit_percent is not None and cache_hit_percent < 85:
        return "degraded"
    return "available"


def postgres_resource_metrics() -> dict[str, Any]:
    """Coleta somente estatísticas operacionais do banco da aplicação."""
    try:
        with SessionLocal() as session:
            row = session.execute(_POSTGRES_METRICS_QUERY).mappings().one()

        active_connections = _as_int(row.get("active_connections"))
        max_connections = _as_int(row.get("max_connections"))
        connection_percent = _percent(active_connections, max_connections)
        blocks_read = _as_int(row.get("blks_read"))
        blocks_hit = _as_int(row.get("blks_hit"))
        cache_hit_percent = _percent(blocks_hit, blocks_hit + blocks_read)
        if cache_hit_percent is None:
            cache_hit_percent = 100.0

        return {
            "state": _postgres_state(connection_percent, cache_hit_percent),
            "detail": "Métricas lidas de pg_stat_database e pg_stat_activity.",
            "database": str(row.get("database_name") or "aplicação"),
            "version": str(row.get("server_version") or "desconhecida"),
            "size_bytes": _as_int(row.get("database_size_bytes")),
            "connections": {
                "active": active_connections,
                "max": max_connections,
                "percent": connection_percent,
            },
            "cache_hit_percent": cache_hit_percent,
            "transactions": {
                "committed": _as_int(row.get("xact_commit")),
                "rolled_back": _as_int(row.get("xact_rollback")),
            },
            "temporary": {
                "files": _as_int(row.get("temp_files")),
                "bytes": _as_int(row.get("temp_bytes")),
            },
            "deadlocks": _as_int(row.get("deadlocks")),
            "rows": {
                "returned": _as_int(row.get("tup_returned")),
                "fetched": _as_int(row.get("tup_fetched")),
            },
        }
    except Exception as exc:
        return {
            "state": "unavailable",
            "detail": f"{type(exc).__name__}: não foi possível coletar as métricas do PostgreSQL.",
            "connections": {"active": None, "max": None, "percent": None},
        }


def _redis_state(memory_percent: float | None, blocked_clients: int, rejected_connections: int) -> str:
    if memory_percent is not None and memory_percent >= 90:
        return "degraded"
    if blocked_clients > 0 or rejected_connections > 0:
        return "degraded"
    return "available"


def redis_resource_metrics(settings: Settings) -> dict[str, Any]:
    """Coleta INFO do Redis sem retornar URL, senha ou qualquer credencial."""
    try:
        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        info = client.info()

        used_memory = _as_int(info.get("used_memory"))
        max_memory = _as_int(info.get("maxmemory"))
        memory_percent = _percent(used_memory, max_memory)
        blocked_clients = _as_int(info.get("blocked_clients"))
        rejected_connections = _as_int(info.get("rejected_connections"))
        keyspace_hits = _as_int(info.get("keyspace_hits"))
        keyspace_misses = _as_int(info.get("keyspace_misses"))
        total_keys = sum(
            _as_int(value.get("keys"))
            for key, value in info.items()
            if str(key).startswith("db") and isinstance(value, dict)
        )

        return {
            "state": _redis_state(memory_percent, blocked_clients, rejected_connections),
            "detail": "Métricas lidas pelo comando INFO do Redis.",
            "version": str(info.get("redis_version") or "desconhecida"),
            "mode": str(info.get("redis_mode") or "standalone"),
            "uptime_seconds": _as_int(info.get("uptime_in_seconds")),
            "memory": {
                "used_bytes": used_memory,
                "peak_bytes": _as_int(info.get("used_memory_peak")),
                "max_bytes": max_memory,
                "percent": memory_percent,
                "fragmentation_ratio": round(_as_float(info.get("mem_fragmentation_ratio")), 2),
            },
            "clients": {
                "connected": _as_int(info.get("connected_clients")),
                "blocked": blocked_clients,
                "rejected_connections": rejected_connections,
            },
            "operations_per_second": _as_int(info.get("instantaneous_ops_per_sec")),
            "keys": total_keys,
            "hit_rate_percent": _percent(keyspace_hits, keyspace_hits + keyspace_misses),
            "evicted_keys": _as_int(info.get("evicted_keys")),
            "expired_keys": _as_int(info.get("expired_keys")),
            "queue": {
                "name": settings.agent_queue_name,
                "depth": _as_int(client.llen(settings.agent_queue_name)),
                "execution_mode": settings.agent_execution_mode,
            },
        }
    except Exception as exc:
        return {
            "state": "unavailable",
            "detail": f"{type(exc).__name__}: não foi possível coletar as métricas do Redis.",
            "memory": {"used_bytes": None, "peak_bytes": None, "max_bytes": None, "percent": None},
            "clients": {"connected": None, "blocked": None, "rejected_connections": None},
            "queue": {
                "name": settings.agent_queue_name,
                "depth": None,
                "execution_mode": settings.agent_execution_mode,
            },
        }


def datastore_resource_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    postgres = postgres_resource_metrics()
    redis = redis_resource_metrics(settings)

    states = {postgres.get("state"), redis.get("state")}
    if "unavailable" in states:
        overall = "critical"
    elif "degraded" in states:
        overall = "attention"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "collected_at": datetime.now(UTC).isoformat(),
        "refresh_recommended_seconds": 15,
        "postgres": postgres,
        "redis": redis,
    }
