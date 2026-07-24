import community_manager_plugin as cmp

# ── comment_sentiment ──────────────────────────────────────────────────

def test_sentiment_no_args(make_ctx):
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment", []))
    assert result.startswith("usage")


def test_sentiment_positive_comment(make_ctx):
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment الفيديو ده حلو جدا شكرا", []))
    assert "positive" in result
    assert "😊" in result


def test_sentiment_negative_comment(make_ctx):
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment الفيديو ده وحش جدا", []))
    assert "negative" in result


def test_sentiment_negation_flips_polarity(make_ctx):
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment مش حلو خالص", []))
    assert "negative" in result


def test_sentiment_neutral_comment(make_ctx):
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment تمام كده", []))
    assert "neutral" in result


def test_sentiment_english_words(make_ctx):
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment this video is amazing thanks", []))
    assert "positive" in result


def test_sentiment_multi_line_file_aggregates(make_ctx, tmp_path):
    f = tmp_path / "comments.txt"
    f.write_text("حلو جدا شكرا\nوحش جدا\nتمام\nرائع تحفة\n", encoding="utf-8")
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment", [str(f)]))
    assert "4 تعليق" in result
    assert "إيجابي: 2" in result
    assert "سلبي: 1" in result
    assert "محايد: 1" in result


def test_sentiment_multi_line_lists_negative_comments(make_ctx, tmp_path):
    f = tmp_path / "comments.txt"
    f.write_text("حلو جدا\nالفيديو ده وحش وفاشل\n", encoding="utf-8")
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment", [str(f)]))
    assert "تستاهل مراجعة" in result
    assert "وحش وفاشل" in result


# ── comment_spam_detect ────────────────────────────────────────────────

def test_spam_detect_no_args(make_ctx):
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect", []))
    assert result.startswith("usage")


def test_spam_detect_normal_comment(make_ctx):
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect فيديو حلو استفدت كتير شكرا", []))
    assert "يبان طبيعي" in result


def test_spam_detect_link_and_promo_phrase(make_ctx):
    result = cmp._cmd_comment_spam_detect(
        make_ctx("comment_spam_detect اشترك في قناتي دلوقتي https://spam.example.com", [])
    )
    assert "🚩" in result
    assert "فيه رابط" in result


def test_spam_detect_repeated_chars(make_ctx):
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect واووووووووو", []))
    assert "حروف مكررة" in result


def test_spam_detect_multi_line_file(make_ctx, tmp_path):
    f = tmp_path / "comments.txt"
    f.write_text(
        "فيديو حلو جدا شكرا\nاشترك في قناتي https://spam.com دخل قناتي\n",
        encoding="utf-8",
    )
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect", [str(f)]))
    assert "1 مشتبه بيه" in result


def test_spam_detect_all_clean_reports_ok(make_ctx, tmp_path):
    f = tmp_path / "comments.txt"
    f.write_text("حلو\nجميل\nرائع\n", encoding="utf-8")
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect", [str(f)]))
    assert "مفيش تعليقات مشتبه فيها" in result


# ── reply_template ────────────────────────────────────────────────────

def test_reply_template_no_args(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", []))
    assert result.startswith("usage")


def test_reply_template_invalid_tone(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["نص", "tone=angry"]))
    assert result.startswith("❌")


def test_reply_template_question_detected(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["ده", "شغال", "ازاي؟", "tone=friendly"]))
    assert "سؤال" in result


def test_reply_template_compliment_detected(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["الفيديو", "ده", "رائع", "شكرا", "tone=professional"]))
    assert "مجاملة" in result


def test_reply_template_complaint_detected(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["الفيديو", "ده", "وحش", "وفاشل", "tone=friendly"]))
    assert "شكوى" in result


def test_reply_template_generic_fallback(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["تمام", "كده", "tone=funny"]))
    assert "عام" in result


def test_reply_template_default_tone_is_friendly(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["تمام"]))
    assert "friendly" in result


def test_reply_template_spam_comment_suggests_no_reply(make_ctx):
    result = cmp._cmd_reply_template(
        make_ctx("reply_template", ["اشترك", "في", "قناتي", "https://spam.com", "دخل", "قناتي"])
    )
    assert "متردش عليه" in result


# ── engagement_calendar ────────────────────────────────────────────────

def test_engagement_calendar_no_args(make_ctx):
    result = cmp._cmd_engagement_calendar(make_ctx("engagement_calendar", []))
    assert result.startswith("usage")


def test_engagement_calendar_invalid_number(make_ctx):
    result = cmp._cmd_engagement_calendar(make_ctx("engagement_calendar", ["abc"]))
    assert result.startswith("❌")


def test_engagement_calendar_out_of_range(make_ctx):
    result = cmp._cmd_engagement_calendar(make_ctx("engagement_calendar", ["8"]))
    assert result.startswith("❌")


def test_engagement_calendar_produces_correct_count(make_ctx):
    result = cmp._cmd_engagement_calendar(make_ctx("engagement_calendar", ["3"]))
    assert result.count("•") == 3


def test_engagement_calendar_rotates_post_types(make_ctx):
    result = cmp._cmd_engagement_calendar(make_ctx("engagement_calendar", ["7"]))
    for day in cmp._DAY_NAMES_AR:
        assert day in result


# ── register ─────────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    cmp.register(FakeEngine)
    for cmd in ("comment_sentiment", "comment_spam_detect", "reply_template", "engagement_calendar"):
        assert cmd in FakeEngine.registry.names
