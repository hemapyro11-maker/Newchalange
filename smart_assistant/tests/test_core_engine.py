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
    # الـ prompt مفتاح ترجمة مش نص جاهز — الواجهة هي اللي بتترجمه
    # بلغتها، فنفس القاعدة بتخدم اللغتين من غير تكرار
    import i18n
    assert asked["prompt"] in i18n.STRINGS["en"]


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


# ── فصل سطر TOOL / ASK ───────────────────────────────────────────────

def test_split_tool_call_extracts_command_and_args():
    body, tool, _q = AssistantEngine._split_directives("شرح كده.\nTOOL: probe /a/b.mp4")
    assert body == "شرح كده."
    assert tool == ("probe", ["/a/b.mp4"])


def test_split_tool_call_returns_none_when_absent():
    body, tool, _q = AssistantEngine._split_directives("رد عادي من غير أدوات")
    assert tool is None
    assert body == "رد عادي من غير أدوات"


def test_split_tool_call_handles_quoted_args():
    _b, tool, _q = AssistantEngine._split_directives('TOOL: probe "C:/My Files/a.mp4"')
    assert tool == ("probe", ["C:/My Files/a.mp4"])


def test_split_tool_call_survives_bad_quoting():
    _b, tool, _q = AssistantEngine._split_directives('TOOL: echo "unterminated')
    assert tool[0] == "echo"


def test_split_tool_call_takes_only_the_first_tool_line():
    _b, tool, _q = AssistantEngine._split_directives("TOOL: echo one\nTOOL: echo two")
    assert tool == ("echo", ["one"])


def test_split_extracts_a_question():
    body, tool, question = AssistantEngine._split_directives(
        "محتاج أعرف حاجة الأول.\nASK: أنهي ملف بالظبط؟"
    )
    assert question == "أنهي ملف بالظبط؟"
    assert tool is None
    assert body == "محتاج أعرف حاجة الأول."


def test_split_takes_only_the_first_question():
    _b, _t, question = AssistantEngine._split_directives("ASK: واحد\nASK: اتنين")
    assert question == "واحد"


def test_a_question_wins_over_a_tool_in_the_same_reply():
    """لو النموذج خالف التعليمات وبعت الاتنين — نسأل. تنفيذ أمر مبني
    على تخمين النموذج نفسه شكّك فيه هو أسوأ الاحتمالات."""
    _b, tool, question = AssistantEngine._split_directives(
        "ASK: أنهي ملف؟\nTOOL: echo guess"
    )
    assert question == "أنهي ملف؟"
    assert tool is None


# ── يسأل بدل ما يخمّن ────────────────────────────────────────────────

def test_a_question_does_not_queue_any_command(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "ASK: أنهي ملف بالظبط؟")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))
    bare_engine._converse("افحص الملف")
    assert bare_engine._pending_intent is None
    assert any("أنهي ملف بالظبط؟" in msg for _, msg in logs)


def test_your_answer_goes_straight_to_the_brain_not_the_dictionary(
    bare_engine, monkeypatch
):
    """لو الإجابة عدّت على القاموس المحلي الأول، رد زي "التقرير" كان
    هيتفهم كأمر أو ميتفهمش خالص بدل ما يتحسب إجابة على السؤال."""
    _fake_brain(monkeypatch, "ASK: أنهي ملف؟")
    bare_engine._converse("افحص الملف")
    assert bare_engine._awaiting_answer is True

    sent = {}
    monkeypatch.setattr(
        bare_engine, "_converse_async",
        lambda text, step=0: sent.update(text=text),
    )
    bare_engine._dispatch("التقرير")
    assert sent["text"] == "التقرير"
    assert bare_engine._awaiting_answer is False


def test_the_waiting_flag_clears_so_the_next_message_is_normal(
    bare_engine, monkeypatch
):
    _fake_brain(monkeypatch, "ASK: أنهي واحد؟")
    bare_engine._converse("حاجة")
    monkeypatch.setattr(bare_engine, "_converse_async", lambda text, step=0: None)
    bare_engine._dispatch("الأول")
    assert bare_engine._awaiting_answer is False


