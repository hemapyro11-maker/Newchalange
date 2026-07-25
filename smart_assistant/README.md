# نيزوكو (Nezuko) — Smart Assistant

وحدة مستقلة بالكامل (منفصلة عن Y99 Filter Bot): مساعد ذكي بواجهة سطح مكتب
عصرية (CustomTkinter، Dark Mode)، عربي-مصري أولاً (مع دعم إنجليزي)، ومبني
حول محرك أوامر/أتمتة (Core Engine) قابل للتوسعة عبر نظام إضافات (Plugins).
الاسم الداخلي للكود (`main_gui.py`, `AssistantEngine`, ...) فضل زي ما هو
عمدًا — التغيير في هوية الواجهة (العنوان، والصوت) مش في بنية الكود.

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

الملف الناتج هيكون في `dist/Nezuko.exe`.

## الملفات

- `main_gui.py` — واجهة المستخدم (CustomTkinter)، فيها زرار 📎 لرفع
  ملف (فيديو/صورة/صوت) وتحليله فوراً عبر أمر `probe`، وزرار 🛡️ منفصل
  لرفع **أي ملف أيًا كان نوعه أو حجمه** وفحصه أمنيًا فورًا عبر
  `security_report` — من غير فلتر نوع ملف، ومن غير أي تنفيذ تلقائي:
  الفحص بيبدأ بس لما تختار الملف بنفسك من نافذة الاختيار. الملفات
  الكبيرة (أكبر من 5MB) بتتفحص فيروسات كاملة عبر ClamAV (بالستريمنج،
  من غير ما تتحمّل في الذاكرة)، والفحص النصي (أسرار/كود) بيتفعّل تلقائي
  للملفات الأصغر بس، حفاظاً على الأداء.
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
  - `connectors_plugin.py` — **Connectors** بنفس بروتوكول MCP اللي
    بيستخدمه Claude/Claude Desktop (شرح تفصيلي تحت).
  - `macros_plugin.py` — أوامر مخصصة (زي Custom Slash Commands في
    Claude Code) من ملفات `.txt` في `commands/`.
  - `todo_plugin.py` — قائمة مهام محلية (`todo add/list/done/clear`).
  - `fetch_plugin.py` — تحميل صفحة ويب وعرض نصها (`fetch <url>`).
  - `inspect_plugin.py` — تحليل ملفات على مستوى البايتات: تحديد النوع
    (`identify`)، `hexdump`، `strings`، وعرض محتويات أرشيف (`archive_list`)
    — بدون أي باكدج خارجي (شرح النطاق تحت).
  - `re_plugin.py` — هندسة عكسية متقدمة: `elf_info`, `pe_info`,
    `entropy`, `disasm` (شرح تفصيلي تحت).
  - `scaffold_plugin.py` — سقالات مشاريع جاهزة لـ 19 نوع (`scaffold
    <type> <name>` — شرح تفصيلي تحت).
  - `database_plugin.py` — أدوات قواعد بيانات حقيقية (sqlite3):
    `db_schema`, `db_query`, `db_export_csv`, `db_migration_status`,
    `db_migrate` (تطبيق هجرات SQL بترتيب داخل transaction، مع تتبّع
    checksum لكل هجرة اتطبقت وتوقف فوري لو محتواها اتغير)، `db_indexes`
    (عرض indexes كل جدول وتنبيه لأعمدة foreign key من غير index).
  - `data_science_plugin.py` — تحليل بيانات حقيقي (pandas/matplotlib):
    `csv_describe`, `csv_plot`, `csv_correlate`.
  - `screenplay_plugin.py` — تحليل سيناريو حقيقي بصيغة Fountain:
    `fountain_stats` (مشاهد، شخصيات، حوار، تقدير صفحات).
  - `design_plugin.py` — لوجو بسيط وتوليد كل أحجام أيقونات iOS/Android
    من صورة واحدة (`make_logo`, `app_icons`) عبر Pillow.
  - `security_plugin.py` — `hash_file` (تحقق سلامة)، `port_scan` (فحص
    منافذ محلي بنطاق محدود، لأجهزتك المصرح لك باختبارها بس)، `tls_check`
    (فحص شهادة TLS: تاريخ انتهاء، مُصدر، SAN)، `file_perms` (تدقيق
    صلاحيات: world-writable, SUID/SGID, ملفات حساسة مقروءة).
  - `security_scan_plugin.py` — فحص أمان شامل (شرح تفصيلي تحت):
    `code_scan` (تحليل AST لكود بايثون: eval/exec، shell=True، pickle،
    yaml.load غير آمن، SQL injection، أسرار مكشوفة — مع إصلاح تلقائي
    للحالات الآمنة الواضحة بـ `--fix`)، `vuln_scan` (أسرار مكشوفة في أي
    ملف نصي + ثغرات مكتبات معروفة عبر pip-audit/npm audit)، `virus_scan`
    (فحص فيروسات/PUA حقيقي عبر ClamAV، بحجر صحي تلقائي — مش حذف أو
    "تنظيف")، `quarantine_file`/`quarantine_list`/`quarantine_restore`،
    و`security_report` (تقرير شامل بيجمعهم كلهم).
  - `plugin_forge_plugin.py` — المساعد يصمم plugins جديدة بنفسه ويصلح
    أخطاءها تلقائياً (شرح تفصيلي تحت).
  - `cinema_plugin.py` — مونتاج وتصحيح ألوان بمستوى احترافي: تصحيح
    ألوان سينمائي، انتقالات، letterbox، تثبيت اهتزاز، تغيير سرعة،
    Picture-in-Picture، شاشة خضراء، وضبط جهارة الصوت لمعيار بث
    (شرح تفصيلي تحت).
  - `voice_plugin.py` — صوت نيزوكو (`speak`, `voice_status`؛ شرح تفصيلي
    تحت): سلسلة احتياطية حقيقية من edge-tts (صوت مصري أنثوي، محتاج
    إنترنت) → Piper (صوت عربي محلي، بيتحمّل مرة واحدة) → espeak-ng
    (احتياطي محلي دايمًا شغال).
  - **فريق يوتيوب الاحترافي** (7 إضافات، شرح تفصيلي تحت): `youtube_strategy_plugin.py`،
    `content_research_plugin.py`، `youtube_seo_plugin.py`،
    `thumbnail_plugin.py`، `youtube_ads_plugin.py`،
    `community_manager_plugin.py`، `youtube_analytics_plugin.py`.
  - `environment_plugin.py` — "طبيب" بيئة العمل: `env_check` (شرح تفصيلي تحت).
  - `external_tools_plugin.py` — ربط أي برنامج خارجي (CLI/سطح مكتب)
    كأمر دائم في نيزوكو (شرح تفصيلي تحت).
  - `android_plugin.py` — تحكم حقيقي في تطبيقات أندرويد عبر ADB (شرح
    تفصيلي تحت).
