import json
import urllib.error

import pytest
import think_plugin as tp


@pytest.fixture(autouse=True)
def _isolate_memory(tmp_path, monkeypatch):
    """كل اختبار بيشتغل بملف think_memory.json خاص بيه، عشان محدش يكتب
    فوق smart_assistant/think_memory.json الحقيقي بتاع المستخدم."""
    monkeypatch.setattr(tp, "_memory_path", lambda: tmp_path / "think_memory.json")


@pytest.fixture(autouse=True)
def _isolate_playbooks(tmp_path, monkeypatch):
    """كل اختبار بيشتغل بمجلد playbooks/ خاص بيه، عشان محدش يكتب فوق
    smart_assistant/playbooks/ الحقيقي بتاع المستخدم."""
    playbooks_dir = tmp_path / "playbooks_test"

    def _fake_dir():
        playbooks_dir.mkdir(parents=True, exist_ok=True)
        return playbooks_dir

    monkeypatch.setattr(tp, "_playbooks_dir", _fake_dir)


def _fake_chat_response(content: str):
    class FakeResp:
        def read(self):
            return json.dumps({"message": {"content": content}}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return FakeResp()


def _mock_ollama_sequence(monkeypatch, replies: list[str]):
    """كل نداء لـ urlopen بيرجع الرد التالي في الليستة بالترتيب."""
    calls = {"i": 0}

    def fake_urlopen(req, timeout):
        reply = replies[calls["i"]]
        calls["i"] += 1
        return _fake_chat_response(reply)
    monkeypatch.setattr(tp.urllib.request, "urlopen", fake_urlopen)
    return calls


# ── _extract_tool_call / _strip_tool_line ──────────────────────────────

def test_extract_tool_call_finds_command_and_args():
    reply = "هفكر في الموضوع...\nTOOL: channel_stats @MrBeast"
    result = tp._extract_tool_call(reply)
    assert result == ("channel_stats", ["@MrBeast"])


def test_extract_tool_call_none_when_absent():
    assert tp._extract_tool_call("مجرد إجابة عادية من غير أداة") is None


def test_extract_tool_call_no_args():
    result = tp._extract_tool_call("رأيي كذا\nTOOL: help")
    assert result == ("help", [])


def test_strip_tool_line_removes_only_tool_line():
    reply = "الجزء ده مهم\nTOOL: echo hi"
    assert tp._strip_tool_line(reply) == "الجزء ده مهم"


# ── _extract_plan / _strip_plan_line ────────────────────────────────────

def test_extract_plan_finds_plan_line():
    reply = "PLAN: step one; step two; step three\nهبدأ دلوقتي"
    assert tp._extract_plan(reply) == "step one; step two; step three"


def test_extract_plan_none_when_absent():
    assert tp._extract_plan("مفيش خطة هنا") is None


def test_strip_plan_line_removes_only_plan_line():
    reply = "PLAN: أ؛ ب\nباقي الرد المهم"
    assert tp._strip_plan_line(reply) == "باقي الرد المهم"


# ── think: no ollama running ────────────────────────────────────────────

def test_think_no_args_shows_usage(make_ctx):
    result = tp._cmd_think(make_ctx("think", []))
    assert result.startswith("usage")


def test_think_no_ollama_gives_clear_message(make_ctx, monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(tp.urllib.request, "urlopen", fake_urlopen)

    result = tp._cmd_think(make_ctx("think مرحبا", ["مرحبا"]))
    assert "Ollama" in result
    assert "ollama.com" in result


def test_think_failed_call_does_not_pollute_history(make_ctx, monkeypatch, bare_engine):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(tp.urllib.request, "urlopen", fake_urlopen)

    tp._cmd_think(make_ctx("think مرحبا", ["مرحبا"], engine=bare_engine))
    state = tp._state(bare_engine)
    assert state["history"] == []


# ── think: plain answer (no tool call), including self-critique pass ────

def test_think_plain_reply_no_tool_call(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, [
        "الإجابة البسيطة من غير أداة",
        "الإجابة البسيطة من غير أداة",  # المراجعة الذاتية بتأكد الإجابة زي ما هي
    ])
    result = tp._cmd_think(make_ctx("think ايه رأيك", ["ايه", "رأيك"], engine=bare_engine))
    assert "🧠" in result
    assert "الإجابة البسيطة" in result
    state = tp._state(bare_engine)
    # user + assistant(draft) + assistant(critique)
    assert len(state["history"]) == 3
    assert state["pending_tool"] is None
    assert state["plan"] is None


def test_think_critique_can_revise_the_draft(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, [
        "مسودة أولى فيها نقص",
        "نسخة محسّنة وأدق بعد المراجعة",
    ])
    result = tp._cmd_think(make_ctx("think اشرحلي", ["اشرحلي"], engine=bare_engine))
    assert "نسخة محسّنة" in result
    assert "مسودة أولى" not in result  # النسخة النهائية بس اللي بتتعرض


def test_think_critique_disabled_skips_second_call(make_ctx, monkeypatch, bare_engine):
    tp._cmd_think_critique(make_ctx("think_critique off", ["off"], engine=bare_engine))
    calls = _mock_ollama_sequence(monkeypatch, ["إجابة من غير مراجعة"])
    result = tp._cmd_think(make_ctx("think سؤال", ["سؤال"], engine=bare_engine))
    assert calls["i"] == 1
    assert "إجابة من غير مراجعة" in result


def test_think_critique_ollama_failure_falls_back_to_draft(make_ctx, monkeypatch, bare_engine):
    calls = {"i": 0}

    def fake_urlopen(req, timeout):
        calls["i"] += 1
        if calls["i"] == 1:
            return _fake_chat_response("المسودة الأصلية")
        raise urllib.error.URLError("ollama died mid-critique")
    monkeypatch.setattr(tp.urllib.request, "urlopen", fake_urlopen)

    result = tp._cmd_think(make_ctx("think سؤال", ["سؤال"], engine=bare_engine))
    assert "المسودة الأصلية" in result  # fail-open: رجع للمسودة الأصلية


# ── think: multi-step plan tracking ─────────────────────────────────────

def test_think_plan_line_extracted_and_shown(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, [
        "PLAN: افحص النظام؛ اجمع البيانات؛ لخّص\nهبدأ بالخطوة الأولى\nTOOL: help",
    ])
    result = tp._cmd_think(make_ctx("think حل المشكلة دي", ["حل"], engine=bare_engine))
    assert "🗺" in result
    assert "افحص النظام" in result
    state = tp._state(bare_engine)
    assert state["plan"] == "افحص النظام؛ اجمع البيانات؛ لخّص"


def test_think_plan_persists_across_tool_confirmation_and_clears_on_final_answer(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, [
        "PLAN: خطوة واحدة بس\nهفحص\nTOOL: help",
        "خلصت المهمة، دي الإجابة النهائية",
        "خلصت المهمة، دي الإجابة النهائية",
    ])
    tp._cmd_think(make_ctx("think مهمة", ["مهمة"], engine=bare_engine))
    state = tp._state(bare_engine)
    assert state["plan"] == "خطوة واحدة بس"

    tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))
    state = tp._state(bare_engine)
    assert state["plan"] is None  # اتمسحت لما وصل لإجابة نهائية


