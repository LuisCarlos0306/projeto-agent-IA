import json
from types import SimpleNamespace
from unittest.mock import patch

from app.services.custom_skill_jobs import _execute_custom_job, enqueue_custom_skill
from app.services.jobs import get_job


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


def settings():
    return SimpleNamespace(
        redis_url="redis://invalid/1",
        agent_queue_name="agent-ia:jobs",
        agent_result_prefix="agent-ia:result:",
        agent_worker_name="worker-test",
        agent_job_ttl_seconds=3600,
        agent_queue_block_seconds=0,
    )


def test_custom_skill_is_enqueued_with_only_skill_and_target():
    fake = FakeRedis()
    config = settings()
    with patch("app.services.jobs._redis", return_value=fake):
        queued = enqueue_custom_skill("skill123", "172.27.232.212", settings=config)
        stored = get_job(queued["job_id"], settings=config)

    raw = json.loads(fake.queue[0][1])
    assert raw["skill"] == "custom:skill123"
    assert raw["reference"] == "172.27.232.212"
    assert raw["ssh_port"] is None
    assert "commands" not in raw
    assert stored["status"] == "queued"


def test_custom_skill_worker_persists_result():
    fake = FakeRedis()
    config = settings()
    result = {
        "skill": "custom:skill123",
        "skill_id": "skill123",
        "name": "Filesystem",
        "status": "healthy",
        "commands": [{"command": "df -h", "exit_code": 0, "stdout": "ok", "stderr": ""}],
        "executed_actions": [],
    }

    with patch("app.services.jobs._redis", return_value=fake):
        queued = enqueue_custom_skill("skill123", "172.27.232.212", settings=config)
        raw = json.loads(fake.queue[0][1])
        with patch("app.services.custom_skill_jobs.run_custom_skill", return_value=result):
            completed = _execute_custom_job(raw, settings=config)
        stored = get_job(queued["job_id"], settings=config)

    assert completed["status"] == "completed"
    assert completed["skill"] == "custom:skill123"
    assert stored["result"]["name"] == "Filesystem"
    assert stored["result"]["executed_actions"] == []
