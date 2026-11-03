@echo off
rem WhisperLocal - installazione su Windows (non servono i diritti di amministratore).
rem Crea l'ambiente Python in .venv e installa le versioni di requirements.txt.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

rem Python 3.11: prima il launcher "py", poi un "python" nel PATH se e' proprio la 3.11
set "PYBASE=py -3.11"
%PYBASE% -c "import sys" >nul 2>nul
if not errorlevel 1 goto python_ok
set "PYBASE=python"
python -c "import sys; sys.exit(sys.version_info[:2] != (3, 11))" >nul 2>nul
if errorlevel 1 goto senza_python
:python_ok

if not exist ".venv\Scripts\python.exe" (
  echo Creo l'ambiente Python in .venv ...
  %PYBASE% -m venv .venv
  if errorlevel 1 goto errore
)
echo Installo i pacchetti: alcuni GB, puo' richiedere diversi minuti ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto errore
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto errore

set "PATH=%~dp0strumenti\ffmpeg\bin;%PATH%"
where ffmpeg >nul 2>nul
if errorlevel 1 goto senza_ffmpeg
where ffprobe >nul 2>nul
if errorlevel 1 goto senza_ffmpeg

echo.
echo Installazione completata.
echo Ultimo passo, una volta sola e con internet: scarica i modelli con
echo   .venv\Scripts\python.exe prepara_modelli.py --online
echo Poi avvia WhisperLocal con un doppio clic su WhisperLocal.bat
if not defined WHISPERLOCAL_SENZA_PAUSA pause
exit /b 0

:senza_python
echo Python 3.11 non trovato. Versioni presenti:
py -0 2>nul
echo.
echo WhisperLocal richiede la 3.11 (la 3.14 non e' supportata da WhisperX). Non serve
echo togliere le altre versioni: aggiungi la 3.11 da
echo   https://www.python.org/downloads/release/python-3119/  (Windows installer 64-bit,
echo   Customize installation, togli "for all users": niente diritti di amministratore)
echo oppure: winget install Python.Python.3.11 --scope user
echo poi rilancia installa.bat.
if not defined WHISPERLOCAL_SENZA_PAUSA pause
exit /b 1

:senza_ffmpeg
echo.
echo Pacchetti installati, ma ffmpeg/ffprobe non sono stati trovati.
echo Scarica
echo   https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
echo estrai lo zip (tasto destro, Estrai tutto) e rinomina la cartella in modo da avere:
echo   %~dp0strumenti\ffmpeg\bin\ffmpeg.exe
echo   %~dp0strumenti\ffmpeg\bin\ffprobe.exe
echo Poi rilancia installa.bat.
if not defined WHISPERLOCAL_SENZA_PAUSA pause
exit /b 1

:errore
echo.
echo Installazione non riuscita: leggi i messaggi qui sopra.
echo Su una rete aziendale pip puo' richiedere il proxy: chiedi all'IT l'indirizzo e usa
echo   set HTTPS_PROXY=http://indirizzo:porta
echo prima di rilanciare installa.bat dalla stessa finestra.
if not defined WHISPERLOCAL_SENZA_PAUSA pause
exit /b 1