# ── think: proposes a real tool, requires confirmation ──────────────────

def test_think_proposes_real_tool_and_waits_for_confirmation(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, ["هفحص الأوامر المتاحة\nTOOL: help"])
    result = tp._cmd_think(make_ctx("think ايه الأوامر المتاحة", ["ايه"], engine=bare_engine))
    assert "🔧" in result
    assert "help" in result
    assert "think y" in result
    state = tp._state(bare_engine)
    assert state["pending_tool"] == ("help", [])


def test_think_confirm_yes_actually_runs_tool_and_continues(make_ctx, monkeypatch, bare_engine):
    calls = _mock_ollama_sequence(monkeypatch, [
        "هفحص الأوامر المتاحة\nTOOL: help",
        "شفت الأوامر، مفيش حاجة تانية محتاجها",
        "شفت الأوامر، مفيش حاجة تانية محتاجها",  # مراجعة ذاتية
    ])
    tp._cmd_think(make_ctx("think ايه الأوامر المتاحة", ["ايه"], engine=bare_engine))
    result = tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))

    assert calls["i"] == 3  # اقتراح + استكمال + مراجعة ذاتية
    assert "شفت الأوامر" in result
    state = tp._state(bare_engine)
    assert state["pending_tool"] is None
    # نتيجة تشغيل الأداة الحقيقية (help) لازم تكون اتسجلت في التاريخ
    tool_result_messages = [m for m in state["history"] if "نتيجة تشغيل help" in m.get("content", "")]
    assert len(tool_result_messages) == 1
    assert "echo" in tool_result_messages[0]["content"]  # ناتج أمر help الحقيقي فيه أسماء أوامر تانية زي echo