- `connectors.example.json` — مثال لإعداد MCP Connectors (انسخه لـ
  `connectors.json` وعدّله). `connectors.json` نفسه بيتعمل تلقائياً
  أول ما التطبيق يشتغل ومش متتبع في git (ممكن يحتوي مسارات/أسرار خاصة بيك).
- `commands/` — مجلد الـ macros (بيتعمل تلقائياً، فاضي في الأول).
- `plugins_pending/` — plugins ولّدها/صلّحها المساعد بنفسه ولسه مستنية
  مراجعتك قبل ما تشتغل فعلياً (بيتعمل تلقائياً، مش متتبع في git).
- `skills.json` — سجل تراكمي دائم لكل إضافة وأمر اتعلمهم المساعد من
  الأول (مش متتبع في git، خاص بكل جهاز — شرح تحت).
- `requirements.txt` — المتطلبات.
- `requirements-dev.txt` — متطلبات التطوير (pytest) + `requirements.txt`.
- `tests/` — اختبارات آلية حقيقية (pytest) لكل plugin وCore Engine.
- `build_exe.bat` — سكربت بناء ملف تنفيذي واحد باستخدام PyInstaller.

## الاختبارات الآلية (Tests)

```bash
pip install -r requirements-dev.txt
pytest
```

568 اختبار حقيقي (مش placeholders) بتغطي كل plugin و Core Engine —
تحليل ELF/PE حقيقي، معالجة فيديو حقيقية عبر FFmpeg، توليد أيقونات
حقيقي، حلقة توليد/تصحيح plugin_forge كاملة، إلخ. الاختبارات اللي
محتاجة أدوات اختيارية (FFmpeg, Pillow, capstone, mcp) بتتخطى تلقائياً
(`SKIPPED`) لو الأداة مش متثبتة، بدل ما تفشل — جرّبتها في البيئتين
(بالأداة وبدونها) والنتيجة صح في الحالتين.

**اختبار الحمل:** `python loadtest.py` — أداة benchmark مستقلة (مش
pytest) بتقيس أداء المكونات الحرجة تحت أحمال حقيقية (مئات الآلاف من
الصفوف/الأوامر/التعليقات) وتوريك النطاق العملي الفعلي. النتائج
والمنهجية كاملة في [`LOADTEST.md`](LOADTEST.md).

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

## Connectors (MCP) — زي الموجودة في Claude

المساعد بيدعم **Model Context Protocol (MCP)** — نفس البروتوكول المفتوح
المصدر اللي Claude / Claude Desktop بيستخدمه للـ Connectors (Google Drive،
Gmail، GitHub، filesystem محلي، ...). أي MCP server بتوصّله (محلي ومجاني
زي `filesystem`/`git`/`fetch`، أو أي server تاني) بتظهر أدواته تلقائياً
كأوامر في المساعد.

**الإعداد:**

1. `pip install mcp` (موجود في `requirements.txt`).
2. انسخ `connectors.example.json` إلى `connectors.json` وعدّل السيرفرات
   اللي عايزها — نفس شكل ملف إعداد Claude Desktop بالظبط:
   ```json
   {
     "mcpServers": {
       "filesystem": {
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
       }
     }
   }
   ```
3. شغّل التطبيق — بيتصل تلقائياً بكل connector معرّف. تابع الحالة بأمر
   `connectors`، أو اتصل/افصل يدوياً بـ `connectors connect <name>` /
   `connectors disconnect <name>`.
4. أدوات كل connector بتظهر كأوامر باسم `<connector>.<tool>`، وباخد
   الوسيطة كـ JSON، مثلاً:
   ```
   filesystem.read_file {"path": "/tmp/notes.txt"}
   ```

ملحوظة: بعض الـ MCP servers الجاهزة (زي `@modelcontextprotocol/server-*`)
محتاجة Node.js (`npx`) أو Python (`uvx`) متثبتين على الجهاز — دول أدوات
مجانية ومفتوحة المصدر برضه، مفيش أي اشتراك أو تكلفة.

## أوامر مخصصة (Macros) — زي Custom Slash Commands في Claude Code

حط ملف `.txt` في `commands/`، كل سطر أمر يتنفذ بالتتابع، و`{args}` بتتبدل
بأي حاجة يكتبها المستخدم بعد اسم الأمر:

```
# commands/deploy.txt
echo بدأ الديبلوي لـ {args}
run git pull
```

بعدها اكتب `deploy production` في المساعد، وهيشغل السطرين بالترتيب.
`macros` بتعرض كل الـ macros المتاحة، و`reload_macros` بتلقط أي ملف جديد.

## المهارات التراكمية (Skills Ledger) — تعلّم بيفضل ومبيتنساش

