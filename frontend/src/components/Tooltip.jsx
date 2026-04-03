import React, { useState } from "react";

/**
 * Inline ? icon that shows a floating help bubble on hover or click/tap.
 *
 * Usage:
 *   <Tooltip text={t("tooltipTargetBpm")} />
 *
 * The bubble anchors to the right edge of the trigger and opens upward,
 * so it never overflows the panel edge.
 */
export default function Tooltip({ text }) {
  const [visible, setVisible] = useState(false);

  return (
    <span className="tooltip-wrap">
      <button
        type="button"
        className="tooltip-trigger"
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        onClick={() => setVisible((v) => !v)}
        aria-label="Help"
      >
        ?
      </button>
      {visible && (
        <span className="tooltip-bubble" role="tooltip">
          {text}
        </span>
      )}
    </span>
  );
}
