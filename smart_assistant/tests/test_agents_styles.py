import agents
import agents_plugin as ap
import brain
import pytest
import styles


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(styles, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(brain, "_HAS_KEYRING", False)
    brain.reset_brain()
    yield
    brain.reset_brain()


AGENT_FILE = """---
name: reviewer
description: reviews code
tools: code_scan, strings
---

You are a careful reviewer.
"""


# ── تحليل ملف الـ agent ──────────────────────────────────────────────

def test_parse_reads_header_and_body():
    a = agents.parse(AGENT_FILE)
    assert a["name"] == "reviewer"
    assert a["description"] == "reviews code"
    assert a["tools"] == ["code_scan", "strings"]
    assert "careful reviewer" in a["instructions"]


def test_parse_without_header_still_works():
    """ملف من غير ترويسة لسه صالح — أسهل على المستخدم من إجباره على
    صيغة كاملة."""
    a = agents.parse("just instructions here", "myagent")
    assert a["name"] == "myagent"
    assert a["tools"] == []
    assert a["instructions"] == "just instructions here"


def test_parse_empty_body_returns_none():
    assert agents.parse("---\nname: x\n---\n\n   ") is None


def test_parse_ignores_malformed_header_lines():
    a = agents.parse("---\nname: x\ngarbage line\n---\nbody")
    assert a["name"] == "x"


# ── التخزين والقايمة ─────────────────────────────────────────────────

def test_save_then_load():
    agents.save("helper", "does things", "Be helpful.", ["echo"])
    loaded = agents.load_all()
    assert "helper" in loaded
    assert loaded["helper"]["tools"] == ["echo"]


def test_save_sanitises_the_filename():
    agents.save("a/b:c*d", "", "body")
    name = list(agents.agents_dir().glob("*.md"))[0].name
    assert all(ch not in name for ch in "/\\:*")


def test_get_returns_none_for_unknown():
    assert agents.get("nope") is None


def test_delete_removes_the_agent():
    agents.save("temp", "", "body")
    assert agents.delete("temp") is True
    assert agents.get("temp") is None


def test_delete_unknown_is_false():
    assert agents.delete("nope") is False


def test_starters_are_written_once():
    first = agents.write_starters()
    assert len(first) >= 3
    assert agents.write_starters() == []      # مش بيتكتبوا تاني


# ── تقييد الأدوات ────────────────────────────────────────────────────

def test_tools_are_filtered_to_what_is_actually_registered():
    """أسماء وهمية في tools: بتتشال بدل ما تتعرض على النموذج فيهلوس
    بيها."""
    agent = {"tools": ["echo", "does_not_exist"]}
    assert agents.allowed_tools(agent, {"echo", "help"}) == ["echo"]


def test_empty_tools_means_everything():
    assert agents.allowed_tools({"tools": []}, {"a", "b"}) == ["a", "b"]


def test_tools_never_widen_beyond_the_registry():
    agent = {"tools": ["run", "echo"]}
    assert "run" not in agents.allowed_tools(agent, {"echo"})


# ── التشغيل ──────────────────────────────────────────────────────────

def test_run_reports_unknown_agent(bare_engine):
    reply, _ = agents.run(bare_engine, "nope", "task")
    assert "no agent" in reply


def test_run_reports_missing_brain(bare_engine, monkeypatch):
    agents.save("a1", "", "instructions")
    monkeypatch.setattr(brain.Brain, "ready", lambda self: False)
    reply, _ = agents.run(bare_engine, "a1", "task")
    assert "brain_setup" in reply


def test_run_sends_only_the_agents_own_context(bare_engine, monkeypatch):
    """السياق منفصل: الـ agent مبيشوفش محادثتك — ده اللي بيوفّر التوكنز
    وبيسيب محادثتك نضيفة."""
    agents.save("a1", "", "You are a narrow specialist.", ["echo"])
    bare_engine.chat_history = [{"role": "user", "content": "SECRET HISTORY"}]
    captured = {}

    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: captured.setdefault("m", messages)
        and None or brain.BrainReply(text="ok", label="X"),
    )
    agents.run(bare_engine, "a1", "do the thing")
    blob = " ".join(m["content"] for m in captured["m"])
    assert "SECRET HISTORY" not in blob
    assert "narrow specialist" in blob


def test_run_only_lists_the_agents_allowed_tools(bare_engine, monkeypatch):
    agents.save("a1", "", "spec", ["echo"])
    captured = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: captured.setdefault("m", messages)
        and None or brain.BrainReply(text="ok", label="X"),
    )
    agents.run(bare_engine, "a1", "task")
    system = captured["m"][0]["content"]
    assert "echo —" in system
    assert "reload_plugins" not in system      # مش في أدواته


def test_run_returns_the_provider_label(bare_engine, monkeypatch):
    agents.save("a1", "", "spec")
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(text="done", label="Groq"),
    )
    reply, provider = agents.run(bare_engine, "a1", "task")
    assert reply == "done"
    assert provider == "Groq"


