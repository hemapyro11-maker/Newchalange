"""
repomap.py — خريطة مرتّبة للكود، عشان المخ يشوف المشروع كله مش ملف واحد.

**المشكلة اللي بيحلها:** لما تقول "صلّح الباج في التسجيل"، المخ محتاج
يعرف إيه الموجود في المشروع أصلاً. من غير ده بيخمّن أسماء دوال، أو
بيطلب منك تلزق الملف بإيدك. لكن المشروع كله مستحيل يتبعت — 16 ألف سطر
أكبر من سياق أي مزوّد مجاني.

**الحل (مأخوذ من aider، وهي أداة مفتوحة المصدر Apache-2.0):** نبعت
**التعريفات بس** — أسماء الدوال والكلاسات وتوقيعاتها من غير أجسامها —
ومرتّبة بالأهمية. الترتيب مش أبجدي ولا بحجم الملف: بنبني جراف "مين
بيستخدم مين" ونشغّل عليه **PageRank**. دالة بينادي عليها عشرين حتة أهم
من helper خاص بينادى عليه مرة واحدة، بالظبط زي صفحة كتير رابطين ليها.

التنفيذ ده بيستخدم tree-sitter (بيفهم بنية الكود فعليًا، مش regex)
و PageRank متكتوبة هنا في ~20 سطر بدل ما نجيب networkx كدبندنسي كامل.

اختياري بالكامل: من غير tree-sitter بترجع خريطة فاضية والباقي شغال.
"""
from __future__ import annotations

import pathlib

# امتدادات → اسم اللغة في tree-sitter-language-pack
_LANGS = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".jsx": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".cs": "c_sharp", ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".lua": "lua", ".sh": "bash", ".sql": "sql",
}

# مجلدات مبنعدّيش عليها — مش كود المشروع
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".pytest_cache", ".mypy_cache", "site-packages",
    ".tox", "target", "vendor", ".next", "coverage", "htmlcov",
}

_MAX_FILE_BYTES = 400_000     # ملف أكبر من كده غالبًا مولّد أو بيانات
_MAX_FILES = 800              # سقف عشان مشروع ضخم ميعلّقش
_DAMPING = 0.85               # معامل PageRank القياسي
_ITERATIONS = 30

# أنواع العُقد اللي بتمثّل تعريف في أغلب قواعد tree-sitter
_DEF_HINTS = ("definition", "declaration", "declarator", "item")
# ودي مش تعريفات رغم إن اسمها فيه declaration
_DEF_EXCLUDE = ("variable_declaration", "lexical_declaration",
                "import_declaration", "package_declaration")


def _parser_for(lang: str):
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    try:
        return get_parser(lang)
    except Exception:  # noqa: BLE001 - لغة مش مدعومة في النسخة دي
        return None


def available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
    except ImportError:
        return False
    return True


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)


def _name_of(node) -> str | None:
    """اسم التعريف — بناخده من الحقل المسمّى `name` لو موجود."""
    child = node.child_by_field_name("name")
    if child is not None and child.text:
        return child.text.decode("utf-8", "replace")
    # بعض القواعد بتحط الاسم جوه declarator متداخل
    child = node.child_by_field_name("declarator")
    if child is not None:
        inner = child.child_by_field_name("declarator")
        target = inner if inner is not None else child
        if target.text and target.type in ("identifier", "field_identifier"):
            return target.text.decode("utf-8", "replace")
    return None


def _is_def(node_type: str) -> bool:
    if any(bad in node_type for bad in _DEF_EXCLUDE):
        return False
    return any(hint in node_type for hint in _DEF_HINTS)


def scan_file(path: pathlib.Path) -> tuple[set[str], set[str]]:
    """بيرجع (التعريفات، الإشارات) في الملف ده.

    التعريفات = أسماء الدوال/الكلاسات المعرّفة هنا.
    الإشارات   = كل المعرّفات المستخدمة، وهي اللي بتبني حواف الجراف.
    """
    lang = _LANGS.get(path.suffix.lower())
    if lang is None:
        return set(), set()
    parser = _parser_for(lang)
    if parser is None:
        return set(), set()
    try:
        data = path.read_bytes()
    except OSError:
        return set(), set()
    if len(data) > _MAX_FILE_BYTES:
        return set(), set()
    try:
        tree = parser.parse(data)
    except Exception:  # noqa: BLE001
        return set(), set()

    defs: set[str] = set()
    refs: set[str] = set()
    for node in _walk(tree.root_node):
        if _is_def(node.type):
            name = _name_of(node)
            if name:
                defs.add(name)
        elif node.type in ("identifier", "field_identifier", "type_identifier"):
            if node.text:
                refs.add(node.text.decode("utf-8", "replace"))
    return defs, refs - defs


