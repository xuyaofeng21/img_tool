from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import shutil
import sys
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


LogFn = Callable[[str, str], None]

_SCRIPT_MODULES: dict[str, Any] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_script_module(module_name: str, relative_file: str) -> Any:
    if module_name in _SCRIPT_MODULES:
        return _SCRIPT_MODULES[module_name]

    file_path = _project_root() / "script" / relative_file
    if not file_path.exists():
        raise FileNotFoundError(f"未找到脚本文件: {file_path}")

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本模块: {file_path}")

    module = importlib.util.module_from_spec(spec)
    # Register module name so multiprocessing can import task functions by module name.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _SCRIPT_MODULES[module_name] = module
    return module


def _normalize_dir(path: str, field_name: str, must_exist: bool = True) -> Path:
    if not path or not str(path).strip():
        raise ValueError(f"{field_name} 不能为空")
    p = Path(path).expanduser().resolve()
    if must_exist and not p.is_dir():
        raise ValueError(f"{field_name} 不是有效目录: {p}")
    return p


def _ensure_dir(path: str, field_name: str) -> Path:
    if not path or not str(path).strip():
        raise ValueError(f"{field_name} 不能为空")
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return candidate == root


def _ensure_not_inside(candidate: Path, protected_roots: list[Path], label: str) -> None:
    for root in protected_roots:
        if _is_within(candidate, root):
            raise ValueError(f"{label} 不能位于受影响目录内: {candidate}")


def _ensure_safe_output_dir(path: str, protected_roots: list[Path], field_name: str) -> Path:
    target = Path(path).expanduser().resolve()
    _ensure_not_inside(target, protected_roots, field_name)
    return _ensure_dir(str(target), field_name)


def _run_with_captured_stdout(log: LogFn, func: Callable[..., Any], *args: Any, **kwargs: Any) -> list[str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(*args, **kwargs)

    lines = [line.rstrip() for line in buf.getvalue().splitlines() if line.strip()]
    _log_lines(lines, log)
    return lines


def _log_lines(lines: list[str], log: LogFn) -> None:
    for line in lines:
        low = line.lower()
        if "错误" in line or "失败" in line or low.startswith("❌"):
            log("error", line)
        elif "警告" in line or low.startswith("⚠"):
            log("warn", line)
        else:
            log("info", line)


def _backup_directories(task_name: str, directories: list[Path], backup_dir: str, log: LogFn) -> Path:
    backup_root = _ensure_dir(backup_dir, "backup_dir")
    _ensure_not_inside(backup_root, directories, "backup_dir")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = backup_root / f"{task_name}_{stamp}"
    suffix = 1
    while session.exists():
        suffix += 1
        session = backup_root / f"{task_name}_{stamp}_{suffix}"
    session.mkdir(parents=True, exist_ok=False)

    for index, src in enumerate(directories, 1):
        if not src.is_dir():
            raise ValueError(f"备份源目录无效: {src}")
        dst_name = src.name if index == 1 else f"{src.name}_{index}"
        dst = session / dst_name
        log("info", f"开始备份: {src} -> {dst}")
        shutil.copytree(src, dst)
        log("info", f"备份完成: {dst}")
    return session


def _copy_all_files(src: Path, dst: Path) -> None:
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _copy_json_workspace(src: Path, dst: Path, log: LogFn) -> None:
    _ensure_not_inside(dst, [src], "output_dir")
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    log("info", f"已复制 JSON 目录到: {dst}")


def _extract_int(lines: list[str], pattern: str, default: int = 0) -> int:
    regex = re.compile(pattern)
    for line in lines:
        m = regex.search(line)
        if m:
            return int(m.group(1))
    return default


def _counts_from_bgr(lines: list[str]) -> tuple[int, int, int]:
    success = sum(1 for x in lines if "成功处理并保存" in x)
    fail = sum(1 for x in lines if ("无法读取图像" in x or "无法保存图像" in x or "发生错误" in x))
    return success, fail, 0


def _counts_from_rename(lines: list[str]) -> tuple[int, int, int]:
    image_count = _extract_int(lines, r"共处理了\s*(\d+)\s*张图片")
    json_count = _extract_int(lines, r"共处理了\s*(\d+)\s*个JSON文件")
    fail = sum(1 for x in lines if x.strip().startswith("❌"))
    return image_count + json_count, fail, 0


def _counts_from_select(lines: list[str]) -> tuple[int, int, int]:
    success = _extract_int(lines, r"共复制\s*(\d+)\s*张图片")
    fail = sum(1 for x in lines if "[WARN]" in x)
    return success, fail, 0


def _counts_from_json(lines: list[str]) -> tuple[int, int, int]:
    success = sum(1 for x in lines if x.strip().startswith("✅"))
    fail = sum(1 for x in lines if x.strip().startswith("❌"))
    skipped = sum(1 for x in lines if (x.strip().startswith("⚠") or x.strip().startswith("ℹ")))
    return success, fail, skipped


def _validate_mode(mode: str) -> str:
    if mode not in {"safe_copy", "in_place"}:
        raise ValueError("mode 必须是 safe_copy 或 in_place")
    return mode


def _run_bgr2rgb(paths: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    module = _load_script_module("script_bgr2rgb", "bgr2rgb.py")
    convert = module.convert_rgb_to_bgr_and_save

    input_dir = _normalize_dir(str(paths.get("input_dir", "")), "input_dir", must_exist=True)
    backup_path = ""

    if mode == "safe_copy":
        output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), [input_dir], "output_dir")
        lines = _run_with_captured_stdout(log, convert, str(input_dir), str(output_dir))
        success, fail, skipped = _counts_from_bgr(lines)
        return {
            "status": "success",
            "success_count": success,
            "fail_count": fail,
            "skipped_count": skipped,
            "output_path": str(output_dir),
            "backup_path": backup_path,
            "error": "",
        }

    if not backup_dir:
        raise ValueError("原地修改模式必须提供 backup_dir")
    backup_session = _backup_directories("bgr2rgb", [input_dir], backup_dir, log)
    backup_path = str(backup_session)

    temp_dir = Path(tempfile.mkdtemp(prefix="bgr2rgb_tmp_", dir=str(backup_session)))
    try:
        lines = _run_with_captured_stdout(log, convert, str(input_dir), str(temp_dir))
        _copy_all_files(temp_dir, input_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    success, fail, skipped = _counts_from_bgr(lines)
    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(input_dir),
        "backup_path": backup_path,
        "error": "",
    }


