# 编译原生窗口宿主（使用系统自带的 .NET Framework 编译器，无需安装任何 SDK）
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc  = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$out  = Join-Path $here 'dist'
$exe  = Join-Path $out 'ZzyangMonitor.exe'

if (-not (Test-Path $csc)) { throw "找不到系统编译器：$csc" }
New-Item -ItemType Directory -Force -Path $out | Out-Null

& $csc /nologo /target:winexe /platform:x64 /optimize+ `
    "/out:$exe" `
    "/reference:$(Join-Path $here 'lib\Microsoft.Web.WebView2.Core.dll')" `
    "/reference:$(Join-Path $here 'lib\Microsoft.Web.WebView2.WinForms.dll')" `
    /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll `
    (Join-Path $here 'Program.cs')

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $exe)) { throw '编译失败' }

Copy-Item (Join-Path $here 'lib\Microsoft.Web.WebView2.Core.dll') $out -Force
Copy-Item (Join-Path $here 'lib\Microsoft.Web.WebView2.WinForms.dll') $out -Force
Copy-Item (Join-Path $here 'lib\WebView2Loader.dll') $out -Force
if (Test-Path (Join-Path $here 'app.ico')) { Copy-Item (Join-Path $here 'app.ico') $out -Force }

Write-Host "编译完成：$exe ($([math]::Round((Get-Item $exe).Length/1KB,1)) KB)"
