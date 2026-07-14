@echo off
rem AllocSignal - Windows launcher.
setlocal
cd /d "%~dp0"

set "PYTHON_CMD=py -3"
%PYTHON_CMD% -c "import sys" >nul 2>nul || set "PYTHON_CMD=python"
%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul || (
  echo AllocSignal needs Python 3.10 or newer.
  echo Install it from https://www.python.org/downloads/
  echo IMPORTANT: tick "Add python.exe to PATH" during installation, then try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating AllocSignal's private Python environment...
  %PYTHON_CMD% -m venv .venv
)

for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash requirements.txt -Algorithm SHA256).Hash.ToLower()"') do set "REQ_HASH=%%H"
if not exist ".venv\.allocsignal-requirements-%REQ_HASH%" (
  echo First launch: downloading AllocSignal's Python packages. This can take a few minutes.
  echo Later launches will be much faster.
  ".venv\Scripts\python.exe" -m pip --disable-pip-version-check install --prefer-binary -r requirements.txt || (
    echo Package installation failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
  del /q .venv\.allocsignal-requirements-* .venv\.allocsignal-ready 2>nul
  type nul > ".venv\.allocsignal-requirements-%REQ_HASH%"
) else (
  echo Using the existing AllocSignal environment.
)

if not defined ARROW_DEFAULT_MEMORY_POOL set "ARROW_DEFAULT_MEMORY_POOL=system"
if not defined ALLOCSIGNAL_PORT set "ALLOCSIGNAL_PORT=8593"

echo Starting AllocSignal at http://127.0.0.1:%ALLOCSIGNAL_PORT% ...
".venv\Scripts\python.exe" -m streamlit run app.py ^
  --server.headless=false ^
  --server.address=127.0.0.1 ^
  --server.port=%ALLOCSIGNAL_PORT% ^
  --server.maxUploadSize=200 ^
  --server.fileWatcherType=none ^
  --browser.gatherUsageStats=false

if errorlevel 1 (
  echo AllocSignal stopped with an error. Review the message above.
  pause
  exit /b 1
)
