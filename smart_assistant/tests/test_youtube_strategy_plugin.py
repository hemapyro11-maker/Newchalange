import json

import pytest
import youtube_strategy_plugin as ysp


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """كل اختبار بيستخدم youtube_config.json خاص بيه، عشان محدش يلمس
    الملف الحقيقي بتاع المستخدم."""
    monkeypatch.setattr(ysp, "_config_dir", lambda: tmp_path)
    return tmp_path


class FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _json_urlopen(monkeypatch, payload: dict, capture: dict | None = None):
    def fake_urlopen(req, timeout):
        if capture is not None:
            capture["url"] = req.full_url
        return FakeResp(json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(ysp.urllib.request, "urlopen", fake_urlopen)


def _channel(title="Test Channel", subs=1000, views=100_000, videos=50,
             created="2020-01-01T00:00:00Z", uploads_playlist="UUxxxx"):
    return {
        "snippet": {"title": title, "publishedAt": created},
        "statistics": {"subscriberCount": str(subs), "viewCount": str(views), "videoCount": str(videos)},
        "contentDetails": {"relatedPlaylists": {"uploads": uploads_playlist}},
    }


# ── youtube_set_key / youtube_key_status ──────────────────────────────

def test_set_key_no_args(make_ctx):
    assert ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", [])).startswith("usage")


def test_set_key_empty_string(make_ctx):
    result = ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", [""]))
    assert result.startswith("❌")


def test_key_status_before_set(make_ctx):
    result = ysp._cmd_youtube_key_status(make_ctx("youtube_key_status", []))
    assert result.startswith("❌")


def test_set_key_then_status_round_trip(make_ctx, isolated_config):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["AIzaSyTESTKEY12345"]))
    assert ysp._api_key() == "AIzaSyTESTKEY12345"
    result = ysp._cmd_youtube_key_status(make_ctx("youtube_key_status", []))
    assert result.startswith("✅")
    assert "AIza" in result  # الأول مقصوص لكن ظاهر جزئيًا


def test_set_key_preserves_other_config_keys(make_ctx, isolated_config):
    (isolated_config / "youtube_config.json").write_text(
        json.dumps({"other_field": "keep_me"}), encoding="utf-8"
    )
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["newkey"]))
    data = json.loads((isolated_config / "youtube_config.json").read_text())
    assert data["other_field"] == "keep_me"
    assert data["api_key"] == "newkey"


# ── channel_stats ───────────────────────────────────────────────────────

def test_channel_stats_no_args(make_ctx):
    assert ysp._cmd_channel_stats(make_ctx("channel_stats", [])).startswith("usage")


def test_channel_stats_no_key_configured(make_ctx):
    result = ysp._cmd_channel_stats(make_ctx("channel_stats", ["@somechannel"]))
    assert result.startswith("❌")
    assert "youtube_set_key" in result


def test_channel_stats_real_data(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    _json_urlopen(monkeypatch, {"items": [_channel(title="MKBHD", subs=18_000_000, views=5_000_000_000, videos=1800)]})
    result = ysp._cmd_channel_stats(make_ctx("channel_stats", ["@mkbhd"]))
    assert "MKBHD" in result
    assert "18,000,000" in result
    assert "1,800" in result


def test_channel_stats_channel_not_found(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    _json_urlopen(monkeypatch, {"items": []})
    result = ysp._cmd_channel_stats(make_ctx("channel_stats", ["@nope_channel_xyz"]))
    assert result.startswith("❌")


def test_channel_stats_resolves_channel_id_vs_handle(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    captured = {}
    _json_urlopen(monkeypatch, {"items": [_channel()]}, captured)
    ysp._cmd_channel_stats(make_ctx("channel_stats", ["UC" + "x" * 22]))
    assert "id=UC" in captured["url"]

    ysp._cmd_channel_stats(make_ctx("channel_stats", ["@handle"]))
    assert "forHandle=%40handle" in captured["url"]

    ysp._cmd_channel_stats(make_ctx("channel_stats", ["barehandle"]))
    assert "forHandle=%40barehandle" in captured["url"]


def test_channel_stats_hidden_subscriber_count(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    ch = _channel()
    ch["statistics"]["hiddenSubscriberCount"] = True
    _json_urlopen(monkeypatch, {"items": [ch]})
    result = ysp._cmd_channel_stats(make_ctx("channel_stats", ["@x"]))
    assert "مخفي" in result


def test_channel_stats_http_error_reported_clearly(make_ctx, monkeypatch):
    import urllib.error

    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["badkey"]))

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            __import__("io").BytesIO(json.dumps({"error": {"message": "API key invalid"}}).encode()),
        )
    monkeypatch.setattr(ysp.urllib.request, "urlopen", fake_urlopen)
    result = ysp._cmd_channel_stats(make_ctx("channel_stats", ["@x"]))
    assert result.startswith("❌")
    assert "API key invalid" in result


# ── channel_strategy_report ────────────────────────────────────────────

def _playlist_items(gaps_days: list[float]):
    """بيبني sequence فيديوهات بفجوات زمنية معينة بينهم (بالأيام)، للاختبار."""
    from datetime import datetime, timedelta, timezone
    items = []
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    items.append({"contentDetails": {"videoPublishedAt": t.isoformat()}})
    for g in gaps_days:
        t = t + timedelta(days=g)
        items.append({"contentDetails": {"videoPublishedAt": t.isoformat()}})
    return items


def test_channel_strategy_report_no_args(make_ctx):
    assert ysp._cmd_channel_strategy_report(make_ctx("channel_strategy_report", [])).startswith("usage")


def test_channel_strategy_report_consistent_uploads(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if "channels?" in req.full_url:
            return FakeResp(json.dumps({"items": [_channel(subs=10_000, views=500_000, videos=50)]}).encode())
        return FakeResp(json.dumps({"items": _playlist_items([7.0, 7.0, 7.0, 7.0])}).encode())

    monkeypatch.setattr(ysp.urllib.request, "urlopen", fake_urlopen)
    result = ysp._cmd_channel_strategy_report(make_ctx("channel_strategy_report", ["@x"]))
    assert "ممتاز" in result
    assert calls["n"] == 2


def test_channel_strategy_report_inconsistent_uploads(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))

    def fake_urlopen(req, timeout):
        if "channels?" in req.full_url:
            return FakeResp(json.dumps({"items": [_channel(subs=10_000, views=500_000, videos=50)]}).encode())
        return FakeResp(json.dumps({"items": _playlist_items([1.0, 20.0, 2.0, 30.0])}).encode())

    monkeypatch.setattr(ysp.urllib.request, "urlopen", fake_urlopen)
    result = ysp._cmd_channel_strategy_report(make_ctx("channel_strategy_report", ["@x"]))
    assert "غير منتظم" in result


def test_channel_strategy_report_too_few_uploads_for_consistency(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))

    def fake_urlopen(req, timeout):
        if "channels?" in req.full_url:
            return FakeResp(json.dumps({"items": [_channel(videos=1)]}).encode())
        return FakeResp(json.dumps({"items": _playlist_items([])}).encode())

    monkeypatch.setattr(ysp.urllib.request, "urlopen", fake_urlopen)
    result = ysp._cmd_channel_strategy_report(make_ctx("channel_strategy_report", ["@x"]))
    assert "مش كفاية فيديوهات" in result


