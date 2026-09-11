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
Write-Host "引擎启动中：http://127.0.0.1:8765"
& $py -m uvicorn main:app --host 127.0.0.1 --port 8765
