from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import random
import re
import shutil
import sys
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2
import imagehash
import numpy as np
from PIL import Image
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union


LogFn = Callable[[str, str], None]

_SCRIPT_MODULES: dict[str, Any] = {}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp"}


def _check_cancelled() -> bool:
    """检查当前任务是否已被取消"""
    from . import tasks
    manager = tasks.get_task_manager_ref()
    if manager is None:
        return False
    task_id = tasks.get_current_task_id()
    if task_id is None:
        return False
    return manager.is_task_cancelled(task_id)


def _require_not_cancelled() -> None:
    """如果任务已取消则抛出 KeyboardInterrupt"""
    if _check_cancelled():
        raise KeyboardInterrupt("任务已被取消")


def _counts_to_items(counts: dict[str, int]) -> list[dict[str, int | str]]:
    return [{"label": key, "count": int(value)} for key, value in counts.items()]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_json_path_script() -> Path:
    scripts_dir = _project_root() / "script"
    preferred_names = ["更改json路径.py", "修改json路径.py", "json_path.py"]
    for name in preferred_names:
        candidate = scripts_dir / name
        if candidate.exists():
            return candidate

    py_files = sorted([p for p in scripts_dir.glob("*.py") if p.is_file()], key=lambda p: str(p))
    candidates = [p for p in py_files if "json" in p.stem.lower()]
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"未找到 json_path 脚本，请检查目录: {scripts_dir}")


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


