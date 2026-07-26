"""
security_plugin.py — أدوات أمان أساسية: حساب checksum لملف (تحقق
سلامة/integrity)، وفحص منافذ TCP محلي بسيط لأغراض تشخيصية، فحص شهادات
TLS (تاريخ انتهاء، مُصدر، SAN)، وتدقيق صلاحيات ملفات (world-writable،
SUID/SGID). استخدم فحص المنافذ وTLS بس على أجهزة إنت مالكها أو عندك
إذن صريح تختبرها — فحص أنظمة غيرك من غير إذن غير قانوني في أغلب الدول،
وده خارج نطاق المشروع. النطاق محدود عمداً (حد أقصى 1024 بورت في المرة
لـ port_scan، وحد أقصى لعدد الملفات في file_perms) عشان تفضل أدوات
تشخيص شخصية مش أدوات scanning جماعي.
"""
from __future__ import annotations

import datetime
import hashlib
import pathlib
import socket
import ssl
import stat

MAX_PORT_RANGE = 1024
MAX_FILE_PERMS_SCAN = 5000


def _cmd_hash_file(ctx) -> str:
    if not ctx.args:
        return "usage: hash_file <file> [algo=sha256]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ file not found: {path}"
    algo = ctx.args[1] if len(ctx.args) > 1 else "sha256"
    try:
        h = hashlib.new(algo)
    except ValueError:
        return f"❌ خوارزمية غير مدعومة: {algo} (جرب: {', '.join(sorted(hashlib.algorithms_guaranteed))[:200]})"
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError as e:
        return f"❌ could not read the file: {e}"
    return f"{algo}({path.name}) = {h.hexdigest()}"


def _cmd_port_scan(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: port_scan <host> <start_port> <end_port>  — لأجهزتك أو المصرح لك باختبارها بس"
    host = ctx.args[0]
    try:
        start, end = int(ctx.args[1]), int(ctx.args[2])
    except ValueError:
        return "❌ start_port و end_port لازم يكونوا أرقام"
    if not (0 < start <= 65535 and 0 < end <= 65535):
        return "❌ أرقام البورتات لازم تكون بين 1 و65535"
    if end < start:
        return "❌ end_port لازم يكون أكبر من أو يساوي start_port"
    if end - start + 1 > MAX_PORT_RANGE:
        return f"❌ النطاق كبير أوي — الحد الأقصى {MAX_PORT_RANGE} بورت في المرة الواحدة"

    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return f"❌ تعذر إيجاد المضيف {host}: {e}"

    open_ports = []
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    open_ports.append(port)
        except OSError:
            continue
    if not open_ports:
        return f"مفيش بورتات مفتوحة من {start} لـ {end} على {host}"
    return f"🔓 بورتات مفتوحة على {host}: {', '.join(map(str, open_ports))}"


def _decode_unverified_cert(der_bytes: bytes) -> dict:
    """SSLSocket.getpeercert() بيرجع dict فاضي لو الشهادة متتحققتش
    (verify_mode=CERT_NONE زي في --insecure) — ده سلوك موثق في مكتبة ssl
    القياسية. الطريقة الوحيدة اللي تقرا تفاصيل شهادة غير موثوقة من غير
    ما نضيف مكتبة زي cryptography كـ dependency جديدة للمشروع هي
    ssl._ssl._test_decode_cert (API داخلي بس مستقر عبر إصدارات بايثون
    3.6+ ومُستخدم فعليًا في اختبارات CPython نفسها)."""
    import tempfile

    pem = ssl.DER_cert_to_PEM_cert(der_bytes)
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(pem)
        tmp_path = f.name
    try:
        return ssl._ssl._test_decode_cert(tmp_path)
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)


