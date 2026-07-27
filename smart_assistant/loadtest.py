"""
loadtest.py — أداة اختبار حمل حقيقية لنيزوكو: بتقيس أداء المكونات
الحرجة (Core Engine queue، قواعد بيانات، تحليل بيانات، فحص أمان،
مصغرات، تحليل مشاعر) تحت أحمال حقيقية (مش وهمية)، وبتوريك بالضبط
النطاق العملي اللي كل مكون بيشتغل فيه كويس والنقطة اللي يبدأ يبطّئ
عندها.

**ده مش pytest** — ده benchmark script مستقل، بيتشغل يدويًا:

    python loadtest.py [scenario_name ...]   # سيناريوهات محددة
    python loadtest.py                        # كل السيناريوهات

كل سيناريو بيرجع وقت التنفيذ الفعلي وذروة استهلاك الذاكرة (عبر
resource.getrusage — POSIX بس؛ بيتخطى القياس بأمان على ويندوز).
"""
from __future__ import annotations

import csv
import gc
import json
import pathlib
import random
import sqlite3
import sys
import time

try:
    import resource
    HAS_RESOURCE = True
except ImportError:  # ويندوز مفيهوش resource module
    HAS_RESOURCE = False

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins"))

WORKDIR = ROOT / ".loadtest_tmp"


class Ctx:
    """CommandContext خفيف لاستدعاء دوال الـ plugins مباشرة من غير Core Engine."""
    def __init__(self, raw: str, args: list[str]):
        self.raw = raw
        self.args = args
        self.engine = None


def _peak_rss_mb() -> float | None:
    if not HAS_RESOURCE:
        return None
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return kb / 1024  # على لينكس ru_maxrss بالـ KB


def _timed(fn, *args, **kwargs):
    gc.collect()
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    return result, elapsed


def _report(name: str, scale_desc: str, elapsed: float, extra: str = "") -> dict:
    rss = _peak_rss_mb()
    rss_str = f"{rss:.0f}MB" if rss is not None else "N/A"
    line = f"  {name}: {scale_desc} في {elapsed:.3f}s (ذروة RSS: {rss_str}){' — ' + extra if extra else ''}"
    print(line)
    return {"name": name, "scale": scale_desc, "seconds": round(elapsed, 3), "peak_rss_mb": rss, "note": extra}


# ── سيناريو 1: Core Engine — طابور تنفيذ حقيقي بخيط خلفي حقيقي ──────

def scenario_core_engine_queue(results: list[dict]):
    print("\n📦 Core Engine — طابور تنفيذ (submit + خيط خلفي حقيقي)")
    import core_engine
    from core_engine import AssistantEngine

    # نمنع الاختبار من الكتابة على smart_assistant/skills.json الحقيقي
    # بتاع المستخدم — بنوجّه default_state_dir لمجلد مؤقت طول الاختبار بس.
    original_state_dir = core_engine.default_state_dir
    core_engine.default_state_dir = lambda: WORKDIR

    for n in (1_000, 10_000):
        engine = AssistantEngine(plugins_dirs=[WORKDIR / "no_plugins"])
        engine.start()
        t0 = time.perf_counter()
        for _ in range(n):
            engine.submit("echo hi")
        deadline = time.time() + 60
        while not engine._queue.empty() and time.time() < deadline:
            time.sleep(0.01)
        timed_out = not engine._queue.empty()  # لازم يتفحص قبل stop() — stop() نفسها بتحط عنصر جديد في الطابور (__stop__)
        time.sleep(0.15)  # نستنى آخر أمر يخلص فعليًا يتنفذ
        elapsed = time.perf_counter() - t0
        engine.stop()
        throughput = n / elapsed if elapsed else 0
        results.append(_report(
            "core_engine_queue", f"{n:,} أمر", elapsed,
            f"{throughput:.0f} أمر/ثانية"
            + (" ⚠️ التايم آوت — الطابور ماخلصش!" if timed_out else ""),
        ))
        # log_history لازم يفضل محدود بـ maxlen=300 مهما كان عدد الأوامر
        assert len(engine.log_history) <= 300, "BUG: log_history تخطى الحد الأقصى!"

    core_engine.default_state_dir = original_state_dir


# ── سيناريو 2: database_plugin — SQLite بعدد صفوف كبير ──────────────

