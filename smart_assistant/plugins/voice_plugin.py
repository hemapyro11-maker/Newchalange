"""
voice_plugin.py — نطق عربي/إنجليزي عبر محركين أساسيين مستقلين: Kokoro
للإنجليزية الأصلية وVoiceTut للصوت المصري، ثم محركات احتياطية.

1. Kokoro 82M — صوت إنجليزي أمريكي/بريطاني محلي طبيعي.
2. VoiceTut-TTS — نموذج مصري محلي يدعم العربية والإنجليزية والمزج
   بينهما، بأصوات استوديو أنثوية واستنساخ اختياري من مرجع مصرح به.
3. Chatterbox Multilingual V3 — محرك عصبي محلي متعدد اللغات واستنساخ.
4. Microsoft Edge TTS (عبر مكتبة `edge-tts` مفتوحة المصدر) — مجاني
   بالكامل من غير API key أو اشتراك، وفيه صوت مصري أنثوي حقيقي
   (ar-EG-SalmaNeural). العيب الوحيد: التوليد نفسه بيحصل على سيرفرات
   مايكروسوفت، يعني محتاج إنترنت وقت الاستخدام — مش نموذج محلي بالكامل.
5. Piper (محرك TTS عصبي محلي، مفتوح المصدر GPL) — صوت عربي واحد بس
   متاح رسميًا (`ar_JO-kareem`، أردني، رجالي) بيتحمّل مرة واحدة
   (~60MB) ويشتغل offline تمامًا بعد كده. مفيش صوت عربي أنثوي في
   مكتبة أصوات Piper الرسمية للأسف — قيد حقيقي في الأدوات المتاحة،
   مش قرار تصميم.
6. espeak-ng (مضمّن محليًا دايمًا، بدون إنترنت خالص) — صوت عربي
   روبوتي (formant synthesis قديم)، لكنه الضمانة الأخيرة اللي هتشتغل
   في كل الحالات.

السلسلة بتجرب بالترتيب ده وتاخد أول واحد يشتغل فعليًا — مش اختيار
عشوائي.

**استماع صوتي (STT) — الاتجاه التاني اللي كان ناقص:** نيزوكو كان
عنده نطق (TTS) بس من غير استماع خالص — نقطة متسجلة في CLAUDE.md نفسه
("Voice Interaction Pipeline"). `listen`/`listen_run` بيسجلوا من
المايك عبر `sounddevice` (مكتبة بايثون خفيفة، مش أداة CLI منفصلة —
من غير تعقيد تحديد اسم جهاز المايك يدويًا زي ما ffmpeg بيحتاج على
ويندوز)، وبعدين بيفرّغوا الصوت لنص عبر سلسلة احتياطية حقيقية من ثلاث
محركات، من الأفضل جودة/أسرع للأضمن توفر:

1. **faster-whisper** (عبر CTranslate2، مش PyTorch) — أدق وأسرع لغاية
   4 أضعاف من openai-whisper الكلاسيكي، وأخف بكتير في الحجم (بالظبط
   نفس السبب اللي خلانا ماندمجش openai-whisper جوه الـ exe نفسه).
   نموذج محلي، بيتحمّل مرة واحدة زي Piper.
2. **whisper CLI** (من حزمة `openai-whisper`) — احتياطي لو faster-whisper
   مش متثبت، بنفس الجودة تقريبًا بس أبطأ وأتقل.
3. **Vosk** — الضمانة الأخيرة: نموذج offline بالكامل وخفيف جدًا (زي
   espeak-ng للنطق)، لكن محتاج تحميل نموذج يدوي (مش أوتوماتيك زي
   الاتنين اللي فوق) من [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models)
   وفكه في `voice_cache/vosk-model/` (أو مسار تحدده بمتغير بيئة
   `NEZUKO_VOSK_MODEL`).

`listen` بس بيرجع النص من غير تنفيذ؛ `listen_run` بينفذ النص كأمر
فعلي فورًا (لو مش أمر مطابق حرفيًا، بيمر على نفس نظام تصحيح الأخطاء
الإملائية والتأكيد بتاع core_engine — نفس الحماية اللي أي نص متكتوب
بييجي منها).

**ملحوظة منصة (اتجرب فعليًا):** على ويندوز/ماك، wheel بتاع
`sounddevice` بيجي ومعاه PortAudio جاهز — من غير خطوة إضافية. على
لينكس، الـ wheel **مبيضمّش** PortAudio (سياسة sounddevice نفسها، مش
حد في نيزوكو) — لازم `apt install libportaudio2` (أو المكافئ في
توزيعتك) قبل `pip install sounddevice`، وإلا `import sounddevice`
بيفشل بـ `OSError: PortAudio library not found`. اتأكد من السلوك ده
تجريبيًا (نفس الخطأ بيحصل حتى من غير PyInstaller خالص)، فمش باگ في
التجميع — بس حد حقيقي يستاهل التوثيق لمين بيشغّل نيزوكو من السورس
على لينكس مباشرة.

**معالجة صوت متقدمة:** `separate_vocals` بيفصل مسار صوتي لعناصره
(صوت/طبول/باص/باقي) عبر Demucs (Meta، أداة خارجية اختيارية، `pip
install demucs`) — مفيد لعزل الصوت من موسيقى خلفية قبل STT، أو
لاستخراج instrumental. زي auto-editor، بيتنادى عن طريق subprocess،
ونموذجه بيتحمّل تلقائيًا مرة واحدة (~80MB) عند أول استخدام.

**تحديد المتكلمين (speaker diarization):** `diarize` بيحدد "مين اتكلم
وإمتى" في تسجيل فيه أكتر من متكلم، عبر pyannote.audio (اختيارية، `pip
install pyannote.audio`). النموذج الافتراضي (pyannote/speaker-diarization-3.1)
"gated" على Hugging Face — يعني محتاج توكن حساب مجاني
(huggingface.co/settings/tokens) **وموافقة يدوية لمرة واحدة بس** على
شروط الاستخدام (ماينفعش تتعمل أوتوماتيك، قرار Hugging Face مش نيزوكو)
قبل أول استخدام. التوكن بيتحفظ بنفس نموذج keyring-مع-fallback بتاع
telegram_plugin.py/youtube_strategy_plugin.py عبر `diarize_set_token`.

**استنساخ الصوت (voice cloning):** `clone_voice` بيستنسخ أي صوت من
عينة صوتية قصيرة (~6 ثواني كفاية) وينطق بيه نص جديد، عبر Coqui
XTTS-v2 (اختيارية، `pip install coqui-tts` — أول تشغيل بيحمّل نموذج تقيل
~2GB). زي pyannote، النموذج ده محتاج موافقة صريحة على الترخيص
(Coqui Public Model License — استخدام غير تجاري بشكل أساسي،
https://coqui.ai/cpml) قبل أول استخدام؛ نيزوكو **مش** بيوافق نيابة
عنك أوتوماتيك — لازم تشغّل `clone_voice_agree_license` بنفسك مرة
واحدة الأول. **مهم:** الاستخدام المقصود هنا هو استنساخ صوتك إنت أو
صوت عندك إذن صريح منه — مش تقليد صوت أي حد من غير موافقته.
محتاج GPU عشان يبقى سريع؛ على CPU بيشتغل بس بطيء جدًا (دقايق للجملة
الواحدة)، عكس فلسفة سلسلة speak (edge-tts/Piper/espeak-ng) اللي
مصممة تكون خفيفة على أي جهاز — ده قيد حقيقي في التكنولوجيا نفسها،
مش قرار تصميم.

الأوامر: speak, voice_status, listen, listen_run, stt_status,
separate_vocals, diarize_set_token, diarize_key_status, diarize,
clone_voice_agree_license, clone_voice
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import inspect
import html
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import unicodedata
import wave
import brain
import media_runtime as mr
import natural_voice_runtime as nvr
import voicetut_runtime as vtr
import english_voice_runtime as evr
from voice_worker_runtime import hidden_process_kwargs

try:
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

try:
    import keyring
    from keyring.errors import KeyringError
    _HAS_KEYRING = True
except ImportError:
    keyring = None
    KeyringError = Exception
    _HAS_KEYRING = False

# ── أصوات لكل لغة ────────────────────────────────────────────────────
# نيزوكو بتتكلم عربي وإنجليزي. قبل كده كل المحركات كانت مربوطة بالعربي
# بالإيد، فأي نص إنجليزي كان بيتقري بصوت عربي — كلام مش مفهوم.
# دلوقتي اللغة بتتحدد من النص نفسه (_detect_lang) وكل محرك بياخد
# الصوت المناسب ليها.

_VOICES = {
    "ar": {
        "edge": "ar-EG-SalmaNeural",          # مصري أنثوي طبيعي
        "espeak": "ar",
        "piper_name": "ar_JO-kareem-medium",
        "piper_base": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium",
        "sherpa_bundle": "vits-piper-ar_JO-kareem-medium",
        "sherpa_model": "ar_JO-kareem-medium.onnx",
        "sherpa_mb": 67,
    },
    "en": {
        "edge": "en-US-AriaNeural",           # أمريكي أنثوي طبيعي
        "espeak": "en-us",
        "piper_name": "en_US-amy-medium",
        "piper_base": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium",
        "sherpa_bundle": "vits-piper-en_US-amy-medium",
        "sherpa_model": "en_US-amy-medium.onnx",
        "sherpa_mb": 64,
    },
}

# نماذج sherpa-onnx الجاهزة. دي **نفس** نماذج Piper الأصلية بترخيص
# MIT، معادة التغليف مع tokens.txt وبيانات espeak-ng اللي المحرك
# محتاجها — مش النسخة الجديدة بترخيص GPL-3.0.
_SHERPA_BASE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
)

# للتوافق مع الكود القديم/الاختبارات اللي بتشاور على الاسم ده
EDGE_VOICE = _VOICES["ar"]["edge"]
PIPER_VOICE_NAME = _VOICES["ar"]["piper_name"]
PIPER_MODEL_URL = _VOICES["ar"]["piper_base"] + ".onnx?download=true"
PIPER_CONFIG_URL = _VOICES["ar"]["piper_base"] + ".onnx.json?download=true.json"

_ARABIC_RANGE = re.compile(r"[\u0600-\u06FF]")
_LATIN_RANGE = re.compile(r"[A-Za-z]")
_VOICE_PROFILES = {
    "natural": {"rate": "+0%", "pitch": "+0Hz", "volume": "+0%", "speed": 1.0, "espeak_rate": 155, "espeak_pitch": 70},
    "warm": {"rate": "-6%", "pitch": "-2Hz", "volume": "+0%", "speed": 0.94, "espeak_rate": 145, "espeak_pitch": 65},
    "clear": {"rate": "-10%", "pitch": "+0Hz", "volume": "+5%", "speed": 0.9, "espeak_rate": 140, "espeak_pitch": 70},
    "fast": {"rate": "+16%", "pitch": "+0Hz", "volume": "+0%", "speed": 1.16, "espeak_rate": 180, "espeak_pitch": 70},
}


def _detect_lang(text: str) -> str:
    """بيحدد لغة النص من الحروف نفسها.

    مش محتاج مكتبة ولا نموذج: بنقارن عدد الحروف العربية واللاتينية مع
    وزن للعربي، عشان اسم ملف إنجليزي طويل جوه أمر عربي ما يقلبش الصوت.
    حرف عربي وحيد جوه فقرة إنجليزية لا يغيّر صوت الفقرة كلها.
    """
    text = text or ""
    arabic = len(_ARABIC_RANGE.findall(text))
    latin = len(_LATIN_RANGE.findall(text))
    # A short Arabic instruction can contain a longer Latin filename.  Weight
    # script counts instead of treating a single Arabic glyph as the language.
    return "ar" if arabic >= 2 and arabic * 2 >= latin else "en"


def _voice_for(lang: str) -> dict:
    return _VOICES.get(lang, _VOICES["en"])


def _profile() -> tuple[str, dict]:
    import brain
    name = str(brain.load_config().get("voice_profile", "natural")).lower()
    if name not in _VOICE_PROFILES:
        name = "natural"
    return name, _VOICE_PROFILES[name]


def _prepare_speech_text(text: str) -> str:
    """Turn formatted assistant output into text that sounds natural aloud."""
    value = unicodedata.normalize("NFKC", html.unescape(text or ""))
    value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[`*_#>|~]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _edge_available() -> bool:
    return (
        shutil.which("edge-tts") is not None
        or "edge_tts" in sys.modules
        or importlib.util.find_spec("edge_tts") is not None
    )

_NETWORK_TIMEOUT = 20
_SYNTH_TIMEOUT = 30
_PLAYBACK_TIMEOUT = 120

WHISPER_MODEL = "base"
_SAMPLE_RATE = 16000
_LISTEN_DEFAULT_SECONDS = 5
_LISTEN_MAX_SECONDS = 30
_TRANSCRIBE_TIMEOUT = 180
_SEPARATE_TIMEOUT = 1800  # فصل صوتي (Demucs) تقيل، ممكن ياخد دقايق كتير على CPU

_DIARIZE_KEYRING_SERVICE = "nezuko-diarize"
_DIARIZE_TOKEN_NAME = "hf_token"
_DIARIZE_MODEL = "pyannote/speaker-diarization-3.1"

_CLONE_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
_CLONE_LANGUAGES = {
    "ar", "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "zh-cn", "ja", "hu", "ko", "hi",
}


def _voice_cache_dir() -> pathlib.Path:
    # نفس منطق _quarantine_dir في security_scan_plugin.py: exe المبني
    # بـ PyInstaller بيفكك __file__ في مجلد مؤقت، فلازم نستخدم مسار
    # الـ exe نفسه في الحالة دي.
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    d = base / "voice_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clone_voice_config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "clone_voice_config.json"


def _clone_license_agreed() -> bool:
    path = _clone_voice_config_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("license_agreed"))


def _diarize_config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "diarize_config.json"


def _hf_token() -> str | None:
    if _HAS_KEYRING:
        try:
            token = keyring.get_password(_DIARIZE_KEYRING_SERVICE, _DIARIZE_TOKEN_NAME)
        except KeyringError:
            token = None
        if token:
            return token
    path = _diarize_config_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = data.get("hf_token")
    return token if token else None


def _set_hf_token_keyring(token: str) -> bool:
    """يحاول يحفظ التوكن في keyring، يرجع True لو نجح، وبيمسح أي نسخة
    نص عادي قديمة كانت متسجلة لو نجح الحفظ الآمن. نفس نموذج
    youtube_strategy_plugin.py._set_api_key_keyring."""
    if not _HAS_KEYRING:
        return False
    try:
        keyring.set_password(_DIARIZE_KEYRING_SERVICE, _DIARIZE_TOKEN_NAME, token)
    except KeyringError:
        return False
    path = _diarize_config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if data and data.get("hf_token"):
            data["hf_token"] = None
            try:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
    return True


def _download(url: str, dest: pathlib.Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=_NETWORK_TIMEOUT) as resp, dest.open("wb") as f:
            shutil.copyfileobj(resp, f)
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        dest.unlink(missing_ok=True)
        return False


def _ensure_piper_voice(lang: str = "ar") -> tuple[pathlib.Path, pathlib.Path] | None:
    """بينزّل صوت Piper الخاص باللغة دي مرة واحدة ويخزّنه.

    كل لغة ليها نموذجها — نموذج عربي مينفعش ينطق إنجليزي والعكس.
    """
    voice = _voice_for(lang)
    d = _voice_cache_dir()
    name = voice["piper_name"]
    model = d / f"{name}.onnx"
    config = d / f"{name}.onnx.json"
    if model.is_file() and config.is_file():
        return model, config
    if not _download(voice["piper_base"] + ".onnx?download=true", model):
        return None
    if not _download(voice["piper_base"] + ".onnx.json?download=true.json", config):
        model.unlink(missing_ok=True)
        return None
    return model, config


def _synthesize_edge(text: str, out_path: pathlib.Path, lang: str = "ar") -> bool:
    executable = shutil.which("edge-tts")
    try:
        _name, profile = _profile()
        if executable:
            proc = subprocess.run(
                ["edge-tts", "-t", text, "-v", _voice_for(lang)["edge"],
                 f"--rate={profile['rate']}", f"--pitch={profile['pitch']}",
                 f"--volume={profile['volume']}",
                 "--write-media", str(out_path)],
                capture_output=True, text=True,
                timeout=max(_SYNTH_TIMEOUT, min(180, 20 + len(text) // 12)),
                **hidden_process_kwargs(),
            )
            return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0

        # Target-directory and embedded installs can expose the Python package
        # without installing the edge-tts console launcher into PATH.
        if not _edge_available():
            return False
        import edge_tts
        speech = edge_tts.Communicate(
            text, _voice_for(lang)["edge"], rate=profile["rate"],
            volume=profile["volume"], pitch=profile["pitch"],
        )
        asyncio.run(speech.save(str(out_path)))
    except (ImportError, OSError, RuntimeError, subprocess.TimeoutExpired):
        return False
    return out_path.is_file() and out_path.stat().st_size > 0


def _synthesize_piper(text: str, out_path: pathlib.Path, lang: str = "ar") -> bool:
    if not shutil.which("piper"):
        return False
    voice = _ensure_piper_voice(lang)
    if voice is None:
        return False
    model, config = voice
    try:
        proc = subprocess.run(
            ["piper", "-m", str(model), "-c", str(config), "-f", str(out_path)],
            input=text, capture_output=True, text=True, timeout=_SYNTH_TIMEOUT,
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


# ── sherpa-onnx: محرك نطق محلي مصان ─────────────────────────────────
# ليه ده موجود: Piper الأصلي (رخصة MIT) اتأرشف read-only في أكتوبر
# 2025، والتطوير انتقل لـ OHF-Voice/piper1-gpl بترخيص GPL-3.0. يعني
# إحنا واقفين على مكتبة مش هتتصلح تاني.
#
# sherpa-onnx (Apache-2.0، من k2-fsa) بيشغّل **نفس نماذج Piper الأصلية**
# من غير ما نحتاج برنامج piper نفسه — فبنكسب محرك مصان ونفضل على
# النماذج بترخيصها المتساهل. وكمان بيشتغل كمكتبة بايثون مباشرة بدل
# subprocess، فأسرع وأنضف.

_sherpa_cache: dict[str, object] = {}


def _safe_extract(archive: pathlib.Path, dest: pathlib.Path) -> bool:
    """بيفك أرشيف متحمّل من الإنترنت جوه `dest` **بس**.

    أرشيف خبيث ممكن يكون فيه مسار زي `../../etc/passwd` أو رابط رمزي
    بيطلع بره المجلد. بنتحقق من كل مُدخل قبل الفك بدل ما نثق في
    الملف — `tarfile.extractall` من غير فحص كانت ثغرة معروفة.
    """
    root = dest.resolve()
    try:
        with tarfile.open(archive, "r:bz2") as tar:
            for member in tar.getmembers():
                target = (root / member.name).resolve()
                if not target.is_relative_to(root):
                    return False
                if member.issym() or member.islnk():
                    return False
            tar.extractall(dest, filter="data")
    except (tarfile.TarError, OSError, ValueError):
        return False
    return True


def _ensure_sherpa_voice(lang: str = "ar") -> pathlib.Path | None:
    """بينزّل حزمة صوت sherpa مرة واحدة ويفكها. بيرجع مجلدها أو None."""
    voice = _voice_for(lang)
    bundle = voice.get("sherpa_bundle")
    if not bundle:
        return None
    out_dir = _voice_cache_dir() / bundle
    if (out_dir / voice["sherpa_model"]).is_file() and (out_dir / "tokens.txt").is_file():
        return out_dir

    archive = _voice_cache_dir() / f"{bundle}.tar.bz2"
    if not _download(f"{_SHERPA_BASE}{bundle}.tar.bz2", archive):
        return None
    ok = _safe_extract(archive, _voice_cache_dir())
    archive.unlink(missing_ok=True)
    if not ok or not (out_dir / voice["sherpa_model"]).is_file():
        return None
    return out_dir


def _load_sherpa(lang: str = "ar"):
    """بيبني محرك النطق مرة واحدة لكل لغة (بناؤه تقيل، نطقه رخيص)."""
    if lang in _sherpa_cache:
        return _sherpa_cache[lang]
    try:
        import sherpa_onnx
    except ImportError:
        return None
    voice_dir = _ensure_sherpa_voice(lang)
    if voice_dir is None:
        return None
    try:
        tts = sherpa_onnx.OfflineTts(
            sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(voice_dir / _voice_for(lang)["sherpa_model"]),
                        tokens=str(voice_dir / "tokens.txt"),
                        data_dir=str(voice_dir / "espeak-ng-data"),
                    ),
                    num_threads=1,
                )
            )
        )
    except Exception:  # noqa: BLE001 - أي فشل = المحرك ده مش متاح، نكمّل للي بعده
        return None
    _sherpa_cache[lang] = tts
    return tts


def _synthesize_sherpa(text: str, out_path: pathlib.Path, lang: str = "ar") -> bool:
    tts = _load_sherpa(lang)
    if tts is None:
        return False
    try:
        import numpy as np

        _name, profile = _profile()
        audio = tts.generate(text, sid=0, speed=profile["speed"])
        if not len(audio.samples):
            return False
        pcm = (np.array(audio.samples, dtype=np.float32) * 32767).astype(np.int16)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(audio.sample_rate)
            wf.writeframes(pcm.tobytes())
    except Exception:  # noqa: BLE001
        return False
    return out_path.is_file() and out_path.stat().st_size > 0


def sherpa_available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def _synthesize_espeak(text: str, out_path: pathlib.Path, lang: str = "ar") -> bool:
    if not shutil.which("espeak-ng"):
        return False
    try:
        _name, profile = _profile()
        proc = subprocess.run(
            ["espeak-ng", "-v", _voice_for(lang)["espeak"], "-s", str(profile["espeak_rate"]),
             "-p", str(profile["espeak_pitch"]), "-w", str(out_path), text],
            capture_output=True, text=True, timeout=_SYNTH_TIMEOUT,
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


def _natural_reference() -> pathlib.Path | None:
    import brain
    value = str(brain.load_config().get("natural_voice_reference", "")).strip()
    path = pathlib.Path(value).expanduser() if value else None
    return path.resolve() if path and path.is_file() else None


def _synthesize_natural(text: str, out_path: pathlib.Path, lang: str = "ar") -> bool:
    if not nvr.available():
        return False
    ok, _detail = nvr.render(text, lang, out_path, _natural_reference())
    return ok


def _synthesize_human(text: str, out_path: pathlib.Path, lang: str = "ar") -> bool:
    if not vtr.available():
        return False
    # The default assistant voice must use VoiceTut's clean studio reference.
    # `natural_voice_reference` may belong to Chatterbox (and may itself be
    # synthetic), so never leak it into this engine.  Explicit cloning remains
    # available through the `human_voice ... reference.wav` command.
    ok, _detail = vtr.render(text, lang, out_path)
    return ok


def _synthesize_english_native(text: str, out_path: pathlib.Path, lang: str = "en") -> bool:
    """Use Kokoro only for English so Arabic keeps its Egyptian identity."""
    if lang != "en" or not evr.available():
        return False
    ok, _detail = evr.render(text, out_path)
    return ok


# الترتيب بيمثّل أولوية الجودة الحقيقية: الإنجليزي الأصلي أولاً لما
# اللغة إنجليزي، ثم الصوت المصري للعربي، ثم المحركات الاحتياطية.
# بنخزّن **أسماء** الدوال مش الدوال نفسها، وبنجيبها وقت النداء.
# لو خزّنّا المرجع نفسه هنا، القايمة بتتجمّد على النسخة الموجودة وقت
# الاستيراد — فمينفعش تستبدل محرك (لا في اختبار ولا في تخصيص).
# العنصر الرابع هو مفتاح اسم الصوت في `_VOICES` — بيخلي إضافة محرك
# جديد تعديل في مكان واحد بدل اتنين.
_BACKENDS = [
    ("Kokoro native English", "_synthesize_english_native", ".wav", "edge"),
    ("VoiceTut Egyptian", "_synthesize_human", ".wav", "edge"),
    ("Chatterbox Multilingual V3", "_synthesize_natural", ".wav", "edge"),
    ("edge-tts", "_synthesize_edge", ".mp3", "edge"),
    ("sherpa-onnx", "_synthesize_sherpa", ".wav", "piper_name"),
    ("Piper", "_synthesize_piper", ".wav", "piper_name"),
    ("espeak-ng", "_synthesize_espeak", ".wav", "espeak"),
]


def _synthesize_with_fallback(text: str, tmp_dir: pathlib.Path,
                              lang: str | None = None) -> tuple[pathlib.Path, str] | None:
    lang = lang or _detect_lang(text)
    voice = _voice_for(lang)
    cfg = brain.load_config()
    local_only = bool(cfg.get("local_only"))
    backends = list(_BACKENDS)
    # VoiceTut sounds like a studio model but diffusion inference is slow on CPU.
    # Conversation mode prefers Microsoft's Egyptian neural voice and retains
    # VoiceTut as the high-quality offline fallback. English remains local Kokoro.
    if lang == "ar" and not local_only and cfg.get("voice_latency_mode", "instant") == "instant":
        edge = next(item for item in backends if item[1] == "_synthesize_edge")
        backends.remove(edge)
        backends.insert(0, edge)
    for label, fn_name, ext, voice_key in backends:
        if local_only and "edge" in fn_name:
            continue
        synth_fn = globals()[fn_name]
        out_path = tmp_dir / f"speech{ext}"
        if synth_fn(text, out_path, lang):
            if fn_name == "_synthesize_human":
                voice_name = vtr._settings()[2]
            elif fn_name == "_synthesize_english_native":
                voice_name = evr._settings()[1]
            else:
                voice_name = voice.get(voice_key, lang)
            return out_path, f"{label} ({voice_name})"
    return None


def _play_windows_wav(path: pathlib.Path) -> bool:
    """Play PCM WAV without spawning ffplay or depending on `winsound`."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        winmm = ctypes.WinDLL("winmm")
        play = winmm.PlaySoundW
        play.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint]
        play.restype = ctypes.c_bool
        # SND_SYNC | SND_NODEFAULT | SND_FILENAME
        return bool(play(str(path), None, 0x0000 | 0x0002 | 0x00020000))
    except (AttributeError, OSError):
        return False


