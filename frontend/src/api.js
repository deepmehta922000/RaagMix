const API_BASE = "http://localhost:8000";

// ── Typed error ────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(status, code, detail) {
    super(detail || code);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function _handleResponse(res) {
  if (res.ok) return res.json();
  let body;
  try {
    body = await res.json();
  } catch {
    body = {};
  }
  const code = body?.error ?? "unknown_error";
  const detail = body?.detail ?? res.statusText;
  throw new ApiError(res.status, code, typeof detail === "string" ? detail : JSON.stringify(detail));
}

// ── Health ─────────────────────────────────────────────────────────────────────

export async function checkHealth() {
  const res = await fetch(`${API_BASE}/health`);
  return _handleResponse(res);
}

// ── Upload ─────────────────────────────────────────────────────────────────────

/**
 * Upload a single audio File object.
 * @returns {{ file_id: string, filename: string, size_bytes: number }}
 */
export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: form });
  return _handleResponse(res);
}

// ── Analyze ────────────────────────────────────────────────────────────────────

/**
 * Analyze BPM and duration for an uploaded file.
 * @returns {{ file_id, bpm, bpm_confidence, duration_seconds }}
 */
export async function analyzeFile(fileId) {
  const res = await fetch(`${API_BASE}/analyze/${fileId}`, { method: "POST" });
  return _handleResponse(res);
}

// ── Waveform ───────────────────────────────────────────────────────────────────

/**
 * Fetch downsampled peak-amplitude waveform data.
 * @returns {{ file_id, amplitudes: number[], duration_seconds, num_points }}
 */
export async function getWaveform(fileId, numPoints = 200) {
  const res = await fetch(`${API_BASE}/waveform/${fileId}?num_points=${numPoints}`);
  return _handleResponse(res);
}

// ── AI Remix ───────────────────────────────────────────────────────────────────

/**
 * Generate and execute an AI mix plan via Gemini.
 * @param {string[]} fileIds
 * @param {string} userPrompt
 * @param {string|null} preset
 * @param {Record<string,string>} filenames  map of fileId → display name
 * @returns {{ output_file_id, target_bpm, steps_completed, step_results, plan }}
 */
export async function remix(fileIds, userPrompt, preset = null, filenames = {}) {
  const res = await fetch(`${API_BASE}/remix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_ids: fileIds, user_prompt: userPrompt, preset, filenames }),
  });
  return _handleResponse(res);
}

// ── Manual Remix ───────────────────────────────────────────────────────────────

/**
 * Execute a manual timestamp-based remix.
 * @param {object[]} segments  [{ file_id, start_time, end_time, order, crossfade_with_next, skip_stretch }]
 * @param {number|null} targetBpm
 * @param {number} crossfadeSeconds
 * @param {string} fadeType  "linear" | "logarithmic"
 * @returns {{ output_file_id, target_bpm, segments_processed, ... }}
 */
export async function remixManual(
  segments,
  targetBpm = null,
  crossfadeSeconds = 2.0,
  fadeType = "linear",
  fadeOutSeconds = 3.0,
  vocalDuck = false,
) {
  const res = await fetch(`${API_BASE}/remix/manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      segments,
      target_bpm: targetBpm,
      crossfade_seconds: crossfadeSeconds,
      fade_type: fadeType,
      fade_out_seconds: fadeOutSeconds,
      vocal_duck: vocalDuck,
    }),
  });
  return _handleResponse(res);
}

// ── File serving ───────────────────────────────────────────────────────────────

/**
 * Returns the URL to stream or download a file by file_id.
 * Used as <audio src> and <a href download>.
 */
export function getFileUrl(fileId) {
  return `${API_BASE}/files/${fileId}`;
}
