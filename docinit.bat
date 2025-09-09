@echo off

REM Check if 'docs' directory exists
if not exist docs (
    git clone https://github.com/GATEOverflow/inference_results_visualization_template.git docs
    if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
)

REM Install Python dependencies
python -m pip install -r docs\requirements.txt
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

REM Check if 'overrides' directory exists
if not exist overrides (
    xcopy /e /i /q docs\overrides overrides
    if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
)

REM Set default values for environment variables if not already set
if not defined INFERENCE_RESULTS_REPO_OWNER set INFERENCE_RESULTS_REPO_OWNER=mlcommons
if not defined INFERENCE_RESULTS_REPO_BRANCH set INFERENCE_RESULTS_REPO_BRANCH=main
if not defined INFERENCE_RESULTS_REPO_NAME set INFERENCE_RESULTS_REPO_NAME=inference_results_%INFERENCE_RESULTS_VERSION%

REM Increment version number from dbversion file
set /p ver_num=<dbversion
set /a ver_num+=1
echo ver_num=%ver_num% > dbversion

REM Create config.js if it doesn't exist
if not exist docs\javascripts\config.js (
    if defined INFERENCE_RESULTS_VERSION (
        echo const results_version="%INFERENCE_RESULTS_VERSION%"; > docs\javascripts\config.js
        echo var repo_owner="%INFERENCE_RESULTS_REPO_OWNER%"; >> docs\javascripts\config.js
        echo var repo_branch="%INFERENCE_RESULTS_REPO_BRANCH%"; >> docs\javascripts\config.js
        echo var repo_name="%INFERENCE_RESULTS_REPO_NAME%"; >> docs\javascripts\config.js
        echo const dbVersion="%ver_num%"; >> docs\javascripts\config.js
    ) else (
        echo Please set INFERENCE_RESULTS_VERSION to v4.1 or the corresponding version
        exit /b 1
    )
)

REM Clone tablesorter if not already cloned
if not exist docs\thirdparty\tablesorter (
    pushd docs\thirdparty
    git clone https://github.com/Mottie/tablesorter.git
    if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
    popd
)

REM Run the Python scripts
python process.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

python process_results_table.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
