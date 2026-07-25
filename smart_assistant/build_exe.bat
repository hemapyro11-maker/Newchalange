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
py -m pip install customtkinter pyinstaller mcp typer capstone Pillow pandas matplotlib edge-tts piper-tts sounddevice python-telegram-bot discord.py keyring --quiet

:: بناء الـ EXE
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "Nezuko" ^
    --hidden-import customtkinter ^
    --hidden-import core_engine ^
    --hidden-import i18n ^
    --hidden-import version ^
    --collect-all mcp ^
    --collect-all capstone ^
    --collect-all PIL ^
    --collect-all pandas ^
    --collect-all matplotlib ^
    --collect-all edge_tts ^
    --collect-all piper ^
    --collect-all onnxruntime ^
    --collect-all sounddevice ^
    --collect-all telegram ^
    --collect-all discord ^
    --collect-all keyring ^
    --add-data "core_engine.py;." ^
    --add-data "i18n.py;." ^
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
echo   - أمر speak (صوت نيزوكو) محتاج ffplay (جزء من FFmpeg، شوف فوق)
echo     عشان يشغّل الصوت. أفضل جودة (صوت مصري أنثوي حقيقي) محتاجة
echo     إنترنت وقت الاستخدام (edge-tts، مجاني بالكامل). من غير إنترنت،
echo     بيرجع لـ Piper (صوت عربي محلي، بيتحمّل مرة واحدة ~60MB) وبعدين
echo     espeak-ng (لازم يتثبت يدوي من espeak-ng.github.io، صوت روبوتي
echo     بس ضامن يشتغل offline بالكامل من غير أي تحميل).
echo   - أوامر listen/listen_run (استماع صوتي) محتاجة: pip install
echo     openai-whisper على جهاز المستخدم النهائي (بيوصّل أمر whisper،
echo     أول استخدام بيحمّل نموذجه مرة واحدة وبعدين offline بالكامل).
echo     sounddevice (تسجيل المايك) متضمّن في الـ exe نفسه أصلاً.
echo   - قناة تليجرام (telegram_set_token) محتاجة إنترنت وقت التشغيل
echo     (بوليينج عادي، مفيش سيرفر عام مطلوب). أول مستخدم يكلم البوت
echo     لازم يتوافق عليه من على الجهاز نفسه بـ telegram_approve
echo     <code> — التوافق ده بيدّي صلاحية كاملة زي القاعد على الجهاز.
echo   - قناة ديسكورد (discord_set_token) نفس فكرة تليجرام بالظبط
echo     (discord_approve <code>)، لكن لازم تفعّل 'Message Content
echo     Intent' من Discord Developer Portal وإلا الرسائل هتوصل فاضية.
echo ====================================
pause
