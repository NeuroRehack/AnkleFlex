/**
 * AnkleFlex — real-time weight display + history view
 * Connects to /stream (SSE) and updates Chart.js charts.
 */

"use strict";

// ── Constants (must match app.py) ─────────────────────────────────────────
const THRESHOLD_UP   = 30;
const THRESHOLD_DOWN = -30;

// ── State ────────────────────────────────────────────────────────────────
let appState = { weight: 0, min_weight: 0, max_weight: 0, emulation: false, history: [], above_count: 0, below_count: 0 };
let axisFlipped = false;
let scale = 1.0;
let chart = null;
let graphChart = null;
let graphYRange = 45;
let thresholdUp = THRESHOLD_UP;
let graphXRangeSec = 10; // Time-based window in seconds
let thresholdDown = THRESHOLD_DOWN;
let showThresholds = true;
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
    if (document.body.dataset.view === "graph" && graphChart) {
      updateGraphChart(appState.history);
      updateXRangeLabel();
    }
  });
}

// ── Navigation / routing ────────────────────────────────────────────────────
function showView(hash) {
  const view = hash === "#graph" || hash === "#history"
    ? "graph"
    : hash === "#bar" || hash === "#live"
      ? "bar"
      : "bar";
  document.body.dataset.view = view;
  document.getElementById("nav-bar-view").classList.toggle("active", view === "bar");
  document.getElementById("nav-graph-view").classList.toggle("active", view === "graph");

  if (view === "graph") {
    if (!graphChart) {
      initGraphChart();
    }
    graphChart.resize();
    updateGraphChart(appState.history);
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
  if (graphChart && document.body.dataset.view === "graph") {
    updateGraphChart(appState.history);
  }
}

function setGraphYRange(value) {
  graphYRange = Math.min(100, Math.max(10, parseInt(value, 10)));
  document.getElementById("yrange-value").textContent = graphYRange;
  document.getElementById("yrange-slider").value = graphYRange;
  updateGraphChart(appState.history);
}

function toggleShowThresholds(checked) {
  showThresholds = !!checked;
  updateGraphChart(appState.history);
}

function setThresholdUp(value) {
  let up = parseFloat(value);
  if (isNaN(up)) up = thresholdUp;
  if (up < thresholdDown) {
    up = thresholdDown;
  }
  thresholdUp = up;
  document.getElementById("upper-threshold").value = thresholdUp;
  if (thresholdDown > thresholdUp) {
    thresholdDown = thresholdUp;
    document.getElementById("lower-threshold").value = thresholdDown;
  }
  // Send to backend
  fetch("/thresholds", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upper: thresholdUp, lower: thresholdDown })
  });
  updateGraphChart(appState.history);
}

function setThresholdDown(value) {
  let down = parseFloat(value);
  if (isNaN(down)) down = thresholdDown;
  if (down > thresholdUp) {
    down = thresholdUp;
  }
  thresholdDown = down;
  document.getElementById("lower-threshold").value = thresholdDown;
  if (thresholdUp < thresholdDown) {
    thresholdUp = thresholdDown;
    document.getElementById("upper-threshold").value = thresholdUp;
  }
  // Send to backend
  fetch("/thresholds", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upper: thresholdUp, lower: thresholdDown })
  });
  updateGraphChart(appState.history);
}

// ── Graph chart ────────────────────────────────────────────────────────────
const graphThresholdPlugin = {
  id: "graphThresholds",
  afterDraw(ch) {
    if (!showThresholds) return;
    const { ctx, chartArea, scales } = ch;
    const yScale = scales.y;
    const displayedUpper = displayValue(thresholdUp);
    const displayedLower = displayValue(thresholdDown);
    const topZone = axisFlipped ? displayedLower : displayedUpper;
    const bottomZone = axisFlipped ? displayedUpper : displayedLower;

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

    function drawZone(yTop, yBottom, color) {
      const top    = Math.max(yScale.getPixelForValue(yTop),    chartArea.top);
      const bottom = Math.min(yScale.getPixelForValue(yBottom), chartArea.bottom);
      if (bottom <= top) return;
      ctx.save();
      ctx.fillStyle = color;
      ctx.fillRect(chartArea.left, top, chartArea.right - chartArea.left, bottom - top);
      ctx.restore();
    }

    drawZone(yScale.max, topZone,   "rgba(90,90,90,0.08)");
    drawZone(bottomZone, yScale.min, "rgba(90,90,90,0.08)");
    drawThreshold(displayedUpper, "rgba(90,90,90,0.8)",  `+${thresholdUp}`);
    drawThreshold(displayedLower, "rgba(90,90,90,0.8)", `${thresholdDown}`);
  },
};

