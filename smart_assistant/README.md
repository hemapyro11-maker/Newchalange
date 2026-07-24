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
  - `scaffold_plugin.py` — سقالات مشاريع جاهزة: ويب/أندرويد/iOS/لعبة
    Pygame/بايثون (`scaffold <type> <name>`).
  - `design_plugin.py` — لوجو بسيط وتوليد كل أحجام أيقونات iOS/Android
    من صورة واحدة (`make_logo`, `app_icons`) عبر Pillow.
  - `security_plugin.py` — `hash_file` (تحقق سلامة) و`port_scan` (فحص
    منافذ محلي بنطاق محدود، لأجهزتك المصرح لك باختبارها بس).
  - `plugin_forge_plugin.py` — المساعد يصمم plugins جديدة بنفسه ويصلح
    أخطاءها تلقائياً (شرح تفصيلي تحت).
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

128 اختبار حقيقي (مش placeholders) بتغطي كل plugin و Core Engine —
تحليل ELF/PE حقيقي، معالجة فيديو حقيقية عبر FFmpeg، توليد أيقونات
حقيقي، حلقة توليد/تصحيح plugin_forge كاملة، إلخ. الاختبارات اللي
محتاجة أدوات اختيارية (FFmpeg, Pillow, capstone, mcp) بتتخطى تلقائياً
(`SKIPPED`) لو الأداة مش متثبتة، بدل ما تفشل — جرّبتها في البيئتين
(بالأداة وبدونها) والنتيجة صح في الحالتين.

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

## تطوير متعدد المجالات (iOS / Android / Web / ألعاب / تصميم / أمان)

المساعد بقى فيه أدوات حقيقية شغالة عبر مجالات تطوير مختلفة، كلها
مبنية على أدوات مجانية 100%:

| المجال | الأمر | الحالة |
|---|---|---|
| Website Developer | `scaffold web <name>` | ✅ HTML/CSS/JS شغال فوراً |
| Android Developer | `scaffold android <name>` | ✅ سقالة Kotlin/Gradle — افتحها في Android Studio (مجاني) |
| iOS Developer | `scaffold ios <name>` | ✅ سقالة SwiftUI — محتاجة Xcode على ماك (قيد النظام، مش تكلفة) |
| Gaming Developer | `scaffold game <name>` | ✅ لعبة Pygame **شغالة فعلياً** — اتجرب وشغلت نافذة حقيقية |
| Coding Developer | `scaffold python <name>` + `run` + `git` عبره | ✅ |
| Video Editor | `media_plugin`: `trim/merge_av/concat/extract_audio/thumbnail/overlay_text` | ✅ كله اتجرب على فيديو حقيقي |
| Logo Designer | `make_logo <text> <output.png>` | ✅ لوجو حروف أولى فوري |
| App Designer | `app_icons <source.png> <out_dir>` | ✅ يولّد كل أحجام أيقونات iOS+Android (19 حجم) من صورة واحدة |
| Security Developer | `hash_file`, `port_scan`, + `re_plugin`/`inspect_plugin` | ✅ |

**ملحوظة مهمة عن iOS/Android:** التطبيق بيولّد الكود والسقالة، لكن
البناء الفعلي لـ .ipa/.apk محتاج Xcode (ماك بس) أو Android Studio —
دي قيود المنصات نفسها (Apple/Google) مش حاجة المشروع فارض تكلفة عليها؛
الأدوات دي مجانية للتنزيل لكنها محتاجة نظام تشغيل/بيئة معينة.

## ليه مفيش "توليد فيديو/صورة بالذكاء الاصطناعي" زي Higgsfield؟

بناء نموذج generative AI خاص ينافس منصات زي Higgsfield محتاج فرق بحث ML
وملايين الدولارات من موارد تدريب — مش حاجة ممكن تتبنى "مجاناً" في مشروع
زي ده. المرحلة الحالية بتركّز على اللي فعلاً ممكن يكون مجاني ومحلي 100%:
تحليل الميديا، تحرير/دمج عبر FFmpeg، واقتراحات تحسين عبر نموذج محلي
(Ollama). لو حبيت مرحلة تانية بموديل توليد صور/فيديو مفتوح المصدر شغال
محلياً (زي Stable Diffusion)، ده ممكن يتضاف كإضافة (plugin) جديدة — لكنه
هيحتاج GPU قوي ومساحة تخزين كبيرة على جهاز المستخدم.