def _run_rename(paths: dict[str, Any], params: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    module = _load_script_module("script_rename2", "rename2.py")
    process = module.process_files_and_rename

    source_dir = _normalize_dir(str(paths.get("source_dir", "")), "source_dir", must_exist=True)
    prefix = str(params.get("prefix", "")).strip()
    if not prefix:
        raise ValueError("prefix 不能为空")
    if any(c in prefix for c in r'\/:*?"<>|'):
        raise ValueError(r'prefix 不能包含字符: \ / : * ? " < > |')

    backup_path = ""
    if mode == "safe_copy":
        target_dir = _ensure_safe_output_dir(str(paths.get("target_dir", "")), [source_dir], "target_dir")
    else:
        if not backup_dir:
            raise ValueError("原地修改模式必须提供 backup_dir")
        backup_session = _backup_directories("rename2", [source_dir], backup_dir, log)
        backup_path = str(backup_session)
        target_dir = source_dir

    lines = _run_with_captured_stdout(log, process, str(source_dir), str(target_dir), prefix)
    success, fail, skipped = _counts_from_rename(lines)
    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(target_dir),
        "backup_path": backup_path,
        "error": "",
    }


def _run_select_diverse(
    paths: dict[str, Any], params: dict[str, Any], mode: str, backup_dir: str, log: LogFn
) -> dict[str, Any]:
    module = _load_script_module("script_select_diverse", "select_diverse.py")
    select = module.select_diverse_images

    input_dir = _normalize_dir(str(paths.get("input_dir", "")), "input_dir", must_exist=True)
    try:
        select_ratio = float(params.get("select_ratio", 0.1))
    except (TypeError, ValueError) as exc:
        raise ValueError("select_ratio 必须是数字") from exc
    try:
        hamming_thresh = int(params.get("hamming_thresh", 10))
    except (TypeError, ValueError) as exc:
        raise ValueError("hamming_thresh 必须是整数") from exc
    if not (0 < select_ratio <= 1):
        raise ValueError("select_ratio 必须在 (0, 1] 区间")
    if hamming_thresh < 0:
        raise ValueError("hamming_thresh 必须 >= 0")

    backup_path = ""
    if mode == "safe_copy":
        output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), [input_dir], "output_dir")
    else:
        if not backup_dir:
            raise ValueError("原地修改模式必须提供 backup_dir")
        backup_session = _backup_directories("select_diverse", [input_dir], backup_dir, log)
        backup_path = str(backup_session)
        output_dir = input_dir / "_selected_diverse"
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        lines = _run_with_captured_stdout(
            log, select, str(input_dir), str(output_dir), select_ratio=select_ratio, hamming_thresh=hamming_thresh
        )
        success, fail, skipped = _counts_from_select(lines)
    except NameError as exc:
        if "sf" not in str(exc):
            raise
        # Keep original script untouched, but provide a deterministic fallback for the known runtime typo.
        log("warn", "select_diverse 脚本触发已知异常，启用兼容回退策略。")
        success = _select_diverse_compat_fallback(input_dir, output_dir, select_ratio, log)
        fail = 0
        skipped = 0

    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(output_dir),
        "backup_path": backup_path,
        "error": "",
    }