def _cmd_speak(ctx) -> str:
    parts = ctx.raw.split(maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return "usage: speak <text>   [lang=ar|en]"

    text = _prepare_speech_text(text)
    if not text:
        return "❌ there is no speakable text after removing formatting"

    # lang=xx صريحة بتتقدّم على الاكتشاف التلقائي — مفيدة للنصوص
    # المختلطة اللي الاكتشاف ممكن يقراها غلط
    lang = None
    for token in ("lang=ar", "lang=en"):
        if text.endswith(token):
            lang = token.split("=")[1]
            text = text[: -len(token)].strip()
            break
    if not text:
        return "usage: speak <text>   [lang=ar|en]"

    with tempfile.TemporaryDirectory(prefix="nezuko_speech_") as tmp:
        result = _synthesize_with_fallback(text, pathlib.Path(tmp), lang)
        if result is None:
            return (
                "❌ every speech engine failed — check Kokoro/VoiceTut setup, internet for edge-tts, "
                "and sherpa/Piper/espeak-ng local fallbacks with voice_status."
            )
        audio_path, backend_label = result

        try:
            if os.name == "nt" and audio_path.suffix.lower() == ".wav" and _play_windows_wav(audio_path):
                play_proc = type("Result", (), {"returncode": 0})()
            elif shutil.which("ffplay"):
                play_proc = subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)],
                    capture_output=True, text=True, timeout=_PLAYBACK_TIMEOUT,
                    **hidden_process_kwargs(),
                )
            else:
                return f"✅ audio generated with {backend_label} — but ffplay (or a native WAV player) is not available"
        except subprocess.TimeoutExpired:
            return f"⚠️ audio generated with {backend_label} but playback took too long"

        if play_proc.returncode != 0:
            return f"⚠️ audio generated with {backend_label} but ffplay could not play it (exit {play_proc.returncode})"

    return f"🔊 spoken with {backend_label}"


