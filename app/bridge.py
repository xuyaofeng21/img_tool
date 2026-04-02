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

from .settings_store import DEFAULT_SETTINGS_STORE, SettingsStore
from .tasks import TaskManager
from .wrappers import preview_path_info


class ApiBridge:
    def __init__(self, task_manager: TaskManager) -> None:
        self.task_manager = task_manager
        self.window = None
        self.settings_store: SettingsStore = DEFAULT_SETTINGS_STORE

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

    def select_file(self) -> str:
        if self.window is None or webview is None:
            return ""
        try:
            result = self.window.create_file_dialog(webview.OPEN_DIALOG)
            return result[0] if result else ""
        except Exception:
            return ""

    def select_files(self) -> str:
        if self.window is None or webview is None:
            return ""
        try:
            result = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=(
                    "Images (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp;*.tiff;*.tif;*.ico)\0*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp;*.tiff;*.tif;*.ico\0"
                    "All Files (*.*)\0*.*\0"
                ),
            )
            if not result:
                return ""
            return ";".join(result)
        except Exception:
            return ""

    def preview_path(self, payload: dict[str, Any]) -> dict[str, Any]:
        return preview_path_info(payload)

    def get_settings(self) -> dict[str, Any]:
        try:
            return {
                "ok": True,
                "settings": self.settings_store.get_settings(),
                "path": str(self.settings_store.path),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def update_settings(self, payload: Any) -> dict[str, Any]:
        try:
            settings = self.settings_store.update_settings(payload)
            return {
                "ok": True,
                "settings": settings,
                "path": str(self.settings_store.path),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def validate_settings(self, payload: Any) -> dict[str, Any]:
        try:
            result = self.settings_store.validate_settings(payload)
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "valid": False, "errors": [str(exc)], "error": str(exc)}

    def reset_settings(self, payload: Any = None) -> dict[str, Any]:
        try:
            keys: list[str] | None = None
            if isinstance(payload, dict) and isinstance(payload.get("keys"), list):
                keys = [str(item) for item in payload["keys"]]
            settings = self.settings_store.reset_settings(keys)
            return {
                "ok": True,
                "settings": settings,
                "path": str(self.settings_store.path),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def export_settings(self, payload: Any = None) -> dict[str, Any]:
        try:
            output_path = ""
            if isinstance(payload, dict):
                output_path = str(payload.get("path", "") or "").strip()
            exported = self.settings_store.export_settings(output_path or None)
            return {
                "ok": True,
                "json": exported,
                "settings": self.settings_store.get_settings(),
                "path": str(self.settings_store.path),
                "export_path": output_path,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def import_settings(self, payload: Any) -> dict[str, Any]:
        try:
            settings = self.settings_store.import_settings(payload)
            return {
                "ok": True,
                "settings": settings,
                "path": str(self.settings_store.path),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

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