كل إضافة اتحملت مرة واحدة، وكل أمر اتنفذ، بيتسجلوا في `skills.json` —
سجل تراكمي بس (append-only): حتى لو مسحت ملف إضافة بعدين، سجل إنها
"اتعلمت" فاضل موجود، وعدد استخدام كل أمر بيزيد مع الوقت ومبيرجعش صفر.
جرب الأمر `skills` عشان تشوف كل حاجة اتعلمها المساعد من أول ما اشتغل.

ده التفسير الصادق لـ"تطور ذاتي بيكتسب مهارات ومتضعش منه" في نطاق ممكن
فعلياً: مش موديل بيعيد تدريب نفسه، لكن نظام بيتذكر كل حاجة قدر عليها
قبل كده وبيوسّع نفسه بإضافات جديدة (plugins) بمرور الوقت من غير ما
يفقد أي حاجة اتعلمها.

**"بدون تدخل مني" — الحد اللي المشروع مش هيتخطاه:** التوليد والتصحيح
التلقائي للـ plugins (شرح تحت) بيغطي جزء كبير من "بدون تدخل" فعلاً —
لكن نقل كود مولّد آلياً لتشغيل حقيقي بامتيازات كاملة في التطبيق من
غير أي مراجعة بشرية هو بالتعريف ثغرة تنفيذ كود عن بُعد (RCE) على
جهازك، وده حد مش هيتغير. الخطوة الوحيدة اللي لسه محتاجة إذنك الصريح:
`approve_plugin`.

## المساعد بيصمم ويصلح Plugins بنفسه — `plugin_forge_plugin.py`

`create_plugin <name> <وصف المهمة>` بيطلب من نموذج محلي مجاني (Ollama)
يكتب plugin جديد، وبعدين تلقائياً وبدون أي تدخل بشري: يتحقق من الكود
(syntax + تشغيل فعلي في عملية منعزلة بمهلة زمنية لمنع infinite loops)،
ولو فشل بيبعت الخطأ نفسه تاني للنموذج ويطلب تصحيح، لحد 4 محاولات. ده
حلقة "اكتشاف الخطأ وإصلاحه" الحقيقية.

**بس النتيجة النهائية مش بتتحمّل كأمر حي دائم في التطبيق أوتوماتيك.**
بتتحفظ في `plugins_pending/` وتقولك النتيجة (نجح ولا لسه فيه مشكلة)،
وإنت اللي تقرر. ملحوظة أمان مهمة: خطوة التحقق نفسها بتشغّل الكود
المتولد مرة (في عملية منعزلة بمهلة زمنية) *قبل* ما تراجعه — التفاصيل
والحدود الحقيقية لده موجودة في [`SECURITY.md`](SECURITY.md).

```
create_plugin weather بلاش صور، يجيب حالة الطقس من نص المستخدم
review_pending weather      # تشوف الكود كامل قبل ما توافق
approve_plugin weather      # لو تمام — يتنقل لـ plugins/ ويتحمّل فوراً
reject_plugin weather       # لو مش عايزه
```

`fix_plugin <name> [error]` بنفس الآلية: يصلح plugin موجود (لو الخطأ
مش مكتوب، بيدور عليه في السجل بنفسه)، وبرضه بيحط النتيجة في
`plugins_pending/` مستنية موافقتك.

اتختبرت الحلقة دي كاملة (توليد → فشل → إصلاح تلقائي → نجاح → موافقة →
تحميل حي → استخدام الأمر الجديد فعلياً) — شغالة بالكامل.

## تحليل الملفات (Inspect) — الجزء الشرعي من "الهندسة العكسية"

`identify` / `hexdump` / `strings` / `archive_list` بتديك نفس الإمكانيات
اللي أدوات زي `file`/`xxd`/`strings` اليونكسية بتقدمها: تعرف نوع أي ملف
من البايتات بتاعته، تشوف محتواه الخام، تستخرج النصوص المقروءة جواه،
وتشوف محتويات أرشيف من غير فك ضغط. مفيد لفهم ملف مش عارف نوعه، تصحيح
أخطاء، أو تحليل جنائي على ملفاتك إنت.

**مش موجود ومش هيتضاف عن قصد:** كسر باسوردات، تجاوز حماية DRM، أو فك
تشفير ملفات/برامج محمية اللي مش من حقك توصلها. ده خارج نطاق المشروع
تماماً بغض النظر عن الصياغة.

## هندسة عكسية متقدمة (Static Analysis) — `re_plugin.py`

تحليل بنية ملفات تنفيذية حقيقي، بنفس المستوى اللي أدوات RE قياسية
(readelf/objdump/pefile) بتقدمه — بدون أي باكدج خارجي غير `capstone`
(محرك disassembly مفتوح المصدر، BSD-licensed، نفس المحرك اللي بيستخدمه
Ghidra/radare2). كل النتائج اتقارنت واتأكد إنها مطابقة لـ `readelf`/
`objdump` على ملفات حقيقية:

- `elf_info <file>` — بنية ملف ELF (لينكس): الـ architecture، entry
  point، كل الـ sections، والمكتبات المطلوبة (`DT_NEEDED`).
- `pe_info <file>` — بنية ملف PE (ويندوز `.exe`/`.dll`): وقت البناء،
  entry point، الـ sections، وجدول الـ imports كامل (كل DLL والدوال
  المستوردة منه بالاسم).
- `entropy <file> [chunk_size]` — حساب Shannon entropy لاكتشاف مناطق
  مضغوطة/مشفّرة/packed (تقنية قياسية في تحليل البرمجيات الخبيثة).
- `disasm <file> [offset] [length] [arch]` — فك تجميع حقيقي لتعليمات
  المعالج (x86/x64/ARM/ARM64) عبر Capstone. من غير offset، بيلاقي
  نقطة الدخول (entry point) تلقائياً في ملفات ELF/PE ويبدأ منها.

