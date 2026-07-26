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


# ── التشغيل والتقرير ─────────────────────────────────────────────────

MEASURES = (
    measure_intent_accuracy,
    measure_typo_correction,
    measure_false_match_rate,
    measure_local_resolution,
    measure_dictionary_coverage,
    measure_repo_map,
    measure_local_latency,
    measure_brain_latency,
)


def run(engine, include_model: bool = True) -> list[Result]:
    results = []
    for fn in MEASURES:
        if not include_model and fn is measure_brain_latency:
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