def test_think_confirm_no_skips_tool_and_continues(make_ctx, monkeypatch, bare_engine):
    calls = _mock_ollama_sequence(monkeypatch, [
        "هفحص الأوامر المتاحة\nTOOL: help",
        "تمام، هجاوب من غير ما أستخدم الأداة",
        "تمام، هجاوب من غير ما أستخدم الأداة",  # مراجعة ذاتية
    ])
    tp._cmd_think(make_ctx("think ايه الأوامر المتاحة", ["ايه"], engine=bare_engine))
    result = tp._cmd_think(make_ctx("think n", ["n"], engine=bare_engine))

    assert calls["i"] == 3
    assert "هجاوب من غير" in result
    state = tp._state(bare_engine)
    assert state["pending_tool"] is None
    rejection_messages = [m for m in state["history"] if "رفضت" in m.get("content", "")]
    assert len(rejection_messages) == 1


def test_think_unrelated_reply_discards_pending_and_processes_fresh(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, [
        "هفحص الأوامر المتاحة\nTOOL: help",
        "إجابة على السؤال الجديد",
        "إجابة على السؤال الجديد",  # مراجعة ذاتية
    ])
    tp._cmd_think(make_ctx("think ايه الأوامر المتاحة", ["ايه"], engine=bare_engine))
    state = tp._state(bare_engine)
    assert state["pending_tool"] is not None

    result = tp._cmd_think(make_ctx("think خليها سؤال تاني خالص", ["خليها"], engine=bare_engine))
    assert "إجابة على السؤال الجديد" in result
    state = tp._state(bare_engine)
    assert state["pending_tool"] is None


def test_think_hallucinated_tool_name_rejected(make_ctx, monkeypatch, bare_engine):
    """النموذج ممكن "يهلوس" اسم أداة مش موجودة فعليًا — لازم يتجاهلها
    ويوريها كإجابة عادية بدل ما يصدّقها أعمى."""
    _mock_ollama_sequence(monkeypatch, [
        "هستخدم أداة سحرية\nTOOL: this_tool_does_not_exist_anywhere",
        "هستخدم أداة سحرية",  # مراجعة ذاتية (بعد ما اتشالت سطر TOOL الوهمي)
    ])
    result = tp._cmd_think(make_ctx("think جرب حاجة", ["جرب"], engine=bare_engine))
    assert "🧠" in result
    assert "هستخدم أداة سحرية" in result
    state = tp._state(bare_engine)
    assert state["pending_tool"] is None  # مفيش pending — الأداة الوهمية اتجاهلت


# ── tool failure recovery ───────────────────────────────────────────────

