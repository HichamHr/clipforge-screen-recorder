@echo off
setlocal
cd /d "%~dp0"
echo Screen Recorder - Build a standalone Windows EXE
echo Only the build computer needs Python and internet.
echo.
if exist ".build-venv\Scripts\python.exe" goto dependencies
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 -m venv .build-venv
if errorlevel 1 goto failed
goto dependencies
:usepython
where python >nul 2>nul
if errorlevel 1 goto missing
python -m venv .build-venv
if errorlevel 1 goto failed
:dependencies
".build-venv\Scripts\python.exe" -c "import sys, struct, tkinter; assert sys.platform == 'win32' and struct.calcsize('P') == 8 and sys.version_info >= (3,10), 'Use 64-bit Python 3.10 or newer on Windows'"
if errorlevel 1 goto failed
echo Installing build components...
".build-venv\Scripts\python.exe" -m pip install --only-binary=:all: -r build-requirements.txt
if errorlevel 1 goto failed
echo.
echo Building ScreenRecorder.exe - this may take several minutes...
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --name ScreenRecorder --collect-all imageio_ffmpeg --collect-all pyaudiowpatch --copy-metadata imageio-ffmpeg --copy-metadata PyAudioWPatch screen_recorder.py
if errorlevel 1 goto failed
if not exist "dist\ScreenRecorder.exe" goto failed
echo.
echo SUCCESS: dist\ScreenRecorder.exe
echo Share that EXE. Recipients do not need Python or FFmpeg installed.
echo Test recording, audio, saving and recovery on Windows before sharing.
start "" explorer.exe "%CD%\dist"
pause
exit /b 0
:missing
echo Install 64-bit Python from https://www.python.org/downloads/windows/
echo Enable Add Python to PATH, then run Build EXE.bat again.
pause
exit /b 1
:failed
echo.
echo Build failed. Read the error above; no working EXE has been confirmed.
echo Close any running ScreenRecorder.exe before rebuilding.
echo Build on Windows using 64-bit Python with Tcl/Tk and pip enabled.
pause
exit /b 1
