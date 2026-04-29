from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ── 最早期日志初始化（必须在所有其他操作之前） ──
# 这样 webview 导入失败、路径解析错误等都能写入 system.log
from app.logger import early_init_logging
early_init_logging()
_log = logging.getLogger("system")
_log.info("===== ImgToolbox 进程启动 =====")
_log.info("命令行: %s", sys.argv)
_log.info("平台: %s %s, Python %s", sys.platform, os.getenv('PROCESSOR_ARCHITECTURE', ''), sys.version.split()[0])
_log.info("frozen=%s, executable=%s", getattr(sys, 'frozen', False), getattr(sys, 'executable', 'N/A'))

# 设置 U2NET_HOME 到项目本地 models/ 目录（必须在 rembg 导入前设置）
_PROJECT_MODELS_DIR = Path(__file__).resolve().parent / "models"
os.environ["U2NET_HOME"] = str(_PROJECT_MODELS_DIR)
_log.info("U2NET_HOME=%s", _PROJECT_MODELS_DIR)

try:
    import webview
except Exception as exc:  # pragma: no cover - startup environment guard
    webview = None
    _WEBVIEW_IMPORT_ERROR = exc
    _log.error("pywebview 导入失败: %s", exc, exc_info=True)
else:
    _WEBVIEW_IMPORT_ERROR = None
    _log.info("pywebview 导入成功, version=%s", getattr(webview, '__version__', 'unknown'))
    # 记录 webview 后端类型（edgechromium/mshtml/cef 等）
    # 如果是 mshtml 说明用的是 IE 内核，ES6+ JS 无法执行
    _log.info("pywebview platform=%s", getattr(webview, 'platform', 'unknown'))

from app.bridge import ApiBridge
from app.logger import setup_logging, get_log_dir
from app.tasks import TaskManager


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        _log.debug("base_dir (frozen/MEIPASS): %s", base)
        return base
    base = Path(__file__).resolve().parent
    _log.debug("base_dir (development): %s", base)
    return base


def _resolve_ui_file() -> Path:
    ui_file = _resolve_base_dir() / "ui" / "new.html"
    _log.info("UI 文件路径: %s, exists=%s", ui_file, ui_file.exists())
    if not ui_file.exists():
        _log.error("未找到前端页面: %s", ui_file)
        raise FileNotFoundError(f"未找到前端页面: {ui_file}")
    return ui_file


def main() -> None:
    try:
        _main_inner()
    except Exception:
        # 兜底：确保即使 _main_inner 崩溃也能写日志
        _log.exception("main() 顶层异常，应用即将退出")
        raise


def _on_webview_loaded() -> None:
    """webview 窗口加载完成后的回调，验证前端 JS 引擎和后端类型。

    通过 evaluate_js 获取 navigator.userAgent，根据 UA 判断实际使用的渲染引擎：
    - 包含 Edg/ 或 Chrome/ → EdgeChromium (WebView2)，ES6+ 正常
    - 包含 Trident/ 或 MSIE → MSHTML (IE)，ES6+ 无法执行
    这比启动前猜测注册表可靠得多。
    """
    log = logging.getLogger("system")
    log.info("_on_webview_loaded: 窗口已加载，开始验证前端...")

    # 记录 pywebview 实际选择的后端（start 之后才有值）
    platform = getattr(webview, 'platform', 'unknown')
    log.info("pywebview 实际后端: %s", platform)

    try:
        result = window.evaluate_js("JSON.stringify({ok: true, ua: navigator.userAgent})")
        log.info("前端 JS 验证结果: %s", result)

        # 根据 UA 判断渲染引擎
        if result:
            ua = ""
            # result 是 JSON 字符串，解析出 ua
            try:
                import json
                parsed = json.loads(result)
                ua = parsed.get("ua", "")
            except (json.JSONDecodeError, AttributeError):
                ua = str(result)

            if "Edg/" in ua or "Chrome/" in ua:
                log.info("前端渲染引擎: Chromium/Edge (WebView2)，ES6+ 支持正常")
            elif "Trident/" in ua or "MSIE" in ua:
                log.critical("!!! 前端渲染引擎: MSHTML (IE)，ES6+ JS 无法执行 !!!")
                log.critical("!!! 请安装 WebView2 Runtime: https://developer.microsoft.com/en-us/microsoft-edge/webview2/ !!!")
            else:
                log.warning("前端渲染引擎: 未知 (%s)", ua[:100])
    except Exception as e:
        log.error("前端 JS 验证失败: %s", e)
        log.error("可能原因: 前端 JS 引擎无法执行，疑似缺少 WebView2 Runtime")
        log.error("请安装 WebView2 Runtime: https://developer.microsoft.com/en-us/microsoft-edge/webview2/")


def _main_inner() -> None:
    global window
    if webview is None:
        _log.critical("pywebview 不可用，无法启动。错误: %s", _WEBVIEW_IMPORT_ERROR)
        raise RuntimeError("未安装或无法加载 pywebview，请先安装依赖后再运行。") from _WEBVIEW_IMPORT_ERROR

    _log.info("开始完整初始化...")
    setup_logging()
    from app.logger import get_system_logger
    log = get_system_logger()

    log.info("===== ImgToolbox 启动序列 =====")
    log.info("日志目录: %s", get_log_dir())
    log.info("平台: %s %s, Python %s", sys.platform, os.getenv('PROCESSOR_ARCHITECTURE', ''), sys.version.split()[0])
    log.info("frozen=%s, executable=%s", getattr(sys, 'frozen', False), getattr(sys, 'executable', 'N/A'))
    log.info("pywebview platform(导入时)=%s", getattr(webview, 'platform', 'unknown'))

    log.info("创建 TaskManager...")
    task_manager = TaskManager()
    log.info("创建 ApiBridge...")
    bridge = ApiBridge(task_manager)

    ui_file = _resolve_ui_file()
    log.info("UI 文件: %s", ui_file)

    log.info("创建窗口...")
    window = webview.create_window(
        title="图片工具箱(纯AI 0手工)",
        url=ui_file.as_uri(),
        js_api=bridge,
        width=1320,
        height=820,
        min_size=(1000, 680),
        resizable=True,
    )
    log.info("窗口创建成功, url=%s", ui_file.as_uri())

    bridge.set_window(window)
    log.info("bridge.set_window 完成")

    log.info("调用 webview.start()，进入主事件循环...")
    webview.start(debug=False, func=_on_webview_loaded)
    log.info("webview.start() 已返回，应用正常退出")


if __name__ == "__main__":
    main()
