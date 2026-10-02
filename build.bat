@echo off
REM Gera:  dist\Portinho-Setup-<versao>.exe  (instalador)  e  dist\Portinho.exe  (portatil)
REM Requer Python 3.11+ (python.org). O instalador requer Inno Setup 6 (jrsoftware.org).
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv || goto :erro
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :erro
for /f %%v in ('python -c "import portinho; print(portinho.__version__)"') do set VERSION=%%v
set QT_QPA_PLATFORM=offscreen
python packaging\make_icon.py || goto :erro
set QT_QPA_PLATFORM=

REM Deno: necessario para o yt-dlp abrir os videos do YouTube
if not exist build\deno\deno.exe (
    mkdir build\deno 2>nul
    powershell -NoProfile -Command "Invoke-WebRequest https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip -OutFile build\deno\deno.zip; Expand-Archive build\deno\deno.zip -DestinationPath build\deno -Force; Remove-Item build\deno\deno.zip" || goto :erro
)

set COMMON=--noconfirm --windowed --icon assets\icon.ico --add-data "assets;assets" --add-binary "build\deno\deno.exe;." --collect-all imageio_ffmpeg --collect-all yt_dlp_ejs --collect-submodules yt_dlp

REM 1) pasta para o instalador
pyinstaller %COMMON% --onedir --name Portinho run.py || goto :erro
REM 2) .exe unico portatil
pyinstaller %COMMON% --onefile --name Portinho --distpath dist\portatil run.py || goto :erro
move /y dist\portatil\Portinho.exe dist\Portinho.exe >nul
rmdir /s /q dist\portatil

set ISCC=
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe") do if exist %%P set ISCC=%%P
if defined ISCC (
    %ISCC% /Q /DMyVersion=%VERSION% packaging\installer.iss || goto :erro
) else (
    echo.
    echo Inno Setup nao encontrado: so o Portinho.exe portatil foi gerado.
    echo Para o instalador, instale o Inno Setup 6 e rode de novo.
)

echo.
echo Pronto:
dir /b dist\*.exe
pause
exit /b 0

:erro
echo.
echo Falhou a compilacao.
pause
exit /b 1
