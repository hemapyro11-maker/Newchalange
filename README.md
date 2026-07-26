# Y99 Filter Bot

بوت بواجهة رسومية (customtkinter) بيشغّل متصفح (Playwright/Chromium) على `y99.in`،
يبعت رسالة ثابتة، وبناءً على الرد (`F`/`M`) يقرر يفضل في الشات أو يتخطاه.

## إزاي بيقرا الرد

`classify()` في `bot_core.py` بتشوف الرد وترجّع واحد من تلاتة:

| الرد | النتيجة |
|------|---------|
| `f` · `18f` · `f 18` · `female` · `girl` · `بنت` | **stay** — يفضل في الشات وينبّهك |
| `m` · `22m` · `male` · `boy` · `ولد` | **skip** — يتخطى |
| `fine` · `maybe` · `hello` · `hey man` | **unknown** — يكمل استنى |
| `m or f?` · `f or m` · `r u f?` | **unknown** — سؤال/غامض، يكمل استنى |

حالتين مهمين بالتحديد:

- **أي سطر بينتهي بعلامة استفهام مش تعريف بالجنس** — لو الطرف التاني سأل
  `m or f?` ده سؤال منه، فالبوت يكمل استنى الرد الحقيقي بدل ما يتخطى بنت بالغلط.
- **لو السطر فيه الجنسين مع بعض** (`m f`) فهو غامض، برضه بيكمل استنى.

الكلمات اللي بتستخدم كنداء (`man` · `bro` · `dude` · `guys`) **مش** محسوبة
كتعريف بالجنس، عشان `hey man` ما يتخطاش بنت.

## التشغيل

```bash
pip install -r requirements.txt
python -m playwright install chromium
python main_gui.py
```

## الاختبارات

منطق التصنيف متغطّى باختبارات بتشتغل من غير متصفح ولا `playwright`:

```bash
python -m unittest discover -s tests -v
```

## بناء EXE (ويندوز)

```bat
build_exe.bat
```

الملف الناتج هيكون في مجلد `dist/Y99FilterBot.exe`.

## الملفات

- `main_gui.py` — واجهة المستخدم (customtkinter).
- `bot_core.py` — منطق البوت (Playwright) بدون أي اعتماد على الواجهة.
- `tests/test_classify.py` — اختبارات `classify()` و `is_noise()`.
- `requirements.txt` — المتطلبات.
- `build_exe.bat` — سكربت بناء ملف تنفيذي واحد باستخدام PyInstaller.
