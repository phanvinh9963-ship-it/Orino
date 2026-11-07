@echo off
setlocal
cd /d "F:\Orino\OpenMontage"
call ".venv\Scripts\activate.bat"
echo ========================================
echo  OpenMontage - moi truong da san sang
echo  Dat video / SRT vao:  OpenMontage\exchange\input\
echo  Ket qua xuat ra:      OpenMontage\exchange\output\
echo  Lenh: opencode (agent se doc AGENTS.md)
echo ========================================
opencode
endlocal