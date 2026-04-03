import React, { useRef, useState, useCallback } from "react";
import { uploadFile, analyzeFile, getWaveform } from "../api.js";
import { useApp } from "../context/AppContext.jsx";
import { t } from "../i18n.js";
import Tooltip from "./Tooltip.jsx";
import WaveformDisplay from "./WaveformDisplay.jsx";

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function SongCard({ song, onRemove }) {
  const bpmBadge =
    song.bpmConfidence === "low"
      ? "badge--warn"
      : song.bpmConfidence === "unreliable"
      ? "badge--error"
      : "badge--ok";

  const showBpmWarning =
    song.bpmConfidence === "low" || song.bpmConfidence === "unreliable";

  return (
    <div className="song-card">
      <div className="song-card__header">
        <span className="song-card__name" title={song.filename}>
          {song.filename}
        </span>
        <span className="song-card__actions">
          <Tooltip text={t("tooltipRemoveSong")} />
          <button
            className="btn btn--ghost btn--xs"
            onClick={() => onRemove(song.fileId)}
            aria-label={t("removeSong")}
          >
            ✕
          </button>
        </span>
      </div>

      <div className="song-card__meta">
        <span className={`badge ${bpmBadge}`}>
          {song.bpm.toFixed(1)} {t("bpm")}
          {showBpmWarning && (
            <Tooltip text={t("tooltipBpmBadge")} />
          )}
        </span>
        <span className="badge badge--dim">
          {formatDuration(song.durationSeconds)}
        </span>
      </div>

      <WaveformDisplay
        amplitudes={song.waveformAmplitudes}
        durationSeconds={song.durationSeconds}
        variant="mini"
      />
    </div>
  );
}

export default function SongLibrary() {
  const { songs, addSong, removeSong } = useApp();
  const [uploading, setUploading] = useState({}); // fileId or tempId → status string
  const [errors, setErrors] = useState({}); // tempId → error string
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const processFile = useCallback(
    async (file) => {
      const tempId = `${file.name}-${file.size}`;
      setUploading((p) => ({ ...p, [tempId]: "uploading" }));
      setErrors((p) => { const n = { ...p }; delete n[tempId]; return n; });

      try {
        const { file_id } = await uploadFile(file);
        setUploading((p) => ({ ...p, [tempId]: "analyzing" }));

        const [analysis, waveformData] = await Promise.all([
          analyzeFile(file_id),
          getWaveform(file_id, 200),
        ]);

        addSong({
          fileId: file_id,
          filename: file.name,
          bpm: analysis.bpm,
          bpmConfidence: analysis.bpm_confidence,
          durationSeconds: analysis.duration_seconds,
          waveformAmplitudes: waveformData.amplitudes,
        });
      } catch (err) {
        setErrors((p) => ({ ...p, [tempId]: err.message ?? t("uploadError") }));
      } finally {
        setUploading((p) => { const n = { ...p }; delete n[tempId]; return n; });
      }
    },
    [addSong]
  );

  const handleFiles = useCallback(
    (files) => {
      const audioFiles = Array.from(files).filter((f) =>
        f.name.match(/\.(mp3|wav)$/i)
      );
      audioFiles.forEach(processFile);
    },
    [processFile]
  );

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const onDragOver = (e) => { e.preventDefault(); setDragOver(true); };
  const onDragLeave = () => setDragOver(false);

  const pendingCount = Object.keys(uploading).length;
  const errorEntries = Object.entries(errors);

  return (
    <section className="panel song-library">
      <h2 className="panel__title">{t("songLibrary")}</h2>

      {/* Drop zone */}
      <div
        className={`drop-zone${dragOver ? " drop-zone--active" : ""}`}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      >
        <span className="drop-zone__icon">🎵</span>
        <span className="drop-zone__text">{t("dropZone")}</span>
        <span className="drop-zone__sub">{t("dropZoneOr")}</span>
        <input
          ref={inputRef}
          type="file"
          accept=".mp3,.wav"
          multiple
          style={{ display: "none" }}
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {/* In-progress uploads */}
      {pendingCount > 0 && (
        <div className="upload-progress">
          {Object.entries(uploading).map(([id, status]) => (
            <div key={id} className="upload-progress__item">
              <span className="spinner" />
              <span>
                {status === "uploading" ? t("uploading") : t("analyzing")}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Per-file errors */}
      {errorEntries.map(([id, msg]) => (
        <div key={id} className="error-banner">
          {t("uploadError")}: {msg}
        </div>
      ))}

      {/* Song list */}
      <div className="song-list">
        {songs.length === 0 && pendingCount === 0 ? (
          <p className="empty-hint">{t("noSongs")}</p>
        ) : (
          songs.map((song) => (
            <SongCard
              key={song.fileId}
              song={song}
              onRemove={removeSong}
            />
          ))
        )}
      </div>
    </section>
  );
}
