# Smart Assistant

وحدة مستقلة بالكامل (منفصلة عن Y99 Filter Bot): مساعد ذكي بواجهة سطح مكتب
عصرية (CustomTkinter، Dark Mode)، يدعم العربي والإنجليزي، ومبني حول محرك
أوامر/أتمتة (Core Engine) قابل للتوسعة عبر نظام إضافات (Plugins).

## التشغيل

```bash
pip install -r requirements.txt
python main_gui.py
```

الأوامر اللي بتحلل/تعالج فيديو وصوت (`probe`, `convert`, `trim`, `merge_av`,
`concat`) محتاجة **FFmpeg** متثبت على الجهاز (أداة مجانية ومفتوحة المصدر،
مش pip package): https://ffmpeg.org/download.html

## بناء EXE (ويندوز)

```bat
build_exe.bat
```

الملف الناتج هيكون في `dist/SmartAssistant.exe`.

## الملفات

- `main_gui.py` — واجهة المستخدم (CustomTkinter)، فيها زرار 📎 لرفع
  ملف (فيديو/صورة/صوت) وتحليله فوراً عبر أمر `probe`.
- `core_engine.py` — Core Engine: تسجيل الأوامر (`CommandRegistry`)، طابور
  تنفيذ خلفي (`AssistantEngine`)، وتحميل الإضافات ديناميكياً من `plugins/`.
- `i18n.py` — طبقة الترجمة (عربي/إنجليزي) لكل نصوص الواجهة.
- `version.py` / `version.json` — رقم إصدار التطبيق، بيُستخدم في التحقق
  من التحديثات.
- `plugins/` — كل إضافة ملف `.py` مستقل بيسجل أوامره بنفسه:
  - `media_plugin.py` — تحليل ومعالجة فيديو/صوت عبر FFmpeg.
  - `self_improve_plugin.py` — يحلل السجل الأخير ويقترح تحسينات عبر
    نموذج محلي مجاني (Ollama)، بدون أي تعديل تلقائي للكود.
  - `update_plugin.py` — تحقق آمن (بدون تحديث تلقائي) من وجود إصدار أحدث.
- `requirements.txt` — المتطلبات.
- `build_exe.bat` — سكربت بناء ملف تنفيذي واحد باستخدام PyInstaller.

## نظام الإضافات (Plugins) — إزاي المشروع "يتوسع من نفسه"

أي ملف `.py` تحطه في `plugins/` (سواء وأنت بتطور، أو جنب `SmartAssistant.exe`
بعد البناء) بيتحمّل تلقائياً لو فيه دالة `register(engine)`. مفيش حاجة في
`core_engine.py` بتحتاج تتعدل. جرب:

```python
# plugins/hello_plugin.py
def _cmd_hello(ctx):
    return f"hello, {' '.join(ctx.args) or 'world'}!"

def register(engine):
    engine.registry.register("hello", _cmd_hello, "تحية بسيطة")
```

وبعدين من داخل التطبيق اكتب `reload_plugins` عشان يلقط الإضافة الجديدة
من غير ما تعيد تشغيل التطبيق، أو `plugins` عشان تشوف كل الإضافات المحمّلة.

## ليه مفيش "توليد فيديو/صورة بالذكاء الاصطناعي" زي Higgsfield؟

بناء نموذج generative AI خاص ينافس منصات زي Higgsfield محتاج فرق بحث ML
وملايين الدولارات من موارد تدريب — مش حاجة ممكن تتبنى "مجاناً" في مشروع
زي ده. المرحلة الحالية بتركّز على اللي فعلاً ممكن يكون مجاني ومحلي 100%:
تحليل الميديا، تحرير/دمج عبر FFmpeg، واقتراحات تحسين عبر نموذج محلي
(Ollama). لو حبيت مرحلة تانية بموديل توليد صور/فيديو مفتوح المصدر شغال
محلياً (زي Stable Diffusion)، ده ممكن يتضاف كإضافة (plugin) جديدة — لكنه
هيحتاج GPU قوي ومساحة تخزين كبيرة على جهاز المستخدم.
