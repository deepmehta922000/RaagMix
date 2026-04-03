import React from "react";
import { getFileUrl } from "../api.js";
import { useApp } from "../context/AppContext.jsx";
import { t } from "../i18n.js";
import Tooltip from "./Tooltip.jsx";

export default function ExportPanel() {
  const { remixResult } = useApp();
  const outputFileId = remixResult?.outputFileId ?? null;

  return (
    <section className="panel export-panel">
      <h2 className="panel__title">{t("export")}</h2>

      {!outputFileId ? (
        <p className="hint-text">{t("noOutputExport")}</p>
      ) : (
        <div className="export-buttons">
          <div className="btn-row">
            <a
              className="btn btn--export"
              href={getFileUrl(outputFileId)}
              download={`raagmix_${outputFileId.slice(0, 8)}.wav`}
            >
              ⬇ {t("downloadWav")}
            </a>
            <Tooltip text={t("tooltipDownloadWav")} />
          </div>
        </div>
      )}
    </section>
  );
}
