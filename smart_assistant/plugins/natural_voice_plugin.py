"""Explicit modern speech rendering through an isolated Python runtime."""
from pathlib import Path
import wave

import natural_voice_runtime as nvr


def _render(ctx):
    if len(ctx.args) not in (3, 4):
        return 'usage: natural_voice <ar|en> "text" <output.wav> [authorized-reference.wav]'
    language, text, output = ctx.args[:3]
    if language not in {"ar", "en"} or not text.strip() or len(text) > 5000:
        return "❌ use ar/en and 1–5000 characters"
    output = Path(output).resolve()
    if output.suffix.lower() != ".wav":
        return "❌ output must be a WAV file"
    if output.exists():
        return "❌ output already exists; choose a new filename"
    reference = str(Path(ctx.args[3]).resolve()) if len(ctx.args) == 4 else None
    if reference and not Path(reference).is_file():
        return "❌ reference audio not found"
    ok, detail = nvr.render(text, language, output, Path(reference) if reference else None)
    if not ok:
        return "❌ natural speech failed: " + detail
    with wave.open(str(output), "rb") as wav:
        seconds = wav.getnframes() / wav.getframerate()
    return f"✅ Chatterbox Multilingual V3: {seconds:.1f}s at {output}"


def _setup(ctx):
    if len(ctx.args) != 1:
        current = nvr.runtime_path() or "not configured"
        return f"Natural voice runtime: {current}\nusage: natural_voice_setup <python.exe|clear>"
    if ctx.args[0].lower() == "clear":
        nvr.configure(None)
        return "✅ saved natural voice runtime cleared"
    runtime = Path(ctx.args[0]).expanduser().resolve()
    if not runtime.is_file() or runtime.suffix.lower() != ".exe":
        return "❌ choose an existing Python executable from the isolated Chatterbox environment"
    nvr.configure(runtime)
    return f"✅ natural voice runtime saved: {runtime}"


def register(engine):
    engine.registry.register("natural_voice_setup", _setup,
        "natural_voice_setup <python.exe|clear> — persist the isolated Chatterbox runtime")
    engine.registry.register("natural_voice", _render,
        'natural_voice <ar|en> "text" <output.wav> [reference.wav] — Chatterbox V3, isolated runtime')