def _cmd_voice_profile(ctx) -> str:
    import brain
    cfg = brain.load_config()
    if not ctx.args:
        return (f"Voice profile: {cfg.get('voice_profile', 'natural')}\n"
                "usage: voice_profile natural|warm|clear|fast")
    name = ctx.args[0].lower()
    if name not in _VOICE_PROFILES:
        return "usage: voice_profile natural|warm|clear|fast"
    cfg["voice_profile"] = name
    brain.save_config(cfg)
    return f"✅ voice profile set to {name} for Arabic and English"


def _cmd_voice_reference(ctx) -> str:
    import brain
    cfg = brain.load_config()
    if not ctx.args:
        current = cfg.get("natural_voice_reference") or "none"
        return f"Natural voice reference: {current}\nusage: voice_reference <authorized-audio.wav|clear>"
    if len(ctx.args) != 1:
        return "usage: voice_reference <authorized-audio.wav|clear>"
    if ctx.args[0].lower() == "clear":
        cfg.pop("natural_voice_reference", None)
        brain.save_config(cfg)
        return "✅ natural voice reference cleared"
    path = pathlib.Path(ctx.args[0]).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg"}:
        return "❌ choose an existing WAV, MP3, FLAC, or OGG file"
    cfg["natural_voice_reference"] = str(path)
    brain.save_config(cfg)
    return "✅ natural voice reference saved; only use audio you are authorized to clone"


