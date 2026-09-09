"""Run inside an isolated Chatterbox environment, never inside the GUI process."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile


def chunks(text, limit=240):
    words = text.split()
    current = ""
    for word in words:
        if len(word) > limit:
            raise ValueError("speech contains an overlong word")
        if current and len(current) + len(word) + 1 > limit:
            yield current
            current = ""
        current = f"{current} {word}".strip()
        if re.search(r"[.!?؟]$", current):
            yield current
            current = ""
    if current:
        yield current


def render(job):
    import torch
    import soundfile as sf
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(min(8, os.cpu_count() or 1))
    model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
    pieces = []
    with torch.inference_mode():
        for part in chunks(job["text"]):
            speech = model.generate(
                part, language_id=job["language"],
                audio_prompt_path=job.get("reference"),
                exaggeration=0.3, cfg_weight=0.4, temperature=0.65,
            ).detach().cpu().reshape(-1)
            if not torch.isfinite(speech).all() or speech.numel() == 0:
                raise ValueError("model returned invalid audio")
            if pieces:
                pieces.append(torch.zeros(int(model.sr * 0.18)))
            pieces.append(speech)
    if not pieces:
        raise ValueError("no speech text")
    output = Path(job["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix=".wav", dir=output.parent)
    os.close(fd)
    try:
        sf.write(temporary, torch.cat(pieces).numpy(), model.sr, subtype="PCM_16")
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    args = parser.parse_args()
    render(json.loads(Path(args.job).read_text(encoding="utf-8")))
