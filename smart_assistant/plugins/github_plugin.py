"""
github_plugin.py — تكامل Git/GitHub جوه نيزوكو، بنفس فكرة Claude Code:
عمليات Git محلية (status, add, commit, push, pull, branch, diff, log)
+ عمليات GitHub الفعلية (فتح Pull Request, إنشاء Issue, عرض الحالة)
عن طريق GitHub REST API مباشرة، من غير أي اعتمادية خارجية (زي brain.py
بالظبط: urllib من المكتبة القياسية بس).

**نموذج الثقة:** زي external_tools_plugin.py و run — الأوامر هنا بتنفذ
subprocess حقيقي (git) على المشروع اللي نيزوكو شغالة فيه (ctx.engine.
project_dir). مفيش shell=True، ومفيش أي أمر بيتنفذ من غير ما تكتبه إنت
بنفسك — نفس المبدأ الثابت في كل المشروع: "the user confirms first".

**التوكن (GitHub Personal Access Token):** بيتحفظ في مخزن أسرار نظام
التشغيل عبر keyring، بنفس الأسلوب بالظبط اللي telegram_plugin.py و
discord_plugin.py بيستخدموه للتوكنات بتاعتهم — مش نص عادي في ملف JSON.
لو keyring مش متاح، بيرجع تلقائيًا لتخزين نص عادي في github_config.json
مع تحذير واضح (نفس fallback الموجود في brain.py و telegram_plugin.py).

**التوكن مطلوب بس للعمليات اللي بتلمس GitHub API فعليًا** (فتح PR،
عرض/إنشاء Issue). عمليات Git المحلية البحتة (status, add, commit, log,
diff, branch) شغالة من غير توكن خالص — هي أصلاً مجرد `git` عادي.
عملية push بتستخدم بيانات اعتماد Git العادية بتاعتك (SSH key أو
Git Credential Manager) مش التوكن المخزّن هنا؛ التوكن هنا لـ API بس.

الأوامر:
  github_set_token, github_token_status, github_remove_token
  github_status, github_diff, github_add, github_commit
  github_push, github_pull, github_branch, github_checkout, github_log
  github_pr_create, github_pr_list, github_issue_create, github_issue_list
  github_repo_info
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    import keyring
    from keyring.errors import KeyringError
    _HAS_KEYRING = True
except ImportError:  # pragma: no cover - بيعتمد على البيئة
    keyring = None
    KeyringError = Exception
    _HAS_KEYRING = False

_KEYRING_SERVICE = "nezuko-github"
_TOKEN_KEY = "pat"
_API_ROOT = "https://api.github.com"
_TIMEOUT_GIT = 30
_TIMEOUT_API = 20


# ── تخزين التوكن ──────────────────────────────────────────────────────

def _config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "github_config.json"


def _load_plain_token() -> str | None:
    path = _config_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("token")
    except (OSError, json.JSONDecodeError):
        return None


def _save_plain_token(token: str | None) -> None:
    _config_path().write_text(json.dumps({"token": token}, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_token() -> str | None:
    if _HAS_KEYRING:
        try:
            tok = keyring.get_password(_KEYRING_SERVICE, _TOKEN_KEY)
            if tok:
                return tok
        except KeyringError:
            pass
    return _load_plain_token()


def _set_token(token: str) -> str:
    if _HAS_KEYRING:
        try:
            keyring.set_password(_KEYRING_SERVICE, _TOKEN_KEY, token)
            return "✅ token saved securely in the OS credential store"
        except KeyringError:
            pass
    _save_plain_token(token)
    return "⚠️ keyring unavailable — token saved in plain text in github_config.json instead"


def _remove_token() -> str:
    removed = False
    if _HAS_KEYRING:
        try:
            keyring.delete_password(_KEYRING_SERVICE, _TOKEN_KEY)
            removed = True
        except KeyringError:
            pass
    if _load_plain_token() is not None:
        _save_plain_token(None)
        removed = True
    return "✅ token removed" if removed else "no token was stored"


# ── تشغيل git محليًا ─────────────────────────────────────────────────

def _run_git(engine, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=engine.project_dir,
            capture_output=True, text=True, timeout=_TIMEOUT_GIT, shell=False,
        )
    except FileNotFoundError:
        return "❌ git isn't installed or isn't on PATH — https://git-scm.com/downloads"
    except subprocess.TimeoutExpired:
        return f"⏱ git timed out after {_TIMEOUT_GIT}s"
    out = (result.stdout or "") + (result.stderr or "")
    out = out.strip()
    if result.returncode != 0:
        return f"❌ git {' '.join(args)} failed:\n{out or f'(exit code {result.returncode})'}"
    return out or "✅ done (no output)"


def _remote_owner_repo(engine) -> tuple[str, str] | None:
    """بيقرا remote 'origin' ويطلع منه owner/repo، سواء https أو ssh."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=engine.project_dir,
        capture_output=True, text=True, timeout=10, shell=False,
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", url)
    if not m:
        return None
    return m.group(1), m.group(2)


