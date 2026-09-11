# ============================================================
#  AutoGameTool 安装包端到端验证
#
#  静默安装 → 校验文件 / 快捷方式 / 注册表 → 冒烟测试 → 静默卸载 → 校验清理
#
#  用法：
#      .\tools\test_installer.ps1                    # 验证完自动卸载
#      .\tools\test_installer.ps1 -KeepInstalled     # 验证后保留安装
#
#  注意：安装/卸载会写注册表与「开始菜单 / 桌面」，需要有相应权限。
#        用户数据目录 %APPDATA%\AutoGameTool 会被保留（与安装包行为一致）。
# ============================================================
[CmdletBinding()]
param(
    [string]$SetupPath,
    [switch]$KeepInstalled,
    [int]$UninstallTimeoutSec = 60
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $SetupPath) { $SetupPath = Join-Path $root 'AutoGameTool-Setup.exe' }
if (-not (Test-Path $SetupPath)) { Write-Host "未找到安装包：$SetupPath" -ForegroundColor Red; exit 1 }
$SetupPath = (Resolve-Path $SetupPath).Path

$installDir = Join-Path $env:LOCALAPPDATA 'AutoGameTool'
$exe        = Join-Path $installDir 'AutoGameTool.exe'
$readme     = Join-Path $installDir 'README.md'
$uninst     = Join-Path $installDir 'Uninstall.exe'
$appDataDir = Join-Path $env:APPDATA 'AutoGameTool'
$startMenu  = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\AutoGameTool'
$desktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AutoGameTool.lnk'
$uninstKey  = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoGameTool'
$appKey     = 'HKCU:\Software\AutoGameTool'
$appPaths   = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\AutoGameTool.exe'

$results = New-Object System.Collections.Generic.List[object]
function Add-Result([string]$Name, [bool]$Ok, [string]$Detail) {
    $results.Add([pscustomobject]@{ 项目 = $Name; 结果 = $(if ($Ok) { 'PASS' } else { 'FAIL' }); 说明 = $Detail })
}
function Get-RegVal([string]$Path, [string]$Name) {
    try { return (Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop).$Name } catch { return $null }
}
function Get-RegDefault([string]$Path) {
    # 读取注册表键的「默认值」；Get-ItemProperty -Name '' 取不到，必须用 .GetValue('')
    try { return (Get-Item -Path $Path -ErrorAction Stop).GetValue('') } catch { return $null }
}
function Wait-PathGone([string]$Path, [int]$TimeoutSec) {
    $dl = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $dl) {
        if (-not (Test-Path $Path)) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return -not (Test-Path $Path)
}

Write-Host "=== AutoGameTool 安装包端到端验证 ===" -ForegroundColor Cyan
Write-Host "  安装包：$SetupPath"
Write-Host ("  大小：{0:N1} MB" -f ((Get-Item $SetupPath).Length / 1MB))
Write-Host "  目标目录：$installDir"
Write-Host ""

# ---------------------------------------------------------- 0. 环境准备
$userDataExistedBefore = Test-Path $appDataDir
Get-Process AutoGameTool -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
if (Test-Path $uninst) {
    Write-Host "检测到已安装版本，先静默卸载旧版 ..." -ForegroundColor Yellow
    Start-Process -FilePath $uninst -ArgumentList '/S' -Wait
    [void](Wait-PathGone $installDir $UninstallTimeoutSec)
}

# ---------------------------------------------------------- 1. 静默安装
Write-Host "=== 1. 静默安装（/S）===" -ForegroundColor Cyan
$sw = [System.Diagnostics.Stopwatch]::StartNew()
Start-Process -FilePath $SetupPath -ArgumentList '/S' -Wait
$sw.Stop()
Write-Host ("  耗时 {0:N1}s" -f $sw.Elapsed.TotalSeconds)

Add-Result '安装目录已创建'   (Test-Path $installDir)   $installDir
Add-Result 'AutoGameTool.exe' (Test-Path $exe)          $(if (Test-Path $exe) { "{0:N1} MB" -f ((Get-Item $exe).Length / 1MB) } else { '缺失' })
Add-Result 'README.md 已安装' (Test-Path $readme)       $(if (Test-Path $readme) { "{0} bytes" -f (Get-Item $readme).Length } else { '缺失' })
Add-Result 'Uninstall.exe'    (Test-Path $uninst)       $(if (Test-Path $uninst) { "{0} bytes" -f (Get-Item $uninst).Length } else { '缺失' })