def _pagerank(out_edges: dict[str, dict[str, float]],
              personalization: dict[str, float]) -> dict[str, float]:
    """PageRank على جراف الملفات.

    مكتوبة هنا بدل ما نجيب networkx: الخوارزمية نفسها عشرين سطر،
    وجلب دبندنسي كامل عشانها بس مش مبرر في مشروع بيتحزم كـ exe.
    """
    nodes = set(out_edges) | {t for d in out_edges.values() for t in d}
    nodes |= set(personalization)
    if not nodes:
        return {}
    n = len(nodes)

    total_p = sum(personalization.values())
    if total_p > 0:
        base = {k: personalization.get(k, 0.0) / total_p for k in nodes}
    else:
        base = {k: 1.0 / n for k in nodes}

    rank = {k: 1.0 / n for k in nodes}
    for _ in range(_ITERATIONS):
        nxt = {k: (1 - _DAMPING) * base[k] for k in nodes}
        dangling = 0.0
        for node in nodes:
            targets = out_edges.get(node) or {}
            weight_sum = sum(targets.values())
            if weight_sum <= 0:
                dangling += rank[node]
                continue
            for target, w in targets.items():
                nxt[target] += _DAMPING * rank[node] * (w / weight_sum)
        if dangling:
            for k in nodes:
                nxt[k] += _DAMPING * dangling * base[k]
        rank = nxt
    return rank


def _is_test_path(key: str) -> bool:
    low = key.lower()
    return (
        "test" in pathlib.Path(low).name
        or "tests" in pathlib.PurePosixPath(low.replace("\\", "/")).parts
    )


def _source_files(root: pathlib.Path) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for path in sorted(root.rglob("*")):
        if len(out) >= _MAX_FILES:
            break
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _LANGS:
            out.append(path)
    return out


# تحليل المشروع كله بياخد ثواني، ومينفعش يتعاد مع كل رسالة. بنكاش
# نتيجة القراءة (مش الخريطة النهائية — دي بتتغير حسب اللي المستخدم
# ذكره)، وبنبطّلها لو أي ملف اتعدّل.
_scan_cache: dict[str, tuple[float, int, dict, dict, dict]] = {}


def reset_cache() -> None:
    _scan_cache.clear()


def _scan_tree(root: pathlib.Path):
    files = _source_files(root)
    if not files:
        return {}, {}, {}

    try:
        stamp = max(p.stat().st_mtime for p in files)
    except OSError:
        stamp = 0.0
    key = str(root.resolve())
    cached = _scan_cache.get(key)
    if cached and cached[0] == stamp and cached[1] == len(files):
        return cached[2], cached[3], cached[4]

    file_defs: dict[str, set[str]] = {}
    file_refs: dict[str, set[str]] = {}
    definer: dict[str, list[str]] = {}
    for path in files:
        name = str(path.relative_to(root))
        defs, refs = scan_file(path)
        if not defs and not refs:
            continue
        file_defs[name] = defs
        file_refs[name] = refs
        for symbol in defs:
            definer.setdefault(symbol, []).append(name)

    _scan_cache[key] = (stamp, len(files), file_defs, file_refs, definer)
    return file_defs, file_refs, definer


def build(root: str | pathlib.Path, mentioned: set[str] | None = None,
          budget_chars: int = 6000) -> str:
    """بيبني خريطة نصية للمشروع، مرتّبة بالأهمية ومحدودة بميزانية.

    `mentioned` = أسماء جت في كلام المستخدم. الملفات اللي بتعرّفها
    بتاخد وزن أعلى بكتير، فالخريطة بتتمركز حوالين اللي بتسأل عنه.
    """
    root = pathlib.Path(root)
    if not root.is_dir() or not available():
        return ""

    mentioned = {m.lower() for m in (mentioned or set())}
    file_defs, file_refs, definer = _scan_tree(root)
    if not file_defs:
        return ""

    # حواف: ملف بيستخدم اسم ← الملف اللي بيعرّفه
    out_edges: dict[str, dict[str, float]] = {k: {} for k in file_defs}
    for src, refs in file_refs.items():
        for name in refs:
            for dst in definer.get(name, ()):
                if dst == src:
                    continue
                weight = 10.0 if name.lower() in mentioned else 1.0
                out_edges[src][dst] = out_edges[src].get(dst, 0.0) + weight

    # ملفات الاختبارات بتعرّف مئات الدوال وبتشاور على كل حاجة، فبتطلع
    # فوق في PageRank من غير ما تكون هي اللي بتعدّل فيها. بنخفّض وزنها
    # بدل ما نشيلها — أحيانًا بتكون هي المقصودة فعلاً.
    personalization = {}
    for key, defs in file_defs.items():
        if any(d.lower() in mentioned for d in defs):
            weight = 50.0
        elif _is_test_path(key):
            weight = 0.15
        else:
            weight = 1.0
        personalization[key] = weight

    rank = _pagerank(out_edges, personalization)
    # الوزن بيدخل في الترتيب النهائي كمان، مش في نقطة الانطلاق بس. من
    # غير كده ملف اختبارات بيعرّف 80 دالة بيفضل طالع فوق رغم إنه آخر
    # حاجة المستخدم بيعدّل فيها.
    ordered = sorted(
        file_defs,
        key=lambda k: -(rank.get(k, 0.0) * min(personalization.get(k, 1.0), 1.0)),
    )

    lines = ["Repository map (most structurally important first):"]
    used = len(lines[0])
    for key in ordered:
        defs = sorted(file_defs[key])
        if not defs:
            continue
        shown = defs[:12]
        more = f"  … +{len(defs) - 12}" if len(defs) > 12 else ""
        block = f"\n{key}\n  " + "\n  ".join(shown) + more
        if used + len(block) > budget_chars:
            break
        lines.append(block)
        used += len(block)
    if len(lines) == 1:
        return ""
    return "".join(lines)
