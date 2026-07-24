import plugin_forge_plugin as pf
from core_engine import CommandContext


def test_validate_candidate_accepts_good_plugin(tmp_path):
    code = (
        "def _h(ctx):\n    return 'ok'\n\n"
        "def register(engine):\n    engine.registry.register('x', _h, 'd')\n"
    )
    p = tmp_path / "c.py"
    p.write_text(code, encoding="utf-8")
    ok, msg = pf._validate_candidate(p)
    assert ok
    assert "x" in msg


def test_validate_candidate_rejects_syntax_error(tmp_path):
    p = tmp_path / "c.py"
    p.write_text("def register(engine)\n    pass\n", encoding="utf-8")
    ok, msg = pf._validate_candidate(p)
    assert not ok


def test_validate_candidate_rejects_missing_register(tmp_path):
    p = tmp_path / "c.py"
    p.write_text("def foo():\n    pass\n", encoding="utf-8")
    ok, msg = pf._validate_candidate(p)
    assert not ok
    assert "register" in msg


def test_validate_candidate_rejects_zero_commands(tmp_path):
    p = tmp_path / "c.py"
    p.write_text("def register(engine):\n    pass\n", encoding="utf-8")
    ok, msg = pf._validate_candidate(p)
    assert not ok
    assert "zero commands" in msg


def test_validate_candidate_catches_infinite_loop(tmp_path):
    p = tmp_path / "c.py"
    p.write_text("def register(engine):\n    while True:\n        pass\n", encoding="utf-8")
    ok, msg = pf._validate_candidate(p)
    assert not ok
    assert "TIMEOUT" in msg


def test_validate_candidate_catches_runtime_error(tmp_path):
    p = tmp_path / "c.py"
    p.write_text("def register(engine):\n    1 / 0\n", encoding="utf-8")
    ok, msg = pf._validate_candidate(p)
    assert not ok


def test_generate_with_retries_self_corrects(monkeypatch, tmp_path, bare_engine):
    monkeypatch.setattr(pf, "_pending_dir", lambda: tmp_path)
    calls = {"n": 0}

    def fake_ask(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "def register(engine)\n    pass"  # syntax error
        if calls["n"] == 2:
            return "def register(engine):\n    pass"  # zero commands
        return (
            "def _h(ctx):\n    return 'pong'\n\n"
            "def register(engine):\n    engine.registry.register('ping', _h, 'd')\n"
        )

    ok, code, msg, attempts = pf._generate_with_retries(bare_engine, "prompt", "test", ask=fake_ask)
    assert ok
    assert attempts == 3
    assert "ping" in code


def test_generate_with_retries_gives_up_after_max_attempts(monkeypatch, tmp_path, bare_engine):
    monkeypatch.setattr(pf, "_pending_dir", lambda: tmp_path)

    def always_broken(prompt):
        return "this is not valid python (((("

    ok, code, msg, attempts = pf._generate_with_retries(bare_engine, "prompt", "test", ask=always_broken)
    assert not ok
    assert attempts == pf.MAX_ATTEMPTS


def test_generate_with_retries_handles_ollama_unreachable(monkeypatch, tmp_path, bare_engine):
    monkeypatch.setattr(pf, "_pending_dir", lambda: tmp_path)

    def raises_connection_error(prompt):
        raise ConnectionError("refused")

    ok, code, msg, attempts = pf._generate_with_retries(bare_engine, "prompt", "test", ask=raises_connection_error)
    assert not ok
    assert not code
    assert "Ollama" in msg


def _fake_generator(prompt):
    return (
        "def _h(ctx):\n    return 'pong'\n\n"
        "def register(engine):\n    engine.registry.register('ping', _h, 'd')\n"
    )


def test_full_lifecycle_generate_review_approve(monkeypatch, tmp_path, bare_engine):
    pending = tmp_path / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "_pending_dir", lambda: pending)
    live_dir = tmp_path / "live"
    bare_engine.plugins_dirs = [live_dir]

    ok, code, msg, attempts = pf._generate_with_retries(bare_engine, "prompt", "weatherbot", ask=_fake_generator)
    pf._save_candidate("weatherbot", code, "desc", ok, attempts, msg)

    listing = pf._cmd_list_pending(CommandContext(raw="list_pending", args=[], engine=bare_engine))
    assert "weatherbot" in listing

    review = pf._cmd_review_pending(CommandContext(raw="review_pending weatherbot", args=["weatherbot"], engine=bare_engine))
    assert "ping" in review

    approve = pf._cmd_approve_plugin(CommandContext(raw="approve_plugin weatherbot", args=["weatherbot"], engine=bare_engine))
    assert approve.startswith("✅")
    assert (live_dir / "weatherbot.py").is_file()
    assert bare_engine.registry.get("ping") is not None

    result = bare_engine.registry.get("ping").handler(CommandContext(raw="ping", args=[], engine=bare_engine))
    assert result == "pong"


def test_reject_plugin_removes_candidate(monkeypatch, tmp_path, bare_engine):
    pending = tmp_path / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "_pending_dir", lambda: pending)
    ok, code, msg, attempts = pf._generate_with_retries(bare_engine, "prompt", "x", ask=_fake_generator)
    pf._save_candidate("x", code, "d", ok, attempts, msg)

    result = pf._cmd_reject_plugin(CommandContext(raw="reject_plugin x", args=["x"], engine=bare_engine))
    assert "اتشالت" in result
    assert not (pending / "x.py").exists()


def test_path_traversal_name_rejected_everywhere(bare_engine):
    for cmd, args in [
        ("create_plugin", ["../../evil", "desc"]),
        ("fix_plugin", ["../../evil"]),
        ("review_pending", ["../../evil"]),
        ("approve_plugin", ["../../evil"]),
        ("reject_plugin", ["../../evil"]),
    ]:
        handler = {
            "create_plugin": pf._cmd_create_plugin,
            "fix_plugin": pf._cmd_fix_plugin,
            "review_pending": pf._cmd_review_pending,
            "approve_plugin": pf._cmd_approve_plugin,
            "reject_plugin": pf._cmd_reject_plugin,
        }[cmd]
        result = handler(CommandContext(raw=f"{cmd} {' '.join(args)}", args=args, engine=bare_engine))
        assert result.startswith("❌"), f"{cmd} did not reject path traversal"
