"""Explicit VoiceTut and Chatterbox rendering through isolated runtimes."""
from pathlib import Path
import wave

import natural_voice_runtime as nvr
import voicetut_runtime as vtr

_HUMAN_SPEAKERS = {"Asmaa", "Esraa", "Hanan", "Sarah", "Yasmin", "Omnia"}


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


def _human_setup(ctx):
    if not ctx.args:
        runtime, model, speaker, steps = vtr._settings()
        return (f"VoiceTut runtime: {runtime or 'not configured'}\n"
                f"Model: {model or 'not configured'}\nSpeaker: {speaker}\nQuality steps: {steps}\n"
                "usage: human_voice_setup <python.exe> <model-directory> [speaker=Omnia] [steps=48] | clear")
    if len(ctx.args) == 1 and ctx.args[0].lower() == "clear":
        vtr.configure(None)
        return "✅ VoiceTut human voice configuration cleared"
    if len(ctx.args) < 2:
        return "usage: human_voice_setup <python.exe> <model-directory> [speaker=Omnia] [steps=48]"
    runtime = Path(ctx.args[0]).expanduser().resolve()
    model = Path(ctx.args[1]).expanduser().resolve()
    speaker, steps = vtr.DEFAULT_SPEAKER, vtr.DEFAULT_STEPS
    for item in ctx.args[2:]:
        if item.startswith("speaker="):
            speaker = item.split("=", 1)[1]
        elif item.startswith("steps="):
            try:
                steps = int(item.split("=", 1)[1])
            except ValueError:
                return "❌ steps must be an integer from 16 to 64"
    if not runtime.is_file() or runtime.suffix.lower() != ".exe":
        return "❌ choose an existing Python executable from the isolated VoiceTut environment"
    if not (model / "model.safetensors").is_file():
        return "❌ choose the downloaded VoiceTut model directory containing model.safetensors"
    if speaker not in _HUMAN_SPEAKERS or not 16 <= steps <= 64:
        return "❌ speaker must be Asmaa, Esraa, Hanan, Sarah, Yasmin, or Omnia; steps must be 16-64"
    vtr.configure(runtime, model, speaker, steps)
    return f"✅ VoiceTut saved: {speaker}, {steps} quality steps, model {model}"


def _human_render(ctx):
    if len(ctx.args) not in (3, 4):
        return 'usage: human_voice <ar|en> "text" <output.wav> [authorized-reference.wav]'
    language, text, output = ctx.args[:3]
    if language not in {"ar", "en"} or not text.strip() or len(text) > 5000:
        return "❌ use ar/en and 1-5000 characters"
    output = Path(output).resolve()
    if output.suffix.lower() != ".wav" or output.exists():
        return "❌ choose a new .wav output filename"
    reference = Path(ctx.args[3]).resolve() if len(ctx.args) == 4 else None
    if reference and not reference.is_file():
        return "❌ reference audio not found"
    ok, detail = vtr.render(text, language, output, reference)
    if not ok:
        return "❌ VoiceTut speech failed: " + detail
    with wave.open(str(output), "rb") as wav:
        seconds = wav.getnframes() / wav.getframerate()
    return f"✅ VoiceTut Egyptian human voice: {seconds:.1f}s at {output}"


def register(engine):
    engine.registry.register("human_voice_setup", _human_setup,
        "human_voice_setup <python.exe> <model-dir> [speaker=Omnia] [steps=48] — configure VoiceTut")
    engine.registry.register("human_voice", _human_render,
        'human_voice <ar|en> "text" <output.wav> [reference.wav] — Egyptian human-trained TTS')
    engine.registry.register("natural_voice_setup", _setup,
        "natural_voice_setup <python.exe|clear> — persist the isolated Chatterbox runtime")
    engine.registry.register("natural_voice", _render,
        'natural_voice <ar|en> "text" <output.wav> [reference.wav] — Chatterbox V3, isolated runtime')
