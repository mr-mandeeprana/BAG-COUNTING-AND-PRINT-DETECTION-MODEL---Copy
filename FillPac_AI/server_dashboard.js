/*
==========================================================
FillPac AI
Dashboard Frontend
==========================================================
*/

"use strict";


/* ==========================================================
   CONFIGURATION
   ========================================================== */

const API_BASE = "http://127.0.0.1:8000";

const REFRESH_INTERVAL_MS = 5000;

const CAMERA_COUNT = 4;


/* ==========================================================
   APPLICATION STATE
   ========================================================== */

const appState = {

    currentPage: "dashboard",

    dashboardState: null,

    cameras: {},

    socket: null,

    socketConnected: false,

    lastStateUpdate: null,

    refreshTimer: null,

    events: [],

    analytics: null,

    production: null,

    cameraConfig: null
};


/* ==========================================================
   PAGE INFORMATION
   ========================================================== */

const PAGE_INFO = {

    dashboard: {
        title: "Dashboard",
        subtitle: "Real-time FillPac AI production overview"
    },

    "live-monitor": {
        title: "Live Monitor",
        subtitle: "Real-time camera streams and AI inspection"
    },

    production: {
        title: "Production",
        subtitle: "Production counts and print inspection performance"
    },

    analytics: {
        title: "Analytics",
        subtitle: "Production analytics and camera performance"
    },

    events: {
        title: "Events",
        subtitle: "Search and export persisted production events"
    },

    "jam-monitor": {
        title: "Jam Monitoring",
        subtitle: "Real-time conveyor motion and bag jam detection"
    },

    cameras: {
        title: "Cameras",
        subtitle: "Camera configuration and runtime status"
    },

    settings: {
        title: "Settings",
        subtitle: "FillPac AI dashboard settings"
    }
};


/* ==========================================================
   JAM STATES
   ========================================================== */

const JAM_STATES = [
    "normal",
    "slow",
    "warning",
    "jam",
    "recovering",
    "disabled",
    "unknown"
];


/* ==========================================================
   DOM HELPERS
   ========================================================== */

function byId(id) {

    return document.getElementById(id);
}


function setText(id, value) {

    const element = byId(id);

    if (!element) {
        return;
    }

    element.textContent =
        value ?? "--";
}


function safeNumber(
    value,
    fallback = 0
) {

    const number = Number(value);

    return Number.isFinite(number)
        ? number
        : fallback;
}


function formatInteger(value) {

    return Math.round(
        safeNumber(value, 0)
    ).toLocaleString();
}


function formatDecimal(
    value,
    digits = 1
) {

    return safeNumber(
        value,
        0
    ).toFixed(digits);
}


function formatPercent(value) {

    return `${formatDecimal(value, 1)}%`;
}


function formatRoiBagDetail(bags) {

    const list =
        Array.isArray(bags)
            ? bags
            : [];

    if (list.length === 0) {
        return "--";
    }

    return list
        .map(
            bag => {

                const trackId =
                    bag?.track_id
                    ??
                    "?";

                const center =
                    Array.isArray(bag?.center)
                        ? bag.center
                        : null;

                if (!center) {
                    return `${trackId}`;
                }

                const x =
                    Math.round(
                        safeNumber(center[0], 0)
                    );

                const y =
                    Math.round(
                        safeNumber(center[1], 0)
                    );

                return `${trackId} @ (${x}, ${y})`;
            }
        )
        .join(", ");
}


function formatUptime(totalSeconds) {

    const seconds =
        Math.max(
            0,
            Math.floor(
                safeNumber(totalSeconds, 0)
            )
        );

    const hours =
        Math.floor(seconds / 3600);

    const minutes =
        Math.floor((seconds % 3600) / 60);

    const secs =
        seconds % 60;

    const pad =
        value => String(value).padStart(2, "0");

    return `${pad(hours)}:${pad(minutes)}:${pad(secs)}`;
}


function escapeHtml(value) {

    return String(
        value ?? ""
    )
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* ==========================================================
   DATE / TIME HELPERS
   ========================================================== */

function parseDate(value) {

    if (!value) {
        return null;
    }

    const date = new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return null;
    }

    return date;
}


function formatDateTime(value) {

    const date = parseDate(value);

    if (!date) {
        return "--";
    }

    return date.toLocaleString();
}


function formatTime(value) {

    const date = parseDate(value);

    if (!date) {
        return "--";
    }

    return date.toLocaleTimeString();
}


/* ==========================================================
   CHART REGISTRY

   Chart.js is loaded globally (see index.html). Every chart on
   the dashboard is created once, lazily, the first time it has
   data to show, then updated in place on every subsequent
   refresh instead of being destroyed/recreated.
   ========================================================== */

const chartInstances = {};

const CHART_COLORS = {
    blue: "#1976d2",
    blueSoft: "rgba(25, 118, 210, 0.15)",
    success: "#16a34a",
    successSoft: "rgba(22, 163, 74, 0.15)",
    danger: "#dc2626",
    dangerSoft: "rgba(220, 38, 38, 0.15)",
    warning: "#f59e0b",
    grid: "rgba(0, 63, 70, 0.08)",
    text: "#005864"
};


function getOrCreateChart(
    canvasId,
    buildConfig
) {

    const canvas =
        byId(canvasId);

    if (!canvas) {
        return null;
    }

    if (
        typeof Chart === "undefined"
    ) {
        return null;
    }

    if (chartInstances[canvasId]) {
        return chartInstances[canvasId];
    }

    const config =
        buildConfig();

    chartInstances[canvasId] =
        new Chart(
            canvas,
            config
        );

    return chartInstances[canvasId];
}


function baseChartOptions(extra = {}) {

    return {

        responsive: true,

        maintainAspectRatio: false,

        plugins: {

            legend: {
                labels: {
                    color: CHART_COLORS.text
                }
            }
        },

        scales: {

            x: {
                ticks: { color: CHART_COLORS.text },
                grid: { color: CHART_COLORS.grid }
            },

            y: {
                beginAtZero: true,
                ticks: { color: CHART_COLORS.text },
                grid: { color: CHART_COLORS.grid }
            }
        },

        ...extra
    };
}


/* ----------------------------------------------------------
   DASHBOARD: PRODUCTION TREND (line chart, hourly totals)
   ---------------------------------------------------------- */

function updateProductionTrendChart(hourly) {

    const rows =
        Array.isArray(hourly)
            ? hourly
            : [];

    const labels =
        rows.map(row => row.hour);

    const totals =
        rows.map(
            row => safeNumber(row.total, 0)
        );

    const chart =
        getOrCreateChart(
            "productionChart",
            () => ({
                type: "line",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "Bags produced",
                            data: totals,
                            borderColor: CHART_COLORS.blue,
                            backgroundColor: CHART_COLORS.blueSoft,
                            fill: true,
                            tension: 0.35,
                            pointRadius: 2
                        }
                    ]
                },
                options: baseChartOptions({
                    scales: {
                        x: {
                            ticks: { color: CHART_COLORS.text },
                            grid: { display: false }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: { color: CHART_COLORS.text },
                            grid: { color: CHART_COLORS.grid }
                        }
                    }
                })
            })
        );

    if (!chart) {
        return;
    }

    chart.data.labels = labels;
    chart.data.datasets[0].data = totals;
    chart.update();
}


/* ----------------------------------------------------------
   DASHBOARD: PRINT INSPECTION (donut, printed vs missing)
   ---------------------------------------------------------- */

function updatePrintInspectionChart(printed, missing) {

    const chart =
        getOrCreateChart(
            "printChart",
            () => ({
                type: "doughnut",
                data: {
                    labels: ["Printed", "Not Printed"],
                    datasets: [
                        {
                            data: [printed, missing],
                            backgroundColor: [
                                CHART_COLORS.success,
                                CHART_COLORS.danger
                            ],
                            borderWidth: 0
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "65%",
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: { color: CHART_COLORS.text }
                        }
                    }
                }
            })
        );

    if (!chart) {
        return;
    }

    chart.data.datasets[0].data = [printed, missing];
    chart.update();
}


/* ----------------------------------------------------------
   ANALYTICS: HOURLY PRODUCTION (bar)
   ---------------------------------------------------------- */

function updateAnalyticsHourlyChart(hourly) {

    const rows =
        Array.isArray(hourly)
            ? hourly
            : [];

    const labels =
        rows.map(row => row.hour);

    const totals =
        rows.map(
            row => safeNumber(row.total, 0)
        );

    const printed =
        rows.map(
            row => safeNumber(row.printed, 0)
        );

    const missing =
        rows.map(
            row => safeNumber(row.missing, 0)
        );

    const chart =
        getOrCreateChart(
            "analyticsHourlyChart",
            () => ({
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "Printed",
                            data: printed,
                            backgroundColor: CHART_COLORS.success,
                            stack: "stack0"
                        },
                        {
                            label: "Missing",
                            data: missing,
                            backgroundColor: CHART_COLORS.danger,
                            stack: "stack0"
                        }
                    ]
                },
                options: baseChartOptions({
                    scales: {
                        x: {
                            stacked: true,
                            ticks: { color: CHART_COLORS.text },
                            grid: { display: false }
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            ticks: { color: CHART_COLORS.text },
                            grid: { color: CHART_COLORS.grid }
                        }
                    }
                })
            })
        );

    if (!chart) {
        return;
    }

    chart.data.labels = labels;
    chart.data.datasets[0].data = printed;
    chart.data.datasets[1].data = missing;
    chart.update();

    void totals;
}


/* ----------------------------------------------------------
   ANALYTICS: CAMERA COMPARISON (bar)
   ---------------------------------------------------------- */

function updateAnalyticsCameraChart(byCamera) {

    const rows =
        Array.isArray(byCamera)
            ? byCamera
            : [];

    const labels =
        rows.map(row => row.camera);

    const totals =
        rows.map(
            row => safeNumber(row.total, 0)
        );

    const chart =
        getOrCreateChart(
            "analyticsCameraChart",
            () => ({
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "Events",
                            data: totals,
                            backgroundColor: CHART_COLORS.blue
                        }
                    ]
                },
                options: baseChartOptions({
                    plugins: {
                        legend: { display: false }
                    }
                })
            })
        );

    if (!chart) {
        return;
    }

    chart.data.labels = labels;
    chart.data.datasets[0].data = totals;
    chart.update();
}


/* ----------------------------------------------------------
   ANALYTICS: PRINT INSPECTION ANALYTICS (donut, overall)
   ---------------------------------------------------------- */

