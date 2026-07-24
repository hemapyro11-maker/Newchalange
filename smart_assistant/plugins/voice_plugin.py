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
عشوائي. الأوامر: speak, voice_status
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

EDGE_VOICE = "ar-EG-SalmaNeural"
PIPER_VOICE_NAME = "ar_JO-kareem-medium"
PIPER_MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx?download=true"
PIPER_CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json?download=true.json"

_NETWORK_TIMEOUT = 20
_SYNTH_TIMEOUT = 30
_PLAYBACK_TIMEOUT = 120


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


def register(engine):
    engine.registry.register("speak", _cmd_speak, "speak <نص> — نطق نص بصوت نيزوكو (edge-tts أنثوي مصري → Piper محلي → espeak-ng احتياطي)")
    engine.registry.register("voice_status", _cmd_voice_status, "voice_status — عرض حالة محركات النطق المتاحة")
