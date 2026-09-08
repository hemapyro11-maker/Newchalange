@echo off
py "%~dp0cli.py" --coding-only %*
exit /b %errorlevel%
