# 全部自检：一次跑完所有套件，输出汇总表，任一项失败就返回非 0。
# 用法：
#   powershell -File tools\allcheck.ps1            # 全部（含界面自检与关窗测试）
#   powershell -File tools\allcheck.ps1 -Quick     # 只跑脚本套件，不启动窗口
param(
    [switch]$Quick,
    [switch]$NoUi,
    [switch]$NoExit
)

$ErrorActionPreference = 'Continue'
# 控制台统一 UTF-8，避免中文和符号被 GBK 吞掉
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$py = Join-Path $root 'runtime\python.exe'

if (-not (Test-Path $py)) {
    Write-Host "[错误] 找不到运行环境：$py" -ForegroundColor Red
    exit 1
}

function Format-Duration([double]$seconds) {
    if ($seconds -lt 60) { return ('{0:N1}s' -f $seconds) }
    return ('{0:N0}m{1:N0}s' -f [Math]::Floor($seconds / 60), ($seconds % 60))
}

$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$name, [bool]$ok, [string]$detail, [double]$seconds) {
    $script:results.Add([pscustomobject]@{
        Name = $name
        Ok   = $ok
        Detail = $detail
        Time = $seconds
    })
}

function Invoke-PySuite([string]$name, [string]$file) {
    $path = Join-Path $here $file
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $oldEnc = $env:PYTHONIOENCODING
    $env:PYTHONIOENCODING = 'utf-8'
    $out = & $py $path 2>&1
    $code = $LASTEXITCODE
    if ($null -eq $oldEnc) { Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue }
    else { $env:PYTHONIOENCODING = $oldEnc }
    $sw.Stop()

    $resultLine = ($out | Select-String -Pattern 'RESULT:' | Select-Object -Last 1)
    $detail = if ($resultLine) { $resultLine.Line.Trim() } else { "没有输出 RESULT 行（退出码 $code）" }
    if ($code -ne 0 -and -not $resultLine) {
        $detail = ($out | Select-Object -Last 1)
    }

    Write-Host ("  {0} … {1}" -f $name, $(if ($code -eq 0) { 'OK' } else { 'FAIL' }))
    Add-Result $name ($code -eq 0) $detail $sw.Elapsed.TotalSeconds
}

function Invoke-PsScript([string]$name, [string]$file) {
    $path = Join-Path $here $file
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $path 2>&1
    $code = $LASTEXITCODE
    $sw.Stop()

    $resultLine = ($out | Select-String -Pattern 'RESULT:' | Select-Object -Last 1)
    $detail = if ($resultLine) { $resultLine.Line.Trim() } else { "没有输出 RESULT 行（退出码 $code）" }
    Write-Host ("  {0} … {1}" -f $name, $(if ($code -eq 0) { 'OK' } else { 'FAIL' }))
    Add-Result $name ($code -eq 0) $detail $sw.Elapsed.TotalSeconds
}

$total = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host ''
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ' 大肥鱼监测 · 全部自检' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''
Write-Host '[脚本套件]'

$suites = @(
    @('启动自检', 'selfcheck.py'),
    @('只读性检查', 'readonly_check.py'),
    @('校验自测', 'readonly_selftest.py'),
    @('HTTP 边界', 'edge_check.py'),
    @('功能检查', 'feature_check.py'),
    @('数据层', 'm3_check.py'),
    @('存储与文档', 'm4_check.py')
)
foreach ($s in $suites) { Invoke-PySuite $s[0] $s[1] }

if (-not $Quick) {
    Write-Host ''
    Write-Host '[界面与窗口]'
    if (-not $NoUi) { Invoke-PsScript '界面自检' 'ui_check.ps1' }
    if (-not $NoExit) { Invoke-PsScript '关窗测试' 'exit_check.ps1' }
}

$total.Stop()
Write-Host ''
Write-Host '----------------------------------------'
Write-Host ("{0,-12} {1,-6} {2,-8} {3}" -f '检查项', '结果', '耗时', '详情')
Write-Host '----------------------------------------'
$bad = 0
foreach ($r in $results) {
    $mark = if ($r.Ok) { 'PASS' } else { 'FAIL'; }
    if (-not $r.Ok) { $bad++ }
    $color = if ($r.Ok) { 'Green' } else { 'Red' }
    $detail = $r.Detail
    if ($detail.Length -gt 52) { $detail = $detail.Substring(0, 52) + '…' }
    Write-Host ("{0,-12} {1,-6} {2,-8} {3}" -f $r.Name, $mark, (Format-Duration $r.Time), $detail) -ForegroundColor $color
}
Write-Host '----------------------------------------'

if ($bad -eq 0) {
    Write-Host ("全部通过  {0}/{0}   总耗时 {1}" -f $results.Count, (Format-Duration $total.Elapsed.TotalSeconds)) -ForegroundColor Green
    exit 0
}
Write-Host ("{0} 项未通过  共 {1} 项   总耗时 {2}" -f $bad, $results.Count, (Format-Duration $total.Elapsed.TotalSeconds)) -ForegroundColor Red
exit 1
