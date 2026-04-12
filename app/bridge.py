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
from .wrappers import inspect_synthesize_source_info, preview_path_info


def _resolve_u2net_home() -> Path:
    """Resolve rembg model home with rembg rules (U2NET_HOME/XDG_DATA_HOME)."""
    try:
        from rembg.sessions.base import BaseSession

        return Path(BaseSession.u2net_home()).expanduser().resolve()
    except Exception:
        return (Path.home() / ".u2net").expanduser().resolve()


def _normalize_model_name(model_name: str) -> str:
    key = str(model_name or "").strip().lower()
    alias = {
        "u2net": "u2net",
        "precise": "u2net",
        "u2netp": "u2netp",
        "u2net_small": "u2netp",
        "small": "u2netp",
    }
    return alias.get(key, key)


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

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self.task_manager.cancel_task(task_id)

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

    def inspect_synthesize_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        return inspect_synthesize_source_info(payload)

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

    def check_model_status(self) -> dict[str, Any]:
        """检查 u2net 模型是否已下载"""
        try:
            u2net_dir = _resolve_u2net_home()

            u2net_exists = (u2net_dir / "u2net.onnx").exists()
            # rembg 新版使用 u2netp.onnx，兼容历史命名 u2net_small.onnx
            u2netp_exists = (u2net_dir / "u2netp.onnx").exists()
            u2net_small_legacy_exists = (u2net_dir / "u2net_small.onnx").exists()
            u2net_small_exists = u2netp_exists or u2net_small_legacy_exists
            onnx_files = sorted(
                [p.name for p in u2net_dir.glob("*.onnx")] if u2net_dir.exists() else []
            )
            runtime_device = "unknown"
            runtime_providers: list[str] = []
            try:
                import onnxruntime as ort

                runtime_device = str(ort.get_device())
                runtime_providers = list(ort.get_available_providers())
            except Exception:
                pass

            return {
                "ok": True,
                "model_home": str(u2net_dir),
                "u2net": u2net_exists,
                "u2net_small": u2net_small_exists,
                "u2netp": u2netp_exists,
                "u2net_small_legacy": u2net_small_legacy_exists,
                "files": onnx_files,
                "both": u2net_exists and u2net_small_exists,
                "runtime_device": runtime_device,
                "runtime_providers": runtime_providers,
            }
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(exc)}

    def download_model(self, model_name: str = "u2net") -> dict[str, Any]:
        """下载 rembg 模型"""
        try:
            normalized_model = _normalize_model_name(model_name)
            if normalized_model not in {"u2net", "u2netp"}:
                return {
                    "ok": False,
                    "error": f"不支持的模型: {model_name}（支持: u2net / u2net_small）",
                }

            # rembg>=2.0.75 可用接口
            from rembg.bg import download_models

            download_models((normalized_model,))
            status = self.check_model_status()
            return {
                "ok": True,
                "requested_model": model_name,
                "normalized_model": normalized_model,
                "status": status,
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
