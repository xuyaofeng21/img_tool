from __future__ import annotations

from pathlib import Path

import app.tasks as tasks_module
from app.bridge import ApiBridge
from app.tasks import TaskManager


def wait_for_status(manager: TaskManager, task_id: str, expected: str, timeout: float = 3.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.get_status(task_id)
        if status["status"] == expected:
            return status
        time.sleep(0.02)
    return manager.get_status(task_id)


def test_run_task_and_status_payload_shape(monkeypatch):
    def fake_execute_task(payload, log):
        log("info", f"task={payload['task']}")
        return {
            "status": "success",
            "success_count": 1,
            "fail_count": 0,
            "skipped_count": 0,
            "output_path": "output",
            "backup_path": "backup",
            "error": "",
        }

    monkeypatch.setattr(tasks_module, "execute_task", fake_execute_task)

    manager = TaskManager()
    bridge = ApiBridge(manager)

    ret = bridge.run_task(
        {
            "task": "rename2",
            "mode": "safe_copy",
            "paths": {"source_dir": "src", "target_dir": "dst"},
            "params": {"prefix": "new_"},
            "backup_dir": "",
        }
    )

    assert ret["ok"] is True
    assert ret["task_id"]

    status = wait_for_status(manager, ret["task_id"], "success")
    expected_keys = {
        "task_id",
        "status",
        "success_count",
        "fail_count",
        "skipped_count",
        "output_path",
        "backup_path",
        "error",
        "logs",
        "created_at",
        "started_at",
        "ended_at",
    }
    assert expected_keys.issubset(status.keys())
    assert status["status"] == "success"
    assert status["success_count"] == 1
    assert status["output_path"] == "output"
    assert status["backup_path"] == "backup"
    assert any("task=rename2" in line for line in status["logs"])

    log_chunk = bridge.get_task_logs(ret["task_id"], 0)
    assert log_chunk["ok"] is True
    assert isinstance(log_chunk["logs"], list)
    assert isinstance(log_chunk["next_index"], int)


def test_run_task_rejects_non_dict_payload():
    manager = TaskManager()
    bridge = ApiBridge(manager)

    ret = bridge.run_task("not-a-dict")

    assert ret["ok"] is False
    assert "payload" in ret["error"]


def test_select_folder_and_open_path(monkeypatch, tmp_path):
    manager = TaskManager()
    bridge = ApiBridge(manager)

    class DummyWindow:
        def create_file_dialog(self, dialog_type):
            self.dialog_type = dialog_type
            return [str(tmp_path)]

    bridge.set_window(DummyWindow())
    assert bridge.select_folder() == str(tmp_path)

    called = {}

    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("os.startfile", lambda path: called.setdefault("path", path), raising=False)

    path = tmp_path / "data"
    path.mkdir()
    result = bridge.open_path(str(path))

    assert result["ok"] is True
    assert Path(called["path"]).resolve() == path.resolve()


def test_get_task_status_and_logs_for_unknown_task():
    manager = TaskManager()
    bridge = ApiBridge(manager)

    status = bridge.get_task_status("missing")
    logs = bridge.get_task_logs("missing", 0)

    assert status["status"] == "not_found"
    assert status["error"] == "任务不存在"
    assert logs["ok"] is False
    assert logs["error"] == "任务不存在"

