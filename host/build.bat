@echo off
chcp 65001 >nul
rem 编译原生窗口宿主（需要系统自带的 .NET Framework 编译器）
setlocal
set HERE=%~dp0
set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
set OUT=%HERE%dist

if not exist "%OUT%" mkdir "%OUT%"

"%CSC%" /nologo /target:winexe /platform:x64 /optimize+ ^
  /out:"%OUT%\子漾监测.exe" ^
  /reference:%HERE%lib\Microsoft.Web.WebView2.Core.dll ^
  /reference:%HERE%lib\Microsoft.Web.WebView2.WinForms.dll ^
  /reference:System.dll ^
  /reference:System.Drawing.dll ^
  /reference:System.Windows.Forms.dll ^
  "%HERE%Program.cs"

if errorlevel 1 (
  echo 编译失败
  exit /b 1
)

copy /y "%HERE%lib\Microsoft.Web.WebView2.Core.dll" "%OUT%" >nul
copy /y "%HERE%lib\Microsoft.Web.WebView2.WinForms.dll" "%OUT%" >nul
copy /y "%HERE%lib\WebView2Loader.dll" "%OUT%" >nul
if exist "%HERE%app.ico" copy /y "%HERE%app.ico" "%OUT%" >nul

echo 编译完成：%OUT%\子漾监测.exe
