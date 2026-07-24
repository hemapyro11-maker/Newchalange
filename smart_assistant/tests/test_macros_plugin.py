import macros_plugin as mp


def test_macro_loads_and_expands_args(bare_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "_commands_dir", lambda: tmp_path)
    (tmp_path / "greet.txt").write_text("echo hi {args}\n", encoding="utf-8")
    mp.load_macros(bare_engine)
    cmd = bare_engine.registry.get("greet")
    assert cmd is not None

    from core_engine import CommandContext
    submitted = []
    bare_engine.submit = lambda text: submitted.append(text)
    result = cmd.handler(CommandContext(raw="greet Ahmed", args=["Ahmed"], engine=bare_engine))
    assert "echo hi Ahmed" in result
    assert submitted == ["echo hi Ahmed"]


def test_macro_colliding_with_builtin_is_skipped(bare_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "_commands_dir", lambda: tmp_path)
    (tmp_path / "help.txt").write_text("echo not the real help\n", encoding="utf-8")
    warnings = []
    bare_engine._log = lambda msg, level="info": warnings.append((level, msg))
    mp.load_macros(bare_engine)
    # builtin help must remain untouched
    assert bare_engine.registry.get("help").description == "عرض كل الأوامر المتاحة"
    assert any("يصطدم" in msg for _, msg in warnings)


def test_self_referential_macro_is_skipped(bare_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "_commands_dir", lambda: tmp_path)
    (tmp_path / "loop.txt").write_text("echo before\nloop\necho after\n", encoding="utf-8")
    warnings = []
    bare_engine._log = lambda msg, level="info": warnings.append((level, msg))
    mp.load_macros(bare_engine)
    assert bare_engine.registry.get("loop") is None
    assert any("نفسه" in msg for _, msg in warnings)


def test_reload_picks_up_new_macro(bare_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "_commands_dir", lambda: tmp_path)
    mp.load_macros(bare_engine)
    assert bare_engine.registry.get("brandnew") is None
    (tmp_path / "brandnew.txt").write_text("echo new\n", encoding="utf-8")
    mp.load_macros(bare_engine)
    assert bare_engine.registry.get("brandnew") is not None


def test_macros_command_lists_available(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "_commands_dir", lambda: tmp_path)
    (tmp_path / "one.txt").write_text("echo 1\n", encoding="utf-8")
    result = mp._cmd_macros(make_ctx("macros", []))
    assert "one" in result


def test_macros_command_empty(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "_commands_dir", lambda: tmp_path)
    result = mp._cmd_macros(make_ctx("macros", []))
    assert "مفيش" in result
