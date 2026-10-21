@echo off
setlocal
cd /d "%~dp0"
set "CLIPFORGE_ISCC="
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "CLIPFORGE_ISCC=%%I"
if not defined CLIPFORGE_ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "CLIPFORGE_ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined CLIPFORGE_ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "CLIPFORGE_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined CLIPFORGE_ISCC goto missing
call "Build EXE.bat"
if errorlevel 1 exit /b 1
for /f "delims=" %%V in ('.build-venv\Scripts\python.exe -c "import screen_recorder; print(screen_recorder.APP_VERSION)"') do set "CLIPFORGE_VERSION=%%V"
if not defined CLIPFORGE_VERSION exit /b 1
"%CLIPFORGE_ISCC%" /DAppVersion=%CLIPFORGE_VERSION% installer\ClipForge.iss
if errorlevel 1 exit /b 1
echo Installer ready in dist\installer
pause
exit /b 0
:missing
echo Install Inno Setup 6 from https://jrsoftware.org/isinfo.php then run this again.
pause
exit /b 1
