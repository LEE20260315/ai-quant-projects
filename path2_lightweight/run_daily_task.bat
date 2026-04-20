@echo off
REM 实盘跟踪定时任务 - 每日15:30自动运行
REM 安装方法: 以管理员身份运行 install_task.bat

set PYTHON=python
set SCRIPT=D:\My project\ai-quant-projects-merged\path2_lightweight\live_tracker.py
set LOGDIR=D:\My project\ai-quant-projects-merged\path2_lightweight\tracking

echo [%date% %time%] Starting daily tracking... >> "%LOGDIR%\task_log.txt"
%PYTHON% "%SCRIPT%" daily >> "%LOGDIR%\task_log.txt" 2>&1
echo [%date% %time%] Daily tracking completed. >> "%LOGDIR%\task_log.txt"