# ── كشف الأسئلة الصعبة (بيشغّل التفكير خطوة بخطوة) ──────────────────

@pytest.mark.parametrize("text", [
    "ليه الكود ده بطيء؟",
    "قارن بين الطريقتين",
    "why is this slower",
    "compare these two approaches",
    "احسب 12 * 340",
    "what is 15% of 240",
    "explain the complexity here",
    "ايه السبب في المشكله دي",
])
def test_hard_questions_are_detected(text):
    assert AssistantEngine._looks_hard(text) is True


@pytest.mark.parametrize("text", [
    "إزيك",
    "hi there",
    "افتح الإعدادات",
    "شكرًا",
])
def test_ordinary_messages_are_not_treated_as_hard(text):
    assert AssistantEngine._looks_hard(text) is False


def test_think_step_by_step_is_injected_only_when_hard(bare_engine, monkeypatch):
    seen = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            seen.update(system=messages[0]["content"]),
            brain.BrainReply(text="رد", provider="f", label="F"),
        ][1],
    )
    bare_engine._converse("إزيك")
    assert "step by step" not in seen["system"]

    bare_engine._converse("ليه ده بيحصل؟")
    assert "step by step" in seen["system"]


def test_auto_deep_stays_off_unless_you_turn_it_on(bare_engine, monkeypatch):
    """الوضع العميق بيستهلك ~4 أضعاف الحصة — قرار المستخدم مش قرارنا."""
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    used = {}
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            used.setdefault("normal", True),
            brain.BrainReply(text="رد", provider="f", label="F"),
        ][1],
    )
    monkeypatch.setattr(
        brain.Brain, "deep_chat",
        lambda self, messages, **kw: [
            used.setdefault("deep", True),
            brain.BrainReply(text="رد", provider="f", label="F"),
        ][1],
    )
    bare_engine._converse("ليه ده بيحصل؟")
    assert used == {"normal": True}


def test_auto_deep_escalates_hard_questions_when_enabled(bare_engine, monkeypatch):
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    used = {}
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            used.setdefault("normal", True),
            brain.BrainReply(text="رد", provider="f", label="F"),
        ][1],
    )
    monkeypatch.setattr(
        brain.Brain, "deep_chat",
        lambda self, messages, **kw: [
            used.setdefault("deep", True),
            brain.BrainReply(text="رد", provider="f", label="F"),
        ][1],
    )
    cfg = brain.load_config()
    cfg["auto_deep"] = True
    brain.save_config(cfg)

    bare_engine._converse("إزيك")       # عادي → مايتصعّدش
    assert used == {"normal": True}
    bare_engine._converse("ليه ده بيحصل؟")  # صعب → يتصعّد
    assert used.get("deep") is True


# ── ضغط المحادثة بدل رميها ───────────────────────────────────────────

def _long_history(n: int) -> list[dict]:
    out = []
    for i in range(n):
        out += [
            {"role": "user", "content": f"رسالة {i}"},
            {"role": "assistant", "content": f"رد {i}"},
        ]
    return out


def test_old_messages_become_notes_instead_of_being_dropped(
    bare_engine, monkeypatch
):
    """الفرق العملي: بعد 30 دور، نيزوكو تفضل فاكرة إنك شغال على
    مشروع معيّن — مش تسأل من الأول."""
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(
            text="المستخدم شغال على مشروع نيزوكو", provider="f", label="F"
        ),
    )
    bare_engine.chat_history = _long_history(20)
    bare_engine._compact_history(brain.get_brain())

    assert bare_engine.chat_history[0]["role"] == "system"
    assert "مشروع نيزوكو" in bare_engine.chat_history[0]["content"]
    assert len(bare_engine.chat_history) == core_engine._COMPACT_KEEP + 1


def test_compaction_does_not_run_below_the_threshold(bare_engine, monkeypatch):
    """كل ضغط بيكلّف نداء نموذج — مينفعش يحصل كل رسالة."""
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    calls = []
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            calls.append(1),
            brain.BrainReply(text="ملخص", provider="f", label="F"),
        ][1],
    )
    bare_engine.chat_history = _long_history(5)
    bare_engine._compact_history(brain.get_brain())
    assert calls == []


