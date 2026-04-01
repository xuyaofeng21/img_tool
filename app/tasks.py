from __future__ import annotations

import copy
import threading
import traceback
import uuid
from datetime import datetime
from typing import Any

from .wrappers import execute_task


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def start_task(self, payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是对象")

        task_id = uuid.uuid4().hex
        task_record = {
            "task_id": task_id,
            "status": "queued",
            "logs": [],
            "result": {
                "status": "queued",
                "success_count": 0,
                "fail_count": 0,
                "skipped_count": 0,
                "output_path": "",
                "backup_path": "",
                "error": "",
                "logs": [],
            },
            "created_at": _now(),
            "started_at": "",
            "ended_at": "",
        }

        with self._lock:
            self._tasks[task_id] = task_record

        thread = threading.Thread(target=self._run_task, args=(task_id, payload), daemon=True)
        thread.start()
        return task_id

    def _append_log(self, task_id: str, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level.upper()}] {message}"
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            record["logs"].append(line)

    def _run_task(self, task_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record:
                record["status"] = "running"
                record["result"]["status"] = "running"
                record["started_at"] = _now()

        self._append_log(task_id, "info", "任务已启动")
        try:
            result = execute_task(payload, lambda level, msg: self._append_log(task_id, level, msg))
            with self._lock:
                record = self._tasks.get(task_id)
                if record:
                    record["status"] = "success"
                    record["result"].update(result)
                    record["result"]["status"] = "success"
                    record["result"]["logs"] = list(record["logs"])
                    record["ended_at"] = _now()
            self._append_log(task_id, "info", "任务执行完成")
        except Exception as exc:
            err_msg = str(exc)
            self._append_log(task_id, "error", err_msg)
            self._append_log(task_id, "error", traceback.format_exc())
            with self._lock:
                record = self._tasks.get(task_id)
                if record:
                    record["status"] = "fail"
                    record["result"]["status"] = "fail"
                    record["result"]["error"] = err_msg
                    record["result"]["logs"] = list(record["logs"])
                    record["ended_at"] = _now()

    def get_logs(self, task_id: str, from_index: int = 0) -> dict[str, Any]:
        try:
            index = max(0, int(from_index or 0))
        except (TypeError, ValueError):
            index = 0

        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return {"ok": False, "error": "任务不存在", "logs": [], "next_index": index}
            logs = record["logs"]
            sliced = logs[index:]
            return {"ok": True, "logs": sliced, "next_index": index + len(sliced)}

    def get_status(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return {
                    "task_id": task_id,
                    "status": "not_found",
                    "success_count": 0,
                    "fail_count": 0,
                    "skipped_count": 0,
                    "output_path": "",
                    "backup_path": "",
                    "error": "任务不存在",
                    "logs": [],
                    "created_at": "",
                    "started_at": "",
                    "ended_at": "",
                }

            result = copy.deepcopy(record["result"])
            result["task_id"] = task_id
            result["status"] = record["status"]
            result["logs"] = list(record["logs"])
            result["created_at"] = record["created_at"]
            result["started_at"] = record["started_at"]
            result["ended_at"] = record["ended_at"]
            return result

