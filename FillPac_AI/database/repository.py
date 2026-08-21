from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .connection import database_connection
from .models import initialize_schema


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


def start_jam_event(
    camera_id: str,
    jam_type: str,
    condition_code: str,
    track_ids: list[int] | None = None,
    reason: str | None = None,
    roi_snapshot_id: int | None = None,
    metadata: dict | None = None,
) -> int:

    initialize_schema()

    condition_code = str(condition_code).upper().strip()

    if condition_code not in {"A", "B", "C"}:
        raise ValueError(
            f"Invalid condition_code: {condition_code}. "
            f"Expected A, B or C."
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
                status,
                track_ids,
                reason,
                roi_snapshot_id,
                metadata_json,
                created_at
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                utc_now(),
                jam_type,
                condition_code,
                "ACTIVE",
                json_string(track_ids),
                reason,
                roi_snapshot_id,
                json_string(metadata),
                utc_now(),
            ),
        )


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