# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('core_engine.py', '.'), ('coding.py', '.'), ('command_text.py', '.'), ('media_runtime.py', '.'), ('i18n.py', '.'), ('brain.py', '.'), ('intents.py', '.'), ('theme.py', '.'), ('sessions.py', '.'), ('permissions.py', '.'), ('hooks.py', '.'), ('agents.py', '.'), ('styles.py', '.'), ('benchmark.py', '.'), ('natural_voice_runtime.py', '.'), ('natural_voice_worker.py', '.'), ('voicetut_runtime.py', '.'), ('voicetut_voice_worker.py', '.'), ('english_voice_runtime.py', '.'), ('english_voice_worker.py', '.'), ('youtube_public.py', '.'), ('version.py', '.'), ('version.json', '.'), ('connectors.example.json', '.'), ('plugins', 'plugins'),
         (r'C:\Users\Hemap\Documents\Codex\2026-09-07\new-chat\work\dev-tcl\tcl8.6', 'tcl/tcl8.6'),
         (r'C:\Users\Hemap\Documents\Codex\2026-09-07\new-chat\work\dev-tcl\tk8.6', 'tcl/tk8.6'),
         (r'C:\Users\Hemap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\tkinter', 'tkinter')]
binaries = [
    (r'C:\Users\Hemap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\DLLs\_tkinter.pyd', '.'),
    (r'C:\Users\Hemap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\DLLs\tcl86t.dll', '.'),
    (r'C:\Users\Hemap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\DLLs\tk86t.dll', '.'),
]
hiddenimports = ['jarvis_hud', 'desktop_gui', 'PySide6.QtWidgets', 'customtkinter', 'arabic_reshaper', 'bidi.algorithm', 'core_engine', 'coding', 'command_text', 'media_runtime', 'i18n', 'version', 'brain', 'intents', 'theme', 'sessions', 'permissions', 'hooks', 'agents', 'styles', 'benchmark', 'natural_voice_runtime', 'voicetut_runtime', 'english_voice_runtime', 'pywintypes', 'pythoncom', 'win32api']
tmp_ret = collect_all('CTkToolTip')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mcp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('capstone')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yara')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('imageio_ffmpeg')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('matplotlib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('edge_tts')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sherpa_onnx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('piper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openwakeword')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += [('assets', 'assets')]
hiddenimports += ['wake_word']
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('vosk')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('scenedetect')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('telegram')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('discord')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('keyring')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['qt_runtime_hook.py', r'C:\Users\Hemap\Documents\Codex\2026-09-07\new-chat\work\tcl_runtime_hook.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt uses Windows' own unversioned ICU API. Poppler's ICU DLL with this
# basename has version-suffixed exports and must not shadow the system DLL.
a.binaries = [entry for entry in a.binaries if entry[0].lower() != 'icuuc.dll']
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Jarvis',
    icon='assets/jarvis.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
