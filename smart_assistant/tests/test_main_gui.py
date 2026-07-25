"""
اختبارات الواجهة (طراز الطرفية) — بتتخطى تلقائيًا لو tkinter/customtkinter
مش متاحين أو مفيش شاشة، بنفس أسلوب باقي الاختبارات مع الأدوات الاختيارية.

لتشغيلها على جهاز بدون شاشة:
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
import hooks  # noqa: E402
import main_gui  # noqa: E402
import permissions  # noqa: E402
import sessions  # noqa: E402
import theme  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp)
    monkeypatch.setattr(brain, "is_local_alive", lambda prov, **kw: False)
    monkeypatch.setattr(sessions, "_base_dir", lambda: tmp)
    monkeypatch.setattr(hooks, "_base_dir", lambda: tmp)
    brain.reset_brain()
    a = main_gui.AssistantApp()
    a.update()
    yield a
    a.engine.stop()
    a.destroy()
    brain.reset_brain()


# ── الثيم والخط ──────────────────────────────────────────────────────

def test_dark_is_the_default_mode(app):
    assert app.mode == "dark"
    assert app.c is theme.DARK


def test_theme_toggle_switches_palette_and_persists(app):
    app._toggle_theme()
    assert app.mode == "light"
    assert app.c is theme.LIGHT
    assert brain.load_config()["ui_theme"] == "light"


def test_theme_choice_survives_restart(app, monkeypatch):
    app._toggle_theme()
    tmp = brain._base_dir()
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp)
    fresh = main_gui.AssistantApp()
    try:
        assert fresh.mode == "light"
    finally:
        fresh.engine.stop()
        fresh.destroy()


def test_a_real_monospace_font_is_picked(app):
    """راجع: تحديد خط مش موجود بيخلي Tk يرجع للخط الافتراضي بصمت،
    فالشكل بيتكسر من غير أي رسالة خطأ."""
    from tkinter import font as tkfont
    assert app.mono.lower() in {f.lower() for f in tkfont.families(app)}


def test_palette_has_every_colour_key_in_both_modes():
    assert set(theme.DARK) == set(theme.LIGHT)


# ── الاتجاه ──────────────────────────────────────────────────────────

def test_arabic_flows_right_to_left(app):
    assert app._rtl is True
    assert app._side == "right"
    assert app._anchor == "e"
    assert app._justify == "right"


def test_english_flows_left_to_right(app):
    app.t.set_lang("en")
    assert app._side == "left"
    assert app._anchor == "w"


def test_entry_justifies_with_the_language(app):
    assert app.entry.cget("justify") == "right"


# ── أسطر المحادثة ────────────────────────────────────────────────────

def test_user_line_is_added(app):
    before = len(app._rows)
    app._add_user("سطر تجريبي")
    assert len(app._rows) > before


def test_assistant_line_is_added(app):
    before = len(app._rows)
    app._add_assistant("رد")
    assert len(app._rows) > before


def test_tool_result_line_is_added(app):
    before = len(app._rows)
    app._add_result("0 تهديد", "ok")
    assert len(app._rows) == before + 1


def test_rows_are_capped(app):
    for i in range(main_gui.MAX_ROWS + 40):
        app._add_result(f"سطر {i}")
    assert len(app._rows) <= main_gui.MAX_ROWS


def test_very_long_text_is_truncated_without_crashing(app):
    app._add_assistant("ط" * (main_gui.MAX_CHARS + 5000))
    app.update()


def test_clear_resets_stream_and_history(app):
    app._add_user("حاجة")
    app.engine.chat_history.append({"role": "user", "content": "x"})
    app._new_chat()
    assert app.engine.chat_history == []


# ── تصفية رسايل تحميل الإضافات ──────────────────────────────────────

def test_plugin_load_lines_go_to_the_status_line_not_the_stream(app):
    before_rows = len(app._rows)
    before_count = app._plugin_count
    for i in range(8):
        app._render_log(f"🧩 plugin loaded: p{i}", "ok")
    assert len(app._rows) == before_rows
    assert app._plugin_count == before_count + 8


def test_plugin_count_appears_in_status_line(app):
    app._render_log("🧩 plugin loaded: x", "ok")
    assert "إضافة" in app.status_label.cget("text")


def test_a_normal_ok_message_is_still_shown(app):
    before = len(app._rows)
    app._render_log("✅ خلص وطلع نضيف", "ok")
    assert len(app._rows) > before


def test_executed_command_renders_as_a_tool_line(app):
    """السطر اللي بيبدأ بـ ↪ معناه أمر اتنفذ فعلاً — بيتعرض بلون
    مختلف عن كلام المخ عشان تفرق بينهم بالبصر."""
    before = len(app._rows)
    app._render_log("↪ security_report C:/x.exe", "info")
    assert len(app._rows) > before


# ── سطر الحالة ───────────────────────────────────────────────────────

def test_status_line_warns_when_no_brain(app):
    app._refresh_status()
    assert "مفيش مخ" in app.status_label.cget("text")


def test_status_line_shows_provider_and_quota(app):
    brain.set_key("groq", "k")
    app._refresh_status()
    text = app.status_label.cget("text")
    assert "groq" in text.lower()
    assert "متبقي" in text


def test_status_line_shows_active_modes(app):
    cfg = brain.load_config()
    cfg["deep_mode"] = True
    cfg["local_only"] = True
    brain.save_config(cfg)
    app._refresh_status()
    text = app.status_label.cget("text")
    assert "عميق" in text and "محلي" in text


# ── أوامر الشرطة المائلة ─────────────────────────────────────────────

def test_slash_clear_empties_the_stream(app):
    app._add_user("حاجة")
    app.entry.insert(0, "/clear")
    app._send()
    assert app.engine.chat_history == []


def test_slash_theme_toggles_mode(app):
    app.entry.insert(0, "/theme")
    app._send()
    assert app.mode == "light"


def test_slash_voice_toggles_voice(app):
    app.entry.insert(0, "/voice")
    app._send()
    assert app.voice_enabled is True


def test_unknown_slash_lists_available_ones(app):
    before = len(app._rows)
    app.entry.insert(0, "/nonsense")
    app._send()
    assert len(app._rows) > before


def test_slash_command_is_not_sent_to_the_engine(app, monkeypatch):
    sent = []
    monkeypatch.setattr(app.engine, "submit", sent.append)
    app.entry.insert(0, "/theme")
    app._send()
    assert sent == []


def test_plain_text_is_sent_to_the_engine(app, monkeypatch):
    sent = []
    monkeypatch.setattr(app.engine, "submit", sent.append)
    app.entry.insert(0, "إزيك")
    app._send()
    assert sent == ["إزيك"]


# ── الصوت ────────────────────────────────────────────────────────────

def test_voice_starts_off(app):
    assert app.voice_enabled is False


def test_speak_is_skipped_for_speak_itself(app, monkeypatch):
    """من غير الاستثناء ده، نتيجة speak كانت هتترجع لـ speak تاني
    وتدخل في حلقة نطق بلا نهاية."""
    spoken = []
    monkeypatch.setattr(app, "_speak", spoken.append)
    app.voice_enabled = True
    app._last_command_name = "speak"
    app._on_log("اتقالت", "info")
    app.update()
    assert spoken == []


# ── اختيار الملف ─────────────────────────────────────────────────────

def test_need_file_hook_is_wired(app):
    assert callable(app.engine.on_need_file)


def test_cancelled_file_dialog_passes_empty_string(app, monkeypatch):
    monkeypatch.setattr(main_gui.filedialog, "askopenfilename", lambda **kw: "")
    got = []
    spec = type("S", (), {"kind": "file", "prompt": "اختار"})()
    app._pick_file(spec, got.append)
    assert got == [""]


def test_directory_spec_uses_the_directory_dialog(app, monkeypatch):
    called = {}
    monkeypatch.setattr(
        main_gui.filedialog, "askdirectory",
        lambda **kw: called.setdefault("dir", True) or "/tmp",
    )
    spec = type("S", (), {"kind": "dir", "prompt": "مجلد"})()
    app._pick_file(spec, lambda v: None)
    assert called.get("dir") is True


# ── قايمة الإعدادات: التنقل بين الصفحات ─────────────────────────────

def test_settings_opens_on_the_home_page(app):
    app._open_settings()
    app.update()
    assert app._settings.page == "home"
    app._settings.close()


def test_home_lists_every_section(app):
    app._open_settings()
    app.update()
    panel = app._settings
    pages = {i["page"] for i in panel.data if i["kind"] == "goto"}
    for key, _label in main_gui.SettingsPanel.PAGES:
        if key != "home":
            assert key in pages
    panel.close()


def test_enter_on_a_section_navigates_into_it(app):
    app._open_settings()
    app.update()
    panel = app._settings
    target = next(i for i, idx in enumerate(panel._selectable())
                  if panel.data[idx].get("page") == "brain")
    panel.cursor = target
    panel._activate()
    assert panel.page == "brain"
    panel.close()


def test_back_returns_to_home(app):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "sessions"
    panel._build()
    panel._back()
    assert panel.page == "home"
    panel.close()


@pytest.mark.parametrize("page", [k for k, _ in main_gui.SettingsPanel.PAGES])
def test_every_page_renders_without_error(app, page):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = page
    panel.cursor = 0
    panel._build()
    app.update()
    panel.close()


def test_info_rows_are_not_selectable(app):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "permissions"
    panel._build()
    for idx in panel._selectable():
        assert panel.data[idx]["kind"] not in ("head", "info")
    panel.close()


def test_cursor_wraps_around(app):
    app._open_settings()
    app.update()
    panel = app._settings
    total = len(panel._selectable())
    panel.cursor = total - 1
    panel._move(1)
    assert panel.cursor == 0
    panel.close()


# ── صفحة المخ ───────────────────────────────────────────────────────

def test_brain_page_lists_every_provider(app):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "brain"
    panel._build()
    labels = [i["label"] for i in panel.data if i["kind"] != "head"]
    for prov in brain.PROVIDERS.values():
        assert prov.label in labels
    panel.close()


def test_key_editor_saves_a_typed_key(app):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "brain"
    panel.cursor = next(i for i, idx in enumerate(
        [j for j, it in enumerate(panel._items()) if it["kind"] not in ("head", "info")]
    ) if True)
    panel._build()
    app.update()
    # اظبط المؤشر على groq تحديدًا
    for i in range(len(panel._selectable())):
        panel.cursor = i
        panel._build()
        cur = panel._current()
        if cur and cur.get("prov") and cur["prov"].name == "groq":
            break
    app.update()
    panel.editing.insert(0, "gsk_typed")
    panel._save_key()
    assert brain.get_key("groq") == "gsk_typed"
    panel.close()


def test_masked_placeholder_does_not_wipe_an_existing_key(app):
    brain.set_key("groq", "real")
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "brain"
    for i in range(len(panel._selectable())):
        panel.cursor = i
        panel._build()
        cur = panel._current()
        if cur and cur.get("prov") and cur["prov"].name == "groq":
            break
    app.update()
    panel._save_key()          # من غير ما نكتب حاجة
    assert brain.get_key("groq") == "real"
    panel.close()


# ── الأوضاع ─────────────────────────────────────────────────────────

def test_enter_toggles_deep_mode(app):
    app._open_settings()
    app.update()
    panel = app._settings
    target = next(i for i, idx in enumerate(panel._selectable())
                  if panel.data[idx].get("cfg") == "deep_mode")
    panel.cursor = target
    panel._activate()
    assert brain.load_config()["deep_mode"] is True
    panel.close()


def test_enter_toggles_local_only(app):
    app._open_settings()
    app.update()
    panel = app._settings
    target = next(i for i, idx in enumerate(panel._selectable())
                  if panel.data[idx].get("cfg") == "local_only")
    panel.cursor = target
    panel._activate()
    assert brain.load_config()["local_only"] is True
    panel.close()


# ── صفحة الجلسات ────────────────────────────────────────────────────

def test_sessions_page_lists_saved_conversations(app):
    sessions.save("s1", [{"role": "user", "content": "افحص الملف"}])
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "sessions"
    panel._build()
    assert any(i.get("session") == "s1" for i in panel.data)
    panel.close()


def test_opening_a_session_loads_it_into_the_stream(app):
    msgs = [{"role": "user", "content": "سؤال قديم"},
            {"role": "assistant", "content": "رد قديم"}]
    sessions.save("s1", msgs)
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "sessions"
    panel._build()
    target = next(i for i, idx in enumerate(panel._selectable())
                  if panel.data[idx].get("session") == "s1")
    panel.cursor = target
    panel._activate()
    app.update()
    assert app.engine.session_id == "s1"
    assert app.engine.chat_history == msgs


def test_wipe_sessions_clears_them_all(app):
    sessions.save("s1", [{"role": "user", "content": "a"}])
    sessions.save("s2", [{"role": "user", "content": "b"}])
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "sessions"
    panel._build()
    target = next(i for i, idx in enumerate(panel._selectable())
                  if panel.data[idx]["kind"] == "wipe_sessions")
    panel.cursor = target
    panel._activate()
    assert sessions.list_all() == []
    panel.close()


def test_new_chat_starts_a_fresh_session_id(app):
    old = app.engine.session_id
    app._new_chat()
    assert app.engine.session_id != old


# ── صفحة الصلاحيات ──────────────────────────────────────────────────

def test_permissions_page_says_nothing_allowed_by_default(app):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "permissions"
    panel._build()
    assert any("كل حاجة بتتسأل" in i["label"] for i in panel.data)
    panel.close()


def test_permissions_page_lists_granted_commands(app):
    permissions.allow("probe")
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "permissions"
    panel._build()
    assert any(i.get("kind") == "revoke" and i["label"] == "probe"
               for i in panel.data)
    panel.close()


def test_enter_revokes_a_permission(app):
    permissions.allow("probe")
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "permissions"
    panel._build()
    target = next(i for i, idx in enumerate(panel._selectable())
                  if panel.data[idx].get("kind") == "revoke")
    panel.cursor = target
    panel._activate()
    assert permissions.is_allowed("probe") is False
    panel.close()


def test_permissions_page_shows_the_never_allowed_list(app):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "permissions"
    panel._build()
    text = " ".join(i["label"] for i in panel.data)
    assert "run" in text
    panel.close()


# ── صفحة الأحداث ────────────────────────────────────────────────────

def test_hooks_page_lists_every_event(app):
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "hooks"
    panel._build()
    heads = {i["label"] for i in panel.data if i["kind"] == "head"}
    for event in hooks.EVENTS:
        assert event in heads
    panel.close()


def test_enter_unhooks_a_bound_command(app):
    hooks.add("startup", "echo hi")
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "hooks"
    panel._build()
    target = next(i for i, idx in enumerate(panel._selectable())
                  if panel.data[idx].get("kind") == "unhook")
    panel.cursor = target
    panel._activate()
    assert hooks.commands_for("startup") == []
    panel.close()


# ── الخروج ──────────────────────────────────────────────────────────

def test_escape_closes_the_panel(app):
    app._open_settings()
    app.update()
    app._settings._on_escape()
    assert app._settings is None


def test_escape_cancels_typing_before_closing(app):
    """راجع: خانة المفتاح بتتبني لمجرد إن المؤشر واقف على مزوّد، فلو
    Esc اكتفى بوجودها كان هيحتاج ضغطتين على أي سطر مزوّد."""
    app._open_settings()
    app.update()
    panel = app._settings
    panel.page = "brain"
    panel.cursor = 0
    panel._build()
    app.update()

    # تحت Xvfb من غير مدير نوافذ، focus_get() بترجع None دايمًا — فبنحاكي
    # التركيز مباشرة عشان نختبر المنطق نفسه مش سلوك الـ X server.
    editing = panel.editing
    panel.focus_get = lambda: editing
    panel._on_escape()
    assert app._settings is panel
    panel.focus_get = lambda: None
    panel._on_escape()
    assert app._settings is None


def test_only_one_panel_at_a_time(app):
    app._open_settings()
    first = app._settings
    app._open_settings()
    assert app._settings is first
    first.close()


def test_closing_clears_the_reference(app):
    app._open_settings()
    app._settings.close()
    assert app._settings is None