function updateAnalyticsPrintChart(printed, missing) {

    const chart =
        getOrCreateChart(
            "analyticsPrintChart",
            () => ({
                type: "doughnut",
                data: {
                    labels: ["Printed", "Missing"],
                    datasets: [
                        {
                            data: [printed, missing],
                            backgroundColor: [
                                CHART_COLORS.success,
                                CHART_COLORS.danger
                            ],
                            borderWidth: 0
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "65%",
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: { color: CHART_COLORS.text }
                        }
                    }
                }
            })
        );

    if (!chart) {
        return;
    }

    chart.data.datasets[0].data = [printed, missing];
    chart.update();
}


/* ----------------------------------------------------------
   ANALYTICS: SHIFT PRODUCTION (bar)
   ---------------------------------------------------------- */

function updateAnalyticsShiftChart(byShift) {

    const rows =
        Array.isArray(byShift)
            ? byShift
            : [];

    const labelMap = {
        "shift-a": "Shift A",
        "shift-b": "Shift B",
        "shift-c": "Shift C",
        "unknown": "Unknown"
    };

    const labels =
        rows.map(
            row => labelMap[row.shift] || row.shift
        );

    const printed =
        rows.map(
            row => safeNumber(row.printed, 0)
        );

    const missing =
        rows.map(
            row => safeNumber(row.missing, 0)
        );

    const chart =
        getOrCreateChart(
            "analyticsShiftChart",
            () => ({
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "Printed",
                            data: printed,
                            backgroundColor: CHART_COLORS.success,
                            stack: "stack0"
                        },
                        {
                            label: "Missing",
                            data: missing,
                            backgroundColor: CHART_COLORS.danger,
                            stack: "stack0"
                        }
                    ]
                },
                options: baseChartOptions({
                    scales: {
                        x: {
                            stacked: true,
                            ticks: { color: CHART_COLORS.text },
                            grid: { display: false }
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            ticks: { color: CHART_COLORS.text },
                            grid: { color: CHART_COLORS.grid }
                        }
                    }
                })
            })
        );

    if (!chart) {
        return;
    }

    chart.data.labels = labels;
    chart.data.datasets[0].data = printed;
    chart.data.datasets[1].data = missing;
    chart.update();
}


/* ==========================================================
   API
   ========================================================== */

async function apiFetch(
    path,
    options = {}
) {

    const response =
        await fetch(
            `${API_BASE}${path}`,
            {
                cache: "no-store",
                ...options
            }
        );

    if (!response.ok) {

        throw new Error(
            `HTTP ${response.status}: ${path}`
        );
    }

    const contentType =
        response.headers.get(
            "content-type"
        ) || "";

    if (
        contentType.includes(
            "application/json"
        )
    ) {

        return await response.json();
    }

    return await response.text();
}


/* ==========================================================
   NAVIGATION
   ========================================================== */

function initializeNavigation() {

    const items =
        document.querySelectorAll(
            ".sidebar-item[data-page]"
        );

    items.forEach(
        item => {

            item.addEventListener(
                "click",
                async () => {

                    const page =
                        item.dataset.page;

                    if (!page) {
                        return;
                    }

                    await showPage(page);
                }
            );
        }
    );
}


async function showPage(page) {

    // ------------------------------------------------------
    // Validate page
    // ------------------------------------------------------

    if (!PAGE_INFO[page]) {

        console.warn(
            "Unknown dashboard page:",
            page
        );

        return;
    }


    // ------------------------------------------------------
    // Find requested page
    // ------------------------------------------------------

    const target =
        byId(`page-${page}`);


    if (!target) {

        console.error(
            `Dashboard page not found: page-${page}`
        );

        return;
    }


    // ------------------------------------------------------
    // Hide all pages
    // ------------------------------------------------------

    document
        .querySelectorAll(
            ".dashboard-page"
        )
        .forEach(
            element => {

                element.classList.remove(
                    "active-page"
                );
            }
        );


    // ------------------------------------------------------
    // Show selected page
    // ------------------------------------------------------

    target.classList.add(
        "active-page"
    );


    // ------------------------------------------------------
    // Update sidebar active button
    // ------------------------------------------------------

    document
        .querySelectorAll(
            ".sidebar-item[data-page]"
        )
        .forEach(
            item => {

                item.classList.toggle(
                    "active",
                    item.dataset.page === page
                );
            }
        );


    // ------------------------------------------------------
    // Store selected page
    // ------------------------------------------------------

    appState.currentPage =
        page;


    // ------------------------------------------------------
    // Update page heading
    // ------------------------------------------------------

    updatePageHeader(
        page
    );


    // ------------------------------------------------------
    // Load page data
    // ------------------------------------------------------

    try {

        await loadCurrentPage();

    }

    catch (error) {

        console.error(
            `Failed loading page "${page}":`,
            error
        );
    }
}


function updatePageHeader(page) {

    const info =
        PAGE_INFO[page]
        ||
        PAGE_INFO.dashboard;


    setText(
        "pageTitle",
        info.title
    );


    setText(
        "pageSubtitle",
        info.subtitle
    );
}


/* ==========================================================
   CURRENT PAGE LOADER
   ========================================================== */

async function loadCurrentPage() {

    try {

        switch (
            appState.currentPage
        ) {

            case "dashboard":

                await loadDashboardState();

                await loadAnalytics();

                break;


            case "live-monitor":

                await loadDashboardState();

                break;


            case "production":

                await loadProduction();

                break;


            case "analytics":

                await loadAnalytics();

                break;


            case "events":

                await loadEvents();

                break;


            case "jam-monitor":

                /*
                Fetch fresh state before rendering the
                dedicated jam monitoring page.
                */

                await loadDashboardState();

                renderJamMonitoring(
                    appState
                        .dashboardState
                        ?.cameras
                    || {}
                );

                break;


            case "cameras":

                await loadDashboardState();

                await loadCameraConfig();

                break;


            case "settings":

                await loadDashboardState();

                await loadSettings();

                break;


            default:

                await loadDashboardState();

                break;
        }

    }

    catch (error) {

        console.error(
            "Page load failed:",
            error
        );
    }
}


/* ==========================================================
   DASHBOARD STATE
   ========================================================== */

async function loadDashboardState() {

    try {

        const state =
            await apiFetch(
                "/state"
            );


        renderDashboardState(
            state
        );


        return state;

    }

    catch (error) {

        console.error(
            "Failed loading dashboard state:",
            error
        );


        updateSystemStatus(
            "offline"
        );


        throw error;
    }
}


/* ==========================================================
   RENDER DASHBOARD STATE
   ========================================================== */

function renderDashboardState(state) {

    if (
        !state
        ||
        typeof state !== "object"
    ) {
        return;
    }


    appState.dashboardState =
        state;


    appState.cameras =
        state.cameras || {};


    appState.lastStateUpdate =
        new Date();


    /* ------------------------------------------------------
       SYSTEM
       ------------------------------------------------------ */

    updateSystemStatus(
        state.system_status
        || "offline"
    );


    setText(
        "systemUptime",
        formatUptime(
            state.uptime_seconds
        )
    );


    /* ------------------------------------------------------
       MAIN COUNTS
       ------------------------------------------------------ */

    setText(
        "totalBags",
        formatInteger(
            state.total_count
        )
    );


    setText(
        "printedBags",
        formatInteger(
            state.total_printed_count
            ??
            state.total_printed_bags_count
            ??
            0
        )
    );


    setText(
        "missingBags",
        formatInteger(
            state.total_missing_count
            ??
            state.total_not_printed_bags_count
            ??
            0
        )
    );


    updatePrintInspectionChart(
        safeNumber(
            state.total_printed_count
            ??
            state.total_printed_bags_count
            ??
            0
        ),
        safeNumber(
            state.total_missing_count
            ??
            state.total_not_printed_bags_count
            ??
            0
        )
    );


    /* ------------------------------------------------------
       CAMERA CARDS
       ------------------------------------------------------ */

    renderCameraCards(
        state.cameras || {}
    );


    /* ------------------------------------------------------
       JAM MONITORING
       ------------------------------------------------------ */

    renderJamMonitoring(
        state.cameras || {}
    );


    /* ------------------------------------------------------
       DASHBOARD HEALTH
       ------------------------------------------------------ */

    renderDashboardHealthSummary(
        state
    );


    /* ------------------------------------------------------
       SERVICE HEALTH
       ------------------------------------------------------ */

    renderServiceHealth(
        state.service_status || {}
    );
}


/* ==========================================================
   SYSTEM STATUS
   ========================================================== */

function updateSystemStatus(status) {

    const normalized =
        String(
            status || "offline"
        )
            .trim()
            .toLowerCase();


    const statusElement =
        byId("systemStatus");


    if (statusElement) {

        statusElement.className =
            `system-status ${normalized}`;
    }


    const statusText =
        byId("systemStatusText");


    if (statusText) {

        statusText.textContent =
            normalized.toUpperCase();
    }


    const dot =
        byId("systemStatusDot");


    if (dot) {

        dot.className =
            `status-dot ${normalized}`;
    }
}


/* ==========================================================
   SERVICE HEALTH
   ========================================================== */

function renderServiceHealth(
    serviceStatus
) {

    const modelLoaded =
        Boolean(
            serviceStatus
                ?.model_loaded
        );


    const inferenceRunning =
        Boolean(
            serviceStatus
                ?.inference_manager_running
        );


    const elasticsearch =
        Boolean(
            serviceStatus
                ?.elasticsearch_connected
        );


    setText(
        "healthModel",
        modelLoaded
            ? "Loaded"
            : "Not Loaded"
    );


    setText(
        "healthInference",
        inferenceRunning
            ? "Running"
            : "Stopped"
    );


    setText(
        "healthElasticsearch",
        elasticsearch
            ? "Connected"
            : "Disconnected"
    );
}


/* ==========================================================
   CAMERA LOOKUP
   ========================================================== */

function findCameraByIndex(
    cameras,
    index
) {

    const entries =
        Object.entries(
            cameras || {}
        );


    const wanted =
        `camera${index}`
            .replaceAll(" ", "")
            .replaceAll("_", "")
            .toLowerCase();


    const direct =
        entries.find(
            ([key, camera]) => {

                const values = [
                    key,
                    camera?.camera_id,
                    camera?.camera_name,
                    camera?.name
                ];


                return values.some(
                    value => {

                        const normalized =
                            String(
                                value || ""
                            )
                                .replaceAll(
                                    " ",
                                    ""
                                )
                                .replaceAll(
                                    "_",
                                    ""
                                )
                                .toLowerCase();


                        return (
                            normalized
                            ===
                            wanted
                        );
                    }
                );
            }
        );


    if (direct) {

        return direct[1];
    }


    /*
    Fallback to insertion order if backend camera
    keys do not exactly match Camera1/Camera2/etc.
    */

    return (
        entries[
            index - 1
        ]?.[1]
        ||
        null
    );
}


