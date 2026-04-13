@echo off
echo ================================================================
echo 路径二 v5：组合严谨研究 - 全品种
echo 运行时间可能较长，请耐心等待...
echo ================================================================
cd /d "d:\My project\ai-quant-projects-merged\path2_lightweight"
python portfolio\portfolio_rigorous_study.py 2>&1 | tee portfolio_research_results\run_log.txt
echo.
echo ================================================================
echo 完成！按任意键退出...
echo ================================================================
pause >nul
