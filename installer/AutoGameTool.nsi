; ============================================================================
;  AutoGameTool 安装包脚本（NSIS 3.x / Unicode）
;
;  构建方式：执行项目根目录的  .\build_installer.ps1
;  （该脚本会用 /D 传入 PROJECT_ROOT / OUT_DIR 的绝对路径）
;
;  产物：AutoGameTool-Setup.exe
;  特性：免管理员（安装到 %LOCALAPPDATA%）、开始菜单 + 桌面快捷方式、
;        标准卸载入口、升级时自动静默卸载旧版、支持 /S 静默安装
;
;  注意 1：NSIS 3 的 Icon / File / OutFile 相对路径是以「脚本所在目录」为基准的，
;          不是 makensis 的当前工作目录，所以这里统一用 PROJECT_ROOT 拼绝对路径。
;  注意 2：本文件必须保存为「UTF-8 with BOM」，否则 makensis 会按 ANSI 解析中文。
; ============================================================================

Unicode true

; ------------------------------------------------------------ 路径（可被 /D 覆盖）
!ifndef PROJECT_ROOT
    !define PROJECT_ROOT ".."
!endif
!ifndef OUT_DIR
    !define OUT_DIR "${PROJECT_ROOT}"
!endif

; ---------------------------------------------------------------- 基本信息
!define APP_NAME      "AutoGameTool"
!define APP_NAME_CN   "AutoGameTool 游戏自动化脚本工具"
!define APP_VERSION   "0.5.1"
!define APP_PUBLISHER "AutoGameTool"
!define APP_EXE       "AutoGameTool.exe"
!define APP_ICON      "${PROJECT_ROOT}\assets\AutoGameTool.ico"
!define README_FILE   "README.md"
!define OUT_FILE      "${OUT_DIR}\AutoGameTool-Setup.exe"

!define APP_KEY    "Software\${APP_NAME}"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define KILL_CMD   '"$SYSDIR\taskkill.exe" /F /T /IM ${APP_EXE}'

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\${APP_NAME}"
InstallDirRegKey HKCU "${APP_KEY}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64

Icon "${APP_ICON}"
UninstallIcon "${APP_ICON}"

; ------------------------------------------------------- 文件属性（右键详情）
VIProductVersion "0.5.1.0"
VIAddVersionKey /LANG=2052 "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_NAME} 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion"     "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=2052 "LegalCopyright"  "Copyright (C) 2026 ${APP_PUBLISHER}"
VIAddVersionKey /LANG=1033 "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=1033 "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey /LANG=1033 "FileVersion"     "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=1033 "LegalCopyright"  "Copyright (C) 2026 ${APP_PUBLISHER}"

; ------------------------------------------------------------------- 依赖
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "WinVer.nsh"

; --------------------------------------------------------------- 界面外观
!define MUI_ABORTWARNING
!define MUI_ICON   "${APP_ICON}"
!define MUI_UNICON "${APP_ICON}"

; 欢迎页
!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT "本向导将引导您完成 ${APP_NAME} ${APP_VERSION} 的安装。$\r$\n$\r$\n${APP_NAME} 是一款面向 Windows 的「零代码」游戏自动化脚本工具：$\r$\n    · 拖拽节点即可编排流程（找图 / 点击 / 按键 / 判断分支 / 循环挂机）$\r$\n    · 全部能力在本地运行，找图、点击、按键不经过任何服务器$\r$\n    · 单文件分发，目标机器无需安装 Python 或任何运行环境$\r$\n$\r$\n安装位置：$LOCALAPPDATA\${APP_NAME}（仅当前用户，无需管理员权限）$\r$\n$\r$\n点击「下一步」继续。"

; 完成页
!define MUI_FINISHPAGE_TITLE "${APP_NAME} 安装完成"
!define MUI_FINISHPAGE_TEXT "${APP_NAME} 已成功安装到：$\r$\n$INSTDIR$\r$\n$\r$\n程序启动后会自动打开浏览器进入可视化编辑器。$\r$\n默认快捷键：alt+f1 启动/停止脚本 · F8 坐标拾取 · alt+9 键鼠录制。$\r$\n$\r$\n提示：程序同一时刻只能运行一个实例。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 ${APP_NAME}"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\${README_FILE}"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "查看使用说明（README）"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------------ 安装
Function .onInit
    SetShellVarContext current

    ${IfNot} ${AtLeastWin10}
        MessageBox MB_ICONSTOP "AutoGameTool 仅支持 Windows 10 / 11 系统。" /SD IDOK
        Abort
    ${EndIf}

    ; 已安装旧版本 → 先静默卸载，避免残留文件与重复的卸载入口
    ReadRegStr $R0 HKCU "${UNINST_KEY}" "UninstallString"
    ${If} $R0 != ""
        MessageBox MB_ICONQUESTION|MB_YESNO "检测到已安装 ${APP_NAME}。$\r$\n$\r$\n是否先卸载旧版本再继续安装？$\r$\n（用户数据：模板与配置会保留）" /SD IDYES IDNO done_old
        ExecWait '"$R0" /S _?=$INSTDIR'
        done_old:
    ${EndIf}
