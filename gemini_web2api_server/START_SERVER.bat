@echo off
setlocal
cd /d "%~dp0"
echo Dang khoi dong gemini-web2api tai http://127.0.0.1:8000 ...
echo (Dung server nay CHUNG cho: Reup Studio + auto_rewrite_products.py + du an khac)
python -m gemini_web2api --config config.json
pause
