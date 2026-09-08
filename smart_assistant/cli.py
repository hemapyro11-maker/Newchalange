"""Nezuko terminal client: python cli.py --project /path/to/repo."""
from __future__ import annotations

import argparse
import pathlib
import sys
import threading

from core_engine import AssistantEngine
import sessions


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nezuko coding assistant")
    parser.add_argument("--project", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--prompt", help="Run one request; proposed commands still require interactive approval")
    parser.add_argument("--coding-only", action="store_true", help="Load only file editing tools and built-in coding commands")
    args = parser.parse_args(argv)
    if not args.project.is_dir():
        parser.error("project must be an existing directory")
    output_lock = threading.Lock()
    def log(message, level="info"):
        with output_lock:
            print(message, flush=True)
    engine = AssistantEngine(on_log=log, plugins_dirs=[] if args.coding_only else None)
    if args.coding_only:
        from plugins.edit_plugin import register
        register(engine)
    engine.project_dir = args.project.resolve()
    engine.start()
    print(f"Nezuko · {engine.project_dir}\n/help · /cancel · /new · /exit\nFor multiline edits use /paste and finish with /end.")
    try:
        if args.prompt:
            engine.submit(args.prompt)
        while True:
            try:
                line = input("nezuko> ")
            except EOFError:
                # Drain submitted work before exiting when reading piped input.
                engine._queue.join()
                break
            except KeyboardInterrupt:
                engine.cancel()
                print("\nPending work cancelled; running commands may still finish.")
                continue
            if line.strip() == "/exit":
                break
            if line.strip() == "/new":
                engine.new_session()
                continue
            if line.startswith("/resume "):
                session_id = line.split(maxsplit=1)[1].strip()
                messages = sessions.load(session_id)
                if messages is None:
                    print("Session not found or invalid.")
                else:
                    engine.new_session(session_id, messages)
                    print(f"Resumed {session_id} · {engine.project_dir}")
                continue
            if line.strip() in {"/plan", "/code"}:
                line = "mode plan" if line.strip() == "/plan" else "mode ask"
            if line.strip() == "/paste":
                lines = []
                while (line := input("... ")) != "/end":
                    lines.append(line)
                line = "\n".join(lines)
            engine.submit("help" if line.strip() == "/help" else line)
    finally:
        engine.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
