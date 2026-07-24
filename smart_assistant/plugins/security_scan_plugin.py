"""
security_scan_plugin.py — فحص أمان شامل: أخطاء/ثغرات في كود بايثون
(code_scan)، ثغرات في ملفات/مشاريع (vuln_scan: أسرار مكشوفة + ثغرات
مكتبات معروفة + صلاحيات ملفات)، وفحص فيروسات حقيقي عبر ClamAV
(virus_scan) — مع حجر صحي (quarantine) للملفات المصابة بدل حذفها أو
"تنظيفها" التلقائي، لأن ضمان إن ملف مصاب هيفضل شغال طبيعي بعد "تنظيفه"
مش حاجة أي أداة أمان جادة بتقدر تضمنها فعليًا. للأنماط غير الآمنة في
كودك (مش فيروسات — زي yaml.load بدل safe_load)، code_scan بيصلح
تلقائيًا الحالات الآمنة والواضحة بس، والباقي بيتبلّغ بيه للمراجعة اليدوية.

الأوامر: code_scan, vuln_scan, virus_scan, quarantine_file,
quarantine_list, quarantine_restore, security_report
"""
from __future__ import annotations

import ast
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import stat
import subprocess
import sys

MAX_SCAN_FILES = 2000
MAX_FILE_SIZE_FOR_SCAN = 5 * 1024 * 1024  # 5MB — ملفات نصية أكبر من كده نادراً ما تكون كود/كونفيج حقيقي

_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yml", ".yaml", ".env",
    ".ini", ".cfg", ".conf", ".toml", ".txt", ".sh", ".ps1", ".xml", ".properties",
}

_SECRET_PATTERNS = [
    ("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,48}\b")),
    ("Private Key Block", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("JWT-looking Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "Credentials in Connection String",
        re.compile(r"\b\w{2,15}://[^\s:@/'\"]+:[^\s@/'\"]+@[^\s\"']+"),
    ),
]

# اسم المتغير + القيمة بيتفحصوا لوحدهم (مش regex واحد كبير) عشان نتجنب
# مشكلة \b مع underscore: في regex، الـ underscore عنصر "كلمة" زي أي
# حرف، يعني \bsecret\b مبيلقاش SECRET جوه REAL_SECRET (مفيش حدود كلمة
# حقيقية هناك). بنقسّم اسم المتغير على أي حاجة مش حرف ونقارن كل جزء
# (أو زوج أجزاء متجاورة) لوحده — كده REAL_SECRET وAPI_KEY بيتلقطوا، لكن
# secretary_name (كلمة واحدة متقسّمتش) لأ.
_ASSIGNMENT_RE = re.compile(
    r'''^\s*([\w.\[\]]+)\s*[:=]\s*(?:"([^"]{6,})"|'([^']{6,})'|([^\s#'"]{6,}))\s*(?:#.*)?$'''
)
_SECRET_KEYWORDS = {
    "apikey", "secretkey", "secret", "accesstoken", "authtoken", "token", "password", "passwd", "pwd",
}


def _key_looks_like_secret(key: str) -> bool:
    parts = [p for p in re.split(r"[^a-zA-Z]+", key.lower()) if p]
    if not parts:
        return False
    for i in range(len(parts)):
        for j in range(i + 1, min(i + 3, len(parts)) + 1):
            if "".join(parts[i:j]) in _SECRET_KEYWORDS:
                return True
    return False


_PLACEHOLDER_VALUE = re.compile(
    r"^(x+|\*+|changeme|change_me|your[_-]?\w*|<.*>|\$\{.*\}|%.*%|todo|fixme|dummy|example|placeholder|none|null)$",
    re.IGNORECASE,
)

_DANGEROUS_CALLS = {
    ("", "eval"): ("critical", "eval() بينفذ أي كود بايثون جاي كنص — لو المصدر مش موثوق ده تنفيذ كود عن بُعد"),
    ("", "exec"): ("critical", "exec() بينفذ أي كود بايثون جاي كنص — نفس خطورة eval()"),
    ("os", "system"): ("high", "os.system() بيمرّر الأمر لـ shell مباشرة — استخدم subprocess.run(..., shell=False)"),
    ("pickle", "load"): ("high", "pickle.load() ممكن ينفذ كود عشوائي وقت فك تسلسل بيانات غير موثوقة"),
    ("pickle", "loads"): ("high", "pickle.loads() نفس خطورة pickle.load()"),
    ("marshal", "load"): ("high", "marshal.load() ممكن يسبب سلوك غير آمن مع بيانات غير موثوقة"),
    ("marshal", "loads"): ("high", "marshal.loads() نفس خطورة marshal.load()"),
    ("hashlib", "md5"): ("low", "MD5 ضعيف تشفيريًا — متستخدمهوش لباسورد أو توقيع أمني (كويس بس لـ checksum عادي)"),
    ("hashlib", "sha1"): ("low", "SHA1 ضعيف تشفيريًا — متستخدمهوش لباسورد أو توقيع أمني"),
}


