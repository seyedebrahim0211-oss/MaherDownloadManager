@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1 || (echo Python 3.12 must be installed. & pause & exit /b 1)
py -3.12 -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements-build.txt || exit /b 1
python -m unittest discover -s tests -v || exit /b 1
if not exist assets\bin mkdir assets\bin
where deno >nul 2>&1 && for /f "delims=" %%D in ('where deno') do (copy /y "%%D" assets\bin\deno.exe >nul & goto :deno_copied)
:deno_copied
pyinstaller --noconfirm --clean --onedir --windowed --name MaherDownloader --icon assets\maher.ico --add-data "assets;assets" --collect-all yt_dlp --collect-all yt_dlp_ejs --collect-all imageio_ffmpeg --collect-all tkinterdnd2 app.py || exit /b 1
echo Built: dist\MaherDownloader\MaherDownloader.exe
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
 "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer\MaherDownloader.iss
) else (
 echo Inno Setup 6 required to build Setup EXE: https://jrsoftware.org/isdl.php
)
pause
