/**
 * AnkleFlex — Timeline minimap (range brush / overview+detail control)
 *
 * Draws a full-history sparkline with a draggable brush window. Dragging
 * the body of the brush pans through history; dragging either edge resizes
 * the time window (clamped to the same limits as the toolbar slider).
 *
 * When the right edge of the brush is at the tail of the data the control
 * is in "live" mode and the main chart auto-scrolls with incoming samples.
 * Moving the brush left freezes the view at that historical position.
 *
 * Bridge to app.js (all accessed via window.*):
 *   window.appState              — current state including full history array
 *   window.graphXRangeSec        — visible window width in seconds (read/write)
 *   window.graphXPinnedEndTs     — null = live tail; absolute ms timestamp = pinned (read/write)
 *   window.setGraphXRange(sec)   — update window width and redraw main chart
 *   window.setPinnedEndTs(tsOrNull) — pin/unpin the view and redraw main chart
 *   window.displayValue(v)       — applies axis flip + scale transform
 *   window.minimapDraw()         — exposed by this module; called by app.js
 *                                  after every main-chart update
 */
(function () {
  "use strict";

  // ── Interaction constants ──────────────────────────────────────────────────
  const HANDLE_WIDTH   = 8;   // px — visual width of each drag handle
  const PICK_RADIUS    = 10;  // px — hit zone around a handle edge
  const LIVE_SNAP_PX   = 14;  // px — snap to live when right edge is this close to the wall
  const MIN_WINDOW_SEC = 1;
  const MAX_WINDOW_SEC = 1200;

  // ── Module state ──────────────────────────────────────────────────────────
  let canvas   = null;
  let ctx      = null;
  let liveBtn  = null;

  // dragMode: null | 'pan' | 'resize-left' | 'resize-right'
  let dragMode          = null;
  let dragStartX        = null;
  let dragStartLeftPx   = null; // canvas x of left handle at mousedown (pinned by resize-right)
  let dragStartRightPx  = null; // canvas x of right handle at mousedown (pinned by resize-left)
  // Coordinate system frozen at mousedown so the pinned edge cannot drift
  // within a single gesture as new live data extends getTotalMs().
  let dragStartFirstTs  = null;
  let dragStartTotalMs  = null;
  let dragStartEndTs    = null; // absolute endTs at mousedown (used by pan)

  // ── Data accessors ────────────────────────────────────────────────────────

  function getHistory() {
    return (window.appState && Array.isArray(window.appState.history))
      ? window.appState.history
      : [];
  }

  function getLatestTs() {
    const h = getHistory();
    return h.length ? h[h.length - 1].ts : 0;
  }

  function getFirstTs() {
    const h = getHistory();
    return h.length ? h[0].ts : 0;
  }

  // Total span of history in ms — always at least 1 to avoid division by zero.
  function getTotalMs() {
    return Math.max(getLatestTs() - getFirstTs(), 1);
  }

  function getWindowMs() {
    return (window.graphXRangeSec || 10) * 1000;
  }

  // Returns the absolute end timestamp of the current view.
  // null in the bridge means live — use the actual latest sample timestamp.
  function getEffectiveEndTs() {
    const pinned = window.graphXPinnedEndTs;
    return (pinned !== null && pinned !== undefined) ? pinned : getLatestTs();
  }

  function isLive() {
    const pinned = window.graphXPinnedEndTs;
    return pinned === null || pinned === undefined;
  }

  // ── Coordinate helpers ────────────────────────────────────────────────────

  // Absolute timestamp → canvas x pixel (0 = oldest sample, W = newest sample).
  function tsToX(ts) {
    return ((ts - getFirstTs()) / getTotalMs()) * canvas.width;
  }

  // Canvas x pixel → absolute timestamp.
  function xToTs(x) {
    return getFirstTs() + (x / canvas.width) * getTotalMs();
  }

  // Current brush bounds in canvas pixels, clamped to [0, W].
  function getBrushBounds() {
    const W        = canvas.width;
    const endTs    = getEffectiveEndTs();
    const startTs  = endTs - getWindowMs();
    return {
      left:  Math.max(0, Math.min(W, tsToX(startTs))),
      right: Math.max(0, Math.min(W, tsToX(endTs))),
    };
  }

  // ── Theme helper ──────────────────────────────────────────────────────────

  function cssVar(name, fallback) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim() || fallback;
  }

  // ── Canvas drawing ────────────────────────────────────────────────────────

  // Rounded rectangle path — polyfill for environments without ctx.roundRect.
  function roundRect(c, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    c.beginPath();
    c.moveTo(x + r, y);
    c.lineTo(x + w - r, y);
    c.arcTo(x + w, y,     x + w, y + r,     r);
    c.lineTo(x + w, y + h - r);
    c.arcTo(x + w, y + h, x + w - r, y + h, r);
    c.lineTo(x + r, y + h);
    c.arcTo(x,     y + h, x,     y + h - r, r);
    c.lineTo(x,     y + r);
    c.arcTo(x,     y,     x + r, y,         r);
    c.closePath();
  }

  function draw() {
    if (!canvas || !ctx) return;

    const history = getHistory();
    const W = canvas.width;
    const H = canvas.height;

    const colorSurface = cssVar('--surface', '#ffffff');
    const colorAccent  = cssVar('--accent',  '#457b9d');
    const colorBlue    = cssVar('--blue',    '#1d3557');
    const colorMuted   = cssVar('--muted',   '#64748b');
    const colorBorder  = cssVar('--border',  '#dde3ec');

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = colorSurface;
    ctx.fillRect(0, 0, W, H);

    if (history.length < 2) {
      ctx.fillStyle  = colorMuted;
      ctx.font       = '11px system-ui, -apple-system, sans-serif';
      ctx.textAlign  = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('Waiting for data…', W / 2, H / 2);
      syncLiveButton();
      return;
    }

    // ── Sparkline ──────────────────────────────────────────────────────────
    const displayFn = window.displayValue || (v => v);
    const values    = history.map(s => displayFn(s.w));
    const maxVal    = Math.max(...values);
    const minVal    = Math.min(...values);
    const valRange  = maxVal - minVal || 1;
    const padY      = 5;

    ctx.save();
    ctx.beginPath();
    for (let i = 0; i < history.length; i++) {
      const x = tsToX(history[i].ts);
      // Map value into [padY … H - padY] with y-axis pointing down.
      const y = H - padY - ((values[i] - minVal) / valRange) * (H - padY * 2);
      if (i === 0) ctx.moveTo(x, y);
      else         ctx.lineTo(x, y);
    }
    ctx.strokeStyle = colorAccent;
    ctx.lineWidth   = 1.5;
    ctx.stroke();
    ctx.restore();

    // ── Brush overlay ──────────────────────────────────────────────────────
    const { left, right } = getBrushBounds();

    // Dim the regions outside the brush so the selected window stands out.
    ctx.save();
    ctx.fillStyle = 'rgba(0,0,0,0.22)';
    if (left > 0)  ctx.fillRect(0,     0, left,      H);
    if (right < W) ctx.fillRect(right, 0, W - right, H);
    ctx.restore();

    // Semi-transparent brush fill.
    ctx.save();
    ctx.fillStyle = colorAccent + '28'; // ~16 % alpha
    ctx.fillRect(left, 0, right - left, H);
    ctx.restore();

    // Brush border.
    ctx.save();
    ctx.strokeStyle = colorBlue;
    ctx.lineWidth   = 1.5;
    ctx.strokeRect(left + 0.75, 0.75, right - left - 1.5, H - 1.5);
    ctx.restore();

    // Left resize handle.
    ctx.save();
    ctx.fillStyle = colorBlue;
    roundRect(ctx, left - HANDLE_WIDTH / 2, H * 0.2, HANDLE_WIDTH, H * 0.6, 3);
    ctx.fill();
    ctx.restore();

    // Right resize handle.
    ctx.save();
    ctx.fillStyle = colorBlue;
    roundRect(ctx, right - HANDLE_WIDTH / 2, H * 0.2, HANDLE_WIDTH, H * 0.6, 3);
    ctx.fill();
    ctx.restore();

    syncLiveButton();
  }

  // ── Live-button visibility sync ───────────────────────────────────────────

  // The live-button is shown whenever the view is pinned to history.
  function syncLiveButton() {
    if (!liveBtn) return;
    liveBtn.hidden = isLive();
  }

  // ── Hit testing ───────────────────────────────────────────────────────────

  // Returns the canvas-relative x coordinate from a mouse or touch event.
  function canvasX(e) {
    const rect    = canvas.getBoundingClientRect();
    const clientX = e.type.startsWith('touch')
      ? (e.touches[0] || e.changedTouches[0]).clientX
      : e.clientX;
    return clientX - rect.left;
  }

  // Returns the drag mode for a given canvas x, or null if outside the brush.
  function hitTest(x) {
    const { left, right } = getBrushBounds();
    if (Math.abs(x - left)  <= PICK_RADIUS) return 'resize-left';
    if (Math.abs(x - right) <= PICK_RADIUS) return 'resize-right';
    if (x > left && x < right)              return 'pan';
    return null;
  }

  // ── Drag event handlers ───────────────────────────────────────────────────

  function onPointerDown(e) {
    // Only active in graph view.
    if (document.body.dataset.view !== 'graph') return;
    if (getHistory().length < 2) return;

    const x    = canvasX(e);
    const mode = hitTest(x);
    if (!mode) return;

    dragMode          = mode;
    dragStartX        = x;
    // Freeze the coordinate system at mousedown. Any of the three drag modes
    // needs a stable pixel↔timestamp mapping so that the pinned edge does not
    // creep as new live samples extend getTotalMs() during the gesture.
    dragStartFirstTs  = getFirstTs();
    dragStartTotalMs  = getTotalMs();
    dragStartEndTs    = getEffectiveEndTs();
    const { left: startLeft, right: startRight } = getBrushBounds();
    dragStartLeftPx   = startLeft;
    dragStartRightPx  = startRight;

    e.preventDefault();
  }

  function onPointerMove(e) {
    if (!canvas) return;

    const x = canvasX(e);

    // Update cursor even when not actively dragging.
    if (!dragMode) {
      const hit = hitTest(x);
      if (hit === 'resize-left' || hit === 'resize-right') {
        canvas.style.cursor = 'ew-resize';
      } else if (hit === 'pan') {
        canvas.style.cursor = 'grab';
      } else {
        canvas.style.cursor = 'default';
      }
      return;
    }

    e.preventDefault();

    if (getHistory().length < 2) return;

    const latestTs = getLatestTs(); // current live tail — needed for clamping and live-snap
    const W        = canvas.width;

    if (dragMode === 'pan') {
      // Convert cursor displacement to ms using the frozen coordinate system
      // so that pan speed does not drift as getTotalMs() grows during the drag.
      const dMs      = (x - dragStartX) / W * dragStartTotalMs;
      const windowMs = getWindowMs();
      let newEndTs   = dragStartEndTs + dMs;
      // Clamp so the window stays within the recorded history.
      newEndTs = Math.max(dragStartFirstTs + windowMs, Math.min(latestTs, newEndTs));
      // Unpin (go live) when the right edge reaches the live tail.
      applyPinnedEndTs(newEndTs >= latestTs ? null : newEndTs);

    } else if (dragMode === 'resize-right') {
      // The LEFT edge is pinned at dragStartLeftPx. The right handle follows
      // the cursor. The frozen coordinate system is used throughout so neither
      // edge drifts as new data arrives.
      let rightPx = Math.max(dragStartLeftPx + 1, Math.min(x, W));
      const snapToLive = rightPx >= W - LIVE_SNAP_PX;
      if (snapToLive) rightPx = W;
      const windowMs = Math.max(
        MIN_WINDOW_SEC * 1000,
        Math.min(MAX_WINDOW_SEC * 1000, (rightPx - dragStartLeftPx) / W * dragStartTotalMs),
      );
      // Derive absolute endTs from the right-edge pixel using frozen coords.
      const clampedRightPx = dragStartLeftPx + (windowMs / dragStartTotalMs) * W;
      const newEndTs = dragStartFirstTs + (clampedRightPx / W) * dragStartTotalMs;
      // Write pinnedEndTs directly so setGraphXRange's sync picks it up
      // without triggering a second redraw.
      window.graphXPinnedEndTs = snapToLive ? null : Math.min(newEndTs, latestTs);
      if (typeof window.setGraphXRange === 'function') {
        window.setGraphXRange(windowMs / 1000);
      }

    } else if (dragMode === 'resize-left') {
      // The RIGHT edge is pinned at dragStartRightPx. The left handle follows
      // the cursor. endTs (and therefore pinnedEndTs) does not change at all;
      // only the window width changes.
      const rightPx  = dragStartRightPx;
      const leftPx   = Math.max(0, Math.min(x, rightPx - 1));
      const windowMs = Math.max(
        MIN_WINDOW_SEC * 1000,
        Math.min(MAX_WINDOW_SEC * 1000, (rightPx - leftPx) / W * dragStartTotalMs),
      );
      // pinnedEndTs is intentionally left unchanged — setGraphXRange's sync
      // block will read the existing window.graphXPinnedEndTs value.
      if (typeof window.setGraphXRange === 'function') {
        window.setGraphXRange(windowMs / 1000);
      }
    }

    draw();
  }

  function onPointerUp(e) {
    if (!dragMode) return;
    dragMode          = null;
    dragStartX        = null;
    dragStartLeftPx   = null;
    dragStartRightPx  = null;
    dragStartFirstTs  = null;
    dragStartTotalMs  = null;
    dragStartEndTs    = null;
    canvas.style.cursor = 'default';
    e.preventDefault();
  }

  // ── Offset application ────────────────────────────────────────────────────

  // Central point for committing a pinned-end-timestamp change from the
  // minimap to app.js. Used only by pan (resize handlers write the window
  // bridge directly and call setGraphXRange to avoid a double redraw).
  function applyPinnedEndTs(tsOrNull) {
    if (typeof window.setPinnedEndTs === 'function') {
      window.setPinnedEndTs(tsOrNull);
    } else {
      window.graphXPinnedEndTs = tsOrNull;
    }
  }

  // ── Canvas sizing ──────────────────────────────────────────────────────────

  // Keep the canvas's internal pixel buffer in sync with its CSS layout size
  // so the drawing coordinates map 1:1 to display pixels.
  function syncCanvasSize() {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const w    = Math.round(rect.width);
    const h    = Math.round(rect.height);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width  = w;
      canvas.height = h;
    }
  }

  // ── Installation ──────────────────────────────────────────────────────────

  function install() {
    canvas  = document.getElementById('minimapCanvas');
    liveBtn = document.getElementById('minimap-live-btn');
    if (!canvas) return;

    ctx = canvas.getContext('2d');
    syncCanvasSize();

    // Pointer events on the canvas element itself.
    canvas.addEventListener('mousedown',  onPointerDown);
    canvas.addEventListener('touchstart', onPointerDown, { passive: false });

    // Move and up on window so fast drags that leave the canvas still work.
    window.addEventListener('mousemove', onPointerMove);
    window.addEventListener('touchmove', onPointerMove, { passive: false });
    window.addEventListener('mouseup',   onPointerUp);
    window.addEventListener('touchend',  onPointerUp);

    // Re-draw whenever the container is resized (e.g. panel resize, orientation change).
    const observer = new ResizeObserver(() => {
      syncCanvasSize();
      draw();
    });
    observer.observe(canvas.parentElement || canvas);

    // Wire the "Back to live" button.
    if (liveBtn) {
      liveBtn.addEventListener('click', () => applyPinnedEndTs(null));
    }

    // Expose the draw function so app.js can call window.minimapDraw() after
    // each main-chart update without creating a hard import dependency.
    window.minimapDraw = draw;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }

  // Expose for debugging convenience.
  window.__ankleflex_minimap = { draw };
})();
