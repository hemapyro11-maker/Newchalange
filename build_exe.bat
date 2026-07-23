@echo off
echo ====================================
echo   Y99 Filter Bot - Build EXE
echo ====================================

:: تثبيت المتطلبات
py -m pip install playwright customtkinter pyinstaller --quiet

:: تثبيت المتصفح
py -m playwright install chromium

:: بناء الـ EXE
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "Y99FilterBot" ^
    --hidden-import customtkinter ^
    --hidden-import playwright ^
    --hidden-import bot_core ^
    --add-data "bot_core.py;." ^
    main_gui.py

echo.
echo ====================================
echo   تم البناء! الملف في مجلد dist
echo ====================================
pause