def scenario_database(results: list[dict]):
    print("\n📦 database_plugin — SQLite")
    import database_plugin as dbp

    for n_rows in (100_000, 1_000_000):
        db_path = WORKDIR / f"loadtest_{n_rows}.sqlite"
        db_path.unlink(missing_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, score REAL)")
        rows = [(i, f"user{i}", f"user{i}@example.com", random.random() * 100) for i in range(n_rows)]
        conn.executemany("INSERT INTO users (id, name, email, score) VALUES (?, ?, ?, ?)", rows)
        conn.commit()
        conn.close()

        _, t_schema = _timed(dbp._cmd_db_schema, Ctx("db_schema", [str(db_path)]))
        # db_query بياخد الـ SQL من ctx.raw (مش ctx.args) عشان يتفادى
        # مشاكل shlex مع quotes جوه الجملة — لازم raw يبقى مبني صح.
        query_raw = f"db_query {db_path} SELECT COUNT(*) FROM users"
        _, t_query = _timed(dbp._cmd_db_query, Ctx(query_raw, [str(db_path), "SELECT COUNT(*) FROM users"]))
        out_csv = WORKDIR / f"export_{n_rows}.csv"
        _, t_export = _timed(dbp._cmd_db_export_csv, Ctx("db_export_csv", [str(db_path), "users", str(out_csv)]))

        results.append(_report("db_schema", f"{n_rows:,} صف", t_schema))
        results.append(_report("db_query (COUNT)", f"{n_rows:,} صف", t_query))
        results.append(_report("db_export_csv", f"{n_rows:,} صف", t_export))
        db_path.unlink(missing_ok=True)
        out_csv.unlink(missing_ok=True)


# ── سيناريو 3: data_science_plugin — CSV كبير ────────────────────────

def scenario_data_science(results: list[dict]):
    print("\n📦 data_science_plugin — CSV")
    import data_science_plugin as dsp
    if not dsp.PANDAS_AVAILABLE:
        print("   ⏭ pandas مش متثبت — اتخطى")
        return

    for n_rows in (100_000, 1_000_000):
        csv_path = WORKDIR / f"loadtest_{n_rows}.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "value_a", "value_b", "category"])
            cats = ["A", "B", "C", "D"]
            for i in range(n_rows):
                writer.writerow([i, random.random() * 1000, random.random() * 500, random.choice(cats)])

        _, t_describe = _timed(dsp._cmd_csv_describe, Ctx("csv_describe", [str(csv_path)]))
        _, t_correlate = _timed(dsp._cmd_csv_correlate, Ctx("csv_correlate", [str(csv_path)]))
        results.append(_report("csv_describe", f"{n_rows:,} صف", t_describe))
        results.append(_report("csv_correlate", f"{n_rows:,} صف", t_correlate))
        csv_path.unlink(missing_ok=True)


# ── سيناريو 4: security_scan_plugin — عدد ملفات كبير + حد الحجم ────

def scenario_security_scan(results: list[dict]):
    print("\n📦 security_scan_plugin — code_scan على شجرة ملفات كبيرة")
    import security_scan_plugin as ssp

    for n_files in (500, 5_000):
        proj_dir = WORKDIR / f"proj_{n_files}"
        proj_dir.mkdir(parents=True, exist_ok=True)
        for i in range(n_files):
            (proj_dir / f"mod_{i}.py").write_text(
                f"def f{i}(x):\n    return x + {i}\n\nimport os\nos.system('echo {i}')\n"
            )
        _, elapsed = _timed(ssp._cmd_code_scan, Ctx("code_scan", [str(proj_dir)]))
        results.append(_report("code_scan", f"{n_files:,} ملف .py", elapsed))
        for f in proj_dir.glob("*.py"):
            f.unlink()
        proj_dir.rmdir()

    # حد MAX_FILE_SIZE_FOR_SCAN: نتأكد إن ملف أكبر من الحد بيتخطى فورًا
    # (بدون تحميله كامل في الذاكرة) بدل ما ياخد وقت طويل.
    big_file = WORKDIR / "huge.py"
    with big_file.open("w") as f:
        chunk = "# padding line " + "x" * 200 + "\n"
        target_bytes = ssp.MAX_FILE_SIZE_FOR_SCAN + 1_000_000  # أكبر من الحد بـ 1MB
        written = 0
        while written < target_bytes:
            f.write(chunk)
            written += len(chunk)
    _, elapsed = _timed(ssp._cmd_code_scan, Ctx("code_scan", [str(big_file)]))
    results.append(_report(
        "code_scan (ملف أكبر من MAX_FILE_SIZE_FOR_SCAN)",
        f"{big_file.stat().st_size / 1024 / 1024:.1f}MB", elapsed,
        "لازم يتخطى فورًا من غير ما يحمّل الملف",
    ))
    big_file.unlink()


# ── سيناريو 5: thumbnail_plugin — صورة كبيرة ─────────────────────────

