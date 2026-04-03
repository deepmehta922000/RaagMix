import React from "react";
import { t } from "../i18n.js";

const PRESETS = [
  { key: "bollywood_dance", icon: "💃" },
  { key: "contemporary",    icon: "🎶" },
  { key: "wedding_mashup",  icon: "💍" },
  { key: "warmup",          icon: "🔥" },
];

export default function PresetSelector({ selected, onSelect }) {
  return (
    <div className="preset-selector">
      <span className="preset-selector__label">{t("presetLabel")}</span>
      <div className="preset-selector__row">
        {/* "None" chip */}
        <button
          className={`preset-card${!selected ? " preset-card--active" : ""}`}
          onClick={() => onSelect(null)}
        >
          <span className="preset-card__icon">✕</span>
          <span className="preset-card__name">{t("presetNone")}</span>
        </button>

        {PRESETS.map(({ key, icon }) => (
          <button
            key={key}
            className={`preset-card${selected === key ? " preset-card--active" : ""}`}
            onClick={() => onSelect(selected === key ? null : key)}
          >
            <span className="preset-card__icon">{icon}</span>
            <span className="preset-card__name">{t(`preset_${key}`)}</span>
            <span className="preset-card__bpm">{t(`presetBpmRange_${key}`)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
