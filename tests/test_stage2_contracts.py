from __future__ import annotations

import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import app.wrappers as wrappers
from app.bridge import ApiBridge
from app.tasks import TaskManager


def _make_png(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 12), color).save(path)


def _norm_counts(counts: dict[str, int]) -> dict[str, int]:
    return {str(key).lower().lstrip("."): int(value) for key, value in counts.items()}


def test_bridge_exposes_stage2_apis():
    bridge = ApiBridge(TaskManager())

    assert hasattr(bridge, "select_file"), "missing select_file() bridge API"
    assert hasattr(bridge, "preview_path"), "missing preview_path() bridge API"
    assert callable(getattr(bridge, "select_file"))
    assert callable(getattr(bridge, "preview_path"))


@pytest.mark.parametrize(
    "payload, expected_ok, expected_total, expected_counts",
    [
        (
            {"path": "{root}", "input_mode": "folder", "recursive": False, "sample_limit": 20},
            True,
            4,
            {"png": 2, "json": 1, "txt": 1},
        ),
        (
            {"path": "{file}", "input_mode": "file", "recursive": False, "sample_limit": 20},
            True,
            1,
            {"png": 1},
        ),
        (
            {"path": "", "input_mode": "folder", "recursive": False, "sample_limit": 20},
            False,
            None,
            {},
        ),
        (
            {"path": "{missing}", "input_mode": "folder", "recursive": False, "sample_limit": 20},
            False,
            None,
            {},
        ),
    ],
)
def test_preview_path_contract(tmp_path: Path, payload, expected_ok, expected_total, expected_counts):
    bridge = ApiBridge(TaskManager())

    root = tmp_path / "preview_root"
    root.mkdir()
    image_file = root / "single.png"
    _make_png(image_file)
    _make_png(root / "a.png", (0, 255, 0))
    (root / "b.json").write_text("{}", encoding="utf-8")
    (root / "c.txt").write_text("hello", encoding="utf-8")

    if "{root}" in payload["path"]:
        payload = dict(payload, path=str(root))
    elif "{file}" in payload["path"]:
        payload = dict(payload, path=str(image_file))
    elif "{missing}" in payload["path"]:
        payload = dict(payload, path=str(root / "missing"))

    result = bridge.preview_path(payload)
    assert result["ok"] is expected_ok

    if not expected_ok:
        assert result["error"]
        return

    assert result["total_files"] == expected_total
    assert _norm_counts(result["counts_by_ext"]) == expected_counts
    assert "warnings" in result
    assert "counts" in result
    assert "samples" in result
    assert isinstance(result["sample_files"], list)
    assert len(result["sample_files"]) <= 20
    assert all(isinstance(item, str) for item in result["sample_files"])


def test_preview_path_nested_payload_and_file_aliases(tmp_path: Path):
    bridge = ApiBridge(TaskManager())
    root = tmp_path / "预览目录"
    root.mkdir()
    png_file = root / "样例.png"
    _make_png(png_file, (12, 34, 56))
    (root / "note.json").write_text("{}", encoding="utf-8")

    nested_payload = {
        "paths": {
            "input_mode": "file",
            "input_file": str(png_file),
        },
        "sample_limit": 5,
    }
    nested_result = bridge.preview_path(nested_payload)
    assert nested_result["ok"] is True
    assert nested_result["total_files"] == 1
    assert _norm_counts(nested_result["counts_by_ext"]) == {"png": 1}
    assert isinstance(nested_result["warnings"], list)

    json_alias_payload = {
        "paths": {
            "input_mode": "file",
            "json_file": str(root / "note.json"),
        }
    }
    json_result = bridge.preview_path(json_alias_payload)
    assert json_result["ok"] is True
    assert json_result["total_files"] == 1
    assert _norm_counts(json_result["counts_by_ext"]) == {"json": 1}


