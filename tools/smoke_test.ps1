# ============================================================
#  AutoGameTool 冒烟测试
#
#  启动 exe → 校验引擎 HTTP/静态资源接口 → 关闭进程 → 输出 PASS/FAIL
#
#  用法：
#      .\tools\smoke_test.ps1                                   # 测根目录 AutoGameTool.exe
#      .\tools\smoke_test.ps1 -ExePath "$env:LOCALAPPDATA\AutoGameTool\AutoGameTool.exe"
#
#  为什么需要它：PyInstaller --onefile 运行时会把自身解压到 %TEMP%\_MEIxxxx。
#  若当前环境的 %TEMP% 不可写（受限沙箱 / CI），进程会立刻退出并报
#      [PYI-xxxx:ERROR] Failed to extract VCRUNTIME140.dll: ... Permission denied
#  本脚本会把 TEMP/TMP 指向 exe 同级的 .smoketmp 目录来规避该问题，
#  同时用 AUTOGAMETOOL_NO_BROWSER=1 避免测试期间弹出浏览器。
# ============================================================
[CmdletBinding()]
param(
    [string]$ExePath,
    [int]$TimeoutSec = 90
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$Base = 'http://127.0.0.1:8765'

if (-not $ExePath) { $ExePath = Join-Path $root 'AutoGameTool.exe' }
if (-not (Test-Path $ExePath)) { Write-Host "未找到 exe：$ExePath" -ForegroundColor Red; exit 1 }
$ExePath = (Resolve-Path $ExePath).Path

# ---- 让 PyInstaller 有一个可写的解压目录 ----
# PyInstaller --onefile 会在 %TEMP% 下建 _MEIxxxx 子目录并把 DLL 解压进去，
# 因此「能否在子目录里创建文件」才是有效判据（只测目录本身会误判）。
function Test-TempUsable([string]$Dir) {
    if (-not $Dir) { return $false }
    try {
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        $sub = Join-Path $Dir ('_probe_' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $sub -ErrorAction Stop | Out-Null
        Set-Content -Path (Join-Path $sub 'p.txt') -Value 'x' -ErrorAction Stop
        Remove-Item $sub -Recurse -Force -ErrorAction SilentlyContinue
        return $true
    } catch { return $false }
}

$fallbackDir = Join-Path (Split-Path $ExePath -Parent) '.smoketmp'
$tmpDir = $null
foreach ($cand in @($env:TEMP, $env:TMP, $fallbackDir)) {
    if (Test-TempUsable $cand) { $tmpDir = $cand; break }
}

$usedFallback = $false
if (-not $tmpDir) {
    # 环境受限时的兜底：放到 exe 同级，并在结束时清理
    $tmpDir = $fallbackDir
    $usedFallback = $true
} elseif ($tmpDir -eq $fallbackDir) {
    $usedFallback = $true
}
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

$env:TEMP = $tmpDir
$env:TMP  = $tmpDir
$env:AUTOGAMETOOL_NO_BROWSER = '1'

function Clear-SmokeTemp {
    # 清掉本次兜底创建的临时目录，避免污染 exe 所在目录（进而影响卸载后目录能否删除）
    if (-not $usedFallback) { return }
    for ($i = 0; $i -lt 8; $i++) {
        try { Remove-Item $fallbackDir -Recurse -Force -ErrorAction Stop; return }
        catch { Start-Sleep -Milliseconds 400 }
    }
}

function Stop-Engine {
    Get-Process AutoGameTool -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 700
}

$results = New-Object System.Collections.Generic.List[object]
function Add-Result([string]$Name, [bool]$Ok, [string]$Detail) {
    $results.Add([pscustomobject]@{ 项目 = $Name; 结果 = $(if ($Ok) { 'PASS' } else { 'FAIL' }); 说明 = $Detail })
}

Write-Host "=== AutoGameTool 冒烟测试 ===" -ForegroundColor Cyan
Write-Host "  exe：$ExePath"
Write-Host ("  大小：{0:N1} MB" -f ((Get-Item $ExePath).Length / 1MB))
Write-Host ""

# ---------------------------------------------------------- 1. 启动
Stop-Engine
$proc = Start-Process -FilePath $ExePath -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $tmpDir 'stdout.log') `
    -RedirectStandardError  (Join-Path $tmpDir 'stderr.log')

$up = $false
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    try {
        $null = Invoke-RestMethod "$Base/health" -TimeoutSec 2
        $up = $true
        break
    } catch {
        if ($proc.HasExited) { break }
    }
}
$elapsed = [math]::Round(($TimeoutSec - ($deadline - (Get-Date)).TotalSeconds), 1)

Add-Result '进程启动' (-not $proc.HasExited) $(if ($proc.HasExited) { "进程已退出（exit $($proc.ExitCode)）" } else { "pid $($proc.Id)" })
Add-Result '引擎就绪 (/health)' $up $(if ($up) { "${elapsed}s 内监听 $Base" } else { "等待 ${TimeoutSec}s 仍未就绪" })

if (-not $up) {
    Write-Host "--- stdout ---" -ForegroundColor Yellow
    Get-Content (Join-Path $tmpDir 'stdout.log') -ErrorAction SilentlyContinue | Select-Object -Last 20
    Write-Host "--- stderr ---" -ForegroundColor Yellow
    Get-Content (Join-Path $tmpDir 'stderr.log')  -ErrorAction SilentlyContinue | Select-Object -Last 20
    Stop-Engine
    Clear-SmokeTemp
    $results | Format-Table -AutoSize
    Write-Host "结果：FAIL" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------- 2. 接口检查
try {
    $kb = Invoke-RestMethod "$Base/debug/kb" -TimeoutSec 5
    $alive = $null
    if ($kb.PSObject.Properties.Name -contains 'alive') { $alive = $kb.alive }
    Add-Result '/debug/kb 键盘钩子' ($alive -ne $false) "alive=$alive press=$($kb.press) release=$($kb.release)"
} catch { Add-Result '/debug/kb 键盘钩子' $false $_.Exception.Message }

try {
    $w = Invoke-RestMethod "$Base/windows/list" -TimeoutSec 8
    Add-Result '/windows/list 窗口枚举' ($null -ne $w) "$(@($w).Count) 个任务栏窗口"
} catch { Add-Result '/windows/list 窗口枚举' $false $_.Exception.Message }

try {
    $t = Invoke-RestMethod "$Base/vision/templates" -TimeoutSec 8
    Add-Result '/vision/templates 模板列表' ($null -ne $t) "$(@($t).Count) 个模板"
} catch { Add-Result '/vision/templates 模板列表' $false $_.Exception.Message }

try {
    $hk = Invoke-RestMethod "$Base/config/hotkey" -TimeoutSec 5
    Add-Result '/config/hotkey 快捷键' ($null -ne $hk) ($hk | ConvertTo-Json -Compress)
} catch { Add-Result '/config/hotkey 快捷键' $false $_.Exception.Message }

try {
    $body = @{ flow = @{ name = 'smoke'; repeat = 1; input_mode = 'real'; window = $null; nodes = @(); edges = @() } } | ConvertTo-Json -Depth 8
    $fl = Invoke-RestMethod "$Base/flow/load" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 8
    Add-Result 'POST /flow/load 流程装载' ($null -ne $fl) ($fl | ConvertTo-Json -Compress)
} catch { Add-Result 'POST /flow/load 流程装载' $false $_.Exception.Message }

# ---------------------------------------------------------- 3. 内嵌前端资源
try {
    $r = Invoke-WebRequest "$Base/" -TimeoutSec 8 -UseBasicParsing
    $ok = $r.StatusCode -eq 200 -and $r.Content -match 'id="app"'
    Add-Result 'GET / 前端页面' $ok "HTTP $($r.StatusCode), $($r.RawContentLength) bytes"
} catch { Add-Result 'GET / 前端页面' $false $_.Exception.Message }

try {
    $r = Invoke-WebRequest "$Base/favicon.ico" -TimeoutSec 8 -UseBasicParsing
    Add-Result 'GET /favicon.ico 图标' ($r.StatusCode -eq 200) "HTTP $($r.StatusCode), $($r.RawContentLength) bytes"
} catch { Add-Result 'GET /favicon.ico 图标' $false $_.Exception.Message }

# ---------------------------------------------------------- 4. 关闭
Stop-Engine
$left = @(Get-Process AutoGameTool -ErrorAction SilentlyContinue).Count
Add-Result '进程已退出' ($left -eq 0) "残留 $left 个进程"
Clear-SmokeTemp

Write-Host ""
$results | Format-Table -AutoSize
$failed = @($results | Where-Object { $_.结果 -eq 'FAIL' }).Count
if ($failed -eq 0) {
    Write-Host "结果：全部通过（$($results.Count)/$($results.Count)）" -ForegroundColor Green
    exit 0
} else {
    Write-Host "结果：FAIL（$failed 项未通过）" -ForegroundColor Red
    exit 1
}
