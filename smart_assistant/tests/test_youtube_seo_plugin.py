import youtube_seo_plugin as ysp

# ── seo_title_score ──────────────────────────────────────────────────────

def test_title_score_no_args(make_ctx):
    result = ysp._cmd_seo_title_score(make_ctx("seo_title_score", []))
    assert result.startswith("usage")


def test_title_score_ideal_length(make_ctx):
    title = "أفضل 7 طرق لتعلم بايثون بسرعة في 2025 - دليل شامل"  # ~50 حرف
    result = ysp._cmd_seo_title_score(make_ctx(f"seo_title_score {title}", []))
    assert "excellent length" in result or "ideal" in result


def test_title_score_too_long_gets_penalized(make_ctx):
    long_title = "كلمة " * 30
    result = ysp._cmd_seo_title_score(make_ctx(f"seo_title_score {long_title}", []))
    assert "cut it off" in result or "is long" in result


def test_title_score_with_number_bonus(make_ctx):
    result = ysp._cmd_seo_title_score(make_ctx("seo_title_score 5 اسرار للنجاح", []))
    assert "contains a number" in result


def test_title_score_all_caps_penalized(make_ctx):
    result = ysp._cmd_seo_title_score(make_ctx("seo_title_score THIS IS SUPER SHOUTY CLICKBAIT TITLE", []))
    assert "سبام" in result or "❌" in result


def test_title_score_excessive_punctuation(make_ctx):
    result = ysp._cmd_seo_title_score(make_ctx("seo_title_score شاهد ده دلوقتي!!!؟؟؟", []))
    assert "repeated punctuation" in result


def test_title_score_returns_numeric_score(make_ctx):
    import re
    result = ysp._cmd_seo_title_score(make_ctx("seo_title_score عنوان بسيط", []))
    m = re.search(r"Score: (\d+)/100", result)
    assert m
    assert 0 <= int(m.group(1)) <= 100


# ── seo_description_score ────────────────────────────────────────────────

def test_description_score_no_args(make_ctx):
    result = ysp._cmd_seo_description_score(make_ctx("seo_description_score", []))
    assert result.startswith("usage")


def test_description_score_too_short(make_ctx):
    result = ysp._cmd_seo_description_score(make_ctx("seo_description_score وصف قصير", []))
    assert "short" in result


def test_description_score_good_length_with_link_and_timestamps(make_ctx):
    desc = (
        "في الفيديو ده هنشرح كل حاجة عن الموضوع بالتفصيل من الألف للياء. " * 5
        + "\n0:00 مقدمة\n1:30 الشرح\n5:00 خاتمة\nتابعنا: https://example.com"
    )
    result = ysp._cmd_seo_description_score(make_ctx(f"seo_description_score {desc}", []))
    assert "contains a link" in result
    assert "timestamps" in result


def test_description_score_too_many_hashtags(make_ctx):
    desc = ("محتوى الوصف هنا كافي عشان يبقى طويل بما فيه الكفاية للاختبار ده. " * 3
            + " #a #b #c #d #e")
    result = ysp._cmd_seo_description_score(make_ctx(f"seo_description_score {desc}", []))
    assert "5 hashtags" in result


def test_description_score_from_file(make_ctx, tmp_path):
    f = tmp_path / "desc.txt"
    f.write_text("وصف طويل شوية من ملف. " * 20, encoding="utf-8")
    result = ysp._cmd_seo_description_score(make_ctx("seo_description_score", [str(f)]))
    assert "Description review" in result


# ── seo_tags_suggest ──────────────────────────────────────────────────────

def test_tags_suggest_needs_two_files(make_ctx):
    result = ysp._cmd_seo_tags_suggest(make_ctx("seo_tags_suggest", ["one.txt"]))
    assert result.startswith("usage")


def test_tags_suggest_missing_file(make_ctx, tmp_path):
    result = ysp._cmd_seo_tags_suggest(make_ctx("seo_tags_suggest", [str(tmp_path / "nope1.txt"), str(tmp_path / "nope2.txt")]))
    assert result.startswith("❌")


def test_tags_suggest_extracts_title_keywords(make_ctx, tmp_path):
    title_f = tmp_path / "title.txt"
    desc_f = tmp_path / "desc.txt"
    title_f.write_text("تعلم بايثون للمبتدئين", encoding="utf-8")
    desc_f.write_text("في الفيديو ده هنتعلم بايثون خطوة بخطوة مع أمثلة عملية كتيرة", encoding="utf-8")
    result = ysp._cmd_seo_tags_suggest(make_ctx("seo_tags_suggest", [str(title_f), str(desc_f)]))
    assert "بايثون" in result
    assert "Candidate keywords" in result