def _resolve_existing_path(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        for item in value:
            resolved = _resolve_existing_path(item)
            if resolved is not None:
                return resolved
        return None
    text = str(value).strip()
    if not text:
        return None
    path = Path(text).expanduser().resolve()
    if path.exists():
        return path
    return None


def _split_path_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(_split_path_values(item))
        return parts
    text = str(value).strip()
    if not text:
        return []
    return [chunk.strip() for chunk in text.split(";") if chunk.strip()]


def _normalize_input_mode(value: Any) -> tuple[str, list[str]]:
    mode = str(value or "folder").strip().lower()
    warnings: list[str] = []
    if mode in {"files", "file"}:
        if mode == "files":
            warnings.append("input_mode=files 已兼容为 file")
        return "file", warnings
    if mode in {"folder", "dir", "directory"}:
        return "folder", warnings
    raise ValueError("input_mode 只能是 folder 或 file")


def _collect_existing_paths(mapping: dict[str, Any], keys: list[str]) -> list[Path]:
    results: list[Path] = []
    for key in keys:
        if key not in mapping:
            continue
        for raw in _split_path_values(mapping.get(key)):
            resolved = _resolve_existing_path(raw)
            if resolved is not None:
                results.append(resolved)

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in results:
        marker = str(path)
        if marker not in seen:
            seen.add(marker)
            deduped.append(path)
    return deduped


def _collect_first_existing_dir(mapping: dict[str, Any], keys: list[str]) -> Path | None:
    for key in keys:
        if key not in mapping:
            continue
        for raw in _split_path_values(mapping.get(key)):
            resolved = _resolve_existing_path(raw)
            if resolved is not None and resolved.is_dir():
                return resolved
    return None


def _first_existing_path_from_mapping(mapping: dict[str, Any], keys: list[str]) -> Path | None:
    paths = _collect_existing_paths(mapping, keys)
    return paths[0] if paths else None


def _iter_preview_files(root: Path, recursive: bool = False) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    if recursive:
        return sorted([p for p in root.rglob("*") if p.is_file()], key=lambda p: str(p))
    return sorted([p for p in root.iterdir() if p.is_file()], key=lambda p: str(p))


def _build_preview_section(root: Path, recursive: bool = False, sample_limit: int = 20) -> dict[str, Any]:
    files = _iter_preview_files(root, recursive=recursive)
    counts: dict[str, int] = {}
    for file_path in files:
        suffix = file_path.suffix.lower().lstrip(".") or "[no_ext]"
        counts[suffix] = counts.get(suffix, 0) + 1
    sorted_counts = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    samples = [str(path) for path in files[:sample_limit]]
    return {
        "key": f"{root}:{'r' if recursive else 'n'}",
        "name": root.name or str(root),
        "title": root.name or str(root),
        "path": str(root),
        "counts_by_ext": sorted_counts,
        "counts": _counts_to_items(sorted_counts),
        "sample_files": samples,
        "samples": list(samples),
        "total_files": len(files),
    }


def _build_preview_result(roots: list[Path], recursive: bool = False, sample_limit: int = 20) -> dict[str, Any]:
    sections = [_build_preview_section(root, recursive=recursive, sample_limit=sample_limit) for root in roots]
    all_files: list[Path] = []
    for root in roots:
        all_files.extend(_iter_preview_files(root, recursive=recursive))
    counts: dict[str, int] = {}
    for file_path in all_files:
        suffix = file_path.suffix.lower().lstrip(".") or "[no_ext]"
        counts[suffix] = counts.get(suffix, 0) + 1
    sorted_counts = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    samples = [str(path) for path in all_files[:sample_limit]]
    return {
        "ok": True,
        "total_files": len(all_files),
        "counts_by_ext": sorted_counts,
        "counts": _counts_to_items(sorted_counts),
        "sample_files": samples,
        "samples": list(samples),
        "sections": sections,
        "warnings": [],
        "error": "",
    }


def preview_path_info(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是对象")

        recursive = bool(payload.get("recursive", False))
        sample_limit_raw = payload.get("sample_limit", 20)
        try:
            sample_limit = int(sample_limit_raw)
        except (TypeError, ValueError):
            sample_limit = 20
        if sample_limit <= 0:
            sample_limit = 20

        roots, warnings = _resolve_preview_targets(payload)
        result = _build_preview_result(roots, recursive=recursive, sample_limit=sample_limit)
        result["warnings"] = warnings
        return result
    except Exception as exc:
        return {
            "ok": False,
            "total_files": 0,
            "counts_by_ext": {},
            "counts": [],
            "sample_files": [],
            "samples": [],
            "sections": [],
            "warnings": [],
            "error": str(exc),
        }


def _collect_source_images_for_synthesize(source_folder: Path) -> list[Path]:
    return [
        p
        for p in sorted(source_folder.iterdir(), key=lambda p: str(p))
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}
    ]


def _extract_polygon_labels_from_json(json_path: Path) -> set[str]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    labels: set[str] = set()
    for shape in data.get("shapes", []):
        if not isinstance(shape, dict):
            continue
        if shape.get("shape_type") != "polygon":
            continue
        label = str(shape.get("label", "")).strip()
        if label:
            labels.add(label)
    return labels


def inspect_synthesize_source_info(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是对象")

        paths_data = payload.get("paths", {}) if isinstance(payload.get("paths"), dict) else {}
        source_folder = _collect_first_existing_dir(
            {**paths_data, **payload},
            ["source_folder", "input_dir", "source_dir", "path"],
        )
        if source_folder is None:
            raise ValueError("源物体目录无效")

        source_files = _collect_source_images_for_synthesize(source_folder)
        if not source_files:
            raise ValueError("源物体目录为空或没有可用图片")

        with_json: list[tuple[Path, Path]] = []
        without_json: list[Path] = []
        for img_path in source_files:
            json_path = img_path.with_suffix(".json")
            if json_path.exists():
                with_json.append((img_path, json_path))
            else:
                without_json.append(img_path)

        result: dict[str, Any] = {
            "ok": True,
            "mode": "",
            "source_folder": str(source_folder),
            "total_images": len(source_files),
            "with_json_count": len(with_json),
            "without_json_count": len(without_json),
            "detected_label": "",
            "labels": [],
            "error": "",
        }

        if with_json and without_json:
            result["ok"] = False
            result["mode"] = "mixed"
            result["error"] = "检测到源文件目录混合了带 JSON 和不带 JSON 的图片，请先整理目录后再执行。"
            return result

        if not with_json:
            result["mode"] = "all_without_json"
            return result

        all_labels: set[str] = set()
        for _, json_path in with_json:
            try:
                labels = _extract_polygon_labels_from_json(json_path)
            except Exception as exc:
                result["ok"] = False
                result["mode"] = "invalid_json"
                result["error"] = f"JSON 解析失败: {json_path.name} ({exc})"
                return result
            if not labels:
                result["ok"] = False
                result["mode"] = "missing_label"
                result["error"] = f"检测到源文件带 JSON，但存在无有效 polygon 标签文件: {json_path.name}"
                return result
            all_labels.update(labels)

        result["labels"] = sorted(all_labels)
        if len(all_labels) != 1:
            result["ok"] = False
            result["mode"] = "label_mismatch"
            result["error"] = "检测到源文件带 JSON，但是部分 JSON 的 label 不一致。"
            return result

        result["mode"] = "all_with_json"
        result["detected_label"] = next(iter(all_labels))
        return result
    except Exception as exc:
        return {
            "ok": False,
            "mode": "error",
            "source_folder": "",
            "total_images": 0,
            "with_json_count": 0,
            "without_json_count": 0,
            "detected_label": "",
            "labels": [],
            "error": str(exc),
        }


def _resolve_preview_targets(payload: dict[str, Any]) -> tuple[list[Path], list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象")

    paths_data = payload.get("paths", {}) if isinstance(payload.get("paths"), dict) else {}
    raw_input_mode = paths_data.get("input_mode", payload.get("input_mode", "folder"))
    input_mode, warnings = _normalize_input_mode(raw_input_mode)

    candidate_values: list[Any] = []
    candidate_keys = (
        "path",
        "file",
        "input_file",
        "source_file",
        "json_file",
        "image_file",
        "input_path",
        "input_dir",
        "source_path",
        "source_dir",
        "source_folder",
        "bg_json_folder",
        "json_dir",
        "image_dir",
        "target_dir",
        "output_dir",
    )
    for key in candidate_keys:
        if key in payload:
            candidate_values.append(payload.get(key))
    if isinstance(paths_data, dict):
        for key in candidate_keys:
            if key in paths_data:
                candidate_values.append(paths_data.get(key))

    resolved: list[Path] = []
    for candidate in candidate_values:
        for part in _split_path_values(candidate):
            path = _resolve_existing_path(part)
            if path is not None:
                resolved.append(path)

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in resolved:
        marker = str(path)
        if marker not in seen:
            seen.add(marker)
            deduped.append(path)

    if not deduped:
        raise ValueError("未找到可预览的有效路径")

    if input_mode == "file":
        file_roots = [path for path in deduped if path.is_file()]
        if file_roots:
            return file_roots, warnings
        if len(deduped) == 1:
            return deduped, warnings
        raise ValueError("文件模式下必须提供有效的单个文件或文件列表")

    dir_roots = [path for path in deduped if path.is_dir()]
    if dir_roots:
        return dir_roots, warnings
    return [deduped[0]], warnings


def _stage_single_file(file_path: Path, task_name: str) -> tuple[Path, Path]:
    stage_dir = Path(tempfile.mkdtemp(prefix=f"{task_name}_stage_"))
    staged = stage_dir / file_path.name
    shutil.copy2(file_path, staged)
    return stage_dir, staged


def _stage_files_with_ascii_names(file_paths: list[Path], task_name: str) -> tuple[Path, dict[str, Path]]:
    stage_dir = Path(tempfile.mkdtemp(prefix=f"{task_name}_stage_"))
    mapping: dict[str, Path] = {}
    for index, file_path in enumerate(file_paths, 1):
        staged_name = f"{task_name}_{index:04d}{file_path.suffix}"
        staged_path = stage_dir / staged_name
        shutil.copy2(file_path, staged_path)
        mapping[staged_path.name] = file_path
    return stage_dir, mapping


def _stage_rename_single_file(source_file: Path) -> tuple[Path, dict[str, Path]]:
    stage_dir = Path(tempfile.mkdtemp(prefix="rename2_stage_"))
    mapping: dict[str, Path] = {}

    staged_file = stage_dir / source_file.name
    shutil.copy2(source_file, staged_file)
    mapping[staged_file.name] = source_file

    if source_file.suffix.lower() != ".json":
        assoc_json = source_file.with_suffix(".json")
        if assoc_json.exists():
            staged_json = stage_dir / assoc_json.name
            shutil.copy2(assoc_json, staged_json)
            mapping[staged_json.name] = assoc_json

    return stage_dir, mapping


def _restore_outputs_to_dir(
    staged_output_dir: Path,
    staged_to_original: dict[str, Path],
    final_dir: Path,
    *,
    prefix: str = "",
    output_name_builder: Callable[[Path, Path], str] | None = None,
) -> list[Path]:
    final_dir.mkdir(parents=True, exist_ok=True)
    restored: list[Path] = []
    for output_file in sorted([p for p in staged_output_dir.iterdir() if p.is_file()], key=lambda p: str(p)):
        lookup_name = output_file.name
        if prefix and lookup_name.startswith(prefix):
            lookup_name = lookup_name[len(prefix) :]
        original_path = staged_to_original.get(lookup_name)
        if original_path is None:
            continue
        if output_name_builder is None:
            final_name = original_path.name
        else:
            final_name = output_name_builder(original_path, output_file)
        destination = final_dir / final_name
        shutil.copy2(output_file, destination)
        restored.append(destination)
    return restored


def _restore_outputs_back(
    staged_output_dir: Path,
    staged_to_original: dict[str, Path],
    *,
    prefix: str = "",
    output_name_builder: Callable[[Path, Path], str] | None = None,
) -> list[Path]:
    restored: list[Path] = []
    for output_file in sorted([p for p in staged_output_dir.iterdir() if p.is_file()], key=lambda p: str(p)):
        lookup_name = output_file.name
        if prefix and lookup_name.startswith(prefix):
            lookup_name = lookup_name[len(prefix) :]
        original_path = staged_to_original.get(lookup_name)
        if original_path is None:
            continue
        if output_name_builder is None:
            destination = original_path
        else:
            destination = original_path.parent / output_name_builder(original_path, output_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_file, destination)
        restored.append(destination)
    return restored


def _backup_files(file_paths: list[Path], backup_dir: str, task_name: str) -> Path:
    backup_root = _ensure_dir(backup_dir, "backup_dir")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = backup_root / f"{task_name}_{stamp}"
    suffix = 1
    while session.exists():
        suffix += 1
        session = backup_root / f"{task_name}_{stamp}_{suffix}"
    session.mkdir(parents=True, exist_ok=False)
    for index, file_path in enumerate(file_paths, 1):
        dst_name = file_path.name if index == 1 else f"{index:04d}_{file_path.name}"
        shutil.copy2(file_path, session / dst_name)
    return session


def _backup_single_file(file_path: Path, backup_dir: str, task_name: str) -> Path:
    backup_root = _ensure_dir(backup_dir, "backup_dir")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = backup_root / f"{task_name}_{stamp}"
    suffix = 1
    while session.exists():
        suffix += 1
        session = backup_root / f"{task_name}_{stamp}_{suffix}"
    session.mkdir(parents=True, exist_ok=False)
    dst = session / file_path.name
    shutil.copy2(file_path, dst)
    return session


def _save_image_as_rgb(src_path: Path, dst_path: Path) -> None:
    img = None
    try:
        raw = np.fromfile(str(src_path), dtype=np.uint8)
        if raw.size > 0:
            img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    except Exception:
        img = None
    if img is None:
        img = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"无法读取图像: {src_path.name}")

    if len(img.shape) == 2:
        Image.fromarray(img).save(dst_path)
        return

    if img.shape[2] == 4:
        converted = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        Image.fromarray(converted).save(dst_path)
        return

    converted = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    Image.fromarray(converted).save(dst_path)


def _convert_folder_bgr_to_rgb(input_dir: Path, output_dir: Path, log: LogFn) -> tuple[int, int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    supported = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
    success = 0
    fail = 0

    files = [p for p in sorted(input_dir.iterdir()) if p.is_file() and p.suffix.lower() in supported]
    if not files:
        log("warn", f"在目录 '{input_dir}' 中未找到支持的图片文件")
        return 0, 0, 0

    log("info", f"找到 {len(files)} 个图片文件")
    for file_path in files:
        try:
            _save_image_as_rgb(file_path, output_dir / file_path.name)
            log("info", f"成功处理并保存: {file_path.name}")
            success += 1
        except Exception as exc:
            log("error", f"处理图像 {file_path.name} 时发生错误: {exc}")
            fail += 1
    log("info", "所有图像处理完成")
    return success, fail, 0


def _file_preview_name(path: Path) -> str:
    return str(path.name)


def _compute_phash(file_path: Path):
    return imagehash.phash(Image.open(file_path))


def _select_diverse_with_target(
    input_dir: Path,
    output_dir: Path,
    target_count: int,
    hamming_thresh: int,
    log: LogFn,
) -> tuple[int, int, int]:
    image_files = sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS])
    total = len(image_files)
    if total == 0:
        log("warn", "没有找到图片文件！")
        return 0, 0, 0

    target_count = max(1, min(target_count, total))
    log("info", f"按张数优先执行，目标精选 {target_count} 张")

    hashes: list[tuple[Path, Any] | None] = []
    for i, file_path in enumerate(image_files, 1):
        _require_not_cancelled()
        try:
            hashes.append((file_path, _compute_phash(file_path)))
        except Exception as exc:
            log("warn", f"无法处理 {file_path.name}: {exc}")
            hashes.append(None)
        if i % 50 == 0 or i == total:
            log("info", f"已处理 {i}/{total}")

    _require_not_cancelled()
    valid = [item for item in hashes if item is not None]
    if not valid:
        return 0, 0, 0

    log("info", f"成功计算 {len(valid)} 个哈希，开始筛选...")

    selected: list[tuple[Path, Any]] = []
    for i, (file_path, file_hash) in enumerate(valid, 1):
        _require_not_cancelled()
        if not selected:
            selected.append((file_path, file_hash))
            continue
        min_dist = min((file_hash - chosen_hash) for _, chosen_hash in selected)
        if min_dist > hamming_thresh:
            selected.append((file_path, file_hash))
        if i % 50 == 0 or i == len(valid):
            log("info", f"筛选进度 {i}/{len(valid)}，已选中 {len(selected)} 张")

    _require_not_cancelled()
    if len(selected) > target_count:
        step = len(selected) / target_count
        selected = [selected[int(i * step)] for i in range(target_count)]
    elif len(selected) < target_count:
        chosen_paths = {p for p, _ in selected}
        remaining = [item for item in valid if item[0] not in chosen_paths]
        remaining.sort(
            key=lambda item: min((item[1] - chosen_hash) for _, chosen_hash in selected) if selected else 0,
            reverse=True,
        )
        for item in remaining:
            _require_not_cancelled()
            if len(selected) >= target_count:
                break
            selected.append(item)

    output_dir.mkdir(parents=True, exist_ok=True)
    for file_path, _ in selected:
        shutil.copy2(file_path, output_dir / file_path.name)
    log("info", f"兼容回退完成，已复制 {len(selected)} 张图片。")
    return len(selected), 0, 0


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


def _run_bgr2rgb(paths: dict[str, Any], params: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    module = _load_script_module("script_bgr2rgb", "bgr2rgb.py")
    convert = module.convert_rgb_to_bgr_and_save
    convert_reverse = getattr(module, "convert_bgr_to_rgb_and_save", None)

    input_mode, mode_warnings = _normalize_input_mode(paths.get("input_mode", "folder"))
    color_direction = str(params.get("color_direction", "rgb_to_bgr")).strip().lower()
    if color_direction not in {"rgb_to_bgr", "bgr_to_rgb"}:
        raise ValueError("color_direction 必须为 rgb_to_bgr 或 bgr_to_rgb")

    for warning in mode_warnings:
        log("warn", warning)

    if input_mode == "file":
        source_files = [
            p
            for p in _collect_existing_paths(paths, ["input_file", "source_file", "input_path", "file_path", "input_dir", "source_dir"])
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
        ]
        if not source_files:
            source_dir = _collect_first_existing_dir(paths, ["input_dir", "source_dir", "input_path"])
            if source_dir is not None:
                source_files = [p for p in sorted(source_dir.iterdir(), key=lambda p: str(p)) if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS]
        if not source_files:
            raise ValueError("文件模式下必须提供有效的输入文件")
        working_input, staged_to_original = _stage_files_with_ascii_names(source_files, "bgr2rgb")
        source_roots = sorted({str(p.parent) for p in source_files})
        default_output_dir = source_files[0].parent
    else:
        source_path = _collect_first_existing_dir(paths, ["input_dir", "source_dir", "input_path"])
        if source_path is None:
            raise ValueError("输入目录无效")
        source_files = [p for p in sorted(source_path.iterdir(), key=lambda p: str(p)) if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS]
        if not source_files:
            raise ValueError("输入目录无效")
        working_input, staged_to_original = _stage_files_with_ascii_names(source_files, "bgr2rgb")
        source_roots = [str(source_path)]
        default_output_dir = source_path

    backup_path = ""
    if mode == "safe_copy":
        protected_roots = [Path(root) for root in source_roots]
        output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), protected_roots, "output_dir")
        process_output_dir = Path(tempfile.mkdtemp(prefix="bgr2rgb_out_"))
        result_output_path = output_dir
    else:
        if backup_dir:
            backup_session = _backup_files(source_files, backup_dir, "bgr2rgb") if input_mode == "file" else _backup_directories("bgr2rgb", [default_output_dir], backup_dir, log)
            backup_path = str(backup_session)
        process_output_dir = Path(tempfile.mkdtemp(prefix="bgr2rgb_out_"))
        result_output_path = default_output_dir

    try:
        if color_direction == "rgb_to_bgr":
            lines = _run_with_captured_stdout(log, convert, str(working_input), str(process_output_dir))
            success, fail, skipped = _counts_from_bgr(lines)
        else:
            if callable(convert_reverse):
                lines = _run_with_captured_stdout(log, convert_reverse, str(working_input), str(process_output_dir))
                success, fail, skipped = _counts_from_bgr(lines)
            else:
                success, fail, skipped = _convert_folder_bgr_to_rgb(working_input, process_output_dir, log)

        if mode == "in_place":
            _restore_outputs_back(process_output_dir, staged_to_original)
        else:
            _restore_outputs_to_dir(process_output_dir, staged_to_original, result_output_path)
    finally:
        shutil.rmtree(process_output_dir, ignore_errors=True)
        shutil.rmtree(working_input, ignore_errors=True)

    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(result_output_path),
        "backup_path": backup_path,
        "error": "",
    }


