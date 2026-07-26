"""
benchmark.py — قياس حقيقي لنيزوكو بدل الأرقام المفبركة.

**ليه ده موجود:** لما تسأل "نيزوكو ذكية قد إيه؟" الإجابة الأمينة الوحيدة
هي قياس. أي "نسبة ذكاء" بتتقال من غير تشغيل حاجة هي رقم مخترع شكله
موثوق ومعناه صفر.

الحاجات اللي بتتقاس هنا كلها **قابلة للتحقق** — يعني تقدر تعيد تشغيل
الاختبار وتقارن، وتشوف الرقم بيتحرك لما تغيّر حاجة:

  1. نسبة الحل المحلي   — كام % من الكلام بيتحل بصفر حصة
  2. دقة فهم النية      — بيختار الأمر الصح ولا لأ (مجموعة معلّمة)
  3. تغطية القاموس      — كام أمر ليه صيغة كلام محلية
  4. جودة خريطة الكود   — بتطلّع الملف الصح فوق ولا لأ
  5. زمن الاستجابة      — لكل مسار (محلي / نموذج)

المسارات المحلية بتتقاس من غير أي نداء شبكة ولا مفتاح — فينفع تشغّلها
في أي وقت وتقارن. القياسات اللي محتاجة نموذج بتتخطى لوحدها لو مفيش مخ
متظبط، وبتتعلّم كده في التقرير بدل ما تتعد صفر.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

import intents

# ── مجموعة النوايا المعلّمة ──────────────────────────────────────────
# صيغة كلام حقيقية → الأمر اللي المفروض تتحل ليه. اللغتين مقصودتين:
# نيزوكو بتدّعي إنها بتفهم الاتنين، والادعاء ده لازم يتقاس.
INTENT_CASES: list[tuple[str, str]] = [
    # عربي
    ("حلل الفيديو ده", "probe"),
    ("حوّل الفيديو ده", "convert"),
    ("اقص الفيديو", "trim"),
    ("اطلع الصوت من الفيديو", "extract_audio"),
    ("افحص الكود", "code_scan"),
    ("دور على فيروسات", "virus_scan"),
    ("اعرض المهام", "todo"),
    ("اقفل البرنامج", "quit"),
    ("عرض الأوامر", "help"),
    # إنجليزي
    ("check this file", "probe"),
    ("convert this video", "convert"),
    ("trim the video", "trim"),
    ("extract the audio", "extract_audio"),
    ("scan the code", "code_scan"),
    ("scan for viruses", "virus_scan"),
    ("show my tasks", "todo"),
    ("list the commands", "help"),
]

# أخطاء إملائية. دي **طبقة تانية** (difflib في core_engine) مش القاموس،
# فبتتقاس لوحدها — خلطهم كان بيدّي رقم غلط عن الاتنين.
TYPO_CASES: list[tuple[str, str]] = [
    ("hlp", "help"),
    ("porbe", "probe"),
    ("convrt", "convert"),
    ("thumbnial", "thumbnail"),
    ("sessoins", "sessions"),
]

# صيغ المفروض **ماتتحلش** محليًا — كلام حر محتاج نموذج. لو القاموس
# حلّها يبقى بيطابق بزيادة، وده أسوأ من إنه ميطابقش: بينفذ حاجة غلط.
SHOULD_NOT_MATCH: list[str] = [
    "إزيك عاملة إيه النهاردة",
    "افتكرلي إني لازم أكلم أحمد بكرة",
    "what do you think about this design",
    "اشرحلي الفرق بين البروتوكولين",
    "why is the sky blue",
]


@dataclass
class Result:
    name: str
    value: float
    unit: str
    detail: str = ""
    skipped: bool = False
    failures: list[str] = field(default_factory=list)


def _known_commands(engine) -> set[str]:
    return {c.name for c in engine.registry.list_commands()}


# ── 1+2: فهم النية ───────────────────────────────────────────────────

def measure_intent_accuracy(engine) -> Result:
    """بيختار الأمر الصح؟ بيتقاس على المسارات المحلية بس — صفر حصة."""
    known = _known_commands(engine)
    hits, failures = 0, []
    for phrase, expected in INTENT_CASES:
        if expected not in known:
            continue
        match = intents.resolve(phrase, known)
        got = match.command if match else None
        if got == expected:
            hits += 1
        else:
            failures.append(f"{phrase!r} → {got or 'no match'} (wanted {expected})")
    total = sum(1 for _p, e in INTENT_CASES if e in known)
    pct = (hits / total * 100) if total else 0.0
    return Result(
        "Intent accuracy (local)", pct, "%",
        f"{hits}/{total} phrases resolved to the right command",
        failures=failures,
    )


def measure_false_match_rate(engine) -> Result:
    """بيطابق حاجة المفروض ميطابقهاش؟ الرقم ده كل ما قل كل ما كان أحسن —
    مطابقة غلط بتنفذ أمر مقصدتوش، وده أسوأ من إنه ميفهمش."""
    known = _known_commands(engine)
    bad = [p for p in SHOULD_NOT_MATCH if intents.resolve(p, known) is not None]
    pct = len(bad) / len(SHOULD_NOT_MATCH) * 100
    return Result(
        "False local match rate", pct, "% (lower is better)",
        f"{len(bad)}/{len(SHOULD_NOT_MATCH)} free-text phrases wrongly matched",
        failures=[f"{p!r} matched but should have gone to the brain" for p in bad],
    )


def measure_typo_correction(engine) -> Result:
    """التصحيح الإملائي — طبقة difflib، مش القاموس. بتشتغل دايمًا
    وبصفر حصة، فبتستاهل رقم لوحدها."""
    import difflib

    import core_engine

    known = sorted(_known_commands(engine))
    hits, failures = 0, []
    for typo, expected in TYPO_CASES:
        if expected not in known:
            continue
        close = difflib.get_close_matches(
            typo, known, n=1, cutoff=core_engine.FUZZY_CUTOFF
        )
        if close and close[0] == expected:
            hits += 1
        else:
            failures.append(f"{typo!r} → {close[0] if close else 'no match'} (wanted {expected})")
    total = sum(1 for _t, e in TYPO_CASES if e in known)
    return Result(
        "Typo correction", (hits / total * 100) if total else 0.0, "%",
        f"{hits}/{total} misspellings mapped to the right command",
        failures=failures,
    )


def measure_local_resolution(engine) -> Result:
    """نسبة الكلام اللي بيتحل بصفر حصة. ده الرقم اللي بيحدد الحصة
    بتخلص إمتى — كل حاجة بتتحل محليًا مبتكلفش حاجة أبدًا."""
    known = _known_commands(engine)
    corpus = [p for p, _ in INTENT_CASES] + SHOULD_NOT_MATCH
    local = sum(1 for p in corpus if intents.resolve(p, known) is not None)
    return Result(
        "Resolved locally (zero quota)", local / len(corpus) * 100, "%",
        f"{local}/{len(corpus)} of a mixed corpus needed no model call",
    )


def measure_dictionary_coverage(engine) -> Result:
    rep = intents.coverage_report(_known_commands(engine))
    covered = rep["dictionary"] + rep["learned"]
    total = rep["total"] or 1
    return Result(
        "Command dictionary coverage", covered / total * 100, "%",
        f"{covered}/{total} registered commands reachable in plain language",
    )


# ── 3: خريطة الكود ───────────────────────────────────────────────────

def measure_repo_map(engine) -> Result:
    """الخريطة بتطلّع الملف الصح فوق؟

    بنبني مشروع صغير معروف الإجابة: ملف بينادي عليه الكل، وملف تايه.
    لو الترتيب طلّع التايه فوق، الخريطة مش بتضيف حاجة.
    """
    import tempfile
    import pathlib
    import repomap

    if not repomap.available():
        return Result("Repo map ranking", 0.0, "%",
                      "tree-sitter not installed", skipped=True)

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "core.py").write_text("def shared():\n    return 1\n", encoding="utf-8")
        (root / "orphan.py").write_text("def alone():\n    return 2\n", encoding="utf-8")
        for i in range(6):
            (root / f"u{i}.py").write_text(
                "from core import shared\n\ndef go():\n    return shared()\n",
                encoding="utf-8",
            )
        repomap.reset_cache()
        out = repomap.build(root, budget_chars=4000)

    checks = {
        "hub ranked above orphan":
            "core.py" in out and "orphan.py" in out
            and out.index("core.py") < out.index("orphan.py"),
        "definitions are listed": "shared" in out,
        "stays within budget": len(out) <= 5000,
    }
    passed = sum(checks.values())
    return Result(
        "Repo map ranking", passed / len(checks) * 100, "%",
        f"{passed}/{len(checks)} ranking properties held",
        failures=[k for k, v in checks.items() if not v],
    )


# ── 4: الزمن ─────────────────────────────────────────────────────────

def measure_local_latency(engine) -> Result:
    """زمن المسار المحلي. ده اللي بتحسه في 90% من الاستخدام."""
    known = _known_commands(engine)
    phrases = [p for p, _ in INTENT_CASES]
    times = []
    for phrase in phrases:
        start = time.perf_counter()
        intents.resolve(phrase, known)
        times.append((time.perf_counter() - start) * 1000)
    return Result(
        "Local resolution latency", statistics.median(times), "ms (median)",
        f"over {len(times)} phrases, p95 {sorted(times)[int(len(times) * .95) - 1]:.2f}ms",
    )


def measure_brain_latency(engine) -> Result:
    """زمن نداء النموذج. بيتخطى لو مفيش مخ — منعدّهوش صفر."""
    import brain

    b = brain.get_brain()
    if not b.ready():
        return Result("Model round-trip", 0.0, "s",
                      "no brain configured — run brain_setup", skipped=True)
    start = time.perf_counter()
    reply = b.chat([{"role": "user", "content": "Reply with the single word: ok"}])
    elapsed = time.perf_counter() - start
    if not reply:
        return Result("Model round-trip", 0.0, "s",
                      f"call failed: {reply.error}", skipped=True)
    return Result("Model round-trip", elapsed, "s", f"via {reply.label}")



# ── 4: تعديل الكود ───────────────────────────────────────────────────

EDIT_CASES = [
    # (وصف، محتوى الملف، نص البحث، البديل، المتوقع)
    ("simple replace", "def go():\n    return 1\n", "return 1", "return 2", "ok"),
    ("indented match", "class A:\n    def m(self):\n        return 1\n",
     "        return 1", "        return 2", "ok"),
    ("multi-line match", "a = 1\nb = 2\nc = 3\n", "a = 1\nb = 2", "a = 9\nb = 8", "ok"),
    ("missing text is refused", "x = 1\n", "y = 2", "y = 3", "refused"),
    ("ambiguous match is refused", "x = 1\ny = 2\nx = 1\n", "x = 1", "x = 9", "refused"),
]


def measure_edit_correctness(engine) -> Result:
    """التعديل بيقع في الحالات الصح، وبيرفض في الحالات اللي المفروض
    يرفض فيها. الرفض هنا **نجاح** مش فشل — تعديل المكان الغلط أسوأ من
    عدم التعديل لأنه بيعدي من غير ما حد ياخد باله."""
    import tempfile
    import pathlib as _pl

    try:
        import edit_plugin
    except ImportError:
        return Result("Code edit correctness", 0.0, "%",
                      "edit_plugin not loaded", skipped=True)

    class _Ctx:
        def __init__(self, raw, args):
            self.raw, self.args, self.engine = raw, args, engine

    hits, failures = 0, []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (label, body, search, replace, expect) in enumerate(EDIT_CASES):
            path = _pl.Path(tmp) / f"case{i}.py"
            path.write_text(body, encoding="utf-8")
            raw = (f"edit_file {path}\n<<<<<<< SEARCH\n{search}\n"
                   f"=======\n{replace}\n>>>>>>> REPLACE")
            out = edit_plugin._cmd_edit_file(_Ctx(raw, [str(path)]))
            applied = out.startswith("✅")
            after = path.read_text(encoding="utf-8")
            if expect == "ok":
                good = applied and replace.strip() in after
            else:
                good = (not applied) and after == body
            if good:
                hits += 1
            else:
                failures.append(f"{label}: expected {expect}, got {out.splitlines()[0][:60]!r}")
    return Result(
        "Code edit correctness", hits / len(EDIT_CASES) * 100, "%",
        f"{hits}/{len(EDIT_CASES)} edit cases behaved correctly "
        "(applying when it should, refusing when it should)",
        failures=failures,
    )


def measure_edit_safety(engine) -> Result:
    """ضمانات مكتوبة في الكود مش في التوثيق: أوامر الكتابة مستحيل
    تتحط في المسموح التلقائي، والتعديل بياخد نسخة احتياطية."""
    import tempfile
    import pathlib as _pl

    import permissions

    try:
        import edit_plugin
    except ImportError:
        return Result("Edit safety guarantees", 0.0, "%", "edit_plugin not loaded",
                      skipped=True)

    class _Ctx:
        def __init__(self, raw, args):
            self.raw, self.args, self.engine = raw, args, engine

    checks = {}
    for cmd in ("edit_file", "create_file"):
        ok, _msg = permissions.allow(cmd)
        checks[f"{cmd} cannot be auto-allowed"] = (ok is False)

    with tempfile.TemporaryDirectory() as tmp:
        path = _pl.Path(tmp) / "a.py"
        path.write_text("x = 1\n", encoding="utf-8")
        raw = f"edit_file {path}\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"
        edit_plugin._cmd_edit_file(_Ctx(raw, [str(path)]))
        backup = path.with_suffix(path.suffix + edit_plugin._BACKUP_SUFFIX)
        checks["a backup is written before editing"] = backup.is_file()
        checks["the backup holds the original"] = (
            backup.is_file() and backup.read_text(encoding="utf-8") == "x = 1\n"
        )

        new = _pl.Path(tmp) / "b.py"
        new.write_text("keep me\n", encoding="utf-8")
        edit_plugin._cmd_create_file(_Ctx(f"create_file {new} overwritten", [str(new)]))
        checks["create_file refuses to overwrite"] = (
            new.read_text(encoding="utf-8") == "keep me\n"
        )

    passed = sum(checks.values())
    return Result(
        "Edit safety guarantees", passed / len(checks) * 100, "%",
        f"{passed}/{len(checks)} safety properties hold",
        failures=[k for k, v in checks.items() if not v],
    )


def measure_tool_call_parsing(engine) -> Result:
    """نداء الأداة بيوصل للأمر كامل؟ الأوامر متعددة الأسطر (edit_file)
    بتقرا جسمها من ctx.raw — لو الفصل قصّ عند سطر TOOL، بيوصلها اسم
    الملف وبس."""
    import core_engine

    cases = {
        "single-line call parses": (
            "TOOL: echo hi", "echo", ["hi"], None),
        "multi-line body survives": (
            "TOOL: edit_file a.py\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            "edit_file", ["a.py"], "SEARCH"),
        "quoted paths survive": (
            'TOOL: probe "My Files/a.mp4"', "probe", ["My Files/a.mp4"], None),
        "a question suppresses the tool": ("ASK: which one?\nTOOL: echo x", None, None, None),
    }
    passed, failures = 0, []
    for label, (reply, want_name, want_args, want_in_raw) in cases.items():
        _body, tool, _q = core_engine.AssistantEngine._split_directives(reply)
        if want_name is None:
            good = tool is None
        else:
            good = bool(tool) and tool[0] == want_name and tool[1] == want_args
            if good and want_in_raw:
                good = want_in_raw in tool[2]
        if good:
            passed += 1
        else:
            failures.append(label)
    return Result(
        "Tool call parsing", passed / len(cases) * 100, "%",
        f"{passed}/{len(cases)} parsing properties hold",
        failures=failures,
    )


# ── 5: جودة الاستدلال (محتاج مخ متظبط) ──────────────────────────────
# أسئلة إجابتها **قابلة للتحقق آليًا** — مش رأي ولا ذوق. ده شرط عشان
# الرقم يبقى قياس مش انطباع. كل سؤال محتاج خطوتين على الأقل، فمينفعش
# يتحل بالاسترجاع.

REASONING_CASES: list[tuple[str, str]] = [
    ("A shelf holds 3 boxes. Each box holds 4 packs. Each pack holds 6 pens. "
     "How many pens in total? Reply with the number only.", "72"),
    ("A shirt costs 80 after a 20% discount. What was the original price? "
     "Reply with the number only.", "100"),
    ("If all Bloops are Razzies and all Razzies are Lazzies, are all Bloops "
     "necessarily Lazzies? Answer yes or no only.", "yes"),
    ("A train leaves at 14:45 and the journey takes 2 hours 40 minutes. "
     "What time does it arrive, in 24-hour HH:MM? Reply with the time only.",
     "17:25"),
    ("I have 5 apples, eat 2, then buy twice as many as I have left. "
     "How many do I have? Reply with the number only.", "9"),
    ("عندي 3 صناديق، كل صندوق فيه 4 علب، وكل علبة فيها 6 أقلام. "
     "كام قلم إجمالي؟ رد بالرقم بس.", "72"),
    ("قميص سعره 80 بعد خصم 20%. كان سعره كام قبل الخصم؟ رد بالرقم بس.", "100"),
]


def _answer_matches(reply: str, expected: str) -> bool:
    """مطابقة متساهلة مع الشكل، صارمة مع القيمة — النموذج ممكن يكتب
    "72 pens" أو "**72**"، وده صح. بس 720 غلط."""
    import re as _re

    low = reply.strip().lower()
    if expected in ("yes", "no"):
        return bool(_re.search(rf"\b{expected}\b", low)) or (
            expected == "yes" and "أيوه" in low or expected == "no" and "لأ" in low
        )
    if ":" in expected:
        return expected in low
    return bool(_re.search(rf"(?<![\d.]){_re.escape(expected)}(?![\d.])", low))


def _brain_is_really_reachable(b) -> tuple[bool, str]:
    """`ready()` مش كفاية: Ollama مزوّد محلي مالوش مفتاح، فبيتحسب
    "جاهز" حتى لو مش مشغّل أصلاً. بنعمل نداء تجريبي واحد ونشوف.

    ده مهم لأن الفرق بين "الموديل غبي" و"مفيش موديل" هو الفرق بين
    رقم صادق ورقم كاذب — و0% من غير تفرقة بيقول الأولانية.
    """
    if not b.ready():
        return False, "no brain configured — run brain_setup"
    probe = b.chat([{"role": "user", "content": "Reply with: ok"}])
    if not probe:
        return False, f"no brain actually reachable ({probe.error})"
    return True, ""


def measure_reasoning(engine) -> Result:
    """دقة الاستدلال على أسئلة إجابتها معروفة.

    **ده الرقم اللي بيحتاج مفتاح فعلاً.** من غير مخ متظبط بيتخطى —
    وده أمانة: صفر هنا معناه "الموديل غبي"، والحقيقة "مفيش موديل".
    """
    import brain

    b = brain.get_brain()
    alive, why = _brain_is_really_reachable(b)
    if not alive:
        return Result("Reasoning accuracy", 0.0, "%",
                      f"{why} — then run: benchmark --full", skipped=True)

    hits, failures = 0, []
    for question, expected in REASONING_CASES:
        reply = b.chat([{"role": "user", "content": question}], temperature=0.0)
        if not reply:
            failures.append(f"{question[:40]}… → call failed: {reply.error}")
            continue
        if _answer_matches(reply.text, expected):
            hits += 1
        else:
            got = reply.text.strip().replace("\n", " ")[:50]
            failures.append(f"{question[:40]}… → {got!r} (wanted {expected})")
    return Result(
        "Reasoning accuracy", hits / len(REASONING_CASES) * 100, "%",
        f"{hits}/{len(REASONING_CASES)} verifiable questions answered correctly "
        f"(costs {len(REASONING_CASES)} calls)",
        failures=failures,
    )


def measure_reasoning_verified(engine) -> Result:
    """نفس الأسئلة بالمراجعة الذاتية (CoVe). المقارنة بين الرقمين هي
    الجواب الحقيقي على "هل المراجعة بتفرق؟" — بدل ما نستشهد بورقة."""
    import brain

    b = brain.get_brain()
    alive, why = _brain_is_really_reachable(b)
    if not alive:
        return Result("Reasoning, self-verified", 0.0, "%", why, skipped=True)

    hits, failures = 0, []
    for question, expected in REASONING_CASES:
        reply = b.verified_chat([{"role": "user", "content": question}])
        if not reply:
            failures.append(f"{question[:40]}… → call failed")
            continue
        if _answer_matches(reply.text, expected):
            hits += 1
        else:
            got = reply.text.strip().replace("\n", " ")[:50]
            failures.append(f"{question[:40]}… → {got!r} (wanted {expected})")
    return Result(
        "Reasoning, self-verified", hits / len(REASONING_CASES) * 100, "%",
        f"{hits}/{len(REASONING_CASES)} correct with verification on "
        f"(costs {len(REASONING_CASES) * 4} calls — compare against the row above)",
        failures=failures,
    )


# ── التشغيل والتقرير ─────────────────────────────────────────────────

# القياسات اللي بتنادي نموذج فعلاً — بتتخطى في الوضع السريع
_MODEL_MEASURES: tuple = ()

MEASURES = (
    measure_intent_accuracy,
    measure_typo_correction,
    measure_false_match_rate,
    measure_local_resolution,
    measure_dictionary_coverage,
    measure_repo_map,
    measure_edit_correctness,
    measure_edit_safety,
    measure_tool_call_parsing,
    measure_local_latency,
    measure_brain_latency,
    measure_reasoning,
    measure_reasoning_verified,
)

_MODEL_MEASURES = (measure_brain_latency, measure_reasoning, measure_reasoning_verified)


def run(engine, include_model: bool = True) -> list[Result]:
    results = []
    for fn in MEASURES:
        if not include_model and fn in _MODEL_MEASURES:
            continue
        try:
            results.append(fn(engine))
        except Exception as e:  # noqa: BLE001 - قياس واقع مايوقفش الباقي
            results.append(Result(fn.__name__, 0.0, "", f"errored: {e}", skipped=True))
    return results


def report(results: list[Result], show_failures: bool = True) -> str:
    lines = ["📐 Nezuko benchmark — measured, not estimated\n"]
    for r in results:
        if r.skipped:
            lines.append(f"  ⏭  {r.name:<32} skipped — {r.detail}")
            continue
        lines.append(f"  •  {r.name:<32} {r.value:>7.2f} {r.unit}")
        if r.detail:
            lines.append(f"     {r.detail}")
    if show_failures:
        broken = [(r.name, f) for r in results for f in r.failures]
        if broken:
            lines.append(f"\n  What missed ({len(broken)}):")
            for name, detail in broken[:12]:
                lines.append(f"     [{name}] {detail}")
            if len(broken) > 12:
                lines.append(f"     … and {len(broken) - 12} more")
    lines.append(
        "\n  Every number above comes from running the code. Re-run after a"
        "\n  change and the numbers move — that is the whole point of having"
        "\n  them instead of a made-up percentage."
    )
    return "\n".join(lines)
