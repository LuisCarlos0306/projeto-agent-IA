from __future__ import annotations

import json
from types import SimpleNamespace

from app.services import datastore_metrics


class _FakeResult:
    def __init__(self, row: dict):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class _FakeSession:
    def __init__(self, row: dict):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, _query):
        return _FakeResult(self.row)


class _FakeRedis:
    def ping(self):
        return True

    def info(self):
        return {
            "redis_version": "7.2.0",
            "redis_mode": "standalone",
            "uptime_in_seconds": 86400,
            "used_memory": 256 * 1024 * 1024,
            "used_memory_peak": 300 * 1024 * 1024,
            "maxmemory": 1024 * 1024 * 1024,
            "mem_fragmentation_ratio": 1.15,
            "connected_clients": 12,
            "blocked_clients": 0,
            "rejected_connections": 0,
            "instantaneous_ops_per_sec": 44,
            "keyspace_hits": 900,
            "keyspace_misses": 100,
            "evicted_keys": 2,
            "expired_keys": 9,
            "db0": {"keys": 18, "expires": 4},
            "db1": {"keys": 7, "expires": 0},
        }

    def llen(self, _queue_name):
        return 3


def _settings():
    return SimpleNamespace(
        redis_url="redis://:segredo@127.0.0.1:6379/1",
        agent_queue_name="agent-ia:jobs",
        agent_execution_mode="queue",
    )


def test_postgres_resource_metrics(monkeypatch):
    row = {
        "database_name": "agent_ia",
        "server_version": "16.4",
        "database_size_bytes": 2 * 1024 * 1024,
        "active_connections": 8,
        "max_connections": 100,
        "xact_commit": 1200,
        "xact_rollback": 5,
        "blks_read": 20,
        "blks_hit": 980,
        "temp_files": 2,
        "temp_bytes": 4096,
        "deadlocks": 0,
        "tup_returned": 5000,
        "tup_fetched": 4500,
    }
    monkeypatch.setattr(datastore_metrics, "SessionLocal", lambda: _FakeSession(row))

    result = datastore_metrics.postgres_resource_metrics()

    assert result["state"] == "available"
    assert result["database"] == "agent_ia"
    assert result["connections"] == {"active": 8, "max": 100, "percent": 8.0}
    assert result["cache_hit_percent"] == 98.0
    assert result["transactions"]["committed"] == 1200


def test_redis_resource_metrics_do_not_expose_credentials(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(datastore_metrics.Redis, "from_url", lambda *_args, **_kwargs: fake_redis)

    result = datastore_metrics.redis_resource_metrics(_settings())
    serialized = json.dumps(result)

    assert result["state"] == "available"
    assert result["memory"]["percent"] == 25.0
    assert result["keys"] == 25
    assert result["queue"]["depth"] == 3
    assert "segredo" not in serialized
    assert "redis://" not in serialized


def test_snapshot_marks_unavailable_datastore_as_critical(monkeypatch):
    monkeypatch.setattr(
        datastore_metrics,
        "postgres_resource_metrics",
        lambda: {"state": "available", "connections": {"percent": 10}},
    )
    monkeypatch.setattr(
        datastore_metrics,
        "redis_resource_metrics",
        lambda _settings: {"state": "unavailable", "memory": {"percent": None}},
    )

    result = datastore_metrics.datastore_resource_snapshot(_settings())

    assert result["status"] == "critical"
    assert result["refresh_recommended_seconds"] == 15
    assert result["collected_at"].endswith("+00:00")