def _cmd_voice_status(ctx) -> str:
    profile_name, _profile_cfg = _profile()
    lines = [f"🔊 Speech engines, in the order they are tried (profile: {profile_name}):"]

    english_ok = evr.available()
    _english_runtime, english_voice, english_speed = evr._settings()
    lines.append(
        f"  {'✅' if english_ok else '❌'} Kokoro native English (local, US/UK female voices)"
        + (f" — voice: {english_voice}, speed: {english_speed:.2f}" if english_ok else
           " — run english_voice_setup <python.exe>")
    )

    human_ok = vtr.available()
    _runtime, _model, human_speaker, human_steps = vtr._settings()
    lines.append(
        f"  {'✅' if human_ok else '❌'} VoiceTut Egyptian (human-trained, Arabic/English, isolated)"
        + (f" — speaker: {human_speaker}, quality steps: {human_steps}" if human_ok else
           " — run human_voice_setup <python.exe> <model-directory>")
    )

    natural_ok = nvr.available()
    reference = _natural_reference()
    lines.append(
        f"  {'✅' if natural_ok else '❌'} Chatterbox Multilingual V3 (natural Arabic/English, isolated)"
        + (f" — reference: {reference}" if natural_ok and reference else
           " — ready; optional voice_reference can set an authorized voice" if natural_ok else
           " — set NEZUKO_NATURAL_VOICE_PYTHON")
    )

    edge_ok = _edge_available()
    lines.append(
        f"  {'✅' if edge_ok else '❌'} edge-tts"
        + (f" — voice: {EDGE_VOICE} (needs internet at speak time)"
           if edge_ok else " — pip install edge-tts")
    )

    sherpa_ok = sherpa_available()
    cached = [
        lang for lang, v in _VOICES.items()
        if (_voice_cache_dir() / v["sherpa_bundle"] / v["sherpa_model"]).is_file()
    ]
    if not sherpa_ok:
        sherpa_note = " — pip install sherpa-onnx"
    elif cached:
        sherpa_note = f" — voices ready offline: {', '.join(sorted(cached))}"
    else:
        sherpa_note = " — downloads ~65MB per language on first use, once"
    lines.append(
        f"  {'✅' if sherpa_ok else '❌'} sherpa-onnx (maintained, Apache-2.0, fully offline){sherpa_note}"
    )

    piper_ok = shutil.which("piper") is not None
    voice_cached = (_voice_cache_dir() / f"{PIPER_VOICE_NAME}.onnx").is_file()
    if piper_ok:
        piper_note = (" — voice cached offline" if voice_cached
                      else " — downloads ~60MB on first use, once")
    else:
        piper_note = " — optional; sherpa-onnx above runs the same voices"
    lines.append(
        f"  {'⚠️' if piper_ok else '⬜'} Piper binary ({PIPER_VOICE_NAME}){piper_note}"
    )

    espeak_ok = shutil.which("espeak-ng") is not None
    lines.append(
        f"  {'✅' if espeak_ok else '❌'} espeak-ng (last resort, robotic but always works)"
        + ("" if espeak_ok else " — apt install espeak-ng (or espeak-ng.github.io)")
    )

    ffplay_ok = shutil.which("ffplay") is not None
    lines.append(
        f"  {'✅' if ffplay_ok else '❌'} ffplay to play the audio (part of FFmpeg)"
    )

    if not (english_ok or human_ok or natural_ok or edge_ok or sherpa_ok or piper_ok or espeak_ok):
        lines.append("\n⚠️ No speech engine installed — `speak` will not work at all.")
    elif piper_ok:
        lines.append(
            "\n⚠️ The original Piper repo (MIT) was archived in Oct 2025 and its\n"
            "   successor is GPL-3.0. sherpa-onnx runs the same MIT voices and is\n"
            "   still maintained — it is tried first, so Piper here is just a fallback."
        )

    return "\n".join(lines)


