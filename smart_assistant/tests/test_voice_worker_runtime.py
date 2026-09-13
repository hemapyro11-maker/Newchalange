import os
from pathlib import Path
import sys
import textwrap

from voice_worker_runtime import PersistentVoiceWorker, hidden_process_kwargs


def test_persistent_worker_processes_more_than_one_job(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text(textwrap.dedent("""
        import argparse, json, os, pathlib, time
        parser = argparse.ArgumentParser()
        parser.add_argument('--serve')
        args = parser.parse_args()
        queue = pathlib.Path(args.serve)
        while True:
            jobs = list(queue.glob('*.job.json'))
            if not jobs:
                time.sleep(.01); continue
            path = jobs[0]
            token = path.name.split('.')[0]
            result = queue / f'{token}.result.json'
            result.write_text(json.dumps({'ok': True, 'detail': 'ok'}))
            path.unlink(missing_ok=True)
    """), encoding="utf-8")
    worker = PersistentVoiceWorker(Path(sys.executable), script, dict(os.environ))
    try:
        assert worker.submit({"text": "one"}, 5) == (True, "ok")
        assert worker.submit({"text": "two"}, 5) == (True, "ok")
        assert worker.alive
    finally:
        worker.close()
    assert not worker.alive


def test_hidden_process_configuration_is_available():
    kwargs = hidden_process_kwargs()
    assert "creationflags" in kwargs
    if os.name == "nt":
        assert "startupinfo" in kwargs