/* ==========================================================
   CAMERA CARDS
   ========================================================== */

function renderCameraCards(cameras) {

    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        renderCameraCard(
            index,
            camera
        );
    }
}


function renderCameraCard(
    index,
    camera
) {

    if (!camera) {

        setText(
            `camera${index}Count`,
            "0"
        );


        setText(
            `camera${index}Printed`,
            "0"
        );


        setText(
            `camera${index}Missing`,
            "0"
        );


        setText(
            `camera${index}RoiCount`,
            "0"
        );


        setText(
            `camera${index}RoiActive`,
            "0"
        );


        setText(
            `camera${index}RoiTracks`,
            "--"
        );


        setText(
            `camera${index}Fps`,
            "0.0"
        );


        setText(
            `camera${index}Status`,
            "OFFLINE"
        );


        return;
    }


    const count =
        camera.count
        ??
        camera.total_count
        ??
        0;


    const entryRoiCount =
        camera.entry_roi_count
        ??
        0;


    const entryRoiActiveCount =
        camera.entry_roi_active_count
        ??
        0;


    const entryRoiActiveBags =
        camera.entry_roi_active_bags
        ??
        [];


    const printed =
        camera.printed_count
        ??
        camera.printed_bags_count
        ??
        0;


    const missing =
        camera.missing_count
        ??
        camera.not_printed_bags_count
        ??
        0;


    setText(
        `camera${index}Count`,
        formatInteger(count)
    );


    setText(
        `camera${index}RoiCount`,
        formatInteger(entryRoiCount)
    );


    setText(
        `camera${index}RoiActive`,
        formatInteger(entryRoiActiveCount)
    );


    setText(
        `camera${index}RoiTracks`,
        formatRoiBagDetail(entryRoiActiveBags)
    );


    setText(
        `camera${index}Printed`,
        formatInteger(printed)
    );


    setText(
        `camera${index}Missing`,
        formatInteger(missing)
    );


    setText(
        `camera${index}Fps`,
        formatDecimal(
            camera.fps,
            1
        )
    );


    setText(
        `camera${index}Status`,
        String(
            camera.status
            || "offline"
        ).toUpperCase()
    );
}


/* ==========================================================
   JAM STATUS NORMALIZATION
   ========================================================== */

function normalizeJamStatus(camera) {

    if (
        !camera
        ||
        typeof camera
        !== "object"
    ) {

        return "unknown";
    }


    const enabled =
        camera.jam_detection_enabled;


    if (
        enabled === false
        ||
        enabled === 0
        ||
        enabled === "false"
    ) {

        return "disabled";
    }


    /*
    Explicit confirmed jam takes highest priority.
    */

    if (
        camera.jam_detected
        === true
    ) {

        return "jam";
    }


    /*
    Explicit warning takes priority over textual status.
    */

    if (
        camera.jam_warning
        === true
    ) {

        return "warning";
    }


    const raw =
        String(
            camera.jam_status
            || "normal"
        )
            .trim()
            .toLowerCase()
            .replaceAll(
                "_",
                "-"
            );


    if (
        raw === "jam"
        ||
        raw === "jammed"
    ) {

        return "jam";
    }


    if (
        raw === "warning"
    ) {

        return "warning";
    }


    if (
        raw === "slow"
    ) {

        return "slow";
    }


    if (
        raw === "recovering"
        ||
        raw === "recovery"
    ) {

        return "recovering";
    }


    if (
        raw === "disabled"
    ) {

        return "disabled";
    }


    if (
        raw === "normal"
    ) {

        return "normal";
    }


    return "unknown";
}


/* ==========================================================
   JAM BADGE
   ========================================================== */

function setJamBadge(
    element,
    status
) {

    if (!element) {
        return;
    }


    const normalized =
        JAM_STATES.includes(
            status
        )
            ? status
            : "unknown";


    JAM_STATES.forEach(
        state => {

            element.classList.remove(
                state
            );
        }
    );


    element.classList.add(
        normalized
    );


    element.textContent =
        normalized.toUpperCase();
}


/* ==========================================================
   JAM MONITORING
   ========================================================== */

function renderJamMonitoring(cameras) {

    let normalCount = 0;

    let slowCount = 0;

    let warningCount = 0;

    let activeJamCount = 0;


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        const enabled =
            Boolean(
                camera
                    ?.jam_detection_enabled
            );


        const status =
            camera
                ? normalizeJamStatus(
                    camera
                )
                : "disabled";


        const cameraJamCount =
            Math.max(
                0,
                Math.round(
                    safeNumber(
                        camera
                            ?.active_jam_count,
                        0
                    )
                )
            );


        const trackIds =
            Array.isArray(
                camera
                    ?.condition_c_track_ids
            )
                ? camera
                    .condition_c_track_ids
                : (
                    Array.isArray(
                        camera
                            ?.active_jam_track_ids
                    )
                        ? camera
                            .active_jam_track_ids
                        : []
                );


        /* --------------------------------------------------
           CONDITION C (ROI OCCUPANCY) FIELDS
           -------------------------------------------------- */

        const roiBagCount =
            safeNumber(
                camera
                    ?.condition_c_bag_count,
                0
            );

        const roiGap =
            camera
                ?.condition_c_minimum_gap_mm;

        const roiDistances =
            camera
                ?.condition_c_distances
            || [];

        const roiImage =
            camera
                ?.condition_c_image_url
            ||
            camera
                ?.condition_c_image_path;

        const roiStatus =
            camera
                ?.condition_c_status
            ||
            (
                camera
                    ?.condition_c_detected
                    ? "jam"
                    : "normal"
            );


        /* --------------------------------------------------
           SYSTEM JAM COUNTERS
           -------------------------------------------------- */

        if (enabled) {

            if (
                status === "normal"
            ) {

                normalCount += 1;
            }


            else if (
                status === "slow"
            ) {

                slowCount += 1;
            }


            else if (
                status === "warning"
            ) {

                warningCount += 1;
            }


            else if (
                status === "jam"
            ) {

                activeJamCount +=
                    cameraJamCount > 0
                        ? cameraJamCount
                        : 1;
            }
        }


        /* --------------------------------------------------
           DASHBOARD CAMERA JAM BADGE
           -------------------------------------------------- */

        const summaryBadge =
            byId(
                `camera${index}JamStatus`
            );


        setJamBadge(
            summaryBadge,
            status
        );


        const dashboardCard =
            byId(
                `camera-card-${index}`
            )
            ||
            summaryBadge
                ?.closest(
                    ".camera-card"
                );


        if (dashboardCard) {

            dashboardCard
                .classList
                .toggle(
                    "jam-active",
                    status === "jam"
                );
        }


        /* --------------------------------------------------
           DEDICATED JAM PAGE
           -------------------------------------------------- */

        const jamBadge =
            byId(
                `jamCamera${index}Status`
            );


        setJamBadge(
            jamBadge,
            status
        );


        setText(
            `jamCamera${index}Count`,
            formatInteger(
                cameraJamCount
            )
        );


        setText(
            `jamCamera${index}RoiBags`,
            formatInteger(
                roiBagCount
            )
        );


        setText(
            `jamCamera${index}MinimumGap`,
            roiGap == null
                ? "--"
                : `${formatDecimal(roiGap, 1)} mm`
        );


        const distanceElement =
            byId(
                `jamCamera${index}Distances`
            );

        if (distanceElement) {

            distanceElement.innerHTML =
                roiDistances.length
                    ? roiDistances
                        .map(
                            d => `${formatDecimal(d?.distance_mm, 1)} mm`
                        )
                        .join("<br>")
                    : "--";
        }


        const roiImageElement =
            byId(
                `jamCamera${index}Image`
            );

        if (roiImageElement) {

            roiImageElement.src =
                roiImage
                    ? `${roiImage}?t=${Date.now()}`
                    : "";
        }


        setText(
            `jamCamera${index}ConditionC`,
            roiStatus.toUpperCase()
        );


        setText(
            `camera${index}ConditionC`,
            roiStatus.toUpperCase()
        );


        setText(
            `jamCamera${index}Tracks`,
            trackIds.length > 0
                ? trackIds.join(", ")
                : "--"
        );


        setText(
            `jamCamera${index}Enabled`,
            enabled
                ? "Enabled"
                : "Disabled"
        );


        const jamCard =
            byId(
                `jam-camera-card-${index}`
            );


        if (jamCard) {

            JAM_STATES.forEach(
                state => {

                    jamCard
                        .classList
                        .remove(
                            state
                        );
                }
            );


            jamCard
                .classList
                .add(
                    status
                );
        }
    }


    /* ------------------------------------------------------
       JAM KPI CARDS
       ------------------------------------------------------ */

    setText(
        "jamNormalCameras",
        formatInteger(
            normalCount
        )
    );


    setText(
        "jamSlowCameras",
        formatInteger(
            slowCount
        )
    );


    setText(
        "jamWarningCameras",
        formatInteger(
            warningCount
        )
    );


    setText(
        "jamActiveCount",
        formatInteger(
            activeJamCount
        )
    );
}/* ==========================================================
   PRODUCTION
   ========================================================== */

async function loadProduction() {

    try {

        const data =
            await apiFetch(
                "/production"
            );

        appState.production =
            data;

        renderProduction(
            data
        );

    }

    catch (error) {

        console.error(
            "Failed loading production:",
            error
        );
    }
}


function renderProduction(data) {

    if (
        !data
        ||
        typeof data !== "object"
    ) {
        return;
    }


    const total =
        safeNumber(
            data.total_bags
            ??
            0
        );


    const printed =
        safeNumber(
            data.printed_bags
            ??
            0
        );


    const missing =
        safeNumber(
            data.not_printed_bags
            ??
            0
        );


    const quality =
        safeNumber(
            data.print_quality
            ??
            0
        );


    const ratePerHour =
        safeNumber(
            data.production_rate_per_hour
            ??
            0
        );


    setText(
        "productionTotal",
        formatInteger(total)
    );


    setText(
        "productionPrinted",
        formatInteger(printed)
    );


    setText(
        "productionMissing",
        formatInteger(missing)
    );


    setText(
        "productionQuality",
        formatPercent(quality)
    );


    setText(
        "productionRate",
        formatInteger(ratePerHour)
    );


    renderProductionCameras(
        data.cameras
        ||
        appState
            .dashboardState
            ?.cameras
        ||
        {}
    );
}


