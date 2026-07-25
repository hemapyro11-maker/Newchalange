import csv
import json

import pytest
import youtube_analytics_plugin as yap


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(yap, "_config_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _isolate_keyring(monkeypatch):
    """افتراضيًا نخلي keyring "مش متاح" وقت الاختبار — عشان القراءة
    ترجع من youtube_config.json بشكل ثابت، ومحدش يلمس مخزن أسرار نظام
    التشغيل الحقيقي بتاع اللي بيشغل الاختبارات."""
    monkeypatch.setattr(yap, "_HAS_KEYRING", False)


def _set_key(tmp_path, key="fakekey"):
    (tmp_path / "youtube_config.json").write_text(json.dumps({"api_key": key}), encoding="utf-8")


def test_api_key_reads_from_keyring_when_available(monkeypatch):
    class _FakeKeyring:
        def get_password(self, service, key):
            return "fromkeyring" if key == yap._API_KEY_NAME else None

    monkeypatch.setattr(yap, "_HAS_KEYRING", True)
    monkeypatch.setattr(yap, "keyring", _FakeKeyring())
    assert yap._api_key() == "fromkeyring"


class FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _json_resp(payload: dict) -> FakeResp:
    return FakeResp(json.dumps(payload).encode("utf-8"))


def _video(vid="v1", title="Test Video", views=10_000, likes=500, comments=50,
           duration="PT5M30S", channel="Chan", published="2024-01-01T00:00:00Z"):
    return {
        "id": vid,
        "snippet": {"title": title, "channelTitle": channel, "publishedAt": published},
        "statistics": {"viewCount": str(views), "likeCount": str(likes), "commentCount": str(comments)},
        "contentDetails": {"duration": duration},
    }


def _channel(uploads_playlist="UUxxxx"):
    return {
        "snippet": {"title": "My Channel"},
        "statistics": {},
        "contentDetails": {"relatedPlaylists": {"uploads": uploads_playlist}},
    }


# ── _parse_duration ────────────────────────────────────────────────────

def test_parse_duration_minutes_seconds():
    assert yap._parse_duration("PT5M30S") == "5:30"


def test_parse_duration_hours():
    assert yap._parse_duration("PT1H2M3S") == "1:02:03"


def test_parse_duration_seconds_only():
    assert yap._parse_duration("PT45S") == "0:45"


def test_parse_duration_invalid_returns_placeholder():
    assert yap._parse_duration("") == "؟"


# ── video_stats ───────────────────────────────────────────────────────

def test_video_stats_no_args(make_ctx):
    result = yap._cmd_video_stats(make_ctx("video_stats", []))
    assert result.startswith("usage")


def test_video_stats_no_key(make_ctx):
    result = yap._cmd_video_stats(make_ctx("video_stats", ["abc123"]))
    assert result.startswith("❌")
    assert "youtube_set_key" in result


def test_video_stats_real_data(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    monkeypatch.setattr(yap.urllib.request, "urlopen",
                         lambda req, timeout: _json_resp({"items": [_video(views=100_000, likes=5000, comments=200)]}))
    result = yap._cmd_video_stats(make_ctx("video_stats", ["abc123"]))
    assert "Test Video" in result
    assert "100,000" in result
    assert "5:30" in result


def test_video_stats_engagement_rate_computed(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    # (likes+comments)/views = (100+10)/1000 = 11%
    monkeypatch.setattr(yap.urllib.request, "urlopen",
                         lambda req, timeout: _json_resp({"items": [_video(views=1000, likes=100, comments=10)]}))
    result = yap._cmd_video_stats(make_ctx("video_stats", ["abc123"]))
    assert "11.00%" in result


def test_video_stats_not_found(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    monkeypatch.setattr(yap.urllib.request, "urlopen", lambda req, timeout: _json_resp({"items": []}))
    result = yap._cmd_video_stats(make_ctx("video_stats", ["nope"]))
    assert result.startswith("❌")


# ── channel_growth_report ────────────────────────────────────────────────

def test_growth_report_no_args(make_ctx):
    result = yap._cmd_channel_growth_report(make_ctx("channel_growth_report", []))
    assert result.startswith("usage")


def test_growth_report_no_key(make_ctx):
    result = yap._cmd_channel_growth_report(make_ctx("channel_growth_report", ["@x"]))
    assert result.startswith("❌")


def test_growth_report_channel_not_found(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    monkeypatch.setattr(yap.urllib.request, "urlopen", lambda req, timeout: _json_resp({"items": []}))
    result = yap._cmd_channel_growth_report(make_ctx("channel_growth_report", ["@nope"]))
    assert result.startswith("❌")


def test_growth_report_identifies_best_and_worst(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)

    def fake_urlopen(req, timeout):
        if "channels?" in req.full_url:
            return _json_resp({"items": [_channel()]})
        if "playlistItems?" in req.full_url:
            items = [{"contentDetails": {"videoId": f"v{i}"}} for i in range(4)]
            return _json_resp({"items": items})
        return _json_resp({"items": [
            _video(vid="v0", title="Worst", views=100),
            _video(vid="v1", title="Mid1", views=500),
            _video(vid="v2", title="Mid2", views=600),
            _video(vid="v3", title="Best", views=10_000),
        ]})

    monkeypatch.setattr(yap.urllib.request, "urlopen", fake_urlopen)
    result = yap._cmd_channel_growth_report(make_ctx("channel_growth_report", ["@x"]))
    assert "Best" in result
    assert "Worst" in result


def test_growth_report_trend_correct_despite_api_response_reordering(make_ctx, isolated_config, monkeypatch):
    """videos.list بمعرّفات متعددة (id=v1,v2,...) مش مضمون يحافظ على
    ترتيب الطلب في استجابته — لازم اتجاه النمو يتحسب صح من publishedAt
    الحقيقي حتى لو استجابة الـ API رجعت بترتيب معاكس/عشوائي تمامًا عن
    ترتيب playlistItems الأصلي."""
    _set_key(isolated_config)

    def fake_urlopen(req, timeout):
        if "channels?" in req.full_url:
            return _json_resp({"items": [_channel()]})
        if "playlistItems?" in req.full_url:
            items = [{"contentDetails": {"videoId": f"v{i}"}} for i in range(4)]
            return _json_resp({"items": items})
        # ترتيب استجابة videos.list هنا مقصود إنه مختلف عن ترتيب
        # الطلب — نمو حقيقي واضح بمرور الوقت (v0 الأقدم أقل views،
        # v3 الأحدث أكتر views) لكن مبعوت بترتيب مبعثر.
        return _json_resp({"items": [
            _video(vid="v2", views=800, published="2024-01-03T00:00:00Z"),
            _video(vid="v0", views=100, published="2024-01-01T00:00:00Z"),
            _video(vid="v3", views=1000, published="2024-01-04T00:00:00Z"),
            _video(vid="v1", views=300, published="2024-01-02T00:00:00Z"),
        ]})

    monkeypatch.setattr(yap.urllib.request, "urlopen", fake_urlopen)
    result = yap._cmd_channel_growth_report(make_ctx("channel_growth_report", ["@x"]))
    assert "📈 في تصاعد" in result


def test_growth_report_no_videos(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)

    def fake_urlopen(req, timeout):
        if "channels?" in req.full_url:
            return _json_resp({"items": [_channel()]})
        return _json_resp({"items": []})

    monkeypatch.setattr(yap.urllib.request, "urlopen", fake_urlopen)
    result = yap._cmd_channel_growth_report(make_ctx("channel_growth_report", ["@x"]))
    assert "مفيش فيديوهات" in result


# ── engagement_health_proxy ───────────────────────────────────────────────

def test_engagement_proxy_no_args(make_ctx):
    result = yap._cmd_engagement_health_proxy(make_ctx("engagement_health_proxy", []))
    assert result.startswith("usage")


def test_engagement_proxy_healthy_video(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    # like_ratio = 500/10000=5%, comment_ratio=50/10000=0.5% -> both high bands -> score 4
    published = "2024-01-01T00:00:00Z"
    monkeypatch.setattr(yap.urllib.request, "urlopen",
                         lambda req, timeout: _json_resp({"items": [_video(views=10_000, likes=500, comments=50, published=published)]}))
    result = yap._cmd_engagement_health_proxy(make_ctx("engagement_health_proxy", ["abc"]))
    assert "🟢 صحي" in result
    assert "retention" in result  # الملحوظة الصريحة موجودة


def test_engagement_proxy_weak_video(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    monkeypatch.setattr(yap.urllib.request, "urlopen",
                         lambda req, timeout: _json_resp({"items": [_video(views=100_000, likes=10, comments=0)]}))
    result = yap._cmd_engagement_health_proxy(make_ctx("engagement_health_proxy", ["abc"]))
    assert "🔴 ضعيف" in result


def test_engagement_proxy_not_found(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    monkeypatch.setattr(yap.urllib.request, "urlopen", lambda req, timeout: _json_resp({"items": []}))
    result = yap._cmd_engagement_health_proxy(make_ctx("engagement_health_proxy", ["nope"]))
    assert result.startswith("❌")


# ── report_export ─────────────────────────────────────────────────────

def test_report_export_needs_two_args(make_ctx):
    result = yap._cmd_report_export(make_ctx("report_export", ["@x"]))
    assert result.startswith("usage")


def test_report_export_no_key(make_ctx, tmp_path):
    result = yap._cmd_report_export(make_ctx("report_export", ["@x", str(tmp_path / "out.csv")]))
    assert result.startswith("❌")


def test_report_export_writes_real_csv(make_ctx, isolated_config, monkeypatch, tmp_path):
    _set_key(isolated_config)

    def fake_urlopen(req, timeout):
        if "channels?" in req.full_url:
            return _json_resp({"items": [_channel()]})
        if "playlistItems?" in req.full_url:
            return _json_resp({"items": [{"contentDetails": {"videoId": "v1"}}, {"contentDetails": {"videoId": "v2"}}]})
        return _json_resp({"items": [_video(vid="v1", title="A"), _video(vid="v2", title="B")]})

    monkeypatch.setattr(yap.urllib.request, "urlopen", fake_urlopen)
    out = tmp_path / "report.csv"
    result = yap._cmd_report_export(make_ctx("report_export", ["@x", str(out)]))
    assert result.startswith("✅")
    assert out.is_file()

    with out.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["video_id", "title", "published_at", "views", "likes", "comments", "duration"]
    assert len(rows) == 3  # header + 2 videos
    titles = [r[1] for r in rows[1:]]
    assert "A" in titles and "B" in titles


def test_report_export_no_videos(make_ctx, isolated_config, monkeypatch, tmp_path):
    _set_key(isolated_config)

    def fake_urlopen(req, timeout):
        if "channels?" in req.full_url:
            return _json_resp({"items": [_channel()]})
        return _json_resp({"items": []})

    monkeypatch.setattr(yap.urllib.request, "urlopen", fake_urlopen)
    result = yap._cmd_report_export(make_ctx("report_export", ["@x", str(tmp_path / "out.csv")]))
    assert result.startswith("❌")


# ── register ─────────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    yap.register(FakeEngine)
    for cmd in ("video_stats", "channel_growth_report", "engagement_health_proxy", "report_export"):
        assert cmd in FakeEngine.registry.names
