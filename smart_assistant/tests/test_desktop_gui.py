"""Exercise actual Unicode editing, clipboard order and rendered block layout."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QSpinBox
import core_engine
import desktop_gui as ui


def test_jarvis_identity_and_activity_indicator_follow_real_status(desktop, qtapp):
    assert desktop.windowTitle().startswith("Jarvis ·")
    assert "Jarvis" in desktop.entry.placeholderText()
    desktop.health = "ready"
    desktop.set_status("listening")
    assert desktop.reactor.state == "listening"
    assert desktop.reactor.timer.isActive()
    assert "Listening" in desktop.core_status.text()
    desktop.set_status("ready")
    assert not desktop.reactor.timer.isActive()
    desktop.set_status("thinking")
    desktop.reactor.hide()
    qtapp.processEvents()
    assert not desktop.reactor.timer.isActive()


def test_jarvis_welcome_returns_for_new_session_without_erasing_saved_data(desktop):
    assert not desktop.welcome.isHidden()
    desktop.add_message("user", "مرحبا Jarvis")
    assert desktop.welcome.isHidden()
    desktop.new_chat()
    assert not desktop.welcome.isHidden()
    assert desktop.messages == []


@pytest.fixture(scope="module")
def qtapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(qtapp, tmp_path, monkeypatch):
    cfg = {"assistant_mode": "companion", "ui_theme": "dark", "primary": "ollama"}
    monkeypatch.setattr(ui.brain, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(ui.brain, "save_config", lambda value: cfg.update(value))
    monkeypatch.setattr(ui.sessions, "list_all", lambda: [])
    monkeypatch.setattr(ui.sessions, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(core_engine, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(ui, "AssistantEngine", lambda **kw: core_engine.AssistantEngine(**kw, plugins_dirs=[]))
    window = ui.Desktop(start_engine=False)
    window.show()
    qtapp.processEvents()
    yield window
    window.close()
    qtapp.processEvents()


def test_mixed_script_copy_paste_and_undo_are_logical_unicode(qtapp):
    composer = ui.Composer()
    composer.show()
    composer.setFocus()
    original = "أنا بكتب عربي مع English 123 ورابط https://example.com\nسطر جديد"
    composer.setPlainText(original)
    QTest.keyClick(composer, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(composer, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qtapp.clipboard().text() == original
    qtapp.clipboard().setText("نص جديد New text")
    QTest.keyClick(composer, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert composer.toPlainText() == "نص جديد New text"
    QTest.keyClick(composer, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert composer.toPlainText() == original
    composer.close()


def test_enter_and_ctrl_enter_submit_but_shift_enter_inserts_newline(qtapp):
    composer = ui.Composer()
    submitted = []
    composer.submitted.connect(lambda: submitted.append(True))
    composer.setPlainText("hello")
    composer.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClick(composer, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert composer.toPlainText() == "hello\n"
    QTest.keyClick(composer, Qt.Key.Key_Return)
    QTest.keyClick(composer, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert len(submitted) == 2
    composer.close()


def test_wake_queues_acknowledgement_before_microphone(desktop, monkeypatch):
    calls = []
    desktop.health = "ready"
    desktop.wake_enabled = True
    monkeypatch.setattr(desktop.engine, "run_task", lambda name, fn: calls.append(name))
    monkeypatch.setattr(desktop.engine, "listen", lambda: calls.append("listen"))
    desktop.on_wake()
    assert calls == ["wake acknowledgement", "listen"]
    assert desktop.voice and desktop.activity == "queued"
    desktop.on_wake()
    assert len(calls) == 2


def test_wake_ignores_disabled_busy_or_playing_voice(desktop, monkeypatch):
    calls = []
    monkeypatch.setattr(desktop.engine, "listen", lambda: calls.append(True))
    desktop.health = "ready"
    desktop.on_wake()
    desktop.wake_enabled = True
    desktop.activity = "speaking"
    desktop.on_wake()
    desktop.activity = "ready"
    desktop.tts_pending = True
    desktop.on_wake()
    assert not calls


def test_wake_still_acknowledges_when_local_brain_needs_attention(desktop, monkeypatch):
    calls = []
    desktop.health = "not_ready"
    desktop.wake_enabled = True
    monkeypatch.setattr(desktop.engine, "run_task", lambda name, fn: calls.append(name))
    monkeypatch.setattr(desktop.engine, "listen", lambda: calls.append("listen"))
    desktop.on_wake()
    assert calls == ["wake acknowledgement", "listen"]


def test_dashboard_navigation_keeps_chat_and_uses_real_telemetry(desktop):
    desktop.health = "ready"
    desktop.dashboard.refresh()
    assert "ready" in desktop.dashboard.summary.text()
    assert "18" in desktop.dashboard.summary.text()
    desktop.dashboard.set_metrics({"rms": 3276.8, "score": .42, "peak_score": .48, "threshold": .5})
    assert desktop.dashboard.level.value() == 67
    assert "0.42" in desktop.dashboard.score.text()
    desktop.add_message("user", "اختبار English")
    assert desktop.pages.currentIndex() == 1
    desktop.show_dashboard()
    assert desktop.pages.currentIndex() == 0
    assert desktop.messages == [("user", "اختبار English")]
    desktop.show_chat()
    assert not desktop.entry.isHidden()


def test_composer_shortcut_opens_chat_from_command_center(desktop, qtapp):
    desktop.show_dashboard()
    QTest.keyClick(desktop, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    qtapp.processEvents()
    assert desktop.pages.currentIndex() == 1
    assert desktop.entry.hasFocus()
    desktop.show_dashboard()
    desktop.new_chat()
    assert desktop.pages.currentIndex() == 1


def test_muted_windows_input_is_reported_before_detector_load(desktop, monkeypatch):
    monkeypatch.setattr(ui.audio_health, "microphone_state", lambda selected: {"available": True, "muted": True, "volume": 100})
    class Listener:
        def __init__(self, folder, on_wake, on_status, **kwargs):
            self.folder, self.factory = folder, kwargs["detector_factory"]
        def start(self): self.factory(self.folder)
        def close(self): pass
    monkeypatch.setattr(ui.wake_word, "WakeListener", Listener)
    desktop.toggle_wake()
    assert not desktop.wake_enabled
    assert "Windows microphone is muted" in desktop.messages[-1][1]


def test_arabic_markdown_wraps_without_reversing_copy(qtapp):
    text = "أهلاً بيك، هنراجع فيديو Tuty Storytime ونكتب خطة واضحة. " * 6
    browser = ui.MessageText(text + "\n\nEnglish paragraph stays readable.", QFont("Segoe UI", 14), markdown=True)
    browser.resize(340, 200)
    browser.show()
    qtapp.processEvents()
    assert text.strip() in browser.toPlainText()
    block = browser.document().begin()
    assert block.blockFormat().layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert block.layout().lineCount() > 1
    last = browser.document().lastBlock()
    assert last.blockFormat().layoutDirection() == Qt.LayoutDirection.LeftToRight
    browser.selectAll()
    browser.copy()
    assert "Tuty Storytime" in qtapp.clipboard().text()
    assert "أهلاً بيك" in qtapp.clipboard().text()
    browser.close()


def test_markdown_styles_and_untrusted_images(qtapp):
    browser = ui.MessageText("**Bold**\n\n- First\n- Second\n\n<img src='https://example.com/tracker'>", QFont(), markdown=True)
    assert browser.document().begin().begin().fragment().charFormat().fontWeight() >= QFont.Weight.Bold
    assert browser.document().find("First").block().textList() is not None
    assert browser.loadResource(2, ui.QUrl("https://example.com/tracker")) is None
    assert "<img" in browser.toPlainText()  # raw HTML displayed literally
    browser.close()


def test_native_chat_keeps_original_text_and_larger_font(desktop, qtapp):
    original = "عاملة إيه يا جارفيس؟ Let's work on الفيديو."
    desktop.add_message("assistant", original)
    qtapp.processEvents()
    assert original in desktop.markdown()
    assert desktop.cards[-1][1].toPlainText() == original
    assert desktop.cards[-1][1].font().pixelSize() == 19
    desktop.copy_chat()
    assert original in qtapp.clipboard().text()
    assert ui.theme.DARK["bg"] == "#030a10"


def test_native_settings_save_font_without_overwriting_brain(desktop, qtapp):
    def accept():
        dialog = desktop.findChild(QDialog)
        dialog.findChild(QSpinBox).setValue(22)
        dialog.accept()
    QTimer.singleShot(50, accept)
    desktop.settings()
    assert desktop.text_size == 22
    assert ui.brain.load_config()["primary"] == "ollama"
    assert ui.brain.load_config()["chat_font_size"] == 22


def test_microphone_enables_spoken_answers_and_submits_once(desktop, monkeypatch):
    requests = []
    monkeypatch.setattr(desktop.engine, "listen", lambda: requests.append("listen_run"))
    desktop.activity = "ready"
    desktop.listen()
    desktop.listen()  # no double recording while busy
    assert desktop.voice is True
    assert requests == ["listen_run"]


def test_final_model_reply_is_spoken_once_without_badge(desktop, monkeypatch):
    spoken = []
    monkeypatch.setattr(desktop.engine, "speak", spoken.append)
    desktop.voice = True
    desktop.last_command = "listen_run"
    desktop.render_log("I'm ready.\n— Jarvis · Local", "info")
    assert spoken == []  # logs never trigger speech
    desktop.on_reply("I'm ready.",desktop.engine._generation,True)
    assert spoken == ["I'm ready."]
    assert desktop.messages[-1] == ("assistant", "I'm ready.")
    desktop.render_log("🔊 spoken with Kokoro", "ok")
    assert len(spoken) == 1


def test_repeated_voice_turns_speak_every_final_answer_and_never_drafts(desktop,monkeypatch):
    spoken=[]
    monkeypatch.setattr(desktop.engine,'speak',spoken.append)
    desktop.render_log('🎤 I heard: How are you?', 'info')
    desktop.show_preview('partial response',desktop.engine._generation)
    assert desktop.preview_browser is None
    desktop.on_reply('I am well.',desktop.engine._generation,True)
    desktop.render_log('🔊 spoken with Kokoro','ok')
    desktop.render_log('🎤 I heard: What is your name?', 'info')
    desktop.on_reply('I am Jarvis.',desktop.engine._generation,True)
    assert spoken==['I am well.','I am Jarvis.']
    desktop.on_reply('Typed reply.',desktop.engine._generation,False)
    assert len(spoken)==2


def test_navigation_never_submits_commands_and_background_logs_keep_selected_view(desktop,monkeypatch):
    submitted=[]
    monkeypatch.setattr(desktop.engine,'submit',submitted.append)
    desktop.show_workspace('tools')
    page=desktop.pages.currentWidget()
    desktop.render_log('Background diagnostic','info')
    assert desktop.pages.currentWidget() is page
    assert submitted==[]
    assert not desktop.entry.isVisible()
    assert not desktop.dashboard.backdrop.timer.isActive()
    desktop.show_dashboard()
    assert desktop.dashboard.backdrop.timer.isActive()


def test_session_switch_saves_previous_chat_and_ignores_stale_voice(desktop,monkeypatch):
    old=desktop.engine.session_id
    desktop.engine.chat_history=[{'role':'user','content':'first chat'},{'role':'assistant','content':'first answer'}]
    generation=desktop.engine._generation
    desktop.new_chat()
    assert ui.sessions.load(old)[0]['content']=='first chat'
    assert desktop.engine.session_id!=old
    assert desktop.engine.chat_history==[]
    spoken=[]
    monkeypatch.setattr(desktop.engine,'speak',spoken.append)
    desktop.on_reply('Old answer',generation,True)
    assert spoken==[]
    item=ui.QListWidgetItem('first chat');item.setData(Qt.ItemDataRole.UserRole,old)
    desktop.resume(item)
    assert desktop.engine.session_id==old
    assert desktop.engine.chat_history[0]['content']=='first chat'


def test_unicode_composer_is_submitted_unchanged(desktop, monkeypatch):
    submitted = []
    monkeypatch.setattr(desktop.engine, "submit", submitted.append)
    original = "افتحي مشروع Video 2026 وراجعي الصوت"
    desktop.entry.setPlainText(original)
    desktop.send()
    assert submitted == [original]
    assert desktop.entry.toPlainText() == ""


def test_streaming_draft_is_not_saved_or_spoken_and_disappears_on_final(desktop, monkeypatch):
    spoken = []
    monkeypatch.setattr(desktop.engine, "speak", spoken.append)
    desktop.show_preview("رد لسه بيتكتب…", desktop.engine._generation)
    assert desktop.preview_browser.toPlainText() == "رد لسه بيتكتب…"
    assert desktop.messages == []
    assert spoken == []
    desktop.render_log("الرد النهائي.\n— Jarvis · Local", "info")
    assert desktop.preview_browser is None
    assert desktop.messages == [("assistant", "الرد النهائي.")]


def test_old_session_draft_is_ignored(desktop):
    old_generation = desktop.engine._generation
    desktop.new_chat()
    desktop.show_preview("stale text", old_generation)
    assert desktop.preview_browser is None
