# 回归测试：%TEMP% 不可用时，打包好的 AutoGameTool 仍然必须能启动
#
# 为什么要有这个测试（v0.8.2 的真实事故）：
#   PyInstaller --onefile 会在 %TEMP% 下解压出 _MEIxxxx 目录。如果启动进程的 %TEMP%
#   不可用（被删掉、或环境异常），Windows 的 GetTempPath 会**退回当前目录**；从资源管理器
#   双击（尤其经过 SmartScreen「仍要运行」）时当前目录往往是 System32 —— 于是解压失败，
#   弹出 "could not create temporary directory"，进程还挂在 MessageBox 上不放，
#   顺带锁死安装目录里的 exe，导致升级安装报「无法打开要写入的文件」。
#   修法是在打包时用 --runtime-tmpdir 把解压目录写死，不再看 %TEMP%。
#
# 这个脚本就是那条链路的守门人：故意把 TEMP/TMP 指到一个**不存在**的目录，
# 然后要求程序照样起来。用旧构建跑它必然会失败（这本身就是它的有效性证明）。
#
# 用法：
#   .\tools\test_broken_temp.ps1
#   .\tools\test_broken_temp.ps1 -ExePath 'E:\Apps\AutoGameTool\AutoGameTool.exe'   # 对照旧构建
param(
    [string]$ExePath = '',
    [int]$TimeoutSec = 40
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path $PSScriptRoot -Parent
if (-not $ExePath) {
    # v0.8.2 起是文件夹形态，优先测 AutoGameTool-app\ 下的（仍兼容根目录单文件 exe）
    $appExe = Join-Path $Root 'AutoGameTool-app\AutoGameTool.exe'
    $ExePath = if (Test-Path $appExe) { $appExe } else { Join-Path $Root 'AutoGameTool.exe' }
}
$Base = 'http://127.0.0.1:8765'
$Token = 'broken-temp-test-token'
$Broken = 'C:\__agt_no_such_temp_dir__'

$pass = 0; $fail = 0
function Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    if ($Ok) { $script:pass++; Write-Host ("  PASS  " + $Name) -ForegroundColor Green }
    else { $script:fail++; Write-Host ("  FAIL  " + $Name + $(if ($Detail) { "  -> $Detail" } else { '' })) -ForegroundColor Red }
}

function Stop-Engines {
    Get-Process AutoGameTool -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

Write-Host '=== 打包产物：%TEMP% 不可用时的启动回归 ===' -ForegroundColor Cyan
Write-Host ("  exe：{0}" -f $ExePath)
if (-not (Test-Path $ExePath)) { Write-Host "找不到 exe" -ForegroundColor Red; exit 1 }

Stop-Engines
# 必须先确认端口是空的：否则 /health 可能是上一个残留实例应答的，测试会假通过
$portBusy = [bool](netstat -ano | Select-String ':8765' | Select-String 'LISTENING')
Check '测试开始前 8765 端口空闲' (-not $portBusy) '有残留实例占着端口，请先结束它再跑'
if ($portBusy) { exit 1 }

$tmpLog = Join-Path $env:LOCALAPPDATA 'Temp'
$before = @(Get-ChildItem $tmpLog -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue).Count
# 日志只看本轮新增的部分（否则上一轮留下的「引擎就绪」会让断言假通过）
$mark = 0
$logPath = Join-Path $env:APPDATA 'AutoGameTool\engine.log'
if (Test-Path $logPath) { $mark = (Get-Item $logPath).Length }

# 故意把临时目录指到一个不存在的路径（这就是用户机器上那种"环境异常"）
$env:TEMP = $Broken
$env:TMP = $Broken
$env:AUTOGAMETOOL_NO_BROWSER = '1'
$env:AUTOGAMETOOL_TOKEN = $Token
Write-Host ("  故意把 TEMP/TMP 设为：{0}（不存在）" -f $Broken)

$proc = Start-Process -FilePath $ExePath -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Root '.tmp\broken-temp-out.log') `
    -RedirectStandardError  (Join-Path $Root '.tmp\broken-temp-err.log') -ErrorAction SilentlyContinue
if (-not $proc) { $proc = Start-Process -FilePath $ExePath -PassThru -WindowStyle Hidden }

Check '进程启动' (-not $proc.HasExited) ("pid " + $proc.Id)

$ver = ''
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    try { $ver = (Invoke-RestMethod "$Base/health" -TimeoutSec 2).version; break } catch { if ($proc.HasExited) { break } }
}
Check ("TEMP 不可用时 {0} 秒内 /health 仍就绪" -f $TimeoutSec) ([bool]$ver) '（单文件旧构建会在这里失败：could not create temporary directory）'
Check '引擎版本号正确' ($ver -match '^\d+\.\d+\.\d+$') ("version=" + $ver)
Check '进程没有卡在错误框上' (-not $proc.HasExited) ("exit " + $proc.ExitCode)

# 文件夹形态（v0.8.2 起）根本不解压：这里只要求"没有新增解压目录、也没在坏路径留东西"
$after = @(Get-ChildItem $tmpLog -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue).Count
Check '没有在坏掉的 TEMP 路径下留下任何东西' (-not (Test-Path $Broken))
Check '没有产生新的解压目录（文件夹形态无需解压）' ($after -le $before) ("之前 {0} 个，现在 {1} 个" -f $before, $after)

Stop-Engines
$left = @(Get-Process AutoGameTool -ErrorAction SilentlyContinue).Count
Check '结束后无残留进程' ($left -eq 0) ("残留 " + $left)

Write-Host ''
Write-Host ("结果: PASS={0}  FAIL={1}" -f $pass, $fail)
if ($fail) { Write-Host '提示：单文件旧构建（--onefile）在 TEMP 不可用时必然失败，那是它的已知缺陷。' -ForegroundColor Yellow }
exit $(if ($fail -eq 0) { 0 } else { 1 })
