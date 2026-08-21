from __future__ import annotations

import functools
import inspect
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from . import failsafe
from .connection import database_connection
from .models import initialize_schema


logger = logging.getLogger(__name__)


class SqlWriteFailed(RuntimeError):
    """
    Raised when a repository write could not reach SQL Server,
    even after retrying.

    The underlying event has been queued to the local failover
    file (database/failsafe.py) and will be replayed
    automatically once SQL Server is reachable again -- it has
    NOT been lost. Existing callers that catch `Exception`
    around these calls (CountLogger, pipeline.py, dashboard.py)
    keep working exactly as before; this is just a more specific
    exception type carrying that guarantee.
    """


def _resilient_write(op_name: str, *, retries: int = 0, retry_delay: float = 0.3):
    """
    Wrap a repository write function so a SQL Server failure
    queues the write for later replay instead of silently
    dropping it.

    retries=0 by default: these functions are called inline from
    the live camera/pipeline threads, so we fail fast and hand
    off to the background failover queue rather than blocking
    frame processing with sleep-based retries. The background
    replay thread (started in database/failsafe.py) retries
    queued writes every 30s regardless.
    """

    def decorator(func):

        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            # Normalize to a kwargs-only dict (regardless of how
            # the caller invoked it) so it can be queued and
            # replayed later with the same arguments.
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            call_kwargs = dict(bound.arguments)

            last_error = None

            for attempt in range(retries + 1):
                try:
                    return func(**call_kwargs)
                except (ValueError, TypeError):
                    # Caller/validation error (e.g. an invalid
                    # condition_code), not a SQL Server/connection
                    # failure. Retrying or queuing it would never
                    # succeed and would just sit in the failover
                    # queue -- let it raise immediately instead.
                    raise
                except Exception as error:
                    last_error = error
                    if attempt < retries:
                        time.sleep(retry_delay)

            queued = False

            try:
                failsafe.enqueue(op_name, call_kwargs)
                queued = True
            except Exception:
                logger.exception(
                    "SQL write AND local failover queue both "
                    "failed | op=%s -- this event is lost.",
                    op_name,
                )

            logger.error(
                "SQL write failed after %s attempt(s) | op=%s | "
                "queued_for_replay=%s | error=%s",
                retries + 1, op_name, queued, last_error,
            )

            raise SqlWriteFailed(
                f"{op_name} failed after {retries + 1} attempt(s); "
                + (
                    "queued for automatic replay once SQL Server "
                    "is reachable again."
                    if queued else
                    "ALSO failed to queue locally -- event lost."
                )
            ) from last_error

        # Replay (database/failsafe.py) calls the undecorated
        # function directly so a failed replay attempt doesn't
        # go through this wrapper and get re-queued mid-rewrite.
        wrapper._raw = func

        return wrapper

    return decorator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_string(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
    )


def _insert_and_get_id(
    conn,
    sql: str,
    params: tuple,
) -> int:
    """
    Execute SQL Server INSERT ... OUTPUT INSERTED.id
    and return the newly created ID.
    """

    cursor = conn.execute(sql, params)
    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Database INSERT succeeded but no ID was returned."
        )

    return int(row[0])


@_resilient_write("save_production_event")
def save_production_event(
    camera_id: str,
    bag_count: int = 0,
    printed_count: int = 0,
    unprinted_count: int = 0,
    line_count: int = 0,
    frame_roi_count: int = 0,
    bags_inside_roi: int = 0,
    timestamp: str | None = None,
    metadata: dict | None = None,
) -> int:

    initialize_schema()

    timestamp = timestamp or utc_now()

    with database_connection() as conn:

        return _insert_and_get_id(
            conn,
            """
            INSERT INTO production_events (
                camera_id,
                timestamp,
                bag_count,
                printed_count,
                unprinted_count,
                line_count,
                frame_roi_count,
                bags_inside_roi,
                metadata_json
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                timestamp,
                bag_count,
                printed_count,
                unprinted_count,
                line_count,
                frame_roi_count,
                bags_inside_roi,
                json_string(metadata),
            ),
        )


@_resilient_write("save_print_event")
def save_print_event(
    camera_id: str,
    result: str,
    track_id: int | None = None,
    confidence: float | None = None,
    timestamp: str | None = None,
    metadata: dict | None = None,
) -> int:

    initialize_schema()

    timestamp = timestamp or utc_now()

    with database_connection() as conn:

        return _insert_and_get_id(
            conn,
            """
            INSERT INTO print_events (
                camera_id,
                timestamp,
                track_id,
                result,
                confidence,
                metadata_json
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                timestamp,
                track_id,
                result,
                confidence,
                json_string(metadata),
            ),
        )


