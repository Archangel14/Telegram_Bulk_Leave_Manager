@echo off
echo Starting Telegram Bulk Leave Manager GUI...
cd /d "%~dp0"
call .\.venv\Scripts\activate.bat
python telegram_manager_app.py
pause
