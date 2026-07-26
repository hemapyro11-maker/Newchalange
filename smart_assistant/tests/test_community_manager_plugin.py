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
    assert "across 4 comments" in result
    assert "positive: 2" in result
    assert "negative: 1" in result
    assert "neutral: 1" in result


def test_sentiment_multi_line_lists_negative_comments(make_ctx, tmp_path):
    f = tmp_path / "comments.txt"
    f.write_text("حلو جدا\nالفيديو ده وحش وفاشل\n", encoding="utf-8")
    result = cmp._cmd_comment_sentiment(make_ctx("comment_sentiment", [str(f)]))
    assert "Negative comments worth a look" in result
    assert "وحش وفاشل" in result


# ── comment_spam_detect ────────────────────────────────────────────────

def test_spam_detect_no_args(make_ctx):
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect", []))
    assert result.startswith("usage")


def test_spam_detect_normal_comment(make_ctx):
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect فيديو حلو استفدت كتير شكرا", []))
    assert "looks genuine" in result


def test_spam_detect_link_and_promo_phrase(make_ctx):
    result = cmp._cmd_comment_spam_detect(
        make_ctx("comment_spam_detect اشترك في قناتي دلوقتي https://spam.example.com", [])
    )
    assert "🚩" in result
    assert "contains a link" in result


def test_spam_detect_repeated_chars(make_ctx):
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect واووووووووو", []))
    assert "unnaturally repeated characters" in result


def test_spam_detect_multi_line_file(make_ctx, tmp_path):
    f = tmp_path / "comments.txt"
    f.write_text(
        "فيديو حلو جدا شكرا\nاشترك في قناتي https://spam.com دخل قناتي\n",
        encoding="utf-8",
    )
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect", [str(f)]))
    assert "1 suspicious" in result


def test_spam_detect_all_clean_reports_ok(make_ctx, tmp_path):
    f = tmp_path / "comments.txt"
    f.write_text("حلو\nجميل\nرائع\n", encoding="utf-8")
    result = cmp._cmd_comment_spam_detect(make_ctx("comment_spam_detect", [str(f)]))
    assert "nothing suspicious" in result


# ── reply_template ────────────────────────────────────────────────────

def test_reply_template_no_args(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", []))
    assert result.startswith("usage")


def test_reply_template_invalid_tone(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["نص", "tone=angry"]))
    assert result.startswith("❌")


def test_reply_template_question_detected(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["ده", "شغال", "ازاي؟", "tone=friendly"]))
    assert "question" in result


def test_reply_template_compliment_detected(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["الفيديو", "ده", "رائع", "شكرا", "tone=professional"]))
    assert "compliment" in result


def test_reply_template_complaint_detected(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["الفيديو", "ده", "وحش", "وفاشل", "tone=friendly"]))
    assert "complaint" in result


def test_reply_template_generic_fallback(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["تمام", "كده", "tone=funny"]))
    assert "generic" in result


def test_reply_template_default_tone_is_friendly(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["تمام"]))
    assert "friendly" in result


def test_reply_template_spam_comment_suggests_no_reply(make_ctx):
    result = cmp._cmd_reply_template(
        make_ctx("reply_template", ["اشترك", "في", "قناتي", "https://spam.com", "دخل", "قناتي"])
    )
    assert "better not to reply" in result


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
    for day in cmp._DAY_NAMES:
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


# ── الرد بلغة التعليق ────────────────────────────────────────────────

def test_reply_to_an_english_comment_is_in_english(make_ctx):
    """الرد بيروح لجمهورك — رد بلغة غلط أسوأ من مفيش رد."""
    result = cmp._cmd_reply_template(
        make_ctx("reply_template", ["this", "was", "genuinely", "helpful", "thanks"])
    )
    assert "replying in: en" in result
    assert not any("؀" <= ch <= "ۿ" for ch in result.split("Suggested reply:")[1])


def test_reply_to_an_arabic_comment_is_in_arabic(make_ctx):
    result = cmp._cmd_reply_template(make_ctx("reply_template", ["الفيديو", "ده", "تحفة", "شكرا"]))
    assert "replying in: ar" in result
    assert any("؀" <= ch <= "ۿ" for ch in result.split("Suggested reply:")[1])


def test_every_category_and_tone_exists_in_both_languages():
    ar, en = cmp._REPLY_TEMPLATES["ar"], cmp._REPLY_TEMPLATES["en"]
    assert set(ar) == set(en)
    assert len(ar) == 12      # 4 أنواع × 3 نبرات
