"""
youtube_ads_plugin.py — أخصائي إعلانات يوتيوب: حاسبة ميزانية/وصول
واقعية، مستشار استهداف (targeting) مبني على معرفة حقيقية بأنواع
استهداف Google Ads الفعلية وتوافقها مع هدف الحملة، تقييم نص إعلاني،
وخطة حملة كاملة (تقسيم ميزانية + توصية استراتيجية مزايدة).

**مهم:** الأداة دي حاسبة واستشارة استراتيجية بس — مش متصلة بحساب Google
Ads حقيقي ومش بتنفّذ أو تشغّل أي حملة فعلية أو تصرف أي فلوس. أي تنفيذ
حقيقي بيحتاج حسابك على ads.google.com مباشرة.

الأوامر: ads_budget_calc, ads_targeting_advisor, ads_copy_score,
ads_campaign_plan
"""
from __future__ import annotations

import re

_CTA_WORDS = [
    "اشترك", "جرب", "احجز", "تسوق", "حمل", "سجل", "اطلب", "اكتشف",
    "shop now", "sign up", "learn more", "subscribe", "try", "download",
    "book now", "order", "get started", "join",
]
_URGENCY_WORDS = [
    "الآن", "اليوم", "لفترة محدودة", "عرض", "خصم", "أخر فرصة",
    "now", "today", "limited", "offer", "sale", "last chance", "hurry",
]


def _fmt_int(n) -> str:
    return f"{n:,.0f}"


# ── ads_budget_calc ────────────────────────────────────────────────────

