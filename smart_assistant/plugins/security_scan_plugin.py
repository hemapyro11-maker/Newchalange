"""
security_scan_plugin.py — فحص أمان شامل: أخطاء/ثغرات في كود بايثون
(code_scan)، ثغرات في ملفات/مشاريع (vuln_scan: أسرار مكشوفة + ثغرات
مكتبات معروفة + صلاحيات ملفات)، وفحص فيروسات حقيقي عبر ClamAV
(virus_scan) — مع حجر صحي (quarantine) للملفات المصابة بدل حذفها أو
"تنظيفها" التلقائي، لأن ضمان إن ملف مصاب هيفضل شغال طبيعي بعد "تنظيفه"
مش حاجة أي أداة أمان جادة بتقدر تضمنها فعليًا. للأنماط غير الآمنة في
كودك (مش فيروسات — زي yaml.load بدل safe_load)، code_scan بيصلح
تلقائيًا الحالات الآمنة والواضحة بس، والباقي بيتبلّغ بيه للمراجعة اليدوية.
code_scan كمان بيشغّل bandit (لو متثبت) كفحص إضافي اختياري فوق فحصنا
الأساسي بـ AST — تغطية أوسع (assert بكود إنتاجي، tarfile.extractall
غير آمن، XML/SSL ضعيف، إلخ) من غير ما يبقى معتمد عليه، لأنه مش متضمّن
في requirements.txt الأساسي (اختياري: pip install bandit).

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
    ("", "eval"): ("critical", "eval() executes any Python passed as text — with an untrusted source that is remote code execution"),
    ("", "exec"): ("critical", "exec() executes any Python passed as text — as dangerous as eval()"),
    ("os", "system"): ("high", "os.system() hands the command straight to a shell — use subprocess.run(..., shell=False)"),
    ("pickle", "load"): ("high", "pickle.load() can execute arbitrary code when unpickling untrusted data"),
    ("pickle", "loads"): ("high", "pickle.loads() is as dangerous as pickle.load()"),
    ("marshal", "load"): ("high", "marshal.load() is unsafe with untrusted data"),
    ("marshal", "loads"): ("high", "marshal.loads() is as dangerous as marshal.load()"),
    ("hashlib", "md5"): ("low", "MD5 is cryptographically weak — never for passwords or signatures (fine for a plain checksum)"),
    ("hashlib", "sha1"): ("low", "SHA1 is cryptographically weak — never for passwords or signatures"),
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
        try:
            if root.stat().st_size > MAX_FILE_SIZE_FOR_SCAN:
                return []
        except OSError:
            return []
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


def _oversized_single_file_message(path: pathlib.Path, other_cmd: str) -> str:
    size_mb = path.stat().st_size / (1024 * 1024)
    return (
        f"⚠️ {path} is {size_mb:.1f}MB — over the limit for scanning text content "
        f"({MAX_FILE_SIZE_FOR_SCAN // (1024 * 1024)}MB), so it is not loaded whole into memory.\n"
        f"If it is an executable, archive or media file, use virus_scan instead of {other_cmd} — "
        "ClamAV streams it without loading it into Python memory at all."
    )


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
                        f"{name[0]}.{name[1]}(..., shell=True): runs through a shell — command injection risk if any part comes from user input",
                    ))

        # yaml.load(x) بدون Loader، أو Loader=yaml.Loader/FullLoader/UnsafeLoader
        if name == ("yaml", "load"):
            loader_kw = next((kw for kw in node.keywords if kw.arg == "Loader"), None)
            if loader_kw is None:
                self.findings.append((
                    node.lineno, "high", "unsafe-deserialization",
                    "yaml.load() without a Loader can execute arbitrary Python from untrusted YAML — use yaml.safe_load()",
                ))
            elif (
                isinstance(loader_kw.value, ast.Attribute)
                and isinstance(loader_kw.value.value, ast.Name)
                and loader_kw.value.value.id == "yaml"
                and loader_kw.value.attr in ("Loader", "FullLoader", "UnsafeLoader")
            ):
                self.findings.append((
                    node.lineno, "high", "unsafe-deserialization",
                    f"yaml.load(..., Loader=yaml.{loader_kw.value.attr}) is unsafe — use Loader=yaml.SafeLoader or yaml.safe_load()",
                ))

        # .execute(f"..." أو "..." + ...) — بناء SQL بـ string formatting بدل parameterized query
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executescript") and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.JoinedStr):
                self.findings.append((
                    node.lineno, "critical", "sql-injection",
                    ".execute() with an f-string — use placeholders (?) and pass values as parameters to avoid SQL injection",
                ))
            elif isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)):
                self.findings.append((
                    node.lineno, "critical", "sql-injection",
                    ".execute() building the query with + or % — use placeholders (?) and parameters instead of string building",
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


def _run_bandit(root: pathlib.Path) -> str | None:
    """فحص إضافي اختياري بـ bandit (مكتبة فحص أمان بايثون معروفة ومفتوحة
    المصدر) — بيغطي أنماط أوسع بكتير من الفحص الأساسي فوق (assert في كود
    إنتاجي، tarfile.extractall غير آمن، XML عبر مكتبات ضعيفة، SSL/TLS
    ضعيف، إلخ). بيرجع None لو bandit مش متثبت، عشان code_scan يفضل يشتغل
    بالفحص الأساسي (AST) بس زي ما هو من غيره — مكمّل مش بديل."""
    if not shutil.which("bandit"):
        return None
    cmd = ["bandit"]
    if root.is_dir():
        cmd.append("-r")
    cmd += [str(root), "-f", "json", "-q"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "  ⚠️ bandit took longer than expected (timed out)"
    if proc.returncode not in (0, 1):  # 1 = فيه ملاحظات (متوقع)، أي حاجة تانية خطأ حقيقي
        return f"  ⚠️ bandit failed: {proc.stderr.strip()[:300]}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "  ⚠️ could not parse bandit output"
    results = data.get("results", [])
    if not results:
        return "  ✅ bandit: nothing further to report"
    sev_icon = {"HIGH": "🛑", "MEDIUM": "⚠️", "LOW": "ℹ️"}
    out = [f"  🔍 bandit: {len(results)} additional findings:"]
    for r in results[:30]:
        icon = sev_icon.get(str(r.get("issue_severity", "")).upper(), "•")
        out.append(
            f"    {icon} {r.get('filename')}:{r.get('line_number')} "
            f"[{r.get('test_id')}] {str(r.get('issue_text', '')).strip()}"
        )
    if len(results) > 30:
        out.append(f"    ... and {len(results) - 30} more")
    return "\n".join(out)


def _cmd_code_scan(ctx) -> str:
    if not ctx.args:
        return "usage: code_scan <path> [--fix]"
    do_fix = "--fix" in ctx.args
    path_args = [a for a in ctx.args if a != "--fix"]
    if not path_args:
        return "usage: code_scan <path> [--fix]"
    root = pathlib.Path(path_args[0])
    if not root.exists():
        return f"❌ path not found: {root}"
    if root.is_file() and root.stat().st_size > MAX_FILE_SIZE_FOR_SCAN:
        return _oversized_single_file_message(root, "code_scan")

    files = _iter_scan_files(root, {".py"})
    if not files:
        return f"No .py files in {root}"

    lines = [f"🔎 Code scan: {len(files)} .py files"]
    total_findings = 0
    total_fixed = 0
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    for f in files:
        try:
            source = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            lines.append(f"  ⚠️ {f}: could not read it ({e})")
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
        lines.append(f"  📄 {f} ({len(file_findings)} findings{', ' + str(fixed_count) + ' fixed' if fixed_count else ''}):")
        icon = {"critical": "🛑", "high": "⚠️", "medium": "🟡", "low": "ℹ️"}
        for ln, sev, _cat, msg in file_findings:
            lines.append(f"    {icon.get(sev, '•')} line {ln} [{sev}] {msg}")

    # len(lines) == 1 يعني مفيش حاجة اتضافت غير سطر العنوان — يعني مفيش
    # syntax errors ولا findings ولا fixes خالص. متعتمدش على total_findings
    # لوحده لأنه بيرجع 0 برضو لو الملف كان فيه مشكلة واحدة بس اتصلحت تلقائيًا
    # (يبقى مفيش findings متبقية، لكن فيه حاجة حصلت فعلاً لازم تتقال).
    if len(lines) == 1:
        lines = [f"✅ scanned {len(files)} .py files — the base scan found no security or quality issues"]
    else:
        summary = f"found {total_findings} issues" if total_findings else "no issues left"
        if total_fixed:
            summary += f" — {total_fixed} fixed automatically (yaml.load→safe_load)"
        lines.insert(1, summary)

    lines.append(
        "\n🔍 Extra pass with bandit (wider coverage: assert in production code, "
        "unsafe tarfile.extractall, weak XML/SSL, and so on):"
    )
    bandit_result = _run_bandit(root)
    lines.append(bandit_result if bandit_result else "  ℹ️ bandit is not installed — pip install bandit (free and open source)")

    return "\n".join(lines)


def _run_pip_audit(req_file: pathlib.Path) -> str | None:
    if not shutil.which("pip-audit"):
        return None
    proc = subprocess.run(
        ["pip-audit", "-r", str(req_file), "--format", "json"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode not in (0, 1):  # 1 = فيه ثغرات (متوقع)، أي حاجة تانية خطأ حقيقي
        return f"  ⚠️ pip-audit failed: {proc.stderr.strip()[:300]}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "  ⚠️ could not parse pip-audit output"
    deps = data.get("dependencies", data if isinstance(data, list) else [])
    vulnerable = [d for d in deps if d.get("vulns")]
    if not vulnerable:
        return "  ✅ pip-audit: no known vulnerabilities in your dependencies"
    out = [f"  🛑 pip-audit: {len(vulnerable)} dependencies with known vulnerabilities:"]
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
        return "  ⚠️ could not parse npm audit output"
    meta = data.get("metadata", {}).get("vulnerabilities", {})
    total = sum(meta.get(k, 0) for k in ("critical", "high", "moderate", "low"))
    if total == 0:
        return "  ✅ npm audit: no known vulnerabilities in your packages"
    parts = ", ".join(f"{k}: {meta[k]}" for k in ("critical", "high", "moderate", "low") if meta.get(k))
    return f"  🛑 npm audit: {total} known vulnerabilities ({parts})"


def _cmd_vuln_scan(ctx) -> str:
    if not ctx.args:
        return "usage: vuln_scan <path>"
    root = pathlib.Path(ctx.args[0])
    if not root.exists():
        return f"❌ path not found: {root}"

    lines = [f"🛡️ Vulnerability scan: {root}"]

    skipped_for_size = root.is_file() and root.stat().st_size > MAX_FILE_SIZE_FOR_SCAN
    if skipped_for_size:
        lines.append(f"\n📌 Exposed secrets:\n  {_oversized_single_file_message(root, 'vuln_scan')}")
    else:
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

        lines.append(f"\n📌 Exposed secrets ({len(files)} files scanned):")
        if secret_hits:
            for f, ln, label, snippet in secret_hits[:50]:
                lines.append(f"  🛑 {f}:{ln} [{label}] {snippet}")
            if len(secret_hits) > 50:
                lines.append(f"  ... and {len(secret_hits) - 50} more")
        else:
            lines.append("  ✅ none")

    lines.append("\n📦 Known dependency vulnerabilities:")
    dep_reports = []
    req_file = root / "requirements.txt" if root.is_dir() else (root if root.name == "requirements.txt" else None)
    if req_file and req_file.is_file():
        result = _run_pip_audit(req_file)
        dep_reports.append(result if result else "  ℹ️ pip-audit is not installed — pip install pip-audit (free and open source)")
    pkg_dir = root if root.is_dir() and (root / "package.json").is_file() else None
    if pkg_dir:
        result = _run_npm_audit(pkg_dir)
        dep_reports.append(result if result else "  ℹ️ npm is not available to check package.json")
    if not dep_reports:
        dep_reports.append("  ℹ️ no requirements.txt or package.json at this path")
    lines.extend(dep_reports)

    if root.is_dir():
        perms_cmd = ctx.engine.registry.get("file_perms") if ctx.engine else None
        if perms_cmd:
            lines.append("\n🔐 File permissions:")
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
        return "usage: quarantine_file <path> [reason]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ file not found: {path}"
    reason = " ".join(ctx.args[1:]) or "quarantined by hand"
    entry = _quarantine_move(path, reason)
    return f"🔒 moved to quarantine: {entry['id']}\nOriginal path: {entry['original_path']}\nTo restore it: quarantine_restore {entry['id']}"


def _cmd_quarantine_list(ctx) -> str:
    manifest = _load_manifest()
    if not manifest:
        return "Quarantine is empty"
    lines = [f"🔒 {len(manifest)} files in quarantine:"]
    for e in manifest:
        lines.append(f"  {e['id']} — from: {e['original_path']} — {e['quarantined_at']} — {e['reason']}")
    return "\n".join(lines)


def _cmd_quarantine_restore(ctx) -> str:
    if not ctx.args:
        return "usage: quarantine_restore <id> [destination]"
    qid = ctx.args[0]
    manifest = _load_manifest()
    entry = next((e for e in manifest if e["id"] == qid), None)
    if entry is None:
        return f"❌ nothing in quarantine with that id: {qid}"

    dest = pathlib.Path(ctx.args[1]) if len(ctx.args) > 1 else pathlib.Path(entry["original_path"])
    if dest.exists():
        return f"❌ a file already exists at {dest} — give another path: quarantine_restore {qid} <other_path>"

    src = _quarantine_dir() / qid
    if not src.is_file():
        return f"❌ the quarantined file itself is missing: {src} (removed by hand?)"

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    try:
        dest.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    manifest = [e for e in manifest if e["id"] != qid]
    _save_manifest(manifest)
    return f"✅ restored to {dest}\n⚠️ it was quarantined because: {entry['reason']} — check it before running it"


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
        return f"❌ path not found: {root}"

    clamscan = shutil.which("clamscan") or shutil.which("clamdscan")
    if not clamscan:
        return (
            "❌ ClamAV is not installed — this is not an AI-invented scaffold, it needs a real antivirus "
            "engine with an up-to-date signature database, like any serious security tool. Install it (entirely free and open source):\n"
            "  https://www.clamav.org/downloads\n"
            "After installing, run freshclam once to fetch the virus database, then try virus_scan again."
        )

    try:
        proc = subprocess.run(
            [clamscan, "-r", "--detect-pua=yes", "--scan-archive=yes", "-i", str(root)],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return "❌ the scan took too long (10 minutes) — try a smaller path"

    if proc.returncode == 2:
        return (
            f"❌ ClamAV was found but its signature database is missing or broken:\n{proc.stderr.strip() or proc.stdout.strip()}\n"
            "Run freshclam to fetch or update the virus database."
        )
    if proc.returncode not in (0, 1):
        return f"❌ clamscan returned an unexpected error (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"

    infected = _CLAM_SUMMARY_RE.findall(proc.stdout)
    if not infected:
        return f"✅ deep virus scan of {root} — no infections (PUA, spyware and archives were all included)"

    lines = [f"🛑 found {len(infected)} infected files in {root}:"]
    quarantined = []
    skipped = []
    for file_path, signature in infected:
        lines.append(f"  🦠 {file_path} — {signature}")
        if not no_quarantine:
            p = pathlib.Path(file_path)
            if p.is_file():
                entry = _quarantine_move(p, f"virus_scan: {signature}")
                quarantined.append(entry["id"])
            else:
                skipped.append(file_path)

    # مهم: "اتنقلوا كلهم" (all moved) لازم تتقال بس لو فعلاً كل ملف
    # مصاب اتنقل — مش بس لو القايمة مش فاضية. لو مسار مصاب مش ملف
    # حقيقي على القرص (عنصر جوه أرشيف، أو TOCTOU اتشال بين الفحص
    # والنقل)، لازم المستخدم يعرف إنه لسه في مكانه بدل ما نديله إحساس
    # أمان زايف إن كل حاجة اتحجرت.
    if no_quarantine:
        lines.append("\n(--no-quarantine: the files were left exactly where they are, untouched)")
    elif quarantined and not skipped:
        lines.append(f"\n🔒 all moved to quarantine automatically ({len(quarantined)} files) — not deleted, and not 'cleaned' in place")
        lines.append("because no security tool can honestly promise that 'cleaning' an infected file leaves it working as before.")
        lines.append("To restore one (if it is a false positive): quarantine_restore <id> — see quarantine_list")
    else:
        if quarantined:
            lines.append(f"\n⚠️ only {len(quarantined)} of {len(infected)} infected files were quarantined — the rest were left untouched:")
        else:
            lines.append(f"\n⚠️ none of the {len(infected)} infected files were quarantined — all were left untouched:")
        for sp in skipped:
            lines.append(f"    • {sp} (not a real file on disk — possibly an entry inside an archive)")
        if quarantined:
            lines.append("To restore one (if it is a false positive): quarantine_restore <id> — see quarantine_list")

    return "\n".join(lines)


def _cmd_security_report(ctx) -> str:
    if not ctx.args:
        return "usage: security_report <path>"
    root = pathlib.Path(ctx.args[0])
    if not root.exists():
        return f"❌ path not found: {root}"

    sections = [f"📋 Full security report: {root}", "=" * 50]

    py_files = _iter_scan_files(root, {".py"})
    if py_files:
        sections.append("\n### Python code scan (code_scan) ###")
        sections.append(_cmd_code_scan(_SubCtx(f"code_scan {root}", [str(root)], ctx.engine)))
    else:
        sections.append("\n### Python code scan ### \n(no .py files)")

    sections.append("\n### Vulnerability scan (vuln_scan) ###")
    sections.append(_cmd_vuln_scan(_SubCtx(f"vuln_scan {root}", [str(root)], ctx.engine)))

    if shutil.which("clamscan") or shutil.which("clamdscan"):
        sections.append("\n### Virus scan (virus_scan) ###")
        sections.append(_cmd_virus_scan(_SubCtx(f"virus_scan {root}", [str(root)], ctx.engine)))
    else:
        sections.append("\n### Virus scan ### \n(ClamAV is not installed — run virus_scan on its own for install details)")

    return "\n".join(sections)


def register(engine):
    engine.registry.register("code_scan", _cmd_code_scan, "code_scan <path> [--fix] — Python security and quality scan (AST plus optional bandit), auto-fixing only the clearly safe cases")
    engine.registry.register("vuln_scan", _cmd_vuln_scan, "vuln_scan <path> — exposed secrets, known dependency vulnerabilities (pip-audit/npm audit), and file permissions")
    engine.registry.register("virus_scan", _cmd_virus_scan, "virus_scan <path> [--no-quarantine] — real virus and spyware scan via ClamAV, quarantining automatically")
    engine.registry.register("quarantine_file", _cmd_quarantine_file, "quarantine_file <path> [reason] — move a suspicious file to quarantine yourself")
    engine.registry.register("quarantine_list", _cmd_quarantine_list, "quarantine_list — everything currently in quarantine")
    engine.registry.register("quarantine_restore", _cmd_quarantine_restore, "quarantine_restore <id> [destination] — restore a file out of quarantine")
    engine.registry.register("security_report", _cmd_security_report, "security_report <path> — full security report: code, vulnerabilities and viruses in one command")
