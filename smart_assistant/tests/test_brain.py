import json
import time

import brain
import pytest


@pytest.fixture(autouse=True)
def _isolate_brain(tmp_path, monkeypatch):
    """كل اختبار بمجلد خاص — عشان محدش يكتب فوق brain_config.json
    أو brain_state.json الحقيقيين بتوع المستخدم."""
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(brain, "_HAS_KEYRING", False)
    brain.reset_brain()
    brain._probe_cache.clear()
    yield
    brain.reset_brain()


def _key(provider: str, value: str = "testkey"):
    brain.set_key(provider, value)


# ── قص السياق ────────────────────────────────────────────────────────

def test_fit_to_context_keeps_system_and_last_message():
    msgs = [
        {"role": "system", "content": "تعليمات"},
        {"role": "user", "content": "قديم " * 5000},
        {"role": "assistant", "content": "رد قديم " * 5000},
        {"role": "user", "content": "السؤال الحالي"},
    ]
    fitted = brain._fit_to_context(msgs, 1000)
    assert fitted[0]["role"] == "system"
    assert fitted[-1]["content"] == "السؤال الحالي"


def test_fit_to_context_drops_old_turns_to_fit_small_window():
    msgs = [{"role": "user", "content": "x" * 3000} for _ in range(10)]
    fitted = brain._fit_to_context(msgs, 1000)
    total = sum(brain.estimate_tokens(m["content"]) for m in fitted)
    assert total <= 1000
    assert len(fitted) < len(msgs)


def test_fit_to_context_truncates_single_oversized_message():
    # حتى لو رسالة واحدة أكبر من السياق كله، لازم نرجّع حاجة صالحة
    # مش قايمة فاضية (وإلا الطلب هيتبعت من غير سؤال أصلاً)
    msgs = [{"role": "user", "content": "ط" * 100_000}]
    fitted = brain._fit_to_context(msgs, 500)
    assert len(fitted) == 1
    assert 0 < len(fitted[0]["content"]) < 100_000


def test_fit_to_context_leaves_small_conversation_untouched():
    msgs = [
        {"role": "system", "content": "تعليمات"},
        {"role": "user", "content": "إزيك"},
    ]
    assert brain._fit_to_context(msgs, 1_000_000) == msgs


# ── تخزين المفاتيح ───────────────────────────────────────────────────

def test_set_and_get_key_roundtrip():
    brain.set_key("groq", "gsk_abc")
    assert brain.get_key("groq") == "gsk_abc"


def test_env_var_beats_stored_key(monkeypatch):
    brain.set_key("groq", "stored")
    monkeypatch.setenv("NEZUKO_GROQ_KEY", "from_env")
    assert brain.get_key("groq") == "from_env"


def test_clear_key_removes_it():
    brain.set_key("groq", "x")
    brain.clear_key("groq")
    assert brain.get_key("groq") is None


def test_set_key_without_keyring_reports_plaintext():
    assert brain.set_key("groq", "x") == "plaintext"


# ── سلسلة البدائل ────────────────────────────────────────────────────

def test_chain_excludes_providers_without_keys():
    b = brain.get_brain()
    # مفيش أي مفتاح متظبط، وollama مش محتاج مفتاح
    names = [p.name for p in b.chain()]
    assert names == ["ollama"]


def test_chain_orders_by_quality():
    _key("groq")
    _key("gemini")
    b = brain.get_brain()
    names = [p.name for p in b.chain()]
    # gemini جودته أعلى من groq، وollama أقلهم
    assert names.index("gemini") < names.index("groq") < names.index("ollama")


def test_local_only_mode_excludes_all_cloud_providers():
    _key("gemini")
    _key("groq")
    cfg = brain.load_config()
    cfg["local_only"] = True
    brain.save_config(cfg)
    b = brain.get_brain()
    assert [p.name for p in b.chain()] == ["ollama"]