def _run_rename(paths: dict[str, Any], params: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    module = _load_script_module("script_rename2", "rename2.py")
    process = module.process_files_and_rename

    input_mode, mode_warnings = _normalize_input_mode(paths.get("input_mode", "folder"))
    prefix = str(params.get("prefix", "")).strip()
    if not prefix:
        raise ValueError("prefix 不能为空")
    if any(c in prefix for c in r'\/:*?"<>|'):
        raise ValueError(r'prefix 不能包含字符: \ / : * ? " < > |')

    for warning in mode_warnings:
        log("warn", warning)

    if input_mode == "file":
        source_file = _first_existing_path_from_mapping(paths, ["input_file", "source_file", "input_path", "file_path", "input_dir", "source_dir", "json_file"])
        if source_file is None or not source_file.is_file():
            source_dir = _collect_first_existing_dir(paths, ["input_dir", "source_dir", "input_path"])
            if source_dir is not None:
                candidates = [
                    p
                    for p in sorted(source_dir.iterdir(), key=lambda p: str(p))
                    if p.is_file() and (p.suffix.lower() in _IMAGE_EXTENSIONS or p.suffix.lower() == ".json")
                ]
                source_file = candidates[0] if candidates else None
        if source_file is None:
            raise ValueError("文件模式下必须提供有效的输入文件")
        stage_inputs = [source_file]
        if source_file.suffix.lower() != ".json":
            assoc_json = source_file.with_suffix(".json")
            if assoc_json.exists():
                stage_inputs.append(assoc_json)
        source_dir = source_file.parent
        default_output_path = source_file.parent
        working_input, staged_to_original = _stage_rename_single_file(source_file)
    else:
        source_dir = _collect_first_existing_dir(paths, ["source_dir", "input_dir", "input_path"])
        if source_dir is None:
            raise ValueError("source_dir 不能为空")
        stage_inputs = [
            p
            for p in sorted(source_dir.iterdir(), key=lambda p: str(p))
            if p.is_file() and (p.suffix.lower() in _IMAGE_EXTENSIONS or p.suffix.lower() == ".json")
        ]
        if not stage_inputs:
            raise ValueError("source_dir 中没有可处理的文件")
        default_output_path = source_dir
        deduped_stage_inputs: list[Path] = []
        seen_inputs: set[str] = set()
        for file_path in stage_inputs:
            marker = str(file_path)
            if marker not in seen_inputs:
                seen_inputs.add(marker)
                deduped_stage_inputs.append(file_path)
        stage_inputs = deduped_stage_inputs
        working_input, staged_to_original = _stage_files_with_ascii_names(stage_inputs, "rename2")
    process_output_dir = Path(tempfile.mkdtemp(prefix="rename2_out_"))

    backup_path = ""
    if mode == "safe_copy":
        target_dir = _ensure_safe_output_dir(str(paths.get("target_dir", "")), [source_dir], "target_dir")
    else:
        if backup_dir:
            backup_session = _backup_files(stage_inputs, backup_dir, "rename2") if input_mode == "file" else _backup_directories("rename2", [source_dir], backup_dir, log)
            backup_path = str(backup_session)
        target_dir = process_output_dir

    try:
        lines = _run_with_captured_stdout(log, process, str(working_input), str(process_output_dir), prefix)
        success, fail, skipped = _counts_from_rename(lines)

        if mode == "safe_copy":
            _restore_outputs_to_dir(
                process_output_dir,
                staged_to_original,
                target_dir,
                prefix=prefix,
                output_name_builder=lambda original_path, _: f"{prefix}{original_path.name}",
            )
        else:
            _restore_outputs_back(
                process_output_dir,
                staged_to_original,
                prefix=prefix,
                output_name_builder=lambda original_path, _: f"{prefix}{original_path.name}",
            )
    finally:
        shutil.rmtree(process_output_dir, ignore_errors=True)
        shutil.rmtree(working_input, ignore_errors=True)

    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(target_dir if mode == "safe_copy" else default_output_path),
        "backup_path": backup_path,
        "error": "",
    }