def test_think_tool_failure_streak_suppresses_further_tool_proposals(make_ctx, monkeypatch, bare_engine):
    bare_engine.registry.register("boom", lambda ctx: 1 / 0, "explodes")
    replies = [
        "محاولة 1\nTOOL: boom",
        "محاولة 2\nTOOL: boom",
        "محاولة 3\nTOOL: boom",
        # بعد 3 فشلات متتالية، طلب الأداة الرابع لازم يتجاهل ويتحول لإجابة نهائية
        "هجرب تاني\nTOOL: boom",
        "هجرب تاني",  # مراجعة ذاتية
    ]
    _mock_ollama_sequence(monkeypatch, replies)

    tp._cmd_think(make_ctx("think جرب", ["جرب"], engine=bare_engine))
    tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))  # فشل 1، هيقترح تاني
    state = tp._state(bare_engine)
    assert state["pending_tool"] == ("boom", [])

    tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))  # فشل 2
    state = tp._state(bare_engine)
    assert state["pending_tool"] == ("boom", [])

    result = tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))  # فشل 3 → suppress
    state = tp._state(bare_engine)
    assert state["pending_tool"] is None  # اتجاهل الاقتراح الرابع بسبب الفشل المتكرر
    assert "فشل متكرر" in result
    assert state["tool_fail_streak"] == 0  # اتصفّر بعد التنبيه


def test_think_tool_success_resets_failure_streak(make_ctx, monkeypatch, bare_engine):
    bare_engine.registry.register("boom", lambda ctx: 1 / 0, "explodes")
    _mock_ollama_sequence(monkeypatch, [
        "محاولة\nTOOL: boom",
        "بعد الفشل هستخدم help\nTOOL: help",
    ])
    tp._cmd_think(make_ctx("think جرب", ["جرب"], engine=bare_engine))
    tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))
    state = tp._state(bare_engine)
    assert state["tool_fail_streak"] == 1

    _mock_ollama_sequence(monkeypatch, ["تمام كده", "تمام كده"])
    tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))  # help تنجح
    state = tp._state(bare_engine)
    assert state["tool_fail_streak"] == 0


# ── smart tool selection (relevance filtering) ──────────────────────────

def test_relevant_tools_returns_all_when_under_limit(bare_engine):
    tools = tp._relevant_tools(bare_engine, "أي سؤال عادي")
    assert len(tools) == len(bare_engine.registry.list_commands())


def test_relevant_tools_filters_and_always_keeps_help():
    class FakeCmd:
        def __init__(self, name, description):
            self.name = name
            self.description = description

    class FakeRegistry:
        def __init__(self, commands):
            self._commands = {c.name: c for c in commands}

        def list_commands(self):
            return list(self._commands.values())

        def get(self, name):
            return self._commands.get(name)

    class FakeEngine:
        pass

    commands = [FakeCmd("help", "عرض كل الأوامر")]
    commands += [FakeCmd(f"unrelated_{i}", "شيء عشوائي مالوش علاقة") for i in range(30)]
    commands.append(FakeCmd("youtube_seo", "تحسين ظهور فيديو يوتيوب في نتائج البحث"))

    engine = FakeEngine()
    engine.registry = FakeRegistry(commands)

    result = tp._relevant_tools(engine, "عايز أحسن ظهور فيديو يوتيوب بتاعي")
    names = [c.name for c in result]
    assert "youtube_seo" in names
    assert "help" in names
    assert len(result) <= tp.RELEVANT_TOOLS_LIMIT + 1


# ── persistent memory (think_remember / think_forget) ───────────────────

def test_think_remember_saves_note(make_ctx, bare_engine):
    result = tp._cmd_think_remember(make_ctx("think_remember المستخدم بيفضل الشرح المختصر", ["المستخدم"], engine=bare_engine))
    assert "💾" in result
    assert tp._load_memory() == ["المستخدم بيفضل الشرح المختصر"]


def test_think_remember_no_text_shows_usage(make_ctx, bare_engine):
    result = tp._cmd_think_remember(make_ctx("think_remember", [], engine=bare_engine))
    assert result.startswith("usage")


