@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
    goto run
)

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py"
    set "PYTHON_ARGS=-3"
    goto run
)

python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    set "PYTHON_ARGS="
    goto run
)

set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CODEX_PY%" (
    set "PYTHON=%CODEX_PY%"
    set "PYTHON_ARGS="
    goto run
)

echo Python 3.10+ was not found.
pause
exit /b 1

:run
"%PYTHON%" %PYTHON_ARGS% -c "import PIL" >nul 2>&1
if errorlevel 1 (
    echo Installing Pillow...
    "%PYTHON%" %PYTHON_ARGS% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Dependency installation failed. Check the network and retry.
        pause
        exit /b 1
    )
)
if /i "%~1"=="--check" (
    echo QIXIN_READY
    exit /b 0
)
"%PYTHON%" %PYTHON_ARGS% -m qixin --demo
if errorlevel 1 pause
