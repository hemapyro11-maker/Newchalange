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


def _make_migrations(dirpath, files: dict):
    dirpath.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (dirpath / name).write_text(content, encoding="utf-8")


def test_db_migration_status_missing_migrations_dir(make_ctx, tmp_path):
    result = dbp._cmd_db_migration_status(make_ctx("db_migration_status", [str(tmp_path / "app.db"), str(tmp_path / "nope")]))
    assert result.startswith("❌")


def test_db_migration_status_no_sql_files(make_ctx, tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    result = dbp._cmd_db_migration_status(make_ctx("db_migration_status", [str(tmp_path / "app.db"), str(mig)]))
    assert "مفيش ملفات" in result


def test_db_migration_status_reports_all_pending_on_fresh_db(make_ctx, tmp_path):
    mig = tmp_path / "migrations"
    _make_migrations(mig, {"0001_a.sql": "CREATE TABLE a (id INTEGER PRIMARY KEY);"})
    result = dbp._cmd_db_migration_status(make_ctx("db_migration_status", [str(tmp_path / "app.db"), str(mig)]))
    assert "⏳ 0001_a.sql" in result
    assert "0 متطبقة، 1 في الانتظار" in result


def test_db_migrate_applies_in_order_and_is_idempotent(make_ctx, tmp_path):
    mig = tmp_path / "migrations"
    _make_migrations(mig, {
        "0001_users.sql": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
        "0002_seed.sql": "INSERT INTO users (name) VALUES ('Ahmed');",
    })
    db = tmp_path / "app.db"
    result = dbp._cmd_db_migrate(make_ctx("db_migrate", [str(db), str(mig)]))
    assert result.startswith("✅")
    assert "0001_users.sql" in result and "0002_seed.sql" in result

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM users").fetchone() == ("Ahmed",)
    conn.close()

    # second run: nothing new to apply
    result2 = dbp._cmd_db_migrate(make_ctx("db_migrate", [str(db), str(mig)]))
    assert "مفيش جديد" in result2

    status = dbp._cmd_db_migration_status(make_ctx("db_migration_status", [str(db), str(mig)]))
    assert "2 متطبقة، 0 في الانتظار، 0 فيها تعارض" in status


def test_db_migrate_stops_on_sql_error_and_keeps_earlier_migrations(make_ctx, tmp_path):
    mig = tmp_path / "migrations"
    _make_migrations(mig, {
        "0001_ok.sql": "CREATE TABLE t (id INTEGER PRIMARY KEY);",
        "0002_broken.sql": "THIS IS NOT VALID SQL;",
        "0003_never_reached.sql": "CREATE TABLE t2 (id INTEGER PRIMARY KEY);",
    })
    db = tmp_path / "app.db"
    result = dbp._cmd_db_migrate(make_ctx("db_migrate", [str(db), str(mig)]))
    assert result.startswith("❌")
    assert "0002_broken.sql" in result
    assert "0001_ok.sql" in result  # reports what succeeded before the failure

    conn = sqlite3.connect(db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "t" in tables
    assert "t2" not in tables
    conn.close()


def test_db_migrate_refuses_to_reapply_tampered_migration(make_ctx, tmp_path):
    mig = tmp_path / "migrations"
    _make_migrations(mig, {"0001_a.sql": "CREATE TABLE a (id INTEGER PRIMARY KEY);"})
    db = tmp_path / "app.db"
    dbp._cmd_db_migrate(make_ctx("db_migrate", [str(db), str(mig)]))

    (mig / "0001_a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY); -- tampered", encoding="utf-8")
    result = dbp._cmd_db_migrate(make_ctx("db_migrate", [str(db), str(mig)]))
    assert result.startswith("❌")
    assert "checksum mismatch" in result

    status = dbp._cmd_db_migration_status(make_ctx("db_migration_status", [str(db), str(mig)]))
    assert "⚠️" in status
    assert "0 متطبقة، 0 في الانتظار، 1 فيها تعارض" in status


def test_db_indexes_lists_index_columns_and_uniqueness(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT);
        CREATE INDEX idx_users_name ON users(name);
    ''')
    conn.commit()
    conn.close()

    result = dbp._cmd_db_indexes(make_ctx("db_indexes", [str(db), "users"]))
    assert "idx_users_name" in result
    assert "(name)" in result
    assert "non-unique" in result
    assert "UNIQUE constraint" in result  # from the UNIQUE column's auto-index


def test_db_indexes_flags_foreign_key_without_index(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE orgs (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY, org_id INTEGER REFERENCES orgs(id));
    ''')
    conn.commit()
    conn.close()

    result = dbp._cmd_db_indexes(make_ctx("db_indexes", [str(db)]))
    assert "⚠️ عمود org_id" in result
    assert "orgs" in result


def test_db_indexes_does_not_flag_covered_foreign_key(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE orgs (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY, org_id INTEGER REFERENCES orgs(id));
        CREATE INDEX idx_users_org ON users(org_id);
    ''')
    conn.commit()
    conn.close()

    result = dbp._cmd_db_indexes(make_ctx("db_indexes", [str(db)]))
    assert "⚠️" not in result


def test_db_indexes_missing_file(make_ctx, tmp_path):
    result = dbp._cmd_db_indexes(make_ctx("db_indexes", [str(tmp_path / "nope.db")]))
    assert result.startswith("❌")


def test_db_indexes_unknown_table(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    result = dbp._cmd_db_indexes(make_ctx("db_indexes", [str(db), "no_such_table"]))
    assert result.startswith("❌")


def test_db_indexes_rejects_invalid_table_name(make_ctx, tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    result = dbp._cmd_db_indexes(make_ctx("db_indexes", [str(db), "users; DROP TABLE users;--"]))
    assert result.startswith("❌")