/* ==========================================================
   PRODUCTION CAMERA TABLE
   ========================================================== */

function renderProductionCameras(cameras) {

    const body =
        byId(
            "productionCameraTable"
        );


    if (!body) {
        return;
    }


    const rows = [];


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        if (!camera) {
            continue;
        }


        const count =
            safeNumber(
                camera.count
                ??
                camera.total_count
                ??
                0
            );


        const printed =
            safeNumber(
                camera.printed_count
                ??
                camera.printed_bags_count
                ??
                0
            );


        const missing =
            safeNumber(
                camera.missing_count
                ??
                camera.not_printed_bags_count
                ??
                0
            );


        const printRate =
            count > 0
                ? (printed / count) * 100
                : 0;


        const jamStatus =
            normalizeJamStatus(
                camera
            );


        rows.push(
            `
            <tr>

                <td>
                    Camera ${index}
                </td>

                <td>
                    ${formatInteger(count)}
                </td>

                <td>
                    ${formatInteger(printed)}
                </td>

                <td>
                    ${formatInteger(missing)}
                </td>

                <td>
                    ${formatPercent(printRate)}
                </td>

                <td>
                    <span class="jam-status ${jamStatus}">
                        ${jamStatus.toUpperCase()}
                    </span>
                </td>

            </tr>
            `
        );
    }


    body.innerHTML =
        rows.length > 0
            ? rows.join("")
            : `
                <tr>
                    <td colspan="6">
                        No production data available.
                    </td>
                </tr>
              `;
}


/* ==========================================================
   ANALYTICS
   ========================================================== */

async function loadAnalytics() {

    try {

        const data =
            await apiFetch(
                "/analytics"
            );


        appState.analytics =
            data;


        renderAnalytics(
            data
        );

    }

    catch (error) {

        console.error(
            "Failed loading analytics:",
            error
        );
    }
}


function renderAnalytics(data) {

    if (
        !data
        ||
        typeof data !== "object"
    ) {
        return;
    }


    const total =
        safeNumber(
            data.total_events
            ??
            0
        );


    const printed =
        safeNumber(
            data.printed_events
            ??
            0
        );


    const missing =
        safeNumber(
            data.missing_events
            ??
            0
        );


    const quality =
        safeNumber(
            data.print_quality
            ??
            0
        );


    setText(
        "analyticsTotalEvents",
        formatInteger(total)
    );


    setText(
        "analyticsPrinted",
        formatInteger(printed)
    );


    setText(
        "analyticsMissing",
        formatInteger(missing)
    );


    setText(
        "analyticsQuality",
        formatPercent(quality)
    );


    renderAnalyticsCameraTable(
        data.by_camera
        ||
        []
    );


    /* ------------------------------------------------------
       CHARTS

       Shared between the Dashboard page (Production Trend)
       and the Analytics page (Hourly / Camera / Print / Shift).
       byId() guards inside each updater mean this is a no-op
       for canvases that aren't on the current page.
       ------------------------------------------------------ */

    updateProductionTrendChart(
        data.hourly || []
    );

    updateAnalyticsHourlyChart(
        data.hourly || []
    );

    updateAnalyticsCameraChart(
        data.by_camera || []
    );

    updateAnalyticsPrintChart(
        printed,
        missing
    );

    updateAnalyticsShiftChart(
        data.by_shift || []
    );
}


/* ==========================================================
   ANALYTICS CAMERA TABLE
   ========================================================== */

function renderAnalyticsCameraTable(cameras) {

    const body =
        byId(
            "analyticsCameraTableBody"
        );


    if (!body) {
        return;
    }


    const rows = [];


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        if (!camera) {
            continue;
        }


        const count =
            safeNumber(
                camera.count
                ??
                camera.total_count
                ??
                0
            );


        const printed =
            safeNumber(
                camera.printed_count
                ??
                camera.printed_bags_count
                ??
                0
            );


        const missing =
            safeNumber(
                camera.missing_count
                ??
                camera.not_printed_bags_count
                ??
                0
            );


        const printRate =
            count > 0
                ? (printed / count) * 100
                : 0;


        const jamStatus =
            normalizeJamStatus(
                camera
            );


        rows.push(
            `
            <tr>

                <td>
                    Camera ${index}
                </td>

                <td>
                    ${formatInteger(count)}
                </td>

                <td>
                    ${formatInteger(printed)}
                </td>

                <td>
                    ${formatInteger(missing)}
                </td>

                <td>
                    ${formatPercent(printRate)}
                </td>

                <td>
                    ${formatDecimal(
                        camera.fps,
                        1
                    )}
                </td>

                <td>
                    <span class="jam-status ${jamStatus}">
                        ${jamStatus.toUpperCase()}
                    </span>
                </td>

            </tr>
            `
        );
    }


    body.innerHTML =
        rows.length > 0
            ? rows.join("")
            : `
                <tr>
                    <td colspan="7">
                        No analytics data available.
                    </td>
                </tr>
              `;
}


/* ==========================================================
   EVENTS
   ========================================================== */

async function loadEvents() {

    try {

        const query =
            buildEventQuery();


        const path =
            query
                ? `/events?${query}`
                : "/events";


        const data =
            await apiFetch(
                path
            );


        const events =
            Array.isArray(data)
                ? data
                : (
                    data?.events
                    ??
                    data?.items
                    ??
                    []
                );


        appState.events =
            events;


        renderEvents(
            events
        );

    }

    catch (error) {

        console.error(
            "Failed loading events:",
            error
        );
    }
}


/* ==========================================================
   EVENT QUERY
   ========================================================== */

function isWildcardFilterValue(value) {

    return (
        !value
        ||
        value.trim() === ""
        ||
        value.trim().toLowerCase() === "all"
    );
}


function buildEventQuery() {

    const params =
        new URLSearchParams();


    const camera =
        byId(
            "cameraFilter"
        )?.value;


    const eventType =
        byId(
            "printFilter"
        )?.value;


    const shift =
        byId(
            "shiftFilter"
        )?.value;


    const dateFrom =
        byId(
            "startDate"
        )?.value;


    const dateTo =
        byId(
            "endDate"
        )?.value;


    const limit =
        byId(
            "recordLimit"
        )?.value;


    if (!isWildcardFilterValue(camera)) {

        params.set(
            "camera",
            camera
        );
    }


    if (!isWildcardFilterValue(eventType)) {

        params.set(
            "print_status",
            eventType
        );
    }


    if (!isWildcardFilterValue(shift)) {

        params.set(
            "shift",
            shift
        );
    }


    if (dateFrom) {

        params.set(
            "start",
            dateFrom
        );
    }


    if (dateTo) {

        params.set(
            "end",
            dateTo
        );
    }


    if (limit) {

        params.set(
            "limit",
            limit
        );
    }


    return params.toString();
}


/* ==========================================================
   EVENT TABLE
   ========================================================== */

function renderEvents(events) {

    const body =
        byId(
            "eventsTableBody"
        );


    if (!body) {
        return;
    }


    setText(
        "eventRecordCount",
        formatInteger(
            Array.isArray(events)
                ? events.length
                : 0
        )
    );


    if (
        !Array.isArray(events)
        ||
        events.length === 0
    ) {

        body.innerHTML =
            `
            <tr>
                <td colspan="8">
                    No events found.
                </td>
            </tr>
            `;

        return;
    }


    body.innerHTML =
        events
            .map(
                event => {

                    const camera =
                        event.camera_name
                        ??
                        event.camera
                        ??
                        event.camera_id
                        ??
                        "--";


                    const eventType =
                        event.event_type
                        ??
                        event.type
                        ??
                        event.event
                        ??
                        "--";


                    const totalCount =
                        event.total_count
                        ??
                        event.count
                        ??
                        "--";


                    const printed =
                        event.printed
                        ??
                        event.print_present;


                    const printStatus =
                        printed === true
                            ? "PRINTED"
                            : (
                                printed === false
                                    ? "MISSING"
                                    : "--"
                            );


                    const timestamp =
                        event.timestamp
                        ??
                        event.created_at
                        ??
                        event["@timestamp"]
                        ??
                        null;


                    const trackId =
                        event.track_id
                        ??
                        event.bag_track_id
                        ??
                        "--";


                    return `
                    <tr>

                        <td>
                            ${escapeHtml(
                                formatDateTime(
                                    timestamp
                                )
                            )}
                        </td>

                        <td>
                            ${escapeHtml(camera)}
                        </td>

                        <td>
                            ${escapeHtml(eventType)}
                        </td>

                        <td>
                            ${escapeHtml(totalCount)}
                        </td>

                        <td>
                            ${escapeHtml(printStatus)}
                        </td>

                        <td>
                            ${escapeHtml(trackId)}
                        </td>

                        <td>
                            ${escapeHtml(
                                event.event_id
                                ??
                                event.id
                                ??
                                "--"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                event.status
                                ??
                                "OK"
                            )}
                        </td>

                    </tr>
                    `;
                }
            )
            .join("");
}


/* ==========================================================
   EVENT FILTER CONTROLS
   ========================================================== */

function initializeEventControls() {

    const searchButton =
        byId(
            "applyFilters"
        );


    if (searchButton) {

        searchButton.addEventListener(
            "click",
            async () => {

                await loadEvents();
            }
        );
    }


    const resetButton =
        byId(
            "resetFilters"
        );


    if (resetButton) {

        resetButton.addEventListener(
            "click",
            async () => {

                [
                    "cameraFilter",
                    "printFilter",
                    "shiftFilter"
                ]
                    .forEach(
                        id => {

                            const element =
                                byId(id);


                            if (element) {

                                element.value =
                                    "all";
                            }
                        }
                    );


                [
                    "startDate",
                    "endDate"
                ]
                    .forEach(
                        id => {

                            const element =
                                byId(id);


                            if (element) {

                                element.value =
                                    "";
                            }
                        }
                    );


                const recordLimitElement =
                    byId("recordLimit");


                if (recordLimitElement) {

                    recordLimitElement.value =
                        "100";
                }


                await loadEvents();
            }
        );
    }


    const exportButton =
        byId(
            "exportButton"
        );


    if (exportButton) {

        exportButton.addEventListener(
            "click",
            () => {

                exportEventsCsv(
                    appState.events
                );
            }
        );
    }
}


/* ==========================================================
   EVENT CSV EXPORT
   ========================================================== */

