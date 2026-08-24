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
    """
    Save one production event row for a camera.

    CRITICAL CONTRACT
    ------------------
    Each call inserts exactly one row into production_events.
    Dashboard/API code SUMs bag_count across all rows to get a
    canonical total (see get_production_summary() below) -- so
    this must be called ONCE per confirmed bag, with bag_count
    set to that bag's own contribution (normally 1 for a
    per-event row), NOT the camera's running total. Writing the
    running total on every call would make totals grow by
    O(n^2) instead of matching the true bag count.

    Callers: CountLogger.log_count() is the single source of
    truth for this table (see src/pipeline.py's
    "SQL SERVER PRODUCTION EVENT" section) -- avoid adding a
    second direct call site.

    Returns:
        production_event ID in SQL Server

    Raises:
        SqlWriteFailed: If SQL write fails (queued to failsafe)
    """

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


def _validate_condition_metadata(metadata: dict | None) -> dict:
    """
    Validate that a jam_event `metadata` dict contains the
    fields expected for its condition_code, before it's written
    to SQL Server.

    This does not raise on missing detail fields (Condition B/C
    payloads are built from live detector output that can
    legitimately be incomplete in edge cases) -- it logs a
    warning instead, so a slightly incomplete payload doesn't
    take down the write path. It DOES raise for structurally
    invalid input (wrong type, invalid condition_code), since
    those indicate a caller bug rather than incomplete detector
    output, and writing them would silently produce a broken
    row.

    Args:
        metadata: The metadata dict passed to start_jam_event()

    Returns:
        The metadata dict, unchanged (validated in place).

    Raises:
        ValueError: If metadata is not a dict, or condition_code
            is present but not one of 'A', 'B', 'C'.
    """

    if metadata is None:
        return {}

    if not isinstance(metadata, dict):
        raise ValueError(
            "jam_event metadata must be None or dict, got "
            f"{type(metadata).__name__}"
        )

    condition_code = metadata.get("condition_code")

    if condition_code is not None and condition_code not in {"A", "B", "C"}:
        raise ValueError(
            "jam_event metadata.condition_code must be 'A', 'B', "
            f"or 'C', got {condition_code!r}"
        )

    if condition_code == "B":
        nested = metadata.get("spacing_result")
        flat_keys = {
            k: v for k, v in metadata.items()
            if k not in ("condition_c_result", "spacing_result", "jam_result")
        }
        source = {**nested, **flat_keys} if isinstance(nested, dict) else flat_keys

        has_gap = (
            source.get("minimum_gap_mm") is not None
            or source.get("minimum_safe_gap_mm") is not None
        )

        if not has_gap:
            logger.warning(
                "jam_event metadata for Condition B missing gap "
                "data; expected minimum_gap_mm or "
                "minimum_safe_gap_mm in metadata"
            )

    if condition_code == "C":
        nested = metadata.get("condition_c_result")
        flat_keys = {
            k: v for k, v in metadata.items()
            if k not in ("condition_c_result", "spacing_result", "jam_result")
        }
        source = {**nested, **flat_keys} if isinstance(nested, dict) else flat_keys

        if source.get("occupancy_percent") is None:
            logger.warning(
                "jam_event metadata for Condition C missing "
                "occupancy_percent; this will result in NULL "
                "occupancy_percent in jam_events"
            )

    return metadata


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
    """
    Start recording a new jam event.

    CRITICAL CONTRACT
    ------------------
    This creates ONE row in jam_events with status='ACTIVE'.

    - Do NOT call this multiple times for the same physical jam
      condition. Call it ONCE per (camera_id, condition_code)
      when that condition's jam state transitions False -> True.
    - Condition A (movement), Condition B (spacing), and
      Condition C (occupancy) are independent physical
      conditions that can be active concurrently on the same
      camera -- each gets its own jam_events row and its own
      start/end pair. Do not collapse them into a single call;
      that would lose which condition(s) are actually active.
    - Use end_jam_event() to transition status to
      RECOVERED/TIMEOUT once that same condition clears.

    Returns:
        jam_event ID in SQL Server

    Raises:
        ValueError: If condition_code not in {'A', 'B', 'C'}
        SqlWriteFailed: If SQL write fails (queued to failsafe)
    """

    initialize_schema()

    condition_code = str(condition_code).upper().strip()

    if condition_code not in {"A", "B", "C"}:
        raise ValueError(
            f"Invalid condition_code: {condition_code}. "
            f"Expected A, B or C."
        )

    # Validate metadata early, before any DB work, so malformed
    # detector output fails fast instead of writing a broken row.
    metadata = _validate_condition_metadata(metadata)

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


# ==========================================================
# CANONICAL READ METHODS
#
# These are the single source of truth for dashboard/API
# consumers. server.py should call these instead of running
# its own SUM()/aggregation queries or reconstructing state
# from raw event rows, so there's exactly one place that
# defines what "current state" and "totals" mean.
# ==========================================================

