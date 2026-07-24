@echo off
echo ====================================
echo   Smart Assistant - Build EXE
echo ====================================

:: تثبيت المتطلبات
py -m pip install customtkinter pyinstaller mcp capstone Pillow pandas matplotlib --quiet

:: بناء الـ EXE
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "SmartAssistant" ^
    --hidden-import customtkinter ^
    --hidden-import core_engine ^
    --hidden-import i18n ^
    --hidden-import version ^
    --collect-all mcp ^
    --collect-all capstone ^
    --collect-all PIL ^
    --collect-all pandas ^
    --collect-all matplotlib ^
    --add-data "core_engine.py;." ^
    --add-data "i18n.py;." ^
    --add-data "version.py;." ^
    --add-data "version.json;." ^
    --add-data "connectors.example.json;." ^
    --add-data "plugins;plugins" ^
    main_gui.py

echo.
echo ====================================
echo   تم البناء! الملف في مجلد dist\SmartAssistant.exe
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
echo ====================================
pause
