from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

APP_NAME = "ImgToolbox"
SETTINGS_FILENAME = "settings.json"


DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "ui": {
        "theme": "system",
        "density": "comfortable",
        "accent": "blue",
        "glass_strength": 72,
    },
    "workflow": {
        "default_mode": "safe_copy",
        "default_input_mode": "folder",
        "startup_task": "bgr2rgb",
        "require_inplace_confirm": True,
        "auto_open_output_after_success": False,
    },
    "preview": {
        "auto_refresh": True,
        "recursive": False,
        "sample_limit": 20,
        "debounce_ms": 300,
        "expand_details_by_default": True,
    },
    "logging": {
        "level": "info",
        "max_lines": 3000,
        "retention_days": 30,
        "auto_cleanup": True,
    },
    "history": {
        "remember_paths": True,
        "max_recent_paths": 10,
        "recent_paths": [],
    },
    "paths": {
        "default_backup_dir": "",
        "default_output_dir": "",
    },
    "synthesize": {
        "max_placement_per_material": 10,
    },
}


def _config_base_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    return Path.home() / ".config" / APP_NAME


def _settings_file_path() -> Path:
    base_dir = _config_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / SETTINGS_FILENAME


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _coerce_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off"}:
            return False
    raise ValueError(f"{field} 必须是布尔值")