def _matches_extension(p: pathlib.Path, extensions: set[str]) -> bool:
    if p.suffix.lower() in extensions:
        return True
    # ملفات زي .env / .env.local اسمها بالكامل بيبدأ بنقطة، فـ pathlib
    # بيعتبر p.suffix فاضي مش ".env" — لازم نتحقق من الاسم نفسه كمان،
    # خصوصًا إن .env بالظبط هو أكتر ملف متوقع يحتوي أسرار حقيقية.
    name_lower = p.name.lower()
    return ".env" in extensions and (name_lower == ".env" or name_lower.startswith(".env."))


def _iter_scan_files(root: pathlib.Path, extensions: set[str] | None = None) -> list[pathlib.Path]:
    if root.is_file():
        return [root]
    files = []
    for p in sorted(root.rglob("*")):
        if len(files) >= MAX_SCAN_FILES:
            break
        if not p.is_file():
            continue
        if extensions is not None and not _matches_extension(p, extensions):
            continue
        try:
            if p.stat().st_size > MAX_FILE_SIZE_FOR_SCAN:
                continue
        except OSError:
            continue
        files.append(p)
    return files


def _snippet(line: str) -> str:
    s = line.strip()
    return s[:100] + "..." if len(s) > 100 else s


def _scan_secrets_text(text: str, allow_unquoted: bool = False) -> list[tuple[int, str, str]]:
    """يرجع [(رقم السطر, نوع السر, نص مقتطع)]. بيتجاهل قيم شكلها placeholder
    واضح (changeme, xxx, <...>, ${...}) عشان يقلل false positives.
    allow_unquoted=True بيقبل قيم من غير quotes (زي في .env/.ini) —
    لملفات الكود (.py/.js) بنسيبها False عشان مانمسكش تعبيرات عادية
    زي `token = response.json()["token"]` غلط."""
    findings = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for label, pattern in _SECRET_PATTERNS:
            for m in pattern.finditer(line):
                value = m.group(0)
                if _PLACEHOLDER_VALUE.match(value.strip()):
                    continue
                findings.append((line_no, label, _snippet(line)))

        m = _ASSIGNMENT_RE.match(line)
        if m:
            key = m.group(1)
            value = m.group(2) or m.group(3) or m.group(4)
            is_quoted = m.group(2) is not None or m.group(3) is not None
            if (is_quoted or allow_unquoted) and _key_looks_like_secret(key) and not _PLACEHOLDER_VALUE.match(value.strip()):
                findings.append((line_no, "Hardcoded Secret Assignment", _snippet(line)))
    return findings


