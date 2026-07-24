import json

import content_research_plugin as crp
import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(crp, "_config_dir", lambda: tmp_path)
    return tmp_path


def _set_key(tmp_path, key="fakekey"):
    (tmp_path / "youtube_config.json").write_text(json.dumps({"api_key": key}), encoding="utf-8")


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


# ── youtube_search ──────────────────────────────────────────────────────

def test_youtube_search_no_args(make_ctx):
    assert crp._cmd_youtube_search(make_ctx("youtube_search", [])).startswith("usage")


def test_youtube_search_no_key(make_ctx):
    result = crp._cmd_youtube_search(make_ctx("youtube_search", ["cats"]))
    assert result.startswith("❌")
    assert "youtube_set_key" in result


def test_youtube_search_invalid_max(make_ctx, isolated_config):
    _set_key(isolated_config)
    result = crp._cmd_youtube_search(make_ctx("youtube_search", ["cats", "max=abc"]))
    assert result.startswith("❌")


def test_youtube_search_max_out_of_range(make_ctx, isolated_config):
    _set_key(isolated_config)
    result = crp._cmd_youtube_search(make_ctx("youtube_search", ["cats", "max=99"]))
    assert result.startswith("❌")


def test_youtube_search_real_data_with_view_counts(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if "search?" in req.full_url:
            return _json_resp({"items": [
                {"id": {"videoId": "abc123"}, "snippet": {"title": "Cat video", "channelTitle": "CatChan"}},
            ]})
        return _json_resp({"items": [{"id": "abc123", "statistics": {"viewCount": "5000"}}]})

    monkeypatch.setattr(crp.urllib.request, "urlopen", fake_urlopen)
    result = crp._cmd_youtube_search(make_ctx("youtube_search", ["cats"]))
    assert "Cat video" in result
    assert "5,000" in result
    assert "abc123" in result
    assert calls["n"] == 2


def test_youtube_search_no_results(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    monkeypatch.setattr(crp.urllib.request, "urlopen", lambda req, timeout: _json_resp({"items": []}))
    result = crp._cmd_youtube_search(make_ctx("youtube_search", ["zzzznonexistent"]))
    assert "مفيش نتائج" in result


def test_youtube_search_query_with_multiple_words_and_max(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return _json_resp({"items": []})

    monkeypatch.setattr(crp.urllib.request, "urlopen", fake_urlopen)
    crp._cmd_youtube_search(make_ctx("youtube_search", ["best", "cat", "videos", "max=5"]))
    assert "best+cat+videos" in captured["url"] or "best%20cat%20videos" in captured["url"]
    assert "maxResults=5" in captured["url"]


# ── trending_videos ──────────────────────────────────────────────────────

def test_trending_videos_no_key(make_ctx):
    result = crp._cmd_trending_videos(make_ctx("trending_videos", []))
    assert result.startswith("❌")


def test_trending_videos_default_region(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return _json_resp({"items": [
            {"snippet": {"title": "Trend 1", "channelTitle": "X"}, "statistics": {"viewCount": "1000", "likeCount": "50"}},
        ]})

    monkeypatch.setattr(crp.urllib.request, "urlopen", fake_urlopen)
    result = crp._cmd_trending_videos(make_ctx("trending_videos", []))
    assert "regionCode=EG" in captured["url"]
    assert "Trend 1" in result
    assert "1,000" in result


def test_trending_videos_custom_region_and_category(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return _json_resp({"items": []})

    monkeypatch.setattr(crp.urllib.request, "urlopen", fake_urlopen)
    crp._cmd_trending_videos(make_ctx("trending_videos", ["region=us", "category=10", "max=5"]))
    assert "regionCode=US" in captured["url"]
    assert "videoCategoryId=10" in captured["url"]
    assert "maxResults=5" in captured["url"]


def test_trending_videos_invalid_max(make_ctx, isolated_config):
    _set_key(isolated_config)
    result = crp._cmd_trending_videos(make_ctx("trending_videos", ["max=nope"]))
    assert result.startswith("❌")


def test_trending_videos_max_out_of_range(make_ctx, isolated_config):
    _set_key(isolated_config)
    result = crp._cmd_trending_videos(make_ctx("trending_videos", ["max=0"]))
    assert result.startswith("❌")


def test_trending_videos_no_results(make_ctx, isolated_config, monkeypatch):
    _set_key(isolated_config)
    monkeypatch.setattr(crp.urllib.request, "urlopen", lambda req, timeout: _json_resp({"items": []}))
    result = crp._cmd_trending_videos(make_ctx("trending_videos", []))
    assert "مفيش فيديوهات ترند" in result


# ── keyword_ideas ────────────────────────────────────────────────────────

def test_keyword_ideas_no_args(make_ctx):
    assert crp._cmd_keyword_ideas(make_ctx("keyword_ideas", [])).startswith("usage")


def test_keyword_ideas_generates_ar_and_en_templates(make_ctx):
    result = crp._cmd_keyword_ideas(make_ctx("keyword_ideas", ["فوتوشوب"]))
    assert "ازاي فوتوشوب" in result
    assert "how to فوتوشوب" in result
    assert "أفضل فوتوشوب 2025" in result
    assert "فوتوشوب tutorial" in result


def test_keyword_ideas_multi_word_topic(make_ctx):
    result = crp._cmd_keyword_ideas(make_ctx("keyword_ideas", ["تعلم", "بايثون"]))
    assert "تعلم بايثون" in result


# ── script_outline ───────────────────────────────────────────────────────

def test_script_outline_no_args(make_ctx):
    assert crp._cmd_script_outline(make_ctx("script_outline", [])).startswith("usage")


def test_script_outline_invalid_duration(make_ctx):
    result = crp._cmd_script_outline(make_ctx("script_outline", ["topic", "duration_min=abc"]))
    assert result.startswith("❌")


def test_script_outline_duration_out_of_range(make_ctx):
    result = crp._cmd_script_outline(make_ctx("script_outline", ["topic", "duration_min=0"]))
    assert result.startswith("❌")
    result2 = crp._cmd_script_outline(make_ctx("script_outline", ["topic", "duration_min=200"]))
    assert result2.startswith("❌")


def test_script_outline_default_duration_has_hook_and_outro(make_ctx):
    result = crp._cmd_script_outline(make_ctx("script_outline", ["فوتوشوب"]))
    assert "🪝 الهوك" in result
    assert "🎬 خاتمة" in result
    assert "[0:00" in result


def test_script_outline_longer_video_has_more_segments(make_ctx):
    short = crp._cmd_script_outline(make_ctx("script_outline", ["t", "duration_min=3"]))
    long = crp._cmd_script_outline(make_ctx("script_outline", ["t", "duration_min=30"]))
    assert long.count("📌 نقطة") > short.count("📌 نقطة")


def test_script_outline_timestamps_end_at_total_duration(make_ctx):
    result = crp._cmd_script_outline(make_ctx("script_outline", ["t", "duration_min=5"]))
    assert "5:00" in result  # آخر توقيت لازم يوصل لنهاية المدة


# ── hook_analyzer ────────────────────────────────────────────────────────

def test_hook_analyzer_no_text(make_ctx):
    result = crp._cmd_hook_analyzer(make_ctx("hook_analyzer", []))
    assert result.startswith("usage")


def test_hook_analyzer_strong_hook_scores_high(make_ctx):
    result = crp._cmd_hook_analyzer(make_ctx("hook_analyzer 5 أسرار محدش قالهالك قبل كده؟", []))
    assert "🔥" in result or "🙂" in result


def test_hook_analyzer_generic_opener_penalized(make_ctx):
    result = crp._cmd_hook_analyzer(
        make_ctx("hook_analyzer مرحبا بكم في الفيديو ده هنتكلم عن حاجة عادية جدا من غير اي اثارة او حاجة مثيرة للاهتمام خالص", [])
    )
    assert "⚠️" in result or "❌" in result


def test_hook_analyzer_question_detected(make_ctx):
    result = crp._cmd_hook_analyzer(make_ctx("hook_analyzer عايز تعرف السر؟", []))
    assert "فيه سؤال" in result


def test_hook_analyzer_number_detected(make_ctx):
    result = crp._cmd_hook_analyzer(make_ctx("hook_analyzer 7 حاجات محدش بيقولهالك", []))
    assert "فيه رقم" in result


def test_hook_analyzer_score_in_valid_range(make_ctx):
    result = crp._cmd_hook_analyzer(make_ctx("hook_analyzer test", []))
    import re
    m = re.search(r"\((\d+)/100\)", result)
    assert m
    assert 0 <= int(m.group(1)) <= 100


# ── register ─────────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    crp.register(FakeEngine)
    for cmd in ("youtube_search", "trending_videos", "keyword_ideas", "script_outline", "hook_analyzer"):
        assert cmd in FakeEngine.registry.names
