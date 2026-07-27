import intents
import pytest


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(intents, "_cache_path", lambda: tmp_path / "intent_cache.json")


ALL = {r.command for r in intents.RULES} | {
    "probe", "virus_scan", "security_report", "help", "echo", "run", "convert",
}


# ── التطبيع العربي ───────────────────────────────────────────────────

def test_normalize_unifies_alef_forms():
    assert intents.normalize("إفحص") == intents.normalize("افحص")
    assert intents.normalize("أفحص") == intents.normalize("افحص")
    assert intents.normalize("آفحص") == intents.normalize("افحص")


def test_normalize_unifies_ta_marbuta_and_alef_maqsura():
    assert intents.normalize("قناة") == intents.normalize("قناه")
    assert intents.normalize("علي") == intents.normalize("على")


def test_normalize_strips_diacritics():
    assert intents.normalize("اِفْحَص") == "افحص"


def test_normalize_converts_arabic_digits():
    assert intents.normalize("٣ مرات") == "3 مرات"


def test_normalize_collapses_whitespace():
    assert intents.normalize("  افحص    الملف  ") == "افحص الملف"


# ── المطابقة الأساسية ────────────────────────────────────────────────

def test_exact_command_is_free_and_marked_exact():
    m = intents.resolve("virus_scan C:/x.exe", ALL)
    assert m.command == "virus_scan"
    assert m.source == "exact"
    assert m.is_complete()


def test_arabic_phrase_maps_to_command():
    m = intents.resolve("شوف الملف ده فيه فيروس ولا لأ", ALL)
    assert m.command == "virus_scan"
    assert m.source == "dict"


def test_phrase_with_different_alef_spelling_still_matches():
    assert intents.resolve("إفحص الملف ده أمنياً", ALL).command == "security_report"


def test_command_name_with_spaces_matches():
    m = intents.resolve("virus scan", ALL)
    assert m.command == "virus_scan"


def test_unknown_phrase_returns_none():
    assert intents.resolve("ايه رأيك في الفلسفة الوجودية", ALL) is None


def test_empty_text_returns_none():
    assert intents.resolve("   ", ALL) is None


def test_resolve_skips_rules_for_unregistered_commands():
    # لو الأمر مش مسجّل فعلاً (الـ plugin مش محمّل)، مالوش لازمة نقترحه
    assert intents.resolve("شوف الملف ده فيه فيروس", {"help"}) is None


# ── استخراج الوسائط ──────────────────────────────────────────────────

def test_quoted_path_is_extracted():
    m = intents.resolve('افحص "C:/My Files/report.pdf" أمنيًا', ALL)
    assert m.command == "security_report"
    assert "C:/My Files/report.pdf" in m.args
    assert m.is_complete()


def test_windows_path_is_extracted():
    m = intents.resolve(r"افحص C:\Users\me\file.exe فيروسات", ALL)
    assert r"C:\Users\me\file.exe" in m.args


def test_missing_path_is_reported_not_guessed():
    # مفيش مسار في الجملة — لازم نقول للواجهة تفتح نافذة اختيار،
    # مش نخترع مسار ولا نستدعي نموذج
    m = intents.resolve("افحص ملف أمنيًا", ALL)
    assert not m.is_complete()
    assert m.missing[0].kind == intents.FILE
    assert m.missing[0].prompt


def test_output_path_is_derived_from_input():
    m = intents.resolve("شيل الصمت من /home/u/vid.mp4", ALL)
    assert m.command == "auto_trim_silence"
    assert m.args[0] == "/home/u/vid.mp4"
    assert m.args[1] == "/home/u/vid_trimmed.mp4"
    assert m.is_complete()


def test_output_extension_override_is_applied():
    m = intents.resolve("استخرج الصوت من /home/u/clip.mp4", ALL)
    assert m.command == "extract_audio"
    assert m.args[1].endswith("_audio.mp3")


def test_number_is_extracted_from_arabic_digits():
    m = intents.resolve("سرع الفيديو /a/b.mp4 ٣ مرات", ALL)
    assert m.command == "speed_ramp"
    assert "3" in m.args


def test_number_falls_back_to_default_when_absent():
    m = intents.resolve("سرع الفيديو /a/b.mp4", ALL)
    assert "2" in m.args


def test_handle_is_extracted():
    m = intents.resolve("عايز تحليل نمو القناة @MrBeast", ALL)
    assert m.command == "channel_growth_report"
    assert "@MrBeast" in m.args


