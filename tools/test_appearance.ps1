# ============================================================
#  外观（浅色 / 深色 / 跟随系统）判定回归测试（frontend/src/lib/appearance.ts）
#
#  为什么需要：这里出错的表现是「选了浅色还是黑的」「跟随系统时系统切了主题界面不跟着变」
#  「升级后默认外观被改掉」——都不容易靠肉眼覆盖，而判定逻辑本身只有几行。
#
#  用法：
#      .\tools\test_appearance.ps1
# ============================================================
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

$tsc  = Join-Path $root 'frontend\node_modules\typescript\bin\tsc'
$src  = Join-Path $root 'frontend\src\lib\appearance.ts'
$test = Join-Path $PSScriptRoot 'test_appearance.js'
$out  = Join-Path $PSScriptRoot '.appearance_build'

if (-not (Test-Path $tsc)) {
    Write-Host "未找到 TypeScript，请先执行：cd frontend; pnpm install" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $src)) {
    Write-Host "未找到被测源码：$src" -ForegroundColor Red
    exit 1
}

if (Test-Path $out) { Remove-Item $out -Recurse -Force }

Write-Host "=== 1. 编译 appearance.ts ===" -ForegroundColor Cyan
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