def test_think_forget_clears_all_notes(make_ctx, bare_engine):
    tp._cmd_think_remember(make_ctx("think_remember ملاحظة 1", ["ملاحظة", "1"], engine=bare_engine))
    tp._cmd_think_remember(make_ctx("think_remember ملاحظة 2", ["ملاحظة", "2"], engine=bare_engine))
    assert len(tp._load_memory()) == 2

    result = tp._cmd_think_forget(make_ctx("think_forget", [], engine=bare_engine))
    assert "🗑" in result
    assert tp._load_memory() == []


def test_think_memory_injected_into_system_prompt(bare_engine):
    tp._save_memory(["حقيقة دائمة محفوظة من قبل"])
    prompt = tp._system_prompt(bare_engine, "سؤال عادي", tp._state(bare_engine))
    assert "حقيقة دائمة محفوظة من قبل" in prompt


def test_think_memory_survives_think_reset(make_ctx, monkeypatch, bare_engine):
    tp._cmd_think_remember(make_ctx("think_remember ثابتة", ["ثابتة"], engine=bare_engine))
    _mock_ollama_sequence(monkeypatch, ["رد", "رد"])
    tp._cmd_think(make_ctx("think سؤال", ["سؤال"], engine=bare_engine))
    tp._cmd_think_reset(make_ctx("think_reset", [], engine=bare_engine))
    assert tp._load_memory() == ["ثابتة"]


# ── multi-turn memory (conversation history, not persistent notes) ──────

def test_think_maintains_conversation_history_across_turns(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, [
        "الرد الأول", "الرد الأول",  # draft + critique
        "الرد الثاني", "الرد الثاني",  # draft + critique
    ])
    tp._cmd_think(make_ctx("think السؤال الأول", ["السؤال"], engine=bare_engine))
    tp._cmd_think(make_ctx("think السؤال الثاني", ["السؤال"], engine=bare_engine))
    state = tp._state(bare_engine)
    # (user + assistant + critique) × 2 = 6
    assert len(state["history"]) == 6
    assert state["history"][0]["content"] == "السؤال الأول"
    assert state["history"][3]["content"] == "السؤال الثاني"


def test_think_reset_clears_history(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, ["رد", "رد"])
    tp._cmd_think(make_ctx("think سؤال", ["سؤال"], engine=bare_engine))
    state = tp._state(bare_engine)
    assert len(state["history"]) == 3

    result = tp._cmd_think_reset(make_ctx("think_reset", [], engine=bare_engine))
    assert "اتمسحت" in result
    state = tp._state(bare_engine)
    assert state["history"] == []
    assert state["pending_tool"] is None
    assert state["plan"] is None


# ── think_status ─────────────────────────────────────────────────────

def test_think_status_shows_model_and_count(make_ctx, bare_engine):
    result = tp._cmd_think_status(make_ctx("think_status", [], engine=bare_engine))
    assert "llama3.2" in result
    assert "0" in result


def test_think_status_shows_pending_tool(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, ["هفحص\nTOOL: help"])
    tp._cmd_think(make_ctx("think جرب", ["جرب"], engine=bare_engine))
    result = tp._cmd_think_status(make_ctx("think_status", [], engine=bare_engine))
    assert "help" in result


def test_think_status_shows_critique_and_memory_state(make_ctx, bare_engine):
    tp._cmd_think_remember(make_ctx("think_remember ملحوظة", ["ملحوظة"], engine=bare_engine))
    result = tp._cmd_think_status(make_ctx("think_status", [], engine=bare_engine))
    assert "شغالة" in result
    assert "1" in result


# ── think_model ──────────────────────────────────────────────────────

def test_think_model_no_args_shows_current(make_ctx, bare_engine):
    result = tp._cmd_think_model(make_ctx("think_model", [], engine=bare_engine))
    assert "llama3.2" in result