def test_disabled_provider_is_skipped():
    _key("gemini")
    cfg = brain.load_config()
    cfg["enabled"] = ["gemini"]
    brain.save_config(cfg)
    b = brain.get_brain()
    assert [p.name for p in b.chain()] == ["gemini"]


# ── الحدود ───────────────────────────────────────────────────────────

def test_daily_limit_blocks_provider_when_exhausted():
    _key("groq")
    b = brain.get_brain()
    cfg = brain.load_config()
    prov = brain.PROVIDERS["groq"]
    st = b._states["groq"]
    st.day_count = prov.rpd
    assert not b._available(prov, cfg, time.time())


def test_minute_limit_blocks_provider_when_exhausted():
    _key("groq")
    b = brain.get_brain()
    cfg = brain.load_config()
    prov = brain.PROVIDERS["groq"]
    now = time.time()
    b._states["groq"].minute_hits = [now] * prov.rpm
    assert not b._available(prov, cfg, now)


def test_minute_limit_recovers_after_window_passes():
    _key("groq")
    b = brain.get_brain()
    cfg = brain.load_config()
    prov = brain.PROVIDERS["groq"]
    now = time.time()
    b._states["groq"].minute_hits = [now - 120] * prov.rpm  # كلهم قدام
    assert b._available(prov, cfg, now)


def test_daily_counter_survives_restart():
    # راجع: من غير حفظ العدّاد على القرص، إعادة تشغيل البرنامج كانت
    # بتصفّر معرفتنا بالحد اليومي، فأول نداء بعد التشغيل يضرب الحد.
    _key("groq")
    b = brain.get_brain()
    b._note_success("groq", time.time())
    b._note_success("groq", time.time())
    assert b._states["groq"].day_count == 2

    brain.reset_brain()
    fresh = brain.get_brain()
    assert fresh._states["groq"].day_count == 2


def test_daily_counter_resets_on_new_day(tmp_path):
    _key("groq")
    brain._state_path().write_text(
        json.dumps({"groq": {"day_count": 999, "day_stamp": "2020-01-01"}}),
        encoding="utf-8",
    )
    brain.reset_brain()
    b = brain.get_brain()
    assert b._states["groq"].day_count == 0


def test_config_limit_override_is_respected():
    _key("groq")
    cfg = brain.load_config()
    cfg["limits"] = {"groq": {"rpm": 1, "rpd": 1}}
    brain.save_config(cfg)
    b = brain.get_brain()
    b._states["groq"].day_count = 1
    assert not b._available(brain.PROVIDERS["groq"], brain.load_config(), time.time())


# ── قاطع الدائرة ─────────────────────────────────────────────────────

def test_circuit_breaker_opens_after_repeated_failures():
    _key("groq")
    b = brain.get_brain()
    now = time.time()
    b._note_failure("groq", now, rate_limited=False)
    assert b._available(brain.PROVIDERS["groq"], brain.load_config(), now)  # فشل واحد لسه مقبول
    b._note_failure("groq", now, rate_limited=False)
    assert not b._available(brain.PROVIDERS["groq"], brain.load_config(), now)


def test_circuit_breaker_backoff_grows_but_is_capped():
    _key("groq")
    b = brain.get_brain()
    now = time.time()
    for _ in range(20):
        b._note_failure("groq", now, rate_limited=False)
    assert b._states["groq"].cold_until - now <= 600


def test_rate_limited_failure_cools_provider_for_a_minute():
    _key("groq")
    b = brain.get_brain()
    now = time.time()
    b._note_failure("groq", now, rate_limited=True)
    assert b._states["groq"].cold_until >= now + 59


def test_success_resets_failure_count():
    _key("groq")
    b = brain.get_brain()
    now = time.time()
    b._note_failure("groq", now, rate_limited=False)
    b._note_failure("groq", now, rate_limited=False)
    b._note_success("groq", now)
    assert b._states["groq"].fails == 0
    assert b._available(brain.PROVIDERS["groq"], brain.load_config(), now)


