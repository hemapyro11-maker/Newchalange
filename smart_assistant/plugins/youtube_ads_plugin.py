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
        return "❌ the daily budget and CPM estimate must be numbers"
    days = 30
    for arg in ctx.args[2:]:
        if arg.startswith("days="):
            try:
                days = int(arg[5:])
            except ValueError:
                return "❌ days must be a whole number"
    if daily_budget <= 0 or cpm <= 0:
        return "❌ the budget and CPM must be greater than zero"
    if not (1 <= days <= 365):
        return "❌ days must be between 1 and 365"

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
        f"💰 Budget calculator: {_fmt_int(daily_budget)}/day × {days} days",
        f"\n  💵 total budget: {_fmt_int(total_budget)}",
        f"  👁 expected impressions: ~{_fmt_int(total_impressions)}",
        "\n  🎬 expected views (at a 10%-30% view rate for skippable ads):",
        f"     low: ~{_fmt_int(views_low)}   |   mid: ~{_fmt_int(views_mid)}   |   high: ~{_fmt_int(views_high)}",
        f"\n  📊 approximate cost per view (at the mid estimate): ~{total_budget / views_mid:.3f} each" if views_mid else "",
        (
            "\n⚠️ These are estimates built on general industry averages — real "
            "performance depends on your targeting, your content, and the competition in your niche. "
            "Treat them as a planning starting point, not a guarantee."
        ),
    ]
    return "\n".join(line for line in lines if line)


# ── ads_targeting_advisor ────────────────────────────────────────────────

_TARGETING_ADVICE = {
    "views": {
        "primary": ["Affinity Audiences (people interested in similar topics)", "Custom Intent (search terms tied to your niche)"],
        "why": "a views goal needs wide reach at low cost — a broad interested audience is cheaper than tight targeting",
        "avoid": "do not use Remarketing as your primary targeting — the audience that already saw you is small and will not deliver many views",
    },
    "subs": {
        "primary": ["Custom Intent (precise search intent in your niche)", "Similar Audiences / Lookalike (like your existing subscribers)"],
        "why": "to win a subscription you need an audience close to your existing subscribers interests, not a general one",
        "avoid": "very broad targeting (general Affinity) brings views rather than subscribers — a weak conversion rate",
    },
    "sales": {
        "primary": ["In-market Audiences (people actively shopping in this category)", "Remarketing (visitors to your site or channel)", "Customer Match, if you have a customer list"],
        "why": "sales need an audience close to a buying decision — In-market and Remarketing are genuinely closer than anything else",
        "avoid": "do not rely on Affinity or general interests alone — they are far too broad for a sales goal",
    },
    "awareness": {
        "primary": ["Affinity Audiences (wide reach)", "broad demographics", "Placements on large channels in your field"],
        "why": "brand awareness needs the widest reach at reasonable frequency — not precise targeting",
        "avoid": "do not narrow with Remarketing or In-market — that cuts the reach, which is the whole point here",
    },
}


