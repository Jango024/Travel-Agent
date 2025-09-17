"""Tests for the TaskManager persistence layer."""
from __future__ import annotations

import time
from threading import Event

from task_repository import TaskRepository
from webapp import TaskManager


class DummyResult:
    """Minimal stand-in for :class:`agent_core.AgentResult`."""

    def __init__(self, report: str) -> None:
        self.report = report

    def to_dict(self) -> dict:
        return {"report": self.report}


def test_task_persistence_across_managers(tmp_path) -> None:
    """Two managers should see the same task record via the repository."""

    database_path = tmp_path / "tasks.db"
    repository = TaskRepository(str(database_path))
    manager_a = TaskManager(repository)
    manager_b = TaskManager(repository)

    completed = Event()

    def _run() -> DummyResult:
        completed.set()
        return DummyResult("Report from worker")

    record = manager_a.submit({"foo": "bar"}, _run)
    assert completed.wait(timeout=5), "Background task did not complete in time"

    retrieved = None
    for _ in range(50):
        retrieved = manager_b.get(record.id)
        if retrieved and retrieved.status == "finished":
            break
        time.sleep(0.1)

    assert retrieved is not None
    assert retrieved.status == "finished"
    payload = retrieved.to_dict()
    assert payload["config"] == {"foo": "bar"}
    assert payload["result"]["report"] == "Report from worker"

    manager_a.executor.shutdown(wait=True)
    manager_b.executor.shutdown(wait=True)
