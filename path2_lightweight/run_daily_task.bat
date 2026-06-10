@echo off
chcp 65001 >nul 2>&1

set PYTHON=python
set BASEDIR=%~dp0
set LOGDIR=%BASEDIR%tracking
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [%date% %time%] Starting daily tracking... >> "%LOGDIR%\task_log.txt"
cd /d "%BASEDIR%"
"%PYTHON%" "%BASEDIR%live_tracker.py" daily >> "%LOGDIR%\task_log.txt" 2>&1
echo [%date% %time%] Daily tracking completed. >> "%LOGDIR%\task_log.txt"

for /f "tokens=1" %%i in ('%PYTHON% -c "from datetime import datetime; print(datetime.now().weekday())"') do set DOW=%%i
if "%DOW%"=="4" (
    echo [%date% %time%] Starting weekly report... >> "%LOGDIR%\task_log.txt"
    "%PYTHON%" "%BASEDIR%weekly_report.py" >> "%LOGDIR%\task_log.txt" 2>&1
    echo [%date% %time%] Weekly report completed. >> "%LOGDIR%\task_log.txt"
)