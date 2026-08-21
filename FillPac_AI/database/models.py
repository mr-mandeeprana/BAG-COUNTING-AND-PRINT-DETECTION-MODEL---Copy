from __future__ import annotations

from .connection import database_connection


# ==========================================================
# SQL SERVER SCHEMA
# ==========================================================

SCHEMA_STATEMENTS = [

    # ======================================================
    # SYSTEM STATE
    # ======================================================

    """
    IF OBJECT_ID('dbo.system_state', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.system_state (
            id INT NOT NULL PRIMARY KEY,
            system_status NVARCHAR(50),
            model_loaded BIT NOT NULL DEFAULT 0,
            inference_manager_running BIT NOT NULL DEFAULT 0,
            elasticsearch_connected BIT NOT NULL DEFAULT 0,
            dashboard_enabled BIT NOT NULL DEFAULT 1,
            updated_at DATETIMEOFFSET NOT NULL
        );
    END
    """,

    # ======================================================
    # CAMERA STATUS
    # ======================================================

    """
    IF OBJECT_ID('dbo.camera_status', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.camera_status (
            id INT IDENTITY(1,1) PRIMARY KEY,
            camera_id NVARCHAR(100) NOT NULL UNIQUE,
            status NVARCHAR(50),
            fps FLOAT,
            frame_count BIGINT NOT NULL DEFAULT 0,
            last_seen DATETIMEOFFSET,
            updated_at DATETIMEOFFSET NOT NULL
        );
    END
    """,

    # ======================================================
    # PRODUCTION EVENTS
    # ======================================================

    """
    IF OBJECT_ID('dbo.production_events', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.production_events (
            id BIGINT IDENTITY(1,1) PRIMARY KEY,
            camera_id NVARCHAR(100) NOT NULL,
            timestamp DATETIMEOFFSET NOT NULL,
            bag_count INT NOT NULL DEFAULT 0,
            printed_count INT NOT NULL DEFAULT 0,
            unprinted_count INT NOT NULL DEFAULT 0,
            line_count INT NOT NULL DEFAULT 0,
            frame_roi_count INT NOT NULL DEFAULT 0,
            bags_inside_roi INT NOT NULL DEFAULT 0,
            metadata_json NVARCHAR(MAX)
        );
    END
    """,

    # ======================================================
    # PRINT EVENTS
    # ======================================================

    """
    IF OBJECT_ID('dbo.print_events', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.print_events (
            id BIGINT IDENTITY(1,1) PRIMARY KEY,
            camera_id NVARCHAR(100) NOT NULL,
            timestamp DATETIMEOFFSET NOT NULL,
            track_id BIGINT,
            result NVARCHAR(50),
            confidence FLOAT,
            metadata_json NVARCHAR(MAX)
        );
    END
    """,

    # ======================================================
    # ROI SNAPSHOTS
    # ======================================================

    """
    IF OBJECT_ID('dbo.roi_snapshots', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.roi_snapshots (
            id BIGINT IDENTITY(1,1) PRIMARY KEY,
            camera_id NVARCHAR(100) NOT NULL,
            timestamp DATETIMEOFFSET NOT NULL,
            event_type NVARCHAR(100),
            image_path NVARCHAR(1000) NOT NULL,
            file_size BIGINT,
            width INT,
            height INT,
            sha256 NVARCHAR(128),
            metadata_json NVARCHAR(MAX),
            created_at DATETIMEOFFSET NOT NULL
        );
    END
    """,

    # ======================================================
    # JAM EVENTS
    #
    # CONDITION A = MOVEMENT JAM
    # CONDITION B = BAG SPACING JAM
    # CONDITION C = ROI OCCUPANCY JAM
    #
    # All three conditions are stored in one table and
    # distinguished by condition_code / condition_name.
    # ======================================================

    """
    IF OBJECT_ID('dbo.jam_events', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.jam_events (
            id BIGINT IDENTITY(1,1) PRIMARY KEY,
            camera_id NVARCHAR(100) NOT NULL,
            start_time DATETIMEOFFSET NOT NULL,
            end_time DATETIMEOFFSET,
            duration_seconds FLOAT,
            jam_type NVARCHAR(100),
            condition_code NVARCHAR(10),
            status NVARCHAR(50),
            track_ids NVARCHAR(MAX),
            reason NVARCHAR(1000),
            roi_snapshot_id BIGINT,
            metadata_json NVARCHAR(MAX),
            created_at DATETIMEOFFSET NOT NULL,

            CONSTRAINT FK_jam_roi_snapshot
                FOREIGN KEY (roi_snapshot_id)
                REFERENCES dbo.roi_snapshots(id)
        );
    END
    """,

    # ======================================================
    # APPLICATION LOGS
    # ======================================================

    """
    IF OBJECT_ID('dbo.application_logs', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.application_logs (
            id BIGINT IDENTITY(1,1) PRIMARY KEY,
            timestamp DATETIMEOFFSET NOT NULL,
            level NVARCHAR(50),
            logger NVARCHAR(200),
            event_type NVARCHAR(100),
            camera_id NVARCHAR(100),
            message NVARCHAR(MAX),
            exception NVARCHAR(MAX),
            metadata_json NVARCHAR(MAX)
        );
    END
    """,

    # ======================================================
    # INDEXES
    # ======================================================

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'idx_production_camera_time'
          AND object_id = OBJECT_ID('dbo.production_events')
    )
    BEGIN
        CREATE INDEX idx_production_camera_time
        ON dbo.production_events(camera_id, timestamp);
    END
    """,

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'idx_print_camera_time'
          AND object_id = OBJECT_ID('dbo.print_events')
    )
    BEGIN
        CREATE INDEX idx_print_camera_time
        ON dbo.print_events(camera_id, timestamp);
    END
    """,

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'idx_jam_camera_time'
          AND object_id = OBJECT_ID('dbo.jam_events')
    )
    BEGIN
        CREATE INDEX idx_jam_camera_time
        ON dbo.jam_events(camera_id, start_time);
    END
    """,

    """
    IF OBJECT_ID('dbo.jam_events', 'U') IS NOT NULL
       AND NOT EXISTS (
            SELECT 1
            FROM sys.indexes
            WHERE name = 'idx_jam_condition'
              AND object_id = OBJECT_ID('dbo.jam_events')
       )
    BEGIN
        CREATE INDEX idx_jam_condition
        ON dbo.jam_events(condition_code);
    END
    """,

    """
    IF OBJECT_ID('dbo.jam_events', 'U') IS NOT NULL
       AND NOT EXISTS (
            SELECT 1
            FROM sys.indexes
            WHERE name = 'idx_jam_camera_condition_time'
              AND object_id = OBJECT_ID('dbo.jam_events')
       )
    BEGIN
        CREATE INDEX idx_jam_camera_condition_time
        ON dbo.jam_events(camera_id, condition_code, start_time);
    END
    """,

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'idx_jam_status'
          AND object_id = OBJECT_ID('dbo.jam_events')
    )
    BEGIN
        CREATE INDEX idx_jam_status
        ON dbo.jam_events(status);
    END
    """,

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'idx_snapshot_camera_time'
          AND object_id = OBJECT_ID('dbo.roi_snapshots')
    )
    BEGIN
        CREATE INDEX idx_snapshot_camera_time
        ON dbo.roi_snapshots(camera_id, timestamp);
    END
    """,

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'idx_logs_time'
          AND object_id = OBJECT_ID('dbo.application_logs')
    )
    BEGIN
        CREATE INDEX idx_logs_time
        ON dbo.application_logs(timestamp);
    END
    """,

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'idx_camera_status'
          AND object_id = OBJECT_ID('dbo.camera_status')
    )
    BEGIN
        CREATE INDEX idx_camera_status
        ON dbo.camera_status(status);
    END
    """,
]


# ==========================================================
# INITIALIZE SCHEMA
# ==========================================================

def initialize_schema() -> None:

    with database_connection() as conn:

        cursor = conn.cursor()

        for statement in SCHEMA_STATEMENTS:
            cursor.execute(statement)

        conn.commit()