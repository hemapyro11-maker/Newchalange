"""
youtube_seo_plugin.py — خبير تحسين محركات البحث ليوتيوب: تقييم عنوان
ووصف حقيقي (طول، بنية، إشارات معروفة بتأثيرها على الـ SEO)، استخراج
كلمات مفتاحية مرشحة من نص العنوان/الوصف (تحليل تكرار محلي، من غير أي
API أو نموذج خارجي)، وتدقيق وسوم (tags) مقابل حدود يوتيوب الفعلية.

الأوامر: seo_title_score, seo_description_score, seo_tags_suggest,
seo_tags_audit, seo_full_audit
"""
from __future__ import annotations

import pathlib
import re

TITLE_MAX_LEN = 100          # حد يوتيوب الفعلي (بايت 100 حرف تقريبًا)
TITLE_IDEAL_MIN = 40
TITLE_IDEAL_MAX = 60
TITLE_TRUNCATE_WARN = 70     # نتائج البحث بتقطع حوالي هنا

TAGS_CHAR_BUDGET = 500       # حد يوتيوب الفعلي لإجمالي حروف الوسوم

_POWER_WORDS = [
    "أفضل", "أسرع", "مجاني", "حصري", "جديد", "سر", "أسرار", "نهائي",
    "كامل", "شامل", "احترافي", "مضمون",
    "best", "free", "ultimate", "complete", "guide", "secret", "proven",
    "easy", "fast", "new",
]

_AR_STOPWORDS = {
    "من", "في", "على", "الى", "إلى", "عن", "مع", "هذا", "هذه", "ذلك",
    "التي", "الذي", "كل", "او", "أو", "و", "ثم", "لكن", "ان", "إن",
    "لا", "ما", "هو", "هي", "هم", "انت", "أنت", "انا", "أنا", "كان",
    "يكون", "بين", "بعد", "قبل", "عند", "كيف", "متى", "اين", "أين",
    "له", "لها", "لهم", "به", "بها", "التى", "دي", "ده", "احنا", "انتوا",
}
_EN_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
    "is", "are", "was", "were", "be", "been", "this", "that", "with",
    "how", "what", "when", "where", "why", "you", "your", "it", "its",
    "as", "by", "from", "we", "i", "my", "our",
}
_STOPWORDS = _AR_STOPWORDS | _EN_STOPWORDS

_WORD_RE = re.compile(r"[\w#]+", re.UNICODE)
_TIMESTAMP_RE = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b")
_HASHTAG_RE = re.compile(r"#\w+")
_URL_RE = re.compile(r"https?://\S+")


def _read_text_or_raw(ctx) -> str | None:
    """للأوامر اللي بتاخد نص حر طويل (وصف): لو الوسيطة الوحيدة مسار ملف
    موجود، بنقراه؛ غير كده بناخد النص الخام زي ما اتكتب (بمسافاته وعلامات
    ترقيمه، من غير ما shlex يبوظها)."""
    if len(ctx.args) == 1 and pathlib.Path(ctx.args[0]).is_file():
        try:
            return pathlib.Path(ctx.args[0]).read_text(encoding="utf-8")
        except OSError:
            return None
    parts = ctx.raw.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else None


# ── seo_title_score ──────────────────────────────────────────────────────

