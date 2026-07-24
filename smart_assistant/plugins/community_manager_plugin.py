"""
community_manager_plugin.py — مدير التواصل والمجتمع: تحليل مشاعر تعليقات
حقيقي (قاموس عربي مصري + إنجليزي، مع التعامل مع النفي زي "مش حلو")،
كشف سبام هيكلي (روابط، عبارات ترويجية معروفة، تكرار حروف)، توليد ردود
مقترحة حسب نوع التعليق ونبرة الرد، وخطة نشر مجتمعي أسبوعية.

الأوامر: comment_sentiment, comment_spam_detect, reply_template,
engagement_calendar
"""
from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta

_DAY_NAMES_AR = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

# ── قاموس المشاعر ─────────────────────────────────────────────────────────

_POSITIVE_WORDS = {
    "حلو", "جميل", "رائع", "تحفة", "جامد", "احسنت", "أحسنت", "شكرا", "شكرًا",
    "ممتاز", "عاش", "برافو", "مفيد", "استفدت", "تسلم", "تسلملي", "روعة",
    "عظيم", "مبدع", "الله", "نايس", "كويس", "افضل", "أفضل", "يجننن",
    "great", "love", "amazing", "awesome", "best", "nice", "helpful",
    "thanks", "thank", "good", "excellent", "perfect", "wonderful", "cool",
}
_NEGATIVE_WORDS = {
    "وحش", "سيء", "سيئ", "زبالة", "فاشل", "مقرف", "غبي", "حرامي", "نصاب",
    "كذاب", "تقليد", "ضايع", "زفت", "تعبان", "بايظ", "وسخ", "مخيب",
    "bad", "worst", "hate", "terrible", "awful", "scam", "fake", "waste",
    "boring", "sucks", "garbage", "stupid", "trash", "horrible",
}
_NEGATIONS = {"مش", "مو", "لا", "مافيش", "no", "not", "never", "don't", "isn't"}
_POSITIVE_EMOJI = {"😂", "❤️", "👍", "🔥", "💯", "✨", "🙌", "😍", "👏"}
_NEGATIVE_EMOJI = {"👎", "😡", "🤮", "💩", "😠", "😢"}

_WORD_RE = re.compile(r"[\w']+|[😂❤️👍🔥💯✨🙌😍👏👎😡🤮💩😠😢]", re.UNICODE)


def _sentiment_of_line(text: str) -> tuple[str, int]:
    tokens = _WORD_RE.findall(text.lower())
    score = 0
    negate_next = False
    for tok in tokens:
        if tok in _NEGATIONS:
            negate_next = True
            continue
        polarity = 0
        if tok in _POSITIVE_WORDS or tok in _POSITIVE_EMOJI:
            polarity = 1
        elif tok in _NEGATIVE_WORDS or tok in _NEGATIVE_EMOJI:
            polarity = -1
        if polarity:
            score += -polarity if negate_next else polarity
        negate_next = False
    if score > 0:
        return "positive", score
    if score < 0:
        return "negative", score
    return "neutral", score


def _read_lines(ctx) -> list[str] | None:
    if len(ctx.args) == 1 and pathlib.Path(ctx.args[0]).is_file():
        try:
            text = pathlib.Path(ctx.args[0]).read_text(encoding="utf-8")
        except OSError:
            return None
        return [ln for ln in text.splitlines() if ln.strip()]
    parts = ctx.raw.split(None, 1)
    if len(parts) < 2:
        return None
    return [parts[1].strip()]


def _cmd_comment_sentiment(ctx) -> str:
    lines = _read_lines(ctx)
    if not lines:
        return "usage: comment_sentiment <comment text OR path to .txt file (سطر لكل تعليق)>"

    results = [(ln, *_sentiment_of_line(ln)) for ln in lines]
    pos = [r for r in results if r[1] == "positive"]
    neg = [r for r in results if r[1] == "negative"]
    neu = [r for r in results if r[1] == "neutral"]

    if len(lines) == 1:
        text, label, score = results[0]
        icon = {"positive": "😊", "negative": "😞", "neutral": "😐"}[label]
        return f"{icon} المشاعر: {label} (score={score})\n\"{text}\""

    total = len(results)
    lines_out = [
        f"💬 تحليل مشاعر {total} تعليق:",
        f"   😊 إيجابي: {len(pos)} ({len(pos) / total * 100:.0f}%)",
        f"   😐 محايد: {len(neu)} ({len(neu) / total * 100:.0f}%)",
        f"   😞 سلبي: {len(neg)} ({len(neg) / total * 100:.0f}%)",
    ]
    if neg:
        lines_out.append("\n⚠️ تعليقات سلبية تستاهل مراجعة:")
        for text, _, score in sorted(neg, key=lambda r: r[2])[:5]:
            lines_out.append(f"   • {text}")
    return "\n".join(lines_out)


