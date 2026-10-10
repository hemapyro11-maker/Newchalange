"""Launch the optional Chatterbox engine without importing it into Jarvis."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


def runtime_path() -> Path | None:
    value = os.environ.get("NEZUKO_NATURAL_VOICE_PYTHON", "").strip()
    if not value:
        try:
            import brain
            value = str(brain.load_config().get("natural_voice_python", "")).strip()
        except (ImportError, AttributeError, OSError):
            value = ""
    path = Path(value).expanduser() if value else None
    return path.resolve() if path and path.is_file() else None


def available() -> bool:
    return runtime_path() is not None


def configure(path: Path | None) -> None:
    import brain
    cfg = brain.load_config()
    if path is None:
        cfg.pop("natural_voice_python", None)
    else:
        cfg["natural_voice_python"] = str(path.resolve())
    brain.save_config(cfg)


def render(text: str, language: str, output: Path, reference: Path | None = None,
           timeout: int = 1800) -> tuple[bool, str]:
    runtime = runtime_path()
    if runtime is None:
        return False, "set NEZUKO_NATURAL_VOICE_PYTHON to the isolated Chatterbox Python executable"
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    worker = base / "natural_voice_worker.py"
    if not worker.is_file():
        return False, "natural_voice_worker.py is missing"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nezuko_natural_") as temporary:
        job = Path(temporary) / "job.json"
        job.write_text(json.dumps({
            "text": text, "language": language, "output": str(output),
            "reference": str(reference.resolve()) if reference else None,
        }, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PYTHONUTF8"] = "1"
        # Hugging Face's optional Xet transport can hang on some Windows
        # installations; ordinary HTTPS is slower but much more predictable.
        env.setdefault("HF_HUB_DISABLE_XET", "1")
        cache_root = runtime.parent.parent / "nezuko-model-cache"
        env.setdefault("HF_HOME", str(cache_root / "huggingface"))
        env.setdefault("PKUSEG_HOME", str(cache_root / "pkuseg"))
        try:
            result = subprocess.run(
                [str(runtime), str(worker), str(job)], env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
    if result.returncode:
        return False, (result.stderr or result.stdout or "worker failed")[-1600:]
    try:
        with wave.open(str(output), "rb") as wav:
            if wav.getnframes() <= 0 or wav.getframerate() <= 0:
                raise ValueError("empty audio")
    except (OSError, ValueError, wave.Error) as exc:
        output.unlink(missing_ok=True)
        return False, f"invalid output: {exc}"
    return True, "ok"
