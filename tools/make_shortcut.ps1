# 在桌面（以及项目上一级目录）创建启动快捷方式，带自定义图标
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1 -Remove
param(
    [switch]$Remove,
    [string[]]$ExtraDirs = @()
)

$ErrorActionPreference = 'Stop'

$tools   = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Split-Path -Parent $tools
$target  = Join-Path $project '大肥鱼监测.vbs'
$icon    = Join-Path $project 'host\app.ico'

if (-not (Test-Path $target)) { throw "找不到启动文件：$target" }

$desktop = [Environment]::GetFolderPath('Desktop')
$dirs = @($desktop) + $ExtraDirs
$shell = New-Object -ComObject WScript.Shell

foreach ($dir in $dirs) {
    if (-not $dir -or -not (Test-Path $dir)) { continue }
    $link = Join-Path $dir '大肥鱼监测.lnk'

    if ($Remove) {
        if (Test-Path $link) {
            Remove-Item $link -Force
            Write-Host "已删除快捷方式：$link"
        }
        continue
    }

    $sc = $shell.CreateShortcut($link)
    $sc.TargetPath = $target
    $sc.WorkingDirectory = $project
    $sc.WindowStyle = 7
    $sc.Description = '大肥鱼监测（只读）'
    if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
    $sc.Save()

    if (Test-Path $link) { Write-Host "已创建快捷方式：$link" }
    else { throw "创建失败：$link" }
}