function exportEventsCsv(events) {

    if (
        !Array.isArray(events)
        ||
        events.length === 0
    ) {

        alert(
            "No events available to export."
        );

        return;
    }


    const headers = [
        "Timestamp",
        "Camera",
        "Event Type",
        "Total Count",
        "Printed",
        "Track ID",
        "Event ID"
    ];


    const rows =
        events.map(
            event => [

                event.timestamp
                ??
                event.created_at
                ??
                event["@timestamp"]
                ??
                "",

                event.camera_name
                ??
                event.camera
                ??
                event.camera_id
                ??
                "",

                event.event_type
                ??
                event.type
                ??
                event.event
                ??
                "",

                event.total_count
                ??
                event.count
                ??
                "",

                event.printed
                ??
                event.print_present
                ??
                "",

                event.track_id
                ??
                "",

                event.event_id
                ??
                event.id
                ??
                ""
            ]
        );


    const csv =
        [
            headers,
            ...rows
        ]
            .map(
                row =>

                    row
                        .map(
                            value => {

                                const text =
                                    String(
                                        value ?? ""
                                    )
                                        .replaceAll(
                                            '"',
                                            '""'
                                        );


                                return `"${text}"`;
                            }
                        )
                        .join(",")
            )
            .join("\n");


    const blob =
        new Blob(
            [csv],
            {
                type:
                    "text/csv;charset=utf-8"
            }
        );


    const url =
        URL.createObjectURL(
            blob
        );


    const anchor =
        document.createElement(
            "a"
        );


    anchor.href =
        url;


    anchor.download =
        `fillpac-events-${Date.now()}.csv`;


    document.body.appendChild(
        anchor
    );


    anchor.click();


    anchor.remove();


    URL.revokeObjectURL(
        url
    );
}


/* ==========================================================
   LIVE CAMERA STREAMS
   ========================================================== */

function initializeLiveStreams() {

    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const feedContainer =
            byId(
                `liveCamera${index}Feed`
            );


        if (!feedContainer) {
            continue;
        }


        const cameraName =
            `Camera ${index}`;


        const image =
            document.createElement(
                "img"
            );


        image.className =
            "camera-feed-stream";


        image.alt =
            `${cameraName} live feed`;


        image.addEventListener(
            "error",
            () => {

                feedContainer.classList
                    .remove(
                        "has-stream"
                    );

                feedContainer.innerHTML =
                    `
                    <i class="fa-solid fa-video-slash"></i>
                    <span>
                        Live video stream not connected
                    </span>
                    `;
            }
        );


        image.addEventListener(
            "load",
            () => {

                feedContainer.classList.add(
                    "has-stream"
                );
            }
        );


        image.src =
            `${API_BASE}/live/${encodeURIComponent(
                cameraName
            )}`;


        feedContainer.innerHTML = "";

        feedContainer.appendChild(
            image
        );
    }
}


/* ==========================================================
   CAMERA CONFIGURATION
   ========================================================== */

async function loadCameraConfig() {

    try {

        const data =
            await apiFetch(
                "/cameras"
            );


        appState.cameraConfig =
            data;


        renderCameraManagement(
            data
        );


        return data;

    }

    catch (error) {

        console.error(
            "Failed loading camera configuration:",
            error
        );

        return null;
    }
}


/* ==========================================================
   SETTINGS PAGE
   ========================================================== */

async function loadSettings() {

    try {

        const data =
            await apiFetch(
                "/config"
            );

        renderSettings(
            data
        );

        return data;

    }

    catch (error) {

        console.error(
            "Failed loading settings:",
            error
        );

        return null;
    }
}


function prettifySettingLabel(key) {

    return String(key)
        .replaceAll("_", " ")
        .replace(
            /\b\w/g,
            character =>
                character.toUpperCase()
        );
}


function renderSettingsGroup(
    containerId,
    data
) {

    const container =
        byId(containerId);

    if (!container) {
        return;
    }

    const entries =
        Object.entries(
            data || {}
        );

    if (entries.length === 0) {

        container.innerHTML =
            `
            <div class="setting-row">
                <span>Status</span>
                <strong>No configuration found</strong>
            </div>
            `;

        return;
    }

    container.innerHTML =
        entries
            .map(
                ([key, value]) => {

                    const displayValue =
                        typeof value === "object"
                        && value !== null
                            ? JSON.stringify(value)
                            : String(
                                value
                                ??
                                "--"
                            );

                    return `
                    <div class="setting-row">
                        <span>${escapeHtml(
                            prettifySettingLabel(key)
                        )}</span>
                        <strong>${escapeHtml(
                            displayValue
                        )}</strong>
                    </div>
                    `;
                }
            )
            .join("");
}


function renderSettings(data) {

    if (
        !data
        ||
        typeof data !== "object"
    ) {
        return;
    }

    setText(
        "settingProjectRoot",
        data.project_root
        ??
        "--"
    );

    setText(
        "settingConfigFile",
        data.config_file
        ??
        "--"
    );

    setText(
        "settingEventsFile",
        data.events_file
        ??
        "--"
    );

    if (data.available === false) {

        const message =
            data.error
            ??
            "Configuration unavailable.";

        [
            "modelSettings",
            "countingSettings",
            "dashboardSettings"
        ].forEach(
            id => {

                const container =
                    byId(id);

                if (container) {

                    container.innerHTML =
                        `
                        <div class="setting-row">
                            <span>Status</span>
                            <strong>${escapeHtml(message)}</strong>
                        </div>
                        `;
                }
            }
        );

        return;
    }

    renderSettingsGroup(
        "modelSettings",
        data.model
    );

    renderSettingsGroup(
        "countingSettings",
        data.counting
    );

    renderSettingsGroup(
        "dashboardSettings",
        data.dashboard
    );
}


/* ==========================================================
   CAMERA MANAGEMENT
   ========================================================== */

function renderCameraManagement(data) {

    const grid =
        byId(
            "cameraManagementGrid"
        );


    if (!grid) {
        return;
    }


    const cameras =
        data?.cameras
        ??
        data
        ??
        {};


    const cards = [];


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        const status =
            String(
                camera?.status
                ??
                "offline"
            ).toLowerCase();


        const mode =
            camera?.mode
            ??
            camera?.source_type
            ??
            "--";


        const fps =
            formatDecimal(
                camera?.fps,
                1
            );


        const jamStatus =
            normalizeJamStatus(
                camera ?? {}
            );


        const printDetection =
            camera?.print_detection_enabled
                ? "Enabled"
                : "Disabled";


        cards.push(
            `
            <article class="management-camera-card ${status}">

                <div class="management-camera-header">

                    <div class="management-camera-title">

                        <div class="camera-management-icon">
                            <i class="fa-solid fa-camera"></i>
                        </div>

                        <div>
                            <h3>${escapeHtml(
                                camera?.name
                                ??
                                `Camera ${index}`
                            )}</h3>
                            <p>${escapeHtml(
                                status.toUpperCase()
                            )}</p>
                        </div>

                    </div>

                </div>

                <div class="management-camera-details">

                    <div class="management-detail">
                        <span>Mode</span>
                        <strong>${escapeHtml(
                            String(mode)
                        )}</strong>
                    </div>

                    <div class="management-detail">
                        <span>FPS</span>
                        <strong>${fps}</strong>
                    </div>

                    <div class="management-detail">
                        <span>Jam Status</span>
                        <strong>${escapeHtml(
                            jamStatus.toUpperCase()
                        )}</strong>
                    </div>

                    <div class="management-detail">
                        <span>Print Detection</span>
                        <strong>${printDetection}</strong>
                    </div>

                </div>

            </article>
            `
        );
    }


    grid.innerHTML =
        cards.length > 0
            ? cards.join("")
            : `
                <article class="management-camera-card offline">
                    <div>
                        <h3>No cameras configured</h3>
                        <p>Waiting for backend</p>
                    </div>
                </article>
              `;
}


/* ==========================================================
   CAMERA CONTROLS
   ========================================================== */

function initializeCameraControls() {

    const refreshButton =
        byId(
            "refreshCamerasButton"
        );


    if (!refreshButton) {
        return;
    }


    refreshButton.addEventListener(
        "click",
        async () => {

            refreshButton.disabled =
                true;


            try {

                await loadCameraConfig();

                await loadDashboardState();

            }

            catch (error) {

                console.error(
                    "Camera refresh failed:",
                    error
                );

            }

            finally {

                refreshButton.disabled =
                    false;
            }
        }
    );
}


/* ==========================================================
   JAM TRACK HELPERS
   ========================================================== */

function getJamTracks(camera) {

    if (
        !camera
        ||
        typeof camera !== "object"
    ) {

        return [];
    }


    const tracks =
        camera.jam_tracks
        ??
        camera.tracks
        ??
        [];


    return Array.isArray(tracks)
        ? tracks
        : [];
}


function getJamTrackSpeed(track) {

    if (!track) {
        return 0;
    }


    return safeNumber(
        track.speed_px_s
        ??
        track.speed
        ??
        track.motion_speed
        ??
        0,
        0
    );
}


function getJamTrackDistance(track) {

    if (!track) {
        return 0;
    }


    return safeNumber(
        track.distance_px
        ??
        track.movement_distance
        ??
        track.distance
        ??
        0,
        0
    );
}


function getJamTrackStationaryTime(track) {

    if (!track) {
        return 0;
    }


    return safeNumber(
        track.stationary_seconds
        ??
        track.stationary_time
        ??
        track.time_stationary
        ??
        0,
        0
    );
}


function getJamTrackState(track) {

    if (!track) {
        return "unknown";
    }


    return String(
        track.status
        ??
        track.state
        ??
        "unknown"
    )
        .trim()
        .toLowerCase();
}


function getJamTrackId(track) {

    if (!track) {
        return "--";
    }


    return (
        track.track_id
        ??
        track.id
        ??
        "--"
    );
}


/* ==========================================================
   JAM CAMERA SUMMARY
   ========================================================== */

function getJamCameraSummary(camera) {

    if (!camera) {

        return {

            enabled: false,

            status: "disabled",

            activeCount: 0,

            trackIds: [],

            tracks: []
        };
    }


    const enabled =
        Boolean(
            camera.jam_detection_enabled
        );


    const status =
        normalizeJamStatus(
            camera
        );


    const trackIds =
        Array.isArray(
            camera.active_jam_track_ids
        )
            ? camera.active_jam_track_ids
            : [];


    const activeCount =
        Math.max(
            0,
            Math.round(
                safeNumber(
                    camera.active_jam_count,
                    0
                )
            )
        );


    return {

        enabled,

        status,

        activeCount,

        trackIds,

        tracks:
            getJamTracks(
                camera
            )
    };
}


