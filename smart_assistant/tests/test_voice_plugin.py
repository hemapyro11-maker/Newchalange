import shutil
import subprocess

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
