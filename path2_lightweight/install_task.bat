@echo off
REM 安装Windows定时任务 - 每个交易日15:30自动运行实盘跟踪
REM 需要以管理员身份运行此脚本

schtasks /create /tn "QuantFusion_Daily" /tr "D:\My project\ai-quant-projects-merged\path2_lightweight\run_daily_task.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 15:30 /f

echo.
echo 定时任务已创建:
echo   名称: QuantFusion_Daily
echo   时间: 每周一至周五 15:30
echo   脚本: run_daily_task.bat
echo.
echo 查看任务: schtasks /query /tn "QuantFusion_Daily"
echo 删除任务: schtasks /delete /tn "QuantFusion_Daily" /f
pause
