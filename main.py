from __future__ import annotations

import sys
from pathlib import Path

try:
    import webview
except Exception as exc:  # pragma: no cover - startup environment guard
    webview = None
    _WEBVIEW_IMPORT_ERROR = exc
else:
    _WEBVIEW_IMPORT_ERROR = None

from app.bridge import ApiBridge
from app.tasks import TaskManager


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def _resolve_ui_file() -> Path:
    ui_file = _resolve_base_dir() / "ui" / "new.html"
    if not ui_file.exists():
        raise FileNotFoundError(f"未找到前端页面: {ui_file}")
    return ui_file


def main() -> None:
    if webview is None:
        raise RuntimeError("未安装或无法加载 pywebview，请先安装依赖后再运行。") from _WEBVIEW_IMPORT_ERROR

    task_manager = TaskManager()
    bridge = ApiBridge(task_manager)
    ui_file = _resolve_ui_file()

    window = webview.create_window(
        title="个人图片批量处理工具箱",
        url=ui_file.as_uri(),
        js_api=bridge,
        width=1320,
        height=820,
        min_size=(1000, 680),
        resizable=True,
    )
    bridge.set_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
