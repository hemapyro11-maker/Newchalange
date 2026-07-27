"""
youtube_strategy_plugin.py — مدير استراتيجية يوتيوب: بيانات حقيقية عن أي
قناة عبر YouTube Data API v3 (مجاني، محتاج مفتاح API مجاني من Google Cloud
Console — تسجيل مجاني بدون فلوس)، بالإضافة لتحليل استراتيجي (اتساق النشر،
كفاءة المشاهدات) وخطة تقويم نشر — من غير أي مفتاح، بيوضح ده صراحةً بدل
ما يورّي بيانات وهمية.

**تخزين المفتاح بأمان (keyring):** المفتاح بيتحفظ في مخزن أسرار نظام
التشغيل عبر `keyring` بدل نص عادي في youtube_config.json، مع fallback
تلقائي لنص عادي لو keyring مش متاح — نفس نموذج telegram_plugin.py.

الأوامر: youtube_set_key, youtube_key_status, channel_stats,
channel_strategy_report, content_calendar, competitor_compare
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    import keyring
    from keyring.errors import KeyringError
    _HAS_KEYRING = True
except ImportError:
    keyring = None
    KeyringError = Exception
    _HAS_KEYRING = False

API_BASE = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 15
_KEYRING_SERVICE = "nezuko-youtube"
_API_KEY_NAME = "api_key"
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class YouTubeAPIError(Exception):
    pass


def _config_dir() -> pathlib.Path:
    # بـ PyInstaller (sys.frozen)، __file__ بيتفكك جوه مجلد استخراج مؤقت
    # مش جنب الـ exe الحقيقي — فلازم نستخدم sys.executable بدل كده.
    return pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent


def _config_path() -> pathlib.Path:
    return _config_dir() / "youtube_config.json"


def _api_key() -> str | None:
    if _HAS_KEYRING:
        try:
            key = keyring.get_password(_KEYRING_SERVICE, _API_KEY_NAME)
        except KeyringError:
            key = None
        if key:
            return key
    path = _config_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    key = data.get("api_key")
    return key if key else None


def _set_api_key_keyring(key: str) -> bool:
    """يحاول يحفظ المفتاح في keyring، يرجع True لو نجح، وبيمسح أي نسخة
    نص عادي قديمة كانت متسجلة لو نجح الحفظ الآمن."""
    if not _HAS_KEYRING:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, _API_KEY_NAME, key)
    except KeyringError:
        return False
    path = _config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if data and data.get("api_key"):
            data["api_key"] = None
            try:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
    return True


def _yt_get(endpoint: str, params: dict) -> dict:
    """بيرجع dict لو الطلب نجح، أو يرمي YouTubeAPIError برسالة واضحة."""
    key = _api_key()
    if not key:
        raise YouTubeAPIError(
            "No YouTube API key configured. Get one free at "
            "https://console.cloud.google.com (enable YouTube Data API v3) "
            "then save it with: youtube_set_key <key>"
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
        raise YouTubeAPIError(f"HTTP {e.code} from YouTube: {msg}") from e
    except urllib.error.URLError as e:
        raise YouTubeAPIError(f"could not reach the YouTube API: {e.reason}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise YouTubeAPIError(f"unexpected response from YouTube: {e}") from e


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


def _recent_uploads(channel: dict, max_results: int = 15) -> list[dict]:
    uploads_playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads_playlist:
        return []
    data = _yt_get("playlistItems", {
        "part": "contentDetails,snippet",
        "playlistId": uploads_playlist,
        "maxResults": min(max_results, 50),
    })
    return data.get("items", [])


def _cmd_youtube_set_key(ctx) -> str:
    if not ctx.args:
        return "usage: youtube_set_key <api_key>"
    key = ctx.args[0].strip()
    if not key:
        return "❌ an empty key will not be saved"
    if _set_api_key_keyring(key):
        return (
            "✅ YouTube API key saved safely in the operating system secret store (keyring).\n"
            "Try: channel_stats <channel_id_or_@handle>"
        )
    path = _config_path()
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["api_key"] = key
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        return f"❌ could not save the key: {e}"
    return (
        "⚠️ Key saved as plain text in youtube_config.json — secure keyring storage is not available here.\n"
        "   For safer storage: pip install keyring\n"
        "Try: channel_stats <channel_id_or_@handle>"
    )


def _cmd_youtube_key_status(ctx) -> str:
    key = _api_key()
    if not key:
        return "❌ no key configured — use youtube_set_key <key>"
    masked = key[:4] + "…" + key[-2:] if len(key) > 8 else "…"
    line = f"✅ a key is configured ({masked})"
    if not _HAS_KEYRING:
        line += "\n⚠️ keyring is not installed — stored as plain text (pip install keyring for safer storage)"
    return line


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "?"


def _cmd_channel_stats(ctx) -> str:
    if not ctx.args:
        return "usage: channel_stats <channel_id_or_@handle>"
    identifier = ctx.args[0]
    try:
        channel = _fetch_channel(identifier)
    except YouTubeAPIError as e:
        return f"❌ {e}"
    if channel is None:
        return f"❌ no channel with that id or name: {identifier}"

    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    subs = stats.get("subscriberCount")
    views = int(stats.get("viewCount", 0))
    videos = int(stats.get("videoCount", 0))
    avg_views = views / videos if videos else 0

    lines = [
        f"📺 {snippet.get('title', identifier)}",
        f"   👥 subscribers: {_fmt_int(subs) if not stats.get('hiddenSubscriberCount') else 'hidden'}",
        f"   👁 total views: {_fmt_int(views)}",
        f"   🎬 videos: {_fmt_int(videos)}",
        f"   📊 average views per video: {_fmt_int(avg_views)}",
        f"   📅 created: {snippet.get('publishedAt', '?')[:10]}",
    ]
    return "\n".join(lines)


def _cmd_channel_strategy_report(ctx) -> str:
    if not ctx.args:
        return "usage: channel_strategy_report <channel_id_or_@handle>"
    identifier = ctx.args[0]
    try:
        channel = _fetch_channel(identifier)
        if channel is None:
            return f"❌ no channel with that id or name: {identifier}"
        uploads = _recent_uploads(channel)
    except YouTubeAPIError as e:
        return f"❌ {e}"

    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    subs = int(stats.get("subscriberCount", 0) or 0)
    views = int(stats.get("viewCount", 0))
    videos = int(stats.get("videoCount", 0))

    lines = [f"📈 Strategy report: {snippet.get('title', identifier)}"]

    # اتساق النشر: بنحسب الفجوات بين تواريخ آخر الفيديوهات، ومعامل التباين
    # (coefficient of variation = الانحراف المعياري ÷ المتوسط) عشان نقيس
    # الاتساق بمعزل عن معدل النشر نفسه (قناة تنشر كل يوم بانتظام لازم
    # تاخد نفس تقييم قناة تنشر كل أسبوع بانتظام).
    if len(uploads) >= 3:
        dates = sorted(
            datetime.fromisoformat(u["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))
            for u in uploads
        )
        gaps_days = [(dates[i + 1] - dates[i]).total_seconds() / 86400 for i in range(len(dates) - 1)]
        mean_gap = statistics.mean(gaps_days)
        if mean_gap > 0 and len(gaps_days) >= 2:
            cv = statistics.stdev(gaps_days) / mean_gap
            if cv < 0.3:
                consistency = "excellent — very regular publishing"
            elif cv < 0.6:
                consistency = "good — consistent, though not perfectly so"
            else:
                consistency = "irregular — the gaps between videos swing about"
            lines.append(f"   🗓 average gap between videos: {mean_gap:.1f} days — consistency: {consistency}")
        else:
            lines.append(f"   🗓 average gap between videos: {mean_gap:.1f} days")
    else:
        lines.append("   🗓 not enough videos to judge publishing consistency (needs at least 3)")

    # كفاءة الوصول: متوسط مشاهدات القناة مقسومة على عدد المشتركين — نسبة
    # أعلى من 1 معناها المحتوى بيوصل لناس أكتر من قاعدة المشتركين
    # (اكتشاف/بحث)، نسبة أقل بكتير معناها الاعتماد شبه كامل على المشتركين.
    if subs > 0 and videos > 0:
        avg_views = views / videos
        reach_ratio = avg_views / subs
        if reach_ratio >= 1.0:
            reach_desc = "strong — reaching well beyond subscribers (good discovery)"
        elif reach_ratio >= 0.3:
            reach_desc = "middling — limited reach outside the subscriber base"
        else:
            reach_desc = "weak — almost entirely dependent on existing subscribers"
        lines.append(f"   🎯 reach ratio (average views ÷ subscribers): {reach_ratio:.2f} — {reach_desc}")

    created = snippet.get("publishedAt")
    if created:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
        if age_days > 0 and videos > 0:
            videos_per_month = videos / (age_days / 30)
            lines.append(f"   ⏱ historic publishing rate: ~{videos_per_month:.1f} videos/month since the channel started")

    lines.append("\n💡 Recommendations:")
    if videos == 0:
        lines.append("   • the channel has no videos yet — there is no activity to analyse")
    else:
        if subs > 0 and views / max(videos, 1) / subs < 0.3:
            lines.append("   • focus on SEO and thumbnails to reach viewers beyond your subscriber base")
        lines.append("   • keep a steady publishing schedule (use content_calendar) — consistency is what the algorithm builds on")

    return "\n".join(lines)


def _cmd_content_calendar(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: content_calendar <videos_per_week 1-7> <weeks>"
    try:
        per_week = int(ctx.args[0])
        weeks = int(ctx.args[1])
    except ValueError:
        return "❌ two whole numbers are required"
    if not (1 <= per_week <= 7):
        return "❌ videos per week must be between 1 and 7"
    if not (1 <= weeks <= 26):
        return "❌ the number of weeks must be between 1 and 26"

    # توزيع متساوي عبر أيام الأسبوع: بنستخدم round(i * 7 / n) عشان الأيام
    # تتباعد بأقصى قدر ممكن بدل ما تتكدس (زي توزيع الـ 3/أسبوع على
    # الإثنين/الأربعاء/الجمعة بدل الإثنين/الثلاثاء/الأربعاء).
    day_indices = sorted({round(i * 7 / per_week) % 7 for i in range(per_week)})
    while len(day_indices) < per_week:  # لو التقريب كرر يوم، كمّل بأقرب يوم فاضي
        for d in range(7):
            if d not in day_indices:
                day_indices.append(d)
                break
        day_indices = sorted(set(day_indices))

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())

    lines = [f"🗓 Publishing plan: {per_week} videos/week × {weeks} weeks = {per_week * weeks} videos"]
    for w in range(weeks):
        week_start = monday + timedelta(days=7 * w)
        lines.append(f"\n  Week {w + 1} ({week_start.strftime('%Y-%m-%d')}):")
        for d in day_indices:
            day_date = week_start + timedelta(days=d)
            lines.append(f"    • {_DAY_NAMES[d]} — {day_date.strftime('%Y-%m-%d')}")

    lines.append(
        "\n💡 Note: this spacing is even, to keep a steady presence "
        "through the week rather than bunching up. The genuinely best time to publish depends on "
        "your own audience — check your YouTube Studio Analytics (free to "
        "any channel owner) to tune the hour."
    )
    return "\n".join(lines)


def _cmd_competitor_compare(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: competitor_compare <channel_1> <channel_2>"
    try:
        a = _fetch_channel(ctx.args[0])
        b = _fetch_channel(ctx.args[1])
    except YouTubeAPIError as e:
        return f"❌ {e}"
    if a is None:
        return f"❌ no channel with that id or name: {ctx.args[0]}"
    if b is None:
        return f"❌ no channel with that id or name: {ctx.args[1]}"

    def stat(ch, key):
        return int(ch.get("statistics", {}).get(key, 0) or 0)

    name_a = a.get("snippet", {}).get("title", ctx.args[0])
    name_b = b.get("snippet", {}).get("title", ctx.args[1])
    subs_a, subs_b = stat(a, "subscriberCount"), stat(b, "subscriberCount")
    views_a, views_b = stat(a, "viewCount"), stat(b, "viewCount")
    vids_a, vids_b = stat(a, "videoCount"), stat(b, "videoCount")
    avg_a = views_a / vids_a if vids_a else 0
    avg_b = views_b / vids_b if vids_b else 0

    def cmp_line(label, va, vb, fmt=_fmt_int):
        if va == vb:
            marker = "="
        elif va > vb:
            marker = f"◀ {name_a} higher"
        else:
            marker = f"{name_b} higher ▶"
        return f"   {label}: {fmt(va)}  vs  {fmt(vb)}   ({marker})"

    lines = [
        f"⚔️ Comparison: {name_a}  vs  {name_b}",
        cmp_line("👥 subscribers", subs_a, subs_b),
        cmp_line("👁 total views", views_a, views_b),
        cmp_line("🎬 videos", vids_a, vids_b),
        cmp_line("📊 average views per video", avg_a, avg_b, lambda x: f"{x:,.0f}"),
    ]
    return "\n".join(lines)


def register(engine):
    engine.registry.register("youtube_set_key", _cmd_youtube_set_key,
                              "youtube_set_key <api_key> — save a free YouTube Data API v3 key")
    engine.registry.register("youtube_key_status", _cmd_youtube_key_status,
                              "youtube_key_status — is a YouTube API key configured?")
    engine.registry.register("channel_stats", _cmd_channel_stats,
                              "channel_stats <channel_id_or_@handle> — real data about a channel")
    engine.registry.register("channel_strategy_report", _cmd_channel_strategy_report,
                              "channel_strategy_report <channel_id_or_@handle> — publishing consistency and reach efficiency")
    engine.registry.register("content_calendar", _cmd_content_calendar,
                              "content_calendar <videos_per_week> <weeks> — a publishing plan with real dates")
    engine.registry.register("competitor_compare", _cmd_competitor_compare,
                              "competitor_compare <channel_1> <channel_2> — compare two channels statistics")
