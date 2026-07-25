@echo off
echo ====================================
echo   Nezuko (Smart Assistant) - Build EXE
echo ====================================

:: تثبيت المتطلبات
:: ملحوظة: typer مش مستخدم فعليًا في نيزوكو نفسه — لكن --collect-all mcp
:: تحت بيحاول يمسح كل sub-modules بتاعة mcp، وده بيشمل mcp.cli اللي
:: بيعمل import لـ typer وقت الفحص بس (مش وقت التشغيل الفعلي). من غيره
:: البناء بالكامل بيفشل بـ "ModuleNotFoundError: No module named 'typer'"
:: حتى لو الميزة دي (mcp.cli) نيزوكو نفسه ماستخدمهاش أبدًا.
:: sounddevice: نيزوكو بيعمل import ليها فعليًا (voice_plugin.py، لتسجيل
:: المايك لأمر listen) فمحتاجة تكون في بيئة البناء وتتجمع بـ collect-all
:: تحت (بتحمل PortAudio كملف native جواها، زي ما customtkinter محتاج
:: ملفات theme JSON تتجمع معاها). openai-whisper (أمر whisper CLI،
:: لتفريغ الصوت لنص) عن قصد **مش** هنا ولا في collect-all: نيزوكو
:: بيناديها عن طريق subprocess بس (زي ffmpeg/ClamAV/espeak-ng بالظبط)
:: من غير أي import مباشر ليها، فمحتاجة تتثبت على جهاز المستخدم النهائي
:: بس (pip install openai-whisper) مش جوه الـ exe نفسه — وبما إنها حزمة
:: تقيلة (torch وغيرها)، ضمها بـ collect-all كان هيزود حجم/وقت البناء
:: من غير أي فايدة حقيقية، وممكن كمان يكرر مشكلة mcp.cli اللي فوق مع
:: أي submodule اختياري تاني جواها.
:: python-telegram-bot: نيزوكو بيعمل import ليها فعليًا (telegram_plugin.py)
:: لو حابب قناة تليجرام تشتغل — اسم الحزمة على pip مختلف عن اسم الـ
:: import (زي Pillow/PIL بالظبط): بتتثبت بـ python-telegram-bot، وبيتجمع
:: بـ --collect-all telegram.
:: discord.py: نفس الفكرة بالظبط لقناة ديسكورد (discord_plugin.py) —
:: اسم الحزمة discord.py، اسم الـ import discord.
:: keyring: تخزين آمن لتوكنات تليجرام/ديسكورد ومفتاح YouTube API عبر
:: مخزن أسرار نظام التشغيل. بيكتشف backend المنصة (Windows/macOS/Linux
:: Secret Service) وقت التشغيل عبر entry points، فمحتاج --collect-all
:: عشان الميتاداتا دي تتجمع صح — اتجرب فعليًا (onefile Linux مبني بنفس
:: الفلاج ده اشتغل وكشف حالة الـ backend صح من غير أي crash).
:: faster-whisper: أول محاولة تفريغ صوتي (STT) للأمر listen — نيزوكو
:: بيعمل import ليها فعليًا (voice_plugin.py) فمحتاجة collect-all زيها
:: زي sounddevice. بتجيب معاها ctranslate2 (حزمة compiled تقيلة) —
:: اتجرب فعليًا (onefile Linux بنفس الفلاج ده بنى واشتغل من غير أي
:: crash، بعكس مخاوفنا الأولانية من نفس مشكلة mcp.cli).
:: vosk: الضمانة الأخيرة لتفريغ الصوت، خفيفة وبتتجمع بنفس الأمان
:: (اتجرب فعليًا في نفس البناء اللي فوق). النموذج نفسه (~40-50MB)
:: **مش** بيتحمّل هنا ولا يتضم في الـ exe — لازم المستخدم يحمّله يدويًا
:: (شوف الملاحظات تحت) لأنه مفيش نموذج قياسي واحد نقدر نحطه هنا.
:: openai-whisper لسه عن قصد **مش** هنا زي ما هو موضح فوق — بيتنادى
:: بس عن طريق subprocess (أمر whisper CLI)، مش import مباشر.
:: CTkToolTip: تلميحات (tooltips) لأزرار main_gui.py — تحسين واجهة
:: اختياري بمكتبة خفيفة جدًا (مفيش أي dependencies ليها) من غير أي
:: مخاطرة حقيقية. مختلفة عن باقي الحزم فوق في حاجة واحدة: main_gui.py
:: بيعمل لها import اختياري (try/except) مش إجباري زي customtkinter
:: نفسها — لو مش موجودة، الواجهة تشتغل عادي من غير تلميحات بس. اتجرب
:: فعليًا (onefile Linux بنفس الفلاج ده بنى واشتغل من غير أي crash).
:: scenedetect: كشف تلقائي لتغييرات المشاهد (detect_scenes في
:: cinema_plugin.py) — نيزوكو بيعمل import ليها فعليًا (زي
:: faster-whisper بالظبط)، فمحتاجة collect-all. بتجيب معاها
:: opencv-python (حزمة كبيرة الحجم لكنها مستقرة ومعروفة) — اتجرب
:: فعليًا (onefile Linux بنفس الفلاج ده بنى واشتغل من غير أي crash).
::
:: ═══════════════════════════════════════════════════════════════
:: ملحوظة معمارية مهمة: pyannote.audio و TTS (Coqui) عن قصد **مش**
:: هنا ولا في collect-all تحت، رغم إن diarize/clone_voice في
:: voice_plugin.py بيعملوا لهم import مباشر (مش subprocess). السبب:
:: الحزمتين دول بيجيبوا معاهم PyTorch كامل + عشرات الحزم الفرعية
:: (torchaudio, pytorch-lightning, transformers, إلخ) — تقيلين
:: بمراحل عن faster-whisper (اللي مبني على CTranslate2 الأخف عمداً)
:: أو حتى opencv بتاعة scenedetect فوق. ضمهم هيزود حجم/وقت البناء
:: بشكل كبير جداً لميزتين متقدمتين (diarize محتاج توكن Hugging
:: Face + موافقة يدوية على نموذج gated، clone_voice محتاج موافقة
:: على ترخيص CPML + تحميل نموذج ~2GB) اللي غالبية المستخدمين مش
:: هيستخدموها أصلاً. النتيجة العملية: diarize/clone_voice بيشتغلوا
:: بس لو نيزوكو شغّال من السورس (python main_gui.py) مع تثبيت
:: pyannote.audio/TTS يدويًا في نفس بيئة بايثون — مش متاحين في
:: Nezuko.exe الجاهز. ده قيد معماري صريح ومقصود، مش نسيان.
:: ═══════════════════════════════════════════════════════════════
py -m pip install customtkinter CTkToolTip pyinstaller mcp typer capstone Pillow pandas matplotlib edge-tts piper-tts sounddevice faster-whisper vosk scenedetect[opencv] python-telegram-bot discord.py keyring --quiet

