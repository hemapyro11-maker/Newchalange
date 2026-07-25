import json
import urllib.error

import think_plugin as tp


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


# ── think: plain answer (no tool call) ──────────────────────────────────

def test_think_plain_reply_no_tool_call(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, ["الإجابة البسيطة من غير أداة"])
    result = tp._cmd_think(make_ctx("think ايه رأيك", ["ايه", "رأيك"], engine=bare_engine))
    assert "🧠" in result
    assert "الإجابة البسيطة" in result
    state = tp._state(bare_engine)
    assert len(state["history"]) == 2  # user + assistant
    assert state["pending_tool"] is None


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
    ])
    tp._cmd_think(make_ctx("think ايه الأوامر المتاحة", ["ايه"], engine=bare_engine))
    result = tp._cmd_think(make_ctx("think y", ["y"], engine=bare_engine))

    assert calls["i"] == 2  # اتنادى Ollama مرتين: مرة للاقتراح ومرة بعد نتيجة الأداة
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
    ])
    tp._cmd_think(make_ctx("think ايه الأوامر المتاحة", ["ايه"], engine=bare_engine))
    result = tp._cmd_think(make_ctx("think n", ["n"], engine=bare_engine))

    assert calls["i"] == 2
    assert "هجاوب من غير" in result
    state = tp._state(bare_engine)
    assert state["pending_tool"] is None
    rejection_messages = [m for m in state["history"] if "رفضت" in m.get("content", "")]
    assert len(rejection_messages) == 1


def test_think_unrelated_reply_discards_pending_and_processes_fresh(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, [
        "هفحص الأوامر المتاحة\nTOOL: help",
        "إجابة على السؤال الجديد",
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
    _mock_ollama_sequence(monkeypatch, ["هستخدم أداة سحرية\nTOOL: this_tool_does_not_exist_anywhere"])
    result = tp._cmd_think(make_ctx("think جرب حاجة", ["جرب"], engine=bare_engine))
    assert "🧠" in result
    assert "هستخدم أداة سحرية" in result
    state = tp._state(bare_engine)
    assert state["pending_tool"] is None  # مفيش pending — الأداة الوهمية اتجاهلت


# ── multi-turn memory ────────────────────────────────────────────────

def test_think_maintains_conversation_history_across_turns(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, ["الرد الأول", "الرد الثاني"])
    tp._cmd_think(make_ctx("think السؤال الأول", ["السؤال"], engine=bare_engine))
    tp._cmd_think(make_ctx("think السؤال الثاني", ["السؤال"], engine=bare_engine))
    state = tp._state(bare_engine)
    # 2 رسائل مستخدم + 2 رد مساعد = 4
    assert len(state["history"]) == 4
    assert state["history"][0]["content"] == "السؤال الأول"
    assert state["history"][2]["content"] == "السؤال الثاني"


def test_think_reset_clears_history(make_ctx, monkeypatch, bare_engine):
    _mock_ollama_sequence(monkeypatch, ["رد"])
    tp._cmd_think(make_ctx("think سؤال", ["سؤال"], engine=bare_engine))
    state = tp._state(bare_engine)
    assert len(state["history"]) == 2

    result = tp._cmd_think_reset(make_ctx("think_reset", [], engine=bare_engine))
    assert "اتمسحت" in result
    state = tp._state(bare_engine)
    assert state["history"] == []
    assert state["pending_tool"] is None


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
    for cmd in ("think", "think_reset", "think_status", "think_model"):
        assert cmd in FakeEngine.registry.names