النطاق واضح: تحليل *ساكن* لبنية ملف عندك حق تحلله (فهم كود، اعتماديات،
دلائل تغليف) — مش كسر حماية ولا تجاوز تراخيص، زي ما اتقال فوق.

## فحص أمان شامل — `security_scan_plugin.py`

أربع أدوات حقيقية، كل واحدة بحدود واضحة عن قصد مش "ذكاء اصطناعي بيحل كل
حاجة":

- **`code_scan <path> [--fix]`** — تحليل AST حقيقي لكود بايثون (مش
  regex سطحي): بيكتشف `eval`/`exec`، `os.system`، `subprocess(...,
  shell=True)`، `pickle.load`، `yaml.load` غير آمن، هاش ضعيف
  (md5/sha1)، SQL injection عبر f-string أو string concatenation
  (ومبيلمسش parameterized queries)، وأسرار مكتوبة صريح في الكود. مع
  `--fix`، بيصلح تلقائيًا **الحالة الآمنة والواضحة 100% بس**:
  `yaml.load()` من غير `Loader` أو بـ `Loader=yaml.Loader/FullLoader/
  UnsafeLoader` بيتحول لـ `safe_load()`/`Loader=yaml.SafeLoader` —
  بإحداثيات دقيقة من الـ AST نفسه (مش استبدال نصي عشوائي)، وبيتأكد إن
  الملف لسه بيترجم بعد التعديل قبل ما يكتبه، وإلا يرجع للأصل من غير
  ما يلمسه. أي ملاحظة تانية (eval، shell=True، أسرار...) بتتبلّغ بس
  للمراجعة اليدوية — إصلاحها الآمن محتاج فهم للسياق مش تحويل مضمون.
- **`vuln_scan <path>`** — أسرار مكشوفة في أي ملف نصي (مفاتيح AWS،
  Slack tokens، JWT، مفاتيح خاصة، بيانات اعتماد في connection strings،
  وتعيينات أسرار عامة زي `SECRET`/`API_KEY`/`PASSWORD` — بما فيها ملفات
  `.env` اللي اسمها بالكامل نقطة، وده حالة حقيقية `pathlib` بيتعامل
  معاها غلط بالافتراضي) + ثغرات مكتبات معروفة عبر `pip-audit`
  (لـ requirements.txt) و`npm audit` (لـ package.json) + صلاحيات ملفات
  (بيستدعي `file_perms` من `security_plugin.py` مباشرة عبر command
  registry، مش نسخة مكررة من نفس المنطق).
- **`virus_scan <path> [--no-quarantine]`** — فحص فيروسات وبرامج تجسس
  (PUA/spyware عبر `--detect-pua=yes`) *حقيقي* عبر
  [ClamAV](https://www.clamav.org/downloads) (مجاني ومفتوح المصدر
  بالكامل) — مش محرك فحص مؤلَّف. **أي ملف يتكشف مصاب بيتنقل تلقائيًا
  للحجر الصحي (quarantine)، مش بيتمسح ولا "يتنضّف" في مكانه** — لأن
  ضمان إن ملف "اتنضّف" من فيروس وهيفضل شغال طبيعي بعد كده مش حاجة أي
  أداة أمان جادة بتقدر تضمنها فعليًا، حتى لو الملف نفسه ماتغيّرش.
- **`quarantine_file` / `quarantine_list` / `quarantine_restore`** —
  إدارة الحجر الصحي يدويًا: نقل أي ملف مشبوه بنفسك، عرض كل حاجة فيه،
  أو استعادة ملف (لو false positive) — بيرفض يكتب فوق ملف موجود بالفعل
  في مكان الاستعادة عشان محدش يفقد بيانات بالغلط.
- **`security_report <path>`** — تقرير واحد بيجمع الثلاثة كلهم.

## تطوير متعدد المجالات (Desktop / Web / Mobile / Games / Data / AI / أمان / أفلام...)

المساعد بقى فيه أدوات حقيقية شغالة عبر عشرات مجالات التطوير، كلها
مبنية على أدوات مجانية 100%:

