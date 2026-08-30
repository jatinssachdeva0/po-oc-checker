@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Run setup first.
  pause
  exit /b 1
)
call .venv\Scripts\activate
streamlit run app.py
pause
