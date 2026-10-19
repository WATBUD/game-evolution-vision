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
powershell.exe -NoProfile -Command "$pythonwPath = [IO.Path]::GetFullPath('%CD%\.venv\Scripts\pythonw.exe'); $all = @(Get-CimInstance Win32_Process); $ids = New-Object 'System.Collections.Generic.HashSet[int]'; foreach ($process in $all) { if ($process.Name -eq 'pythonw.exe' -and $process.ExecutablePath -and ([IO.Path]::GetFullPath($process.ExecutablePath) -ieq $pythonwPath)) { [void]$ids.Add([int]$process.ProcessId) } }; do { $added = $false; foreach ($process in $all) { if ($ids.Contains([int]$process.ParentProcessId) -and $ids.Add([int]$process.ProcessId)) { $added = $true } } } while ($added); $targetIds = @($ids); foreach ($processId in $targetIds) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }; $deadline = (Get-Date).AddSeconds(5); do { $remaining = @(); foreach ($processId in $targetIds) { if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { $remaining += $processId } }; if ($remaining.Count -eq 0) { break }; Start-Sleep -Milliseconds 100 } while ((Get-Date) -lt $deadline); if ($remaining.Count -gt 0) { Write-Error ('Unable to stop process IDs: ' + ($remaining -join ', ')); exit 1 }"
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to close the previous Game Evolution instance.
  pause
  exit /b 1
)

echo [Game Evolution] Starting as an independent GUI process...
echo.
powershell.exe -NoProfile -Command "$process = Start-Process -FilePath '%CD%\.venv\Scripts\pythonw.exe' -ArgumentList 'app.py' -WorkingDirectory '%CD%' -RedirectStandardError '%CD%\game-evolution-error.log' -WindowStyle Hidden -PassThru; Start-Sleep -Seconds 2; if ($process.HasExited) { Write-Error ('Game Evolution exited during startup with code ' + $process.ExitCode); exit 1 }; Set-Content -LiteralPath '%CD%\game-evolution.pid' -Value $process.Id -Encoding ASCII"
if errorlevel 1 (
  echo [ERROR] Failed to start Game Evolution.
  echo Check game-evolution-error.log for details.
  pause
  exit /b 1
)

echo [Game Evolution] Previous instance closed and new instance started successfully.
echo You may close this black window with X. The GUI will keep running.
echo If the GUI does not appear, check: %CD%\game-evolution-error.log
echo.
echo Press any key to close this window, or leave it open.
pause >nul
exit /b 0