def get_current_system_state() -> dict | None:
    """
    Return the current system state as a single dict.

    Canonical source for model_loaded, inference_manager_running,
    elasticsearch_connected, dashboard_enabled, and the full
    last-persisted DashboardState snapshot (via state_json).

    Returns:
        dict with system status fields, or None if
        dbo.system_state has never been written to.
    """

    initialize_schema()

    with database_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                system_status,
                model_loaded,
                inference_manager_running,
                elasticsearch_connected,
                dashboard_enabled,
                state_json,
                updated_at
            FROM dbo.system_state
            WHERE id = 1
            """
        )

        row = cursor.fetchone()

        if row is None:
            return None

        try:
            state_dict = json.loads(row[5]) if row[5] else {}
        except (TypeError, ValueError):
            state_dict = {}

        return {
            **state_dict,
            "system_status": row[0],
            "model_loaded": bool(row[1]),
            "inference_manager_running": bool(row[2]),
            "elasticsearch_connected": bool(row[3]),
            "dashboard_enabled": bool(row[4]),
            "updated_at": row[6].isoformat() if row[6] else None,
        }


def get_camera_state(camera_id: str) -> dict | None:
    """
    Return normalized camera state (current snapshot, not
    history) -- single row per camera from dbo.camera_status.

    Returns:
        dict with camera status, or None if the camera has
        never reported in.
    """

    initialize_schema()

    with database_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                camera_id,
                status,
                fps,
                frame_count,
                last_seen,
                updated_at,
                state_json
            FROM dbo.camera_status
            WHERE camera_id = ?
            """,
            (camera_id,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        try:
            state_dict = json.loads(row[6]) if row[6] else {}
        except (TypeError, ValueError):
            state_dict = {}

        return {
            **state_dict,
            "camera_id": row[0],
            "status": row[1],
            "fps": row[2],
            "frame_count": int(row[3] or 0),
            "last_seen": row[4].isoformat() if row[4] else None,
            "updated_at": row[5].isoformat() if row[5] else None,
        }


def get_all_camera_states() -> dict[str, dict]:
    """
    Return all cameras' current state in one call.

    Returns:
        {"camera_1": {...}, "camera_2": {...}, ...}
    """

    initialize_schema()

    with database_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                camera_id,
                status,
                fps,
                frame_count,
                last_seen,
                updated_at,
                state_json
            FROM dbo.camera_status
            ORDER BY camera_id
            """
        )

        result = {}

        for row in cursor.fetchall():
            try:
                state_dict = json.loads(row[6]) if row[6] else {}
            except (TypeError, ValueError):
                state_dict = {}

            result[row[0]] = {
                **state_dict,
                "camera_id": row[0],
                "status": row[1],
                "fps": row[2],
                "frame_count": int(row[3] or 0),
                "last_seen": row[4].isoformat() if row[4] else None,
                "updated_at": row[5].isoformat() if row[5] else None,
            }

        return result


def get_production_summary(camera_id: str | None = None) -> dict:
    """
    Return production totals from dbo.production_events.

    CRITICAL: This is the ONLY source of truth for counts.
    Dashboard/API code must not recompute totals by summing
    raw event rows itself -- call this instead.

    Args:
        camera_id: If provided, return totals for one camera
            only. If None, return system-wide totals plus a
            per-camera breakdown.

    Returns:
        If camera_id is None:
            {
                "total_bags": 1234,
                "total_printed": 1000,
                "total_missing": 234,
                "cameras": {
                    "camera_1": {"total": ..., "printed": ..., "missing": ...},
                    ...
                },
            }

        If camera_id is given:
            {"total": 100, "printed": 85, "missing": 15}
    """

    initialize_schema()

    with database_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                camera_id,
                SUM(bag_count),
                SUM(printed_count),
                SUM(unprinted_count)
            FROM dbo.production_events
            GROUP BY camera_id
            ORDER BY camera_id
            """
        )

        cameras = {}
        total_bags = 0
        total_printed = 0
        total_missing = 0

        for cam_id, bags, printed, missing in cursor.fetchall():
            bags = int(bags or 0)
            printed = int(printed or 0)
            missing = int(missing or 0)

            cameras[cam_id] = {
                "total": bags,
                "printed": printed,
                "missing": missing,
            }

            total_bags += bags
            total_printed += printed
            total_missing += missing

        if camera_id is not None:
            return cameras.get(camera_id, {
                "total": 0,
                "printed": 0,
                "missing": 0,
            })

        return {
            "total_bags": total_bags,
            "total_printed": total_printed,
            "total_missing": total_missing,
            "cameras": cameras,
        }


