"""Use Windows' ICU API for Qt, not a same-name Poppler ICU DLL.

PyInstaller can collect Poppler's version-suffixed ICU from PATH. Qt on Windows
expects the operating system's unversioned API; loading that DLL first prevents
the unrelated PDF runtime from shadowing it in onefile builds.
"""
import ctypes
import os
import pathlib

if os.name == "nt":
    system_icu = pathlib.Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "icuuc.dll"
    if system_icu.is_file():
        _windows_icu = ctypes.WinDLL(str(system_icu), winmode=0x1000)
