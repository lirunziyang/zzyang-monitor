@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动子漾监测（这个窗口不要关，关了程序就退出）...
echo.
"%~dp0runtime\python.exe" "%~dp0app.py"
echo.
echo 程序已退出。如果上面有红色报错，把它发给我。
pause
