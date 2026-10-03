@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Please run the installation steps in README.md first.
  pause
  exit /b 1
)

if not exist "frontend\node_modules" (
  echo Installing frontend dependencies...
  pushd frontend
  call npm install
  popd
)

rem Start Vite once when it is not already listening on the development port.
powershell -NoProfile -Command "if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 5173 -InformationLevel Quiet)) { Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev' -WorkingDirectory '%CD%\frontend' -WindowStyle Minimized }"

echo Waiting for the frontend development server...
for /l %%i in (1,1,20) do (
  powershell -NoProfile -Command "if (Test-NetConnection -ComputerName 127.0.0.1 -Port 5173 -InformationLevel Quiet) { exit 0 } else { exit 1 }"
  if not errorlevel 1 goto frontend_ready
  timeout /t 1 /nobreak >nul
)

echo The frontend development server did not start on port 5173.
pause
exit /b 1

:frontend_ready
".venv\Scripts\python.exe" launcher.py --dev

if errorlevel 1 pause
endlocal
