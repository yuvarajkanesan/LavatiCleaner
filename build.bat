@echo off
rem Builds dist\LavatiCleaner\LavatiCleaner.exe and, when Inno Setup is installed, dist\LavatiCleaner-Setup.exe
rem Code signing: set SIGN_CERT_SHA1=<thumbprint> (or SIGN_PFX + SIGN_PFX_PASSWORD); see tools\sign.ps1.
rem Both the exe and the installer are then signed. Unset = unsigned local build.
setlocal
cd /d "%~dp0"
python -m pip install --quiet -r requirements.txt || goto :err
python -m unittest discover -s tests || goto :err
python -m PyInstaller --noconfirm --clean --windowed --name LavatiCleaner ^
  --icon assets\lavati.ico --version-file version_info.txt ^
  --add-data "rules;rules" --add-data "fonts;fonts" --add-data "assets;assets" ^
  --add-data "LICENSE.txt;." --add-data "THIRD_PARTY_NOTICES.txt;." --add-data "PRIVACY.md;." --add-data "SECURITY.md;." ^
  --exclude-module ssl --exclude-module _ssl --exclude-module _hashlib ^
  --exclude-module win32api --exclude-module win32con --exclude-module pywintypes --exclude-module win32com ^
  --exclude-module _decimal --exclude-module _lzma --exclude-module _bz2 --exclude-module _zstd ^
  --exclude-module pydoc --exclude-module doctest --exclude-module unittest ^
  main.py || goto :err
call :trim || goto :err
rem smoke-test the packaged exe (start /wait because it is a windowed app)
start /wait "" dist\LavatiCleaner\LavatiCleaner.exe --selftest
if errorlevel 1 (echo Packaged selftest FAILED & goto :err)
echo Packaged selftest OK
call :sign dist\LavatiCleaner\LavatiCleaner.exe || goto :err
echo.
echo Built: dist\LavatiCleaner\LavatiCleaner.exe

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if defined ISCC (
  "%ISCC%" installer.iss || goto :err
  call :sign dist\LavatiCleaner-Setup.exe || goto :err
  echo Installer: dist\LavatiCleaner-Setup.exe
  powershell -NoProfile -Command "Get-FileHash dist\LavatiCleaner-Setup.exe -Algorithm SHA256 | Format-List Hash"
) else (
  echo Inno Setup not found - skipping installer. Install it from https://jrsoftware.org/isdl.php and re-run.
)
exit /b 0

:trim
rem drop Tcl/Tk data the app never uses: translations, time zones and non-Western code pages
set I=dist\LavatiCleaner\_internal
rmdir /s /q "%I%\_tcl_data\msgs" "%I%\_tcl_data\tzdata" "%I%\_tk_data\msgs" 2>nul
powershell -NoProfile -Command "Get-ChildItem '%I%\_tcl_data\encoding\*.enc' | Where-Object { $_.BaseName -notin 'cp1252','cp1250','cp1251','cp437','cp850','iso8859-1','iso8859-15','ascii','unicode' } | Remove-Item"
exit /b 0

:sign
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\sign.ps1" %1
exit /b %errorlevel%

:err
echo Build failed.
exit /b 1