def _run_select_diverse(
    paths: dict[str, Any], params: dict[str, Any], mode: str, backup_dir: str, log: LogFn
) -> dict[str, Any]:
    module = _load_script_module("script_select_diverse", "select_diverse.py")
    select = module.select_diverse_images

    input_mode, mode_warnings = _normalize_input_mode(paths.get("input_mode", "folder"))
    for warning in mode_warnings:
        log("warn", warning)

    try:
        select_ratio = float(params.get("select_ratio", 0.1))
    except (TypeError, ValueError) as exc:
        raise ValueError("select_ratio 必须是数字") from exc
    try:
        hamming_thresh = int(params.get("hamming_thresh", 10))
    except (TypeError, ValueError) as exc:
        raise ValueError("hamming_thresh 必须是整数") from exc

    target_count_raw = params.get("target_count")
    target_count: int | None
    if target_count_raw in (None, "", False):
        target_count = None
    else:
        try:
            target_count = int(target_count_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("target_count 必须是整数") from exc
        if target_count <= 0:
            target_count = None

    if not (0 < select_ratio <= 1):
        raise ValueError("select_ratio 必须在 (0, 1] 区间")
    if hamming_thresh < 0:
        raise ValueError("hamming_thresh 必须 >= 0")

    if target_count is not None:
        log("warn", "已提供 target_count，将优先忽略 select_ratio。")

    if input_mode == "file":
        source_files = [
            p
            for p in _collect_existing_paths(paths, ["input_file", "source_file", "input_path", "file_path", "input_dir", "source_dir"])
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
        ]
        if not source_files:
            source_dir = _collect_first_existing_dir(paths, ["input_dir", "source_dir", "input_path"])
            if source_dir is not None:
                source_files = [p for p in sorted(source_dir.iterdir(), key=lambda p: str(p)) if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS]
        if not source_files:
            raise ValueError("文件模式下必须提供有效的图片文件")
        working_input, staged_to_original = _stage_files_with_ascii_names(source_files, "select_diverse")
        source_roots = sorted({p.parent for p in source_files}, key=lambda p: str(p))
        inplace_output_path = source_files[0].parent
    else:
        source_path = _collect_first_existing_dir(paths, ["input_dir", "source_dir", "input_path"])
        if source_path is None:
            raise ValueError(f"输入目录无效：未找到有效的目录路径（已尝试 input_dir/source_dir/input_path）")
        all_files = [p for p in sorted(source_path.iterdir(), key=lambda p: str(p)) if p.is_file()]
        log("debug", f"[select_diverse] source_path={source_path}, total_files={len(all_files)}, extensions={set(p.suffix.lower() for p in all_files)}")
        source_files = [p for p in all_files if p.suffix.lower() in _IMAGE_EXTENSIONS]
        if not source_files:
            raise ValueError(f"输入目录无效：目录 '{source_path}' 中未找到图片文件（可用格式：{', '.join(sorted(_IMAGE_EXTENSIONS))}）")
        working_input, staged_to_original = _stage_files_with_ascii_names(source_files, "select_diverse")
        source_roots = [source_path]
        inplace_output_path = source_path

    backup_path = ""
    if mode == "safe_copy":
        output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), source_roots, "output_dir")
        process_output_dir = Path(tempfile.mkdtemp(prefix="select_diverse_out_"))
        result_output_path = output_dir
    else:
        if backup_dir:
            backup_session = _backup_files(source_files, backup_dir, "select_diverse") if input_mode == "file" else _backup_directories("select_diverse", [inplace_output_path], backup_dir, log)
            backup_path = str(backup_session)
        process_output_dir = Path(tempfile.mkdtemp(prefix="select_diverse_out_"))
        user_output_dir = paths.get("output_dir")
        if user_output_dir:
            result_output_path = Path(user_output_dir)
        else:
            result_output_path = inplace_output_path
            log("warn", "未指定输出目录，已将选中图片移回源目录（兼容模式）")

    try:
        _require_not_cancelled()
        if target_count is not None:
            try:
                lines = _run_with_captured_stdout(
                    log,
                    select,
                    str(working_input),
                    str(process_output_dir),
                    select_ratio=select_ratio,
                    hamming_thresh=hamming_thresh,
                    target_count=target_count,
                )
                success, fail, skipped = _counts_from_select(lines)
            except TypeError as exc:
                if "target_count" not in str(exc):
                    raise
                log("warn", "当前脚本接口未暴露 target_count 参数，已切换到兼容内部筛选逻辑。")
                _require_not_cancelled()
                success, fail, skipped = _select_diverse_with_target(working_input, process_output_dir, target_count, hamming_thresh, log)
        else:
            try:
                lines = _run_with_captured_stdout(
                    log, select, str(working_input), str(process_output_dir), select_ratio=select_ratio, hamming_thresh=hamming_thresh
                )
                success, fail, skipped = _counts_from_select(lines)
            except NameError as exc:
                if "sf" not in str(exc):
                    raise
                log("warn", "select_diverse 脚本触发已知异常，启用兼容回退策略。")
                _require_not_cancelled()
                success = _select_diverse_compat_fallback(working_input, process_output_dir, select_ratio, log)
                fail = 0
                skipped = 0

        if mode == "in_place":
            result_output_path.mkdir(parents=True, exist_ok=True)
            for output_file in sorted(
                [p for p in process_output_dir.iterdir() if p.is_file()], key=lambda p: str(p)
            ):
                original_path = staged_to_original.get(output_file.name)
                if original_path is None:
                    continue
                dest = result_output_path / original_path.name
                shutil.move(str(output_file), str(dest))
                if dest != original_path and original_path.exists():
                    original_path.unlink()
        else:
            _restore_outputs_to_dir(process_output_dir, staged_to_original, result_output_path)
    finally:
        shutil.rmtree(process_output_dir, ignore_errors=True)
        shutil.rmtree(working_input, ignore_errors=True)

    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(result_output_path),
        "backup_path": backup_path,
        "error": "",
    }


