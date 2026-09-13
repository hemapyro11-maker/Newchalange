"""Deterministic, local repair for Nezuko's runtime and common failures."""
from __future__ import annotations

import json
import pathlib
import tempfile
import urllib.error
import urllib.request

import brain
import media_runtime as mr


def _repair_ollama_model() -> str | None:
    """Select an installed Ollama model when config points at a missing one."""
    cfg = brain.load_config()
    configured = cfg.get("models", {}).get("ollama", "llama3.2")
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    installed = [row.get("name") for row in payload.get("models", []) if row.get("name")]
    base_names = {name.split(":", 1)[0] for name in installed}
    if not installed or configured in installed or configured in base_names:
        return None
    cfg.setdefault("models", {})["ollama"] = installed[0]
    brain.save_config(cfg)
    brain.reset_brain()
    return f"Ollama model changed from missing '{configured}' to installed '{installed[0]}'"


def _real_media_smoke() -> tuple[bool, str]:
    if mr.binary("ffmpeg") is None:
        return False, "FFmpeg is unavailable"
    with tempfile.TemporaryDirectory(prefix="nezuko_repair_") as folder:
        out = pathlib.Path(folder) / "check.mp4"
        result = mr.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=96x64:d=0.12:r=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
        ], 20)
        if result.returncode or not mr.valid_output(out):
            error = (result.stderr or result.stdout or "encode produced no output").strip()[-400:]
            return False, error
    return True, "portable H.264 render passed"


def _cmd_self_repair(ctx) -> str:
    engine = ctx.engine
    fixed, checks, found = [], [], []

    for folder in (engine.project_dir / ".nezuko", engine.project_dir / ".nezuko" / "cache"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            found.append(f"could not prepare {folder}: {exc}")

    before = set(engine._loaded_plugins)
    loaded = set(engine.load_plugins())
    recovered = sorted(loaded - before)
    if recovered:
        fixed.append(f"reloaded plugins: {', '.join(recovered)}")
    broken = [name for name, state in engine.plugin_health.items() if state.get("status") not in {"ok", "loaded"}]
    checks.append(f"plugins: {len(loaded)} loaded" + (f", {len(broken)} need attention" if broken else ""))

    model_fix = _repair_ollama_model()
    if model_fix:
        fixed.append(model_fix)

    media_ok, media_detail = _real_media_smoke()
    checks.append(("media: " if media_ok else "media problem: ") + media_detail)

    transcript = "\n".join(message for _level, message in list(engine.log_history)[-80:])
    known = (
        ("Fontconfig error", "old FFmpeg text-render failure detected; title_card now renders text through Pillow"),
        ("cannot identify image file", "non-image thumbnail input detected; validation now stops it before rendering"),
        ("HTTP 503", "temporary provider overload detected; Nezuko will use cooldown and the next available provider"),
        ("rate limit", "provider quota/rate limit detected; cooldown prevents immediate repeated calls"),
        ("model 'llama3.2' not found", "missing local model detected"),
    )
    for marker, explanation in known:
        if marker.lower() in transcript.lower():
            found.append(explanation)

    lines = ["🩺 Nezuko self-repair completed locally."]
    lines += [f"✅ {item}" for item in fixed]
    lines += [f"✅ {item}" if not item.startswith("media problem") else f"❌ {item}" for item in checks]
    lines += [f"• {item}" for item in dict.fromkeys(found)]
    if not fixed and media_ok and not broken:
        lines.append("✅ No repairable runtime fault remains in the checked systems.")
    if broken:
        lines.append("❌ Broken plugins: " + ", ".join(broken))
    return "\n".join(lines)


def register(engine):
    engine.registry.register(
        "self_repair", _cmd_self_repair,
        "self_repair — diagnose recent failures, reload plugins, repair a missing Ollama model selection, prepare runtime folders, and run a real video encode test without needing an AI provider",
    )
