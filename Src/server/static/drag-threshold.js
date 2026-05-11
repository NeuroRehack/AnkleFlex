/**
 * Chart threshold drag logic for AnkleFlex
 * Single-file vanilla JS. No global namespace pollution.
 */
(function() {
  // Sensitivity zone for picking a line (in px)
  const PICK_RADIUS = 8;
  let dragging = null; // null | 'upper' | 'lower'
  let lastDragY = null;

  // Util: Get graphChart and yScale
  function getYScale() {
    if (!window.graphChart) return null;
    return window.graphChart.scales && window.graphChart.scales.y;
  }

  // Util: screenY to chart value
  function yPixelToValue(y) {
    const yScale = getYScale();
    if (!yScale) return null;
    const rect = window.graphChart.canvas.getBoundingClientRect();
    const yChart = y - rect.top;
    return yScale.getValueForPixel(yChart);
  }

  // Util: chart value to screenY
  function valueToYPixel(val) {
    const yScale = getYScale();
    if (!yScale) return null;
    const px = yScale.getPixelForValue(val);
    const rect = window.graphChart.canvas.getBoundingClientRect();
    return px + rect.top;
  }

  // Handler: mouse/touch down
  function startDrag(e) {
    if (!window.graphChart) return;
    // Only active in graph view
    if (document.body.dataset.view !== 'graph') return;
    const yScale = getYScale();
    if (!yScale) return;
    let clientY;
    if (e.type.startsWith('touch')) {
      if (e.touches.length !== 1) return;
      clientY = e.touches[0].clientY;
    } else {
      clientY = e.clientY;
    }
    const upY   = valueToYPixel(window.displayValue(window.thresholdUp));
    const downY = valueToYPixel(window.displayValue(window.thresholdDown));
    if (Math.abs(clientY - upY) <= PICK_RADIUS) {
      dragging = 'upper';
      lastDragY = clientY;
      document.body.style.cursor = 'ns-resize';
      e.preventDefault();
    } else if (Math.abs(clientY - downY) <= PICK_RADIUS) {
      dragging = 'lower';
      lastDragY = clientY;
      document.body.style.cursor = 'ns-resize';
      e.preventDefault();
    }
  }

  function dragMove(e) {
    if (!dragging || !window.graphChart) return;
    let clientY;
    if (e.type.startsWith('touch')) {
      if (e.touches.length !== 1) return;
      clientY = e.touches[0].clientY;
    } else {
      clientY = e.clientY;
    }
    const val = yPixelToValue(clientY);
    if (typeof val !== 'number' || isNaN(val)) return;
    if (dragging === 'upper') {
      // Clamp so upper >= lower
      let newUp = Math.max(Math.round(val), window.thresholdDown);
      window.thresholdUp = newUp;
      if (typeof window.setThresholdUp === 'function') {
        window.setThresholdUp(newUp);
      } else {
        document.getElementById('upper-threshold').value = newUp.toFixed(1);
        window.updateGraphChart(window.appState.history);
        if (window.graphChart) window.graphChart.update('none');
      }
    } else if (dragging === 'lower') {
      // Clamp so lower <= upper
      let newDown = Math.min(Math.round(val), window.thresholdUp);
      window.thresholdDown = newDown;
      if (typeof window.setThresholdDown === 'function') {
        window.setThresholdDown(newDown);
      } else {
        document.getElementById('lower-threshold').value = newDown.toFixed(1);
        window.updateGraphChart(window.appState.history);
        if (window.graphChart) window.graphChart.update('none');
      }
    }
    if (window.graphChart) window.graphChart.update('none');
    lastDragY = clientY;
    e.preventDefault();
  }

  async function endDrag(e) {
    if (!dragging) return;
    // Save to backend
    const up = window.thresholdUp;
    const down = window.thresholdDown;
    try {
      await fetch("/thresholds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upper: up, lower: down })
      });
    } catch {
      // Could enhance: show error message, revert?
      console.error("Failed to update thresholds to backend.");
    }
    dragging = null;
    document.body.style.cursor = '';
    e.preventDefault();
  }

  // Visual cue: ns-resize on hover
  function handleHover(e) {
    if (!window.graphChart) return;
    const canvas = window.graphChart.canvas;
    if (!canvas) return;
    if (dragging) return; // already dragging
    let clientY = e.clientY;
    const upY   = valueToYPixel(window.displayValue(window.thresholdUp));
    const downY = valueToYPixel(window.displayValue(window.thresholdDown));
    if (Math.abs(clientY - upY) <= PICK_RADIUS || Math.abs(clientY - downY) <= PICK_RADIUS) {
      canvas.style.cursor = 'ns-resize';
    } else {
      canvas.style.cursor = '';
    }
  }

  // Install listeners
  function install() {
    const canvas = document.getElementById('graphChart');
    canvas.addEventListener('mousedown', startDrag);
    canvas.addEventListener('touchstart', startDrag, {passive:false});
    window.addEventListener('mousemove', dragMove);
    window.addEventListener('touchmove', dragMove, {passive:false});
    window.addEventListener('mouseup', endDrag);
    window.addEventListener('touchend', endDrag);
    canvas.addEventListener('mousemove', handleHover);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }

  // Expose for debugging
  window.__ankleflex_dragthreshold = {startDrag, dragMove, endDrag, handleHover};
})();
