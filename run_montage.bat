@echo off
rem ============================================================================
rem  run_montage.bat - Khoi chay moi truong OpenMontage tu goc F:\Orino
rem
rem  OpenMontage la he thong do AI agent dieu khien (agentic), khong phai CLI
rem  nhan file. Bat script nay chi khoi chay moi truong va mo opencode tai
rem  thu muc OpenMontage; agent se doc AGENTS.md + AGENTS.local.md va chay
rem  pipeline video tuong ung.
rem
rem  LUONG DU LIEU (Phuong an A - giao tiep qua thu muc, khong import code):
rem    Reup Studio xuat final_vi.mp4 + translated.srt
rem          => copy vao OpenMontage\exchange\input\
rem    OpenMontage (agent chon pipeline, xac nhan truoc khi render)
rem          => ket qua luu o OpenMontage\exchange\output\
rem ============================================================================

@echo on
cd /d "F:\Orino\OpenMontage"

rem Kich hoat virtual environment Python coc lap cua OpenMontage
call .venv\Scripts\activate.bat

echo.
echo ============================================================================
echo   OpenMontage da san sang tai: F:\Orino\OpenMontage
echo   Moi truong Python (.venv) da duoc kich hoat.
echo ============================================================================
echo.
echo   HUONG DAN:
echo   1. Tu Reup Studio, xuat video final_vi.mp4 va file translated.srt
echo      (tu tab Translate / Job Center) vao thu muc:
echo         F:\Orino\OpenMontage\exchange\input\
echo   2. Mo file nay (run_montage.bat) de kich hoat moi truong, thi opencode
echo      se duoc mo tai thu muc OpenMontage.
echo   3. Agent doc OpenMontage\AGENTS.md va OpenMontage\AGENTS.local.md,
echo      chon pipeline phu hop (animation / cinematic / documentary-montage ...)
echo      va xac nhan truoc khi render.
echo   4. Ket qua video cuoi cung lay tai:
echo         F:\Orino\OpenMontage\exchange\output\
echo.
echo   LUU Y QUY TAC:
echo   - KHONG render video thu nghiem, KHONG goi API tra phi, KHONG nhap API key.
echo   - Xac nhan truoc khi render (theo quy tac cua OpenMontage AGENT_GUIDE.md).
echo   - OpenMontage co giay phep AGPL-3.0: giu nhu mot thu tuoc lap, KHONG
echo      imports ma OpenMontage vao core/ cua du an chinh.
echo.
echo   Lenh de mo opencode tai day (neu lenh opencode khong duoc tinh toi):
echo       opencode
echo   hoac:
echo       npx -y opencode
echo.
echo   De thoat, dong cua so nay.

cmd /k