def _cmd_ads_targeting_advisor(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: ads_targeting_advisor <niche> <goal: views|subs|sales|awareness>"
    goal = ctx.args[-1].lower()
    niche = " ".join(ctx.args[:-1])
    if goal not in _TARGETING_ADVICE:
        return f"❌ goal must be one of: {', '.join(_TARGETING_ADVICE)}"

    advice = _TARGETING_ADVICE[goal]
    lines = [
        f"🎯 Targeting advice: {niche} — goal: {goal}",
        "\n✅ Recommended targeting:",
    ]
    lines += [f"   • {t}" for t in advice["primary"]]
    lines.append(f"\n💡 Why: {advice['why']}")
    lines.append(f"⚠️ Avoid: {advice['avoid']}")
    lines.append(
        "\n📌 Note: apply this targeting inside your own account at "
        "ads.google.com — this only suggests the strategy, it does not run it."
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
        return "usage: ads_copy_score <headline> | <description>   (separate them with |)"
    headline, description = (p.strip() for p in joined.split("|", 1))
    if not headline or not description:
        return "❌ both a headline and a description are required"

    lines = ["📢 Ad copy review", f"\nHeadline: \"{headline}\" ({len(headline)} characters)"]
    if len(headline) > 100:
        lines.append("  ❌ over 100 characters — it will be cut off in most YouTube ad formats")
    elif len(headline) > 40:
        lines.append("  ⚠️ longer than ideal (40 characters) — it may be cut off in places, mobile especially")
    else:
        lines.append("  ✅ good length")

    lines.append(f"\nDescription: \"{description}\" ({len(description)} characters)")
    if len(description) > 70:
        lines.append("  ⚠️ beyond the safe range (~70 characters for two lines) — it may be cut off")
    else:
        lines.append("  ✅ good length")

    combined = (headline + " " + description).lower()
    has_cta = [c for c in _CTA_WORDS if c in combined]
    has_urgency = [u for u in _URGENCY_WORDS if u in combined]
    has_number = bool(re.search(r"\d", combined))

    lines.append("\nAnalysis:")
    if has_cta:
        lines.append(f"  ✅ has a call to action: {has_cta[0]}")
    else:
        lines.append("  ❌ no clear call to action — add an imperative like \"subscribe\", \"try\", \"book\"")
    if has_urgency:
        lines.append(f"  ✅ conveys urgency: {has_urgency[0]}")
    else:
        lines.append("  ℹ️ no sense of urgency — adding one can lift conversion, though it is optional")
    if has_number:
        lines.append("  ✅ contains a number — that adds credibility and specificity")

    return "\n".join(lines)


# ── ads_campaign_plan ────────────────────────────────────────────────────

_FUNNEL_PLANS = {
    "awareness": {
        "split": [("Skippable In-Stream (wide reach)", 0.70), ("Bumper Ads, 6 seconds (frequency)", 0.20), ("Remarketing", 0.10)],
        "bid_strategy": "Target CPM — you pay per 1000 impressions, maximising the reach that is the goal here",
    },
    "subs": {
        "split": [("Skippable In-Stream", 0.50), ("Discovery Ads", 0.30), ("Remarketing", 0.20)],
        "bid_strategy": "Maximize Conversions or Target CPV — if you track the subscribe event, use Maximize Conversions",
    },
    "sales": {
        "split": [("Skippable In-Stream", 0.40), ("Discovery Ads", 0.20), ("Remarketing", 0.40)],
        "bid_strategy": "Target CPA or Maximize Conversions — needs conversion tracking enabled before you start",
    },
}


def _cmd_ads_campaign_plan(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: ads_campaign_plan <budget_total> <duration_days> <goal: awareness|subs|sales>"
    try:
        budget_total = float(ctx.args[0])
        duration_days = int(ctx.args[1])
    except ValueError:
        return "❌ the budget and duration must be numbers"
    goal = ctx.args[2].lower()
    if goal not in _FUNNEL_PLANS:
        return f"❌ goal must be one of: {', '.join(_FUNNEL_PLANS)}"
    if budget_total <= 0:
        return "❌ the budget must be greater than zero"
    if not (1 <= duration_days <= 365):
        return "❌ the duration must be between 1 and 365 days"

    plan = _FUNNEL_PLANS[goal]
    daily_budget = budget_total / duration_days

    lines = [
        f"📋 Campaign plan: {_fmt_int(budget_total)} over {duration_days} days — goal: {goal}",
        f"\n  💵 daily budget: ~{daily_budget:.2f}",
        "\n  📊 Suggested budget split:",
    ]
    for name, pct in plan["split"]:
        lines.append(f"     • {name}: {pct * 100:.0f}%  (~{budget_total * pct:.0f})")
    lines.append(f"\n  🎯 Recommended bid strategy: {plan['bid_strategy']}")
    lines.append(
        "\n📌 This plan is a strategic starting point — adjust it against real performance "
        "after the first week of actually running it on ads.google.com."
    )
    return "\n".join(lines)


def register(engine):
    engine.registry.register("ads_budget_calc", _cmd_ads_budget_calc,
                              "ads_budget_calc <daily_budget> <cpm_estimate> [days=30] — reach and cost calculator")
    engine.registry.register("ads_targeting_advisor", _cmd_ads_targeting_advisor,
                              "ads_targeting_advisor <niche> <goal> — targeting advice for a campaign goal")
    engine.registry.register("ads_copy_score", _cmd_ads_copy_score,
                              "ads_copy_score <headline> | <description> — review ad copy")
    engine.registry.register("ads_campaign_plan", _cmd_ads_campaign_plan,
                              "ads_campaign_plan <budget_total> <duration_days> <goal> — a full campaign plan")
