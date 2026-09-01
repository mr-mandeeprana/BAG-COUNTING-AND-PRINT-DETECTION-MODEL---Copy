"""
==========================================================
FillPac AI
Tests for src/config_manager.py
==========================================================

Pure unit tests against ConfigManager -- no FastAPI app, no
SQL Server, no auth. Each test gets its own tmp_path with a
fresh config.yaml, so nothing here touches the real project
config.yaml.

Run:

    pytest tests/test_config_manager.py -v
==========================================================
"""

import sys
from pathlib import Path

import pytest
import yaml

# Make "src" importable when running pytest from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_manager import ConfigManager, ConfigValidationError  # noqa: E402


# ==========================================================
# FIXTURES
# ==========================================================

MINIMAL_VALID_CONFIG = {
    "project": {"name": "FillPac AI Test", "version": "1.1.0"},
    "model": {"path": "models/fillpac_yolo26n_best.pt", "confidence": 0.20},
    "counting": {"method": "center", "direction": "left"},
    "jam_detection": {"enabled": False},
    "bag_spacing": {"enabled": False},
    "condition_c": {"enabled": False},
    "cameras": [
        {
            "id": 1,
            "name": "Camera 1",
            "enabled": True,
            "mode": "video",
            "source": "data/videos/camera1_test.mp4",
            "roi": {"x1": 0, "y1": 0, "x2": 100, "y2": 100},
            "jam_detection": {"enabled": False},
            "bag_spacing": {"enabled": False},
            "condition_c": {"enabled": False},
        }
    ],
}


@pytest.fixture
def config_path(tmp_path):

    path = tmp_path / "config.yaml"

    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(MINIMAL_VALID_CONFIG, fh)

    return path


@pytest.fixture
def manager(config_path, tmp_path):

    return ConfigManager(
        config_path,
        backup_dir=tmp_path / "config_backups",
    )


# ==========================================================
# LOAD
# ==========================================================

def test_load_returns_dict(manager):

    data = manager.load()

    assert isinstance(data, dict)
    assert data["cameras"][0]["name"] == "Camera 1"


def test_load_missing_file_raises(tmp_path):

    missing = ConfigManager(tmp_path / "does_not_exist.yaml")

    with pytest.raises(FileNotFoundError):
        missing.load()


# ==========================================================
# VALIDATE
# ==========================================================

def test_validate_accepts_valid_config(manager):

    data = manager.load()
    manager.validate(data)  # should not raise


def test_validate_rejects_non_dict_root(manager):

    with pytest.raises(ConfigValidationError):
        manager.validate(["not", "a", "dict"])


def test_validate_rejects_duplicate_camera_ids(manager):

    data = manager.load()
    data["cameras"].append(dict(data["cameras"][0]))  # same id=1, same name

    with pytest.raises(ConfigValidationError):
        manager.validate(data)


def test_validate_rejects_camera_missing_name(manager):

    data = manager.load()
    del data["cameras"][0]["name"]

    with pytest.raises(ConfigValidationError):
        manager.validate(data)


def test_validate_rejects_invalid_jam_roi(manager):
    """
    Condition A ROI must have nonzero width/height once
    jam_detection.enabled is true (Config._validate_jam_config
    rejects x1 == x2 or y1 == y2, exercised here via
    ConfigManager.validate()).
    """

    data = manager.load()

    data["cameras"][0]["jam_detection"] = {
        "enabled": True,
        "roi": {"x1": 100, "y1": 90, "x2": 100, "y2": 680},  # zero width: x1 == x2
        "history_seconds": 1.0,
        "min_history_seconds": 0.5,
        "stationary_speed_threshold": 4.0,
        "slow_speed_threshold": 9.0,
        "warning_time_seconds": 3.0,
        "jam_time_seconds": 5.0,
        "recovery_time_seconds": 1.0,
        "min_track_age": 4,
        "track_ttl_seconds": 2.0,
    }

    with pytest.raises(ConfigValidationError):
        manager.validate(data)


# ==========================================================
# SAVE / ATOMIC WRITE / BACKUP
# ==========================================================

def test_save_writes_new_values(manager, config_path):

    data = manager.load()
    data["counting"]["direction"] = "right"

    manager.save(data)

    reloaded = manager.load()
    assert reloaded["counting"]["direction"] == "right"


def test_save_creates_backup(manager):

    assert manager.list_backups() == []

    data = manager.load()
    data["counting"]["direction"] = "right"

    result = manager.save(data)

    assert result["backup_path"] is not None
    assert Path(result["backup_path"]).exists()
    assert len(manager.list_backups()) == 1


def test_save_invalid_config_does_not_modify_file(manager, config_path):
    """
    Critical safety property: a rejected PUT must leave
    config.yaml byte-for-byte untouched.
    """

    original_bytes = config_path.read_bytes()

    bad_data = manager.load()
    del bad_data["cameras"][0]["name"]  # now invalid

    with pytest.raises(ConfigValidationError):
        manager.save(bad_data)

    assert config_path.read_bytes() == original_bytes
    assert manager.list_backups() == []  # no backup for a rejected save


def test_save_returns_diff_of_changed_fields(manager):

    data = manager.load()
    data["counting"]["direction"] = "right"

    result = manager.save(data)

    paths_changed = {change["path"] for change in result["changes"]}
    assert "counting.direction" in paths_changed


def test_atomic_write_leaves_no_tmp_file(manager, config_path):

    data = manager.load()
    data["counting"]["direction"] = "right"

    manager.save(data)

    tmp_path = config_path.with_suffix(".yaml.tmp")
    assert not tmp_path.exists()


# ==========================================================
# RELOAD (read current file state fresh)
# ==========================================================

def test_load_reflects_external_edit(manager, config_path):

    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    data["counting"]["direction"] = "both"

    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh)

    reloaded = manager.load()
    assert reloaded["counting"]["direction"] == "both"


# ==========================================================
# RESET / RESTORE BACKUP
# ==========================================================

def test_restore_backup_reverts_change(manager):

    original = manager.load()

    edited = manager.load()
    edited["counting"]["direction"] = "right"
    result = manager.save(edited)

    backup_name = Path(result["backup_path"]).name
    restored = manager.restore_backup(backup_name)

    assert restored["counting"]["direction"] == original["counting"]["direction"]


def test_restore_unknown_backup_raises(manager):

    with pytest.raises(FileNotFoundError):
        manager.restore_backup("config-does-not-exist.yaml")


def test_restore_backup_rejects_path_traversal(manager):

    with pytest.raises(FileNotFoundError):
        manager.restore_backup("../../etc/passwd")


def test_max_backups_is_enforced(manager):

    manager.MAX_BACKUPS = 3

    data = manager.load()

    for i in range(5):
        data["counting"]["duplicate_distance"] = i
        manager.save(data)

    assert len(manager.list_backups()) == 3


# ==========================================================
# DIFF
# ==========================================================

def test_diff_detects_nested_changes(manager):

    old = manager.load()
    new = manager.load()
    new["cameras"][0]["jam_detection"]["enabled"] = True
    new["cameras"][0]["jam_detection"]["jam_time_seconds"] = 5.0

    changes = manager.diff(old, new)
    paths = {c["path"] for c in changes}

    assert "cameras.0.jam_detection.enabled" in paths


def test_diff_empty_when_no_changes(manager):

    data = manager.load()
    assert manager.diff(data, data) == []
    