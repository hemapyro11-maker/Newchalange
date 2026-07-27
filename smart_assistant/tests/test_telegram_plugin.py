import datetime
import threading

import pytest
import telegram_plugin as tg


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "_config_path", lambda: tmp_path / "telegram_config.json")


@pytest.fixture(autouse=True)
def _isolate_keyring(monkeypatch):
    """افتراضيًا نخلي keyring "مش متاح" وقت الاختبار — عشان (أ) الاختبارات
    الحالية تتحقق من سلوك fallback النص العادي بشكل ثابت بغض النظر عن
    الجهاز اللي الاختبارات شغالة عليه، و(ب) محدش يلمس مخزن أسرار نظام
    التشغيل الحقيقي بتاع اللي بيشغل الاختبارات. اختبارات "keyring متاح"
    بتعمل override صريح بنفسها (monkeypatch لـ _HAS_KEYRING و keyring)."""
    monkeypatch.setattr(tg, "_HAS_KEYRING", False)


class _FakeKeyring:
    """مخزن أسرار وهمي في الذاكرة — بديل آمن للاختبار بدل ما نلمس
    مخزن أسرار نظام التشغيل الحقيقي."""
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, key):
        return self._store.get((service, key))

    def set_password(self, service, key, value):
        self._store[(service, key)] = value


# ── config load/save ─────────────────────────────────────────────────

def test_load_config_defaults_when_missing():
    data = tg._load_config()
    assert data == {"bot_token": None, "owner_ids": [], "pending_pairs": {}}


def test_save_and_reload_config():
    data = tg._load_config()
    data["bot_token"] = "abc123"
    data["owner_ids"].append(111)
    tg._save_config(data)
    reloaded = tg._load_config()
    assert reloaded["bot_token"] == "abc123"
    assert reloaded["owner_ids"] == [111]


