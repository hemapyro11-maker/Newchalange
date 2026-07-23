"""
bot_core.py — منطق البوت بدون GUI
"""
import asyncio
import logging
import random
import re
import time
import threading
from playwright.async_api import async_playwright

log = logging.getLogger("bot")

UI_NOISE = {
    "ano","check","send","typing","online","offline","a few seconds",
    "just now","new chat","end chat","start chat","conversations",
    "pending","unread","notifications","home","memes","apps","share",
    "people","rooms","all","search","eagle_eye123","okay","ok","pro",
}

# "f", "F", "f18", "F 22" ... لكن مش كلمات زي "Fine"/"Maybe" اللي بتبدأ بنفس الحرف
_GENDER_TOKEN = re.compile(r"^[fm]\d{0,3}$")
_STRIP_CHARS  = ".,!?؟،:؛-_()[]{}\"'*"

def is_noise(text: str) -> bool:
    t = text.strip().lower()
    if t in UI_NOISE:
        return True
    if len(t) <= 3 and t.isalpha() and t not in ("m","f"):
        return True
    if any(kw in t for kw in ["seconds","minutes","hours","ago","just now","level","reached"]):
        return True
    return False

def classify(text: str) -> str:
    t = text.strip().lower()
    if not t:
        return "unknown"
    first = t.split()[0].strip(_STRIP_CHARS)
    if _GENDER_TOKEN.match(first):
        return "stay" if first[0] == "f" else "skip"
    return "unknown"


class Y99Bot:
    def __init__(self, settings: dict, on_log=None, on_stats=None, on_status=None):
        self.settings   = settings
        self.on_log     = on_log     or (lambda msg, color="white": None)
        self.on_stats   = on_stats   or (lambda s, sk, st: None)
        self.on_status  = on_status  or (lambda s: None)
        self._stop_flag = threading.Event()
        self._thread    = None
        self._next_requested = False
        self.total = self.skipped = self.stayed = 0

    # ── public ─────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._next_requested = False
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

            sent = await self._send(page, self.settings.get("send_msg","M"))
            if not sent:
                self.on_log("🔄  مفيش اتصال → شات جديد", "gray")
                await self._next(page)
                self.skipped += 1
                self.on_stats(self.total, self.skipped, self.stayed)
                continue

            await asyncio.sleep(0.8)
            text_after = await self._get_text(page)

            self.on_log(f"⏳  مستني رد ({self.settings.get('wait_reply',8)}ث)...", "gray")
            reply = await self._wait_reply(page, text_after)

            if reply is None:
                self.on_log("⌛  مفيش رد → skip", "gray")
                await self._next(page)
                self.skipped += 1
            else:
                decision = classify(reply)
                if decision == "stay":
                    self.stayed += 1
                    self.on_log(f"✅  F!  فضلت في الشات", "green")
                    self.on_status("found_f")
                    # استنى لحد ما المستخدم يضغط Next من الـ GUI
                    while not self._stop_flag.is_set():
                        await asyncio.sleep(0.5)
                        if self._next_requested:
                            self._next_requested = False
                            break
                    await self._next(page)
                    self.on_status("running")
                else:
                    self.skipped += 1
                    self.on_log(f"❌  M → skip", "salmon")
                    await self._next(page)

            self.on_stats(self.total, self.skipped, self.stayed)
            await asyncio.sleep(random.uniform(0.8, 1.5))

    def request_next(self):
        """الـ GUI يضغط Next وهو في شات F."""
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

    async def _wait_reply(self, page, text_after_send) -> str | None:
        deadline = time.time() + self.settings.get("wait_reply", 8)
        baseline = set(l.strip() for l in text_after_send.splitlines() if l.strip())
        seen = set()
        while time.time() < deadline:
            if self._stop_flag.is_set():
                return None
            txt = await self._get_text(page)
            for line in txt.splitlines():
                l = line.strip()
                if not l or l in baseline or l in seen:
                    continue
                seen.add(l)
                if is_noise(l):
                    continue
                self.on_log(f"📋  نص جديد: {l!r}", "lightblue")
                if classify(l) != "unknown":
                    return l
            await asyncio.sleep(0.6)
        return None

    async def _next(self, page):
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
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
        await asyncio.sleep(random.uniform(1.2, 2.0))

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
