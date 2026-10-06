# ============================================================
#  AutoTool 一键打包脚本
#  1) 构建前端（vue-tsc 类型检查 + vite build）
#  2) PyInstaller 打包为单文件 exe（内嵌前端静态资源 + 应用图标）
#  3) 复制到项目根目录
# ============================================================
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# ---------- 0. 应用图标（缺失时自动生成） ----------
$icon = Join-Path $root "assets\AutoTool.ico"
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
# 走 `python -m PyInstaller`，**不要**用 `engine\.venv\Scripts\pyinstaller.exe`：
# venv 里的控制台启动器（pyinstaller.exe / pip.exe / uvicorn.exe / fastapi.exe …）是 pip 生成的
# PE 包装器，尾部内嵌了绝对 shebang `#!<venv>\Scripts\python.exe` —— 工程一旦换目录就全部失效
# （2026-10-03 迁移时实测：Scripts\ 下 31 个文件有 25 个指向旧路径）。
# 而 `Scripts\python.exe` 本身不内嵌任何路径（运行时按 pyvenv.cfg 定位），换目录照样能用。
# 详见 AGENTS.local.md 第六节。
Write-Host "=== 2. PyInstaller 打包 ===" -ForegroundColor Cyan
$py = Join-Path $root "engine\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "未找到虚拟环境解释器：$py" -ForegroundColor Red
    Write-Host "先重建 venv，见 AGENTS.local.md 第六节" -ForegroundColor Red
    exit 1
}

$dist = Join-Path $root "frontend\dist"
if (-not (Test-Path (Join-Path $dist "index.html"))) {
    Write-Host "前端产物缺失：$dist\index.html" -ForegroundColor Red
    exit 1
}

Push-Location (Join-Path $root "engine")
try {
    # --noconsole（= --windowed）：不创建控制台窗口。两个理由：
    #   1) 那是个可以被点掉的窗口 —— 流程回放是「真实输入 + 绝对坐标点击」，
    #      脚本完全可能点到它自己的控制台 ✕ 上，把后端当场杀掉（v0.7.2 事故的可疑成因之一）；
    #   2) 挂机时它还会抢屏幕/焦点。
    # 代价：stdout/stderr 不再存在，**所有输出只进 %APPDATA%\AutoTool\engine.log**
    #（engine/enginelog.py 会接管 sys.stdout/stderr，所以原有的 print 不会抛异常）。
    $pyiArgs = @(
        "--noconfirm", "--clean", "--onedir", "--noconsole", "--name", "AutoTool",
        # --onedir（v0.8.2 起）：不再往 %TEMP% 解压。为什么必须换掉 --onefile：
        # 单文件版每次启动都要在 %TEMP% 下解开 _MEIxxxx；一旦启动进程的 %TEMP% 不可用
        # （被删掉、或环境异常，例如从 SmartScreen 点「仍要运行」拉起时），Windows 的
        # GetTempPath 会退回「当前目录」（那时往往是 System32）→ 解压失败 →
        # 弹 "could not create temporary directory"，进程挂在错误框上不放，
        # 还顺带锁死安装目录里的 exe，导致升级安装报「无法打开要写入的文件」。
        # 文件夹形态没有解压这一步，从根上消除这类故障，启动也更快。
        "--add-data", "$dist;frontend_dist",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on"
    )
    if ($icon) { $pyiArgs += @("--icon", $icon) }
    $pyiArgs += "main.py"

    & $py -m PyInstaller @pyiArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（exit $LASTEXITCODE）" }
} finally {
    Pop-Location
}

# ---------- 3. 复制到根目录 ----------
# v0.8.2 起改成 --onedir（文件夹形态）：不再需要往 %TEMP% 解压，因此
# 「%TEMP% 不可用 / 从 SmartScreen 点『仍要运行』拉起」这类环境问题一律不再影响启动。
# 代价是不能再单独复制 AutoTool.exe 走天下——必须整目录一起分发（安装包已处理好）。
$builtDir = Join-Path $root "engine\dist\AutoTool"
$appDir = Join-Path $root "AutoTool-app"
if (-not (Test-Path (Join-Path $builtDir "AutoTool.exe"))) {
    Write-Host "打包产物缺失：$builtDir\AutoTool.exe" -ForegroundColor Red
    exit 1
}
# 旧版残留的单文件 exe 会让「双击哪个」变得含糊，直接清掉
Remove-Item (Join-Path $root "AutoTool.exe") -Force -ErrorAction SilentlyContinue
if (Test-Path $appDir) { Remove-Item $appDir -Recurse -Force -ErrorAction SilentlyContinue }
Copy-Item $builtDir $appDir -Recurse -Force

$size = [math]::Round(((Get-ChildItem $appDir -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host ""
Write-Host "打包完成：$(Join-Path $appDir 'AutoTool.exe')  (整目录 $size MB)" -ForegroundColor Green
Write-Host "下一步可执行 .\build_desktop.ps1 -SkipEngine 生成安装包。" -ForegroundColor DarkGray
