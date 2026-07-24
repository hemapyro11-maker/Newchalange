"""
i18n.py — طبقة الترجمة (i18n) للمساعد الذكي: عربي / إنجليزي.
كل نصوص الواجهة بتتسحب من هنا بدل ما تتكتب مباشرة جوه main_gui.py.
"""
from __future__ import annotations

STRINGS = {
    "ar": {
        "app_title": "نيزوكو",
        "app_subtitle": "مساعدتك الذكية المصرية",
        "status_idle": "جاهزة",
        "status_running": "شغالة",
        "status_stopped": "متوقفة",
        "input_placeholder": "اكتبي أمرك هنا... (help لعرض الأوامر)",
        "send": "تنفيذ",
        "clear_log": "مسح",
        "log_title": "السجل",
        "lang_toggle": "English",
        "start": "▶  تشغيل",
        "stop": "⏹  إيقاف",
        "attach_file": "إرفاق ملف للتحليل",
        "scan_file": "فحص ملف أمنيًا (أي نوع، أي حجم)",
        "scanning_file": "📡  بيتفحص",
        "voice_toggle_on": "الصوت شغال",
        "voice_toggle_off": "الصوت مقفول",
        "quick_actions": "إجراءات سريعة",
    },
    "en": {
        "app_title": "Nezuko",
        "app_subtitle": "Your Egyptian AI assistant",
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
        "attach_file": "Attach file to analyze",
        "scan_file": "Security-scan a file (any type, any size)",
        "scanning_file": "📡  Scanning",
        "voice_toggle_on": "Voice on",
        "voice_toggle_off": "Voice off",
        "quick_actions": "Quick actions",
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
