@echo off
echo Starting Leave Chats...
cd /d "%~dp0"
call .\.venv\Scripts\activate.bat
python leave_chats.py
echo.
pause
