# ============================================================
#  录制拆分算法回归测试（frontend/src/lib/macroSplit.ts）
#
#  为什么需要：录制拆分（「键鼠录制」节点 → ✂ 拆分为可编辑步骤）的合并规则
#  有几处容易写错的边界 —— 组合键的结算时机、同名修饰键连续配多个键等。
#  该模块刻意写成不依赖 Vue 的纯函数，因此可以脱离浏览器单独跑断言。
#
#  做法：用前端自带的 tsc 把 macroSplit.ts 编成 CommonJS 到 tools\.macro_split_build，
#  再用 node 执行 tools\test_macro_split.js 里的 15 条断言。
#
#  用法：
#      .\tools\test_macro_split.ps1
# ============================================================
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

$tsc  = Join-Path $root 'frontend\node_modules\typescript\bin\tsc'
$src  = Join-Path $root 'frontend\src\lib\macroSplit.ts'
$test = Join-Path $PSScriptRoot 'test_macro_split.js'
$out  = Join-Path $PSScriptRoot '.macro_split_build'

if (-not (Test-Path $tsc)) {
    Write-Host "未找到 TypeScript，请先执行：cd frontend; pnpm install" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $src)) {
    Write-Host "未找到被测源码：$src" -ForegroundColor Red
    exit 1
}

if (Test-Path $out) { Remove-Item $out -Recurse -Force }

Write-Host "=== 1. 编译 macroSplit.ts ===" -ForegroundColor Cyan
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