FunctionEnd

Section "主程序（必需）" SEC_MAIN
    SectionIn RO
    SetShellVarContext current

    ; 关闭正在运行的实例，避免 exe 被占用导致覆盖失败
    nsExec::Exec '${KILL_CMD}'
    Pop $0
    Sleep 700

    SetOutPath "$INSTDIR"
    File "/oname=${APP_EXE}"     "${PROJECT_ROOT}\${APP_EXE}"
    File "/oname=${README_FILE}" "${PROJECT_ROOT}\${README_FILE}"

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; ---- 注册表：安装信息 + 标准卸载入口（设置 → 应用） ----
    WriteRegStr HKCU "${APP_KEY}" "InstallDir" "$INSTDIR"
    WriteRegStr HKCU "${APP_KEY}" "Version"    "${APP_VERSION}"

    WriteRegStr   HKCU "${UNINST_KEY}" "DisplayName"         "${APP_NAME_CN}"
    WriteRegStr   HKCU "${UNINST_KEY}" "DisplayVersion"      "${APP_VERSION}"
    WriteRegStr   HKCU "${UNINST_KEY}" "Publisher"           "${APP_PUBLISHER}"
    WriteRegStr   HKCU "${UNINST_KEY}" "DisplayIcon"         "$INSTDIR\${APP_EXE},0"
    WriteRegStr   HKCU "${UNINST_KEY}" "InstallLocation"     "$INSTDIR"
    WriteRegStr   HKCU "${UNINST_KEY}" "UninstallString"     '"$INSTDIR\Uninstall.exe"'
    WriteRegStr   HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    ${If} $0 != ""
        IntFmt $0 "0x%08X" $0
        WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
    ${EndIf}

    ; 支持 Win+R 直接输入 AutoGameTool 启动
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\App Paths\${APP_EXE}" ""     "$INSTDIR\${APP_EXE}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\App Paths\${APP_EXE}" "Path" "$INSTDIR"

    ; ---- 开始菜单 ----
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"     "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\使用说明.lnk"         "$INSTDIR\${README_FILE}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "创建桌面快捷方式" SEC_DESKTOP
    SetShellVarContext current
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN}    "AutoGameTool 主程序：单文件 exe，已内嵌前端界面与 Python 引擎。"
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} "在当前用户桌面创建启动快捷方式。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ------------------------------------------------------------------ 卸载
Function un.onInit
    SetShellVarContext current
FunctionEnd

Section "Uninstall"
    SetShellVarContext current

    nsExec::Exec '${KILL_CMD}'
    Pop $0
    Sleep 700

    ; 快捷方式
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\使用说明.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
    RMDir  "$SMPROGRAMS\${APP_NAME}"
    Delete "$DESKTOP\${APP_NAME}.lnk"

    ; 程序文件
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\${README_FILE}"
    Delete "$INSTDIR\Uninstall.exe"

    ; 目录里可能还留有运行时产物。只有目录名仍是默认的 AutoGameTool 时才递归清理，
    ; 避免用户把安装目录指到别处（例如某个已有文件夹）时误删。
    ${un.GetFileName} "$INSTDIR" $R2
    ${If} $R2 == "${APP_NAME}"
        RMDir /r "$INSTDIR"
    ${Else}
        RMDir "$INSTDIR"
    ${EndIf}

    ; 注册表
    DeleteRegKey HKCU "${UNINST_KEY}"
    DeleteRegKey HKCU "${APP_KEY}"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\App Paths\${APP_EXE}"

    ; 用户数据（模板 / 配置）默认保留；静默卸载一律保留
    IfSilent keep_userdata
    MessageBox MB_ICONQUESTION|MB_YESNO "是否同时删除用户数据（找图模板、快捷键配置）？$\r$\n$\r$\n位置：$APPDATA\${APP_NAME}$\r$\n$\r$\n选择「否」将保留，重新安装后可继续使用原有脚本与模板。" /SD IDNO IDNO keep_userdata
    RMDir /r "$APPDATA\${APP_NAME}"
    keep_userdata:
SectionEnd
