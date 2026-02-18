@echo off
set PYTHONUTF8=1

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe src/demo.py --config config/chat_with_interview.yaml
) else (
    python src/demo.py --config config/chat_with_interview.yaml
)
