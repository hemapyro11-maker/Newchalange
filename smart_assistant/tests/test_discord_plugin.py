import datetime
import threading

import discord_plugin as dc
import pytest


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "_config_path", lambda: tmp_path / "discord_config.json")


@pytest.fixture(autouse=True)
def _isolate_keyring(monkeypatch):
    """افتراضيًا نخلي keyring "مش متاح" وقت الاختبار — نفس السبب
    المذكور في test_telegram_plugin.py بالظبط."""
    monkeypatch.setattr(dc, "_HAS_KEYRING", False)


class _FakeKeyring:
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, key):
        return self._store.get((service, key))

    def set_password(self, service, key, value):
        self._store[(service, key)] = value


# ── config load/save ─────────────────────────────────────────────────

def test_load_config_defaults_when_missing():
    data = dc._load_config()
    assert data == {"bot_token": None, "owner_ids": [], "pending_pairs": {}}


def test_save_and_reload_config():
    data = dc._load_config()
    data["bot_token"] = "abc123"
    data["owner_ids"].append(111)
    dc._save_config(data)
    reloaded = dc._load_config()
    assert reloaded["bot_token"] == "abc123"
    assert reloaded["owner_ids"] == [111]


def test_load_config_recovers_from_corrupted_file(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(dc, "_config_path", lambda: path)
    assert dc._load_config() == dc._default_config()


# ── pairing ──────────────────────────────────────────────────────────

def test_request_pairing_generates_code():
    code = dc._request_pairing(12345)
    assert len(code) == 6
    assert code.isdigit()


def test_request_pairing_returns_same_code_for_same_sender():
    code1 = dc._request_pairing(12345)
    code2 = dc._request_pairing(12345)
    assert code1 == code2


def test_request_pairing_stores_in_config():
    code = dc._request_pairing(12345)
    data = dc._load_config()
    assert data["pending_pairs"]["12345"]["code"] == code


def test_request_pairing_caps_pending_and_evicts_oldest():
    for i in range(dc._MAX_PENDING_PAIRS):
        dc._request_pairing(1000 + i)
    data = dc._load_config()
    assert len(data["pending_pairs"]) == dc._MAX_PENDING_PAIRS

    dc._request_pairing(99999)
    data = dc._load_config()
    assert len(data["pending_pairs"]) == dc._MAX_PENDING_PAIRS
    assert "1000" not in data["pending_pairs"]
    assert "99999" in data["pending_pairs"]


def test_generate_pair_code_retries_on_collision(monkeypatch):
    # لو أول كودين اتولدوا مصادفين أكواد موجودة فعلاً، الدالة لازم
    # تعيد المحاولة لغاية ما تلاقي كود فريد — بدل ما ترجّع كود متصادم
    # ممكن يخلي صاحب الجهاز يوافق بالغلط على مرسل تاني.
    calls = iter([111111, 111111, 222222])
    monkeypatch.setattr(dc.secrets, "randbelow", lambda n: next(calls))
    code = dc._generate_pair_code({"111111"})
    assert code == "222222"


def test_concurrent_pairing_requests_do_not_lose_data():
    # راجع: _request_pairing كانت بتعمل load→modify→save من غير قفل —
    # لو طلبين وصلوا في نفس اللحظة (من threads مختلفة، زي ما بيحصل
    # فعليًا بين thread البوت وthread المحرك)، كان ممكن كل واحد يقرا
    # نفس النسخة القديمة من الملف ويكتب فوق تعديل التاني، فيضيع طلب
    # كامل بصمت. بنطلق عدد كبير من الطلبات المتزامنة الحقيقية (threads
    # فعلية، مش موك) ونتأكد إن كل واحد فيهم اتسجل فعلاً.
    sender_ids = list(range(200, 200 + dc._MAX_PENDING_PAIRS))
    threads = [threading.Thread(target=dc._request_pairing, args=(sid,)) for sid in sender_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    data = dc._load_config()
    assert len(data["pending_pairs"]) == len(sender_ids)
    for sid in sender_ids:
        assert str(sid) in data["pending_pairs"]


# ── discord_approve / discord_deauthorize ────────────────────────────

def test_approve_moves_pending_to_owner(make_ctx, bare_engine):
    code = dc._request_pairing(555)
    result = dc._cmd_discord_approve(make_ctx(f"discord_approve {code}", [code], engine=bare_engine))
    assert "✅" in result
    assert "555" in result
    data = dc._load_config()
    assert 555 in data["owner_ids"]
    assert "555" not in data["pending_pairs"]


def test_approve_unknown_code_rejected(make_ctx, bare_engine):
    result = dc._cmd_discord_approve(make_ctx("discord_approve 000000", ["000000"], engine=bare_engine))
    assert result.startswith("❌")


def test_approve_no_args_shows_usage(make_ctx, bare_engine):
    result = dc._cmd_discord_approve(make_ctx("discord_approve", [], engine=bare_engine))
    assert result.startswith("usage")


def test_approve_rejects_expired_code(make_ctx, bare_engine):
    code = dc._request_pairing(777)
    data = dc._load_config()
    old_time = datetime.datetime.now() - dc._PAIR_CODE_TTL - datetime.timedelta(hours=1)
    data["pending_pairs"]["777"]["requested_at"] = old_time.isoformat(timespec="seconds")
    dc._save_config(data)

    result = dc._cmd_discord_approve(make_ctx(f"discord_approve {code}", [code], engine=bare_engine))
    assert result.startswith("❌")
    assert "منتهي" in result
    data = dc._load_config()
    assert 777 not in data["owner_ids"]
    assert "777" not in data["pending_pairs"]  # الكود المنتهي اتشال برضو، مش فاضل معلّق للأبد


def test_approve_accepts_code_within_ttl(make_ctx, bare_engine):
    code = dc._request_pairing(778)
    data = dc._load_config()
    recent_time = datetime.datetime.now() - datetime.timedelta(hours=1)
    data["pending_pairs"]["778"]["requested_at"] = recent_time.isoformat(timespec="seconds")
    dc._save_config(data)

    result = dc._cmd_discord_approve(make_ctx(f"discord_approve {code}", [code], engine=bare_engine))
    assert result.startswith("✅")
    data = dc._load_config()
    assert 778 in data["owner_ids"]


def test_deauthorize_removes_owner(make_ctx, bare_engine):
    code = dc._request_pairing(555)
    dc._cmd_discord_approve(make_ctx(f"discord_approve {code}", [code], engine=bare_engine))
    result = dc._cmd_discord_deauthorize(make_ctx("discord_deauthorize 555", ["555"], engine=bare_engine))
    assert "🚫" in result
    assert 555 not in dc._load_config()["owner_ids"]


def test_deauthorize_unknown_id(make_ctx, bare_engine):
    result = dc._cmd_discord_deauthorize(make_ctx("discord_deauthorize 555", ["555"], engine=bare_engine))
    assert result.startswith("❌")


def test_deauthorize_no_args_shows_usage(make_ctx, bare_engine):
    result = dc._cmd_discord_deauthorize(make_ctx("discord_deauthorize", [], engine=bare_engine))
    assert result.startswith("usage")


# ── discord_set_token / discord_status ───────────────────────────────

def test_set_token_saves_and_reports_without_keyring(make_ctx, bare_engine):
    result = dc._cmd_discord_set_token(make_ctx("discord_set_token mytok123", ["mytok123"], engine=bare_engine))
    assert "⚠️" in result
    assert dc._load_config()["bot_token"] == "mytok123"
    assert dc._get_token() == "mytok123"


def test_set_token_no_args_shows_usage(make_ctx, bare_engine):
    result = dc._cmd_discord_set_token(make_ctx("discord_set_token", [], engine=bare_engine))
    assert result.startswith("usage")


# ── تخزين آمن للتوكن عبر keyring ──────────────────────────────────────

def test_set_token_uses_keyring_when_available(monkeypatch, make_ctx, bare_engine):
    fake = _FakeKeyring()
    monkeypatch.setattr(dc, "_HAS_KEYRING", True)
    monkeypatch.setattr(dc, "keyring", fake)

    result = dc._cmd_discord_set_token(make_ctx("discord_set_token sectok", ["sectok"], engine=bare_engine))
    assert "✅" in result
    assert "keyring" in result
    assert fake.get_password(dc._KEYRING_SERVICE, dc._TOKEN_KEY) == "sectok"
    assert dc._get_token() == "sectok"
    assert not dc._load_config().get("bot_token")


def test_set_token_clears_old_plaintext_after_keyring_success(monkeypatch, make_ctx, bare_engine):
    dc._save_config({**dc._default_config(), "bot_token": "oldplain"})
    fake = _FakeKeyring()
    monkeypatch.setattr(dc, "_HAS_KEYRING", True)
    monkeypatch.setattr(dc, "keyring", fake)

    dc._cmd_discord_set_token(make_ctx("discord_set_token newsecure", ["newsecure"], engine=bare_engine))
    assert not dc._load_config().get("bot_token")
    assert dc._get_token() == "newsecure"


def test_set_token_keyring_error_falls_back_to_plaintext(monkeypatch, make_ctx, bare_engine):
    import keyring.errors as kerrors

    class _BrokenKeyring:
        def get_password(self, *a):
            raise kerrors.NoKeyringError("no backend")

        def set_password(self, *a):
            raise kerrors.NoKeyringError("no backend")

    monkeypatch.setattr(dc, "_HAS_KEYRING", True)
    monkeypatch.setattr(dc, "keyring", _BrokenKeyring())

    result = dc._cmd_discord_set_token(make_ctx("discord_set_token fallbacktok", ["fallbacktok"], engine=bare_engine))
    assert "⚠️" in result
    assert dc._load_config()["bot_token"] == "fallbacktok"
    assert dc._get_token() == "fallbacktok"


def test_get_token_reads_legacy_plaintext_when_keyring_has_nothing(monkeypatch, bare_engine):
    fake = _FakeKeyring()
    monkeypatch.setattr(dc, "_HAS_KEYRING", True)
    monkeypatch.setattr(dc, "keyring", fake)
    dc._save_config({**dc._default_config(), "bot_token": "legacytok"})
    assert dc._get_token() == "legacytok"


def test_status_reports_no_token(make_ctx, bare_engine):
    result = dc._cmd_discord_status(make_ctx("discord_status", [], engine=bare_engine))
    assert "❌ مش متظبط" in result


def test_status_reports_owners_and_pending(make_ctx, bare_engine):
    dc._cmd_discord_set_token(make_ctx("discord_set_token tok", ["tok"], engine=bare_engine))
    code = dc._request_pairing(555)
    dc._cmd_discord_approve(make_ctx(f"discord_approve {code}", [code], engine=bare_engine))
    dc._request_pairing(999)
    result = dc._cmd_discord_status(make_ctx("discord_status", [], engine=bare_engine))
    assert "✅ متظبط" in result
    assert "555" in result
    assert "طلبات موافقة معلّقة: 1" in result


# ── _handle_incoming (المنطق الأمني الأساسي) ─────────────────────────

def test_handle_incoming_unknown_sender_gets_pairing_instructions(monkeypatch, bare_engine):
    called = {"ran": False}
    monkeypatch.setattr(dc, "_run_and_capture", lambda engine, text: called.update(ran=True) or "should not happen")

    result = dc._handle_incoming(bare_engine, 42, "run rm -rf /")
    assert "🔒" in result
    assert "discord_approve" in result
    assert called["ran"] is False


def test_handle_incoming_approved_owner_executes(monkeypatch, bare_engine):
    data = dc._load_config()
    data["owner_ids"].append(42)
    dc._save_config(data)

    captured = {}

    def fake_run_and_capture(engine, text):
        captured["text"] = text
        return "تم التنفيذ"

    monkeypatch.setattr(dc, "_run_and_capture", fake_run_and_capture)
    result = dc._handle_incoming(bare_engine, 42, "echo hi")
    assert result == "تم التنفيذ"
    assert captured["text"] == "echo hi"


def test_handle_incoming_never_executes_for_unapproved_even_with_valid_looking_command(monkeypatch, bare_engine):
    monkeypatch.setattr(dc, "_run_and_capture", lambda engine, text: pytest.fail("must never execute"))
    result = dc._handle_incoming(bare_engine, 1234567, "help")
    assert "🔒" in result


# ── _run_and_capture (تنفيذ حقيقي عبر core_engine) ────────────────────

def test_run_and_capture_real_execution(bare_engine):
    bare_engine.start()
    try:
        result = dc._run_and_capture(bare_engine, "echo hello world")
        assert result == "hello world"
    finally:
        bare_engine.stop()
        bare_engine._worker.join(timeout=2)


def test_run_and_capture_still_logs_to_original_on_log(bare_engine):
    seen = []
    bare_engine.on_log = lambda msg, level="info": seen.append(msg)
    bare_engine.start()
    try:
        dc._run_and_capture(bare_engine, "echo still logged")
        assert any("still logged" in m for m in seen)
    finally:
        bare_engine.stop()
        bare_engine._worker.join(timeout=2)


def test_run_and_capture_times_out_gracefully_when_engine_not_running(monkeypatch, bare_engine):
    monkeypatch.setattr(dc, "_DISPATCH_TIMEOUT", 0.2)
    result = dc._run_and_capture(bare_engine, "echo hi")
    assert "⏱" in result


# ── register ─────────────────────────────────────────────────────────

def test_register_adds_desktop_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    dc.register(FakeEngine)
    for cmd in ("discord_set_token", "discord_approve", "discord_deauthorize", "discord_status"):
        assert cmd in FakeEngine.registry.names


def test_register_does_not_crash_without_discord_py_installed(bare_engine):
    dc.register(bare_engine)
    assert bare_engine.registry.get("discord_status") is not None
