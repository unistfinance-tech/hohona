@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Python could not be found.
    pause
    exit /b 1
  )
  set "PYTHON_EXE=py"
)

"%PYTHON_EXE%" update_restaurant_data.py %*

if errorlevel 1 (
  echo.
  echo Update failed. Check the message above.
  pause
  exit /b 1
)

echo.
echo Update completed.
pause
