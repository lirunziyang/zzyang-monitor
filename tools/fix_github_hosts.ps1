# 让 github.com 能访问：自动挑一个当前可用的节点写进 hosts
# 由 修复GitHub连接.bat 提权调用；GitHub 又打不开时重跑本脚本即可
# 撤销：powershell -ExecutionPolicy Bypass -File fix_github_hosts.ps1 -Remove
param(
    [switch]$Remove,
    [string]$IP = ""          # 留空 = 自动挑
)

$ErrorActionPreference = 'Stop'
$hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$marker = '# zzyang-monitor: pin github.com'

$CANDIDATES = @(
    '140.82.113.3', '140.82.114.3', '140.82.116.3', '140.82.121.3',
    '140.82.112.3', '20.27.177.113', '4.237.22.38', '20.205.243.166',
    '20.205.243.168'
)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "需要管理员权限，请通过 修复GitHub连接.bat 运行。" -ForegroundColor Red
    exit 1
}

function Strip-OurLines($text) {
    ($text -split "`r?`n") | Where-Object {
        $_ -notmatch 'zzyang-monitor: pin github\.com' -and
        $_ -notmatch '^\s*\d{1,3}(\.\d{1,3}){3}\s+github\.com\s*$'
    }
}

$content = Get-Content $hosts -Raw -Encoding UTF8
if (-not $content) { $content = '' }

if ($Remove) {
    Set-Content -Path $hosts -Value ((Strip-OurLines $content) -join "`r`n") -Encoding ASCII
    ipconfig /flushdns | Out-Null
    Write-Host "已移除 github.com 的固定条目。" -ForegroundColor Green
    exit 0
}

function Test-Node($ip) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $task = $c.ConnectAsync($ip, 443)
        if ($task.Wait(1800) -and $c.Connected) { $c.Close(); return $true }
        $c.Close()
    } catch { }
    return $false
}

$chosen = $null
if ($IP) {
    if (Test-Node $IP) { $chosen = $IP }
    else { Write-Host "指定的 $IP 当前不通。" -ForegroundColor Yellow }
}

if (-not $chosen) {
    Write-Host "正在测试可用节点…"
    foreach ($ip in $CANDIDATES) {
        if (Test-Node $ip) {
            $chosen = $ip
            Write-Host "  选中 $ip" -ForegroundColor Green
            break
        }
        Write-Host "  $ip 不通"
    }
}

if (-not $chosen) {
    Write-Host ""
    Write-Host "所有候选节点都不通。" -ForegroundColor Red
    Write-Host "这说明到 GitHub 的线路整体被卡，不是节点问题。" -ForegroundColor Red
    Write-Host "建议改用代理/VPN，或者换个时间段再试。"
    exit 1
}

$kept = (Strip-OurLines $content) -join "`r`n"
if ($kept.Trim()) { $kept += "`r`n" }
$kept += "`r`n$marker`r`n$chosen github.com`r`n"

$backup = "$hosts.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item $hosts $backup -Force
[System.IO.File]::WriteAllText($hosts, $kept, [System.Text.Encoding]::ASCII)
ipconfig /flushdns | Out-Null

Write-Host ""
Write-Host "已写入：$chosen github.com" -ForegroundColor Green
Write-Host "原文件备份：$backup"

Write-Host ""
Write-Host "验证："
try {
    $resolved = [System.Net.Dns]::GetHostAddresses('github.com') |
        Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1
    Write-Host "  github.com -> $resolved"
    $c = New-Object System.Net.Sockets.TcpClient
    $t = $c.ConnectAsync('github.com', 443)
    if ($t.Wait(6000) -and $c.Connected) {
        Write-Host "  443 连接成功，浏览器可以打开 github.com 了" -ForegroundColor Green
        $c.Close()
    } else {
        Write-Host "  443 仍不通，再重跑一次本脚本（会换节点）" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  验证失败：$($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "以后 GitHub 又打不开时，重跑这个 bat 就行（会自动换到当前可用的节点）。" -ForegroundColor Cyan
Write-Host "撤销：管理员 PowerShell 里执行本脚本加 -Remove"
