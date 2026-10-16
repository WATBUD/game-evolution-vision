@echo off
title Game Evolution Launcher and Error Log

if /i not "%~1"=="--elevated" (
  echo [Game Evolution] Requesting administrator privileges...
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '--elevated' -Verb RunAs"
  if errorlevel 1 (
    echo.
    echo [ERROR] Administrator permission was denied or elevation failed.
    pause
  )
  exit /b
)

whoami /groups | findstr /c:"S-1-16-12288" >nul
if errorlevel 1 (
  echo.
  echo [ERROR] Game Evolution did not receive administrator privileges.
  pause
  exit /b 1
)

cd /d "%~dp0"

echo [Game Evolution] Working directory: %CD%
echo [Game Evolution] Checking runtime...

if not exist ".venv\Scripts\pythonw.exe" (
  echo.
  echo [ERROR] Missing .venv\Scripts\pythonw.exe
  echo Install the Python environment described in README.md first.
  pause
  exit /b 1
)

if not exist "app.py" (
  echo.
  echo [ERROR] Missing app.py
  pause
  exit /b 1
)

echo [Game Evolution] Closing previous Game Evolution instance...
powershell.exe -NoProfile -Command "$appPath = [IO.Path]::GetFullPath('%CD%\app.py'); Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like ('*' + $appPath + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo [Game Evolution] Starting as an independent GUI process...
echo.
start "Game Evolution" /D "%CD%" ".venv\Scripts\pythonw.exe" "app.py" 1>>"game-evolution-error.log" 2>&1
if errorlevel 1 (
  echo [ERROR] Failed to start Game Evolution.
  echo Check game-evolution-error.log for details.
  pause
  exit /b 1
)

echo [Game Evolution] Launch command completed.
echo You may close this black window with X. The GUI will keep running.
echo If the GUI does not appear, check: %CD%\game-evolution-error.log
echo.
echo Press any key to close this window, or leave it open.
pause >nul
exit /b 0
