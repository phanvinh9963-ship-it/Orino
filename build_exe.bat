@echo off
REM ============================================================
REM  build_exe.bat
REM  Dong goi Reup Studio (main.py) thanh 1 thu muc .exe chay
REM  duoc tren may khac KHONG can cai Python/pip gi ca.
REM
REM  CACH DUNG:
REM   1. Dat file nay vao thu muc G:\reup-studio\ (cung cap voi main.py)
REM   2. Dat file requirements_full.txt cung thu muc
REM   3. Chay: build_exe.bat
REM   4. Cho chay xong (co the mat 5-15 phut lan dau vi tai + build).
REM   5. Ket qua nam trong thu muc: dist\ReupStudio\
REM ============================================================

setlocal

echo ==========================================================
echo   Buoc 1/4: Tao moi truong build rieng (venv_build)
echo ==========================================================
if exist venv_build (
    echo   venv_build da ton tai, bo qua buoc tao moi.
) else (
    py -3.12 -m venv venv_build
    if errorlevel 1 (
        echo LOI: Khong tao duoc venv. Kiem tra da cai Python 3.12 chua ^(py -3.12^).
        pause
        exit /b 1
    )
)

call venv_build\Scripts\activate.bat

echo.
echo ==========================================================
echo   Buoc 2/4: Cai dat toan bo thu vien tu requirements_full.txt
echo ==========================================================
python -m pip install --upgrade pip
pip install -r requirements_full.txt
if errorlevel 1 (
    echo LOI: Cai thu vien that bai. Xem log ben tren.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   Buoc 3/4: Dong goi bang PyInstaller
echo ==========================================================
REM --onedir: xuat ra 1 thu muc (khoi dong nhanh hon --onefile, de debug hon).
REM --collect-all: dam bao lay du binary/DLL cua cac goi native-heavy.
pyinstaller main.py ^
  --name ReupStudio ^
  --noconsole ^
  --onedir ^
  --noconfirm ^
  --add-data "core;core" ^
  --collect-all customtkinter ^
  --collect-all ttkbootstrap ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all onnxruntime ^
  --collect-all av ^
  --collect-all tokenizers ^
  --collect-all huggingface_hub ^
  --collect-all yt_dlp ^
  --collect-all google_auth_oauthlib ^
  --collect-all googleapiclient ^
  --collect-all google_auth_httplib2 ^
  --collect-all PIL ^
  --hidden-import google.auth ^
  --hidden-import google.auth.transport.requests ^
  --hidden-import google.oauth2.credentials

if errorlevel 1 (
    echo LOI: PyInstaller build that bai. Xem log ben tren de biet thieu module gi.
    echo Meo: neu bao "ModuleNotFoundError: X" khi CHAY thu file exe, quay lai them:
    echo      --hidden-import X   vao lenh pyinstaller o tren roi build lai.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   Buoc 4/4: Copy them cac thu muc/tai nguyen khong phai code Python
echo ==========================================================
if exist ffmpeg (
    echo   Copy ffmpeg...
    xcopy /E /I /Y ffmpeg dist\ReupStudio\ffmpeg >nul
)
if exist model_cache (
    echo   Copy model_cache...
    xcopy /E /I /Y model_cache dist\ReupStudio\model_cache >nul
)
if exist TiktokAuto (
    echo   Copy TiktokAuto ^(kem Python 3.12 rieng neu da chay setup_embedded_python312.bat^)...
    xcopy /E /I /Y TiktokAuto dist\ReupStudio\TiktokAuto >nul
)

call venv_build\Scripts\deactivate.bat

echo.
echo ==========================================================
echo   XONG! Ket qua nam trong: dist\ReupStudio\
echo   Nen thu muc "ReupStudio" thanh .zip roi gui cho nguoi khac.
echo   Nguoi nhan chi can giai nen va chay ReupStudio.exe, KHONG
echo   can cai Python/pip gi ca. Van can tu cai san Google Chrome.
echo ==========================================================
pause
