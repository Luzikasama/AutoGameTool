# ============================================================
#  AutoGameTool 一键打包脚本
#  1) 构建前端（vue-tsc 类型检查 + vite build）
#  2) PyInstaller 打包为单文件 exe（内嵌前端静态资源 + 应用图标）
#  3) 复制到项目根目录
# ============================================================
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# ---------- 0. 应用图标（缺失时自动生成） ----------
$icon = Join-Path $root "assets\AutoGameTool.ico"
if (-not (Test-Path $icon)) {
    Write-Host "=== 0. 生成应用图标 ===" -ForegroundColor Cyan
    $py = Join-Path $root "engine\.venv\Scripts\python.exe"
    if (Test-Path $py) { & $py (Join-Path $root "tools\make_icon.py") }
    if (-not (Test-Path $icon)) { Write-Host "图标生成失败，将使用默认图标" -ForegroundColor Yellow; $icon = $null }
}
if ($icon) { Write-Host "应用图标：$icon" -ForegroundColor DarkGray }

# ---------- 1. 构建前端 ----------
Write-Host "=== 1. 构建前端 ===" -ForegroundColor Cyan
$fe = Join-Path $root "frontend"
$bin = Join-Path $fe "node_modules\.bin"
if (-not (Test-Path (Join-Path $bin "vite.CMD"))) {
    Write-Host "未找到前端依赖，请先执行：" -ForegroundColor Red
    Write-Host "  cd frontend; pnpm install"
    exit 1
}

Push-Location $fe
try {
    # 说明：这里刻意不走 `pnpm build`。pnpm 11 在执行 script 前会做依赖状态检查，
    # 无 TTY 时会因需要清理 node_modules 而直接中止
    # （ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY）。直接调用本地二进制更快更稳，
    # 且无需联网。两步与 `pnpm build` 等价：vue-tsc 类型检查 + vite 构建。
    & (Join-Path $bin "vue-tsc.CMD") --noEmit
    if ($LASTEXITCODE -ne 0) { throw "前端类型检查失败（exit $LASTEXITCODE）" }

    # 静态检查：<n-xxx> 用到了却没 import 的话，组件会被静默丢掉、按钮直接消失，
    # 而 vue-tsc / vite 都不会报错（v0.7.1 真踩过），所以必须在构建期拦住。
    & node (Join-Path $root "tools\check_ui_imports.mjs") "src"
    if ($LASTEXITCODE -ne 0) { throw "UI 组件导入检查失败（exit $LASTEXITCODE）" }

    & (Join-Path $bin "vite.CMD") build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败（exit $LASTEXITCODE）" }
} finally {
    Pop-Location
}

# ---------- 2. PyInstaller 打包 ----------
Write-Host "=== 2. PyInstaller 打包 ===" -ForegroundColor Cyan
$pyi = Join-Path $root "engine\.venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyi)) {
    Write-Host "未找到 PyInstaller，请先安装：" -ForegroundColor Red
    Write-Host "  engine\.venv\Scripts\python -m pip install pyinstaller"
    exit 1
}

$dist = Join-Path $root "frontend\dist"
if (-not (Test-Path (Join-Path $dist "index.html"))) {
    Write-Host "前端产物缺失：$dist\index.html" -ForegroundColor Red
    exit 1
}

Push-Location (Join-Path $root "engine")
try {
    $pyiArgs = @(
        "--noconfirm", "--clean", "--onefile", "--name", "AutoGameTool",
        "--add-data", "$dist;frontend_dist",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on"
    )
    if ($icon) { $pyiArgs += @("--icon", $icon) }
    $pyiArgs += "main.py"

    & $pyi @pyiArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（exit $LASTEXITCODE）" }
} finally {
    Pop-Location
}

# ---------- 3. 复制到根目录 ----------
$built = Join-Path $root "engine\dist\AutoGameTool.exe"
Copy-Item $built (Join-Path $root "AutoGameTool.exe") -Force

$size = [math]::Round((Get-Item $built).Length / 1MB, 1)
Write-Host ""
Write-Host "打包完成：$(Join-Path $root 'AutoGameTool.exe')  ($size MB)" -ForegroundColor Green
Write-Host "下一步可执行 .\build_installer.ps1 生成安装包。" -ForegroundColor DarkGray