# ── chat + الانتقال للبديل ───────────────────────────────────────────

def test_chat_returns_error_when_nothing_configured(monkeypatch):
    cfg = brain.load_config()
    cfg["enabled"] = []
    brain.save_config(cfg)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert not reply
    assert "مفيش أي مخ" in reply.error


def test_chat_uses_highest_quality_provider_first(monkeypatch):
    _key("gemini")
    _key("groq")
    used = []

    def fake_call(prov, model, messages, temperature, max_tokens):
        used.append(prov.name)
        return "رد"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert reply.provider == "gemini"
    assert used == ["gemini"]


def test_chat_falls_over_to_next_provider_on_failure(monkeypatch):
    _key("gemini")
    _key("groq")
    used = []

    def fake_call(prov, model, messages, temperature, max_tokens):
        used.append(prov.name)
        if prov.name == "gemini":
            raise RuntimeError("سيرفر واقع")
        return "رد من البديل"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert reply.text == "رد من البديل"
    assert reply.provider == "groq"
    assert used == ["gemini", "groq"]


def test_chat_falls_over_on_rate_limit(monkeypatch):
    _key("gemini")
    _key("groq")

    def fake_call(prov, model, messages, temperature, max_tokens):
        if prov.name == "gemini":
            raise brain._RateLimited("429")
        return "بديل"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert reply.provider == "groq"


def test_chat_skips_empty_reply_and_tries_next(monkeypatch):
    _key("gemini")
    _key("groq")

    def fake_call(prov, model, messages, temperature, max_tokens):
        return "" if prov.name == "gemini" else "رد حقيقي"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert reply.provider == "groq"


def test_chat_reports_error_when_all_providers_fail(monkeypatch):
    _key("gemini")

    def fake_call(*a, **k):
        raise RuntimeError("مقفول")

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert not reply
    assert "مقفول" in reply.error


def test_chat_error_mentions_every_provider_that_failed(monkeypatch):
    """راجع: لو Gemini فشل بسبب حقيقي (quota) وبعده Ollama فشل لأنه
    مش شغال، الرسالة القديمة كانت بتوريك آخر مزوّد بس وتخبي السبب
    الحقيقي — المستخدم كان يفتكر المشكلة في Ollama."""
    _key("gemini")
    cfg = brain.load_config()
    cfg["enabled"] = ["gemini", "ollama"]
    brain.save_config(cfg)

    def fake_call(prov, *a, **k):
        if prov.name == "gemini":
            raise brain._RateLimited("quota exceeded")
        raise RuntimeError("connection refused")

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert not reply
    assert "quota exceeded" in reply.error
    assert "connection refused" in reply.error
    assert "Gemini" in reply.error and "Ollama" in reply.error


def test_chat_marks_local_provider_as_local(monkeypatch):
    monkeypatch.setattr(brain, "_call_provider", lambda *a, **k: "رد محلي")
    cfg = brain.load_config()
    cfg["enabled"] = ["ollama"]
    brain.save_config(cfg)
    reply = brain.get_brain().chat([{"role": "user", "content": "hi"}])
    assert reply.is_local is True
    assert reply.provider == "ollama"


def test_chat_truncates_history_to_active_provider_context(monkeypatch):
    # ده الاختبار المهم: محادثة طويلة اتبنت على مزوّد سياقه كبير، ولما
    # تتحوّل لمزوّد سياقه صغير لازم تتقص — مش تتبعت كما هي وتقع.
    cfg = brain.load_config()
    cfg["enabled"] = ["ollama"]
    brain.save_config(cfg)
    seen = {}

    def fake_call(prov, model, messages, temperature, max_tokens):
        seen["count"] = len(messages)
        seen["tokens"] = sum(brain.estimate_tokens(m["content"]) for m in messages)
        return "ok"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    long_history = [{"role": "user", "content": "كلام طويل " * 2000} for _ in range(20)]
    brain.get_brain().chat(long_history)
    assert seen["tokens"] <= brain.PROVIDERS["ollama"].context
    assert seen["count"] < 20


