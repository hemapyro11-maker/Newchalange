import json

import video_intelligence_plugin as vip


def _public_video():
    return {
        "kind": "video", "title": "Winning Story", "url": "https://youtu.be/win",
        "channel": "Tuty Storytime", "views": 2000, "likes": 100,
        "comments": 20, "upload_date": "20260901",
    }


def test_video_analyze_remote_measures_and_learns(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vip, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(vip.youtube_public, "inspect_url", lambda url: _public_video())
    monkeypatch.setattr(vip.youtube_public, "download_video", lambda url, folder, height=480: (tmp_path / "v.mp4", {}))
    monkeypatch.setattr(vip, "_analyse_local", lambda path: ({
        "duration": 60, "width": 1280, "height": 720, "fps": 30,
        "video_codec": "h264", "audio_codec": "aac", "bitrate_kbps": 1200,
        "scene_count": 12, "avg_shot_seconds": 5, "silence_ratio": .02,
        "mean_volume_db": -16,
    }, "A fast opening that promises a calm bedtime story"))
    result = vip._cmd_youtube_video_analyze(
        make_ctx("youtube_video_analyze", ["https://youtu.be/win"])
    )
    assert "Winning Story" in result
    assert "12 scenes" in result
    assert "saved to the production profile" in result
    saved = json.loads((tmp_path / "video_learning.json").read_text(encoding="utf-8"))
    assert saved["records"][0]["views"] == 2000


def test_analyze_same_source_updates_instead_of_duplicating(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vip, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(vip.youtube_public, "inspect_url", lambda url: _public_video())
    monkeypatch.setattr(vip.youtube_public, "download_video", lambda url, folder, height=480: (tmp_path / "v.mp4", {}))
    monkeypatch.setattr(vip, "_analyse_local", lambda path: ({"duration": 60}, ""))
    ctx = make_ctx("youtube_video_analyze", ["https://youtu.be/win"])
    vip._cmd_youtube_video_analyze(ctx)
    vip._cmd_youtube_video_analyze(ctx)
    assert len(vip._load_profile()["records"]) == 1


def test_unavailable_stream_keeps_metadata_analysis(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vip, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(vip.youtube_public, "inspect_url", lambda url: _public_video())
    monkeypatch.setattr(vip.youtube_public, "download_video", lambda *a, **k: (_ for _ in ()).throw(
        vip.youtube_public.PublicYouTubeError("This video is not available")
    ))
    result = vip._cmd_youtube_video_analyze(
        make_ctx("youtube_video_analyze", ["https://youtu.be/win"])
    )
    assert "Winning Story" in result
    assert "metadata only" in result
    assert "2,000 views" in result
    assert len(vip._load_profile()["records"]) == 1


def test_learning_profile_uses_best_performing_evidence(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vip, "_data_dir", lambda: tmp_path)
    (tmp_path / "video_learning.json").write_text(json.dumps({"records": [
        {"source": "a", "title": "Low", "views": 10, "metrics": {"duration": 120, "avg_shot_seconds": 8, "silence_ratio": .1}},
        {"source": "b", "title": "High", "views": 1000, "metrics": {"duration": 60, "avg_shot_seconds": 4, "silence_ratio": .02}},
    ]}), encoding="utf-8")
    result = vip._cmd_video_learning_profile(make_ctx("video_learning_profile", []))
    assert result.index("High") < result.index("Low")
    brief = vip._cmd_video_learning_brief(make_ctx("video_learning_brief", ["new", "story"]))
    assert "new story" in brief
    assert "Target duration: about 60s" in brief


def test_channel_growth_lab_ranks_outliers(make_ctx, monkeypatch):
    monkeypatch.setattr(vip.youtube_public, "channel_info", lambda identifier, maximum: {
        "title": "Tuty Storytime", "videos": [
            {"title": "Winner", "views": 1000, "url": "https://youtu.be/a"},
            {"title": "Normal", "views": 100, "url": "https://youtu.be/b"},
            {"title": "Low", "views": 50, "url": "https://youtu.be/c"},
        ],
    })
    result = vip._cmd_channel_view_growth_lab(
        make_ctx("channel_view_growth_lab", ["Tuty", "Storytime"])
    )
    assert "Winner" in result
    assert "10.00×" in result
    assert "youtube_video_analyze" in result


def test_registers_video_intelligence_commands():
    names = []

    class Registry:
        def register(self, name, handler, description=""):
            names.append(name)

    class Engine:
        registry = Registry()

    vip.register(Engine())
    assert set(names) == {"youtube_video_analyze", "channel_view_growth_lab", "video_learning_profile", "video_learning_brief"}


def test_technical_metrics_falls_back_to_bundled_ffmpeg(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(vip.media_runtime, "probe", lambda path: None)
    monkeypatch.setattr(vip.media_runtime, "binary", lambda name: "ffmpeg.exe")

    class Result:
        stderr = "Duration: 00:01:02.50, start: 0.0, bitrate: 850 kb/s\nStream #0: Video: h264, yuv420p, 1280x720, 30 fps\nStream #1: Audio: aac, 48000 Hz"

    monkeypatch.setattr(vip.media_runtime, "run", lambda args, timeout: Result())
    metrics = vip._technical_metrics(video)
    assert metrics["duration"] == 62.5
    assert metrics["width"] == 1280
    assert metrics["height"] == 720
    assert metrics["fps"] == 30
    assert metrics["audio_codec"] == "aac"
