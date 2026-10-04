<#
.SYNOPSIS
  编辑器界面回归测试：用**无头 Chrome + CDP** 跑一遍界面结构断言（只需要 DOM，不需要人眼）。

.DESCRIPTION
  配合 tools\ui-editor-checks.mjs 使用。脚本负责把"跑起来"的部分准备好：
    1. 起一份打包好的引擎（默认取 ..\AutoGameTool-app\，会**先复制到 TEMP 再运行**）
    2. 起一个无头 Chrome，开远程调试端口
    3. 跑 node 断言脚本，把结果打到控制台并写文件
    4. 收尾（无论成败都收回引擎与 Chrome 进程）

  ⚠️ 为什么复制到 TEMP 再运行：本机在 E:\codes 下执行刚构建出来的 exe 会被静默拦掉
  （exit 1、零输出），复制到工作区外才正常。其它机器上这步无害。
  ⚠️ 断言脚本只用**页面内事件派发**，不做真实鼠标注入，不会干扰你正在用的电脑。

.EXAMPLE
  .\tools\test_ui_editor.ps1
  .\tools\test_ui_editor.ps1 -OpenResult      # 跑完把结果文件打开
  .\tools\test_ui_editor.ps1 -Refresh         # 强制重新复制引擎（改过引擎代码后用）

.NOTES
  本文件含中文，**必须保存为「UTF-8 with BOM」**，否则 Windows PowerShell 5.1 会按 ANSI 读，
  报「字符串缺少终止符」之类的解析错误。新增/改完请跑一次 `.\tools\to-utf8-bom.ps1`。
#>
[CmdletBinding()]
param(
  # 引擎产物目录（含 AutoGameTool.exe 与 _internal\）。默认 ..\AutoGameTool-app
  [string]$AppDir,
  # 打包好的或已安装的引擎目录
  [string]$Node,
  [string]$Chrome,
  [int]$CdpPort = 9223,
  [int]$EnginePort = 8765,
  # 重新复制一份引擎到 TEMP（引擎代码或前端资源改过之后用）
  [switch]$Refresh,
  # 跑完打开结果文件
  [switch]$OpenResult
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

$repo = Split-Path $PSScriptRoot -Parent
if (-not $AppDir) { $AppDir = Join-Path $repo 'AutoGameTool-app' }
$AppDir = (Resolve-Path $AppDir).Path

# ---------- 找 node / chrome ----------
if (-not $Node -or -not (Test-Path $Node)) {
  $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
  if ($cmd) { $Node = $cmd.Source }
}
if (-not $Node -or -not (Test-Path $Node)) {
  $managed = 'C:\Users\' + $env:USERNAME + '\.workbuddy\binaries\node\versions\22.22.2-3\node.exe'
  if (Test-Path $managed) { $Node = $managed }
}
if (-not $Node -or -not (Test-Path $Node)) {
  throw '找不到 node.exe：请把 Node.js 加进 PATH，或用 -Node 指定完整路径'
}

if (-not $Chrome -or -not (Test-Path $Chrome)) {
  $cands = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
  )
  foreach ($c in $cands) { if (Test-Path $c) { $Chrome = $c; break } }
}
if (-not $Chrome -or -not (Test-Path $Chrome)) {
  throw '找不到 Chrome / Edge：请用 -Chrome 指定 chrome.exe 的完整路径'
}

Write-Host "[1/5] 引擎产物 : $AppDir"
Write-Host "      node     : $Node"
Write-Host "      浏览器   : $Chrome"

