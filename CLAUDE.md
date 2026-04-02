# RaagMix — AI-Powered Music Remix Tool

## Project Summary
Desktop app for a Bollywood/contemporary dance studio owner in India. She uploads multiple songs and gives remix instructions (text prompts or presets). The app remixes them like a professional editor with BPM matching, crossfading, beat-drop transitions, looping, real-time playback, and export to MP3/WAV.

## Tech Stack
- Desktop shell: Electron + React (frontend/)
- Audio engine: Python 3.10 + librosa + pydub + FastAPI (backend/)
- AI remix brain: Gemini API for mix plan generation
- Packaging: Electron Builder (Windows + Mac)

## Project Structure
- Monorepo with two main directories: frontend/ and backend/
- frontend/ is an Electron + React app using Vite as the bundler
- backend/ is a FastAPI server that handles all audio processing
- The frontend communicates with the backend over HTTP (localhost)

## Conventions
- Python: use type hints, Black formatter, 88-char line length
- JavaScript/React: use functional components, hooks, ES modules
- All API endpoints go in backend/routers/ as separate files
- Use descriptive commit messages in imperative mood (e.g. "Add BPM detection endpoint")
- Hindi + English bilingual UI (labels in both languages)

## Current Phase
Phase 3 — AI Remix Brain: Gemini API integration for natural language remix instructions, style presets (Bollywood/contemporary), JSON mix plan generator, mix plan executor that chains audio engine endpoints.