def _select_diverse_compat_fallback(input_dir: Path, output_dir: Path, select_ratio: float, log: LogFn) -> int:
    files = sorted([f for f in input_dir.glob("*.png") if f.is_file()])
    total = len(files)
    if total == 0:
        log("warn", "未找到 PNG 图片，兼容回退未执行复制。")
        return 0

    target = max(1, int(total * select_ratio))
    if target >= total:
        chosen = files
    else:
        step = total / target
        chosen = [files[int(i * step)] for i in range(target)]

    output_dir.mkdir(parents=True, exist_ok=True)
    for img in chosen:
        shutil.copy2(img, output_dir / img.name)
    log("info", f"兼容回退完成，已复制 {len(chosen)} 张图片。")
    return len(chosen)


def _run_json_path(paths: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    json_dir = _normalize_dir(str(paths.get("json_dir", "")), "json_dir", must_exist=True)
    image_dir = _normalize_dir(str(paths.get("image_dir", "")), "image_dir", must_exist=True)

    script_path = _project_root() / "script" / "更改json路径.py"
    if not script_path.exists():
        raise FileNotFoundError(f"未找到脚本: {script_path}")

    def run_script(target_json_dir: Path) -> list[str]:
        cmd = [sys.executable, str(script_path), str(target_json_dir), str(image_dir)]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            cmd,
            cwd=str(_project_root()),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        merged = []
        merged.extend(completed.stdout.splitlines())
        merged.extend(completed.stderr.splitlines())
        lines = [x.rstrip() for x in merged if x.strip()]
        _log_lines(lines, log)
        if completed.returncode != 0:
            tail = "\n".join(lines[-12:]) if lines else ""
            raise RuntimeError(f"json_path 脚本执行失败，退出码 {completed.returncode}\n{tail}")
        return lines

    backup_path = ""
    if mode == "safe_copy":
        output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), [json_dir], "output_dir")
        _copy_json_workspace(json_dir, output_dir, log)
        lines = run_script(output_dir)
        output_path = output_dir
    else:
        if not backup_dir:
            raise ValueError("原地修改模式必须提供 backup_dir")
        backup_session = _backup_directories("json_path", [json_dir], backup_dir, log)
        backup_path = str(backup_session)
        lines = run_script(json_dir)
        output_path = json_dir

    success, fail, skipped = _counts_from_json(lines)
    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(output_path),
        "backup_path": backup_path,
        "error": "",
    }


def execute_task(payload: dict[str, Any], log: LogFn) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象")

    task = str(payload.get("task", "")).strip()
    mode = _validate_mode(str(payload.get("mode", "safe_copy")).strip() or "safe_copy")
    paths = payload.get("paths", {}) or {}
    params = payload.get("params", {}) or {}
    backup_dir = str(payload.get("backup_dir", "")).strip()

    if not isinstance(paths, dict):
        raise ValueError("paths 必须是对象")
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")

    log("info", f"任务开始: task={task}, mode={mode}")
    if task == "bgr2rgb":
        return _run_bgr2rgb(paths, mode, backup_dir, log)
    if task == "rename2":
        return _run_rename(paths, params, mode, backup_dir, log)
    if task == "select_diverse":
        return _run_select_diverse(paths, params, mode, backup_dir, log)
    if task == "json_path":
        return _run_json_path(paths, mode, backup_dir, log)
    raise ValueError(f"不支持的 task: {task}")