def test_think_model_changes_model(make_ctx, bare_engine):
    result = tp._cmd_think_model(make_ctx("think_model", ["deepseek-r1"], engine=bare_engine))
    assert "deepseek-r1" in result
    state = tp._state(bare_engine)
    assert state["model"] == "deepseek-r1"


def test_think_uses_configured_model(make_ctx, monkeypatch, bare_engine):
    tp._cmd_think_model(make_ctx("think_model", ["custom-model"], engine=bare_engine))
    captured = {}

    def fake_urlopen(req, timeout):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _fake_chat_response("رد")
    monkeypatch.setattr(tp.urllib.request, "urlopen", fake_urlopen)

    tp._cmd_think(make_ctx("think سؤال", ["سؤال"], engine=bare_engine))
    assert captured["payload"]["model"] == "custom-model"


# ── think_critique ───────────────────────────────────────────────────

def test_think_critique_no_args_shows_status(make_ctx, bare_engine):
    result = tp._cmd_think_critique(make_ctx("think_critique", [], engine=bare_engine))
    assert "شغالة" in result


def test_think_critique_off_then_on(make_ctx, bare_engine):
    result = tp._cmd_think_critique(make_ctx("think_critique off", ["off"], engine=bare_engine))
    assert "متوقفة" in result
    state = tp._state(bare_engine)
    assert state["critique_enabled"] is False

    result = tp._cmd_think_critique(make_ctx("think_critique on", ["on"], engine=bare_engine))
    assert "شغالة" in result
    state = tp._state(bare_engine)
    assert state["critique_enabled"] is True


def test_think_critique_invalid_arg_shows_usage(make_ctx, bare_engine):
    result = tp._cmd_think_critique(make_ctx("think_critique maybe", ["maybe"], engine=bare_engine))
    assert result.startswith("usage")


# ── _invoke_tool ─────────────────────────────────────────────────────

def test_invoke_tool_unknown_command(bare_engine):
    result = tp._invoke_tool(bare_engine, "totally_unknown_xyz", [])
    assert result.startswith("❌")


def test_invoke_tool_runs_real_registered_command(bare_engine):
    result = tp._invoke_tool(bare_engine, "echo", ["hello", "world"])
    assert result == "hello world"


def test_invoke_tool_handles_handler_exception(bare_engine):
    bare_engine.registry.register("boom", lambda ctx: 1 / 0, "explodes")
    result = tp._invoke_tool(bare_engine, "boom", [])
    assert result.startswith("❌")


# ── register ─────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    tp.register(FakeEngine)
    for cmd in (
        "think", "think_reset", "think_status", "think_model",
        "think_critique", "think_remember", "think_forget", "think_playbooks",
    ):
        assert cmd in FakeEngine.registry.names


# ── think_playbooks ───────────────────────────────────────────────────

def test_playbook_name_validation():
    assert tp._valid_playbook_name("youtube_seo")
    assert tp._valid_playbook_name("خطة-يوتيوب")
    assert not tp._valid_playbook_name("../../etc/passwd")
    assert not tp._valid_playbook_name("bad name")
    assert not tp._valid_playbook_name("bad/name")
    assert not tp._valid_playbook_name("")


def test_playbooks_add_and_list(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx(
        "think_playbooks add yt_seo دايمًا استخدم channel_growth_report الأول",
        ["add", "yt_seo", "دايمًا", "استخدم", "channel_growth_report", "الأول"],
        engine=bare_engine,
    ))
    assert "✅" in result
    assert "yt_seo" in result

    result = tp._cmd_think_playbooks(make_ctx("think_playbooks list", ["list"], engine=bare_engine))
    assert "yt_seo" in result


def test_playbooks_add_rejects_invalid_name(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx(
        "think_playbooks add ../evil محتوى خبيث",
        ["add", "../evil", "محتوى", "خبيث"],
        engine=bare_engine,
    ))
    assert result.startswith("❌")
    assert tp._list_playbooks() == []


