import React, { createContext, useContext, useState, useCallback } from "react";

const AppContext = createContext(null);

export function AppProvider({ children }) {
  // Master list of uploaded + analyzed songs
  // Shape: { fileId, filename, bpm, bpmConfidence, durationSeconds, waveformAmplitudes }
  const [songs, setSongs] = useState([]);

  // Output of either remix endpoint
  // Shape: { outputFileId, targetBpm, stepsCompleted, stepResults, ... }
  const [remixResult, setRemixResult] = useState(null);

  // Global processing lock — disables remix buttons while a request is in flight
  const [isProcessing, setIsProcessing] = useState(false);

  // Last error message to display in the remix panel
  const [processingError, setProcessingError] = useState(null);

  const addSong = useCallback((song) => {
    setSongs((prev) => {
      // Guard against duplicate file_ids (e.g. same file dropped twice)
      if (prev.some((s) => s.fileId === song.fileId)) return prev;
      return [...prev, song];
    });
  }, []);

  const removeSong = useCallback((fileId) => {
    setSongs((prev) => prev.filter((s) => s.fileId !== fileId));
  }, []);

  const clearRemixResult = useCallback(() => {
    setRemixResult(null);
    setProcessingError(null);
  }, []);

  return (
    <AppContext.Provider
      value={{
        songs,
        remixResult,
        isProcessing,
        processingError,
        addSong,
        removeSong,
        setRemixResult,
        setIsProcessing,
        setProcessingError,
        clearRemixResult,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
