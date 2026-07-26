"""
bot_core.py — منطق البوت بدون GUI
"""
import asyncio
import logging
import random
import re
import time
import threading
from collections import Counter

log = logging.getLogger("bot")

UI_NOISE = {
    "ano","check","send","typing","online","offline","a few seconds",
    "just now","new chat","end chat","start chat","conversations",
    "pending","unread","notifications","home","memes","apps","share",
    "people","rooms","all","search","eagle_eye123","okay","ok","pro",
    # أسماء أيقونات (material icons) بتتقرا كنص عادي جوه الصفحة
    "person_add","volume_up","volume_down","volume_off","close","menu",
    "more_vert","settings","arrow_back","end chat (esc)",
    "this user account has changed name or deleted itself.",
}

# يقبل f / m / f18 / 18f / m22 / 22m ...
# لكن مش كلمات زي "Fine"/"Maybe"/"for" اللي بتبدأ أو فيها نفس الحرف
_GENDER_TOKEN = re.compile(r"^\d{0,3}[fm]\d{0,3}$")
_STRIP_CHARS  = ".,!?؟،:؛-_()[]{}\"'*"
_QUESTION_MARKS = "?؟"

# كلمات صريحة بتحدد الجنس. متعمد إننا مانحطش كلمات بتستخدم كنداء
# ("man", "bro", "dude", "guys") عشان "hey man" مش تعريف بالجنس.
_FEMALE_WORDS = {
    "f", "fem", "female", "girl", "girls", "woman", "women", "lady", "ladies",
    "بنت", "بنوتة", "انثى", "أنثى", "فتاة",
}
_MALE_WORDS = {
    "m", "male", "boy", "boys",
    "ذكر", "ولد", "راجل", "رجل",
}
_GENDER_WORDS = _FEMALE_WORDS | _MALE_WORDS

def is_noise(text: str) -> bool:
    t = text.strip().lower()
    if t in UI_NOISE:
        return True
    if len(t) <= 3 and t.isalpha() and t not in _GENDER_WORDS:
        return True
    if any(kw in t for kw in ["seconds","minutes","hours","ago","just now","level","reached"]):
        return True
    return False

def classify(text: str) -> str:
    """
    بيرجّع "stay" (بنت) أو "skip" (شاب) أو "unknown".

    مهم: أي سطر بيسأل ("m or f?" / "r u f?") بيرجع unknown، لأنه سؤال منهم
    مش تعريف بنفسهم — ولو السطر فيه الجنسين مع بعض فهو غامض برضه، فنكمل
    استنى الرد الحقيقي بدل ما نتخطى بنت بالغلط.
    """
    t = text.strip()
    if not t:
        return "unknown"
    if t[-1] in _QUESTION_MARKS:
        return "unknown"

    found = set()
    for tok in t.lower().split():
        tok = tok.strip(_STRIP_CHARS)
        if not tok:
            continue
        if tok in _FEMALE_WORDS:
            found.add("f")
        elif tok in _MALE_WORDS:
            found.add("m")
        elif _GENDER_TOKEN.match(tok):
            found.add("f" if "f" in tok else "m")

    if len(found) != 1:
        return "unknown"
    return "stay" if "f" in found else "skip"


