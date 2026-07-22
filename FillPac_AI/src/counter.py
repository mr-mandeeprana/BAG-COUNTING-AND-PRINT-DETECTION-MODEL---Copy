"""
==========================================================
FillPac AI
Physical Bag Center Counter
==========================================================

Purpose
-------
Counts physical bags crossing a configured horizontal line.

Counting is based on:
- Bag bounding-box center
- Crossing direction
- Track stability
- Minimum crossing distance
- Spatial duplicate suppression
- Time-based duplicate suppression

Important
---------
Track IDs are used only to maintain movement history.

The actual count event is based on the physical bag center
crossing the counting line.

If ByteTrack changes the track ID near the counting line,
duplicate_distance + duplicate_time help prevent the same
physical bag from being counted twice.
==========================================================
"""

import math
import time


class Counter:

    def __init__(
        self,
        roi_y,
        direction="down",
        duplicate_distance=40,
        duplicate_time=0.8,
        max_history=200,
        line_tolerance=20,
        late_start_margin=40,
        min_track_frames=4,
        stale_track_frames=120,
        minimum_cross_distance=0,
    ):

        # ==================================================
        # COUNTING LINE
        # ==================================================

        self.roi_y = int(
            roi_y
        )

        self.direction = str(
            direction
        ).lower()

        if self.direction not in {
            "up",
            "down",
            "both",
        }:

            raise ValueError(
                "Counter direction must be "
                "'up', 'down', or 'both'."
            )

        # ==================================================
        # DUPLICATE PROTECTION
        # ==================================================

        self.duplicate_distance = max(
            float(
                duplicate_distance
            ),
            0.0,
        )

        self.duplicate_time = max(
            float(
                duplicate_time
            ),
            0.0,
        )

        # ==================================================
        # TRACK HISTORY CONFIGURATION
        # ==================================================

        self.max_history = max(
            int(
                max_history
            ),
            1,
        )

        self.line_tolerance = max(
            int(
                line_tolerance
            ),
            0,
        )

        self.late_start_margin = max(
            int(
                late_start_margin
            ),
            0,
        )

        self.min_track_frames = max(
            int(
                min_track_frames
            ),
            1,
        )

        self.stale_track_frames = max(
            int(
                stale_track_frames
            ),
            1,
        )

        self.minimum_cross_distance = max(
            int(
                minimum_cross_distance
            ),
            0,
        )

        # ==================================================
        # TOTAL COUNT
        # ==================================================

        self.total_count = 0

        # ==================================================
        # CURRENT FRAME COUNT EVENTS
        # ==================================================

        self.last_count_center = None

        self.last_counted_bags = []

        # ==================================================
        # TRACK STATE
        # ==================================================

        self.track_centers = {}

        self.track_previous_centers = {}

        self.track_zones = {}

        self.track_start_zones = {}

        self.track_start_centers = {}

        self.track_states = {}

        self.track_frame_count = {}

        self.track_last_seen = {}

        # Prevent the same active Track ID
        # from being counted more than once.
        self.counted_track_ids = set()

        # ==================================================
        # PHYSICAL BAG DUPLICATE HISTORY
        #
        # Each item:
        #
        # {
        #     "center": (x, y),
        #     "timestamp": monotonic_time,
        #     "track_id": id
        # }
        #
        # This protects against ByteTrack assigning a new
        # track ID to the same physical bag near the line.
        # ==================================================

        self.recent_counts = []

        # ==================================================
        # FRAME INDEX
        # ==================================================

        self.frame_index = 0

    # ======================================================
    # GET BOUNDING BOX CENTER
    # ======================================================

    @staticmethod
    def get_center(
        bbox,
    ):

        x1, y1, x2, y2 = bbox

        center_x = int(
            (
                x1
                + x2
            )
            / 2
        )

        center_y = int(
            (
                y1
                + y2
            )
            / 2
        )

        return (
            center_x,
            center_y,
        )

    # ======================================================
    # UPDATE
    # ======================================================

    def update(
        self,
        tracks,
    ):

        self.frame_index += 1

        self.last_count_center = None

        self.last_counted_bags = []

        active_track_ids = set()

        # Current monotonic time for duplicate checks.
        current_time = time.monotonic()

        # Remove expired physical count records.
        self._trim_recent_counts(
            current_time
        )

        # ==================================================
        # PROCESS TRACKS
        # ==================================================

        for track in tracks:

            # ----------------------------------------------
            # Only count Bag class
            # ----------------------------------------------

            if track.get(
                "class_id"
            ) != 0:

                continue

            # ----------------------------------------------
            # Track ID
            # ----------------------------------------------

            track_id = track.get(
                "track_id"
            )

            if track_id is None:

                continue

            active_track_ids.add(
                track_id
            )

            # ----------------------------------------------
            # Track frame count
            # ----------------------------------------------

            self.track_frame_count[
                track_id
            ] = (

                self.track_frame_count.get(
                    track_id,
                    0,
                )

                + 1
            )

            # ----------------------------------------------
            # Track last seen
            # ----------------------------------------------

            self.track_last_seen[
                track_id
            ] = self.frame_index

            # ----------------------------------------------
            # Physical center
            # ----------------------------------------------

            center = self.get_center(
                track[
                    "bbox"
                ]
            )

            # ----------------------------------------------
            # Previous center / zone
            # ----------------------------------------------

            previous_center = (
                self.track_centers.get(
                    track_id
                )
            )

            previous_zone = (
                self.track_zones.get(
                    track_id
                )
            )

            current_zone = (
                self._get_zone(
                    center[
                        1
                    ]
                )
            )

            # ----------------------------------------------
            # Track starting state
            # ----------------------------------------------

            self.track_start_zones.setdefault(
                track_id,
                current_zone,
            )

            self.track_start_centers.setdefault(
                track_id,
                center,
            )

            # ----------------------------------------------
            # Store previous center
            # ----------------------------------------------

            if previous_center is not None:

                self.track_previous_centers[
                    track_id
                ] = previous_center

            # ----------------------------------------------
            # Update center
            # ----------------------------------------------

            self.track_centers[
                track_id
            ] = center

            # ----------------------------------------------
            # Update zone
            # ----------------------------------------------

            self._update_track_zone(
                track_id,
                previous_zone,
                current_zone,
            )

            # ----------------------------------------------
            # Count decision
            # ----------------------------------------------

            if self._should_count(
                track_id=track_id,
                bbox=track[
                    "bbox"
                ],
                center=center,
                previous_center=
                    previous_center,
                previous_zone=
                    previous_zone,
                current_zone=
                    current_zone,
                current_time=
                    current_time,
            ):

                self._register_count(
                    track_id=
                        track_id,
                    bbox=
                        track[
                            "bbox"
                        ],
                    center=
                        center,
                    timestamp=
                        current_time,
                )

        # ==================================================
        # CLEAN OLD TRACK HISTORY
        # ==================================================

        self._trim_history(
            active_track_ids
        )

        return self.total_count

    # ======================================================
    # REGISTER COUNT
    # ======================================================

    def _register_count(
        self,
        track_id,
        bbox,
        center,
        timestamp,
    ):

        self.total_count += 1

        # ----------------------------------------------
        # Track ID deduplication
        # ----------------------------------------------

        self.counted_track_ids.add(
            track_id
        )

        # ----------------------------------------------
        # Last count center
        # ----------------------------------------------

        self.last_count_center = (
            center
        )

        # ----------------------------------------------
        # Current frame events
        # ----------------------------------------------

        self.last_counted_bags.append(
            {
                "track_id":
                    track_id,

                "bbox":
                    bbox,

                "center":
                    center,
            }
        )

        # ----------------------------------------------
        # Track state
        # ----------------------------------------------

        self.track_states[
            track_id
        ] = "COUNTED"

        # ----------------------------------------------
        # Physical bag duplicate history
        # ----------------------------------------------

        self.recent_counts.append(
            {
                "center":
                    center,

                "timestamp":
                    timestamp,

                "track_id":
                    track_id,
            }
        )

    # ======================================================
    # SHOULD COUNT
    # ======================================================

    def _should_count(
        self,
        track_id,
        bbox,
        center,
        previous_center,
        previous_zone,
        current_zone,
        current_time,
    ):

        # ----------------------------------------------
        # Track stability
        # ----------------------------------------------

        if not self._is_stable(
            track_id
        ):

            self._advance_state(
                track_id,
                "BEFORE_LINE",
            )

            return False

        # ----------------------------------------------
        # Duplicate protection
        # ----------------------------------------------

        if not self._can_count(
            track_id,
            center,
            current_time,
        ):

            return False

        # ----------------------------------------------
        # Movement direction
        # ----------------------------------------------

        if not self._is_moving_in_count_direction(
            previous_center,
            center,
        ):

            return False

        # ----------------------------------------------
        # Bounding box reaches line
        # ----------------------------------------------

        bbox_cross = (
            self._bbox_reached_roi(
                previous_zone,
                bbox,
            )
        )

        # ----------------------------------------------
        # Physical center crosses line
        # ----------------------------------------------

        center_cross = (
            self._center_crossed_roi(
                previous_center,
                center,
            )
        )

        # ----------------------------------------------
        # State progression
        # ----------------------------------------------

        if bbox_cross:

            self._advance_state(
                track_id,
                "ENTERING_ROI",
            )

        if center_cross:

            self._advance_state(
                track_id,
                "CENTER_CROSSED",
            )

        # ----------------------------------------------
        # Standard crossing
        # ----------------------------------------------

        if (
            bbox_cross
            and center_cross
        ):

            return (
                self._has_minimum_cross_distance(
                    center[
                        1
                    ]
                )
            )

        # ----------------------------------------------
        # Previously crossed but waiting for
        # minimum crossing distance
        # ----------------------------------------------

        if self._is_confirmed_pending_crossing(
            track_id,
            bbox,
            center,
            current_zone,
        ):

            return True

        # ----------------------------------------------
        # Late-start recovery
        #
        # Useful when tracking begins very close to
        # or slightly after the counting line.
        # ----------------------------------------------

        if self._is_valid_late_start(
            track_id,
            bbox,
            center,
            current_zone,
        ):

            self._advance_state(
                track_id,
                "CENTER_CROSSED",
            )

            return (
                self._has_minimum_cross_distance(
                    center[
                        1
                    ]
                )
            )

        return False

    # ======================================================
    # TRACK STABILITY
    # ======================================================

    def _is_stable(
        self,
        track_id,
    ):

        return (

            self.track_frame_count.get(
                track_id,
                0,
            )

            >= self.min_track_frames
        )

    # ======================================================
    # CAN COUNT
    # ======================================================

    def _can_count(
        self,
        track_id,
        center,
        current_time,
    ):

        # ----------------------------------------------
        # Same Track ID already counted
        # ----------------------------------------------

        if track_id in self.counted_track_ids:

            return False

        # ----------------------------------------------
        # Physical duplicate detection
        #
        # A detection is considered a duplicate only when:
        #
        # 1. It happens within duplicate_time seconds.
        # 2. Its physical center is within
        #    duplicate_distance pixels.
        #
        # This handles tracker ID changes near the line.
        # ----------------------------------------------

        for item in self.recent_counts:

            elapsed_time = (

                current_time

                - item[
                    "timestamp"
                ]
            )

            if elapsed_time > self.duplicate_time:

                continue

            previous_center = item[
                "center"
            ]

            distance = math.hypot(

                previous_center[
                    0
                ]
                - center[
                    0
                ],

                previous_center[
                    1
                ]
                - center[
                    1
                ],
            )

            if (
                distance
                <= self.duplicate_distance
            ):

                return False

        return True

    # ======================================================
    # ADVANCE TRACK STATE
    # ======================================================

    def _advance_state(
        self,
        track_id,
        state,
    ):

        if (
            self.track_states.get(
                track_id
            )
            == "COUNTED"
        ):

            return

        state_rank = {

            "NEW":
                0,

            "BEFORE_LINE":
                1,

            "ENTERING_ROI":
                2,

            "CENTER_CROSSED":
                3,

            "COUNTED":
                4,
        }

        current_state = (

            self.track_states.get(
                track_id,
                "NEW",
            )
        )

        if (

            state_rank[
                state
            ]

            >= state_rank[
                current_state
            ]

        ):

            self.track_states[
                track_id
            ] = state

    # ======================================================
    # MOVEMENT DIRECTION
    # ======================================================

    def _is_moving_in_count_direction(
        self,
        previous_center,
        center,
    ):

        if previous_center is None:

            return False

        dy = (

            center[
                1
            ]

            - previous_center[
                1
            ]
        )

        if self.direction == "up":

            return dy < 0

        if self.direction == "both":

            return dy != 0

        return dy > 0

    # ======================================================
    # CENTER CROSSED ROI
    # ======================================================

    def _center_crossed_roi(
        self,
        previous_center,
        center,
    ):

        if previous_center is None:

            return False

        previous_y = (
            previous_center[
                1
            ]
        )

        center_y = (
            center[
                1
            ]
        )

        if self.direction == "up":

            return (

                previous_y
                > self.roi_y

                and center_y
                <= self.roi_y
            )

        if self.direction == "both":

            return (

                (
                    previous_y
                    < self.roi_y

                    and center_y
                    >= self.roi_y
                )

                or

                (
                    previous_y
                    > self.roi_y

                    and center_y
                    <= self.roi_y
                )
            )

        return (

            previous_y
            < self.roi_y

            and center_y
            >= self.roi_y
        )

    # ======================================================
    # BBOX REACHED ROI
    # ======================================================

    def _bbox_reached_roi(
        self,
        previous_zone,
        bbox,
    ):

        if previous_zone is None:

            return False

        _, y1, _, y2 = bbox

        if self.direction == "up":

            return (

                previous_zone
                == "below"

                and y1
                <= (
                    self.roi_y
                    + self.line_tolerance
                )
            )

        if self.direction == "both":

            return (

                (
                    previous_zone
                    == "above"

                    and y2
                    >= (
                        self.roi_y
                        - self.line_tolerance
                    )
                )

                or

                (
                    previous_zone
                    == "below"

                    and y1
                    <= (
                        self.roi_y
                        + self.line_tolerance
                    )
                )
            )

        return (

            previous_zone
            == "above"

            and y2
            >= (
                self.roi_y
                - self.line_tolerance
            )
        )

    # ======================================================
    # BBOX PAST ROI
    # ======================================================

    def _bbox_past_roi(
        self,
        bbox,
    ):

        _, y1, _, y2 = bbox

        if self.direction == "up":

            return (

                y1
                <= (
                    self.roi_y
                    + self.line_tolerance
                )
            )

        if self.direction == "both":

            return (

                y2
                >= (
                    self.roi_y
                    - self.line_tolerance
                )

                or

                y1
                <= (
                    self.roi_y
                    + self.line_tolerance
                )
            )

        return (

            y2
            >= (
                self.roi_y
                - self.line_tolerance
            )
        )

    # ======================================================
    # GET ZONE
    # ======================================================

    def _get_zone(
        self,
        center_y,
    ):

        if (

            center_y
            < (
                self.roi_y
                - self.line_tolerance
            )

        ):

            return "above"

        if (

            center_y
            > (
                self.roi_y
                + self.line_tolerance
            )

        ):

            return "below"

        return "line"

    # ======================================================
    # VALID LATE START
    # ======================================================

    def _is_valid_late_start(
        self,
        track_id,
        bbox,
        center,
        current_zone,
    ):

        start_zone = (

            self.track_start_zones.get(
                track_id
            )
        )

        start_center = (

            self.track_start_centers.get(
                track_id,
                center,
            )
        )

        if self.direction == "up":

            started_after_line = (

                start_zone
                == "above"

                or start_center[
                    1
                ]
                <= self.roi_y
            )

        elif self.direction == "both":

            started_after_line = (

                start_zone
                in {
                    "above",
                    "below",
                }
            )

        else:

            started_after_line = (

                start_zone
                == "below"

                or start_center[
                    1
                ]
                >= self.roi_y
            )

        return (

            started_after_line

            and self._bbox_past_roi(
                bbox
            )

            and self._center_past_roi(
                center[
                    1
                ],
                current_zone,
            )

            and self._inside_late_start_margin(
                center[
                    1
                ],
                current_zone,
            )
        )

    # ======================================================
    # CENTER PAST ROI
    # ======================================================

    def _center_past_roi(
        self,
        center_y,
        current_zone,
    ):

        if self.direction == "up":

            return (

                current_zone
                == "above"

                or center_y
                <= self.roi_y
            )

        if self.direction == "both":

            return (

                current_zone
                != "line"
            )

        return (

            current_zone
            == "below"

            or center_y
            >= self.roi_y
        )

    # ======================================================
    # CONFIRMED PENDING CROSSING
    # ======================================================

    def _is_confirmed_pending_crossing(
        self,
        track_id,
        bbox,
        center,
        current_zone,
    ):

        return (

            self.track_states.get(
                track_id
            )
            == "CENTER_CROSSED"

            and self._bbox_past_roi(
                bbox
            )

            and self._center_past_roi(
                center[
                    1
                ],
                current_zone,
            )

            and self._has_minimum_cross_distance(
                center[
                    1
                ]
            )
        )

    # ======================================================
    # MINIMUM CROSS DISTANCE
    # ======================================================

    def _has_minimum_cross_distance(
        self,
        center_y,
    ):

        if self.minimum_cross_distance <= 0:

            return True

        if self.direction == "up":

            return (

                self.roi_y
                - center_y

                >= self.minimum_cross_distance
            )

        if self.direction == "both":

            return (

                abs(
                    center_y
                    - self.roi_y
                )

                >= self.minimum_cross_distance
            )

        return (

            center_y
            - self.roi_y

            >= self.minimum_cross_distance
        )

    # ======================================================
    # LATE START MARGIN
    # ======================================================

    def _inside_late_start_margin(
        self,
        center_y,
        current_zone,
    ):

        if self.direction == "up":

            return (

                current_zone
                == "above"

                and center_y
                >= (
                    self.roi_y
                    - self.line_tolerance
                    - self.late_start_margin
                )
            )

        if self.direction == "both":

            return (

                current_zone
                != "line"

                and abs(
                    center_y
                    - self.roi_y
                )

                <= (
                    self.line_tolerance
                    + self.late_start_margin
                )
            )

        return (

            current_zone
            == "below"

            and center_y
            <= (
                self.roi_y
                + self.line_tolerance
                + self.late_start_margin
            )
        )

    # ======================================================
    # UPDATE TRACK ZONE
    # ======================================================

    def _update_track_zone(
        self,
        track_id,
        previous_zone,
        current_zone,
    ):

        if current_zone == "line":

            if previous_zone is None:

                if self.direction == "up":

                    self.track_zones[
                        track_id
                    ] = "below"

                else:

                    self.track_zones[
                        track_id
                    ] = "above"

            else:

                self.track_zones[
                    track_id
                ] = previous_zone

            return

        self.track_zones[
            track_id
        ] = current_zone

    # ======================================================
    # TRIM RECENT PHYSICAL COUNTS
    # ======================================================

    def _trim_recent_counts(
        self,
        current_time,
    ):

        if self.duplicate_time <= 0:

            self.recent_counts = []

            return

        self.recent_counts = [

            item

            for item
            in self.recent_counts

            if (

                current_time
                - item[
                    "timestamp"
                ]

                <= self.duplicate_time
            )
        ]

    # ======================================================
    # TRIM TRACK HISTORY
    # ======================================================

    def _trim_history(
        self,
        active_track_ids,
    ):

        fresh_ids = {

            track_id

            for (
                track_id,
                last_seen,
            )

            in self.track_last_seen.items()

            if (

                self.frame_index
                - last_seen

                <= self.stale_track_frames
            )
        }

        recent_ids = sorted(

            fresh_ids,

            key=lambda track_id:

                self.track_last_seen.get(
                    track_id,
                    0,
                ),

            reverse=True,
        )

        retained_ids = []

        for track_id in (

            list(
                active_track_ids
            )

            + recent_ids

        ):

            if track_id not in retained_ids:

                retained_ids.append(
                    track_id
                )

            if (

                len(
                    retained_ids
                )

                >= self.max_history

            ):

                break

        retained_set = set(
            retained_ids
        )

        # ----------------------------------------------
        # Centers
        # ----------------------------------------------

        self.track_centers = {

            track_id:
                center

            for (
                track_id,
                center,
            )

            in self.track_centers.items()

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Previous Centers
        # ----------------------------------------------

        self.track_previous_centers = {

            track_id:
                center

            for (
                track_id,
                center,
            )

            in self.track_previous_centers.items()

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Zones
        # ----------------------------------------------

        self.track_zones = {

            track_id:
                zone

            for (
                track_id,
                zone,
            )

            in self.track_zones.items()

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Start Zones
        # ----------------------------------------------

        self.track_start_zones = {

            track_id:
                zone

            for (
                track_id,
                zone,
            )

            in self.track_start_zones.items()

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Start Centers
        # ----------------------------------------------

        self.track_start_centers = {

            track_id:
                center

            for (
                track_id,
                center,
            )

            in self.track_start_centers.items()

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Counted Track IDs
        # ----------------------------------------------

        self.counted_track_ids = {

            track_id

            for track_id
            in self.counted_track_ids

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Track States
        # ----------------------------------------------

        self.track_states = {

            track_id:
                state

            for (
                track_id,
                state,
            )

            in self.track_states.items()

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Frame Counts
        # ----------------------------------------------

        self.track_frame_count = {

            track_id:
                frame_count

            for (
                track_id,
                frame_count,
            )

            in self.track_frame_count.items()

            if track_id
            in retained_set
        }

        # ----------------------------------------------
        # Last Seen
        # ----------------------------------------------

        self.track_last_seen = {

            track_id:
                frame_index

            for (
                track_id,
                frame_index,
            )

            in self.track_last_seen.items()

            if track_id
            in retained_set
        }