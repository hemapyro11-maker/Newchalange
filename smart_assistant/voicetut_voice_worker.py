"""VoiceTut inference worker for natural Egyptian speech and voice cloning."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import time

SPEAKERS = {"Asmaa", "Esraa", "Hanan", "Sarah", "Yasmin", "Omnia"}
_MODELS: dict[tuple[str, str, str], object] = {}


def _load_model(model_path: Path):
    import torch
    from voicetut_tts import VoiceTutTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = "float16" if device == "cuda" else "float32"
    key = (str(model_path), device, dtype)
    model = _MODELS.get(key)
    if model is None:
        if device == "cpu":
            torch.set_num_threads(min(8, os.cpu_count() or 1))
        model = VoiceTutTTS.from_pretrained(str(model_path), device=device, dtype=dtype)
        _MODELS[key] = model
    return model


def render(job: dict) -> None:
    import numpy as np
    import soundfile as sf
    import torch

    text = str(job.get("text", "")).strip()
    if not text or len(text) > 5000:
        raise ValueError("speech text must contain 1-5000 characters")
    language = str(job.get("language", "ar")).lower()
    if language not in {"ar", "en"}:
        raise ValueError("language must be ar or en")
    model_path = Path(job["model"]).resolve()
    if not (model_path / "model.safetensors").is_file():
        raise FileNotFoundError("VoiceTut model.safetensors is missing")
    steps = min(64, max(16, int(job.get("steps", 48))))
    model = _load_model(model_path)

    reference = job.get("reference")
    kwargs = {
        "language": language,
        "normalize": True,
        "num_step": steps,
        "guidance_scale": 2.2,
        "speed": 0.96,
    }
    if reference:
        reference_path = Path(reference).resolve()
        if not reference_path.is_file():
            raise FileNotFoundError("voice reference is missing")
        kwargs["ref_audio"] = str(reference_path)
        if job.get("reference_text"):
            kwargs["ref_text"] = str(job["reference_text"])
    else:
        speaker = str(job.get("speaker", "Omnia"))
        if speaker not in SPEAKERS:
            raise ValueError("unknown female VoiceTut speaker")
        kwargs["speaker"] = speaker

    with torch.inference_mode():
        speech = np.asarray(model.synthesize(text, **kwargs), dtype=np.float32).reshape(-1)
    if not speech.size or not np.isfinite(speech).all():
        raise ValueError("model returned invalid audio")
    output = Path(job["output"]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix=".wav", dir=output.parent)
    os.close(fd)
    try:
        sf.write(temporary, speech, 24000, subtype="PCM_16")
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def serve(queue_dir: Path) -> None:
    """Keep the heavy model in memory and process atomic JSON jobs."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "ready").write_text("ready", encoding="utf-8")
    while True:
        jobs = sorted(queue_dir.glob("*.job.json"), key=lambda p: p.stat().st_mtime)
        if not jobs:
            time.sleep(0.03)
            continue
        job_path = jobs[0]
        result_path = job_path.with_suffix("").with_suffix(".result.json")
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
            render(job)
            result = {"ok": True, "detail": "ok"}
        except Exception as exc:  # server must survive one bad utterance
            result = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        temporary_result = result_path.with_suffix(".tmp")
        temporary_result.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary_result, result_path)
        job_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", nargs="?")
    parser.add_argument("--serve")
    args = parser.parse_args()
    if args.serve:
        serve(Path(args.serve))
    elif args.job:
        render(json.loads(Path(args.job).read_text(encoding="utf-8")))
    else:
        parser.error("job or --serve is required")