def test_load_config_recovers_from_corrupted_file(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(tg, "_config_path", lambda: path)
    assert tg._load_config() == tg._default_config()


# ── pairing ──────────────────────────────────────────────────────────

def test_request_pairing_generates_code():
    code = tg._request_pairing(12345)
    assert len(code) == 6
    assert code.isdigit()


def test_request_pairing_returns_same_code_for_same_sender():
    code1 = tg._request_pairing(12345)
    code2 = tg._request_pairing(12345)
    assert code1 == code2


def test_request_pairing_stores_in_config():
    code = tg._request_pairing(12345)
    data = tg._load_config()
    assert data["pending_pairs"]["12345"]["code"] == code


def test_request_pairing_caps_pending_and_evicts_oldest():
    for i in range(tg._MAX_PENDING_PAIRS):
        tg._request_pairing(1000 + i)
    data = tg._load_config()
    assert len(data["pending_pairs"]) == tg._MAX_PENDING_PAIRS

    tg._request_pairing(99999)  # طلب زيادة عن الحد
    data = tg._load_config()
    assert len(data["pending_pairs"]) == tg._MAX_PENDING_PAIRS
    assert "1000" not in data["pending_pairs"]  # الأقدم اتشال
    assert "99999" in data["pending_pairs"]


def test_generate_pair_code_retries_on_collision(monkeypatch):
    # لو أول كودين اتولدوا مصادفين أكواد موجودة فعلاً، الدالة لازم
    # تعيد المحاولة لغاية ما تلاقي كود فريد — بدل ما ترجّع كود متصادم
    # ممكن يخلي صاحب الجهاز يوافق بالغلط على مرسل تاني.
    calls = iter([111111, 111111, 222222])
    monkeypatch.setattr(tg.secrets, "randbelow", lambda n: next(calls))
    code = tg._generate_pair_code({"111111"})
    assert code == "222222"


def test_concurrent_pairing_requests_do_not_lose_data():
    # راجع: _request_pairing كانت بتعمل load→modify→save من غير قفل —
    # لو طلبين وصلوا في نفس اللحظة (من threads مختلفة، زي ما بيحصل
    # فعليًا بين thread البوت وthread المحرك)، كان ممكن كل واحد يقرا
    # نفس النسخة القديمة من الملف ويكتب فوق تعديل التاني، فيضيع طلب
    # كامل بصمت. بنطلق عدد كبير من الطلبات المتزامنة الحقيقية (threads
    # فعلية، مش موك) ونتأكد إن كل واحد فيهم اتسجل فعلاً.
    sender_ids = list(range(200, 200 + tg._MAX_PENDING_PAIRS))
    threads = [threading.Thread(target=tg._request_pairing, args=(sid,)) for sid in sender_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    data = tg._load_config()
    assert len(data["pending_pairs"]) == len(sender_ids)
    for sid in sender_ids:
        assert str(sid) in data["pending_pairs"]


# ── telegram_approve / telegram_deauthorize ──────────────────────────

def test_approve_moves_pending_to_owner(make_ctx, bare_engine):
    code = tg._request_pairing(555)
    result = tg._cmd_telegram_approve(make_ctx(f"telegram_approve {code}", [code], engine=bare_engine))
    assert "✅" in result
    assert "555" in result
    data = tg._load_config()
    assert 555 in data["owner_ids"]
    assert "555" not in data["pending_pairs"]


def test_approve_unknown_code_rejected(make_ctx, bare_engine):
    result = tg._cmd_telegram_approve(make_ctx("telegram_approve 000000", ["000000"], engine=bare_engine))
    assert result.startswith("❌")


def test_approve_no_args_shows_usage(make_ctx, bare_engine):
    result = tg._cmd_telegram_approve(make_ctx("telegram_approve", [], engine=bare_engine))
    assert result.startswith("usage")


def test_approve_rejects_expired_code(make_ctx, bare_engine):
    code = tg._request_pairing(777)
    data = tg._load_config()
    old_time = datetime.datetime.now() - tg._PAIR_CODE_TTL - datetime.timedelta(hours=1)
    data["pending_pairs"]["777"]["requested_at"] = old_time.isoformat(timespec="seconds")
    tg._save_config(data)

    result = tg._cmd_telegram_approve(make_ctx(f"telegram_approve {code}", [code], engine=bare_engine))
    assert result.startswith("❌")
    assert "expired" in result
    data = tg._load_config()
    assert 777 not in data["owner_ids"]
    assert "777" not in data["pending_pairs"]  # الكود المنتهي اتشال برضو، مش فاضل معلّق للأبد


def test_approve_accepts_code_within_ttl(make_ctx, bare_engine):
    code = tg._request_pairing(778)
    data = tg._load_config()
    recent_time = datetime.datetime.now() - datetime.timedelta(hours=1)
    data["pending_pairs"]["778"]["requested_at"] = recent_time.isoformat(timespec="seconds")
    tg._save_config(data)

    result = tg._cmd_telegram_approve(make_ctx(f"telegram_approve {code}", [code], engine=bare_engine))
    assert result.startswith("✅")
    data = tg._load_config()
    assert 778 in data["owner_ids"]


def test_deauthorize_removes_owner(make_ctx, bare_engine):
    code = tg._request_pairing(555)
    tg._cmd_telegram_approve(make_ctx(f"telegram_approve {code}", [code], engine=bare_engine))
    result = tg._cmd_telegram_deauthorize(make_ctx("telegram_deauthorize 555", ["555"], engine=bare_engine))
    assert "🚫" in result
    assert 555 not in tg._load_config()["owner_ids"]


def test_deauthorize_unknown_id(make_ctx, bare_engine):
    result = tg._cmd_telegram_deauthorize(make_ctx("telegram_deauthorize 555", ["555"], engine=bare_engine))
    assert result.startswith("❌")


def test_deauthorize_no_args_shows_usage(make_ctx, bare_engine):
    result = tg._cmd_telegram_deauthorize(make_ctx("telegram_deauthorize", [], engine=bare_engine))
    assert result.startswith("usage")


# ── telegram_set_token / telegram_status ─────────────────────────────

def test_set_token_saves_and_reports_without_keyring(make_ctx, bare_engine):
    # _isolate_keyring بيوقف keyring افتراضيًا في كل الاختبارات دي، فده
    # بيتحقق من مسار fallback النص العادي تحديدًا.
    result = tg._cmd_telegram_set_token(make_ctx("telegram_set_token mytok123", ["mytok123"], engine=bare_engine))
    assert "⚠️" in result
    assert tg._load_config()["bot_token"] == "mytok123"
    assert tg._get_token() == "mytok123"


def test_set_token_no_args_shows_usage(make_ctx, bare_engine):
    result = tg._cmd_telegram_set_token(make_ctx("telegram_set_token", [], engine=bare_engine))
    assert result.startswith("usage")


# ── تخزين آمن للتوكن عبر keyring ──────────────────────────────────────

def test_set_token_uses_keyring_when_available(monkeypatch, make_ctx, bare_engine):
    fake = _FakeKeyring()
    monkeypatch.setattr(tg, "_HAS_KEYRING", True)
    monkeypatch.setattr(tg, "keyring", fake)

    result = tg._cmd_telegram_set_token(make_ctx("telegram_set_token sectok", ["sectok"], engine=bare_engine))
    assert "✅" in result
    assert "keyring" in result
    assert fake.get_password(tg._KEYRING_SERVICE, tg._TOKEN_KEY) == "sectok"
    assert tg._get_token() == "sectok"
    # ما بيتحفظش نص عادي في الملف لما keyring ينجح
    assert not tg._load_config().get("bot_token")


def test_set_token_clears_old_plaintext_after_keyring_success(monkeypatch, make_ctx, bare_engine):
    tg._save_config({**tg._default_config(), "bot_token": "oldplain"})
    fake = _FakeKeyring()
    monkeypatch.setattr(tg, "_HAS_KEYRING", True)
    monkeypatch.setattr(tg, "keyring", fake)

    tg._cmd_telegram_set_token(make_ctx("telegram_set_token newsecure", ["newsecure"], engine=bare_engine))
    assert not tg._load_config().get("bot_token")
    assert tg._get_token() == "newsecure"


def test_set_token_keyring_error_falls_back_to_plaintext(monkeypatch, make_ctx, bare_engine):
    import keyring.errors as kerrors

    class _BrokenKeyring:
        def get_password(self, *a):
            raise kerrors.NoKeyringError("no backend")

        def set_password(self, *a):
            raise kerrors.NoKeyringError("no backend")

    monkeypatch.setattr(tg, "_HAS_KEYRING", True)
    monkeypatch.setattr(tg, "keyring", _BrokenKeyring())

    result = tg._cmd_telegram_set_token(make_ctx("telegram_set_token fallbacktok", ["fallbacktok"], engine=bare_engine))
    assert "⚠️" in result
    assert tg._load_config()["bot_token"] == "fallbacktok"
    assert tg._get_token() == "fallbacktok"


def test_get_token_reads_legacy_plaintext_when_keyring_has_nothing(monkeypatch, bare_engine):
    fake = _FakeKeyring()
    monkeypatch.setattr(tg, "_HAS_KEYRING", True)
    monkeypatch.setattr(tg, "keyring", fake)
    tg._save_config({**tg._default_config(), "bot_token": "legacytok"})
    assert tg._get_token() == "legacytok"


def test_status_reports_no_token(make_ctx, bare_engine):
    result = tg._cmd_telegram_status(make_ctx("telegram_status", [], engine=bare_engine))
    assert "❌ not configured" in result


def test_status_reports_owners_and_pending(make_ctx, bare_engine):
    tg._cmd_telegram_set_token(make_ctx("telegram_set_token tok", ["tok"], engine=bare_engine))
    code = tg._request_pairing(555)
    tg._cmd_telegram_approve(make_ctx(f"telegram_approve {code}", [code], engine=bare_engine))
    tg._request_pairing(999)  # طلب تاني معلّق
    result = tg._cmd_telegram_status(make_ctx("telegram_status", [], engine=bare_engine))
    assert "✅ configured" in result
    assert "555" in result
    assert "Pending approval requests: 1" in result


# ── _handle_incoming (المنطق الأمني الأساسي) ─────────────────────────

def test_handle_incoming_unknown_sender_gets_pairing_instructions(monkeypatch, bare_engine):
    called = {"ran": False}
    monkeypatch.setattr(tg, "_run_and_capture", lambda engine, text: called.update(ran=True) or "should not happen")

    result = tg._handle_incoming(bare_engine, 42, "run rm -rf /")
    assert "🔒" in result
    assert "telegram_approve" in result
    assert called["ran"] is False  # الأهم: الأمر ما اتنفذش خالص


def test_handle_incoming_approved_owner_executes(monkeypatch, bare_engine):
    data = tg._load_config()
    data["owner_ids"].append(42)
    tg._save_config(data)

    captured = {}

    def fake_run_and_capture(engine, text):
        captured["text"] = text
        return "تم التنفيذ"

    monkeypatch.setattr(tg, "_run_and_capture", fake_run_and_capture)
    result = tg._handle_incoming(bare_engine, 42, "echo hi")
    assert result == "تم التنفيذ"
    assert captured["text"] == "echo hi"


def test_handle_incoming_never_executes_for_unapproved_even_with_valid_looking_command(monkeypatch, bare_engine):
    """أهم اختبار أمني هنا: حتى لو النص أمر حقيقي مضبوط، مفيش تنفيذ
    خالص لغير المعتمدين — الرد الوحيد المسموح هو تعليمات pairing."""
    monkeypatch.setattr(tg, "_run_and_capture", lambda engine, text: pytest.fail("must never execute"))
    result = tg._handle_incoming(bare_engine, 1234567, "help")
    assert "🔒" in result


# ── _run_and_capture (تنفيذ حقيقي عبر core_engine) ────────────────────

def test_run_and_capture_real_execution(bare_engine):
    bare_engine.start()
    try:
        result = tg._run_and_capture(bare_engine, "echo hello world")
        assert result == "hello world"
    finally:
        bare_engine.stop()
        bare_engine._worker.join(timeout=2)


def test_run_and_capture_still_logs_to_original_on_log(bare_engine):
    seen = []
    bare_engine.on_log = lambda msg, level="info": seen.append(msg)
    bare_engine.start()
    try:
        tg._run_and_capture(bare_engine, "echo still logged")
        assert any("still logged" in m for m in seen)
    finally:
        bare_engine.stop()
        bare_engine._worker.join(timeout=2)


def test_run_and_capture_times_out_gracefully_when_engine_not_running(monkeypatch, bare_engine):
    monkeypatch.setattr(tg, "_DISPATCH_TIMEOUT", 0.2)  # مش 30 ثانية حقيقية وقت الاختبار
    # engine.start() ماتنداهاش عمدًا — مفيش حد بيستهلك الطابور
    result = tg._run_and_capture(bare_engine, "echo hi")
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

    tg.register(FakeEngine)
    for cmd in ("telegram_set_token", "telegram_approve", "telegram_deauthorize", "telegram_status"):
        assert cmd in FakeEngine.registry.names


def test_register_does_not_crash_without_ptb_installed(bare_engine):
    # لو python-telegram-bot مش متثبت (زي بيئة الاختبار دي غالبًا)،
    # register() لازم يسجل الأوامر عادي من غير أي محاولة تشغيل بوت حقيقي.
    tg.register(bare_engine)
    assert bare_engine.registry.get("telegram_status") is not None
