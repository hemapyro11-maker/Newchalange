import screenplay_plugin as scp

SAMPLE = """Title: Test Script
Credit: Written by

FADE IN:

INT. COFFEE SHOP - DAY

Ahmed sits alone at a table, staring at his laptop.

AHMED
This code better work this time.

He types furiously.

SARA (V.O.)
You always say that.

Ahmed looks up, startled.

AHMED
Sara? Where are you?

CUT TO:

EXT. STREET - NIGHT

Sara walks briskly down the empty street.

SARA
Right behind you, always.

FADE OUT.
"""


def test_fountain_stats_counts_scenes_correctly(make_ctx, tmp_path):
    f = tmp_path / "s.fountain"
    f.write_text(SAMPLE, encoding="utf-8")
    result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(f)]))
    assert "2 مشهد" in result
    assert "INT. COFFEE SHOP - DAY" in result
    assert "EXT. STREET - NIGHT" in result


def test_fountain_stats_counts_characters_and_dedupes_extensions(make_ctx, tmp_path):
    f = tmp_path / "s.fountain"
    f.write_text(SAMPLE, encoding="utf-8")
    result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(f)]))
    assert "2 شخصية" in result
    assert "AHMED" in result
    # "SARA (V.O.)" and plain "SARA" must dedupe to one character
    assert result.count("SARA") == 1


def test_fountain_stats_counts_dialogue_lines(make_ctx, tmp_path):
    f = tmp_path / "s.fountain"
    f.write_text(SAMPLE, encoding="utf-8")
    result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(f)]))
    assert "4 سطر حوار" in result


def test_fountain_stats_missing_file(make_ctx, tmp_path):
    result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(tmp_path / "nope.fountain")]))
    assert result.startswith("❌")


def test_fountain_stats_empty_file(make_ctx, tmp_path):
    f = tmp_path / "empty.fountain"
    f.write_text("", encoding="utf-8")
    result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(f)]))
    assert "فاضي" in result


def test_fountain_stats_no_scenes_or_characters(make_ctx, tmp_path):
    f = tmp_path / "justtext.fountain"
    f.write_text("This is just some plain narration with no structure.\n", encoding="utf-8")
    result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(f)]))
    assert "0 مشهد" in result
    assert "0 شخصية" in result


def test_page_estimate_scales_with_length(make_ctx, tmp_path):
    short = tmp_path / "short.fountain"
    short.write_text("INT. ROOM - DAY\n\nA short scene.\n", encoding="utf-8")
    long_text = "INT. ROOM - DAY\n\n" + "\n".join(f"Line {i} of action text here." for i in range(300))
    long_f = tmp_path / "long.fountain"
    long_f.write_text(long_text, encoding="utf-8")

    short_result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(short)]))
    long_result = scp._cmd_fountain_stats(make_ctx("fountain_stats", [str(long_f)]))
    assert "~1 " in short_result
    assert "~1 " not in long_result
