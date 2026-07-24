"""
database_plugin.py — أدوات قواعد بيانات حقيقية عبر sqlite3 (مكتبة
بايثون القياسية، بدون أي باكدج خارجي أو خدمة سحابية مدفوعة).

الأوامر: db_schema, db_query, db_export_csv
"""
from __future__ import annotations

import csv
import pathlib
import re
import sqlite3

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(name: str) -> str | None:
    """يرجع الاسم بين علامات اقتباس مزدوجة لو identifier صالح، وإلا None
    — عشان نمنع SQL injection وقت ما إحنا نفسنا بنبني query (زي في
    db_export_csv) من اسم جدول جاي من args المستخدم."""
    if not _IDENTIFIER.match(name):
        return None
    return f'"{name}"'


def _cmd_db_schema(ctx) -> str:
    if not ctx.args:
        return "usage: db_schema <sqlite_file>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cur.fetchall()]
        if not tables:
            return "مفيش جداول في القاعدة دي"
        lines = [f"📊 {len(tables)} جدول:"]
        for table in tables:
            quoted = _quote_identifier(table)
            if quoted is None:
                continue
            cur.execute(f"PRAGMA table_info({quoted})")
            cols = cur.fetchall()
            col_desc = ", ".join(f"{c[1]} {c[2]}{' PK' if c[5] else ''}" for c in cols)
            lines.append(f"  🗂  {table} ({col_desc})")
        return "\n".join(lines)
    except sqlite3.Error as e:
        return f"❌ خطأ SQLite: {e}"
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass


def _cmd_db_query(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: db_query <sqlite_file> <SQL...>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    # نفس منطق connectors_plugin: الـ SQL بيتاخد من ctx.raw مش ctx.args
    # عشان shlex.split ممكن يبلع quotes/علامات جوه الجملة نفسها
    head_and_rest = ctx.raw.split(maxsplit=2)
    sql = head_and_rest[2].strip() if len(head_and_rest) > 2 else ""
    if not sql:
        return "usage: db_query <sqlite_file> <SQL...>"

    try:
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description is None:
            conn.commit()
            return f"✅ تم التنفيذ — {cur.rowcount} صف اتأثر"
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(200)
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(v) for v in row))
        suffix = "\n... (النتائج مقصوصة عند 200 صف)" if len(rows) == 200 else ""
        return "\n".join(lines) + suffix
    except sqlite3.Error as e:
        return f"❌ خطأ SQLite: {e}"
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass


def _cmd_db_export_csv(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: db_export_csv <sqlite_file> <table> <output.csv>"
    path, table, output = pathlib.Path(ctx.args[0]), ctx.args[1], ctx.args[2]
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    quoted = _quote_identifier(table)
    if quoted is None:
        return f"❌ اسم جدول غير صالح: {table}"

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {quoted}")
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except sqlite3.Error as e:
        return f"❌ خطأ SQLite: {e}"
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass

    out_path = pathlib.Path(output)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
    except OSError as e:
        return f"❌ تعذر الكتابة: {e}"
    return f"✅ اتصدّر {len(rows)} صف من {table} في {out_path}"


def register(engine):
    engine.registry.register("db_schema", _cmd_db_schema, "db_schema <file.sqlite> — عرض كل الجداول وأعمدتها")
    engine.registry.register("db_query", _cmd_db_query, "db_query <file.sqlite> <SQL> — تنفيذ استعلام SQL")
    engine.registry.register("db_export_csv", _cmd_db_export_csv, "db_export_csv <file.sqlite> <table> <out.csv> — تصدير جدول لملف CSV")
