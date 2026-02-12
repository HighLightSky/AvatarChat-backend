@echo off
echo Starting OpenAvatarChat with LAM mode...
echo.
echo IMPORTANT: Make sure you have configured your DASHSCOPE_API_KEY in .env file
echo.
set PYTHONUTF8=1
.venv\Scripts\python.exe src/demo.py --config config/chat_with_lam.yaml
pause