function initGraphChart() {
  const ctx = document.getElementById("graphChart").getContext("2d");
  graphChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        data: [],
        borderColor: "rgb(67, 97, 238)",
        backgroundColor: "rgba(67, 97, 238, 0.12)",
        borderWidth: 2.5,
        pointRadius: 3,
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
          min: -graphYRange,
          max:  graphYRange,
          ticks: { font: { size: 10 }, color: "#6c757d" },
          grid: { color: "rgba(0,0,0,0.05)" },
        },
      },
    },
    plugins: [graphThresholdPlugin],
  });
}

function calculateGraphCounters(history) {
  let above = 0;
  let below = 0;
  if (!Array.isArray(history)) {
    return { above: 0, below: 0 };
  }

  for (const sample of history) {
    const value = sample.w;
    if (value > thresholdUp) {
      above += 1;
    }
    if (value < thresholdDown) {
      below += 1;
    }
  }

  return { above, below };
}

function updateGraphChart(history) {
  if (!graphChart || !history) return;
  // Only display samples within the most recent graphXRangeSec seconds
  let trimmed = history;
  if (history.length && history[history.length-1].ts) {
    const latestTs = history[history.length-1].ts;
    const windowMs = graphXRangeSec * 1000;
    let start = history.findIndex(s => s.ts && (latestTs - s.ts) <= windowMs);
    if (start === -1) start = 0;
    trimmed = history.slice(start);
  }
  graphChart.data.labels              = trimmed.map(s => s.t);
  graphChart.data.datasets[0].data    = trimmed.map(s => displayValue(s.w));
  graphChart.options.scales.y.min     = -graphYRange;
  graphChart.options.scales.y.max     =  graphYRange;
  graphChart.update("none");

  updateAllCounters();
}

function updateAllCounters() {
  document.getElementById("sequence-count").textContent = appState.sequence_count ?? 0;
}

// ── X-Range stepper (Graph View) ──────────────────────────────────────────
function stepGraphXRange(delta) {
  setGraphXRange(graphXRange + delta);
}

// ── X-Range setter (Graph View) ──────────────────────────────────────────
function setGraphXRange(value) {
  graphXRangeSec = Math.min(1200, Math.max(1, parseInt(value, 10)));
  updateXRangeLabel();
  document.getElementById('xrange-slider').value = graphXRangeSec;
  updateGraphChart(appState.history);
}

function stepGraphXRange(delta) {
  setGraphXRange(graphXRangeSec + delta);
}

function updateXRangeLabel() {
  // Always show the selected window (even if not enough data)
  const min = Math.floor(graphXRangeSec/60);
  const sec = graphXRangeSec%60;
  document.getElementById('xrange-value').textContent = `${min}:${sec.toString().padStart(2, '0')}`;
}

// ── Y-Range stepper (Graph View) ──────────────────────────────────────────
function stepGraphYRange(delta) {
  setGraphYRange(graphYRange + delta);
}

// ── Boot ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  // Fetch backend thresholds and set UI
  try {
    const resp = await fetch("/status");
    if (resp.ok) {
      const data = await resp.json();
      if (typeof data.threshold_up !== "undefined") {
        thresholdUp = data.threshold_up;
        document.getElementById("upper-threshold").value = thresholdUp;
      }
      if (typeof data.threshold_down !== "undefined") {
        thresholdDown = data.threshold_down;
        document.getElementById("lower-threshold").value = thresholdDown;
      }
    }
  } catch {}
  // Initialize X-range UI elements
  document.getElementById('xrange-slider').value = graphXRangeSec;
  updateXRangeLabel();
  initChart();
  showView(window.location.hash || "#bar");
  window.addEventListener("hashchange", () => showView(window.location.hash));
  connectStream();
});