# ── نداءات GitHub API ────────────────────────────────────────────────

def _api(engine, method: str, path: str, body: dict | None = None) -> tuple[bool, dict | str]:
    token = _get_token()
    if not token:
        return False, "❌ no GitHub token set — use github_set_token <token> first (needs 'repo' scope)"
    req = urllib.request.Request(
        f"{_API_ROOT}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nezuko-assistant",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_API) as resp:
            raw = resp.read().decode("utf-8")
            return True, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(raw).get("message", raw)
        except json.JSONDecodeError:
            msg = raw
        return False, f"❌ GitHub API error {e.code}: {msg}"
    except urllib.error.URLError as e:
        return False, f"❌ network error: {e.reason}"


# ── أوامر التوكن ─────────────────────────────────────────────────────

def _cmd_set_token(ctx) -> str:
    if not ctx.args:
        return "usage: github_set_token <personal_access_token>"
    return _set_token(ctx.args[0])


def _cmd_token_status(ctx) -> str:
    tok = _get_token()
    if not tok:
        return "no GitHub token set — github_set_token <token>"
    backend = "OS credential store (keyring)" if _HAS_KEYRING and keyring.get_password(_KEYRING_SERVICE, _TOKEN_KEY) else "plain text file"
    return f"✅ token set ({backend}) — last 4 chars: ...{tok[-4:]}"


def _cmd_remove_token(ctx) -> str:
    return _remove_token()


# ── أوامر Git محلية ──────────────────────────────────────────────────

def _cmd_status(ctx) -> str:
    return _run_git(ctx.engine, ["status", "--short", "--branch"])


def _cmd_diff(ctx) -> str:
    return _run_git(ctx.engine, ["diff", *ctx.args])


def _cmd_add(ctx) -> str:
    if not ctx.args:
        return "usage: github_add <file...> (or 'github_add .' for everything)"
    return _run_git(ctx.engine, ["add", *ctx.args])


def _cmd_commit(ctx) -> str:
    if not ctx.args:
        return "usage: github_commit <message...>"
    message = " ".join(ctx.args)
    return _run_git(ctx.engine, ["commit", "-m", message])


def _cmd_push(ctx) -> str:
    args = list(ctx.args) or []
    return _run_git(ctx.engine, ["push", *args])


def _cmd_pull(ctx) -> str:
    return _run_git(ctx.engine, ["pull", *ctx.args])


def _cmd_branch(ctx) -> str:
    if not ctx.args:
        return _run_git(ctx.engine, ["branch"])
    return _run_git(ctx.engine, ["checkout", "-b", ctx.args[0]])


def _cmd_checkout(ctx) -> str:
    if not ctx.args:
        return "usage: github_checkout <branch_name>"
    return _run_git(ctx.engine, ["checkout", ctx.args[0]])


def _cmd_log(ctx) -> str:
    n = ctx.args[0] if ctx.args and ctx.args[0].isdigit() else "10"
    return _run_git(ctx.engine, ["log", f"-{n}", "--oneline"])


# ── أوامر GitHub API ─────────────────────────────────────────────────

def _cmd_repo_info(ctx) -> str:
    owner_repo = _remote_owner_repo(ctx.engine)
    if not owner_repo:
        return "❌ couldn't find a GitHub remote named 'origin' in this project"
    owner, repo = owner_repo
    ok, data = _api(ctx.engine, "GET", f"/repos/{owner}/{repo}")
    if not ok:
        return data
    return (
        f"📦 {data.get('full_name')}\n"
        f"  ⭐ {data.get('stargazers_count', 0)}  🍴 {data.get('forks_count', 0)}  "
        f"🐛 open issues: {data.get('open_issues_count', 0)}\n"
        f"  default branch: {data.get('default_branch')}\n"
        f"  {data.get('html_url')}"
    )


