# 打包成「解压即用」的发布包（含 Python 运行环境）
# 用法：powershell -ExecutionPolicy Bypass -File tools\打包发布.ps1
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

if (-not $OutDir) { $OutDir = Join-Path $root 'release' }

$version = (Get-Content (Join-Path $root 'VERSION') -Raw -Encoding UTF8).Trim()
$name = "子漾监测-$version-win64"
$stage = Join-Path $OutDir $name
$zipPath = Join-Path $OutDir "zzyang-monitor-$version-win64.zip"

Write-Host "== 打包 $name ==" -ForegroundColor Cyan

# 1. 运行环境必须存在
$runtime = Join-Path $root 'runtime'
if (-not (Test-Path (Join-Path $runtime 'python.exe'))) {
    throw "找不到 runtime\python.exe。先运行 tools\setup_runtime.ps1 准备运行环境。"
}

# 2. 重新编译窗口宿主（程序正开着时 exe 被占用，退回用现有的）
$distExe = Join-Path $root 'host\dist\ZzyangMonitor.exe'
try {
    & (Join-Path $root 'host\build.ps1')
    if ($LASTEXITCODE -ne 0) { throw '编译返回非零' }
} catch {
    if (Test-Path $distExe) {
        Write-Host "  宿主正被占用，沿用现有编译产物" -ForegroundColor Yellow
    } else {
        throw "编译失败，且没有可用的 $distExe"
    }
}

# 3. 准备目录
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# 4. 复制内容
$items = @(
    'app.py', 'VERSION', 'LICENSE', 'README.md', '使用说明.txt',
    '子漾监测.vbs', '调试启动.bat',
    'core', 'ui', 'tools', 'host', 'vendor', 'runtime'
)
foreach ($item in $items) {
    $src = Join-Path $root $item
    if (-not (Test-Path $src)) {
        Write-Host "  跳过（不存在）：$item" -ForegroundColor Yellow
        continue
    }
    $dst = Join-Path $stage $item
    if ((Get-Item $src).PSIsContainer) {
        robocopy $src $dst /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ /XF *.pyc | Out-Null
    } else {
        Copy-Item $src $dst -Force
    }
}

# 5. 清掉发布包里不该有的东西
foreach ($junk in @('data', 'tests')) {
    $p = Join-Path $stage $junk
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

# 6. 压缩
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $stage -DestinationPath $zipPath -CompressionLevel Optimal

$size = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
$files = (Get-ChildItem $stage -Recurse -File | Measure-Object).Count
Write-Host ""
Write-Host "完成：$zipPath" -ForegroundColor Green
Write-Host "  版本 $version · $files 个文件 · 压缩后 $size MB"
Write-Host "  解压后双击 子漾监测.vbs 即可运行"
