# Project Guidelines & Architecture Standards

This document defines the engineering standards for this repository. It applies to
the current codebase (`Y99 Filter Bot` — a Python desktop automation app) and to any
future modules added to it.

## 1. Core Operational Behavior
- **Zero-Cost First:** Prefer open-source, programmatic, and free tools (Playwright,
  FFmpeg, Python standard library / PyPI packages, local models) over paid SaaS APIs.
  This project already follows that principle: browser automation via Playwright,
  GUI via CustomTkinter, packaging via PyInstaller — no paid services involved.
- **Autonomous Problem Solving:** When something breaks, read the stack trace, find
  the root cause in `bot_core.py` / `main_gui.py`, and fix it directly instead of
  papering over the symptom. Only stop to ask when a decision requires information
  only the user has (credentials, target site behavior, desired UX tradeoffs).
- **Production Quality:** New code should be modular (keep automation logic in
  `bot_core.py`, UI logic in `main_gui.py` — do not mix the two), handle errors from
  the browser/network explicitly, and avoid busy-waiting where an event/callback is
  possible.

## 2. Desktop Application & Standalone Executable (.exe)
- **Native Windows Executable Build:** Keep the app packageable into a single
  zero-dependency `.exe` via PyInstaller (`build_exe.bat`). Any new dependency added
  to `requirements.txt` must also be added to `build_exe.bat` as a `--hidden-import`
  if PyInstaller can't auto-detect it, and verified to not break the onefile build.
- **World-Class Modern UI:** The GUI is built with CustomTkinter (`main_gui.py`) with
  a dark theme, card-based layout, live stats, and a color-coded log panel. Keep new
  UI additions consistent with the existing theme constants (`BG`, `CARD`, `ACCENT`,
  etc.) rather than introducing ad hoc colors.
- **Smooth UX:** Preserve fast startup, non-blocking UI (bot runs on a background
  thread, callbacks marshal back to the Tk main loop via `self.after(...)`), and
  clear real-time status/log feedback for every state transition.

## 3. Multilingual & Voice Capabilities
- **Universal Language Support:** The current UI is Arabic-first. If English (or
  other language) support is added, structure UI strings so they can be swapped via
  an i18n layer rather than hardcoding text inline throughout `main_gui.py`.
- **Voice Interaction Pipeline:** If voice command / STT / TTS features are added,
  use open-source frameworks (e.g., OpenAI Whisper or Vosk for STT; a local/open TTS
  engine for output) to keep the project dependency-free of paid APIs, consistent
  with the Zero-Cost First principle above.

## 4. Automation, Media & Security Standards
- **Web & Process Automation:** Browser automation goes through Playwright
  (`bot_core.Y99Bot`), driving Chromium directly rather than scraping HTML statically,
  since the target site is JS-rendered. Keep automation logic resilient to timing
  issues (see `_wait_reply`'s baseline/diff approach to avoid re-processing stale
  text) and avoid brittle fixed sleeps where a poll/deadline loop is more robust.
- **Media Processing:** If video/audio processing is ever needed, use FFmpeg driven
  from Python rather than a paid transcoding service.
- **Security Engineering:** Validate all user-supplied settings before use (see
  `App._read_settings` validating wait times), never execute untrusted input as code,
  and keep local config (`y99_settings.json`) out of version control (already
  excluded via `.gitignore`).

## 5. Development Workflow
1. Break new work into clear modules: automation/core logic vs. UI vs. build tooling.
2. Reuse or extend existing open-source integrations already in this repo
   (Playwright, CustomTkinter, PyInstaller) before introducing new dependencies.
3. Deliver fully tested, executable code, and update `build_exe.bat` /
   `requirements.txt` / `README.md` whenever the build or run instructions change.
