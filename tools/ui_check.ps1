# 界面自检：起服务 → 开无头浏览器 → 跑一遍真实交互 → 读回结果
# 全程用 PowerShell 启动浏览器，避免从受限的 Python 子进程里拉浏览器导致页面加载不出来
$ErrorActionPreference = 'Continue'

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$root   = Split-Path -Parent $here
$py     = Join-Path $root 'runtime\python.exe'
$app    = Join-Path $root 'app.py'
$result = Join-Path $root 'data\uitest.json'
$prof   = Join-Path $root 'data\.ui_profile'
$log    = Join-Path $root 'data\_serve.out'

$edge = @(
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $edge) {
  Write-Host '!! 找不到 Edge/Chrome，无法做界面自检' -ForegroundColor Red
  exit 1
}

if (Test-Path $result) { Remove-Item $result -Force }
if (Test-Path $log)    { Remove-Item $log -Force }
if (Test-Path $prof)   { Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $prof | Out-Null

$srv = Start-Process -FilePath $py -ArgumentList @($app, '--serve') -PassThru -WindowStyle Hidden -RedirectStandardOutput $log
$url = $null
for ($i = 0; $i -lt 100; $i++) {
  Start-Sleep -Milliseconds 200
  if (Test-Path $log) {
    $line = Get-Content $log -ErrorAction SilentlyContinue | Where-Object { $_ -like 'http://*' } | Select-Object -First 1
    if ($line) { $url = $line.Trim(); break }
  }
}
if (-not $url) {
  Write-Host '!! 服务没有启动' -ForegroundColor Red
  if ($srv -and -not $srv.HasExited) { Stop-Process -Id $srv.Id -Force }
  exit 1
}

$args_list = @('--headless=new', '--disable-gpu', '--no-first-run', "--user-data-dir=$prof", "$url#diag?selftest=1")
Start-Process -FilePath $edge -ArgumentList $args_list

$data = $null
for ($i = 0; $i -lt 110; $i++) {
  Start-Sleep -Milliseconds 400
  if (Test-Path $result) {
    try { $data = Get-Content $result -Raw -Encoding UTF8 | ConvertFrom-Json; break } catch { }
  }
}

Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*$prof*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if ($srv -and -not $srv.HasExited) { Stop-Process -Id $srv.Id -Force }
Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $log -Force -ErrorAction SilentlyContinue

if (-not $data) {
  Write-Host '!! 没有拿到自检结果（页面可能没跑完）' -ForegroundColor Red
  Write-Host '   如果你是在受限环境里运行，请改用普通桌面窗口执行本脚本。'
  exit 1
}

$failed = @($data.results | Where-Object { -not $_.ok })
Write-Host ''
Write-Host "== 界面自检 == $($data.at)" -ForegroundColor Cyan
foreach ($r in $data.results) {
  $mark = if ($r.ok) { '  ' } else { '!!' }
  $word = if ($r.ok) { 'OK  ' } else { 'FAIL' }
  $color = if ($r.ok) { 'Gray' } else { 'Red' }
  Write-Host ("{0} {1,-16} {2}  {3}" -f $mark, $r.name, $word, $r.detail) -ForegroundColor $color
}
Write-Host ''
if ($failed.Count -eq 0 -and $data.results.Count -gt 0) {
  Write-Host "RESULT: PASS  ($($data.results.Count) 项)" -ForegroundColor Green
  exit 0
} else {
  Write-Host "RESULT: FAIL  ($($data.results.Count) 项，失败 $($failed.Count))" -ForegroundColor Red
  exit 1
}
