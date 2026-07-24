import json

import todo_plugin as tp


def test_add_and_list(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "_todo_path", lambda: tmp_path / "todo.json")
    result = tp._cmd_todo(make_ctx("todo add buy milk", ["add", "buy", "milk"]))
    assert "اتضافت" in result
    result = tp._cmd_todo(make_ctx("todo list", ["list"]))
    assert "buy milk" in result
    assert "#1" in result


def test_add_without_text_shows_usage(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "_todo_path", lambda: tmp_path / "todo.json")
    result = tp._cmd_todo(make_ctx("todo add", ["add"]))
    assert "usage" in result


def test_done_marks_task(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "_todo_path", lambda: tmp_path / "todo.json")
    tp._cmd_todo(make_ctx("todo add task", ["add", "task"]))
    result = tp._cmd_todo(make_ctx("todo done 1", ["done", "1"]))
    assert "خلصت" in result
    result = tp._cmd_todo(make_ctx("todo list", ["list"]))
    assert "✅" in result


def test_done_unknown_id(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "_todo_path", lambda: tmp_path / "todo.json")
    result = tp._cmd_todo(make_ctx("todo done 99", ["done", "99"]))
    assert result.startswith("❌")


def test_clear(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "_todo_path", lambda: tmp_path / "todo.json")
    tp._cmd_todo(make_ctx("todo add x", ["add", "x"]))
    tp._cmd_todo(make_ctx("todo clear", ["clear"]))
    result = tp._cmd_todo(make_ctx("todo list", ["list"]))
    assert "فاضية" in result


def test_corrupted_file_not_a_list_self_heals(make_ctx, tmp_path, monkeypatch):
    path = tmp_path / "todo.json"
    path.write_text(json.dumps({"not": "a list"}))
    monkeypatch.setattr(tp, "_todo_path", lambda: path)
    result = tp._cmd_todo(make_ctx("todo list", ["list"]))
    assert "فاضية" in result
    result = tp._cmd_todo(make_ctx("todo add y", ["add", "y"]))
    assert "اتضافت مهمة #1" in result


def test_malformed_items_are_skipped_not_crashed(make_ctx, tmp_path, monkeypatch):
    path = tmp_path / "todo.json"
    path.write_text(json.dumps([{"no_id_here": True}, {"id": 3, "text": "ok", "done": False}]))
    monkeypatch.setattr(tp, "_todo_path", lambda: path)
    result = tp._cmd_todo(make_ctx("todo list", ["list"]))
    assert "#3" in result
    assert "ok" in result


def test_invalid_json_self_heals(make_ctx, tmp_path, monkeypatch):
    path = tmp_path / "todo.json"
    path.write_text("{not valid json!!")
    monkeypatch.setattr(tp, "_todo_path", lambda: path)
    result = tp._cmd_todo(make_ctx("todo list", ["list"]))
    assert "فاضية" in result