def _select_diverse_compat_fallback(input_dir: Path, output_dir: Path, select_ratio: float, log: LogFn) -> int:
    files = sorted([f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() in _IMAGE_EXTENSIONS])
    total = len(files)
    if total == 0:
        log("warn", "未找到图片文件，兼容回退未执行复制。")
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
    script_path = _project_root() / "script" / "更改json路径.py"
    if not script_path.exists():
        raise FileNotFoundError(f"未找到脚本: {script_path}")

    input_mode, mode_warnings = _normalize_input_mode(paths.get("input_mode", "folder"))
    for warning in mode_warnings:
        log("warn", warning)

    image_path = _first_existing_path_from_mapping(paths, ["image_dir", "image_file", "image_path"])
    if image_path is None:
        raise ValueError("image_dir 不能为空")
    image_dir = image_path if image_path.is_dir() else image_path.parent

    def run_script(target_json_dir: Path, source_json_dir: Path | None = None) -> list[str]:
        cmd = [sys.executable, str(script_path), str(target_json_dir), str(image_dir)]
        if source_json_dir:
            cmd.append(str(source_json_dir))
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
    if input_mode == "file":
        source_json = _first_existing_path_from_mapping(paths, ["json_file", "input_file", "source_file", "input_path", "file_path", "json_dir"])
        if source_json is None or not source_json.is_file() or source_json.suffix.lower() != ".json":
            json_dir_candidate = _collect_first_existing_dir(paths, ["json_dir", "source_dir", "input_dir"])
            if json_dir_candidate is not None:
                json_candidates = [p for p in sorted(json_dir_candidate.iterdir(), key=lambda p: str(p)) if p.is_file() and p.suffix.lower() == ".json"]
                source_json = json_candidates[0] if json_candidates else None
        if source_json is None:
            raise ValueError("文件模式下必须提供有效的单个 JSON 文件")

        working_input = Path(tempfile.mkdtemp(prefix="json_path_stage_"))
        staged_json = working_input / source_json.name
        shutil.copy2(source_json, staged_json)
        staged_to_original = {staged_json.name: source_json}
        result_output_path = source_json.parent

        if mode == "safe_copy":
            output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), [source_json.parent], "output_dir")
            output_path = output_dir
        else:
            if backup_dir:
                backup_session = _backup_files([source_json], backup_dir, "json_path")
                backup_path = str(backup_session)
            output_path = result_output_path

        try:
            lines = run_script(working_input, source_json.parent)
            if mode == "safe_copy":
                _restore_outputs_to_dir(working_input, staged_to_original, output_path)
            else:
                _restore_outputs_back(working_input, staged_to_original)
        finally:
            shutil.rmtree(working_input, ignore_errors=True)
    else:
        json_dir = _collect_first_existing_dir(paths, ["json_dir", "source_dir", "input_dir", "input_path"])
        if json_dir is None:
            raise ValueError("json_dir 不能为空")

        if mode == "safe_copy":
            output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), [json_dir], "output_dir")
            _copy_json_workspace(json_dir, output_dir, log)
            lines = run_script(output_dir)
            output_path = output_dir
        else:
            if backup_dir:
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


def _run_rename_v2(paths: dict[str, Any], params: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    module = _load_script_module("script_rename2", "rename2.py")
    process = module.process_files_and_rename

    input_mode, mode_warnings = _normalize_input_mode(paths.get("input_mode", "folder"))
    prefix = str(params.get("prefix", "")).strip()
    if not prefix:
        raise ValueError("prefix 不能为空")
    if any(c in prefix for c in r'\/:*?"<>|'):
        raise ValueError(r'prefix 不能包含字符: \ / : * ? " < > |')

    for warning in mode_warnings:
        log("warn", warning)

    if input_mode == "file":
        source_files = [
            p
            for p in _collect_existing_paths(paths, ["input_file", "source_file", "input_path", "file_path", "input_dir", "source_dir", "json_file"])
            if p.is_file() and (p.suffix.lower() in _IMAGE_EXTENSIONS or p.suffix.lower() == ".json")
        ]
        if not source_files:
            source_dir = _collect_first_existing_dir(paths, ["input_dir", "source_dir", "input_path"])
            if source_dir is not None:
                source_files = [
                    p
                    for p in sorted(source_dir.iterdir(), key=lambda p: str(p))
                    if p.is_file() and (p.suffix.lower() in _IMAGE_EXTENSIONS or p.suffix.lower() == ".json")
                ]
        if not source_files:
            raise ValueError("文件模式下必须提供有效输入文件")

        stage_inputs: list[Path] = []
        for source_file in source_files:
            stage_inputs.append(source_file)
            if source_file.suffix.lower() != ".json":
                assoc_json = source_file.with_suffix(".json")
                if assoc_json.exists():
                    stage_inputs.append(assoc_json)
        stage_inputs = list(dict.fromkeys(stage_inputs))
        source_roots = sorted({p.parent for p in stage_inputs}, key=lambda p: str(p))
        default_output_path = source_roots[0]
    else:
        source_dir = _collect_first_existing_dir(paths, ["source_dir", "input_dir", "input_path"])
        if source_dir is None:
            raise ValueError("source_dir 不能为空")
        stage_inputs = [
            p
            for p in sorted(source_dir.iterdir(), key=lambda p: str(p))
            if p.is_file() and (p.suffix.lower() in _IMAGE_EXTENSIONS or p.suffix.lower() == ".json")
        ]
        if not stage_inputs:
            raise ValueError("source_dir 中没有可处理文件")
        stage_inputs = list(dict.fromkeys(stage_inputs))
        source_roots = [source_dir]
        default_output_path = source_dir

    working_input, staged_to_original = _stage_files_with_ascii_names(stage_inputs, "rename2")
    process_output_dir = Path(tempfile.mkdtemp(prefix="rename2_out_"))

    backup_path = ""
    if mode == "safe_copy":
        target_dir = _ensure_safe_output_dir(str(paths.get("target_dir", "")), source_roots, "target_dir")
    else:
        if backup_dir:
            backup_session = _backup_files(stage_inputs, backup_dir, "rename2") if input_mode == "file" else _backup_directories("rename2", source_roots, backup_dir, log)
            backup_path = str(backup_session)
        target_dir = process_output_dir

    try:
        lines = _run_with_captured_stdout(log, process, str(working_input), str(process_output_dir), prefix)
        success, fail, skipped = _counts_from_rename(lines)

        if mode == "safe_copy":
            _restore_outputs_to_dir(
                process_output_dir,
                staged_to_original,
                target_dir,
                prefix=prefix,
                output_name_builder=lambda original_path, _: f"{prefix}{original_path.name}",
            )
        else:
            _restore_outputs_back(
                process_output_dir,
                staged_to_original,
                prefix=prefix,
                output_name_builder=lambda original_path, _: f"{prefix}{original_path.name}",
            )
    finally:
        shutil.rmtree(process_output_dir, ignore_errors=True)
        shutil.rmtree(working_input, ignore_errors=True)

    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(target_dir if mode == "safe_copy" else default_output_path),
        "backup_path": backup_path,
        "error": "",
    }


def _run_json_path_v2(paths: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    script_path = _resolve_json_path_script()

    input_mode, mode_warnings = _normalize_input_mode(paths.get("input_mode", "folder"))
    for warning in mode_warnings:
        log("warn", warning)

    image_path = _first_existing_path_from_mapping(paths, ["image_dir", "image_file", "image_path"])
    if image_path is None:
        raise ValueError("image_dir 不能为空")
    image_dir = image_path if image_path.is_dir() else image_path.parent

    def run_script(target_json_dir: Path, source_json_dir: Path | None = None) -> list[str]:
        cmd = [sys.executable, str(script_path), str(target_json_dir), str(image_dir)]
        if source_json_dir:
            cmd.append(str(source_json_dir))
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
        merged: list[str] = []
        merged.extend(completed.stdout.splitlines())
        merged.extend(completed.stderr.splitlines())
        lines = [x.rstrip() for x in merged if x.strip()]
        _log_lines(lines, log)
        if completed.returncode != 0:
            tail = "\n".join(lines[-12:]) if lines else ""
            raise RuntimeError(f"json_path 脚本执行失败，退出码 {completed.returncode}\n{tail}")
        return lines

    backup_path = ""
    if input_mode == "file":
        source_jsons = [
            p
            for p in _collect_existing_paths(paths, ["json_file", "input_file", "source_file", "input_path", "file_path", "json_dir"])
            if p.is_file() and p.suffix.lower() == ".json"
        ]
        if not source_jsons:
            json_dir_candidate = _collect_first_existing_dir(paths, ["json_dir", "source_dir", "input_dir"])
            if json_dir_candidate is not None:
                source_jsons = [
                    p for p in sorted(json_dir_candidate.iterdir(), key=lambda p: str(p)) if p.is_file() and p.suffix.lower() == ".json"
                ]
        if not source_jsons:
            raise ValueError("文件模式下必须提供有效的 JSON 文件")

        source_jsons = list(dict.fromkeys(source_jsons))
        source_roots = sorted({p.parent for p in source_jsons}, key=lambda p: str(p))
        result_output_path = source_roots[0]

        working_input, staged_to_original = _stage_files_with_ascii_names(source_jsons, "json_path")
        if mode == "safe_copy":
            output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), source_roots, "output_dir")
            output_path = output_dir
        else:
            if backup_dir:
                backup_session = _backup_files(source_jsons, backup_dir, "json_path")
                backup_path = str(backup_session)
            output_path = result_output_path

        try:
            lines = run_script(working_input, source_roots[0])
            if mode == "safe_copy":
                _restore_outputs_to_dir(working_input, staged_to_original, output_path)
            else:
                _restore_outputs_back(working_input, staged_to_original)
        finally:
            shutil.rmtree(working_input, ignore_errors=True)
    else:
        json_dir = _collect_first_existing_dir(paths, ["json_dir", "source_dir", "input_dir", "input_path"])
        if json_dir is None:
            raise ValueError("json_dir 不能为空")

        if mode == "safe_copy":
            output_dir = _ensure_safe_output_dir(str(paths.get("output_dir", "")), [json_dir], "output_dir")
            _copy_json_workspace(json_dir, output_dir, log)
            lines = run_script(output_dir)
            output_path = output_dir
        else:
            if backup_dir:
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


