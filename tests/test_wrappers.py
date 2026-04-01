from __future__ import annotations

import types
from pathlib import Path

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
            self.stdout = "✅ ok\n"
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

