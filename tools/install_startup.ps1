# 开机自启：在「启动」文件夹里放一个快捷方式，只想自己用的时候打开。
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\install_startup.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_startup.ps1 -Remove
param(
    [switch]$Remove,
    [string]$AppDataRoot = $env:APPDATA
)

$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$target  = Join-Path $project '子漾监测.vbs'
$startup = Join-Path $AppDataRoot 'Microsoft\Windows\Start Menu\Programs\Startup'
$link    = Join-Path $startup '子漾监测.lnk'

if ($Remove) {
    if (Test-Path $link) {
        Remove-Item $link -Force
        Write-Host "已取消开机自启：$link"
    } else {
        Write-Host "没有找到自启项，无需取消。"
    }
    exit 0
}

if (-not (Test-Path $target)) { throw "找不到启动文件：$target" }
New-Item -ItemType Directory -Force -Path $startup | Out-Null

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = $target
$sc.WorkingDirectory = $project
$sc.WindowStyle = 7
$sc.Description = '子漾监测（只读）'
$sc.Save()

if (Test-Path $link) {
    Write-Host "已设置开机自启：$link"
    Write-Host "取消方法：同一命令加 -Remove"
} else {
    throw '快捷方式创建失败'
}
