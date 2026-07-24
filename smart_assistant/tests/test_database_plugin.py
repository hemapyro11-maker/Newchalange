import sqlite3

import database_plugin as dbp


def _make_db(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER)")
    cur.executemany("INSERT INTO users (name, age) VALUES (?, ?)", [("Ahmed", 30), ("Sara", 25)])
    conn.commit()
    conn.close()


def test_db_schema_lists_tables_and_columns(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    result = dbp._cmd_db_schema(make_ctx("db_schema", [str(db)]))
    assert "users" in result
    assert "name TEXT" in result
    assert "id INTEGER PK" in result


def test_db_schema_missing_file(make_ctx, tmp_path):
    result = dbp._cmd_db_schema(make_ctx("db_schema", [str(tmp_path / "nope.db")]))
    assert result.startswith("❌")


def test_db_schema_empty_database(make_ctx, tmp_path):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    result = dbp._cmd_db_schema(make_ctx("db_schema", [str(db)]))
    assert "مفيش جداول" in result


def test_db_query_select_returns_rows(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    result = dbp._cmd_db_query(make_ctx(
        f"db_query {db} SELECT name, age FROM users ORDER BY age",
        [str(db), "SELECT", "name,", "age", "FROM", "users", "ORDER", "BY", "age"],
    ))
    assert "Sara" in result
    assert "Ahmed" in result
    assert result.index("Sara") < result.index("Ahmed")  # Sara(25) before Ahmed(30)


def test_db_query_insert_reports_rowcount(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    raw = f"db_query {db} INSERT INTO users (name, age) VALUES ('Omar', 40)"
    result = dbp._cmd_db_query(make_ctx(raw, [str(db), "INSERT", "..."]))
    assert "✅" in result
    assert "1" in result


def test_db_query_syntax_error_is_friendly(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    raw = f"db_query {db} SELEKT * FROM users"
    result = dbp._cmd_db_query(make_ctx(raw, [str(db), "SELEKT", "*", "FROM", "users"]))
    assert result.startswith("❌")


def test_db_query_missing_file(make_ctx, tmp_path):
    raw = f"db_query {tmp_path}/nope.db SELECT 1"
    result = dbp._cmd_db_query(make_ctx(raw, [f"{tmp_path}/nope.db", "SELECT", "1"]))
    assert result.startswith("❌")


def test_db_export_csv_writes_correct_data(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    out = tmp_path / "out.csv"
    result = dbp._cmd_db_export_csv(make_ctx("db_export_csv", [str(db), "users", str(out)]))
    assert result.startswith("✅")
    content = out.read_text(encoding="utf-8")
    assert "id,name,age" in content
    assert "Ahmed,30" in content


def test_db_export_csv_rejects_sql_injection_in_table_name(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    out = tmp_path / "out.csv"
    malicious = "users; DROP TABLE users;--"
    result = dbp._cmd_db_export_csv(make_ctx("db_export_csv", [str(db), malicious, str(out)]))
    assert result.startswith("❌")

    # confirm the table really wasn't dropped
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    assert cur.fetchone()[0] == 2
    conn.close()


def test_db_export_csv_unknown_table(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    result = dbp._cmd_db_export_csv(make_ctx("db_export_csv", [str(db), "no_such_table", str(tmp_path / "out.csv")]))
    assert result.startswith("❌")
