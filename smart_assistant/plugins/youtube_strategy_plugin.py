"""
youtube_strategy_plugin.py — مدير استراتيجية يوتيوب: بيانات حقيقية عن أي
قناة عبر YouTube Data API v3 (مجاني، محتاج مفتاح API مجاني من Google Cloud
Console — تسجيل مجاني بدون فلوس)، بالإضافة لتحليل استراتيجي (اتساق النشر،
كفاءة المشاهدات) وخطة تقويم نشر — من غير أي مفتاح، بيوضح ده صراحةً بدل
ما يورّي بيانات وهمية.

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

API_BASE = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 15
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_DAY_NAMES_AR = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


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
    path = _config_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    key = data.get("api_key")
    return key if key else None


def _yt_get(endpoint: str, params: dict) -> dict:
    """بيرجع dict لو الطلب نجح، أو يرمي YouTubeAPIError برسالة واضحة."""
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
        return "❌ مفتاح فاضي مش هيتحفظ"
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
        return f"❌ تعذر حفظ المفتاح: {e}"
    return "✅ اتحفظ مفتاح YouTube API. جرّب: channel_stats <channel_id_or_@handle>"


def _cmd_youtube_key_status(ctx) -> str:
    key = _api_key()
    if not key:
        return "❌ مفيش مفتاح متظبط — استخدم youtube_set_key <key>"
    masked = key[:4] + "…" + key[-2:] if len(key) > 8 else "…"
    return f"✅ فيه مفتاح متظبط ({masked}) — {_config_path()}"


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "؟"


def _cmd_channel_stats(ctx) -> str:
    if not ctx.args:
        return "usage: channel_stats <channel_id_or_@handle>"
    identifier = ctx.args[0]
    try:
        channel = _fetch_channel(identifier)
    except YouTubeAPIError as e:
        return f"❌ {e}"
    if channel is None:
        return f"❌ مفيش قناة بالمعرف/الاسم ده: {identifier}"

    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    subs = stats.get("subscriberCount")
    views = int(stats.get("viewCount", 0))
    videos = int(stats.get("videoCount", 0))
    avg_views = views / videos if videos else 0

    lines = [
        f"📺 {snippet.get('title', identifier)}",
        f"   👥 مشتركين: {_fmt_int(subs) if not stats.get('hiddenSubscriberCount') else 'مخفي'}",
        f"   👁 إجمالي مشاهدات: {_fmt_int(views)}",
        f"   🎬 عدد فيديوهات: {_fmt_int(videos)}",
        f"   📊 متوسط مشاهدات/فيديو: {_fmt_int(avg_views)}",
        f"   📅 اتعملت: {snippet.get('publishedAt', '؟')[:10]}",
    ]
    return "\n".join(lines)


def _cmd_channel_strategy_report(ctx) -> str:
    if not ctx.args:
        return "usage: channel_strategy_report <channel_id_or_@handle>"
    identifier = ctx.args[0]
    try:
        channel = _fetch_channel(identifier)
        if channel is None:
            return f"❌ مفيش قناة بالمعرف/الاسم ده: {identifier}"
        uploads = _recent_uploads(channel)
    except YouTubeAPIError as e:
        return f"❌ {e}"

    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    subs = int(stats.get("subscriberCount", 0) or 0)
    views = int(stats.get("viewCount", 0))
    videos = int(stats.get("videoCount", 0))

    lines = [f"📈 تقرير استراتيجية: {snippet.get('title', identifier)}"]

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
                consistency = "ممتاز — نشر منتظم جدًا"
            elif cv < 0.6:
                consistency = "كويس — فيه اتساق بس مش مثالي"
            else:
                consistency = "غير منتظم — الفجوات بين الفيديوهات متذبذبة"
            lines.append(f"   🗓 متوسط الفجوة بين الفيديوهات: {mean_gap:.1f} يوم — الاتساق: {consistency}")
        else:
            lines.append(f"   🗓 متوسط الفجوة بين الفيديوهات: {mean_gap:.1f} يوم")
    else:
        lines.append("   🗓 مش كفاية فيديوهات لتحليل اتساق النشر (محتاج 3 على الأقل)")

    # كفاءة الوصول: متوسط مشاهدات القناة مقسومة على عدد المشتركين — نسبة
    # أعلى من 1 معناها المحتوى بيوصل لناس أكتر من قاعدة المشتركين
    # (اكتشاف/بحث)، نسبة أقل بكتير معناها الاعتماد شبه كامل على المشتركين.
    if subs > 0 and videos > 0:
        avg_views = views / videos
        reach_ratio = avg_views / subs
        if reach_ratio >= 1.0:
            reach_desc = "قوي — بيوصل لناس أكتر من مجرد المشتركين (اكتشاف كويس)"
        elif reach_ratio >= 0.3:
            reach_desc = "متوسط — وصول محدود برّه قاعدة المشتركين"
        else:
            reach_desc = "ضعيف — الاعتماد شبه كامل على المشتركين الحاليين"
        lines.append(f"   🎯 نسبة الوصول (متوسط مشاهدات÷مشتركين): {reach_ratio:.2f} — {reach_desc}")

    created = snippet.get("publishedAt")
    if created:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
        if age_days > 0 and videos > 0:
            videos_per_month = videos / (age_days / 30)
            lines.append(f"   ⏱ معدل نشر تاريخي: ~{videos_per_month:.1f} فيديو/شهر منذ إنشاء القناة")

    lines.append("\n💡 توصيات:")
    if videos == 0:
        lines.append("   • القناة لسه من غير فيديوهات — مفيش بيانات نشاط تتحلل")
    else:
        if subs > 0 and views / max(videos, 1) / subs < 0.3:
            lines.append("   • ركّز على SEO/thumbnails عشان توصل لمشاهدين جداد برّه قاعدة مشتركينك")
        lines.append("   • حافظ على جدول نشر ثابت (استخدم content_calendar) — الاتساق بيبني الخوارزمية عليك")

    return "\n".join(lines)


def _cmd_content_calendar(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: content_calendar <videos_per_week 1-7> <weeks>"
    try:
        per_week = int(ctx.args[0])
        weeks = int(ctx.args[1])
    except ValueError:
        return "❌ لازم رقمين صحاح"
    if not (1 <= per_week <= 7):
        return "❌ عدد الفيديوهات أسبوعيًا لازم يكون بين 1 و7"
    if not (1 <= weeks <= 26):
        return "❌ عدد الأسابيع لازم يكون بين 1 و26"

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

    lines = [f"🗓 خطة نشر: {per_week} فيديو/أسبوع × {weeks} أسبوع = {per_week * weeks} فيديو"]
    for w in range(weeks):
        week_start = monday + timedelta(days=7 * w)
        lines.append(f"\n  أسبوع {w + 1} ({week_start.strftime('%Y-%m-%d')}):")
        for d in day_indices:
            day_date = week_start + timedelta(days=d)
            lines.append(f"    • {_DAY_NAMES_AR[d]} — {day_date.strftime('%Y-%m-%d')}")

    lines.append(
        "\n💡 ملحوظة: التوزيع ده متباعد بالتساوي عشان يفضل حضور ثابت "
        "طول الأسبوع بدل ما يتكدس. أفضل وقت نشر فعليًا بيختلف حسب "
        "جمهورك — راجع YouTube Studio Analytics بتاعتك (متاح مجانًا "
        "لأي صاحب قناة) لتضبط التوقيت بالساعة."
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
        return f"❌ مفيش قناة بالمعرف ده: {ctx.args[0]}"
    if b is None:
        return f"❌ مفيش قناة بالمعرف ده: {ctx.args[1]}"

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
            marker = f"◀ {name_a} أعلى"
        else:
            marker = f"{name_b} أعلى ▶"
        return f"   {label}: {fmt(va)}  مقابل  {fmt(vb)}   ({marker})"

    lines = [
        f"⚔️ مقارنة: {name_a}  مقابل  {name_b}",
        cmp_line("👥 مشتركين", subs_a, subs_b),
        cmp_line("👁 إجمالي مشاهدات", views_a, views_b),
        cmp_line("🎬 عدد فيديوهات", vids_a, vids_b),
        cmp_line("📊 متوسط مشاهدات/فيديو", avg_a, avg_b, lambda x: f"{x:,.0f}"),
    ]
    return "\n".join(lines)


def register(engine):
    engine.registry.register("youtube_set_key", _cmd_youtube_set_key,
                              "youtube_set_key <api_key> — تسجيل مفتاح YouTube Data API v3 (مجاني)")
    engine.registry.register("youtube_key_status", _cmd_youtube_key_status,
                              "youtube_key_status — هل فيه مفتاح YouTube API متظبط؟")
    engine.registry.register("channel_stats", _cmd_channel_stats,
                              "channel_stats <channel_id_or_@handle> — بيانات حقيقية عن قناة")
    engine.registry.register("channel_strategy_report", _cmd_channel_strategy_report,
                              "channel_strategy_report <channel_id_or_@handle> — تحليل اتساق النشر وكفاءة الوصول")
    engine.registry.register("content_calendar", _cmd_content_calendar,
                              "content_calendar <videos_per_week> <weeks> — خطة نشر بتواريخ حقيقية")
    engine.registry.register("competitor_compare", _cmd_competitor_compare,
                              "competitor_compare <channel_1> <channel_2> — مقارنة إحصائيات قناتين")
