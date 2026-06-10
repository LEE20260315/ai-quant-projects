@echo off
set SCRIPT_DIR=%~dp0
schtasks /create /tn "QuantFusion_Daily" /tr "%SCRIPT_DIR%run_daily_task.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 15:30 /f

echo.
echo ==============================================
echo QuantFusion v1.3 Daily Task Installer
echo ==============================================
echo.
echo   Task Name:  QuantFusion_Daily
echo   Schedule:   Mon-Fri 15:30
echo   Script:     %SCRIPT_DIR%run_daily_task.bat
echo.
echo   View task:  schtasks /query /tn "QuantFusion_Daily"
echo   Delete:     schtasks /delete /tn "QuantFusion_Daily" /f
echo   Run now:    schtasks /run /tn "QuantFusion_Daily"
echo.
echo IMPORTANT: Run this script as Administrator!
echo.
pause