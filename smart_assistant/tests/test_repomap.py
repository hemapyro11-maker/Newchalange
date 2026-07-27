"""اختبارات خريطة المشروع — الترتيب بالأهمية مش بالأبجدية."""
import pathlib

import core_engine
import pytest
import repomap

requires_ts = pytest.mark.skipif(
    not repomap.available(), reason="tree-sitter not installed"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    repomap.reset_cache()
    yield
    repomap.reset_cache()


def _write(root: pathlib.Path, name: str, body: str):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ── قراءة الرموز ─────────────────────────────────────────────────────

@requires_ts
def test_finds_functions_and_classes(tmp_path):
    p = _write(tmp_path, "a.py", "class Widget:\n    pass\n\ndef build(x):\n    return x\n")
    defs, _refs = repomap.scan_file(p)
    assert "Widget" in defs
    assert "build" in defs


@requires_ts
def test_references_exclude_own_definitions(tmp_path):
    """اسم معرّف في الملف ده مش "إشارة لبره" — وإلا كل ملف بيربط
    بنفسه والجراف بيبقى بلا معنى."""
    p = _write(tmp_path, "a.py", "def build():\n    return build\n")
    defs, refs = repomap.scan_file(p)
    assert "build" in defs
    assert "build" not in refs


@requires_ts
def test_picks_up_cross_file_references(tmp_path):
    _write(tmp_path, "core.py", "def shared():\n    return 1\n")
    p = _write(tmp_path, "user.py", "from core import shared\n\ndef go():\n    return shared()\n")
    _defs, refs = repomap.scan_file(p)
    assert "shared" in refs


def test_unknown_extension_is_skipped(tmp_path):
    p = _write(tmp_path, "notes.txt", "def build(): pass")
    assert repomap.scan_file(p) == (set(), set())


def test_unreadable_file_does_not_raise(tmp_path):
    missing = tmp_path / "gone.py"
    assert repomap.scan_file(missing) == (set(), set())


@requires_ts
def test_oversized_file_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(repomap, "_MAX_FILE_BYTES", 10)
    p = _write(tmp_path, "big.py", "def a():\n    pass\n" * 50)
    assert repomap.scan_file(p) == (set(), set())


# ── الترتيب ──────────────────────────────────────────────────────────

@requires_ts
def test_widely_used_file_outranks_a_leaf(tmp_path):
    """المبدأ كله: دالة بينادي عليها عشرين حتة أهم من helper بينادى
    عليه مرة — الترتيب هيكلي مش أبجدي."""
    _write(tmp_path, "core.py", "def shared():\n    return 1\n")
    _write(tmp_path, "zzz_leaf.py", "def lonely():\n    return 2\n")
    for i in range(6):
        _write(tmp_path, f"user{i}.py",
               "from core import shared\n\ndef go():\n    return shared()\n")

    out = repomap.build(tmp_path, budget_chars=4000)
    assert "core.py" in out
    assert out.index("core.py") < out.index("zzz_leaf.py")


@requires_ts
def test_mentioning_a_symbol_pulls_its_file_up(tmp_path):
    _write(tmp_path, "hub.py", "def central():\n    return 1\n")
    for i in range(6):
        _write(tmp_path, f"u{i}.py", "from hub import central\n\ndef g():\n    return central()\n")
    _write(tmp_path, "obscure.py", "def needle():\n    return 0\n")

    plain = repomap.build(tmp_path, budget_chars=4000)
    repomap.reset_cache()
    focused = repomap.build(tmp_path, mentioned={"needle"}, budget_chars=4000)

    assert plain.index("obscure.py") > plain.index("hub.py")
    assert focused.index("obscure.py") < focused.index("hub.py")


@requires_ts
def test_test_files_are_pushed_down(tmp_path):
    """ملف اختبارات بيعرّف عشرات الدوال وبيشاور على كل حاجة، فبيطلع
    فوق زورًا — وهو آخر حاجة بتعدّل فيها."""
    _write(tmp_path, "app.py", "def run():\n    return 1\n")
    body = "".join(f"def test_{i}():\n    return run()\n" for i in range(40))
    _write(tmp_path, "tests/test_app.py", "from app import run\n" + body)

    out = repomap.build(tmp_path, budget_chars=4000)
    assert out.index("app.py") < out.index("test_app.py")


# ── الميزانية والحدود ────────────────────────────────────────────────

@requires_ts
def test_output_respects_the_character_budget(tmp_path):
    for i in range(40):
        _write(tmp_path, f"m{i}.py", "".join(f"def f{j}():\n    pass\n" for j in range(20)))
    out = repomap.build(tmp_path, budget_chars=900)
    assert len(out) <= 1200      # سطر واحد ممكن يعدّي شوية، مش أضعاف


@requires_ts
def test_skips_vendor_and_build_directories(tmp_path):
    _write(tmp_path, "app.py", "def mine():\n    return 1\n")
    _write(tmp_path, "node_modules/pkg/index.js", "function theirs() { return 2 }\n")
    _write(tmp_path, ".venv/lib/thing.py", "def vendored():\n    return 3\n")

    out = repomap.build(tmp_path, budget_chars=4000)
    assert "mine" in out
    assert "theirs" not in out
    assert "vendored" not in out


def test_empty_directory_gives_empty_map(tmp_path):
    assert repomap.build(tmp_path) == ""


def test_missing_directory_gives_empty_map(tmp_path):
    assert repomap.build(tmp_path / "nope") == ""


def test_map_is_empty_without_tree_sitter(tmp_path, monkeypatch):
    """اختياري بالكامل — من غير tree-sitter كل حاجة تفضل شغالة."""
    _write(tmp_path, "a.py", "def x():\n    pass\n")
    monkeypatch.setattr(repomap, "available", lambda: False)
    assert repomap.build(tmp_path) == ""


# ── الكاش ────────────────────────────────────────────────────────────

@requires_ts
def test_second_build_reuses_the_scan(tmp_path, monkeypatch):
    """تحليل المشروع بياخد ثواني — مينفعش يتعاد مع كل رسالة."""
    _write(tmp_path, "a.py", "def x():\n    pass\n")
    repomap.build(tmp_path)

    calls = []
    real = repomap.scan_file
    monkeypatch.setattr(repomap, "scan_file",
                        lambda p: (calls.append(p), real(p))[1])
    repomap.build(tmp_path)
    assert calls == []


@requires_ts
def test_editing_a_file_invalidates_the_cache(tmp_path):
    _write(tmp_path, "a.py", "def before():\n    pass\n")
    first = repomap.build(tmp_path)
    assert "before" in first

    import os
    p = _write(tmp_path, "a.py", "def after():\n    pass\n")
    os.utime(p, (p.stat().st_atime + 10, p.stat().st_mtime + 10))

    second = repomap.build(tmp_path)
    assert "after" in second


# ── PageRank نفسها ───────────────────────────────────────────────────

def test_pagerank_sums_to_one():
    edges = {"a": {"b": 1.0}, "b": {"c": 1.0}, "c": {"a": 1.0}}
    rank = repomap._pagerank(edges, {k: 1.0 for k in edges})
    assert abs(sum(rank.values()) - 1.0) < 1e-6


def test_pagerank_favours_the_node_everyone_points_at():
    edges = {"a": {"hub": 1.0}, "b": {"hub": 1.0}, "c": {"hub": 1.0}, "hub": {}}
    rank = repomap._pagerank(edges, {k: 1.0 for k in edges})
    assert max(rank, key=rank.get) == "hub"


def test_pagerank_on_an_empty_graph():
    assert repomap._pagerank({}, {}) == {}


def test_dangling_node_does_not_leak_rank():
    """عقدة بلا حواف خارجة بتاخد رتبة ومتوزّعهاش — من غير معالجة
    صريحة المجموع بينزل تحت 1 والترتيب بيتشوّه."""
    edges = {"a": {"dead": 1.0}, "dead": {}}
    rank = repomap._pagerank(edges, {"a": 1.0, "dead": 1.0})
    assert abs(sum(rank.values()) - 1.0) < 1e-6


# ── الوصل بالمحرك ────────────────────────────────────────────────────

def test_engine_only_maps_when_the_talk_is_about_code(bare_engine):
    assert bare_engine._looks_like_code_work("fix the bug in listen") is True
    assert bare_engine._looks_like_code_work("صلّح الباج ده") is True
    assert bare_engine._looks_like_code_work("إزيك عاملة إيه") is False
    assert bare_engine._looks_like_code_work("hi there") is False


def test_engine_skips_the_map_for_small_talk(bare_engine, monkeypatch):
    """الخريطة بتاخد ~2000 توكن — حطّها في "إزيك" هدر خالص."""
    called = []
    monkeypatch.setattr(repomap, "build",
                        lambda *a, **k: (called.append(1), "MAP")[1])
    assert bare_engine._repo_context("إزيك") == ""
    assert called == []


def test_engine_asks_for_the_map_on_code_talk(bare_engine, monkeypatch):
    monkeypatch.setattr(repomap, "build", lambda *a, **k: "MAP")
    assert bare_engine._repo_context("there is a bug in the code") == "MAP"


def test_mentioned_symbols_are_passed_through(bare_engine, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        repomap, "build",
        lambda root, mentioned=None, budget_chars=0: (
            seen.update(mentioned=mentioned or set()), "MAP")[1],
    )
    bare_engine._repo_context("the bug is in _record_until_silence")
    assert "_record_until_silence" in seen["mentioned"]


def test_a_broken_map_never_blocks_the_reply(bare_engine, monkeypatch):
    """الخريطة تحسين مش شرط — لو فشلت لازم الرد يكمّل عادي."""
    def boom(*a, **k):
        raise RuntimeError("tree-sitter exploded")
    monkeypatch.setattr(repomap, "build", boom)
    assert bare_engine._repo_context("fix the bug in the code") == ""


def test_the_map_reaches_the_model(bare_engine, monkeypatch):
    import brain
    seen = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(repomap, "build", lambda *a, **k: "REPO MAP HERE")
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            seen.update(system=messages[0]["content"]),
            brain.BrainReply(text="ok", provider="f", label="F"),
        ][1],
    )
    bare_engine._converse("there is a bug in the code")
    assert "REPO MAP HERE" in seen["system"]


def test_the_chain_limit_is_high_enough_for_real_code_work():
    """"شغّل الاختبارات → اقرا الخطأ → صلّح → شغّل تاني → أكّد" لوحدها
    خمس خطوات. السقف القديم (4) كان بيقطع في النص."""
    assert core_engine._MAX_TOOL_STEPS >= 8
