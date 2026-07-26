import json
import os
import pathlib
import shutil
import subprocess
import sys
import types
import wave

import numpy as _np
import pytest
import voice_plugin as vp

requires_espeak = pytest.mark.skipif(not shutil.which("espeak-ng"), reason="espeak-ng not installed")
requires_ffplay = pytest.mark.skipif(not shutil.which("ffplay"), reason="ffplay not installed")
requires_demucs = pytest.mark.skipif(not shutil.which("demucs"), reason="demucs not installed")
requires_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(autouse=True)
def _isolate_keyring(monkeypatch):
    """افتراضيًا نخلي keyring "مش متاح" وقت الاختبار — عشان diarize_set_token
    يتحفظ في diarize_config.json بشكل ثابت، ومحدش يلمس مخزن أسرار نظام
    التشغيل الحقيقي بتاع اللي بيشغل الاختبارات."""
    monkeypatch.setattr(vp, "_HAS_KEYRING", False)


@pytest.fixture
def isolated_diarize_config(tmp_path, monkeypatch):
    path = tmp_path / "diarize_config.json"
    monkeypatch.setattr(vp, "_diarize_config_path", lambda: path)
    return path


@pytest.fixture
def isolated_clone_config(tmp_path, monkeypatch):
    path = tmp_path / "clone_voice_config.json"
    monkeypatch.setattr(vp, "_clone_voice_config_path", lambda: path)
    return path


class _FakeKeyring:
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, key):
        return self._store.get((service, key))

    def set_password(self, service, key, value):
        self._store[(service, key)] = value


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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """مفيش أي اختبار بيلمس الشبكة.

    باقي المحركات بتتقفل بـ `shutil.which`، لكن sherpa مكتبة بايثون —
    فلو مثبتة على جهاز اللي بيشغّل الاختبارات كانت هتشتغل فعلاً وتنزّل
    نموذج 65 ميجا. بنقفل عند الحدود الحقيقية (`urlopen`) مش عند دالة
    معيّنة، فالمنع بيشمل أي مسار تنزيل جديد يتضاف بعدين كمان. اللي
    عايز ينزّل في اختباره بيستبدلها صراحة.
    """
    def _blocked(*args, **kwargs):
        raise vp.urllib.error.URLError("network blocked in tests")

    monkeypatch.setattr(vp.urllib.request, "urlopen", _blocked)
    vp._sherpa_cache.clear()
    yield
    vp._sherpa_cache.clear()


