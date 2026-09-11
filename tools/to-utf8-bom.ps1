# ============================================================
#  将项目内的 .ps1 / .nsi 源码统一转换为「UTF-8 with BOM」。
#
#  为什么需要：Windows PowerShell 5.1（powershell.exe）在文件没有 BOM 时
#  会按系统 ANSI 代码页解码，中文会变成乱码并导致字符串未闭合之类的语法错误；
#  makensis 同样依赖 BOM 来判断源文件是 UTF-8。而很多编辑器/工具默认保存为
#  「UTF-8 无 BOM」，所以每次改完脚本后跑一次本脚本最保险。
#
#  用法：
#      .\tools\to-utf8-bom.ps1              # 处理项目内所有 .ps1 / .nsi
#      .\tools\to-utf8-bom.ps1 -Check       # 只检查，不修改（有问题的返回 1）
#
#  本文件本身只含 ASCII 字符，因此无 BOM 也能正常运行。
# ============================================================
[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

$skip = @('node_modules', '.venv', 'dist', 'build', '.tmp', 'nsis', '__pycache__')

$files = Get-ChildItem $root -Recurse -File -Include '*.ps1', '*.nsi' -ErrorAction SilentlyContinue |
    Where-Object {
        $rel = $_.FullName.Substring($root.Length).TrimStart('\')
        $parts = $rel -split '\\'
        -not ($parts | Where-Object { $skip -contains $_ })
    }

$changed = 0
$bad = 0

foreach ($f in $files) {
    $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
    $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    $rel = $f.FullName.Substring($root.Length).TrimStart('\')

    if ($hasBom) {
        Write-Host "  ok      $rel"
        continue
    }

    if ($Check) {
        Write-Host "  MISSING $rel" -ForegroundColor Yellow
        $bad++
        continue
    }

    $text = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)
    $utf8Bom = New-Object System.Text.UTF8Encoding($true)
    [System.IO.File]::WriteAllText($f.FullName, $text, $utf8Bom)
    Write-Host "  fixed   $rel" -ForegroundColor Green
    $changed++
}

Write-Host ""
if ($Check) {
    Write-Host "缺少 BOM 的文件：$bad / 共 $($files.Count)" -ForegroundColor $(if ($bad) { 'Yellow' } else { 'Green' })
    if ($bad) { exit 1 }
} else {
    Write-Host "已修复：$changed 个文件（共扫描 $($files.Count) 个）" -ForegroundColor Green
}