def _cmd_pr_create(ctx) -> str:
    """usage: github_pr_create <base>|<head>|<title>|<body...>"""
    raw = " ".join(ctx.args)
    parts = raw.split("|")
    if len(parts) < 3:
        return "usage: github_pr_create <base_branch>|<head_branch>|<title>|[body...]"
    base, head, title = (p.strip() for p in parts[:3])
    body = parts[3].strip() if len(parts) > 3 else ""
    owner_repo = _remote_owner_repo(ctx.engine)
    if not owner_repo:
        return "❌ couldn't find a GitHub remote named 'origin' in this project"
    owner, repo = owner_repo
    ok, data = _api(ctx.engine, "POST", f"/repos/{owner}/{repo}/pulls", {
        "title": title, "head": head, "base": base, "body": body,
    })
    if not ok:
        return data
    return f"✅ PR #{data.get('number')} opened: {data.get('html_url')}"


def _cmd_pr_list(ctx) -> str:
    owner_repo = _remote_owner_repo(ctx.engine)
    if not owner_repo:
        return "❌ couldn't find a GitHub remote named 'origin' in this project"
    owner, repo = owner_repo
    ok, data = _api(ctx.engine, "GET", f"/repos/{owner}/{repo}/pulls?state=open")
    if not ok:
        return data
    if not data:
        return "no open pull requests"
    return "\n".join(f"  #{pr['number']} {pr['title']} ({pr['head']['ref']} → {pr['base']['ref']})" for pr in data)


def _cmd_issue_create(ctx) -> str:
    """usage: github_issue_create <title>|[body...]"""
    raw = " ".join(ctx.args)
    parts = raw.split("|")
    title = parts[0].strip()
    if not title:
        return "usage: github_issue_create <title>|[body...]"
    body = parts[1].strip() if len(parts) > 1 else ""
    owner_repo = _remote_owner_repo(ctx.engine)
    if not owner_repo:
        return "❌ couldn't find a GitHub remote named 'origin' in this project"
    owner, repo = owner_repo
    ok, data = _api(ctx.engine, "POST", f"/repos/{owner}/{repo}/issues", {"title": title, "body": body})
    if not ok:
        return data
    return f"✅ issue #{data.get('number')} created: {data.get('html_url')}"


def _cmd_issue_list(ctx) -> str:
    owner_repo = _remote_owner_repo(ctx.engine)
    if not owner_repo:
        return "❌ couldn't find a GitHub remote named 'origin' in this project"
    owner, repo = owner_repo
    ok, data = _api(ctx.engine, "GET", f"/repos/{owner}/{repo}/issues?state=open")
    if not ok:
        return data
    data = [i for i in data if "pull_request" not in i]
    if not data:
        return "no open issues"
    return "\n".join(f"  #{i['number']} {i['title']}" for i in data)


# ── بحث + قراءة ملف مباشرة (من غير clone) ───────────────────────────
#
# دول الوحيدين اللي بيشتغلوا من غير توكن كمان (GitHub بيسمح بـ 10
# نداءات/دقيقة search من غير auth، 30/دقيقة بيه) — بس لو فيه توكن
# بنستخدمه عشان الحد الأعلى يبقى أكبر بكتير ويقل احتمال 403.

def _api_maybe_auth(method: str, path: str) -> tuple[bool, dict | str]:
    token = _get_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nezuko-assistant",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{_API_ROOT}{path}", method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_API) as resp:
            raw = resp.read().decode("utf-8")
            return True, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(raw).get("message", raw)
        except json.JSONDecodeError:
            msg = raw
        hint = "" if _get_token() else " (tip: github_set_token raises the rate limit a lot)"
        return False, f"❌ GitHub API error {e.code}: {msg}{hint}"
    except urllib.error.URLError as e:
        return False, f"❌ network error: {e.reason}"


def _cmd_search_repos(ctx) -> str:
    if not ctx.args:
        return "usage: github_search_repos <query...>"
    query = urllib.parse.quote(" ".join(ctx.args))
    ok, data = _api_maybe_auth("GET", f"/search/repositories?q={query}&sort=stars&order=desc&per_page=10")
    if not ok:
        return data
    items = data.get("items", [])
    if not items:
        return "no repositories found"
    lines = [f"🔎 {data.get('total_count', len(items))} result(s), top {len(items)}:"]
    for r in items:
        lines.append(f"  ⭐{r['stargazers_count']:<6} {r['full_name']} — {(r.get('description') or '').strip()[:80]}")
        lines.append(f"           {r['html_url']}")
    return "\n".join(lines)


