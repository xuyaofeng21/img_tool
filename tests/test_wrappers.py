from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from PIL import Image

import app.wrappers as wrappers


def test_select_diverse_known_nameerror_fallback(monkeypatch, tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for i in range(4):
        Image.new("RGB", (8, 8), (i * 20, i * 20, i * 20)).save(input_dir / f"{i}.png")

    fake_module = types.SimpleNamespace(
        select_diverse_images=lambda *args, **kwargs: (_ for _ in ()).throw(NameError("name 'sf' is not defined"))
    )
    monkeypatch.setattr(wrappers, "_load_script_module", lambda *args, **kwargs: fake_module)

    result = wrappers.execute_task(
        {
            "task": "select_diverse",
            "mode": "safe_copy",
            "paths": {"input_dir": str(input_dir), "output_dir": str(output_dir)},
            "params": {"select_ratio": 0.5, "hamming_thresh": 10},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert result["status"] == "success"
    assert result["success_count"] > 0
    assert len(list(output_dir.glob("*.png"))) == result["success_count"]


def test_json_path_runs_via_subprocess(monkeypatch, tmp_path: Path):
    json_dir = tmp_path / "json"
    image_dir = tmp_path / "image"
    output_dir = tmp_path / "output"
    json_dir.mkdir()
    image_dir.mkdir()
    (json_dir / "a.json").write_text('{"imagePath":"old"}', encoding="utf-8")

    calls: list[dict] = []

    class DummyCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "钉?ok\n"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return DummyCompleted()

    monkeypatch.setattr(wrappers.subprocess, "run", fake_run)

    result = wrappers.execute_task(
        {
            "task": "json_path",
            "mode": "safe_copy",
            "paths": {"json_dir": str(json_dir), "image_dir": str(image_dir), "output_dir": str(output_dir)},
            "params": {},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert result["status"] == "success"
    assert result["output_path"] == str(output_dir.resolve())
    assert (output_dir / "a.json").exists()
    assert calls
    env = calls[0]["kwargs"]["env"]
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


@pytest.mark.parametrize(
    "color_direction, expected_func",
    [
        ("rgb_to_bgr", "rgb_to_bgr"),
        ("bgr_to_rgb", "bgr_to_rgb"),
    ],
)
def test_bgr2rgb_file_mode_chinese_path_does_not_crash(
    monkeypatch,
    tmp_path: Path,
    color_direction: str,
    expected_func: str,
):
    src_dir = tmp_path / "中文源目录"
    out_dir = tmp_path / "中文输出目录"
    src_dir.mkdir()
    source_file = src_dir / "图像一.png"
    Image.new("RGB", (10, 10), (20, 40, 60)).save(source_file)

    calls: list[tuple[str, str, str]] = []

    def _copy_input_dir(tag: str, input_dir: str, output_dir: str) -> None:
        calls.append((tag, input_dir, output_dir))
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        for item in input_path.iterdir():
            if item.is_file():
                (output_path / item.name).write_bytes(item.read_bytes())

    fake_module = types.SimpleNamespace(
        convert_rgb_to_bgr_and_save=lambda input_dir, output_dir: _copy_input_dir("rgb_to_bgr", input_dir, output_dir),
        convert_bgr_to_rgb_and_save=lambda input_dir, output_dir: _copy_input_dir("bgr_to_rgb", input_dir, output_dir),
    )
    monkeypatch.setattr(wrappers, "_load_script_module", lambda *args, **kwargs: fake_module)

    result = wrappers.execute_task(
        {
            "task": "bgr2rgb",
            "mode": "safe_copy",
            "paths": {
                "input_mode": "file",
                "input_file": str(source_file),
                "output_dir": str(out_dir),
            },
            "params": {"color_direction": color_direction},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert result["status"] == "success"
    assert calls, "conversion helper was not called"
    assert calls[0][0] == expected_func
    assert Path(result["output_path"]).resolve() == out_dir.resolve()
    assert (out_dir / source_file.name).exists()


def test_select_diverse_target_count_takes_precedence(monkeypatch, tmp_path: Path):
    src_dir = tmp_path / "select_input"
    out_dir = tmp_path / "select_output"
    src_dir.mkdir()
    for idx in range(5):
        Image.new("RGB", (8, 8), (idx * 30, idx * 30, idx * 30)).save(src_dir / f"{idx}.png")

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
        chosen = list(Path(input_dir).glob("*.png"))[: int(target_count or 1)]
        for src in chosen:
            (out / src.name).write_bytes(src.read_bytes())

    fake_module = types.SimpleNamespace(select_diverse_images=fake_select_diverse_images)
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


def test_rename2_safe_copy_and_in_place_backup_contract(tmp_path: Path):
    source_dir = tmp_path / "rename_source"
    target_dir = tmp_path / "rename_target"
    backup_dir = tmp_path / "rename_backup"
    source_dir.mkdir()
    (source_dir / "a.png").write_bytes(b"png")
    (source_dir / "a.json").write_text("{}", encoding="utf-8")

    safe_copy = wrappers.execute_task(
        {
            "task": "rename2",
            "mode": "safe_copy",
            "paths": {"source_dir": str(source_dir), "target_dir": str(target_dir)},
            "params": {"prefix": "new_"},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert safe_copy["status"] == "success"
    assert Path(safe_copy["output_path"]).resolve() == target_dir.resolve()
    assert (target_dir / "new_a.png").exists()
    assert (target_dir / "new_a.json").exists()

    in_place = wrappers.execute_task(
        {
            "task": "rename2",
            "mode": "in_place",
            "paths": {"source_dir": str(source_dir)},
            "params": {"prefix": "in_"},
            "backup_dir": str(backup_dir),
        },
        lambda *_: None,
    )

    assert in_place["status"] == "success"
    assert Path(in_place["output_path"]).resolve() == source_dir.resolve()
    assert in_place["backup_path"]
    assert Path(in_place["backup_path"]).exists()


def test_json_path_safe_copy_and_in_place_backup_contract(monkeypatch, tmp_path: Path):
    json_dir = tmp_path / "json_dir"
    image_dir = tmp_path / "image_dir"
    out_dir = tmp_path / "json_out"
    backup_dir = tmp_path / "json_backup"
    json_dir.mkdir()
    image_dir.mkdir()
    (json_dir / "a.json").write_text('{"imagePath":"old"}', encoding="utf-8")
    (image_dir / "a.png").write_bytes(b"png")

    calls: list[dict[str, object]] = []

    class DummyCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "钉?ok\n"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return DummyCompleted()

    monkeypatch.setattr(wrappers.subprocess, "run", fake_run)

    safe_copy = wrappers.execute_task(
        {
            "task": "json_path",
            "mode": "safe_copy",
            "paths": {"json_dir": str(json_dir), "image_dir": str(image_dir), "output_dir": str(out_dir)},
            "params": {},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert safe_copy["status"] == "success"
    assert Path(safe_copy["output_path"]).resolve() == out_dir.resolve()
    assert calls
    assert (out_dir / "a.json").exists()

    calls.clear()
    in_place = wrappers.execute_task(
        {
            "task": "json_path",
            "mode": "in_place",
            "paths": {"json_dir": str(json_dir), "image_dir": str(image_dir)},
            "params": {},
            "backup_dir": str(backup_dir),
        },
        lambda *_: None,
    )

    assert in_place["status"] == "success"
    assert Path(in_place["output_path"]).resolve() == json_dir.resolve()
    assert in_place["backup_path"]
    assert Path(in_place["backup_path"]).exists()


def test_rename2_file_mode_supports_multiple_files(monkeypatch, tmp_path: Path):
    src_dir = tmp_path / "rename_file_mode"
    out_dir = tmp_path / "rename_file_mode_out"
    src_dir.mkdir()
    (src_dir / "a.png").write_bytes(b"a")
    (src_dir / "b.png").write_bytes(b"b")

    def fake_process(input_dir: str, output_dir: str, prefix: str):
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        for file_path in Path(input_dir).iterdir():
            if file_path.is_file():
                (output / f"{prefix}{file_path.name}").write_bytes(file_path.read_bytes())

    fake_module = types.SimpleNamespace(process_files_and_rename=fake_process)
    monkeypatch.setattr(wrappers, "_load_script_module", lambda *args, **kwargs: fake_module)

    result = wrappers.execute_task(
        {
            "task": "rename2",
            "mode": "safe_copy",
            "paths": {
                "input_mode": "file",
                "input_path": f"{src_dir / 'a.png'};{src_dir / 'b.png'}",
                "target_dir": str(out_dir),
            },
            "params": {"prefix": "new_"},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert result["status"] == "success"
    assert (out_dir / "new_a.png").exists()
    assert (out_dir / "new_b.png").exists()


def test_json_path_file_mode_supports_multiple_files(monkeypatch, tmp_path: Path):
    json_dir = tmp_path / "json_file_mode"
    image_dir = tmp_path / "image_file_mode"
    output_dir = tmp_path / "json_file_mode_out"
    json_dir.mkdir()
    image_dir.mkdir()
    (json_dir / "a.json").write_text('{"imagePath":"old_a"}', encoding="utf-8")
    (json_dir / "b.json").write_text('{"imagePath":"old_b"}', encoding="utf-8")

    class DummyCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "ok\n"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        target_json_dir = Path(cmd[2])
        for file_path in target_json_dir.glob("*.json"):
            file_path.write_text('{"imagePath":"new"}', encoding="utf-8")
        return DummyCompleted()

    monkeypatch.setattr(wrappers.subprocess, "run", fake_run)

    result = wrappers.execute_task(
        {
            "task": "json_path",
            "mode": "safe_copy",
            "paths": {
                "input_mode": "file",
                "input_path": f"{json_dir / 'a.json'};{json_dir / 'b.json'}",
                "image_dir": str(image_dir),
                "output_dir": str(output_dir),
            },
            "params": {},
            "backup_dir": "",
        },
        lambda *_: None,
    )

    assert result["status"] == "success"
    assert (output_dir / "a.json").exists()
    assert (output_dir / "b.json").exists()
    assert "new" in (output_dir / "a.json").read_text(encoding="utf-8")
    assert "new" in (output_dir / "b.json").read_text(encoding="utf-8")


def test_select_diverse_file_mode_rejects_non_png(monkeypatch, tmp_path: Path):
    src_dir = tmp_path / "select_non_png"
    out_dir = tmp_path / "select_non_png_out"
    src_dir.mkdir()
    Image.new("RGB", (8, 8), (100, 100, 100)).save(src_dir / "a.jpg")

    fake_module = types.SimpleNamespace(select_diverse_images=lambda *args, **kwargs: None)
    monkeypatch.setattr(wrappers, "_load_script_module", lambda *args, **kwargs: fake_module)

    with pytest.raises(ValueError):
        wrappers.execute_task(
            {
                "task": "select_diverse",
                "mode": "safe_copy",
                "paths": {
                    "input_mode": "file",
                    "input_file": str(src_dir / "a.jpg"),
                    "output_dir": str(out_dir),
                },
                "params": {"select_ratio": 0.5, "hamming_thresh": 10},
                "backup_dir": "",
            },
            lambda *_: None,
        )


def test_inspect_synthesize_source_info_all_without_json(tmp_path: Path):
    src = tmp_path / "src_no_json"
    src.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(src / "a.png")
    Image.new("RGB", (8, 8), (4, 5, 6)).save(src / "b.jpg")

    result = wrappers.inspect_synthesize_source_info({"source_folder": str(src)})

    assert result["ok"] is True
    assert result["mode"] == "all_without_json"
    assert result["with_json_count"] == 0
    assert result["without_json_count"] == 2


def test_inspect_synthesize_source_info_detects_mixed(tmp_path: Path):
    src = tmp_path / "src_mixed"
    src.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(src / "a.png")
    Image.new("RGB", (8, 8), (4, 5, 6)).save(src / "b.png")
    (src / "a.json").write_text(
        json.dumps({"shapes": [{"label": "animal", "shape_type": "polygon", "points": [[1, 1], [6, 1], [6, 6]]}]}),
        encoding="utf-8",
    )

    result = wrappers.inspect_synthesize_source_info({"source_folder": str(src)})

    assert result["ok"] is False
    assert result["mode"] == "mixed"
    assert "混合" in result["error"]


def test_inspect_synthesize_source_info_detects_unique_and_mismatch(tmp_path: Path):
    src_ok = tmp_path / "src_ok"
    src_ok.mkdir()
    for name in ("a", "b"):
        Image.new("RGB", (8, 8), (1, 2, 3)).save(src_ok / f"{name}.png")
        (src_ok / f"{name}.json").write_text(
            json.dumps({"shapes": [{"label": "hedgehog", "shape_type": "polygon", "points": [[1, 1], [6, 1], [6, 6]]}]}),
            encoding="utf-8",
        )

    ok_result = wrappers.inspect_synthesize_source_info({"source_folder": str(src_ok)})
    assert ok_result["ok"] is True
    assert ok_result["mode"] == "all_with_json"
    assert ok_result["detected_label"] == "hedgehog"

    src_bad = tmp_path / "src_bad"
    src_bad.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(src_bad / "a.png")
    Image.new("RGB", (8, 8), (1, 2, 3)).save(src_bad / "b.png")
    (src_bad / "a.json").write_text(
        json.dumps({"shapes": [{"label": "animal_a", "shape_type": "polygon", "points": [[1, 1], [6, 1], [6, 6]]}]}),
        encoding="utf-8",
    )
    (src_bad / "b.json").write_text(
        json.dumps({"shapes": [{"label": "animal_b", "shape_type": "polygon", "points": [[1, 1], [6, 1], [6, 6]]}]}),
        encoding="utf-8",
    )

    bad_result = wrappers.inspect_synthesize_source_info({"source_folder": str(src_bad)})
    assert bad_result["ok"] is False
    assert bad_result["mode"] == "label_mismatch"
    assert "label 不一致" in bad_result["error"]


def test_run_synthesize_blocks_mixed_or_mismatch_source(tmp_path: Path):
    bg = tmp_path / "bg"
    out = tmp_path / "out"
    bg.mkdir()
    out.mkdir()
    Image.new("RGB", (12, 12), (10, 20, 30)).save(bg / "bg1.png")
    (bg / "bg1.json").write_text(
        json.dumps({"shapes": [], "imageWidth": 12, "imageHeight": 12}),
        encoding="utf-8",
    )

    src_mixed = tmp_path / "src_mixed"
    src_mixed.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(src_mixed / "a.png")
    Image.new("RGB", (8, 8), (4, 5, 6)).save(src_mixed / "b.png")
    (src_mixed / "a.json").write_text(
        json.dumps({"shapes": [{"label": "animal", "shape_type": "polygon", "points": [[1, 1], [6, 1], [6, 6]]}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="混合"):
        wrappers.execute_task(
            {
                "task": "synthesize",
                "mode": "safe_copy",
                "paths": {"source_folder": str(src_mixed), "bg_json_folder": str(bg), "output_folder": str(out)},
                "params": {"label": "x", "max_objects": 1},
                "backup_dir": "",
            },
            lambda *_: None,
        )

    src_mismatch = tmp_path / "src_mismatch"
    src_mismatch.mkdir()
    for idx, lbl in enumerate(("a", "b"), start=1):
        Image.new("RGB", (8, 8), (idx, idx, idx)).save(src_mismatch / f"{idx}.png")
        (src_mismatch / f"{idx}.json").write_text(
            json.dumps({"shapes": [{"label": lbl, "shape_type": "polygon", "points": [[1, 1], [6, 1], [6, 6]]}]}),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="label 不一致"):
        wrappers.execute_task(
            {
                "task": "synthesize",
                "mode": "safe_copy",
                "paths": {"source_folder": str(src_mismatch), "bg_json_folder": str(bg), "output_folder": str(out)},
                "params": {"label": "x", "max_objects": 1},
                "backup_dir": "",
            },
            lambda *_: None,
        )
