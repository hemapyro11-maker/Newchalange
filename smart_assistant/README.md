# Smart Assistant

وحدة مستقلة بالكامل (منفصلة عن Y99 Filter Bot): مساعد ذكي بواجهة سطح مكتب
عصرية (CustomTkinter، Dark Mode)، يدعم العربي والإنجليزي، ومبني حول محرك
أوامر/أتمتة (Core Engine) قابل للتوسعة.

## التشغيل

```bash
pip install -r requirements.txt
python main_gui.py
```

## بناء EXE (ويندوز)

```bat
build_exe.bat
```

الملف الناتج هيكون في `dist/SmartAssistant.exe`.

## الملفات

- `main_gui.py` — واجهة المستخدم (CustomTkinter)، بدون أي منطق تنفيذ داخلها.
- `core_engine.py` — Core Engine: تسجيل الأوامر (`CommandRegistry`)، طابور
  تنفيذ خلفي (`AssistantEngine`)، ودعم مهام أتمتة إضافية عبر `run_task`.
- `i18n.py` — طبقة الترجمة (عربي/إنجليزي) لكل نصوص الواجهة.
- `requirements.txt` — المتطلبات.
- `build_exe.bat` — سكربت بناء ملف تنفيذي واحد باستخدام PyInstaller.

## إضافة أمر جديد

```python
engine.registry.register(
    "mycommand",
    lambda ctx: f"got args: {ctx.args}",
    "وصف مختصر للأمر",
)
```

## إضافة مهمة أتمتة

```python
def my_task(ctx):
    ctx.engine.on_log("running automation task...", "info")

engine.run_task("my_task", my_task)
```
