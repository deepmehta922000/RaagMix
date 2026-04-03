import React, { useState, useCallback } from "react";
import { remix, remixManual } from "../api.js";
import { useApp } from "../context/AppContext.jsx";
import { t } from "../i18n.js";
import PresetSelector from "./PresetSelector.jsx";
import Tooltip from "./Tooltip.jsx";
import WaveformDisplay from "./WaveformDisplay.jsx";

// ── Helpers ────────────────────────────────────────────────────────────────────

function msToMmss(ms) {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function mmssToMs(str) {
  const parts = str.split(":").map(Number);
  if (parts.length === 2) {
    const [m, s] = parts;
    if (!isNaN(m) && !isNaN(s)) return (m * 60 + s) * 1000;
  }
  const sec = parseFloat(str);
  if (!isNaN(sec)) return Math.round(sec * 1000);
  return null;
}

// ── AI Tab ─────────────────────────────────────────────────────────────────────

function AIRemixTab({ songs }) {
  const { setRemixResult, setIsProcessing, setProcessingError, isProcessing } = useApp();
  const [prompt, setPrompt] = useState("");
  const [preset, setPreset] = useState(null);

  const handlePresetSelect = useCallback((key) => {
    setPreset(key);
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!prompt.trim() || songs.length < 2) return;
    setIsProcessing(true);
    setProcessingError(null);
    try {
      const fileIds = songs.map((s) => s.fileId);
      const filenames = Object.fromEntries(songs.map((s) => [s.fileId, s.filename]));
      const result = await remix(fileIds, prompt, preset, filenames);
      setRemixResult({
        outputFileId: result.output_file_id,
        targetBpm: result.target_bpm,
        stepsCompleted: result.steps_completed,
        stepResults: result.step_results,
        plan: result.plan,
      });
    } catch (err) {
      setProcessingError(err.detail ?? err.message ?? t("remixError"));
    } finally {
      setIsProcessing(false);
    }
  }

  return (
    <form className="ai-tab" onSubmit={handleSubmit}>
      <div className="preset-selector-row">
        <PresetSelector selected={preset} onSelect={handlePresetSelect} />
        <Tooltip text={t("tooltipPreset")} />
      </div>

      <div className="field">
        <label className="field__label">
          {t("promptLabel")} <Tooltip text={t("tooltipPrompt")} />
        </label>
        <textarea
          className="field__textarea"
          rows={3}
          maxLength={500}
          placeholder={t("promptPlaceholder")}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <span className="field__counter">{prompt.length}/500</span>
      </div>

      <div className="btn-row">
        <button
          type="submit"
          className="btn btn--primary"
          disabled={isProcessing || !prompt.trim() || songs.length < 2}
        >
          {isProcessing ? t("generating") : t("remixBtn")}
        </button>
        <Tooltip text={t("tooltipGenerateRemix")} />
      </div>
    </form>
  );
}

// ── Manual Tab ─────────────────────────────────────────────────────────────────

const EMPTY_SEGMENT = (order) => ({
  id: crypto.randomUUID(),
  fileId: "",
  startMs: 0,
  endMs: 30000,
  order,
  crossfadeWithNext: true,
  skipStretch: false,
});

function SegmentRow({ seg, index, songs, onChange, onRemove }) {
  const song = songs.find((s) => s.fileId === seg.fileId);

  function field(key, val) {
    onChange(seg.id, { [key]: val });
  }

  return (
    <div className="segment-row">
      <div className="segment-row__header">
        <span className="segment-row__num">{t("segmentN")} {index + 1}</span>
        <button
          type="button"
          className="btn btn--ghost btn--xs"
          onClick={() => onRemove(seg.id)}
        >
          {t("removeSegment")}
        </button>
      </div>

      {/* Song picker */}
      <div className="field field--row">
        <label className="field__label">
          {t("segmentSong")} <Tooltip text={t("tooltipCrossfadeWithNext")} />
        </label>
        <select
          className="field__select"
          value={seg.fileId}
          onChange={(e) => field("fileId", e.target.value)}
        >
          <option value="">{t("selectSong")}</option>
          {songs.map((s) => (
            <option key={s.fileId} value={s.fileId}>
              {s.filename}
            </option>
          ))}
        </select>
      </div>

      {/* Waveform with markers */}
      {song && (
        <WaveformDisplay
          amplitudes={song.waveformAmplitudes}
          durationSeconds={song.durationSeconds}
          variant="full"
          startMs={seg.startMs}
          endMs={seg.endMs}
          onMarkersChange={({ startMs, endMs }) =>
            onChange(seg.id, { startMs, endMs })
          }
        />
      )}

      {/* Time inputs */}
      <div className="segment-row__times">
        <div className="field field--row">
          <label className="field__label">
            {t("segmentStart")} <Tooltip text="Drag the blue marker on the waveform or type mm:ss." />
          </label>
          <input
            className="field__input field__input--sm"
            value={msToMmss(seg.startMs)}
            onChange={(e) => {
              const ms = mmssToMs(e.target.value);
              if (ms !== null) field("startMs", ms);
            }}
          />
        </div>
        <div className="field field--row">
          <label className="field__label">
            {t("segmentEnd")} <Tooltip text="Drag the red marker on the waveform or type mm:ss." />
          </label>
          <input
            className="field__input field__input--sm"
            value={msToMmss(seg.endMs)}
            onChange={(e) => {
              const ms = mmssToMs(e.target.value);
              if (ms !== null) field("endMs", ms);
            }}
          />
        </div>
      </div>

      {/* Checkboxes */}
      <div className="segment-row__flags">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={seg.crossfadeWithNext}
            onChange={(e) => field("crossfadeWithNext", e.target.checked)}
          />
          {t("crossfadeNext")}
          <Tooltip text={t("tooltipCrossfadeWithNext")} />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={seg.skipStretch}
            onChange={(e) => field("skipStretch", e.target.checked)}
          />
          {t("skipStretch")}
          <Tooltip text={t("tooltipSkipStretch")} />
        </label>
      </div>
    </div>
  );
}

function ManualRemixTab({ songs }) {
  const { setRemixResult, setIsProcessing, setProcessingError, isProcessing } = useApp();
  const [segments, setSegments] = useState([EMPTY_SEGMENT(1)]);
  const [targetBpm, setTargetBpm] = useState("");
  const [crossfadeSec, setCrossfadeSec] = useState("2");
  const [fadeType, setFadeType] = useState("linear");
  const [fadeOutSec, setFadeOutSec] = useState("3");
  const [vocalDuck, setVocalDuck] = useState(false);

  function addSegment() {
    if (segments.length >= 20) return;
    setSegments((prev) => [...prev, EMPTY_SEGMENT(prev.length + 1)]);
  }

  function removeSegment(id) {
    setSegments((prev) => {
      const next = prev.filter((s) => s.id !== id).map((s, i) => ({ ...s, order: i + 1 }));
      return next.length > 0 ? next : [EMPTY_SEGMENT(1)];
    });
  }

  function updateSegment(id, patch) {
    setSegments((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const validSegs = segments.filter((s) => s.fileId);
    if (validSegs.length === 0) return;

    setIsProcessing(true);
    setProcessingError(null);
    try {
      const payload = validSegs.map((s) => ({
        file_id: s.fileId,
        start_time: s.startMs,
        end_time: s.endMs,
        order: s.order,
        crossfade_with_next: s.crossfadeWithNext,
        skip_stretch: s.skipStretch,
      }));
      const bpm = targetBpm ? parseFloat(targetBpm) : null;
      const result = await remixManual(
        payload,
        bpm,
        parseFloat(crossfadeSec) || 2,
        fadeType,
        parseFloat(fadeOutSec) || 0,
        vocalDuck,
      );
      setRemixResult({
        outputFileId: result.final_file_id,
        targetBpm: result.target_bpm,
        stepsCompleted: result.segments?.length ?? validSegs.length,
        stepResults: result.segments ?? [],
      });
    } catch (err) {
      setProcessingError(err.detail ?? err.message ?? t("remixError"));
    } finally {
      setIsProcessing(false);
    }
  }

  return (
    <form className="manual-tab" onSubmit={handleSubmit}>
      {/* Segment rows */}
      <div className="segment-list">
        {segments.map((seg, i) => (
          <SegmentRow
            key={seg.id}
            seg={seg}
            index={i}
            songs={songs}
            onChange={updateSegment}
            onRemove={removeSegment}
          />
        ))}
      </div>

      <button
        type="button"
        className="btn btn--secondary btn--sm"
        onClick={addSegment}
        disabled={segments.length >= 20}
      >
        + {t("addSegment")}
      </button>

      {/* Mix options */}
      <div className="mix-options">
        <div className="field field--row">
          <label className="field__label">
            {t("targetBpmLabel")} <Tooltip text={t("tooltipTargetBpm")} />
          </label>
          <input
            className="field__input field__input--sm"
            type="number"
            min="40"
            max="220"
            placeholder="—"
            value={targetBpm}
            onChange={(e) => setTargetBpm(e.target.value)}
          />
        </div>

        <div className="field field--row">
          <label className="field__label">
            {t("crossfadeSec")} <Tooltip text={t("tooltipCrossfadeSec")} />
          </label>
          <input
            className="field__input field__input--sm"
            type="number"
            min="0.5"
            max="10"
            step="0.5"
            value={crossfadeSec}
            onChange={(e) => setCrossfadeSec(e.target.value)}
          />
        </div>

        <div className="field field--row">
          <label className="field__label">
            {t("fadeType")} <Tooltip text={t("tooltipFadeType")} />
          </label>
          <select
            className="field__select field__select--sm"
            value={fadeType}
            onChange={(e) => setFadeType(e.target.value)}
          >
            <option value="linear">{t("fadeLinear")}</option>
            <option value="logarithmic">{t("fadeLogarithmic")}</option>
          </select>
        </div>

        <div className="field field--row">
          <label className="field__label">
            {t("fadeOutSec")} <Tooltip text={t("tooltipFadeOut")} />
          </label>
          <input
            className="field__input field__input--sm"
            type="number"
            min="0"
            max="10"
            step="0.5"
            value={fadeOutSec}
            onChange={(e) => setFadeOutSec(e.target.value)}
          />
        </div>

        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={vocalDuck}
            onChange={(e) => setVocalDuck(e.target.checked)}
          />
          {t("vocalDuck")}
          <Tooltip text={t("tooltipVocalDuck")} />
        </label>
      </div>

      <div className="btn-row">
        <button
          type="submit"
          className="btn btn--primary"
          disabled={isProcessing || segments.every((s) => !s.fileId)}
        >
          {isProcessing ? t("building") : t("buildMix")}
        </button>
        <Tooltip text={t("tooltipBuildMix")} />
      </div>
    </form>
  );
}

// ── RemixPanel ─────────────────────────────────────────────────────────────────

export default function RemixPanel() {
  const { songs, remixResult, isProcessing, processingError } = useApp();
  const [activeTab, setActiveTab] = useState("ai");

  return (
    <section className="panel remix-panel">
      <h2 className="panel__title">{t("remixPanel")}</h2>

      {/* Tab bar */}
      <div className="tab-bar">
        <button
          className={`tab-btn${activeTab === "ai" ? " tab-btn--active" : ""}`}
          onClick={() => setActiveTab("ai")}
        >
          {t("tabAI")}
        </button>
        <button
          className={`tab-btn${activeTab === "manual" ? " tab-btn--active" : ""}`}
          onClick={() => setActiveTab("manual")}
        >
          {t("tabManual")}
        </button>
      </div>

      {/* Not enough songs */}
      {songs.length < 2 && activeTab === "ai" && (
        <p className="hint-text">{t("selectSongs")}</p>
      )}

      {/* Active tab */}
      {activeTab === "ai" ? (
        <AIRemixTab songs={songs} />
      ) : (
        <ManualRemixTab songs={songs} />
      )}

      {/* Error */}
      {processingError && (
        <div className="error-banner">
          {t("remixError")}: {processingError}
        </div>
      )}

      {/* Success summary */}
      {remixResult && !isProcessing && (
        <div className="success-banner">
          <span>{t("remixSuccess")}</span>
          <span className="success-banner__meta">
            {remixResult.stepsCompleted} {t("stepsCompleted")} ·{" "}
            {t("targetBpm")}: {remixResult.targetBpm?.toFixed(1) ?? "—"}
          </span>
        </div>
      )}
    </section>
  );
}
