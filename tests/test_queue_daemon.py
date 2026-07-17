from pathlib import Path

import pytest

from sapiens.budget import ExecutionContext
from sapiens.daemon import DiscoveryDaemon
from sapiens.queue import WorkQueue


def test_queue_capacity_idempotency_and_stale_lease(tmp_path: Path):
    q = WorkQueue(tmp_path / "q.sqlite", max_jobs=1, max_payload_bytes=100)
    assert q.enqueue("j1", "echo", {"x": 1}, idempotency_key="same")
    assert not q.enqueue("j2", "echo", {"x": 1}, idempotency_key="same")
    with pytest.raises(OverflowError):
        q.enqueue("j3", "echo", {"x": 3})
    job = q.lease("w1", seconds=10)
    assert job is not None
    stale = q.lease("w2", seconds=10)
    assert stale is None
    q.finish(job, {"ok": True})
    assert q.status("j1") == "succeeded"
    with pytest.raises(RuntimeError):
        q.finish(job, {"again": True})


def test_queue_rejects_oversized_payload(tmp_path: Path):
    q = WorkQueue(tmp_path / "q.sqlite", max_payload_bytes=8)
    with pytest.raises(ValueError):
        q.enqueue("j", "echo", {"too": "large"})


def test_daemon_runs_bounded_registered_handler(tmp_path: Path):
    q = WorkQueue(tmp_path / "q.sqlite")
    q.enqueue("j1", "echo", {"x": 2})

    def handler(job, context: ExecutionContext):
        context.checkpoint()
        return {"x": job.payload["x"]}

    report = DiscoveryDaemon(q, {"echo": handler}).run_bounded(
        worker="w", max_jobs=1, max_seconds=2, steps_per_job=5
    )
    assert report.completed == 1
    assert q.status("j1") == "succeeded"