def test_playbooks_add_no_content_shows_usage(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks add yt_seo", ["add", "yt_seo"], engine=bare_engine))
    assert result.startswith("usage")


def test_playbooks_list_empty(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks list", ["list"], engine=bare_engine))
    assert "مفيش" in result


def test_playbooks_show(make_ctx, bare_engine):
    tp._cmd_think_playbooks(make_ctx(
        "think_playbooks add yt_seo محتوى تفصيلي هنا",
        ["add", "yt_seo", "محتوى", "تفصيلي", "هنا"],
        engine=bare_engine,
    ))
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks show yt_seo", ["show", "yt_seo"], engine=bare_engine))
    assert "محتوى تفصيلي هنا" in result


def test_playbooks_show_unknown(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks show ghost", ["show", "ghost"], engine=bare_engine))
    assert result.startswith("❌")


def test_playbooks_remove(make_ctx, bare_engine):
    tp._cmd_think_playbooks(make_ctx(
        "think_playbooks add yt_seo محتوى", ["add", "yt_seo", "محتوى"], engine=bare_engine,
    ))
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks remove yt_seo", ["remove", "yt_seo"], engine=bare_engine))
    assert "🗑" in result
    assert tp._list_playbooks() == []


def test_playbooks_remove_unknown(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks remove ghost", ["remove", "ghost"], engine=bare_engine))
    assert result.startswith("❌")


def test_playbooks_no_args_shows_usage(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks", [], engine=bare_engine))
    assert result.startswith("usage")


def test_playbooks_unknown_subcommand_shows_usage(make_ctx, bare_engine):
    result = tp._cmd_think_playbooks(make_ctx("think_playbooks frobnicate", ["frobnicate"], engine=bare_engine))
    assert result.startswith("usage")


# ── _relevant_playbooks ──────────────────────────────────────────────

def test_relevant_playbooks_matches_by_keyword_overlap(bare_engine):
    tp._write_playbook("yt", "لما حد يسأل عن قناة يوتيوب استخدم channel_growth_report")
    tp._write_playbook("db", "لما حد يسأل عن قاعدة بيانات استخدم db_migrate")

    result = tp._relevant_playbooks("عايز أحلل قناة يوتيوب بتاعتي")
    names = [name for name, _ in result]
    assert "yt" in names
    assert "db" not in names


def test_relevant_playbooks_empty_when_no_match(bare_engine):
    tp._write_playbook("yt", "لما حد يسأل عن قناة يوتيوب استخدم channel_growth_report")
    result = tp._relevant_playbooks("سؤال مالوش أي علاقة خالص بكلمات تانية")
    assert result == []


def test_relevant_playbooks_empty_when_no_playbooks_exist(bare_engine):
    assert tp._relevant_playbooks("عايز أحلل قناة يوتيوب") == []


def test_relevant_playbooks_truncates_long_content(bare_engine):
    long_content = "يوتيوب " * 1000
    tp._write_playbook("yt", long_content)
    result = tp._relevant_playbooks("يوتيوب")
    assert len(result) == 1
    assert len(result[0][1]) <= tp.MAX_PLAYBOOK_CHARS


def test_system_prompt_injects_relevant_playbook(bare_engine):
    tp._write_playbook("yt", "لما حد يسأل عن قناة يوتيوب استخدم channel_growth_report الأول")
    prompt = tp._system_prompt(bare_engine, "عايز أحلل قناة يوتيوب", tp._state(bare_engine))
    assert "channel_growth_report" in prompt
    assert "yt" in prompt


def test_system_prompt_skips_irrelevant_playbook(bare_engine):
    tp._write_playbook("yt", "لما حد يسأل عن قناة يوتيوب استخدم channel_growth_report الأول")
    prompt = tp._system_prompt(bare_engine, "سؤال عادي عن حاجة تانية خالص", tp._state(bare_engine))
    assert "channel_growth_report" not in prompt