/* ==========================================================
   JAM SYSTEM SUMMARY
   ========================================================== */

function getJamSystemSummary(cameras) {

    const summary = {

        enabledCameras: 0,

        normal: 0,

        slow: 0,

        warning: 0,

        jam: 0,

        recovering: 0,

        disabled: 0,

        activeJams: 0
    };


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        const cameraSummary =
            getJamCameraSummary(
                camera
            );


        if (!cameraSummary.enabled) {

            summary.disabled += 1;

            continue;
        }


        summary.enabledCameras += 1;


        if (
            Object.prototype
                .hasOwnProperty
                .call(
                    summary,
                    cameraSummary.status
                )
        ) {

            summary[
                cameraSummary.status
            ] += 1;
        }


        if (
            cameraSummary.status
            === "jam"
        ) {

            summary.activeJams +=
                cameraSummary.activeCount > 0
                    ? cameraSummary.activeCount
                    : 1;
        }
    }


    return summary;
}/* ==========================================================
   SOCKET.IO
   ========================================================== */

function initializeSocket() {

    if (
        typeof io !== "function"
    ) {

        console.warn(
            "Socket.IO client is not available. REST refresh will remain active."
        );

        return;
    }


    try {

        const API_BASE =
    "http://127.0.0.1:8000";

appState.socket =
    io(
        API_BASE,
        {
            transports: [
                "websocket",
                "polling"
            ],

            reconnection: true,

            reconnectionAttempts:
                Infinity,

            reconnectionDelay:
                1000,

            reconnectionDelayMax:
                5000,

            timeout:
                10000
        }
    );


        /* --------------------------------------------------
           CONNECT
           -------------------------------------------------- */

        appState.socket.on(
            "connect",
            () => {

                appState.socketConnected =
                    true;


                console.log(
                    "FillPac Dashboard Socket.IO connected."
                );


                updateSocketIndicator(
                    true
                );
            }
        );


        /* --------------------------------------------------
           DISCONNECT
           -------------------------------------------------- */

        appState.socket.on(
            "disconnect",
            () => {

                appState.socketConnected =
                    false;


                console.warn(
                    "FillPac Dashboard Socket.IO disconnected."
                );


                updateSocketIndicator(
                    false
                );
            }
        );


        /* --------------------------------------------------
           FULL STATE
           -------------------------------------------------- */

        appState.socket.on(
            "state",
            state => {

                renderDashboardState(
                    state
                );
            }
        );


        /* --------------------------------------------------
           STATE UPDATE
           -------------------------------------------------- */

        appState.socket.on(
            "state_update",
            state => {

                renderDashboardState(
                    state
                );
            }
        );


        /* --------------------------------------------------
           DASHBOARD STATE
           -------------------------------------------------- */

        appState.socket.on(
            "dashboard_state",
            state => {

                renderDashboardState(
                    state
                );
            }
        );


        /* --------------------------------------------------
           CAMERA UPDATE
           -------------------------------------------------- */

        appState.socket.on(
            "camera_update",
            payload => {

                handleCameraSocketUpdate(
                    payload
                );
            }
        );


        /* --------------------------------------------------
           JAM UPDATE
           -------------------------------------------------- */

        appState.socket.on(
            "jam_update",
            payload => {

                handleJamSocketUpdate(
                    payload
                );
            }
        );


        /* --------------------------------------------------
           COUNT EVENT
           -------------------------------------------------- */

        appState.socket.on(
            "count_event",
            payload => {

                handleCountEvent(
                    payload
                );
            }
        );


        /* --------------------------------------------------
           PRODUCTION EVENT
           -------------------------------------------------- */

        appState.socket.on(
            "production_event",
            payload => {

                handleProductionEvent(
                    payload
                );
            }
        );

    }

    catch (error) {

        console.error(
            "Socket.IO initialization failed:",
            error
        );
    }
}


/* ==========================================================
   SOCKET INDICATOR
   ========================================================== */

function updateSocketIndicator(
    connected
) {

    const indicator =
        byId(
            "socketStatus"
        );


    if (!indicator) {
        return;
    }


    indicator.textContent =
        connected
            ? "LIVE"
            : "OFFLINE";


    indicator.classList.toggle(
        "online",
        connected
    );


    indicator.classList.toggle(
        "offline",
        !connected
    );
}


/* ==========================================================
   ENSURE DASHBOARD STATE
   ========================================================== */

function ensureDashboardState() {

    if (
        !appState.dashboardState
        ||
        typeof appState.dashboardState
        !== "object"
    ) {

        appState.dashboardState = {
            cameras: {}
        };
    }


    if (
        !appState.dashboardState.cameras
        ||
        typeof appState.dashboardState.cameras
        !== "object"
    ) {

        appState.dashboardState.cameras =
            {};
    }


    return appState.dashboardState;
}


/* ==========================================================
   CAMERA SOCKET UPDATE
   ========================================================== */

function handleCameraSocketUpdate(
    payload
) {

    if (
        !payload
        ||
        typeof payload !== "object"
    ) {
        return;
    }


    const cameraName =
        payload.camera_name
        ??
        payload.name
        ??
        payload.camera
        ??
        payload.camera_id;


    if (!cameraName) {

        console.warn(
            "Camera socket update without camera identifier:",
            payload
        );

        return;
    }


    const state =
        ensureDashboardState();


    const existing =
        state.cameras[
            cameraName
        ]
        || {};


    state.cameras[
        cameraName
    ] = {

        ...existing,

        ...payload
    };


    renderDashboardState(
        state
    );
}


/* ==========================================================
   JAM SOCKET UPDATE
   ========================================================== */

function handleJamSocketUpdate(
    payload
) {

    if (
        !payload
        ||
        typeof payload !== "object"
    ) {
        return;
    }


    const cameraName =
        payload.camera_name
        ??
        payload.name
        ??
        payload.camera
        ??
        payload.camera_id;


    if (!cameraName) {

        console.warn(
            "Jam update without camera identifier:",
            payload
        );

        return;
    }


    const state =
        ensureDashboardState();


    const existing =
        state.cameras[
            cameraName
        ]
        || {};


    state.cameras[
        cameraName
    ] = {

        ...existing,

        jam_detection_enabled:
            payload.jam_detection_enabled
            ??
            existing.jam_detection_enabled,

        jam_status:
            payload.jam_status
            ??
            payload.status
            ??
            existing.jam_status,

        jam_detected:
            payload.jam_detected
            ??
            existing.jam_detected,

        jam_warning:
            payload.jam_warning
            ??
            payload.warning
            ??
            existing.jam_warning,

        active_jam_count:
            payload.active_jam_count
            ??
            existing.active_jam_count
            ??
            0,

        active_jam_track_ids:
            payload.active_jam_track_ids
            ??
            existing.active_jam_track_ids
            ??
            [],

        jam_tracks:
            payload.jam_tracks
            ??
            payload.tracks
            ??
            existing.jam_tracks
            ??
            [],

        condition_c_detected:
            payload.condition_c_detected
            ??
            existing.condition_c_detected,

        condition_c_status:
            payload.condition_c_status
            ??
            existing.condition_c_status,

        condition_c_bag_count:
            payload.condition_c_bag_count
            ??
            existing.condition_c_bag_count,

        condition_c_track_ids:
            payload.condition_c_track_ids
            ??
            existing.condition_c_track_ids,

        condition_c_minimum_gap_mm:
            payload.condition_c_minimum_gap_mm
            ??
            existing.condition_c_minimum_gap_mm,

        condition_c_distances:
            payload.condition_c_distances
            ??
            existing.condition_c_distances,

        condition_c_image_url:
            payload.condition_c_image_url
            ??
            existing.condition_c_image_url,

        condition_c_image_path:
            payload.condition_c_image_path
            ??
            existing.condition_c_image_path
    };


    /*
    Update only the jam UI immediately.

    The normal periodic /state refresh remains the
    authoritative source for the complete dashboard.
    */

    renderJamMonitoring(
        state.cameras
    );


    renderDashboardHealthSummary(
        state
    );
}


/* ==========================================================
   COUNT EVENT
   ========================================================== */

function handleCountEvent(
    payload
) {

    if (
        !payload
        ||
        typeof payload !== "object"
    ) {
        return;
    }


    /*
    Backend remains the source of truth for counts.

    Do not increment counters in JavaScript because
    doing so could create duplicate counts when REST
    synchronization occurs.
    */

    loadDashboardState()
        .catch(
            error => {

                console.error(
                    "Count-event state refresh failed:",
                    error
                );
            }
        );


    if (
        appState.currentPage
        === "events"
    ) {

        loadEvents()
            .catch(
                error => {

                    console.error(
                        "Count-event event refresh failed:",
                        error
                    );
                }
            );
    }
}


/* ==========================================================
   PRODUCTION EVENT
   ========================================================== */

function handleProductionEvent(
    payload
) {

    if (
        !payload
        ||
        typeof payload !== "object"
    ) {
        return;
    }


    if (
        appState.currentPage
        === "events"
    ) {

        loadEvents()
            .catch(
                error => {

                    console.error(
                        "Production event refresh failed:",
                        error
                    );
                }
            );
    }


    if (
        appState.currentPage
        === "production"
    ) {

        loadProduction()
            .catch(
                error => {

                    console.error(
                        "Production page refresh failed:",
                        error
                    );
                }
            );
    }
}


/* ==========================================================
   JAM DIAGNOSTICS
   ========================================================== */

function logJamDiagnostics() {

    const cameras =
        appState
            .dashboardState
            ?.cameras
        || {};


    const summary =
        getJamSystemSummary(
            cameras
        );


    console.group(
        "FillPac AI - Jam Detection"
    );


    console.log(
        "System Summary:",
        summary
    );


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        const cameraSummary =
            getJamCameraSummary(
                camera
            );


        console.log(
            `Camera ${index}:`,
            cameraSummary
        );


        if (
            cameraSummary.tracks.length > 0
        ) {

            console.table(
                cameraSummary.tracks.map(
                    track => ({

                        trackId:
                            getJamTrackId(
                                track
                            ),

                        state:
                            getJamTrackState(
                                track
                            ),

                        speedPxS:
                            getJamTrackSpeed(
                                track
                            ),

                        distancePx:
                            getJamTrackDistance(
                                track
                            ),

                        stationarySeconds:
                            getJamTrackStationaryTime(
                                track
                            )
                    })
                )
            );
        }
    }


    console.groupEnd();
}


/* ==========================================================
   REFRESH LOOP
   ========================================================== */