def test_url_is_extracted_as_handle():
    m = intents.resolve("احصائيات قناة https://youtube.com/@x", ALL)
    assert any(a.startswith("http") for a in m.args)


def test_rest_of_sentence_becomes_free_text_arg():
    m = intents.resolve("قولي صباح الخير يا نيزوكو", ALL)
    assert m.command == "speak"
    assert m.args == ["صباح الخير يا نيزوكو"]


def test_zero_arg_command_needs_nothing():
    m = intents.resolve("ايه الناقص عندي", ALL)
    assert m.command == "env_check"
    assert m.is_complete()
    assert m.args == []


# ── الأولوية ─────────────────────────────────────────────────────────

def test_higher_priority_rule_wins_over_generic_one():
    # "استخرج الصوت" أولوية أعلى من "حول الملف" العامة
    assert intents.resolve("استخرج الصوت من /a/v.mp4", ALL).command == "extract_audio"


def test_specific_upscale_video_beats_generic_image():
    assert intents.resolve("كبر الفيديو /a/v.mp4", ALL).command == "upscale_video"


# ── الذاكرة المتعلّمة ────────────────────────────────────────────────

def test_remembered_phrase_resolves_for_free_next_time():
    phrase = "بصلي الملف ده كده كده"
    assert intents.resolve(phrase, ALL) is None       # مش في القاموس
    intents.remember(phrase, "virus_scan")
    m = intents.resolve(phrase, ALL)
    assert m.command == "virus_scan"
    assert m.source == "cache"


def test_remember_is_normalization_insensitive():
    intents.remember("إفحصلي الملف", "virus_scan")
    # نفس الجملة بألف مختلفة لازم تلاقي نفس الربط
    assert intents.resolve("افحصلي الملف", ALL).command == "virus_scan"


def test_remember_ignores_empty_input():
    intents.remember("", "virus_scan")
    intents.remember("حاجة", "")
    assert intents.load_cache() == {}


def test_cache_survives_reload():
    intents.remember("جملة جديدة خالص", "help")
    assert intents.load_cache()[intents.normalize("جملة جديدة خالص")] == "help"


def test_forget_all_clears_cache():
    intents.remember("x y z", "help")
    assert intents.forget_all() == 1
    assert intents.load_cache() == {}


def test_cached_command_ignored_if_no_longer_registered():
    # الـ plugin اتشال بعد ما اتعلمنا الصيغة — منقترحش أمر مش موجود
    intents.remember("افتح الحاجة دي", "some_removed_command")
    assert intents.resolve("افتح الحاجة دي", ALL) is None


# ── سطر الأمر النهائي ────────────────────────────────────────────────

def test_command_line_quotes_paths_with_spaces():
    m = intents.IntentMatch("probe", ["C:/My Files/a.mp4"])
    assert m.command_line() == 'probe "C:/My Files/a.mp4"'


def test_command_line_leaves_simple_args_unquoted():
    assert intents.IntentMatch("probe", ["/a/b.mp4"]).command_line() == "probe /a/b.mp4"


# ── تقرير التغطية ────────────────────────────────────────────────────

def test_coverage_report_counts_dictionary_and_learned():
    rep = intents.coverage_report(ALL)
    assert rep["total"] == len(ALL)
    assert rep["dictionary"] > 0
    intents.remember("صيغة اتعلمتها", "echo")
    rep2 = intents.coverage_report(ALL)
    assert rep2["learned"] == 1


def test_coverage_report_lists_uncovered_commands():
    rep = intents.coverage_report(ALL | {"totally_unmapped_cmd"})
    assert "totally_unmapped_cmd" in rep["uncovered"]


# ── مساعدات الاستخراج ────────────────────────────────────────────────

def test_derive_output_keeps_directory():
    spec = intents.ArgSpec(intents.OUT, suffix="_x")
    assert intents.derive_output("/a/b/c.mp4", spec) == "/a/b/c_x.mp4"


def test_derive_output_applies_extension_override():
    spec = intents.ArgSpec(intents.OUT, suffix="_a", ext=".mp3")
    assert intents.derive_output("/a/v.mkv", spec) == "/a/v_a.mp3"


def test_extract_number_handles_decimals():
    assert intents.extract_number("سرعة 1.5 مرة") == "1.5"


def test_extract_handle_finds_channel_id():
    assert intents.extract_handle("قناة UCabcdefghijklmnopqrstuv").startswith("UC")
