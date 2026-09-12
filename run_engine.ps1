# AutoGameTool 引擎启动脚本
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py = Join-Path $root "engine\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "未找到引擎虚拟环境，请先执行："
    Write-Host "  cd engine"
    Write-Host "  py -3.13 -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install -r requirements.txt"
    exit 1
}
Set-Location (Join-Path $root "engine")
# 开发模式：放行 vite 1420 端口 CORS 并跳过令牌校验（v0.3.0 起默认开令牌鉴权）
$env:AUTOGAMETOOL_DEV = '1'
$env:AUTOGAMETOOL_NO_BROWSER = '1'
Write-Host "引擎启动中：http://127.0.0.1:8765 （开发模式，免令牌）"
& $py -m uvicorn main:app --host 127.0.0.1 --port 8765
