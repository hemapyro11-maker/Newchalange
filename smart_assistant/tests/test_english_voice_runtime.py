from pathlib import Path

import english_voice_runtime as evr


def test_settings_clamp_speed_and_default_voice(monkeypatch, tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    monkeypatch.setenv("NEZUKO_ENGLISH_VOICE_PYTHON", str(runtime))
    monkeypatch.setenv("NEZUKO_ENGLISH_VOICE_SPEED", "9")
    monkeypatch.delenv("NEZUKO_ENGLISH_VOICE", raising=False)
    actual_runtime, voice, speed = evr._settings()
    assert actual_runtime == runtime.resolve()
    assert voice == "af_heart"
    assert speed == 1.25


def test_render_passes_selected_voice_to_isolated_worker(monkeypatch, tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"x")
    monkeypatch.setenv("NEZUKO_ENGLISH_VOICE_PYTHON", str(runtime))
    monkeypatch.setenv("NEZUKO_ENGLISH_VOICE", "bf_emma")
    seen = {}

    class Result:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(command, **kwargs):
        import json, wave
        job = json.loads(Path(command[2]).read_text(encoding="utf-8"))
        seen.update(job)
        with wave.open(job["output"], "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b"\0\0" * 240)
        return Result()

    monkeypatch.setattr(evr.subprocess, "run", fake_run)
    output = tmp_path / "out.wav"
    ok, detail = evr.render("hello", output)
    assert (ok, detail) == (True, "ok")
    assert seen["voice"] == "bf_emma"
