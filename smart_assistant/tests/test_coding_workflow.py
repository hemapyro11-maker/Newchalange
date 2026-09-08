"""Regression tests for the audit findings and an end-to-end coding task."""
import json
import pathlib
import sqlite3
import sys
import threading
from types import SimpleNamespace

import pytest

import brain
import coding
import command_text
import core_engine
import hooks
import intents
import permissions
import sessions
import styles
import edit_plugin
import database_plugin
import plugin_forge_plugin


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, '_base_dir', lambda: tmp_path)
    monkeypatch.setattr(brain, '_HAS_KEYRING', False)
    monkeypatch.setattr(intents, '_cache_path', lambda: tmp_path / 'intents.json')
    monkeypatch.setattr(sessions, '_base_dir', lambda: tmp_path)
    monkeypatch.setattr(hooks, 'fire', lambda *a, **k: None)
    monkeypatch.setattr(styles, 'prompt_for', lambda: '')
    brain.reset_brain()


def model(monkeypatch, replies):
    responses = iter(replies)
    monkeypatch.setattr(brain.Brain, 'ready', lambda self: True)
    monkeypatch.setattr(brain.Brain, 'chat', lambda self, messages, **kw:
                        brain.BrainReply(text=next(responses), label='Test model'))


def test_windows_paths_and_quotes():
    assert command_text.split(r'run "C:\Program Files\Python\python.exe" C:\code\main.py') == [
        'run', r'C:\Program Files\Python\python.exe', r'C:\code\main.py']


def test_create_preserves_inline_quotes_and_multiline_indent(make_ctx, tmp_path):
    path = tmp_path / 'file with spaces.py'
    raw = f'create_file "{path}"\n    print("hello")\n'
    assert 'created' in edit_plugin._cmd_create_file(make_ctx(raw, []))
    assert path.read_text() == '    print("hello")\n'
    filename, body = command_text.file_request('create_file a.py print("hello")')
    assert (filename, body) == ('a.py', 'print("hello")')


def test_relative_edit_uses_project_and_backup(bare_engine, make_ctx):
    path = bare_engine.project_dir / 'my code.py'
    path.write_text('x = 1\n')
    raw = 'edit_file "my code.py"\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE'
    assert 'applied' in edit_plugin._cmd_edit_file(make_ctx(raw, []))
    assert path.read_text() == 'x = 2\n'
    assert path.with_suffix('.py.nezuko-bak').read_text() == 'x = 1\n'


def test_large_file_can_read_range(make_ctx, tmp_path):
    path = tmp_path / 'large.txt'
    path.write_text('line\n' * 100000)
    result = edit_plugin._cmd_read_file(make_ctx('read_file', [str(path), '90000', '90002']))
    assert '90000  line' in result and '90002  line' in result
    assert len(result) < 1000


@pytest.mark.parametrize('text', ['TOOL: run bad\nASK: Which project?', 'ASK: Which project?\nTOOL: run bad'])
def test_question_suppresses_tool_in_both_orders(text):
    _, tool, question = core_engine.AssistantEngine._split_directives(text)
    assert tool is None and question == 'Which project?'


def test_edit_body_ask_is_literal():
    _, tool, question = core_engine.AssistantEngine._split_directives(
        'TOOL: edit_file a.txt\n<<<<<<< SEARCH\nASK: literal\n=======\nyes\n>>>>>>> REPLACE')
    assert tool is not None and question is None


def test_background_cannot_confirm_or_overwrite(bare_engine):
    seen = []
    bare_engine.registry.register('danger', lambda ctx: seen.append(True))
    bare_engine._pending_intent = ('danger', [], 'request')
    bare_engine._in_hook = True
    bare_engine._dispatch('y')
    assert bare_engine._pending_intent == ('danger', [], 'request')
    assert not seen


def test_channels_do_not_share_approvals(bare_engine):
    seen = []
    bare_engine.registry.register('danger', lambda ctx: seen.append(True))
    bare_engine._pending_intent = ('danger', [], 'request')
    bare_engine._dispatch('y', source='telegram:1')
    assert not seen and bare_engine._pending_intent
    bare_engine._dispatch('y')
    assert seen


@pytest.mark.parametrize('name', ['run', 'schedule', 'allow', 'reload_plugins', 'test', 'env_install'])
def test_execution_wrappers_cannot_be_permanently_allowed(name):
    assert not permissions.allow(name)[0]


def test_new_session_clears_all_pending_work(bare_engine):
    bare_engine._pending_intent = ('run', ['bad'], 'task')
    bare_engine._pending_args = ('run', [], [], 'task')
    bare_engine._awaiting_answer = True
    bare_engine._chain_step = 3
    old = bare_engine.session_id
    bare_engine.new_session()
    assert bare_engine.session_id != old
    assert not bare_engine._pending_intent and not bare_engine._pending_args
    assert not bare_engine._awaiting_answer and bare_engine._chain_step is None