@_resilient_write("save_roi_snapshot")
def save_roi_snapshot(
    camera_id: str,
    event_type: str,
    image_path: str,
    timestamp: str | None = None,
    file_size: int | None = None,
    width: int | None = None,
    height: int | None = None,
    sha256: str | None = None,
    metadata: dict | None = None,
) -> int:

    initialize_schema()

    timestamp = timestamp or utc_now()

    with database_connection() as conn:

        return _insert_and_get_id(
            conn,
            """
            INSERT INTO roi_snapshots (
                camera_id,
                timestamp,
                event_type,
                image_path,
                file_size,
                width,
                height,
                sha256,
                metadata_json,
                created_at
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                timestamp,
                event_type,
                image_path,
                file_size,
                width,
                height,
                sha256,
                json_string(metadata),
                utc_now(),
            ),
        )


def get_recent_production_events(limit: int = 5000) -> list[dict]:
    """
    Return recent confirmed bag-count events for the dashboard
    /events, /events/export and /analytics endpoints.

    Each dict is the full original event that CountLogger
    recorded (camera, total_count, track_id, print_status,
    shift, etc.) -- reconstructed from metadata_json, the same
    shape the old count_events.jsonl rows used to have.

    NOTE: unlike the old JSONL file (which the dashboard read
    in full, unbounded, on every request), this is capped at
    `limit` most-recent rows so a long-running plant doesn't
    turn every dashboard request into an unbounded table scan.
    Increase `limit` if you need a longer history in one call.
    """

    initialize_schema()

    with database_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT TOP (?) metadata_json, camera_id, timestamp
            FROM dbo.production_events
            ORDER BY timestamp DESC
            """,
            (limit,),
        )

        events = []

        for metadata_json, camera_id, timestamp in cursor.fetchall():

            if metadata_json:

                try:
                    event = json.loads(metadata_json)

                except (TypeError, ValueError):
                    event = None

            else:
                event = None

            if not isinstance(event, dict):

                # Fall back to the structured columns if
                # metadata_json is missing/unparseable so the
                # row still shows up instead of disappearing.
                event = {
                    "camera": camera_id,
                    "timestamp": (
                        timestamp.isoformat()
                        if hasattr(timestamp, "isoformat")
                        else timestamp
                    ),
                }

            events.append(event)

        # Oldest-first, matching the old JSONL append order.
        events.reverse()

        return events