def _cmd_search_code(ctx) -> str:
    """usage: github_search_code <query...> [in:owner/repo]"""
    if not ctx.args:
        return "usage: github_search_code <query...> (add 'repo:owner/name' to narrow to one repo)"
    query = urllib.parse.quote(" ".join(ctx.args))
    ok, data = _api_maybe_auth("GET", f"/search/code?q={query}&per_page=15")
    if not ok:
        return data if isinstance(data, str) else data
    items = data.get("items", [])
    if not items:
        return "no matching code found"
    lines = [f"🔎 {data.get('total_count', len(items))} result(s), top {len(items)}:"]
    for it in items:
        lines.append(f"  {it['repository']['full_name']}: {it['path']}")
        lines.append(f"           {it['html_url']}")
    return "\n".join(lines)


def _cmd_get_file(ctx) -> str:
    """usage: github_get_file <owner/repo> <path> [ref]"""
    if len(ctx.args) < 2:
        return "usage: github_get_file <owner/repo> <path/to/file> [branch_or_tag]"
    owner_repo, path = ctx.args[0], ctx.args[1]
    if "/" not in owner_repo:
        return "❌ first argument must be owner/repo, e.g. torvalds/linux"
    owner, repo = owner_repo.split("/", 1)
    ref_qs = f"?ref={urllib.parse.quote(ctx.args[2])}" if len(ctx.args) > 2 else ""
    ok, data = _api_maybe_auth("GET", f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}{ref_qs}")
    if not ok:
        return data
    if isinstance(data, list):
        return f"❌ '{path}' is a directory, not a file — entries: " + ", ".join(e["name"] for e in data[:30])
    if data.get("encoding") != "base64":
        return f"❌ unexpected encoding: {data.get('encoding')}"
    import base64
    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
    except UnicodeDecodeError:
        return f"⚠️ '{path}' looks like a binary file ({data.get('size', 0)} bytes) — can't display as text.\n{data.get('html_url')}"
    header = f"📄 {owner}/{repo}:{path} ({data.get('size', 0)} bytes)\n" + "─" * 40 + "\n"
    if len(content) > 8000:
        content = content[:8000] + f"\n... (truncated, {len(content)} chars total — narrow with github_get_file for a smaller file, or open {data.get('html_url')})"
    return header + content


def register(engine):
    engine.registry.register("github_set_token", _cmd_set_token,
                              "github_set_token <token> — save a GitHub Personal Access Token (needs 'repo' scope)")
    engine.registry.register("github_token_status", _cmd_token_status,
                              "github_token_status — check if a GitHub token is stored")
    engine.registry.register("github_remove_token", _cmd_remove_token,
                              "github_remove_token — delete the stored GitHub token")
    engine.registry.register("github_status", _cmd_status,
                              "github_status — git status (short + branch)")
    engine.registry.register("github_diff", _cmd_diff,
                              "github_diff [file] — git diff, optionally for one file")
    engine.registry.register("github_add", _cmd_add,
                              "github_add <file...> — git add (use '.' for everything)")
    engine.registry.register("github_commit", _cmd_commit,
                              "github_commit <message...> — git commit -m")
    engine.registry.register("github_push", _cmd_push,
                              "github_push [remote] [branch] — git push")
    engine.registry.register("github_pull", _cmd_pull,
                              "github_pull — git pull")
    engine.registry.register("github_branch", _cmd_branch,
                              "github_branch [name] — list branches, or create+switch to a new one")
    engine.registry.register("github_checkout", _cmd_checkout,
                              "github_checkout <branch> — switch branches")
    engine.registry.register("github_log", _cmd_log,
                              "github_log [n] — last n commits, one line each (default 10)")
    engine.registry.register("github_repo_info", _cmd_repo_info,
                              "github_repo_info — show stars/forks/issues for this repo (needs token)")
    engine.registry.register("github_pr_create", _cmd_pr_create,
                              "github_pr_create <base>|<head>|<title>|[body] — open a pull request (needs token)")
    engine.registry.register("github_pr_list", _cmd_pr_list,
                              "github_pr_list — list open pull requests (needs token)")
    engine.registry.register("github_issue_create", _cmd_issue_create,
                              "github_issue_create <title>|[body] — open an issue (needs token)")
    engine.registry.register("github_issue_list", _cmd_issue_list,
                              "github_issue_list — list open issues (needs token)")
    engine.registry.register("github_search_repos", _cmd_search_repos,
                              "github_search_repos <query...> — search GitHub repositories by name/topic")
    engine.registry.register("github_search_code", _cmd_search_code,
                              "github_search_code <query...> — search code across GitHub (add 'repo:owner/name' to narrow)")
    engine.registry.register("github_get_file", _cmd_get_file,
                              "github_get_file <owner/repo> <path> [ref] — read a single file's content from any repo, no clone needed")