def _score_title(title: str) -> tuple[int, list[str]]:
    score = 50
    notes = []
    length = len(title)

    if length > TITLE_MAX_LEN:
        notes.append(f"❌ العنوان أطول من {TITLE_MAX_LEN} حرف — يوتيوب هيقطعه")
        score -= 25
    elif TITLE_IDEAL_MIN <= length <= TITLE_IDEAL_MAX:
        notes.append(f"✅ طول ممتاز ({length} حرف) — ضمن المدى المثالي {TITLE_IDEAL_MIN}-{TITLE_IDEAL_MAX}")
        score += 20
    elif length < TITLE_IDEAL_MIN:
        notes.append(f"⚠️ العنوان قصير ({length} حرف) — ممكن ينقصه كلمات مفتاحية")
        score += 5
    elif length <= TITLE_TRUNCATE_WARN:
        notes.append(f"🙂 طول مقبول ({length} حرف)")
        score += 10
    else:
        notes.append(f"⚠️ العنوان طويل ({length} حرف) — ممكن يتقطع في نتائج البحث حوالي {TITLE_TRUNCATE_WARN} حرف")

    if re.search(r"\d", title):
        score += 10
        notes.append("✅ فيه رقم — بيلفت الانتباه ويوحي بمحتوى محدد (زي \"7 طرق\")")

    hit_power = [w for w in _POWER_WORDS if w.lower() in title.lower()]
    if hit_power:
        score += 10
        notes.append(f"✅ فيه كلمة قوية: {', '.join(hit_power[:3])}")

    letters = [c for c in title if c.isalpha()]
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters) if letters else 0
    if upper_ratio > 0.6 and len(letters) > 8:
        score -= 15
        notes.append("❌ نسبة حروف كبيرة عالية جدًا — بيبان سبام/كليك بيت رخيص")

    punct_spam = re.findall(r"[!?]{2,}", title)
    if punct_spam:
        score -= 10
        notes.append("⚠️ علامات ترقيم متكررة (!!! أو ???) — ممكن تقلل المصداقية")

    if "|" in title or " - " in title:
        notes.append("ℹ️ فيه فاصل (| أو -) — كويس لو بيفصل بين الموضوع واسم القناة/سلسلة")

    return max(0, min(100, score)), notes


def _cmd_seo_title_score(ctx) -> str:
    if not ctx.raw or len(ctx.raw.split(None, 1)) < 2:
        return "usage: seo_title_score <title>"
    title = ctx.raw.split(None, 1)[1].strip()
    if not title:
        return "usage: seo_title_score <title>"

    score, notes = _score_title(title)
    lines = [f"🏷 تقييم العنوان: \"{title}\"", f"\nالنتيجة: {score}/100", "\nالتفاصيل:"]
    lines += [f"  {n}" for n in notes]
    return "\n".join(lines)


# ── seo_description_score ────────────────────────────────────────────────

def _score_description(text: str) -> tuple[int, list[str]]:
    score = 40
    notes = []
    length = len(text)
    above_fold = text[:150]

    if length < 100:
        notes.append(f"❌ قصير جدًا ({length} حرف) — مساحة ضايعة لكلمات مفتاحية ومعلومات")
    elif length < 250:
        notes.append(f"⚠️ قصير ({length} حرف) — يوتيوب بيفضّل وصف أطول للـ SEO (200+ كلمة مثالي)")
        score += 10
    else:
        notes.append(f"✅ طول جيد ({length} حرف)")
        score += 20

    if len(above_fold.strip()) < 50:
        notes.append("⚠️ أول 150 حرف (اللي بتظهر قبل \"عرض المزيد\") فاضية شبه — حط أهم معلومة هنا")
    else:
        score += 15
        notes.append("✅ أول 150 حرف فيها محتوى فعلي")

    if _URL_RE.search(text):
        score += 10
        notes.append("✅ فيه رابط (سوشيال ميديا/موقع)")

    ts_count = len(_TIMESTAMP_RE.findall(text))
    if ts_count >= 2:
        score += 15
        notes.append(f"✅ فيه {ts_count} توقيت (chapters) — بيحسّن engagement والـ SEO")

    hashtags = _HASHTAG_RE.findall(text)
    if len(hashtags) > 3:
        score -= 10
        notes.append(f"⚠️ فيه {len(hashtags)} هاشتاج — يوتيوب بيعرض أول 3 بس فوق العنوان، الباقي ممكن يبان سبام")
    elif hashtags:
        score += 5
        notes.append(f"✅ فيه {len(hashtags)} هاشتاج (ضمن الحد المعقول)")

    return max(0, min(100, score)), notes


