# ============================================================
#  AutoGameTool 安装包构建脚本（NSIS）
#
#  前置：先生成 AutoGameTool.exe（.\build_exe.ps1）
#  产物：AutoGameTool-Setup.exe
#
#  安装包特性：免管理员（装到 %LOCALAPPDATA%\AutoGameTool）、
#  开始菜单 + 桌面快捷方式、标准卸载入口、升级自动卸载旧版、支持 /S 静默安装
# ============================================================
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$NSIS_VERSION = "3.10"
$NSIS_URLS = @(
    "https://sourceforge.net/projects/nsis/files/NSIS%203/$NSIS_VERSION/nsis-$NSIS_VERSION.zip/download",
    "https://downloads.sourceforge.net/project/nsis/NSIS%203/$NSIS_VERSION/nsis-$NSIS_VERSION.zip"
)

function Get-Makensis {
    <# 依次在：环境变量 → PATH → 项目内置 tools\nsis → 系统安装目录 中查找 makensis.exe #>
    $candidates = @()
    if ($env:AUTOGAMETOOL_MAKENSIS) { $candidates += $env:AUTOGAMETOOL_MAKENSIS }
    $cmd = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $candidates += @(
        (Join-Path $root "tools\nsis\makensis.exe"),
        (Join-Path $root "tools\nsis\Bin\makensis.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"),
        (Join-Path $env:ProgramFiles "NSIS\makensis.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return $null
}

function Install-Nsis {
    <# 自动下载并解压 NSIS 到 tools\nsis #>
    $dest = Join-Path $root "tools\nsis"
    $zip = Join-Path $root "tools\nsis-$NSIS_VERSION.zip"
    $ok = $false

    foreach ($url in $NSIS_URLS) {
        try {
            Write-Host "  下载 $url" -ForegroundColor DarkGray
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 300
            if ((Get-Item $zip).Length -gt 500000) { $ok = $true; break }
            Write-Host "  文件过小，疑似失败" -ForegroundColor DarkYellow
        } catch {
            Write-Host "  失败：$($_.Exception.Message)" -ForegroundColor DarkYellow
        }
    }
    if (-not $ok) {
        throw "NSIS 自动下载失败。请手动安装 NSIS 3.x（https://nsis.sourceforge.io/），或设置环境变量 AUTOGAMETOOL_MAKENSIS 指向 makensis.exe。"
    }

    $tmp = Join-Path $root "tools\_nsis_unpack"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $inner) { throw "NSIS 压缩包结构异常：$zip" }
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Move-Item $inner.FullName $dest
    Remove-Item $tmp -Recurse -Force
    Remove-Item $zip -Force

    $mk = Join-Path $dest "makensis.exe"
    if (-not (Test-Path $mk)) { throw "解压后未找到 makensis.exe" }
    return $mk
}

# ---------------------------------------------------------------- 1. 前置检查
Write-Host "=== 1. 检查输入 ===" -ForegroundColor Cyan

$exe  = Join-Path $root "AutoGameTool.exe"
$icon = Join-Path $root "assets\AutoGameTool.ico"
$nsi  = Join-Path $root "installer\AutoGameTool.nsi"
$out  = Join-Path $root "AutoGameTool-Setup.exe"

if (-not (Test-Path $exe)) {
    Write-Host "未找到 AutoGameTool.exe，请先执行：.\build_exe.ps1" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $nsi)) {
    Write-Host "未找到安装脚本：$nsi" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $icon)) {
    Write-Host "未找到图标，正在生成 ..." -ForegroundColor Yellow
    $py = Join-Path $root "engine\.venv\Scripts\python.exe"
    if (Test-Path $py) { & $py (Join-Path $root "tools\make_icon.py") }
}
if (-not (Test-Path $icon)) {
    Write-Host "未找到图标：$icon" -ForegroundColor Red
    exit 1
}

Write-Host ("  主程序：{0}  ({1} MB)" -f (Split-Path $exe -Leaf), [math]::Round((Get-Item $exe).Length / 1MB, 1))

# ---------------------------------------------------------------- 2. 查找 NSIS
Write-Host "=== 2. 查找 NSIS (makensis) ===" -ForegroundColor Cyan
$makensis = Get-Makensis
if (-not $makensis) {
    Write-Host "  未找到 makensis.exe，尝试自动下载 NSIS $NSIS_VERSION ..." -ForegroundColor Yellow
    $makensis = Install-Nsis
}
Write-Host "  makensis：$makensis" -ForegroundColor DarkGray
Write-Host "  版本：$(& $makensis /VERSION)" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 3. 生成安装包
Write-Host "=== 3. 生成安装包（LZMA 压缩，可能需要 1-3 分钟）===" -ForegroundColor Cyan

if (Test-Path $out) { Remove-Item $out -Force }

# 注意：NSIS 3 的 Icon / File / OutFile 相对路径以「.nsi 所在目录」为基准，
# 而不是 makensis 的当前工作目录，因此这里用 /D 把绝对路径传进去。
# /D 必须放在脚本文件名之前，且写法是 /D名称=值
& $makensis /V3 "/DPROJECT_ROOT=$root" "/DOUT_DIR=$root" $nsi
if ($LASTEXITCODE -ne 0) { throw "makensis 构建失败（exit $LASTEXITCODE）" }

if (-not (Test-Path $out)) { throw "未生成安装包：$out" }

# ---------------------------------------------------------------- 4. 结果
$size = [math]::Round((Get-Item $out).Length / 1MB, 1)
$hash = (Get-FileHash $out -Algorithm SHA256).Hash

Write-Host ""
Write-Host "安装包已生成：$out" -ForegroundColor Green
Write-Host "  大小：$size MB" -ForegroundColor Green
Write-Host "  SHA256：$hash" -ForegroundColor DarkGray
Write-Host ""
Write-Host "安装包行为：" -ForegroundColor DarkGray
Write-Host "  安装目录：%LOCALAPPDATA%\AutoGameTool（免管理员）" -ForegroundColor DarkGray
Write-Host "  快捷方式：开始菜单 + 桌面" -ForegroundColor DarkGray
Write-Host "  卸载入口：设置 → 应用 → 已安装的应用" -ForegroundColor DarkGray
Write-Host "  用户数据：%APPDATA%\AutoGameTool（模板/配置，卸载默认保留）" -ForegroundColor DarkGray
