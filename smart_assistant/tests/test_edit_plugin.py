"""اختبارات قراءة/تعديل الملفات — الحلقة اللي كانت مقطوعة في شغل الكود."""
import edit_plugin as ep
import permissions
import pytest


def _f(tmp_path, name="a.py", body="def go():\n    return 1\n"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ── read_file ────────────────────────────────────────────────────────

def test_read_shows_line_numbers(make_ctx, tmp_path):
    p = _f(tmp_path)
    out = ep._cmd_read_file(make_ctx("read_file", [str(p)]))
    assert "1  def go():" in out
    assert "2      return 1" in out


def test_read_reports_the_total_line_count(make_ctx, tmp_path):
    p = _f(tmp_path, body="a\nb\nc\n")
    assert "3 lines" in ep._cmd_read_file(make_ctx("read_file", [str(p)]))


def test_read_a_line_range(make_ctx, tmp_path):
    p = _f(tmp_path, body="one\ntwo\nthree\nfour\n")
    out = ep._cmd_read_file(make_ctx("read_file", [str(p), "2", "3"]))
    assert "two" in out and "three" in out
    assert "one" not in out and "four" not in out


def test_read_missing_file(make_ctx, tmp_path):
    assert ep._cmd_read_file(make_ctx("read_file", [str(tmp_path / "no.py")])).startswith("❌")


def test_read_without_args_shows_usage(make_ctx):
    assert ep._cmd_read_file(make_ctx("read_file", [])).startswith("usage")


def test_read_refuses_a_huge_file(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_MAX_READ_BYTES", 10)
    p = _f(tmp_path, body="x" * 200)
    out = ep._cmd_read_file(make_ctx("read_file", [str(p)]))
    assert "read limit" in out


def test_read_rejects_a_backwards_range(make_ctx, tmp_path):
    p = _f(tmp_path, body="a\nb\nc\n")
    out = ep._cmd_read_file(make_ctx("read_file", [str(p), "3", "1"]))
    assert "must not be before" in out


def test_read_rejects_a_non_numeric_range(make_ctx, tmp_path):
    p = _f(tmp_path)
    assert "whole number" in ep._cmd_read_file(make_ctx("read_file", [str(p), "x"]))


# ── فصل الكتل ────────────────────────────────────────────────────────

def test_parses_one_block():
    blocks = ep.parse_blocks(
        "edit_file a.py\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"
    )
    assert blocks == [("old\n", "new\n")]


def test_parses_several_blocks():
    raw = ("edit_file a.py\n"
           "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
           "<<<<<<< SEARCH\nc\n=======\nd\n>>>>>>> REPLACE")
    assert len(ep.parse_blocks(raw)) == 2


def test_text_without_a_block_parses_to_nothing():
    assert ep.parse_blocks("edit_file a.py\njust change the thing") == []


# ── edit_file ────────────────────────────────────────────────────────

def _edit(make_ctx, path, search, replace):
    raw = f"edit_file {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"
    return ep._cmd_edit_file(make_ctx(raw, [str(path)]))


def test_edit_replaces_the_text(make_ctx, tmp_path):
    p = _f(tmp_path)
    out = _edit(make_ctx, p, "return 1", "return 2")
    assert out.startswith("✅")
    assert "return 2" in p.read_text(encoding="utf-8")


def test_edit_keeps_a_backup(make_ctx, tmp_path):
    p = _f(tmp_path)
    _edit(make_ctx, p, "return 1", "return 2")
    backup = p.with_suffix(p.suffix + ep._BACKUP_SUFFIX)
    assert backup.is_file()
    assert "return 1" in backup.read_text(encoding="utf-8")


def test_edit_reports_the_line_delta(make_ctx, tmp_path):
    p = _f(tmp_path)
    out = _edit(make_ctx, p, "return 1", "x = 1\n    return x")
    assert "+1 lines" in out


def test_edit_refuses_when_the_text_is_not_there(make_ctx, tmp_path):
    p = _f(tmp_path)
    before = p.read_text(encoding="utf-8")
    out = _edit(make_ctx, p, "return 999", "return 2")
    assert "not found" in out
    assert p.read_text(encoding="utf-8") == before


def test_edit_refuses_an_ambiguous_match(make_ctx, tmp_path):
    """تعديل المكان الغلط أسوأ من عدم التعديل — الغلطة دي بتعدي من
    غير ما حد ياخد باله."""
    p = _f(tmp_path, body="x = 1\ny = 2\nx = 1\n")
    out = _edit(make_ctx, p, "x = 1", "x = 9")
    assert "appears 2 times" in out
    assert p.read_text(encoding="utf-8") == "x = 1\ny = 2\nx = 1\n"


def test_a_failing_block_writes_nothing_at_all(make_ctx, tmp_path):
    """كله أو ولا حاجة: تعديل نص الطريق بيسيب الملف مش القديم ولا الجديد."""
    p = _f(tmp_path, body="a = 1\nb = 2\n")
    raw = (f"edit_file {p}\n"
           "<<<<<<< SEARCH\na = 1\n=======\na = 9\n>>>>>>> REPLACE\n"
           "<<<<<<< SEARCH\nnot here\n=======\nz\n>>>>>>> REPLACE")
    out = ep._cmd_edit_file(make_ctx(raw, [str(p)]))
    assert "block 2 of 2" in out
    assert "unchanged" in out
    assert p.read_text(encoding="utf-8") == "a = 1\nb = 2\n"


def test_several_blocks_all_apply(make_ctx, tmp_path):
    p = _f(tmp_path, body="a = 1\nb = 2\n")
    raw = (f"edit_file {p}\n"
           "<<<<<<< SEARCH\na = 1\n=======\na = 9\n>>>>>>> REPLACE\n"
           "<<<<<<< SEARCH\nb = 2\n=======\nb = 8\n>>>>>>> REPLACE")
    ep._cmd_edit_file(make_ctx(raw, [str(p)]))
    assert p.read_text(encoding="utf-8") == "a = 9\nb = 8\n"


def test_edit_without_a_block_explains_the_format(make_ctx, tmp_path):
    p = _f(tmp_path)
    out = ep._cmd_edit_file(make_ctx(f"edit_file {p}\njust fix it", [str(p)]))
    assert "SEARCH" in out
    assert out.startswith("❌")


def test_edit_missing_file_points_at_create(make_ctx, tmp_path):
    missing = tmp_path / "nope.py"
    out = _edit(make_ctx, missing, "a", "b")
    assert "create_file" in out


def test_edit_without_args_shows_the_format(make_ctx):
    assert "SEARCH" in ep._cmd_edit_file(make_ctx("edit_file", []))


def test_a_no_op_edit_says_so(make_ctx, tmp_path):
    p = _f(tmp_path)
    out = _edit(make_ctx, p, "return 1", "return 1")
    assert "already like that" in out


def test_an_empty_search_appends(make_ctx, tmp_path):
    p = _f(tmp_path, body="a\n")
    raw = f"edit_file {p}\n<<<<<<< SEARCH\n=======\nb\n>>>>>>> REPLACE"
    ep._cmd_edit_file(make_ctx(raw, [str(p)]))
    assert p.read_text(encoding="utf-8") == "a\nb\n"


# ── create_file ──────────────────────────────────────────────────────

def test_create_writes_a_new_file(make_ctx, tmp_path):
    p = tmp_path / "new.py"
    out = ep._cmd_create_file(make_ctx(f"create_file {p} print('hi')", [str(p)]))
    assert out.startswith("✅")
    assert p.read_text(encoding="utf-8") == "print('hi')"


def test_create_makes_parent_directories(make_ctx, tmp_path):
    p = tmp_path / "deep" / "down" / "new.py"
    ep._cmd_create_file(make_ctx(f"create_file {p} x", [str(p)]))
    assert p.is_file()


def test_create_refuses_to_overwrite(make_ctx, tmp_path):
    """الكتابة فوق ملف موجود بتضيّع شغل — لازم تعدي على edit_file."""
    p = _f(tmp_path)
    out = ep._cmd_create_file(make_ctx(f"create_file {p} whatever", [str(p)]))
    assert "already exists" in out
    assert "return 1" in p.read_text(encoding="utf-8")


def test_create_without_args_shows_usage(make_ctx):
    assert ep._cmd_create_file(make_ctx("create_file", [])).startswith("usage")


# ── الأمان ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", ["edit_file", "create_file"])
def test_writing_commands_can_never_be_auto_allowed(cmd):
    """بتكتب محتوى حر على القرص — تعديل ملف .py هو كود هيتنفذ بعدين،
    فده تنفيذ مؤجل مش مجرد كتابة."""
    assert cmd in permissions.never_allowed()
    ok, msg = permissions.allow(cmd)
    assert ok is False
    assert "never be allowed" in msg


def test_read_file_may_be_allowed(bare_engine):
    """القراءة مالهاش أثر — منطقي تعدي من غير سؤال لو المستخدم حب."""
    assert "read_file" not in permissions.never_allowed()


def test_register_adds_all_three(bare_engine):
    ep.register(bare_engine)
    for name in ("read_file", "edit_file", "create_file"):
        assert bare_engine.registry.get(name) is not None
