from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

try:
    import webview
except Exception:  # pragma: no cover
    webview = None

from .tasks import TaskManager


class ApiBridge:
    def __init__(self, task_manager: TaskManager) -> None:
        self.task_manager = task_manager
        self.window = None

    def set_window(self, window: Any) -> None:
        self.window = window

    def run_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是对象")
            task_id = self.task_manager.start_task(payload)
            return {"ok": True, "task_id": task_id}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self.task_manager.get_status(task_id)

    def get_task_logs(self, task_id: str, from_index: int = 0) -> dict[str, Any]:
        return self.task_manager.get_logs(task_id, from_index=from_index)

    def select_folder(self) -> str:
        if self.window is None or webview is None:
            return ""
        try:
            result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            return result[0] if result else ""
        except Exception:
            return ""

    def open_path(self, path: str) -> dict[str, Any]:
        try:
            if not path or not str(path).strip():
                return {"ok": False, "error": "路径不能为空"}
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return {"ok": False, "error": f"路径不存在: {p}"}

            system = platform.system().lower()
            if system == "windows":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif system == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