def test_old_model_reply_cannot_enter_new_session(bare_engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def chat(self, messages, **kw):
        entered.set()
        assert release.wait(5)
        return brain.BrainReply(text='TOOL: run unsafe', label='Fake')
    monkeypatch.setattr(brain.Brain, 'ready', lambda self: True)
    monkeypatch.setattr(brain.Brain, 'chat', chat)
    thread = threading.Thread(target=bare_engine._converse, args=('do work',))
    thread.start()
    assert entered.wait(5)
    bare_engine.new_session()
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert bare_engine.chat_history == [] and bare_engine._pending_intent is None


def test_queue_serializes_model_requests(bare_engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def chat(self, messages, **kw):
        calls.append(messages[-1]['content'])
        entered.set()
        assert release.wait(5)
        return brain.BrainReply(text='answer', label='Fake')
    monkeypatch.setattr(brain.Brain, 'ready', lambda self: True)
    monkeypatch.setattr(brain.Brain, 'chat', chat)
    bare_engine.start()
    try:
        bare_engine.submit('explain this unusual problem')
        assert entered.wait(5)
        bare_engine.submit('another unusual problem')
        assert len(calls) == 1
        release.set()
        bare_engine._queue.join()
        assert len(calls) == 2
    finally:
        release.set()
        bare_engine.stop()


def test_cache_keeps_arguments_but_requires_confirmation(bare_engine):
    phrase = 'perform the saved task'
    intents.remember(phrase, 'echo', ['a b', r'C:\code'])
    bare_engine._dispatch(phrase)
    assert bare_engine._pending_intent[:2] == ('echo', ['a b', r'C:\code'])


def test_legacy_cache_is_not_used(tmp_path):
    intents._cache_path().write_text(json.dumps({'some old phrase': 'run'}))
    assert intents.resolve('some old phrase', {'run'}) is None


def test_migration_rolls_back_ddl_and_data(make_ctx, tmp_path):
    db, folder = tmp_path / 'app.db', tmp_path / 'migrations'
    folder.mkdir()
    (folder / '001.sql').write_text('CREATE TABLE items(id); INSERT INTO items VALUES(1); invalid sql;')
    result = database_plugin._cmd_db_migrate(make_ctx('db_migrate', [str(db), str(folder)]))
    assert 'failed' in result
    with sqlite3.connect(db) as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='items'").fetchall()


def test_migration_cannot_commit_halfway(make_ctx, tmp_path):
    db, folder = tmp_path / 'app.db', tmp_path / 'migrations'
    folder.mkdir()
    (folder / '001.sql').write_text('CREATE TABLE items(id); COMMIT; invalid sql;')
    assert 'failed' in database_plugin._cmd_db_migrate(make_ctx('db_migrate', [str(db), str(folder)]))
    with sqlite3.connect(db) as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='items'").fetchall()


def test_validation_does_not_execute_candidate(tmp_path):
    marker = tmp_path / 'executed'
    candidate = tmp_path / 'candidate.py'
    candidate.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\ndef register(engine):\n    pass\n')
    ok, message = plugin_forge_plugin._validate_candidate(candidate)
    assert ok and 'NOT been executed' in message
    assert not marker.exists()


def test_context_budget_includes_oversized_system():
    messages = [{'role': 'system', 'content': 'S' * 50000}, {'role': 'user', 'content': 'U' * 40000}]
    fitted = brain._fit_to_context(messages, 1000)
    assert sum(brain.estimate_tokens(m['content']) for m in fitted) <= 750
    assert len(messages[0]['content']) == 50000
    assert fitted[-1]['role'] == 'user'


def test_inflight_call_reserves_quota(monkeypatch):
    b = brain.Brain()
    provider = next(iter(brain.PROVIDERS.values()))
    cfg = {'limits': {provider.name: {'rpm': 1, 'rpd': 1}}}
    assert b._available(provider, cfg, 100)
    b._inflight[provider.name] = 1
    assert not b._available(provider, cfg, 100)
    b._note_failure(provider.name, 100, rate_limited=False)
    assert b._inflight[provider.name] == 0


def test_reload_removes_deleted_commands(tmp_path):
    folder = tmp_path / 'plugins'
    folder.mkdir()
    file = folder / 'demo.py'
    file.write_text("def register(engine):\n    engine.registry.register('old_command', lambda ctx: 'ok')\n")
    engine = core_engine.AssistantEngine(plugins_dirs=[folder])
    assert engine.registry.get('old_command')
    file.unlink()
    engine.load_plugins()
    assert engine.registry.get('old_command') is None
    assert engine.registry.get('project')


def test_direct_command_is_saved(bare_engine):
    bare_engine._dispatch('echo hello')
    assert sessions.load(bare_engine.session_id)[-1]['content'] == 'hello'


def test_search_and_listing_skip_private_files(bare_engine, make_ctx):
    root = bare_engine.project_dir
    (root / 'app.py').write_text('needle = 1\n')
    (root / '.env').write_text('needle=secret')
    (root / 'node_modules').mkdir()
    (root / 'node_modules/noisy.py').write_text('needle')
    result = coding.search(make_ctx('search', ['needle']))
    assert 'app.py:1:' in result and 'secret' not in result and 'noisy' not in result


def test_coding_task_reads_edits_runs_real_tests(bare_engine, monkeypatch):
    root = bare_engine.project_dir
    (root / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
    (root / 'test_calc.py').write_text('import unittest\nfrom calc import add\nclass TestAdd(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n')
    edit_plugin.register(bare_engine)
    before = coding._run(bare_engine, [sys.executable, '-m', 'unittest', '-q'])
    assert 'exit code 1' in before and 'FAILED' in before
    replies = [
        'TOOL: read_file calc.py',
        'TOOL: edit_file calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE',
        f'TOOL: test "{sys.executable}" -m unittest -q',
        'The addition bug is fixed and the test passed.',
    ]
    model(monkeypatch, replies)
    bare_engine._converse('Fix the addition bug and verify it.')
    assert (root / 'calc.py').read_text().endswith('return a - b\n')
    for name in ['read_file', 'edit_file', 'test']:
        assert bare_engine._pending_intent[0] == name
        bare_engine._dispatch('y')
    assert (root / 'calc.py').read_text().endswith('return a + b\n')
    logs = '\n'.join(message for _, message in bare_engine.log_history)
    assert 'exit code 0' in logs and 'Ran 1 test' in logs
    assert bare_engine._pending_intent is None


def test_plan_mode_blocks_writes_even_if_previously_allowed(bare_engine, monkeypatch):
    model(monkeypatch, ['TOOL: create_file bad.py\nunsafe'])
    bare_engine.coding_mode = 'plan'
    bare_engine._converse('write a file')
    assert bare_engine._pending_intent is None
    bare_engine._dispatch('run something')
    assert 'Plan mode blocked run' in bare_engine.log_history[-1][1]


def test_agent_proposals_use_confirmation_and_runtime_scope(bare_engine, monkeypatch):
    import agents
    monkeypatch.setattr(agents, 'get', lambda name: {'instructions': 'Inspect only', 'tools': ['echo']})
    model(monkeypatch, ['TOOL: run unsafe', 'TOOL: echo done', 'Finished'])
    bare_engine.begin_agent('reviewer', 'inspect')
    assert bare_engine._pending_intent is None
    assert 'outside its allowed scope' in bare_engine.log_history[-1][1]
    bare_engine.begin_agent('reviewer', 'inspect')
    assert bare_engine._pending_intent[0] == 'echo'
    bare_engine._dispatch('y')
    assert bare_engine._pending_intent is None


def test_local_voice_never_calls_cloud(tmp_path, monkeypatch):
    import voice_plugin
    brain.save_config({'local_only': True})
    called = []
    monkeypatch.setattr(voice_plugin, '_synthesize_edge', lambda *args: called.append('cloud') or True)
    monkeypatch.setattr(voice_plugin, '_synthesize_sherpa', lambda *args: called.append('local') or True)
    assert voice_plugin._synthesize_with_fallback('hello', tmp_path)
    assert called == ['local']


def test_frozen_install_does_not_launch_app_as_python(make_ctx, monkeypatch):
    import environment_plugin
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert 'external Python' in environment_plugin._cmd_env_install(make_ctx('env_install', ['pytest', '--yes']))


def test_frozen_update_uses_plugins_directory(monkeypatch, tmp_path):
    import self_update_plugin
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'Nezuko.exe'))
    assert self_update_plugin._local_plugins_dir() == tmp_path / 'plugins'


def test_session_restores_project(bare_engine, tmp_path):
    project = tmp_path / 'saved project'
    project.mkdir()
    messages = [{'role': 'user', 'content': 'hello'}]
    sessions.save('saved', messages, project=str(project))
    bare_engine.new_session('saved', sessions.load('saved'))
    assert bare_engine.project_dir == project.resolve()


@pytest.mark.parametrize('data', [[], {'messages': [1]}, {'messages': 'bad'}])
def test_invalid_session_cannot_crash_load(tmp_path, data):
    sessions._path('broken').write_text(json.dumps(data))
    assert sessions.load('broken') is None


@pytest.mark.parametrize('payload', [{'error': {'code': 'ENOLOCK'}}, {}, []])
def test_failed_npm_audit_never_reports_clean(tmp_path, monkeypatch, payload):
    import security_scan_plugin
    monkeypatch.setattr(security_scan_plugin.shutil, 'which', lambda name: 'npm')
    monkeypatch.setattr(security_scan_plugin.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(stdout=json.dumps(payload), returncode=1))
    result = security_scan_plugin._run_npm_audit(tmp_path)
    assert '✅' not in result
    assert 'no verdict' in result or 'no vulnerability verdict' in result
