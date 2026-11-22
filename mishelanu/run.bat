@echo off
rem Starts the Mishelanu site at http://localhost:5002 and opens it in the browser.
rem Close this window (or press Ctrl+C) to stop the site.
cd /d "%~dp0"
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:5002"
python app.py
pause
