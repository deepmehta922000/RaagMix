from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "bollywood_dance": {
        "id": "bollywood_dance",
        "display_name": "बॉलीवुड डांस / Bollywood Dance",
        "target_bpm_range": {"min": 120.0, "max": 130.0},
        "default_crossfade_ms": 2000,
        "default_fade_type": "logarithmic",
        "instructions": (
            "This is a high-energy Bollywood dance mix. Follow these guidelines:\n"
            "- Target BPM must be between 120 and 130.\n"
            "- Use \"logarithmic\" fade_type on all crossfade steps to maintain energy at "
            "transition points. Never use \"linear\" for this preset.\n"
            "- Identify a dhol-prominent or percussion-heavy section in each song "
            "(typically the first 30–60 seconds or a chorus at ~60–90% through the track). "
            "Use extract_loop to create a loop from that section (loop_count: 1), then place "
            "it as a bridge between two crossfade steps for a beat-drop effect.\n"
            "- Transitions should feel like a DJ set: tight overlaps (1500–3000 ms), not long blends.\n"
            "- If a song's BPM is below 100, do not include it; flag it in \"description\".\n"
            "- Arrange songs in energy-ascending order (lowest BPM first, then stretched up)."
        ),
    },
    "contemporary": {
        "id": "contemporary",
        "display_name": "कॉन्टेम्परेरी / Contemporary",
        "target_bpm_range": {"min": 90.0, "max": 110.0},
        "default_crossfade_ms": 8000,
        "default_fade_type": "linear",
        "instructions": (
            "This is a smooth contemporary mix. Follow these guidelines:\n"
            "- Target BPM must be between 90 and 110.\n"
            "- Use \"linear\" fade_type on all crossfade steps for a gentle, cinematic blend.\n"
            "- Crossfade durations should be long: 6000–12000 ms. Short cuts are not "
            "appropriate for this preset.\n"
            "- Avoid extract_loop unless the user explicitly asks for a repeat section. "
            "Loops interrupt the flowing, minimal feel of this preset.\n"
            "- Prefer stretching all tracks to the median BPM of the input set rather "
            "than the maximum BPM.\n"
            "- Keep the plan simple: time_stretch each track, then chain crossfades. "
            "Do not add unnecessary steps."
        ),
    },
    "wedding_mashup": {
        "id": "wedding_mashup",
        "display_name": "वेडिंग माशप / Wedding Mashup",
        "target_bpm_range": {"min": 95.0, "max": 120.0},
        "default_crossfade_ms": 3000,
        "default_fade_type": "linear",
        "instructions": (
            "This is a crowd-friendly wedding medley. Follow these guidelines:\n"
            "- Target BPM must be between 95 and 120. Choose a BPM near 110 if songs "
            "span a wide tempo range.\n"
            "- Designed for 5–6 songs. If fewer than 5 are provided, note it in "
            "\"description\" but proceed.\n"
            "- Use extract_loop to take the most recognizable hook section of each song "
            "(typically a 16–32 bar chorus). Loop it once (loop_count: 1), then crossfade "
            "to the next song's hook. This creates a medley of highlights.\n"
            "- Crossfade duration: 2000–4000 ms. Clean and punctual, not blurry.\n"
            "- After every 2 songs, insert a 4-bar drum intro loop (extract_loop from the "
            "percussion-heavy intro of the next track) before the crossfade.\n"
            "- Do not stretch any song by more than 15% (keep stretch ratio in [0.85, 1.15])."
        ),
    },
    "warmup": {
        "id": "warmup",
        "display_name": "वार्मअप / Warmup",
        "target_bpm_range": {"min": 85.0, "max": 100.0},
        "default_crossfade_ms": 5000,
        "default_fade_type": "linear",
        "instructions": (
            "This is a warmup set with gradually increasing energy. Follow these guidelines:\n"
            "- Begin at the lowest available BPM among input songs (or 85.0, whichever is "
            "higher) and step up toward 100 BPM across the set.\n"
            "- Sort songs in ascending BPM order. If a song's natural BPM already exceeds "
            "100, place it at the end and stretch down lightly, or omit it and note it.\n"
            "- Assign a unique target_bpm to each time_stretch step — do not stretch all "
            "songs to the same BPM. Each track should be 3–8 BPM higher than the previous.\n"
            "- Use gentle transitions: crossfade_ms between 4000 and 8000, fade_type "
            "\"linear\". No beat drops, no extract_loop for percussion emphasis.\n"
            "- The plan's top-level target_bpm should be the BPM of the final (fastest) song.\n"
            "- Keep the total planned mix duration under 30 minutes."
        ),
    },
}


def get_preset(preset_id: str) -> dict[str, Any] | None:
    """Return the preset dict for the given id, or None if not found."""
    return PRESETS.get(preset_id)
