import datetime

import pytest
import schedule_plugin as sp


@pytest.fixture(autouse=True)
def _isolate_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "_schedule_path", lambda: tmp_path / "schedule.json")


# ── _parse_spec ──────────────────────────────────────────────────────

def test_parse_every_minutes():
    assert sp._parse_spec("every:30m") == ("every", {"seconds": 1800})


def test_parse_every_seconds_hours_days():
    assert sp._parse_spec("every:5s") == ("every", {"seconds": 5})
    assert sp._parse_spec("every:2h") == ("every", {"seconds": 7200})
    assert sp._parse_spec("every:1d") == ("every", {"seconds": 86400})


def test_parse_daily():
    assert sp._parse_spec("daily:09:00") == ("daily", {"hour": 9, "minute": 0})


def test_parse_daily_invalid_time_rejected():
    assert sp._parse_spec("daily:25:00") is None
    assert sp._parse_spec("daily:09:60") is None


def test_parse_weekly():
    assert sp._parse_spec("weekly:mon:09:00") == ("weekly", {"weekday": 0, "hour": 9, "minute": 0})
    assert sp._parse_spec("weekly:sun:23:59") == ("weekly", {"weekday": 6, "hour": 23, "minute": 59})


def test_parse_invalid_spec_returns_none():
    assert sp._parse_spec("whenever") is None
    assert sp._parse_spec("every:abc") is None
    assert sp._parse_spec("weekly:someday:09:00") is None


# ── _compute_next_run ────────────────────────────────────────────────

def test_next_run_every_adds_interval():
    now = datetime.datetime(2026, 1, 1, 12, 0, 0)
    result = sp._compute_next_run("every", {"seconds": 60}, now)
    assert result == datetime.datetime(2026, 1, 1, 12, 1, 0)


def test_next_run_daily_same_day_if_time_still_ahead():
    now = datetime.datetime(2026, 1, 1, 8, 0, 0)
    result = sp._compute_next_run("daily", {"hour": 9, "minute": 0}, now)
    assert result == datetime.datetime(2026, 1, 1, 9, 0, 0)


def test_next_run_daily_rolls_to_tomorrow_if_time_passed():
    now = datetime.datetime(2026, 1, 1, 10, 0, 0)
    result = sp._compute_next_run("daily", {"hour": 9, "minute": 0}, now)
    assert result == datetime.datetime(2026, 1, 2, 9, 0, 0)


def test_next_run_weekly_finds_upcoming_weekday():
    # 2026-01-01 is a Thursday (weekday=3)
    now = datetime.datetime(2026, 1, 1, 8, 0, 0)
    result = sp._compute_next_run("weekly", {"weekday": 0, "hour": 9, "minute": 0}, now)  # next Monday
    assert result.weekday() == 0
    assert result > now
    assert (result - now).days <= 7


def test_next_run_weekly_rolls_to_next_week_if_same_day_passed():
    now = datetime.datetime(2026, 1, 1, 10, 0, 0)  # Thursday, 10:00
    result = sp._compute_next_run("weekly", {"weekday": 3, "hour": 9, "minute": 0}, now)  # same weekday, earlier time
    assert result == datetime.datetime(2026, 1, 8, 9, 0, 0)


# ── schedule add ─────────────────────────────────────────────────────