def get_condition_c_events(limit: int = 2000) -> list[dict]:
    """
    Return recent Condition C (ROI occupancy) jam events for
    the dashboard /analytics endpoint.

    Each dict is the full result payload the pipeline passed
    to start_jam_event(condition_code="C", metadata=...) --
    reconstructed from metadata_json, the same shape the old
    logs/condition_c/events/*.json files used to have.
    """

    initialize_schema()

    with database_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT TOP (?) metadata_json
            FROM dbo.jam_events
            WHERE condition_code = 'C'
            ORDER BY start_time DESC
            """,
            (limit,),
        )

        events = []

        for (metadata_json,) in cursor.fetchall():

            if not metadata_json:
                continue

            try:
                event = json.loads(metadata_json)

            except (TypeError, ValueError):
                continue

            if isinstance(event, dict):
                events.append(event)

        events.reverse()

        return events


@_resilient_write("save_dashboard_state")
def save_dashboard_state(state: dict) -> None:
    """
    Persist the DashboardState in-memory snapshot to SQL Server.

    Replaces the old dashboard/backend/state.json file. The
    top-level (system-wide) fields are upserted into
    dbo.system_state (id = 1), and each entry under
    state["cameras"] is upserted into dbo.camera_status.

    The full snapshot is also stored per-row as JSON
    (state_json) so nothing is lost even though only a
    handful of fields are broken out into real columns.
    """

    initialize_schema()

    service_status = state.get("service_status") or {}

    cameras = state.get("cameras") or {}

    now = utc_now()

    with database_connection() as conn:

        cursor = conn.cursor()

        # --------------------------------------------------
        # system_state (single row, id = 1)
        # --------------------------------------------------

        cursor.execute(
            """
            IF EXISTS (SELECT 1 FROM dbo.system_state WHERE id = 1)
                UPDATE dbo.system_state
                SET
                    system_status = ?,
                    model_loaded = ?,
                    inference_manager_running = ?,
                    elasticsearch_connected = ?,
                    dashboard_enabled = ?,
                    state_json = ?,
                    updated_at = ?
                WHERE id = 1
            ELSE
                INSERT INTO dbo.system_state (
                    id,
                    system_status,
                    model_loaded,
                    inference_manager_running,
                    elasticsearch_connected,
                    dashboard_enabled,
                    state_json,
                    updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                # UPDATE branch params
                state.get("system_status"),
                bool(service_status.get("model_loaded", False)),
                bool(service_status.get("inference_manager_running", False)),
                bool(service_status.get("elasticsearch_connected", False)),
                bool(service_status.get("dashboard_enabled", True)),
                json_string(state),
                now,
                # INSERT branch params
                state.get("system_status"),
                bool(service_status.get("model_loaded", False)),
                bool(service_status.get("inference_manager_running", False)),
                bool(service_status.get("elasticsearch_connected", False)),
                bool(service_status.get("dashboard_enabled", True)),
                json_string(state),
                now,
            ),
        )

        # --------------------------------------------------
        # camera_status (one row per camera)
        # --------------------------------------------------

        for camera_name, camera in cameras.items():

            if not isinstance(camera, dict):
                continue

            cursor.execute(
                """
                IF EXISTS (
                    SELECT 1 FROM dbo.camera_status
                    WHERE camera_id = ?
                )
                    UPDATE dbo.camera_status
                    SET
                        status = ?,
                        fps = ?,
                        frame_count = ?,
                        last_seen = ?,
                        state_json = ?,
                        updated_at = ?
                    WHERE camera_id = ?
                ELSE
                    INSERT INTO dbo.camera_status (
                        camera_id,
                        status,
                        fps,
                        frame_count,
                        last_seen,
                        state_json,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    # UPDATE branch params
                    camera_name,
                    camera.get("status"),
                    camera.get("fps"),
                    int(camera.get("frame_count", 0) or 0),
                    now,
                    json_string(camera),
                    now,
                    camera_name,
                    # INSERT branch params
                    camera_name,
                    camera.get("status"),
                    camera.get("fps"),
                    int(camera.get("frame_count", 0) or 0),
                    now,
                    json_string(camera),
                    now,
                ),
            )

        conn.commit()


def load_dashboard_state() -> dict | None:
    """
    Reload the most recently persisted DashboardState snapshot
    from SQL Server (system_state + camera_status), for seeding
    a fresh DashboardState instance after a restart.

    Returns None if nothing has been persisted yet.
    """

    initialize_schema()

    with database_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            "SELECT state_json FROM dbo.system_state WHERE id = 1"
        )

        row = cursor.fetchone()

        if row is None or row[0] is None:
            return None

        try:
            state = json.loads(row[0])

        except (TypeError, ValueError):
            return None

        cursor.execute(
            "SELECT camera_id, state_json FROM dbo.camera_status"
        )

        cameras = {}

        for camera_id, state_json_value in cursor.fetchall():

            if not state_json_value:
                continue

            try:
                cameras[camera_id] = json.loads(state_json_value)

            except (TypeError, ValueError):
                continue

        if cameras:
            state["cameras"] = cameras

        return state


@_resilient_write("start_jam_event")
def start_jam_event(
    camera_id: str,
    jam_type: str,
    condition_code: str,
    track_ids: list[int] | None = None,
    reason: str | None = None,
    roi_snapshot_id: int | None = None,
    metadata: dict | None = None,
    condition_name: str | None = None,
) -> int:

    initialize_schema()

    condition_code = str(condition_code).upper().strip()

    if condition_code not in {"A", "B", "C"}:
        raise ValueError(
            f"Invalid condition_code: {condition_code}. "
            f"Expected A, B or C."
        )

    # Falls back to the standard name for the condition code if
    # the caller didn't pass one explicitly, so condition_name
    # is always populated even for older call sites.
    CONDITION_NAMES = {
        "A": "MOVEMENT_JAM",
        "B": "BAG_SPACING_JAM",
        "C": "ROI_OCCUPANCY_JAM",
    }

    condition_name = (
        condition_name
        or CONDITION_NAMES.get(condition_code)
    )

    with database_connection() as conn:

        return _insert_and_get_id(
            conn,
            """
            INSERT INTO dbo.jam_events (
                camera_id,
                start_time,
                jam_type,
                condition_code,
                condition_name,
                status,
                track_ids,
                reason,
                roi_snapshot_id,
                metadata_json,
                created_at
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                utc_now(),
                jam_type,
                condition_code,
                condition_name,
                "ACTIVE",
                json_string(track_ids),
                reason,
                roi_snapshot_id,
                json_string(metadata),
                utc_now(),
            ),
        )


@_resilient_write("end_jam_event")
def end_jam_event(
    jam_event_id: int,
    duration_seconds: float,
    status: str = "RECOVERED",
) -> None:

    initialize_schema()

    with database_connection() as conn:

        cursor = conn.execute(
            """
            UPDATE dbo.jam_events
            SET
                end_time = ?,
                duration_seconds = ?,
                status = ?
            WHERE id = ?
            """,
            (
                utc_now(),
                float(duration_seconds),
                status,
                jam_event_id,
            ),
        )

        if cursor.rowcount == 0:
            raise RuntimeError(
                f"Jam event ID {jam_event_id} was not found."
            )


@_resilient_write("save_application_log")
def save_application_log(
    level: str,
    logger: str,
    message: str,
    event_type: str | None = None,
    camera_id: str | None = None,
    exception: str | None = None,
    metadata: dict | None = None,
) -> int:

    initialize_schema()

    with database_connection() as conn:

        return _insert_and_get_id(
            conn,
            """
            INSERT INTO application_logs (
                timestamp,
                level,
                logger,
                event_type,
                camera_id,
                message,
                exception,
                metadata_json
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now(),
                level,
                logger,
                event_type,
                camera_id,
                message,
                exception,
                json_string(metadata),
            ),
        )