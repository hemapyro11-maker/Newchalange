"""
i18n.py — طبقة الترجمة: إنجليزي / عربي.

**الافتراضي إنجليزي.** نيزوكو بتشتغل باللغتين بالكامل — كتابة، نطق،
وسمع — وتبدّل من الإعدادات أو `/lang`.

كل نص بيظهر في الواجهة بيتسحب من هنا بمفتاح، مش مكتوب في مكانه. أي
مفتاح ناقص في لغة بيرجع للإنجليزي بدل ما يختفي.
"""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # الهوية
        "app_title": "nezuko",
        "app_subtitle": "your local AI assistant",
        # الحالة
        "status_running": "running",
        "status_stopped": "stopped",
        "no_brain": "no brain · press ⚙",
        "quota_left": "{n} left",
        "plugins_loaded": "{n} plugins",
        "mode_deep": "deep",
        "mode_local": "local only",
        "mode_voice": "voice",
        # الإدخال
        "input_placeholder": "Type anything...",
        "input_hint": "Just type naturally — no commands to memorise",
        # الترحيب
        "greet_ready": "Type anything in plain language — no commands to learn.",
        "greet_commands": "Direct commands work now (help / env_check).",
        "greet_setup": "To understand plain language, press ⚙ and set up a free brain.",
        "resumed": "conversation resumed",
        "thinking": "…",
        # أوامر الشرطة
        "slash_unknown": "/settings  /resume  /clear  /theme  /voice  /lang  /quit",
        # حوارات الملفات
        "pick_file": "Choose a file",
        "pick_dir": "Choose a folder",
        "pick_file_scan": "Choose the file to scan",
        "pick_code": "Choose the code file or folder",
        "pick_media": "Choose a media file",
        "pick_video": "Choose a video",
        "pick_audio": "Choose an audio file",
        "pick_image": "Choose an image",
        "pick_csv": "Choose a CSV file",
        "pick_db": "Choose the database",
        "pick_apk": "Choose an APK",
        "pick_out_dir": "Choose where to save",
        "pick_host": "Which host?",
        "pick_channel": "Which channel? (name or @handle)",
        "pick_video_id": "Which video? (id or URL)",
        "attach_title": "Attach a file",
        "scan_title": "Security scan",
        # الإعدادات
        "settings": "Settings",
        "nav_hint": "↑ ↓ move  ·  Enter change  ·  Esc close",
        "nav_hint_sub": "↑ ↓ move  ·  Enter change  ·  ← back  ·  Esc close",
        "back_home": "← back to main",
        "page_home": "Main",
        "page_brain": "Brain",
        "page_connectors": "Connectors (MCP)",
        "page_plugins": "Plugins",
        "page_skills": "Skills",
        "page_macros": "Macros",
        "page_sessions": "Sessions",
        "page_permissions": "Permissions",
        "page_hooks": "Hooks",
        "page_interface": "Interface",
        "sec_sections": "Sections",
        "sec_modes": "Modes",
        "sec_actions": "Actions",
        "sec_appearance": "Appearance",
        "sec_ui_commands": "Interface commands",
        "deep_mode": "Deep mode",
        "deep_note": "several models answer, the strongest merges them · ~4× quota",
        "auto_deep": "Auto deep",
        "auto_note": "use deep mode only for questions that need working out",
        "verify_mode": "Self-check",
        "verify_note": "answer, then check the answer and fix what fails · 4 calls",
        "local_only": "Local only",
        "local_note": "disables every cloud provider · needs Ollama",
        "theme": "Theme",
        "language": "Language",
        "voice": "Voice",
        "on": "on",
        "off": "off",
        "none": "none",
        "ready": "ready",
        "not_set": "—",
        "configured": "configured",
        "running_word": "running",
        "not_running": "not running",
        # المخ
        "free_providers": "Free providers",
        "paste_key": "Paste the key and press Enter",
        "trains_warning": "🔓 this free tier trains on your input",
        "key_saved_keyring": "{p} key saved to the system secret store",
        "key_saved_plain": "{p} key saved to a local file",
        # الموصلات
        "mcp_servers": "MCP servers",
        "mcp_missing": "plugin not loaded",
        "mcp_none": "no connectors configured",
        "mcp_hint": "copy connectors.example.json and edit it",
        "tools_count": "{n} tools",
        # الإضافات
        "loaded_n": "Loaded ({n})",
        "pending_approval": "Awaiting your approval",
        "reload_plugins": "Reload plugins",
        "reload_macros": "Reload macros",
        # المهارات
        "top_commands": "Most used commands (of {n})",
        "local_dictionary": "Local dictionary",
        "dict_coverage": "Dictionary coverage and learned phrasings",
        "think_playbooks": "think playbooks",
        # الماكروهات
        "custom_commands": "Custom commands (commands/*.txt)",
        "no_macros": "no macros — drop a .txt file into commands/",
        # الجلسات
        "saved_chats": "Saved conversations",
        "no_sessions": "nothing saved yet",
        "session_hint": "Enter opens it · Delete removes it",
        "wipe_sessions": "Delete every conversation",
        "wiped_sessions": "deleted {n} conversations",
        # الصلاحيات
        "auto_allowed": "Commands that run without asking",
        "nothing_allowed": "none — everything asks",
        "safe_default_note": "The safe default. Answer 'a' instead of 'y' at a prompt to add one here.",
        "revoke_hint": "Enter removes the permission",
        "wipe_perms": "Revoke every permission",
        "wiped_perms": "revoked {n} permissions",
        "never_allowed": "Never allowed",
        "never_note": "These execute code or take free-form input — they need your approval every time.",
        "allowed_word": "allowed",
        # الأحداث
        "bound": "bound",
        "unhook_hint": "Enter unbinds it",
        "hook_hint": "Bind from the command line: hook add <event> <command>",
        # الوقت
        "t_now": "just now",
        "t_min": "{n}m ago",
        "t_hour": "{n}h ago",
        "t_day": "{n}d ago",
        "untitled": "untitled conversation",
    },
    "ar": {
        "app_title": "نيزوكو",
        "app_subtitle": "مساعدتك الذكية المحلية",
        "status_running": "شغالة",
        "status_stopped": "متوقفة",
        "no_brain": "مفيش مخ · دوس ⚙",
        "quota_left": "{n} متبقي",
        "plugins_loaded": "{n} إضافة",
        "mode_deep": "عميق",
        "mode_local": "محلي بس",
        "mode_voice": "صوت",
        "input_placeholder": "اكتب أي حاجة...",
        "input_hint": "اكتب بالعامية عادي — مش لازم تحفظ أوامر",
        "greet_ready": "اكتب أي حاجة بالعامية — مفيش أوامر تتحفظ.",
        "greet_commands": "الأوامر المباشرة شغالة (help / env_check).",
        "greet_setup": "عشان أفهم كلامك العادي، دوس ⚙ وظبّط مخ مجاني.",
        "resumed": "محادثة مستكملة",
        "thinking": "…",
        "slash_unknown": "/settings  /resume  /clear  /theme  /voice  /lang  /quit",
        "pick_file": "اختار ملف",
        "pick_dir": "اختار مجلد",
        "pick_file_scan": "اختار الملف اللي عايز تفحصه",
        "pick_code": "اختار ملف أو مجلد الكود",
        "pick_media": "اختار ملف الميديا",
        "pick_video": "اختار الفيديو",
        "pick_audio": "اختار ملف الصوت",
        "pick_image": "اختار الصورة",
        "pick_csv": "اختار ملف CSV",
        "pick_db": "اختار قاعدة البيانات",
        "pick_apk": "اختار ملف APK",
        "pick_out_dir": "اختار مكان الحفظ",
        "pick_host": "اسم الموقع؟",
        "pick_channel": "أنهي قناة؟ (اسم أو @handle)",
        "pick_video_id": "أنهي فيديو؟ (معرّف أو رابط)",
        "attach_title": "إرفاق ملف",
        "scan_title": "فحص أمني",
        "settings": "الإعدادات",
        "nav_hint": "↑ ↓ تنقل  ·  Enter تغيير  ·  Esc خروج",
        "nav_hint_sub": "↑ ↓ تنقل  ·  Enter تغيير  ·  ← رجوع  ·  Esc خروج",
        "back_home": "← رجوع للرئيسية",
        "page_home": "الرئيسية",
        "page_brain": "المخ",
        "page_connectors": "الموصلات (MCP)",
        "page_plugins": "الإضافات",
        "page_skills": "المهارات",
        "page_macros": "الماكروهات",
        "page_sessions": "الجلسات",
        "page_permissions": "الصلاحيات",
        "page_hooks": "الأحداث",
        "page_interface": "الواجهة",
        "sec_sections": "الأقسام",
        "sec_modes": "الأوضاع",
        "sec_actions": "أفعال",
        "sec_appearance": "الشكل",
        "sec_ui_commands": "أوامر الواجهة",
        "deep_mode": "الوضع العميق",
        "deep_note": "كذا نموذج يجاوبوا وأقواهم يدمجهم · ~4× الحصة",
        "auto_deep": "عميق تلقائي",
        "auto_note": "الوضع العميق في الأسئلة اللي محتاجة تفكير بس",
        "verify_mode": "مراجعة ذاتية",
        "verify_note": "يجاوب، يراجع إجابته، ويصلّح اللي وقع · 4 نداءات",
        "local_only": "محلي بس",
        "local_note": "بيقفل كل السحابي · محتاج Ollama",
        "theme": "الثيم",
        "language": "اللغة",
        "voice": "الصوت",
        "on": "شغال",
        "off": "مقفول",
        "none": "مفيش",
        "ready": "جاهز",
        "not_set": "—",
        "configured": "متظبط",
        "running_word": "شغال",
        "not_running": "مش شغال",
        "free_providers": "المزوّدين المجانيين",
        "paste_key": "الصق المفتاح واضغط Enter",
        "trains_warning": "🔓 الخطة المجانية بتستخدم كلامك للتدريب",
        "key_saved_keyring": "مفتاح {p} اتحفظ في مخزن أسرار النظام",
        "key_saved_plain": "مفتاح {p} اتحفظ في ملف محلي",
        "mcp_servers": "خوادم MCP",
        "mcp_missing": "الإضافة مش محمّلة",
        "mcp_none": "مفيش موصلات متظبطة",
        "mcp_hint": "انسخ connectors.example.json وعدّله",
        "tools_count": "{n} أداة",
        "loaded_n": "محمّلة ({n})",
        "pending_approval": "مستنية موافقتك",
        "reload_plugins": "إعادة تحميل الإضافات",
        "reload_macros": "إعادة تحميل الماكروهات",
        "top_commands": "أكتر الأوامر استخدامًا (من {n})",
        "local_dictionary": "القاموس المحلي",
        "dict_coverage": "تغطية القاموس والصيغ المتعلّمة",
        "think_playbooks": "playbooks بتاعة think",
        "custom_commands": "أوامر مخصصة (commands/*.txt)",
        "no_macros": "مفيش ماكروهات — حط ملف .txt في commands/",
        "saved_chats": "محادثات محفوظة",
        "no_sessions": "مفيش محادثات محفوظة لسه",
        "session_hint": "Enter يفتحها · Delete يمسحها",
        "wipe_sessions": "امسح كل المحادثات",
        "wiped_sessions": "اتمسحت {n} محادثة",
        "auto_allowed": "أوامر بتعدي من غير سؤال",
        "nothing_allowed": "مفيش — كل حاجة بتتسأل",
        "safe_default_note": "الافتراضي الآمن. لما تأكّد أمر اكتب a بدل y عشان يتضاف هنا.",
        "revoke_hint": "Enter يشيل السماح",
        "wipe_perms": "اسحب كل الصلاحيات",
        "wiped_perms": "اتسحبت {n} صلاحية",
        "never_allowed": "ممنوعة نهائيًا",
        "never_note": "بتنفذ كود أو بتوصل لحاجة بمدخلات حرة — محتاجة موافقتك كل مرة.",
        "allowed_word": "مسموح",
        "bound": "مربوط",
        "unhook_hint": "Enter يفكّه",
        "hook_hint": "الربط من الأمر: hook add <event> <command>",
        "t_now": "دلوقتي",
        "t_min": "من {n} دقيقة",
        "t_hour": "من {n} ساعة",
        "t_day": "من {n} يوم",
        "untitled": "محادثة من غير عنوان",
    },
}

DEFAULT_LANG = "en"
RTL_LANGS = frozenset({"ar"})


class Translator:
    """بيحفظ اللغة الحالية ويترجم المفاتيح.

    أي مفتاح ناقص في اللغة الحالية بيرجع للإنجليزي بدل ما يختفي —
    فإضافة نص جديد مش بتكسر الواجهة قبل ما يتترجم.
    """

    def __init__(self, lang: str = DEFAULT_LANG):
        self.lang = lang if lang in STRINGS else DEFAULT_LANG

    def set_lang(self, lang: str) -> str:
        if lang in STRINGS:
            self.lang = lang
        return self.lang

    def toggle(self) -> str:
        return self.set_lang("ar" if self.lang == "en" else "en")

    @property
    def is_rtl(self) -> bool:
        return self.lang in RTL_LANGS

    def t(self, key: str, **fmt) -> str:
        text = STRINGS.get(self.lang, {}).get(key)
        if text is None:
            text = STRINGS[DEFAULT_LANG].get(key, key)
        if fmt:
            try:
                return text.format(**fmt)
            except (KeyError, IndexError):
                return text
        return text
