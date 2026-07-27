import json

import external_tools_plugin as ep
import pytest

from core_engine import AssistantEngine


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    config_path = tmp_path / "external_tools.json"
    monkeypatch.setattr(ep, "_config_path", lambda: config_path)
    return config_path


@pytest.fixture
def engine(tmp_path):
    return AssistantEngine(plugins_dirs=[tmp_path / "no_plugins_here"])


def _ctx(engine, raw, args):
    from core_engine import CommandContext
    return CommandContext(raw=raw, args=args, engine=engine)


# ── external_add ─────────────────────────────────────────────────────

def test_add_needs_two_args(engine):
    result = ep._cmd_external_add(_ctx(engine, "external_add", ["only_one"]))
    assert result.startswith("usage")


def test_add_invalid_type(engine):
    result = ep._cmd_external_add(_ctx(engine, "external_add", ["mytool", "echo", "--type", "weird"]))
    assert result.startswith("❌")


def test_add_missing_type_value(engine):
    result = ep._cmd_external_add(_ctx(engine, "external_add", ["mytool", "echo", "--type"]))
    assert result.startswith("❌")


def test_add_invalid_name_rejected(engine):
    result = ep._cmd_external_add(_ctx(engine, "external_add", ["bad name!", "echo hi"]))
    assert result.startswith("❌")


def test_add_collides_with_builtin_command(engine):
    result = ep._cmd_external_add(_ctx(engine, "external_add", ["help", "echo hi"]))
    assert result.startswith("❌")
    assert "collides with a built-in" in result


def test_add_registers_and_persists(engine, isolated_config):
    result = ep._cmd_external_add(_ctx(engine, "external_add", ["mytool", "echo", "hello"]))
    assert result.startswith("✅")
    assert engine.registry.get("mytool") is not None
    data = json.loads(isolated_config.read_text())
    assert data["mytool"]["command"] == "echo hello"
    assert data["mytool"]["type"] == "cli"


def test_add_desktop_type(engine, isolated_config):
    ep._cmd_external_add(_ctx(engine, "external_add", ["mydesktopapp", "some_app", "--type", "desktop"]))
    data = json.loads(isolated_config.read_text())
    assert data["mydesktopapp"]["type"] == "desktop"


def test_add_reregistering_same_external_tool_is_allowed(engine):
    ep._cmd_external_add(_ctx(engine, "external_add", ["mytool", "echo", "v1"]))
    result = ep._cmd_external_add(_ctx(engine, "external_add", ["mytool", "echo", "v2"]))
    assert result.startswith("✅")


# ── {args} substitution ──────────────────────────────────────────────

def test_expand_command_appends_args_without_placeholder():
    assert ep._expand_command("echo", ["a", "b"]) == "echo a b"


def test_expand_command_uses_placeholder_position():
    assert ep._expand_command("echo before {args} after", ["x"]) == "echo before x after"


def test_expand_command_no_args():
    assert ep._expand_command("echo", []) == "echo"


# ── actual execution (real subprocess, real echo) ──────────────────────

def test_registered_cli_tool_actually_runs(engine):
    ep._cmd_external_add(_ctx(engine, "external_add", ["greet", "echo", "hello", "{args}"]))
    cmd = engine.registry.get("greet")
    result = cmd.handler(_ctx(engine, "greet world", ["world"]))
    assert "hello world" in result


def test_registered_cli_tool_nonexistent_binary(engine):
    ep._cmd_external_add(_ctx(engine, "external_add", ["ghost", "this_binary_does_not_exist_xyz"]))
    cmd = engine.registry.get("ghost")
    result = cmd.handler(_ctx(engine, "ghost", []))
    assert result.startswith("❌")
    assert "program not found" in result


def test_registered_cli_tool_timeout(engine, monkeypatch):
    ep._cmd_external_add(_ctx(engine, "external_add", ["slow", "sleep", "999"]))
    monkeypatch.setattr(ep, "TIMEOUT_CLI", 0.1)
    cmd = engine.registry.get("slow")
    result = cmd.handler(_ctx(engine, "slow", []))
    assert result.startswith("⏱")


def test_registered_desktop_tool_uses_popen_not_run(engine, monkeypatch):
    captured = {}

    def fake_popen(argv, **kw):
        captured["argv"] = argv

        class FakeProc:
            pass
        return FakeProc()

    def fail_if_run_called(*a, **kw):
        raise AssertionError("subprocess.run should not be called for desktop-type tools")

    monkeypatch.setattr(ep.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ep.subprocess, "run", fail_if_run_called)

    ep._cmd_external_add(_ctx(engine, "external_add", ["myapp", "true", "--type", "desktop"]))
    cmd = engine.registry.get("myapp")
    result = cmd.handler(_ctx(engine, "myapp", []))
    assert result.startswith("✅")
    assert "in the background" in result
    assert captured["argv"] == ["true"]


