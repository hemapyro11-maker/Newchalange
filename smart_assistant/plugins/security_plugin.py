"""
security_plugin.py — أدوات أمان أساسية: حساب checksum لملف (تحقق
سلامة/integrity)، وفحص منافذ TCP محلي بسيط لأغراض تشخيصية. استخدم
فحص المنافذ بس على أجهزة إنت مالكها أو عندك إذن صريح تختبرها — فحص
أنظمة غيرك من غير إذن غير قانوني في أغلب الدول، وده خارج نطاق المشروع.
النطاق محدود عمداً (حد أقصى 1024 بورت في المرة) عشان يفضل أداة تشخيص
شخصية مش أداة scanning جماعي.
"""
from __future__ import annotations

import hashlib
import pathlib
import socket

MAX_PORT_RANGE = 1024


def _cmd_hash_file(ctx) -> str:
    if not ctx.args:
        return "usage: hash_file <file> [algo=sha256]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
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
        return f"❌ تعذرت قراءة الملف: {e}"
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


def register(engine):
    engine.registry.register("hash_file", _cmd_hash_file, "hash_file <file> [algo] — حساب checksum لملف (تحقق سلامة)")
    engine.registry.register("port_scan", _cmd_port_scan, "port_scan <host> <start> <end> — فحص منافذ TCP (لأجهزتك بس، حد أقصى 1024 بورت)")
