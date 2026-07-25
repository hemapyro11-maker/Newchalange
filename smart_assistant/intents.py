"""
intents.py — طبقة النوايا المحلية: بتترجم كلامك العادي لأمر حقيقي
**من غير ما تلمس أي نموذج لغة**، يعني بصفر استهلاك من الحصة المجانية.

**ليه الملف ده موجود:** المخ (brain.py) بيستهلك حصة في كل نداء. لكن
لما تقول "افحص الملف ده أمنيًا" مفيش أي داعي لنموذج ذكاء — الجملة دي
واضحة وثابتة، ومطابقتها بقاموس محلي أسرع وأدق ومجاني. النموذج المفروض
يتنادى بس للكلام اللي فعلاً محتاج فهم.

**إزاي بنحل الوسائط محليًا كمان (مش بس اسم الأمر):**

| نوع الوسيطة | الحل المحلي |
|---|---|
| مسار ملف | نافذة اختيار ملف (الواجهة بتفتحها) |
| ملف خرج | يتشتق من ملف الدخل (`video.mp4` → `video_graded.mp4`) |
| رقم | regex بيمسك الأرقام العربية والإنجليزية |
| نص حر | باقي الجملة بعد كلمة التشغيل |
| قناة/رابط | regex بيمسك `@handle` أو URL |

**القاموس بيتعلّم:** أي صيغة كلام النموذج فهمها لأول مرة بتتحفظ في
`intent_cache.json`، فنفس الصيغة تاني مرة بتتحل محليًا ببلاش. يعني
كل نداء بتدفعه مرة واحدة بس في حياتك، والقاموس بيتشكّل على طريقتك
إنت في الكلام مع الوقت — نفس فلسفة `skills.json` الموجودة أصلاً.

**حدود صريحة:** القاموس بيمسك الصيغ المكتوبة فيه. اللغة البشرية
مالهاش حصر، فالتغطية الواقعية ~70-85% من الكلام الحقيقي، والباقي
بيقع على المخ (ويتحفظ بعدها). أي حد يقول إن قاموس بيغطي 100% بيبيع وهم.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import threading
from dataclasses import dataclass, field

_lock = threading.Lock()

# ── تطبيع النص العربي ────────────────────────────────────────────────

_DIACRITICS = re.compile(r"[ؗ-ًؚ-ْٰـ]")
_ALEF = re.compile(r"[أإآٱ]")
_ALEF_MAQSURA = re.compile(r"ى")
_TA_MARBUTA = re.compile(r"ة")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize(text: str) -> str:
    """بيوحّد صيغ الكتابة العربية المختلفة عشان المطابقة تنجح.

    من غير التطبيع ده، "إفحص" و"افحص" و"أفحص" هيبقوا 3 كلمات مختلفة
    تمامًا وهنحتاج نكتب كل صيغة بالإيد — وده مستحيل عمليًا.
    """
    text = text.strip().lower()
    text = _DIACRITICS.sub("", text)
    text = _ALEF.sub("ا", text)
    text = _ALEF_MAQSURA.sub("ي", text)
    text = _TA_MARBUTA.sub("ه", text)
    text = text.translate(_ARABIC_DIGITS)
    text = re.sub(r"\s+", " ", text)
    return text


# ── وصف الوسائط ──────────────────────────────────────────────────────

FILE = "file"          # مسار ملف موجود — الواجهة بتفتح نافذة اختيار
DIR = "dir"            # مجلد
OUT = "out"            # ملف خرج — بيتشتق من ملف الدخل
REST = "rest"          # باقي الجملة كنص حر
NUMBER = "number"      # رقم من الجملة
HANDLE = "handle"      # @قناة أو رابط أو معرّف


@dataclass(frozen=True)
class ArgSpec:
    kind: str
    prompt: str = ""
    suffix: str = "_out"      # لـ OUT: اللاحقة المضافة لاسم ملف الدخل
    ext: str = ""             # لـ OUT: امتداد مختلف (زي .mp3)
    default: str = ""         # لـ NUMBER لو مفيش رقم في الجملة
    filetypes: str = "all"    # تلميح للواجهة: media/image/audio/video/all


@dataclass(frozen=True)
class IntentRule:
    command: str
    patterns: tuple[str, ...]
    args: tuple[ArgSpec, ...] = ()
    # أولوية أعلى = يتجرب الأول (للقواعد المحددة قبل العامة)
    priority: int = 0


@dataclass
class IntentMatch:
    """نتيجة مطابقة محلية ناجحة."""
    command: str
    args: list[str] = field(default_factory=list)
    # وسائط لسه ناقصة محتاجة تفاعل من الواجهة (نافذة ملف مثلاً) —
    # مهم: ملء الوسائط دي **برضه بصفر حصة**، مش محتاج نموذج
    missing: list[ArgSpec] = field(default_factory=list)
    source: str = "dict"      # dict | cache | exact

    def is_complete(self) -> bool:
        return not self.missing

    def command_line(self) -> str:
        parts = [self.command]
        for a in self.args:
            parts.append(f'"{a}"' if " " in a else a)
        return " ".join(parts)


# ── القاموس المنسّق ──────────────────────────────────────────────────
# كل قاعدة: الأنماط اللي بتشغّلها + وصف وسائطها.
# الأنماط بتتطابق على النص **بعد التطبيع**، فاكتبها بصيغة مطبّعة
# (ا بدل أ/إ، ي بدل ى، ه بدل ة).

RULES: tuple[IntentRule, ...] = (
    # ── أمان ──────────────────────────────────────────────────────
    IntentRule(
        "virus_scan",
        ("فيروس", "فيروسات", "مصاب", "برامج خبيثه", "malware", "virus"),
        (ArgSpec(FILE, "اختار الملف اللي عايز تفحصه"),),
        priority=10,
    ),
    IntentRule(
        "security_report",
        ("افحص .*امني", "فحص امني", "تقرير امني", "امان الملف",
         "الملف ده امان", "security report", "افحص الملف ده"),
        (ArgSpec(FILE, "اختار الملف للفحص الأمني"),),
        priority=9,
    ),
    IntentRule(
        "code_scan",
        ("افحص الكود", "فحص كود", "ثغرات في الكود", "مشاكل امنيه في الكود",
         "راجع الكود", "code scan"),
        (ArgSpec(FILE, "اختار ملف/مجلد الكود"),),
    ),
    IntentRule(
        "vuln_scan",
        ("ثغرات", "اسرار مكشوفه", "مفاتيح مكشوفه", "vulnerabilit"),
        (ArgSpec(FILE, "اختار المجلد"),),
    ),
    IntentRule("quarantine_list", ("الحجر الصحي", "الملفات المعزوله", "quarantine list")),
    IntentRule(
        "hash_file",
        ("بصمه الملف", "checksum", "هاش الملف", "تجزئه الملف"),
        (ArgSpec(FILE, "اختار الملف"),),
    ),
    IntentRule(
        "tls_check",
        ("شهاده", "ssl", "tls", "https امان"),
        (ArgSpec(HANDLE, "اسم الموقع"),),
    ),
    IntentRule(
        "file_perms",
        ("صلاحيات", "permissions", "الصلاحيات"),
        (ArgSpec(FILE, "اختار المسار"),),
    ),

    # ── فيديو وصوت ────────────────────────────────────────────────
    IntentRule(
        "probe",
        ("حلل الفيديو", "معلومات الفيديو", "تفاصيل الملف", "بيانات الفيديو",
         "الفيديو ده ايه", "probe"),
        (ArgSpec(FILE, "اختار ملف الميديا", filetypes="media"),),
    ),
    IntentRule(
        "extract_audio",
        ("استخرج الصوت", "طلع الصوت", "الصوت بس", "حول .* mp3", "extract audio"),
        (ArgSpec(FILE, "اختار الفيديو", filetypes="video"),
         ArgSpec(OUT, suffix="_audio", ext=".mp3")),
        priority=8,
    ),
    IntentRule(
        "convert",
        ("حول الفيديو", "حول الملف", "غير صيغه", "convert"),
        (ArgSpec(FILE, "اختار الملف", filetypes="media"),
         ArgSpec(OUT, suffix="_converted")),
    ),
    IntentRule(
        "auto_trim_silence",
        ("شيل الصمت", "قص الصمت", "نضف الصمت", "الاجزاء الميته", "trim silence"),
        (ArgSpec(FILE, "اختار الفيديو", filetypes="media"),
         ArgSpec(OUT, suffix="_trimmed")),
        priority=8,
    ),
    IntentRule(
        "color_grade",
        ("تدرج لوني", "تصحيح الوان", "لوك سينمائي", "الوان سينمائيه", "color grade"),
        (ArgSpec(FILE, "اختار الفيديو", filetypes="video"),
         ArgSpec(OUT, suffix="_graded")),
    ),
    IntentRule(
        "stabilize",
        ("ثبت الفيديو", "الاهتزاز", "شيل الرجفه", "stabilize"),
        (ArgSpec(FILE, "اختار الفيديو", filetypes="video"),
         ArgSpec(OUT, suffix="_stable")),
    ),
    IntentRule(
        "speed_ramp",
        ("سرع الفيديو", "بطء الفيديو", "سلو موشن", "غير السرعه", "speed"),
        (ArgSpec(FILE, "اختار الفيديو", filetypes="video"),
         ArgSpec(OUT, suffix="_speed"),
         ArgSpec(NUMBER, default="2")),
    ),
    IntentRule(
        "denoise_audio",
        ("شيل الضوضاء", "نضف الصوت", "ضوضاء", "denoise"),
        (ArgSpec(FILE, "اختار ملف الصوت", filetypes="audio"),
         ArgSpec(OUT, suffix="_clean")),
    ),
    IntentRule(
        "master_audio",
        ("اضبط الصوت", "مستوي الصوت", "جهاره", "master audio", "loudness"),
        (ArgSpec(FILE, "اختار ملف الصوت", filetypes="audio"),
         ArgSpec(OUT, suffix="_mastered")),
    ),
    IntentRule(
        "detect_scenes",
        ("المشاهد", "قسم الفيديو", "تغيير المشهد", "detect scenes"),
        (ArgSpec(FILE, "اختار الفيديو", filetypes="video"),),
    ),
    IntentRule(
        "separate_vocals",
        ("افصل الصوت", "افصل الغنا", "اعزل الصوت", "separate vocals", "الموسيقي لوحدها"),
        (ArgSpec(FILE, "اختار ملف الصوت", filetypes="audio"),
         ArgSpec(DIR, "اختار مجلد الحفظ")),
    ),
    IntentRule(
        "upscale_video",
        ("كبر الفيديو", "جوده الفيديو", "دقه اعلي للفيديو", "upscale video"),
        (ArgSpec(FILE, "اختار الفيديو", filetypes="video"),
         ArgSpec(OUT, suffix="_4k")),
        priority=8,
    ),
    IntentRule(
        "upscale_image",
        ("كبر الصوره", "جوده الصوره", "دقه اعلي", "upscale image"),
        (ArgSpec(FILE, "اختار الصورة", filetypes="image"),
         ArgSpec(OUT, suffix="_big")),
    ),

    # ── صوت نيزوكو ────────────────────────────────────────────────
    IntentRule("speak", ("قولي", "اقري", "انطقي", "قول ", "say "), (ArgSpec(REST),), priority=5),
    IntentRule("listen", ("اسمعيني", "سجل صوت", "شغل المايك", "listen")),
    IntentRule("voice_status", ("حاله الصوت", "الصوت شغال", "voice status")),

    # ── يوتيوب ────────────────────────────────────────────────────
    IntentRule(
        "channel_stats",
        ("احصائيات قناه", "بيانات قناه", "معلومات قناه", "channel stats"),
        (ArgSpec(HANDLE, "اسم أو معرّف القناة"),),
        priority=8,
    ),
    IntentRule(
        "channel_growth_report",
        ("نمو القناه", "تحليل القناه", "القناه بتكبر", "اداء القناه", "growth"),
        (ArgSpec(HANDLE, "اسم أو معرّف القناة"),),
        priority=9,
    ),
    IntentRule(
        "video_stats",
        ("احصائيات الفيديو", "مشاهدات الفيديو", "video stats"),
        (ArgSpec(HANDLE, "معرّف الفيديو"),),
    ),
    IntentRule(
        "youtube_search",
        ("دور في يوتيوب", "ابحث في يوتيوب", "youtube search"),
        (ArgSpec(REST),),
    ),
    IntentRule("trending_videos", ("الترند", "الرايج", "trending")),
    IntentRule(
        "seo_title_score",
        ("قيم العنوان", "العنوان ده كويس", "seo title"),
        (ArgSpec(REST),),
    ),
    IntentRule(
        "hook_analyzer",
        ("قيم الهوك", "البدايه دي", "hook"),
        (ArgSpec(REST),),
    ),
    IntentRule(
        "thumbnail_analyze",
        ("حلل المصغره", "المصغره دي", "thumbnail analyze"),
        (ArgSpec(FILE, "اختار المصغرة", filetypes="image"),),
    ),
    IntentRule(
        "comment_sentiment",
        ("مشاعر التعليقات", "التعليقات ايجابيه", "رأي الناس", "sentiment"),
        (ArgSpec(REST),),
    ),

    # ── بيانات وقواعد بيانات ─────────────────────────────────────
    IntentRule(
        "csv_describe",
        ("حلل الملف ده csv", "احصائيات csv", "وصف البيانات", "csv describe"),
        (ArgSpec(FILE, "اختار ملف CSV"),),
    ),
    IntentRule(
        "db_schema",
        ("جداول قاعده البيانات", "بنيه قاعده", "schema"),
        (ArgSpec(FILE, "اختار قاعدة البيانات"),),
    ),

    # ── أندرويد ───────────────────────────────────────────────────
    IntentRule("android_devices", ("الاجهزه المتصله", "الموبايلات", "android devices")),
    IntentRule(
        "android_install",
        ("ثبت التطبيق", "نزل apk", "install apk"),
        (ArgSpec(FILE, "اختار ملف APK"),),
    ),
    IntentRule(
        "android_screenshot",
        ("صوره من الموبايل", "سكرين شوت للموبايل", "android screenshot"),
        (ArgSpec(OUT, suffix="screenshot", ext=".png"),),
    ),

    # ── تصميم ─────────────────────────────────────────────────────
    IntentRule(
        "app_icons",
        ("ايقونات التطبيق", "احجام الايقونات", "app icons"),
        (ArgSpec(FILE, "اختار الصورة", filetypes="image"),
         ArgSpec(DIR, "اختار مجلد الحفظ")),
    ),
    IntentRule(
        "make_logo",
        ("اعملي لوجو", "صمم لوجو", "logo"),
        (ArgSpec(REST), ArgSpec(OUT, suffix="logo", ext=".png")),
    ),

    # ── النظام والأدوات ───────────────────────────────────────────
    IntentRule(
        "env_check",
        ("فحص البيئه", "الادوات المتثبته", "ايه الناقص", "ايه المتثبت",
         "environment", "env check"),
    ),
    IntentRule("plugins", ("الاضافات", "plugins")),
    IntentRule("skills", ("مهاراتك", "بتعرفي تعملي ايه", "skills")),
    IntentRule("help", ("الاوامر", "ساعديني", "ايه الاوامر", "قايمه الاوامر", "help")),
    IntentRule("todo", ("المهام", "قايمه المهام", "todo")),
    IntentRule("schedule", ("الجدوله", "المواعيد", "schedule")),
    IntentRule("check_update", ("تحديث", "اصدار جديد", "update")),
    IntentRule("brain_status", ("حاله المخ", "المخ شغال", "الحصه", "brain status")),
)


# ── استخراج الوسائط من النص ─────────────────────────────────────────

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_HANDLE_RE = re.compile(r"(@[\w\-.]+|https?://\S+|UC[\w\-]{20,})")
_QUOTED_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')
_PATHY_RE = re.compile(r"[A-Za-z]:\\[^\s\"']+|/[^\s\"']+/[^\s\"']+|\S+\.\w{2,5}\b")


def scrub_paths(text: str) -> str:
    """بيشيل المسارات والروابط من الجملة.

    ضروري قبل استخراج الأرقام: `/a/b.mp4` فيه "4"، ولو مشيلناهوش
    الأول كان "سرع الفيديو /a/b.mp4 ٣ مرات" بيطلع منه 4 بدل 3.
    """
    text = _QUOTED_RE.sub(" ", text)
    text = _HANDLE_RE.sub(" ", text)
    return _PATHY_RE.sub(" ", text)


def extract_number(text: str, default: str = "") -> str:
    m = _NUM_RE.search(normalize(scrub_paths(text)))
    return m.group(0) if m else default


def extract_handle(text: str) -> str:
    m = _HANDLE_RE.search(text)
    return m.group(0) if m else ""


def extract_path(text: str) -> str:
    """بيدوّر على مسار ملف مكتوب صراحةً في الجملة (بين علامات اقتباس
    أو شكله مسار). لو ملقاش، الواجهة بتفتح نافذة اختيار — وبرضه ببلاش."""
    q = _QUOTED_RE.search(text)
    if q:
        return q.group(1) or q.group(2)
    p = _PATHY_RE.search(text)
    return p.group(0) if p else ""


def derive_output(source: str, spec: ArgSpec) -> str:
    """بيشتق اسم ملف الخرج من ملف الدخل — من غير ما نسأل المستخدم
    ومن غير ما نستخدم نموذج. `video.mp4` + `_graded` → `video_graded.mp4`"""
    path = pathlib.Path(source)
    ext = spec.ext or path.suffix
    stem = path.stem + spec.suffix
    return str(path.with_name(stem + ext))


def _strip_trigger(text: str, pattern: str) -> str:
    """بيشيل كلمة التشغيل من الجملة عشان الباقي يبقى هو النص الحر."""
    norm = normalize(text)
    m = re.search(pattern, norm)
    if not m:
        return text.strip()
    return norm[m.end():].strip(" :،,.") or text.strip()


# ── ذاكرة القاموس المتعلّمة ─────────────────────────────────────────

def _cache_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent \
        if getattr(sys, "frozen", False) else pathlib.Path(__file__).resolve().parent
    return base / "intent_cache.json"


def load_cache() -> dict[str, str]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def remember(phrase: str, command: str) -> None:
    """بيحفظ ربط صيغة كلام ← أمر، عشان المرة الجاية تتحل ببلاش.

    ده اللي بيخلي الاستهلاك ينزل ناحية الصفر مع الوقت: كل صيغة بتدفع
    نداء واحد بس أول مرة في حياتها.
    """
    key = normalize(phrase)
    if not key or not command:
        return
    with _lock:
        cache = load_cache()
        if cache.get(key) == command:
            return
        cache[key] = command
        try:
            _cache_path().write_text(
                json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass


def forget_all() -> int:
    with _lock:
        n = len(load_cache())
        try:
            _cache_path().write_text("{}", encoding="utf-8")
        except OSError:
            pass
        return n


# ── المطابقة ─────────────────────────────────────────────────────────

def _build_args(rule: IntentRule, text: str, matched_pattern: str
                ) -> tuple[list[str], list[ArgSpec]]:
    args: list[str] = []
    missing: list[ArgSpec] = []
    source_path = ""

    for spec in rule.args:
        if spec.kind == FILE or spec.kind == DIR:
            found = extract_path(text)
            if found:
                args.append(found)
                source_path = source_path or found
            else:
                missing.append(spec)
        elif spec.kind == OUT:
            if source_path:
                args.append(derive_output(source_path, spec))
            else:
                # هيتشتق بعد ما الواجهة تجيب ملف الدخل
                missing.append(spec)
        elif spec.kind == REST:
            rest = _strip_trigger(text, matched_pattern)
            if rest:
                args.append(rest)
            else:
                missing.append(spec)
        elif spec.kind == NUMBER:
            args.append(extract_number(text, spec.default))
        elif spec.kind == HANDLE:
            found = extract_handle(text)
            if found:
                args.append(found)
            else:
                missing.append(spec)
    return args, missing


def resolve(text: str, known_commands: set[str] | None = None) -> IntentMatch | None:
    """بيحاول يترجم كلام حر لأمر حقيقي **محليًا بالكامل**.

    بيرجع None لو مفيش مطابقة — وساعتها بس المخ بيتنادى.
    ترتيب المحاولات: أمر مباشر ← الذاكرة المتعلّمة ← القاموس ←
    اسم أمر مكتوب بمسافات.
    """
    raw = text.strip()
    if not raw:
        return None
    norm = normalize(raw)
    first = raw.split(maxsplit=1)[0].lower()

    # 1) أمر مطابق حرفيًا — أرخص وأسرع مسار
    if known_commands and first in known_commands:
        rest = raw.split(maxsplit=1)
        return IntentMatch(first, rest[1].split() if len(rest) > 1 else [], source="exact")

    # 2) الذاكرة المتعلّمة — صيغة النموذج فهمها قبل كده
    cached = load_cache().get(norm)
    if cached and (not known_commands or cached in known_commands):
        return IntentMatch(cached, source="cache")

    # 3) القاموس المنسّق
    best: tuple[int, IntentRule, str] | None = None
    for rule in RULES:
        if known_commands and rule.command not in known_commands:
            continue
        for pat in rule.patterns:
            if re.search(pat, norm):
                score = rule.priority * 100 + len(pat)
                if best is None or score > best[0]:
                    best = (score, rule, pat)
    if best is not None:
        _, rule, pat = best
        args, missing = _build_args(rule, raw, pat)
        return IntentMatch(rule.command, args, missing, source="dict")

    # 4) اسم أمر مكتوب بمسافات بدل underscore ("virus scan" → virus_scan)
    if known_commands:
        squashed = norm.replace(" ", "_")
        for name in known_commands:
            if squashed == name or squashed.startswith(name + "_"):
                return IntentMatch(name, source="dict")

    return None


def coverage_report(known_commands: set[str]) -> dict:
    """كام أمر من المسجّلين فعلاً عنده تغطية في القاموس — بيتعرض
    للمستخدم في `intents_status` عشان يبقى شايف الحقيقة بالأرقام."""
    covered = {r.command for r in RULES if r.command in known_commands}
    cache_cmds = {c for c in load_cache().values() if c in known_commands}
    return {
        "total": len(known_commands),
        "dictionary": len(covered),
        "learned": len(cache_cmds - covered),
        "uncovered": sorted(known_commands - covered - cache_cmds),
    }
