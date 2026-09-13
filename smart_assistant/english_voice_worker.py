"""Kokoro worker: natural native US/UK English speech at 24 kHz."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

VOICES = {
    "af_heart", "af_bella", "af_nicole", "af_aoede", "af_kore",
    "af_sarah", "af_nova", "af_sky", "af_alloy", "af_jessica", "af_river",
    "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
}


def render(job: dict) -> None:
    import numpy as np
    import soundfile as sf
    import torch
    from kokoro import KPipeline

    text = str(job.get("text", "")).strip()
    if not text or len(text) > 5000:
        raise ValueError("speech text must contain 1-5000 characters")
    voice = str(job.get("voice", "af_heart"))
    if voice not in VOICES:
        raise ValueError("unknown Kokoro female voice")
    speed = min(1.25, max(0.75, float(job.get("speed", 0.96))))
    if not torch.cuda.is_available():
        torch.set_num_threads(min(8, os.cpu_count() or 1))
    pipeline = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")
    pieces = []
    with torch.inference_mode():
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed):
            chunk = np.asarray(audio, dtype=np.float32).reshape(-1)
            if chunk.size:
                pieces.append(chunk)
                pieces.append(np.zeros(2400, dtype=np.float32))
    if not pieces:
        raise ValueError("model returned no audio")
    speech = np.concatenate(pieces[:-1])
    if not np.isfinite(speech).all():
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    args = parser.parse_args()
    render(json.loads(Path(args.job).read_text(encoding="utf-8")))
