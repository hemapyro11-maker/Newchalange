"""
brain.py — طبقة "المخ" الموحّدة لنيزوكو: واجهة واحدة قدّام كل مزوّدي
نماذج اللغة، مجانيين كانوا أو محليين.

**ليه الملف ده موجود أصلاً:** قبل كده كان عنوان Ollama متحطوط بالإيد
في 4 ملفات مختلفة (core_engine.py, think_plugin.py, self_improve_plugin.py,
plugin_forge_plugin.py) — أي تغيير في المخ كان بيتطلب تعديل 4 أماكن،
ومكانش فيه أي طريقة تضيف مزوّد تاني من غير ما تكرر الكود خامس مرة.
دلوقتي كل حاجة بتعدي من هنا.

**المزوّدين المدعومين (كلهم مجانيين، من غير كارت ائتمان):**
معظمهم متوافق مع صيغة OpenAI (`/v1/chat/completions`) فمحوّل واحد
بيغطيهم كلهم: Groq, OpenRouter, Cerebras, Mistral, Z.AI, SambaNova،
وكمان Ollama المحلي (عنده endpoint متوافق مع OpenAI برضه). Gemini
بصيغته الخاصة فليه محوّل تاني — اتنين بس، مش ستة.

**صفر اعتماديات جديدة:** كل دول HTTPS عادي، فـ `urllib` من مكتبة
بايثون القياسية كفاية. مفيش أي زيادة في حجم الـ .exe.

**المشاكل الحقيقية اللي الملف ده بيحلها (مش نظرية):**

1. **اختلاف حجم السياق** — Gemini بيشيل مليون توكن، Llama على Groq
   128 ألف، والنماذج المحلية الصغيرة 8 آلاف. لو محادثة طويلة اتحوّلت
   لمزوّد أصغر، كانت **هتقع** مش هتضعف بس. عشان كده بنقص التاريخ على
   حد المزوّد **النشط** قبل كل نداء (`_fit_to_context`).

2. **الحدود بالدقيقة واليوم** — كل مزوّد بحدوده. بنعدّهم فعليًا،
   والعداد اليومي **بيتحفظ على القرص** عشان قفل البرنامج ميصفّرش
   معرفتنا بالحد اليومي (لو اتصفّر، أول تشغيل تاني هيضرب الحد فورًا).

3. **عاصفة إعادة المحاولة** — مزوّد بيرجّع 429 أو بيقع، لو ضربناه تاني
   على طول بنحرق الحصة. عشان كده circuit breaker: بعد فشلين متتاليين
   المزوّد بيتقفل مؤقتًا (backoff تصاعدي لحد 10 دقايق).

4. **الشفافية عن الخصوصية** — الخطط المجانية لبعض المزوّدين (Gemini,
   Mistral) بتقول صراحةً إن كلامك ممكن يستخدموه لتحسين نماذجهم. كل رد
   بيرجع معاه اسم المزوّد اللي ردّ (`BrainReply.provider`) عشان الواجهة
   تعرضه، وفيه وضع `local_only` بيقفل كل السحابي.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

try:
    import keyring
    from keyring.errors import KeyringError
    _HAS_KEYRING = True
except ImportError:  # pragma: no cover - بيعتمد على البيئة
    keyring = None
    KeyringError = Exception
    _HAS_KEYRING = False

_KEYRING_SERVICE = "nezuko-brain"

# قفل واحد لكل حالة المخ المشتركة (العدّادات، القاطع، الإعدادات) —
# بتتقرا/تتكتب من thread الواجهة، thread المحرك، وthreads المخ نفسها.
_lock = threading.RLock()


# ── تعريف المزوّدين ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Provider:
    """وصف مزوّد واحد. `quality` بترتّب سلسلة البدائل — الأعلى الأول.

    `rpm`/`rpd` هي الحدود المجانية المعلنة وقت الكتابة؛ المزوّدين
    بيغيّروها، فهي في `brain_config.json` كمان وتقدر تعدّلها من غير ما
    تلمس الكود. `context` بالتوكن، وبنستخدمه فعليًا لقص التاريخ.
    """
    name: str
    label: str
    kind: str            # "openai" | "gemini" | "ollama"
    base_url: str
    model: str
    rpm: int
    rpd: int
    context: int
    quality: int
    timeout: int = 60
    needs_key: bool = True
    signup: str = ""
    # الخطة المجانية بتستخدم كلامك لتحسين نماذجهم؟ (بيتعرض للمستخدم)
    trains_on_input: bool = False


# مرتبين حسب الجودة — دي سلسلة البدائل الافتراضية.
# Gemini الأول لأنه أقوى واحد في العربي وأسخى في الحد اليومي.
PROVIDERS: dict[str, Provider] = {
    "gemini": Provider(
        name="gemini", label="Google Gemini", kind="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.0-flash", rpm=15, rpd=1500, context=1_000_000,
        quality=100, signup="https://aistudio.google.com/apikey",
        trains_on_input=True,
    ),
    "groq": Provider(
        name="groq", label="Groq", kind="openai",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile", rpm=30, rpd=1000, context=128_000,
        quality=90, timeout=30, signup="https://console.groq.com/keys",
    ),
    "cerebras": Provider(
        name="cerebras", label="Cerebras", kind="openai",
        base_url="https://api.cerebras.ai/v1",
        model="llama-3.3-70b", rpm=30, rpd=900, context=64_000,
        quality=85, timeout=30, signup="https://cloud.cerebras.ai",
    ),
    "openrouter": Provider(
        name="openrouter", label="OpenRouter", kind="openai",
        base_url="https://openrouter.ai/api/v1",
        model="meta-llama/llama-3.3-70b-instruct:free", rpm=20, rpd=200,
        context=128_000, quality=80, signup="https://openrouter.ai/keys",
    ),
    "mistral": Provider(
        name="mistral", label="Mistral", kind="openai",
        base_url="https://api.mistral.ai/v1",
        model="mistral-small-latest", rpm=60, rpd=500, context=128_000,
        quality=75, signup="https://console.mistral.ai/api-keys",
        trains_on_input=True,
    ),
    "ollama": Provider(
        name="ollama", label="Ollama (محلي)", kind="ollama",
        base_url="http://localhost:11434/v1",
        model="llama3.2", rpm=10_000, rpd=1_000_000, context=8_000,
        quality=40, timeout=180, needs_key=False,
        signup="https://ollama.com",
    ),
}

LOCAL_PROVIDERS = {"ollama"}


@dataclass
class BrainReply:
    """رد المخ + معلومات شفافية عنه."""
    text: str
    provider: str = ""
    label: str = ""
    is_local: bool = True
    error: str = ""

    def __bool__(self) -> bool:
        return bool(self.text) and not self.error


@dataclass
class _ProviderState:
    """حالة وقت التشغيل لمزوّد واحد — عدّادات وقاطع دائرة."""
    minute_hits: list[float] = field(default_factory=list)
    day_count: int = 0
    day_stamp: str = ""
    fails: int = 0
    cold_until: float = 0.0


# ── مسارات الملفات ───────────────────────────────────────────────────

def _base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def _config_path() -> pathlib.Path:
    return _base_dir() / "brain_config.json"


def _state_path() -> pathlib.Path:
    return _base_dir() / "brain_state.json"


def _default_config() -> dict:
    return {
        "enabled": list(PROVIDERS),
        "models": {},        # override اسم النموذج لكل مزوّد
        "limits": {},        # override rpm/rpd لكل مزوّد
        "local_only": False,
        "deep_mode": False,
        # تصعيد تلقائي للوضع العميق في الأسئلة الصعبة بس. مقفول
        # افتراضيًا عن قصد: الوضع العميق بيستهلك ~4 أضعاف الحصة،
        # وقرار صرف الحصة قرار المستخدم مش قرار البرنامج.
        "auto_deep": False,
        # مراجعة ذاتية (CoVe) على الأسئلة الصعبة. 4 نداءات بدل واحد،
        # بس الحصة مجانية — التكلفة الحقيقية وقت مش فلوس.
        "verify_mode": False,
        "keys": {},          # نص عادي — احتياطي بس لو keyring مش متاح
    }


def load_config() -> dict:
    path = _config_path()
    data = _default_config()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass
    return data


def save_config(data: dict) -> None:
    try:
        _config_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ── تخزين المفاتيح (نفس نمط telegram_plugin بالظبط) ──────────────────

def set_key(provider: str, key: str) -> str:
    """بيحفظ المفتاح في مخزن أسرار النظام لو متاح، وإلا نص عادي مع
    تحذير صريح. بيرجع وصف الطريقة اللي اتستخدمت فعليًا."""
    if _HAS_KEYRING:
        try:
            keyring.set_password(_KEYRING_SERVICE, provider, key)
            with _lock:
                cfg = load_config()
                cfg.setdefault("keys", {}).pop(provider, None)
                save_config(cfg)
            return "keyring"
        except KeyringError:
            pass
    with _lock:
        cfg = load_config()
        cfg.setdefault("keys", {})[provider] = key
        save_config(cfg)
    return "plaintext"


def get_key(provider: str) -> str | None:
    """ترتيب البحث: متغير بيئة ← keyring ← ملف الإعدادات."""
    env = os.environ.get(f"NEZUKO_{provider.upper()}_KEY") or \
        os.environ.get(f"{provider.upper()}_API_KEY")
    if env:
        return env
    if _HAS_KEYRING:
        try:
            stored = keyring.get_password(_KEYRING_SERVICE, provider)
            if stored:
                return stored
        except KeyringError:
            pass
    return load_config().get("keys", {}).get(provider)


def clear_key(provider: str) -> None:
    if _HAS_KEYRING:
        try:
            keyring.delete_password(_KEYRING_SERVICE, provider)
        except Exception:
            pass
    with _lock:
        cfg = load_config()
        cfg.get("keys", {}).pop(provider, None)
        save_config(cfg)


# ── تقدير التوكن وقص السياق ──────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """تقدير تقريبي متحفّظ. العربي بياخد توكن أكتر من الإنجليزي لكل
    حرف، فبنقسم على 3 مش 4 — الغلط في اتجاه الأمان (نقص أكتر من
    اللازم أحسن من إننا نبعت طلب أكبر من السياق فيقع)."""
    return max(1, len(text) // 3)


def _fit_to_context(messages: list[dict], limit: int) -> list[dict]:
    """بيقص أقدم الرسائل عشان الطلب يدخل في سياق المزوّد النشط.

    ده الإصلاح للمشكلة رقم 1 في رأس الملف: من غيره، محادثة اتبنت على
    Gemini (مليون توكن) وبعدين اتحوّلت لنموذج محلي (8 آلاف) كانت
    هترجّع خطأ بدل رد. بنسيب رسالة الـ system دايمًا (فيها التعليمات
    وقايمة الأدوات) وآخر رسالة للمستخدم (السؤال الحالي) — الاتنين
    مش قابلين للحذف — وبنشيل من النص.
    """
    budget = int(limit * 0.75)  # نسيب مساحة للرد نفسه
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    used = sum(estimate_tokens(m.get("content", "")) for m in system)
    kept: list[dict] = []
    # من الأحدث للأقدم عشان نحافظ على آخر سياق
    for msg in reversed(rest):
        cost = estimate_tokens(msg.get("content", ""))
        if kept and used + cost > budget:
            break
        used += cost
        kept.append(msg)
    kept.reverse()

    # آخر رسالة مش قابلة للحذف (هي السؤال نفسه)، فلو هي لوحدها أكبر من
    # الميزانية لازم نقصّ محتواها. من غير الخطوة دي كانت بتعدي كما هي
    # ويرجّع المزوّد خطأ سياق بدل رد.
    if kept and used > budget:
        room = max(200, budget - (used - estimate_tokens(kept[-1].get("content", ""))))
        trimmed = dict(kept[-1])
        trimmed["content"] = trimmed.get("content", "")[: room * 3]
        kept[-1] = trimmed
    return system + kept


# ── المخ ─────────────────────────────────────────────────────────────

class Brain:
    """موجّه بين كل المزوّدين، بحدود ومحاولات بديلة وقاطع دائرة."""

    def __init__(self):
        self._states: dict[str, _ProviderState] = {}
        self._load_state()

    # ── حفظ/تحميل العدّادات اليومية ──────────────────────────────
    def _load_state(self) -> None:
        try:
            raw = json.loads(_state_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        today = time.strftime("%Y-%m-%d")
        for name in PROVIDERS:
            info = raw.get(name, {})
            st = _ProviderState()
            # العدّاد اليومي بيتحفظ على القرص عشان إعادة تشغيل البرنامج
            # ماتصفّرش معرفتنا بالحد (المشكلة رقم 2 في رأس الملف)
            if info.get("day_stamp") == today:
                st.day_count = int(info.get("day_count", 0))
                st.day_stamp = today
            else:
                st.day_stamp = today
            self._states[name] = st

    def _save_state(self) -> None:
        data = {
            name: {"day_count": st.day_count, "day_stamp": st.day_stamp}
            for name, st in self._states.items()
        }
        try:
            _state_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass

    # ── الحدود والقاطع ───────────────────────────────────────────
    def _limits_for(self, prov: Provider, cfg: dict) -> tuple[int, int]:
        override = cfg.get("limits", {}).get(prov.name, {})
        return int(override.get("rpm", prov.rpm)), int(override.get("rpd", prov.rpd))

    def _available(self, prov: Provider, cfg: dict, now: float) -> bool:
        """المزوّد ده ينفع يتنادى دلوقتي؟"""
        st = self._states.setdefault(prov.name, _ProviderState())
        if now < st.cold_until:
            return False
        today = time.strftime("%Y-%m-%d")
        if st.day_stamp != today:
            st.day_stamp, st.day_count = today, 0
        rpm, rpd = self._limits_for(prov, cfg)
        if st.day_count >= rpd:
            return False
        st.minute_hits = [t for t in st.minute_hits if now - t < 60]
        return len(st.minute_hits) < rpm

    def _note_success(self, name: str, now: float) -> None:
        st = self._states.setdefault(name, _ProviderState())
        st.minute_hits.append(now)
        st.day_count += 1
        st.fails = 0
        st.cold_until = 0.0
        self._save_state()

    def _note_failure(self, name: str, now: float, *, rate_limited: bool) -> None:
        """قاطع الدائرة: بعد فشلين متتاليين نقفل المزوّد مؤقتًا بـ
        backoff تصاعدي بدل ما نفضل نضربه ونحرق الحصة (المشكلة رقم 3)."""
        st = self._states.setdefault(name, _ProviderState())
        st.fails += 1
        if rate_limited:
            # ضربنا الحد فعلاً — نعتبر الدقيقة مليانة ونستنى
            st.minute_hits = [now] * 10_000
            st.cold_until = now + 60
        elif st.fails >= 2:
            st.cold_until = now + min(600, 30 * (2 ** (st.fails - 2)))

    # ── سلسلة البدائل ────────────────────────────────────────────
    def chain(self, cfg: dict | None = None) -> list[Provider]:
        """المزوّدين المتاحين مرتبين حسب الجودة."""
        cfg = cfg if cfg is not None else load_config()
        enabled = set(cfg.get("enabled", list(PROVIDERS)))
        local_only = bool(cfg.get("local_only"))
        out = []
        for prov in PROVIDERS.values():
            if prov.name not in enabled:
                continue
            if local_only and prov.name not in LOCAL_PROVIDERS:
                continue
            if prov.needs_key and not get_key(prov.name):
                continue
            out.append(prov)
        out.sort(key=lambda p: -p.quality)
        return out

    def ready(self) -> bool:
        return bool(self.chain())

    # ── النداء الأساسي ───────────────────────────────────────────
    def chat(self, messages: list[dict], *, temperature: float = 0.7,
             max_tokens: int = 1200) -> BrainReply:
        """بينادي أول مزوّد متاح، وينتقل للي بعده لو فشل.

        بيرجع BrainReply دايمًا (مبيرميش استثناء) — الكود اللي بينادي
        بيفحص `.error` أو صدق/كذب الكائن.
        """
        cfg = load_config()
        candidates = self.chain(cfg)
        if not candidates:
            return BrainReply(
                text="", error=(
                    "مفيش أي مخ متظبط. ضيف مفتاح مجاني بـ: brain_key <provider> <key>\n"
                    "أو شغّل Ollama محلي. شوف brain_status للتفاصيل."
                ),
            )

        last_error = ""
        for prov in candidates:
            now = time.time()
            with _lock:
                if not self._available(prov, cfg, now):
                    continue
            model = cfg.get("models", {}).get(prov.name, prov.model)
            fitted = _fit_to_context(messages, prov.context)
            try:
                text = _call_provider(prov, model, fitted, temperature, max_tokens)
            except _RateLimited as e:
                with _lock:
                    self._note_failure(prov.name, now, rate_limited=True)
                last_error = f"{prov.label}: تعدّيت الحد ({e})"
                continue
            except Exception as e:  # noqa: BLE001 - أي فشل = جرّب اللي بعده
                with _lock:
                    self._note_failure(prov.name, now, rate_limited=False)
                last_error = f"{prov.label}: {e}"
                continue
            if not text.strip():
                with _lock:
                    self._note_failure(prov.name, now, rate_limited=False)
                last_error = f"{prov.label}: رد فاضي"
                continue
            with _lock:
                self._note_success(prov.name, now)
            return BrainReply(
                text=text.strip(), provider=prov.name, label=prov.label,
                is_local=prov.name in LOCAL_PROVIDERS,
            )

        return BrainReply(text="", error=last_error or "كل المزوّدين مش متاحين دلوقتي")

    # ── الوضع العميق (Mixture-of-Agents مبسّط) ───────────────────
    def deep_chat(self, messages: list[dict], *, proposers: int = 3) -> BrainReply:
        """بيسأل أكتر من مزوّد على نفس السؤال، وبعدين يخلي أقوى واحد
        يدمج أحسن اللي في الردود.

        مبني على بحث Mixture-of-Agents (ICLR 2025) اللي أثبت إن دمج
        نماذج مفتوحة بيتفوّق على نموذج تجاري واحد قوي. بنستخدم النسخة
        الخفيفة (طبقة واحدة + مُجمِّع) لأن الطبقات المتعددة بتضاعف
        الاستهلاك والبطء من غير مكسب يوازيهم.

        مكلّف: بيستهلك (proposers + 1) نداء لكل سؤال — عشان كده
        اختياري مش افتراضي.
        """
        cfg = load_config()
        candidates = self.chain(cfg)
        if len(candidates) < 2:
            return self.chat(messages)

        drafts: list[tuple[str, str]] = []
        for prov in candidates[:proposers]:
            now = time.time()
            with _lock:
                if not self._available(prov, cfg, now):
                    continue
            model = cfg.get("models", {}).get(prov.name, prov.model)
            try:
                text = _call_provider(
                    prov, model, _fit_to_context(messages, prov.context), 0.7, 1200
                )
            except Exception:  # noqa: BLE001
                with _lock:
                    self._note_failure(prov.name, time.time(), rate_limited=False)
                continue
            if text.strip():
                with _lock:
                    self._note_success(prov.name, now)
                drafts.append((prov.label, text.strip()))

        if not drafts:
            return BrainReply(text="", error="كل المزوّدين فشلوا في الوضع العميق")
        if len(drafts) == 1:
            label, text = drafts[0]
            return BrainReply(text=text, provider="deep", label=f"{label} (منفرد)")

        question = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        merged = "\n\n".join(
            f"--- إجابة {i + 1} ---\n{text}" for i, (_, text) in enumerate(drafts)
        )
        synth = [
            {"role": "system", "content": (
                "أنت مُجمِّع إجابات. هتلاقي تحت سؤال المستخدم وكذا إجابة من "
                "نماذج مختلفة. اكتب إجابة نهائية واحدة أفضل منهم كلهم: خد "
                "الصح من كل واحدة، تجاهل الغلط والتكرار، ولو فيه تعارض "
                "رجّح الأدق. اكتب بنفس لغة السؤال. مترجعش مقارنة بين "
                "الإجابات — رجّع الإجابة النهائية بس."
            )},
            {"role": "user", "content": f"سؤال المستخدم:\n{question}\n\n{merged}"},
        ]
        final = self.chat(synth, temperature=0.3)
        if final:
            return BrainReply(
                text=final.text, provider="deep",
                label=f"عميق ({len(drafts)} نماذج → {final.label})",
                is_local=final.is_local,
            )
        # المُجمِّع فشل — نرجّع أحسن مسودة بدل ما نفشل تمامًا
        label, text = drafts[0]
        return BrainReply(text=text, provider="deep", label=f"{label} (بدون دمج)")

    def verified_chat(self, messages: list[dict]) -> BrainReply:
        """يجاوب، بعدين يراجع إجابته بنفسه، بعدين يصححها.

        Chain-of-Verification (CoVe): النموذج بيكتب مسودة، وبعدين يكتب
        أسئلة تحقق عن ادعاءاته، ويجاوبها، وبعدين يعيد كتابة الإجابة على
        ضوء اللي طلع. البحث المنشور بيقول إنها بتقلل الهلوسة 50-70%
        وبتزوّد دقة سلاسل الاستدلال ~8 نقاط مئوية.

        **ليه ده منطقي هنا بالذات:** الطريقة دي بتكلّف 3 نداءات بدل
        واحد. ده غالي لو بتدفع بالنداء — لكن حصة نيزوكو مجانية، فالتكلفة
        الحقيقية هي الوقت بس. يعني نيزوكو تقدر تراجع نفسها على كل سؤال
        صعب، وده مكسب حقيقي مش تقليد.

        بترجع لأول مسودة لو أي مرحلة فشلت — التحقق تحسين، مش شرط.
        """
        draft = self.chat(messages, temperature=0.4)
        if not draft:
            return draft

        question = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )

        checks = self.chat([
            {"role": "system", "content": (
                "You check answers for mistakes. Given a question and a draft "
                "answer, write 2-4 short verification questions that would "
                "expose an error in the draft if one exists. Target the "
                "specific claims, numbers, names and steps it asserts — not "
                "its tone or style. One question per line, nothing else."
            )},
            {"role": "user", "content": f"Question:\n{question}\n\nDraft answer:\n{draft.text}"},
        ], temperature=0.3)
        if not checks or not checks.text.strip():
            return draft

        answers = self.chat([
            {"role": "system", "content": (
                "Answer each verification question briefly and independently. "
                "Do not try to defend any earlier answer — judge each question "
                "on its own. If something cannot be verified, say so plainly."
            )},
            {"role": "user", "content": checks.text.strip()},
        ], temperature=0.2)
        if not answers:
            return draft

        final = self.chat([
            {"role": "system", "content": (
                "Rewrite the draft answer using the verification results.\n"
                "- Correct anything the checks contradict.\n"
                "- Drop claims the checks could not confirm.\n"
                "- Keep everything the checks confirmed.\n"
                "- Answer in the same language as the question.\n"
                "Return the corrected answer only — no commentary about the "
                "revision, and no mention that a check happened."
            )},
            {"role": "user", "content": (
                f"Question:\n{question}\n\nDraft:\n{draft.text}\n\n"
                f"Verification questions:\n{checks.text}\n\n"
                f"Verification results:\n{answers.text}"
            )},
        ], temperature=0.3)
        if not final or not final.text.strip():
            return draft

        return BrainReply(
            text=final.text, provider=final.provider,
            label=f"{final.label} (verified)", is_local=final.is_local,
        )

    # ── تقرير الحالة ─────────────────────────────────────────────
    def status(self) -> list[dict]:
        cfg = load_config()
        enabled = set(cfg.get("enabled", list(PROVIDERS)))
        now = time.time()
        rows = []
        for prov in sorted(PROVIDERS.values(), key=lambda p: -p.quality):
            st = self._states.setdefault(prov.name, _ProviderState())
            rpm, rpd = self._limits_for(prov, cfg)
            if prov.name in LOCAL_PROVIDERS:
                # مزوّد محلي مالوش مفتاح، فـ"جاهز" عنده = السيرفر رادّ
                has_key = is_local_alive(prov)
            else:
                has_key = bool(get_key(prov.name))
            rows.append({
                "name": prov.name,
                "label": prov.label,
                "enabled": prov.name in enabled,
                "has_key": has_key,
                "local": prov.name in LOCAL_PROVIDERS,
                "used_today": st.day_count,
                "rpd": rpd,
                "rpm": rpm,
                "cold_for": max(0, int(st.cold_until - now)),
                "context": prov.context,
                "model": cfg.get("models", {}).get(prov.name, prov.model),
                "signup": prov.signup,
                "trains_on_input": prov.trains_on_input,
            })
        return rows


class _RateLimited(Exception):
    """المزوّد رجّع 429 — نتعامل معاه غير الأخطاء العادية."""


# ── فحص المزوّد المحلي ───────────────────────────────────────────────
# مزوّد محلي "مش محتاج مفتاح"، بس ده **مش** معناه إنه شغال. من غير
# الفحص ده كنا بنقول للمستخدم "مخ جاهز ✅" وهو مفيش أي حاجة متثبتة
# عنده أصلاً — أسوأ من إننا نقوله مفيش.

_probe_cache: dict[str, tuple[float, bool]] = {}
_PROBE_TTL = 30.0


def is_local_alive(prov: Provider, *, timeout: float = 1.0) -> bool:
    """بيتأكد إن سيرفر محلي (زي Ollama) رادّ فعلاً. النتيجة بتتخزن
    مؤقتًا عشان مانفحصش في كل نداء status."""
    now = time.time()
    cached = _probe_cache.get(prov.name)
    if cached and now - cached[0] < _PROBE_TTL:
        return cached[1]
    root = prov.base_url.rsplit("/v1", 1)[0]
    try:
        with urllib.request.urlopen(f"{root}/api/tags", timeout=timeout):
            alive = True
    except Exception:  # noqa: BLE001 - أي فشل = مش شغال
        alive = False
    _probe_cache[prov.name] = (now, alive)
    return alive


# ── المحوّلات (adapters) ─────────────────────────────────────────────

def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        if e.code == 429:
            raise _RateLimited(body or "429") from e
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def _call_provider(prov: Provider, model: str, messages: list[dict],
                   temperature: float, max_tokens: int) -> str:
    if prov.kind == "gemini":
        return _call_gemini(prov, model, messages, temperature, max_tokens)
    return _call_openai_compatible(prov, model, messages, temperature, max_tokens)


def _call_openai_compatible(prov: Provider, model: str, messages: list[dict],
                            temperature: float, max_tokens: int) -> str:
    """بيغطي Groq/OpenRouter/Cerebras/Mistral/Z.AI/SambaNova/Ollama —
    كلهم بيتكلموا نفس صيغة `/v1/chat/completions` بتاعة OpenAI."""
    headers = {"Content-Type": "application/json"}
    key = get_key(prov.name)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if prov.name == "openrouter":
        # OpenRouter بيطلب الترويسات دي لتحديد هوية التطبيق
        headers["HTTP-Referer"] = "https://github.com/hemapyro11-maker/Newchalange"
        headers["X-Title"] = "Nezuko"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    data = _post_json(
        f"{prov.base_url}/chat/completions", payload, headers, prov.timeout
    )
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(data.get("error", {}).get("message", "رد من غير choices"))
    return choices[0].get("message", {}).get("content", "") or ""


def _call_gemini(prov: Provider, model: str, messages: list[dict],
                 temperature: float, max_tokens: int) -> str:
    """Gemini بصيغته الخاصة: أدوار user/model، والـ system منفصل."""
    key = get_key(prov.name)
    if not key:
        raise RuntimeError("مفيش مفتاح Gemini")
    contents = []
    system_bits = []
    for msg in messages:
        role = msg.get("role")
        text = msg.get("content", "")
        if role == "system":
            system_bits.append(text)
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": text}],
        })
    payload: dict = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_bits:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_bits)}]}
    url = f"{prov.base_url}/models/{model}:generateContent?key={key}"
    data = _post_json(url, payload, {"Content-Type": "application/json"}, prov.timeout)
    candidates = data.get("candidates") or []
    if not candidates:
        reason = data.get("promptFeedback", {}).get("blockReason", "")
        raise RuntimeError(f"مفيش رد{f' ({reason})' if reason else ''}")
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


# ── نسخة واحدة مشتركة ────────────────────────────────────────────────

_brain: Brain | None = None


def get_brain() -> Brain:
    global _brain
    with _lock:
        if _brain is None:
            _brain = Brain()
        return _brain


def reset_brain() -> None:
    """للاختبارات — بيجبر إعادة بناء الحالة من القرص."""
    global _brain
    with _lock:
        _brain = None