def scenario_thumbnail(results: list[dict]):
    print("\n📦 thumbnail_plugin — صورة عالية الدقة")
    import thumbnail_plugin as tp
    if not tp.PIL_AVAILABLE:
        print("   ⏭ Pillow مش متثبت — اتخطى")
        return
    from PIL import Image

    for size in ((1920, 1080), (6000, 4000)):
        img_path = WORKDIR / f"big_{size[0]}x{size[1]}.png"
        Image.new("RGB", size, "#3366cc").save(img_path)
        _, t_analyze = _timed(tp._cmd_thumbnail_analyze, Ctx("thumbnail_analyze", [str(img_path)]))
        out_path = WORKDIR / f"thumb_out_{size[0]}.jpg"
        _, t_generate = _timed(
            tp._cmd_thumbnail_generate, Ctx("thumbnail_generate", [str(img_path), "اختبار حمل", str(out_path)])
        )
        results.append(_report("thumbnail_analyze", f"{size[0]}x{size[1]}", t_analyze))
        results.append(_report("thumbnail_generate", f"{size[0]}x{size[1]} → 1280x720", t_generate))
        img_path.unlink()
        out_path.unlink(missing_ok=True)


# ── سيناريو 6: community_manager_plugin — عدد تعليقات كبير ──────────

def scenario_community_manager(results: list[dict]):
    print("\n📦 community_manager_plugin — تحليل مشاعر/سبام لعدد تعليقات كبير")
    import community_manager_plugin as cmp

    sample_comments = [
        "الفيديو ده حلو جدا شكرا", "مش عاجبني خالص الشرح ده", "تمام كده",
        "اشترك في قناتي دلوقتي https://spam.example.com", "رائع تحفة استفدت كتير",
        "وحش جدا ملوش لازمة", "this video is amazing thanks",
    ]
    for n_comments in (10_000, 100_000):
        comments_path = WORKDIR / f"comments_{n_comments}.txt"
        with comments_path.open("w", encoding="utf-8") as f:
            for i in range(n_comments):
                f.write(random.choice(sample_comments) + f" {i}\n")

        _, t_sentiment = _timed(cmp._cmd_comment_sentiment, Ctx("comment_sentiment", [str(comments_path)]))
        _, t_spam = _timed(cmp._cmd_comment_spam_detect, Ctx("comment_spam_detect", [str(comments_path)]))
        results.append(_report("comment_sentiment", f"{n_comments:,} تعليق", t_sentiment))
        results.append(_report("comment_spam_detect", f"{n_comments:,} تعليق", t_spam))
        comments_path.unlink()


# ── سيناريو 7: youtube_seo_plugin — استخراج كلمات مفتاحية من نص كبير ─

def scenario_youtube_seo(results: list[dict]):
    print("\n📦 youtube_seo_plugin — استخراج كلمات مفتاحية من نص كبير")
    import youtube_seo_plugin as ysp

    words = ["بايثون", "تعلم", "برمجة", "فيديو", "شرح", "تطبيق", "كود", "مشروع", "python", "learn"]
    for n_words in (10_000, 200_000):
        text = " ".join(random.choice(words) for _ in range(n_words))
        title = "تعلم بايثون للمبتدئين"
        _, elapsed = _timed(ysp._extract_keywords, title, text)
        results.append(_report("_extract_keywords", f"{n_words:,} كلمة", elapsed))


SCENARIOS = {
    "core_engine": scenario_core_engine_queue,
    "database": scenario_database,
    "data_science": scenario_data_science,
    "security_scan": scenario_security_scan,
    "thumbnail": scenario_thumbnail,
    "community_manager": scenario_community_manager,
    "youtube_seo": scenario_youtube_seo,
}


def main():
    requested = sys.argv[1:] or list(SCENARIOS)
    unknown = [s for s in requested if s not in SCENARIOS]
    if unknown:
        print(f"❌ سيناريوهات غير معروفة: {unknown}\nالمتاح: {list(SCENARIOS)}")
        sys.exit(1)

    WORKDIR.mkdir(exist_ok=True)
    results: list[dict] = []
    t_start = time.perf_counter()
    try:
        for name in requested:
            SCENARIOS[name](results)
    finally:
        import shutil
        shutil.rmtree(WORKDIR, ignore_errors=True)

    total = time.perf_counter() - t_start
    print(f"\n✅ خلص كل حاجة في {total:.1f}s إجمالي")

    report_path = ROOT / "loadtest_results.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📄 النتائج التفصيلية في {report_path}")


if __name__ == "__main__":
    main()
