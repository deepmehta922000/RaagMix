import React, { useEffect, useState } from "react";
import { AppProvider } from "./context/AppContext.jsx";
import SongLibrary from "./components/SongLibrary.jsx";
import RemixPanel from "./components/RemixPanel.jsx";
import PlaybackControls from "./components/PlaybackControls.jsx";
import ExportPanel from "./components/ExportPanel.jsx";
import { checkHealth } from "./api.js";
import { t } from "./i18n.js";

function Studio() {
  const [backendOk, setBackendOk] = useState(null); // null = checking, true, false

  useEffect(() => {
    checkHealth()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false));
  }, []);

  return (
    <div className="app-shell">
      {/* ── Header ── */}
      <header className="app-header">
        <div className="app-header__brand">
          <span className="app-header__logo">🎵</span>
          <span className="app-header__title">{t("appTitle")}</span>
          <span className="app-header__subtitle">{t("appSubtitle")}</span>
        </div>

        <div className="app-header__right">
          {backendOk === false && (
            <span className="status-badge status-badge--error">
              {t("backendOffline")}
            </span>
          )}
          {backendOk === true && (
            <span className="status-badge status-badge--ok">● online</span>
          )}
        </div>
      </header>

      {/* ── Main layout ── */}
      <main className="app-main">
        {/* Left column: song library */}
        <aside className="col col--left">
          <SongLibrary />
        </aside>

        {/* Centre column: remix controls */}
        <section className="col col--centre">
          <RemixPanel />
        </section>

        {/* Right column: playback + export */}
        <aside className="col col--right">
          <PlaybackControls />
          <ExportPanel />
        </aside>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Studio />
    </AppProvider>
  );
}
