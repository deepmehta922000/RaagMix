import React, { useRef, useState, useEffect } from "react";
import { getFileUrl } from "../api.js";
import { useApp } from "../context/AppContext.jsx";
import { t } from "../i18n.js";
import Tooltip from "./Tooltip.jsx";

function formatTime(seconds) {
  if (!isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function PlaybackControls() {
  const { remixResult } = useApp();
  const audioRef = useRef(null);
  const [playState, setPlayState] = useState("stopped"); // "stopped" | "playing" | "paused"
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const outputFileId = remixResult?.outputFileId ?? null;
  const audioUrl = outputFileId ? getFileUrl(outputFileId) : null;

  // Reset player when a new mix is generated
  useEffect(() => {
    setPlayState("stopped");
    setCurrentTime(0);
    setDuration(0);
  }, [outputFileId]);

  function handlePlay() {
    const audio = audioRef.current;
    if (!audio) return;
    audio.play();
    setPlayState("playing");
  }

  function handlePause() {
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    setPlayState("paused");
  }

  function handleStop() {
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    audio.currentTime = 0;
    setPlayState("stopped");
    setCurrentTime(0);
  }

  function handleSeek(e) {
    const audio = audioRef.current;
    if (!audio || !duration) return;
    const frac = parseFloat(e.target.value) / 100;
    audio.currentTime = frac * duration;
  }

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <section className="panel playback-panel">
      <h2 className="panel__title">{t("playback")}</h2>

      {!audioUrl ? (
        <p className="hint-text">{t("noOutput")}</p>
      ) : (
        <>
          {/* Hidden audio element */}
          <audio
            ref={audioRef}
            src={audioUrl}
            onTimeUpdate={() => setCurrentTime(audioRef.current?.currentTime ?? 0)}
            onDurationChange={() => setDuration(audioRef.current?.duration ?? 0)}
            onEnded={() => setPlayState("stopped")}
            preload="metadata"
          />

          {/* Seek bar */}
          <div className="seek-bar">
            <span className="seek-bar__time">{formatTime(currentTime)}</span>
            <input
              type="range"
              className="seek-bar__slider"
              min={0}
              max={100}
              step={0.1}
              value={progress}
              onChange={handleSeek}
            />
            <span className="seek-bar__time">{formatTime(duration)}</span>
          </div>

          {/* Transport buttons */}
          <div className="transport">
            {playState === "playing" ? (
              <button className="btn btn--transport" onClick={handlePause} title={t("pause")}>
                ⏸
              </button>
            ) : (
              <button className="btn btn--transport" onClick={handlePlay} title={t("play")}>
                ▶
              </button>
            )}
            <button className="btn btn--transport" onClick={handleStop} title={t("stop")}>
              ⏹
            </button>
            <Tooltip text={`${t("tooltipPlay")} / ${t("tooltipStop")}`} />
          </div>
        </>
      )}
    </section>
  );
}
