import json
import shutil
import subprocess

import pytest
import security_scan_plugin as ssp

from core_engine import AssistantEngine, CommandContext

requires_clamscan = pytest.mark.skipif(
    not (shutil.which("clamscan") or shutil.which("clamdscan")), reason="clamav not installed"
)
requires_pip_audit = pytest.mark.skipif(not shutil.which("pip-audit"), reason="pip-audit not installed")
requires_npm = pytest.mark.skipif(not shutil.which("npm"), reason="npm not installed")
requires_bandit = pytest.mark.skipif(not shutil.which("bandit"), reason="bandit not installed")


@pytest.fixture(autouse=True)
def isolated_quarantine(tmp_path, monkeypatch):
    """كل اختبار بيستخدم مجلد quarantine خاص بيه، عشان محدش يلمس
    smart_assistant/quarantine/ الحقيقي بتاع المستخدم."""
    qdir = tmp_path / "quarantine"

    def fake_quarantine_dir():
        qdir.mkdir(parents=True, exist_ok=True)
        return qdir

    monkeypatch.setattr(ssp, "_quarantine_dir", fake_quarantine_dir)
    return qdir


# ── code_scan ──────────────────────────────────────────────────────────

def test_code_scan_no_args(make_ctx):
    assert ssp._cmd_code_scan(make_ctx("code_scan", [])).startswith("usage")


def test_code_scan_missing_path(make_ctx, tmp_path):
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(tmp_path / "nope")]))
    assert result.startswith("❌")


def test_code_scan_clean_file_reports_ok(make_ctx, tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert result.startswith("✅")


def test_code_scan_no_py_files(make_ctx, tmp_path):
    (tmp_path / "readme.txt").write_text("hi")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(tmp_path)]))
    assert "مفيش ملفات .py" in result


