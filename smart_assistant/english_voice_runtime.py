"""Run Kokoro's native English voice in Nezuko's isolated voice environment."""
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

DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 0.96
_worker: PersistentVoiceWorker | None = None
_worker_lock = threading.Lock()
_warming = False


def _settings() -> tuple[Path | None, str, float]:
    runtime_value = os.environ.get("NEZUKO_ENGLISH_VOICE_PYTHON", "").strip()
    voice = os.environ.get("NEZUKO_ENGLISH_VOICE", "").strip()
    speed_value = os.environ.get("NEZUKO_ENGLISH_VOICE_SPEED", "").strip()
    try:
        import brain
        cfg = brain.load_config()
    except (ImportError, AttributeError, OSError):
        cfg = {}
    runtime_value = runtime_value or str(cfg.get("english_voice_python", "")).strip()
    voice = voice or str(cfg.get("english_voice_voice", DEFAULT_VOICE)).strip()
    try:
        speed = float(speed_value or cfg.get("english_voice_speed", DEFAULT_SPEED))
    except (TypeError, ValueError):
        speed = DEFAULT_SPEED
    runtime = Path(runtime_value).expanduser() if runtime_value else None
    runtime = runtime.resolve() if runtime and runtime.is_file() else None
    return runtime, voice or DEFAULT_VOICE, min(1.25, max(0.75, speed))


def available() -> bool:
    return _settings()[0] is not None


def configure(runtime: Path | None, voice: str = DEFAULT_VOICE,
              speed: float = DEFAULT_SPEED) -> None:
    import brain
    cfg = brain.load_config()
    if runtime is None:
        for key in ("english_voice_python", "english_voice_voice", "english_voice_speed"):
            cfg.pop(key, None)
    else:
        cfg["english_voice_python"] = str(runtime.resolve())
        cfg["english_voice_voice"] = voice
        cfg["english_voice_speed"] = min(1.25, max(0.75, float(speed)))
    brain.save_config(cfg)


def _ensure_worker(runtime: Path, worker_script: Path, env: dict[str, str]) -> PersistentVoiceWorker:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.alive:
            _worker = PersistentVoiceWorker(runtime, worker_script, env)
        return _worker


def prewarm() -> None:
    global _warming
    if _warming or not available():
        return
    _warming = True

    def warm() -> None:
        global _warming
        try:
            with tempfile.TemporaryDirectory(prefix="nezuko_english_warmup_") as tmp:
                render("Ready", Path(tmp) / "warm.wav", timeout=900, persistent=True)
        finally:
            _warming = False

    threading.Thread(target=warm, name="nezuko-english-warmup", daemon=True).start()


def render(text: str, output: Path, timeout: int = 900,
           persistent: bool = False) -> tuple[bool, str]:
    runtime, voice, speed = _settings()
    if runtime is None:
        return False, "configure the isolated Kokoro Python executable"
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    worker = base / "english_voice_worker.py"
    if not worker.is_file():
        return False, "english_voice_worker.py is missing"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nezuko_english_voice_") as temporary:
        job = Path(temporary) / "job.json"
        job.write_text(json.dumps({
            "text": text, "output": str(output), "voice": voice, "speed": speed,
        }, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PYTHONUTF8"] = "1"
        env.setdefault("HF_HOME", str(runtime.parent.parent / "nezuko-kokoro-cache"))
        if persistent or (_worker is not None and _worker.alive):
            result_ok, detail = _ensure_worker(runtime, worker, env).submit(
                {"text": text, "output": str(output), "voice": voice, "speed": speed}, timeout)
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
