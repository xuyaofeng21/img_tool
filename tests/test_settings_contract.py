from __future__ import annotations

import json
from pathlib import Path

from app.bridge import ApiBridge
from app.settings_store import DEFAULT_SETTINGS, SettingsStore
from app.tasks import TaskManager


def _make_bridge(tmp_path: Path) -> ApiBridge:
    bridge = ApiBridge(TaskManager())
    bridge.settings_store = SettingsStore(tmp_path / "settings.json")
    return bridge


def test_settings_api_contract_via_bridge(tmp_path: Path):
    bridge = _make_bridge(tmp_path)

    current = bridge.get_settings()
    assert current["ok"] is True
    assert current["path"].endswith("settings.json")
    assert current["settings"]["version"] == DEFAULT_SETTINGS["version"]
    assert current["settings"]["preview"]["sample_limit"] == DEFAULT_SETTINGS["preview"]["sample_limit"]
    assert current["settings"]["workflow"]["auto_open_output_after_success"] is False
    assert current["settings"]["preview"]["expand_details_by_default"] is False
    assert current["settings"]["paths"]["default_output_dir"] == ""
    assert current["settings"]["history"]["recent_paths"] == []

    valid = bridge.validate_settings({"settings": current["settings"]})
    assert valid["ok"] is True
    assert valid["valid"] is True
    assert valid["settings"]["workflow"]["startup_task"] == DEFAULT_SETTINGS["workflow"]["startup_task"]

    invalid = bridge.validate_settings({"settings": {"preview": {"sample_limit": 0}}})
    assert invalid["ok"] is False
    assert invalid["valid"] is False
    assert invalid["errors"]

    updated = bridge.update_settings(
        {
            "settings": {
                "ui": {"density": "compact"},
                "preview": {"sample_limit": 7},
                "workflow": {"startup_task": "rename2", "auto_open_output_after_success": True},
                "paths": {"default_output_dir": "D:/out"},
                "history": {"recent_paths": ["C:/a", "C:/b"], "max_recent_paths": 5},
            }
        }
    )
    assert updated["ok"] is True
    assert updated["settings"]["ui"]["density"] == "compact"
    assert updated["settings"]["preview"]["sample_limit"] == 7
    assert updated["settings"]["workflow"]["startup_task"] == "rename2"
    assert updated["settings"]["workflow"]["auto_open_output_after_success"] is True
    assert updated["settings"]["paths"]["default_output_dir"] == "D:/out"
    assert updated["settings"]["history"]["recent_paths"] == ["C:/a", "C:/b"]
    assert bridge.get_settings()["settings"]["preview"]["sample_limit"] == 7

    export_path = tmp_path / "exported-settings.json"
    exported = bridge.export_settings({"path": str(export_path)})
    assert exported["ok"] is True
    assert exported["path"].endswith("settings.json")
    assert export_path.exists()
    exported_json = json.loads(exported["json"])
    assert exported_json["preview"]["sample_limit"] == 7
    assert exported_json["workflow"]["startup_task"] == "rename2"

    imported = bridge.import_settings({"json": json.dumps({"preview": {"sample_limit": 12}, "history": {"max_recent_paths": 5}})})
    assert imported["ok"] is True
    assert imported["settings"]["preview"]["sample_limit"] == 12
    assert imported["settings"]["history"]["max_recent_paths"] == 5

    reset_subset = bridge.reset_settings({"keys": ["preview.sample_limit", "ui.density"]})
    assert reset_subset["ok"] is True
    assert reset_subset["settings"]["preview"]["sample_limit"] == DEFAULT_SETTINGS["preview"]["sample_limit"]
    assert reset_subset["settings"]["ui"]["density"] == DEFAULT_SETTINGS["ui"]["density"]

    reset_all = bridge.reset_settings()
    assert reset_all["ok"] is True
    assert reset_all["settings"]["preview"]["sample_limit"] == DEFAULT_SETTINGS["preview"]["sample_limit"]
    assert reset_all["settings"]["workflow"]["startup_task"] == DEFAULT_SETTINGS["workflow"]["startup_task"]
