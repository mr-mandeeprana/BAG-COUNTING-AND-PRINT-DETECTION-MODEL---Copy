"""
==========================================================
FillPac AI
Tests for the /api/settings endpoints in
dashboard/backend/server.py
==========================================================

Uses FastAPI's TestClient with dependency_overrides for
get_current_user / require_admin, so these tests exercise
the real route handlers (and the real ConfigManager) without
needing a live SQL Server session/auth flow.

server.CONFIG_MANAGER is swapped for a ConfigManager pointed
at a tmp_path config.yaml for every test, so the real project
config.yaml is never touched.

Run (from the project root, with dashboard/backend on the
path -- adjust the import below if your test runner's
rootdir differs):

    pytest tests/test_settings_api.py -v
==========================================================
"""

import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "dashboard" / "backend"))

import server  # noqa: E402
from src.config_manager import ConfigManager  # noqa: E402


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

ADMIN_USER = {"id": 1, "username": "admin_test", "role": "admin"}
OPERATOR_USER = {"id": 2, "username": "operator_test", "role": "operator"}


@pytest.fixture
def config_path(tmp_path):

    path = tmp_path / "config.yaml"

    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(MINIMAL_VALID_CONFIG, fh)

    return path


@pytest.fixture
def client(monkeypatch, config_path, tmp_path):
    """
    Points server.CONFIG_MANAGER / server.CONFIG_FILE at an
    isolated tmp config.yaml for the duration of one test, and
    clears auth dependency overrides afterwards.
    """

    test_manager = ConfigManager(
        config_path,
        backup_dir=tmp_path / "config_backups",
    )

    monkeypatch.setattr(server, "CONFIG_MANAGER", test_manager)
    monkeypatch.setattr(server, "CONFIG_FILE", config_path)

    yield TestClient(server.api)

    server.api.dependency_overrides.clear()


def as_admin():
    server.api.dependency_overrides[server.get_current_user] = lambda: ADMIN_USER
    server.api.dependency_overrides[server.require_admin] = lambda: ADMIN_USER


def as_operator():
    server.api.dependency_overrides[server.get_current_user] = lambda: OPERATOR_USER
    # require_admin is NOT overridden -- it must still reject a
    # non-admin role for real, exercising the actual role check.


def as_anonymous():
    server.api.dependency_overrides.clear()


# ==========================================================
# GET /api/settings
# ==========================================================

def test_get_settings_requires_auth(client):

    as_anonymous()
    response = client.get("/api/settings")

    assert response.status_code == 401


def test_get_settings_returns_config_for_authenticated_user(client):

    as_operator()
    response = client.get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["counting"]["direction"] == "left"
    assert body["config"]["cameras"][0]["name"] == "Camera 1"


# ==========================================================
# PUT /api/settings
# ==========================================================

def test_put_settings_requires_admin(client):

    as_operator()

    payload = dict(MINIMAL_VALID_CONFIG)
    payload["counting"] = {**payload["counting"], "direction": "right"}

    response = client.put("/api/settings", json=payload)

    assert response.status_code == 403


def test_put_settings_saves_valid_config(client, config_path):

    as_admin()

    payload = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID_CONFIG))  # deep copy
    payload["counting"]["direction"] = "right"

    response = client.put("/api/settings", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["applied_live"] is False
    assert body["backup_path"]

    with open(config_path, "r", encoding="utf-8") as fh:
        on_disk = yaml.safe_load(fh)

    assert on_disk["counting"]["direction"] == "right"


def test_put_settings_rejects_invalid_roi(client, config_path):
    """
    Condition A ROI must have nonzero width/height once
    jam_detection.enabled is true. This must be rejected AND
    must not modify config.yaml on disk.
    """

    as_admin()

    original_bytes = config_path.read_bytes()

    payload = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID_CONFIG))
    payload["cameras"][0]["jam_detection"] = {
        "enabled": True,
        "roi": {"x1": 100, "y1": 90, "x2": 100, "y2": 680},  # invalid: zero width
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

    response = client.put("/api/settings", json=payload)

    assert response.status_code == 400
    assert config_path.read_bytes() == original_bytes


def test_put_settings_rejects_missing_camera_name(client, config_path):

    as_admin()

    original_bytes = config_path.read_bytes()

    payload = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID_CONFIG))
    del payload["cameras"][0]["name"]

    response = client.put("/api/settings", json=payload)

    assert response.status_code == 400
    assert config_path.read_bytes() == original_bytes


# ==========================================================
# POST /api/settings/validate
# ==========================================================

def test_validate_endpoint_does_not_write_file(client, config_path):

    as_admin()
    original_bytes = config_path.read_bytes()

    payload = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID_CONFIG))
    payload["counting"]["direction"] = "right"

    response = client.post("/api/settings/validate", json=payload)

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert config_path.read_bytes() == original_bytes  # unchanged


def test_validate_endpoint_reports_invalid_config(client):

    as_admin()

    payload = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID_CONFIG))
    del payload["cameras"][0]["name"]

    response = client.post("/api/settings/validate", json=payload)

    assert response.status_code == 200
    assert response.json()["valid"] is False


# ==========================================================
# POST /api/settings/reload
# ==========================================================

def test_reload_requires_admin(client):

    as_operator()
    response = client.post("/api/settings/reload")

    assert response.status_code == 403


def test_reload_confirms_valid_config_on_disk(client):

    as_admin()
    response = client.post("/api/settings/reload")

    assert response.status_code == 200
    assert response.json()["valid"] is True


# ==========================================================
# GET /api/settings/backups
# ==========================================================

def test_list_backups_empty_before_any_save(client):

    as_operator()
    response = client.get("/api/settings/backups")

    assert response.status_code == 200
    assert response.json()["backups"] == []


# ==========================================================
# POST /api/settings/reset
# ==========================================================

def test_reset_requires_admin(client):

    as_operator()
    response = client.post("/api/settings/reset")

    assert response.status_code == 403


def test_reset_with_no_backups_returns_404(client):

    as_admin()
    response = client.post("/api/settings/reset")

    assert response.status_code == 404


def test_reset_restores_most_recent_backup(client, config_path):

    as_admin()

    payload = yaml.safe_load(yaml.safe_dump(MINIMAL_VALID_CONFIG))
    payload["counting"]["direction"] = "right"
    client.put("/api/settings", json=payload)  # create one backup

    response = client.post("/api/settings/reset")

    assert response.status_code == 200
    body = response.json()
    assert body["restored"] is True
    assert body["config"]["counting"]["direction"] == "left"  # back to original

    with open(config_path, "r", encoding="utf-8") as fh:
        on_disk = yaml.safe_load(fh)

    assert on_disk["counting"]["direction"] == "left"


# ==========================================================
# EXISTING APIS STILL WORK
# (sanity check that adding /api/settings didn't break the
#  unrelated status endpoint)
# ==========================================================

def test_api_info_endpoint_still_works(client):

    response = client.get("/api")

    assert response.status_code == 200
    assert response.json()["service"] == "FillPac AI Dashboard API"