| المجال | الأمر | الحالة |
|---|---|---|
| Desktop App Developer | Smart Assistant نفسه (CustomTkinter) + `scaffold python` | ✅ |
| Frontend Web Developer | `scaffold web <name>` | ✅ HTML/CSS/JS شغال فوراً |
| Backend Web Developer | `scaffold backend <name>` | ✅ FastAPI شغال فوراً (`uvicorn main:app`) |
| Full-Stack Web Developer | `scaffold fullstack <name>` | ✅ frontend+backend مع بعض |
| Android Developer | `scaffold android <name>` | ✅ Gradle settings/dependencies كاملة؛ منطق `Greeter.kt` منفصل عن Android framework — **اتجرب فعلياً**: كومبايل بـ kotlinc واختبارات JUnit عدّت (OK 2 tests) |
| iOS Developer | `scaffold ios <name>` | ✅ سقالة SwiftUI + منطق `Greeter.swift` منفصل للاختبار بـ XCTest — محتاجة Xcode على ماك لتترجم فعليًا (قيد نظام موثّق، مش تكلفة) |
| Game Developer | `scaffold game <name>` | ✅ لعبة Pygame **شغالة فعلياً** — منطق حركة اللاعب منفصل ومُختبر، واختبار headless حقيقي (`SDL_VIDEODRIVER=dummy`) بيشغّل حلقة اللعبة كاملة |
| Data Scientist | `csv_describe`, `csv_plot`, `csv_correlate` | ✅ اتجرب على بيانات حقيقية (إحصائيات، رسومات، correlation) |
| AI/ML Engineer | `scaffold ml <name>` | ✅ **اتجرب فعلياً** — درّب نموذج حقيقي بدقة 100% على بيانات اختبار |
| Systems/Embedded Developer | `scaffold embedded <name>` | ✅ بنية HAL حقيقية (`blink.c` منفصل عن الهاردوير) — **اتجرب فعلياً**: `make check` (compile) و`make test` (منطق الـ blink شغال ومُختبر على الـ host) |
| Cybersecurity/Pentest | `hash_file`, `port_scan`, `tls_check`, `file_perms`, `code_scan`, `vuln_scan`, `virus_scan`, `security_report`, `re_plugin`/`inspect_plugin` | ✅ اتجرب فعلياً: شهادة self-signed، صلاحيات SUID/world-writable، كشف eval/shell=True/SQLi/أسرار حقيقية، وكشف+حجر صحي فعلي لملف مصاب عبر ClamAV (بتوقيع اختباري مخصص) |
| Cloud/DevOps Engineer | `scaffold docker <name>` (multi-stage, non-root, HEALTHCHECK), `scaffold ci <name>` (lint→test matrix→build) | ✅ Dockerfile اتفحص بـ `docker build`، YAML اتأكد بـ `yaml.safe_load` |
| Database Engineer | `db_schema`, `db_query`, `db_export_csv`, `db_migration_status`, `db_migrate`, `db_indexes` | ✅ SQLite حقيقي؛ هجرات اتجربت فعلياً (نجاح/توقف عند خطأ/رفض tampering)، وكشف foreign key من غير index |
| Blockchain Developer | `scaffold blockchain <name>` | ✅ عقد Solidity + Hardhat toolbox test حقيقي (deploy/تعديل/owner guard) — **اتجرب فعلياً**: العقد اتترجم بـ solc لـ bytecode حقيقي |
| Quantum Computing | `scaffold quantum <name>` | ✅ دائرة Bell state — **اتجرب فعلياً** على AerSimulator: القياسات '00'/'11' بس (تشابك حقيقي)، pytest بيعدي |
| AR/VR Developer | `scaffold arvr <name>` | ✅ WebXR (A-Frame) + component تفاعلي حقيقي — **اتجرب فعلياً**: `npm start` شغّل السيرفر وقدّم الملفات |
| QA/Test Automation | `scaffold pytest <name>` | ✅ سقالة pytest + tox شغالة وبتعدي فعلاً (pytest و`tox -e py311` اتجربوا) |
| Kernel/Low-Level Developer | `scaffold kernel_module <name>` | ✅ يحتاج kernel headers مثبتة للبناء (قيد نظام، موثّق) — README لـ insmod/rmmod/dmesg |
| Network/Multiplayer Backend | `scaffold multiplayer_server <name>` | ✅ **اتجرب فعلياً** — سيرفر حقيقي استقبل اتصال TCP |
| Video Editor | `media_plugin` + `cinema_plugin` (مونتاج احترافي، شرح تحت) | ✅ كله اتجرب على فيديو حقيقي |
| Color Grading / VFX / Audio Mixing | `cinema_plugin` (`color_grade`, `chroma_key`, `master_audio`...) | ✅ |
| Logo Designer | `make_logo <text> <output.png>` | ✅ لوجو حروف أولى فوري |
| App/UI Designer | `app_icons <source.png> <out_dir>` | ✅ يولّد كل أحجام أيقونات iOS+Android (19 حجم) من صورة واحدة |
| Screenwriter | `scaffold screenplay <name>` + `fountain_stats` | ✅ صيغة Fountain القياسية + تحليل حقيقي (مشاهد/شخصيات/حوار) |
| Game Narrative Designer | `scaffold ink_story <name>` | ✅ صيغة Ink (نفس أداة ألعاب حقيقية زي 80 Days) |
| YouTube Creator/Growth Team | 7 إضافات (استراتيجية، بحث محتوى، SEO، مصغرات، إعلانات، تواصل مجتمعي، تحليلات — شرح تفصيلي تحت) | ✅ بيانات حقيقية عبر YouTube Data API v3 (محتاج مفتاح مجاني)، توليد مصغرات فعلي عبر Pillow، تحليل مشاعر/سبام محلي بدون إنترنت |

**اللي مش موجود ومش هيتضاف — بصراحة:** إخراج سينمائي، اختيار ممثلين،
تصميم أزياء/ماكياج، تصوير وإضاءة فعلية، تسجيل صوت ميداني، إنتاج/تسويق/
توزيع الأفلام، تصميم مفاهيمي وكتابة قصة الألعاب، إدارة إنتاج الألعاب،
تمثيل صوتي/موشن كابتشر، وإدارة مجتمعات اللاعبين. دول أدوار قرار بشري
وحرفة فيزيائية وعمل تجاري — مش حاجة أي أداة برمجية ممكن "تكون" بمستوى
احترافي، بغض النظر عن الصياغة. أي حاجة تانية من الليستة الأصلية مش
مذكورة هنا اتغطت فعلياً بالأدوات فوق.

**ملحوظة مهمة عن iOS/Android:** التطبيق بيولّد الكود والسقالة، لكن
البناء الفعلي لـ .ipa/.apk محتاج Xcode (ماك بس) أو Android Studio —
دي قيود المنصات نفسها (Apple/Google) مش حاجة المشروع فارض تكلفة عليها؛
الأدوات دي مجانية للتنزيل لكنها محتاجة نظام تشغيل/بيئة معينة.

## مونتاج احترافي (Cinema-Grade Editing) — `cinema_plugin.py`

الأوامر دي بتستخدم نفس تقنيات المونتاج والتصحيح اللوني اللي أدوات
احترافية زي DaVinci Resolve/Premiere بتستخدمها تحت الغطاء (فلاتر FFmpeg
حقيقية، مش تقريب)، اتختبرت كلها بصرياً على فيديو حقيقي:

- `color_grade <in> <out> [preset]` — تصحيح ألوان سينمائي: presets
  `cinematic`, `teal_orange` (اللوك الهوليوودي الكلاسيكي), `noir`,
  `vintage`, `warm`, `cool`, `bw`.
- `transition <clip1> <clip2> <out> [style] [duration]` — انتقال حقيقي
  بين كليبين (58 نوع: dissolve, wipe, slide, zoom...)، فيديو وصوت مع
  بعض (`xfade` + `acrossfade`).
- `letterbox <in> <out> [ratio=2.39]` — الشرايط السوداء السينمائية
  (2.39:1 زي أفلام السينما سكوب).
- `stabilize <in> <out>` — تثبيت اهتزاز الكاميرا (two-pass عبر
  libvidstab، نفس التقنية في مثبتات الفيديو الاحترافية).
- `speed_ramp <in> <out> <factor>` — سلو موشن/تسريع مع تعديل طبقة
  الصوت تلقائياً (مش بس تسريع الفيديو وسيبان الصوت).
- `pip <bg> <overlay> <out> [position] [scale]` — Picture-in-Picture.
- `chroma_key <fg> <bg> <out> [color] [similarity]` — دمج خلفية خضراء
  (green screen) حقيقي — جربته بموضوع ملوّن فوق خلفية خضرا واتأكد إن
  الخلفية بس اللي اتشالت والموضوع فضل زي ما هو.
- `master_audio <in> <out> [lufs]` — توحيد جهارة الصوت لمعيار بث حقيقي
  (loudnorm/EBU R128) — `-16` LUFS لليوتيوب/الستريمنج، `-23` للبث.
- `denoise_audio <in> <out>` — إزالة ضوضاء الخلفية من الصوت.
- `title_card <text> <out> [duration] [size]` — لوحة عنوان متحركة
  (fade in/out حقيقي، مش نص ثابت).

**بصراحة كاملة:** الأدوات دي بتديك نفس المحرك التقني اللي أفلام
هوليوود بتتمنتج بيه (FFmpeg نفسه بيتستخدم في استوديوهات حقيقية) —
لكن "جودة هوليوود" الفعلية قرارات فنية (توقيت القص، اختيار الألوان،
حكاية القصة) بيعملها مونتير بشري. السوفت وير بيدّيك الأداة، مش الفن.

## صوت نيزوكو (Text-to-Speech) — `voice_plugin.py`

الأمر `speak <نص>` بينطق أي نص بصوت نيزوكو عبر سلسلة احتياطية حقيقية
من ثلاث محركات، من الأفضل جودة للأضمن توفر — كل واحدة بيتجرب لو اللي
قبلها فشل فعليًا، مش اختيار عشوائي:

1. **edge-tts** — مجاني بالكامل من غير API key أو اشتراك، وفيه صوت
   مصري أنثوي حقيقي (`ar-EG-SalmaNeural`). العيب الوحيد: التوليد نفسه
   بيحصل على سيرفرات مايكروسوفت، يعني محتاج إنترنت وقت الاستخدام —
   مش نموذج محلي 100%.
2. **Piper** — محرك TTS عصبي محلي مفتوح المصدر (GPL)، بيتحمّل صوته
   (`ar_JO-kareem`، ~60MB) مرة واحدة بس وبعدين يشتغل offline بالكامل.
   **بصراحة:** مفيش صوت عربي أنثوي في مكتبة أصوات Piper الرسمية حاليًا
   — ده قيد حقيقي في الأدوات المتاحة مجانًا، مش قرار تصميم من المشروع.