class _DangerVisitor(ast.NodeVisitor):
    def __init__(self):
        self.findings: list[tuple[int, str, str, str]] = []  # (line, severity, category, message)

    def _call_name(self, node: ast.Call) -> tuple[str, str] | None:
        func = node.func
        if isinstance(func, ast.Name):
            return ("", func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return (func.value.id, func.attr)
        return None

    def visit_Call(self, node: ast.Call):
        name = self._call_name(node)
        if name and name in _DANGEROUS_CALLS:
            severity, msg = _DANGEROUS_CALLS[name]
            label = f"{name[0]}.{name[1]}" if name[0] else name[1]
            self.findings.append((node.lineno, severity, "dangerous-call", f"{label}(): {msg}"))

        # subprocess.*(..., shell=True)
        if name and name[0] in ("subprocess", "sp") and name[1] in ("run", "call", "Popen", "check_call", "check_output"):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self.findings.append((
                        node.lineno, "high", "dangerous-call",
                        f"{name[0]}.{name[1]}(..., shell=True): تنفيذ عبر shell — خطر command injection لو أي جزء من الأمر جاي من مدخل مستخدم",
                    ))

        # yaml.load(x) بدون Loader، أو Loader=yaml.Loader/FullLoader/UnsafeLoader
        if name == ("yaml", "load"):
            loader_kw = next((kw for kw in node.keywords if kw.arg == "Loader"), None)
            if loader_kw is None:
                self.findings.append((
                    node.lineno, "high", "unsafe-deserialization",
                    "yaml.load() من غير Loader بيقدر ينفذ كود بايثون عشوائي من محتوى YAML غير موثوق — استخدم yaml.safe_load()",
                ))
            elif (
                isinstance(loader_kw.value, ast.Attribute)
                and isinstance(loader_kw.value.value, ast.Name)
                and loader_kw.value.value.id == "yaml"
                and loader_kw.value.attr in ("Loader", "FullLoader", "UnsafeLoader")
            ):
                self.findings.append((
                    node.lineno, "high", "unsafe-deserialization",
                    f"yaml.load(..., Loader=yaml.{loader_kw.value.attr}) غير آمن — استخدم Loader=yaml.SafeLoader أو yaml.safe_load()",
                ))

        # .execute(f"..." أو "..." + ...) — بناء SQL بـ string formatting بدل parameterized query
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executescript") and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.JoinedStr):
                self.findings.append((
                    node.lineno, "critical", "sql-injection",
                    ".execute() باستخدام f-string — استخدم placeholders (?) ومرّر القيم كـ parameters لتفادي SQL injection",
                ))
            elif isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)):
                self.findings.append((
                    node.lineno, "critical", "sql-injection",
                    ".execute() باستخدام + أو % لبناء الاستعلام — استخدم placeholders (?) وparameters بدل string building",
                ))

        self.generic_visit(node)


