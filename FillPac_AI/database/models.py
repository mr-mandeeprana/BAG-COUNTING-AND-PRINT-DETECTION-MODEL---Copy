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
    # SYSTEM STATE / CAMERA STATUS -- LIVE PAYLOAD COLUMN
    #
    # DashboardState used to publish its full in-memory
    # snapshot to dashboard/backend/state.json. That file is
    # being removed; the same snapshot now lives in SQL
    # Server instead. Rather than redesigning the dashboard
    # payload into many narrow columns (which would require
    # rewriting every dashboard consumer at the same time),
    # a `state_json` column holds the full snapshot for each
    # side, while the existing structured columns above stay
    # populated for simple/fast queries.
    # ======================================================

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('dbo.system_state')
          AND name = 'state_json'
    )
    BEGIN
        ALTER TABLE dbo.system_state
        ADD state_json NVARCHAR(MAX) NULL;
    END
    """,

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('dbo.camera_status')
          AND name = 'state_json'
    )
    BEGIN
        ALTER TABLE dbo.camera_status
        ADD state_json NVARCHAR(MAX) NULL;
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
            condition_name NVARCHAR(50),
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
    # JAM EVENTS -- condition_name column
    #
    # Added after jam_events already existed in some
    # deployments (condition_name was only ever written into
    # metadata_json, never as its own column). This ALTER
    # brings existing tables up to date the same way the
    # state_json columns above were added.
    # ======================================================

    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('dbo.jam_events')
          AND name = 'condition_name'
    )
    BEGIN
        ALTER TABLE dbo.jam_events
        ADD condition_name NVARCHAR(50) NULL;
    END
    """,

    # ======================================================
    # JAM EVENTS -- backfill condition_name on old rows
    #
    # Rows written before the column above existed have
    # condition_name = NULL. This backfills them from
    # condition_code every time the schema initializes --
    # idempotent (WHERE condition_name IS NULL), so it's a
    # no-op once everything is backfilled.
    # ======================================================

    """
    IF OBJECT_ID('dbo.jam_events', 'U') IS NOT NULL
    BEGIN
        UPDATE dbo.jam_events
        SET condition_name =
            CASE condition_code
                WHEN 'A' THEN 'MOVEMENT_JAM'
                WHEN 'B' THEN 'BAG_SPACING_JAM'
                WHEN 'C' THEN 'ROI_OCCUPANCY_JAM'
                ELSE condition_name
            END
        WHERE condition_name IS NULL
          AND condition_code IN ('A', 'B', 'C');
    END
    """,

    # ======================================================
    # JAM EVENTS -- normalized condition B/C detail columns
    #
    # Previously the only place these values existed was
    # inside metadata_json (spacing_result / condition_c_result),
    # which meant every dashboard/report query had to parse
    # JSON to read something as simple as bag_count or
    # minimum_gap_mm. These columns are additive (existing rows
    # simply have NULL until re-written) and metadata_json is
    # left in place unchanged for full-fidelity/audit purposes.
    #
    # IMPORTANT: each column gets its OWN guarded ALTER
    # statement here, rather than one ALTER ... ADD col1, col2,
    # ... bundle guarded by a single "does bag_count exist"
    # check. Some deployments already had a handful of these
    # columns (e.g. bag_count) from an earlier manual fix; a
    # single combined guard skipped the ENTIRE statement in
    # that case, silently leaving the *other* new columns
    # (pair_count, roi_x1, etc.) missing even though the code
    # now inserts into them. One guard per column makes this
    # idempotent no matter which subset already exists.
    # ======================================================
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'bag_count')
    BEGIN ALTER TABLE dbo.jam_events ADD bag_count INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'pair_count')
    BEGIN ALTER TABLE dbo.jam_events ADD pair_count INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'active_jam_count')
    BEGIN ALTER TABLE dbo.jam_events ADD active_jam_count INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'minimum_gap_mm')
    BEGIN ALTER TABLE dbo.jam_events ADD minimum_gap_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'average_gap_mm')
    BEGIN ALTER TABLE dbo.jam_events ADD average_gap_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'threshold_mm')
    BEGIN ALTER TABLE dbo.jam_events ADD threshold_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'minimum_safe_gap_mm')
    BEGIN ALTER TABLE dbo.jam_events ADD minimum_safe_gap_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'measurement_margin_mm')
    BEGIN ALTER TABLE dbo.jam_events ADD measurement_margin_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'max_allowed_bags')
    BEGIN ALTER TABLE dbo.jam_events ADD max_allowed_bags INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'occupancy_percent')
    BEGIN ALTER TABLE dbo.jam_events ADD occupancy_percent DECIMAL(10,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'jam_duration')
    BEGIN ALTER TABLE dbo.jam_events ADD jam_duration DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'direction')
    BEGIN ALTER TABLE dbo.jam_events ADD direction NVARCHAR(20) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'calibrated')
    BEGIN ALTER TABLE dbo.jam_events ADD calibrated BIT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'roi_x1')
    BEGIN ALTER TABLE dbo.jam_events ADD roi_x1 INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'roi_y1')
    BEGIN ALTER TABLE dbo.jam_events ADD roi_y1 INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'roi_x2')
    BEGIN ALTER TABLE dbo.jam_events ADD roi_x2 INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.jam_events') AND name = 'roi_y2')
    BEGIN ALTER TABLE dbo.jam_events ADD roi_y2 INT NULL; END
    """,

    # ======================================================
    # ROI SNAPSHOTS -- normalized JAM-snapshot detail columns
    #
    # Condition C snapshots previously carried this same
    # information only inside metadata_json
    # (condition_c_result). Kept in sync with the jam_events
    # columns above so both tables can be queried the same way.
    # Same one-guard-per-column reasoning as jam_events above.
    # ======================================================
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'source_event_id')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD source_event_id NVARCHAR(100) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'condition_code')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD condition_code NVARCHAR(20) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'condition_name')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD condition_name NVARCHAR(100) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'jam_type')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD jam_type NVARCHAR(50) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'jam_status')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD jam_status NVARCHAR(30) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'jam_detected')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD jam_detected BIT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'bag_count')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD bag_count INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'minimum_gap_mm')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD minimum_gap_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'average_gap_mm')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD average_gap_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'threshold_mm')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD threshold_mm DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'max_allowed_bags')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD max_allowed_bags INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'occupancy_percent')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD occupancy_percent DECIMAL(10,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'jam_duration')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD jam_duration DECIMAL(12,3) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'track_count')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD track_count INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'track_ids_json')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD track_ids_json NVARCHAR(MAX) NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'roi_x1')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD roi_x1 INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'roi_y1')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD roi_y1 INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'roi_x2')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD roi_x2 INT NULL; END
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.roi_snapshots') AND name = 'roi_y2')
    BEGIN ALTER TABLE dbo.roi_snapshots ADD roi_y2 INT NULL; END
    """,

    # ======================================================
    # JAM PAIR MEASUREMENTS
    #
    # Individual bag-to-bag spacing measurements (Condition B
    # `distances`/`pairs`/`jam_pairs`, Condition C `distances`).
    # These are per-event arrays and do not belong flattened
    # into jam_events/roi_snapshots columns -- one child row
    # per measured pair instead.
    # ======================================================

    """
    IF OBJECT_ID('dbo.jam_pair_measurements', 'U') IS NULL
    BEGIN
        CREATE TABLE dbo.jam_pair_measurements (
            id BIGINT IDENTITY(1,1) PRIMARY KEY,
            jam_event_id BIGINT NULL,
            snapshot_id BIGINT NULL,
            camera_id NVARCHAR(100) NOT NULL,
            front_track_id BIGINT,
            rear_track_id BIGINT,
            distance_mm DECIMAL(12,3),
            distance_px DECIMAL(12,3),
            threshold_mm DECIMAL(12,3),
            minimum_safe_gap_mm DECIMAL(12,3),
            measurement_margin_mm DECIMAL(12,3),
            jam_detected BIT,
            status NVARCHAR(30),
            front_center_x DECIMAL(12,3),
            front_center_y DECIMAL(12,3),
            rear_center_x DECIMAL(12,3),
            rear_center_y DECIMAL(12,3),
            front_bbox_json NVARCHAR(MAX),
            rear_bbox_json NVARCHAR(MAX),
            created_at DATETIMEOFFSET NOT NULL,

            CONSTRAINT FK_pair_jam_event
                FOREIGN KEY (jam_event_id)
                REFERENCES dbo.jam_events(id),

            CONSTRAINT FK_pair_snapshot
                FOREIGN KEY (snapshot_id)
                REFERENCES dbo.roi_snapshots(id)
        );
    END
    """,

    """
    IF OBJECT_ID('dbo.jam_pair_measurements', 'U') IS NOT NULL
       AND NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = 'idx_pair_jam_event'
              AND object_id = OBJECT_ID('dbo.jam_pair_measurements')
       )
    BEGIN
        CREATE INDEX idx_pair_jam_event
        ON dbo.jam_pair_measurements(jam_event_id);
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