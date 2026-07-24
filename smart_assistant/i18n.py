"""
i18n.py — طبقة الترجمة (i18n) للمساعد الذكي: عربي / إنجليزي.
كل نصوص الواجهة بتتسحب من هنا بدل ما تتكتب مباشرة جوه main_gui.py.
"""
from __future__ import annotations

STRINGS = {
    "ar": {
        "app_title": "المساعد الذكي",
        "app_subtitle": "منصة أوامر وأتمتة",
        "status_idle": "جاهز",
        "status_running": "شغال",
        "status_stopped": "متوقف",
        "input_placeholder": "اكتب أمرك هنا... (help لعرض الأوامر)",
        "send": "تنفيذ",
        "clear_log": "مسح",
        "log_title": "السجل",
        "lang_toggle": "English",
        "start": "▶  تشغيل",
        "stop": "⏹  إيقاف",
    },
    "en": {
        "app_title": "Smart Assistant",
        "app_subtitle": "Command & automation platform",
        "status_idle": "Ready",
        "status_running": "Running",
        "status_stopped": "Stopped",
        "input_placeholder": "Type a command... (help to list commands)",
        "send": "Run",
        "clear_log": "Clear",
        "log_title": "Log",
        "lang_toggle": "العربية",
        "start": "▶  Start",
        "stop": "⏹  Stop",
    },
}

DEFAULT_LANG = "ar"


class Translator:
    """مسؤول عن حفظ اللغة الحالية وترجمة المفاتيح لنصوص الواجهة."""

    def __init__(self, lang: str = DEFAULT_LANG):
        self.lang = lang if lang in STRINGS else DEFAULT_LANG

    def set_lang(self, lang: str):
        if lang in STRINGS:
            self.lang = lang

    def toggle(self) -> str:
        self.set_lang("en" if self.lang == "ar" else "ar")
        return self.lang

    def t(self, key: str) -> str:
        return STRINGS.get(self.lang, STRINGS[DEFAULT_LANG]).get(key, key)