def _line_col_to_offset(source: str) -> list[int]:
    """يرجع أوفست بداية كل سطر (1-indexed lineno -> offsets[lineno-1])."""
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _apply_yaml_safe_load_fix(source: str) -> tuple[str, int]:
    """بيصلح تلقائيًا الحالة الوحيدة الآمنة والواضحة 100%: yaml.load() من غير
    Loader، أو Loader=yaml.Loader/FullLoader/UnsafeLoader -> SafeLoader.
    مبيلمسش أي نمط تاني (زي eval/pickle/shell=True) لأن الإصلاح الآمن لهم
    محتاج فهم للسياق مش تحويل نصي مضمون — بيتبلّغ عنهم بس في التقرير."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, 0

    edits: list[tuple[int, int, str]] = []  # (start_offset, end_offset, replacement)
    line_offsets = _line_col_to_offset(source)

    def span(node) -> tuple[int, int]:
        return (line_offsets[node.lineno - 1] + node.col_offset, line_offsets[node.end_lineno - 1] + node.end_col_offset)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "load"
                and isinstance(func.value, ast.Name) and func.value.id == "yaml"):
            continue
        if func.lineno != func.end_lineno:
            continue  # نتجنب الحالات النادرة اللي الاسم بينقسم على أكتر من سطر

        loader_kw = next((kw for kw in node.keywords if kw.arg == "Loader"), None)
        if loader_kw is None:
            start, end = span(func)
            attr_start = end - len("load")
            edits.append((attr_start, end, "safe_load"))
        elif (
            isinstance(loader_kw.value, ast.Attribute)
            and isinstance(loader_kw.value.value, ast.Name)
            and loader_kw.value.value.id == "yaml"
            and loader_kw.value.attr in ("Loader", "FullLoader", "UnsafeLoader")
            and loader_kw.value.lineno == loader_kw.value.end_lineno
        ):
            start, end = span(loader_kw.value)
            edits.append((start, end, "yaml.SafeLoader"))

    if not edits:
        return source, 0

    edits.sort(key=lambda e: e[0], reverse=True)
    new_source = source
    for start, end, replacement in edits:
        new_source = new_source[:start] + replacement + new_source[end:]

    try:
        ast.parse(new_source)
    except SyntaxError:
        return source, 0  # لو الإصلاح كسر بناء الكود بأي شكل، ارجع للأصل ومتلمسش الملف خالص

    return new_source, len(edits)


def _cmd_code_scan(ctx) -> str:
    if not ctx.args:
        return "usage: code_scan <path> [--fix]"
    do_fix = "--fix" in ctx.args
    path_args = [a for a in ctx.args if a != "--fix"]
    if not path_args:
        return "usage: code_scan <path> [--fix]"
    root = pathlib.Path(path_args[0])
    if not root.exists():
        return f"❌ المسار مش موجود: {root}"

    files = _iter_scan_files(root, {".py"})
    if not files:
        return f"مفيش ملفات .py في {root}"

    lines = [f"🔎 فحص كود: {len(files)} ملف .py"]
    total_findings = 0
    total_fixed = 0
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    for f in files:
        try:
            source = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            lines.append(f"  ⚠️ {f}: تعذرت القراءة ({e})")
            continue

        try:
            tree = ast.parse(source, filename=str(f))
        except SyntaxError as e:
            lines.append(f"  ❌ {f}:{e.lineno}: syntax error — {e.msg}")
            continue

        visitor = _DangerVisitor()
        visitor.visit(tree)
        secrets = [(ln, f"Hardcoded Secret ({label})", snippet) for ln, label, snippet in _scan_secrets_text(source)]

        file_findings = visitor.findings + [(ln, "critical", "secret", f"{label}: {snippet}") for ln, label, snippet in secrets]
        if not file_findings:
            continue

        fixed_count = 0
        if do_fix:
            new_source, fixed_count = _apply_yaml_safe_load_fix(source)
            if fixed_count:
                f.write_text(new_source, encoding="utf-8")
                total_fixed += fixed_count
                # أعد الفحص على النسخة المصلّحة عشان نبلّغ بالحالة الحقيقية بعد الإصلاح
                tree = ast.parse(new_source, filename=str(f))
                visitor = _DangerVisitor()
                visitor.visit(tree)
                file_findings = visitor.findings + [
                    (ln, "critical", "secret", f"{label}: {snippet}") for ln, label, snippet in secrets
                ]

        file_findings.sort(key=lambda x: severity_order.get(x[1], 9))
        total_findings += len(file_findings)
        lines.append(f"  📄 {f} ({len(file_findings)} ملاحظة{'، اتصلح ' + str(fixed_count) + ' منها' if fixed_count else ''}):")
        icon = {"critical": "🛑", "high": "⚠️", "medium": "🟡", "low": "ℹ️"}
        for ln, sev, _cat, msg in file_findings:
            lines.append(f"    {icon.get(sev, '•')} سطر {ln} [{sev}] {msg}")

    # len(lines) == 1 يعني مفيش حاجة اتضافت غير سطر العنوان — يعني مفيش
    # syntax errors ولا findings ولا fixes خالص. متعتمدش على total_findings
    # لوحده لأنه بيرجع 0 برضو لو الملف كان فيه مشكلة واحدة بس اتصلحت تلقائيًا
    # (يبقى مفيش findings متبقية، لكن فيه حاجة حصلت فعلاً لازم تتقال).
    if len(lines) == 1:
        return f"✅ فحصت {len(files)} ملف .py — مفيش ملاحظات أمنية/جودة كود ظاهرة"

    summary = f"لقيت {total_findings} ملاحظة" if total_findings else "مفيش ملاحظات متبقية"
    if total_fixed:
        summary += f" — اتصلح {total_fixed} تلقائيًا (yaml.load→safe_load)"
    lines.insert(1, summary)
    return "\n".join(lines)


def _run_pip_audit(req_file: pathlib.Path) -> str | None:
    if not shutil.which("pip-audit"):
        return None
    proc = subprocess.run(
        ["pip-audit", "-r", str(req_file), "--format", "json"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode not in (0, 1):  # 1 = فيه ثغرات (متوقع)، أي حاجة تانية خطأ حقيقي
        return f"  ⚠️ pip-audit فشل: {proc.stderr.strip()[:300]}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "  ⚠️ تعذر تفسير مخرجات pip-audit"
    deps = data.get("dependencies", data if isinstance(data, list) else [])
    vulnerable = [d for d in deps if d.get("vulns")]
    if not vulnerable:
        return "  ✅ pip-audit: مفيش ثغرات معروفة في المكتبات"
    out = [f"  🛑 pip-audit: {len(vulnerable)} مكتبة فيها ثغرات معروفة:"]
    for d in vulnerable[:20]:
        vuln_ids = ", ".join(v.get("id", "?") for v in d.get("vulns", [])[:5])
        out.append(f"    - {d.get('name')} {d.get('version')}: {vuln_ids}")
    return "\n".join(out)


def _run_npm_audit(pkg_dir: pathlib.Path) -> str | None:
    if not shutil.which("npm"):
        return None
    proc = subprocess.run(
        ["npm", "audit", "--json"], cwd=pkg_dir, capture_output=True, text=True, timeout=120,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "  ⚠️ تعذر تفسير مخرجات npm audit"
    meta = data.get("metadata", {}).get("vulnerabilities", {})
    total = sum(meta.get(k, 0) for k in ("critical", "high", "moderate", "low"))
    if total == 0:
        return "  ✅ npm audit: مفيش ثغرات معروفة في الحزم"
    parts = ", ".join(f"{k}: {meta[k]}" for k in ("critical", "high", "moderate", "low") if meta.get(k))
    return f"  🛑 npm audit: {total} ثغرة معروفة ({parts})"


def _cmd_vuln_scan(ctx) -> str:
    if not ctx.args:
        return "usage: vuln_scan <path>"
    root = pathlib.Path(ctx.args[0])
    if not root.exists():
        return f"❌ المسار مش موجود: {root}"

    lines = [f"🛡️ فحص ثغرات: {root}"]

    _unquoted_exts = {".env", ".ini", ".cfg", ".conf", ".properties"}
    files = _iter_scan_files(root, _TEXT_EXTENSIONS)
    secret_hits = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        allow_unquoted = f.suffix.lower() in _unquoted_exts or f.name.lower().startswith(".env")
        for ln, label, snippet in _scan_secrets_text(text, allow_unquoted=allow_unquoted):
            secret_hits.append((f, ln, label, snippet))

    lines.append(f"\n📌 أسرار مكشوفة ({len(files)} ملف اتفحص):")
    if secret_hits:
        for f, ln, label, snippet in secret_hits[:50]:
            lines.append(f"  🛑 {f}:{ln} [{label}] {snippet}")
        if len(secret_hits) > 50:
            lines.append(f"  ... و{len(secret_hits) - 50} أخرى")
    else:
        lines.append("  ✅ مفيش")

    lines.append("\n📦 ثغرات مكتبات معروفة:")
    dep_reports = []
    req_file = root / "requirements.txt" if root.is_dir() else (root if root.name == "requirements.txt" else None)
    if req_file and req_file.is_file():
        result = _run_pip_audit(req_file)
        dep_reports.append(result if result else "  ℹ️ pip-audit مش متثبت — نزّله بـ: pip install pip-audit (مجاني ومفتوح المصدر)")
    pkg_dir = root if root.is_dir() and (root / "package.json").is_file() else None
    if pkg_dir:
        result = _run_npm_audit(pkg_dir)
        dep_reports.append(result if result else "  ℹ️ npm مش متاح لفحص package.json")
    if not dep_reports:
        dep_reports.append("  ℹ️ مفيش requirements.txt ولا package.json في المسار ده")
    lines.extend(dep_reports)

    if root.is_dir():
        perms_cmd = ctx.engine.registry.get("file_perms") if ctx.engine else None
        if perms_cmd:
            lines.append("\n🔐 صلاحيات ملفات:")
            perms_result = perms_cmd.handler(_SubCtx(f"file_perms {root}", [str(root)], ctx.engine))
            lines.append("  " + perms_result.replace("\n", "\n  "))

    return "\n".join(lines)


class _SubCtx:
    """نسخة مبسّطة من CommandContext عشان نستدعي أوامر مسجّلة في نفس
    الـ registry من غير ما نحتاج نستورد core_engine (الإضافات مستقلة
    عن بعضها بتصميم المشروع — شوف core_engine.load_plugins)."""

    def __init__(self, raw: str, args: list[str], engine):
        self.raw = raw
        self.args = args
        self.engine = engine


_QUARANTINE_DIRNAME = "quarantine"


def _quarantine_dir() -> pathlib.Path:
    # نفس منطق _todo_path في todo_plugin.py: لما التطبيق يبقى exe مبني
    # بـ PyInstaller (sys.frozen)، __file__ بيتفكك جوه مجلد استخراج مؤقت
    # مش جنب الـ exe الحقيقي — فلازم نستخدم sys.executable بدل كده.
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    d = base / _QUARANTINE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quarantine_manifest_path() -> pathlib.Path:
    return _quarantine_dir() / "manifest.json"


def _load_manifest() -> list[dict]:
    p = _quarantine_manifest_path()
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_manifest(entries: list[dict]) -> None:
    _quarantine_manifest_path().write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _quarantine_move(path: pathlib.Path, reason: str) -> dict:
    qdir = _quarantine_dir()
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine_name = f"{timestamp}_{digest}_{path.name}.quarantined"
    dest = qdir / quarantine_name
    shutil.move(str(path), str(dest))
    try:
        dest.chmod(stat.S_IRUSR)  # قراءة للمالك بس — مفيش تنفيذ ولا كتابة، عشان الملف يفضل غير قابل للتشغيل بالخطأ
    except OSError:
        pass
    entry = {
        "id": quarantine_name,
        "original_path": str(path.resolve()),
        "quarantined_at": timestamp,
        "reason": reason,
    }
    manifest = _load_manifest()
    manifest.append(entry)
    _save_manifest(manifest)
    return entry


def _cmd_quarantine_file(ctx) -> str:
    if not ctx.args:
        return "usage: quarantine_file <path> [سبب]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    reason = " ".join(ctx.args[1:]) or "quarantine يدوي"
    entry = _quarantine_move(path, reason)
    return f"🔒 اتنقل للحجر الصحي: {entry['id']}\nالمسار الأصلي: {entry['original_path']}\nلاستعادته: quarantine_restore {entry['id']}"


def _cmd_quarantine_list(ctx) -> str:
    manifest = _load_manifest()
    if not manifest:
        return "الحجر الصحي فاضي"
    lines = [f"🔒 {len(manifest)} ملف في الحجر الصحي:"]
    for e in manifest:
        lines.append(f"  {e['id']} — أصله: {e['original_path']} — {e['quarantined_at']} — {e['reason']}")
    return "\n".join(lines)


def _cmd_quarantine_restore(ctx) -> str:
    if not ctx.args:
        return "usage: quarantine_restore <id> [مسار_بديل]"
    qid = ctx.args[0]
    manifest = _load_manifest()
    entry = next((e for e in manifest if e["id"] == qid), None)
    if entry is None:
        return f"❌ مفيش عنصر بالـ id ده في الحجر الصحي: {qid}"

    dest = pathlib.Path(ctx.args[1]) if len(ctx.args) > 1 else pathlib.Path(entry["original_path"])
    if dest.exists():
        return f"❌ في ملف موجود بالفعل في {dest} — حدد مسار بديل: quarantine_restore {qid} <مسار_تاني>"

    src = _quarantine_dir() / qid
    if not src.is_file():
        return f"❌ ملف الحجر الصحي نفسه مش موجود: {src} (ممكن اتشال يدويًا؟)"

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    try:
        dest.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    manifest = [e for e in manifest if e["id"] != qid]
    _save_manifest(manifest)
    return f"✅ اتستعاد لـ {dest}\n⚠️ ده كان في الحجر الصحي بسبب: {entry['reason']} — راجعه قبل ما تشغّله"


_CLAM_SUMMARY_RE = re.compile(r"^(.+?): (.+) FOUND$", re.MULTILINE)


def _cmd_virus_scan(ctx) -> str:
    if not ctx.args:
        return "usage: virus_scan <path> [--no-quarantine]"
    no_quarantine = "--no-quarantine" in ctx.args
    path_args = [a for a in ctx.args if a != "--no-quarantine"]
    if not path_args:
        return "usage: virus_scan <path> [--no-quarantine]"
    root = pathlib.Path(path_args[0])
    if not root.exists():
        return f"❌ المسار مش موجود: {root}"

    clamscan = shutil.which("clamscan") or shutil.which("clamdscan")
    if not clamscan:
        return (
            "❌ ClamAV مش متثبت — الفحص ده مش سقالة ذكاء اصطناعي مؤلَّفة، ده بيحتاج محرك antivirus "
            "حقيقي بقاعدة توقيعات محدَّثة (زي أي أداة أمان جادة). نزّله (مجاني ومفتوح المصدر بالكامل):\n"
            "  https://www.clamav.org/downloads\n"
            "بعد التثبيت شغّل freshclam مرة عشان يحمّل قاعدة الفيروسات، وبعدين جرب virus_scan تاني."
        )

    try:
        proc = subprocess.run(
            [clamscan, "-r", "--detect-pua=yes", "--scan-archive=yes", "-i", str(root)],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return "❌ الفحص أخد وقت أطول من اللازم (10 دقايق) — جرب على مسار أصغر"

    if proc.returncode == 2:
        return (
            f"❌ ClamAV اتلاقى بس قاعدة التوقيعات مش موجودة أو فيها مشكلة:\n{proc.stderr.strip() or proc.stdout.strip()}\n"
            "شغّل freshclam عشان تحمّل/تحدّث قاعدة الفيروسات."
        )
    if proc.returncode not in (0, 1):
        return f"❌ clamscan رجّع خطأ غير متوقع (كود {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"

    infected = _CLAM_SUMMARY_RE.findall(proc.stdout)
    if not infected:
        return f"✅ فحص فيروسات عميق على {root} — مفيش إصابات (PUA/spyware/archives متضمّنة في الفحص)"

    lines = [f"🛑 لقيت {len(infected)} ملف مصاب في {root}:"]
    quarantined = []
    for file_path, signature in infected:
        lines.append(f"  🦠 {file_path} — {signature}")
        if not no_quarantine:
            p = pathlib.Path(file_path)
            if p.is_file():
                entry = _quarantine_move(p, f"virus_scan: {signature}")
                quarantined.append(entry["id"])

    if quarantined:
        lines.append(f"\n🔒 اتنقلوا كلهم للحجر الصحي تلقائيًا ({len(quarantined)} ملف) — ماتم مسحهم ولا 'تنظيفهم' في مكانهم")
        lines.append("عشان أي محاولة 'تنظيف' فيروس مع ضمان إن الملف يفضل شغال زي الأول مش حاجة أي أداة أمان بتضمنها فعليًا.")
        lines.append("للاستعادة (لو false positive): quarantine_restore <id> — شوف quarantine_list")
    elif no_quarantine:
        lines.append("\n(--no-quarantine: الملفات اتسابت في مكانها من غير ما تتلمس)")

    return "\n".join(lines)


def _cmd_security_report(ctx) -> str:
    if not ctx.args:
        return "usage: security_report <path>"
    root = pathlib.Path(ctx.args[0])
    if not root.exists():
        return f"❌ المسار مش موجود: {root}"

    sections = [f"📋 تقرير أمان شامل: {root}", "=" * 50]

    py_files = _iter_scan_files(root, {".py"})
    if py_files:
        sections.append("\n### فحص كود بايثون (code_scan) ###")
        sections.append(_cmd_code_scan(_SubCtx(f"code_scan {root}", [str(root)], ctx.engine)))
    else:
        sections.append("\n### فحص كود بايثون ### \n(مفيش ملفات .py)")

    sections.append("\n### فحص ثغرات (vuln_scan) ###")
    sections.append(_cmd_vuln_scan(_SubCtx(f"vuln_scan {root}", [str(root)], ctx.engine)))

    if shutil.which("clamscan") or shutil.which("clamdscan"):
        sections.append("\n### فحص فيروسات (virus_scan) ###")
        sections.append(_cmd_virus_scan(_SubCtx(f"virus_scan {root}", [str(root)], ctx.engine)))
    else:
        sections.append("\n### فحص فيروسات ### \n(ClamAV مش متثبت — شغّل virus_scan لوحده عشان تفاصيل التثبيت)")

    return "\n".join(sections)


def register(engine):
    engine.registry.register("code_scan", _cmd_code_scan, "code_scan <path> [--fix] — فحص أمان/جودة كود بايثون (AST)، مع إصلاح تلقائي للحالات الآمنة الواضحة")
    engine.registry.register("vuln_scan", _cmd_vuln_scan, "vuln_scan <path> — أسرار مكشوفة + ثغرات مكتبات معروفة (pip-audit/npm audit) + صلاحيات ملفات")
    engine.registry.register("virus_scan", _cmd_virus_scan, "virus_scan <path> [--no-quarantine] — فحص فيروسات/spyware حقيقي عبر ClamAV، مع حجر صحي تلقائي")
    engine.registry.register("quarantine_file", _cmd_quarantine_file, "quarantine_file <path> [سبب] — نقل ملف مشبوه للحجر الصحي يدويًا")
    engine.registry.register("quarantine_list", _cmd_quarantine_list, "quarantine_list — عرض كل الملفات في الحجر الصحي")
    engine.registry.register("quarantine_restore", _cmd_quarantine_restore, "quarantine_restore <id> [مسار_بديل] — استعادة ملف من الحجر الصحي")
    engine.registry.register("security_report", _cmd_security_report, "security_report <path> — تقرير أمان شامل: كود + ثغرات + فيروسات في أمر واحد")
