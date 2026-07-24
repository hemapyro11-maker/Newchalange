"""
youtube_analytics_plugin.py — محلل بيانات يوتيوب: إحصائيات فيديو حقيقية،
تقرير نمو قناة (اتجاه مشاهدات، أفضل/أسوأ فيديو، معدل نشر)، مؤشر صحة
تفاعل تقريبي من بيانات عامة، وتصدير CSV — كله عبر YouTube Data API v3.

**مهم:** الـ retention (نسبة المشاهدة الفعلية) والـ CTR الحقيقيين
بيانات خاصة بصاحب القناة بس، متاحة عبر YouTube Analytics API بمصادقة
OAuth على حساب القناة نفسها — مش عبر مفتاح API عام زي ده. الأداة هنا
بتبني مؤشر تقريبي من بيانات عامة (مشاهدات/لايكات/تعليقات) بدل ما تدّعي
إنها بتجيب retention حقيقي مش قادرة عليه فعليًا.

الأوامر: video_stats, channel_growth_report, engagement_health_proxy,
report_export
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 15
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


class YouTubeAPIError(Exception):
    pass


def _config_dir() -> pathlib.Path:
    return pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent


def _api_key() -> str | None:
    path = _config_dir() / "youtube_config.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    key = data.get("api_key")
    return key if key else None


def _yt_get(endpoint: str, params: dict) -> dict:
    key = _api_key()
    if not key:
        raise YouTubeAPIError(
            "مفيش مفتاح YouTube API متظبط. هات واحد مجاني من "
            "https://console.cloud.google.com (فعّل YouTube Data API v3) "
            "وسجّله بـ: youtube_set_key <المفتاح>"
        )
    q = dict(params)
    q["key"] = key
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Nezuko/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", str(e))
        except json.JSONDecodeError:
            msg = str(e)
        raise YouTubeAPIError(f"HTTP {e.code} من يوتيوب: {msg}") from e
    except urllib.error.URLError as e:
        raise YouTubeAPIError(f"تعذر الوصول لـ YouTube API: {e.reason}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise YouTubeAPIError(f"رد غير متوقع من يوتيوب: {e}") from e


def _fetch_channel(identifier: str) -> dict | None:
    params = {"part": "snippet,statistics,contentDetails"}
    if _CHANNEL_ID_RE.match(identifier):
        params["id"] = identifier
    elif identifier.startswith("@"):
        params["forHandle"] = identifier
    else:
        params["forHandle"] = "@" + identifier
    data = _yt_get("channels", params)
    items = data.get("items", [])
    return items[0] if items else None


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "؟"


def _parse_duration(iso: str) -> str:
    m = _DURATION_RE.match(iso or "")
    if not m:
        return "؟"
    h, mnt, s = (int(x) if x else 0 for x in m.groups())
    total_min = h * 60 + mnt
    return f"{h}:{mnt:02d}:{s:02d}" if h else f"{total_min}:{s:02d}"


# ── video_stats ────────────────────────────────────────────────────────

def _cmd_video_stats(ctx) -> str:
    if not ctx.args:
        return "usage: video_stats <video_id>"
    video_id = ctx.args[0]
    try:
        data = _yt_get("videos", {"part": "snippet,statistics,contentDetails", "id": video_id})
    except YouTubeAPIError as e:
        return f"❌ {e}"
    items = data.get("items", [])
    if not items:
        return f"❌ مفيش فيديو بالمعرف ده: {video_id}"

    video = items[0]
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    views = int(stats.get("viewCount", 0) or 0)
    likes = int(stats.get("likeCount", 0) or 0)
    comments = int(stats.get("commentCount", 0) or 0)
    engagement = (likes + comments) / views * 100 if views else 0

    lines = [
        f"🎬 {snippet.get('title', video_id)}",
        f"   📺 {snippet.get('channelTitle', '؟')}  |  📅 {snippet.get('publishedAt', '؟')[:10]}",
        f"   ⏱ المدة: {_parse_duration(video.get('contentDetails', {}).get('duration', ''))}",
        f"   👁 مشاهدات: {_fmt_int(views)}   👍 لايكات: {_fmt_int(likes)}   💬 تعليقات: {_fmt_int(comments)}",
        f"   📊 معدل التفاعل (لايك+تعليق÷مشاهدة): {engagement:.2f}%",
    ]
    return "\n".join(lines)


# ── channel_growth_report ─────────────────────────────────────────────────

def _fetch_recent_video_stats(channel: dict, max_results: int = 15) -> list[dict]:
    uploads_playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads_playlist:
        return []
    playlist_data = _yt_get("playlistItems", {
        "part": "contentDetails,snippet", "playlistId": uploads_playlist,
        "maxResults": min(max_results, 50),
    })
    items = playlist_data.get("items", [])
    video_ids = [it["contentDetails"]["videoId"] for it in items if "videoId" in it.get("contentDetails", {})]
    if not video_ids:
        return []
    stats_data = _yt_get("videos", {"part": "snippet,statistics", "id": ",".join(video_ids)})
    return stats_data.get("items", [])


def _cmd_channel_growth_report(ctx) -> str:
    if not ctx.args:
        return "usage: channel_growth_report <channel_id_or_@handle>"
    identifier = ctx.args[0]
    try:
        channel = _fetch_channel(identifier)
        if channel is None:
            return f"❌ مفيش قناة بالمعرف/الاسم ده: {identifier}"
        videos = _fetch_recent_video_stats(channel)
    except YouTubeAPIError as e:
        return f"❌ {e}"

    name = channel.get("snippet", {}).get("title", identifier)
    if not videos:
        return f"📊 {name}: مفيش فيديوهات كفاية لتحليل النمو"

    def views_of(v):
        return int(v.get("statistics", {}).get("viewCount", 0) or 0)

    # ترتيب زمني (الأحدث أول) هو ترتيب playlistItems الطبيعي، فبنعكسه هنا
    # عشان "أول نص" يبقى فعليًا الأقدم و"تاني نص" الأحدث للمقارنة الاتجاهية.
    videos_chrono = list(reversed(videos))
    views_list = [views_of(v) for v in videos_chrono]
    avg_views = statistics.mean(views_list)
    best = max(videos_chrono, key=views_of)
    worst = min(videos_chrono, key=views_of)

    lines = [
        f"📊 تقرير نمو: {name}  ({len(videos_chrono)} فيديو تم تحليلهم)",
        f"\n   📈 متوسط المشاهدات: {_fmt_int(avg_views)}",
        f"   🏆 أفضل أداء: \"{best.get('snippet', {}).get('title', '؟')}\" — {_fmt_int(views_of(best))} مشاهدة",
        f"   📉 أضعف أداء: \"{worst.get('snippet', {}).get('title', '؟')}\" — {_fmt_int(views_of(worst))} مشاهدة",
    ]

    if len(views_list) >= 4:
        mid = len(views_list) // 2
        first_half_avg = statistics.mean(views_list[:mid])
        second_half_avg = statistics.mean(views_list[mid:])
        if first_half_avg > 0:
            trend_pct = (second_half_avg - first_half_avg) / first_half_avg * 100
            if trend_pct > 10:
                trend_desc = f"📈 في تصاعد ({trend_pct:+.0f}%)"
            elif trend_pct < -10:
                trend_desc = f"📉 في تراجع ({trend_pct:+.0f}%)"
            else:
                trend_desc = f"➡️ مستقر تقريبًا ({trend_pct:+.0f}%)"
            lines.append(f"   📐 اتجاه المشاهدات (أقدم نص مقابل أحدث نص من العينة): {trend_desc}")

    return "\n".join(lines)


# ── engagement_health_proxy ─────────────────────────────────────────────

def _cmd_engagement_health_proxy(ctx) -> str:
    if not ctx.args:
        return "usage: engagement_health_proxy <video_id>"
    video_id = ctx.args[0]
    try:
        data = _yt_get("videos", {"part": "snippet,statistics", "id": video_id})
    except YouTubeAPIError as e:
        return f"❌ {e}"
    items = data.get("items", [])
    if not items:
        return f"❌ مفيش فيديو بالمعرف ده: {video_id}"

    video = items[0]
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    views = int(stats.get("viewCount", 0) or 0)
    likes = int(stats.get("likeCount", 0) or 0)
    comments = int(stats.get("commentCount", 0) or 0)

    published = snippet.get("publishedAt")
    days_up = 1
    if published:
        days_up = max(1, (datetime.now(timezone.utc) - datetime.fromisoformat(published.replace("Z", "+00:00"))).days)

    like_ratio = likes / views * 100 if views else 0
    comment_ratio = comments / views * 100 if views else 0
    views_per_day = views / days_up

    score = 0
    if like_ratio >= 4:
        score += 2
    elif like_ratio >= 2:
        score += 1
    if comment_ratio >= 0.3:
        score += 2
    elif comment_ratio >= 0.1:
        score += 1

    verdict = "🟢 صحي" if score >= 3 else ("🟡 متوسط" if score >= 1 else "🔴 ضعيف")

    lines = [
        f"🩺 مؤشر صحة تفاعل تقريبي: \"{snippet.get('title', video_id)}\"",
        f"\n   👁 {_fmt_int(views)} مشاهدة على مدار {days_up} يوم (~{_fmt_int(views_per_day)}/يوم)",
        f"   👍 نسبة اللايك: {like_ratio:.2f}%   💬 نسبة التعليق: {comment_ratio:.2f}%",
        f"\n   {verdict}  ({score}/4)",
        (
            "\n⚠️ ده مؤشر تقريبي من بيانات عامة (مشاهدات/لايكات/تعليقات) — "
            "مش بيانات retention/CTR الحقيقية. البيانات دي متاحة بس لصاحب "
            "القناة عبر YouTube Analytics (studio.youtube.com) بحسابه الخاص."
        ),
    ]
    return "\n".join(lines)


# ── report_export ──────────────────────────────────────────────────────

def _cmd_report_export(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: report_export <channel_id_or_@handle> <out.csv>"
    identifier = ctx.args[0]
    out_path = pathlib.Path(ctx.args[1])
    try:
        channel = _fetch_channel(identifier)
        if channel is None:
            return f"❌ مفيش قناة بالمعرف/الاسم ده: {identifier}"
        videos = _fetch_recent_video_stats(channel, max_results=50)
    except YouTubeAPIError as e:
        return f"❌ {e}"

    if not videos:
        return "❌ مفيش فيديوهات نصدرها"

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["video_id", "title", "published_at", "views", "likes", "comments", "duration"])
            for v in videos:
                snippet = v.get("snippet", {})
                stats = v.get("statistics", {})
                writer.writerow([
                    v.get("id", ""), snippet.get("title", ""), snippet.get("publishedAt", ""),
                    stats.get("viewCount", 0), stats.get("likeCount", 0), stats.get("commentCount", 0),
                    _parse_duration(v.get("contentDetails", {}).get("duration", "")),
                ])
    except OSError as e:
        return f"❌ تعذر الكتابة: {e}"

    return f"✅ اتصدّر {len(videos)} فيديو في {out_path}"


def register(engine):
    engine.registry.register("video_stats", _cmd_video_stats,
                              "video_stats <video_id> — إحصائيات فيديو حقيقية (مشاهدات/لايك/تعليق/تفاعل)")
    engine.registry.register("channel_growth_report", _cmd_channel_growth_report,
                              "channel_growth_report <channel_id_or_@handle> — اتجاه مشاهدات وأفضل/أسوأ أداء")
    engine.registry.register("engagement_health_proxy", _cmd_engagement_health_proxy,
                              "engagement_health_proxy <video_id> — مؤشر صحة تفاعل تقريبي (مش retention حقيقي)")
    engine.registry.register("report_export", _cmd_report_export,
                              "report_export <channel_id_or_@handle> <out.csv> — تصدير إحصائيات فيديوهات القناة")
