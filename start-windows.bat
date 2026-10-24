@echo off
REM Starts BuyWise backend and frontend in two windows. Run the install steps in README.md once first.
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe (
  echo Backend virtual environment not found. Follow "Run on Windows" in README.md first.
  pause
  exit /b 1
)
if not exist backend\.env copy backend\.env.example backend\.env >nul
if not exist frontend\.env copy frontend\.env.example frontend\.env >nul
start "BuyWise backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765"
start "BuyWise frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 6 >nul
start http://127.0.0.1:5173