def get_active_jam_events() -> list[dict]:
    """
    Return all currently ACTIVE jam events (status = 'ACTIVE'),
    across all conditions/cameras.

    Because Condition A/B/C are tracked independently (see
    start_jam_event()'s docstring), a single camera can have
    more than one ACTIVE row at once -- e.g. a spacing jam and
    an occupancy jam concurrently. That's expected, not a bug.

    Returns:
        List of jam event dicts, most recent first per camera.
    """

    initialize_schema()

    with database_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                camera_id,
                start_time,
                condition_code,
                condition_name,
                jam_type,
                status,
                track_ids,
                bag_count,
                minimum_gap_mm,
                average_gap_mm,
                threshold_mm,
                occupancy_percent,
                max_allowed_bags,
                direction,
                metadata_json,
                created_at
            FROM dbo.jam_events
            WHERE status = 'ACTIVE'
            ORDER BY camera_id, start_time DESC
            """
        )

        events = []

        for row in cursor.fetchall():
            try:
                metadata = json.loads(row[15]) if row[15] else {}
            except (TypeError, ValueError):
                metadata = {}

            try:
                track_ids = json.loads(row[7]) if row[7] else []
            except (TypeError, ValueError):
                track_ids = []

            events.append({
                "id": row[0],
                "camera_id": row[1],
                "start_time": row[2].isoformat() if row[2] else None,
                "condition_code": row[3],
                "condition_name": row[4],
                "jam_type": row[5],
                "status": row[6],
                "track_ids": track_ids,
                "bag_count": row[8],
                "minimum_gap_mm": row[9],
                "average_gap_mm": row[10],
                "threshold_mm": row[11],
                "occupancy_percent": row[12],
                "max_allowed_bags": row[13],
                "direction": row[14],
                "created_at": row[16].isoformat() if row[16] else None,
                "metadata": metadata,
            })

        return events


def get_recent_jam_events(
    camera_id: str | None = None,
    limit: int = 100,
    hours: int = 24,
) -> list[dict]:
    """
    Return recent jam events (completed or active), most recent
    first.

    Args:
        camera_id: Optional filter for one camera.
        limit: Max number of events to return.
        hours: Only include events created in the last N hours.

    Returns:
        List of jam event dicts.
    """

    initialize_schema()

    with database_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT DATEADD(HOUR, ?, GETUTCDATE())", (-hours,))
        cutoff_time = cursor.fetchone()[0]

        query = """
            SELECT TOP (?)
                id,
                camera_id,
                start_time,
                end_time,
                duration_seconds,
                condition_code,
                condition_name,
                jam_type,
                status,
                track_ids,
                bag_count,
                minimum_gap_mm,
                average_gap_mm,
                threshold_mm,
                occupancy_percent,
                metadata_json,
                created_at
            FROM dbo.jam_events
            WHERE created_at >= ?
        """

        params = [limit, cutoff_time]

        if camera_id:
            query += " AND camera_id = ?"
            params.append(camera_id)

        query += " ORDER BY created_at DESC"

        cursor.execute(query, params)

        events = []

        for row in cursor.fetchall():
            try:
                metadata = json.loads(row[15]) if row[15] else {}
            except (TypeError, ValueError):
                metadata = {}

            try:
                track_ids = json.loads(row[9]) if row[9] else []
            except (TypeError, ValueError):
                track_ids = []

            events.append({
                "id": row[0],
                "camera_id": row[1],
                "start_time": row[2].isoformat() if row[2] else None,
                "end_time": row[3].isoformat() if row[3] else None,
                "duration_seconds": row[4],
                "condition_code": row[5],
                "condition_name": row[6],
                "jam_type": row[7],
                "status": row[8],
                "track_ids": track_ids,
                "bag_count": row[10],
                "minimum_gap_mm": row[11],
                "average_gap_mm": row[12],
                "threshold_mm": row[13],
                "occupancy_percent": row[14],
                "created_at": row[16].isoformat() if row[16] else None,
                "metadata": metadata,
            })

        return events


def get_recent_print_events(
    camera_id: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    Return recent print detection events, most recent first.

    Should be ONE record per bag detection (see
    save_print_event()'s single call site in
    src/pipeline.py's "SQL SERVER PRINT EVENTS" section).

    Args:
        camera_id: Optional filter for one camera.
        limit: Max number of events to return.

    Returns:
        List of print event dicts.
    """

    initialize_schema()

    with database_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT TOP (?)
                id,
                camera_id,
                timestamp,
                track_id,
                result,
                confidence,
                metadata_json
            FROM dbo.print_events
        """

        params = [limit]

        if camera_id:
            query += " WHERE camera_id = ?"
            params.append(camera_id)

        query += " ORDER BY timestamp DESC"

        cursor.execute(query, params)

        events = []

        for row in cursor.fetchall():
            try:
                metadata = json.loads(row[6]) if row[6] else {}
            except (TypeError, ValueError):
                metadata = {}

            events.append({
                "id": row[0],
                "camera_id": row[1],
                "timestamp": row[2].isoformat() if row[2] else None,
                "track_id": row[3],
                "result": row[4],
                "confidence": row[5],
                "metadata": metadata,
            })

        return events


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