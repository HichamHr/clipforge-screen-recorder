@echo off
setlocal
title ClipForge
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto installed
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 -m venv .venv
if errorlevel 1 goto failed
goto installed
:usepython
where python >nul 2>nul
if errorlevel 1 goto missing
python -m venv .venv
if errorlevel 1 goto failed
:installed
".venv\Scripts\python.exe" -c "from importlib.metadata import version; assert version('imageio-ffmpeg') == '0.6.0' and version('PyAudioWPatch') == '0.2.12.9'" >nul 2>nul
if not errorlevel 1 goto run
echo Setting up screen recording and audio support...
echo This first-time setup needs internet access.
".venv\Scripts\python.exe" -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 goto failed
:run
".venv\Scripts\python.exe" screen_recorder.py
if errorlevel 1 goto failed
exit /b 0
:missing
echo Install 64-bit Python 3.10 or newer from https://www.python.org/downloads/windows/
echo Enable 'Add Python to PATH', then open this launcher again.
pause
exit /b 1
:failed
echo Setup or recording failed. Check the message above.
echo Use 64-bit Python on Windows 10/11. Python must include Tcl/Tk and pip.
echo Check internet access if setup failed. See READ_ME.txt for help.
pause
exit /b 1
