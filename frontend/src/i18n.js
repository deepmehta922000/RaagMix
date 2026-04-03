// All visible UI strings in English.
// Usage:  import { t } from '../i18n.js'
//         t("dropZone")   →  "Drop songs here"

const STRINGS = {
  // ── App shell ───────────────────────────────────────────────────────────────
  appTitle:         "RaagMix",
  appSubtitle:      "AI-Powered Music Remix",
  backendOffline:   "Backend offline — start the Python server",

  // ── Song Library ────────────────────────────────────────────────────────────
  songLibrary:      "Song Library",
  dropZone:         "Drop MP3 / WAV files here",
  dropZoneOr:       "or click to browse",
  uploading:        "Uploading…",
  analyzing:        "Analyzing…",
  uploadError:      "Upload failed",
  noSongs:          "No songs yet. Upload to get started.",
  bpm:              "BPM",
  duration:         "Duration",
  removeSong:       "Remove",
  bpmLow:           "BPM estimate low confidence",
  bpmUnreliable:    "BPM unreliable",

  // ── Remix Panel tabs ────────────────────────────────────────────────────────
  remixPanel:       "Remix",
  tabAI:            "AI Remix",
  tabManual:        "Manual Remix",
  selectSongs:      "Select at least 2 songs from the library to remix.",

  // ── AI Remix tab ────────────────────────────────────────────────────────────
  promptLabel:      "Describe your remix",
  promptPlaceholder:"e.g. Blend these into a high-energy Bollywood dance mix with a strong beat drop",
  remixBtn:         "Generate Remix",
  generating:       "Generating…",
  remixSuccess:     "Remix ready!",
  remixError:       "Remix failed",
  stepsCompleted:   "steps completed",
  targetBpm:        "Target BPM",

  // ── Preset Selector ─────────────────────────────────────────────────────────
  presetLabel:              "Style Preset",
  presetNone:               "None",
  preset_bollywood_dance:   "Bollywood Dance",
  preset_contemporary:      "Contemporary",
  preset_wedding_mashup:    "Wedding Mashup",
  preset_warmup:            "Warmup",
  presetBpmRange_bollywood_dance:  "120–130 BPM",
  presetBpmRange_contemporary:     "90–110 BPM",
  presetBpmRange_wedding_mashup:   "95–120 BPM",
  presetBpmRange_warmup:           "85–100 BPM",

  // ── Manual Remix tab ────────────────────────────────────────────────────────
  addSegment:       "Add Segment",
  removeSegment:    "Remove",
  segmentSong:      "Song",
  segmentStart:     "Start (mm:ss)",
  segmentEnd:       "End (mm:ss)",
  crossfadeNext:    "Crossfade to next",
  skipStretch:      "Skip BPM stretch",
  targetBpmLabel:   "Target BPM (optional)",
  crossfadeSec:     "Crossfade (sec)",
  fadeType:         "Fade Type",
  fadeLinear:       "Linear",
  fadeLogarithmic:  "Logarithmic",
  buildMix:         "Build Mix",
  building:         "Building…",
  selectSong:       "— select song —",
  segmentN:         "Segment",
  fadeOutSec:       "Fade Out (sec)",
  vocalDuck:        "Vocal Duck",

  // ── Waveform ─────────────────────────────────────────────────────────────────
  waveformLoading:  "Loading waveform…",
  waveformError:    "Waveform unavailable",
  markerStart:      "Start",
  markerEnd:        "End",

  // ── Playback Controls ────────────────────────────────────────────────────────
  playback:         "Playback",
  play:             "Play",
  pause:            "Pause",
  stop:             "Stop",
  noOutput:         "No mix yet — generate a remix first.",

  // ── Export Panel ─────────────────────────────────────────────────────────────
  export:           "Export",
  downloadWav:      "Download WAV",
  noOutputExport:   "Generate a remix to enable export.",

  // ── Tooltips ─────────────────────────────────────────────────────────────────
  tooltipTargetBpm:         "All segments are time-stretched to this BPM. Leave blank to keep original tempos.",
  tooltipCrossfadeSec:      "How many seconds the two tracks overlap during a transition. Longer = smoother blend.",
  tooltipFadeType:          "Linear: smooth equal-volume blend. Logarithmic: equal-loudness curve that sounds more natural at the crossover point.",
  tooltipFadeOut:           "Smoothly fades the remix to silence at the end. Set to 0 to disable.",
  tooltipAlignBeats:        "Snaps the transition to the nearest 8-bar phrase boundary and aligns beat grids so the two tracks stay in rhythm.",
  tooltipEqCrossfade:       "Cuts bass below 200 Hz during the overlap to prevent muddy double kick-drums, then restores bass on the drop.",
  tooltipVocalDuck:         "Removes vocals during the crossfade so only instrumentals blend. Vocals return after the transition. Requires Spleeter.",
  tooltipSkipStretch:       "Keep this segment at its original speed. Use for dialogue clips or sound effects that shouldn't be pitch-shifted.",
  tooltipCrossfadeWithNext: "Blend this segment into the next with a crossfade. Turn off for a hard cut (instant switch).",
  tooltipBuildMix:          "Extracts all segments, stretches them to the target BPM, then chains them together with crossfades.",
  tooltipPreset:            "Pre-configured style settings. Bollywood Dance targets 120–130 BPM, Wedding Mashup 95–120, etc.",
  tooltipPrompt:            "Describe the remix you want — mood, energy level, transitions. Gemini AI will plan the mix.",
  tooltipGenerateRemix:     "Sends your prompt and songs to Gemini AI, which generates and executes a multi-step remix plan.",
  tooltipBpmBadge:          "BPM confidence is low on short clips or tracks with irregular rhythm. Time-stretch results may be less accurate.",
  tooltipRemoveSong:        "Remove this song from the library. The original file is not deleted from disk.",
  tooltipPlay:              "Play the generated remix from the current position.",
  tooltipPause:             "Pause playback.",
  tooltipStop:              "Stop playback and return to the beginning.",
  tooltipDownloadWav:       "Save the remix as a lossless 16-bit WAV file.",
};

/**
 * Return the English string for a UI key.
 * The second argument is accepted but ignored (previously the language code).
 * @param {string} key
 * @returns {string}
 */
export function t(key) {
  return STRINGS[key] ?? key; // missing key — surface it visibly for debugging
}

export default STRINGS;
