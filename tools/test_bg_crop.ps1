# ============================================================
#  背景「按屏幕比例截取」几何回归测试（frontend/src/lib/bgCrop.ts）
#
#  为什么需要：自定义背景是"所见即所得"——界面里显示的取景结果，必须和导出到
#  canvas 的裁剪区域完全一致。这类几何偏差差几个像素肉眼根本看不出来，
#  但会导致存下来的背景和预览不一样（或者边缘露白）。所以把几何算法抽成纯函数
#  并用断言把"必须完全覆盖取景框""平移必须被夹住""等比缩放不变性"钉死。
#
#  用法：
#      .\tools\test_bg_crop.ps1
# ============================================================
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

$tsc  = Join-Path $root 'frontend\node_modules\typescript\bin\tsc'
$src  = Join-Path $root 'frontend\src\lib\bgCrop.ts'
$test = Join-Path $PSScriptRoot 'test_bg_crop.js'
$out  = Join-Path $PSScriptRoot '.bg_crop_build'

if (-not (Test-Path $tsc)) {
    Write-Host "未找到 TypeScript，请先执行：cd frontend; pnpm install" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $src)) {
    Write-Host "未找到被测源码：$src" -ForegroundColor Red
    exit 1
}

if (Test-Path $out) { Remove-Item $out -Recurse -Force }

Write-Host "=== 1. 编译 bgCrop.ts ===" -ForegroundColor Cyan
& node $tsc $src --target es2020 --module commonjs --moduleResolution node --outDir $out --skipLibCheck
if ($LASTEXITCODE -ne 0) { throw "编译失败（exit $LASTEXITCODE）" }

Write-Host "=== 2. 执行断言 ===" -ForegroundColor Cyan
& node $test
$code = $LASTEXITCODE

# 产物只是中间物，跑完即清（避免污染仓库）
if (Test-Path $out) { Remove-Item $out -Recurse -Force }

if ($code -ne 0) {
    Write-Host "结果：FAIL（exit $code）" -ForegroundColor Red
    exit $code
}
Write-Host "结果：全部通过" -ForegroundColor Green