class Y99Bot:
    def __init__(self, settings: dict, on_log=None, on_stats=None, on_status=None):
        self.settings   = settings
        self.on_log     = on_log     or (lambda msg, color="white": None)
        self.on_stats   = on_stats   or (lambda s, sk, st: None)
        self.on_status  = on_status  or (lambda s: None)
        self._stop_flag = threading.Event()
        self._thread    = None
        self._next_requested = False
        self._awaiting_next   = False
        self.total = self.skipped = self.stayed = 0

    # ── public ─────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._next_requested = False
        self._awaiting_next  = False
        self.total = self.skipped = self.stayed = 0
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        self.on_status("stopped")
        self.on_log("⏹  تم الإيقاف", "orange")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── internal ────────────────────────────────────────────────────────
    def _run_loop(self):
        asyncio.run(self._main())

    async def _main(self):
        self.on_status("starting")
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.on_log("❌  Playwright مش متثبّت. شغّل:", "red")
            self.on_log("    pip install playwright", "red")
            self.on_log("    python -m playwright install chromium", "red")
            self.on_status("error")
            return

        self.on_log("🌐  بفتح المتصفح...", "cyan")
        had_error = False
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)
                try:
                    page = await browser.new_page()
                    await page.goto("https://y99.in/web/desktop/discover",
                                    wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(4)
                    await self._click_start(page)
                    self.on_status("running")
                    self.on_log("🚀  البوت شغال!", "green")
                    await asyncio.sleep(2)
                    await self._loop(page)
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        except Exception as e:
            had_error = True
            self.on_log(f"❌  خطأ: {e}", "red")
            self.on_status("error")
        if not had_error:
            self.on_status("stopped")

    async def _loop(self, page):
        while not self._stop_flag.is_set():
            self.total += 1
            self.on_stats(self.total, self.skipped, self.stayed)
            self.on_log(f"━━  شات #{self.total}", "gray")

            # لازم ناخد الـ baseline قبل ما نبعت، عشان لو التانية ردت بسرعة
            # (زي رد بحرف واحد "F") ما نضيعش ردها باعتباره جزء من الصفحة الأصلية
            text_before = await self._get_text(page)
            send_msg = self.settings.get("send_msg", "M")
            sent = await self._send(page, send_msg)
            if not sent:
                self.on_log("🔄  مفيش اتصال → شات جديد", "gray")
                await self._next(page)
                self.skipped += 1
                self.on_stats(self.total, self.skipped, self.stayed)
                continue

            self.on_log(f"⏳  مستني رد ({self.settings.get('wait_reply',8)}ث)...", "gray")
            reply = await self._wait_reply(page, text_before, ignore_text=send_msg)

            if reply is None:
                self.on_log("⌛  مفيش رد → skip", "gray")
                await self._next(page)
                self.skipped += 1
            else:
                decision = classify(reply)
                if decision == "stay":
                    self.stayed += 1
                    self.on_stats(self.total, self.skipped, self.stayed)
                    self.on_log(f"✅  F!  فضلت في الشات", "green")
                    # نمسح أي طلب Next قديم فضل واقف من شات سابق، عشان
                    # ما نتخطاش الشات ده فورًا من غير ما نستناها
                    self._next_requested = False
                    self._awaiting_next  = True
                    self.on_status("found_f")
                    # استنى لحد ما المستخدم يضغط Next من الـ GUI
                    while not self._stop_flag.is_set():
                        await asyncio.sleep(0.5)
                        if self._next_requested:
                            self._next_requested = False
                            break
                    self._awaiting_next = False
                    # لو الإيقاف اتطلب وإحنا مستنيين، نخرج من غير ما نرجّع
                    # الحالة "running" ونلخبط الواجهة
                    if self._stop_flag.is_set():
                        break
                    await self._next(page)
                    self.on_status("running")
                else:
                    self.skipped += 1
                    self.on_stats(self.total, self.skipped, self.stayed)
                    self.on_log(f"❌  M → skip", "salmon")
                    await self._next(page)

            self.on_stats(self.total, self.skipped, self.stayed)
            await asyncio.sleep(random.uniform(0.15, 0.3))

    def request_next(self):
        """الـ GUI يضغط Next وهو في شات F. بيتجاهل أي ضغطة زيادة/متأخرة."""
        if self._awaiting_next:
            self._next_requested = True

    async def _send(self, page, text) -> bool:
        deadline = time.time() + self.settings.get("wait_connect", 5)
        while time.time() < deadline:
            if self._stop_flag.is_set():
                return False
            found = await self._focus_input(page)
            if found:
                break
            await asyncio.sleep(0.5)
        else:
            return False
        try:
            await page.keyboard.press("Control+a")
            await page.keyboard.press("Delete")
            await asyncio.sleep(0.2)
            await page.keyboard.type(text, delay=60)
            await asyncio.sleep(0.4)
            await page.keyboard.press("Enter")
            self.on_log(f"✉  بعت: {text}", "white")
            return True
        except Exception:
            return False

    async def _focus_input(self, page) -> bool:
        try:
            return await page.evaluate("""
                () => {
                    const els = [...document.querySelectorAll('input,textarea')];
                    const c = els.find(el => {
                        const ph = (el.placeholder||'').toLowerCase();
                        return !el.disabled && !el.readOnly &&
                               el.getBoundingClientRect().width > 0 &&
                               ph.includes('message');
                    });
                    if(c){c.focus();return true;}
                    return false;
                }
            """)
        except Exception:
            return False

    async def _get_text(self, page) -> str:
        try:
            return await page.evaluate("()=>document.body.innerText")
        except Exception:
            return ""

    async def _wait_reply(self, page, text_before, ignore_text=None) -> str | None:
        """
        بيتابع عدد مرات ظهور كل سطر (مش بس هل ظهر قبل كده)، عشان لو الطرف
        التاني رد بنفس النص اللي إحنا بعتناه (زي رد بـ "m" لما إحنا كمان
        بعتنا "M")، الرد بتاعه ما يتجاهلش باعتباره صدى رسالتنا احنا.
        """
        deadline = time.time() + self.settings.get("wait_reply", 8)
        baseline = Counter(l.strip() for l in text_before.splitlines() if l.strip())
        processed = Counter()
        ignore = (ignore_text or "").strip().lower()
        ignore_budget = 1 if ignore else 0  # اتجاهل ظهور واحد بس (رسالتنا احنا)

        while time.time() < deadline:
            if self._stop_flag.is_set():
                return None
            txt = await self._get_text(page)
            counts = Counter(l.strip() for l in txt.splitlines() if l.strip())
            for l, count in counts.items():
                new_occurrences = count - baseline.get(l, 0) - processed[l]
                for _ in range(max(0, new_occurrences)):
                    processed[l] += 1
                    if ignore_budget > 0 and l.lower() == ignore:
                        ignore_budget -= 1
                        continue
                    # الترتيب مهم: نصنّف الأول، عشان رد زي "fem" ما يقعش
                    # في فلتر الضوضاء (كلمة قصيرة) قبل ما نقراه كتعريف بالجنس
                    if classify(l) != "unknown":
                        self.on_log(f"📋  نص جديد: {l!r}", "lightblue")
                        return l
                    if is_noise(l):
                        continue
                    self.on_log(f"📋  نص جديد: {l!r}", "lightblue")
            await asyncio.sleep(0.6)
        return None

    async def _next(self, page):
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.15)
        try:
            await page.evaluate("""
                ()=>{
                    const b=[...document.querySelectorAll('button,a')];
                    const n=b.find(x=>/new.?chat|start.?chat|new.?random/i.test(x.innerText));
                    if(n)n.click();
                }
            """)
        except Exception:
            pass
        # قصيرة قصادنا - _send() أصلاً بيستنى لحد ما مربع الكتابة يظهر
        await asyncio.sleep(random.uniform(0.25, 0.45))

    async def _click_start(self, page):
        try:
            await page.evaluate("""
                ()=>{
                    const b=[...document.querySelectorAll('button,a')];
                    const n=b.find(x=>/start.?chat|new.?random|new.?chat/i.test(x.innerText));
                    if(n)n.click();
                }
            """)
        except Exception:
            pass
