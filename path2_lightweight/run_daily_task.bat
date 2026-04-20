@echo off
chcp 65001 >nul 2>&1

set PYTHON=C:\Python314\python.exe
set SCRIPT=D:\My project\ai-quant-projects-merged\path2_lightweight\live_tracker.py
set LOGDIR=D:\My project\ai-quant-projects-merged\path2_lightweight\tracking

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [%date% %time%] Starting daily tracking... >> "%LOGDIR%\task_log.txt"
cd /d "D:\My project\ai-quant-projects-merged\path2_lightweight"
"%PYTHON%" "%SCRIPT%" daily >> "%LOGDIR%\task_log.txt" 2>&1
echo [%date% %time%] Daily tracking completed. >> "%LOGDIR%\task_log.txt"
