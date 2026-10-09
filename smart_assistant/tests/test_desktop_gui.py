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


@pytest.fixture(scope="module")
def qtapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(qtapp, tmp_path, monkeypatch):
    cfg = {"assistant_mode": "companion", "ui_theme": "dark", "primary": "ollama"}
    monkeypatch.setattr(ui.brain, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(ui.brain, "save_config", lambda value: cfg.update(value))
    monkeypatch.setattr(ui.sessions, "list_all", lambda: [])
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
    original = "عاملة إيه يا نيزكو؟ Let's work on الفيديو."
    desktop.add_message("assistant", original)
    qtapp.processEvents()
    assert original in desktop.markdown()
    assert desktop.cards[-1][1].toPlainText() == original
    assert desktop.cards[-1][1].font().pixelSize() == 19
    desktop.copy_chat()
    assert original in qtapp.clipboard().text()
    assert ui.theme.DARK["bg"] == "#181818"


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
    desktop.render_log("I'm ready.\n— Nezuko · Local", "info")
    assert spoken == ["I'm ready."]
    assert desktop.messages[-1] == ("assistant", "I'm ready.")
    desktop.render_log("🔊 spoken with Kokoro", "ok")
    assert len(spoken) == 1


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
    desktop.render_log("الرد النهائي.\n— Nezuko · Local", "info")
    assert desktop.preview_browser is None
    assert desktop.messages == [("assistant", "الرد النهائي.")]


def test_old_session_draft_is_ignored(desktop):
    old_generation = desktop.engine._generation
    desktop.new_chat()
    desktop.show_preview("stale text", old_generation)
    assert desktop.preview_browser is None