# ---------- 复制引擎到工作区外再跑 ----------
$runRoot = Join-Path $env:TEMP 'agt-ui-run'
$engDir = Join-Path $runRoot 'engine'
if ($Refresh -or -not (Test-Path (Join-Path $engDir 'AutoGameTool.exe'))) {
  if (Test-Path $engDir) {
    # 用 Move 而不是删除：本机删除会被 safe-delete 掐断
    Move-Item $engDir (Join-Path $runRoot ('stale-engine-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))) -Force
  }
  New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
  Copy-Item $AppDir $engDir -Recurse -Force
}
# 前端资源始终用最新的 dist 覆盖（比重新打包快得多）
$dist = Join-Path $repo 'frontend\dist\index.html'
if (Test-Path $dist) {
  $fd = Join-Path $engDir '_internal\frontend_dist'
  if (Test-Path (Join-Path $fd 'assets')) {
    Move-Item (Join-Path $fd 'assets') (Join-Path $runRoot ('stale-fe-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))) -Force
  }
  Copy-Item (Join-Path $repo 'frontend\dist\*') $fd -Recurse -Force
  Write-Host "[2/5] 已把 frontend\dist 覆盖进引擎资源目录"
} else {
  Write-Host '[2/5] 提示：没有 frontend\dist，用引擎里自带的前端资源' -ForegroundColor Yellow
}

function Stop-NamedProcess([string]$name) {
  Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
}

$engineProc = $null
$chromeProc = $null
$exit = 1
try {
  # ---------- 起引擎 ----------
  Stop-NamedProcess 'AutoGameTool'
  Start-Sleep -Seconds 1
  $engineProc = Start-Process -FilePath (Join-Path $engDir 'AutoGameTool.exe') -WorkingDirectory $engDir -PassThru
  $health = $null
  $ok = $false
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try {
      $health = Invoke-RestMethod "http://127.0.0.1:$EnginePort/health" -TimeoutSec 2
      $ok = $true
      break
    } catch { }
  }
  if (-not $ok) { throw "引擎 40 秒内没有就绪（http://127.0.0.1:$EnginePort/health）" }
  Write-Host ("[3/5] 引擎就绪： " + ($health | ConvertTo-Json -Compress))

  $token = ''
  $tokenFile = Join-Path $env:APPDATA 'AutoGameTool\engine.token'
  if (Test-Path $tokenFile) { $token = (Get-Content $tokenFile -Raw).Trim() }

  # ---------- 起无头浏览器 ----------
  $profile = Join-Path $runRoot 'chrome-profile'
  if (Test-Path $profile) {
    Move-Item $profile (Join-Path $runRoot ('stale-profile-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))) -Force
  }
  $chromeArgs = @(
    '--headless=new', '--disable-gpu', '--no-first-run',
    "--remote-debugging-port=$CdpPort",
    "--user-data-dir=$profile",
    '--window-size=1280,900',
    'about:blank'
  )
  $chromeProc = Start-Process -FilePath $Chrome -ArgumentList $chromeArgs -PassThru
  Start-Sleep -Seconds 4
  Write-Host "[4/5] 无头浏览器已启动（调试端口 $CdpPort）"

  # ---------- 跑断言 ----------
  $outFile = Join-Path $runRoot 'ui-editor-checks.txt'
  $env:AGT_URL = "http://127.0.0.1:$EnginePort/?token=$token"
  $env:AGT_OUT = $outFile
  $env:AGT_CDP_PORT = "$CdpPort"
  & $Node (Join-Path $PSScriptRoot 'ui-editor-checks.mjs')
  $exit = $LASTEXITCODE
  Write-Host "[5/5] 结果文件：$outFile"
  if ($OpenResult -and (Test-Path $outFile)) { Start-Process $outFile }
} finally {
  if ($chromeProc) { Get-Process -Id $chromeProc.Id -ErrorAction SilentlyContinue | Stop-Process -Force }
  Stop-NamedProcess 'AutoGameTool'
  Write-Host '已收尾（引擎与无头浏览器均已关闭）'
}

# 不用 exit：脚本被 `& .\tools\test_ui_editor.ps1` 这样在同一次会话里调用时，
# exit 会把调用方（你的终端 / 会话）一起结束掉。失败改成 throw，交互式与 -File 都能拿到失败。
if ($exit -ne 0) {
  throw "界面回归有失败项（node 退出码 $exit）—— 详见 $outFile"
}
Write-Host '[完成] 界面回归全部通过'