# ── استماع صوتي (STT): sounddevice للتسجيل + whisper CLI للتفريغ ────────

def _record_audio(seconds: int, out_path: pathlib.Path) -> str | None:
    """يسجل من المايك الافتراضي، يرجع None لو نجح أو رسالة خطأ لو فشل."""
    if sd is None:
        return "sounddevice is not installed — pip install sounddevice"
    try:
        audio = sd.rec(int(seconds * _SAMPLE_RATE), samplerate=_SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
    except Exception as e:
        return f"could not record from the microphone: {e}"
    try:
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 بايت
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
    except OSError as e:
        return f"could not save the recording: {e}"
    return None


# ── كشف نشاط الصوت (VAD) — يوقف التسجيل لما تسكت ────────────────────
# المشكلة اللي بيحلها: `sd.rec(seconds)` بتسجّل مدة ثابتة مهما حصل.
# لو خلصت كلامك في ثانيتين بتستنى الباقي بالعافية، ولو محتاج تمن ثواني
# بتتقطع في نص الجملة. VAD بتخلي التسجيل يقف لوحده لما تسكت.
#
# silero-vad: نموذج 2 ميجا، رخصة MIT، أقل من 1ms للشريحة على معالج
# عادي، ومدرّب على أكتر من 6000 لغة — فبيشتغل على العربي والإنجليزي
# من غير أي تظبيط. اختياري بالكامل: لو مش متثبت، بنرجع للمدة الثابتة.

_VAD_CHUNK = 512               # عينات لكل شريحة (المقاس اللي silero بيتوقعه)
_VAD_SPEECH_PROB = 0.5         # فوق كده = فيه كلام
_VAD_SILENCE_MS = 800          # سكوت بالمدة دي = خلصت كلام
_VAD_MIN_SPEECH_MS = 300       # أقل من كده = ضوضاء مش كلام
_VAD_PRE_ROLL_MS = 300         # بنحتفظ باللي قبل أول كلمة عشان متتقصّش

_vad_model = None


def _load_vad():
    """بيحمّل نموذج silero مرة واحدة. بيرجع None لو مش متثبت.

    بنستخدم حزمة `silero-vad` من PyPI مش `torch.hub.load` — الحزمة
    جايبة ملف النموذج جوّاها، فمفيش أي تنزيل من الشبكة ولا وقت انتظار
    أول مرة، ولا فحص الحالة بيلمس النت.
    """
    global _vad_model
    if _vad_model is not None:
        return _vad_model
    try:
        from silero_vad import load_silero_vad
    except ImportError:
        return None
    try:
        _vad_model = load_silero_vad()
    except Exception:  # noqa: BLE001 - أي فشل = مفيش VAD، نرجع للمدة الثابتة
        return None
    return _vad_model


def vad_available() -> bool:
    return _load_vad() is not None


def _vad_prob(model, mono) -> float:
    """احتمال إن الشريحة دي فيها كلام (0..1).

    متفصولة في دالة لوحدها عشان الاختبارات تقدر تستبدلها من غير ما
    torch يكون متثبت أصلاً على الجهاز اللي بيشغّل الاختبارات.
    """
    import numpy as np
    import torch

    tensor = torch.from_numpy(mono.astype(np.float32) / 32768.0)
    return float(model(tensor, _SAMPLE_RATE).item())


def _record_until_silence(out_path: pathlib.Path, max_seconds: int
                          ) -> tuple[str | None, bool]:
    """بيسجّل لحد ما تسكت. بيرجع (رسالة خطأ أو None، هل VAD اتستخدم).

    لو silero مش متثبت بيرجع (None, False) من غير ما يسجّل، والنداء
    اللي فوق بيرجع للمدة الثابتة.
    """
    if sd is None:
        return "sounddevice is not installed — pip install sounddevice", False
    model = _load_vad()
    if model is None:
        return None, False

    kept: list = []
    pre_roll: list = []
    pre_roll_max = max(1, (_VAD_PRE_ROLL_MS * _SAMPLE_RATE) // (1000 * _VAD_CHUNK))
    speech_chunks = 0
    silence_chunks = 0
    started = False
    silence_limit = max(1, (_VAD_SILENCE_MS * _SAMPLE_RATE) // (1000 * _VAD_CHUNK))
    min_speech = max(1, (_VAD_MIN_SPEECH_MS * _SAMPLE_RATE) // (1000 * _VAD_CHUNK))
    max_chunks = (max_seconds * _SAMPLE_RATE) // _VAD_CHUNK

    try:
        with sd.InputStream(samplerate=_SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=_VAD_CHUNK) as stream:
            for _ in range(int(max_chunks)):
                block, _overflow = stream.read(_VAD_CHUNK)
                mono = block[:, 0]
                prob = _vad_prob(model, mono)

                if prob >= _VAD_SPEECH_PROB:
                    if not started:
                        # نضم اللي قبل أول كلمة عشان مبدأ الجملة ميتقصّش
                        kept.extend(pre_roll)
                        started = True
                    kept.append(mono.copy())
                    speech_chunks += 1
                    silence_chunks = 0
                elif started:
                    kept.append(mono.copy())
                    silence_chunks += 1
                    if silence_chunks >= silence_limit and speech_chunks >= min_speech:
                        break
                else:
                    pre_roll.append(mono.copy())
                    if len(pre_roll) > pre_roll_max:
                        pre_roll.pop(0)
    except Exception as e:  # noqa: BLE001
        return f"could not record from the microphone: {e}", True

    if speech_chunks < min_speech:
        return "did not hear clear speech — try again, closer to the mic", True

    try:
        import numpy as np
        audio = np.concatenate(kept)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
    except (OSError, ValueError) as e:
        return f"could not save the recording: {e}", True
    return None, True


_faster_whisper_models: dict[str, object] = {}


def _transcribe_faster_whisper(wav_path: pathlib.Path, model_size: str,
                               language: str | None = None) -> tuple[str | None, bool]:
    """يرجع (النص أو None، هل المحرك متاح أصلاً). لو متاح لكن مسمعش
    كلام واضح، بيرجع (None, True)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None, False
    try:
        model = _faster_whisper_models.get(model_size)
        if model is None:
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            _faster_whisper_models[model_size] = model
        try:
            segments, _info = model.transcribe(
                str(wav_path), language=language, beam_size=5,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
            )
        except TypeError:
            segments, _info = model.transcribe(str(wav_path))
        text = " ".join(seg.text for seg in segments).strip()
    except Exception:
        return None, True
    return (text or None), True


def _transcribe_whisper_cli(wav_path: pathlib.Path, model: str,
                            language: str | None = None) -> tuple[str | None, bool]:
    if not shutil.which("whisper"):
        return None, False
    with tempfile.TemporaryDirectory(prefix="nezuko_stt_") as tmp:
        cmd = [
            "whisper", str(wav_path), "--model", model,
            "--output_format", "txt", "--output_dir", tmp, "--fp16", "False",
        ]
        if language:
            cmd += ["--language", language]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TRANSCRIBE_TIMEOUT,
                                  **hidden_process_kwargs())
        except subprocess.TimeoutExpired:
            return None, True
        if proc.returncode != 0:
            return None, True
        txt_path = pathlib.Path(tmp) / f"{wav_path.stem}.txt"
        if not txt_path.is_file():
            return None, True
        text = txt_path.read_text(encoding="utf-8").strip()
    return (text or None), True


def _vosk_model_dir() -> pathlib.Path:
    override = os.environ.get("NEZUKO_VOSK_MODEL")
    if override:
        return pathlib.Path(override)
    return _voice_cache_dir() / "vosk-model"


def _transcribe_vosk(wav_path: pathlib.Path) -> tuple[str | None, bool]:
    model_dir = _vosk_model_dir()
    if not model_dir.is_dir():
        return None, False
    try:
        import vosk
    except ImportError:
        return None, False
    try:
        vosk.SetLogLevel(-1)
        model = vosk.Model(str(model_dir))
        with wave.open(str(wav_path), "rb") as wf:
            rec = vosk.KaldiRecognizer(model, wf.getframerate())
            parts = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    chunk = json.loads(rec.Result()).get("text", "")
                    if chunk:
                        parts.append(chunk)
            final = json.loads(rec.FinalResult()).get("text", "")
            if final:
                parts.append(final)
        text = " ".join(parts).strip()
    except Exception:
        return None, True
    return (text or None), True


_STT_MISSING_MSG = (
    "❌ No speech-to-text engine installed — install at least one:\n"
    "   pip install faster-whisper   (best — most accurate, lightest, fastest)\n"
    "   pip install openai-whisper\n"
    "   or download a small Vosk model: https://alphacephei.com/vosk/models\n"
    "     and unpack it into voice_cache/vosk-model/ (or set NEZUKO_VOSK_MODEL)"
)


def _transcribe(wav_path: pathlib.Path, model: str = WHISPER_MODEL,
                language: str | None = None) -> tuple[str | None, str | None]:
    """يرجع (النص، None) لو نجح، أو (None، رسالة خطأ) لو كل المحركات
    فشلت أو مفيش ولا واحد متثبت. بيجرب faster-whisper الأول (أدق
    وأخف)، بعدين whisper CLI، وأخيرًا Vosk (لو نموذجه متحمّل يدويًا)."""
    def _with_optional_language(fn):
        """Keep third-party/test STT backends that implement the old API working."""
        try:
            accepts_language = len(inspect.signature(fn).parameters) >= 3
        except (TypeError, ValueError):
            accepts_language = True
        return fn(wav_path, model, language) if accepts_language else fn(wav_path, model)

    any_available = False
    for backend_fn in (
        lambda: _with_optional_language(_transcribe_faster_whisper),
        lambda: _with_optional_language(_transcribe_whisper_cli),
        lambda: _transcribe_vosk(wav_path),
    ):
        text, available = backend_fn()
        any_available = any_available or available
        if text:
            return text, None
    if not any_available:
        return None, _STT_MISSING_MSG
    return None, "🔇 did not hear any clear speech"


# ═══════════════════════════════════════════════════════════════════
# فصل مسارات صوتية (Demucs) — أداة خارجية اختيارية
# ═══════════════════════════════════════════════════════════════════

def _cmd_separate_vocals(ctx) -> str:
    if len(ctx.args) < 2:
        return (
            "usage: separate_vocals <audio> <output_dir> [mode=all|vocals] — "
            "split audio into stems (Demucs): all=4 stems, vocals=voice/no-voice only (faster)"
        )
    if not shutil.which("demucs"):
        return "❌ demucs is not installed — pip install demucs (free and open source; first run downloads a ~80MB model)"
    src, out_dir = ctx.args[0], ctx.args[1]
    if not pathlib.Path(src).is_file():
        return f"❌ file not found: {src}"
    mode = ctx.args[2] if len(ctx.args) > 2 else "all"
    if mode not in ("all", "vocals"):
        return "❌ mode must be all or vocals"

    cmd = ["demucs", "-o", out_dir]
    if mode == "vocals":
        cmd += ["--two-stems", "vocals"]
    cmd.append(src)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_SEPARATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"⏱ timed out after {_SEPARATE_TIMEOUT}s — stem separation is slow on CPU; try a shorter file or a machine with a GPU"
    if proc.returncode != 0:
        return f"❌ failed: {proc.stderr.strip()[-600:]}"
    if not any(pathlib.Path(out_dir).rglob("*.wav")):
        return "❌ separation failed — demucs exited without an error but produced no real audio files"
    stems = "vocals + no_vocals" if mode == "vocals" else "vocals + drums + bass + other"
    return f"✅ audio split into {stems} at {out_dir}"


# ═══════════════════════════════════════════════════════════════════
# تحديد المتكلمين (speaker diarization عبر pyannote.audio) — أداة
# خارجية اختيارية، محتاجة توكن Hugging Face (نموذج gated)
# ═══════════════════════════════════════════════════════════════════

_diarize_pipeline_cache: dict[str, object] = {}


def _cmd_diarize_set_token(ctx) -> str:
    if not ctx.args:
        return "usage: diarize_set_token <hf_token>"
    token = ctx.args[0].strip()
    if not token:
        return "❌ an empty token will not be saved"
    if _set_hf_token_keyring(token):
        return (
            "✅ Hugging Face token saved safely in the operating system secret store (keyring).\n"
            "If this is your first time you must also accept the model terms by hand, once — see diarize_key_status."
        )
    path = _diarize_config_path()
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["hf_token"] = token
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        return f"❌ could not save the token: {e}"
    return (
        "⚠️ Token saved as plain text in diarize_config.json — secure keyring storage is not available here.\n"
        "   For safer storage: pip install keyring\n"
        "If this is your first time you must also accept the model terms by hand, once — see diarize_key_status."
    )


def _cmd_diarize_key_status(ctx) -> str:
    token = _hf_token()
    if not token:
        return (
            "❌ no Hugging Face token configured — use diarize_set_token <token>\n"
            "Get one free at: https://huggingface.co/settings/tokens\n"
            "You must also accept these two models terms by hand — once, and it cannot be automated:\n"
            f"  - https://huggingface.co/{_DIARIZE_MODEL}\n"
            "  - https://huggingface.co/pyannote/segmentation-3.0"
        )
    masked = token[:4] + "…" + token[-2:] if len(token) > 8 else "…"
    line = f"✅ a token is configured ({masked})"
    if not _HAS_KEYRING:
        line += "\n⚠️ keyring is not installed — stored as plain text (pip install keyring for safer storage)"
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        line += "\n❌ pyannote.audio is not installed — pip install pyannote.audio"
    return line


def _cmd_diarize(ctx) -> str:
    if not ctx.args:
        return "usage: diarize <audio> — work out who spoke when in a multi-speaker recording (pyannote.audio)"
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        return "❌ pyannote.audio is not installed — pip install pyannote.audio (free and open source)"
    src = ctx.args[0]
    if not pathlib.Path(src).is_file():
        return f"❌ file not found: {src}"
    token = _hf_token()
    if not token:
        return "❌ a Hugging Face token is needed first — use diarize_set_token <token> (details: diarize_key_status)"

    pipeline = _diarize_pipeline_cache.get(_DIARIZE_MODEL)
    if pipeline is None:
        try:
            pipeline = Pipeline.from_pretrained(_DIARIZE_MODEL, token=token)
        except Exception as e:
            return f"❌ could not load the pyannote model: {e}"
        if pipeline is None:
            return (
                "❌ could not load the model — you must accept the terms by hand first at:\n"
                f"  https://huggingface.co/{_DIARIZE_MODEL}\n"
                "  https://huggingface.co/pyannote/segmentation-3.0"
            )
        _diarize_pipeline_cache[_DIARIZE_MODEL] = pipeline

    try:
        diarization = pipeline(src)
    except Exception as e:
        return f"❌ analysis failed: {e}"

    segments = list(diarization.itertracks(yield_label=True))
    if not segments:
        return "ℹ️ no distinct speakers were found in this recording"
    speakers = {speaker for _turn, _track, speaker in segments}
    lines = [f"🗣️ {len(speakers)} speakers found:"]
    for turn, _track, speaker in segments:
        lines.append(f"  [{turn.start:6.1f}s → {turn.end:6.1f}s] {speaker}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# استنساخ الصوت (Coqui XTTS-v2) — أداة خارجية اختيارية، محتاجة موافقة
# صريحة على الترخيص قبل أول استخدام (ماينفعش نيزوكو يوافق نيابة عنك)
# ═══════════════════════════════════════════════════════════════════

_clone_voice_models: dict[str, object] = {}


def _reference_duration(path: pathlib.Path) -> float | None:
    """Read WAV duration locally; other formats are inspected when ffprobe exists."""
    try:
        with wave.open(str(path), "rb") as stream:
            return stream.getnframes() / max(1, stream.getframerate())
    except (OSError, wave.Error, EOFError):
        data = mr.probe(path)
        try:
            return float(data["format"]["duration"]) if data else None
        except (KeyError, TypeError, ValueError):
            return None


def _polish_cloned_wav(path: pathlib.Path) -> bool:
    """Apply a consistent speech master while keeping a valid original on failure."""
    try:
        if path.read_bytes()[:4] != b"RIFF" or mr.binary("ffmpeg") is None:
            return False
    except OSError:
        return False
    polished = path.with_name(f".{path.stem}.polished.wav")
    try:
        result = mr.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
            "-af", "highpass=f=55,lowpass=f=11000,loudnorm=I=-18:TP=-2:LRA=7",
            "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(polished),
        ], 600)
        if result.returncode == 0 and mr.valid_output(polished, minimum_bytes=44):
            os.replace(polished, path)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        polished.unlink(missing_ok=True)
    return False


def _cmd_clone_voice_agree_license(ctx) -> str:
    path = _clone_voice_config_path()
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["license_agreed"] = True
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        return f"❌ could not record your acceptance: {e}"
    return (
        "✅ Your acceptance of the Coqui Public Model License (CPML) for XTTS-v2 is recorded.\n"
        "Full text: https://coqui.ai/cpml — in short: primarily non-commercial\n"
        "use. Nezuko will not accept a licence on your behalf when it governs your own\n"
        "use, so this command must be run explicitly, once, before clone_voice.\n"
        "Try it now: clone_voice <reference.wav> \"<text>\" <output.wav> [language=ar]"
    )


def _cmd_clone_voice(ctx) -> str:
    if len(ctx.args) < 3:
        return (
            "usage: clone_voice <reference.wav> <text> <output.wav> [language=ar] — "
            "clone a voice from a short sample (~6+ seconds) and speak any text in it (Coqui XTTS-v2)\n"
            "⚠️ Use this for your own voice, or one you have explicit permission to clone — not to imitate someone without their consent."
        )
    if not _clone_license_agreed():
        return (
            "❌ you must accept the Coqui Public Model License (CPML) once before first use:\n"
            "   Full text: https://coqui.ai/cpml\n"
            "   Accept with: clone_voice_agree_license"
        )
    try:
        from TTS.api import TTS as CoquiTTS
    except ImportError:
        return "❌ Coqui TTS is not installed — install PyTorch for your CPU/GPU, then: pip install coqui-tts"

    reference, text, output = ctx.args[0], ctx.args[1], ctx.args[2]
    reference_path, output_path = pathlib.Path(reference), pathlib.Path(output)
    if not reference_path.is_file():
        return f"❌ reference audio file not found: {reference}"
    try:
        if reference_path.resolve() == output_path.resolve():
            return "❌ reference and output must be different files"
    except OSError:
        pass
    text = _prepare_speech_text(text)
    if not text:
        return "❌ the text is empty"
    language = ctx.args[3] if len(ctx.args) > 3 else "ar"
    if language not in _CLONE_LANGUAGES:
        return f"❌ language must be one of: {', '.join(sorted(_CLONE_LANGUAGES))}"
    duration = _reference_duration(reference_path)
    if duration is not None and not 3 <= duration <= 30:
        return (f"❌ reference is {duration:.1f}s; use one clean speaker for 3-30 seconds "
                "(6-12 seconds is usually best). Run prepare_voice_sample first.")

    os.environ["COQUI_TOS_AGREED"] = "1"  # موافقتنا الصريحة فوق سجّلت فعلاً — ده بس بيبلّغ مكتبة Coqui نفسها
    os.environ.setdefault("TTS_HOME", str(_voice_cache_dir() / "coqui"))
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"❌ could not create the output folder: {e}"

    model = _clone_voice_models.get(_CLONE_MODEL)
    if model is None:
        try:
            model = CoquiTTS(_CLONE_MODEL, progress_bar=False)
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
                if device == "cpu":
                    torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))
                if hasattr(model, "to"):
                    model = model.to(device)
            except (ImportError, RuntimeError):
                pass
        except Exception as e:
            return f"❌ could not load the XTTS-v2 model: {e}"
        _clone_voice_models[_CLONE_MODEL] = model

    try:
        model.tts_to_file(text=text, speaker_wav=reference, language=language, file_path=output)
    except Exception as e:
        return f"❌ voice cloning failed: {e}"

    if not mr.valid_output(output, minimum_bytes=44):
        return "❌ voice cloning failed — no usable WAV output was produced"
    polished = _polish_cloned_wav(output_path)
    master = "; speech loudness mastered" if polished else ""
    return f"✅ voice cloned (language: {language}{master}) at {output}"


def _cmd_clone_voice_status(ctx) -> str:
    try:
        import torch
        from TTS.api import TTS as _CoquiTTS  # noqa: F401
        import transformers
    except (ImportError, OSError) as exc:
        return ("❌ XTTS runtime is incomplete: " + str(exc) + "\n"
                "Install PyTorch/torchaudio first, then requirements-media-pro.txt")
    major = int(transformers.__version__.split(".", 1)[0])
    compatible = major < 5
    device = "CUDA GPU" if torch.cuda.is_available() else "CPU"
    cached = _CLONE_MODEL in _clone_voice_models
    lines = [
        "XTTS voice cloning:",
        f"  ✅ Coqui TTS import",
        f"  {'✅' if compatible else '❌'} Transformers {transformers.__version__} (requires <5)",
        f"  ✅ PyTorch {torch.__version__} on {device}",
        f"  {'✅' if cached else '⬜'} XTTS model loaded in this session",
    ]
    if device == "CPU":
        lines.append("  ℹ️ CPU works but synthesis is slower; CUDA is selected automatically when available.")
    return "\n".join(lines)


def _parse_listen_seconds(ctx) -> tuple[int, str | None]:
    if not ctx.args:
        return _LISTEN_DEFAULT_SECONDS, None
    try:
        seconds = int(ctx.args[0])
    except ValueError:
        return 0, f"usage: listen [seconds]   (1-{_LISTEN_MAX_SECONDS})"
    return max(1, min(seconds, _LISTEN_MAX_SECONDS)), None


def _listen_smart(ctx) -> tuple[str | None, str | None]:
    """بيسجّل ويفرّغ. من غير وسائط بيستنى لحد ما تسكت (VAD)؛ بعدد
    ثواني صريح بيسجّل المدة دي بالظبط.

    بيرجع (النص، رسالة الخطأ).
    """
    options = [a for a in ctx.args if "=" in a]
    positional = [a for a in ctx.args if "=" not in a]
    language, model = None, WHISPER_MODEL
    for option in options:
        key, value = option.split("=", 1)
        if key == "lang" and value in {"auto", "ar", "en"}:
            language = None if value == "auto" else value
        elif key == "model" and value in {"tiny", "base", "small", "medium", "large-v3"}:
            model = value
        else:
            return None, "usage: listen [seconds] [lang=auto|ar|en] [model=tiny|base|small|medium|large-v3]"
    explicit = bool(positional)
    original_args, ctx.args = ctx.args, positional
    seconds, err = _parse_listen_seconds(ctx)
    ctx.args = original_args
    if err:
        return None, err

    with tempfile.TemporaryDirectory(prefix="nezuko_listen_") as tmp:
        wav_path = pathlib.Path(tmp) / "input.wav"
        if not explicit:
            err, used_vad = _record_until_silence(wav_path, _LISTEN_MAX_SECONDS)
            if err:
                return None, f"❌ {err}"
            if not used_vad:
                # silero مش متثبت — نرجع للمدة الثابتة زي الأول
                err = _record_audio(seconds, wav_path)
                if err:
                    return None, f"❌ {err}"
        else:
            err = _record_audio(seconds, wav_path)
            if err:
                return None, f"❌ {err}"
        try:
            return _transcribe(wav_path, model, language)
        except TypeError:
            return _transcribe(wav_path)


def _cmd_listen(ctx) -> str:
    text, err = _listen_smart(ctx)
    if err:
        return err
    return f"🎤 heard: {text}"


def _cmd_listen_run(ctx) -> str:
    text, err = _listen_smart(ctx)
    if err:
        return err
    # The queued conversation is a two-way voice turn. The core selects its
    # low-latency model first and the GUI speaks the final reply automatically.
    ctx.engine._voice_turn_text = text
    ctx.engine.submit(text)
    return f"🎤 heard: {text}\n▶️ sent it off to run"


def _cmd_stt_status(ctx) -> str:
    lines = ["🎤 Listening (speech-to-text) status:"]
    mic_ok = sd is not None
    lines.append(
        f"  {'✅' if mic_ok else '❌'} sounddevice (records from the mic)"
        + ("" if mic_ok else " — pip install sounddevice")
    )

    try:
        import faster_whisper  # noqa: F401
        faster_ok = True
    except ImportError:
        faster_ok = False
    lines.append(
        f"  {'✅' if faster_ok else '❌'} faster-whisper (best — most accurate and lightest, model: {WHISPER_MODEL})"
        + ("" if faster_ok else " — pip install faster-whisper")
    )

    whisper_ok = shutil.which("whisper") is not None
    lines.append(
        f"  {'✅' if whisper_ok else '❌'} whisper CLI (fallback, model: {WHISPER_MODEL})"
        + ("" if whisper_ok else " — pip install openai-whisper")
    )

    vosk_dir_ok = _vosk_model_dir().is_dir()
    try:
        import vosk  # noqa: F401
        vosk_pkg_ok = True
    except ImportError:
        vosk_pkg_ok = False
    vosk_ok = vosk_dir_ok and vosk_pkg_ok
    vosk_note = ""
    if not vosk_pkg_ok:
        vosk_note = " — pip install vosk"
    elif not vosk_dir_ok:
        vosk_note = f" — download a model into {_vosk_model_dir()} (https://alphacephei.com/vosk/models)"
    lines.append(f"  {'✅' if vosk_ok else '❌'} Vosk (last resort, fully offline){vosk_note}")

    vad_ok = vad_available()
    lines.append(
        f"  {'✅' if vad_ok else '⬜'} silero-vad (stops recording when you stop talking)"
        + ("" if vad_ok else " — pip install silero-vad torch  ·  optional")
    )

    stt_engine_ok = faster_ok or whisper_ok or vosk_ok
    if not mic_ok or not stt_engine_ok:
        lines.append("\n⚠️ listen / listen_run need sounddevice plus at least one transcription engine.")
    elif not vad_ok:
        lines.append(
            f"\n💡 Without silero-vad, `listen` records a fixed {_LISTEN_DEFAULT_SECONDS}s."
            " With it, it stops as soon as you go quiet."
        )
    return "\n".join(lines)


def register(engine):
    engine.registry.register("speak", _cmd_speak, "speak <text> — say something in Nezuko's voice (edge-tts → sherpa-onnx offline → espeak-ng fallback)")
    engine.registry.register("voice_profile", _cmd_voice_profile, "voice_profile natural|warm|clear|fast — tune speech pacing, pitch, and clarity")
    engine.registry.register("voice_reference", _cmd_voice_reference, "voice_reference <authorized-audio|clear> — set the natural Nezuko voice")
    engine.registry.register("voice_status", _cmd_voice_status, "voice_status — which speech engines are available")
    engine.registry.register("listen", _cmd_listen, "listen [seconds] [lang=auto|ar|en] [model=...] — transcribe the mic without executing")
    engine.registry.register("listen_run", _cmd_listen_run, "listen_run [seconds] [lang=auto|ar|en] — transcribe then submit through normal approvals")
    engine.registry.register("stt_status", _cmd_stt_status, "stt_status — which listening engines are available")
    engine.registry.register("separate_vocals", _cmd_separate_vocals, "separate_vocals <audio> <out_dir> [mode=all|vocals] — split an audio file into stems (Demucs)")
    engine.registry.register("diarize_set_token", _cmd_diarize_set_token, "diarize_set_token <hf_token> — save a Hugging Face token for speaker diarization")
    engine.registry.register("diarize_key_status", _cmd_diarize_key_status, "diarize_key_status — is a Hugging Face token configured?")
    engine.registry.register("diarize", _cmd_diarize, "diarize <audio> — work out who spoke when (speaker diarization, pyannote.audio)")
    engine.registry.register("clone_voice_agree_license", _cmd_clone_voice_agree_license, "clone_voice_agree_license — accept the voice-cloning model's licence, once, explicitly")
    engine.registry.register("clone_voice_status", _cmd_clone_voice_status, "clone_voice_status — verify Coqui, Transformers, PyTorch, device, and model cache")
    engine.registry.register("clone_voice", _cmd_clone_voice, "clone_voice <reference.wav> <text> <output.wav> [language=ar] — clone a voice from a sample (Coqui XTTS-v2)")
    # Prepare only the current interface language in the background. Loading both
    # large models at once wastes RAM, while this removes the first-reply delay.
    try:
        cfg = brain.load_config()
        # Arabic conversation mode uses the low-latency network voice, so warming
        # the 90-second diffusion model here only slows the whole application.
        # Kokoro is compact and benefits greatly: measured 18.62s cold vs 0.62s warm.
        evr.prewarm()
        if cfg.get("local_only") and (cfg.get("preferred_voice_language") or "ar") == "ar":
            vtr.prewarm()
    except Exception:
        pass
