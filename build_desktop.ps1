# AutoGameTool 桌面版构建（Tauri 2 + Python sidecar）
#
# 步骤：
#   1. 前端构建（vue-tsc + vite build）
#   2. 引擎打包成 onedir（AutoGameTool-app\，复用 build_exe.ps1 的 PyInstaller 部分）
#   3. tauri build：壳 + 把 AutoGameTool-app\ 作为 resources 一起塞进安装包
#
# 为什么引擎用 onedir（而不是 onefile）：
#   onefile 每次启动都要往 %TEMP% 解压，%TEMP% 一旦不可用就会弹
#   "could not create temporary directory"（v0.8.2 修过的老问题）；
#   onedir 没有解压这一步，启动更快，也不再依赖临时目录。
#
# 用法：
#   .\build_desktop.ps1              # 完整构建（含 NSIS 安装包）
#   .\build_desktop.ps1 -SkipEngine  # 只重建壳（引擎产物已存在时）
param(
    [switch]$SkipEngine
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

# 构建期工具（makensis / cargo / node）在受限会话里对临时目录挑剔：
# 统一把 TEMP 指到工作区内，避免 "error creating mmap" 这类环境性失败。
$buildTmp = Join-Path $root '.tmp\build-temp'
New-Item -ItemType Directory -Force -Path $buildTmp | Out-Null
$env:TEMP = $buildTmp
$env:TMP = $buildTmp
# Rust 产物放工作区（E: 空间充足），避免把 C: 撑满
if (-not $env:CARGO_TARGET_DIR) {
    $env:CARGO_TARGET_DIR = Join-Path $root '.tmp\cargo-target'
}
# pnpm 在「没有 TTY」的脚本环境里会因「是否清空 node_modules」的交互确认直接中止
# （ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY）；CI=true 等价于关掉那个确认。
$env:CI = 'true'

function Step($n, $text) { Write-Host "=== $n. $text ===" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 1. 前端
Step 1 '前端构建（类型检查 + vite build）'
Push-Location (Join-Path $root 'frontend')
try {
    # 外部命令（pnpm / cargo / tauri）都会往 stderr 写进度；本脚本 EAP=Stop 时
    # PowerShell 会把那当成终止性错误。执行期间临时放宽，之后按退出码判断。
    $ErrorActionPreference = 'Continue'
    & pnpm.cmd build
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0) { throw "前端构建失败（exit $code）" }
} finally { Pop-Location }

# ---------------------------------------------------------------- 2. 引擎
if ($SkipEngine -and (Test-Path (Join-Path $root 'AutoGameTool-app\AutoGameTool.exe'))) {
    Step 2 '引擎打包（已存在，跳过）'
} else {
    Step 2 '引擎打包（PyInstaller onedir → AutoGameTool-app\）'
    & (Join-Path $root 'build_exe.ps1')
    if ($LASTEXITCODE -ne 0) { throw "引擎打包失败（exit $LASTEXITCODE）" }
}
$engineDir = Join-Path $root 'AutoGameTool-app'
if (-not (Test-Path (Join-Path $engineDir 'AutoGameTool.exe'))) {
    throw "缺少引擎产物：$engineDir\AutoGameTool.exe"
}

# ---------------------------------------------------------------- 3. 壳 + 安装包
Step 3 'Tauri 构建（壳 + 引擎作为 resources + NSIS 安装包）'
Push-Location (Join-Path $root 'frontend')
try {
    $ErrorActionPreference = 'Continue'   # cargo/tauri 的 stderr 进度输出同上
    & pnpm.cmd tauri build
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0) { throw "Tauri 构建失败（exit $code）" }
} finally { Pop-Location }

# ---------------------------------------------------------------- 4. 汇总
$nsis = Get-ChildItem $env:CARGO_TARGET_DIR -Recurse -Filter '*setup.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$shell = Get-ChildItem $env:CARGO_TARGET_DIR -Recurse -Filter 'autogametool.exe' -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\release\\' } | Select-Object -First 1

Write-Host ''
if ($shell) {
    Write-Host ("桌面壳：{0}  ({1} MB)" -f $shell.FullName, [math]::Round($shell.Length / 1MB, 1)) -ForegroundColor Green
}
if ($nsis) {
    $hash = (Get-FileHash $nsis.FullName -Algorithm SHA256).Hash
    Write-Host ("安装包：{0}  ({1} MB)" -f $nsis.FullName, [math]::Round($nsis.Length / 1MB, 1)) -ForegroundColor Green
    Write-Host ("SHA256：{0}" -f $hash) -ForegroundColor DarkGray
} else {
    Write-Host '未找到 NSIS 安装包（tauri build 可能只产出了 exe）' -ForegroundColor Yellow
}
