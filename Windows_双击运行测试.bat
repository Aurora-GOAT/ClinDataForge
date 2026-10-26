@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m unittest discover -s tests -v
set "TEST_EXIT=%ERRORLEVEL%"
if not "%TEST_EXIT%"=="0" (
  echo 测试失败，请把完整输出发给Codex排查。
) else (
  echo 全量测试已通过，测试数量以控制台输出为准。
)
pause
exit /b %TEST_EXIT%
