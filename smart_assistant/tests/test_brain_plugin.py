import brain
import brain_plugin as bp
import intents
import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    # Ollama مش شغال افتراضيًا في الاختبارات — مفيش فحص شبكة حقيقي
    monkeypatch.setattr(brain, "is_local_alive", lambda prov, **kw: False)
    monkeypatch.setattr(brain, "_HAS_KEYRING", False)
    monkeypatch.setattr(intents, "_cache_path", lambda: tmp_path / "intent_cache.json")
    brain.reset_brain()
    yield
    brain.reset_brain()


# ── brain_setup ──────────────────────────────────────────────────────

def test_setup_lists_free_providers_with_signup_links(make_ctx):
    out = bp._cmd_brain_setup(make_ctx("brain_setup", []))
    assert "aistudio.google.com" in out
    assert "console.groq.com" in out
    assert "ollama.com" in out


def test_setup_warns_when_nothing_configured(make_ctx):
    assert "مفيش أي مخ متظبط" in bp._cmd_brain_setup(make_ctx("brain_setup", []))


def test_setup_reports_ready_count_once_a_key_exists(make_ctx):
    brain.set_key("gemini", "k")
    assert "1 مخ جاهز" in bp._cmd_brain_setup(make_ctx("brain_setup", []))


# ── brain_key ────────────────────────────────────────────────────────

def test_key_stores_and_reports_plaintext_fallback(make_ctx):
    out = bp._cmd_brain_key(make_ctx("brain_key groq k", ["groq", "k"]))
    assert "⚠️" in out
    assert brain.get_key("groq") == "k"


def test_key_uses_keyring_when_available(make_ctx, monkeypatch):
    store = {}

    class FakeKeyring:
        def set_password(self, s, k, v):
            store[(s, k)] = v

        def get_password(self, s, k):
            return store.get((s, k))

    monkeypatch.setattr(brain, "_HAS_KEYRING", True)
    monkeypatch.setattr(brain, "keyring", FakeKeyring())
    out = bp._cmd_brain_key(make_ctx("brain_key groq sec", ["groq", "sec"]))
    assert "✅" in out and "مخزن أسرار" in out


def test_key_rejects_unknown_provider(make_ctx):
    out = bp._cmd_brain_key(make_ctx("brain_key nope k", ["nope", "k"]))
    assert out.startswith("❌")


def test_key_without_args_shows_usage(make_ctx):
    assert bp._cmd_brain_key(make_ctx("brain_key", [])).startswith("usage")


def test_forget_key_removes_it(make_ctx):
    brain.set_key("groq", "k")
    bp._cmd_brain_forget_key(make_ctx("brain_forget_key groq", ["groq"]))
    assert brain.get_key("groq") is None


# ── brain_status ─────────────────────────────────────────────────────

def test_status_shows_missing_key_marker(make_ctx):
    out = bp._cmd_brain_status(make_ctx("brain_status", []))
    assert "مفيش مفتاح" in out


def test_status_shows_ready_and_remaining_quota(make_ctx):
    brain.set_key("groq", "k")
    out = bp._cmd_brain_status(make_ctx("brain_status", []))
    assert "جاهز" in out
    assert "متبقي النهارده" in out


def test_status_flags_providers_that_train_on_input(make_ctx):
    brain.set_key("gemini", "k")
    out = bp._cmd_brain_status(make_ctx("brain_status", []))
    assert "🔓" in out
    assert "brain_local on" in out


def test_status_counts_usage_against_daily_limit(make_ctx):
    brain.set_key("groq", "k")
    b = brain.get_brain()
    b._note_success("groq", 1.0)
    assert "1/" in bp._cmd_brain_status(make_ctx("brain_status", []))


def test_status_shows_cold_provider(make_ctx):
    brain.set_key("groq", "k")
    b = brain.get_brain()
    import time
    b._states["groq"].cold_until = time.time() + 120
    assert "❄️" in bp._cmd_brain_status(make_ctx("brain_status", []))


# ── brain_mode / brain_local ─────────────────────────────────────────

def test_mode_switches_to_deep_and_warns_about_cost(make_ctx):
    out = bp._cmd_brain_mode(make_ctx("brain_mode deep", ["deep"]))
    assert "4 أضعاف" in out
    assert brain.load_config()["deep_mode"] is True


def test_mode_switches_back_to_normal(make_ctx):
    bp._cmd_brain_mode(make_ctx("brain_mode deep", ["deep"]))
    bp._cmd_brain_mode(make_ctx("brain_mode normal", ["normal"]))
    assert brain.load_config()["deep_mode"] is False


def test_mode_without_args_reports_current(make_ctx):
    assert "الوضع الحالي" in bp._cmd_brain_mode(make_ctx("brain_mode", []))


def test_local_on_blocks_cloud_and_says_so(make_ctx):
    out = bp._cmd_brain_local(make_ctx("brain_local on", ["on"]))
    assert "هيخرج من جهازك" in out
    assert brain.load_config()["local_only"] is True


def test_local_off_reenables_cloud(make_ctx):
    bp._cmd_brain_local(make_ctx("brain_local on", ["on"]))
    bp._cmd_brain_local(make_ctx("brain_local off", ["off"]))
    assert brain.load_config()["local_only"] is False


# ── brain_model ──────────────────────────────────────────────────────

def test_model_override_is_saved(make_ctx):
    bp._cmd_brain_model(make_ctx("brain_model groq x", ["groq", "x"]))
    assert brain.load_config()["models"]["groq"] == "x"


def test_model_without_args_lists_current_models(make_ctx):
    out = bp._cmd_brain_model(make_ctx("brain_model", []))
    assert "gemini" in out and "ollama" in out


def test_model_rejects_unknown_provider(make_ctx):
    assert bp._cmd_brain_model(make_ctx("brain_model x y", ["x", "y"])).startswith("❌")


# ── brain_dict ───────────────────────────────────────────────────────

def test_dict_reports_coverage_numbers(make_ctx, bare_engine):
    out = bp._cmd_brain_dict(make_ctx("brain_dict", [], engine=bare_engine))
    assert "إجمالي الأوامر المسجّلة" in out
    assert "متغطّية بالقاموس" in out


def test_dict_lists_learned_phrases(make_ctx, bare_engine):
    intents.remember("جملة اتعلمتها", "echo")
    out = bp._cmd_brain_dict(make_ctx("brain_dict", [], engine=bare_engine))
    assert "جمله اتعلمتها" in out or "جملة اتعلمتها" in out


def test_forget_dict_clears_learned_phrases(make_ctx):
    intents.remember("x y", "echo")
    out = bp._cmd_brain_forget_dict(make_ctx("brain_forget_dict", []))
    assert "1" in out
    assert intents.load_cache() == {}


# ── register ─────────────────────────────────────────────────────────

def test_register_adds_all_brain_commands(bare_engine):
    bp.register(bare_engine)
    for cmd in ("brain_setup", "brain_status", "brain_key", "brain_mode",
                "brain_local", "brain_dict", "brain_model", "brain_forget_key",
                "brain_forget_dict"):
        assert bare_engine.registry.get(cmd) is not None
