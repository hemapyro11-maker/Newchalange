import self_repair_plugin as sr


def test_self_repair_registers(bare_engine):
    sr.register(bare_engine)
    assert bare_engine.registry.get("self_repair") is not None


def test_media_smoke_reports_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr(sr.mr, "binary", lambda name: None)
    assert sr._real_media_smoke() == (False, "FFmpeg is unavailable")
