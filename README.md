# Y99 Filter Bot

بوت بواجهة رسومية (customtkinter) بيشغّل متصفح (Playwright/Chromium) على `y99.in`،
يبعت رسالة ثابتة، وبناءً على أول حرف في الرد (`F`/`M`) يقرر يفضل في الشات أو يتخطاه.

## التشغيل

```bash
pip install -r requirements.txt
python -m playwright install chromium
python main_gui.py
```

## بناء EXE (ويندوز)

```bat
build_exe.bat
```

الملف الناتج هيكون في مجلد `dist/Y99FilterBot.exe`.

## الملفات

- `main_gui.py` — واجهة المستخدم (customtkinter).
- `bot_core.py` — منطق البوت (Playwright) بدون أي اعتماد على الواجهة.
- `requirements.txt` — المتطلبات.
- `build_exe.bat` — سكربت بناء ملف تنفيذي واحد باستخدام PyInstaller.