def test_channel_strategy_report_channel_not_found(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    _json_urlopen(monkeypatch, {"items": []})
    result = ysp._cmd_channel_strategy_report(make_ctx("channel_strategy_report", ["@nope"]))
    assert result.startswith("❌")


# ── content_calendar ────────────────────────────────────────────────────

def test_content_calendar_no_args(make_ctx):
    assert ysp._cmd_content_calendar(make_ctx("content_calendar", [])).startswith("usage")


def test_content_calendar_invalid_numbers(make_ctx):
    result = ysp._cmd_content_calendar(make_ctx("content_calendar", ["three", "2"]))
    assert result.startswith("❌")


def test_content_calendar_out_of_range_per_week(make_ctx):
    result = ysp._cmd_content_calendar(make_ctx("content_calendar", ["8", "2"]))
    assert result.startswith("❌")


def test_content_calendar_out_of_range_weeks(make_ctx):
    result = ysp._cmd_content_calendar(make_ctx("content_calendar", ["3", "0"]))
    assert result.startswith("❌")


def test_content_calendar_produces_correct_total_dates(make_ctx):
    result = ysp._cmd_content_calendar(make_ctx("content_calendar", ["3", "2"]))
    assert "6 فيديو" in result
    # 3 نقط (•) لكل أسبوع × أسبوعين = 6
    assert result.count("•") == 6


def test_content_calendar_single_video_per_week(make_ctx):
    result = ysp._cmd_content_calendar(make_ctx("content_calendar", ["1", "1"]))
    assert result.count("•") == 1


def test_content_calendar_seven_per_week_covers_all_days(make_ctx):
    result = ysp._cmd_content_calendar(make_ctx("content_calendar", ["7", "1"]))
    for day in ysp._DAY_NAMES_AR:
        assert day in result


# ── competitor_compare ──────────────────────────────────────────────────

def test_competitor_compare_needs_two_args(make_ctx):
    result = ysp._cmd_competitor_compare(make_ctx("competitor_compare", ["@only_one"]))
    assert result.startswith("usage")


def test_competitor_compare_real_data(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(json.dumps({"items": [_channel(title="Channel A", subs=1000, views=100_000, videos=100)]}).encode())
        return FakeResp(json.dumps({"items": [_channel(title="Channel B", subs=2000, views=50_000, videos=50)]}).encode())

    monkeypatch.setattr(ysp.urllib.request, "urlopen", fake_urlopen)
    result = ysp._cmd_competitor_compare(make_ctx("competitor_compare", ["@a", "@b"]))
    assert "Channel A" in result
    assert "Channel B" in result
    assert "1,000" in result
    assert "2,000" in result


def test_competitor_compare_first_channel_not_found(make_ctx, monkeypatch):
    ysp._cmd_youtube_set_key(make_ctx("youtube_set_key", ["fakekey"]))
    _json_urlopen(monkeypatch, {"items": []})
    result = ysp._cmd_competitor_compare(make_ctx("competitor_compare", ["@a", "@b"]))
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

    ysp.register(FakeEngine)
    for cmd in ("youtube_set_key", "youtube_key_status", "channel_stats",
                "channel_strategy_report", "content_calendar", "competitor_compare"):
        assert cmd in FakeEngine.registry.names