# ── أنماط الرد ───────────────────────────────────────────────────────

def test_default_style_is_active_initially():
    assert styles.current() == "default"


def test_every_builtin_style_has_a_prompt():
    for name, meta in styles.BUILTIN.items():
        assert meta["prompt"].strip(), name


def test_switching_style_persists():
    ok, _ = styles.set_current("concise")
    assert ok is True
    assert styles.current() == "concise"
    assert brain.load_config()["output_style"] == "concise"


def test_unknown_style_is_rejected():
    ok, msg = styles.set_current("nope")
    assert ok is False
    assert "unknown style" in msg


def test_prompt_for_returns_the_active_style_text():
    styles.set_current("concise")
    assert "one or two lines" in styles.prompt_for()


def test_prompt_for_named_style_ignores_the_active_one():
    styles.set_current("concise")
    assert "Teach as you answer" in styles.prompt_for("teacher")


def test_custom_style_from_a_file_is_picked_up():
    styles.save_custom("pirate", "Answer like a pirate.")
    assert "pirate" in styles.all_styles()
    styles.set_current("pirate")
    assert "like a pirate" in styles.prompt_for()


def test_custom_style_can_override_a_builtin():
    """المخصص بيغلب المدمج بنفس الاسم — فتقدر تستبدل نمط من غير ما
    تلمس الكود."""
    styles.save_custom("concise", "MY OWN CONCISE RULE")
    assert styles.prompt_for("concise") == "MY OWN CONCISE RULE"


def test_deleting_a_custom_style_restores_the_builtin():
    styles.save_custom("concise", "OVERRIDE")
    styles.delete_custom("concise")
    assert "one or two lines" in styles.prompt_for("concise")


def test_invalid_stored_style_falls_back_to_default():
    cfg = brain.load_config()
    cfg["output_style"] = "deleted-style"
    brain.save_config(cfg)
    assert styles.current() == "default"


def test_style_is_injected_into_the_engine_prompt(bare_engine, monkeypatch):
    """النمط بيغيّر الأسلوب بس — مش الأدوات ولا الصلاحيات."""
    styles.set_current("teacher")
    captured = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: captured.setdefault("m", messages)
        and None or brain.BrainReply(text="ok", label="X"),
    )
    bare_engine._converse("hello")
    assert "Teach as you answer" in captured["m"][0]["content"]


# ── الأوامر ──────────────────────────────────────────────────────────

def test_agents_command_writes_starters_and_lists_them(make_ctx, bare_engine):
    out = ap._cmd_agents(make_ctx("agents", [], engine=bare_engine))
    assert "code-reviewer" in out


def test_agent_command_needs_a_task(make_ctx, bare_engine):
    assert ap._cmd_agent(make_ctx("agent x", ["x"], engine=bare_engine)).startswith("usage")


def test_agent_command_passes_the_raw_task(make_ctx, bare_engine, monkeypatch):
    """المهمة بتتاخد من ctx.raw مش ctx.args — عشان متتقصّش."""
    seen = {}
    monkeypatch.setattr(agents, "run", lambda e, n, t: seen.update(task=t) or ("ok", "X"))
    ap._cmd_agent(make_ctx('agent a1 look at "my file.py" please',
                           ["a1", "look", "at", "my file.py", "please"],
                           engine=bare_engine))
    assert seen["task"] == 'look at "my file.py" please'


def test_agent_new_creates_a_file(make_ctx, bare_engine):
    out = ap._cmd_agent_new(make_ctx("agent_new tester Be a tester.",
                                     ["tester", "Be", "a", "tester."],
                                     engine=bare_engine))
    assert "saved" in out
    assert agents.get("tester") is not None


def test_agent_new_without_instructions_shows_usage(make_ctx, bare_engine):
    assert ap._cmd_agent_new(
        make_ctx("agent_new x", ["x"], engine=bare_engine)
    ).startswith("usage")


def test_agent_delete_command(make_ctx, bare_engine):
    agents.save("gone", "", "body")
    out = ap._cmd_agent_delete(make_ctx("agent_delete gone", ["gone"], engine=bare_engine))
    assert "deleted" in out


def test_styles_command_marks_the_active_one(make_ctx, bare_engine):
    styles.set_current("detailed")
    out = ap._cmd_styles(make_ctx("styles", [], engine=bare_engine))
    assert "❯ detailed" in out


def test_style_command_switches(make_ctx, bare_engine):
    ap._cmd_style(make_ctx("style concise", ["concise"], engine=bare_engine))
    assert styles.current() == "concise"


def test_style_command_without_args_reports_current(make_ctx, bare_engine):
    out = ap._cmd_style(make_ctx("style", [], engine=bare_engine))
    assert "Current style" in out


def test_register_adds_every_command(bare_engine):
    ap.register(bare_engine)
    for cmd in ("agents", "agent", "agent_new", "agent_delete", "style", "styles"):
        assert bare_engine.registry.get(cmd) is not None
