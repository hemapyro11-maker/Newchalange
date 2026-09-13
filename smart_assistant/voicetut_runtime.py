"""Run the optional Egyptian VoiceTut engine outside Nezuko's GUI process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import wave

from voice_worker_runtime import PersistentVoiceWorker

DEFAULT_SPEAKER = "Omnia"
# 32 diffusion steps keeps the studio character while cutting synthesis latency
# materially on CPU. Users can still select 16-64 in configuration.
DEFAULT_STEPS = 32
_worker: PersistentVoiceWorker | None = None
_worker_lock = threading.Lock()
_warming = False


def _settings() -> tuple[Path | None, Path | None, str, int]:
    runtime_value = os.environ.get("NEZUKO_HUMAN_VOICE_PYTHON", "").strip()
    model_value = os.environ.get("NEZUKO_HUMAN_VOICE_MODEL", "").strip()
    speaker = os.environ.get("NEZUKO_HUMAN_VOICE_SPEAKER", "").strip()
    steps_value = os.environ.get("NEZUKO_HUMAN_VOICE_STEPS", "").strip()
    try:
        import brain
        cfg = brain.load_config()
    except (ImportError, AttributeError, OSError):
        cfg = {}
    runtime_value = runtime_value or str(cfg.get("human_voice_python", "")).strip()
    model_value = model_value or str(cfg.get("human_voice_model", "")).strip()
    speaker = speaker or str(cfg.get("human_voice_speaker", DEFAULT_SPEAKER)).strip()
    try:
        steps = int(steps_value or cfg.get("human_voice_steps", DEFAULT_STEPS))
    except (TypeError, ValueError):
        steps = DEFAULT_STEPS
    runtime = Path(runtime_value).expanduser() if runtime_value else None
    model = Path(model_value).expanduser() if model_value else None
    runtime = runtime.resolve() if runtime and runtime.is_file() else None
    model = model.resolve() if model and (model / "model.safetensors").is_file() else None
    return runtime, model, speaker or DEFAULT_SPEAKER, min(64, max(16, steps))


def runtime_path() -> Path | None:
    return _settings()[0]


def model_path() -> Path | None:
    return _settings()[1]


def available() -> bool:
    runtime, model, _speaker, _steps = _settings()
    return runtime is not None and model is not None


def configure(runtime: Path | None, model: Path | None = None,
              speaker: str = DEFAULT_SPEAKER, steps: int = DEFAULT_STEPS) -> None:
    import brain
    cfg = brain.load_config()
    if runtime is None:
        for key in ("human_voice_python", "human_voice_model", "human_voice_speaker",
                    "human_voice_steps"):
            cfg.pop(key, None)
    else:
        cfg["human_voice_python"] = str(runtime.resolve())
        if model is not None:
            cfg["human_voice_model"] = str(model.resolve())
        cfg["human_voice_speaker"] = speaker
        cfg["human_voice_steps"] = min(64, max(16, int(steps)))
    brain.save_config(cfg)


def _job(text: str, language: str, output: Path, model: Path, speaker: str,
         steps: int, reference: Path | None, reference_text: str | None) -> dict:
    return {
        "text": text, "language": language, "output": str(output),
        "model": str(model), "speaker": speaker, "steps": steps,
        "reference": str(reference.resolve()) if reference else None,
        "reference_text": reference_text,
    }


def _ensure_worker(runtime: Path, worker_script: Path, env: dict[str, str]) -> PersistentVoiceWorker:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.alive:
            _worker = PersistentVoiceWorker(runtime, worker_script, env)
        return _worker


def prewarm() -> None:
    """Load VoiceTut off the UI thread so the first spoken reply starts faster."""
    global _warming
    if _warming or not available():
        return
    _warming = True

    def warm() -> None:
        global _warming
        try:
            with tempfile.TemporaryDirectory(prefix="nezuko_voice_warmup_") as tmp:
                render("جاهزة", "ar", Path(tmp) / "warm.wav", timeout=1800, persistent=True)
        finally:
            _warming = False

    threading.Thread(target=warm, name="nezuko-voice-warmup", daemon=True).start()


def render(text: str, language: str, output: Path, reference: Path | None = None,
           reference_text: str | None = None, timeout: int = 1800,
           persistent: bool = False) -> tuple[bool, str]:
    runtime, model, speaker, steps = _settings()
    if runtime is None or model is None:
        return False, "configure the isolated VoiceTut Python executable and local model directory"
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    worker = base / "voicetut_voice_worker.py"
    if not worker.is_file():
        return False, "voicetut_voice_worker.py is missing"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nezuko_human_voice_") as temporary:
        job = Path(temporary) / "job.json"
        payload = _job(text, language, output, model, speaker, steps, reference, reference_text)
        job.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PYTHONUTF8"] = "1"
        env.setdefault("HF_HOME", str(runtime.parent.parent / "nezuko-voicetut-cache"))
        if persistent or (_worker is not None and _worker.alive):
            result_ok, detail = _ensure_worker(runtime, worker, env).submit(payload, timeout)
            result = type("Result", (), {"returncode": 0 if result_ok else 1,
                                          "stdout": "", "stderr": detail})()
        else:
            try:
                result = subprocess.run(
                    [str(runtime), str(worker), str(job)], env=env, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return False, str(exc)
    if result.returncode:
        return False, (result.stderr or result.stdout or "worker failed")[-2000:]
    try:
        with wave.open(str(output), "rb") as wav:
            if wav.getnframes() <= 0 or wav.getframerate() != 24000:
                raise ValueError("empty audio or unexpected sample rate")
    except (OSError, ValueError, wave.Error) as exc:
        output.unlink(missing_ok=True)
        return False, f"invalid output: {exc}"
    return True, "ok"
