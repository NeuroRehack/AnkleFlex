/**
 * AnkleFlex — real-time weight display
 * Connects to /stream (SSE) and updates a Chart.js bar chart.
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let appState = { weight: 0, min_weight: 0, max_weight: 0, emulation: false };
let axisFlipped = false;
let scale = 1.0;
let chart = null;

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
      animation: { duration: 180 },
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
          title: {
            display: true,
            text: "Force (kg)",
            font: { size: 14, weight: "600" },
            color: "#6c757d",
          },
          ticks: {
            font: { size: 13 },
            color: "#495057",
          },
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
}

// ── DOM updates ───────────────────────────────────────────────────────────────
function updateWeightDisplay() {
  document.getElementById("weight-value").textContent =
    displayValue(appState.weight).toFixed(1);
}

function updateEmulationPanel() {
  const panel = document.getElementById("emulation-panel");
  panel.style.display = appState.emulation ? "flex" : "none";
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
  });
}

// ── API calls ─────────────────────────────────────────────────────────────────
function tare() {
  fetch("/tare", { method: "POST" })
    .then((r) => r.json())
    .catch((err) => console.error("Tare failed:", err));
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

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initChart();
  connectStream();
});
