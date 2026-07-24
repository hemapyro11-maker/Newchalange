import re

import youtube_ads_plugin as yap

# ── ads_budget_calc ──────────────────────────────────────────────────────

def test_budget_calc_needs_two_args(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["100"]))
    assert result.startswith("usage")


def test_budget_calc_invalid_numbers(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["abc", "5"]))
    assert result.startswith("❌")


def test_budget_calc_zero_budget_rejected(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["0", "5"]))
    assert result.startswith("❌")


def test_budget_calc_negative_cpm_rejected(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["100", "-5"]))
    assert result.startswith("❌")


def test_budget_calc_invalid_days(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["100", "5", "days=abc"]))
    assert result.startswith("❌")


def test_budget_calc_days_out_of_range(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["100", "5", "days=999"]))
    assert result.startswith("❌")


def test_budget_calc_computes_expected_totals(make_ctx):
    # 100/يوم بـ CPM=5 لمدة 30 يوم (افتراضي):
    # total_budget = 3000، impressions/day = 100/5*1000 = 20000، total_impressions = 600000
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["100", "5"]))
    assert "3,000" in result
    assert "600,000" in result


def test_budget_calc_respects_custom_days(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["10", "5", "days=10"]))
    assert "100" in result  # total budget = 10*10=100


def test_budget_calc_shows_view_range(make_ctx):
    result = yap._cmd_ads_budget_calc(make_ctx("ads_budget_calc", ["100", "5"]))
    assert "منخفض" in result and "متوسط" in result and "مرتفع" in result


# ── ads_targeting_advisor ────────────────────────────────────────────────

def test_targeting_advisor_needs_two_args(make_ctx):
    result = yap._cmd_ads_targeting_advisor(make_ctx("ads_targeting_advisor", ["gaming"]))
    assert result.startswith("usage")


def test_targeting_advisor_invalid_goal(make_ctx):
    result = yap._cmd_ads_targeting_advisor(make_ctx("ads_targeting_advisor", ["gaming", "world_domination"]))
    assert result.startswith("❌")


def test_targeting_advisor_views_goal(make_ctx):
    result = yap._cmd_ads_targeting_advisor(make_ctx("ads_targeting_advisor", ["ألعاب", "views"]))
    assert "Affinity" in result
    assert "تجنب" in result


def test_targeting_advisor_sales_goal_recommends_remarketing(make_ctx):
    result = yap._cmd_ads_targeting_advisor(make_ctx("ads_targeting_advisor", ["متجر إلكتروني", "sales"]))
    assert "Remarketing" in result
    assert "In-market" in result


def test_targeting_advisor_multi_word_niche(make_ctx):
    result = yap._cmd_ads_targeting_advisor(make_ctx("ads_targeting_advisor", ["تعلم", "البرمجة", "subs"]))
    assert "تعلم البرمجة" in result


# ── ads_copy_score ────────────────────────────────────────────────────────

def test_copy_score_needs_pipe_separator(make_ctx):
    result = yap._cmd_ads_copy_score(make_ctx("ads_copy_score", ["headline", "no pipe here"]))
    assert result.startswith("usage")


def test_copy_score_empty_parts_rejected(make_ctx):
    result = yap._cmd_ads_copy_score(make_ctx("ads_copy_score", ["|", "desc"]))
    assert result.startswith("❌")


def test_copy_score_good_copy_detects_cta_and_urgency(make_ctx):
    result = yap._cmd_ads_copy_score(make_ctx("ads_copy_score", ["اشترك", "الآن", "|", "عرض", "لفترة", "محدودة", "جرب", "مجانا"]))
    assert "فيه دعوة لاتخاذ إجراء" in result
    assert "فيه إحساس بالإلحاح" in result


def test_copy_score_missing_cta_flagged(make_ctx):
    result = yap._cmd_ads_copy_score(make_ctx("ads_copy_score", ["عنوان", "عادي", "|", "وصف", "عادي", "جدا"]))
    assert "مفيش CTA واضح" in result


def test_copy_score_long_headline_flagged(make_ctx):
    long_words = ["كلمة"] * 30
    result = yap._cmd_ads_copy_score(make_ctx("ads_copy_score", [*long_words, "|", "وصف", "قصير"]))
    assert "أطول من" in result


# ── ads_campaign_plan ────────────────────────────────────────────────────

def test_campaign_plan_needs_three_args(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["1000", "30"]))
    assert result.startswith("usage")


def test_campaign_plan_invalid_numbers(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["abc", "30", "sales"]))
    assert result.startswith("❌")


def test_campaign_plan_invalid_goal(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["1000", "30", "world_peace"]))
    assert result.startswith("❌")


def test_campaign_plan_zero_budget_rejected(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["0", "30", "sales"]))
    assert result.startswith("❌")


def test_campaign_plan_days_out_of_range(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["1000", "0", "sales"]))
    assert result.startswith("❌")


def test_campaign_plan_splits_sum_to_full_budget(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["1000", "30", "sales"]))
    amounts = [float(m) for m in re.findall(r"~(\d+(?:\.\d+)?)\)", result)]
    assert len(amounts) == 3
    assert abs(sum(amounts) - 1000) < 1  # هامش تقريب بسيط


def test_campaign_plan_awareness_recommends_target_cpm(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["500", "10", "awareness"]))
    assert "Target CPM" in result


def test_campaign_plan_daily_budget_correct(make_ctx):
    result = yap._cmd_ads_campaign_plan(make_ctx("ads_campaign_plan", ["300", "10", "subs"]))
    assert "30.00" in result  # 300/10=30


# ── register ─────────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    yap.register(FakeEngine)
    for cmd in ("ads_budget_calc", "ads_targeting_advisor", "ads_copy_score", "ads_campaign_plan"):
        assert cmd in FakeEngine.registry.names