def _cmd_seo_description_score(ctx) -> str:
    text = _read_text_or_raw(ctx)
    if text is None:
        return "usage: seo_description_score <description text OR path to .txt file>"
    if not text.strip():
        return "usage: seo_description_score <description text OR path to .txt file>"

    score, notes = _score_description(text)
    lines = [f"📄 تقييم الوصف ({len(text)} حرف)", f"\nالنتيجة: {score}/100", "\nالتفاصيل:"]
    lines += [f"  {n}" for n in notes]
    return "\n".join(lines)


# ── keyword extraction (مشترك بين seo_tags_suggest و seo_full_audit) ───

def _extract_keywords(title: str, description: str, top_n: int = 15) -> list[str]:
    def tokens(text: str) -> list[str]:
        return [w.lower() for w in _WORD_RE.findall(text) if len(w) > 2 and w.lower() not in _STOPWORDS]

    title_tokens = tokens(title)
    desc_tokens = tokens(description)

    counts: dict[str, int] = {}
    # كلمات العنوان أهم — بنوزن تكرارها ×3 عشان تتصدر الترشيحات.
    for w in title_tokens:
        counts[w] = counts.get(w, 0) + 3
    for w in desc_tokens:
        counts[w] = counts.get(w, 0) + 1

    # ثنائيات (bigrams) من العنوان — عبارات أدق من كلمة واحدة، غالبًا
    # أقرب لحاجة الناس بتدوّرها فعليًا.
    for i in range(len(title_tokens) - 1):
        bigram = f"{title_tokens[i]} {title_tokens[i + 1]}"
        counts[bigram] = counts.get(bigram, 0) + 2

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:top_n]]