# ── comment_spam_detect ───────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_REPEATED_CHAR_RE = re.compile(r"(.)\1{4,}")
_SPAM_PHRASES = [
    "دخل قناتي", "اشترك في قناتي", "check my channel", "subscribe to my channel",
    "click here", "free followers", "earn money", "لايك ع الفيديو دا وهرجعلك",
    "تابعني وهتابعك", "sub4sub", "follow for follow", "دخول فوري", "ربح سريع",
]
_PHONE_RE = re.compile(r"\b\d{10,}\b|\+\d{8,}")


def _spam_score(text: str) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    low = text.lower()

    if _URL_RE.search(text):
        score += 2
        reasons.append("فيه رابط")

    hit_phrases = [p for p in _SPAM_PHRASES if p in low]
    if hit_phrases:
        score += 2
        reasons.append(f"عبارة ترويجية معروفة: \"{hit_phrases[0]}\"")

    if _PHONE_RE.search(text):
        score += 1
        reasons.append("فيه رقم يشبه رقم تليفون/واتساب")

    letters = [c for c in text if c.isalpha()]
    if letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio > 0.7 and len(letters) > 10:
            score += 1
            reasons.append("حروف كبيرة زيادة عن اللزوم")

    if _REPEATED_CHAR_RE.search(text):
        score += 1
        reasons.append("حروف مكررة بشكل غير طبيعي")

    emoji_count = sum(1 for c in text if c in _POSITIVE_EMOJI or c in _NEGATIVE_EMOJI)
    if emoji_count >= 6:
        score += 1
        reasons.append("عدد إيموجي كبير جدًا")

    return score, reasons


def _cmd_comment_spam_detect(ctx) -> str:
    lines = _read_lines(ctx)
    if not lines:
        return "usage: comment_spam_detect <comment text OR path to .txt file>"

    flagged = []
    for ln in lines:
        score, reasons = _spam_score(ln)
        if score >= 2:
            flagged.append((ln, score, reasons))

    if len(lines) == 1:
        score, reasons = _spam_score(lines[0])
        verdict = "🚩 سبام محتمل" if score >= 2 else "✅ يبان طبيعي"
        out = [f"{verdict} (score={score})", f"\"{lines[0]}\""]
        if reasons:
            out.append("الأسباب: " + "، ".join(reasons))
        return "\n".join(out)

    lines_out = [f"🚩 فحص سبام لـ {len(lines)} تعليق — {len(flagged)} مشتبه بيه:"]
    for text, score, reasons in sorted(flagged, key=lambda f: -f[1])[:10]:
        lines_out.append(f"   • [{score}] {text}")
        lines_out.append(f"     ({', '.join(reasons)})")
    if not flagged:
        lines_out.append("   ✅ مفيش تعليقات مشتبه فيها")
    return "\n".join(lines_out)


# ── reply_template ────────────────────────────────────────────────────────

_REPLY_TEMPLATES = {
    ("question", "friendly"): "سؤال حلو! هرد عليك بسرعة — لو لسه مش واضح قولي وهوضحلك أكتر 🙌",
    ("question", "professional"): "شكرًا لسؤالك، سأقوم بالرد عليه بالتفصيل. لا تتردد في التواصل لو احتجت أي توضيح إضافي.",
    ("question", "funny"): "ياااه سؤال VIP 😄 هجاوبك دلوقتي بس ركز معايا كويس!",
    ("compliment", "friendly"): "تسلملي يا نجم 🙏 كلامك ده بيفرحني جدًا",
    ("compliment", "professional"): "نشكرك جزيل الشكر على كلماتك الطيبة، سعداء لأنك استفدت من المحتوى.",
    ("compliment", "funny"): "هعلقها في فريمي بقى 😂 شكرًا ليك يا وحش!",
    ("complaint", "friendly"): "معلش يا صديقي، سامعك. قولي بالظبط إيه المشكلة عشان أقدر أساعدك.",
    ("complaint", "professional"): "نأسف لتجربتك، ونقدر ملاحظتك. هل يمكنك توضيح المشكلة بالتفصيل حتى نتمكن من المساعدة؟",
    ("complaint", "funny"): "أوبس! 😅 قولي حصل إيه بالظبط وهنصلحها سوا",
    ("generic", "friendly"): "شكرًا لتعليقك يا نجم 🙌",
    ("generic", "professional"): "شكرًا لتعليقك، نقدر تفاعلك معنا.",
    ("generic", "funny"): "تعليقك وصل واتسجل في التاريخ 😄 شكرًا!",
}
_VALID_TONES = {"friendly", "professional", "funny"}


