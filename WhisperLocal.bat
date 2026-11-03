@echo off
rem Doppio clic: apre l'interfaccia di WhisperLocal nel browser (http://127.0.0.1:8765).
rem Lascia aperta questa finestra mentre la usi: chiudendola si ferma tutto,
rem compresa un'eventuale trascrizione in corso.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo WhisperLocal non e' ancora installato: esegui prima installa.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" interfaccia.py %*
if errorlevel 1 pause