function startRefreshLoop() {

    if (
        appState.refreshTimer
    ) {

        clearInterval(
            appState.refreshTimer
        );
    }


    appState.refreshTimer =
        setInterval(
            async () => {

                try {

                    /*
                    --------------------------------------------------
                    Always refresh /state.

                    Socket.IO gives low-latency updates while this
                    REST poll protects against missed socket events.
                    --------------------------------------------------
                    */

                    await loadDashboardState();


                    /* ----------------------------------------------
                       PRODUCTION
                       ---------------------------------------------- */

                    if (
                        appState.currentPage
                        === "production"
                    ) {

                        await loadProduction();
                    }


                    /* ----------------------------------------------
                       ANALYTICS

                       Also runs on the Dashboard page, since the
                       Production Trend chart there is fed by the
                       same /analytics payload.
                       ---------------------------------------------- */

                    if (
                        appState.currentPage
                        === "analytics"
                        ||
                        appState.currentPage
                        === "dashboard"
                    ) {

                        await loadAnalytics();
                    }


                    /* ----------------------------------------------
                       EVENTS
                       ---------------------------------------------- */

                    if (
                        appState.currentPage
                        === "events"
                    ) {

                        await loadEvents();
                    }


                    /* ----------------------------------------------
                       CAMERAS
                       ---------------------------------------------- */

                    if (
                        appState.currentPage
                        === "cameras"
                    ) {

                        await loadCameraConfig();
                    }


                    /* ----------------------------------------------
                       JAM MONITOR

                       /state already refreshed the values.
                       Re-render explicitly for clarity.
                       ---------------------------------------------- */

                    if (
                        appState.currentPage
                        === "jam-monitor"
                    ) {

                        renderJamMonitoring(
                            appState
                                .dashboardState
                                ?.cameras
                            || {}
                        );
                    }

                }

                catch (error) {

                    console.error(
                        "Dashboard refresh cycle failed:",
                        error
                    );
                }

            },
            REFRESH_INTERVAL_MS
        );
}


/* ==========================================================
   STOP REFRESH LOOP
   ========================================================== */

function stopRefreshLoop() {

    if (
        !appState.refreshTimer
    ) {
        return;
    }


    clearInterval(
        appState.refreshTimer
    );


    appState.refreshTimer =
        null;
}


/* ==========================================================
   MANUAL REFRESH
   ========================================================== */

function initializeRefreshButton() {

    const button =
        byId(
            "refreshButton"
        )
        ||
        byId(
            "dashboardRefreshButton"
        );


    if (!button) {
        return;
    }


    button.addEventListener(
        "click",
        async () => {

            button.disabled =
                true;


            try {

                await loadDashboardState();


                /*
                Load page-specific information only when
                necessary. Dashboard state has already been
                refreshed above.
                */

                if (
                    appState.currentPage
                    === "production"
                ) {

                    await loadProduction();
                }


                else if (
                    appState.currentPage
                    === "analytics"
                ) {

                    await loadAnalytics();
                }


                else if (
                    appState.currentPage
                    === "events"
                ) {

                    await loadEvents();
                }


                else if (
                    appState.currentPage
                    === "cameras"
                ) {

                    await loadCameraConfig();
                }

            }

            catch (error) {

                console.error(
                    "Manual dashboard refresh failed:",
                    error
                );

            }

            finally {

                button.disabled =
                    false;
            }
        }
    );
}


/* ==========================================================
   NETWORK STATUS
   ========================================================== */

function initializeNetworkListeners() {

    window.addEventListener(
        "online",
        () => {

            console.log(
                "Browser network connection restored."
            );


            loadDashboardState()
                .catch(
                    error => {

                        console.error(
                            "Network recovery refresh failed:",
                            error
                        );
                    }
                );
        }
    );


    window.addEventListener(
        "offline",
        () => {

            console.warn(
                "Browser network connection lost."
            );


            updateSystemStatus(
                "offline"
            );
        }
    );
}


/* ==========================================================
   PAGE VISIBILITY
   ========================================================== */

function initializeVisibilityListener() {

    document.addEventListener(
        "visibilitychange",
        () => {

            if (
                document.visibilityState
                !== "visible"
            ) {
                return;
            }


            /*
            Browser tabs may throttle timers while hidden.
            Refresh immediately when the operator returns.
            */

            loadDashboardState()
                .catch(
                    error => {

                        console.error(
                            "Visibility refresh failed:",
                            error
                        );
                    }
                );
        }
    );
}


/* ==========================================================
   KEYBOARD SHORTCUT
   ========================================================== */

function initializeKeyboardShortcuts() {

    document.addEventListener(
        "keydown",
        async event => {

            const target =
                event.target;


            const typing =
                target
                &&
                (
                    target.tagName === "INPUT"
                    ||
                    target.tagName === "TEXTAREA"
                    ||
                    target.tagName === "SELECT"
                );


            if (typing) {
                return;
            }


            /*
            Press R to manually refresh dashboard data.
            */

            if (
                event.key
                    .toLowerCase()
                === "r"
            ) {

                event.preventDefault();


                try {

                    await loadDashboardState();


                    if (
                        appState.currentPage
                        === "production"
                    ) {

                        await loadProduction();
                    }


                    else if (
                        appState.currentPage
                        === "analytics"
                    ) {

                        await loadAnalytics();
                    }


                    else if (
                        appState.currentPage
                        === "events"
                    ) {

                        await loadEvents();
                    }


                    else if (
                        appState.currentPage
                        === "cameras"
                    ) {

                        await loadCameraConfig();
                    }

                }

                catch (error) {

                    console.error(
                        "Keyboard refresh failed:",
                        error
                    );
                }
            }
        }
    );
}


/* ==========================================================
   CLOCK
   ========================================================== */

function updateClock() {

    const now =
        new Date();


    setText(
        "currentTime",
        now.toLocaleTimeString()
    );


    setText(
        "currentDate",
        now.toLocaleDateString()
    );
}


function initializeClock() {

    updateClock();


    setInterval(
        updateClock,
        1000
    );
}


/* ==========================================================
   LAST STATE UPDATE
   ========================================================== */

function updateLastRefreshIndicator() {

    const element =
        byId(
            "lastUpdated"
        );


    if (!element) {
        return;
    }


    if (
        !appState.lastStateUpdate
    ) {

        element.textContent =
            "Waiting for data";

        return;
    }


    const elapsed =
        Math.max(
            0,
            (
                Date.now()
                -
                appState
                    .lastStateUpdate
                    .getTime()
            )
            /
            1000
        );


    if (
        elapsed < 2
    ) {

        element.textContent =
            "Updated now";
    }


    else if (
        elapsed < 60
    ) {

        element.textContent =
            `Updated ${Math.round(
                elapsed
            )}s ago`;
    }


    else {

        element.textContent =
            `Updated ${Math.round(
                elapsed / 60
            )}m ago`;
    }
}


function initializeLastUpdateIndicator() {

    updateLastRefreshIndicator();


    setInterval(
        updateLastRefreshIndicator,
        1000
    );
}


/* ==========================================================
   STATE AGE
   ========================================================== */

function getStateAgeSeconds(state) {

    if (!state) {
        return null;
    }


    const timestamp =
        state.updated_at
        ??
        state.timestamp
        ??
        state.last_update;


    if (!timestamp) {
        return null;
    }


    const updated =
        parseDate(
            timestamp
        );


    if (!updated) {
        return null;
    }


    return Math.max(
        0,
        (
            Date.now()
            -
            updated.getTime()
        )
        /
        1000
    );
}


/* ==========================================================
   STATE FRESHNESS
   ========================================================== */

function monitorStateFreshness() {

    const state =
        appState.dashboardState;


    if (!state) {
        return;
    }


    const age =
        getStateAgeSeconds(
            state
        );


    const stale =
        state.state_stale === true
        ||
        (
            age !== null
            &&
            age > 15
        );


    const element =
        byId(
            "dataFreshness"
        );


    if (!element) {
        return;
    }


    element.textContent =
        stale
            ? "STALE"
            : "LIVE";


    element.classList.toggle(
        "stale",
        stale
    );


    element.classList.toggle(
        "live",
        !stale
    );
}


function initializeFreshnessMonitor() {

    monitorStateFreshness();


    setInterval(
        monitorStateFreshness,
        2000
    );
}/* ==========================================================
   DASHBOARD HEALTH SUMMARY
   ========================================================== */

function cameraIsOnline(camera) {

    if (!camera) {
        return false;
    }


    const status =
        String(
            camera.status
            ??
            camera.camera_status
            ??
            ""
        )
            .trim()
            .toLowerCase();


    return (
        status === "online"
        ||
        status === "running"
        ||
        status === "active"
    );
}


function countOnlineCameras(cameras) {

    let count = 0;


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const camera =
            findCameraByIndex(
                cameras,
                index
            );


        if (
            cameraIsOnline(
                camera
            )
        ) {

            count += 1;
        }
    }


    return count;
}


function renderDashboardHealthSummary(state) {

    if (!state) {
        return;
    }


    const cameras =
        state.cameras
        || {};


    const onlineCameras =
        countOnlineCameras(
            cameras
        );


    const jamSummary =
        getJamSystemSummary(
            cameras
        );


    setText(
        "onlineCameras",
        formatInteger(
            onlineCameras
        )
    );


    setText(
        "dashboardActiveJamCount",
        formatInteger(
            jamSummary.activeJams
        )
    );
}


/* ==========================================================
   SETTINGS
   ========================================================== */

function initializeSettings() {

    const autoRefreshToggle =
        byId(
            "autoRefreshToggle"
        );


    if (autoRefreshToggle) {

        autoRefreshToggle.addEventListener(
            "change",
            event => {

                if (
                    event.target.checked
                ) {

                    startRefreshLoop();
                }

                else {

                    stopRefreshLoop();
                }
            }
        );
    }


    const diagnosticsButton =
        byId(
            "jamDiagnosticsButton"
        );


    if (diagnosticsButton) {

        diagnosticsButton.addEventListener(
            "click",
            () => {

                logJamDiagnostics();
            }
        );
    }
}


/* ==========================================================
   CAMERA STREAM REFRESH
   ========================================================== */

function refreshCameraStreams() {

    const timestamp =
        Date.now();


    for (
        let index = 1;
        index <= CAMERA_COUNT;
        index += 1
    ) {

        const feedContainer =
            byId(
                `liveCamera${index}Feed`
            );


        if (!feedContainer) {
            continue;
        }


        const image =
            feedContainer.querySelector(
                "img"
            );


        if (!image) {
            continue;
        }


        const cameraName =
            `Camera ${index}`;


        image.src =
            `${API_BASE}/live/${encodeURIComponent(
                cameraName
            )}?t=${timestamp}`;
    }
}


