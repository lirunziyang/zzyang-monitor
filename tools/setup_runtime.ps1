# 准备运行环境：把 Python 放进 runtime\，之后双击 子漾监测.vbs 就能用
# 用法：powershell -ExecutionPolicy Bypass -File tools\setup_runtime.ps1
#       （或者直接双击 tools\准备运行环境.bat）
param(
    [string]$Version = "3.12.10",
    [switch]$Force,
    [string]$PythonPath = ""
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$target = Join-Path $root 'runtime'

function Say($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }

if ((Test-Path (Join-Path $target 'python.exe')) -and -not $Force) {
    Say "运行环境已就绪：$target" 'Green'
    Say "（想强制重装，加 -Force）"
    exit 0
}

Say "== 准备运行环境 ==" 'Cyan'
Say "目标目录：$target"
Say ""

# ---------- 方式一：复制本机已有的 Python 3.12 ----------
function Copy-LocalPython($exe) {
    Say "发现本机 Python：$exe" 'Yellow'
    $src = Split-Path -Parent $exe
    if (-not (Test-Path (Join-Path $src 'Lib'))) {
        Say "  这个 Python 没有 Lib 目录，跳过（可能是精简版）" 'Yellow'
        return $false
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($f in @('python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll',
                     'vcruntime140.dll', 'vcruntime140_1.dll')) {
        $p = Join-Path $src $f
        if (Test-Path $p) { Copy-Item $p $target -Force }
    }
    # DLLs 与 Lib（跳过 site-packages / test / tkinter，省空间也不影响本程序）
    $dlls = Join-Path $src 'DLLs'
    if (Test-Path $dlls) { Copy-Item $dlls (Join-Path $target 'DLLs') -Recurse -Force }
    $lib = Join-Path $src 'Lib'
    if (Test-Path $lib) {
        $dest = Join-Path $target 'Lib'
        robocopy $lib $dest /E /NFL /NDL /NJH /NJS /NP /XD (Join-Path $lib 'site-packages') `
            (Join-Path $lib 'test') (Join-Path $lib 'idlelib') (Join-Path $lib 'ensurepip') `
            (Join-Path $lib 'tkinter') /XF *.pyc | Out-Null
    }
    return $true
}

function Test-Py312($exe) {
    if (-not $exe) { return $false }
    if (-not (Test-Path $exe)) { return $false }
    if ($exe -like '*\WindowsApps\*') { return $false }   # 商店占位程序，不是真 Python
    try {
        $ver = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        return ($ver -and $ver.Trim() -eq '3.12')
    } catch {
        return $false
    }
}

$candidates = @()
if ($PythonPath) {
    $full = [System.IO.Path]::GetFullPath($PythonPath)
    if (Test-Py312 $full) { $candidates += $full }
    else { Say "指定的 Python 不是 3.12 或路径不对：$PythonPath" 'Red' }
}

try {
    $pyOut = & py -3.12 -c "import sys;print(sys.executable)" 2>$null
    if ($pyOut -and (Test-Py312 $pyOut.Trim())) { $candidates += $pyOut.Trim() }
} catch { }

$guesses = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    'C:\Python312\python.exe',
    (Join-Path $env:ProgramFiles 'Python312\python.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Python312\python.exe')
)
foreach ($g in $guesses) {
    if ($g -and (Test-Py312 $g)) { $candidates += $g }
}

$sysPython = (Get-Command python -ErrorAction SilentlyContinue)
if ($sysPython -and (Test-Py312 $sysPython.Source)) { $candidates += $sysPython.Source }

$candidates = $candidates | Select-Object -Unique

foreach ($c in $candidates) {
    if (Copy-LocalPython $c) {
        $probe = Join-Path $target 'python.exe'
        if (Test-Path $probe) {
            & $probe -c "import sys,sqlite3,json,http.server" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Say ""
                Say "完成：已复制本机 Python 到 $target" 'Green'
                exit 0
            }
        }
        Say "  复制后自检失败，继续尝试其他方式" 'Yellow'
        Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ---------- 方式二：下载官方嵌入式包 ----------
Say "本机没有可用的 Python 3.12，改为下载官方嵌入式版本（约 11MB）。" 'Yellow'
$url = "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"
$zip = Join-Path $env:TEMP "python-$Version-embed-amd64.zip"
$downloaded = $false

# 2.1 curl
if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    Say "  尝试 curl.exe …"
    & curl.exe -L --fail --silent --show-error -o $zip $url 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $zip)) { $downloaded = $true }
}

# 2.2 PowerShell（强制 TLS1.2）
if (-not $downloaded) {
    Say "  尝试 PowerShell 下载 …"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 120
        if (Test-Path $zip) { $downloaded = $true }
    } catch { }
}

# 2.3 任何能用的 Python（不一定是 3.12）拿来下载；只要它能联网就行
$downloader = $null
if ($sysPython -and $sysPython.Source -and $sysPython.Source -notlike '*\WindowsApps\*') {
    $downloader = $sysPython.Source
}
if (-not $downloaded -and $downloader) {
    Say "  尝试用本机 Python 下载 …"
    & $downloader -c "import urllib.request,sys;urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" $url $zip 2>$null
    if (Test-Path $zip) { $downloaded = $true }
}

if (-not $downloaded) {
    Say ""
    Say "自动下载失败（可能是网络或证书问题）。请手动处理：" 'Red'
    Say "  1. 用浏览器打开：$url"
    Say "  2. 把解压出来的所有文件放进：$target"
    Say "  3. 再运行一次本脚本（或直接双击 子漾监测.vbs）"
    exit 1
}

Say "下载完成：$([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB，正在解压 …"
New-Item -ItemType Directory -Force -Path $target | Out-Null
try {
    Expand-Archive -Path $zip -DestinationPath $target -Force
} catch {
    Say "解压失败：$($_.Exception.Message)" 'Red'
    exit 1
}
Remove-Item $zip -Force -ErrorAction SilentlyContinue

$probe = Join-Path $target 'python.exe'
if (-not (Test-Path $probe)) {
    Say "解压后没找到 python.exe，请检查 $target" 'Red'
    exit 1
}
& $probe -c "import sys,sqlite3,json,http.server" 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "运行环境自检失败（缺少标准库模块）" 'Red'
    exit 1
}

Say ""
Say "完成：运行环境已放进 $target" 'Green'
Say "现在双击 子漾监测.vbs 即可启动。"
exit 0
