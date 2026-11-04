@echo off
REM ============================================================
REM  setup_embedded_python312.bat
REM  Tao 1 ban Python 3.12 "portable" (khong can cai dat) rieng
REM  cho TiktokAuto, kem san toan bo pip packages can thiet.
REM  Sau khi chay xong, nguoi dung cuoi KHONG can tu cai Python
REM  3.12 tren may ho nua - app se tu goi thang toi ban portable
REM  nay.
REM
REM  CACH DUNG:
REM   1. Dat file nay vao thu muc G:\reup-studio\TiktokAuto\
REM   2. Chay: setup_embedded_python312.bat
REM   3. Doi tai + cai xong (vai phut, can mang).
REM   4. Ket qua: thu muc TiktokAuto\python312_embed\
REM   5. Trong app (tab TikTok), doi o "Lenh Python chay
REM      TiktokAuto" tu "py -3.12" thanh duong dan day du:
REM      TiktokAuto\python312_embed\python.exe
REM      (hoac de duong dan tuyet doi neu ban cho vao dist exe)
REM ============================================================

setlocal
set PYVER=3.12.7
set EMBED_URL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip
set GETPIP_URL=https://bootstrap.pypa.io/get-pip.py
set TARGET=python312_embed

echo ==========================================================
echo   Buoc 1/4: Tai Python %PYVER% embeddable (~10MB)
echo ==========================================================
if exist %TARGET% (
    echo   Thu muc %TARGET% da ton tai, xoa de tao lai sach...
    rmdir /S /Q %TARGET%
)
mkdir %TARGET%
powershell -Command "Invoke-WebRequest -Uri '%EMBED_URL%' -OutFile 'python_embed.zip'"
if errorlevel 1 (
    echo LOI: Khong tai duoc Python embeddable. Kiem tra ket noi mang.
    pause
    exit /b 1
)
powershell -Command "Expand-Archive -Path 'python_embed.zip' -DestinationPath '%TARGET%' -Force"
del python_embed.zip

echo.
echo ==========================================================
echo   Buoc 2/4: Bat pip cho ban embeddable (mac dinh bi tat)
echo ==========================================================
REM Sua file ._pth de bo comment dong "import site", can thiet de pip hoat dong.
powershell -Command "(Get-Content '%TARGET%\python312._pth') -replace '#import site', 'import site' | Set-Content '%TARGET%\python312._pth'"

powershell -Command "Invoke-WebRequest -Uri '%GETPIP_URL%' -OutFile '%TARGET%\get-pip.py'"
%TARGET%\python.exe %TARGET%\get-pip.py
if errorlevel 1 (
    echo LOI: Cai pip that bai.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   Buoc 3/4: Cai thu vien cua TiktokAuto vao ban Python nay
echo ==========================================================
%TARGET%\python.exe -m pip install --upgrade pip
REM Ban Python embeddable KHONG co san setuptools/wheel - can cai truoc,
REM vi undetected-chromedriver duoc cai tu ma nguon git (sdist), can
REM setuptools.build_meta de build. Thieu buoc nay se loi "Cannot import
REM 'setuptools.build_meta'".
%TARGET%\python.exe -m pip install --upgrade setuptools wheel
if errorlevel 1 (
    echo LOI: Cai setuptools/wheel that bai.
    pause
    exit /b 1
)
%TARGET%\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo LOI: Cai requirements.txt that bai. Xem log ben tren.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   Buoc 4/4: Cai them Node.js + playwright cho tiktok-signature
echo ==========================================================
echo   LUU Y: Node.js KHONG the nhung vao Python embeddable duoc.
echo   Neu may nguoi dung cuoi chua co Node.js, ho van can tu cai
echo   Node.js rieng (khong tranh duoc voi co che ky TikTok signature).
echo   Neu ban da chay "npm install" trong TiktokAuto\tiktok_uploader\tiktok-signature
echo   tren may nay roi thi thu muc node_modules se duoc dong goi
echo   kem theo khi zip ca thu muc TiktokAuto lai.

echo.
echo ==========================================================
echo   XONG! Duong dan Python dung cho tab TikTok trong app:
echo   TiktokAuto\%TARGET%\python.exe
echo   ^(Mo app, tab TikTok, sua o "Lenh Python chay TiktokAuto"
echo    thanh duong dan tren^)
echo ==========================================================
pause
