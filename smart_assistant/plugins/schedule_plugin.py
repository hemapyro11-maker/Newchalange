"""
schedule_plugin.py — أتمتة أوامر نيزوكو على مواعيد (زي cron، لكن أبسط
وبصياغة نصية بسيطة بدل خمس حقول رقمية). مستوحى من ميزة الـ cron/webhook
automation في Clawdbot، وده كان غايب تمامًا من نيزوكو قبل كده.

صيغ المواعيد المدعومة:
  every:<N>s|m|h|d    — كل N ثانية/دقيقة/ساعة/يوم (زي: every:30m)
  daily:HH:MM         — كل يوم الساعة دي (زي: daily:09:00)
  weekly:day:HH:MM    — كل أسبوع يوم معيّن الساعة دي (زي: weekly:mon:09:00)

الأوامر بتتحفظ في schedule.json (محلي، خارج git زي أي state file تاني في
المشروع) وبتتنفذ عبر thread خلفي واحد بيفحص كل 15 ثانية أي جدول "مستحق"
ويبعته لنفس طابور التنفيذ العادي (engine.submit) — يعني بينفذ بنفس
الصلاحيات والمسار اللي أي أمر عادي بيمشي فيه، مفيش تنفيذ "خاص" أو تحايل
على أي حماية موجودة أصلاً (زي فحص core_engine للأوامر غير الموجودة).

الأوامر: schedule add|list|remove|pause|resume|run_now
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys
import threading

_EVERY_RE = re.compile(r"^every:(\d+)([smhd])$")
_DAILY_RE = re.compile(r"^daily:(\d{1,2}):(\d{2})$")
_WEEKLY_RE = re.compile(r"^weekly:(mon|tue|wed|thu|fri|sat|sun):(\d{1,2}):(\d{2})$")
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_TICK_SECONDS = 15


def _schedule_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "schedule.json"


def _load() -> dict:
    path = _schedule_path()
    if not path.exists():
        return {"jobs": [], "next_id": 1}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"jobs": [], "next_id": 1}
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return {"jobs": [], "next_id": 1}
    data.setdefault("next_id", 1)
    return data


def _save(data: dict) -> None:
    try:
        _schedule_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _lock(engine) -> threading.Lock:
    if not hasattr(engine, "_schedule_lock"):
        engine._schedule_lock = threading.Lock()
    return engine._schedule_lock


def _parse_spec(spec: str) -> tuple[str, dict] | None:
    m = _EVERY_RE.match(spec)
    if m:
        n, unit = m.groups()
        return "every", {"seconds": int(n) * _UNIT_SECONDS[unit]}
    m = _DAILY_RE.match(spec)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return "daily", {"hour": hour, "minute": minute}
    m = _WEEKLY_RE.match(spec)
    if m:
        day, hour, minute = m.group(1), int(m.group(2)), int(m.group(3))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return "weekly", {"weekday": _WEEKDAYS[day], "hour": hour, "minute": minute}
    return None


def _compute_next_run(kind: str, params: dict, after: datetime.datetime) -> datetime.datetime:
    if kind == "every":
        return after + datetime.timedelta(seconds=params["seconds"])
    if kind == "daily":
        candidate = after.replace(hour=params["hour"], minute=params["minute"], second=0, microsecond=0)
        if candidate <= after:
            candidate += datetime.timedelta(days=1)
        return candidate
    if kind == "weekly":
        candidate = after.replace(hour=params["hour"], minute=params["minute"], second=0, microsecond=0)
        days_ahead = (params["weekday"] - candidate.weekday()) % 7
        candidate += datetime.timedelta(days=days_ahead)
        if candidate <= after:
            candidate += datetime.timedelta(days=7)
        return candidate
    raise ValueError(f"unknown schedule kind: {kind}")


def _tick(engine) -> None:
    with _lock(engine):
        data = _load()
        now = datetime.datetime.now()
        changed = False
        for job in data["jobs"]:
            if not job.get("enabled", True):
                continue
            try:
                next_run = datetime.datetime.fromisoformat(job["next_run"])
            except ValueError:
                continue
            if next_run > now:
                continue
            engine.submit(job["command"])
            job["last_run"] = now.isoformat(timespec="seconds")
            parsed = _parse_spec(job["spec"])
            if parsed is None:
                continue
            kind, params = parsed
            job["next_run"] = _compute_next_run(kind, params, now).isoformat(timespec="seconds")
            changed = True
        if changed:
            _save(data)


def _scheduler_loop(engine, stop_event: threading.Event) -> None:
    while not stop_event.wait(_TICK_SECONDS):
        try:
            _tick(engine)
        except Exception:
            pass


def _ensure_scheduler_started(engine) -> None:
    existing = getattr(engine, "_scheduler_thread", None)
    if existing is not None and existing.is_alive():
        return
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_scheduler_loop, args=(engine, stop_event), daemon=True, name="nezuko-scheduler",
    )
    engine._scheduler_stop = stop_event
    engine._scheduler_thread = thread
    thread.start()


def _usage() -> str:
    return (
        "usage:\n"
        "  schedule add <spec> <command...>    — schedule a new command\n"
        "     spec: every:<N>s|m|h|d  |  daily:HH:MM  |  weekly:mon..sun:HH:MM\n"
        "     example: schedule add daily:09:00 channel_growth_report @MrBeast\n"
        "  schedule list                        — show every schedule\n"
        "  schedule remove <id>                 — delete a schedule\n"
        "  schedule pause <id> / resume <id>     — pause or resume without deleting\n"
        "  schedule run_now <id>                — run it now instead of waiting"
    )


def _handle_add(ctx) -> str:
    parts = ctx.raw.split(maxsplit=3)
    if len(parts) < 4 or not parts[3].strip():
        return _usage()
    spec, command = parts[2], parts[3].strip()
    parsed = _parse_spec(spec)
    if parsed is None:
        return f"❌ could not read that schedule: {spec}\n  use: every:<N>s|m|h|d  |  daily:HH:MM  |  weekly:mon..sun:HH:MM"
    kind, params = parsed
    cmd_name = command.split(maxsplit=1)[0]
    warn = ""
    if ctx.engine.registry.get(cmd_name) is None:
        warn = f"\n⚠️ warning: '{cmd_name}' is not a registered command right now — the schedule is saved anyway, but it will fail when it fires unless that changes."
    with _lock(ctx.engine):
        data = _load()
        job_id = data["next_id"]
        data["next_id"] += 1
        now = datetime.datetime.now()
        next_run = _compute_next_run(kind, params, now)
        data["jobs"].append({
            "id": job_id, "spec": spec, "command": command, "enabled": True,
            "next_run": next_run.isoformat(timespec="seconds"),
            "last_run": None, "created": now.isoformat(timespec="seconds"),
        })
        _save(data)
    return f"✅ added #{job_id} — first run: {next_run.strftime('%Y-%m-%d %H:%M')}{warn}"


def _handle_list(ctx) -> str:
    data = _load()
    if not data["jobs"]:
        return "Nothing scheduled. Add one with: schedule add <spec> <command...>"
    lines = ["📅 Scheduled commands:"]
    for job in sorted(data["jobs"], key=lambda j: j["id"]):
        status = "✅" if job.get("enabled", True) else "⏸"
        line = f"  {status} #{job['id']} [{job['spec']}] {job['command']} — next: {job['next_run']}"
        if job.get("last_run"):
            line += f" — last run: {job['last_run']}"
        lines.append(line)
    return "\n".join(lines)


def _find_job(data: dict, job_id: int) -> dict | None:
    return next((j for j in data["jobs"] if j["id"] == job_id), None)


def _handle_remove(ctx) -> str:
    if len(ctx.args) < 2 or not ctx.args[1].isdigit():
        return "usage: schedule remove <id>"
    job_id = int(ctx.args[1])
    with _lock(ctx.engine):
        data = _load()
        before = len(data["jobs"])
        data["jobs"] = [j for j in data["jobs"] if j["id"] != job_id]
        if len(data["jobs"]) == before:
            return f"❌ no schedule numbered #{job_id}"
        _save(data)
    return f"🗑 removed #{job_id}"


def _handle_toggle(ctx, enabled: bool) -> str:
    verb = "resume" if enabled else "pause"
    if len(ctx.args) < 2 or not ctx.args[1].isdigit():
        return f"usage: schedule {verb} <id>"
    job_id = int(ctx.args[1])
    with _lock(ctx.engine):
        data = _load()
        job = _find_job(data, job_id)
        if job is None:
            return f"❌ no schedule numbered #{job_id}"
        job["enabled"] = enabled
        _save(data)
    return f"{'▶️ resumed' if enabled else '⏸ paused'} #{job_id}"


def _handle_run_now(ctx) -> str:
    if len(ctx.args) < 2 or not ctx.args[1].isdigit():
        return "usage: schedule run_now <id>"
    job_id = int(ctx.args[1])
    data = _load()
    job = _find_job(data, job_id)
    if job is None:
        return f"❌ no schedule numbered #{job_id}"
    ctx.engine.submit(job["command"])
    return f"▶️ sent #{job_id} ({job['command']}) to run now"


def _cmd_schedule(ctx) -> str:
    if not ctx.args:
        return _usage()
    sub = ctx.args[0].lower()
    if sub == "add":
        return _handle_add(ctx)
    if sub == "list":
        return _handle_list(ctx)
    if sub == "remove":
        return _handle_remove(ctx)
    if sub == "pause":
        return _handle_toggle(ctx, enabled=False)
    if sub == "resume":
        return _handle_toggle(ctx, enabled=True)
    if sub == "run_now":
        return _handle_run_now(ctx)
    return _usage()


def register(engine):
    engine.registry.register(
        "schedule", _cmd_schedule,
        "schedule add|list|remove|pause|resume|run_now — run Nezuko commands on a timer (every:/daily:/weekly:)",
    )
    _ensure_scheduler_started(engine)
