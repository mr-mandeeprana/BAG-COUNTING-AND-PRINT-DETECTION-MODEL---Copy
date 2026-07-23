/*
==========================================================
FillPac AI
Production Vision Dashboard
Frontend JavaScript
==========================================================

Purpose
-------
- Connect to FillPac AI Socket.IO dashboard backend
- Receive real-time "dashboard_state" events
- Update production KPIs
- Update Camera 1-4 cards
- Update system health
- Update production charts
- Handle filters
- Handle refresh
- Handle fullscreen
- Export current dashboard data as CSV

Backend
-------
Default URL:
http://localhost:8000

Socket Event:
dashboard_state
==========================================================
*/


// ==========================================================
// CONFIGURATION
// ==========================================================

const DASHBOARD_SERVER = "http://localhost:8000";

const SOCKET_EVENT = "dashboard_state";

const MAX_CHART_POINTS = 30;


// ==========================================================
// APPLICATION STATE
// ==========================================================

let currentDashboardState = null;

let socket = null;

let productionChart = null;

let printChart = null;

let previousCameraState = {};

let recentEvents = [];


// ==========================================================
// DOM HELPERS
// ==========================================================

function getElement(id) {
    return document.getElementById(id);
}


function setText(id, value) {

    const element = getElement(id);

    if (element) {
        element.textContent = value;
    }

}


function safeNumber(value) {

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return 0;
    }

    return number;

}


function formatNumber(value) {

    return safeNumber(value).toLocaleString();

}


// ==========================================================
// INITIALIZE DASHBOARD
// ==========================================================

document.addEventListener(
    "DOMContentLoaded",
    () => {

        initializeClock();

        initializeCharts();

        initializeSocket();

        initializeControls();

        initializeSidebar();

        initializeDefaultDates();

        loadInitialState();

    }
);


// ==========================================================
// CLOCK
// ==========================================================

function initializeClock() {

    updateClock();

    setInterval(
        updateClock,
        1000
    );

}


function updateClock() {

    const now = new Date();


    const time = now.toLocaleTimeString(
        [],
        {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit"
        }
    );


    const date = now.toLocaleDateString(
        [],
        {
            day: "2-digit",
            month: "short",
            year: "numeric"
        }
    );


    setText(
        "currentTime",
        time
    );


    setText(
        "currentDate",
        date
    );

}


// ==========================================================
// INITIAL DEFAULT FILTER DATES
// ==========================================================

function initializeDefaultDates() {

    const endDate = new Date();

    const startDate = new Date();

    startDate.setHours(
        startDate.getHours() - 24
    );


    const startInput =
        getElement("startDate");

    const endInput =
        getElement("endDate");


    if (startInput) {

        startInput.value =
            formatDateTimeLocal(
                startDate
            );

    }


    if (endInput) {

        endInput.value =
            formatDateTimeLocal(
                endDate
            );

    }

}


function formatDateTimeLocal(date) {

    const offset =
        date.getTimezoneOffset();

    const localDate =
        new Date(
            date.getTime()
            - offset * 60000
        );

    return localDate
        .toISOString()
        .slice(
            0,
            16
        );

}


// ==========================================================
// LOAD INITIAL STATE USING REST
// ==========================================================

