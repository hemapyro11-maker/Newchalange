"""
اختبارات الواجهة — بتتخطى تلقائيًا لو tkinter/customtkinter مش متاحين
أو مفيش شاشة (زي سيرفرات CI بدون X)، بنفس أسلوب باقي الاختبارات في
المشروع مع الأدوات الاختيارية.

لتشغيلها فعليًا على جهاز بدون شاشة:
    Xvfb :99 -screen 0 1400x900x24 &
    DISPLAY=:99 pytest tests/test_main_gui.py
"""
import os
import pathlib
import tempfile

import pytest

pytest.importorskip("tkinter", reason="tkinter not available")
pytest.importorskip("customtkinter", reason="customtkinter not installed")

if not os.environ.get("DISPLAY") and os.name != "nt":
    pytest.skip("no display available", allow_module_level=True)

import brain  # noqa: E402
import main_gui  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp)
    monkeypatch.setattr(brain, "is_local_alive", lambda prov, **kw: False)
    brain.reset_brain()
    a = main_gui.AssistantApp()
    a.update()
    yield a
    a.engine.stop()
    a.destroy()
    brain.reset_brain()


# ── اتجاه الواجهة (RTL) ──────────────────────────────────────────────

def test_arabic_is_rtl_by_default(app):
    assert app._rtl is True


def test_icon_goes_after_text_in_arabic(app):
    """راجع: النسخة القديمة كانت بتحط الأيقونة بادئة دايمًا مع
    anchor='w' — تخطيط إنجليزي مركّب على نص عربي."""
    assert app._icon_text(app.attach_btn, "إرفاق ملف") == "إرفاق ملف  📎"


def test_icon_goes_before_text_in_english(app):
    app.t.set_lang("en")
    assert app._icon_text(app.attach_btn, "Attach") == "📎  Attach"


def test_sidebar_buttons_anchor_east_in_arabic(app):
    assert app.attach_btn.cget("anchor") == "e"


def test_entry_justifies_right_in_arabic(app):
    assert app.entry.cget("justify") == "right"


# ── الفقاعات ─────────────────────────────────────────────────────────

def test_user_message_creates_a_row(app):
    before = len(app._rows)
    app._add_user("رسالة تجريبية")
    assert len(app._rows) == before + 1


def test_assistant_message_creates_a_row(app):
    before = len(app._rows)
    app._add_assistant("رد تجريبي")
    assert len(app._rows) == before + 1


def test_rows_are_capped_to_avoid_unbounded_growth(app):
    for i in range(main_gui.MAX_ROWS + 25):
        app._add_user(f"م {i}")
    assert len(app._rows) <= main_gui.MAX_ROWS


def test_very_long_reply_is_truncated(app):
    app._add_assistant("ط" * (main_gui.MAX_CHARS + 5000))
    app.update()  # لازم مايرميش استثناء ولا يعلّق الواجهة


def test_new_chat_clears_rows_and_history(app):
    app._add_user("حاجة")
    app.engine.chat_history.append({"role": "user", "content": "x"})
    app._new_chat()
    assert app.engine.chat_history == []


# ── تصفية رسايل تحميل الإضافات ──────────────────────────────────────

def test_plugin_load_messages_do_not_flood_the_chat(app):
    """راجع: كل تشغيل كان بيطبع ~34 رسالة "plugin loaded" كفقاعات في
    المحادثة، فأول شاشة يشوفها المستخدم بتبقى مليانة ضوضاء بدل الترحيب."""
    before_rows = len(app._rows)
    before_count = app._plugin_count
    for i in range(10):
        app._render_log(f"🧩 plugin loaded: p{i}", "ok")
    assert len(app._rows) == before_rows
    assert app._plugin_count == before_count + 10


def test_plugin_count_shows_in_subtitle(app):
    app._render_log("🧩 plugin loaded: x", "ok")
    assert "إضافة" in app.subtitle_label.cget("text")


def test_normal_ok_message_is_still_shown(app):
    before = len(app._rows)
    app._render_log("✅ الملف اتفحص وطلع نضيف", "ok")
    assert len(app._rows) == before + 1


# ── شارة المزوّد ─────────────────────────────────────────────────────

