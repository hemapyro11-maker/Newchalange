"""اختبارات Core Engine: CommandRegistry، الـ dispatch، تحميل الإضافات، وسجل المهارات."""
import time

from core_engine import AssistantEngine, CommandContext, CommandRegistry


def test_registry_register_and_get():
    reg = CommandRegistry()
    reg.register("Hello", lambda ctx: "hi", "greet")
    cmd = reg.get("hello")  # case-insensitive lookup
    assert cmd is not None
    assert cmd.name == "hello"
    assert cmd.description == "greet"


def test_registry_unregister():
    reg = CommandRegistry()
    reg.register("x", lambda ctx: "y")
    reg.unregister("x")
    assert reg.get("x") is None


def test_registry_list_sorted():
    reg = CommandRegistry()
    reg.register("zebra", lambda ctx: "")
    reg.register("apple", lambda ctx: "")
    names = [c.name for c in reg.list_commands()]
    assert names == sorted(names)


def test_builtin_help_lists_commands(bare_engine, make_ctx):
    result = bare_engine._cmd_help(make_ctx("help", []))
    assert "help" in result
    assert "echo" in result


def test_builtin_echo(bare_engine, make_ctx):
    result = bare_engine._cmd_echo(make_ctx("echo hi there", ["hi", "there"]))
    assert result == "hi there"


def test_run_command_executes_and_captures_output(bare_engine, make_ctx):
    result = bare_engine._cmd_run(make_ctx("run echo hello", ["echo", "hello"]))
    assert "hello" in result


def test_run_command_missing_binary_is_friendly(bare_engine, make_ctx):
    result = bare_engine._cmd_run(make_ctx("run this_binary_does_not_exist_xyz", ["this_binary_does_not_exist_xyz"]))
    assert result.startswith("❌")


def test_run_command_no_args_shows_usage(bare_engine, make_ctx):
    result = bare_engine._cmd_run(make_ctx("run", []))
    assert "usage" in result


def test_dispatch_unknown_command_warns(bare_engine):
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("totally_unknown_command")
    assert any(level == "warn" for level, _ in logs)


def test_dispatch_empty_command_is_noop(bare_engine):
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("   ")
    assert logs == []


def test_dispatch_malformed_quoting_reports_parse_error(bare_engine):
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("echo 'unterminated")
    assert any(level == "error" and "parse error" in msg for level, msg in logs)


def test_engine_start_stop_lifecycle(bare_engine):
    assert not bare_engine.is_running()
    bare_engine.start()
    assert bare_engine.is_running()
    bare_engine.stop()
    time.sleep(0.3)
    assert not bare_engine.is_running()


def test_double_start_is_idempotent(bare_engine):
    bare_engine.start()
    worker1 = bare_engine._worker
    bare_engine.start()
    assert bare_engine._worker is worker1
    bare_engine.stop()
    time.sleep(0.2)


def test_submit_and_command_result_reaches_log(bare_engine):
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine.start()
    bare_engine.submit("echo works")
    time.sleep(0.3)
    bare_engine.stop()
    time.sleep(0.2)
    assert any("works" in msg for _, msg in logs)


# ── plugin loading ────────────────────────────────────────────────────

def test_load_plugins_from_directory(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "sample_plugin.py").write_text(
        "def _h(ctx):\n    return 'pong'\n\n"
        "def register(engine):\n    engine.registry.register('ping', _h, 'test')\n",
        encoding="utf-8",
    )
    engine = AssistantEngine(plugins_dirs=[plugins_dir])
    assert "sample_plugin" in engine._loaded_plugins
    assert engine.registry.get("ping") is not None


def test_load_plugins_skips_underscore_files(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "_private.py").write_text("def register(engine):\n    raise RuntimeError('should not run')\n", encoding="utf-8")
    engine = AssistantEngine(plugins_dirs=[plugins_dir])
    assert "_private" not in engine._loaded_plugins


def test_load_plugins_survives_broken_plugin(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "broken.py").write_text("this is not valid python (((", encoding="utf-8")
    (plugins_dir / "good.py").write_text(
        "def register(engine):\n    engine.registry.register('fine', lambda ctx: 'ok', 'd')\n",
        encoding="utf-8",
    )
    engine = AssistantEngine(plugins_dirs=[plugins_dir])
    assert "good" in engine._loaded_plugins
    assert "broken" not in engine._loaded_plugins
    assert engine.registry.get("fine") is not None


def test_load_plugins_without_register_function_is_skipped(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "noreg.py").write_text("x = 1\n", encoding="utf-8")
    engine = AssistantEngine(plugins_dirs=[plugins_dir])
    assert "noreg" not in engine._loaded_plugins


def test_reload_plugins_picks_up_new_file(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    engine = AssistantEngine(plugins_dirs=[plugins_dir])
    assert engine.registry.get("newcmd") is None

    (plugins_dir / "hot.py").write_text(
        "def register(engine):\n    engine.registry.register('newcmd', lambda ctx: 'hi', 'd')\n",
        encoding="utf-8",
    )
    engine.load_plugins()
    assert engine.registry.get("newcmd") is not None


# ── skills ledger ──────────────────────────────────────────────────────

def test_skills_ledger_records_loaded_plugins(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "tracked.py").write_text(
        "def register(engine):\n    engine.registry.register('t', lambda ctx: '', 'd')\n",
        encoding="utf-8",
    )
    engine = AssistantEngine(plugins_dirs=[plugins_dir])
    assert "tracked" in engine.skills["plugins"]


def test_skills_ledger_persists_across_instances(tmp_path):
    # isolate_state_dir (autouse) already points both instances at the
    # same tmp_path, so skills.json is genuinely shared between them.
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    engine1 = AssistantEngine(plugins_dirs=[plugins_dir])
    engine1._dispatch("help")  # records a command usage

    engine2 = AssistantEngine(plugins_dirs=[plugins_dir])
    assert engine2.skills["commands"].get("help", {}).get("count", 0) >= 1


def test_skills_ledger_survives_plugin_deletion(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin_file = plugins_dir / "temp_plugin.py"
    plugin_file.write_text(
        "def register(engine):\n    engine.registry.register('t2', lambda ctx: '', 'd')\n",
        encoding="utf-8",
    )
    engine = AssistantEngine(plugins_dirs=[plugins_dir])
    assert "temp_plugin" in engine.skills["plugins"]

    plugin_file.unlink()
    engine.load_plugins()
    assert "temp_plugin" not in engine._loaded_plugins  # no longer active
    assert "temp_plugin" in engine.skills["plugins"]  # but never forgotten