# ---------------------------------------------------------- 2. 快捷方式
Write-Host "=== 2. 快捷方式 ===" -ForegroundColor Cyan
$smLnk  = Join-Path $startMenu 'AutoGameTool.lnk'
$smHelp = Join-Path $startMenu '使用说明.lnk'
$smUnin = Join-Path $startMenu '卸载 AutoGameTool.lnk'
Add-Result '开始菜单目录'       (Test-Path $startMenu) (Split-Path $startMenu -Leaf)
Add-Result '开始菜单-启动'      (Test-Path $smLnk)     'AutoGameTool.lnk'
Add-Result '开始菜单-使用说明'  (Test-Path $smHelp)    '使用说明.lnk'
Add-Result '开始菜单-卸载'      (Test-Path $smUnin)    '卸载 AutoGameTool.lnk'
Add-Result '桌面快捷方式'       (Test-Path $desktopLnk) $desktopLnk

# ---------------------------------------------------------- 3. 注册表
Write-Host "=== 3. 注册表 ===" -ForegroundColor Cyan
$dn = Get-RegVal $uninstKey 'DisplayName'
$dv = Get-RegVal $uninstKey 'DisplayVersion'
$us = Get-RegVal $uninstKey 'UninstallString'
$qs = Get-RegVal $uninstKey 'QuietUninstallString'
$il = Get-RegVal $uninstKey 'InstallLocation'
$di = Get-RegVal $uninstKey 'DisplayIcon'
$es = Get-RegVal $uninstKey 'EstimatedSize'
Add-Result '卸载入口 DisplayName'   ($dn -like '*AutoGameTool*') "$dn"
Add-Result '卸载入口 DisplayVersion' ($dv -eq '0.1.0')           "$dv"
Add-Result '卸载入口 UninstallString' ($us -like '*Uninstall.exe*') "$us"
Add-Result '卸载入口 QuietUninstallString' ($qs -like '*/S*')     "$qs"
Add-Result '卸载入口 InstallLocation' ($il -eq $installDir)       "$il"
Add-Result '卸载入口 DisplayIcon'    ($di -like '*AutoGameTool.exe*') "$di"
Add-Result '卸载入口 EstimatedSize'  ($null -ne $es -and $es -gt 0) "$es KB"
Add-Result 'InstallDir 记录'         ((Get-RegVal $appKey 'InstallDir') -eq $installDir) "$(Get-RegVal $appKey 'InstallDir')"
Add-Result 'App Paths 注册'          ((Get-RegDefault $appPaths) -eq $exe) "$(Get-RegDefault $appPaths)"

# ---------------------------------------------------------- 4. 冒烟测试
Write-Host "=== 4. 冒烟测试（运行已安装的 exe）===" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'smoke_test.ps1') -ExePath $exe
$smokeOk = ($LASTEXITCODE -eq 0)
Add-Result '冒烟测试' $smokeOk $(if ($smokeOk) { '10 项检查全部通过' } else { "退出码 $LASTEXITCODE" })

# ---------------------------------------------------------- 5. 卸载
if ($KeepInstalled) {
    Write-Host "=== 5. 按要求保留安装（跳过卸载）===" -ForegroundColor Yellow
} else {
    Write-Host "=== 5. 静默卸载（Uninstall.exe /S）===" -ForegroundColor Cyan
    Start-Process -FilePath $uninst -ArgumentList '/S' -Wait
    $gone = Wait-PathGone $installDir $UninstallTimeoutSec
    Add-Result '安装目录已删除'     (-not (Test-Path $installDir))  "$installDir 残留=$(Test-Path $installDir)"
    Add-Result '开始菜单已清理'     (-not (Test-Path $startMenu))   "$startMenu 残留=$(Test-Path $startMenu)"
    Add-Result '桌面快捷方式已清理' (-not (Test-Path $desktopLnk))  "$desktopLnk 残留=$(Test-Path $desktopLnk)"
    Add-Result '卸载注册表项已删除' ($null -eq (Get-RegVal $uninstKey 'DisplayName')) 'Uninstall 键'
    Add-Result 'App Paths 已清理'   ($null -eq (Get-RegDefault $appPaths)) 'App Paths 键'
    Add-Result '用户数据已保留'     (Test-Path $appDataDir) $appDataDir
}

Write-Host ""
$results | Format-Table -AutoSize
$failed = @($results | Where-Object { $_.结果 -eq 'FAIL' }).Count
$pass = $results.Count - $failed
if ($failed -eq 0) {
    Write-Host "结果：全部通过（$pass/$($results.Count)）" -ForegroundColor Green
    exit 0
} else {
    Write-Host "结果：FAIL（$failed 项未通过，共 $($results.Count) 项）" -ForegroundColor Red
    exit 1
}
