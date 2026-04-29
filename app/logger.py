"""日志模块：双文件日志（task.log + system.log），每次启动覆盖写入，过滤 pywebview 噪音。

提供两级初始化：
  1. early_init_logging() - 在 main() 最开头调用，用 basicConfig 快速建立文件日志
  2. setup_logging() - 完整初始化（格式化、双文件、过滤器等），会接管 early_init 的配置
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 模块级缓存，early_init 和 setup_logging 共用
_log_dir: Path | None = None


def _resolve_log_dir() -> Path:
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


def get_log_dir() -> Path:
    """获取当前日志目录（供外部查询）。"""
    global _log_dir
    if _log_dir is None:
        _log_dir = _resolve_log_dir()
    return _log_dir


def early_init_logging() -> None:
    """最早期日志初始化，在 main() 最开头调用。

    用 basicConfig 快速建立 system.log 文件输出，确保 setup_logging() 之前
    的关键步骤（如 webview 导入检查、路径解析）也能写入日志。
    后续 setup_logging() 会重新配置 handler，覆盖此配置。
    """
    global _log_dir
    _log_dir = _resolve_log_dir()
    # 用 append 模式写入，setup_logging 会切换为覆盖模式
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(_log_dir / "system.log", mode="a", encoding="utf-8"),
        ],
    )
    log = logging.getLogger("system")
    log.info("===== early_init_logging: 早期日志已建立 =====")
    log.info("日志目录: %s", _log_dir)


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
    """完整初始化日志系统，在 early_init_logging() 之后调用。

    会重新配置 handler（覆盖 basicConfig），建立双文件日志（task.log + system.log），
    每次启动覆盖写入旧日志，并设置全局异常捕获。
    """
    global _log_dir
    from app.settings_store import DEFAULT_SETTINGS_STORE

    settings = DEFAULT_SETTINGS_STORE.get_settings()
    log_cfg = settings.get("logging", {})
    level_name = str(log_cfg.get("level", "info")).upper()
    level = getattr(logging, level_name, logging.INFO)

    if _log_dir is None:
        _log_dir = _resolve_log_dir()
    log_dir = _log_dir

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
    # 注意：mode="w" 会覆盖 early_init 写入的内容，但 setup_logging 之前的关键步骤
    # 已经在 early_init 阶段被记录过了，setup_logging 会重新记录完整启动信息
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

    # System logger -> system.log（专属 handler，不依赖 root 传播）
    system_logger = logging.getLogger("system")
    system_logger.setLevel(level)
    system_logger.handlers.clear()
    system_logger.addHandler(system_handler)
    system_logger.propagate = False

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

    root_logger.info("===== 日志系统完整初始化完成, 日志目录: %s =====", log_dir)


def get_task_logger() -> logging.Logger:
    """获取任务日志记录器"""
    return logging.getLogger("task")


def get_system_logger() -> logging.Logger:
    """获取系统日志记录器"""
    return logging.getLogger("system")


def log_frontend(message: str, level: str = "info") -> None:
    """供前端 JS 调用，将前端日志写入 system.log。

    前端页面加载成功/失败、JS 错误等信息通过 ApiBridge 暴露的接口调用此方法，
    实现前后端日志统一记录，便于诊断 UI 无法渲染的问题。
    """
    try:
        log = logging.getLogger("system")
        py_level = {"warn": "warning", "error": "error", "debug": "debug"}.get(level, "info")
        # 安全格式化：message 可能包含 % 等特殊字符，用 %s 占位避免格式化异常
        getattr(log, py_level)("[前端] %s", str(message or ""))
    except Exception:
        # 兜底：日志模块自身不应导致业务中断
        pass
