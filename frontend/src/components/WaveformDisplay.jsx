import React, { useRef, useCallback } from "react";
import { t } from "../i18n.js";

/**
 * Renders an SVG waveform from an amplitude array.
 *
 * variant="mini"  — compact, read-only thumbnail used in SongCard
 * variant="full"  — taller, clickable; shows draggable start/end markers
 *                   fires onMarkersChange({ startMs, endMs }) on click/drag
 */
export default function WaveformDisplay({
  amplitudes = [],
  durationSeconds = 0,
  startMs = null,
  endMs = null,
  onMarkersChange = null,
  variant = "mini",
  loading = false,
  error = false,
}) {
  const svgRef = useRef(null);
  const dragging = useRef(null); // "start" | "end" | null

  const height = variant === "mini" ? 40 : 80;
  const barColor = variant === "mini" ? "#555" : "#e6b800";
  const markerColorStart = "#00d4ff";
  const markerColorEnd = "#ff6b6b";

  // ── Helpers ────────────────────────────────────────────────────────────────

  function xFromMs(ms, svgWidth) {
    if (!durationSeconds) return 0;
    return (ms / (durationSeconds * 1000)) * svgWidth;
  }

  function msFromX(x, svgWidth) {
    if (!durationSeconds || !svgWidth) return 0;
    const raw = (x / svgWidth) * durationSeconds * 1000;
    return Math.max(0, Math.min(durationSeconds * 1000, Math.round(raw)));
  }

  function getSvgX(e) {
    const svg = svgRef.current;
    if (!svg) return 0;
    const rect = svg.getBoundingClientRect();
    return e.clientX - rect.left;
  }

  // ── Interaction (full variant only) ───────────────────────────────────────

  const handleMouseDown = useCallback(
    (e) => {
      if (variant !== "full" || !onMarkersChange) return;
      const svg = svgRef.current;
      if (!svg) return;
      const svgWidth = svg.clientWidth;
      const x = getSvgX(e);
      const ms = msFromX(x, svgWidth);

      // Decide which marker to move based on proximity
      const startX = startMs !== null ? xFromMs(startMs, svgWidth) : null;
      const endX = endMs !== null ? xFromMs(endMs, svgWidth) : null;

      if (startX !== null && Math.abs(x - startX) < 12) {
        dragging.current = "start";
      } else if (endX !== null && Math.abs(x - endX) < 12) {
        dragging.current = "end";
      } else {
        // Click outside markers — place start marker
        dragging.current = "start";
        onMarkersChange({ startMs: ms, endMs: endMs ?? durationSeconds * 1000 });
      }
      e.preventDefault();
    },
    [variant, onMarkersChange, startMs, endMs, durationSeconds]
  );

  const handleMouseMove = useCallback(
    (e) => {
      if (!dragging.current || variant !== "full" || !onMarkersChange) return;
      const svg = svgRef.current;
      if (!svg) return;
      const ms = msFromX(getSvgX(e), svg.clientWidth);
      if (dragging.current === "start") {
        onMarkersChange({ startMs: ms, endMs: endMs ?? durationSeconds * 1000 });
      } else {
        onMarkersChange({ startMs: startMs ?? 0, endMs: ms });
      }
    },
    [variant, onMarkersChange, startMs, endMs, durationSeconds]
  );

  const handleMouseUp = useCallback(() => {
    dragging.current = null;
  }, []);

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="waveform-placeholder">
        <span className="waveform-msg">{t("waveformLoading")}</span>
      </div>
    );
  }

  if (error || amplitudes.length === 0) {
    return (
      <div className="waveform-placeholder">
        <span className="waveform-msg waveform-msg--error">{t("waveformError")}</span>
      </div>
    );
  }

  const max = Math.max(...amplitudes, 0.001);
  const bars = amplitudes.map((amp, i) => {
    const pct = amp / max;
    const barH = Math.max(1, pct * (height - 4));
    return { i, barH };
  });

  return (
    <svg
      ref={svgRef}
      className={`waveform waveform--${variant}`}
      style={{ height, cursor: variant === "full" ? "crosshair" : "default" }}
      preserveAspectRatio="none"
      viewBox={`0 0 ${amplitudes.length} ${height}`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {bars.map(({ i, barH }) => (
        <rect
          key={i}
          x={i}
          y={(height - barH) / 2}
          width={0.8}
          height={barH}
          fill={barColor}
          opacity={0.85}
        />
      ))}

      {/* Start marker */}
      {variant === "full" && startMs !== null && durationSeconds > 0 && (
        <line
          x1={((startMs / 1000) / durationSeconds) * amplitudes.length}
          x2={((startMs / 1000) / durationSeconds) * amplitudes.length}
          y1={0}
          y2={height}
          stroke={markerColorStart}
          strokeWidth={1.5}
        />
      )}

      {/* End marker */}
      {variant === "full" && endMs !== null && durationSeconds > 0 && (
        <line
          x1={((endMs / 1000) / durationSeconds) * amplitudes.length}
          x2={((endMs / 1000) / durationSeconds) * amplitudes.length}
          y1={0}
          y2={height}
          stroke={markerColorEnd}
          strokeWidth={1.5}
        />
      )}
    </svg>
  );
}