def _classify_comment(text: str) -> str:
    if "؟" in text or "?" in text:
        return "question"
    label, _ = _sentiment_of_line(text)
    if label == "positive":
        return "compliment"
    if label == "negative":
        return "complaint"
    return "generic"


def _cmd_reply_template(ctx) -> str:
    if len(ctx.args) < 1:
        return "usage: reply_template <comment text> tone=friendly|professional|funny"
    tone = "friendly"
    comment_parts = []
    for arg in ctx.args:
        if arg.startswith("tone="):
            tone = arg[5:].lower()
        else:
            comment_parts.append(arg)
    if tone not in _VALID_TONES:
        return f"❌ tone لازم يكون واحد من: {', '.join(sorted(_VALID_TONES))}"
    comment = " ".join(comment_parts).strip()
    if not comment:
        return "usage: reply_template <comment text> tone=friendly|professional|funny"

    category = _classify_comment(comment)
    spam_score, spam_reasons = _spam_score(comment)
    if spam_score >= 2:
        return (
            f"🚩 التعليق ده بيبان سبام محتمل ({', '.join(spam_reasons)}) — "
            "الأفضل متردش عليه، بلّغ عنه أو اخفيه بدل ما تديله تفاعل."
        )

    template = _REPLY_TEMPLATES[(category, tone)]
    category_ar = {"question": "سؤال", "compliment": "مجاملة", "complaint": "شكوى", "generic": "عام"}[category]
    return f"📝 نوع التعليق: {category_ar}  |  النبرة: {tone}\n\nرد مقترح:\n{template}"


# ── engagement_calendar ────────────────────────────────────────────────────

_COMMUNITY_POST_TYPES = [
    "استطلاع رأي (Poll)", "سؤال تفاعلي", "كواليس/behind the scenes",
    "صورة من التصوير", "تذكير بفيديو جديد", "Meme متعلق بالنيش", "شكر للمتابعين",
]


def _cmd_engagement_calendar(ctx) -> str:
    if not ctx.args:
        return "usage: engagement_calendar <posts_per_week 1-7>"
    try:
        per_week = int(ctx.args[0])
    except ValueError:
        return "❌ عدد المنشورات لازم يكون رقم صحيح"
    if not (1 <= per_week <= 7):
        return "❌ عدد المنشورات أسبوعيًا لازم يكون بين 1 و7"

    day_indices = sorted({round(i * 7 / per_week) % 7 for i in range(per_week)})
    while len(day_indices) < per_week:
        for d in range(7):
            if d not in day_indices:
                day_indices.append(d)
                break
        day_indices = sorted(set(day_indices))

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())

    lines = [f"📅 خطة تفاعل مجتمعي: {per_week} منشور/أسبوع"]
    for i, d in enumerate(day_indices):
        day_date = monday + timedelta(days=d)
        post_type = _COMMUNITY_POST_TYPES[i % len(_COMMUNITY_POST_TYPES)]
        lines.append(f"   • {_DAY_NAMES_AR[d]} ({day_date.strftime('%Y-%m-%d')}) — {post_type}")

    lines.append(
        "\n💡 توجيه عام: التفاعل غالبًا بيزيد بالليل ونهاية الأسبوع، لكن "
        "الوقت الأمثل الفعلي بيختلف حسب جمهورك — راجع تبويب Community "
        "في YouTube Studio (مجاني) عشان تشوف أوقات نشاط متابعينك بالظبط."
    )
    return "\n".join(lines)


def register(engine):
    engine.registry.register("comment_sentiment", _cmd_comment_sentiment,
                              "comment_sentiment <text|path> — تحليل مشاعر تعليق أو ملف تعليقات")
    engine.registry.register("comment_spam_detect", _cmd_comment_spam_detect,
                              "comment_spam_detect <text|path> — كشف سبام هيكلي في التعليقات")
    engine.registry.register("reply_template", _cmd_reply_template,
                              "reply_template <comment text> tone=friendly|professional|funny — رد مقترح")
    engine.registry.register("engagement_calendar", _cmd_engagement_calendar,
                              "engagement_calendar <posts_per_week> — خطة منشورات مجتمعية أسبوعية")
