@echo off
setlocal enableextensions enabledelayedexpansion

REM --- Resolve repo root to the folder containing this .bat ---
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul 2>&1

REM --- Prefer UTF-8 for predictable console behavior ---
set "PYTHONUTF8=1"

echo [STEP] Locate Python
set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    where python >nul 2>&1 && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo [ERROR] Python not found in PATH. Install Python 3.10+ and try again.
    popd & exit /b 2
)

echo [STEP] Ensure virtual environment
if not exist ".venv" (
    echo [INFO] Creating virtual environment: .venv
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        popd & exit /b 2
    )
)

echo [STEP] Activate virtual environment
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    popd & exit /b 2
)

REM Use the venv’s python explicitly
set "PYEXE=%VIRTUAL_ENV%\Scripts\python.exe"

echo [STEP] Install dependencies
"%PYEXE%" -m pip install --upgrade pip >nul
if exist "requirements.txt" (
    "%PYEXE%" -m pip install -r requirements.txt
) else (
    "%PYEXE%" -m pip install PyYAML
)
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    popd & exit /b 2
)

echo [STEP] Locate sync script and config
set "SCRIPT=sync_net_dir.py"
if not exist "%SCRIPT%" (
    echo [ERROR] Script not found: %SCRIPT%
    popd & exit /b 2
)
set "CONFIG=configs\sync_job.yaml"
if not exist "%CONFIG%" (
    echo [ERROR] Config not found: %CONFIG%
    popd & exit /b 2
)
echo [INFO] Using script: %SCRIPT%
echo [INFO] Using config: %CONFIG%

echo [STEP] Dry-run
echo [INFO] "%PYEXE%" "%SCRIPT%" --config "%CONFIG%" --compact
"%PYEXE%" "%SCRIPT%" --config "%CONFIG%" --compact
if errorlevel 1 (
    echo.
    echo [ERROR] Dry-run reported errors. Aborting.
    popd & exit /b 1
)

echo.
choice /M "Proceed to apply changes?"
if errorlevel 2 (
    echo [INFO] Skipped applying changes.
    goto :done
)

echo [STEP] Apply changes
echo [INFO] "%PYEXE%" "%SCRIPT%" --config "%CONFIG%" --apply
"%PYEXE%" "%SCRIPT%" --config "%CONFIG%" --apply
if errorlevel 1 (
    echo [ERROR] Apply failed with exit code %ERRORLEVEL%.
    popd & exit /b %ERRORLEVEL%
)
echo [INFO] Apply complete.

:done
popd >nul 2>&1
exit /b 0