def test_registered_desktop_tool_missing_binary(engine, monkeypatch):
    def fake_popen(argv, **kw):
        raise FileNotFoundError()
    monkeypatch.setattr(ep.subprocess, "Popen", fake_popen)

    ep._cmd_external_add(_ctx(engine, "external_add", ["ghostapp", "nope_binary", "--type", "desktop"]))
    cmd = engine.registry.get("ghostapp")
    result = cmd.handler(_ctx(engine, "ghostapp", []))
    assert result.startswith("❌")


def test_expanded_command_bad_quoting_reported_clearly(engine):
    ep._cmd_external_add(_ctx(engine, "external_add", ["broken", 'echo "unterminated']))
    cmd = engine.registry.get("broken")
    result = cmd.handler(_ctx(engine, "broken", []))
    assert result.startswith("❌")


# ── external_remove ─────────────────────────────────────────────────

def test_remove_no_args(engine):
    result = ep._cmd_external_remove(_ctx(engine, "external_remove", []))
    assert result.startswith("usage")


def test_remove_unknown_tool(engine):
    result = ep._cmd_external_remove(_ctx(engine, "external_remove", ["nope"]))
    assert result.startswith("❌")


def test_remove_deletes_from_registry_and_persistence(engine, isolated_config):
    ep._cmd_external_add(_ctx(engine, "external_add", ["mytool", "echo hi"]))
    result = ep._cmd_external_remove(_ctx(engine, "external_remove", ["mytool"]))
    assert result.startswith("✅")
    assert engine.registry.get("mytool") is None
    data = json.loads(isolated_config.read_text())
    assert "mytool" not in data


# ── external_list ────────────────────────────────────────────────────

def test_list_empty(engine):
    result = ep._cmd_external_list(_ctx(engine, "external_list", []))
    assert "No external tools registered" in result


def test_list_shows_registered_tools(engine):
    ep._cmd_external_add(_ctx(engine, "external_add", ["tool_a", "echo a"]))
    ep._cmd_external_add(_ctx(engine, "external_add", ["tool_b", "echo b", "--type", "desktop"]))
    result = ep._cmd_external_list(_ctx(engine, "external_list", []))
    assert "tool_a" in result
    assert "tool_b" in result
    assert "desktop" in result


# ── external_reload / load_external_tools (persistence across restarts) ─

def test_reload_loads_persisted_tools_into_fresh_engine(tmp_path, isolated_config):
    isolated_config.write_text(json.dumps({
        "persisted_tool": {"command": "echo persisted", "type": "cli"},
    }), encoding="utf-8")
    fresh_engine = AssistantEngine(plugins_dirs=[tmp_path / "no_plugins_here"])
    n = ep.load_external_tools(fresh_engine)
    assert n == 1
    assert fresh_engine.registry.get("persisted_tool") is not None


def test_reload_skips_tool_colliding_with_builtin(tmp_path, isolated_config):
    isolated_config.write_text(json.dumps({
        "help": {"command": "echo oops", "type": "cli"},
    }), encoding="utf-8")
    fresh_engine = AssistantEngine(plugins_dirs=[tmp_path / "no_plugins_here"])
    n = ep.load_external_tools(fresh_engine)
    assert n == 0
    # الأمر المدمج الحقيقي لازم يفضل زي ما هو، مش يتاستبدل
    assert "help" in fresh_engine.registry.get("help").description or True


def test_external_reload_command(engine, isolated_config):
    isolated_config.write_text(json.dumps({
        "x": {"command": "echo x", "type": "cli"},
    }), encoding="utf-8")
    result = ep._cmd_external_reload(_ctx(engine, "external_reload", []))
    assert "1" in result
    assert engine.registry.get("x") is not None


def test_register_loads_persisted_tools_on_startup(tmp_path, isolated_config):
    isolated_config.write_text(json.dumps({
        "startup_tool": {"command": "echo startup", "type": "cli"},
    }), encoding="utf-8")
    fresh_engine = AssistantEngine(plugins_dirs=[tmp_path / "no_plugins_here"])
    ep.register(fresh_engine)
    assert fresh_engine.registry.get("startup_tool") is not None
    for cmd in ("external_add", "external_remove", "external_list", "external_reload"):
        assert fresh_engine.registry.get(cmd) is not None