# ── الوضع العميق ─────────────────────────────────────────────────────

def test_deep_chat_falls_back_to_normal_with_single_provider(monkeypatch):
    _key("gemini")
    cfg = brain.load_config()
    cfg["enabled"] = ["gemini"]
    brain.save_config(cfg)
    monkeypatch.setattr(brain, "_call_provider", lambda *a, **k: "رد واحد")
    reply = brain.get_brain().deep_chat([{"role": "user", "content": "hi"}])
    assert reply.text == "رد واحد"


def test_deep_chat_queries_multiple_then_synthesizes(monkeypatch):
    _key("gemini")
    _key("groq")
    _key("cerebras")
    calls = []

    def fake_call(prov, model, messages, temperature, max_tokens):
        calls.append(prov.name)
        joined = " ".join(m["content"] for m in messages)
        if "مُجمِّع إجابات" in joined:
            return "الإجابة المدموجة"
        return f"مسودة من {prov.name}"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().deep_chat([{"role": "user", "content": "سؤال صعب"}])
    assert reply.text == "الإجابة المدموجة"
    assert reply.provider == "deep"
    # 3 مقترحين + مُجمِّع = 4 نداءات
    assert len(calls) == 4


def test_deep_chat_returns_best_draft_when_synthesis_fails(monkeypatch):
    _key("gemini")
    _key("groq")
    state = {"n": 0}

    def fake_call(prov, model, messages, temperature, max_tokens):
        joined = " ".join(m["content"] for m in messages)
        if "مُجمِّع إجابات" in joined:
            raise RuntimeError("المُجمِّع وقع")
        state["n"] += 1
        return f"مسودة {state['n']}"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().deep_chat([{"role": "user", "content": "س"}])
    assert reply.text.startswith("مسودة")
    assert "بدون دمج" in reply.label


def test_deep_chat_survives_one_proposer_failing(monkeypatch):
    _key("gemini")
    _key("groq")
    _key("cerebras")

    def fake_call(prov, model, messages, temperature, max_tokens):
        if prov.name == "groq":
            raise RuntimeError("واقع")
        joined = " ".join(m["content"] for m in messages)
        if "مُجمِّع إجابات" in joined:
            return "مدموج"
        return f"مسودة {prov.name}"

    monkeypatch.setattr(brain, "_call_provider", fake_call)
    reply = brain.get_brain().deep_chat([{"role": "user", "content": "س"}])
    assert reply.text == "مدموج"


# ── المحوّلات ────────────────────────────────────────────────────────

def test_openai_adapter_builds_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update(url=url, payload=payload, headers=headers)
        return {"choices": [{"message": {"content": "أهلاً"}}]}

    monkeypatch.setattr(brain, "_post_json", fake_post)
    brain.set_key("groq", "gsk_secret")
    out = brain._call_openai_compatible(
        brain.PROVIDERS["groq"], "m1", [{"role": "user", "content": "hi"}], 0.5, 100
    )
    assert out == "أهلاً"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer gsk_secret"
    assert captured["payload"]["model"] == "m1"
    assert captured["payload"]["stream"] is False


def test_openrouter_adapter_adds_required_identity_headers(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        brain, "_post_json",
        lambda url, payload, headers, timeout: captured.update(headers=headers)
        or {"choices": [{"message": {"content": "x"}}]},
    )
    brain.set_key("openrouter", "k")
    brain._call_openai_compatible(
        brain.PROVIDERS["openrouter"], "m", [{"role": "user", "content": "hi"}], 0.5, 10
    )
    assert "HTTP-Referer" in captured["headers"]
    assert captured["headers"]["X-Title"] == "Nezuko"


