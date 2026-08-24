@echo off
setlocal
echo ========================================
echo Telegram Bulk Leave Manager - Installer
echo ========================================
echo.
echo Please choose your installation preference:
echo [G] Global (Installs directly to your system Python)
echo [L] Local  (Creates an isolated .venv environment folder)
echo.
set /p choice="Enter G or L: "

if /i "%choice%"=="G" goto global
if /i "%choice%"=="L" goto local

echo.
echo Invalid choice. Exiting.
pause
exit /b

:global
echo.
echo Installing dependencies globally...
python -m pip install -r components\requirements.txt
if errorlevel 1 (
    echo Error during installation! Please check if Python is added to PATH.
    pause
    exit /b
)
echo.
echo Creating Global Launcher...
(
echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
echo currentDir = fso.GetParentFolderName^(WScript.ScriptFullName^)
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = currentDir ^& "\components"
echo WshShell.Run "cmd /c pythonw telegram_manager_app.py", 0, False
) > "Launch App.vbs"
goto finish

:local
echo.
echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo Error creating virtual environment! Please ensure Python is installed.
    pause
    exit /b
)
echo Installing dependencies locally...
call .\.venv\Scripts\activate.bat
python -m pip install -r components\requirements.txt
if errorlevel 1 (
    echo Error during installation!
    pause
    exit /b
)
echo.
echo Creating Local Launcher...
(
echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
echo currentDir = fso.GetParentFolderName^(WScript.ScriptFullName^)
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = currentDir ^& "\components"
echo WshShell.Run "cmd /c ..\.venv\Scripts\pythonw.exe telegram_manager_app.py", 0, False
) > "Launch App.vbs"
goto finish

:finish
echo.
echo ========================================
echo Installation Complete!
echo You can now double-click "Launch App.vbs" to start the application.
echo ========================================
pause