def _cmd_seo_tags_suggest(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: seo_tags_suggest <title.txt> <description.txt>"
    title_path, desc_path = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if not title_path.is_file():
        return f"❌ file not found: {title_path}"
    if not desc_path.is_file():
        return f"❌ file not found: {desc_path}"
    try:
        title = title_path.read_text(encoding="utf-8")
        description = desc_path.read_text(encoding="utf-8")
    except OSError as e:
        return f"❌ تعذرت القراءة: {e}"

    keywords = _extract_keywords(title, description)
    if not keywords:
        return "❌ مش لاقي كلمات كفاية (كل الكلمات قصيرة جدًا أو stopwords)"

    total_chars = sum(len(k) + 1 for k in keywords)  # +1 للفاصلة تقريبًا
    lines = [f"🏷 كلمات مفتاحية مرشحة ({len(keywords)}):"]
    lines += [f"  • {k}" for k in keywords]
    lines.append(f"\n📏 لو استخدمتها كلها كـ tags: ~{total_chars} حرف من أصل {TAGS_CHAR_BUDGET} المسموحين")
    return "\n".join(lines)


# ── seo_tags_audit ────────────────────────────────────────────────────────

def _cmd_seo_tags_audit(ctx) -> str:
    if not ctx.raw or len(ctx.raw.split(None, 1)) < 2:
        return "usage: seo_tags_audit <tag1, tag2, tag3, ...>"
    raw_tags = ctx.raw.split(None, 1)[1].strip()
    if not raw_tags:
        return "usage: seo_tags_audit <tag1, tag2, tag3, ...>"

    tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    if not tags:
        return "❌ مفيش وسوم صالحة بعد الفصل بالفاصلة"

    total_chars = sum(len(t) for t in tags)
    lines = [f"🏷 تدقيق {len(tags)} وسم — إجمالي {total_chars}/{TAGS_CHAR_BUDGET} حرف"]

    if total_chars > TAGS_CHAR_BUDGET:
        lines.append(f"  ❌ تجاوزت حد يوتيوب ({TAGS_CHAR_BUDGET} حرف) — يوتيوب هيتجاهل الوسوم الزيادة")
    elif total_chars > TAGS_CHAR_BUDGET * 0.9:
        lines.append("  ⚠️ قريب من الحد الأقصى")
    else:
        lines.append(f"  ✅ في حدود المسموح (باقيلك {TAGS_CHAR_BUDGET - total_chars} حرف)")

    lower_seen: dict[str, str] = {}
    duplicates = []
    for t in tags:
        low = t.lower()
        if low in lower_seen:
            duplicates.append(t)
        else:
            lower_seen[low] = t
    if duplicates:
        lines.append(f"  ⚠️ وسوم مكررة: {', '.join(duplicates)}")

    near_dupes = []
    lowers = [t.lower() for t in tags]
    for i, a in enumerate(lowers):
        for b in lowers[i + 1:]:
            if a != b and (a == b + "s" or b == a + "s" or a == b + "es" or b == a + "es"):
                near_dupes.append(f"{a} / {b}")
    if near_dupes:
        lines.append(f"  ℹ️ وسوم شبه مكررة (مفرد/جمع) — ممكن تدمجهم: {', '.join(near_dupes[:5])}")

    broad = sum(1 for t in tags if " " not in t.strip())
    specific = len(tags) - broad
    lines.append(f"  📊 وسوم عامة (كلمة واحدة): {broad}  |  وسوم محددة (عبارة): {specific}")
    if specific == 0 and len(tags) > 3:
        lines.append("  💡 كل الوسوم كلمة واحدة — ضيف عبارات أدق (2-3 كلمات) بتوصف الفيديو تحديدًا")
    elif broad == 0 and len(tags) > 3:
        lines.append("  💡 كل الوسوم عبارات — ضيف كام وسم عام (كلمة واحدة) للوصول الأوسع")

    return "\n".join(lines)


# ── seo_full_audit ────────────────────────────────────────────────────────

def _cmd_seo_full_audit(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: seo_full_audit <title.txt> <description.txt> <tag1,tag2,...>"
    title_path, desc_path = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if not title_path.is_file():
        return f"❌ file not found: {title_path}"
    if not desc_path.is_file():
        return f"❌ file not found: {desc_path}"
    try:
        title = title_path.read_text(encoding="utf-8").strip()
        description = desc_path.read_text(encoding="utf-8")
    except OSError as e:
        return f"❌ تعذرت القراءة: {e}"

    tags_raw = " ".join(ctx.args[2:])
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    title_score, title_notes = _score_title(title)
    desc_score, desc_notes = _score_description(description)
    tags_score = 50
    if tags:
        total_chars = sum(len(t) for t in tags)
        if total_chars <= TAGS_CHAR_BUDGET:
            tags_score += 20
        if len(tags) >= 5:
            tags_score += 15
        if any(" " in t for t in tags):
            tags_score += 15
    tags_score = max(0, min(100, tags_score))

    overall = round(title_score * 0.4 + desc_score * 0.3 + tags_score * 0.3)

    lines = [
        "📋 تقرير SEO شامل",
        f"\nالنتيجة الكلية: {overall}/100",
        f"\n🏷 العنوان ({title_score}/100): \"{title}\"",
    ]
    lines += [f"  {n}" for n in title_notes]
    lines.append(f"\n📄 الوصف ({desc_score}/100):")
    lines += [f"  {n}" for n in desc_notes]
    lines.append(f"\n🔖 الوسوم ({tags_score}/100): {len(tags)} وسم")
    if not tags:
        lines.append("  ❌ مفيش وسوم خالص")

    return "\n".join(lines)


def register(engine):
    engine.registry.register("seo_title_score", _cmd_seo_title_score,
                              "seo_title_score <title> — تقييم عنوان الفيديو /100")
    engine.registry.register("seo_description_score", _cmd_seo_description_score,
                              "seo_description_score <text|path> — تقييم وصف الفيديو /100")
    engine.registry.register("seo_tags_suggest", _cmd_seo_tags_suggest,
                              "seo_tags_suggest <title.txt> <description.txt> — كلمات مفتاحية مرشحة")
    engine.registry.register("seo_tags_audit", _cmd_seo_tags_audit,
                              "seo_tags_audit <tag1, tag2, ...> — تدقيق وسوم مقابل حدود يوتيوب")
    engine.registry.register("seo_full_audit", _cmd_seo_full_audit,
                              "seo_full_audit <title.txt> <description.txt> <tags> — تقرير SEO كامل")
