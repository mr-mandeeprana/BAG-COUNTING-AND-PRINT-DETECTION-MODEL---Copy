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


def _first_present(d: dict, *keys):
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return None


def _extract_condition_detail(metadata: dict | None) -> dict:
    """
    Pull the normalized Condition B/C fields out of a jam/
    snapshot `metadata` dict, regardless of whether they live
    under `spacing_result` (Condition B), `condition_c_result`
    (Condition C), or at the top level already.

    This is what lets start_jam_event()/save_roi_snapshot()
    populate real SQL columns (bag_count, minimum_gap_mm,
    occupancy_percent, ...) from the same metadata dict callers
    already build today -- no pipeline.py call-site changes
    required. Returns a dict of column_name -> value; missing
    fields are simply absent (left NULL by the caller's default
    handling).
    """

    if not isinstance(metadata, dict):
        return {}

    # The nested result dict, if any (Condition B/C shape).
    nested = (
        metadata.get("condition_c_result")
        if isinstance(metadata.get("condition_c_result"), dict)
        else (
            metadata.get("spacing_result")
            if isinstance(metadata.get("spacing_result"), dict)
            else {}
        )
    )

    source = {**nested, **{
        k: v for k, v in metadata.items()
        if k not in ("condition_c_result", "spacing_result", "jam_result")
    }}

    roi = source.get("roi") if isinstance(source.get("roi"), dict) else {}

    pairs = (
        source.get("distances")
        or source.get("pairs")
        or source.get("jam_pairs")
        or []
    )

    return {
        "condition_code": metadata.get("condition_code"),
        "condition_name": metadata.get("condition_name"),
        "jam_type": metadata.get("jam_type"),
        "jam_status": source.get("status"),
        "jam_detected": bool(
            _first_present(source, "jam_detected", "jam") or False
        ),
        "bag_count": _first_present(source, "bag_count"),
        "pair_count": (
            source.get("pair_count")
            if source.get("pair_count") is not None
            else (len(pairs) if pairs else None)
        ),
        "active_jam_count": source.get("active_jam_count"),
        "minimum_gap_mm": _first_present(
            source, "minimum_gap_mm", "minimum_safe_gap_mm"
        ),
        "average_gap_mm": source.get("average_gap_mm"),
        "threshold_mm": _first_present(
            source, "threshold_mm", "spacing_threshold_mm"
        ),
        "minimum_safe_gap_mm": source.get("minimum_safe_gap_mm"),
        "measurement_margin_mm": source.get("measurement_margin_mm"),
        "max_allowed_bags": source.get("max_allowed_bags"),
        "occupancy_percent": source.get("occupancy_percent"),
        "jam_duration": source.get("jam_duration"),
        "direction": source.get("direction"),
        "calibrated": source.get("calibrated"),
        "track_ids": source.get("track_ids"),
        "roi_x1": roi.get("x1"),
        "roi_y1": roi.get("y1"),
        "roi_x2": roi.get("x2"),
        "roi_y2": roi.get("y2"),
        "source_event_id": source.get("event_id"),
        "pairs": pairs,
    }


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

    # Normalized Condition B/C detail, extracted from the same
    # metadata dict callers already pass -- see
    # _extract_condition_detail() above. Falls back to all-NULL
    # for snapshot types that carry no jam detail.
    detail = _extract_condition_detail(metadata)

    with database_connection() as conn:

        snapshot_id = _insert_and_get_id(
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
                created_at,
                source_event_id,
                condition_code,
                condition_name,
                jam_type,
                jam_status,
                jam_detected,
                bag_count,
                minimum_gap_mm,
                average_gap_mm,
                threshold_mm,
                max_allowed_bags,
                occupancy_percent,
                jam_duration,
                track_count,
                track_ids_json,
                roi_x1,
                roi_y1,
                roi_x2,
                roi_y2
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                (
                    str(detail.get("source_event_id"))
                    if detail.get("source_event_id") is not None
                    else None
                ),
                detail.get("condition_code"),
                detail.get("condition_name"),
                detail.get("jam_type"),
                detail.get("jam_status"),
                detail.get("jam_detected"),
                detail.get("bag_count"),
                detail.get("minimum_gap_mm"),
                detail.get("average_gap_mm"),
                detail.get("threshold_mm"),
                detail.get("max_allowed_bags"),
                detail.get("occupancy_percent"),
                detail.get("jam_duration"),
                (
                    len(detail["track_ids"])
                    if detail.get("track_ids") is not None
                    else None
                ),
                json_string(detail.get("track_ids")),
                detail.get("roi_x1"),
                detail.get("roi_y1"),
                detail.get("roi_x2"),
                detail.get("roi_y2"),
            ),
        )

        # Individual bag-pair measurements, if this snapshot's
        # metadata carried any (Condition C `distances`).
        pairs = detail.get("pairs") or []

        if pairs:
            _insert_pair_measurements(
                conn,
                camera_id=camera_id,
                jam_event_id=None,
                snapshot_id=snapshot_id,
                pairs=pairs,
            )

        return snapshot_id