def test_tags_suggest_all_stopwords_returns_error(make_ctx, tmp_path):
    title_f = tmp_path / "title.txt"
    desc_f = tmp_path / "desc.txt"
    title_f.write_text("في من على", encoding="utf-8")
    desc_f.write_text("the a an", encoding="utf-8")
    result = ysp._cmd_seo_tags_suggest(make_ctx("seo_tags_suggest", [str(title_f), str(desc_f)]))
    assert result.startswith("❌")


# ── seo_tags_audit ────────────────────────────────────────────────────────

def test_tags_audit_no_args(make_ctx):
    result = ysp._cmd_seo_tags_audit(make_ctx("seo_tags_audit", []))
    assert result.startswith("usage")


def test_tags_audit_within_budget(make_ctx):
    result = ysp._cmd_seo_tags_audit(make_ctx("seo_tags_audit بايثون, تعلم بايثون, برمجة", []))
    assert "✅" in result


def test_tags_audit_over_budget(make_ctx):
    long_tag = "كلمة طويلة جدا " * 10
    tags = ", ".join([long_tag] * 5)
    result = ysp._cmd_seo_tags_audit(make_ctx(f"seo_tags_audit {tags}", []))
    assert "over YouTube" in result


def test_tags_audit_detects_duplicates(make_ctx):
    result = ysp._cmd_seo_tags_audit(make_ctx("seo_tags_audit بايثون, Python, بايثون", []))
    assert "duplicate tags" in result


def test_tags_audit_detects_near_duplicates_singular_plural(make_ctx):
    result = ysp._cmd_seo_tags_audit(make_ctx("seo_tags_audit cat, cats, dog", []))
    assert "near-duplicate tags" in result


def test_tags_audit_reports_broad_vs_specific(make_ctx):
    result = ysp._cmd_seo_tags_audit(make_ctx("seo_tags_audit python, python tutorial for beginners", []))
    assert "broad tags" in result


# ── seo_full_audit ────────────────────────────────────────────────────────

def test_full_audit_needs_three_args(make_ctx):
    result = ysp._cmd_seo_full_audit(make_ctx("seo_full_audit", ["a.txt", "b.txt"]))
    assert result.startswith("usage")


def test_full_audit_missing_files(make_ctx, tmp_path):
    result = ysp._cmd_seo_full_audit(make_ctx(
        "seo_full_audit", [str(tmp_path / "nope1.txt"), str(tmp_path / "nope2.txt"), "tag1,tag2"]
    ))
    assert result.startswith("❌")


def test_full_audit_combines_all_scores(make_ctx, tmp_path):
    title_f = tmp_path / "title.txt"
    desc_f = tmp_path / "desc.txt"
    title_f.write_text("أفضل 5 طرق لتعلم البايثون في 2025", encoding="utf-8")
    desc_f.write_text("شرح تفصيلي لتعلم بايثون من الصفر. " * 15 + "0:00 مقدمة\n2:00 شرح", encoding="utf-8")
    result = ysp._cmd_seo_full_audit(make_ctx(
        "seo_full_audit", [str(title_f), str(desc_f), "بايثون, تعلم بايثون, برمجة"]
    ))
    assert "Overall score" in result
    assert "Title" in result
    assert "Description" in result
    assert "Tags" in result


def test_full_audit_no_tags_flagged(make_ctx, tmp_path):
    title_f = tmp_path / "title.txt"
    desc_f = tmp_path / "desc.txt"
    title_f.write_text("عنوان", encoding="utf-8")
    desc_f.write_text("وصف بسيط جدا للاختبار فقط بدون اي محتوى حقيقي هنا خالص", encoding="utf-8")
    result = ysp._cmd_seo_full_audit(make_ctx("seo_full_audit", [str(title_f), str(desc_f), ""]))
    assert "no tags at all" in result


# ── register ─────────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    ysp.register(FakeEngine)
    for cmd in ("seo_title_score", "seo_description_score", "seo_tags_suggest",
                "seo_tags_audit", "seo_full_audit"):
        assert cmd in FakeEngine.registry.names
