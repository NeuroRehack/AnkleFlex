/**
 * AnkleFlex — real-time weight display + history view
 * Connects to /stream (SSE) and updates Chart.js charts.
 */

"use strict";

// ── Constants (must match app.py) ─────────────────────────────────────────
const THRESHOLD_UP   = 500;
const THRESHOLD_DOWN = -500;

// ── State ────────────────────────────────────────────────────────────────
let appState = { weight: 0, min_weight: 0, max_weight: 0, emulation: false, history: [], above_count: 0, below_count: 0 };
let axisFlipped = false;
let scale = 1.0;
let chart = null;
let historyChart = null;
let historyYRange = 500;
let tareFeedbackTimer = null;

// Returns the value with axis direction and scale applied.
function displayValue(v) { return (axisFlipped ? -v : v) * scale; }

// ── Custom Chart.js plugin: horizontal reference lines ────────────────────────
const refLinesPlugin = {
  id: "refLines",
  afterDraw(ch) {
    const { ctx, chartArea, scales } = ch;
    const yScale = scales.y;

    // Always draw a solid zero baseline
    const zeroPx = yScale.getPixelForValue(0);
    ctx.save();
    ctx.strokeStyle = "rgba(0,0,0,1)";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(chartArea.left, zeroPx);
    ctx.lineTo(chartArea.right, zeroPx);
    ctx.stroke();
    ctx.restore();

    const hasMeasured = appState.max_weight !== 0 || appState.min_weight !== 0;
    if (!hasMeasured) return;

    function drawLine(value, color, label) {
      const yPx = yScale.getPixelForValue(value);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.setLineDash([10, 5]);
      ctx.beginPath();
      ctx.moveTo(chartArea.left, yPx);
      ctx.lineTo(chartArea.right, yPx);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "bold 13px 'Segoe UI', sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(`${label} ${value.toFixed(1)} kg`, chartArea.right - 6, yPx - 5);
      ctx.restore();
    }

    drawLine(displayValue(appState.max_weight), "#e63946", "MAX");
    if (appState.min_weight !== 0) {
      drawLine(displayValue(appState.min_weight), "#f4a261", "MIN");
    }
  },
};

// ── Chart initialisation ──────────────────────────────────────────────────────
function initChart() {
  const ctx = document.getElementById("weightChart").getContext("2d");
  chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: [""],
      datasets: [
        {
          data: [0],
          backgroundColor: "rgba(67, 97, 238, 0.82)",
          borderColor: "rgb(67, 97, 238)",
          borderWidth: 2,
          borderRadius: 6,
          borderSkipped: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { display: false },
          border: { display: false },
        },
        y: {
          min: -1,
          max: 10,
          title: { display: false },
          ticks: { display: false },
          grid: { color: "rgba(0,0,0,0.06)" },
        },
      },
    },
    plugins: [refLinesPlugin],
  });
}

// ── Chart update ─────────────────────────────────────────────────────────────
function updateChart() {
  if (!chart) return;
  const w = displayValue(appState.weight);
  const dMax = displayValue(appState.max_weight);
  const dMin = displayValue(appState.min_weight);
  const peak = Math.max(Math.abs(dMax), Math.abs(dMin), 1);
  const yMax = Math.ceil(Math.max(dMax, dMin, w, 0) * 1.25 || peak * 1.25);
  const yMin = Math.floor(Math.min(dMax, dMin, w, 0) * 1.25);

  chart.data.datasets[0].data = [w];
  chart.options.scales.y.max = yMax;
  chart.options.scales.y.min = yMin;
  chart.update("none");  // skip transition for live data
  repositionWeightDisplay();
}

// ── DOM updates ───────────────────────────────────────────────────────────────
function repositionWeightDisplay() {
  if (!chart) return;
  const el = document.getElementById("weight-display");
  const yScale = chart.scales.y;
  const zeroPx = yScale.getPixelForValue(0);
  const container = document.getElementById("chart-container");
  // Offset from the top of #chart-container (which has 12px padding)
  const containerTop = container.getBoundingClientRect().top;
  const chartTop = chart.chartArea.top;
  // zeroPx is relative to canvas; canvas starts at chartTop inside container
  const offsetFromContainerTop = zeroPx + chartTop - chart.chartArea.top + 12;
  const elHeight = el.offsetHeight || 36;
  el.style.top = (zeroPx - elHeight / 2) + "px";
}

function updateWeightDisplay() {
  document.getElementById("weight-value").textContent =
    displayValue(appState.weight).toFixed(1);
}

function updateEmulationPanel() {
  const panel = document.getElementById("emulation-panel");
  panel.style.display = appState.emulation ? "flex" : "none";
}

function toggleEmulationExpand() {
  document.getElementById("emulation-panel").classList.toggle("expanded");
  const toggle = document.getElementById("emulation-toggle");
  const expanded = document.getElementById("emulation-panel").classList.contains("expanded");
  toggle.textContent = expanded ? "▲ collapse" : "▼ expand";
}

function setConnected(connected) {
  const dot   = document.getElementById("status-dot");
  const label = document.getElementById("status-label");
  if (connected) {
    dot.className   = "dot connected";
    label.textContent = "Connected";
  } else {
    dot.className   = "dot disconnected";
    label.textContent = "Reconnecting…";
  }
}

// ── SSE connection ────────────────────────────────────────────────────────────
function connectStream() {
  const es = new EventSource("/stream");

  es.addEventListener("open", () => setConnected(true));
  es.addEventListener("error", () => setConnected(false));
  es.addEventListener("message", (event) => {
    try {
      appState = JSON.parse(event.data);
    } catch {
      return;
    }
    updateWeightDisplay();
    updateChart();
    updateEmulationPanel();
    if (!document.getElementById("view-history").hidden) {
      updateHistoryChart(appState.history);
    }
    updateThresholdCounters(appState.above_count, appState.below_count);
  });
}

