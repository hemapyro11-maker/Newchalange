@echo off
echo ====================================
echo   Smart Assistant - Build EXE
echo ====================================

:: تثبيت المتطلبات
py -m pip install customtkinter pyinstaller mcp capstone --quiet

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
echo ====================================
pause
