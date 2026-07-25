"""اختبارات Core Engine: CommandRegistry، الـ dispatch، تحميل الإضافات، وسجل المهارات."""
import threading
import time

import brain
import core_engine
import hooks
import intents
import pytest
import sessions
from core_engine import AssistantEngine, CommandRegistry


@pytest.fixture(autouse=True)
def _isolate_brain_and_intents(tmp_path, monkeypatch):
    """كل اختبار بحالة مخ/قاموس خاصة بيه — عشان محدش يكتب فوق ملفات
    المستخدم الحقيقية، ومحدش يعمل نداء شبكة حقيقي."""
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(brain, "_HAS_KEYRING", False)
    monkeypatch.setattr(intents, "_cache_path", lambda: tmp_path / "intent_cache.json")
    monkeypatch.setattr(sessions, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(hooks, "_base_dir", lambda: tmp_path)
    brain.reset_brain()
    brain.save_config({**brain._default_config(), "enabled": []})
    yield
    brain.reset_brain()


def _no_brain(monkeypatch):
    """بيخلي المخ 'مش متظبط' — عشان التستات اللي بتختبر المسارات
    المحلية (تصحيح إملائي، قاموس) تفضل حتمية وسريعة ومن غير شبكة."""
    monkeypatch.setattr(brain.Brain, "ready", lambda self: False)


def _fake_brain(monkeypatch, reply_text: str, label: str = "Fake"):
    """بيرجّع رد ثابت من المخ من غير أي نداء شبكة."""
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(
            text=reply_text, provider="fake", label=label, is_local=True
        ),
    )


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
    # الكلام اللي مالوش مقابل محلي بيروح للمخ، والمخ بيشتغل على thread
    # منفصل (عشان مايقفلش الطابور) — فبنستنى شوية قبل ما نفحص اللوج.
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("totally_unknown_command")
    time.sleep(0.4)
    assert any(level == "warn" for level, _ in logs)
    assert any("totally_unknown_command" in msg for _, msg in logs)


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
    _no_brain(monkeypatch)
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