def test_gemini_adapter_maps_roles_and_system_instruction(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update(url=url, payload=payload)
        return {"candidates": [{"content": {"parts": [{"text": "مرحبا"}]}}]}

    monkeypatch.setattr(brain, "_post_json", fake_post)
    brain.set_key("gemini", "AIza_x")
    out = brain._call_gemini(
        brain.PROVIDERS["gemini"], "gemini-2.0-flash",
        [
            {"role": "system", "content": "أنت مساعد"},
            {"role": "user", "content": "إزيك"},
            {"role": "assistant", "content": "كويس"},
        ],
        0.5, 100,
    )
    assert out == "مرحبا"
    # الـ system بيتفصل في حقل خاص، مش جوه contents
    assert captured["payload"]["systemInstruction"]["parts"][0]["text"] == "أنت مساعد"
    roles = [c["role"] for c in captured["payload"]["contents"]]
    assert roles == ["user", "model"]  # assistant بيتحول لـ model
    assert "key=AIza_x" in captured["url"]


def test_gemini_adapter_raises_on_blocked_prompt(monkeypatch):
    monkeypatch.setattr(
        brain, "_post_json",
        lambda *a, **k: {"promptFeedback": {"blockReason": "SAFETY"}},
    )
    brain.set_key("gemini", "k")
    with pytest.raises(RuntimeError, match="SAFETY"):
        brain._call_gemini(
            brain.PROVIDERS["gemini"], "m", [{"role": "user", "content": "x"}], 0.5, 10
        )


def test_gemini_adapter_without_key_raises():
    with pytest.raises(RuntimeError, match="مفتاح"):
        brain._call_gemini(
            brain.PROVIDERS["gemini"], "m", [{"role": "user", "content": "x"}], 0.5, 10
        )


def test_post_json_converts_429_to_rate_limited(monkeypatch):
    import urllib.error

    def raise_429(*a, **k):
        raise urllib.error.HTTPError("u", 429, "Too Many", {}, None)

    monkeypatch.setattr(brain.urllib.request, "urlopen", raise_429)
    with pytest.raises(brain._RateLimited):
        brain._post_json("http://x", {}, {}, 5)


def test_post_json_wraps_other_http_errors(monkeypatch):
    import urllib.error

    def raise_500(*a, **k):
        raise urllib.error.HTTPError("u", 500, "Boom", {}, None)

    monkeypatch.setattr(brain.urllib.request, "urlopen", raise_500)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        brain._post_json("http://x", {}, {}, 5)


# ── الحالة ───────────────────────────────────────────────────────────

def test_status_lists_every_provider_with_key_state(monkeypatch):
    monkeypatch.setattr(brain, "is_local_alive", lambda prov, **kw: True)
    _key("groq")
    rows = brain.get_brain().status()
    by_name = {r["name"]: r for r in rows}
    assert by_name["groq"]["has_key"] is True
    assert by_name["gemini"]["has_key"] is False
    assert by_name["ollama"]["local"] is True


def test_status_reports_local_provider_as_unavailable_when_not_running(monkeypatch):
    # راجع: ollama مش محتاج مفتاح، فكان بيتحسب "جاهز ✅" دايمًا حتى لو
    # مش متثبت على الجهاز خالص — أسوأ من إننا نقول مفيش مخ، لأن
    # المستخدم بيفتكر إن كل حاجة تمام وهي مش شغالة.
    monkeypatch.setattr(brain, "is_local_alive", lambda prov, **kw: False)
    rows = {r["name"]: r for r in brain.get_brain().status()}
    assert rows["ollama"]["has_key"] is False


def test_local_probe_is_cached(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(url, timeout):
        calls["n"] += 1
        raise OSError("down")

    monkeypatch.setattr(brain.urllib.request, "urlopen", fake_urlopen)
    brain._probe_cache.clear()
    prov = brain.PROVIDERS["ollama"]
    assert brain.is_local_alive(prov) is False
    assert brain.is_local_alive(prov) is False
    assert calls["n"] == 1  # الفحص التاني جه من الكاش


def test_local_probe_true_when_server_answers(monkeypatch):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(brain.urllib.request, "urlopen", lambda url, timeout: FakeResp())
    brain._probe_cache.clear()
    assert brain.is_local_alive(brain.PROVIDERS["ollama"]) is True


def test_status_reports_privacy_flag_for_training_providers():
    rows = {r["name"]: r for r in brain.get_brain().status()}
    assert rows["gemini"]["trains_on_input"] is True
    assert rows["groq"]["trains_on_input"] is False


def test_status_counts_usage():
    _key("groq")
    b = brain.get_brain()
    b._note_success("groq", time.time())
    rows = {r["name"]: r for r in b.status()}
    assert rows["groq"]["used_today"] == 1


def test_ready_is_true_when_any_provider_available():
    b = brain.get_brain()
    assert b.ready() is True  # ollama دايمًا في السلسلة
    cfg = brain.load_config()
    cfg["enabled"] = []
    brain.save_config(cfg)
    assert brain.get_brain().ready() is False


# ── المراجعة الذاتية (Chain-of-Verification) ─────────────────────────

def _scripted(monkeypatch, replies):
    """بيرجّع الردود دي بالترتيب، ويسجّل كل نداء."""
    calls = []
    seq = list(replies)

    def fake_chat(self, messages, **kw):
        calls.append(messages)
        text = seq.pop(0) if seq else ""
        return brain.BrainReply(text=text, provider="f", label="F")

    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(brain.Brain, "chat", fake_chat)
    return calls


def test_verified_chat_runs_draft_check_answer_revise(monkeypatch):
    calls = _scripted(monkeypatch, ["draft", "q1\nq2", "a1\na2", "corrected"])
    reply = brain.get_brain().verified_chat([{"role": "user", "content": "س"}])
    assert reply.text == "corrected"
    assert len(calls) == 4


def test_verified_reply_is_labelled_as_verified(monkeypatch):
    _scripted(monkeypatch, ["draft", "q", "a", "final"])
    reply = brain.get_brain().verified_chat([{"role": "user", "content": "س"}])
    assert "verified" in reply.label


def test_verification_questions_see_the_draft(monkeypatch):
    calls = _scripted(monkeypatch, ["the sky is green", "q", "a", "final"])
    brain.get_brain().verified_chat([{"role": "user", "content": "what colour"}])
    assert "the sky is green" in calls[1][-1]["content"]


def test_the_rewrite_sees_both_questions_and_answers(monkeypatch):
    calls = _scripted(monkeypatch, ["draft", "is it green?", "no, blue", "final"])
    brain.get_brain().verified_chat([{"role": "user", "content": "س"}])
    last = calls[3][-1]["content"]
    assert "is it green?" in last
    assert "no, blue" in last


def test_a_failed_draft_short_circuits(monkeypatch):
    """لو المسودة نفسها فشلت مفيش حاجة نتحقق منها — منهدرش 3 نداءات."""
    calls = []
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: [
            calls.append(1), brain.BrainReply(text="", error="down")][1],
    )
    reply = brain.get_brain().verified_chat([{"role": "user", "content": "س"}])
    assert not reply
    assert len(calls) == 1


def test_falls_back_to_the_draft_when_checks_fail(monkeypatch):
    """التحقق تحسين مش شرط — لو وقع في النص، بنرجّع المسودة."""
    _scripted(monkeypatch, ["the draft", ""])
    reply = brain.get_brain().verified_chat([{"role": "user", "content": "س"}])
    assert reply.text == "the draft"


def test_falls_back_to_the_draft_when_the_rewrite_is_empty(monkeypatch):
    _scripted(monkeypatch, ["the draft", "q", "a", ""])
    reply = brain.get_brain().verified_chat([{"role": "user", "content": "س"}])
    assert reply.text == "the draft"


def test_verify_mode_is_off_by_default():
    assert brain._default_config()["verify_mode"] is False
