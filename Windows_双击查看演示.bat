@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 最终验收版演示（自包含单文件，零依赖、离线可开）
if exist "demo\index.html" (
  start "" "demo\index.html"
  exit /b 0
)

rem 回退：第四阶段看板
if exist "reports\phase4_dashboard.html" (
  echo 未找到 demo\index.html，改为打开第四阶段看板。
  echo 如需演示页，请运行：python -m scripts.build_demo
  start "" "reports\phase4_dashboard.html"
  exit /b 0
)

echo 未找到任何可打开的演示页。
echo 请先运行：python -m scripts.build_demo
pause
exit /b 1
