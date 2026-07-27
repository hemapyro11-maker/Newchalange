"""
database_plugin.py — أدوات قواعد بيانات حقيقية عبر sqlite3 (مكتبة
بايثون القياسية، بدون أي باكدج خارجي أو خدمة سحابية مدفوعة).

الأوامر: db_schema, db_query, db_export_csv, db_migration_status,
db_migrate, db_indexes
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import pathlib
import re
import sqlite3

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MIGRATIONS_TABLE = "_schema_migrations"


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
        return f"❌ file not found: {path}"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cur.fetchall()]
        if not tables:
            return "No tables in this database"
        lines = [f"📊 {len(tables)} tables:"]
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
        return f"❌ SQLite error: {e}"
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
        return f"❌ file not found: {path}"
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
            return f"✅ done — {cur.rowcount} rows affected"
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(200)
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(v) for v in row))
        suffix = "\n... (results truncated at 200 rows)" if len(rows) == 200 else ""
        return "\n".join(lines) + suffix
    except sqlite3.Error as e:
        return f"❌ SQLite error: {e}"
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
        return f"❌ file not found: {path}"
    quoted = _quote_identifier(table)
    if quoted is None:
        return f"❌ invalid table name: {table}"

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {quoted}")
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except sqlite3.Error as e:
        return f"❌ SQLite error: {e}"
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
        return f"❌ could not write: {e}"
    return f"✅ exported {len(rows)} rows from {table} to {out_path}"


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(f'''CREATE TABLE IF NOT EXISTS "{_MIGRATIONS_TABLE}" (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL UNIQUE,
        checksum TEXT NOT NULL,
        applied_at TEXT NOT NULL
    )''')


def _migration_files(migrations_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(migrations_dir.glob("*.sql"), key=lambda p: p.name)


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cmd_db_migration_status(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: db_migration_status <sqlite_file> <migrations_dir>"
    db_path, migrations_dir = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if db_path.is_dir():
        return f"❌ that is a directory, not a database file: {db_path}"
    if not migrations_dir.is_dir():
        return f"❌ migrations directory not found: {migrations_dir}"

    files = _migration_files(migrations_dir)
    if not files:
        return f"No *.sql files in {migrations_dir}"

    try:
        conn = sqlite3.connect(str(db_path))
        _ensure_migrations_table(conn)
        conn.commit()
        applied = {
            row[0]: (row[1], row[2])
            for row in conn.execute(f'SELECT filename, checksum, applied_at FROM "{_MIGRATIONS_TABLE}"')
        }
    except sqlite3.Error as e:
        return f"❌ SQLite error: {e}"
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass

    lines = [f"📋 {len(files)} migration files in {migrations_dir}:"]
    pending = mismatched = ok = 0
    for f in files:
        checksum = _checksum(f.read_text(encoding="utf-8"))
        record = applied.get(f.name)
        if record is None:
            lines.append(f"  ⏳ {f.name} — not applied yet")
            pending += 1
        else:
            applied_checksum, applied_at = record
            if applied_checksum == checksum:
                lines.append(f"  ✅ {f.name} — applied at {applied_at}")
                ok += 1
            else:
                lines.append(f"  ⚠️ {f.name} — applied at {applied_at}, but its contents changed since (checksum mismatch)")
                mismatched += 1
    lines.append(f"— {ok} applied, {pending} pending, {mismatched} with a checksum mismatch")
    return "\n".join(lines)


def _cmd_db_migrate(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: db_migrate <sqlite_file> <migrations_dir>"
    db_path, migrations_dir = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if db_path.is_dir():
        return f"❌ that is a directory, not a database file: {db_path}"
    if not migrations_dir.is_dir():
        return f"❌ migrations directory not found: {migrations_dir}"

    files = _migration_files(migrations_dir)
    if not files:
        return f"No *.sql files in {migrations_dir}"

    try:
        conn = sqlite3.connect(str(db_path))
        _ensure_migrations_table(conn)
        conn.commit()
        applied = dict(conn.execute(f'SELECT filename, checksum FROM "{_MIGRATIONS_TABLE}"'))

        applied_now = []
        for f in files:
            sql_text = f.read_text(encoding="utf-8")
            checksum = _checksum(sql_text)
            existing_checksum = applied.get(f.name)
            if existing_checksum is not None:
                if existing_checksum != checksum:
                    return (
                        f"❌ stopped at {f.name}: already applied with different contents (checksum mismatch) — "
                        f"rename the file if the change was intentional; never edit a migration that already ran"
                        + (f"\n✅ {len(applied_now)} migrations had already been applied: {', '.join(applied_now)}" if applied_now else "")
                    )
                continue  # applied and unchanged — skip
            try:
                conn.executescript(sql_text)
            except sqlite3.Error as e:
                conn.rollback()
                return (
                    f"❌ migration {f.name} failed: {e}"
                    + (f"\n✅ {len(applied_now)} migrations had already been applied: {', '.join(applied_now)}" if applied_now else "")
                )
            conn.execute(
                f'INSERT INTO "{_MIGRATIONS_TABLE}" (filename, checksum, applied_at) VALUES (?, ?, ?)',
                (f.name, checksum, datetime.datetime.now(datetime.timezone.utc).isoformat()),
            )
            conn.commit()
            applied_now.append(f.name)
    except sqlite3.Error as e:
        return f"❌ SQLite error: {e}"
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass

    if not applied_now:
        return "✅ every migration is already applied — nothing new"
    return f"✅ applied {len(applied_now)} migrations: {', '.join(applied_now)}"


def _cmd_db_indexes(ctx) -> str:
    if not ctx.args:
        return "usage: db_indexes <sqlite_file> [table]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ file not found: {path}"

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        if len(ctx.args) > 1:
            table_arg = ctx.args[1]
            quoted = _quote_identifier(table_arg)
            if quoted is None:
                return f"❌ invalid table name: {table_arg}"
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_arg,))
            if cur.fetchone() is None:
                return f"❌ no table named {table_arg}"
            tables = [table_arg]
        else:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cur.fetchall()]
            if not tables:
                return "No tables in this database"

        lines = []
        for table in tables:
            quoted = _quote_identifier(table)
            if quoted is None:
                continue
            lines.append(f"🗂  {table}")
            cur.execute(f"PRAGMA index_list({quoted})")
            index_rows = cur.fetchall()
            indexed_leading_cols = set()
            if not index_rows:
                lines.append("    (no indexes at all)")
            for idx in index_rows:
                idx_name, is_unique, origin = idx[1], idx[2], idx[3]
                quoted_idx = _quote_identifier(idx_name)
                if quoted_idx is None:
                    lines.append(f"    📌 {idx_name} (invalid index name, skipped)")
                    continue
                cur.execute(f"PRAGMA index_info({quoted_idx})")
                cols = [row[2] for row in sorted(cur.fetchall(), key=lambda r: r[0])]
                if cols:
                    indexed_leading_cols.add(cols[0])
                origin_desc = {"pk": "PRIMARY KEY", "u": "UNIQUE constraint", "c": "manual"}.get(origin, origin)
                unique_tag = "UNIQUE" if is_unique else "non-unique"
                lines.append(f"    📌 {idx_name} ({', '.join(cols)}) — {unique_tag}, {origin_desc}")

            cur.execute(f"PRAGMA foreign_key_list({quoted})")
            for fk in cur.fetchall():
                ref_table, from_col = fk[2], fk[3]
                if from_col not in indexed_leading_cols:
                    lines.append(f"    ⚠️ column {from_col} (foreign key to {ref_table}) has no index — this can slow JOINs down")
        return "\n".join(lines)
    except sqlite3.Error as e:
        return f"❌ SQLite error: {e}"
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass


def register(engine):
    engine.registry.register("db_schema", _cmd_db_schema, "db_schema <file.sqlite> — every table and its columns")
    engine.registry.register("db_query", _cmd_db_query, "db_query <file.sqlite> <SQL> — run an SQL query")
    engine.registry.register("db_export_csv", _cmd_db_export_csv, "db_export_csv <file.sqlite> <table> <out.csv> — export a table to CSV")
    engine.registry.register("db_migration_status", _cmd_db_migration_status, "db_migration_status <file.sqlite> <migrations_dir> — per-migration state (applied/pending/checksum mismatch)")
    engine.registry.register("db_migrate", _cmd_db_migrate, "db_migrate <file.sqlite> <migrations_dir> — apply pending migrations in order, inside a transaction")
    engine.registry.register("db_indexes", _cmd_db_indexes, "db_indexes <file.sqlite> [table] — list indexes and flag unindexed foreign keys")