def test_earlier_notes_are_folded_into_the_new_ones(bare_engine, monkeypatch):
    """الملخص بيتراكم — منستبدلوش، وإلا أقدم حاجة بتضيع في كل ضغطة."""
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    seen = {}
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            seen.update(prompt=messages[-1]["content"]),
            brain.BrainReply(text="ملخص جديد", provider="f", label="F"),
        ][1],
    )
    bare_engine.chat_history = [
        {"role": "system", "content": "ملاحظات قديمة: بيشتغل على الصوت"},
        *_long_history(20),
    ]
    bare_engine._compact_history(brain.get_brain())
    assert "بيشتغل على الصوت" in seen["prompt"]


def test_failed_compaction_still_trims_instead_of_growing_forever(
    bare_engine, monkeypatch
):
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(text="", error="مفيش نت"),
    )
    bare_engine.chat_history = _long_history(20)
    bare_engine._compact_history(brain.get_brain())
    assert len(bare_engine.chat_history) == core_engine._COMPACT_KEEP


def test_the_notes_reach_the_model(bare_engine, monkeypatch):
    seen = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            seen.update(system=messages[0]["content"]),
            brain.BrainReply(text="رد", provider="f", label="F"),
        ][1],
    )
    bare_engine.chat_history = [
        {"role": "system", "content": "ملاحظات: المشروع اسمه نيزوكو"},
    ]
    bare_engine._converse("كمّل")
    assert "المشروع اسمه نيزوكو" in seen["system"]


def test_notes_are_not_replayed_as_a_conversation_turn(bare_engine, monkeypatch):
    """رسالة الملخص بتتحط في الـ system prompt — لو اتبعتت كمان كدور
    عادي كان النموذج هيشوفها مرتين."""
    seen = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            seen.update(rest=messages[1:-1]),
            brain.BrainReply(text="رد", provider="f", label="F"),
        ][1],
    )
    bare_engine.chat_history = [
        {"role": "system", "content": "ملاحظات"},
        {"role": "user", "content": "كلام"},
    ]
    bare_engine._converse("كمّل")
    assert all(m["role"] != "system" for m in seen["rest"])


# ── سلسلة خطوات: نتيجة الأمر بترجع للمخ ──────────────────────────────

def test_command_result_is_returned_so_it_can_feed_the_next_step(bare_engine):
    bare_engine.registry.register("echo2", lambda ctx: "the output")
    assert bare_engine._execute("echo2", [], "echo2") == "the output"


def test_a_failing_command_returns_none_and_stops_the_chain(bare_engine):
    def boom(ctx):
        raise RuntimeError("مكسور")
    bare_engine.registry.register("boom", boom)
    assert bare_engine._execute("boom", [], "boom") is None


def test_tool_output_is_sent_back_to_the_brain(bare_engine, monkeypatch):
    """ده اللي بيخلي "شغّل الاختبارات → اقرا الخطأ → صلّحه" ممكنة."""
    sent = {}
    monkeypatch.setattr(
        bare_engine, "_converse_async",
        lambda text, step=0: sent.update(text=text, step=step),
    )
    bare_engine._continue_chain("run_tests", "2 failed", 0)
    assert "run_tests" in sent["text"]
    assert "2 failed" in sent["text"]
    assert sent["step"] == 1


def test_the_chain_stops_at_the_step_limit(bare_engine, monkeypatch):
    """السقف هو اللي بيمنع حلقة تولّع الحصة."""
    calls = []
    monkeypatch.setattr(
        bare_engine, "_converse_async",
        lambda text, step=0: calls.append(step),
    )
    bare_engine._continue_chain("x", "out", core_engine._MAX_TOOL_STEPS - 1)
    assert calls == []


def test_a_failed_step_does_not_continue_the_chain(bare_engine, monkeypatch):
    calls = []
    monkeypatch.setattr(
        bare_engine, "_converse_async",
        lambda text, step=0: calls.append(step),
    )
    bare_engine._continue_chain("x", None, 0)
    assert calls == []