def _cmd_ads_budget_calc(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: ads_budget_calc <daily_budget> <cpm_estimate> [days=30]"
    try:
        daily_budget = float(ctx.args[0])
        cpm = float(ctx.args[1])
    except ValueError:
        return "❌ الميزانية اليومية وتقدير الـ CPM لازم يكونوا أرقام"
    days = 30
    for arg in ctx.args[2:]:
        if arg.startswith("days="):
            try:
                days = int(arg[5:])
            except ValueError:
                return "❌ days لازم يكون رقم صحيح"
    if daily_budget <= 0 or cpm <= 0:
        return "❌ الميزانية والـ CPM لازم يكونوا أكبر من صفر"
    if not (1 <= days <= 365):
        return "❌ days لازم يكون بين 1 و365"

    total_budget = daily_budget * days
    impressions_per_day = daily_budget / cpm * 1000
    total_impressions = impressions_per_day * days

    # نسبة المشاهدة الفعلية (view-through rate) لإعلانات in-stream
    # skippable بتتراوح واسع جدًا حسب الجودة والاستهداف — بنقدر مدى بدل
    # ما نديك رقم واحد وهمي يوحي بدقة مالهاش أساس.
    vtr_low, vtr_mid, vtr_high = 0.10, 0.20, 0.30
    views_low = total_impressions * vtr_low
    views_mid = total_impressions * vtr_mid
    views_high = total_impressions * vtr_high

    lines = [
        f"💰 حاسبة ميزانية: {_fmt_int(daily_budget)}/يوم × {days} يوم",
        f"\n  💵 إجمالي الميزانية: {_fmt_int(total_budget)}",
        f"  👁 مرات ظهور متوقعة: ~{_fmt_int(total_impressions)}",
        "\n  🎬 مشاهدات متوقعة (حسب نسبة مشاهدة 10%-30% للإعلانات القابلة للتخطي):",
        f"     منخفض: ~{_fmt_int(views_low)}   |   متوسط: ~{_fmt_int(views_mid)}   |   مرتفع: ~{_fmt_int(views_high)}",
        f"\n  📊 تكلفة تقريبية للمشاهدة (عند المتوسط): ~{total_budget / views_mid:.3f} لكل مشاهدة" if views_mid else "",
        (
            "\n⚠️ دي أرقام تقديرية مبنية على متوسطات عامة للصناعة — الأداء "
            "الفعلي بيعتمد على جودة الاستهداف والمحتوى والمنافسة في نيشك. "
            "استخدمها كنقطة بداية للتخطيط مش كضمان."
        ),
    ]
    return "\n".join(line for line in lines if line)


# ── ads_targeting_advisor ────────────────────────────────────────────────

_TARGETING_ADVICE = {
    "views": {
        "primary": ["Affinity Audiences (جمهور بيهتم بمواضيع مشابهة)", "Custom Intent (كلمات بحث متعلقة بالنيش)"],
        "why": "هدف المشاهدات محتاج وصول واسع بتكلفة منخفضة — الجمهور العام المهتم بالمجال أرخص من الاستهداف الضيق",
        "avoid": "ماتستخدمش Remarketing كاستهداف أساسي — الجمهور اللي شافك قبل كده أصلاً صغير، مش هيوصلك لمشاهدات كتير",
    },
    "subs": {
        "primary": ["Custom Intent (نية بحث دقيقة في نيشك)", "Similar Audiences/Lookalike (شبه مشتركينك الحاليين)"],
        "why": "عشان حد يشترك، محتاج جمهور قريب من اهتمامات مشتركينك الحاليين مش جمهور عام",
        "avoid": "الاستهداف الواسع جدًا (زي Affinity العام) هيجيب مشاهدات مش مشتركين — نسبة تحويل ضعيفة",
    },
    "sales": {
        "primary": ["In-market Audiences (ناس بتدور فعليًا تشتري في الفئة دي)", "Remarketing (زوار موقعك/قناتك)", "Customer Match لو عندك قاعدة عملاء"],
        "why": "المبيعات محتاجة جمهور قريب من قرار الشراء — In-market وRemarketing أقرب فعليًا من أي استهداف تاني",
        "avoid": "ماتعتمدش على Affinity/الاهتمامات العامة لوحدها — دي واسعة جدًا لهدف مبيعات",
    },
    "awareness": {
        "primary": ["Affinity Audiences (وصول واسع)", "Demographics عامة", "Placements على قنوات كبيرة في مجالك"],
        "why": "الوعي بالبراند محتاج وصول أوسع ما يمكن بتكرار معقول — مش دقة استهداف عالية",
        "avoid": "ماتضيقش الاستهداف بـ Remarketing/In-market — ده بيقلل الوصول اللي هو الهدف الأساسي هنا",
    },
}


def _cmd_ads_targeting_advisor(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: ads_targeting_advisor <niche> <goal: views|subs|sales|awareness>"
    goal = ctx.args[-1].lower()
    niche = " ".join(ctx.args[:-1])
    if goal not in _TARGETING_ADVICE:
        return f"❌ goal لازم يكون واحد من: {', '.join(_TARGETING_ADVICE)}"

    advice = _TARGETING_ADVICE[goal]
    lines = [
        f"🎯 استشارة استهداف: {niche} — الهدف: {goal}",
        "\n✅ استهداف موصى بيه:",
    ]
    lines += [f"   • {t}" for t in advice["primary"]]
    lines.append(f"\n💡 ليه: {advice['why']}")
    lines.append(f"⚠️ تجنب: {advice['avoid']}")
    lines.append(
        "\n📌 ملحوظة: طبّق الاستهداف ده فعليًا من داخل حسابك على "
        "ads.google.com — الأداة دي بتقترح الاستراتيجية بس، مش بتنفذها."
    )
    return "\n".join(lines)


# ── ads_copy_score ──────────────────────────────────────────────────────

def _cmd_ads_copy_score(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: ads_copy_score <headline> <description>"
    # العنوان أول وسيطة (كلمة واحدة أو محاطة)، والباقي وصف — لتبسيط
    # التعامل مع CLI بنطلب الوصف كوسيطة أخيرة والعنوان الأولى، فاصل بينهم
    # بعلامة | لو فيهم مسافات.
    joined = " ".join(ctx.args)
    if "|" not in joined:
        return "usage: ads_copy_score <headline> | <description>   (افصل بينهم بـ |)"
    headline, description = (p.strip() for p in joined.split("|", 1))
    if not headline or not description:
        return "❌ العنوان والوصف لازم يكونوا موجودين"

    lines = ["📢 تقييم نص إعلاني", f"\nالعنوان: \"{headline}\" ({len(headline)} حرف)"]
    if len(headline) > 100:
        lines.append("  ❌ أطول من 100 حرف — هيتقطع في أغلب صيغ إعلانات يوتيوب")
    elif len(headline) > 40:
        lines.append("  ⚠️ أطول من المثالي (40 حرف) — قد يتقطع في بعض الأماكن (زي الموبايل)")
    else:
        lines.append("  ✅ طول مناسب")

    lines.append(f"\nالوصف: \"{description}\" ({len(description)} حرف)")
    if len(description) > 70:
        lines.append("  ⚠️ أطول من المدى الآمن (~70 حرف لسطرين) — ممكن يتقطع")
    else:
        lines.append("  ✅ طول مناسب")

    combined = (headline + " " + description).lower()
    has_cta = [c for c in _CTA_WORDS if c in combined]
    has_urgency = [u for u in _URGENCY_WORDS if u in combined]
    has_number = bool(re.search(r"\d", combined))

    lines.append("\nالتحليل:")
    if has_cta:
        lines.append(f"  ✅ فيه دعوة لاتخاذ إجراء (CTA): {has_cta[0]}")
    else:
        lines.append("  ❌ مفيش CTA واضح — ضيف فعل أمر زي \"اشترك\"، \"جرب\"، \"احجز\"")
    if has_urgency:
        lines.append(f"  ✅ فيه إحساس بالإلحاح: {has_urgency[0]}")
    else:
        lines.append("  ℹ️ مفيش إحساس بإلحاح — ممكن يزود معدل التحويل لو ضفت واحد (اختياري)")
    if has_number:
        lines.append("  ✅ فيه رقم — بيزود المصداقية والتحديد")

    return "\n".join(lines)


# ── ads_campaign_plan ────────────────────────────────────────────────────

_FUNNEL_PLANS = {
    "awareness": {
        "split": [("Skippable In-Stream (وصول واسع)", 0.70), ("Bumper Ads 6-ثواني (تكرار)", 0.20), ("Remarketing", 0.10)],
        "bid_strategy": "Target CPM — بتدفع لكل 1000 ظهور، بيعظّم الوصول اللي هو الهدف هنا",
    },
    "subs": {
        "split": [("Skippable In-Stream", 0.50), ("Discovery Ads", 0.30), ("Remarketing", 0.20)],
        "bid_strategy": "Maximize Conversions أو Target CPV — لو عندك تتبع لحدث الاشتراك، استخدم Maximize Conversions",
    },
    "sales": {
        "split": [("Skippable In-Stream", 0.40), ("Discovery Ads", 0.20), ("Remarketing", 0.40)],
        "bid_strategy": "Target CPA أو Maximize Conversions — محتاج تتبع تحويلات (conversion tracking) مفعّل قبل ما تبدأ",
    },
}


def _cmd_ads_campaign_plan(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: ads_campaign_plan <budget_total> <duration_days> <goal: awareness|subs|sales>"
    try:
        budget_total = float(ctx.args[0])
        duration_days = int(ctx.args[1])
    except ValueError:
        return "❌ الميزانية والمدة لازم يكونوا أرقام"
    goal = ctx.args[2].lower()
    if goal not in _FUNNEL_PLANS:
        return f"❌ goal لازم يكون واحد من: {', '.join(_FUNNEL_PLANS)}"
    if budget_total <= 0:
        return "❌ الميزانية لازم تكون أكبر من صفر"
    if not (1 <= duration_days <= 365):
        return "❌ المدة لازم تكون بين 1 و365 يوم"

    plan = _FUNNEL_PLANS[goal]
    daily_budget = budget_total / duration_days

    lines = [
        f"📋 خطة حملة: {_fmt_int(budget_total)} على {duration_days} يوم — الهدف: {goal}",
        f"\n  💵 ميزانية يومية: ~{daily_budget:.2f}",
        "\n  📊 تقسيم الميزانية المقترح:",
    ]
    for name, pct in plan["split"]:
        lines.append(f"     • {name}: {pct * 100:.0f}%  (~{budget_total * pct:.0f})")
    lines.append(f"\n  🎯 استراتيجية المزايدة الموصى بيها: {plan['bid_strategy']}")
    lines.append(
        "\n📌 الخطة دي نقطة بداية استراتيجية — عدّلها حسب أداء حقيقي "
        "بعد أول أسبوع من التشغيل الفعلي على ads.google.com."
    )
    return "\n".join(lines)


def register(engine):
    engine.registry.register("ads_budget_calc", _cmd_ads_budget_calc,
                              "ads_budget_calc <daily_budget> <cpm_estimate> [days=30] — حاسبة وصول وتكلفة")
    engine.registry.register("ads_targeting_advisor", _cmd_ads_targeting_advisor,
                              "ads_targeting_advisor <niche> <goal> — توصية استهداف حسب هدف الحملة")
    engine.registry.register("ads_copy_score", _cmd_ads_copy_score,
                              "ads_copy_score <headline> | <description> — تقييم نص إعلاني")
    engine.registry.register("ads_campaign_plan", _cmd_ads_campaign_plan,
                              "ads_campaign_plan <budget_total> <duration_days> <goal> — خطة حملة كاملة")
