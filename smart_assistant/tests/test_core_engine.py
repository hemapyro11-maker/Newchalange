"""اختبارات Core Engine: CommandRegistry، الـ dispatch، تحميل الإضافات، وسجل المهارات."""
import json
import time
import urllib.error

import core_engine
from core_engine import AssistantEngine, CommandRegistry


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


def test_submit_literal_stop_string_does_not_stop_engine(bare_engine):
    # راجع: الإيقاف كان بيتعرّف بمطابقة نص "__stop__" حرفيًا جوه الطابور
    # — لو مستخدم كتب النص ده فعليًا (أو جاله من macro/schedule/لصق)،
    # كان الـ worker thread بيوقف بصمت زي لو stop() اتنادت فعلاً، من
    # غير أي رسالة. دلوقتي الإيقاف بيتعرّف بـ sentinel object فريد
    # (object identity) مش بمطابقة نص، فمينفعش أي نص مكتوب "يطابقه".
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine.start()
    bare_engine.submit("__stop__")
    time.sleep(0.3)
    assert bare_engine.is_running()
    assert any("__stop__" in msg and level == "warn" for level, msg in logs)
    bare_engine.stop()
    time.sleep(0.2)
    assert not bare_engine.is_running()


def test_dispatch_confirm_yes_passes_original_raw_not_confirmation_reply(bare_engine, monkeypatch):
    # راجع: pending_intent كان بيخزن (name, args) بس، من غير النص
    # الأصلي اللي المستخدم كتبه — فلما يتأكد بـ "y"، ctx.raw بتاع الأمر
    # المنفَّذ كان بيبقى "y" نفسها بدل النص الحقيقي. إضافات زي
    # database_plugin.py/connectors_plugin.py بتقرا ctx.raw مباشرة (مش
    # ctx.args) عشان تتفادى مشاكل shlex.split مع JSON/SQL، فكانت بتشتغل
    # على نص فاضي/غلط تمامًا بعد التأكيد.
    monkeypatch.setattr(bare_engine, "_try_llm_intent", lambda text: None)
    bare_engine.registry.register("rawcmd", lambda ctx: f"raw was: {ctx.raw!r}")

    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("rawcmdd some real arguments")  # typo قريب من rawcmd
    assert bare_engine._pending_intent is not None
    logs.clear()
    bare_engine._dispatch("y")
    assert any("raw was: 'rawcmdd some real arguments'" in msg for _, msg in logs)


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


# ── فهم النية: تصحيح إملائي (fuzzy) ─────────────────────────────────

def test_suggest_command_finds_close_typo(bare_engine):
    suggestion = bare_engine._suggest_command("hlp", [])
    assert suggestion is not None
    name, _args, message, level = suggestion
    assert name == "help"
    assert level == "warn"
    assert "help" in message


def test_suggest_command_no_match_for_gibberish(bare_engine, monkeypatch):
    # نتأكد إن مفيش استدعاء Ollama حتى بيتحاول لما مفيش هوية واضحة —
    # لسه ممكن يتحاول، فبنموك عشان الاختبار يفضل حتمي وسريع.
    monkeypatch.setattr(bare_engine, "_try_llm_intent", lambda text: None)
    suggestion = bare_engine._suggest_command("totally_unrelated_gibberish_xyz", [])
    assert suggestion is None


def test_dispatch_typo_sets_pending_and_does_not_execute(bare_engine, monkeypatch):
    monkeypatch.setattr(bare_engine, "_try_llm_intent", lambda text: None)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    assert bare_engine._pending_intent == ("help", [], "hlp")
    assert any("قصدك" in msg for _, msg in logs)
    # مفيش تنفيذ حصل — الـ echo/help output مفيهوش أي دليل تنفيذ فعلي


def test_dispatch_confirm_yes_executes_pending_suggestion(bare_engine, monkeypatch):
    monkeypatch.setattr(bare_engine, "_try_llm_intent", lambda text: None)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    logs.clear()
    bare_engine._dispatch("y")
    assert bare_engine._pending_intent is None
    assert any("help" in msg and "echo" in msg for _, msg in logs)  # نتيجة أمر help الحقيقي اتنفذ


def test_dispatch_confirm_no_cancels_pending_suggestion(bare_engine, monkeypatch):
    monkeypatch.setattr(bare_engine, "_try_llm_intent", lambda text: None)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    logs.clear()
    bare_engine._dispatch("n")
    assert bare_engine._pending_intent is None
    assert any("اتلغى" in msg for _, msg in logs)


