@echo off
echo ====================================
echo   Smart Assistant - Build EXE
echo ====================================

:: تثبيت المتطلبات
py -m pip install customtkinter pyinstaller --quiet

:: بناء الـ EXE
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "SmartAssistant" ^
    --hidden-import customtkinter ^
    --hidden-import core_engine ^
    --hidden-import i18n ^
    --add-data "core_engine.py;." ^
    --add-data "i18n.py;." ^
    main_gui.py

echo.
echo ====================================
echo   تم البناء! الملف في مجلد dist\SmartAssistant.exe
echo ====================================
pause