def _cmd_tls_check(ctx) -> str:
    if not ctx.args:
        return "usage: tls_check <host> [port=443] [--insecure]"
    host = ctx.args[0]
    rest = [a for a in ctx.args[1:] if a != "--insecure"]
    insecure = "--insecure" in ctx.args[1:]
    port = 443
    if rest:
        try:
            port = int(rest[0])
        except ValueError:
            return "❌ port لازم يكون رقم"
    if not (0 < port <= 65535):
        return "❌ port لازم يكون بين 1 و65535"

    context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    try:
        with (
            socket.create_connection((host, port), timeout=5) as sock,
            context.wrap_socket(sock, server_hostname=host) as tls_sock,
        ):
            cert = tls_sock.getpeercert()
            cert_der = tls_sock.getpeercert(binary_form=True)
            cipher = tls_sock.cipher()
    except ssl.SSLCertVerificationError as e:
        return f"❌ الشهادة مش موثوقة/صالحة: {e.verify_message}\n💡 جرب tls_check {host} {port} --insecure عشان تشوف تفاصيلها برضو"
    except socket.gaierror as e:
        return f"❌ تعذر إيجاد المضيف {host}: {e}"
    except (TimeoutError, ConnectionRefusedError, OSError) as e:
        return f"❌ تعذر الاتصال بـ {host}:{port}: {e}"

    if not cert and cert_der:
        try:
            cert = _decode_unverified_cert(cert_der)
        except Exception:
            cert = None
    if not cert:
        return f"⚠️ اتصل بـ {host}:{port} بس مفيش شهادة اتقرت (ممكن --insecure من غير شهادة سيرفر)"

    subject = ", ".join(f"{k}={v}" for pair in cert.get("subject", ()) for k, v in pair)
    issuer = ", ".join(f"{k}={v}" for pair in cert.get("issuer", ()) for k, v in pair)
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]

    try:
        not_after = datetime.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        not_after = not_after.replace(tzinfo=datetime.timezone.utc)
        days_left = (not_after - datetime.datetime.now(datetime.timezone.utc)).days
    except (KeyError, ValueError):
        not_after, days_left = None, None

    lines = [f"🔒 {host}:{port} — {cipher[0] if cipher else 'unknown cipher'}"]
    lines.append(f"  Subject: {subject or '?'}")
    lines.append(f"  Issuer:  {issuer or '?'}")
    if sans:
        lines.append(f"  SAN: {', '.join(sans)}")
    if not_after is not None:
        if days_left < 0:
            lines.append(f"  ❌ الشهادة منتهية من {-days_left} يوم (كانت لغاية {cert['notAfter']})")
        elif days_left < 30:
            lines.append(f"  ⚠️ الشهادة هتنتهي بعد {days_left} يوم ({cert['notAfter']})")
        else:
            lines.append(f"  ✅ صالحة لـ {days_left} يوم كمان (لغاية {cert['notAfter']})")
    if insecure:
        lines.append("  ⚠️ اتعمل الفحص من غير التحقق من صحة الشهادة (--insecure)")
    return "\n".join(lines)


def _cmd_file_perms(ctx) -> str:
    if not ctx.args:
        return "usage: file_perms <path>"
    root = pathlib.Path(ctx.args[0])
    if not root.exists():
        return f"❌ path not found: {root}"

    targets: list[pathlib.Path] = []
    if root.is_file():
        targets.append(root)
    else:
        for p in root.rglob("*"):
            if len(targets) >= MAX_FILE_PERMS_SCAN:
                break
            if p.is_file() or p.is_dir():
                targets.append(p)

    truncated = root.is_dir() and len(targets) >= MAX_FILE_PERMS_SCAN
    findings = []
    for p in targets:
        try:
            st = p.lstat()
        except OSError:
            continue
        mode = st.st_mode
        issues = []
        if stat.S_ISLNK(mode):
            continue
        if mode & stat.S_IWOTH:
            issues.append("world-writable")
        if stat.S_ISREG(mode) and (mode & stat.S_ISUID):
            issues.append("SUID")
        if stat.S_ISREG(mode) and (mode & stat.S_ISGID):
            issues.append("SGID")
        if stat.S_ISREG(mode) and (mode & 0o777) == 0o777:
            issues.append("777 (كل الصلاحيات للكل)")
        name_lower = p.name.lower()
        sensitive = any(kw in name_lower for kw in ("secret", "password", "credential", ".env", "id_rsa", "private_key"))
        if sensitive and (mode & (stat.S_IROTH | stat.S_IRGRP)):
            issues.append("ملف حساس مقروء من غير المالك")
        if issues:
            findings.append((p, oct(mode & 0o7777), issues))

    if not findings:
        summary = f"✅ فحصت {len(targets)} عنصر ({root}) — مفيش مشاكل صلاحيات ظاهرة"
        return summary + ("\n⚠️ (فيه عناصر أكتر متفحصتش — النطاق محدود بـ " + str(MAX_FILE_PERMS_SCAN) + ")" if truncated else "")

    lines = [f"🔍 فحصت {len(targets)} عنصر ولقيت {len(findings)} مشكلة صلاحيات في {root}:"]
    for p, mode_oct, issues in findings[:50]:
        lines.append(f"  ⚠️ {p} ({mode_oct}): {', '.join(issues)}")
    if len(findings) > 50:
        lines.append(f"  ... و{len(findings) - 50} مشكلة تانية متعرضتش")
    if truncated:
        lines.append(f"⚠️ فيه عناصر أكتر متفحصتش — النطاق محدود بـ {MAX_FILE_PERMS_SCAN}")
    return "\n".join(lines)


def register(engine):
    engine.registry.register("hash_file", _cmd_hash_file, "hash_file <file> [algo] — checksum a file to verify its integrity")
    engine.registry.register("port_scan", _cmd_port_scan, "port_scan <host> <start> <end> — scan TCP ports (your own machines only, 1024 ports max)")
    engine.registry.register("tls_check", _cmd_tls_check, "tls_check <host> [port=443] [--insecure] — inspect a TLS certificate (expiry, issuer, SAN)")
    engine.registry.register("file_perms", _cmd_file_perms, "file_perms <path> — audit file permissions (world-writable, SUID/SGID, readable secrets)")
