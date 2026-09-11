# ============================================================
#  AutoGameTool 前端开发服务器
#  说明：这里直接调用本地 Vite，而不是 `pnpm dev`。
#        pnpm 11 在执行 script 前会做依赖状态检查，无 TTY 时会因需要
#        清理 node_modules 而直接中止
#        （ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY）。
#  默认地址：http://localhost:1420
# ============================================================
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$fe = Join-Path $root "frontend"
$vite = Join-Path $fe "node_modules\.bin\vite.CMD"

if (-not (Test-Path $vite)) {
    Write-Host "未找到前端依赖，请先执行：" -ForegroundColor Red
    Write-Host "  cd frontend"
    Write-Host "  pnpm install"
    exit 1
}

Write-Host "启动前端开发服务器：http://localhost:1420" -ForegroundColor Cyan
Write-Host "（按 Ctrl+C 停止）" -ForegroundColor DarkGray

Push-Location $fe
try {
    & $vite
} finally {
    Pop-Location
}
