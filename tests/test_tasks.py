from __future__ import annotations

import threading
import time

import pytest

from app import tasks as tasks_module
from app.tasks import TaskManager


def wait_for_condition(predicate, timeout: float = 3.0, interval: float = 0.02):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def test_get_status_for_missing_task_returns_not_found():
    manager = TaskManager()

    status = manager.get_status("missing-task")
    logs = manager.get_logs("missing-task")

    assert status["status"] == "not_found"
    assert status["error"] == "任务不存在"
    assert status["success_count"] == 0
    assert status["fail_count"] == 0
    assert status["skipped_count"] == 0
    assert status["logs"] == []
    assert logs["ok"] is False
    assert logs["error"] == "任务不存在"
    assert logs["logs"] == []


def test_task_success_and_incremental_logs(monkeypatch):
    def fake_execute_task(payload, log):
        log("info", "step one")
        log("warn", "step two")
        return {
            "status": "success",
            "success_count": 2,
            "fail_count": 0,
            "skipped_count": 1,
            "output_path": "out",
            "backup_path": "bak",
            "error": "",
        }

    monkeypatch.setattr(tasks_module, "execute_task", fake_execute_task)

    manager = TaskManager()
    task_id = manager.start_task({"task": "demo"})

    status = wait_for_condition(lambda: manager.get_status(task_id) if manager.get_status(task_id)["status"] == "success" else None)
    assert status is not None
    assert status["status"] == "success"
    assert status["success_count"] == 2
    assert status["fail_count"] == 0
    assert status["skipped_count"] == 1
    assert status["output_path"] == "out"
    assert status["backup_path"] == "bak"
    assert status["error"] == ""

    logs_all = manager.get_logs(task_id, 0)
    assert logs_all["ok"] is True
    assert logs_all["next_index"] == len(logs_all["logs"])
    assert any("任务已启动" in line for line in logs_all["logs"])
    assert any("step one" in line for line in logs_all["logs"])
    assert any("step two" in line for line in logs_all["logs"])

    logs_tail = manager.get_logs(task_id, logs_all["next_index"])
    assert logs_tail["ok"] is True
    assert logs_tail["logs"] == []
    assert logs_tail["next_index"] == logs_all["next_index"]


def test_task_failure_sets_fail_status(monkeypatch):
    def fake_execute_task(payload, log):
        log("info", "before failure")
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks_module, "execute_task", fake_execute_task)

    manager = TaskManager()
    task_id = manager.start_task({"task": "demo"})

    status = wait_for_condition(lambda: manager.get_status(task_id) if manager.get_status(task_id)["status"] == "fail" else None)
    assert status is not None
    assert status["status"] == "fail"
    assert status["error"] == "boom"
    assert status["success_count"] == 0
    assert status["fail_count"] == 0
    assert any("before failure" in line for line in status["logs"])
    assert any("boom" in line for line in status["logs"])

