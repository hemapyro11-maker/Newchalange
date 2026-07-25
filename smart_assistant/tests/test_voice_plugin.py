import pathlib
import shutil
import subprocess
import sys
import types

import pytest
import voice_plugin as vp

requires_espeak = pytest.mark.skipif(not shutil.which("espeak-ng"), reason="espeak-ng not installed")
requires_ffplay = pytest.mark.skipif(not shutil.which("ffplay"), reason="ffplay not installed")


@pytest.fixture(autouse=True)
def isolated_voice_cache(tmp_path, monkeypatch):
    """كل اختبار بيستخدم مجلد voice_cache خاص بيه، عشان محدش يلمس
    smart_assistant/voice_cache/ الحقيقي بتاع المستخدم أو يحاول ينزّل
    حاجة فعليًا من غير قصد."""
    cache_dir = tmp_path / "voice_cache"

    def fake_cache_dir():
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    monkeypatch.setattr(vp, "_voice_cache_dir", fake_cache_dir)
    return cache_dir


def _deny_all_backends(monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)


# ── speak: usage / no backends ──────────────────────────────────────────

def test_speak_no_text(make_ctx):
    result = vp._cmd_speak(make_ctx("speak", []))
    assert result.startswith("usage")


def test_speak_all_backends_unavailable_is_honest(make_ctx, monkeypatch):
    _deny_all_backends(monkeypatch)
    result = vp._cmd_speak(make_ctx("speak hello", []))
    assert result.startswith("❌")
    assert "espeak-ng" in result


# ── fallback chain ordering ──────────────────────────────────────────────

