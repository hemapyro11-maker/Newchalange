import json
from pathlib import Path
import wave

import voicetut_runtime as vtr
import voicetut_voice_worker as worker


def _wav(path: Path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 2400)


def test_settings_are_validated(tmp_path, monkeypatch):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.safetensors").write_bytes(b"x")
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_PYTHON", str(runtime))
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_MODEL", str(model))
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_SPEAKER", "Omnia")
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_STEPS", "200")
    assert vtr._settings() == (runtime.resolve(), model.resolve(), "Omnia", 64)


def test_render_uses_isolated_environment_and_complete_job(tmp_path, monkeypatch):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.safetensors").write_bytes(b"x")
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_PYTHON", str(runtime))
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_MODEL", str(model))
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_SPEAKER", "Omnia")
    monkeypatch.setenv("PYTHONPATH", "must-not-leak")
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs["env"]
        seen["job"] = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        _wav(Path(seen["job"]["output"]))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(vtr.subprocess, "run", fake_run)
    output = tmp_path / "out.wav"
    ok, detail = vtr.render("أهلاً", "ar", output)
    assert (ok, detail) == (True, "ok")
    assert "PYTHONPATH" not in seen["env"] and "PYTHONHOME" not in seen["env"]
    assert seen["env"]["PYTHONUTF8"] == "1"
    assert seen["job"]["speaker"] == "Omnia"
    assert seen["job"]["model"] == str(model.resolve())


def test_render_rejects_wrong_sample_rate(tmp_path, monkeypatch):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.safetensors").write_bytes(b"x")
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_PYTHON", str(runtime))
    monkeypatch.setenv("NEZUKO_HUMAN_VOICE_MODEL", str(model))

    def wrong_wav(*args, **kwargs):
        job = json.loads(Path(args[0][2]).read_text(encoding="utf-8"))
        with wave.open(job["output"], "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 100)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(vtr.subprocess, "run", wrong_wav)
    ok, detail = vtr.render("hello", "en", tmp_path / "bad.wav")
    assert not ok and "invalid output" in detail


def test_worker_has_only_built_in_female_speakers():
    assert worker.SPEAKERS == {"Asmaa", "Esraa", "Hanan", "Sarah", "Yasmin", "Omnia"}