async function loadInitialState() {

    try {

        const response =
            await fetch(
                `${DASHBOARD_SERVER}/state`,
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const state =
            await response.json();


        updateDashboard(
            state
        );

    }

    catch (error) {

        console.warn(
            "Could not load initial dashboard state:",
            error
        );

        setSystemOffline();

    }

}


// ==========================================================
// SOCKET.IO
// ==========================================================

function initializeSocket() {

    if (
        typeof io
        === "undefined"
    ) {

        console.error(
            "Socket.IO client library is not available."
        );

        setText(
            "socketStatus",
            "Unavailable"
        );

        return;

    }


    socket = io(
        DASHBOARD_SERVER,
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


    // ======================================================
    // CONNECTED
    // ======================================================

    socket.on(
        "connect",
        () => {

            console.log(
                "Dashboard Socket.IO connected."
            );


            setText(
                "socketStatus",
                "Connected"
            );


            updateHealthIndicator(
                "socketStatus",
                true
            );

        }
    );


    // ======================================================
    // DASHBOARD STATE
    // ======================================================

    socket.on(
        SOCKET_EVENT,
        (state) => {

            updateDashboard(
                state
            );

        }
    );


    // ======================================================
    // DISCONNECTED
    // ======================================================

    socket.on(
        "disconnect",
        (reason) => {

            console.warn(
                "Dashboard Socket.IO disconnected:",
                reason
            );


            setText(
                "socketStatus",
                "Disconnected"
            );


            updateHealthIndicator(
                "socketStatus",
                false
            );

        }
    );


    // ======================================================
    // CONNECTION ERROR
    // ======================================================

    socket.on(
        "connect_error",
        (error) => {

            console.warn(
                "Dashboard Socket.IO connection error:",
                error.message
            );


            setText(
                "socketStatus",
                "Connection Error"
            );


            updateHealthIndicator(
                "socketStatus",
                false
            );

        }
    );

}


// ==========================================================
// MAIN DASHBOARD UPDATE
// ==========================================================

function updateDashboard(state) {

    if (
        !state
        ||
        typeof state
        !== "object"
    ) {

        return;

    }


    currentDashboardState =
        state;


    updateSystemStatus(
        state
    );


    updateKPIs(
        state
    );


    updateCameraCards(
        state.cameras || {}
    );


    updateSystemHealth(
        state.service_status || {}
    );


    updateCharts(
        state
    );


    detectCameraEvents(
        state.cameras || {}
    );

}


// ==========================================================
// SYSTEM STATUS
// ==========================================================

function updateSystemStatus(state) {

    const status =
        String(
            state.system_status
            || "offline"
        ).toLowerCase();


    const container =
        getElement(
            "systemStatus"
        );


    if (!container) {
        return;
    }


    container.classList.remove(
        "online",
        "offline"
    );


    if (
        status === "running"
        ||
        status === "online"
        ||
        status === "active"
    ) {

        container.classList.add(
            "online"
        );


        setText(
            "systemStatusText",
            "SYSTEM ONLINE"
        );

    }

    else {

        container.classList.add(
            "offline"
        );


        setText(
            "systemStatusText",
            status.toUpperCase()
        );

    }

}


function setSystemOffline() {

    const container =
        getElement(
            "systemStatus"
        );


    if (container) {

        container.classList.remove(
            "online"
        );


        container.classList.add(
            "offline"
        );

    }


    setText(
        "systemStatusText",
        "SYSTEM OFFLINE"
    );

}


// ==========================================================
// KPI UPDATE
// ==========================================================

function updateKPIs(state) {

    const total =
        safeNumber(
            state.total_count
        );


    const printed =
        safeNumber(
            state.total_printed_count
            ??
            state.total_printed_bags_count
        );


    const missing =
        safeNumber(
            state.total_missing_count
            ??
            state.total_not_printed_bags_count
        );


    setText(
        "totalBags",
        formatNumber(
            total
        )
    );


    setText(
        "printedBags",
        formatNumber(
            printed
        )
    );


    setText(
        "missingBags",
        formatNumber(
            missing
        )
    );


    // ======================================================
    // PRINT QUALITY
    // ======================================================

    const classifiedTotal =
        printed
        + missing;


    let quality =
        0;


    if (
        classifiedTotal
        > 0
    ) {

        quality =
            (
                printed
                /
                classifiedTotal
            )
            * 100;

    }


    setText(
        "printQuality",
        `${quality.toFixed(1)}%`
    );


    // ======================================================
    // ONLINE CAMERAS
    // ======================================================

    const cameras =
        state.cameras
        || {};


    const cameraList =
        Object.values(
            cameras
        );


    const online =
        cameraList.filter(
            camera =>
                String(
                    camera.status
                    || ""
                ).toLowerCase()
                === "online"
        ).length;


    const configuredCameraCount =
        cameraList.length > 0
            ? cameraList.length
            : 4;


    setText(
        "onlineCameras",
        `${online} / ${configuredCameraCount}`
    );

}


// ==========================================================
// CAMERA CARDS
// ==========================================================

function updateCameraCards(
    cameras
) {

    for (
        let cameraNumber = 1;
        cameraNumber <= 4;
        cameraNumber++
    ) {

        const cameraName =
            `Camera ${cameraNumber}`;


        const camera =
            cameras[cameraName]
            || {};


        updateSingleCamera(
            cameraNumber,
            camera
        );

    }

}


// ==========================================================
// SINGLE CAMERA
// ==========================================================

function updateSingleCamera(
    cameraNumber,
    camera
) {

    const count =
        safeNumber(
            camera.count
        );


    const printed =
        safeNumber(
            camera.printed_count
            ??
            camera.printed_bags_count
        );


    const missing =
        safeNumber(
            camera.missing_count
            ??
            camera.not_printed_bags_count
        );


    const fps =
        safeNumber(
            camera.fps
        );


    const status =
        String(
            camera.status
            || "offline"
        ).toLowerCase();


    // ======================================================
    // VALUES
    // ======================================================

    setText(
        `camera${cameraNumber}Count`,
        formatNumber(
            count
        )
    );


    setText(
        `camera${cameraNumber}Printed`,
        formatNumber(
            printed
        )
    );


    setText(
        `camera${cameraNumber}Missing`,
        formatNumber(
            missing
        )
    );


    setText(
        `camera${cameraNumber}Fps`,
        fps.toFixed(1)
    );


    // ======================================================
    // STATUS
    // ======================================================

    const statusElement =
        getElement(
            `camera${cameraNumber}Status`
        );


    if (
        statusElement
    ) {

        statusElement.classList.remove(
            "online",
            "offline"
        );


        if (
            status === "online"
            ||
            status === "running"
        ) {

            statusElement.classList.add(
                "online"
            );


            statusElement.textContent =
                "ONLINE";

        }

        else {

            statusElement.classList.add(
                "offline"
            );


            statusElement.textContent =
                status.toUpperCase();

        }

    }

}


// ==========================================================
// SYSTEM HEALTH
// ==========================================================

function updateSystemHealth(
    serviceStatus
) {

    const modelLoaded =
        Boolean(
            serviceStatus.model_loaded
        );


    const dashboardEnabled =
        serviceStatus.dashboard_enabled
        !== false;


    const elasticsearchConnected =
        Boolean(
            serviceStatus.elasticsearch_connected
        );


    // ======================================================
    // MODEL
    // ======================================================

    setText(
        "healthModel",
        modelLoaded
            ? "Loaded"
            : "Unavailable"
    );


    setText(
        "modelStatus",
        modelLoaded
            ? "Model Loaded"
            : "Model Offline"
    );


    updateHealthIndicator(
        "healthModel",
        modelLoaded
    );


    // ======================================================
    // DASHBOARD
    // ======================================================

    setText(
        "healthDashboard",
        dashboardEnabled
            ? "Enabled"
            : "Disabled"
    );


    updateHealthIndicator(
        "healthDashboard",
        dashboardEnabled
    );


    // ======================================================
    // ELASTICSEARCH
    // ======================================================

    setText(
        "healthElasticsearch",
        elasticsearchConnected
            ? "Connected"
            : "Disconnected"
    );


    updateHealthIndicator(
        "healthElasticsearch",
        elasticsearchConnected
    );

}


// ==========================================================
// HEALTH INDICATOR
// ==========================================================

function updateHealthIndicator(
    elementId,
    healthy
) {

    const element =
        getElement(
            elementId
        );


    if (!element) {
        return;
    }


    const healthItem =
        element.closest(
            ".health-item"
        );


    if (!healthItem) {
        return;
    }


    const dot =
        healthItem.querySelector(
            ".health-dot"
        );


    if (!dot) {
        return;
    }


    if (healthy) {

        dot.style.background =
            "#22c55e";

        dot.style.boxShadow =
            "0 0 0 4px rgba(34, 197, 94, 0.12)";

    }

    else {

        dot.style.background =
            "#ef4444";

        dot.style.boxShadow =
            "0 0 0 4px rgba(239, 68, 68, 0.12)";

    }

}


// ==========================================================
// CHART INITIALIZATION
// ==========================================================

function initializeCharts() {

    if (
        typeof Chart
        === "undefined"
    ) {

        console.warn(
            "Chart.js is unavailable."
        );

        return;

    }


    initializeProductionChart();

    initializePrintChart();

}


// ==========================================================
// PRODUCTION CHART
// ==========================================================

function initializeProductionChart() {

    const canvas =
        getElement(
            "productionChart"
        );


    if (!canvas) {
        return;
    }


    productionChart =
        new Chart(
            canvas,
            {

                type:
                    "line",

                data: {

                    labels:
                        [],

                    datasets: [

                        {

                            label:
                                "Total Bags",

                            data:
                                [],

                            borderWidth:
                                2,

                            tension:
                                0.35,

                            fill:
                                false,

                            pointRadius:
                                2

                        }

                    ]

                },

                options: {

                    responsive:
                        true,

                    maintainAspectRatio:
                        false,

                    animation:
                        false,

                    plugins: {

                        legend: {

                            display:
                                true,

                            position:
                                "top"

                        }

                    },

                    scales: {

                        y: {

                            beginAtZero:
                                true,

                            ticks: {

                                precision:
                                    0

                            }

                        }

                    }

                }

            }
        );

}


// ==========================================================
// PRINT CHART
// ==========================================================

function initializePrintChart() {

    const canvas =
        getElement(
            "printChart"
        );


    if (!canvas) {
        return;
    }


    printChart =
        new Chart(
            canvas,
            {

                type:
                    "doughnut",

                data: {

                    labels: [

                        "Printed",

                        "Not Printed"

                    ],

                    datasets: [

                        {

                            data: [
                                0,
                                0
                            ],

                            borderWidth:
                                0

                        }

                    ]

                },

                options: {

                    responsive:
                        true,

                    maintainAspectRatio:
                        false,

                    cutout:
                        "70%",

                    plugins: {

                        legend: {

                            position:
                                "bottom"

                        }

                    }

                }

            }
        );

}


// ==========================================================
// UPDATE CHARTS
// ==========================================================

function updateCharts(
    state
) {

    const total =
        safeNumber(
            state.total_count
        );


    const printed =
        safeNumber(
            state.total_printed_count
            ??
            state.total_printed_bags_count
        );


    const missing =
        safeNumber(
            state.total_missing_count
            ??
            state.total_not_printed_bags_count
        );


    // ======================================================
    // PRODUCTION TREND
    //
    // NOTE:
    // This is a live session trend.
    // Historical production trends should later come from
    // Elasticsearch.
    // ======================================================

    if (
        productionChart
    ) {

        const now =
            new Date()
                .toLocaleTimeString(
                    [],
                    {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit"
                    }
                );


        productionChart
            .data
            .labels
            .push(
                now
            );


        productionChart
            .data
            .datasets[0]
            .data
            .push(
                total
            );


        if (
            productionChart
                .data
                .labels
                .length
            >
            MAX_CHART_POINTS
        ) {

            productionChart
                .data
                .labels
                .shift();


            productionChart
                .data
                .datasets[0]
                .data
                .shift();

        }


        productionChart.update(
            "none"
        );

    }


    // ======================================================
    // PRINT QUALITY CHART
    // ======================================================

    if (
        printChart
    ) {

        printChart
            .data
            .datasets[0]
            .data =
            [
                printed,
                missing
            ];


        printChart.update(
            "none"
        );

    }

}


// ==========================================================
// DETECT NEW CAMERA EVENTS
// ==========================================================

function detectCameraEvents(
    cameras
) {

    Object.entries(
        cameras
    ).forEach(
        (
            [
                cameraName,
                camera
            ]
        ) => {

            const previous =
                previousCameraState[
                    cameraName
                ];


            if (
                previous
            ) {

                const currentCount =
                    safeNumber(
                        camera.count
                    );


                const previousCount =
                    safeNumber(
                        previous.count
                    );


                if (
                    currentCount
                    >
                    previousCount
                ) {

                    addRecentEvent(
                        cameraName,
                        camera
                    );

                }

            }


            previousCameraState[
                cameraName
            ] = {

                count:
                    camera.count,

                printed_count:
                    camera.printed_count,

                missing_count:
                    camera.missing_count,

                status:
                    camera.status

            };

        }
    );

}


// ==========================================================
// ADD RECENT EVENT
// ==========================================================

function addRecentEvent(
    cameraName,
    camera
) {

    const event = {

        time:
            new Date()
                .toLocaleTimeString(),

        camera:
            cameraName,

        count:
            safeNumber(
                camera.count
            ),

        printStatus:
            camera.print_status
            || "Unknown",

        fps:
            safeNumber(
                camera.fps
            ).toFixed(1),

        status:
            camera.status
            || "Unknown"

    };


    recentEvents.unshift(
        event
    );


    if (
        recentEvents.length
        > 100
    ) {

        recentEvents.pop();

    }


    renderRecentEvents();

}


// ==========================================================
// RENDER RECENT EVENTS
// ==========================================================

function renderRecentEvents() {

    const tableBody =
        getElement(
            "eventTableBody"
        );


    if (!tableBody) {
        return;
    }


    if (
        recentEvents.length
        === 0
    ) {

        tableBody.innerHTML = `

            <tr class="empty-row">

                <td colspan="6">

                    <div class="empty-state">

                        <i class="fa-solid fa-box-open"></i>

                        <span>
                            Waiting for production events...
                        </span>

                    </div>

                </td>

            </tr>

        `;

        return;

    }


    const selectedCamera =
        getElement(
            "cameraFilter"
        )?.value
        || "all";


    const selectedPrint =
        getElement(
            "printFilter"
        )?.value
        || "all";


    const limit =
        safeNumber(
            getElement(
                "recordLimit"
            )?.value
        )
        || 100;


    let filtered =
        recentEvents;


    if (
        selectedCamera
        !== "all"
    ) {

        filtered =
            filtered.filter(
                event =>
                    event.camera
                    === selectedCamera
            );

    }


    if (
        selectedPrint
        !== "all"
    ) {

        filtered =
            filtered.filter(
                event => {

                    const status =
                        String(
                            event.printStatus
                        )
                        .toLowerCase();


                    if (
                        selectedPrint
                        === "printed"
                    ) {

                        return (
                            status
                            === "printed"
                            ||
                            status
                            === "print detected"
                        );

                    }


                    if (
                        selectedPrint
                        === "missing"
                    ) {

                        return (
                            status
                            === "missing"
                            ||
                            status
                            === "not printed"
                        );

                    }


                    return (
                        status
                        === "unknown"
                    );

                }
            );

    }


    filtered =
        filtered.slice(
            0,
            limit
        );


    tableBody.innerHTML =
        filtered
            .map(
                event => `

                    <tr>

                        <td>
                            ${escapeHtml(event.time)}
                        </td>

                        <td>
                            ${escapeHtml(event.camera)}
                        </td>

                        <td>
                            ${formatNumber(event.count)}
                        </td>

                        <td>
                            ${escapeHtml(event.printStatus)}
                        </td>

                        <td>
                            ${escapeHtml(event.fps)}
                        </td>

                        <td>
                            ${escapeHtml(event.status)}
                        </td>

                    </tr>

                `
            )
            .join("");

}


// ==========================================================
// CONTROLS
// ==========================================================

function initializeControls() {

    // ======================================================
    // REFRESH
    // ======================================================

    getElement(
        "refreshButton"
    )?.addEventListener(
        "click",
        () => {

            loadInitialState();

        }
    );


    // ======================================================
    // APPLY FILTERS
    // ======================================================

    getElement(
        "applyFilters"
    )?.addEventListener(
        "click",
        () => {

            applyFilters();

        }
    );


    // ======================================================
    // RESET FILTERS
    // ======================================================

    getElement(
        "resetFilters"
    )?.addEventListener(
        "click",
        () => {

            resetFilters();

        }
    );


    // ======================================================
    // EXPORT
    // ======================================================

    getElement(
        "exportButton"
    )?.addEventListener(
        "click",
        () => {

            exportDashboardCSV();

        }
    );


    // ======================================================
    // FULLSCREEN
    // ======================================================

    getElement(
        "fullscreenButton"
    )?.addEventListener(
        "click",
        () => {

            toggleFullscreen();

        }
    );

}


// ==========================================================
// APPLY FILTERS
// ==========================================================

function applyFilters() {

    /*
    IMPORTANT:

    Current filters affect the live recent-events table.

    Date range and shift filters require historical production
    data from Elasticsearch.

    They should not artificially modify current live counters.
    */

    renderRecentEvents();

}


// ==========================================================
// RESET FILTERS
// ==========================================================

function resetFilters() {

    const cameraFilter =
        getElement(
            "cameraFilter"
        );


    const printFilter =
        getElement(
            "printFilter"
        );


    const shiftFilter =
        getElement(
            "shiftFilter"
        );


    const recordLimit =
        getElement(
            "recordLimit"
        );


    if (
        cameraFilter
    ) {

        cameraFilter.value =
            "all";

    }


    if (
        printFilter
    ) {

        printFilter.value =
            "all";

    }


    if (
        shiftFilter
    ) {

        shiftFilter.value =
            "all";

    }


    if (
        recordLimit
    ) {

        recordLimit.value =
            "100";

    }


    initializeDefaultDates();

    renderRecentEvents();

}


// ==========================================================
// SIDEBAR
// ==========================================================

function initializeSidebar() {

    const items =
        document.querySelectorAll(
            ".sidebar-item"
        );


    items.forEach(
        item => {

            item.addEventListener(
                "click",
                () => {

                    items.forEach(
                        sidebarItem => {

                            sidebarItem
                                .classList
                                .remove(
                                    "active"
                                );

                        }
                    );


                    item
                        .classList
                        .add(
                            "active"
                        );

                }
            );

        }
    );

}


// ==========================================================
// FULLSCREEN
// ==========================================================

async function toggleFullscreen() {

    try {

        if (
            !document.fullscreenElement
        ) {

            await document
                .documentElement
                .requestFullscreen();

        }

        else {

            await document
                .exitFullscreen();

        }

    }

    catch (error) {

        console.warn(
            "Fullscreen operation failed:",
            error
        );

    }

}


// ==========================================================
// EXPORT DASHBOARD CSV
// ==========================================================

function exportDashboardCSV() {

    if (
        !currentDashboardState
    ) {

        console.warn(
            "No dashboard data available for export."
        );

        return;

    }


    const rows = [

        [
            "Camera",
            "Total Count",
            "Printed",
            "Not Printed",
            "FPS",
            "Status",
            "Print Status",
            "Updated At"
        ]

    ];


    const cameras =
        currentDashboardState
            .cameras
        || {};


    Object.entries(
        cameras
    ).forEach(
        (
            [
                cameraName,
                camera
            ]
        ) => {

            rows.push(
                [

                    cameraName,

                    safeNumber(
                        camera.count
                    ),

                    safeNumber(
                        camera.printed_count
                        ??
                        camera.printed_bags_count
                    ),

                    safeNumber(
                        camera.missing_count
                        ??
                        camera.not_printed_bags_count
                    ),

                    safeNumber(
                        camera.fps
                    ),

                    camera.status
                    || "",

                    camera.print_status
                    || "",

                    camera.updated_at
                    || ""

                ]
            );

        }
    );


    const csv =
        rows
            .map(
                row =>
                    row
                        .map(
                            escapeCSV
                        )
                        .join(",")
            )
            .join("\n");


    const blob =
        new Blob(
            [
                csv
            ],
            {
                type:
                    "text/csv;charset=utf-8;"
            }
        );


    const url =
        URL.createObjectURL(
            blob
        );


    const link =
        document.createElement(
            "a"
        );


    link.href =
        url;


    link.download =
        `fillpac-dashboard-${createFileTimestamp()}.csv`;


    document.body
        .appendChild(
            link
        );


    link.click();


    document.body
        .removeChild(
            link
        );


    URL.revokeObjectURL(
        url
    );

}


// ==========================================================
// CSV ESCAPE
// ==========================================================

function escapeCSV(
    value
) {

    const stringValue =
        String(
            value
            ?? ""
        );


    if (
        stringValue.includes(",")
        ||
        stringValue.includes("\"")
        ||
        stringValue.includes("\n")
    ) {

        return (
            "\""
            +
            stringValue.replace(
                /"/g,
                "\"\""
            )
            +
            "\""
        );

    }


    return stringValue;

}


// ==========================================================
// HTML ESCAPE
// ==========================================================

function escapeHtml(
    value
) {

    const div =
        document.createElement(
            "div"
        );


    div.textContent =
        String(
            value
            ?? ""
        );


    return div.innerHTML;

}


// ==========================================================
// FILE TIMESTAMP
// ==========================================================

function createFileTimestamp() {

    const now =
        new Date();


    return now
        .toISOString()
        .replace(
            /[:.]/g,
            "-"
        );

}