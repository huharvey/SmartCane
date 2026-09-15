@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "RAW_DIR=%SCRIPT_DIR%data\raw"
set "AF_DEST=%RAW_DIR%\mimic_perform_af_csv.zip"
set "NON_AF_DEST=%RAW_DIR%\mimic_perform_non_af_csv.zip"
set "NON_AF_PART=%NON_AF_DEST%.part"
set "NON_AF_URL=https://zenodo.org/records/6807403/files/mimic_perform_non_af_csv.zip?download=1"

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
if not exist "%~1" (
  echo [ERROR] AF zip not found: %~1
  exit /b 2
)
if not exist "%~2" (
  echo [ERROR] Local capture directory not found: %~2
  exit /b 2
)

if not exist "%RAW_DIR%" mkdir "%RAW_DIR%"
if not exist "%AF_DEST%" copy /Y "%~1" "%AF_DEST%" >nul

if not exist "%NON_AF_DEST%" (
  echo [DATA] Downloading the official non-AF companion archive...
  if exist "%NON_AF_PART%" (
    curl.exe -L --fail --retry 20 --retry-all-errors --retry-delay 5 -C - --output "%NON_AF_PART%" "%NON_AF_URL%"
  ) else (
    curl.exe -L --fail --retry 20 --retry-all-errors --retry-delay 5 --output "%NON_AF_PART%" "%NON_AF_URL%"
  )
  if errorlevel 1 (
    echo [ERROR] Download interrupted. Run this command again to resume it.
    exit /b 3
  )
  move /Y "%NON_AF_PART%" "%NON_AF_DEST%" >nul
)

if not exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
  echo [PYTHON] Creating isolated environment...
  py -3 -m venv "%SCRIPT_DIR%.venv"
  if errorlevel 1 exit /b 4
)

echo [PYTHON] Installing or updating training dependencies...
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 exit /b 5

echo [TRAIN] Extracting features, training, independent testing, and local replay...
"%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%run_training.py" ^
  --af-zip "%AF_DEST%" ^
  --non-af-zip "%NON_AF_DEST%" ^
  --local-captures "%~2" ^
  --output "%SCRIPT_DIR%artifacts\latest"
if errorlevel 1 exit /b 6

echo.
echo Finished. Read:
echo %SCRIPT_DIR%artifacts\latest\TRAINING_REPORT.md
exit /b 0

:usage
echo Usage:
echo   prepare_and_train.cmd "path-to-mimic_perform_af_csv.zip" "path-to-P001-P043-directory"
exit /b 1
