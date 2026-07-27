import brain
import hooks
import permissions
import pytest
import sessions
import system_plugin as sp


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(brain, "_HAS_KEYRING", False)
    monkeypatch.setattr(hooks, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(sessions, "_base_dir", lambda: tmp_path)
    brain.reset_brain()
    yield
    brain.reset_brain()


def _msgs(*texts):
    out = []
    for t in texts:
        out += [{"role": "user", "content": t}, {"role": "assistant", "content": "رد"}]
    return out


# ── الجلسات ──────────────────────────────────────────────────────────

def test_sessions_empty_message(make_ctx):
    assert "No saved conversations" in sp._cmd_sessions(make_ctx("sessions", []))


def test_sessions_lists_saved_ones(make_ctx):
    sessions.save("s1", _msgs("افحص الملف"))
    out = sp._cmd_sessions(make_ctx("sessions", []))
    assert "s1" in out
    assert "افحص الملف" in out


def test_session_open_loads_into_the_engine(make_ctx, bare_engine):
    sessions.save("s1", _msgs("كلام قديم"))
    out = sp._cmd_session_open(make_ctx("session_open s1", ["s1"], engine=bare_engine))
    assert "✅" in out
    assert bare_engine.session_id == "s1"
    assert bare_engine.chat_history == _msgs("كلام قديم")


def test_session_open_unknown_id(make_ctx, bare_engine):
    out = sp._cmd_session_open(make_ctx("session_open x", ["x"], engine=bare_engine))
    assert out.startswith("❌")


def test_session_open_without_args_shows_usage(make_ctx):
    assert sp._cmd_session_open(make_ctx("session_open", [])).startswith("usage")


def test_session_delete_removes_one(make_ctx):
    sessions.save("s1", _msgs("حاجة"))
    sp._cmd_session_delete(make_ctx("session_delete s1", ["s1"]))
    assert sessions.load("s1") is None


def test_session_delete_all(make_ctx):
    sessions.save("s1", _msgs("a"))
    sessions.save("s2", _msgs("b"))
    out = sp._cmd_session_delete(make_ctx("session_delete --all", ["--all"]))
    assert "2" in out
    assert sessions.list_all() == []


# ── الصلاحيات ────────────────────────────────────────────────────────

def test_allow_adds_permission(make_ctx):
    sp._cmd_allow(make_ctx("allow probe", ["probe"]))
    assert permissions.is_allowed("probe") is True


def test_allow_refuses_dangerous_command(make_ctx):
    out = sp._cmd_allow(make_ctx("allow run", ["run"]))
    assert "never be allowed" in out
    assert permissions.is_allowed("run") is False


def test_allow_without_args_shows_usage(make_ctx):
    assert sp._cmd_allow(make_ctx("allow", [])).startswith("usage")


def test_allow_list_shows_empty_default(make_ctx):
    out = sp._cmd_allow_list(make_ctx("allow_list", []))
    assert "none" in out
    assert "run" in out  # الممنوعة نهائيًا معروضة برضه


def test_allow_list_shows_granted(make_ctx):
    permissions.allow("probe")
    assert "probe" in sp._cmd_allow_list(make_ctx("allow_list", []))


def test_disallow_revokes(make_ctx):
    permissions.allow("probe")
    sp._cmd_disallow(make_ctx("disallow probe", ["probe"]))
    assert permissions.is_allowed("probe") is False


def test_disallow_all(make_ctx):
    permissions.allow("probe")
    permissions.allow("hexdump")
    out = sp._cmd_disallow(make_ctx("disallow --all", ["--all"]))
    assert "2" in out


def test_disallow_unknown(make_ctx):
    assert sp._cmd_disallow(make_ctx("disallow x", ["x"])).startswith("❌")


# ── الأحداث ──────────────────────────────────────────────────────────

def test_hook_without_args_shows_usage(make_ctx):
    assert "usage" in sp._cmd_hook(make_ctx("hook", []))


def test_hook_list_when_empty(make_ctx):
    assert "nothing bound" in sp._cmd_hook(make_ctx("hook list", ["list"]))


def test_hook_add_then_list(make_ctx):
    sp._cmd_hook(make_ctx("hook add startup echo hi", ["add", "startup", "echo", "hi"]))
    out = sp._cmd_hook(make_ctx("hook list", ["list"]))
    assert "echo hi" in out
    assert "startup" in out


def test_hook_add_rejects_bad_event(make_ctx):
    out = sp._cmd_hook(make_ctx("hook add nope echo", ["add", "nope", "echo"]))
    assert "unknown event" in out


def test_hook_add_needs_a_command(make_ctx):
    assert "usage" in sp._cmd_hook(make_ctx("hook add startup", ["add", "startup"]))


def test_hook_remove(make_ctx):
    sp._cmd_hook(make_ctx("x", ["add", "startup", "echo", "hi"]))
    out = sp._cmd_hook(make_ctx("x", ["remove", "startup", "echo", "hi"]))
    assert "unbound" in out
    assert hooks.commands_for("startup") == []


def test_hook_remove_unknown(make_ctx):
    assert sp._cmd_hook(make_ctx("x", ["remove", "startup", "nope"])).startswith("❌")


def test_hook_clear(make_ctx):
    sp._cmd_hook(make_ctx("x", ["add", "startup", "a"]))
    sp._cmd_hook(make_ctx("x", ["add", "on_error", "b"]))
    assert "2" in sp._cmd_hook(make_ctx("hook clear", ["clear"]))


# ── التسجيل ──────────────────────────────────────────────────────────

def test_register_adds_all_commands(bare_engine):
    sp.register(bare_engine)
    for cmd in ("sessions", "session_open", "session_delete",
                "allow", "allow_list", "disallow", "hook"):
        assert bare_engine.registry.get(cmd) is not None