/* ==========================================================
   LIVE MONITOR CONTROLS
   ========================================================== */

function initializeLiveMonitorControls() {

    const refreshButton =
        byId(
            "refreshStreamsButton"
        );


    if (!refreshButton) {
        return;
    }


    refreshButton.addEventListener(
        "click",
        () => {

            refreshCameraStreams();
        }
    );
}


/* ==========================================================
   JAM PAGE REFRESH
   ========================================================== */

function refreshJamPage() {

    const cameras =
        appState
            .dashboardState
            ?.cameras
        || {};


    renderJamMonitoring(
        cameras
    );


    return getJamSystemSummary(
        cameras
    );
}


/* ==========================================================
   INITIAL LOAD
   ========================================================== */

async function initialLoad() {

    try {

        /*
        ------------------------------------------------------
        /state is the primary dashboard source.

        It contains camera runtime state including:
        - counts
        - FPS
        - camera status
        - jam detection enabled
        - jam status
        - jam warning
        - jam detected
        - active jam count
        - active jam track IDs
        - jam track information
        ------------------------------------------------------
        */

        await loadDashboardState();

    }

    catch (error) {

        console.error(
            "Initial dashboard state load failed:",
            error
        );
    }


    /*
    ----------------------------------------------------------
    PAGE-SPECIFIC DATA

    These calls are intentionally isolated so failure of one
    endpoint does not prevent the dashboard from starting.
    ----------------------------------------------------------
    */

    try {

        if (
            appState.currentPage
            === "production"
        ) {

            await loadProduction();
        }


        else if (
            appState.currentPage
            === "analytics"
            ||
            appState.currentPage
            === "dashboard"
        ) {

            await loadAnalytics();
        }


        else if (
            appState.currentPage
            === "events"
        ) {

            await loadEvents();
        }


        else if (
            appState.currentPage
            === "cameras"
        ) {

            await loadCameraConfig();
        }


        else if (
            appState.currentPage
            === "jam-monitor"
        ) {

            refreshJamPage();
        }

    }

    catch (error) {

        console.error(
            "Initial page-specific load failed:",
            error
        );
    }
}


/* ==========================================================
   APPLICATION INITIALIZATION
   ========================================================== */

async function initializeDashboard() {

    console.log(
        "=================================================="
    );

    console.log(
        "FillPac AI Dashboard"
    );

    console.log(
        "Initializing frontend..."
    );

    console.log(
        "=================================================="
    );


    /* ------------------------------------------------------
       NAVIGATION
       ------------------------------------------------------ */

    initializeNavigation();


    /* ------------------------------------------------------
       CLOCK
       ------------------------------------------------------ */

    initializeClock();


    /* ------------------------------------------------------
       LAST UPDATE
       ------------------------------------------------------ */

    initializeLastUpdateIndicator();


    /* ------------------------------------------------------
       NETWORK LISTENERS
       ------------------------------------------------------ */

    initializeNetworkListeners();


    /* ------------------------------------------------------
       PAGE VISIBILITY
       ------------------------------------------------------ */

    initializeVisibilityListener();


    /* ------------------------------------------------------
       KEYBOARD SHORTCUTS
       ------------------------------------------------------ */

    initializeKeyboardShortcuts();


    /* ------------------------------------------------------
       REFRESH BUTTON
       ------------------------------------------------------ */

    initializeRefreshButton();


    /* ------------------------------------------------------
       EVENT CONTROLS
       ------------------------------------------------------ */

    initializeEventControls();


    /* ------------------------------------------------------
       CAMERA CONTROLS
       ------------------------------------------------------ */

    initializeCameraControls();


    /* ------------------------------------------------------
       LIVE STREAMS
       ------------------------------------------------------ */

    initializeLiveStreams();


    initializeLiveMonitorControls();


    /* ------------------------------------------------------
       SETTINGS
       ------------------------------------------------------ */

    initializeSettings();


    /* ------------------------------------------------------
       SOCKET.IO
       ------------------------------------------------------ */

    initializeSocket();


    /* ------------------------------------------------------
       STATE FRESHNESS
       ------------------------------------------------------ */

    initializeFreshnessMonitor();


    /* ------------------------------------------------------
       DETERMINE INITIAL PAGE
       ------------------------------------------------------ */

    const initialActiveItem =
        document.querySelector(
            ".sidebar-item.active[data-page]"
        );


    if (
        initialActiveItem
        &&
        initialActiveItem.dataset.page
    ) {

        appState.currentPage =
            initialActiveItem.dataset.page;
    }


    updatePageHeader(
        appState.currentPage
    );


    /* ------------------------------------------------------
       INITIAL DATA
       ------------------------------------------------------ */

    await initialLoad();


    /* ------------------------------------------------------
       PERIODIC REST REFRESH
       ------------------------------------------------------ */

    startRefreshLoop();


    console.log(
        "=================================================="
    );

    console.log(
        "FillPac AI Dashboard initialized successfully."
    );

    console.log(
        "Current page:",
        appState.currentPage
    );

    console.log(
        "Refresh interval:",
        `${REFRESH_INTERVAL_MS} ms`
    );

    console.log(
        "=================================================="
    );
}


/* ==========================================================
   GLOBAL JAVASCRIPT ERROR HANDLER
   ========================================================== */

window.addEventListener(
    "error",
    event => {

        console.error(
            "Dashboard JavaScript error:",
            event.error
            ??
            event.message
        );
    }
);


/* ==========================================================
   UNHANDLED PROMISE ERROR
   ========================================================== */

window.addEventListener(
    "unhandledrejection",
    event => {

        console.error(
            "Unhandled dashboard promise rejection:",
            event.reason
        );
    }
);


/* ==========================================================
   APPLICATION CLEANUP
   ========================================================== */

window.addEventListener(
    "beforeunload",
    () => {

        /* --------------------------------------------------
           STOP REST REFRESH
           -------------------------------------------------- */

        stopRefreshLoop();


        /* --------------------------------------------------
           DISCONNECT SOCKET
           -------------------------------------------------- */

        if (
            appState.socket
        ) {

            try {

                appState.socket.disconnect();

            }

            catch (error) {

                console.warn(
                    "Socket cleanup failed:",
                    error
                );
            }
        }
    }
);


/* ==========================================================
   DOM READY
   ========================================================== */

document.addEventListener(
    "DOMContentLoaded",
    () => {

        initializeDashboard()
            .catch(
                error => {

                    console.error(
                        "FillPac dashboard initialization failed:",
                        error
                    );


                    updateSystemStatus(
                        "offline"
                    );
                }
            );
    }
);


/* ==========================================================
   DEBUG / DEVELOPMENT INTERFACE
   ========================================================== */

/*
============================================================
Browser Console Commands
============================================================

Open:

    F12
    â?? Console


1. Complete dashboard state

    FillPacDashboard.state()


2. All camera jam states

    FillPacDashboard.jams()


3. Camera 1 jam tracks

    FillPacDashboard.jamTracks(1)


4. Camera 2 jam tracks

    FillPacDashboard.jamTracks(2)


5. Camera 3 jam tracks

    FillPacDashboard.jamTracks(3)


6. Camera 4 jam tracks

    FillPacDashboard.jamTracks(4)


7. Force state refresh

    FillPacDashboard.refresh()


8. Refresh jam UI

    FillPacDashboard.refreshJams()


9. Detailed jam diagnostics

    FillPacDashboard.diagnostics()

============================================================
*/


window.FillPacDashboard = {

    /* ------------------------------------------------------
       COMPLETE STATE
       ------------------------------------------------------ */

    state() {

        return (
            appState.dashboardState
            ??
            null
        );
    },


    /* ------------------------------------------------------
       JAM SUMMARY
       ------------------------------------------------------ */

    jams() {

        const cameras =
            appState
                .dashboardState
                ?.cameras
            || {};


        const result = {};


        for (
            let index = 1;
            index <= CAMERA_COUNT;
            index += 1
        ) {

            const camera =
                findCameraByIndex(
                    cameras,
                    index
                );


            result[
                `Camera ${index}`
            ] =
                getJamCameraSummary(
                    camera
                );
        }


        console.table(
            Object.entries(
                result
            )
                .map(
                    (
                        [
                            camera,
                            value
                        ]
                    ) => ({

                        camera,

                        enabled:
                            value.enabled,

                        status:
                            value.status,

                        activeJams:
                            value.activeCount,

                        trackIds:
                            value.trackIds.join(
                                ", "
                            )
                    })
                )
        );


        return result;
    },


    /* ------------------------------------------------------
       INDIVIDUAL CAMERA JAM TRACKS
       ------------------------------------------------------ */

    jamTracks(
        cameraIndex = 1
    ) {

        const index =
            Math.min(
                CAMERA_COUNT,
                Math.max(
                    1,
                    Math.round(
                        safeNumber(
                            cameraIndex,
                            1
                        )
                    )
                )
            );


        const camera =
            findCameraByIndex(

                appState
                    .dashboardState
                    ?.cameras
                || {},

                index
            );


        const tracks =
            getJamTracks(
                camera
            );


        console.table(
            tracks.map(
                track => ({

                    trackId:
                        getJamTrackId(
                            track
                        ),

                    status:
                        getJamTrackState(
                            track
                        ),

                    speedPxS:
                        getJamTrackSpeed(
                            track
                        ),

                    distancePx:
                        getJamTrackDistance(
                            track
                        ),

                    stationarySeconds:
                        getJamTrackStationaryTime(
                            track
                        )
                })
            )
        );


        return tracks;
    },


    /* ------------------------------------------------------
       FORCE BACKEND REFRESH
       ------------------------------------------------------ */

    async refresh() {

        return await loadDashboardState();
    },


    /* ------------------------------------------------------
       FORCE JAM UI REFRESH
       ------------------------------------------------------ */

    refreshJams() {

        return refreshJamPage();
    },


    /* ------------------------------------------------------
       JAM DIAGNOSTICS
       ------------------------------------------------------ */

    diagnostics() {

        logJamDiagnostics();
    },


    /* ------------------------------------------------------
       JAM SYSTEM SUMMARY
       ------------------------------------------------------ */

    jamSummary() {

        return getJamSystemSummary(

            appState
                .dashboardState
                ?.cameras
            || {}
        );
    }
};


/* ==========================================================
   END OF FILE
   ========================================================== */
