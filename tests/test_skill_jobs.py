import json
from types import SimpleNamespace
from unittest.mock import patch

from app.core.policies import EnvironmentType
from app.services.jobs import enqueue_backup_validation, get_job, run_worker_once
from app.services.progress import report_progress


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.queue = []

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def rpush(self, key, value):
        self.queue.append((key, value))

    def blpop(self, key, timeout=0):
        if not self.queue:
            return None
        return self.queue.pop(0)


def settings():
    return SimpleNamespace(
        redis_url="redis://invalid/1",
        agent_queue_name="agent-ia:jobs",
        agent_result_prefix="agent-ia:result:",
        agent_worker_name="vpn-test",
        agent_job_ttl_seconds=3600,
        agent_queue_block_seconds=0,
        ai_provider="gemini",
    )


def test_backup_validation_is_enqueued_as_skill_job():
    fake = FakeRedis()
    config = settings()
    with patch("app.services.jobs._redis", return_value=fake):
        queued = enqueue_backup_validation(
            "cliente01",
            mount_point="/mnt/backup",
            backup_path="/mnt/backup/app",
            environment=EnvironmentType.PRODUCTION,
            settings=config,
        )
        stored = get_job(queued["job_id"], settings=config)

    raw_job = json.loads(fake.queue[0][1])
    assert queued["job_type"] == "skill"
    assert queued["skill"] == "backup_validation"
    assert raw_job["job_type"] == "skill"
    assert raw_job["skill_payload"]["mount_point"] == "/mnt/backup"
    assert stored["status"] == "queued"


def test_worker_dispatches_backup_validation_without_ai_selection():
    fake = FakeRedis()
    config = settings()

    def operation(*args, **kwargs):
        report_progress(
            "skill_completed",
            status="completed",
            detail="Backup Validation concluída.",
            percent=100,
        )
        return {
            "skill": "backup_validation",
            "status": "healthy",
            "checks": {"mount": {"status": "healthy"}},
            "executed_actions": [],
        }

    with patch("app.services.jobs._redis", return_value=fake):
        queued = enqueue_backup_validation(
            "cliente01",
            mount_point="/mnt/backup",
            backup_path="/mnt/backup/app",
            environment=EnvironmentType.PRODUCTION,
            settings=config,
        )
        with patch("app.services.jobs.run_backup_validation", side_effect=operation) as mocked:
            result = run_worker_once(settings=config, block_seconds=0)
        stored = get_job(queued["job_id"], settings=config)

    assert mocked.called
    assert result["status"] == "completed"
    assert result["job_type"] == "skill"
    assert result["skill"] == "backup_validation"
    assert stored["result"]["status"] == "healthy"
    assert stored["result"]["executed_actions"] == []
    assert "provider" not in stored