:: بناء الـ EXE
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "Nezuko" ^
    --hidden-import customtkinter ^
    --hidden-import core_engine ^
    --hidden-import i18n ^
    --hidden-import version ^
    --hidden-import brain ^
    --hidden-import intents ^
    --collect-all CTkToolTip ^
    --collect-all mcp ^
    --collect-all capstone ^
    --collect-all PIL ^
    --collect-all pandas ^
    --collect-all matplotlib ^
    --collect-all edge_tts ^
    --collect-all piper ^
    --collect-all onnxruntime ^
    --collect-all sounddevice ^
    --collect-all faster_whisper ^
    --collect-all vosk ^
    --collect-all scenedetect ^
    --collect-all telegram ^
    --collect-all discord ^
    --collect-all keyring ^
    --add-data "core_engine.py;." ^
    --add-data "i18n.py;." ^
    --add-data "brain.py;." ^
    --add-data "intents.py;." ^
    --add-data "version.py;." ^
    --add-data "version.json;." ^
    --add-data "connectors.example.json;." ^
    --add-data "plugins;plugins" ^
    main_gui.py

echo.
echo ====================================
echo   تم البناء! الملف في مجلد dist\Nezuko.exe
echo   ملحوظات:
echo   - أوامر الميديا (probe/convert/trim/...) محتاجة FFmpeg
echo     متثبت على الجهاز ومضاف للـ PATH: https://ffmpeg.org/download.html
echo   - الـ Connectors (MCP) اللي بتحتاج npx/uvx محتاجة Node.js أو uv
echo     متثبتين على الجهاز حسب الـ connector المستخدم.
echo   - مشاريع scaffold android محتاجة Android Studio لفتحها/بنائها،
echo     ومشاريع scaffold ios محتاجة Xcode على ماك.
echo   - مشاريع scaffold kernel_module محتاجة kernel headers مثبتة،
echo     و scaffold blockchain محتاجة Node.js+Hardhat، و scaffold
echo     quantum/ml محتاجة pip install قدام المشروع نفسه (requirements.txt
echo     بتاعه) مش داخل SmartAssistant نفسه.
echo   - virus_scan محتاج ClamAV متثبت على الجهاز (مجاني ومفتوح المصدر):
echo     https://www.clamav.org/downloads — شغّل freshclam بعد التثبيت.
echo   - vuln_scan بيستخدم pip-audit (اختياري: pip install pip-audit) و
echo     npm audit (لو Node.js متثبت) لفحص ثغرات المكتبات المعروفة —
echo     من غيرهم بيفحص الأسرار المكشوفة وصلاحيات الملفات بس.
echo   - code_scan بيستخدم bandit (اختياري: pip install bandit) كفحص
echo     إضافي فوق تحليل AST الأساسي بتاعنا — من غيره بيفضل يشتغل
echo     بالفحص الأساسي بس.
echo   - أمر speak (صوت نيزوكو) محتاج ffplay (جزء من FFmpeg، شوف فوق)
echo     عشان يشغّل الصوت. أفضل جودة (صوت مصري أنثوي حقيقي) محتاجة
echo     إنترنت وقت الاستخدام (edge-tts، مجاني بالكامل). من غير إنترنت،
echo     بيرجع لـ Piper (صوت عربي محلي، بيتحمّل مرة واحدة ~60MB) وبعدين
echo     espeak-ng (لازم يتثبت يدوي من espeak-ng.github.io، صوت روبوتي
echo     بس ضامن يشتغل offline بالكامل من غير أي تحميل).
echo   - أوامر listen/listen_run (استماع صوتي): sounddevice + faster-whisper
echo     + Vosk متضمّنين في الـ exe نفسه أصلاً (أول استخدام لـ
echo     faster-whisper بيحمّل نموذجه مرة واحدة، وبعدين offline بالكامل).
echo     Vosk محتاج تحميل نموذج يدوي في voice_cache\vosk-model\ من
echo     alphacephei.com/vosk/models (أو مسار NEZUKO_VOSK_MODEL) —
echo     الضمانة الأخيرة لو مفيش إنترنت وقت أول استخدام لـ faster-whisper.
echo     whisper CLI (pip install openai-whisper) احتياطي اختياري تالت.
echo   - قناة تليجرام (telegram_set_token) محتاجة إنترنت وقت التشغيل
echo     (بوليينج عادي، مفيش سيرفر عام مطلوب). أول مستخدم يكلم البوت
echo     لازم يتوافق عليه من على الجهاز نفسه بـ telegram_approve
echo     <code> — التوافق ده بيدّي صلاحية كاملة زي القاعد على الجهاز.
echo   - قناة ديسكورد (discord_set_token) نفس فكرة تليجرام بالظبط
echo     (discord_approve <code>)، لكن لازم تفعّل 'Message Content
echo     Intent' من Discord Developer Portal وإلا الرسائل هتوصل فاضية.
echo   - auto_trim_silence محتاج auto-editor (اختياري: pip install
echo     auto-editor) — قص صمت تلقائي من فيديو/بودكاست.
echo   - detect_scenes متضمّن في الـ exe نفسه أصلاً (scenedetect، شوف فوق).
echo   - upscale_image/upscale_video محتاجين realesrgan-ncnn-vulkan (ملف
echo     تنفيذي جاهز، مش pip): https://github.com/xinntao/Real-ESRGAN/releases
echo     — حطه في PATH. بطيء جدًا من غير GPU حقيقي بيدعم Vulkan.
echo   - separate_vocals محتاج demucs (اختياري: pip install demucs) —
echo     أول استخدام بيحمّل نموذجه (~80MB).
echo   - diarize محتاج pyannote.audio (pip install pyannote.audio، شغّال
echo     من السورس بس — شوف الملحوظة المعمارية فوق) + توكن Hugging Face
echo     مجاني (diarize_set_token) + موافقة يدوية لمرة واحدة على نموذج
echo     gated (diarize_key_status بيوريك الروابط).
echo   - clone_voice محتاج TTS/Coqui (pip install TTS، شغّال من السورس
echo     بس) + موافقة صريحة على ترخيص CPML (clone_voice_agree_license)
echo     + تحميل نموذج XTTS-v2 (~2GB) عند أول استخدام. استخدمه لصوتك
echo     إنت أو صوت عندك إذن صريح تستنسخه بس.
echo ====================================
pause
