@echo off
REM ============================================================
REM 盘后跑 daily --live (5 天盯盘期)
REM ============================================================
REM 用法: 5 天内每天双击一次, 或挂到 Windows Task Scheduler
REM 盯盘期: 2026-06-10 ~ 2026-06-16 (5 个工作日, 周末跳过)
REM ============================================================

setlocal

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 加载环境变量 (从 .env 文件读, 避免明文密码)
if exist ".env" call :load_env
if not defined CTP_INVESTOR_ID (
    echo [ERROR] CTP_INVESTOR_ID 未设置. 请创建 .env 文件, 内容:
    echo   CTP_INVESTOR_ID=260042
    echo   CTP_PASSWORD=xibeilang@99
    echo   CTP_FRONT_ADDR=tcp://182.254.243.31:40001
    echo   CTP_BROKER_ID=9999
    echo   CTP_APP_ID=simnow_client_test
    echo   CTP_AUTH_CODE=0000000000000000
    echo   [可选] DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
    exit /b 1
)

REM 时间戳
set TS=%date:~0,4%-%date:~5,2%-%date:~8,2% %time:~0,2%:%time:~3,2%:%time:~6,2%
echo ============================================================
echo [%TS%] 盘后跑 daily --live (5 天盯盘期)
echo ============================================================

REM 跑 daily
python live_tracker_ctp.py daily --live 2>&1 | tee logs\daily_%date:~0,4%%date:~5,2%%date:~8,2%_run.log

REM 检查返回码
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [WARN] daily 返回码 %ERRORLEVEL%, 请看上面的日志
    pause
) else (
    echo.
    echo [OK] daily 5/5 全跑通
    echo       1. QQ 邮箱 78644612@qq.com 查收日报
    echo       2. 钉钉 (如配了 webhook) 查收实时告警
    echo       3. tracking\daily_%date:~0,4%-%date:~5,2%-%date:~8,2%.json 看日报原文
    echo       4. tracking\ctp_order_log.json 看 CTP 真下单留痕
)

endlocal
exit /b 0

:load_env
for /f "usebackq tokens=1* delims==" %%a in (".env") do (
    set "%%a=%%b"
)
goto :eof
