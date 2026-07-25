"""
voice_plugin.py — نطق نصوص بصوت أنثوي مصري (نيزوكو) عبر سلسلة احتياطية
حقيقية من ثلاث محركات TTS، من الأفضل جودة للأضمن توفر:

1. Microsoft Edge TTS (عبر مكتبة `edge-tts` مفتوحة المصدر) — مجاني
   بالكامل من غير API key أو اشتراك، وفيه صوت مصري أنثوي حقيقي
   (ar-EG-SalmaNeural). العيب الوحيد: التوليد نفسه بيحصل على سيرفرات
   مايكروسوفت، يعني محتاج إنترنت وقت الاستخدام — مش نموذج محلي بالكامل.
2. Piper (محرك TTS عصبي محلي، مفتوح المصدر GPL) — صوت عربي واحد بس
   متاح رسميًا (`ar_JO-kareem`، أردني، رجالي) بيتحمّل مرة واحدة
   (~60MB) ويشتغل offline تمامًا بعد كده. مفيش صوت عربي أنثوي في
   مكتبة أصوات Piper الرسمية للأسف — قيد حقيقي في الأدوات المتاحة،
   مش قرار تصميم.
3. espeak-ng (مضمّن محليًا دايمًا، بدون إنترنت خالص) — صوت عربي
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

الأوامر: speak, voice_status, listen, listen_run, stt_status, separate_vocals
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave

try:
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

EDGE_VOICE = "ar-EG-SalmaNeural"
PIPER_VOICE_NAME = "ar_JO-kareem-medium"
PIPER_MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx?download=true"
PIPER_CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json?download=true.json"

_NETWORK_TIMEOUT = 20
_SYNTH_TIMEOUT = 30
_PLAYBACK_TIMEOUT = 120

WHISPER_MODEL = "base"
_SAMPLE_RATE = 16000
_LISTEN_DEFAULT_SECONDS = 5
_LISTEN_MAX_SECONDS = 30
_TRANSCRIBE_TIMEOUT = 180
_SEPARATE_TIMEOUT = 1800  # فصل صوتي (Demucs) تقيل، ممكن ياخد دقايق كتير على CPU


def _voice_cache_dir() -> pathlib.Path:
    # نفس منطق _quarantine_dir في security_scan_plugin.py: exe المبني
    # بـ PyInstaller بيفكك __file__ في مجلد مؤقت، فلازم نستخدم مسار
    # الـ exe نفسه في الحالة دي.
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    d = base / "voice_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, dest: pathlib.Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=_NETWORK_TIMEOUT) as resp, dest.open("wb") as f:
            shutil.copyfileobj(resp, f)
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        dest.unlink(missing_ok=True)
        return False


def _ensure_piper_voice() -> tuple[pathlib.Path, pathlib.Path] | None:
    d = _voice_cache_dir()
    model = d / f"{PIPER_VOICE_NAME}.onnx"
    config = d / f"{PIPER_VOICE_NAME}.onnx.json"
    if model.is_file() and config.is_file():
        return model, config
    if not _download(PIPER_MODEL_URL, model):
        return None
    if not _download(PIPER_CONFIG_URL, config):
        model.unlink(missing_ok=True)
        return None
    return model, config


def _synthesize_edge(text: str, out_path: pathlib.Path) -> bool:
    if not shutil.which("edge-tts"):
        return False
    try:
        proc = subprocess.run(
            ["edge-tts", "-t", text, "-v", EDGE_VOICE, "--write-media", str(out_path)],
            capture_output=True, text=True, timeout=_SYNTH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


def _synthesize_piper(text: str, out_path: pathlib.Path) -> bool:
    if not shutil.which("piper"):
        return False
    voice = _ensure_piper_voice()
    if voice is None:
        return False
    model, config = voice
    try:
        proc = subprocess.run(
            ["piper", "-m", str(model), "-c", str(config), "-f", str(out_path)],
            input=text, capture_output=True, text=True, timeout=_SYNTH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


def _synthesize_espeak(text: str, out_path: pathlib.Path) -> bool:
    if not shutil.which("espeak-ng"):
        return False
    try:
        proc = subprocess.run(
            ["espeak-ng", "-v", "ar", "-s", "155", "-p", "70", "-w", str(out_path), text],
            capture_output=True, text=True, timeout=_SYNTH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


# الترتيب بيمثّل أولوية الجودة الحقيقية: صوت أنثوي مصري طبيعي أولاً،
# وبعدين احتياطي محلي أفضل من إسبيك، وأخيرًا الضمانة اللي بتشتغل دايمًا.
_BACKENDS = [
    ("edge-tts (ar-EG-SalmaNeural — صوت مصري أنثوي)", _synthesize_edge, ".mp3"),
    ("Piper (ar_JO-kareem — صوت عربي محلي)", _synthesize_piper, ".wav"),
    ("espeak-ng (احتياطي محلي دايمًا شغال)", _synthesize_espeak, ".wav"),
]


def _synthesize_with_fallback(text: str, tmp_dir: pathlib.Path) -> tuple[pathlib.Path, str] | None:
    for label, synth_fn, ext in _BACKENDS:
        out_path = tmp_dir / f"speech{ext}"
        if synth_fn(text, out_path):
            return out_path, label
    return None


def _cmd_speak(ctx) -> str:
    parts = ctx.raw.split(maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return "usage: speak <نص>"

    with tempfile.TemporaryDirectory(prefix="nezuko_speech_") as tmp:
        result = _synthesize_with_fallback(text, pathlib.Path(tmp))
        if result is None:
            return (
                "❌ كل محركات النطق فشلت — مفيش إنترنت لـ edge-tts، Piper مش متثبت/مش قادر "
                "يحمّل الصوت، وespeak-ng مش متثبت. ثبّت على الأقل espeak-ng (فحص voice_status)."
            )
        audio_path, backend_label = result

        if not shutil.which("ffplay"):
            return f"✅ اتولّد الصوت بـ {backend_label} — بس ffplay (جزء من FFmpeg) مش متثبت عشان يشغّله"

        try:
            play_proc = subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)],
                capture_output=True, text=True, timeout=_PLAYBACK_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return f"⚠️ اتولّد الصوت بـ {backend_label} بس التشغيل أخد وقت أطول من اللازم"

        if play_proc.returncode != 0:
            return f"⚠️ اتولّد الصوت بـ {backend_label} بس ffplay فشل يشغّله (كود {play_proc.returncode})"

    return f"🔊 اتقال بـ {backend_label}"


def _cmd_voice_status(ctx) -> str:
    lines = ["🔊 حالة محركات النطق (نيزوكو):"]

    edge_ok = shutil.which("edge-tts") is not None
    lines.append(
        f"  {'✅' if edge_ok else '❌'} edge-tts"
        + (f" — الصوت: {EDGE_VOICE} (محتاج إنترنت وقت الاستخدام)" if edge_ok else " — pip install edge-tts")
    )

    piper_ok = shutil.which("piper") is not None
    voice_cached = (_voice_cache_dir() / f"{PIPER_VOICE_NAME}.onnx").is_file()
    piper_note = ""
    if piper_ok:
        piper_note = " — الصوت محفوظ محليًا (offline)" if voice_cached else " — هيتحمّل أول استخدام (~60MB، مرة واحدة بس)"
    else:
        piper_note = " — pip install piper-tts"
    lines.append(f"  {'✅' if piper_ok else '❌'} Piper ({PIPER_VOICE_NAME}){piper_note}")

    espeak_ok = shutil.which("espeak-ng") is not None
    lines.append(f"  {'✅' if espeak_ok else '❌'} espeak-ng" + ("" if espeak_ok else " — apt install espeak-ng (أو من espeak-ng.github.io)"))

    ffplay_ok = shutil.which("ffplay") is not None
    lines.append(f"  {'✅' if ffplay_ok else '❌'} ffplay لتشغيل الصوت (جزء من FFmpeg)")

    if not (edge_ok or piper_ok or espeak_ok):
        lines.append("\n⚠️ مفيش أي محرك نطق متثبت — أمر speak مش هيشتغل خالص.")

    return "\n".join(lines)


# ── استماع صوتي (STT): sounddevice للتسجيل + whisper CLI للتفريغ ────────

def _record_audio(seconds: int, out_path: pathlib.Path) -> str | None:
    """يسجل من المايك الافتراضي، يرجع None لو نجح أو رسالة خطأ لو فشل."""
    if sd is None:
        return "مكتبة sounddevice مش متثبتة — pip install sounddevice"
    try:
        audio = sd.rec(int(seconds * _SAMPLE_RATE), samplerate=_SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
    except Exception as e:
        return f"تعذر التسجيل من المايك: {e}"
    try:
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 بايت
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
    except OSError as e:
        return f"تعذر حفظ التسجيل: {e}"
    return None


_faster_whisper_models: dict[str, object] = {}


def _transcribe_faster_whisper(wav_path: pathlib.Path, model_size: str) -> tuple[str | None, bool]:
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
        segments, _info = model.transcribe(str(wav_path))
        text = " ".join(seg.text for seg in segments).strip()
    except Exception:
        return None, True
    return (text or None), True


def _transcribe_whisper_cli(wav_path: pathlib.Path, model: str) -> tuple[str | None, bool]:
    if not shutil.which("whisper"):
        return None, False
    with tempfile.TemporaryDirectory(prefix="nezuko_stt_") as tmp:
        cmd = [
            "whisper", str(wav_path), "--model", model,
            "--output_format", "txt", "--output_dir", tmp, "--fp16", "False",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TRANSCRIBE_TIMEOUT)
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
        import json as _json

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
                    chunk = _json.loads(rec.Result()).get("text", "")
                    if chunk:
                        parts.append(chunk)
            final = _json.loads(rec.FinalResult()).get("text", "")
            if final:
                parts.append(final)
        text = " ".join(parts).strip()
    except Exception:
        return None, True
    return (text or None), True


_STT_MISSING_MSG = (
    "❌ مفيش أي محرك تفريغ صوتي متثبت — ثبّت واحد على الأقل:\n"
    "   pip install faster-whisper   (الأفضل — أدق وأخف وأسرع)\n"
    "   pip install openai-whisper\n"
    "   أو حمّل نموذج Vosk صغير: https://alphacephei.com/vosk/models\n"
    "     وفكه في voice_cache/vosk-model/ (أو اضبط NEZUKO_VOSK_MODEL)"
)


def _transcribe(wav_path: pathlib.Path, model: str = WHISPER_MODEL) -> tuple[str | None, str | None]:
    """يرجع (النص، None) لو نجح، أو (None، رسالة خطأ) لو كل المحركات
    فشلت أو مفيش ولا واحد متثبت. بيجرب faster-whisper الأول (أدق
    وأخف)، بعدين whisper CLI، وأخيرًا Vosk (لو نموذجه متحمّل يدويًا)."""
    any_available = False
    for backend_fn in (
        lambda: _transcribe_faster_whisper(wav_path, model),
        lambda: _transcribe_whisper_cli(wav_path, model),
        lambda: _transcribe_vosk(wav_path),
    ):
        text, available = backend_fn()
        any_available = any_available or available
        if text:
            return text, None
    if not any_available:
        return None, _STT_MISSING_MSG
    return None, "🔇 مسمعتش أي كلام واضح"


# ═══════════════════════════════════════════════════════════════════
# فصل مسارات صوتية (Demucs) — أداة خارجية اختيارية
# ═══════════════════════════════════════════════════════════════════

def _cmd_separate_vocals(ctx) -> str:
    if len(ctx.args) < 2:
        return (
            "usage: separate_vocals <audio> <output_dir> [mode=all|vocals] — "
            "فصل المسارات الصوتية (Demucs): all=4 مسارات، vocals=صوت/بدون صوت بس (أسرع)"
        )
    if not shutil.which("demucs"):
        return "❌ demucs مش متثبت — نزّله بـ: pip install demucs (مجاني ومفتوح المصدر، أول استخدام بيحمّل نموذجه ~80MB)"
    src, out_dir = ctx.args[0], ctx.args[1]
    if not pathlib.Path(src).is_file():
        return f"❌ الملف مش موجود: {src}"
    mode = ctx.args[2] if len(ctx.args) > 2 else "all"
    if mode not in ("all", "vocals"):
        return "❌ mode لازم يكون all أو vocals"

    cmd = ["demucs", "-o", out_dir]
    if mode == "vocals":
        cmd += ["--two-stems", "vocals"]
    cmd.append(src)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_SEPARATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"⏱ انتهت المهلة ({_SEPARATE_TIMEOUT}s) — الفصل الصوتي بطيء على CPU، جرب ملف أقصر أو جهاز فيه GPU"
    if proc.returncode != 0:
        return f"❌ فشل: {proc.stderr.strip()[-600:]}"
    stems = "vocals + no_vocals" if mode == "vocals" else "vocals + drums + bass + other"
    return f"✅ اتفصل الصوت ({stems}) في {out_dir}"


def _parse_listen_seconds(ctx) -> tuple[int, str | None]:
    if not ctx.args:
        return _LISTEN_DEFAULT_SECONDS, None
    try:
        seconds = int(ctx.args[0])
    except ValueError:
        return 0, f"usage: listen [seconds]   (1-{_LISTEN_MAX_SECONDS})"
    return max(1, min(seconds, _LISTEN_MAX_SECONDS)), None


def _listen_and_transcribe(seconds: int) -> tuple[str | None, str | None]:
    with tempfile.TemporaryDirectory(prefix="nezuko_listen_") as tmp:
        wav_path = pathlib.Path(tmp) / "input.wav"
        err = _record_audio(seconds, wav_path)
        if err:
            return None, f"❌ {err}"
        return _transcribe(wav_path)


def _cmd_listen(ctx) -> str:
    seconds, err = _parse_listen_seconds(ctx)
    if err:
        return err
    text, err = _listen_and_transcribe(seconds)
    if err:
        return err
    return f"🎤 سمعت: {text}"


def _cmd_listen_run(ctx) -> str:
    seconds, err = _parse_listen_seconds(ctx)
    if err:
        return err
    text, err = _listen_and_transcribe(seconds)
    if err:
        return err
    ctx.engine.submit(text)
    return f"🎤 سمعت: {text}\n▶️ اتبعت للتنفيذ"


def _cmd_stt_status(ctx) -> str:
    lines = ["🎤 حالة الاستماع الصوتي (نيزوكو):"]
    mic_ok = sd is not None
    lines.append(
        f"  {'✅' if mic_ok else '❌'} sounddevice (تسجيل من المايك)"
        + ("" if mic_ok else " — pip install sounddevice")
    )

    try:
        import faster_whisper  # noqa: F401
        faster_ok = True
    except ImportError:
        faster_ok = False
    lines.append(
        f"  {'✅' if faster_ok else '❌'} faster-whisper (الأفضل — أدق وأخف، نموذج: {WHISPER_MODEL})"
        + ("" if faster_ok else " — pip install faster-whisper")
    )

    whisper_ok = shutil.which("whisper") is not None
    lines.append(
        f"  {'✅' if whisper_ok else '❌'} whisper CLI (احتياطي، نموذج: {WHISPER_MODEL})"
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
        vosk_note = f" — حمّل نموذج في {_vosk_model_dir()} (https://alphacephei.com/vosk/models)"
    lines.append(f"  {'✅' if vosk_ok else '❌'} Vosk (الضمانة الأخيرة، offline بالكامل){vosk_note}")

    stt_engine_ok = faster_ok or whisper_ok or vosk_ok
    if not mic_ok or not stt_engine_ok:
        lines.append("\n⚠️ لازم sounddevice + محرك تفريغ واحد على الأقل عشان listen/listen_run يشتغلوا.")
    return "\n".join(lines)


def register(engine):
    engine.registry.register("speak", _cmd_speak, "speak <نص> — نطق نص بصوت نيزوكو (edge-tts أنثوي مصري → Piper محلي → espeak-ng احتياطي)")
    engine.registry.register("voice_status", _cmd_voice_status, "voice_status — عرض حالة محركات النطق المتاحة")
    engine.registry.register("listen", _cmd_listen, "listen [seconds] — سجل من المايك وفرّغ الكلام لنص (بدون تنفيذ)")
    engine.registry.register("listen_run", _cmd_listen_run, "listen_run [seconds] — زي listen لكن ينفذ النص المسموع كأمر فورًا")
    engine.registry.register("stt_status", _cmd_stt_status, "stt_status — حالة أدوات الاستماع الصوتي المتاحة (sounddevice + whisper)")
    engine.registry.register("separate_vocals", _cmd_separate_vocals, "separate_vocals <audio> <out_dir> [mode=all|vocals] — فصل المسارات الصوتية (Demucs)")
