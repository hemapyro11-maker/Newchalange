"""
self_update_plugin.py — بيزامن مجلد plugins/ المحلي مع اللي في الريبو
على GitHub، من غير أي حاجة لإعادة بناء Nezuko.exe.

**ليه ده ممكن للـ plugins بس مش للمحرك كله:** لما نيزوكو شغالة كـ exe
(PyInstaller onefile)، بتدوّر على مجلد `plugins/` **جنب ملف الـ exe نفسه**
بالإضافة للمجلد المتجمّع جواها (`core_engine.default_plugin_dirs`).
يعني نقدر نكتب ملفات .py جديدة في المجلد الخارجي ده بأمان وهي شغالة —
مجرد ملفات على القرص، مش استبدال للـ exe نفسه اللي شغال دلوقتي (وده
عملية خطرة وموضّح في update_plugin.py ليه مش بيحصل تلقائي).

أما core_engine.py, brain.py, i18n.py, main_gui.py وباقي ملفات الجذر —
دول متجمّعين *جوه* الـ exe وقت البناء، فمفيش طريقة آمنة تتغير من غير
إعادة build_exe.bat فعليًا. self_update_status بيوضح الفرق ده صريح.

**التدفق:**
  1. self_update_status  → مقارنة (بدون أي كتابة) بين اللي عندك محليًا
     واللي في الريبو، حسب SHA بتاع كل ملف (من GitHub Contents API).
  2. self_update_apply [أسماء...]  → التحميل والكتابة الفعلية، بس على
     الملفات اللي self_update_status وضّح إنها جديدة/اتغيّرت. من غير
     أسماء = يطبّق على كل حاجة تغيّرت.

الحالة (آخر SHA اتطبّق لكل ملف) بتتحفظ في self_update_state.json جنب
باقي ملفات الحالة (زي external_tools.json بالظبط).
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

_OWNER = "hemapyro11-maker"
_REPO = "Newchalange"
_BRANCH = "claude/project-guidelines-architecture-dcn5vq"
_REMOTE_PLUGINS_PATH = "smart_assistant/plugins"
_API_ROOT = "https://api.github.com"
_TIMEOUT = 20


def _config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "self_update_state.json"


def _local_plugins_dir() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent
    return base


def _load_state() -> dict:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    _config_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_remote_listing() -> tuple[bool, list[dict] | str]:
    url = f"{_API_ROOT}/repos/{_OWNER}/{_REPO}/contents/{_REMOTE_PLUGINS_PATH}?ref={_BRANCH}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nezuko-assistant",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return False, f"❌ GitHub API error {e.code} — couldn't list the remote plugins folder"
    except urllib.error.URLError as e:
        return False, f"❌ network error: {e.reason}"
    if not isinstance(data, list):
        return False, "❌ unexpected response shape from GitHub"
    return True, [f for f in data if f.get("type") == "file" and f["name"].endswith(".py")]


def _diff(remote_files: list[dict], state: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """بيرجع (new, changed, unchanged) بمقارنة الـ sha المحفوظ بآخر تطبيق."""
    new_, changed, unchanged = [], [], []
    for f in remote_files:
        known_sha = state.get(f["name"])
        if known_sha is None:
            new_.append(f)
        elif known_sha != f["sha"]:
            changed.append(f)
        else:
            unchanged.append(f)
    return new_, changed, unchanged


def _cmd_status(ctx) -> str:
    ok, result = _fetch_remote_listing()
    if not ok:
        return result
    state = _load_state()
    new_, changed, unchanged = _diff(result, state)

    lines = ["📡 comparing local plugins/ with GitHub (no files touched):"]
    if new_:
        lines.append(f"\n🆕 new on GitHub, not installed locally ({len(new_)}):")
        lines += [f"   • {f['name']}" for f in new_]
    if changed:
        lines.append(f"\n♻️  updated on GitHub since your last sync ({len(changed)}):")
        lines += [f"   • {f['name']}" for f in changed]
    if not new_ and not changed:
        lines.append("\n✅ everything is up to date")
    else:
        lines.append("\nrun 'self_update_apply' to download+install these — no exe rebuild needed.")
    if unchanged:
        lines.append(f"\n({len(unchanged)} file(s) already in sync)")
    lines.append(
        "\n⚠️ note: this only covers plugins/. Core files (core_engine.py, "
        "brain.py, main_gui.py, ...) are baked into the exe and still need "
        "build_exe.bat if they change — check_update tells you when that's the case."
    )
    return "\n".join(lines)


def _cmd_apply(ctx) -> str:
    ok, result = _fetch_remote_listing()
    if not ok:
        return result
    state = _load_state()
    new_, changed, _ = _diff(result, state)
    pending = {f["name"]: f for f in (new_ + changed)}

    if not pending:
        return "✅ nothing to update — local plugins/ already matches GitHub"

    requested = set(ctx.args) if ctx.args else set(pending.keys())
    unknown = requested - pending.keys()
    if unknown:
        return f"❌ these aren't pending updates: {', '.join(sorted(unknown))} — run self_update_status first"

    target_dir = _local_plugins_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    applied, failed = [], []
    for name in sorted(requested):
        f = pending[name]
        try:
            req = urllib.request.Request(f["download_url"], headers={"User-Agent": "nezuko-assistant"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                content = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            failed.append(f"{name} ({e})")
            continue
        (target_dir / name).write_bytes(content)
        state[name] = f["sha"]
        applied.append(name)

    _save_state(state)
    lines = []
    if applied:
        lines.append(f"✅ updated {len(applied)} file(s): {', '.join(applied)}")
        lines.append("run 'reload_plugins' now to pick them up — no exe rebuild needed.")
    if failed:
        lines.append(f"❌ failed: {', '.join(failed)}")
    return "\n".join(lines)


def register(engine):
    engine.registry.register("self_update_status", _cmd_status,
                              "self_update_status — compare local plugins/ against GitHub (read-only, no changes made)")
    engine.registry.register("self_update_apply", _cmd_apply,
                              "self_update_apply [file...] — download+install pending plugin updates from GitHub (no exe rebuild needed); no args = apply all pending")