def test_dispatch_unrelated_input_discards_pending_and_processes_normally(bare_engine, monkeypatch):
    monkeypatch.setattr(bare_engine, "_try_llm_intent", lambda text: None)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    logs.clear()
    bare_engine._dispatch("echo fresh command")
    assert bare_engine._pending_intent is None
    assert any("fresh command" in msg for _, msg in logs)


def test_dispatch_pending_preserves_original_args(bare_engine, monkeypatch):
    monkeypatch.setattr(bare_engine, "_try_llm_intent", lambda text: None)
    bare_engine._dispatch("ecoh hello there")  # typo لأمر echo مع وسائط
    assert bare_engine._pending_intent == ("echo", ["hello", "there"], "ecoh hello there")


# ── فهم النية: توجيه ذكي عبر Ollama (موك بالكامل — مفيش شبكة حقيقية) ─

def _fake_ollama_response(text: str):
    class FakeResp:
        def read(self):
            return json.dumps({"response": text}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return FakeResp()


def test_try_llm_intent_no_ollama_running(bare_engine, monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(core_engine.urllib.request, "urlopen", fake_urlopen)
    assert bare_engine._try_llm_intent("some free text") is None


def test_try_llm_intent_valid_response_matches_real_command(bare_engine, monkeypatch):
    monkeypatch.setattr(
        core_engine.urllib.request, "urlopen",
        lambda req, timeout: _fake_ollama_response("echo hello world"),
    )
    result = bare_engine._try_llm_intent("say hello world")
    assert result == ("echo", ["hello", "world"])


def test_try_llm_intent_none_response(bare_engine, monkeypatch):
    monkeypatch.setattr(
        core_engine.urllib.request, "urlopen",
        lambda req, timeout: _fake_ollama_response("NONE"),
    )
    assert bare_engine._try_llm_intent("gibberish") is None


def test_try_llm_intent_hallucinated_command_rejected(bare_engine, monkeypatch):
    """النموذج المحلي ممكن "يهلوس" اسم أمر مش موجود فعليًا — المحرك
    لازم يتحقق من الـ registry الحقيقي بدل ما يصدّق النص أعمى."""
    monkeypatch.setattr(
        core_engine.urllib.request, "urlopen",
        lambda req, timeout: _fake_ollama_response("this_command_does_not_exist_anywhere"),
    )
    assert bare_engine._try_llm_intent("do something") is None


def test_try_llm_intent_malformed_json_handled(bare_engine, monkeypatch):
    class BadResp:
        def read(self):
            return b"not json at all"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(core_engine.urllib.request, "urlopen", lambda req, timeout: BadResp())
    assert bare_engine._try_llm_intent("anything") is None


def test_try_llm_intent_empty_response(bare_engine, monkeypatch):
    monkeypatch.setattr(
        core_engine.urllib.request, "urlopen",
        lambda req, timeout: _fake_ollama_response(""),
    )
    assert bare_engine._try_llm_intent("anything") is None


def test_try_llm_intent_bad_quoting_in_reply_handled(bare_engine, monkeypatch):
    monkeypatch.setattr(
        core_engine.urllib.request, "urlopen",
        lambda req, timeout: _fake_ollama_response('echo "unterminated'),
    )
    assert bare_engine._try_llm_intent("anything") is None


def test_dispatch_llm_intent_full_flow_with_confirmation(bare_engine, monkeypatch):
    """محاكاة كاملة: نص حر مش شبيه لأي أمر → Ollama بيقترح → المستخدم
    بيأكد بـ y → الأمر الحقيقي بينفذ فعليًا."""
    monkeypatch.setattr(
        core_engine.urllib.request, "urlopen",
        lambda req, timeout: _fake_ollama_response("echo intent worked"),
    )
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))

    bare_engine._dispatch("can you say something for me please")
    assert bare_engine._pending_intent == ("echo", ["intent", "worked"], "can you say something for me please")
    assert any("🧠" in msg for _, msg in logs)

    logs.clear()
    bare_engine._dispatch("y")
    assert bare_engine._pending_intent is None
    assert any("intent worked" in msg for _, msg in logs)


def test_execute_helper_used_directly_matches_dispatch_behavior(bare_engine):
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._execute("echo", ["direct", "call"], "echo direct call")
    assert any("direct call" in msg for _, msg in logs)
