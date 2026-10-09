"""Hidden persistent subprocess support for heavyweight speech models."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid


def hidden_process_kwargs() -> dict:
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startup
    return kwargs


class PersistentVoiceWorker:
    """A single hidden Python process that keeps a speech model in memory."""

    def __init__(self, runtime: Path, script: Path, env: dict[str, str]):
        self.queue = Path(tempfile.mkdtemp(prefix="nezuko_voice_worker_"))
        self._lock = threading.Lock()
        self.process = subprocess.Popen(
            [str(runtime), str(script), "--serve", str(self.queue)],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, **hidden_process_kwargs(),
        )
        atexit.register(self.close)

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def submit(self, job: dict, timeout: int) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=max(0, timeout)):
            return False, "voice worker is still preparing; try again shortly"
        try:
            if not self.alive:
                return False, "persistent voice worker stopped"
            token = uuid.uuid4().hex
            job_path = self.queue / f"{token}.job.json"
            result_path = self.queue / f"{token}.result.json"
            temporary = self.queue / f"{token}.tmp"
            temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, job_path)
            while time.monotonic() < deadline:
                if result_path.is_file():
                    try:
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        # The producer may still be flushing the file. Do not
                        # remove a partial result or crash the conversation.
                        time.sleep(0.03)
                        continue
                    try:
                        result_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return bool(result.get("ok")), str(result.get("detail", "worker failed"))
                if not self.alive:
                    return False, "persistent voice worker stopped"
                time.sleep(0.03)
            try:
                job_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False, "voice generation timed out"
        finally:
            self._lock.release()

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        queue = getattr(self, "queue", None)
        if queue is not None:
            shutil.rmtree(queue, ignore_errors=True)