3. **espeak-ng** — مضمّن محليًا دايمًا (لازم تتثبته يدوي على الجهاز،
   [espeak-ng.github.io](https://espeak-ng.github.io/espeak-ng/))، صوت
   عربي روبوتي قديم الطراز (formant synthesis)، لكنه الضمانة الأخيرة
   اللي هتشتغل حتى من غير إنترنت وبدون تحميل أي حاجة.

`voice_status` بيوريك حالة كل محرك (متثبت؟ الصوت متحمّل؟). في الواجهة
الرسومية فيه زرار 🔊/🔇 في الأعلى يفعّل/يوقف نطق نتيجة كل أمر تلقائيًا
— افتراضيًا مقفول، زي أي فحص في المشروع ده: مبيشتغلش غير لما تختاره
إنت بنفسك.

## فريق يوتيوب الاحترافي — 7 إضافات بمستوى متخصص حقيقي

7 أدوار متخصصة (استراتيجية، بحث محتوى، SEO، تصميم مصغرات، إعلانات،
تواصل مجتمعي، تحليلات) — كل واحدة بمنطق حقيقي (حسابات، تحليل نص، توليد
صور فعلي)، مش نصوص عامة مولّدة. الأدوات اللي محتاجة بيانات حقيقية عن
قناة/فيديو بتستخدم **YouTube Data API v3** (مجاني بالكامل — مفتاح API
مجاني من [Google Cloud Console](https://console.cloud.google.com)، بس
محتاج حساب Google، مفيش أي اشتراك أو تكلفة):

```
youtube_set_key <API_KEY>      # يتحفظ في smart_assistant/youtube_config.json (مش متتبع في git)
youtube_key_status             # هل فيه مفتاح متظبط؟
```

من غير مفتاح، أي أمر محتاج بيانات حقيقية بيقولك كده صراحةً بدل ما يورّي
بيانات وهمية — الأدوات اللي مش محتاجة إنترنت خالص (توليد مصغرات، تحليل
مشاعر، حاسبات) بتشتغل عادي من غيره.

### 1. مدير استراتيجية يوتيوب — `youtube_strategy_plugin.py`
- `channel_stats <channel_id_or_@handle>` — مشتركين/مشاهدات/فيديوهات حقيقية.
- `channel_strategy_report <channel>` — اتساق النشر (معامل تباين الفجوات
  بين آخر الفيديوهات) ونسبة الوصول (متوسط مشاهدات ÷ مشتركين) مع توصيات.
- `content_calendar <videos_per_week> <weeks>` — خطة نشر بتواريخ حقيقية،
  موزّعة بالتساوي عبر أيام الأسبوع (مش متكدسة).
- `competitor_compare <channel_1> <channel_2>` — مقارنة إحصائيات جنب بعض.

### 2. باحث المحتوى وكاتب السيناريو — `content_research_plugin.py`
- `youtube_search <query>` / `trending_videos [region=EG]` — بحث/ترند حقيقي
  مع أرقام مشاهدات فعلية.
- `keyword_ideas <topic>` — قوالب نية-بحث عربي/إنجليزي (بدون إنترنت).
- `script_outline <topic> [duration_min=8]` — هيكل سيناريو بتوقيتات فعلية
  محسوبة من مدة الفيديو (هوك أول 15 ثانية، عدد نقاط محسوب من الوقت المتاح).
- `hook_analyzer <hook text>` — تقييم قوة الهوك الافتتاحي /100 (طول، سؤال،
  رقم، كلمات فضول، مقدمات عامة مكرّرة).

### 3. خبير SEO ليوتيوب — `youtube_seo_plugin.py`
- `seo_title_score <title>` / `seo_description_score <text|path>` — تقييم
  حقيقي (طول مقابل حدود يوتيوب الفعلية، أول 150 حرف، توقيتات، هاشتاجات).
- `seo_tags_suggest <title.txt> <description.txt>` — استخراج كلمات مفتاحية
  بتحليل تكرار محلي (unigrams/bigrams، مش API خارجي).
- `seo_tags_audit <tags,...>` — تدقيق مقابل حد يوتيوب الفعلي (500 حرف)،
  كشف تكرار/شبه-تكرار (مفرد/جمع)، توازن عام/محدد.
- `seo_full_audit <title.txt> <description.txt> <tags>` — تقرير شامل موزون.

### 4. مصمم المصغرات — `thumbnail_plugin.py`
- `thumbnail_analyze <image>` — تحليل حقيقي عبر Pillow: سطوع، تباين
  (stddev)، تشبع لون، دقة/نسبة مقابل 1280x720، حجم الملف مقابل حد يوتيوب (2MB).
- `thumbnail_generate <bg> <title> <out.jpg>` — توليد فعلي: cover-fit لـ
  1280x720، حجم خط تلقائي يتصغّر لحد ما يتظبط، **لون نص تلقائي** (بيقيس
  سطوع منطقة النص فعليًا ويختار أبيض/أسود + stroke متباين).
- `thumbnail_ab_compare <a> <b>` — مقارنة A/B على نفس المقاييس.

### 5. أخصائي إعلانات يوتيوب — `youtube_ads_plugin.py`
**حاسبة واستشارة استراتيجية بس — مش متصلة بحساب Google Ads حقيقي ومش
بتنفّذ أي حملة فعلية أو تصرف فلوس.**
- `ads_budget_calc <daily_budget> <cpm>` — وصول/مشاهدات متوقعة (بمدى، مش
  رقم وهمي دقيق).
- `ads_targeting_advisor <niche> <goal>` — توصية استهداف حقيقية مبنية على
  أنواع استهداف Google Ads الفعلية (Affinity/In-market/Remarketing...).
- `ads_copy_score <headline> | <description>` — تقييم نص إعلاني (طول، CTA، إلحاح).
- `ads_campaign_plan <budget> <days> <goal>` — تقسيم ميزانية على قنوات
  إعلانية + توصية استراتيجية مزايدة.

### 6. مدير التواصل والمجتمع — `community_manager_plugin.py`
- `comment_sentiment <text|path>` — تحليل مشاعر بقاموس عربي مصري +
  إنجليزي، مع التعامل مع النفي ("مش حلو" = سلبي مش إيجابي).
- `comment_spam_detect <text|path>` — كشف سبام هيكلي (روابط، عبارات
  ترويجية معروفة، تكرار حروف).
- `reply_template <comment> tone=friendly|professional|funny` — رد مقترح
  حسب نوع التعليق (سؤال/مجاملة/شكوى) المكتشف تلقائيًا.
- `engagement_calendar <posts_per_week>` — خطة منشورات مجتمعية بدوران نوع
  المحتوى (استطلاع/سؤال/كواليس...).

### 7. محلل بيانات يوتيوب — `youtube_analytics_plugin.py`
- `video_stats <video_id>` — مشاهدات/لايك/تعليق/مدة حقيقية + معدل تفاعل.
- `channel_growth_report <channel>` — أفضل/أسوأ أداء واتجاه مشاهدات
  (مقارنة أقدم نص بأحدث نص من آخر الفيديوهات).
- `engagement_health_proxy <video_id>` — **مؤشر تقريبي بس**، مش retention/CTR
  حقيقي: الـ retention الحقيقي بيانات خاصة بصاحب القناة عبر YouTube
  Analytics API بمصادقة OAuth على حسابه — مش متاح عبر مفتاح API عام، والأداة
  بتقول كده صراحةً بدل ما تدّعي عكس ده.
- `report_export <channel> <out.csv>` — تصدير CSV حقيقي لإحصائيات الفيديوهات.

## طبيب بيئة العمل — `environment_plugin.py`

نيزوكو بتعتمد على عشرات الأدوات الخارجية ومكتبات بايثون الاختيارية
(FFmpeg، ClamAV، Ollama، Node.js، Docker، إلخ) عبر جلسة العمل كلها. بدل
ما تكتشف الناقص واحدة واحدة لما أمر يفشل، `env_check` بيفحصهم كلهم
مرة واحدة ويوريك بالظبط إيه المتاح وإيه لأ:

```
env_check                    # فحص شامل، مقسّم بالتصنيف، بأمر تثبيت مضبوط لنظامك
env_install <tool_key>       # تثبيت أداة واحدة (dry-run افتراضيًا)
env_install <tool_key> --yes # تثبيت فعلي (لمكتبات بايثون بس)
env_install_all --yes        # تثبيت كل مكتبات بايثون الناقصة دفعة واحدة
```

**قرار تصميم مقصود ومهم:** الأداة بتفرّق بوضوح بين نوعين:

- **مكتبات بايثون** (Pillow, pandas, capstone, edge-tts...) — دي فعلاً
  بتتثبت تلقائيًا (`pip install`) لما تكتب `--yes`، لأنها بتشتغل في
  مساحة المستخدم بدون أي صلاحيات مرتفعة — نفس فلسفة
  `pip install -r requirements.txt` الموجودة من الأول.
- **أدوات نظام** (FFmpeg, Docker, Node.js, ClamAV...) — دي **مبتتثبتش
  تلقائيًا أبدًا**، حتى مع `--yes`. الأداة بتوريك بس الأمر المضبوط
  لنظامك (`apt`/`dnf`/`pacman`/`brew`/`winget`/`choco`، مكتشف تلقائيًا)
  وانت اللي تنسخه وتشغّله. تشغيل `sudo` أو أي مثبّت نظام تلقائيًا من
  جوه تطبيق من غير علمك الصريح ثغرة صلاحيات حقيقية — مش راحة، بغض
  النظر عن نية الأداة.

Ollama حالة خاصة: مش قابلة للفحص بـ `shutil.which` (بتشتغل كسيرفر
محلي على `localhost:11434`)، فالفحص بيكون HTTP ping حقيقي، والتثبيت
دايمًا تعليمات يدوية (تنزيل من ollama.com) لأنه مش package management
عادي.

## ربط أي برنامج خارجي — `external_tools_plugin.py`

عايز تشغّل برنامج معين (CLI، سكربت بايثون/جافا/شل، أو حتى تطبيق سطح
مكتب) من جوه نيزوكو باسم قصير بدل ما تكتب المسار الكامل كل مرة؟

```
external_add myamr "/path/to/tool.exe {args}"     # {args} تتحدد مكانها بالظبط
external_add ffmpeg_custom "/usr/local/bin/myffmpeg"  # من غير {args} — الوسائط بتتضاف في الآخر تلقائيًا
external_add photoshop "open -a Photoshop" --type desktop   # تطبيق سطح مكتب — بيتشغّل في الخلفية

myamr -i input.txt -o output.txt   # بينفّذ فعليًا: /path/to/tool.exe -i input.txt -o output.txt

external_list       # كل الأدوات المسجّلة
external_remove myamr
```

الأداة بتتسجّل **دائمًا** (`external_tools.json`، مش متتبع في git) —
بتفضل شغالة بعد إعادة تشغيل نيزوكو من غير ما تسجّلها تاني. زي أمر
`run` المدمج بالظبط من ناحية الأمان (subprocess بدون shell=True) —
شرح كامل للفرق ونموذج الثقة في [`SECURITY.md`](SECURITY.md).

## تحكم في تطبيقات أندرويد — `android_plugin.py`

تحكم حقيقي عبر [ADB](https://developer.android.com/tools/releases/platform-tools)
(مجاني ومفتوح المصدر، جزء من Android SDK) — محتاج محاكي (زي Android
Studio Emulator) أو جهاز حقيقي متصل بـ USB debugging مفعّل:

```
android_devices                          # الأجهزة/المحاكيات المتصلة
android_install app.apk                  # تثبيت APK
android_launch com.example.app           # تشغيل تطبيق
android_shell pm list packages           # أي أمر adb shell مباشرة
android_shell input tap 500 800          # محاكاة لمسة
android_screenshot shot.png              # لقطة شاشة حقيقية
android_uninstall com.example.app
```

`android_shell` هو "نفّذ أي أمر" الحقيقي بتاع أندرويد — بيمرر أي
أمر تكتبه مباشرة لـ `adb shell`، يعني بتقدر تعمل أي حاجة adb نفسها
تقدر تعملها. تفاصيل كاملة عن حدود الصلاحية في [`SECURITY.md`](SECURITY.md).

**بصراحة عن iOS:** مفيش أداة مكافئة لـ ADB في نظام آبل — التحكم في
تطبيقات iOS محتاج Mac + Xcode فعليًا، وحتى مع كده بيشتغل بس مع
تطبيقات إنت عندك ملف الـ .app/.ipa بتاعها (مش أي تطبيق من App
Store). ده قيد منصة آبل نفسها مش حاجة نيزوكو تقدر تلتف حواليها —
الشرح الكامل في [`SECURITY.md`](SECURITY.md).

## ليه مفيش "توليد فيديو/صورة بالذكاء الاصطناعي" زي Higgsfield؟

بناء نموذج generative AI خاص ينافس منصات زي Higgsfield محتاج فرق بحث ML
وملايين الدولارات من موارد تدريب — مش حاجة ممكن تتبنى "مجاناً" في مشروع
زي ده. المرحلة الحالية بتركّز على اللي فعلاً ممكن يكون مجاني ومحلي 100%:
تحليل الميديا، تحرير/دمج عبر FFmpeg، واقتراحات تحسين عبر نموذج محلي
(Ollama). لو حبيت مرحلة تانية بموديل توليد صور/فيديو مفتوح المصدر شغال
محلياً (زي Stable Diffusion)، ده ممكن يتضاف كإضافة (plugin) جديدة — لكنه
هيحتاج GPU قوي ومساحة تخزين كبيرة على جهاز المستخدم.
