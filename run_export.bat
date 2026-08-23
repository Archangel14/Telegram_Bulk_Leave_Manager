@echo off
echo Starting Export Chats...
cd /d "%~dp0"
call .\.venv\Scripts\activate.bat
python export_chats.py
echo.
pause
