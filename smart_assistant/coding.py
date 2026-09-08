"""Project-oriented coding commands shared by the desktop and terminal clients."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
MAX_OUTPUT = 24_000
READ_ONLY = {"read_file", "list_files", "search", "git_status", "git_diff", "help", "echo", "plugins", "skills", "mode", "project"}


def instructions(root):
    sections = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= 32_000:
                sections.append(f"{name}:\n{path.read_text(encoding='utf-8')[:8000]}")
        except (OSError, UnicodeError):
            pass
    return "\n\n".join(sections)


def mode(ctx):
    if not ctx.args:
        return f"Mode: {ctx.engine.coding_mode} (ask or plan)"
    if ctx.args not in (["ask"], ["plan"]):
        return "usage: mode ask|plan"
    ctx.engine.cancel()
    ctx.engine.coding_mode = ctx.args[0]
    return f"Mode: {ctx.engine.coding_mode}. Plan mode allows only project inspection commands."


def files(root):
    """Bounded traversal without following directory symlinks or reading secrets."""
    count = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or name.endswith((".pem", ".key", ".nezuko-bak")):
                continue
            path = pathlib.Path(directory) / name
            if path.is_symlink():
                continue
            yield path
            count += 1
            if count >= 10_000:
                return


def _run(engine, argv, timeout=120):
    try:
        result = subprocess.run(argv, cwd=engine.project_dir, shell=False,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Command failed: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    suffix = "\n[output truncated]" if len(output) > MAX_OUTPUT else ""
    return f"exit code {result.returncode}\n{output[:MAX_OUTPUT]}{suffix}"


def project(ctx):
    if not ctx.args:
        return str(ctx.engine.project_dir)
    path = pathlib.Path(ctx.args[0]).expanduser().resolve()
    if len(ctx.args) != 1 or not path.is_dir():
        return 'usage: project "existing project directory"'
    ctx.engine.new_session()
    ctx.engine.project_dir = path
    return f"Project: {path}\nStarted a new session for this project."


def list_files(ctx):
    pattern = ctx.args[0] if ctx.args else "*"
    paths = []
    for path in files(ctx.engine.project_dir):
        relative = path.relative_to(ctx.engine.project_dir)
        if relative.match(pattern):
            paths.append(relative.as_posix())
        if len(paths) >= 500:
            paths.append("[500 results; narrow the glob]")
            break
    return "\n".join(paths) or "No matching files."


def search(ctx):
    if not ctx.args:
        return 'usage: search "literal text" [file glob]'
    needle = ctx.args[0]
    pattern = ctx.args[1] if len(ctx.args) > 1 else "*"
    results = []
    for path in files(ctx.engine.project_dir):
        relative = path.relative_to(ctx.engine.project_dir)
        try:
            if not relative.match(pattern) or path.stat().st_size > 1_000_000:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "\0" in content:
            continue
        for number, line in enumerate(content.splitlines(), 1):
            if needle in line:
                results.append(f"{relative.as_posix()}:{number}: {line[:500]}")
                if len(results) >= 100:
                    return "\n".join(results) + "\n[100 matches; narrow the search]"
    return "\n".join(results) or "No matches."


def test(ctx):
    """Tests execute project code and therefore require model-tool approval."""
    if ctx.args:
        argv = ctx.args
    elif getattr(sys, "frozen", False):
        return "Supply the project's test executable: test <python path> -m pytest"
    else:
        argv = [sys.executable, "-m", "pytest", "-q"]
    return _run(ctx.engine, argv)


def register(engine):
    engine.registry.register("mode", mode, "mode ask|plan — switch between approved execution and read-only planning")
    engine.registry.register("project", project, 'project ["directory"] — show/open a project')
    engine.registry.register("list_files", list_files, "list_files [glob] — list project files")
    engine.registry.register("search", search, 'search "text" [glob] — search project source')
    engine.registry.register("git_status", lambda ctx: _run(ctx.engine, ["git", "status", "--short"]),
                             "git_status — inspect local changes")
    engine.registry.register("git_diff", lambda ctx: _run(ctx.engine, ["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv", "--", *ctx.args]),
                             "git_diff [paths] — inspect unstaged edits without external diff programs")
    engine.registry.register("test", test, "test [executable args...] — run project tests (default: Python pytest)")
