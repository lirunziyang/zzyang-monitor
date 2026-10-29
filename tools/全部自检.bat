@echo off
chcp 936 >nul
cd /d "%~dp0.."
set "PY=runtime\python.exe"
echo ============================================
echo  大肥鱼监测 全部自检
echo ============================================
echo.
echo [1/3] 启动自检（服务、静态资源、接口）
"%PY%" tools\selfcheck.py
set R1=%ERRORLEVEL%
echo.
echo [2/3] 只读性检查（机器人文件是否被改动）
"%PY%" tools\readonly_check.py
set R2=%ERRORLEVEL%
echo.
echo [3/3] 功能检查（设置项、多本书、诊断接口）
"%PY%" tools\feature_check.py
set R3=%ERRORLEVEL%
echo.
if "%R1%%R2%%R3%"=="000" (echo 全部通过) else (echo 有检查未通过，见上面输出)
pause