def test_bgr2rgb_file_mode_and_color_direction_contract(monkeypatch, tmp_path: Path):
    src_dir = tmp_path / "src"
    out_dir = tmp_path / "out"
    file_a = src_dir / "a.png"
    file_b = src_dir / "b.png"
    _make_png(file_a, (255, 0, 0))
    _make_png(file_b, (0, 255, 0))

    calls: list[tuple[str, str, str]] = []

    def fake_rgb_to_bgr(input_dir: str, output_dir: str):
        calls.append(("rgb_to_bgr", input_dir, output_dir))
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for src in Path(input_dir).glob("*.png"):
            shutil.copy2(src, out / src.name)

    def fake_bgr_to_rgb(input_dir: str, output_dir: str):
        calls.append(("bgr_to_rgb", input_dir, output_dir))
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for src in Path(input_dir).glob("*.png"):
            shutil.copy2(src, out / src.name)

    fake_module = SimpleNamespace(
        convert_rgb_to_bgr_and_save=fake_rgb_to_bgr,
        convert_bgr_to_rgb_and_save=fake_bgr_to_rgb,
    )
    monkeypatch.setattr(wrappers, "_load_script_module", lambda *args, **kwargs: fake_module)

    result = wrappers.execute_task(
        {
            "task": "bgr2rgb",
            "mode": "safe_copy",
            "paths": {
                "input_mode": "file",
                "input_dir": str(src_dir),
                "input_file": str(file_a),
                "output_dir": str(out_dir),
            },
            "params": {"color_direction": "bgr_to_rgb"},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert result["status"] == "success"
    assert calls, "conversion function was not called"
    assert calls[0][0] == "bgr_to_rgb"
    assert len(list(out_dir.glob("*.png"))) == 1


def test_select_diverse_target_count_takes_precedence(monkeypatch, tmp_path: Path):
    src_dir = tmp_path / "src"
    out_dir = tmp_path / "out"
    src_dir.mkdir()
    for idx in range(5):
        _make_png(src_dir / f"{idx}.png", (idx * 30, idx * 30, idx * 30))

    calls: list[dict[str, object]] = []

    def fake_select_diverse_images(input_dir, output_dir, select_ratio=0.1, hamming_thresh=10, target_count=None):
        calls.append(
            {
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "select_ratio": select_ratio,
                "hamming_thresh": hamming_thresh,
                "target_count": target_count,
            }
        )
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        chosen = list(Path(input_dir).glob("*.png"))[: int(target_count or max(1, int(len(list(Path(input_dir).glob('*.png'))) * select_ratio)))]
        for src in chosen:
            shutil.copy2(src, out / src.name)

    fake_module = SimpleNamespace(select_diverse_images=fake_select_diverse_images)
    monkeypatch.setattr(wrappers, "_load_script_module", lambda *args, **kwargs: fake_module)

    result = wrappers.execute_task(
        {
            "task": "select_diverse",
            "mode": "safe_copy",
            "paths": {"input_dir": str(src_dir), "output_dir": str(out_dir)},
            "params": {"select_ratio": 0.9, "hamming_thresh": 10, "target_count": 2},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert result["status"] == "success"
    assert calls, "select_diverse_images was not called"
    assert calls[0]["target_count"] == 2
    assert calls[0]["select_ratio"] == 0.9
    assert len(list(out_dir.glob("*.png"))) == 2


def test_ui_contract_contains_stage2_controls():
    ui_path = Path("ui/new.html") if Path("ui/new.html").exists() else Path("ui/index.html")
    html = ui_path.read_text(encoding="utf-8")

    assert "input_mode" in html or "输入类型" in html or "文件夹 / 单文件" in html
    assert "preview" in html.lower() or "预览" in html
    assert "color_direction" in html or "RGB -> BGR" in html or "BGR -> RGB" in html
    assert "target_count" in html or "筛选张数" in html
    assert "workspace" in html.lower() or "layout" in html.lower() or 'class="main"' in html.lower()
    assert re.search(r"overflow[^;]{0,40}(auto|scroll)", html, flags=re.IGNORECASE | re.DOTALL)


def test_bridge_regression_interfaces_still_present():
    bridge = ApiBridge(TaskManager())
    assert callable(bridge.run_task)
    assert callable(bridge.get_task_status)
    assert callable(bridge.get_task_logs)
    assert callable(bridge.select_folder)
    assert callable(bridge.open_path)