def _deny_all_backends(monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    monkeypatch.setattr(vp, "sherpa_available", lambda: False)
    monkeypatch.setattr(vp, "_load_sherpa", lambda lang="ar": None)


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
    assert "No speech engine installed" in result


def test_voice_status_reports_available_backends(make_ctx, monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("espeak-ng", "ffplay") else None

    monkeypatch.setattr(vp.shutil, "which", fake_which)
    monkeypatch.setattr(vp, "sherpa_available", lambda: False)
    result = vp._cmd_voice_status(make_ctx("voice_status", []))
    assert "✅ espeak-ng" in result
    assert "❌ edge-tts" in result
    assert "pip install edge-tts" in result


def test_voice_status_warns_that_the_piper_binary_is_the_archived_one(
    make_ctx, monkeypatch
):
    """Piper الأصلي اتأرشف والوريث GPL — لازم الحالة تقول كده بدل ما
    المستخدم يفضل يبني على مكتبة مش هتتصلح."""
    monkeypatch.setattr(
        vp.shutil, "which",
        lambda name: f"/usr/bin/{name}" if name == "piper" else None,
    )
    result = vp._cmd_voice_status(make_ctx("voice_status", []))
    assert "archived" in result
    assert "GPL-3.0" in result


def test_voice_status_says_sherpa_is_tried_before_piper(make_ctx, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    result = vp._cmd_voice_status(make_ctx("voice_status", []))
    assert result.index("sherpa-onnx") < result.index("Piper binary")


# ── sherpa-onnx: المحرك المصان اللي بيحل محل Piper المؤرشف ──────────

def _make_tar(path, entries, symlink=None):
    """بيبني tar.bz2 فيه المسارات دي بالظبط."""
    import io
    import tarfile as tf
    with tf.open(path, "w:bz2") as tar:
        for name in entries:
            data = b"x" * 16
            info = tf.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if symlink:
            info = tf.TarInfo(symlink[0])
            info.type = tf.SYMTYPE
            info.linkname = symlink[1]
            tar.addfile(info)


def test_extract_accepts_a_normal_archive(tmp_path):
    archive = tmp_path / "ok.tar.bz2"
    _make_tar(archive, ["voice/model.onnx", "voice/tokens.txt"])
    dest = tmp_path / "out"
    dest.mkdir()
    assert vp._safe_extract(archive, dest) is True
    assert (dest / "voice" / "model.onnx").is_file()


def test_extract_refuses_paths_that_escape_the_directory(tmp_path):
    """أرشيف متحمّل من الإنترنت ممكن يكون فيه ../.. — الفك من غير فحص
    ثغرة معروفة، مش احتمال نظري."""
    archive = tmp_path / "evil.tar.bz2"
    _make_tar(archive, ["../escaped.txt"])
    dest = tmp_path / "out"
    dest.mkdir()
    assert vp._safe_extract(archive, dest) is False
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_refuses_symlinks(tmp_path):
    archive = tmp_path / "link.tar.bz2"
    _make_tar(archive, ["voice/model.onnx"], symlink=("voice/evil", "/etc/passwd"))
    dest = tmp_path / "out"
    dest.mkdir()
    assert vp._safe_extract(archive, dest) is False


def test_extract_survives_a_corrupt_archive(tmp_path):
    archive = tmp_path / "bad.tar.bz2"
    archive.write_bytes(b"not an archive at all")
    dest = tmp_path / "out"
    dest.mkdir()
    assert vp._safe_extract(archive, dest) is False


def test_cached_voice_is_not_downloaded_again(monkeypatch, isolated_voice_cache):
    voice = vp._VOICES["ar"]
    d = isolated_voice_cache / voice["sherpa_bundle"]
    d.mkdir(parents=True)
    (d / voice["sherpa_model"]).write_bytes(b"model")
    (d / "tokens.txt").write_text("tokens")

    calls = []
    monkeypatch.setattr(vp, "_download", lambda url, dest: calls.append(url))
    assert vp._ensure_sherpa_voice("ar") == d
    assert calls == []


def test_missing_sherpa_package_is_not_an_error(monkeypatch):
    """sherpa اختياري — من غيره السلسلة بتكمّل للمحرك اللي بعده."""
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    vp._sherpa_cache.clear()
    assert vp._load_sherpa("ar") is None


def test_sherpa_backend_reports_failure_when_model_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "_load_sherpa", lambda lang="ar": None)
    assert vp._synthesize_sherpa("أهلاً", tmp_path / "o.wav", "ar") is False


def test_sherpa_writes_a_real_wav(tmp_path, monkeypatch):
    class _Audio:
        samples = [0.25] * 2048
        sample_rate = 22050

    class _FakeTts:
        def generate(self, text, sid=0, speed=1.0):
            return _Audio()

    monkeypatch.setattr(vp, "_load_sherpa", lambda lang="ar": _FakeTts())
    out = tmp_path / "o.wav"
    assert vp._synthesize_sherpa("أهلاً بيك", out, "ar") is True
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == 22050
        assert wf.getnframes() == 2048
        assert wf.getsampwidth() == 2


def test_sherpa_rejects_empty_audio(tmp_path, monkeypatch):
    class _Audio:
        samples = []
        sample_rate = 22050

    class _FakeTts:
        def generate(self, text, sid=0, speed=1.0):
            return _Audio()

    monkeypatch.setattr(vp, "_load_sherpa", lambda lang="ar": _FakeTts())
    assert vp._synthesize_sherpa("x", tmp_path / "o.wav", "ar") is False


def test_sherpa_is_tried_before_the_archived_piper_binary():
    order = [name for _label, name, _ext, _key in vp._BACKENDS]
    assert order.index("_synthesize_sherpa") < order.index("_synthesize_piper")


def test_every_language_has_a_sherpa_voice():
    for lang, voice in vp._VOICES.items():
        assert voice["sherpa_bundle"], lang
        assert voice["sherpa_model"].endswith(".onnx"), lang


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


def _fixed_recording(monkeypatch, captured):
    """يخلي التسجيل بالمدة الثابتة ينجح من غير مايك حقيقي، ويسجّل المدة."""
    def fake_record(seconds, out_path):
        captured["seconds"] = seconds
        return None
    monkeypatch.setattr(vp, "_record_audio", fake_record)
    monkeypatch.setattr(vp, "_record_until_silence", lambda out, mx: (None, False))


def test_listen_clamps_seconds_to_max(monkeypatch, make_ctx):
    captured = {}
    _fixed_recording(monkeypatch, captured)
    monkeypatch.setattr(vp, "_transcribe", lambda wav: ("تمام", None))
    vp._cmd_listen(make_ctx("listen 999", ["999"]))
    assert captured["seconds"] == vp._LISTEN_MAX_SECONDS


def test_listen_returns_transcribed_text_without_executing(monkeypatch, make_ctx, bare_engine):
    _fixed_recording(monkeypatch, {})
    monkeypatch.setattr(vp, "_transcribe", lambda wav: ("افتح الاعدادات", None))
    result = vp._cmd_listen(make_ctx("listen", [], engine=bare_engine))
    assert "افتح الاعدادات" in result
    assert bare_engine._queue.empty()


def test_listen_propagates_recording_error(monkeypatch, make_ctx):
    monkeypatch.setattr(vp, "_record_until_silence", lambda out, mx: (None, False))
    monkeypatch.setattr(vp, "_record_audio", lambda s, out: "no microphone")
    result = vp._cmd_listen(make_ctx("listen", []))
    assert result.startswith("❌")
    assert "no microphone" in result


def test_listen_run_submits_transcribed_text(monkeypatch, make_ctx, bare_engine):
    _fixed_recording(monkeypatch, {})
    monkeypatch.setattr(vp, "_transcribe", lambda wav: ("echo hi", None))
    result = vp._cmd_listen_run(make_ctx("listen_run", [], engine=bare_engine))
    assert "▶️" in result
    text, _fn = bare_engine._queue.get_nowait()
    assert text == "echo hi"


def test_listen_run_does_not_submit_on_error(monkeypatch, make_ctx, bare_engine):
    _fixed_recording(monkeypatch, {})
    monkeypatch.setattr(vp, "_transcribe", lambda wav: (None, "🔇 heard nothing"))
    result = vp._cmd_listen_run(make_ctx("listen_run", [], engine=bare_engine))
    assert result.startswith("🔇")
    assert bare_engine._queue.empty()


# ── VAD: يقف لما تسكت بدل المدة الثابتة ──────────────────────────────

def test_listen_uses_vad_when_no_duration_given(monkeypatch, make_ctx):
    """من غير وسائط: نستنى لحد ما تسكت، من غير ما نلمس المدة الثابتة."""
    calls = []
    monkeypatch.setattr(vp, "_record_until_silence",
                        lambda out, mx: (calls.append(("vad", mx)), (None, True))[1])
    monkeypatch.setattr(vp, "_record_audio",
                        lambda s, out: calls.append(("fixed", s)))
    monkeypatch.setattr(vp, "_transcribe", lambda wav: ("ok", None))
    vp._cmd_listen(make_ctx("listen", []))
    assert calls == [("vad", vp._LISTEN_MAX_SECONDS)]


def test_explicit_seconds_bypasses_vad(monkeypatch, make_ctx):
    """لو قلت `listen 3` يبقى إنت عايز 3 ثواني بالظبط، مش لحد ما تسكت."""
    calls = []
    monkeypatch.setattr(vp, "_record_until_silence",
                        lambda out, mx: (calls.append("vad"), (None, True))[1])
    monkeypatch.setattr(vp, "_record_audio",
                        lambda s, out: (calls.append(("fixed", s)), None)[1])
    monkeypatch.setattr(vp, "_transcribe", lambda wav: ("ok", None))
    vp._cmd_listen(make_ctx("listen 3", ["3"]))
    assert calls == [("fixed", 3)]


def test_falls_back_to_fixed_duration_when_vad_not_installed(monkeypatch, make_ctx):
    """silero اختياري بالكامل — من غيره الأمر لازم يفضل شغال."""
    calls = []
    monkeypatch.setattr(vp, "_record_until_silence", lambda out, mx: (None, False))
    monkeypatch.setattr(vp, "_record_audio",
                        lambda s, out: (calls.append(s), None)[1])
    monkeypatch.setattr(vp, "_transcribe", lambda wav: ("ok", None))
    vp._cmd_listen(make_ctx("listen", []))
    assert calls == [vp._LISTEN_DEFAULT_SECONDS]


def test_vad_unavailable_reports_not_used(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "sd", object())
    monkeypatch.setattr(vp, "_load_vad", lambda: None)
    err, used = vp._record_until_silence(tmp_path / "out.wav", 10)
    assert err is None
    assert used is False


def test_vad_needs_sounddevice(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "sd", None)
    err, used = vp._record_until_silence(tmp_path / "out.wav", 10)
    assert "sounddevice" in err
    assert used is False


class _FakeStream:
    """مايك مزيّف: بيرجع شرائح جاهزة واحدة ورا التانية."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        self.reads += 1
        if self._chunks:
            return self._chunks.pop(0), False
        return _np.zeros((n, 1), dtype=_np.int16), False


def _fake_sd(stream):
    class FakeSD:
        @staticmethod
        def InputStream(**kwargs):
            return stream
    return FakeSD


def _wire_vad(monkeypatch, probs, chunks):
    """نموذج VAD مزيّف بيرجع احتمالات مكتوبة بالترتيب — من غير torch."""
    stream = _FakeStream(chunks)
    monkeypatch.setattr(vp, "sd", _fake_sd(stream))
    monkeypatch.setattr(vp, "_load_vad", lambda: object())
    seq = list(probs)
    monkeypatch.setattr(vp, "_vad_prob",
                        lambda model, mono: seq.pop(0) if seq else 0.0)
    return stream


def _chunk(value=1000, n=None):
    n = n or vp._VAD_CHUNK
    return _np.full((n, 1), value, dtype=_np.int16)


def test_vad_stops_after_silence(monkeypatch, tmp_path):
    """الفايدة الأساسية: التسجيل بيقف بعد السكوت، مش بيكمّل للنهاية."""
    monkeypatch.setattr(vp, "_VAD_MIN_SPEECH_MS", 0)
    silence_chunks = (vp._VAD_SILENCE_MS * vp._SAMPLE_RATE) // (1000 * vp._VAD_CHUNK)
    probs = [0.9] * 5 + [0.0] * (silence_chunks + 5)
    stream = _wire_vad(monkeypatch, probs, [_chunk() for _ in probs])

    out = tmp_path / "out.wav"
    err, used = vp._record_until_silence(out, 60)

    assert err is None
    assert used is True
    # وقف بعد السكوت بدل ما يكمّل الـ 60 ثانية
    assert stream.reads < (60 * vp._SAMPLE_RATE) // vp._VAD_CHUNK
    assert stream.reads == 5 + silence_chunks
    assert out.is_file()


def test_vad_rejects_noise_shorter_than_min_speech(monkeypatch, tmp_path):
    """خبطة واحدة على الترابيزة مش جملة — منبعتش صوت شبه فاضي للتفريغ."""
    probs = [0.9, 0.0] + [0.0] * 200
    _wire_vad(monkeypatch, probs, [_chunk() for _ in probs])
    err, used = vp._record_until_silence(tmp_path / "out.wav", 5)
    assert used is True
    assert "clear speech" in err


def test_vad_keeps_pre_roll_before_first_word(monkeypatch, tmp_path):
    """أول حرف في الجملة بيتقال قبل ما الـ VAD يقرر إن ده كلام — لو
    رمينا اللي قبله، التفريغ بيضيّع بداية الكلمة."""
    monkeypatch.setattr(vp, "_VAD_MIN_SPEECH_MS", 0)
    silence_chunks = (vp._VAD_SILENCE_MS * vp._SAMPLE_RATE) // (1000 * vp._VAD_CHUNK)
    quiet_before = 3
    probs = [0.0] * quiet_before + [0.9] * 4 + [0.0] * (silence_chunks + 2)
    chunks = ([_chunk(7) for _ in range(quiet_before)]
              + [_chunk(1000) for _ in range(4 + silence_chunks + 2)])
    _wire_vad(monkeypatch, probs, chunks)

    out = tmp_path / "out.wav"
    err, _used = vp._record_until_silence(out, 60)
    assert err is None

    with wave.open(str(out), "rb") as wf:
        frames = wf.getnframes()
    # الشرايح الهادية اللي قبل أول كلمة اتحفظت مع الكلام
    assert frames == (quiet_before + 4 + silence_chunks) * vp._VAD_CHUNK


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
    for cmd in (
        "speak", "voice_status", "listen", "listen_run", "stt_status", "separate_vocals",
        "diarize_set_token", "diarize_key_status", "diarize",
        "clone_voice_agree_license", "clone_voice",
    ):
        assert cmd in FakeEngine.registry.names


# ── diarize_set_token / diarize_key_status ──────────────────────────────

def test_diarize_set_token_no_args(make_ctx):
    result = vp._cmd_diarize_set_token(make_ctx("diarize_set_token", []))
    assert result.startswith("usage")


def test_diarize_set_token_empty(make_ctx):
    result = vp._cmd_diarize_set_token(make_ctx("diarize_set_token", [" "]))
    assert result.startswith("❌")


def test_diarize_set_token_saves_and_reports_without_keyring(make_ctx, isolated_diarize_config):
    result = vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["hf_tok_123"]))
    assert "⚠️" in result
    assert vp._hf_token() == "hf_tok_123"


def test_diarize_set_token_uses_keyring_when_available(make_ctx, monkeypatch, isolated_diarize_config):
    fake = _FakeKeyring()
    monkeypatch.setattr(vp, "_HAS_KEYRING", True)
    monkeypatch.setattr(vp, "keyring", fake)

    result = vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["seckey123"]))
    assert "✅" in result
    assert "keyring" in result
    assert fake.get_password(vp._DIARIZE_KEYRING_SERVICE, vp._DIARIZE_TOKEN_NAME) == "seckey123"
    assert vp._hf_token() == "seckey123"


def test_diarize_set_token_clears_old_plaintext_after_keyring_success(make_ctx, monkeypatch, isolated_diarize_config):
    isolated_diarize_config.write_text(json.dumps({"hf_token": "oldplaintext"}), encoding="utf-8")
    fake = _FakeKeyring()
    monkeypatch.setattr(vp, "_HAS_KEYRING", True)
    monkeypatch.setattr(vp, "keyring", fake)

    vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["newsecure"]))
    data = json.loads(isolated_diarize_config.read_text())
    assert not data.get("hf_token")
    assert vp._hf_token() == "newsecure"


def test_diarize_set_token_keyring_error_falls_back_to_plaintext(make_ctx, monkeypatch, isolated_diarize_config):
    import keyring.errors as kerrors

    class _BrokenKeyring:
        def get_password(self, *a):
            raise kerrors.NoKeyringError("no backend")

        def set_password(self, *a):
            raise kerrors.NoKeyringError("no backend")

    monkeypatch.setattr(vp, "_HAS_KEYRING", True)
    monkeypatch.setattr(vp, "keyring", _BrokenKeyring())

    result = vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["fallbacktoken"]))
    assert "⚠️" in result
    assert vp._hf_token() == "fallbacktoken"


def test_diarize_key_status_no_token(make_ctx, isolated_diarize_config):
    result = vp._cmd_diarize_key_status(make_ctx("diarize_key_status", []))
    assert result.startswith("❌")
    assert "huggingface.co/settings/tokens" in result


def test_diarize_key_status_masks_token(make_ctx, isolated_diarize_config):
    vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["abcdefgh12345678"]))
    result = vp._cmd_diarize_key_status(make_ctx("diarize_key_status", []))
    assert result.startswith("✅")
    assert "abcdefgh12345678" not in result
    assert "abcd" in result


def test_diarize_key_status_reports_pyannote_missing(make_ctx, monkeypatch, isolated_diarize_config):
    vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["tok"]))
    monkeypatch.setitem(sys.modules, "pyannote.audio", None)
    result = vp._cmd_diarize_key_status(make_ctx("diarize_key_status", []))
    assert "pyannote.audio is not installed" in result


# ── diarize ──────────────────────────────────────────────────────────────

def test_diarize_no_args(make_ctx):
    result = vp._cmd_diarize(make_ctx("diarize", []))
    assert result.startswith("usage")


def test_diarize_reports_missing_tool(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyannote.audio", None)
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_diarize(make_ctx("diarize", [str(f)]))
    assert "pyannote.audio is not installed" in result


def test_diarize_missing_input_file(make_ctx, tmp_path, monkeypatch):
    fake_module = types.ModuleType("pyannote.audio")
    fake_module.Pipeline = object
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake_module)
    result = vp._cmd_diarize(make_ctx("diarize", [str(tmp_path / "nope.wav")]))
    assert result.startswith("❌")
    assert "file not found" in result


def test_diarize_no_token(make_ctx, tmp_path, monkeypatch, isolated_diarize_config):
    fake_module = types.ModuleType("pyannote.audio")
    fake_module.Pipeline = object
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake_module)
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_diarize(make_ctx("diarize", [str(f)]))
    assert result.startswith("❌")
    assert "diarize_set_token" in result


def test_diarize_model_not_agreed_reports_manual_step(make_ctx, tmp_path, monkeypatch, isolated_diarize_config):
    vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["tok"]))

    class _FakePipelineClass:
        @staticmethod
        def from_pretrained(model, token=None):
            return None  # pyannote نفسها بترجع None لو الموافقة اليدوية مش متعملة

    fake_module = types.ModuleType("pyannote.audio")
    fake_module.Pipeline = _FakePipelineClass
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake_module)
    monkeypatch.setattr(vp, "_diarize_pipeline_cache", {})

    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_diarize(make_ctx("diarize", [str(f)]))
    assert result.startswith("❌")
    assert "huggingface.co" in result


def test_diarize_success_reports_speakers(make_ctx, tmp_path, monkeypatch, isolated_diarize_config):
    vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["tok"]))

    class _FakeTurn:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class _FakeDiarization:
        def itertracks(self, yield_label=True):
            return iter([
                (_FakeTurn(0.0, 1.5), "track_0", "SPEAKER_00"),
                (_FakeTurn(1.5, 3.2), "track_1", "SPEAKER_01"),
                (_FakeTurn(3.2, 4.0), "track_2", "SPEAKER_00"),
            ])

    class _FakePipeline:
        def __call__(self, path):
            return _FakeDiarization()

    class _FakePipelineClass:
        @staticmethod
        def from_pretrained(model, token=None):
            return _FakePipeline()

    fake_module = types.ModuleType("pyannote.audio")
    fake_module.Pipeline = _FakePipelineClass
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake_module)
    monkeypatch.setattr(vp, "_diarize_pipeline_cache", {})

    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_diarize(make_ctx("diarize", [str(f)]))
    assert result.startswith("🗣️")
    assert "2 speakers found" in result
    assert "SPEAKER_00" in result
    assert "SPEAKER_01" in result


def test_diarize_caches_pipeline_across_calls(make_ctx, tmp_path, monkeypatch, isolated_diarize_config):
    vp._cmd_diarize_set_token(make_ctx("diarize_set_token", ["tok"]))
    load_calls = []

    class _FakeDiarization:
        def itertracks(self, yield_label=True):
            return iter([])

    class _FakePipeline:
        def __call__(self, path):
            return _FakeDiarization()

    class _FakePipelineClass:
        @staticmethod
        def from_pretrained(model, token=None):
            load_calls.append(model)
            return _FakePipeline()

    fake_module = types.ModuleType("pyannote.audio")
    fake_module.Pipeline = _FakePipelineClass
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake_module)
    monkeypatch.setattr(vp, "_diarize_pipeline_cache", {})

    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    vp._cmd_diarize(make_ctx("diarize", [str(f)]))
    vp._cmd_diarize(make_ctx("diarize", [str(f)]))
    assert load_calls == [vp._DIARIZE_MODEL]


# ── separate_vocals ───────────────────────────────────────────────────

def test_separate_vocals_no_args(make_ctx):
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", []))
    assert result.startswith("usage")


def test_separate_vocals_reports_missing_tool(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(f), str(tmp_path / "out")]))
    assert "demucs is not installed" in result
    assert "pip install demucs" in result


def test_separate_vocals_missing_input(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/demucs" if name == "demucs" else None)
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(tmp_path / "nope.wav"), str(tmp_path / "out")]))
    assert result.startswith("❌")
    assert "file not found" in result


def test_separate_vocals_rejects_bad_mode(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/demucs" if name == "demucs" else None)
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(f), str(tmp_path / "out"), "bogus"]))
    assert result.startswith("❌")
    assert "mode" in result


def test_separate_vocals_uses_two_stems_flag_for_vocals_mode(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/demucs" if name == "demucs" else None)
    captured = {}
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # بيحاكي هيكل خرج demucs الحقيقي: <out_dir>/<model>/<track>/*.wav
        stem_dir = out_dir / "htdemucs" / "in"
        stem_dir.mkdir(parents=True, exist_ok=True)
        (stem_dir / "vocals.wav").write_bytes(b"fake")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(f), str(out_dir), "vocals"]))
    assert result.startswith("✅")
    assert "--two-stems" in captured["cmd"]
    assert "vocals" in captured["cmd"]


def test_separate_vocals_detects_exit_zero_but_no_output(make_ctx, tmp_path, monkeypatch):
    # نفس مشكلة realesrgan-ncnn-vulkan/auto-editor (exit 0 حتى لو فشل
    # فعليًا) — لازم نتأكد من وجود ملفات .wav حقيقية مش نثق في exit code بس.
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/demucs" if name == "demucs" else None)
    monkeypatch.setattr(vp.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(f), str(tmp_path / "out")]))
    assert result.startswith("❌")
    assert "produced no real audio files" in result


def test_separate_vocals_timeout_reported(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/demucs" if name == "demucs" else None)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(f), str(tmp_path / "out")]))
    assert result.startswith("⏱")


def test_separate_vocals_nonzero_exit_reports_stderr(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/demucs" if name == "demucs" else None)
    monkeypatch.setattr(
        vp.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"),
    )
    f = tmp_path / "in.wav"
    f.write_bytes(b"x")
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(f), str(tmp_path / "out")]))
    assert result.startswith("❌")
    assert "boom" in result


@requires_demucs
@requires_ffmpeg
def test_separate_vocals_real_run_produces_stems(make_ctx, tmp_path):
    src = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(src), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    out_dir = tmp_path / "separated"
    result = vp._cmd_separate_vocals(make_ctx("separate_vocals", [str(src), str(out_dir), "vocals"]))
    # demucs بيحمّل نموذجه (~80MB) من dl.fbaipublicfiles.com عند أول
    # استخدام — لو الشبكة في بيئة التشغيل دي بتمنع الدومين ده تحديدًا
    # (زي بعض بيئات CI/sandbox المقيّدة)، ده قيد شبكة مش باگ في الكود
    # نفسه، فبنعدي الاختبار بدل ما نفشله.
    if result.startswith("❌") and any(s in result for s in ("URLError", "Forbidden", "Tunnel connection")):
        pytest.skip("demucs model download blocked by network policy in this environment")
    assert result.startswith("✅")
    vocals_files = list(out_dir.rglob("vocals.wav"))
    assert vocals_files, f"no vocals.wav found under {out_dir}"


# ── clone_voice_agree_license ────────────────────────────────────────────

def test_clone_voice_agree_license_saves_and_reports(make_ctx, isolated_clone_config):
    result = vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))
    assert result.startswith("✅")
    assert "coqui.ai/cpml" in result
    assert vp._clone_license_agreed() is True


def test_clone_license_agreed_false_by_default(isolated_clone_config):
    assert vp._clone_license_agreed() is False


# ── clone_voice ─────────────────────────────────────────────────────────

def test_clone_voice_no_args(make_ctx):
    result = vp._cmd_clone_voice(make_ctx("clone_voice", []))
    assert result.startswith("usage")
    assert "without their consent" in result  # التذكير الأخلاقي موجود حتى في رسالة usage


def test_clone_voice_requires_license_agreement_first(make_ctx, tmp_path, isolated_clone_config):
    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "hello", str(tmp_path / "out.wav")]))
    assert result.startswith("❌")
    assert "clone_voice_agree_license" in result


def test_clone_voice_reports_missing_tool(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))
    monkeypatch.setitem(sys.modules, "TTS.api", None)
    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "hello", str(tmp_path / "out.wav")]))
    assert "TTS (Coqui) is not installed" in result
    assert "pip install TTS" in result


def test_clone_voice_missing_reference_file(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))
    fake_module = types.ModuleType("TTS.api")
    fake_module.TTS = object
    monkeypatch.setitem(sys.modules, "TTS.api", fake_module)
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(tmp_path / "nope.wav"), "hello", str(tmp_path / "out.wav")]))
    assert result.startswith("❌")
    assert "file not found" in result


def test_clone_voice_empty_text(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))
    fake_module = types.ModuleType("TTS.api")
    fake_module.TTS = object
    monkeypatch.setitem(sys.modules, "TTS.api", fake_module)
    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "   ", str(tmp_path / "out.wav")]))
    assert result.startswith("❌")
    assert "the text is empty" in result


def test_clone_voice_rejects_bad_language(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))
    fake_module = types.ModuleType("TTS.api")
    fake_module.TTS = object
    monkeypatch.setitem(sys.modules, "TTS.api", fake_module)
    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "hello", str(tmp_path / "out.wav"), "klingon"]))
    assert result.startswith("❌")
    assert "language" in result


def test_clone_voice_success_creates_output_and_sets_tos_env(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))
    monkeypatch.delenv("COQUI_TOS_AGREED", raising=False)

    calls = []

    class _FakeCoquiTTS:
        def __init__(self, model_name, progress_bar=True, gpu=False):
            calls.append(("init", model_name))

        def tts_to_file(self, text, speaker_wav, language, file_path):
            calls.append(("synth", text, speaker_wav, language, file_path))
            pathlib.Path(file_path).write_bytes(b"fake-audio")

    fake_module = types.ModuleType("TTS.api")
    fake_module.TTS = _FakeCoquiTTS
    monkeypatch.setitem(sys.modules, "TTS.api", fake_module)
    monkeypatch.setattr(vp, "_clone_voice_models", {})

    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    out = tmp_path / "out.wav"
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "أهلاً بيكي", str(out), "ar"]))

    assert result.startswith("✅")
    assert out.is_file()
    assert os.environ.get("COQUI_TOS_AGREED") == "1"
    assert calls[0] == ("init", vp._CLONE_MODEL)
    assert calls[1] == ("synth", "أهلاً بيكي", str(f), "ar", str(out))


def test_clone_voice_caches_model_across_calls(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))
    init_calls = []

    class _FakeCoquiTTS:
        def __init__(self, model_name, progress_bar=True, gpu=False):
            init_calls.append(model_name)

        def tts_to_file(self, text, speaker_wav, language, file_path):
            pathlib.Path(file_path).write_bytes(b"fake-audio")

    fake_module = types.ModuleType("TTS.api")
    fake_module.TTS = _FakeCoquiTTS
    monkeypatch.setitem(sys.modules, "TTS.api", fake_module)
    monkeypatch.setattr(vp, "_clone_voice_models", {})

    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "hi", str(tmp_path / "out1.wav")]))
    vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "hi again", str(tmp_path / "out2.wav")]))
    assert init_calls == [vp._CLONE_MODEL]


def test_clone_voice_reports_when_output_missing(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))

    class _FakeCoquiTTS:
        def __init__(self, model_name, progress_bar=True, gpu=False):
            pass

        def tts_to_file(self, text, speaker_wav, language, file_path):
            pass  # عمداً مبيكتبش أي ملف — بيحاكي فشل صامت

    fake_module = types.ModuleType("TTS.api")
    fake_module.TTS = _FakeCoquiTTS
    monkeypatch.setitem(sys.modules, "TTS.api", fake_module)
    monkeypatch.setattr(vp, "_clone_voice_models", {})

    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "hi", str(tmp_path / "missing_out.wav")]))
    assert result.startswith("❌")
    assert "no real output file" in result


def test_clone_voice_model_load_error_reported(make_ctx, tmp_path, monkeypatch, isolated_clone_config):
    vp._cmd_clone_voice_agree_license(make_ctx("clone_voice_agree_license", []))

    class _FailingTTS:
        def __init__(self, model_name, progress_bar=True, gpu=False):
            raise RuntimeError("boom")

    fake_module = types.ModuleType("TTS.api")
    fake_module.TTS = _FailingTTS
    monkeypatch.setitem(sys.modules, "TTS.api", fake_module)
    monkeypatch.setattr(vp, "_clone_voice_models", {})

    f = tmp_path / "ref.wav"
    f.write_bytes(b"x")
    result = vp._cmd_clone_voice(make_ctx("clone_voice", [str(f), "hi", str(tmp_path / "out.wav")]))
    assert result.startswith("❌")
    assert "boom" in result


# ── دعم اللغتين في النطق ─────────────────────────────────────────────

def test_detect_lang_arabic():
    assert vp._detect_lang("افحص الملف ده") == "ar"


def test_detect_lang_english():
    assert vp._detect_lang("scan this file please") == "en"


def test_detect_lang_mixed_counts_as_arabic():
    """نص فيه حرف عربي واحد جوهره عربي — زي "افحص file.exe"."""
    assert vp._detect_lang("افحص file.exe") == "ar"


def test_detect_lang_empty_defaults_to_english():
    assert vp._detect_lang("") == "en"


def test_detect_lang_numbers_only():
    assert vp._detect_lang("12345") == "en"


def test_arabic_and_english_use_different_edge_voices():
    """راجع: المحركات كانت مربوطة بالعربي بالإيد، فأي نص إنجليزي كان
    بيتقري بصوت عربي — كلام مش مفهوم."""
    assert vp._voice_for("ar")["edge"] != vp._voice_for("en")["edge"]
    assert vp._voice_for("ar")["edge"].startswith("ar-")
    assert vp._voice_for("en")["edge"].startswith("en-")


def test_arabic_and_english_use_different_piper_models():
    assert vp._voice_for("ar")["piper_name"] != vp._voice_for("en")["piper_name"]


def test_arabic_and_english_use_different_espeak_voices():
    assert vp._voice_for("ar")["espeak"] == "ar"
    assert vp._voice_for("en")["espeak"] == "en-us"


def test_unknown_language_falls_back_to_english():
    assert vp._voice_for("fr") == vp._voice_for("en")


def test_edge_synthesis_passes_the_english_voice(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        (tmp_path / "out.mp3").write_bytes(b"audio")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/edge-tts")
    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    vp._synthesize_edge("hello world", tmp_path / "out.mp3", "en")
    assert vp._voice_for("en")["edge"] in captured["cmd"]


def test_edge_synthesis_passes_the_arabic_voice(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        (tmp_path / "out.mp3").write_bytes(b"audio")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/edge-tts")
    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    vp._synthesize_edge("أهلاً بيك", tmp_path / "out.mp3", "ar")
    assert vp._voice_for("ar")["edge"] in captured["cmd"]


def test_espeak_synthesis_passes_the_right_voice_flag(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        (tmp_path / "out.wav").write_bytes(b"audio")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/espeak-ng")
    monkeypatch.setattr(vp.subprocess, "run", fake_run)
    vp._synthesize_espeak("hello", tmp_path / "out.wav", "en")
    assert "en-us" in captured["cmd"]


def test_fallback_detects_language_from_the_text(monkeypatch, tmp_path):
    seen = {}

    def fake_edge(text, out, lang="ar"):
        seen["lang"] = lang
        out.write_bytes(b"a")
        return True

    monkeypatch.setattr(vp, "_synthesize_edge", fake_edge)
    vp._synthesize_with_fallback("hello there", tmp_path)
    assert seen["lang"] == "en"

    vp._synthesize_with_fallback("أهلاً بيك", tmp_path)
    assert seen["lang"] == "ar"


def test_explicit_language_overrides_detection(monkeypatch, tmp_path):
    seen = {}

    def fake_edge(text, out, lang="ar"):
        seen["lang"] = lang
        out.write_bytes(b"a")
        return True

    monkeypatch.setattr(vp, "_synthesize_edge", fake_edge)
    # نص عربي بس المستخدم طلب إنجليزي صراحةً
    vp._synthesize_with_fallback("أهلاً", tmp_path, "en")
    assert seen["lang"] == "en"


def test_backend_label_names_the_voice_actually_used(monkeypatch, tmp_path):
    def fake_edge(text, out, lang="ar"):
        out.write_bytes(b"a")
        return True

    monkeypatch.setattr(vp, "_synthesize_edge", fake_edge)
    _path, label = vp._synthesize_with_fallback("hello", tmp_path)
    assert vp._voice_for("en")["edge"] in label


def test_speak_accepts_an_explicit_language_suffix(monkeypatch, make_ctx, tmp_path):
    seen = {}

    def fake_fallback(text, tmp, lang=None):
        seen["text"], seen["lang"] = text, lang
        return None

    monkeypatch.setattr(vp, "_synthesize_with_fallback", fake_fallback)
    vp._cmd_speak(make_ctx("speak أهلاً بيك lang=en", []))
    assert seen["lang"] == "en"
    assert seen["text"] == "أهلاً بيك"      # اللاحقة اتشالت من النص


def test_speak_without_suffix_leaves_detection_to_the_backend(monkeypatch, make_ctx):
    seen = {}
    monkeypatch.setattr(
        vp, "_synthesize_with_fallback",
        lambda text, tmp, lang=None: seen.update(lang=lang) or None,
    )
    vp._cmd_speak(make_ctx("speak hello world", []))
    assert seen["lang"] is None


def test_speak_with_only_a_language_suffix_shows_usage(make_ctx):
    assert vp._cmd_speak(make_ctx("speak lang=en", [])).startswith("usage")


def test_piper_downloads_the_model_for_the_requested_language(monkeypatch, tmp_path):
    urls = []
    monkeypatch.setattr(vp, "_voice_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(vp, "_download", lambda url, dest: urls.append(url) or dest.write_bytes(b"m") or True)
    vp._ensure_piper_voice("en")
    assert any("en_US" in u for u in urls)
    assert not any("ar_JO" in u for u in urls)


def test_arabic_reply_gets_the_arabic_voice_end_to_end(monkeypatch, tmp_path):
    """السلسلة كاملة: رد المخ بالعربي → النطق يختار الصوت العربي.
    ده اللي بيخلي 'اتكلم معاها عربي ترد عربي' مسموع مش مكتوب بس."""
    seen = {}

    def fake_edge(text, out, lang="ar"):
        seen["lang"] = lang
        out.write_bytes(b"a")
        return True

    monkeypatch.setattr(vp, "_synthesize_edge", fake_edge)
    vp._synthesize_with_fallback("أهلاً! أنا تمام الحمد لله", tmp_path)
    assert seen["lang"] == "ar"


def test_english_reply_gets_the_english_voice_end_to_end(monkeypatch, tmp_path):
    seen = {}

    def fake_edge(text, out, lang="ar"):
        seen["lang"] = lang
        out.write_bytes(b"a")
        return True

    monkeypatch.setattr(vp, "_synthesize_edge", fake_edge)
    vp._synthesize_with_fallback("Hi! I'm doing well, thanks", tmp_path)
    assert seen["lang"] == "en"
