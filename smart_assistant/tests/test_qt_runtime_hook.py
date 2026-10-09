"""Reproduce the onefile DLL collision in an isolated Windows process."""
import os
import pathlib
import subprocess
import sys
import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows ICU loader regression")
def test_qt_starts_with_foreign_icu_on_the_dll_search_path():
    pytest.importorskip("PySide6")
    system = pathlib.Path(os.environ["SystemRoot"]) / "System32"
    candidates = [pathlib.Path(folder) for folder in os.environ.get("PATH", "").split(os.pathsep)
                  if folder and "poppler" in folder.lower() and (pathlib.Path(folder)/"icuuc.dll").is_file()]
    if not candidates:
        pytest.skip("no conflicting PDF ICU runtime installed")
    hook = pathlib.Path(__file__).resolve().parents[1] / "qt_runtime_hook.py"
    code = (
        "import ctypes,runpy,sys; "
        "ctypes.windll.kernel32.SetDllDirectoryW(sys.argv[1]); "
        "runpy.run_path(sys.argv[2]); "
        "from PySide6.QtCore import qVersion; print(qVersion())"
    )
    result = subprocess.run([sys.executable, "-c", code, str(candidates[0]), str(hook)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("6.")