def test_add_valid_job(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule add daily:09:00 echo hi", ["add", "daily:09:00", "echo", "hi"], engine=bare_engine))
    assert "✅" in result
    assert "#1" in result
    data = sp._load()
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["command"] == "echo hi"
    assert data["jobs"][0]["spec"] == "daily:09:00"
    assert data["jobs"][0]["enabled"] is True


def test_add_invalid_spec_rejected(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule add whenever echo hi", ["add", "whenever", "echo", "hi"], engine=bare_engine))
    assert result.startswith("❌")
    assert sp._load()["jobs"] == []


def test_add_missing_command_shows_usage(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule add daily:09:00", ["add", "daily:09:00"], engine=bare_engine))
    assert result.startswith("usage")


def test_add_unknown_command_warns_but_still_saves(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx(
        "schedule add every:1h totally_unknown_cmd", ["add", "every:1h", "totally_unknown_cmd"], engine=bare_engine,
    ))
    assert "✅" in result
    assert "تحذير" in result
    assert len(sp._load()["jobs"]) == 1


def test_add_increments_ids(make_ctx, bare_engine):
    sp._cmd_schedule(make_ctx("schedule add every:1h echo a", ["add", "every:1h", "echo", "a"], engine=bare_engine))
    result = sp._cmd_schedule(make_ctx("schedule add every:1h echo b", ["add", "every:1h", "echo", "b"], engine=bare_engine))
    assert "#2" in result


# ── schedule list ────────────────────────────────────────────────────

def test_list_empty(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule list", ["list"], engine=bare_engine))
    assert "مفيش" in result


def test_list_shows_added_jobs(make_ctx, bare_engine):
    sp._cmd_schedule(make_ctx("schedule add daily:09:00 echo hi", ["add", "daily:09:00", "echo", "hi"], engine=bare_engine))
    result = sp._cmd_schedule(make_ctx("schedule list", ["list"], engine=bare_engine))
    assert "#1" in result
    assert "echo hi" in result
    assert "daily:09:00" in result


# ── schedule remove ──────────────────────────────────────────────────

def test_remove_existing_job(make_ctx, bare_engine):
    sp._cmd_schedule(make_ctx("schedule add every:1h echo hi", ["add", "every:1h", "echo", "hi"], engine=bare_engine))
    result = sp._cmd_schedule(make_ctx("schedule remove 1", ["remove", "1"], engine=bare_engine))
    assert "🗑" in result
    assert sp._load()["jobs"] == []


def test_remove_unknown_job(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule remove 99", ["remove", "99"], engine=bare_engine))
    assert result.startswith("❌")


def test_remove_no_id_shows_usage(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule remove", ["remove"], engine=bare_engine))
    assert result.startswith("usage")


# ── schedule pause / resume ──────────────────────────────────────────

def test_pause_and_resume_job(make_ctx, bare_engine):
    sp._cmd_schedule(make_ctx("schedule add every:1h echo hi", ["add", "every:1h", "echo", "hi"], engine=bare_engine))
    result = sp._cmd_schedule(make_ctx("schedule pause 1", ["pause", "1"], engine=bare_engine))
    assert "اتوقف" in result
    assert sp._load()["jobs"][0]["enabled"] is False

    result = sp._cmd_schedule(make_ctx("schedule resume 1", ["resume", "1"], engine=bare_engine))
    assert "اتشغّل" in result
    assert sp._load()["jobs"][0]["enabled"] is True


def test_pause_unknown_job(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule pause 99", ["pause", "99"], engine=bare_engine))
    assert result.startswith("❌")


# ── schedule run_now ─────────────────────────────────────────────────

def test_run_now_submits_to_queue(make_ctx, bare_engine):
    sp._cmd_schedule(make_ctx("schedule add daily:09:00 echo hi", ["add", "daily:09:00", "echo", "hi"], engine=bare_engine))
    result = sp._cmd_schedule(make_ctx("schedule run_now 1", ["run_now", "1"], engine=bare_engine))
    assert "▶️" in result
    text, _fn = bare_engine._queue.get_nowait()
    assert text == "echo hi"
    assert _fn is None


def test_run_now_unknown_job(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule run_now 99", ["run_now", "99"], engine=bare_engine))
    assert result.startswith("❌")


# ── unknown subcommand / no args ────────────────────────────────────

def test_no_args_shows_usage(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule", [], engine=bare_engine))
    assert result.startswith("usage")


def test_unknown_subcommand_shows_usage(make_ctx, bare_engine):
    result = sp._cmd_schedule(make_ctx("schedule frobnicate", ["frobnicate"], engine=bare_engine))
    assert result.startswith("usage")


# ── _tick ────────────────────────────────────────────────────────────

def test_tick_submits_due_job_and_reschedules(bare_engine):
    now = datetime.datetime.now()
    past = now - datetime.timedelta(seconds=5)
    sp._save({
        "jobs": [{
            "id": 1, "spec": "every:60s", "command": "echo due",
            "enabled": True, "next_run": past.isoformat(timespec="seconds"),
            "last_run": None, "created": past.isoformat(timespec="seconds"),
        }],
        "next_id": 2,
    })
    sp._tick(bare_engine)
    text, _fn = bare_engine._queue.get_nowait()
    assert text == "echo due"

    data = sp._load()
    job = data["jobs"][0]
    assert job["last_run"] is not None
    new_next_run = datetime.datetime.fromisoformat(job["next_run"])
    assert new_next_run > now


def test_tick_skips_disabled_job(bare_engine):
    past = datetime.datetime.now() - datetime.timedelta(seconds=5)
    sp._save({
        "jobs": [{
            "id": 1, "spec": "every:60s", "command": "echo skip",
            "enabled": False, "next_run": past.isoformat(timespec="seconds"),
            "last_run": None, "created": past.isoformat(timespec="seconds"),
        }],
        "next_id": 2,
    })
    sp._tick(bare_engine)
    assert bare_engine._queue.empty()


def test_tick_skips_job_not_due_yet(bare_engine):
    future = datetime.datetime.now() + datetime.timedelta(hours=1)
    sp._save({
        "jobs": [{
            "id": 1, "spec": "every:60s", "command": "echo later",
            "enabled": True, "next_run": future.isoformat(timespec="seconds"),
            "last_run": None, "created": future.isoformat(timespec="seconds"),
        }],
        "next_id": 2,
    })
    sp._tick(bare_engine)
    assert bare_engine._queue.empty()


def test_tick_handles_corrupted_next_run_gracefully(bare_engine):
    sp._save({
        "jobs": [{
            "id": 1, "spec": "every:60s", "command": "echo bad",
            "enabled": True, "next_run": "not-a-real-date",
            "last_run": None, "created": "not-a-real-date",
        }],
        "next_id": 2,
    })
    sp._tick(bare_engine)  # لازم ما يعملش crash
    assert bare_engine._queue.empty()


# ── register / background thread lifecycle ──────────────────────────

def test_register_adds_command_and_starts_thread(bare_engine):
    sp.register(bare_engine)
    try:
        assert bare_engine.registry.get("schedule") is not None
        assert bare_engine._scheduler_thread.is_alive()
    finally:
        bare_engine._scheduler_stop.set()
        bare_engine._scheduler_thread.join(timeout=2)


def test_register_twice_does_not_spawn_second_thread(bare_engine):
    sp.register(bare_engine)
    first_thread = bare_engine._scheduler_thread
    try:
        sp.register(bare_engine)
        assert bare_engine._scheduler_thread is first_thread
    finally:
        bare_engine._scheduler_stop.set()
        bare_engine._scheduler_thread.join(timeout=2)
