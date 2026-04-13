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


def _project_models_dir() -> Path:
    """Get project-local models directory (./models/)."""
    return Path(__file__).resolve().parent.parent / "models"


def _resolve_u2net_home() -> Path:
    """Resolve rembg model home - prioritizes project-local models/ directory."""
    # Project-local models directory takes priority
    local_models = _project_models_dir()
    return local_models


def _get_all_model_dirs() -> list[tuple[str, Path]]:
    """Get all possible model directories to search for u2net models."""
    dirs: list[tuple[str, Path]] = []

    # Project-local models directory (highest priority for display)
    local_models = _project_models_dir()
    dirs.append(("项目models/", local_models))

    # U2NET_HOME env
    u2net_home = os.environ.get("U2NET_HOME")
    if u2net_home:
        dirs.append(("U2NET_HOME", Path(u2net_home).expanduser().resolve()))

    # User home .u2net
    home_u2net = Path.home() / ".u2net"
    if home_u2net not in [d[1] for d in dirs]:
        dirs.append(("用户目录~/.u2net", home_u2net))

    # rembg standard location (try lazily, don't block)
    try:
        from rembg.sessions.base import BaseSession
        p = Path(BaseSession.u2net_home()).expanduser().resolve()
        if p not in [d[1] for d in dirs]:
            dirs.append(("rembg标准", p))
    except BaseException:
        pass

    return dirs


def _normalize_model_name(model_name: str) -> str:
    """Normalize model name - only u2net is supported now."""
    key = str(model_name or "").strip().lower()
    if key in ("u2net", "precise", "u2netp", "u2net_small", "small"):
        return "u2net"
    return "u2net"


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
            all_dirs = _get_all_model_dirs()

            # 搜索所有目录
            u2net_exists = False
            all_onnx_files: list[str] = []
            search_results: list[dict[str, Any]] = []

            for label, dir_path in all_dirs:
                if dir_path.exists():
                    onnx_files = sorted([p.name for p in dir_path.glob("*.onnx")])
                    all_onnx_files.extend(onnx_files)
                    search_results.append({
                        "path": str(dir_path),
                        "label": label,
                        "files": onnx_files,
                    })
                    if "u2net.onnx" in onnx_files:
                        u2net_exists = True

            # 去重
            all_onnx_files = sorted(set(all_onnx_files))

            return {
                "ok": True,
                "model_home": str(u2net_dir),
                "u2net": u2net_exists,
                "files": all_onnx_files,
                "search_results": search_results,
            }
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(exc)}

    def download_model(self, model_name: str = "u2net") -> dict[str, Any]:
        """下载 u2net 模型到项目本地 models/ 目录"""
        try:
            # 只支持 u2net
            normalized_model = "u2net"

            # 检查 onnxruntime 是否可用（加载成功）
            onnx_available = True
            try:
                import onnxruntime  # type: ignore
                # 验证能否实际加载
                _ = onnxruntime.get_device()
            except Exception:
                onnx_available = False

            if not onnx_available:
                # 自动安装 onnxruntime 1.19.0（已知可用版本）
                try:
                    import subprocess
                    python_exe = sys.executable
                    result = subprocess.run(
                        [python_exe, "-m", "pip", "install", "onnxruntime==1.19.0"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode != 0:
                        return {
                            "ok": False,
                            "error": f"自动安装 onnxruntime 失败: {result.stderr}",
                        }
                except Exception as e:
                    return {
                        "ok": False,
                        "error": f"自动安装 onnxruntime 失败: {str(e)}",
                    }

            # 项目本地 models 目录
            models_dir = _project_models_dir()
            models_dir.mkdir(parents=True, exist_ok=True)

            # 设置环境变量让 rembg 下载到项目目录
            original_u2net_home = os.environ.get("U2NET_HOME")
            os.environ["U2NET_HOME"] = str(models_dir)

            downloaded = False
            download_error = ""
            try:
                from rembg.bg import download_models

                download_models(("u2net",))
                downloaded = (models_dir / "u2net.onnx").exists()
            except SystemExit as e:
                download_error = f"下载被中断: {e}"
            except BaseException as e:
                download_error = str(e)
            finally:
                # 恢复原环境变量
                if original_u2net_home is None:
                    os.environ.pop("U2NET_HOME", None)
                else:
                    os.environ["U2NET_HOME"] = original_u2net_home

            if not downloaded and download_error:
                return {
                    "ok": False,
                    "error": f"下载失败: {download_error}",
                }

            status = self.check_model_status()
            return {
                "ok": True,
                "downloaded": downloaded,
                "models_dir": str(models_dir),
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