def test_dispatch_typo_sets_pending_and_does_not_execute(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    assert bare_engine._pending_intent == ("help", [], "hlp")
    assert any("قصدك" in msg for _, msg in logs)
    # مفيش تنفيذ حصل — الـ echo/help output مفيهوش أي دليل تنفيذ فعلي


def test_dispatch_confirm_yes_executes_pending_suggestion(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    logs.clear()
    bare_engine._dispatch("y")
    assert bare_engine._pending_intent is None
    assert any("help" in msg and "echo" in msg for _, msg in logs)  # نتيجة أمر help الحقيقي اتنفذ


def test_dispatch_confirm_no_cancels_pending_suggestion(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    logs.clear()
    bare_engine._dispatch("n")
    assert bare_engine._pending_intent is None
    assert any("اتلغى" in msg for _, msg in logs)


def test_dispatch_unrelated_input_discards_pending_and_processes_normally(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._dispatch("hlp")
    logs.clear()
    bare_engine._dispatch("echo fresh command")
    assert bare_engine._pending_intent is None
    assert any("fresh command" in msg for _, msg in logs)


def test_dispatch_pending_preserves_original_args(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    bare_engine._dispatch("ecoh hello there")  # typo لأمر echo مع وسائط
    assert bare_engine._pending_intent == ("echo", ["hello", "there"], "ecoh hello there")


# ── فهم النية: القاموس المحلي (بصفر حصة) ────────────────────────────

def test_local_dictionary_resolves_arabic_without_touching_brain(bare_engine, monkeypatch):
    """الجملة دي في القاموس، فلازم تتنفذ من غير ما المخ يتنادى خالص —
    ده جوهر توفير الحصة المجانية."""
    called = {"brain": False}
    monkeypatch.setattr(
        brain.Brain, "ready",
        lambda self: called.__setitem__("brain", True) or True,
    )
    bare_engine.registry.register("env_check", lambda ctx: "بيئة تمام")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))

    bare_engine._dispatch("ايه الناقص عندي")
    assert any("بيئة تمام" in msg for _, msg in logs)
    assert called["brain"] is False


def test_local_dictionary_derives_output_path(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    seen = {}
    bare_engine.registry.register(
        "auto_trim_silence", lambda ctx: seen.update(args=ctx.args) or "تم"
    )
    bare_engine._dispatch("شيل الصمت من /home/u/vid.mp4")
    assert seen["args"] == ["/home/u/vid.mp4", "/home/u/vid_trimmed.mp4"]


def test_missing_file_arg_asks_instead_of_calling_brain(bare_engine, monkeypatch):
    called = {"brain": False}
    monkeypatch.setattr(
        brain.Brain, "ready", lambda self: called.__setitem__("brain", True) or True
    )
    bare_engine.registry.register("virus_scan", lambda ctx: "فحص")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))

    bare_engine._dispatch("افحص ملف فيروسات")
    assert bare_engine._pending_args is not None
    assert any("📝" in msg for _, msg in logs)
    assert called["brain"] is False


def test_pending_arg_is_filled_by_next_message(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    seen = {}
    bare_engine.registry.register("virus_scan", lambda ctx: seen.update(args=ctx.args) or "تم")
    bare_engine._dispatch("افحص ملف فيروسات")
    bare_engine._dispatch("C:/x/file.exe")
    assert seen["args"] == ["C:/x/file.exe"]
    assert bare_engine._pending_args is None


def test_pending_arg_can_be_cancelled(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine.registry.register("virus_scan", lambda ctx: "لازم مايتنفذش")
    bare_engine._dispatch("افحص ملف فيروسات")
    bare_engine._dispatch("إلغاء")
    assert bare_engine._pending_args is None
    assert any("اتلغى" in msg for _, msg in logs)


def test_gui_file_hook_is_used_when_available(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    bare_engine.registry.register("virus_scan", lambda ctx: "تم")
    asked = {}
    bare_engine.on_need_file = lambda spec, cb: asked.update(prompt=spec.prompt)
    bare_engine._dispatch("افحص ملف فيروسات")
    assert "اختار" in asked["prompt"]


def test_learned_phrase_resolves_locally_afterwards(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    intents.remember("اعمللي الحركة الغريبة دي", "echo")
    seen = {}
    monkeypatch.setattr(
        bare_engine, "_execute",
        lambda name, args, raw: seen.update(name=name),
    )
    bare_engine._dispatch("اعمللي الحركة الغريبة دي")
    assert seen["name"] == "echo"


# ── فهم النية: محادثة المخ ───────────────────────────────────────────

def test_free_text_goes_to_brain_and_replies_conversationally(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "أهلاً! أنا كويسة، إنت عامل إيه؟")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("إزيك عاملة إيه")
    assert any("أهلاً" in msg for _, msg in logs)


def test_brain_reply_carries_provider_badge(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "رد", label="Groq")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("سؤال")
    assert any("Groq" in msg for _, msg in logs)


def test_brain_tool_suggestion_needs_confirmation_and_does_not_run(bare_engine, monkeypatch):
    """مبدأ المشروع الثابت: مفيش تنفيذ تلقائي لأمر اقترحه نموذج."""
    _fake_brain(monkeypatch, "هفحص الملف ده.\nTOOL: echo scanned")
    ran = {"n": 0}
    bare_engine.registry.register("echo", lambda ctx: ran.__setitem__("n", ran["n"] + 1))
    bare_engine._converse("افحص حاجة")
    assert bare_engine._pending_intent == ("echo", ["scanned"], "افحص حاجة")
    assert ran["n"] == 0


def test_confirming_brain_suggestion_executes_and_learns_the_phrase(bare_engine, monkeypatch):
    """الحلقة اللي بتخلي الاستهلاك ينزل للصفر: صيغة كلام النموذج فهمها
    مرة واحدة بتتحفظ، فنفس الصيغة تاني مرة بتتحل محليًا ببلاش."""
    _fake_brain(monkeypatch, "تمام.\nTOOL: echo done")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("اعمل الحاجة دي بقى")
    bare_engine._dispatch("y")

    assert any("done" in msg for _, msg in logs)
    assert intents.load_cache()[intents.normalize("اعمل الحاجة دي بقى")] == "echo"


def test_brain_hallucinated_tool_is_dropped_not_offered(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "تمام.\nTOOL: command_that_does_not_exist x")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("حاجة")
    assert bare_engine._pending_intent is None
    assert not any("command_that_does_not_exist" in msg for _, msg in logs)


def test_brain_error_is_reported_not_swallowed(bare_engine, monkeypatch):
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(text="", error="كله واقع"),
    )
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("سؤال")
    assert any("كله واقع" in msg and level == "error" for level, msg in logs)


def test_no_brain_configured_gives_actionable_message(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("كلام مش مفهوم خالص للقاموس")
    assert any("brain_setup" in msg for _, msg in logs)


def test_chat_history_accumulates_and_is_capped(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "رد")
    for i in range(40):
        bare_engine._converse(f"رسالة {i}")
    assert len(bare_engine.chat_history) <= core_engine._MAX_CHAT_TURNS


def test_deep_mode_uses_deep_chat(bare_engine, monkeypatch):
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    used = {}
    monkeypatch.setattr(
        brain.Brain, "deep_chat",
        lambda self, messages, **kw: [
            used.setdefault("deep", True),
            brain.BrainReply(text="عميق", provider="deep", label="deep"),
        ][1],
    )
    cfg = brain.load_config()
    cfg["deep_mode"] = True
    brain.save_config(cfg)
    bare_engine._converse("سؤال صعب")
    assert used.get("deep") is True


# ── فصل سطر TOOL ─────────────────────────────────────────────────────

def test_split_tool_call_extracts_command_and_args():
    body, tool = AssistantEngine._split_tool_call("شرح كده.\nTOOL: probe /a/b.mp4")
    assert body == "شرح كده."
    assert tool == ("probe", ["/a/b.mp4"])


def test_split_tool_call_returns_none_when_absent():
    body, tool = AssistantEngine._split_tool_call("رد عادي من غير أدوات")
    assert tool is None
    assert body == "رد عادي من غير أدوات"


def test_split_tool_call_handles_quoted_args():
    _, tool = AssistantEngine._split_tool_call('TOOL: probe "C:/My Files/a.mp4"')
    assert tool == ("probe", ["C:/My Files/a.mp4"])


def test_split_tool_call_survives_bad_quoting():
    _, tool = AssistantEngine._split_tool_call('TOOL: echo "unterminated')
    assert tool[0] == "echo"


def test_split_tool_call_takes_only_the_first_tool_line():
    _, tool = AssistantEngine._split_tool_call("TOOL: echo one\nTOOL: echo two")
    assert tool == ("echo", ["one"])


# ── التنفيذ مش بيتقفل على thread المحرك ─────────────────────────────

def test_brain_call_runs_off_the_worker_thread(bare_engine, monkeypatch):
    """راجع: نداء النموذج بياخد عشرات الثواني. لو اتنفذ على thread
    الطابور كان هيقفل كل حاجة تانية (جداول، تليجرام، أوامر تانية)
    طول المدة دي."""
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    worker_thread = {}

    def slow_chat(self, messages, **kw):
        worker_thread["name"] = threading.current_thread().name
        return brain.BrainReply(text="رد", provider="f", label="F")

    monkeypatch.setattr(brain.Brain, "chat", slow_chat)
    bare_engine._converse_async("كلام حر")
    time.sleep(0.4)
    assert worker_thread.get("name", "").startswith("nezuko-brain")



# ── الصلاحيات: بوابة التأكيد ─────────────────────────────────────────

def test_allowed_command_runs_without_asking(bare_engine, monkeypatch):
    """الأمر اللي في قايمة المسموح بيعدي على طول — من غير سؤال."""
    import permissions
    _fake_brain(monkeypatch, "تمام.\nTOOL: echo ran")
    permissions.allow("echo")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("اعمل الحاجة دي")
    assert bare_engine._pending_intent is None
    assert any("ran" in msg for _, msg in logs)


def test_unlisted_command_still_asks(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "تمام.\nTOOL: echo ran")
    bare_engine._converse("اعمل الحاجة دي")
    assert bare_engine._pending_intent is not None


def test_reply_a_grants_permission_and_runs(bare_engine, monkeypatch):
    import permissions
    _fake_brain(monkeypatch, "تمام.\nTOOL: echo done")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("اعمل كده")
    bare_engine._dispatch("a")
    assert permissions.is_allowed("echo") is True
    assert any("done" in msg for _, msg in logs)


def test_reply_a_is_refused_for_a_never_allowed_command(bare_engine, monkeypatch):
    """`run` مينفعش يتسمح أبدًا — حتى لو المستخدم طلب كده صراحةً."""
    import permissions
    _fake_brain(monkeypatch, "تمام.\nTOOL: run ls")
    bare_engine.registry.register("run", lambda ctx: "ران")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("شغّل حاجة")
    bare_engine._dispatch("a")
    assert permissions.is_allowed("run") is False
    assert any("مينفعش" in msg for _, msg in logs)


def test_confirm_prompt_mentions_the_always_option(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "تمام.\nTOOL: echo x")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("حاجة")
    assert any("تسمح بالأمر ده دايمًا" in msg for _, msg in logs)


# ── الجلسات: الحفظ التلقائي ──────────────────────────────────────────

def test_conversation_is_saved_after_each_exchange(bare_engine, monkeypatch, tmp_path):
    import sessions
    monkeypatch.setattr(sessions, "_base_dir", lambda: tmp_path)
    _fake_brain(monkeypatch, "رد")
    bare_engine._converse("سؤال محفوظ")
    saved = sessions.load(bare_engine.session_id)
    assert saved is not None
    assert any("سؤال محفوظ" in m["content"] for m in saved)


def test_each_engine_starts_with_its_own_session_id(tmp_path):
    other = AssistantEngine(plugins_dirs=[tmp_path / "none"])
    assert other.session_id


# ── الأحداث: منع التكرار اللانهائي ───────────────────────────────────

def test_hook_command_does_not_retrigger_its_own_event(bare_engine, monkeypatch, tmp_path):
    """راجع: hook مربوط بـ after_command بيشغّل أمر، والأمر ده كان
    بيطلّع after_command تاني — تكرار بلا نهاية بيملا الطابور."""
    import hooks
    monkeypatch.setattr(hooks, "_base_dir", lambda: tmp_path)
    hooks.add("after_command", "echo من الهوك")

    fired = []
    real_fire = hooks.fire

    def counting_fire(engine, event, **ctx):
        fired.append(event)
        return real_fire(engine, event, **ctx)

    monkeypatch.setattr(hooks, "fire", counting_fire)
    bare_engine.start()
    try:
        bare_engine.submit("echo أصلي")
        time.sleep(0.8)
    finally:
        bare_engine.stop()
        time.sleep(0.3)
    # الأمر الأصلي طلّع الحدث؛ أمر الهوك نفسه مطلّعش حاجة
    assert fired.count("after_command") == 1


def test_startup_hook_fires_on_start(bare_engine, monkeypatch, tmp_path):
    import hooks
    monkeypatch.setattr(hooks, "_base_dir", lambda: tmp_path)
    hooks.add("startup", "echo بدأنا")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine.start()
    time.sleep(0.6)
    bare_engine.stop()
    time.sleep(0.3)
    assert any("بدأنا" in msg for _, msg in logs)
