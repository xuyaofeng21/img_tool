"""日志模块：双文件日志（task.log + system.log），每次启动覆盖写入，过滤 pywebview 噪音。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def _log_dir() -> Path:
    """获取可写日志目录。

    开发环境：项目根目录/logs/
    打包后：可执行文件同级目录/logs/
    AppImage 只读挂载：回退到 ~/.cache/ImgToolbox/logs/
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        exe_parent = Path(sys.executable).parent
        log_dir = exe_parent / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir
        except (OSError, PermissionError):
            # Read-only mount (AppImage FUSE) - use user home
            log_dir = Path.home() / ".cache" / "ImgToolbox" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir
    else:
        # 开发环境：main.py 所在目录的 logs/
        log_dir = Path(sys.argv[0]).resolve().parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir


class _AppOnlyFilter(logging.Filter):
    """只放行应用自身的日志，过滤掉 pywebview 等第三方库的内部报错噪音。

    pywebview 在序列化 WinForms 原生对象时会遍历 Bounds.Empty.Empty...、
    WindowsPath._hash 等，产生大量"Error while processing"日志，这些都是
    框架内部行为，不影响功能，不应写入应用日志。
    """

    BLOCK_PREFIXES = (
        "pywebview",
        "webview",
        "clr",
        "System.",
        "Microsoft.",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        for prefix in self.BLOCK_PREFIXES:
            if name.startswith(prefix):
                return False
        return True


def setup_logging() -> None:
    """初始化日志系统，在应用启动时调用一次。每次启动覆盖旧日志。"""
    from app.settings_store import DEFAULT_SETTINGS_STORE

    settings = DEFAULT_SETTINGS_STORE.get_settings()
    log_cfg = settings.get("logging", {})
    level_name = str(log_cfg.get("level", "info")).upper()
    level = getattr(logging, level_name, logging.INFO)

    log_dir = _log_dir()

    task_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    system_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_filter = _AppOnlyFilter()

    # task.log - 任务相关日志，每次启动覆盖
    task_handler = logging.FileHandler(
        log_dir / "task.log", mode="w", encoding="utf-8"
    )
    task_handler.setFormatter(task_fmt)
    task_handler.setLevel(level)
    task_handler.addFilter(app_filter)

    # system.log - 系统/应用相关日志，每次启动覆盖
    system_handler = logging.FileHandler(
        log_dir / "system.log", mode="w", encoding="utf-8"
    )
    system_handler.setFormatter(system_fmt)
    system_handler.setLevel(level)
    system_handler.addFilter(app_filter)

    # Root logger -> system.log
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(system_handler)

    # Task logger -> task.log
    task_logger = logging.getLogger("task")
    task_logger.setLevel(level)
    task_logger.handlers.clear()
    task_logger.addHandler(task_handler)
    task_logger.propagate = False

    # 捕获未处理异常
    def _global_exception_handler(exc_type, exc_val, exc_tb):
        root_logger.error("Uncaught exception", exc_info=(exc_type, exc_val, exc_tb))
        sys.__excepthook__(exc_type, exc_val, exc_tb)

    sys.excepthook = _global_exception_handler

    root_logger.info("日志系统初始化完成, 日志目录: %s", log_dir)


def get_task_logger() -> logging.Logger:
    """获取任务日志记录器"""
    return logging.getLogger("task")


def get_system_logger() -> logging.Logger:
    """获取系统日志记录器"""
    return logging.getLogger("system")
