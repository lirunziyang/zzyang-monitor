# 关窗退出测试：启动 → 模拟点关闭 → 检查进程是否真的退干净
# 用法：powershell -ExecutionPolicy Bypass -File tools\exit_check.ps1
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$cfg = Join-Path $root 'data\settings.json'

function Get-Json($path) {
    if (-not (Test-Path $path)) { return @{} }
    return (Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json)
}
function Save-Json($path, $obj) {
    $obj | ConvertTo-Json -Depth 6 | Set-Content $path -Encoding UTF8
}

# 保证这次是「关窗即退出」模式
$original = $null
if (Test-Path $cfg) {
    $original = Get-Content $cfg -Raw -Encoding UTF8
    $j = Get-Json $cfg
    $j | Add-Member -NotePropertyName close_to_tray -NotePropertyValue $false -Force
    Save-Json $cfg $j
}

Get-Process ZzyangMonitor -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$root*" } | Stop-Process -Force
Start-Sleep -Seconds 1
Remove-Item (Join-Path $root 'data\instance.json') -Force -ErrorAction SilentlyContinue

Write-Host '启动应用…'
& wscript.exe (Join-Path $root '大肥鱼监测.vbs')
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 300
    $p = Get-Process ZzyangMonitor -ErrorAction SilentlyContinue
    if ($p -and $p.MainWindowHandle -ne 0) { $ok = $true; break }
}
if (-not $ok) {
    Write-Host '!! 窗口没有出现' -ForegroundColor Red
    if ($original) { Set-Content $cfg $original -Encoding UTF8 }
    exit 1
}
Write-Host ("窗口已出现：{0}" -f $p.MainWindowTitle)

# 发送 WM_CLOSE（等同于点右上角关闭）
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CloseWin {
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
}
"@
[CloseWin]::SendMessage($p.MainWindowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null

$gone = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 300
    $h = @(Get-Process ZzyangMonitor -ErrorAction SilentlyContinue)
    $pw = @(Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$root*" })
    if ($h.Count -eq 0 -and $pw.Count -eq 0) { $gone = $true; break }
}

$instanceLeft = Test-Path (Join-Path $root 'data\instance.json')
if ($original) { Set-Content $cfg $original -Encoding UTF8 }

Write-Host ''
if ($gone -and -not $instanceLeft) {
    Write-Host 'RESULT: PASS  关窗后进程完全退出，instance.json 已清理' -ForegroundColor Green
    exit 0
}
Write-Host ("host={0} pythonw={1} instance.json={2}" -f $h.Count, $pw.Count, $instanceLeft) -ForegroundColor Red
Write-Host 'RESULT: FAIL  关窗后仍有残留' -ForegroundColor Red
exit 1