def _run_reorder_labels(paths: dict[str, Any], mode: str, backup_dir: str, log: LogFn) -> dict[str, Any]:
    """重新排序JSON中的shapes，把station标签移到最前面（底层），方便数字标签移动"""
    input_mode, mode_warnings = _normalize_input_mode(paths.get("input_mode", "folder"))
    for warning in mode_warnings:
        log("warn", warning)

    def process_single_json(json_path: Path) -> tuple[bool, str]:
        """处理单个JSON文件，返回(是否成功, 消息)"""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            shapes = data.get('shapes', [])
            if not shapes:
                return True, f"⚠️ {json_path.name} 无shapes"

            # 分离station和其他标签
            station_shapes = [s for s in shapes if s.get('label') == 'station']
            other_shapes = [s for s in shapes if s.get('label') != 'station']

            # 检查是否有station标签
            if not station_shapes:
                return True, f"ℹ️ {json_path.name} 无station标签（跳过）"

            # 重新排序：station在最前面（底层），其他标签在station上面
            data['shapes'] = station_shapes + other_shapes

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return True, f"✅ {json_path.name}"
        except json.JSONDecodeError as e:
            return False, f"❌ {json_path.name} JSON格式错误: {e}"
        except Exception as e:
            return False, f"❌ {json_path.name} 处理失败: {e}"

    def process_directory(json_dir: Path) -> list[str]:
        """处理目录下的所有JSON文件"""
        results = []
        json_files = [p for p in json_dir.glob("*.json") if p.is_file()]
        for json_path in sorted(json_files):
            success, msg = process_single_json(json_path)
            if success or "⚠️" in msg or "ℹ️" in msg:
                log("info", msg)
            else:
                log("error", msg)
            results.append(msg)
        return results

    if input_mode == "file":
        source_jsons = [
            p
            for p in _collect_existing_paths(paths, ["json_file", "input_file", "source_file", "input_path", "file_path", "json_dir"])
            if p.is_file() and p.suffix.lower() == ".json"
        ]
        if not source_jsons:
            json_dir_candidate = _collect_first_existing_dir(paths, ["json_dir", "source_dir", "input_dir"])
            if json_dir_candidate is not None:
                source_jsons = [
                    p for p in sorted(json_dir_candidate.iterdir(), key=lambda p: str(p)) if p.is_file() and p.suffix.lower() == ".json"
                ]
        if not source_jsons:
            raise ValueError("文件模式下必须提供有效的 JSON 文件")

        # 直接处理每个JSON文件（原地修改）
        results = []
        for json_path in source_jsons:
            success, msg = process_single_json(json_path)
            results.append((success, msg))
            if success or "⚠️" in msg or "ℹ️" in msg:
                log("info", msg)
            else:
                log("error", msg)

        result_output_path = source_jsons[0].parent
        success = sum(1 for s, m in results if s)
        fail = sum(1 for s, m in results if not s and "⚠️" not in m and "ℹ️" not in m)
        skipped = sum(1 for s, m in results if "⚠️" in m or "ℹ️" in m)
    else:
        json_dir = _collect_first_existing_dir(paths, ["json_dir", "source_dir", "input_dir", "input_path"])
        if json_dir is None:
            raise ValueError("json_dir 不能为空")

        lines = process_directory(json_dir)
        result_output_path = json_dir
        success = sum(1 for x in lines if x.strip().startswith("✅"))
        fail = sum(1 for x in lines if x.strip().startswith("❌"))
        skipped = sum(1 for x in lines if x.strip().startswith("ℹ️") or x.strip().startswith("⚠️"))

    return {
        "status": "success",
        "success_count": success,
        "fail_count": fail,
        "skipped_count": skipped,
        "output_path": str(result_output_path),
        "backup_path": "",
        "error": "",
    }


def _get_cache_path(cache_dir: str, filename: str, mtime: float, max_size: tuple[int, int], model_name: str) -> str:
    """生成本地缓存路径"""
    name_without_ext = Path(filename).stem
    return str(Path(cache_dir) / f"{name_without_ext}_{mtime}_{max_size[0]}_{max_size[1]}_{model_name}.png")


def _is_cache_valid(cache_path: str, source_mtime: float) -> bool:
    """校验缓存是否有效"""
    cache_p = Path(cache_path)
    if not cache_p.exists():
        return False
    return cache_p.stat().st_mtime >= source_mtime


