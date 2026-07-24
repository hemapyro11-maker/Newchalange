"""
content_research_plugin.py — باحث المحتوى وكاتب السيناريو: بحث حقيقي في
يوتيوب (عبر YouTube Data API v3، محتاج مفتاح — راجع youtube_strategy_plugin)،
توليد أفكار كلمات مفتاحية بدون إنترنت، هيكلة سيناريو بتوقيتات فعلية مبنية
على مدة الفيديو، وتحليل قوة الهوك الافتتاحي.

الأوامر: youtube_search, trending_videos, keyword_ideas, script_outline,
hook_analyzer
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 15


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


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "؟"


# ── youtube_search ─────────────────────────────────────────────────────

def _cmd_youtube_search(ctx) -> str:
    if not ctx.args:
        return "usage: youtube_search <query> [max=10]"
    max_results = 10
    query_parts = []
    for arg in ctx.args:
        if arg.startswith("max="):
            try:
                max_results = int(arg[4:])
            except ValueError:
                return "❌ max لازم يكون رقم"
        else:
            query_parts.append(arg)
    query = " ".join(query_parts)
    if not query:
        return "usage: youtube_search <query> [max=10]"
    if not (1 <= max_results <= 25):
        return "❌ max لازم يكون بين 1 و25"

    try:
        search_data = _yt_get("search", {
            "part": "snippet", "q": query, "type": "video",
            "maxResults": max_results, "order": "relevance",
        })
        items = search_data.get("items", [])
        video_ids = [it["id"]["videoId"] for it in items if "videoId" in it.get("id", {})]
        stats_by_id = {}
        if video_ids:
            stats_data = _yt_get("videos", {"part": "statistics", "id": ",".join(video_ids)})
            stats_by_id = {v["id"]: v.get("statistics", {}) for v in stats_data.get("items", [])}
    except YouTubeAPIError as e:
        return f"❌ {e}"

    if not items:
        return f"🔍 مفيش نتائج لـ: {query}"

    lines = [f"🔍 نتائج البحث عن: {query} ({len(items)})"]
    for it in items:
        vid = it.get("id", {}).get("videoId", "")
        snippet = it.get("snippet", {})
        views = stats_by_id.get(vid, {}).get("viewCount")
        views_str = f" — 👁 {_fmt_int(views)}" if views is not None else ""
        lines.append(f"  🎬 {snippet.get('title', '؟')}")
        lines.append(f"     {snippet.get('channelTitle', '؟')}{views_str} — https://youtu.be/{vid}")
    return "\n".join(lines)


# ── trending_videos ─────────────────────────────────────────────────────

def _cmd_trending_videos(ctx) -> str:
    region = "EG"
    category = None
    max_results = 15
    for arg in ctx.args:
        if arg.startswith("region="):
            region = arg[7:].upper()
        elif arg.startswith("category="):
            category = arg[9:]
        elif arg.startswith("max="):
            try:
                max_results = int(arg[4:])
            except ValueError:
                return "❌ max لازم يكون رقم"
    if not (1 <= max_results <= 50):
        return "❌ max لازم يكون بين 1 و50"

    params = {
        "part": "snippet,statistics", "chart": "mostPopular",
        "regionCode": region, "maxResults": max_results,
    }
    if category:
        params["videoCategoryId"] = category
    try:
        data = _yt_get("videos", params)
    except YouTubeAPIError as e:
        return f"❌ {e}"

    items = data.get("items", [])
    if not items:
        return f"📈 مفيش فيديوهات ترند لمنطقة {region}"

    lines = [f"📈 الترند دلوقتي في {region} ({len(items)}):"]
    for i, it in enumerate(items, 1):
        snippet = it.get("snippet", {})
        stats = it.get("statistics", {})
        lines.append(f"  {i}. {snippet.get('title', '؟')} — {snippet.get('channelTitle', '؟')}")
        lines.append(f"     👁 {_fmt_int(stats.get('viewCount'))}  👍 {_fmt_int(stats.get('likeCount'))}")
    return "\n".join(lines)


# ── keyword_ideas (offline — مبني على قوالب نية بحث معروفة) ────────────

_KEYWORD_TEMPLATES_AR = [
    "ازاي {t}", "أفضل {t} 2025", "{t} للمبتدئين", "{t} خطوة بخطوة",
    "مراجعة {t}", "غلطات شائعة في {t}", "{t} مقابل", "كل حاجة عن {t}",
    "{t} من الصفر", "أسرار {t}", "تجربتي مع {t}", "هل {t} يستاهل؟",
]
_KEYWORD_TEMPLATES_EN = [
    "how to {t}", "best {t} 2025", "{t} for beginners", "{t} tutorial",
    "{t} review", "{t} mistakes to avoid", "{t} vs", "{t} explained",
    "{t} tips and tricks", "is {t} worth it",
]


def _cmd_keyword_ideas(ctx) -> str:
    if not ctx.args:
        return "usage: keyword_ideas <topic>"
    topic = " ".join(ctx.args)
    ar_ideas = [tpl.format(t=topic) for tpl in _KEYWORD_TEMPLATES_AR]
    en_ideas = [tpl.format(t=topic) for tpl in _KEYWORD_TEMPLATES_EN]

    lines = [f"💡 أفكار كلمات مفتاحية لـ: {topic}", "\n  عربي:"]
    lines += [f"   • {idea}" for idea in ar_ideas]
    lines.append("\n  English:")
    lines += [f"   • {idea}" for idea in en_ideas]
    lines.append(
        "\n💡 دي قوالب نية-بحث عامة (اللي المشاهدين بيكتبوها فعليًا في "
        "البحث). لو عندك مفتاح YouTube API، جرّب youtube_search على كل "
        "فكرة تشوف الحجم الفعلي للمنافسة عليها."
    )
    return "\n".join(lines)


# ── script_outline ──────────────────────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    m, s = divmod(max(0, round(seconds)), 60)
    return f"{m}:{s:02d}"


def _cmd_script_outline(ctx) -> str:
    if not ctx.args:
        return "usage: script_outline <topic> [duration_min=8]"
    duration_min = 8.0
    topic_parts = []
    for arg in ctx.args:
        if arg.startswith("duration_min="):
            try:
                duration_min = float(arg[13:])
            except ValueError:
                return "❌ duration_min لازم يكون رقم"
        else:
            topic_parts.append(arg)
    topic = " ".join(topic_parts)
    if not topic:
        return "usage: script_outline <topic> [duration_min=8]"
    if not (1 <= duration_min <= 120):
        return "❌ duration_min لازم يكون بين 1 و120 دقيقة"

    total = duration_min * 60
    # الهوك أول 15 ثانية دايمًا (بحث retention بيأكد إن أول 15 ثانية حرجة
    # بغض النظر عن مدة الفيديو الكلية)، مش نسبة من المدة.
    hook_end = min(15, total * 0.5)
    intro_end = hook_end + max(10, total * 0.05)
    outro_start = total - max(20, total * 0.08)
    main_duration = max(0, outro_start - intro_end)
    # كل سكشن حوالي 2.5 دقيقة (150ث) — رقم متوسط معقول لإبقاء كل نقطة
    # مركزة بدل ما تتوه في نقطة واحدة طويلة.
    n_segments = max(1, round(main_duration / 150)) if main_duration > 0 else 0
    segment_len = main_duration / n_segments if n_segments else 0

    lines = [
        f"📝 هيكل سيناريو: {topic} ({duration_min:.0f} دقيقة)",
        f"\n  [{_fmt_ts(0)}–{_fmt_ts(hook_end)}] 🪝 الهوك — سؤال/تصريح صادم يخلي حد يكمل بعد أول ثواني",
        f"  [{_fmt_ts(hook_end)}–{_fmt_ts(intro_end)}] 👋 مقدمة قصيرة — إيه اللي هيتعرفه المشاهد (من غير ترحيب طويل)",
    ]
    if n_segments:
        for i in range(n_segments):
            seg_start = intro_end + i * segment_len
            seg_end = seg_start + segment_len
            lines.append(f"  [{_fmt_ts(seg_start)}–{_fmt_ts(seg_end)}] 📌 نقطة {i + 1}/{n_segments}")
            if i == n_segments // 2:
                lines.append("       💬 (تذكير لطيف بالـ CTA هنا — نص الفيديو تقريبًا)")
    lines.append(f"  [{_fmt_ts(outro_start)}–{_fmt_ts(total)}] 🎬 خاتمة — ملخص سريع + CTA واضح (اشترك/فيديو تاني)")
    lines.append(
        "\n💡 استخدم hook_analyzer على نص الهوك اللي هتكتبه للثواني "
        f"الأولى ({_fmt_ts(hook_end)}) عشان تقيّم قوته قبل التصوير."
    )
    return "\n".join(lines)


# ── hook_analyzer ────────────────────────────────────────────────────────

_CURIOSITY_WORDS = [
    "سر", "أسرار", "غلط", "غلطة", "أبدا", "لازم", "مفاجأة", "حقيقة",
    "لن تصدق", "خطير", "ممنوع", "صدمة", "مستحيل", "أخيرا",
    "secret", "mistake", "never", "shocking", "truth", "worst", "best",
    "warning", "banned", "nobody tells you", "finally",
]
_GENERIC_OPENERS = [
    "مرحبا بكم", "أهلا وسهلا", "في الفيديو ده هنتكلم عن", "hi guys",
    "hey everyone", "welcome back", "في هذا الفيديو",
]


def _cmd_hook_analyzer(ctx) -> str:
    if not ctx.raw or len(ctx.raw.split(None, 1)) < 2:
        return "usage: hook_analyzer <hook text>"
    text = ctx.raw.split(None, 1)[1].strip()
    if not text:
        return "usage: hook_analyzer <hook text>"

    lower = text.lower()
    words = text.split()
    score = 50
    notes = []

    if len(words) <= 15:
        score += 15
        notes.append("✅ طول مناسب (قصير ومباشر)")
    elif len(words) <= 25:
        score += 5
        notes.append("⚠️ طويل شوية — حاول تقصّره لأقل من 15 كلمة لو ينفع")
    else:
        notes.append("❌ طويل جدًا لهوك — المشاهد بيقرر يكمل ولا لأ في ثواني")

    if "؟" in text or "?" in text:
        score += 10
        notes.append("✅ فيه سؤال — بيشغّل فضول المشاهد")

    if re.search(r"\d", text):
        score += 10
        notes.append("✅ فيه رقم — أرقام بتلفت الانتباه (زي \"5 غلطات\")")

    hit_curiosity = [w for w in _CURIOSITY_WORDS if w in lower]
    if hit_curiosity:
        score += 15
        notes.append(f"✅ فيه كلمة فضول/تباين: {', '.join(hit_curiosity[:3])}")

    hit_generic = [o for o in _GENERIC_OPENERS if lower.startswith(o.lower())]
    if hit_generic:
        score -= 25
        notes.append(f"❌ بيبدأ بمقدمة عامة معروفة (\"{hit_generic[0]}\") — ده بيضيّع ثواني حرجة")

    if any(p in lower[:20] for p in ("انت", "انتي", "you", "your")):
        score += 5
        notes.append("✅ خطاب مباشر للمشاهد بدري في النص")

    score = max(0, min(100, score))
    if score >= 75:
        verdict = "🔥 هوك قوي"
    elif score >= 50:
        verdict = "🙂 هوك متوسط — فيه مجال للتحسين"
    else:
        verdict = "⚠️ هوك ضعيف — يحتاج إعادة صياغة"

    lines = [f"🪝 تحليل الهوك: \"{text}\"", f"\n{verdict}  ({score}/100)", "\nالتفاصيل:"]
    lines += [f"  {n}" for n in notes] if notes else ["  (مفيش ملاحظات خاصة)"]
    return "\n".join(lines)


def register(engine):
    engine.registry.register("youtube_search", _cmd_youtube_search,
                              "youtube_search <query> [max=10] — بحث حقيقي في يوتيوب مع أرقام مشاهدات")
    engine.registry.register("trending_videos", _cmd_trending_videos,
                              "trending_videos [region=EG] [category=N] [max=15] — الترند الحقيقي دلوقتي")
    engine.registry.register("keyword_ideas", _cmd_keyword_ideas,
                              "keyword_ideas <topic> — قوالب نية-بحث عربي/إنجليزي")
    engine.registry.register("script_outline", _cmd_script_outline,
                              "script_outline <topic> [duration_min=8] — هيكل سيناريو بتوقيتات فعلية")
    engine.registry.register("hook_analyzer", _cmd_hook_analyzer,
                              "hook_analyzer <hook text> — تقييم قوة الهوك الافتتاحي /100")