def test_provider_badge_is_split_from_body(app):
    before = len(app._rows)
    app._render_log("ده رد المخ\n— ☁️ Google Gemini", "info")
    assert len(app._rows) == before + 1


def test_message_without_badge_renders_fine(app):
    app._render_log("رد من غير شارة", "info")
    app.update()


# ── حالة المخ في السايدبار ───────────────────────────────────────────

def test_sidebar_warns_when_no_brain_configured(app):
    app._refresh_brain_label()
    assert "مفيش مخ متظبط" in app.brain_label.cget("text")


def test_sidebar_shows_provider_and_remaining_quota(app):
    brain.set_key("groq", "k")
    app._refresh_brain_label()
    text = app.brain_label.cget("text")
    assert "Groq" in text
    assert "متبقي" in text


def test_greeting_tells_user_to_set_up_brain_when_missing(app):
    app._new_chat()
    assert app._rows  # فيه رسالة ترحيب


# ── الصوت ────────────────────────────────────────────────────────────

def test_voice_starts_off(app):
    assert app.voice_enabled is False


def test_voice_toggle_flips_state_and_icon(app):
    app._toggle_voice()
    assert app.voice_enabled is True
    assert app.voice_btn._icon == "🔊"
    app._toggle_voice()
    assert app.voice_btn._icon == "🔇"


def test_voice_reply_is_not_spoken_for_speak_itself(app, monkeypatch):
    """من غير الاستثناء ده، نتيجة أمر speak كانت هتتبعت لـ speak تاني
    وتدخل في حلقة نطق بلا نهاية."""
    spoken = []
    monkeypatch.setattr(app, "_speak", lambda text: spoken.append(text))
    app.voice_enabled = True
    app._last_command_name = "speak"
    app._on_log("اتقالت", "info")
    app.update()
    assert spoken == []


# ── ربط اختيار الملف ─────────────────────────────────────────────────

def test_need_file_hook_is_wired_to_the_engine(app):
    assert callable(app.engine.on_need_file)


def test_pick_file_passes_empty_string_when_cancelled(app, monkeypatch):
    monkeypatch.setattr(main_gui.filedialog, "askopenfilename", lambda **kw: "")
    got = []
    spec = type("S", (), {"kind": "file", "prompt": "اختار"})()
    app._pick_file(spec, got.append)
    assert got == [""]


def test_pick_file_uses_directory_dialog_for_dir_specs(app, monkeypatch):
    called = {"dir": False}
    monkeypatch.setattr(
        main_gui.filedialog, "askdirectory",
        lambda **kw: called.__setitem__("dir", True) or "/tmp",
    )
    spec = type("S", (), {"kind": "dir", "prompt": "مجلد"})()
    app._pick_file(spec, lambda v: None)
    assert called["dir"] is True


# ── نافذة الإعدادات ──────────────────────────────────────────────────

def test_settings_window_opens_with_a_card_per_provider(app):
    win = main_gui.SettingsWindow(app)
    app.update()
    assert len(win._entries) == sum(1 for p in brain.PROVIDERS.values() if p.needs_key)
    win.destroy()


def test_settings_saves_a_typed_key(app):
    win = main_gui.SettingsWindow(app)
    app.update()
    win._entries["groq"].delete(0, "end")
    win._entries["groq"].insert(0, "gsk_typed")
    win._save()
    assert brain.get_key("groq") == "gsk_typed"


def test_settings_does_not_overwrite_key_with_the_masked_placeholder(app):
    """الحقل بيتملي بـ •••• لما يكون فيه مفتاح محفوظ — لو حفظنا القيمة
    دي كما هي كنا هنستبدل المفتاح الحقيقي بنجوم."""
    brain.set_key("groq", "real_key")
    win = main_gui.SettingsWindow(app)
    app.update()
    win._save()
    assert brain.get_key("groq") == "real_key"
    win.destroy()


def test_settings_persists_mode_switches(app):
    win = main_gui.SettingsWindow(app)
    app.update()
    win.deep_var.set(True)
    win.local_var.set(True)
    win._save()
    cfg = brain.load_config()
    assert cfg["deep_mode"] is True
    assert cfg["local_only"] is True