def _create_alpha_mask_from_labelme(json_path: str, img_height: int, img_width: int, target_label: str) -> "np.ndarray":
    """从 LabelMe JSON 读取指定标签的多边形，创建 alpha mask"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    mask = np.zeros((img_height, img_width), dtype=np.uint8)
    for shape in data.get("shapes", []):
        if shape.get("label") == target_label and shape.get("shape_type") == "polygon":
            points = np.array(shape["points"], dtype=np.int32)
            cv2.fillPoly(mask, [points], 255)
    return mask


def _run_synthesize(
    paths: dict[str, Any],
    params: dict[str, Any],
    mode: str,
    backup_dir: str,
    log: LogFn,
) -> dict[str, Any]:
    """合成任务主函数"""
    # 解析参数
    label = str(params.get("label", "")).strip()
    target_label = str(params.get("target_label", "")).strip() or None
    max_objects = int(params.get("max_objects", 3))
    max_object_size = int(params.get("max_object_size", 350))
    rotation_angle = float(params.get("rotation_angle", 30))
    grass_label = str(params.get("grass_label", "grass")).strip()

    # 获取路径
    source_folder = _collect_first_existing_dir(paths, ["source_folder", "input_dir"])
    bg_json_folder = _collect_first_existing_dir(paths, ["bg_json_folder", "source_dir"])

    if source_folder is None:
        raise ValueError("源物体目录无效")
    if bg_json_folder is None:
        raise ValueError("背景图目录无效")
    output_folder = _ensure_safe_output_dir(str(paths.get("output_folder", "")), [source_folder, bg_json_folder], "output_dir")

    source_folder = Path(source_folder)
    bg_json_folder = Path(bg_json_folder)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    source_inspection = inspect_synthesize_source_info({"source_folder": str(source_folder)})
    if not source_inspection.get("ok"):
        raise ValueError(str(source_inspection.get("error") or "源目录校验失败"))

    source_mode = str(source_inspection.get("mode", ""))
    detected_label = str(source_inspection.get("detected_label", "")).strip()

    if source_mode == "all_with_json":
        if not detected_label:
            raise ValueError("源目录 JSON 标签检测失败：未检测到唯一标签。")
        if target_label and target_label != detected_label:
            raise ValueError(
                f"源标注标签与源目录不一致：当前为 '{target_label}'，检测到唯一标签为 '{detected_label}'。"
            )
        target_label = detected_label
        if not label:
            label = detected_label
    elif source_mode == "all_without_json":
        if target_label:
            log("warn", "检测到源目录图片不带 JSON，已忽略源标注标签。")
        target_label = None
        if not label:
            raise ValueError("源图片不带 JSON 时，必须填写合成后标注标签。")
    else:
        raise ValueError(str(source_inspection.get("error") or "源目录校验失败"))

    log("info", f"合成任务开始: label={label}, max_objects={max_objects}")

    # 扫描源物体
    source_files = [p for p in source_folder.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}]
    if not source_files:
        raise ValueError(f"源物体目录为空: {source_folder}")

    # 扫描背景图
    bg_json_pairs = []
    for file in bg_json_folder.iterdir():
        if file.is_file() and file.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
            json_path = bg_json_folder / f"{file.stem}.json"
            if json_path.exists():
                bg_json_pairs.append((file, json_path))

    if not bg_json_pairs:
        raise ValueError(f"背景图目录中未找到带 JSON 的图片: {bg_json_folder}")

    log("info", f"源物体: {len(source_files)} 张, 背景图: {len(bg_json_pairs)} 张")

    # 缓存目录：打包态放在 exe 同级，否则用系统临时目录
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        cache_dir = Path(sys.executable).parent / "cache" / "img_tool_synthesize_cache"
    else:
        cache_dir = Path(tempfile.gettempdir()) / "img_tool_synthesize_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    log("info", f"缓存目录: {cache_dir}")

    model_name = "u2net"

    # 均衡轮转池：打乱原图列表，均衡分配到各背景图
    source_pool = random.sample(source_files, len(source_files))
    source_index = 0

    # 处理每张背景图
    success_count = 0
    fail_count = 0

    for idx, (bg_path, json_path) in enumerate(bg_json_pairs, 1):
        _require_not_cancelled()
        try:
            # 从轮转池中选取原图
            num_objects = random.randint(1, max_objects)
            selected_sources = []
            for _ in range(num_objects):
                if source_index >= len(source_pool):
                    random.shuffle(source_pool)
                    source_index = 0
                selected_sources.append(source_pool[source_index])
                source_index += 1

            result = _process_single_synthesize(
                bg_path, json_path, selected_sources, output_folder,
                label, target_label, max_object_size, model_name,
                rotation_angle, grass_label, cache_dir, log
            )
            if result:
                success_count += 1
            else:
                fail_count += 1
        except Exception as exc:
            log("error", f"处理失败 {bg_path.name}: {str(exc)}")
            fail_count += 1

        if idx % 10 == 0 or idx == len(bg_json_pairs):
            log("info", f"已处理 {idx}/{len(bg_json_pairs)}")

    log("info", f"合成完成: 成功 {success_count}, 失败 {fail_count}")

    return {
        "status": "success",
        "success_count": success_count,
        "fail_count": fail_count,
        "skipped_count": 0,
        "output_path": str(output_folder),
        "backup_path": "",
        "error": "",
    }


def _process_single_synthesize(
    bg_path: Path,
    json_path: Path,
    selected_sources: list[Path],
    output_folder: Path,
    label: str,
    target_label: str | None,
    max_object_size: int,
    model_name: str,
    rotation_angle: float,
    grass_label: str,
    cache_dir: Path,
    log: LogFn,
) -> bool:
    """处理单张背景图的合成"""

    # 加载背景图 - 强制转换为 BGR
    bg_img = cv2.imread(str(bg_path), cv2.IMREAD_COLOR)
    if bg_img is None:
        return False

    # 转换为 BGRA (4通道)
    if len(bg_img.shape) == 2:
        bg_img = cv2.cvtColor(bg_img, cv2.COLOR_GRAY2BGRA)
    elif bg_img.shape[2] == 3:
        bg_img = cv2.cvtColor(bg_img, cv2.COLOR_BGR2BGRA)
    # 如果已经是 4 通道，假设是 BGRA 格式，直接使用

    # 解析 JSON 获取 grass 和 obstacles 区域
    with open(json_path, "r", encoding="utf-8") as f:
        original_json = json.load(f)

    grass_polygons = []
    obstacles_polygons = []
    for shape in original_json.get("shapes", []):
        if shape.get("shape_type") != "polygon":
            continue
        poly_points = [tuple(p) for p in shape["points"]]
        try:
            poly = Polygon(poly_points)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_valid:
                if shape.get("label") == grass_label:
                    grass_polygons.append(poly)
                elif shape.get("label") == "obstacles":
                    obstacles_polygons.append(poly)
        except Exception:
            pass

    bg_h, bg_w = bg_img.shape[:2]

    placed_objects = []

    for source_path in selected_sources:
        obj_result = _get_or_create_object_cache(
            source_path, target_label, max_object_size, model_name, cache_dir, log
        )
        if obj_result is None:
            continue

        object_img = obj_result

        # 旋转和镜像
        object_img = _apply_rotation_and_flip(object_img, rotation_angle, log)

        # 放置物体
        placed, bbox = _place_object_on_grass(
            object_img, bg_img, grass_polygons, obstacles_polygons, placed_objects, log
        )

        if placed and bbox is not None:
            # 创建多边形标注
            obj_shape = _create_polygon_from_object(object_img, bbox, label)
            placed_objects.append((bbox, object_img, obj_shape))

    if not placed_objects:
        return False

    # 保存合成图
    output_img_path = output_folder / bg_path.name
    if bg_img.shape[2] == 4:
        cv2.imwrite(str(output_img_path), cv2.cvtColor(bg_img, cv2.COLOR_BGRA2BGR))
    else:
        cv2.imwrite(str(output_img_path), bg_img)

    # 更新 JSON
    new_shapes = list(original_json.get("shapes", []))
    for bbox, object_img, obj_shape in placed_objects:
        new_shapes = _adjust_polygons_with_object(new_shapes, obj_shape, log)
        new_shapes.append(obj_shape)

    # 读取合成图并转为 base64
    with open(output_img_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode("utf-8")

    new_json = {
        "version": original_json.get("version", "4.5.6"),
        "flags": original_json.get("flags", {}),
        "shapes": new_shapes,
        "imagePath": bg_path.name,
        "imageData": img_data,
        "imageWidth": original_json.get("imageWidth", bg_w),
        "imageHeight": original_json.get("imageHeight", bg_h),
    }

    output_json_path = output_folder / f"{bg_path.stem}.json"
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(new_json, f, ensure_ascii=False, indent=2)

    return True


def _get_or_create_object_cache(
    source_path: Path,
    target_label: str | None,
    max_object_size: int,
    model_name: str,
    cache_dir: Path,
    log: LogFn,
) -> "np.ndarray | None":
    """获取或创建物体缓存"""
    from PIL import Image
    from rembg import remove

    source_stat = source_path.stat()
    source_mtime = source_stat.st_mtime
    cache_path = _get_cache_path(str(cache_dir), source_path.name, source_mtime, (max_object_size, max_object_size), model_name)

    # 检查缓存
    if _is_cache_valid(cache_path, source_mtime):
        try:
            img = cv2.imread(cache_path, cv2.IMREAD_UNCHANGED)
            if img is not None:
                # 确保缓存图片是 4 通道 BGRA
                # 注意：cv2.imwrite 保存 BGRA 时，读取回来仍是 BGRA
                # 所以 4 通道时不需要转换
                if len(img.shape) == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                elif img.shape[2] == 3:
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                # 4通道时假设是 BGRA，直接使用
                return img
        except Exception:
            pass

    # 加载图片 - 保持原始通道
    img = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None

    # 转换为 BGRA 4通道
    # 注意：cv2.imread 对 PNG 等格式返回 BGRA（不是 RGBA），所以 4 通道时不需要转换
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    # 4通道时假设是 BGRA，直接使用

    h, w = img.shape[:2]

    # 尝试用 labelme 标注抠图
    json_path = source_path.parent / f"{source_path.stem}.json"
    has_label_mask = False

    if target_label and json_path.exists():
        try:
            label_mask = _create_alpha_mask_from_labelme(str(json_path), h, w, target_label)
            if cv2.countNonZero(label_mask) > 0:
                img[:, :, 3] = label_mask
                has_label_mask = True
        except Exception:
            pass

    # 用 rembg 抠图
    if not has_label_mask:
        try:
            img_rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
            img_pil = Image.fromarray(img_rgba)
            img_no_bg_pil = remove(img_pil, model=model_name, alpha_matting=False)
            img_no_bg_np = np.array(img_no_bg_pil)
            # rembg 可能返回 RGB(3通道) 或 RGBA(4通道)
            if len(img_no_bg_np.shape) == 2:
                # 灰度图，转为 BGRA
                img_no_bg = cv2.cvtColor(img_no_bg_np, cv2.COLOR_GRAY2BGR)
                img = cv2.cvtColor(img_no_bg, cv2.COLOR_BGR2BGRA)
            elif img_no_bg_np.shape[2] == 3:
                # RGB 转 BGRA
                img = cv2.cvtColor(img_no_bg_np, cv2.COLOR_RGB2BGRA)
            elif img_no_bg_np.shape[2] == 4:
                # RGBA 转 BGRA
                img = cv2.cvtColor(img_no_bg_np, cv2.COLOR_RGBA2BGRA)
            else:
                return None
        except Exception:
            return None

    # 缩放
    h, w = img.shape[:2]
    if w > max_object_size or h > max_object_size:
        scale = min(max_object_size / w, max_object_size / h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # 保存缓存
    cv2.imwrite(cache_path, img)
    return img


def _apply_rotation_and_flip(object_img: "np.ndarray", max_angle: float, log: LogFn) -> "np.ndarray":
    """应用随机旋转和镜像"""
    # 水平镜像
    if random.choice([True, False]):
        object_img = cv2.flip(object_img, 1)

    # 随机旋转
    angle = random.uniform(-max_angle, max_angle)
    h, w = object_img.shape[:2]
    center = (w // 2, h // 2)

    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    # 计算旋转后尺寸
    cos_val = np.abs(rotation_matrix[0, 0])
    sin_val = np.abs(rotation_matrix[0, 1])
    new_w = int((h * sin_val) + (w * cos_val))
    new_h = int((h * cos_val) + (w * sin_val))

    rotation_matrix[0, 2] += (new_w / 2) - center[0]
    rotation_matrix[1, 2] += (new_h / 2) - center[1]

    rotated = cv2.warpAffine(
        object_img,
        rotation_matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=[0, 0, 0, 0]
    )

    return rotated


def _place_object_on_grass(
    object_img: "np.ndarray",
    bg_img: "np.ndarray",
    grass_polygons: list,
    obstacles_polygons: list,
    placed_objects: list,
    log: LogFn,
) -> tuple[bool, tuple | None]:
    """将物体放置在草地上"""
    from shapely.geometry import Point

    # 确保物体图片是 4 通道
    if len(object_img.shape) == 2:
        object_img = cv2.cvtColor(object_img, cv2.COLOR_GRAY2BGRA)
    elif object_img.shape[2] == 3:
        object_img = cv2.cvtColor(object_img, cv2.COLOR_BGR2BGRA)

    # 确保背景图片是 4 通道
    if len(bg_img.shape) == 2:
        bg_img = cv2.cvtColor(bg_img, cv2.COLOR_GRAY2BGRA)
    elif bg_img.shape[2] == 3:
        bg_img = cv2.cvtColor(bg_img, cv2.COLOR_BGR2BGRA)

    obj_h, obj_w = object_img.shape[:2]
    bg_h, bg_w = bg_img.shape[:2]

    # 没有 grass 标签，或者 grass union 计算失败，直接跳过不放置
    if not grass_polygons:
        return False, None

    # 计算 grass union 供后续检查使用
    try:
        union_grass = unary_union(grass_polygons)
    except Exception:
        # grass 计算失败，跳过不放置
        return False, None

    # 计算有效区域：从 grass 中排除 obstacle，得到纯 grass 区域
    valid_grass = union_grass
    if obstacles_polygons:
        try:
            union_obstacles = unary_union(obstacles_polygons)
            valid_grass = union_grass.difference(union_obstacles)
            if valid_grass.is_empty:
                # obstacle 占满了整个 grass，无法放置
                return False, None
        except Exception:
            # obstacle 计算失败，跳过不放置
            return False, None

    # 用 valid_grass 的边界框作为随机放置范围
    try:
        bounds = valid_grass.bounds
        min_x, min_y, max_x, max_y = bounds
        # 扩大范围到图像边界
        min_x = max(0, min_x)
        min_y = max(0, min_y)
        max_x = min(bg_w, max_x)
        max_y = min(bg_h, max_y)
    except Exception:
        min_x, max_x = 0, bg_w
        min_y, max_y = bg_h // 3, bg_h

    # 检查有效区域是否足够放置物体
    if max_x - obj_w < min_x or max_y - obj_h < min_y:
        return False, None

    for attempt in range(50):
        # 在 valid_grass 范围内 rejection sampling 生成随机位置
        x1 = random.randint(int(min_x), max(int(min_x) + 1, int(max_x - obj_w)))
        y1 = random.randint(int(min_y), max(int(min_y) + 1, int(max_y - obj_h)))
        x2 = x1 + obj_w
        y2 = y1 + obj_h

        # 用四角点检查物体是否完全在 valid_grass 内（处理凹形/空洞）
        if valid_grass is not None and not valid_grass.is_empty:
            corners = [Point(x1, y1), Point(x1, y2), Point(x2, y1), Point(x2, y2)]
            if not all(valid_grass.contains(c) for c in corners):
                continue

        candidate_bbox = (x1, y1, x2, y2)

        # 检查与已放置物体重叠
        overlap = False
        for bbox, _, _ in placed_objects:
            ex1, ey1, ex2, ey2 = bbox
            if not (x2 < ex1 or x1 > ex2 or y2 < ey1 or y1 > ey2):
                overlap = True
                break
        if overlap:
            continue

        # 放置物体
        alpha = object_img[:, :, 3] / 255.0
        roi = bg_img[y1:y2, x1:x2]
        object_rgb = object_img[:, :, :3]

        for c in range(3):
            roi[:, :, c] = (alpha * object_rgb[:, :, c] + (1 - alpha) * roi[:, :, c]).astype(np.uint8)

        bg_img[y1:y2, x1:x2] = roi
        return True, candidate_bbox

    return False, None


def _create_polygon_from_object(object_img: "np.ndarray", bbox: tuple, label: str) -> dict:
    """从物体图像创建多边形标注"""
    x1, y1, _, _ = bbox

    # 确保图片是 4 通道
    if len(object_img.shape) == 2:
        # 灰度图转 BGRA
        object_img = cv2.cvtColor(object_img, cv2.COLOR_GRAY2BGRA)
    elif object_img.shape[2] == 3:
        # 3通道转4通道
        object_img = cv2.cvtColor(object_img, cv2.COLOR_BGR2BGRA)

    alpha_channel = object_img[:, :, 3]
    _, binary_mask = cv2.threshold(alpha_channel, 127, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_L1)
    if not contours:
        return {"label": label, "points": [[float(x1), float(y1)], [float(x1 + object_img.shape[1]), float(y1)], [float(x1 + object_img.shape[1]), float(y1 + object_img.shape[0])], [float(x1), float(y1 + object_img.shape[0])]], "shape_type": "polygon"}

    largest_contour = max(contours, key=cv2.contourArea)
    epsilon = 0.01 * cv2.arcLength(largest_contour, True)
    approx_contour = cv2.approxPolyDP(largest_contour, epsilon, True)

    contour_points = approx_contour.reshape(-1, 2) + np.array([x1, y1])
    points = [[float(p[0]), float(p[1])] for p in contour_points]

    return {"label": label, "points": points, "shape_type": "polygon"}


def _adjust_polygons_with_object(original_shapes: list, object_shape: dict, log: LogFn) -> list:
    """当物体与原有多边形重叠时，裁剪多边形边界"""
    adjusted = []
    try:
        object_poly = Polygon(object_shape["points"])
        if not object_poly.is_valid:
            object_poly = object_poly.buffer(0)
    except Exception:
        return original_shapes

    for shape in original_shapes:
        if shape.get("shape_type") != "polygon":
            adjusted.append(shape)
            continue

        try:
            shape_poly = Polygon(shape["points"])
            if not shape_poly.is_valid:
                shape_poly = shape_poly.buffer(0)
            if not shape_poly.is_valid:
                adjusted.append(shape)
                continue

            if shape_poly.contains(object_poly):
                adjusted.append(shape)
                continue

            if not shape_poly.intersects(object_poly):
                adjusted.append(shape)
                continue

            difference = shape_poly.difference(object_poly)

            if difference.is_empty:
                continue

            if isinstance(difference, Polygon):
                new_points = [[float(x), float(y)] for x, y in difference.exterior.coords[:-1]]
                if len(new_points) >= 3:
                    adjusted.append({"label": shape["label"], "points": new_points, "shape_type": "polygon"})
            elif isinstance(difference, MultiPolygon):
                for poly in difference.geoms:
                    new_points = [[float(x), float(y)] for x, y in poly.exterior.coords[:-1]]
                    if len(new_points) >= 3:
                        adjusted.append({"label": shape["label"], "points": new_points, "shape_type": "polygon"})
        except Exception:
            adjusted.append(shape)

    return adjusted


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
        return _run_bgr2rgb(paths, params, mode, backup_dir, log)
    if task == "rename2":
        return _run_rename_v2(paths, params, mode, backup_dir, log)
    if task == "select_diverse":
        return _run_select_diverse(paths, params, mode, backup_dir, log)
    if task == "json_path":
        return _run_json_path_v2(paths, mode, backup_dir, log)
    if task == "reorder_labels":
        return _run_reorder_labels(paths, mode, backup_dir, log)
    if task == "synthesize":
        return _run_synthesize(paths, params, mode, backup_dir, log)
    raise ValueError(f"不支持的 task: {task}")
