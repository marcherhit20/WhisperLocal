@echo off
rem Trascrizione da riga di comando su Windows: stesse opzioni di trascrivi.sh.
rem Aiuto: trascrivi.bat --help
setlocal
set PYTHONUTF8=1
"%~dp0.venv\Scripts\python.exe" "%~dp0trascrivi.py" %*
exit /b %errorlevel%
