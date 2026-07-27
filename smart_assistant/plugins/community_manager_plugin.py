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

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

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
        return "usage: comment_sentiment <comment text OR path to a .txt file, one comment per line>"

    results = [(ln, *_sentiment_of_line(ln)) for ln in lines]
    pos = [r for r in results if r[1] == "positive"]
    neg = [r for r in results if r[1] == "negative"]
    neu = [r for r in results if r[1] == "neutral"]

    if len(lines) == 1:
        text, label, score = results[0]
        icon = {"positive": "😊", "negative": "😞", "neutral": "😐"}[label]
        return f"{icon} sentiment: {label} (score={score})\n\"{text}\""

    total = len(results)
    lines_out = [
        f"💬 Sentiment across {total} comments:",
        f"   😊 positive: {len(pos)} ({len(pos) / total * 100:.0f}%)",
        f"   😐 neutral: {len(neu)} ({len(neu) / total * 100:.0f}%)",
        f"   😞 negative: {len(neg)} ({len(neg) / total * 100:.0f}%)",
    ]
    if neg:
        lines_out.append("\n⚠️ Negative comments worth a look:")
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
        reasons.append("contains a link")

    hit_phrases = [p for p in _SPAM_PHRASES if p in low]
    if hit_phrases:
        score += 2
        reasons.append(f"known promotional phrase: \"{hit_phrases[0]}\"")

    if _PHONE_RE.search(text):
        score += 1
        reasons.append("contains something shaped like a phone or WhatsApp number")

    letters = [c for c in text if c.isalpha()]
    if letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio > 0.7 and len(letters) > 10:
            score += 1
            reasons.append("excessive capitals")

    if _REPEATED_CHAR_RE.search(text):
        score += 1
        reasons.append("unnaturally repeated characters")

    emoji_count = sum(1 for c in text if c in _POSITIVE_EMOJI or c in _NEGATIVE_EMOJI)
    if emoji_count >= 6:
        score += 1
        reasons.append("far too many emoji")

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
        verdict = "🚩 likely spam" if score >= 2 else "✅ looks genuine"
        out = [f"{verdict} (score={score})", f"\"{lines[0]}\""]
        if reasons:
            out.append("Reasons: " + ", ".join(reasons))
        return "\n".join(out)

    lines_out = [f"🚩 Spam check across {len(lines)} comments — {len(flagged)} suspicious:"]
    for text, score, reasons in sorted(flagged, key=lambda f: -f[1])[:10]:
        lines_out.append(f"   • [{score}] {text}")
        lines_out.append(f"     ({', '.join(reasons)})")
    if not flagged:
        lines_out.append("   ✅ nothing suspicious")
    return "\n".join(lines_out)


# ── reply_template ────────────────────────────────────────────────────────

# الردود دي بتتبعت لجمهورك، فبتيجي بلغة التعليق نفسه — مش بلغة
# الواجهة. تعليق إنجليزي بيرد عليه إنجليزي والعكس؛ الرد بلغة غلط
# أسوأ من مفيش رد.
_REPLY_TEMPLATES = {
    "ar": {
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
    },
    "en": {
        ("question", "friendly"): "Good question! I will get back to you shortly — if anything is still unclear, say so and I will explain further 🙌",
        ("question", "professional"): "Thank you for your question. I will answer it in detail — do get in touch if you need any further clarification.",
        ("question", "funny"): "Ooh, a VIP question 😄 answering right now — pay attention!",
        ("compliment", "friendly"): "Thank you, that genuinely made my day 🙏",
        ("compliment", "professional"): "Thank you very much for your kind words. We are glad you found the content useful.",
        ("compliment", "funny"): "Framing this one 😂 thank you!",
        ("complaint", "friendly"): "Sorry about that — I hear you. Tell me exactly what went wrong and I will help.",
        ("complaint", "professional"): "We are sorry about your experience and we appreciate the feedback. Could you describe the problem in detail so we can help?",
        ("complaint", "funny"): "Oops! 😅 tell me exactly what happened and we will sort it out together",
        ("generic", "friendly"): "Thanks for the comment 🙌",
        ("generic", "professional"): "Thank you for your comment — we appreciate you engaging with us.",
        ("generic", "funny"): "Comment received and filed in the archives 😄 thanks!",
    },
}

_ARABIC_RANGE = re.compile(r"[\u0600-\u06FF]")


def _comment_lang(text: str) -> str:
    """لغة التعليق — حرف عربي واحد كفاية يخليه عربي."""
    return "ar" if _ARABIC_RANGE.search(text or "") else "en"


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
        return f"❌ tone must be one of: {', '.join(sorted(_VALID_TONES))}"
    comment = " ".join(comment_parts).strip()
    if not comment:
        return "usage: reply_template <comment text> tone=friendly|professional|funny"

    category = _classify_comment(comment)
    spam_score, spam_reasons = _spam_score(comment)
    if spam_score >= 2:
        return (
            f"🚩 This comment looks like spam ({', '.join(spam_reasons)}) — "
            "better not to reply; report or hide it rather than give it engagement."
        )

    lang = _comment_lang(comment)
    template = _REPLY_TEMPLATES[lang][(category, tone)]
    return (
        f"📝 Comment type: {category}  |  tone: {tone}  |  replying in: {lang}\n\n"
        f"Suggested reply:\n{template}"
    )


# ── engagement_calendar ────────────────────────────────────────────────────

_COMMUNITY_POST_TYPES = [
    "a poll", "an open question", "behind the scenes",
    "a photo from the shoot", "a reminder about a new video", "a meme from your niche", "a thank-you to your followers",
]


def _cmd_engagement_calendar(ctx) -> str:
    if not ctx.args:
        return "usage: engagement_calendar <posts_per_week 1-7>"
    try:
        per_week = int(ctx.args[0])
    except ValueError:
        return "❌ the number of posts must be a whole number"
    if not (1 <= per_week <= 7):
        return "❌ posts per week must be between 1 and 7"

    day_indices = sorted({round(i * 7 / per_week) % 7 for i in range(per_week)})
    while len(day_indices) < per_week:
        for d in range(7):
            if d not in day_indices:
                day_indices.append(d)
                break
        day_indices = sorted(set(day_indices))

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())

    lines = [f"📅 Community plan: {per_week} posts per week"]
    for i, d in enumerate(day_indices):
        day_date = monday + timedelta(days=d)
        post_type = _COMMUNITY_POST_TYPES[i % len(_COMMUNITY_POST_TYPES)]
        lines.append(f"   • {_DAY_NAMES[d]} ({day_date.strftime('%Y-%m-%d')}) — {post_type}")

    lines.append(
        "\n💡 General guidance: engagement usually rises in the evening and at weekends, but "
        "the genuinely best time depends on your audience — check the Community tab "
        "in YouTube Studio (free) to see exactly when your followers are active."
    )
    return "\n".join(lines)


def register(engine):
    engine.registry.register("comment_sentiment", _cmd_comment_sentiment,
                              "comment_sentiment <text|path> — sentiment of one comment or a file of them")
    engine.registry.register("comment_spam_detect", _cmd_comment_spam_detect,
                              "comment_spam_detect <text|path> — structural spam detection in comments")
    engine.registry.register("reply_template", _cmd_reply_template,
                              "reply_template <comment text> tone=friendly|professional|funny — a suggested reply")
    engine.registry.register("engagement_calendar", _cmd_engagement_calendar,
                              "engagement_calendar <posts_per_week> — a weekly community-post plan")