def test_confirming_a_chained_step_continues_the_chain(bare_engine, monkeypatch):
    _fake_brain(monkeypatch, "هجرب.\nTOOL: echo3 hi")
    bare_engine.registry.register("echo3", lambda ctx: "done")
    bare_engine._converse("اعمل حاجة")
    assert bare_engine._pending_intent is not None

    followed = {}
    monkeypatch.setattr(
        bare_engine, "_converse_async",
        lambda text, step=0: followed.update(text=text, step=step),
    )
    bare_engine._dispatch("y")
    assert "done" in followed["text"]
    assert followed["step"] == 1


def test_a_command_you_typed_yourself_does_not_start_a_chain(
    bare_engine, monkeypatch
):
    """السلسلة للأوامر اللي المخ اقترحها بس — أمر كتبته بإيدك مالوش
    متابعة، وإلا كل أمر عادي كان هيصرف من الحصة."""
    _no_brain(monkeypatch)
    bare_engine.registry.register("echo4", lambda ctx: "out")
    calls = []
    monkeypatch.setattr(
        bare_engine, "_converse_async",
        lambda text, step=0: calls.append(text),
    )
    bare_engine._dispatch("echo4 hi")
    assert calls == []


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
    assert any("never be allowed" in msg for _, msg in logs)


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


# ── الرد بلغة المستخدم ───────────────────────────────────────────────

def test_system_prompt_tells_the_model_to_mirror_the_user_language(bare_engine, monkeypatch):
    """راجع: تعليمات النظام كانت مكتوبة بالعربي، فنيزوكو كانت بترد
    عربي حتى لو المستخدم كتب إنجليزي."""
    captured = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: captured.setdefault("m", messages)
        and None or brain.BrainReply(text="ok", label="X"),
    )
    bare_engine._converse("hello there")
    system = captured["m"][0]["content"]
    assert "same language the user wrote in" in system
    assert "Egyptian Arabic" in system


def test_system_prompt_is_not_hardcoded_to_one_language(bare_engine, monkeypatch):
    captured = {}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: captured.setdefault("m", messages)
        and None or brain.BrainReply(text="ok", label="X"),
    )
    bare_engine._converse("x")
    system = captured["m"][0]["content"]
    # التعليمات نفسها إنجليزية، فمش بتجرّ النموذج للعربي
    assert "أنتي نيزوكو" not in system


def test_english_phrase_resolves_locally_without_the_brain(bare_engine, monkeypatch):
    """الإدخال الإنجليزي لازم يتحل من القاموس المحلي زي العربي
    بالظبط — بصفر حصة."""
    called = {"brain": False}
    monkeypatch.setattr(
        brain.Brain, "ready",
        lambda self: called.__setitem__("brain", True) or True,
    )
    bare_engine.registry.register("env_check", lambda ctx: "env fine")
    logs = []
    bare_engine.on_log = lambda msg, level="info": logs.append((level, msg))

    bare_engine._dispatch("what is installed")
    assert any("env fine" in msg for _, msg in logs)
    assert called["brain"] is False


def test_english_and_arabic_reach_the_same_command(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    seen = []
    monkeypatch.setattr(
        bare_engine, "_execute",
        lambda name, args, raw: seen.append(name),
    )
    bare_engine.registry.register("virus_scan", lambda ctx: "x")
    bare_engine._dispatch("scan /a/b.exe for malware")
    bare_engine._dispatch("افحص /a/b.exe فيروسات")
    assert seen == ["virus_scan", "virus_scan"]


def test_cancel_works_in_both_languages(bare_engine, monkeypatch):
    _no_brain(monkeypatch)
    bare_engine.registry.register("virus_scan", lambda ctx: "should not run")
    for word in ("cancel", "إلغاء"):
        bare_engine._dispatch("scan a file for malware")
        assert bare_engine._pending_args is not None
        bare_engine._dispatch(word)
        assert bare_engine._pending_args is None
