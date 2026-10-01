# ============================================================
#  打包产物核验：无控制台 + 运行日志落盘（v0.7.3 的两条硬要求）
#
#  用法：
#      .\tools\test_noconsole_log.ps1                 # 默认测根目录的 AutoGameTool.exe
#      .\tools\test_noconsole_log.ps1 -ExePath <路径>  # 测别的副本（如安装后的 exe）
#
#  校验内容（10 项）：
#    1. PE 子系统 = 2（GUI）：不会分配控制台。同一段检测对 python.exe 读出 3 作阳性对照
#    2. 启动产物后枚举它的全部顶层窗口，断言没有控制台类窗口，且确实看到悬浮框 TkTopLevel
#       （onefile 会有「父 bootloader + 真正跑 Python」两个同名进程，两个都要查）
#    3. %APPDATA%\AutoGameTool\engine.log 被创建、含版本启动记录，
#       且 token= 已掩成 ***、日志里不含启动时传入的真实令牌
#
#  说明：用固定令牌（AUTOGAMETOOL_TOKEN）+ AUTOGAMETOOL_NO_BROWSER=1 启动，便于断言
#        「真令牌没有落盘」；不注入任何真实鼠标/键盘；运行前需 8765 端口空闲。
#        已有的 engine.log 会先备份到 .tmp\ 再重建，测试结束杀掉自己启动的进程。
# ============================================================
[CmdletBinding()]
param(
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $ExePath) {
    # v0.8.2 起是文件夹形态，优先测 AutoGameTool-app\ 下的（仍兼容根目录单文件 exe）
    $appExe = Join-Path $root 'AutoGameTool-app\AutoGameTool.exe'
    $ExePath = if (Test-Path $appExe) { $appExe } else { Join-Path $root 'AutoGameTool.exe' }
}
if (-not (Test-Path $ExePath)) { Write-Host "未找到 exe：$ExePath" -ForegroundColor Red; exit 1 }
$exe = (Resolve-Path $ExePath).Path

# 把 APPDATA 指到项目内 .tmp\ 下：被测程序仍是打包产物本身，但日志写在沙箱允许的目录里。
# （本会话的沙箱策略会拦「往真实 %APPDATA% 写」，那是环境限制，不是产品问题；
#   用户/驱动正常启动时日志照常写在 %APPDATA%\AutoGameTool\engine.log —— 已实测过。）
$env:APPDATA = Join-Path $root '.tmp\noconsole-appdata'
New-Item -ItemType Directory -Force -Path $env:APPDATA | Out-Null

$log = Join-Path $env:APPDATA 'AutoGameTool\engine.log'
$bak = Join-Path $root '.tmp\engine.log.bak'
$token = 'DUMMYTOKEN_v073_verify_0123456789'
$fail = 0

function Check([string]$name, [bool]$ok, [string]$detail = '') {
    if ($ok) { "  PASS  $name" }
    else { "  FAIL  $name  $detail"; $script:fail++ }
}

function Get-Subsystem([string]$path) {
    $fs = [System.IO.File]::OpenRead($path)
    try {
        $br = New-Object System.IO.BinaryReader($fs)
        $fs.Position = 0x3C
        $peOffset = $br.ReadInt32()
        $fs.Position = $peOffset
        if ($br.ReadUInt32() -ne 0x00004550) { return -1 }   # 'PE\0\0'
        $fs.Position = $peOffset + 24 + 68                     # Subsystem 字段（PE32/PE32+ 同偏移）
        return $br.ReadUInt16()
    } finally { $fs.Dispose() }
}

Write-Host "=== 打包产物核验：无控制台 + 日志落盘 ===" -ForegroundColor Cyan
Write-Host "  exe：$exe"
Write-Host ""

# ---- 1. 结构性检查：PE 子系统（2=GUI 无控制台，3=Console）----
$exeSub = Get-Subsystem $exe
$pySub  = Get-Subsystem (Join-Path $root 'engine\.venv\Scripts\python.exe')
Write-Host "        exe 子系统=$exeSub   python.exe 子系统=$pySub"
Check '检测器阳性对照：python.exe 是控制台子系统(3)' ($pySub -eq 3) "得到 $pySub"
Check 'exe 是 GUI 子系统(2)，不会分配控制台' ($exeSub -eq 2) "得到 $exeSub"

# ---- 2. 启动产物，检查窗口 ----
Get-Process AutoGameTool -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
# 用 netstat 判断端口（Get-NetTCPConnection 在某些受限环境里读不到）
Check '运行前 8765 端口空闲' (-not [bool](netstat -ano | Select-String ':8765' | Select-String 'LISTENING')) ''