def _coerce_int(value: Any, field: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是整数") from exc
    if minimum is not None and result < minimum:
        raise ValueError(f"{field} 不能小于 {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{field} 不能大于 {maximum}")
    return result


def _coerce_text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    raise ValueError(f"{field} 必须是字符串")


def _normalize_settings(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("settings 必须是对象")

    merged = _deep_merge(DEFAULT_SETTINGS, data)

    ui = merged.get("ui", {})
    workflow = merged.get("workflow", {})
    preview = merged.get("preview", {})
    logging_cfg = merged.get("logging", {})
    history = merged.get("history", {})
    paths = merged.get("paths", {})

    if not all(isinstance(x, dict) for x in (ui, workflow, preview, logging_cfg, history, paths)):
        raise ValueError("settings 子字段必须是对象")

    theme = _coerce_text(ui.get("theme", "system"), "ui.theme") or "system"
    if theme not in {"system", "light", "dark"}:
        raise ValueError("ui.theme 只能是 system/light/dark")

    density = _coerce_text(ui.get("density", "comfortable"), "ui.density") or "comfortable"
    if density not in {"comfortable", "compact"}:
        raise ValueError("ui.density 只能是 comfortable/compact")

    accent = _coerce_text(ui.get("accent", "blue"), "ui.accent") or "blue"
    if accent not in {"blue", "teal", "green", "orange"}:
        raise ValueError("ui.accent 只能是 blue/teal/green/orange")

    glass_strength = _coerce_int(ui.get("glass_strength", 72), "ui.glass_strength", minimum=0, maximum=100)

    default_mode = _coerce_text(workflow.get("default_mode", "safe_copy"), "workflow.default_mode") or "safe_copy"
    if default_mode not in {"safe_copy", "in_place"}:
        raise ValueError("workflow.default_mode 只能是 safe_copy/in_place")

    default_input_mode = _coerce_text(workflow.get("default_input_mode", "folder"), "workflow.default_input_mode") or "folder"
    if default_input_mode not in {"folder", "file"}:
        raise ValueError("workflow.default_input_mode 只能是 folder/file")

    startup_task = _coerce_text(workflow.get("startup_task", "bgr2rgb"), "workflow.startup_task") or "bgr2rgb"
    if startup_task not in {"bgr2rgb", "rename2", "select_diverse", "json_path"}:
        raise ValueError("workflow.startup_task 只能是 bgr2rgb/rename2/select_diverse/json_path")

    require_inplace_confirm = _coerce_bool(workflow.get("require_inplace_confirm", True), "workflow.require_inplace_confirm")
    auto_open_output_after_success = _coerce_bool(
        workflow.get("auto_open_output_after_success", False), "workflow.auto_open_output_after_success"
    )

    auto_refresh = _coerce_bool(preview.get("auto_refresh", True), "preview.auto_refresh")
    recursive = _coerce_bool(preview.get("recursive", False), "preview.recursive")
    sample_limit = _coerce_int(preview.get("sample_limit", 20), "preview.sample_limit", minimum=1, maximum=300)
    debounce_ms = _coerce_int(preview.get("debounce_ms", 300), "preview.debounce_ms", minimum=100, maximum=3000)
    expand_details_by_default = _coerce_bool(
        preview.get("expand_details_by_default", True), "preview.expand_details_by_default"
    )

    log_level = _coerce_text(logging_cfg.get("level", "info"), "logging.level") or "info"
    if log_level not in {"info", "warn", "error"}:
        raise ValueError("logging.level 只能是 info/warn/error")

    max_lines = _coerce_int(logging_cfg.get("max_lines", 3000), "logging.max_lines", minimum=100, maximum=50000)
    retention_days = _coerce_int(logging_cfg.get("retention_days", 30), "logging.retention_days", minimum=1, maximum=3650)
    auto_cleanup = _coerce_bool(logging_cfg.get("auto_cleanup", True), "logging.auto_cleanup")

    remember_paths = _coerce_bool(history.get("remember_paths", True), "history.remember_paths")
    max_recent_paths = _coerce_int(history.get("max_recent_paths", 10), "history.max_recent_paths", minimum=1, maximum=50)
    raw_recent_paths = history.get("recent_paths", [])
    if raw_recent_paths in (None, ""):
        raw_recent_paths = []
    if isinstance(raw_recent_paths, str):
        raw_recent_paths = [raw_recent_paths]
    if not isinstance(raw_recent_paths, list):
        raise ValueError("history.recent_paths 必须是字符串数组")
    recent_paths: list[str] = []
    seen_paths: set[str] = set()
    for idx, item in enumerate(raw_recent_paths):
        val = _coerce_text(item, f"history.recent_paths[{idx}]")
        if not val:
            continue
        if val in seen_paths:
            continue
        seen_paths.add(val)
        recent_paths.append(val)
    recent_paths = recent_paths[:max_recent_paths]

    default_backup_dir = _coerce_text(paths.get("default_backup_dir", ""), "paths.default_backup_dir")
    default_output_dir = _coerce_text(paths.get("default_output_dir", ""), "paths.default_output_dir")

    synthesize_cfg = merged.get("synthesize", {})
    if not isinstance(synthesize_cfg, dict):
        synthesize_cfg = {}
    max_placement_per_material = _coerce_int(
        synthesize_cfg.get("max_placement_per_material", 10),
        "synthesize.max_placement_per_material",
        minimum=1, maximum=100,
    )

    normalized = {
        "version": 1,
        "ui": {
            "theme": theme,
            "density": density,
            "accent": accent,
            "glass_strength": glass_strength,
        },
        "workflow": {
            "default_mode": default_mode,
            "default_input_mode": default_input_mode,
            "startup_task": startup_task,
            "require_inplace_confirm": require_inplace_confirm,
            "auto_open_output_after_success": auto_open_output_after_success,
        },
        "preview": {
            "auto_refresh": auto_refresh,
            "recursive": recursive,
            "sample_limit": sample_limit,
            "debounce_ms": debounce_ms,
            "expand_details_by_default": expand_details_by_default,
        },
        "logging": {
            "level": log_level,
            "max_lines": max_lines,
            "retention_days": retention_days,
            "auto_cleanup": auto_cleanup,
        },
        "history": {
            "remember_paths": remember_paths,
            "max_recent_paths": max_recent_paths,
            "recent_paths": recent_paths,
        },
        "paths": {
            "default_backup_dir": default_backup_dir,
            "default_output_dir": default_output_dir,
        },
        "synthesize": {
            "max_placement_per_material": max_placement_per_material,
        },
    }

    # Preserve unknown top-level keys for forward compatibility.
    for key, value in merged.items():
        if key not in normalized:
            normalized[key] = value

    return normalized


def _apply_key_resets(data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    if not keys:
        return copy.deepcopy(DEFAULT_SETTINGS)

    result = copy.deepcopy(data)
    defaults = copy.deepcopy(DEFAULT_SETTINGS)

    for raw_key in keys:
        key = str(raw_key).strip()
        if not key:
            continue
        if key in defaults:
            result[key] = copy.deepcopy(defaults[key])
            continue
        # dotted key reset: e.g. preview.sample_limit
        parts = key.split(".")
        src: Any = defaults
        dst: Any = result
        valid_path = True
        for part in parts[:-1]:
            if not isinstance(src, dict) or part not in src:
                valid_path = False
                break
            src = src[part]
            if not isinstance(dst, dict):
                valid_path = False
                break
            dst = dst.setdefault(part, {})
        if not valid_path or not isinstance(src, dict) or parts[-1] not in src or not isinstance(dst, dict):
            continue
        dst[parts[-1]] = copy.deepcopy(src[parts[-1]])

    return result


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _settings_file_path()
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def _read_raw(self) -> dict[str, Any]:
        if not self._path.exists():
            return copy.deepcopy(DEFAULT_SETTINGS)
        text = self._path.read_text(encoding="utf-8")
        if not text.strip():
            return copy.deepcopy(DEFAULT_SETTINGS)
        return _normalize_settings(json.loads(text))

    def _write_raw(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = _normalize_settings(data)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        return normalized

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return self._read_raw()

    def validate_settings(self, data: Any) -> dict[str, Any]:
        payload = data.get("settings") if isinstance(data, dict) and isinstance(data.get("settings"), dict) else data
        normalized = _normalize_settings(payload)
        return {"valid": True, "errors": [], "settings": normalized}

    def update_settings(self, updates: Any) -> dict[str, Any]:
        with self._lock:
            current = self._read_raw()
            payload = updates.get("settings") if isinstance(updates, dict) and isinstance(updates.get("settings"), dict) else updates
            if not isinstance(payload, dict):
                raise ValueError("updates 必须是对象")
            merged = _deep_merge(current, payload)
            return self._write_raw(merged)

    def reset_settings(self, keys: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            if not keys:
                return self._write_raw(copy.deepcopy(DEFAULT_SETTINGS))
            current = self._read_raw()
            updated = _apply_key_resets(current, keys)
            return self._write_raw(updated)

    def export_settings(self, output_path: str | None = None) -> str:
        with self._lock:
            payload = json.dumps(self._read_raw(), ensure_ascii=False, indent=2)
            if output_path:
                target = Path(output_path).expanduser().resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(payload, encoding="utf-8")
            return payload

    def import_settings(self, payload: Any) -> dict[str, Any]:
        with self._lock:
            data: Any
            if isinstance(payload, dict):
                if isinstance(payload.get("settings"), dict):
                    data = payload["settings"]
                elif isinstance(payload.get("json"), str):
                    data = json.loads(payload["json"])
                elif payload.get("path"):
                    data = json.loads(Path(str(payload["path"])).expanduser().read_text(encoding="utf-8"))
                else:
                    data = payload
            elif isinstance(payload, str):
                text = payload.strip()
                if not text:
                    raise ValueError("导入内容不能为空")
                candidate = Path(text).expanduser()
                if candidate.exists() and candidate.is_file():
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                else:
                    data = json.loads(text)
            else:
                raise ValueError("导入内容必须是字符串或对象")
            return self._write_raw(data)


DEFAULT_SETTINGS_STORE = SettingsStore()