def test_code_scan_reports_syntax_error(make_ctx, tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def f(:\n    pass\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "syntax error" in result


def test_code_scan_detects_eval_and_os_system(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("import os\neval('1+1')\nos.system('ls')\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "eval()" in result
    assert "os.system()" in result
    assert "[critical]" in result
    assert "[high]" in result


def test_code_scan_detects_subprocess_shell_true(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("import subprocess\nsubprocess.run(cmd, shell=True)\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "shell=True" in result


def test_code_scan_detects_pickle_load(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("import pickle\ndata = pickle.load(open('x', 'rb'))\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "pickle.load()" in result


def test_code_scan_detects_weak_hash_as_low_severity(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("import hashlib\nhashlib.md5(b'x')\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "hashlib.md5()" in result
    assert "[low]" in result


def test_code_scan_detects_sql_injection_fstring_and_concat(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text(
        "def q(conn, uid):\n"
        "    conn.execute(f'SELECT * FROM t WHERE id = {uid}')\n"
        "    conn.execute('SELECT * FROM t WHERE id = ' + uid)\n"
    )
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert result.count("SQL injection") >= 1
    assert "f-string" in result
    assert "+ أو %" in result


def test_code_scan_does_not_flag_parameterized_query(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("def q(conn, uid):\n    conn.execute('SELECT * FROM t WHERE id = ?', (uid,))\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert result.startswith("✅")


def test_code_scan_does_not_flag_ordinary_dict_indexing(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text(
        "def get_token(response):\n"
        "    token = response.json()['token']\n"
        "    return token\n\n"
        "class Secretary:\n"
        "    secretary_name = 'Ahmed'\n"
    )
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert result.startswith("✅")


def test_code_scan_detects_hardcoded_secret(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text('API_KEY = "sk_live_abcdef1234567890"\n')
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "Hardcoded Secret" in result
    assert "API_KEY" in result


def test_code_scan_ignores_placeholder_secret_value(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text('password = "changeme"\n')
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert result.startswith("✅")


def test_code_scan_skips_oversized_single_file_instead_of_loading_it(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ssp, "MAX_FILE_SIZE_FOR_SCAN", 10)  # حد صغير جدًا عشان الاختبار يبقى سريع
    f = tmp_path / "big.py"
    f.write_text("x = 1\n" * 100)  # أكبر من 10 بايت بكتير
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert result.startswith("⚠️")
    assert "virus_scan" in result


# ── code_scan: bandit (فحص إضافي) ────────────────────────────────────

def test_code_scan_reports_bandit_missing_when_unavailable(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ssp.shutil, "which", lambda name: None if name == "bandit" else shutil.which(name))
    f = tmp_path / "clean.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "bandit مش متثبت" in result
    assert "pip install bandit" in result


@requires_bandit
def test_code_scan_bandit_finds_real_issue(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("import subprocess\nsubprocess.Popen('ls', shell=True)\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "bandit" in result
    assert "B" in result  # test_id زي B602 لازم يظهر


@requires_bandit
def test_code_scan_bandit_clean_file_reports_ok(make_ctx, tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert "bandit: مفيش ملاحظات إضافية" in result


def test_code_scan_bandit_section_present_even_when_ast_scan_is_clean(make_ctx, tmp_path, monkeypatch):
    """حتى لو الفحص الأساسي (AST) مبيلاقيش حاجة، قسم bandit المكمّل
    لازم يفضل يظهر — code_scan متبقاش بترجع مباشرة قبل ما تشغّله."""
    monkeypatch.setattr(ssp.shutil, "which", lambda name: None if name == "bandit" else shutil.which(name))
    f = tmp_path / "clean.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f)]))
    assert result.startswith("✅")
    assert "فحص إضافي بـ bandit" in result


# ── code_scan --fix ───────────────────────────────────────────────────

def test_code_scan_fix_rewrites_yaml_load_without_loader(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("import yaml\nconfig = yaml.load(open('c.yml'))\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f), "--fix"]))
    assert "اتصلح 1" in result
    fixed = f.read_text(encoding="utf-8")
    assert "yaml.safe_load(open('c.yml'))" in fixed
    subprocess.run(["python3", "-m", "py_compile", str(f)], check=True)


def test_code_scan_fix_rewrites_unsafe_loader_kwarg(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("import yaml\nconfig = yaml.load(s, Loader=yaml.Loader)\n")
    ssp._cmd_code_scan(make_ctx("code_scan", [str(f), "--fix"]))
    fixed = f.read_text(encoding="utf-8")
    assert "Loader=yaml.SafeLoader" in fixed
    subprocess.run(["python3", "-m", "py_compile", str(f)], check=True)


def test_code_scan_fix_does_not_touch_already_safe_loader(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    original = "import yaml\nconfig = yaml.load(s, Loader=yaml.SafeLoader)\n"
    f.write_text(original)
    ssp._cmd_code_scan(make_ctx("code_scan", [str(f), "--fix"]))
    assert f.read_text(encoding="utf-8") == original


def test_code_scan_fix_does_not_touch_other_findings(make_ctx, tmp_path):
    f = tmp_path / "d.py"
    f.write_text("eval('1')\nimport yaml\nyaml.load(s)\n")
    result = ssp._cmd_code_scan(make_ctx("code_scan", [str(f), "--fix"]))
    assert "eval()" in result  # لسه متبلّغ عنه، مش اتصلح
    assert "yaml.safe_load" in f.read_text(encoding="utf-8")


def test_code_scan_fix_skips_file_with_syntax_error(make_ctx, tmp_path):
    f = tmp_path / "broken.py"
    original = "def f(:\n    yaml.load(s)\n"
    f.write_text(original)
    ssp._cmd_code_scan(make_ctx("code_scan", [str(f), "--fix"]))
    assert f.read_text(encoding="utf-8") == original  # ملف مكسور من الأول متلمسش


# ── vuln_scan ──────────────────────────────────────────────────────────

def test_vuln_scan_no_args(make_ctx):
    assert ssp._cmd_vuln_scan(make_ctx("vuln_scan", [])).startswith("usage")


def test_vuln_scan_missing_path(make_ctx, tmp_path):
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path / "nope")]))
    assert result.startswith("❌")


def test_vuln_scan_skips_oversized_single_file_instead_of_loading_it(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ssp, "MAX_FILE_SIZE_FOR_SCAN", 10)
    f = tmp_path / "big.txt"
    f.write_text("API_KEY=AKIAABCDEFGHIJKLMNOP\n" * 10)
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(f)]))
    assert "virus_scan" in result
    assert "AKIAABCDEFGHIJKLMNOP" not in result  # الملف متقراش خالص، يبقى مفيش نتيجة منه


def test_vuln_scan_detects_aws_key_in_env_file(make_ctx, tmp_path):
    (tmp_path / ".env").write_text("API_KEY=AKIAABCDEFGHIJKLMNOP\n")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "AWS Access Key ID" in result
    assert "AKIAABCDEFGHIJKLMNOP" in result


def test_vuln_scan_env_dotfile_is_actually_scanned(make_ctx, tmp_path):
    # ريجريشن: pathlib.Path(".env").suffix == "" — ملف اسمه ".env" بالظبط
    # كان بيتفوت بصمت من فلتر الامتدادات لو مش متعامل معاه صراحةً.
    (tmp_path / ".env").write_text("SECRET_TOKEN=realvalue123456\n")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "1 ملف اتفحص" in result or "أسرار مكشوفة" in result
    assert "❌" not in result.split("📌")[0]


def test_vuln_scan_detects_credentials_in_connection_string(make_ctx, tmp_path):
    (tmp_path / ".env").write_text("DATABASE_URL=postgres://user:pass@localhost/db\n")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "Credentials in Connection String" in result


def test_vuln_scan_detects_bare_secret_variable_name(make_ctx, tmp_path):
    (tmp_path / ".env").write_text('REAL_SECRET="s3cr3t-Value-Here-12345"\n')
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "REAL_SECRET" in result


def test_vuln_scan_ignores_placeholder_in_env(make_ctx, tmp_path):
    (tmp_path / ".env").write_text("SECRET_TOKEN=changeme\n")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "أسرار مكشوفة (1 ملف اتفحص):\n  ✅ مفيش" in result


def test_vuln_scan_no_deps_message_when_no_manifest(make_ctx, tmp_path):
    (tmp_path / "readme.txt").write_text("hi")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "مفيش requirements.txt ولا package.json" in result


def test_vuln_scan_reports_pip_audit_missing_when_unavailable(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ssp.shutil, "which", lambda name: None if name == "pip-audit" else shutil.which(name))
    (tmp_path / "requirements.txt").write_text("requests==2.6.0\n")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "pip-audit مش متثبت" in result


@requires_pip_audit
def test_vuln_scan_pip_audit_finds_real_known_vulnerability(make_ctx, tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.6.0\n")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "pip-audit" in result
    assert "requests" in result


@requires_npm
def test_vuln_scan_npm_audit_finds_real_known_vulnerability(make_ctx, tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "t", "version": "1.0.0", "dependencies": {"lodash": "4.17.4"}}))
    subprocess.run(["npm", "install", "--silent"], cwd=tmp_path, capture_output=True, timeout=60)
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "npm audit" in result
    assert "critical" in result.lower() or "🛑" in result


def test_vuln_scan_composes_file_perms_via_registry(tmp_path):
    engine = AssistantEngine(plugins_dirs=[__import__("pathlib").Path(__file__).resolve().parent.parent / "plugins"])
    engine.load_plugins()
    f = tmp_path / "bad.txt"
    f.write_text("x")
    f.chmod(0o666)
    ctx = CommandContext(raw="vuln_scan", args=[str(tmp_path)], engine=engine)
    result = engine.registry.get("vuln_scan").handler(ctx)
    assert "صلاحيات ملفات" in result
    assert "world-writable" in result


def test_vuln_scan_gracefully_skips_file_perms_when_security_plugin_not_loaded(make_ctx, tmp_path):
    # bare_engine (من conftest) مفيهوش plugins محمّلة أصلاً — لازم يفضل
    # يشتغل عادي من غير AttributeError.
    (tmp_path / "readme.txt").write_text("hi")
    result = ssp._cmd_vuln_scan(make_ctx("vuln_scan", [str(tmp_path)]))
    assert "صلاحيات ملفات" not in result


# ── quarantine ─────────────────────────────────────────────────────────

def test_quarantine_file_no_args(make_ctx):
    assert ssp._cmd_quarantine_file(make_ctx("quarantine_file", [])).startswith("usage")


def test_quarantine_file_missing_path(make_ctx, tmp_path):
    result = ssp._cmd_quarantine_file(make_ctx("quarantine_file", [str(tmp_path / "nope")]))
    assert result.startswith("❌")


def test_quarantine_file_moves_and_neutralizes_permissions(make_ctx, tmp_path):
    f = tmp_path / "suspicious.exe"
    f.write_bytes(b"whatever")
    result = ssp._cmd_quarantine_file(make_ctx("quarantine_file", [str(f), "يدوي للاختبار"]))
    assert result.startswith("🔒")
    assert not f.exists()
    manifest = ssp._load_manifest()
    assert len(manifest) == 1
    assert manifest[0]["original_path"] == str(f.resolve())
    quarantined_path = ssp._quarantine_dir() / manifest[0]["id"]
    assert quarantined_path.is_file()
    import stat as stat_module
    mode = quarantined_path.stat().st_mode
    assert not (mode & stat_module.S_IWUSR)  # مفيش صلاحية كتابة حتى للمالك


def test_quarantine_list_empty(make_ctx):
    assert "فاضي" in ssp._cmd_quarantine_list(make_ctx("quarantine_list", []))


def test_quarantine_list_shows_entries(make_ctx, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"x")
    ssp._cmd_quarantine_file(make_ctx("quarantine_file", [str(f)]))
    result = ssp._cmd_quarantine_list(make_ctx("quarantine_list", []))
    assert str(f.resolve()) in result


def test_quarantine_restore_unknown_id(make_ctx):
    result = ssp._cmd_quarantine_restore(make_ctx("quarantine_restore", ["nope-123"]))
    assert result.startswith("❌")


def test_quarantine_restore_round_trip(make_ctx, tmp_path):
    f = tmp_path / "suspicious.exe"
    f.write_bytes(b"original-content")
    ssp._cmd_quarantine_file(make_ctx("quarantine_file", [str(f)]))
    qid = ssp._load_manifest()[0]["id"]

    result = ssp._cmd_quarantine_restore(make_ctx("quarantine_restore", [qid]))
    assert result.startswith("✅")
    assert f.is_file()
    assert f.read_bytes() == b"original-content"
    assert ssp._load_manifest() == []


def test_quarantine_restore_refuses_to_overwrite_existing_file(make_ctx, tmp_path):
    f = tmp_path / "suspicious.exe"
    f.write_bytes(b"original")
    ssp._cmd_quarantine_file(make_ctx("quarantine_file", [str(f)]))
    qid = ssp._load_manifest()[0]["id"]
    f.write_bytes(b"a new file now sits at the same path")  # حد حط ملف تاني في نفس المكان

    result = ssp._cmd_quarantine_restore(make_ctx("quarantine_restore", [qid]))
    assert result.startswith("❌")
    assert f.read_bytes() == b"a new file now sits at the same path"  # الملف الجديد متلمسش
    assert len(ssp._load_manifest()) == 1  # لسه في الحجر الصحي


# ── virus_scan ─────────────────────────────────────────────────────────

def test_virus_scan_no_args(make_ctx):
    assert ssp._cmd_virus_scan(make_ctx("virus_scan", [])).startswith("usage")


def test_virus_scan_missing_path(make_ctx, tmp_path):
    result = ssp._cmd_virus_scan(make_ctx("virus_scan", [str(tmp_path / "nope")]))
    assert result.startswith("❌")


def test_virus_scan_honest_message_when_clamav_not_installed(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(ssp.shutil, "which", lambda name: None)
    f = tmp_path / "x.txt"
    f.write_text("hi")
    result = ssp._cmd_virus_scan(make_ctx("virus_scan", [str(tmp_path)]))
    assert result.startswith("❌")
    assert "clamav.org" in result.lower()


@requires_clamscan
def test_virus_scan_clean_directory_reports_ok_or_missing_db(make_ctx, tmp_path):
    f = tmp_path / "clean.txt"
    f.write_text("nothing suspicious here")
    result = ssp._cmd_virus_scan(make_ctx("virus_scan", [str(tmp_path)]))
    # لو قاعدة الفيروسات مش موجودة في البيئة اللي بيشتغل فيها الاختبار
    # (زي أي بيئة CI بدون freshclam) بيرجع رسالة واضحة، مش استثناء خام.
    assert result.startswith("✅") or "قاعدة التوقيعات" in result


def _make_custom_hdb_signature(clamav_db_dir, content: bytes, sig_name: str):
    import hashlib as _hashlib
    md5 = _hashlib.md5(content).hexdigest()
    (clamav_db_dir / "pytest_custom.hdb").write_text(f"{md5}:{len(content)}:{sig_name}\n")


@requires_clamscan
def test_virus_scan_detects_and_quarantines_real_signature_match(make_ctx, tmp_path):
    """اختبار حقيقي كامل: بنعمل توقيع ClamAV مخصص (custom .hdb) بنفسنا
    عشان نتأكد إن الكشف والحجر الصحي شغالين فعليًا، من غير ما نعتمد على
    قاعدة بيانات فيروسات حقيقية (اللي ممكن متكونش متاحة/محدَّثة وقت
    الاختبار). لازم صلاحية كتابة على مجلد قاعدة بيانات ClamAV."""
    import pathlib as _pathlib

    clam_db_dirs = ["/var/lib/clamav", "/var/lib/clamav-testfiles"]
    db_dir = next((_pathlib.Path(d) for d in clam_db_dirs if _pathlib.Path(d).is_dir()), None)
    if db_dir is None or not __import__("os").access(db_dir, __import__("os").W_OK):
        pytest.skip("مفيش صلاحية كتابة على مجلد قاعدة بيانات ClamAV في البيئة دي")

    payload = b"PYTEST-CUSTOM-VIRUS-SIGNATURE-CONTENT"
    sig_file = db_dir / "pytest_custom_test.hdb"
    _make_custom_hdb_signature(db_dir, payload, "Pytest-Test-Signature")
    try:
        infected = tmp_path / "infected.exe"
        infected.write_bytes(payload)
        clean = tmp_path / "clean.txt"
        clean.write_text("safe")

        result = ssp._cmd_virus_scan(make_ctx("virus_scan", [str(tmp_path)]))
        assert "🛑" in result
        assert "Pytest-Test-Signature" in result
        assert not infected.exists()  # اتنقل للحجر الصحي
        assert clean.exists()  # الملف النضيف متلمسش

        manifest = ssp._load_manifest()
        assert any("Pytest-Test-Signature" in e["reason"] for e in manifest)
    finally:
        sig_file.unlink(missing_ok=True)
        (db_dir / "pytest_custom.hdb").unlink(missing_ok=True)


@requires_clamscan
def test_virus_scan_no_quarantine_flag_leaves_file_in_place(make_ctx, tmp_path):
    import os as _os
    import pathlib as _pathlib

    db_dir = next(
        (_pathlib.Path(d) for d in ["/var/lib/clamav"] if _pathlib.Path(d).is_dir() and _os.access(d, _os.W_OK)),
        None,
    )
    if db_dir is None:
        pytest.skip("مفيش صلاحية كتابة على مجلد قاعدة بيانات ClamAV في البيئة دي")

    payload = b"PYTEST-NOQUARANTINE-SIGNATURE"
    _make_custom_hdb_signature(db_dir, payload, "Pytest-NoQuarantine-Signature")
    try:
        infected = tmp_path / "infected.exe"
        infected.write_bytes(payload)
        result = ssp._cmd_virus_scan(make_ctx("virus_scan", [str(tmp_path), "--no-quarantine"]))
        assert "🛑" in result
        assert infected.exists()  # اتسابت في مكانها
        assert ssp._load_manifest() == []
    finally:
        (db_dir / "pytest_custom.hdb").unlink(missing_ok=True)


# ── security_report ──────────────────────────────────────────────────

def test_security_report_no_args(make_ctx):
    assert ssp._cmd_security_report(make_ctx("security_report", [])).startswith("usage")


def test_security_report_missing_path(make_ctx, tmp_path):
    result = ssp._cmd_security_report(make_ctx("security_report", [str(tmp_path / "nope")]))
    assert result.startswith("❌")


def test_security_report_combines_code_and_vuln_sections(make_ctx, tmp_path):
    (tmp_path / "app.py").write_text('API_KEY = "sk_live_abcdef1234567890"\n')
    result = ssp._cmd_security_report(make_ctx("security_report", [str(tmp_path)]))
    assert "### فحص كود بايثون" in result
    assert "### فحص ثغرات" in result
    assert "API_KEY" in result


def test_security_report_notes_no_python_files(make_ctx, tmp_path):
    (tmp_path / "readme.txt").write_text("hi")
    result = ssp._cmd_security_report(make_ctx("security_report", [str(tmp_path)]))
    assert "مفيش ملفات .py" in result