def _insert_pair_measurements(
    conn,
    camera_id: str,
    jam_event_id: int | None,
    snapshot_id: int | None,
    pairs: list,
) -> None:
    """
    Bulk-insert individual bag-to-bag spacing measurements into
    dbo.jam_pair_measurements. Best-effort: a malformed pair is
    skipped rather than aborting the whole batch, since this
    child data is diagnostic and shouldn't block the parent
    jam_event/roi_snapshot write.
    """

    now = utc_now()
    rows = []

    for pair in pairs:

        if not isinstance(pair, dict):
            continue

        front_bbox = pair.get("front_bbox")
        rear_bbox = pair.get("rear_bbox")

        front_center = pair.get("front_center") or [None, None]
        rear_center = pair.get("rear_center") or [None, None]

        rows.append((
            jam_event_id,
            snapshot_id,
            camera_id,
            _first_present(pair, "front_track_id", "track1"),
            _first_present(pair, "rear_track_id", "track2"),
            _first_present(pair, "distance_mm", "gap_mm", "edge_gap_mm"),
            pair.get("distance_px"),
            pair.get("threshold_mm"),
            pair.get("minimum_safe_gap_mm"),
            pair.get("measurement_margin_mm"),
            bool(_first_present(pair, "jam_detected", "is_jam") or False),
            pair.get("status"),
            front_center[0] if len(front_center) > 0 else None,
            front_center[1] if len(front_center) > 1 else None,
            rear_center[0] if len(rear_center) > 0 else None,
            rear_center[1] if len(rear_center) > 1 else None,
            json_string(front_bbox),
            json_string(rear_bbox),
            now,
        ))

    if not rows:
        return

    cursor = conn.cursor()

    cursor.executemany(
        """
        INSERT INTO dbo.jam_pair_measurements (
            jam_event_id,
            snapshot_id,
            camera_id,
            front_track_id,
            rear_track_id,
            distance_mm,
            distance_px,
            threshold_mm,
            minimum_safe_gap_mm,
            measurement_margin_mm,
            jam_detected,
            status,
            front_center_x,
            front_center_y,
            rear_center_x,
            rear_center_y,
            front_bbox_json,
            rear_bbox_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
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

    # Normalized Condition A/B/C detail extracted from the same
    # `metadata` dict callers already build -- see
    # _extract_condition_detail() above. condition_code/name are
    # passed explicitly by the caller and take priority over
    # whatever (if anything) is duplicated inside metadata.
    detail = _extract_condition_detail(metadata)

    with database_connection() as conn:

        jam_event_id = _insert_and_get_id(
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
                created_at,
                bag_count,
                pair_count,
                active_jam_count,
                minimum_gap_mm,
                average_gap_mm,
                threshold_mm,
                minimum_safe_gap_mm,
                measurement_margin_mm,
                max_allowed_bags,
                occupancy_percent,
                jam_duration,
                direction,
                calibrated,
                roi_x1,
                roi_y1,
                roi_x2,
                roi_y2
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                detail.get("bag_count"),
                detail.get("pair_count"),
                detail.get("active_jam_count"),
                detail.get("minimum_gap_mm"),
                detail.get("average_gap_mm"),
                detail.get("threshold_mm"),
                detail.get("minimum_safe_gap_mm"),
                detail.get("measurement_margin_mm"),
                detail.get("max_allowed_bags"),
                detail.get("occupancy_percent"),
                detail.get("jam_duration"),
                detail.get("direction"),
                detail.get("calibrated"),
                detail.get("roi_x1"),
                detail.get("roi_y1"),
                detail.get("roi_x2"),
                detail.get("roi_y2"),
            ),
        )

        pairs = detail.get("pairs") or []

        if pairs:
            _insert_pair_measurements(
                conn,
                camera_id=camera_id,
                jam_event_id=jam_event_id,
                snapshot_id=roi_snapshot_id,
                pairs=pairs,
            )

        return jam_event_id


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