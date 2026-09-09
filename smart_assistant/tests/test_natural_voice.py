import json
from pathlib import Path
import wave

import natural_voice_runtime as nvr
import natural_voice_worker as worker


def _wav(path: Path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 2400)


def test_chunks_preserve_words_and_limit():
    text = "أهلاً بيك. دي جملة طويلة شوية علشان نختبر تقسيم الكلام؟ تمام"
    parts = list(worker.chunks(text, limit=25))
    assert " ".join(parts) == text
    assert all(0 < len(part) <= 25 for part in parts)


def test_render_uses_isolated_environment(tmp_path, monkeypatch):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    monkeypatch.setenv("NEZUKO_NATURAL_VOICE_PYTHON", str(runtime))
    monkeypatch.setenv("PYTHONPATH", "must-not-leak")
    monkeypatch.setenv("PYTHONHOME", "must-not-leak")
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs["env"])
        job = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        _wav(Path(job["output"]))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(nvr.subprocess, "run", fake_run)
    output = tmp_path / "out.wav"
    ok, detail = nvr.render("أهلاً", "ar", output)
    assert (ok, detail) == (True, "ok")
    assert "PYTHONPATH" not in seen and "PYTHONHOME" not in seen
    assert seen["PYTHONUTF8"] == "1"
    assert seen["HF_HUB_DISABLE_XET"] == "1"
    assert seen["HF_HOME"].endswith("nezuko-model-cache\\huggingface")
    assert seen["PKUSEG_HOME"].endswith("nezuko-model-cache\\pkuseg")


def test_render_rejects_invalid_worker_output(tmp_path, monkeypatch):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    monkeypatch.setenv("NEZUKO_NATURAL_VOICE_PYTHON", str(runtime))
    monkeypatch.setattr(nvr.subprocess, "run", lambda *a, **k:
                        type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    ok, detail = nvr.render("hello", "en", tmp_path / "bad.wav")
    assert not ok
    assert "invalid output" in detail


def test_runtime_can_come_from_saved_config(tmp_path, monkeypatch):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    monkeypatch.delenv("NEZUKO_NATURAL_VOICE_PYTHON", raising=False)
    import brain
    monkeypatch.setattr(brain, "load_config", lambda: {"natural_voice_python": str(runtime)})
    assert nvr.runtime_path() == runtime.resolve()
