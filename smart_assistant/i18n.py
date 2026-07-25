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
        "new_chat": "＋  محادثة جديدة",
        "settings": "الإعدادات",
        "listen": "استماع بالمايك",
        "brain_settings": "المخ والمفاتيح",
        "input_hint": "اكتب بالعامية عادي — مش لازم تحفظ أوامر",
        "tooltip_mic": "سجّل صوتك ونيزوكو تفهمه وتنفذه",
        "tooltip_brain": "ظبّط مخ نيزوكو — كل الخيارات مجانية",
        "input_placeholder": "اكتب أي حاجة...",
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
        "tooltip_send": "أرسل الأمر (Enter)",
        "tooltip_attach": "بينفذ: probe <ملف> — تحليل ميتاداتا/محتوى الملف",
        "tooltip_scan": "بينفذ: security_report <ملف> — فحص أمني شامل (فيروسات، أسرار مكشوفة، صلاحيات)",
        "tooltip_voice_on": "الصوت شغال — نيزوكو بتقرا ردودها بصوتها. دوسي تقفليه",
        "tooltip_voice_off": "الصوت مقفول — دوسي عشان نيزوكو تقرا ردودها بصوتها",
        "tooltip_lang": "بدّل لغة الواجهة (عربي ⇄ إنجليزي)",
        "tooltip_clear": "امسح فقاعات المحادثة من الشاشة (السجل نفسه فاضل زي ما هو)",
        "tooltip_start": "شغّل محرك نيزوكو (بيحمّل كل الإضافات)",
        "tooltip_stop": "أوقف محرك نيزوكو",
    },
    "en": {
        "app_title": "Nezuko",
        "app_subtitle": "Your Egyptian AI assistant",
        "status_idle": "Ready",
        "status_running": "Running",
        "status_stopped": "Stopped",
        "new_chat": "＋  New chat",
        "settings": "Settings",
        "listen": "Listen (mic)",
        "brain_settings": "Brain & keys",
        "input_hint": "Just type naturally — no commands to memorise",
        "tooltip_mic": "Record your voice; Nezuko transcribes and runs it",
        "tooltip_brain": "Set up Nezuko's brain — all options are free",
        "input_placeholder": "Type anything...",
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
        "tooltip_send": "Send command (Enter)",
        "tooltip_attach": "Runs: probe <file> — analyze file metadata/content",
        "tooltip_scan": "Runs: security_report <file> — full security scan (virus, exposed secrets, permissions)",
        "tooltip_voice_on": "Voice is on — Nezuko speaks her replies aloud. Click to turn off",
        "tooltip_voice_off": "Voice is off — click so Nezuko speaks her replies aloud",
        "tooltip_lang": "Switch UI language (Arabic ⇄ English)",
        "tooltip_clear": "Clear chat bubbles from view (the underlying log is unaffected)",
        "tooltip_start": "Start Nezuko's engine (loads all plugins)",
        "tooltip_stop": "Stop Nezuko's engine",
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