def test_speak_prefers_edge_tts_when_available(make_ctx, monkeypatch, tmp_path):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("edge-tts", "ffplay") else None

    def fake_run(cmd, **kwargs):
        if cmd[0] == "edge-tts":
            out_path = kwargs.get("input") or cmd[cmd.index("--write-media") + 1]
            from pathlib import Path
            Path(out_path).write_bytes(b"fake-mp3-bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[0] == "ffplay":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(vp.shutil, "which", fake_which)
    monkeypatch.setattr(vp.subprocess, "run", fake_run)

    result = vp._cmd_speak(make_ctx("speak أهلاً", []))
    assert result.startswith("🔊")
    assert "edge-tts" in result
    assert "Piper" not in result
    assert "espeak-ng" not in result


def test_speak_falls_back_to_piper_when_edge_fails(make_ctx, monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("edge-tts", "piper", "ffplay") else None

    def fake_run(cmd, **kwargs):
        from pathlib import Path
        if cmd[0] == "edge-tts":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="network error")
        if cmd[0] == "piper":
            out_path = cmd[cmd.index("-f") + 1]
            Path(out_path).write_bytes(b"fake-wav-bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[0] == "ffplay":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(vp.shutil, "which", fake_which)
    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    monkeypatch.setattr(vp, "_download", lambda url, dest: (dest.write_bytes(b"x"), True)[1])

    result = vp._cmd_speak(make_ctx("speak أهلاً", []))
    assert result.startswith("🔊")
    assert "Piper" in result


def test_speak_falls_back_to_espeak_when_edge_and_piper_fail(make_ctx, monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("edge-tts", "piper", "espeak-ng", "ffplay") else None

    def fake_run(cmd, **kwargs):
        from pathlib import Path
        if cmd[0] in ("edge-tts", "piper"):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fail")
        if cmd[0] == "espeak-ng":
            out_path = cmd[cmd.index("-w") + 1]
            Path(out_path).write_bytes(b"fake-wav-bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[0] == "ffplay":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(vp.shutil, "which", fake_which)
    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    # الداونلود بيفشل (زي مفيش إنترنت) فـ Piper ميتجربش أصلاً
    monkeypatch.setattr(vp, "_download", lambda url, dest: False)

    result = vp._cmd_speak(make_ctx("speak أهلاً", []))
    assert result.startswith("🔊")
    assert "espeak-ng" in result


def test_speak_reports_missing_ffplay_but_still_synthesized(make_ctx, monkeypatch):
    def fake_which(name):
        return "/usr/bin/espeak-ng" if name == "espeak-ng" else None

    def fake_run(cmd, **kwargs):
        from pathlib import Path
        out_path = cmd[cmd.index("-w") + 1]
        Path(out_path).write_bytes(b"fake-wav-bytes")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vp.shutil, "which", fake_which)
    monkeypatch.setattr(vp.subprocess, "run", fake_run)

    result = vp._cmd_speak(make_ctx("speak أهلاً", []))
    assert result.startswith("✅")
    assert "ffplay" in result


# ── real espeak-ng synthesis (no network, no mocking) ───────────────────

@requires_espeak
def test_synthesize_espeak_produces_real_audio(tmp_path):
    out = tmp_path / "out.wav"
    ok = vp._synthesize_espeak("أهلاً بيك، أنا نيزوكو", out)
    assert ok is True
    assert out.is_file()
    assert out.stat().st_size > 1000  # ملف صوت حقيقي، مش فاضي


@requires_espeak
@requires_ffplay
def test_speak_end_to_end_with_only_espeak_available(make_ctx, monkeypatch):
    real_which = shutil.which  # لازم نلقط النسخة الأصلية قبل الـ patch — vp.shutil هو
    # نفس module object بتاع shutil العادي، فلو fake_which استخدمت shutil.which
    # جوّاها هتنده على نفسها من غير نهاية بعد الـ monkeypatch.

    def fake_which(name):
        return real_which(name) if name in ("espeak-ng", "ffplay") else None

    monkeypatch.setattr(vp.shutil, "which", fake_which)
    result = vp._cmd_speak(make_ctx("speak أهلاً بيك، أنا نيزوكو", []))
    assert result.startswith("🔊")
    assert "espeak-ng" in result


# ── Piper voice caching ──────────────────────────────────────────────────

def test_ensure_piper_voice_downloads_and_caches(monkeypatch, tmp_path):
    calls = []

    def fake_download(url, dest):
        calls.append(url)
        dest.write_bytes(b"fake-model-bytes")
        return True

    monkeypatch.setattr(vp, "_download", fake_download)
    result = vp._ensure_piper_voice()
    assert result is not None
    model, config = result
    assert model.is_file() and config.is_file()
    assert len(calls) == 2  # موديل + كونفيج

    # المرة التانية: من الكاش من غير أي تنزيل جديد
    calls.clear()
    result2 = vp._ensure_piper_voice()
    assert result2 == result
    assert calls == []


def test_ensure_piper_voice_returns_none_on_download_failure(monkeypatch):
    monkeypatch.setattr(vp, "_download", lambda url, dest: False)
    assert vp._ensure_piper_voice() is None


def test_download_cleans_up_partial_file_on_failure(monkeypatch, tmp_path):
    def failing_urlopen(*args, **kwargs):
        raise vp.urllib.error.URLError("network unreachable")

    monkeypatch.setattr(vp.urllib.request, "urlopen", failing_urlopen)
    dest = tmp_path / "partial.onnx"
    ok = vp._download("https://example.com/model.onnx", dest)
    assert ok is False
    assert not dest.exists()


# ── voice_status ─────────────────────────────────────────────────────────

def test_voice_status_reports_all_missing(make_ctx, monkeypatch):
    _deny_all_backends(monkeypatch)
    result = vp._cmd_voice_status(make_ctx("voice_status", []))
    assert result.count("❌") == 4
    assert "مفيش أي محرك نطق متثبت" in result


def test_voice_status_reports_available_backends(make_ctx, monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("espeak-ng", "ffplay") else None

    monkeypatch.setattr(vp.shutil, "which", fake_which)
    result = vp._cmd_voice_status(make_ctx("voice_status", []))
    assert "✅ espeak-ng" in result
    assert "❌ edge-tts" in result
    assert "pip install edge-tts" in result


# ── STT: _record_audio ──────────────────────────────────────────────────

class _FakeAudioArray:
    def __init__(self, data: bytes):
        self._data = data

    def tobytes(self) -> bytes:
        return self._data


class _FakeSD:
    def __init__(self, data: bytes = b"\x00\x01" * 100, raise_on_rec: Exception | None = None):
        self._data = data
        self._raise = raise_on_rec
        self.rec_args = None
        self.waited = False

    def rec(self, n, samplerate, channels, dtype):
        if self._raise:
            raise self._raise
        self.rec_args = (n, samplerate, channels, dtype)
        return _FakeAudioArray(self._data)

    def wait(self):
        self.waited = True


def test_record_audio_no_sounddevice_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "sd", None)
    err = vp._record_audio(1, tmp_path / "out.wav")
    assert err is not None
    assert "sounddevice" in err


def test_record_audio_success_writes_wav(monkeypatch, tmp_path):
    fake = _FakeSD()
    monkeypatch.setattr(vp, "sd", fake)
    out_path = tmp_path / "out.wav"
    err = vp._record_audio(1, out_path)
    assert err is None
    assert out_path.is_file()
    assert fake.waited is True
    assert fake.rec_args == (vp._SAMPLE_RATE, vp._SAMPLE_RATE, 1, "int16")


def test_record_audio_mic_exception_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "sd", _FakeSD(raise_on_rec=RuntimeError("no mic found")))
    err = vp._record_audio(1, tmp_path / "out.wav")
    assert err is not None
    assert "no mic found" in err


# ── STT: _transcribe_faster_whisper ──────────────────────────────────────

def test_transcribe_faster_whisper_not_installed(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_faster_whisper(wav, "base")
    assert text is None
    assert available is False


def test_transcribe_faster_whisper_success(monkeypatch, tmp_path):
    class FakeSegment:
        def __init__(self, text):
            self.text = text

    class FakeModel:
        def __init__(self, model_size, **kwargs):
            pass

        def transcribe(self, path):
            return [FakeSegment("شغّل"), FakeSegment("الأمر ده")], object()

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(vp, "_faster_whisper_models", {})
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_faster_whisper(wav, "base")
    assert available is True
    assert text == "شغّل الأمر ده"


def test_transcribe_faster_whisper_caches_model_by_size(monkeypatch, tmp_path):
    calls = []

    class FakeModel:
        def __init__(self, model_size, **kwargs):
            calls.append(model_size)

        def transcribe(self, path):
            return [], object()

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(vp, "_faster_whisper_models", {})
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    vp._transcribe_faster_whisper(wav, "base")
    vp._transcribe_faster_whisper(wav, "base")
    assert calls == ["base"]


def test_transcribe_faster_whisper_model_error_reported_as_available(monkeypatch, tmp_path):
    class FakeModel:
        def __init__(self, model_size, **kwargs):
            raise RuntimeError("boom")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(vp, "_faster_whisper_models", {})
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_faster_whisper(wav, "base")
    assert text is None
    assert available is True


# ── STT: _transcribe_whisper_cli ─────────────────────────────────────────

def test_transcribe_whisper_cli_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_whisper_cli(wav, vp.WHISPER_MODEL)
    assert text is None
    assert available is False


def test_transcribe_whisper_cli_success(monkeypatch, tmp_path):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/whisper" if name == "whisper" else None)

    def fake_run(cmd, **kwargs):
        out_dir = pathlib.Path(cmd[cmd.index("--output_dir") + 1])
        wav_stem = pathlib.Path(cmd[1]).stem
        (out_dir / f"{wav_stem}.txt").write_text("شغّل الأمر ده", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_whisper_cli(wav, vp.WHISPER_MODEL)
    assert available is True
    assert text == "شغّل الأمر ده"


def test_transcribe_whisper_cli_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/whisper" if name == "whisper" else None)
    monkeypatch.setattr(vp.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"))
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_whisper_cli(wav, vp.WHISPER_MODEL)
    assert text is None
    assert available is True


def test_transcribe_whisper_cli_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/whisper" if name == "whisper" else None)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_whisper_cli(wav, vp.WHISPER_MODEL)
    assert text is None
    assert available is True


def test_transcribe_whisper_cli_empty_output_reported_as_available(monkeypatch, tmp_path):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/whisper" if name == "whisper" else None)

    def fake_run(cmd, **kwargs):
        out_dir = pathlib.Path(cmd[cmd.index("--output_dir") + 1])
        wav_stem = pathlib.Path(cmd[1]).stem
        (out_dir / f"{wav_stem}.txt").write_text("   ", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, available = vp._transcribe_whisper_cli(wav, vp.WHISPER_MODEL)
    assert text is None
    assert available is True


# ── STT: _transcribe_vosk ────────────────────────────────────────────────

def _write_silent_wav(path: pathlib.Path) -> None:
    import wave as _wave

    with _wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)


def test_transcribe_vosk_no_model_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "_vosk_model_dir", lambda: tmp_path / "missing-model")
    wav = tmp_path / "in.wav"
    _write_silent_wav(wav)
    text, available = vp._transcribe_vosk(wav)
    assert text is None
    assert available is False


def test_transcribe_vosk_package_not_installed(monkeypatch, tmp_path):
    model_dir = tmp_path / "vosk-model"
    model_dir.mkdir()
    monkeypatch.setattr(vp, "_vosk_model_dir", lambda: model_dir)
    monkeypatch.setitem(sys.modules, "vosk", None)
    wav = tmp_path / "in.wav"
    _write_silent_wav(wav)
    text, available = vp._transcribe_vosk(wav)
    assert text is None
    assert available is False


def test_transcribe_vosk_success(monkeypatch, tmp_path):
    model_dir = tmp_path / "vosk-model"
    model_dir.mkdir()
    monkeypatch.setattr(vp, "_vosk_model_dir", lambda: model_dir)

    class FakeRecognizer:
        def __init__(self, model, rate):
            pass

        def AcceptWaveform(self, data):
            return False

        def Result(self):
            return "{}"

        def FinalResult(self):
            return '{"text": "شغّل الأمر ده"}'

    fake_module = types.ModuleType("vosk")
    fake_module.SetLogLevel = lambda level: None
    fake_module.Model = lambda path: object()
    fake_module.KaldiRecognizer = FakeRecognizer
    monkeypatch.setitem(sys.modules, "vosk", fake_module)

    wav = tmp_path / "in.wav"
    _write_silent_wav(wav)
    text, available = vp._transcribe_vosk(wav)
    assert available is True
    assert text == "شغّل الأمر ده"


def test_transcribe_vosk_error_reported_as_available(monkeypatch, tmp_path):
    model_dir = tmp_path / "vosk-model"
    model_dir.mkdir()
    monkeypatch.setattr(vp, "_vosk_model_dir", lambda: model_dir)

    fake_module = types.ModuleType("vosk")
    fake_module.SetLogLevel = lambda level: None

    def _boom(path):
        raise RuntimeError("boom")

    fake_module.Model = _boom
    fake_module.KaldiRecognizer = object
    monkeypatch.setitem(sys.modules, "vosk", fake_module)

    wav = tmp_path / "in.wav"
    _write_silent_wav(wav)
    text, available = vp._transcribe_vosk(wav)
    assert text is None
    assert available is True


# ── STT: _transcribe (orchestrator) ──────────────────────────────────────

def test_transcribe_no_engine_installed_reports_missing_message(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "_transcribe_faster_whisper", lambda wav, model: (None, False))
    monkeypatch.setattr(vp, "_transcribe_whisper_cli", lambda wav, model: (None, False))
    monkeypatch.setattr(vp, "_transcribe_vosk", lambda wav: (None, False))
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, err = vp._transcribe(wav)
    assert text is None
    assert err is vp._STT_MISSING_MSG


def test_transcribe_prefers_faster_whisper_over_other_backends(monkeypatch, tmp_path):
    def _fail(*a, **kw):
        raise AssertionError("shouldn't be called — faster-whisper already succeeded")

    monkeypatch.setattr(vp, "_transcribe_faster_whisper", lambda wav, model: ("نتيجة faster-whisper", True))
    monkeypatch.setattr(vp, "_transcribe_whisper_cli", _fail)
    monkeypatch.setattr(vp, "_transcribe_vosk", _fail)
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, err = vp._transcribe(wav)
    assert err is None
    assert text == "نتيجة faster-whisper"


def test_transcribe_falls_back_to_whisper_cli_then_vosk(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "_transcribe_faster_whisper", lambda wav, model: (None, False))
    monkeypatch.setattr(vp, "_transcribe_whisper_cli", lambda wav, model: (None, True))
    monkeypatch.setattr(vp, "_transcribe_vosk", lambda wav: ("نتيجة vosk", True))
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, err = vp._transcribe(wav)
    assert err is None
    assert text == "نتيجة vosk"


def test_transcribe_all_backends_available_but_silent(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "_transcribe_faster_whisper", lambda wav, model: (None, True))
    monkeypatch.setattr(vp, "_transcribe_whisper_cli", lambda wav, model: (None, True))
    monkeypatch.setattr(vp, "_transcribe_vosk", lambda wav: (None, True))
    wav = tmp_path / "in.wav"
    wav.write_bytes(b"fake")
    text, err = vp._transcribe(wav)
    assert text is None
    assert "🔇" in err


# ── listen / listen_run / stt_status ─────────────────────────────────────

def test_listen_invalid_seconds_shows_usage(make_ctx):
    result = vp._cmd_listen(make_ctx("listen abc", ["abc"]))
    assert result.startswith("usage")


def test_listen_clamps_seconds_to_max(monkeypatch, make_ctx):
    captured = {}

    def fake_listen_and_transcribe(seconds):
        captured["seconds"] = seconds
        return "تمام", None

    monkeypatch.setattr(vp, "_listen_and_transcribe", fake_listen_and_transcribe)
    vp._cmd_listen(make_ctx("listen 999", ["999"]))
    assert captured["seconds"] == vp._LISTEN_MAX_SECONDS


def test_listen_returns_transcribed_text_without_executing(monkeypatch, make_ctx, bare_engine):
    monkeypatch.setattr(vp, "_listen_and_transcribe", lambda seconds: ("افتح الاعدادات", None))
    result = vp._cmd_listen(make_ctx("listen", [], engine=bare_engine))
    assert "افتح الاعدادات" in result
    assert bare_engine._queue.empty()


def test_listen_propagates_recording_error(monkeypatch, make_ctx):
    monkeypatch.setattr(vp, "_listen_and_transcribe", lambda seconds: (None, "❌ تعذر التسجيل"))
    result = vp._cmd_listen(make_ctx("listen", []))
    assert result.startswith("❌")


def test_listen_run_submits_transcribed_text(monkeypatch, make_ctx, bare_engine):
    monkeypatch.setattr(vp, "_listen_and_transcribe", lambda seconds: ("echo hi", None))
    result = vp._cmd_listen_run(make_ctx("listen_run", [], engine=bare_engine))
    assert "▶️" in result
    text, _fn = bare_engine._queue.get_nowait()
    assert text == "echo hi"


def test_listen_run_does_not_submit_on_error(monkeypatch, make_ctx, bare_engine):
    monkeypatch.setattr(vp, "_listen_and_transcribe", lambda seconds: (None, "🔇 مسمعتش حاجة"))
    result = vp._cmd_listen_run(make_ctx("listen_run", [], engine=bare_engine))
    assert result.startswith("🔇")
    assert bare_engine._queue.empty()


def test_stt_status_reports_missing(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "sd", None)
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "vosk", None)
    monkeypatch.setattr(vp, "_vosk_model_dir", lambda: tmp_path / "missing-vosk")
    result = vp._cmd_stt_status(make_ctx("stt_status", []))
    assert result.count("❌") == 4
    assert "pip install sounddevice" in result
    assert "pip install faster-whisper" in result
    assert "pip install openai-whisper" in result
    assert "pip install vosk" in result


def test_stt_status_reports_available(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "sd", _FakeSD())
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/whisper" if name == "whisper" else None)
    fake_faster_whisper = types.ModuleType("faster_whisper")
    fake_faster_whisper.WhisperModel = object
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_faster_whisper)
    monkeypatch.setitem(sys.modules, "vosk", types.ModuleType("vosk"))
    vosk_dir = tmp_path / "vosk-model"
    vosk_dir.mkdir()
    monkeypatch.setattr(vp, "_vosk_model_dir", lambda: vosk_dir)
    result = vp._cmd_stt_status(make_ctx("stt_status", []))
    assert result.count("✅") == 4


def test_register_adds_stt_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    vp.register(FakeEngine)
    for cmd in ("speak", "voice_status", "listen", "listen_run", "stt_status"):
        assert cmd in FakeEngine.registry.names