// ── Navigation / routing ────────────────────────────────────────────────────
function showView(hash) {
  const isHistory = hash === "#history";
  document.getElementById("view-live").hidden    = isHistory;
  document.getElementById("view-history").hidden = !isHistory;
  document.getElementById("nav-live").classList.toggle("active", !isHistory);
  document.getElementById("nav-history").classList.toggle("active", isHistory);
  if (isHistory && historyChart) {
    // Force a resize in case the canvas was hidden during init
    historyChart.resize();
    updateHistoryChart(appState.history);
  }
}

// ── API calls ────────────────────────────────────────────────────────────────
function tare() {
  fetch("/tare", { method: "POST" })
    .then((r) => r.json())
    .then(() => showTareFeedback())
    .catch((err) => console.error("Tare failed:", err));
}

function showTareFeedback() {
  const el = document.getElementById("tare-feedback");
  const now = new Date();
  const hms = now.toTimeString().slice(0, 8);
  el.textContent = `Tared at ${hms}`;
  el.classList.remove("fade-out");
  clearTimeout(tareFeedbackTimer);
  tareFeedbackTimer = setTimeout(() => el.classList.add("fade-out"), 2500);
}

function setEmulatedWeight(value) {
  const v = parseFloat(value);
  document.getElementById("slider-value").textContent = v.toFixed(1);
  fetch("/emulation/weight", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weight: v }),
  }).catch((err) => console.error("Set emulated weight failed:", err));
}

// ── Axis flip ─────────────────────────────────────────────────────────────────
function toggleAxisFlip(checked) {
  axisFlipped = checked;
  updateWeightDisplay();
  updateChart();
}

// ── Scale ──────────────────────────────────────────────────────────────────────
function setScale(value) {
  const v = Math.max(0.1, Math.min(20, parseFloat(value) || 1));
  scale = v;
  syncScaleControls();
  updateWeightDisplay();
  updateChart();
}

function syncScaleControls() {
  document.getElementById("scale-slider").value = scale;
  document.getElementById("scale-slider-value").textContent = scale.toFixed(1) + "×";
}

function stepScale(delta) {
  setScale(Math.round((scale + delta) * 10) / 10);
}

// ── History chart ────────────────────────────────────────────────────────────
const historyThresholdPlugin = {
  id: "historyThresholds",
  afterDraw(ch) {
    const { ctx, chartArea, scales } = ch;
    const yScale = scales.y;

    function drawThreshold(value, color, label) {
      if (value < yScale.min || value > yScale.max) return;
      const yPx = yScale.getPixelForValue(value);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 4]);
      ctx.beginPath();
      ctx.moveTo(chartArea.left, yPx);
      ctx.lineTo(chartArea.right, yPx);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "bold 11px 'Segoe UI', sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(label, chartArea.right - 4, yPx - 4);
      ctx.restore();
    }

    // Shaded zones
    function drawZone(yTop, yBottom, color) {
      const top    = Math.max(yScale.getPixelForValue(yTop),    chartArea.top);
      const bottom = Math.min(yScale.getPixelForValue(yBottom), chartArea.bottom);
      if (bottom <= top) return;
      ctx.save();
      ctx.fillStyle = color;
      ctx.fillRect(chartArea.left, top, chartArea.right - chartArea.left, bottom - top);
      ctx.restore();
    }

    drawZone(yScale.max, THRESHOLD_UP,   "rgba(45,198,83,0.07)");
    drawZone(THRESHOLD_DOWN, yScale.min, "rgba(67,97,238,0.07)");
    drawThreshold(THRESHOLD_UP,   "rgba(45,198,83,0.8)",  `+${THRESHOLD_UP}`);
    drawThreshold(THRESHOLD_DOWN, "rgba(67,97,238,0.8)", `${THRESHOLD_DOWN}`);
  },
};

function initHistoryChart() {
  const ctx = document.getElementById("historyChart").getContext("2d");
  historyChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        data: [],
        borderColor: "#2dc653",
        backgroundColor: "rgba(45,198,83,0.10)",
        borderWidth: 2.5,
        pointRadius: 3,
        pointBackgroundColor: "#2dc653",
        fill: false,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: {
          ticks: {
            maxTicksLimit: 6,
            maxRotation: 0,
            font: { size: 10 },
            color: "#6c757d",
          },
          grid: { display: false },
        },
        y: {
          min: -historyYRange,
          max:  historyYRange,
          ticks: { font: { size: 10 }, color: "#6c757d" },
          grid: { color: "rgba(0,0,0,0.05)" },
        },
      },
    },
    plugins: [historyThresholdPlugin],
  });
}

function updateHistoryChart(history) {
  if (!historyChart || !history) return;
  historyChart.data.labels              = history.map(s => s.t);
  historyChart.data.datasets[0].data    = history.map(s => s.w);
  historyChart.options.scales.y.min     = -historyYRange;
  historyChart.options.scales.y.max     =  historyYRange;
  historyChart.update("none");
}

function updateThresholdCounters(above, below) {
  document.getElementById("above-count").textContent = above ?? 0;
  document.getElementById("below-count").textContent = below ?? 0;
}

// ── Y-Range stepper (History View) ──────────────────────────────────────────
function stepHistoryYRange(delta) {
  historyYRange = Math.min(3000, Math.max(100, historyYRange + delta));
  document.getElementById("yrange-value").textContent = historyYRange;
  updateHistoryChart(appState.history);
}

// ── Boot ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initChart();
  initHistoryChart();
  showView(window.location.hash || "#live");
  window.addEventListener("hashchange", () => showView(window.location.hash));
  connectStream();
});