if (-not (Test-Path (Split-Path $bak -Parent))) { New-Item -ItemType Directory -Path (Split-Path $bak -Parent) -Force | Out-Null }
if (Test-Path $log) { Copy-Item $log $bak -Force; Remove-Item $log -Force }

$env:AUTOGAMETOOL_TOKEN = $token
$env:AUTOGAMETOOL_NO_BROWSER = '1'
# 必须重定向输出：GUI 子进程若继承本 shell 的 stdout 句柄，外层工具会一直等它退出
$proc = Start-Process -FilePath $exe -PassThru `
    -RedirectStandardOutput (Join-Path (Split-Path $PSScriptRoot -Parent) '.tmp\noconsole-out.log') `
    -RedirectStandardError  (Join-Path (Split-Path $PSScriptRoot -Parent) '.tmp\noconsole-err.log')
$env:AUTOGAMETOOL_TOKEN = ''
$env:AUTOGAMETOOL_NO_BROWSER = ''

try {
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $h = Invoke-RestMethod "http://127.0.0.1:8765/health?token=$token" -TimeoutSec 2
            if ($h) { $ok = $true; break }
        } catch { }
    }
    Check '引擎启动并响应 /health' $ok
    if ($ok) { Write-Host "        health: $($h | ConvertTo-Json -Compress)" }

    Add-Type -Namespace Win32 -Name W -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder s, int n);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder s, int n);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
'@

    function Get-WindowsOf([uint32[]]$pids) {
        $list = New-Object System.Collections.ArrayList
        $cb = [Win32.W+EnumWindowsProc]{
            param($hWnd, $lParam)
            $wpid = [uint32]0
            [void][Win32.W]::GetWindowThreadProcessId($hWnd, [ref]$wpid)
            if ($pids -contains $wpid) {
                $cn = New-Object System.Text.StringBuilder 256
                [void][Win32.W]::GetClassName($hWnd, $cn, 256)
                $tt = New-Object System.Text.StringBuilder 256
                [void][Win32.W]::GetWindowText($hWnd, $tt, 256)
                [void]$list.Add([pscustomobject]@{
                    Pid = $wpid; Class = $cn.ToString(); Title = $tt.ToString()
                    Visible = [Win32.W]::IsWindowVisible($hWnd)
                })
            }
            return $true
        }
        [void][Win32.W]::EnumWindows($cb, [IntPtr]::Zero)
        return $list
    }

    $pids = @(Get-Process AutoGameTool -ErrorAction SilentlyContinue |
              Select-Object -ExpandProperty Id | ForEach-Object { [uint32]$_ })
    Write-Host "        进程：$($pids -join ',')（Start-Process 返回 $($proc.Id)）"
    Check '找到 AutoGameTool 进程' ($pids.Count -gt 0) ''
    $windows = Get-WindowsOf $pids
    Write-Host "        顶层窗口："
    $windows | ForEach-Object { Write-Host "          pid=$($_.Pid) [$($_.Class)] visible=$($_.Visible) title='$($_.Title)'" }

    $consoleClasses = @('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS', 'PseudoConsoleWindow', 'mintty')
    $consoles = @($windows | Where-Object { $consoleClasses -contains $_.Class })
    Check '没有控制台窗口' ($consoles.Count -eq 0) "找到: $($consoles.Class -join ',')"
    Check '枚举器工作正常（至少看到悬浮框 TkTopLevel）' (@($windows | Where-Object { $_.Class -eq 'TkTopLevel' }).Count -gt 0) ''

    # ---- 3. 日志（进程持有句柄，必须以 ReadWrite 共享方式打开）----
    Start-Sleep -Milliseconds 800
    Check 'engine.log 已创建' (Test-Path $log) $log
    if (Test-Path $log) {
        $fs = [System.IO.File]::Open($log, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
            $text = $sr.ReadToEnd()
        } finally { $fs.Dispose() }
        Check '日志含启动记录（版本号）' ($text -match '引擎启动：版本 \d+\.\d+\.\d+') ''
        Check '日志把令牌掩码为 token=***' ($text -match 'token=\*\*\*') ''
        Check '日志未泄漏真令牌' (-not $text.Contains($token)) ''
        if ($text.Contains($token)) {
            Write-Host "        泄漏上下文：" + (($text -split "`n" | Where-Object { $_.Contains($token) }) -join ' | ')
        }
        Write-Host "        ---- 日志前 8 行 ----"
        ($text -split "`r?`n" | Select-Object -First 8) | ForEach-Object { Write-Host "          $_" }
    }
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    Get-Process AutoGameTool -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 800
}

Write-Host ""
if ($fail -eq 0) { Write-Host "结果：全部通过" -ForegroundColor Green } else { Write-Host "结果：FAIL（$fail 项）" -ForegroundColor Red }
exit $fail
