# AutoGameTool

> 轻量级游戏自动化脚本工具 —— **零代码可视化编排** + **本地 Python 引擎**
>
> 像搭积木一样"画"出游戏脚本：找图、点击、按键、判断分支、循环挂机，全程不写一行代码。

## 前言

- 此项目完全由 **DeepSeek Harness** 完成，使用模型为 **DeepSeek V4.1 Flash**。
- 原本是为**造梦西游4**设计的挂机脚本程序，主要为了解决360游戏大厅固定流程，游戏加载卡住等问题。
- 实测opencv运行识别有时偏慢，但总体效果良好，10+小时挂机无问题
- todo：后台模拟输入、区域识别（减少opencv识别时间）

## 下载

| 方式 | 说明 |
|---|---|
| **[⬇ 安装包（Releases）](https://github.com/Luzikasama/AutoGameTool/releases/latest)** | `AutoGameTool-Setup.exe`，Windows 10 / 11，免管理员，约 71 MB |
| 从源码构建 | 见 [9. 打包与发布](#9-打包与发布)：`build_exe.ps1` → `build_installer.ps1` |

安装包未做代码签名，若 SmartScreen 提示请选「更多信息 → 仍要运行」。

---

## 目录

- [前言](#前言)
- [下载](#下载)
- [1. 项目简介](#1-项目简介)
- [2. 功能特性](#2-功能特性)
- [3. 技术栈](#3-技术栈)
- [4. 系统架构](#4-系统架构)
- [5. 目录结构](#5-目录结构)
- [6. 快速开始](#6-快速开始)
- [7. 使用指南](#7-使用指南)
- [8. 引擎 API 参考](#8-引擎-api-参考)
- [9. 打包与发布](#9-打包与发布)
- [10. 关键设计说明](#10-关键设计说明)
- [11. 常见问题与排错](#11-常见问题与排错)
- [12. 已知限制](#12-已知限制)
- [13. 路线图](#13-路线图)
- [14. 更新日志](#14-更新日志)
- [15. 开源协议](#15-开源协议)

---

## 1. 项目简介

AutoGameTool 是一款面向 **Windows** 的轻量级游戏自动化（类 RPA）工具。核心思路：

- **用户画流程，引擎跑流程**。用户在可视化编辑器里拖拽节点、连线、填参数，产出的是一个 **JSON 工程文件**（`.agflow`），而不是代码。
- 运行时由内置的 **Python 引擎**解释这份 JSON，调用底层能力（截图 / 图像识别 / 键鼠控制 / OCR）。
- 前后端同源打包成 **一个 exe**，双击即用，**目标机器无需安装 Python 或任何运行环境**。

> ⚠️ 合规提醒：本项目定位为**自有游戏、工作室多开、测试自动化**等合法场景。请勿用于绕过反作弊、破坏游戏公平性或任何侵权用途。

---

## 2. 功能特性

### 2.1 可视化编排

| 能力 | 说明 |
|---|---|
| 节点式流程编辑器 | 基于 Vue Flow，拖拽节点 + 手动连线，支持任意拓扑 |
| 画布控制 | 放大 / 缩小 / 适应视图 / 上下左右平移（清晰图标 + 悬浮提示） |
| 可缩放面板 | 日志面板高度、属性面板宽度均可拖拽调整，整体填满窗口 |
| 鼠标定位新增 | 新节点生成在**鼠标指针位置** |
| 单次执行 | 任意动作节点可勾选「单次执行」，仅第一轮循环生效 |
| 撤销 / 重做 | **Ctrl+Z / Ctrl+Y**（顶栏 ↶ ↷ 按钮），覆盖增删节点、连线、拖动、改参数、拆分、打包、加载等所有改动 |
| 新建脚本 | 顶栏右上角 **＋ 新建**（「保存」左边）：清空画布与脚本名，误点可 `Ctrl+Z` 找回 |
| 保存 / 加载 | 自定义格式 `.agflow`，保存时弹出**原生保存对话框**（可覆盖 / 另存） |

### 2.2 节点类型

| 节点 | 图标 | 说明 |
|---|---|---|
| 延时 | ⏱ | 分段延时，每 1000ms 输出一次进度日志 |
| 找图 | 🎯 | OpenCV 模板匹配；可设阈值、超时、**超时处理（跳过/退出）**、找到后自动点击 |
| 判断分支 | 🔀 | 识图条件二分支，**双出口（成功 / 失败）**，按结果走不同连线 |
| 鼠标点击 | 🖱 | 坐标可**屏幕点选拾取**；左/右/中键、点击次数 |
| 键盘按键 | ⌨ | **按键录制**：点「录制」后直接按下按键即可识别（支持组合键） |
| 输入文本 | 📝 | 输入任意文本 |
| 键鼠录制 | ⏺ | **alt+F2**（可改）开始/停止，录制鼠标(点击/滚轮)与键盘(按下/抬起)，打包为**一个步骤**，支持 0.25x~4x 变速回放；可**一键拆分为可编辑节点**，也可把相邻步骤**打包合并**回来（见 [10.12](#1012-录制模型的拆分与打包)） |
| 终止条件 | 🛑 | 执行到此节点立即停止整个脚本（无论循环是否完成） |

### 2.3 图像识别

- 截图 → **框选**目标区域 → 自动存为模板
- 模板管理：**预览 / 重命名 / 删除**
- OpenCV `TM_CCOEFF_NORMED` 模板匹配，**灰度加速**（2560×1528 帧约 76ms）
- 支持**中文模板名**（内部用 `np.fromfile + imdecode` 规避 OpenCV 非 ASCII 路径缺陷）

### 2.4 窗口与输入

| 能力 | 说明 |
|---|---|
| 窗口枚举 | 只列出**任务栏真实窗口**（过滤工具窗口 / 有属主窗口 / DWM 隐藏窗口） |
| 窗口绑定 | 脚本只针对绑定的单个窗口运行，坐标自动换算 |
| 窗口预览 | 用 **PrintWindow(PW_RENDERFULLCONTENT)** 直接抓取窗口内容（可捕获被遮挡 / DirectX 窗口） |
| 坐标拾取 | **alt+F3**（可改）进入拾取 → **左键单击** → 捕获**真实屏幕坐标**（全局鼠标监听，无换算误差） |
| 输入模式 | **键鼠输入**（真实设备）/ **模拟输入**（PostMessage 后台消息，不占用物理键鼠） |

### 2.5 运行与调试

- **全局快捷键统一管理**：启动/停止、键鼠录制、坐标拾取三条**都能改键、都能单独停用**，默认依次是 `alt+F1` / `alt+F2` / `alt+F3`（界面顶栏 **⌨ 快捷键**）
- **实时日志**：WebSocket 推送，带**毫秒级时间戳**
- **循环执行**：整图按轮次循环
- **悬浮框**：可开关的置顶小窗，显示循环进度与当前节点，并内置 **启动/停止、暂停/继续、录制、循环次数（± 与直接输入）**，以及右上角的**回到界面图标**（可拖拽、点 ✕ 收起、**不抢焦点**）
- **暂停 / 继续**：界面与悬浮框都有。暂停只让流程停在**下一个检查点**，继续后从原地接着跑（不是重新开始）；暂停期间延时不再流逝，进度显示为 `⏸ 已暂停 · 第 n/m 轮`
- **急停**：界面按钮 / 快捷键 / 引擎侧停止。**停止始终由引擎执行**，不受两边状态显示影响；长延时也会在 250ms 内被打断
- **运行状态自愈**：前端每秒以 `/run/state` 为准校正按钮，引擎侧另有 1 秒看门狗把真实状态推给悬浮框，两边不会再出现"一个显示运行中、一个显示已停止"
- **单步容错**：单个节点失败只记日志，不中断整个流程（挂机更稳）
- **单实例保护 + 单页面**：重复启动会被拦截并提示；编辑器也只允许**一个** WebUI 窗口，重复打开的那个会看到「已在另一个窗口打开」而不会去干扰正在工作的窗口（刷新页面仍然正常，见 [10.19](#1019-为什么只允许一个-webui窗口v080-起)）
- **页面离开后端不再自杀（挂机安全）**：页面**静默掉线**（浏览器挂起/丢弃标签页、崩溃）时后端与悬浮框**继续运行**，页面回来还能连上；只有用户**真的关页面**（前端发告别信号）才在 5 秒宽限后退出，而且**流程运行中一律不退**。`AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1` 可恢复「断开即退出」的旧行为（见 [10.14](#1014-关闭-webui-即关闭后端v070-起)）
- **录制可拆分**：录完的「键鼠录制」步骤，点**顶栏常驻**的 **✂ 拆分录制**（或选中该节点后在右侧属性面板点 **✂ 拆分为可编辑步骤**），自动变成 点击 / 按键 / 延时 / 滚轮 等独立节点，可单独改坐标、改键、调顺序
- **步骤可打包**：反向操作。框选（`Shift`+拖拽）或 `Ctrl`+点击选中一串**相邻**步骤，点顶栏 **📦 打包合并**，合并回一个「键鼠录制」步骤
- **拆分后自动排版**：按编辑区大小铺成蛇形网格（不是一列排到底），相邻步骤首尾相接、连线不交叉；会被压到的原有节点整体让位
- **顶栏「关于」**：显示当前引擎版本（如 `关于 v0.8.0`），点一下在**新标签页**打开 GitHub 发布页查看更新与下载（新标签页，不会断开当前页面）
- **打开即进编辑器**：不再需要先点「新建脚本 / 编辑脚本」；新建脚本挪到编辑器右上角「保存」左边
- **外观：浅色 / 深色 / 跟随系统**：顶栏 **⚙ 设定 → 外观** 里切换，**默认跟随系统**；偏好只存本机浏览器（见 [10.18](#1018-外观浅色--深色--跟随系统v080-起)）
- **自定义背景**：顶栏 **⚙ 设定** 里选一张本地图片 → 按屏幕比例**截取** → 可调**透明度**（见 [10.17](#1017-自定义背景选图--按屏幕比例截取--透明度v071-起)）

---

## 3. 技术栈

### 3.1 前端

| 分类 | 选型 | 版本 | 用途 |
|---|---|---|---|
| 框架 | **Vue 3** | ^3.5.13 | 组合式 API |
| 语言 | **TypeScript** | ~5.6.2 | 全量类型 |
| 构建 | **Vite** | ^6.0.3 | 开发服务器 + 生产构建 |
| UI 组件 | **Naive UI** | ^2.44.1 | 暗色主题、表单、弹窗、消息 |
| 流程编辑器 | **Vue Flow** | ^1.x | 节点图（`@vue-flow/core` + `background` + `controls`） |
| 状态管理 | **Pinia** | ^3.0.4 | 流程元数据 / 日志 |
| 路由 | **Vue Router** | ^4.6.4 | 唯一主界面：编辑器（`/` 与未匹配路径都重定向到 `/editor`） |
| 类型检查 | **vue-tsc** | ^2.1.10 | CI 与构建前校验 |

### 3.2 引擎（后端）

| 分类 | 选型 | 用途 |
|---|---|---|
| 运行时 | **Python 3.11+**（本项目用 3.13） | 引擎语言 |
| Web 服务 | **FastAPI** + **uvicorn[standard]** | HTTP + WebSocket |
| 图像处理 | **OpenCV**（opencv-python） | 模板匹配 |
| 截图 | **mss** | 高速屏幕抓取 |
| 键鼠 | **pynput** | 真实输入 + 全局事件监听 |
| Windows API | **ctypes**（user32/gdi32/dwmapi） | 窗口枚举、PrintWindow、PostMessage、消息总线 |
| 数值 | **numpy** | 图像数组运算 |

### 3.3 桌面壳与打包

| 分类 | 选型 | 说明 |
|---|---|---|
| 桌面壳 | **Tauri 2**（Rust + WebView2） | 当前形态（v0.9.0 起）：原生窗口显示编辑器，Python 引擎作为 sidecar/资源随包分发 |
| 当前发行方式 | **PyInstaller `--onedir`**（引擎）+ **Tauri NSIS 安装包**（v0.9.0 起） | 引擎产出 `AutoGameTool-app\`（exe + `_internal\`），由 `build_desktop.ps1` 串起壳与安装包。<br>选文件夹形态是为了**不依赖系统临时目录**：onefile 每次启动都要往 `%TEMP%` 解压，`%TEMP%` 一旦不可用就会弹 `could not create temporary directory` 而起不来 |
| 安装包 | **NSIS 3.10**（Unicode） | 生成带向导、快捷方式、卸载器的 `AutoGameTool-Setup.exe` |
| 图标生成 | **Pillow 12** | `tools/make_icon.py` 生成多尺寸 `.ico` 与 favicon |
| NSIS 工具链 | 内置 `tools/nsis/` | `build_installer.ps1` 找不到 `makensis` 时自动下载 |

### 3.4 关键依赖版本（实测）

```
fastapi 0.141.1      uvicorn 0.52.4      opencv-python 5.0.0.93
numpy 2.5.3          mss 10.2.0          pynput 1.8.2
pyinstaller 6.22.2   vue 3.5.42          naive-ui 2.45.3
pillow 12.3.0        pnpm 11.4.0         NSIS 3.10 (Unicode)
```

---

## 4. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│              AutoGameTool.exe + _internal\（文件夹形态）        │
│                                                              │
│  ┌────────────────────────┐      ┌─────────────────────────┐  │
│  │  前端（Vue 3 静态包）    │      │  Python 引擎（FastAPI）  │  │
│  │  由引擎同源提供          │◄────►│                         │  │
│  │  · 流程图编辑器          │ HTTP │  · 流程解释执行器         │  │
│  │  · 属性 / 日志面板       │  +   │  · 视觉模块（OpenCV）     │  │
│  │  · 截图框选 / 坐标拾取    │  WS  │  · 输入模块（真实/模拟）   │  │
│  └────────────────────────┘      │  · 窗口模块（user32）      │  │
│                                   │  · 事件总线（键盘/鼠标钩子）│  │
│                                   └───────────┬─────────────┘  │
└───────────────────────────────────────────────┼────────────────┘
                                                │ Windows API
                          ┌─────────────────────┴─────────────────────┐
                          │  目标窗口（游戏）                          │
                          │  截图 / 模板匹配 / 点击 / 按键              │
                          └───────────────────────────────────────────┘
```

**运行数据流**

1. 用户双击 exe → 引擎启动（单实例检测）→ 自动打开浏览器到 `http://127.0.0.1:8765`
2. 前端编辑流程 → **防抖(150ms) + 每秒定时**同步流程到引擎（保证快捷键随时可用）
3. 点「运行」或按 `alt+f1` → 前端 `POST /run` → 引擎解释执行
4. 执行中通过 **WebSocket** 回传日志 / 状态 / 当前节点
5. 全局快捷键（`alt+f1`）走 WebSocket **通知前端**执行，与点「运行」完全一致

---

## 5. 目录结构

```
AutoGameTool/
├─ AutoGameTool-app/          # 发行版（PyInstaller 产物，文件夹形态）
│  ├─ AutoGameTool.exe        #   主程序（8.6 MB）
│  └─ _internal/              #   运行库（Python、OpenCV、Tk 等，约 170 MB）
├─ AutoGameTool-Setup.exe     # 安装包（NSIS 产物）
├─ README.md
├─ build_exe.ps1              # 一键打包：前端构建 + PyInstaller（--onedir）
├─ build_installer.ps1        # 一键制作安装包（自动定位 / 下载 NSIS）
├─ run_engine.ps1             # 开发：启动引擎
├─ run_frontend.ps1           # 开发：启动前端
│
├─ assets/
│  ├─ AutoGameTool.ico        # 应用图标（多尺寸 16~256，exe / 安装包 / 快捷方式共用）
│  └─ AutoGameTool.png        # 512px 主图
│
├─ installer/
│  └─ AutoGameTool.nsi        # NSIS 安装包脚本
│
├─ tools/
│  ├─ make_icon.py            # 用 Pillow 生成图标（同时输出前端 favicon 与 Tauri 图标）
│  ├─ to-utf8-bom.ps1         # 把 .ps1 / .nsi 统一转为 UTF-8 with BOM
│  ├─ smoke_test.ps1          # 冒烟测试：启动 exe → 校验接口 → 关闭
│  ├─ test_macro_split.ps1    # 录制拆分/打包算法回归测试（编译 macroSplit.ts 后跑 52 条断言）
│  ├─ test_macro_split.js     # 上述断言本体
│  ├─ test_engine_state.py    # 快捷键锁 / 快捷键绑定表 / 录制收尾清理 / 悬浮框状态去重 / 暂停状态机（纯逻辑，不起服务）
│  ├─ test_single_page.py     # 端到端：只允许一个 WebUI（4409 拒绝 + 原窗口不受影响 + 接管）
│  ├─ test_ui_appearance.py   # 界面回归：外观三态、顶栏/设置栏按钮位置、中文确认框（无头浏览器 + CDP）
│  ├─ test_appearance.ps1     # 外观判定纯函数回归（编译 appearance.ts 后跑 28 条断言）
│  ├─ test_appearance.js      # 上述断言本体
│  ├─ test_state_sync.py      # 端到端：WebUI 与悬浮框启停状态一致、暂停真的冻住、停止真能停
│  ├─ test_webui_close.py     # 端到端：页面离开时后端退不退（静默掉线不退 / 主动告别才退 / 运行中不退）
│  ├─ test_overlay_edit.py    # 悬浮框循环次数编辑（Tk 内部合成事件，不注入系统输入）
│  ├─ test_engine_log.py      # 运行日志：落盘、轮转、令牌绝不落盘
│  ├─ test_noconsole_log.ps1  # 打包产物核验：GUI 子系统（无控制台）+ 日志落盘 + 令牌掩码
│  ├─ test_bg_crop.ps1        # 背景截取几何回归测试（编译 bgCrop.ts 后跑 23 条断言）
│  ├─ test_bg_crop.js         # 上述断言本体
│  ├─ check_ui_imports.mjs    # 静态检查：.vue 里用到的 <n-xxx> 是否都 import 了（构建期自动跑）
│  ├─ test_installer.ps1      # 安装包端到端验证：装 → 校验 → 跑 → 卸载
│  └─ nsis/                   # NSIS 3.10 工具链（build_installer.ps1 可自动下载）
│
├─ frontend/                  # Vue 3 前端
│  ├─ package.json
│  ├─ pnpm-workspace.yaml     # pnpm v11 配置（allowBuilds 等）
│  ├─ vite.config.ts
│  ├─ index.html
│  ├─ public/favicon.ico
│  ├─ src/
│  │  ├─ main.ts              # 入口
│  │  ├─ App.vue              # 全局 Provider（主题/中文 locale）+ 布局
│  │  ├─ style.css            # 外观 token（深色默认 + 浅色覆盖）/ 全局样式
│  │  ├─ types.ts             # 节点 / 流程 / 日志类型
│  │  ├─ router/index.ts      # 路由
│  │  ├─ stores/project.ts    # Pinia：流程名/循环/输入模式/绑定窗口/日志
│  │  ├─ api/client.ts        # 引擎 HTTP 客户端
│  │  ├─ lib/macroSplit.ts    # ★ 录制拆分：把录制事件编译成可编辑步骤（纯函数）
│  │  ├─ lib/bgCrop.ts        # ★ 自定义背景的截取几何（纯函数，界面与导出共用）
│  │  ├─ lib/appearance.ts    # ★ 外观三态（浅色/深色/跟随系统）判定（纯函数）
│  │  ├─ stores/ui.ts         # Pinia：界面外观 + 自定义背景（存 localStorage）
│  │  ├─ views/
│  │  │  └─ Editor.vue        # 唯一主界面（画布 / 属性 / 日志 / 录制）
│  │  └─ components/
│  │     ├─ StepNode.vue      # 自定义流程节点（判断节点双出口）
│  │     ├─ ScreenCapture.vue # 截图框选 / 单点拾取
│  │     └─ SettingsModal.vue # 设定面板（外观 → 选图 → 截取 → 透明度）
│  └─ src-tauri/              # Tauri 2 桌面壳（Rust，可选）
│
└─ engine/                    # Python 引擎
   ├─ requirements.txt
   ├─ main.py                 # FastAPI 入口（25 个端点 + WebSocket）
   ├─ executor.py             # 图执行器（分支/单次/终止/宏回放）
   ├─ vision.py               # 截图 + 模板匹配 + 模板管理
   ├─ inputctl.py             # 真实输入 + 模拟输入（PostMessage）
   ├─ window.py               # 窗口枚举 / 截图 / 快速截图
   ├─ keybus.py               # ★ 全局键盘事件总线（唯一钩子）
   ├─ mousebus.py             # ★ 全局鼠标事件总线（唯一钩子）
   ├─ hotkey.py               # ★ 全局快捷键注册表（全部可改键 + 启用开关）
   ├─ picker.py               # 坐标拾取（快捷键由 hotkey.py 统一匹配）
   ├─ recorder.py             # 键鼠录制（快捷键由 hotkey.py 统一匹配）
   ├─ overlay.py              # ★ 悬浮框（tkinter 置顶小窗，显示循环进度与当前步骤）
   ├─ appconfig.py            # 用户配置读写（%APPDATA%\AutoGameTool\config.json）
   ├─ enginelog.py            # ★ 运行日志落盘（轮转 + 令牌掩码 + 接管 stdout/stderr）
   └─ ws_manager.py           # WebSocket 广播（含「日志同时落盘」的钩子）
```

> 运行时用户数据（模板、配置）位于 `%APPDATA%\AutoGameTool\`。

---

## 6. 快速开始

### 6.1 发行版（推荐）

**方式 A：安装包**

1. 双击 `AutoGameTool-Setup.exe`，按向导安装（默认安装到 `%LOCALAPPDATA%\AutoGameTool`）
2. 从开始菜单或桌面快捷方式启动
3. 程序会自动打开浏览器进入编辑器

**方式 B：免安装**

直接双击 `AutoGameTool.exe` 即可（绿色版，配置与模板仍写入 `%APPDATA%`）。

> 🔸 **只能运行一个实例**。重复启动会提示"程序已在运行"并退出——这是为了避免多开导致键盘钩子冲突。

### 6.2 开发环境

**前置要求**：Windows 10/11、Node.js 18+ 与 pnpm、Python 3.11+（本项目用 3.13）

```powershell
# 0) 首次（可选）：生成应用图标；打包时也会自动补齐
engine\.venv\Scripts\python tools\make_icon.py

# 1) 引擎
cd engine
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8765

# 2) 前端（另开一个终端）
cd frontend
pnpm install
pnpm dev            # → http://localhost:1420
```

也可以直接用项目根目录的封装脚本（等价于上面两步）：

```powershell
.\run_engine.ps1     # 引擎  → http://127.0.0.1:8765
.\run_frontend.ps1   # 前端  → http://localhost:1420
```

> 开发时两个都跑起来，前端通过 Vite 访问引擎的 8765 端口；打包版则由引擎同源托管前端静态文件，因此只需要一个 exe。
> v0.3.0 起开发模式需先设 `$env:AUTOGAMETOOL_DEV='1'` 再启动引擎（放行 1420 端口 CORS 并跳过令牌校验），否则 vite 页面调引擎会 401。
> 若 pnpm 因依赖状态检查中止（`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`），见 [9.4 关于 pnpm 11](#94-关于-pnpm-11)。

---

## 7. 使用指南

### 7.1 快捷键

三条全局快捷键**都能改键、都能单独停用**（顶栏 **⌨ 快捷键** → 点键位显示区 → 按下想要的组合键 → 保存）：

| 快捷键 | 功能 | 可配置 |
|---|---|---|
| `alt+F1` | 启动 / 停止脚本（全局，游戏窗口聚焦时也生效） | ✅ 改键 + 停用 |
| `alt+F2` | 键鼠录制：开始 / 停止 | ✅ 改键 + 停用 |
| `alt+F3` | 坐标拾取：进入选取 → 左键单击捕获坐标 | ✅ 改键 + 停用 |
| `Ctrl+Z` | 画布撤销上一步改动 | ❌（固定） |
| `Ctrl+Y` / `Ctrl+Shift+Z` | 画布重做 | ❌（固定） |

> 改键规则：支持 `ctrl` / `alt` / `shift` / `win` + 字母、数字、`f1`–`f12`（例如 `alt+f1`、`ctrl+shift+a`）。
> 同一组按键不能给两个功能用，保存时引擎会**直接拒绝并说明冲突**；启用中的功能必须有键，清空后想启用会被拦下来。
> 停用某个快捷键**不影响界面按钮**（「开始录制」按钮照样能点），只是那组按键不再触发。
> 改键结果写在 `%APPDATA%\AutoGameTool\config.json` 的 `hotkeys` 里，升级/重装都保留。

> 撤销/重做只在画布上生效；光标在输入框里时 `Ctrl+Z` 交给浏览器做文本撤销。

### 7.2 输入模式

| 模式 | 原理 | 占用物理键鼠 | 备注 |
|---|---|---|---|
| **键鼠输入** | pynput 真实输入 | ✅ 占用 | 最兼容，需要游戏在前台 |
| **模拟输入** | `PostMessage` 向目标窗口发消息 | ❌ 不占用 | 需绑定窗口；仅对"消息循环型"程序有效 |

> 选择「模拟输入」时必须**先在顶栏绑定目标窗口**，否则自动回退为键鼠输入。

### 7.3 模板管理

在「找图」或「判断分支」节点中：

1. 点「截取」→ 弹窗内**选择窗口**（可切换目标，含刷新）→ 框选区域 → 保存
2. 选中模板后下方显示**预览图**，可**重命名 / 删除**
3. 重命名会**同步更新所有引用该模板的节点**

### 7.4 工程文件格式（`.agflow`）

```jsonc
{
  "format": "agflow",
  "version": 1,
  "name": "刷副本脚本",
  "repeat": 10,                       // 循环轮数
  "input_mode": "real",               // real | simulated
  "window": { "hwnd": 123456, "title": "造梦西游4",
              "rect": { "left": 100, "top": 60, "right": 1380, "bottom": 840,
                        "width": 1280, "height": 780 } },  // 保存时窗口位置尺寸（分辨率自适应用）
  "screen": { "width": 2560, "height": 1440 },  // 保存时主屏物理分辨率（跨分辨率运行按比例换算坐标）
  "nodes": [
    { "id": "n1", "type": "find_image",
      "params": { "template": "任务", "threshold": 0.85,
                  "timeout_ms": 5000, "on_timeout": "skip", "click": true },
      "once": false },
    { "id": "n2", "type": "judge",
      "params": { "template": "返回地图（成功）", "threshold": 0.85, "timeout_ms": 3000 } },
    { "id": "n3", "type": "macro",
      "params": { "events": [
        { "t": 0,   "type": "mousedown", "x": 900, "y": 500, "button": "left" },
        { "t": 60,  "type": "mouseup",   "x": 900, "y": 500, "button": "left" }
      ], "speed": 1 } },
    { "id": "n4", "type": "terminate", "params": {} }
  ],
  "edges": [
    { "id": "e1", "source": "n1", "target": "n2", "sourceHandle": null },
    { "id": "e2", "source": "n2", "target": "n3", "sourceHandle": "yes" },
    { "id": "e3", "source": "n2", "target": "n4", "sourceHandle": "no" }
  ]
}
```

> 判断节点的两条出边用 `sourceHandle` 区分：`"yes"`（成功）/ `"no"`（失败）。
> `screen` 与 `window.rect` 由编辑器自动写入（旧版文件没有也能正常运行，只是不做分辨率换算）。
> v0.4.0 起**加载脚本默认全局绑定**——不恢复文件里保存的窗口（旧 hwnd 多半已失效），需要绑定时在顶栏手动选择。

---

## 8. 引擎 API 参考

引擎默认监听 `http://127.0.0.1:8765`（开发文档 `/docs`）。
**v0.3.0 起除 `/health` 与静态资源外所有接口需要令牌**（`Authorization: Bearer <token>` 或 `?token=`），见 [10.8](#108-本地访问令牌v030-起)。

### 基础

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/debug/kb` | 诊断：键盘事件计数与钩子存活状态 |
| WS | `/ws` | 日志 / 状态 / 事件推送 |

### 窗口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/windows/list` | 枚举任务栏窗口（hwnd / 标题 / pid / 位置） |

### 屏幕与视觉

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/screen/screenshot?window=<hwnd>` | 截图（可选指定窗口），返回 JPEG data URL |
| GET | `/vision/templates` | 模板列表 |
| GET | `/vision/template/{id}/image` | 模板预览图 |
| POST | `/vision/capture_template` | 保存裁剪图为模板 |
| POST | `/vision/template/rename` | 重命名模板 `{id, new_name}` |
| POST | `/vision/template/delete` | 删除模板 `{id}` |
| POST | `/vision/match` | 模板匹配 `{template, threshold, window}` → `{found,x,y,score}` |

### 输入

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/input/click` | `{x,y,button,clicks,mode,window}` |
| POST | `/input/key` | `{key,mode,window}` |
| POST | `/input/text` | `{text,mode,window}` |
| POST | `/input/probe` | **诊断模拟输入**：返回目标子窗口 / 焦点窗口 / 客户区坐标 / PostMessage 结果 |

### 流程

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/flow/load` | 仅加载流程（不执行），供快捷键使用 |
| POST | `/run` | 执行流程（已有流程运行时返回 409） |
| POST | `/run/stop` | 停止执行（会等流程真正收尾，最多 2 秒；同时清除暂停） |
| POST | `/run/pause` | 暂停（在下一个检查点生效；空闲时返回 `paused=false`） |
| POST | `/run/resume` | 从暂停处继续 |
| GET | `/run/state` | 真实运行状态：`{running, paused}` |

### 配置与工具

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/config/hotkeys` | 读取**全部**快捷键绑定（`{bindings:[{id,label,keys,enabled}], defaults:[...]}`），界面据此渲染设置列表 |
| POST | `/config/hotkeys` | 整体保存绑定；校验「重复组合」「启用却没键」，冲突时返回 **400 + 具体原因** |
| GET / POST | `/config/hotkey` | 兼容旧接口：只读写「启动 / 停止脚本」这一条 |
| POST | `/goodbye` | 页面主动告别（关闭/跳转离开时由前端 `sendBeacon` 调用）：5 秒宽限内没有页面重连就优雅退出；流程运行中不退。需令牌 |
| GET | `/overlay/state` | 悬浮框状态：`{enabled, available, visible, loop, total, repeat, running, recording, step, error}` |
| POST | `/overlay/enable` | 开 / 关悬浮框 `{enabled: bool}`（状态持久化到 `config.json`） |
| POST | `/pick/start` · `/pick/cancel` | 坐标拾取启用 / 取消 |
| POST | `/record/start` · `/record/stop` | 键鼠录制开始 / 停止 |

### WebSocket 消息类型

| type | 载荷 | 说明 |
|---|---|---|
| `log` | `{level, message, step, ts}` | 执行日志 |
| `state` | `{state: "running"\|"idle", paused: bool}` | 运行/暂停状态（引擎为唯一事实来源，每秒兜底广播） |
| `overlay` | `{enabled: bool}` | 悬浮框开关变化（多标签页同步；点悬浮框的 ✕ 也会广播） |
| `repeat` | `{value: int}` | 悬浮框调整了循环轮数，前端应更新 `repeat` |
| `run_request` | `{ts}` | 引擎已判定「应当启动」，前端用画布上最新的流程调 `/run`。**停止不会走这条**——引擎侧直接执行（见 [10.13](#1013-启停状态为什么不会再分叉v070-起)） |
| `hotkey` | `{ts}` | 旧版引擎的启停广播，仅为兼容保留；新版前端收到后仍按老逻辑 toggle |
| `picked` | `{x, y}` | 坐标拾取结果 |
| `recording` | `{recording: bool}` | 录制状态 |
| `recorded` | `{events: [...]}` | 录制完成的事件列表 |
| `busy` | `{ts}` | 已有另一个编辑器窗口在运行，本页即将被拒绝（随后以 **4409** 关闭，见 [10.19](#1019-为什么只允许一个-webui窗口v080-起)） |

---

## 9. 打包与发布

> **形态变更（v0.9.0）**：本项目已从「浏览器 WebUI」迁移为 **Tauri 2 桌面版 + Python sidecar**：
> 界面在原生窗口里显示，引擎仍以本地 HTTP/WS 提供服务（`127.0.0.1:8765`），
> 用户数据目录与脚本格式完全不变（`%APPDATA%\AutoGameTool`、`.agflow`、找图模板按 id 引用）。
>
> - 开发：`pnpm tauri dev`（壳会用 venv 里的解释器拉起引擎源码，并开 DEV 模式免令牌 + 放行 vite 的 CORS）
> - 构建：`.\build_desktop.ps1`（前端 → 引擎 onedir → `tauri build` → NSIS 安装包）
> - **WebUI 时期的回归测试脚本已全部移除**（`tools\test_*.py/ps1/js`、`smoke_test.ps1` 等，仍可从 git 历史取回）；
>   下面 9.3~9.13 为迁移前的历史说明，保留供查阅，不再对应仓库里的文件。

### 9.1 打包发行版（文件夹形态）

```powershell
# 一键（推荐）：类型检查 + 前端构建 + PyInstaller 打包 + 复制到 AutoGameTool-app\
.\build_exe.ps1
```

脚本做四件事：

1. `vue-tsc --noEmit` 类型检查
2. **`tools\check_ui_imports.mjs` 静态检查**：`.vue` 里用到的 `<n-xxx>` 是否都在该文件里 import 了
3. `vite build` 产出 `frontend\dist`
4. 调用 `engine\.venv\Scripts\pyinstaller.exe` 打成**文件夹形态**（带应用图标），并整体复制到 `AutoGameTool-app\`

> 第 2 步为什么必须有（v0.7.1 真实事故）：Naive UI 是按需 import 的，没有全局注册。如果某个 `<n-xxx>` 忘了 import，Vue 会把它当未知元素渲染，**具名插槽里的内容被整个丢掉**——那个按钮在界面上根本不存在。而 `vue-tsc` 只查类型、`vite build` 只做打包，**两者都不报错**，功能就这么无声无息地消失了（当时是 `NPopconfirm` 漏了，顶栏「＋ 新建」和属性面板的「✂ 拆分为可编辑步骤」都不显示）。现在构建期会直接失败并指出缺哪个组件。

等价的 PyInstaller 命令：

```powershell
cd engine
.venv\Scripts\pyinstaller.exe --noconfirm --clean --onedir --noconsole --name AutoGameTool `
  --icon ..\assets\AutoGameTool.ico `
  --add-data "..\frontend\dist;frontend_dist" `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on `
  main.py
```

产物：`engine\dist\AutoGameTool\` → 复制为 `AutoGameTool-app\`（exe 8.6 MB + `_internal\`，整目录约 179 MB）

**打包要点**

- 前端 `dist` 通过 `--add-data` 打进 `frontend_dist`，运行时由引擎同源提供
- opencv / onnxruntime 等含动态库的包建议加 `--collect-all`
- **用 `--onedir` 而不是 `--onefile`**（v0.8.2 起）：单文件版每次启动都要往 `%TEMP%` 解压 `_MEIxxxx`，而 `%TEMP%` 可能不可用（被清理掉、或从 SmartScreen 点「仍要运行」拉起时环境异常），此时 Windows 的 `GetTempPath` 会退回「当前目录」（往往是 `C:\Windows\System32`）→ 弹 `could not create temporary directory` 起不来。文件夹形态没有解压这一步，启动也更快；回归测试见 `tools\test_broken_temp.ps1`
- 分发时必须**整个目录一起给**（不能只复制 exe）；安装包已处理好
- 图标取自 `assets\AutoGameTool.ico`，缺失时脚本会先调用 `tools\make_icon.py` 生成

### 9.2 制作安装包（NSIS）

```powershell
.\build_exe.ps1        # 1) 先产出 AutoGameTool-app\
.\build_installer.ps1  # 2) 再产出安装包
```

产物：`AutoGameTool-Setup.exe`

`build_installer.ps1` 的行为：

1. 检查 `AutoGameTool.exe`、应用图标、`installer\AutoGameTool.nsi` 是否齐备
2. 依次在 环境变量 `AUTOGAMETOOL_MAKENSIS` → `PATH` → `tools\nsis\` → 系统安装目录 中查找 `makensis.exe`；都没有就**自动下载并解压 NSIS 3.10** 到 `tools\nsis`
3. 用 `/DPROJECT_ROOT=<项目根>` `/DOUT_DIR=<项目根>` 调用 `makensis`（NSIS 3 中 `Icon` / `File` / `OutFile` 的相对路径是以「`.nsi` 所在目录」为基准的，所以统一传绝对路径）
4. 输出安装包大小与 SHA256 校验值

**安装包行为**

| 项 | 说明 |
|---|---|
| 安装目录 | `%LOCALAPPDATA%\AutoGameTool`（当前用户，**不触发 UAC**） |
| 可选组件 | 主程序（必需）+ 桌面快捷方式（可选，默认勾选） |
| 快捷方式 | 开始菜单（启动 / 使用说明 / 卸载）+ 桌面 |
| 卸载入口 | 设置 → 应用 → 已安装的应用（注册标准 `Uninstall` 键） |
| 用户数据 | `%APPDATA%\AutoGameTool`（模板 / 配置，**卸载时询问，默认保留**） |
| 版本升级 | 检测到旧版会先静默卸载再安装，用户数据不受影响 |
| 静默安装 | `AutoGameTool-Setup.exe /S`（`/D=路径` 可指定目录，须置于最后且不加引号） |
| 静默卸载 | `"%LOCALAPPDATA%\AutoGameTool\Uninstall.exe" /S`（静默卸载一律保留用户数据） |
| 系统要求 | Windows 10 / 11（安装时校验，低版本直接拦截） |
| 免安装绿色版 | 直接跑 `AutoGameTool.exe`，数据同样写入 `%APPDATA%\AutoGameTool` |

> **关于体积**（v0.8.2 实测）：改成文件夹形态后安装包**反而更小了**——`AutoGameTool-app\` 整目录 179 MB，其中大量未压缩的 DLL 交给 NSIS 的 LZMA 压缩，安装包只有 **51.8 MB**（此前单文件版是 71.3 MB：PyInstaller `--onefile` 的载荷本身已 deflate 过，NSIS 几乎压不动，实测压缩率 99.6%）。

> 安装前建议先退出正在运行的 AutoGameTool：安装包会自动 `taskkill` 旧进程，但手动退出更稳妥（避免脚本执行到一半被打断）。

### 9.3 源码编码约定（重要）

`build_exe.ps1`、`build_installer.ps1`、`installer\AutoGameTool.nsi` 内含中文，**必须保存为「UTF-8 with BOM」**：

- Windows PowerShell 5.1 对无 BOM 的 UTF-8 文件会按系统 ANSI 代码页解码，中文变乱码并抛出「字符串缺少终止符」之类的语法错误
- `makensis` 同样依赖 BOM 判断源文件是 UTF-8

改完脚本后跑一次即可修正：

```powershell
.\tools\to-utf8-bom.ps1            # 修复所有 .ps1 / .nsi
.\tools\to-utf8-bom.ps1 -Check     # 仅检查，未通过返回 1（可放进 CI）
```

### 9.4 关于 pnpm 11

pnpm 11 起不再读取 `package.json#pnpm`，也不再从 `.npmrc` 读取非 registry 配置，构建相关设置统一放在 `frontend\pnpm-workspace.yaml`（本项目已配置 `allowBuilds`）。

另外，pnpm 11 在执行任何 script 前会做依赖状态检查，**无 TTY 时可能直接中止**：

```
ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY
```

因此 `build_exe.ps1` 与 `run_frontend.ps1` 都直接调用 `node_modules\.bin\` 下的 `vue-tsc` / `vite`，不经过 pnpm——更快、离线可用，也不会踩到上述问题。

### 9.5 产物体检（冒烟测试）

```powershell
.\tools\smoke_test.ps1                                                             # 测根目录 exe
.\tools\smoke_test.ps1 -ExePath "$env:LOCALAPPDATA\AutoGameTool\AutoGameTool.exe"  # 测安装后的 exe
```

> 安装目录以注册表 `HKCU\Software\AutoGameTool\InstallDir` 为准：安装脚本里有 `InstallDirRegKey`，**装过一次之后就会沿用那个目录**（比如你当初装到了 `E:\Apps\AutoGameTool`，升级不会把它搬回 `%LOCALAPPDATA%`）。`.\tools\test_installer.ps1` 也是按这个规则解析安装位置的。

脚本会启动 exe，逐项校验 `/health`、`/debug/kb`（键盘钩子是否存活）、`/windows/list`、`/vision/templates`、`/config/hotkey`、`POST /flow/load` 以及内嵌前端页面与 favicon，最后关闭进程并输出 PASS/FAIL（有失败项时返回 1，可直接用于 CI）。

它顺带处理了两个常见的"假失败"：

- 把 `TEMP` / `TMP` 指向一个**可写的解压目录**（优先系统临时目录，不可写时才退到 exe 同级的 `.smoketmp`，并在结束时清理）——`--onefile` 需要一个可写的解压目录，受限环境下会报 `Failed to extract VCRUNTIME140.dll: ... Permission denied` 并秒退
- 设置 `AUTOGAMETOOL_NO_BROWSER=1`，避免测试期间弹出浏览器

### 9.6 录制拆分与打包算法回归测试

```powershell
.\tools\test_macro_split.ps1
```

`macroSplit.ts` 是不依赖 Vue 的纯函数，所以能脱离浏览器直接跑断言：脚本用前端自带的 `tsc` 把它编成 CommonJS，再由 node 执行 **52 条断言**，结束后清掉中间产物。覆盖：

- **拆分**：轨迹丢弃、左右键坐标、组合键合并、`ctrl` 连配两键、延时插入、空输入
- **打包**：点击/按键/延时/嵌套录制、双击、不可打包类型整体拒绝
- **往返等价**：`打包 → 再拆分` 后步骤序列、坐标、组合键、延时长度都不变
- **网格排版**：12 步铺成 3 列 × 4 行、相邻步骤必定只差一个行距或列距（无长对角线）、位置不重叠、小批量仍是单列
- **链序判定**：隔着没选的步骤 / 成环 / 有分支 / 两条独立链 都应被拒绝

### 9.7 引擎行为回归测试

```powershell
# 纯逻辑：快捷键锁 / 快捷键绑定表 / 录制收尾清理 / 悬浮框状态去重（不起服务、不装钩子）
engine\.venv\Scripts\python.exe tools\test_engine_state.py

# 端到端：WebUI 与悬浮框的启停状态始终一致、停止真的能停
engine\.venv\Scripts\python.exe tools\test_state_sync.py

# 端到端：关闭 WebUI 页面后后端自动退出（含「刷新页面不该退出」的宽限期保护）
engine\.venv\Scripts\python.exe tools\test_webui_close.py

# 端到端：只允许一个 WebUI（第二个连接被 4409 拒绝）+ 快捷键接口读写与校验
engine\.venv\Scripts\python.exe tools\test_single_page.py

# 悬浮框：循环次数直接编辑（**不注入系统级鼠标/键盘**）
engine\.venv\Scripts\python.exe tools\test_overlay_edit.py
```

五个脚本合计 **176 条断言**，覆盖的都是「改错了很难靠肉眼发现」的状态逻辑：

- `test_engine_state.py`（89 条）：按住 `alt` 连按两次 `f1` 必须触发两次；长按 `f1` 只触发一次；两条便捷键互不干扰；停用的绑定不触发也不占锁；**快捷键绑定表**（默认 alt+F1/F2/F3、旧配置 `hotkey` 迁移到新表并落盘、改键后锁清空、重复组合与「启用却没键」被拒、键名别名 `ArrowUp→up`）；**录制收尾清理**（按录制快捷键本身产生的按键要被剔掉，但录制中段/开头的合法 `alt` 组合不能误删）；**访问令牌持久化**（两次调用同一令牌、落盘、过短令牌重生成、环境变量优先）；**「启动」不依赖页面**（页面没响应时用缓存流程兜底、页面正常响应时不重复启动）；悬浮框状态去重（值没变不重绘）；`overlay` 模块级 API 完整性；Executor 暂停状态机（空闲暂停无效、停止清暂停、任务结束后 `reconcile` 复位）；**WebUI 窗口定位只认浏览器**（造一个标题唯一的非浏览器窗口，断言它必须被拒绝——旧版会返回它）；循环轮数直接输入的夹取与同步
- `test_state_sync.py`（32 条）：`/run` 之后 `/run/state` 与 `/overlay/state` 必须同时为「运行中」；`/run/stop` 后两边都回到「未运行」；长延时能被立刻中断；反复停止幂等；**暂停必须真的冻住流程**（暂停 6.5 秒后 5 秒的延时仍未结束）、继续后正常跑完、暂停中也能停止、空闲暂停不产生假状态
- `test_webui_close.py`（17 条）：从未有页面连接过 → 永不退出；**静默掉线 → 不退出**（挂机不中断，`/health` 仍可用、重连可成功）；刷新式重连 → 不退出；**主动告别 → 宽限期后退出**（且 `/goodbye` 无令牌 401）；**流程运行中告别 → 也不退出**；`AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1` 时才恢复旧行为
- `test_single_page.py`（19 条）：`/config/hotkeys` 默认值 / 改键 / 停用 / 冲突与空键被 400 拒绝；第二个 WebSocket 被 **4409** 拒绝且**不影响已连接的页面**；原窗口关闭后新连接能接管（刷新页面不会被锁死）
- `test_overlay_edit.py`（19 条）：点击数字进入编辑态（`WS_EX_NOACTIVATE` 被临时解除）；点击 / 回车 / 小键盘回车 / Esc / 失焦**都绑了处理函数**；输入框宽度能显示 5 位数字；提交发出 `repeat_set:<n>`、提交后恢复「不抢焦点」；越界夹到 1–99999、非法输入不产生动作；`Esc` 放弃、恢复显示并恢复「不抢焦点」；运行中禁用且点击不进入编辑态；**激活期内（窗口拿不到前台时）的延时判定绝不能抢跑提交**——把前台窗口固定为 0 并手动触发那次判定，断言编辑态与用户已敲进去的内容都不丢

> 端到端脚本会真起一个引擎进程，并把 `APPDATA` 指向项目内 `.tmp\`，因此**不会碰你自己的 `%APPDATA%\AutoGameTool` 配置**（顺带保证测试期间悬浮框是关的、不弹窗）。它们需要 8765 端口空闲：先退出正在运行的 AutoGameTool。
>
> `test_overlay_edit.py` 会在屏幕上短暂出现一个悬浮框窗口，但**只用 Tk 内部合成事件驱动**——不移动你的鼠标、不模拟按键。这是刻意的：早期版本用真实点击 + 真实按键去测，那会劫持用户的鼠标键盘（还把字符打进当时的前台窗口），而且只要用户此刻在用电脑就必然测不稳。
>
> 该脚本里的「提交 / 放弃」是直接调用 `Return`、`Esc` 绑定执行的那两个回调，而不是合成 `<Return>` / `<Escape>`：Tk 会把**键盘事件重定向到当前焦点窗口**，而自动化环境下悬浮框常拿不到真实焦点（`SetForegroundWindow` 被系统拒绝），合成的回车会被丢到别处、提交根本不发生——那是环境限制，不是产品缺陷（实测过：同一份代码在本机随机失败，日志里 `focus_get()` 是 `None`）。因此**真实键盘路径（点数字 → 手敲 → 回车）按约定由用户手工确认**，自动化负责逻辑、夹取、状态回滚与绑定是否存在。

### 9.8 背景截取几何回归测试

```powershell
.\tools\test_bg_crop.ps1
```

`bgCrop.ts` 同样是不依赖 DOM 的纯函数：脚本用前端自带的 `tsc` 编译后由 node 执行 **23 条断言**，覆盖「绘制矩形必须完全覆盖取景框（任何比例 × 缩放 × 平移组合）」「平移被夹住后图片边缘正好贴住框边」「等比缩放不变性」「导出分辨率与总像素上限」「异常输入不产生 NaN」。这类几何偏差差几个像素肉眼看不出来，只能靠断言。

### 9.9 外观判定回归测试

```powershell
.\tools\test_appearance.ps1
```

`appearance.ts` 是「浅色 / 深色 / 跟随系统」的纯逻辑，同样编译后由 node 跑 **28 条断言**：非法与历史值（`undefined` / `''` / `'Light'` / 数字 / 对象）一律收敛到**默认的跟随系统**；「跟随系统」时跟系统的浅/深走，**取不到系统偏好时保持深色**（不突然刷白）；显式选择优先于系统；选项表顺序与文案（「跟随系统（当前深色）」）。这里出错的表现是「选了浅色还是黑的」「升级后默认外观被改掉」，肉眼很难覆盖到。

### 9.10 界面回归测试（无头浏览器）

```powershell
engine\.venv\Scripts\python.exe tools\test_ui_appearance.py
```

用**无头 Edge + CDP**跑 **28 项断言**（虚拟输入，不碰你的鼠标键盘；跑完把截图留在 `.tmp\ui-shots\` 供人工核对外观）：外观默认跟随系统、系统深色/浅色时界面真的跟着变、设定面板里的三个选项、显式选择覆盖系统并持久化（刷新后仍在）、**顶栏有「快捷键 / 悬浮框」且设置栏有「撤销 / 重做」**（本版的位置对调）、循环轮数输入框宽度 ≥ 110px、顶栏是「关于」且指向 GitHub 发布页、新建确认框按钮是**中文的「确定 / 取消」**、快捷键面板列出三条并带启用开关。

> 该脚本需要 `frontend\dist`（先 `.\build_exe.ps1` 或 `cd frontend; pnpm build`）：源码运行时引擎从 `engine\frontend_dist` 提供界面，脚本会临时复制一份并在结束时清理。

### 9.11 安装包端到端验证

```powershell
.\tools\test_installer.ps1                  # 验证完自动卸载
.\tools\test_installer.ps1 -KeepInstalled   # 验证后保留安装
```

脚本按真实用户路径跑一遍完整闭环，共 25 项断言：

1. 静默安装（`/S`）：安装位置为注册表记录的 `InstallDir`（首次安装即 `%LOCALAPPDATA%\AutoGameTool`）
2. 校验主程序 / README / Uninstall.exe 是否落盘
3. 校验开始菜单 3 个快捷方式与桌面快捷方式
4. 校验注册表：`DisplayName`、`DisplayVersion`（期望值从 `installer/AutoGameTool.nsi` 的 `APP_VERSION` 读出，不写死）、`UninstallString`、`QuietUninstallString`、`InstallLocation`、`DisplayIcon`、`EstimatedSize`、`App Paths`
5. 对**已安装的 exe** 跑一遍 `smoke_test.ps1`
6. 静默卸载，校验安装目录 / 快捷方式 / 注册表项均已清理，且**用户数据被保留**

> 注意：该脚本会写注册表与「开始菜单 / 桌面」，需要相应权限；它不会删除 `%APPDATA%\AutoGameTool`（模板与配置）。
>
> 它**会先卸载本机已安装的副本再重装**（安装包自身的行为就是升级前先静默卸载旧版）。只想在已装好的副本上跑冒烟测试、不动安装的话，用 `.\tools\smoke_test.ps1 -ExePath <安装目录>\AutoGameTool.exe`。

### 9.12 打包产物核验（无控制台 + 日志落盘）

```powershell
.\tools\test_noconsole_log.ps1                    # 默认测 AutoGameTool-app\AutoGameTool.exe
.\tools\test_noconsole_log.ps1 -ExePath <路径>     # 测别的副本
```

针对 v0.7.3 的两条硬要求，在**打包产物**上核验（10 项检查）：

1. `AutoGameTool.exe` 是 **GUI 子系统**（PE 头 `Subsystem = 2`），不会分配控制台。同一段检测代码对 `engine\.venv\Scripts\python.exe` 读出 `3`（控制台）作为阳性对照——否则「没看到控制台窗口」可能只是检测本身失效
2. 启动产物后枚举它的**全部顶层窗口**（v0.7.3~v0.8.1 的单文件版会同时存在「父 bootloader」与「真正跑 Python 的子进程」两个同名进程，两个都查；v0.8.2 起的文件夹形态只有一个进程），断言没有任何控制台类窗口（`ConsoleWindowClass` / `CASCADIA_HOSTING_WINDOW_CLASS` 等），并且确实看到了悬浮框的 `TkTopLevel`
3. `%APPDATA%\AutoGameTool\engine.log` 被创建、含带版本号的启动记录，且日志里的 `token=` 已掩成 `***`、**不含启动时传入的真实令牌**

> 脚本用固定令牌（`AUTOGAMETOOL_TOKEN`）启动产物，才能断言「真令牌没有落盘」；它不注入任何真实鼠标 / 键盘，只在开始时把已有的 `engine.log` 备份到 `.tmp\`。运行前需 8765 端口空闲。

### 9.13 发布 Release

安装包构建完成后，用 GitHub CLI 上传到 Releases：

```powershell
gh release create v0.7.2 .\AutoGameTool-Setup.exe --title "v0.7.2 —— ..." --notes-file .\notes.md
gh release upload v0.7.2 .\AutoGameTool-Setup.exe --clobber   # 补传 / 覆盖已有资产
```

约定：

- **版本号必须三处一致**：`engine/main.py`（FastAPI title + `/health`）、`frontend/package.json`、`installer/AutoGameTool.nsi`（`APP_VERSION` / `VIProductVersion`）
- **Release 说明直接取自本 README 的「更新日志」对应章节**，保持单一事实来源，不在别处另写一份
- `AutoGameTool.exe` 与 `AutoGameTool-Setup.exe` **不入库**（见 `.gitignore`），只随 Release 分发；仓库里始终只有源码
- 补传资产用 `--clobber` 覆盖同名文件，避免留下 `state=starter` 的僵尸资产

---

## 10. 关键设计说明

### 10.1 为什么用「事件总线」管理钩子（重要）

Windows 低级键盘钩子（`WH_KEYBOARD_LL`）是**系统级资源**。早期版本为每个功能（启停快捷键、坐标拾取、录制）各自创建/销毁监听器，**反复装卸会破坏钩子链，导致键盘全局失灵（需重启电脑）**。

现在改为：

- `keybus.py` / `mousebus.py`：**全进程各自唯一**一个常驻监听器（启动时创建，永不销毁）
- 所有功能只向总线**注册/注销回调**；录制时仅切换标志
- 效果：连续录制多轮，键盘钩子始终存活

### 10.2 中文模板名处理

OpenCV 的 `cv2.imread / imwrite` 在 Windows 上**不支持非 ASCII 路径**，会静默返回 `None`，导致中文模板"重命名后消失"。

`vision.py` 统一改用：

```python
# 读
data = np.fromfile(path, dtype=np.uint8)
img = cv2.imdecode(data, cv2.IMREAD_COLOR)
# 写
ok, buf = cv2.imencode(".png", img)
buf.tofile(path)
```

### 10.3 单实例保护

启动时创建命名互斥体；若已存在则提示并退出。多开会创建多套键盘钩子互相干扰。

### 10.4 DPI 感知

引擎启动即调用 `SetProcessDpiAwareness(2)`（每显示器 DPI 感知），保证 `GetWindowRect` 与截图/点击坐标在同一坐标系。

### 10.5 识别加速

| 优化 | 效果 |
|---|---|
| 匹配前转**灰度** | 约 3 倍提速（2560×1528 帧约 76ms） |
| 键鼠输入模式用 **mss 区域截图** | 比 PrintWindow 快约 10 倍 |
| 模拟输入模式用 **PrintWindow** | 保证窗口被遮挡时仍可截取 |

### 10.6 快捷键执行链路

```
按 alt+f1 → 引擎判定当前状态 → 要停止：引擎侧直接停（不惊动前端）
                              → 要启动：广播 {type:"run_request"} → 前端调 POST /run
```

好处：启动始终使用**前端当前最新流程**，不依赖引擎侧的流程缓存；而「停止」由引擎自己执行，不必先跟前端对齐状态（旧版正是这里出的问题，见 [10.13](#1013-启停状态为什么不会再分叉v070-起)）。两种动作都会在日志面板留下明确记录（`全局快捷键：启动脚本` / `停止脚本`），便于确认快捷键到底有没有生效。

> 每次按键都会记录，所以「快捷键疑似无效」可以直接从日志判断：**日志里没有这一行 = 按键没被识别**（检查是否多开、钩子是否被占用）；**有这一行但流程没动 = 后续链路问题**（看紧随其后的报错）。

### 10.7 无人值守启动

引擎启动后默认会自动打开浏览器到 `http://127.0.0.1:8765`。设置环境变量后可以跳过：

```powershell
$env:AUTOGAMETOOL_NO_BROWSER = '1'
.\AutoGameTool.exe
```

适用于自动化测试、开机自启、由其他程序拉起的场景；界面上仍可手动访问该地址。

> 注意：v0.8.1 起**页面静默掉线不再关后端**（挂机安全），只有用户**主动关页面**（前端发告别信号）才会在 5 秒宽限后退出；流程运行中一律不退。详见 [10.14](#1014-页面离开时后端怎么办v070-起v081-重做判定)。想恢复旧行为设 `AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1`，想永不退出设 `AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE=1`。

### 10.8 本地访问令牌（v0.3.0 起）

引擎具备操控键鼠、截屏的能力，而浏览器里任何网页都能向 `127.0.0.1` 发请求。为防止恶意网页把引擎当"RPA 后门"：

- **令牌持久化**（v0.8.1 起）：首次启动生成随机令牌并保存到 `%APPDATA%\AutoGameTool\engine.token`，之后每次启动复用同一串——这样「程序已在运行时再启动一次」打开的页面也能连上（旧版每次新生成，那个页面永远 401）
- 自动打开的浏览器地址形如 `http://127.0.0.1:8765/?token=xxx`，前端存 sessionStorage 后自动从地址栏抹除
- 所有 API（`/run`、`/input/*`、`/screen/*`、`/vision/*`、`/goodbye` 等）必须携带 `Authorization: Bearer <token>` 或 `?token=`；WebSocket 同样校验；无令牌一律 401
- 校验 `Host` 头白名单（仅 127.0.0.1/localhost），防 DNS rebinding
- 打包版与前端同源，**默认关闭 CORS**；仅 `AUTOGAMETOOL_DEV=1` 时放行 vite 调试端口并跳过令牌（开发用）

相关环境变量：

| 变量 | 作用 |
|---|---|
| `AUTOGAMETOOL_TOKEN` | 固定令牌（自动化测试用，如 `smoke_test.ps1`），优先级高于落盘的令牌 |
| `AUTOGAMETOOL_DEV` | `=1` 开启开发模式：放行 `localhost:1420` CORS 且跳过令牌校验 |
| `AUTOGAMETOOL_NO_BROWSER` | `=1` 不自动打开浏览器 |
| `AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE` | `=1` 页面离开时**永不退出**后端（无人值守挂机） |
| `AUTOGAMETOOL_EXIT_ON_PAGE_LOSS` | `=1` 恢复 v0.7.x 旧行为：静默掉线也在 6 秒后退出 |

> 直接手动访问 `http://127.0.0.1:8765`（不带 token）时页面能打开但 API 全部 401。请使用引擎控制台打印的带 token 地址，或由程序自动打开的页面进入。

### 10.9 多分辨率 / DPI 自适应（v0.3.0 起）

换显示器、改分辨率或 DPI 缩放变化后，旧脚本的模板和坐标不再对得上。v0.3.0 引入参考基准自动适配：

- **识图**：截取模板时记录捕获画面尺寸（存为 `模板名.meta.json`）。匹配时若当前画面尺寸与参考不同（分辨率变了 / 窗口缩放），引擎先把模板按相同比例缩放（0.3x~3x，横纵比一致才启用）再匹配，得分不理想自动回退原尺寸取高分
- **点击 / 宏坐标**：`.agflow` 保存时写入参考主屏分辨率（`screen`）与绑定窗口 rect（`window.rect`）。运行时：绑定窗口优先按「参考 rect → 当前 rect」换算（同时覆盖窗口移动、缩放与分辨率变化）；未绑定按主屏分辨率比例换算
- 引擎本身 `SetProcessDpiAwareness(2)`（每显示器 DPI 感知），截图与点击始终在同一物理像素坐标系

> 注意：加载他机脚本后再用拾取快捷键（默认 `alt+F3`）新拾取的坐标按当前分辨率记录，与文件原有参考系不同——跨机复用时建议重新拾取全部坐标并重新保存（保存会把参考系更新为当前环境）。

### 10.10 悬浮框（v0.4.0 起，v0.5.0 增加快捷按钮，v0.7.0 改为图标入口）

挂机时主界面通常被游戏挡住，所以循环到了第几轮、当前卡在哪一步，需要一个**盖在游戏上面**的小窗来显示，并且最好不用切回浏览器就能操作。

**为什么由引擎画、而不是网页画**：浏览器无法创建真正置顶于其它程序（尤其独占/无边框游戏）之上的窗口，任何网页内的"悬浮层"都只在自己页面内生效。因此悬浮框由 Python 侧用 `tkinter` 在**独立线程**里创建原生窗口。

**界面**

```
● AutoGameTool                    ↗▣  ✕
第 2/3 轮
当前：找图 任务
[▶ 启动] [⏸ 暂停] [● 录制]    循环 [－][[3]][＋]
                                        ↑ 可直接输入
```

| 按钮 | 行为 |
|---|---|
| **▶ 启动 / ■ 停止** | 与全局快捷键、界面「运行」按钮**完全同一条链路**（见 [10.6](#106-快捷键执行链路)），始终使用画布上最新的流程 |
| **● 录制 / ■ 停录** | 开始/停止键鼠录制；停止后录到的事件照常推给前端并生成一个「键鼠录制」节点 |
| **循环 － / [n] / ＋** | 调整或**直接输入**循环轮数（1–99999），同步到前端并广播给所有页面；**运行中禁用**，改动在下一轮运行生效 |
| **↗▣（右上角图标）** | 把 WebUI 所在**浏览器**窗口恢复并切到前台（标题匹配 + 浏览器识别，最小化状态也能唤回）。**只认真正的浏览器窗口**：同名文件夹的资源管理器、承载后端的终端/控制台窗口都不会被误选，找不到就只记一条提示日志、不乱切窗口 |

**循环次数可直接编辑**：中间那个数字是输入框（不只是 ± ）。点它 → 临时解除 `WS_EX_NOACTIVATE` 并激活窗口（否则窗口拿不到键盘焦点、输入框打不了字）→ 输入数字 → `Enter` 提交、`Esc` 放弃、点别处也会提交；提交后立刻恢复"不抢焦点"。非法输入与越界值会被夹回合法范围（1–99999，输入框宽度按 5 位数字留足）并回显真实值。

右上角的「回到界面」是**矢量图标**而不是文字按钮（更省横向空间，也不再和底部的启停按钮抢注意力）：一个左上角开口的方框 + 指向左上角的箭头 + 右下角实心方块。用 Tk `Canvas` 画线绘制，不引入图片资源、任意 DPI 都清晰；鼠标移上去会变成主题青色作为可点击反馈。

另外：无边框 + 置顶、按住可拖动、点 `✕` 收起并同步回前端开关、开关持久化到 `config.json`。

**两个刻意的设计（都与"窗口最小化"有关）**

1. **点击悬浮框不抢焦点**：窗口带 `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`，点按钮不会夺走前台焦点，也不会出现在 Alt-Tab 里。
2. **置顶只在真的丢失时才写 Z 序**：旧版每 2 秒无条件 `SetWindowPos(HWND_TOPMOST)`，会在别的窗口播放最小化动画时搅动 Z 序，导致**偶发最小化失败**；现在先读扩展样式判断，正常情况是纯读操作。

**线程模型**：引擎主线程跑 uvicorn 事件循环，Tk 必须在自己的线程里 `mainloop`。两者不共享任何 Tk 对象——执行器只往队列投递状态，Tk 线程每 120 ms 消费一次并刷新；按钮回调也只把动作名交回事件循环线程执行。

**可靠性**：`tkinter` 缺失或窗口创建失败时自动降级为「空实现」（`/overlay/state` 的 `available=false`，前端按钮置灰），**绝不影响流程执行**；执行器侧对悬浮框更新也做了兜底捕获。

开关会记录在 `%APPDATA%\AutoGameTool\config.json` 的 `overlay` 字段，下次启动沿用。

### 10.11 窗口最小化与截图（v0.5.0 修正）

`capture_window` 旧版会在窗口最小化时**无条件** `ShowWindow(SW_RESTORE)` 把它弹到前台。挂机时用户常常故意最小化游戏/浏览器，于是每个找图/判断节点都会把它弹回来，表现为"最小化失败"。

现在改为：

- **流程执行（找图 / 判断）**：`restore_minimized=False`，窗口最小化时直接报 `目标窗口已最小化…` 并结束该节点，**不弹窗**
- **用户主动操作（界面「截取」/ 测试匹配）**：显式传 `restore_minimized=True`，照旧把窗口恢复出来，方便取模板

> 提示：多数游戏/浏览器在最小化后会停止渲染，此时截图本来也拿不到有效画面；所以"报错而不弹窗"既保住了你的窗口，也避免了无意义的轮询。

### 10.12 录制模型的拆分与打包

> v0.6.0 引入拆分（录制不再记鼠标轨迹）；v0.6.1 给拆分补了顶栏常驻入口；v0.6.2 补上打包合并（拆分的逆操作）与拆分后的网格排版。

**为什么不再录鼠标轨迹**：早期录制把 `mousemove` 一并记下，一段录制里绝大部分事件是轨迹点。回放时逐点移动光标既慢又脆（受分辨率、帧率、窗口位置影响），而且**没法编辑**——想改一次点击的位置，得在成百上千个轨迹点里找。

v0.6.0 起改为**只记语义事件**：

| 记录 | 不记录 |
|---|---|
| 鼠标按下 / 抬起（含按键与**按下时的坐标**）、滚轮 | `mousemove` 轨迹 |
| 键盘按下 / 抬起（含组合键） | 鼠标移动的中间过程 |

回放时由 **点击节点**把光标直接落到该坐标再按下（`inputctl.mouse_down` → 真实模式 `SetCursorPos` / 模拟模式 `PostMessage`），效果等价而事件数下降一到两个数量级。

**两个入口**（v0.6.1 起）：

| 入口 | 位置 | 作用对象 |
|---|---|---|
| **✂ 拆分录制** | **顶栏设置条常驻**（「⏺ 开始录制」右侧） | 当前选中的录制步骤；流程里只有一个录制步骤时直接生效，无需先选中；有多个且未选中时会提示先选 |
| **✂ 拆分为可编辑步骤** | 选中录制步骤后，右侧属性面板 | 该录制步骤 |

> 为什么要加顶栏入口：v0.6.0 只有属性面板那一个按钮，而它**只在选中「键鼠录制」节点时才出现**——不在工具栏、也不在左侧步骤面板，结果就是"功能明明做了却找不到"。顶栏入口没这个前提：流程里只要有录制步骤，按钮就亮着；一个都没有时置灰并提示先录一段。

拆分把一段录制编译成普通节点：

| 录制事件 | 拆分结果 |
|---|---|
| `mousedown` + 紧随同键 `mouseup` | 一个 **鼠标点击**节点（保留按下时的坐标、按键） |
| 连续按键（如先后按下 `ctrl`/`shift`/`a` 再抬起） | 一个 **键盘按键**节点，键名为 `ctrl+shift+a` |
| 连续的 `scroll` | 一个 **键鼠录制**节点（引擎暂无独立滚轮节点，故保留原样回放） |
| 相邻动作间隔 ≥ 80 ms | 中间插入一个 **延时**节点，保留原有节奏 |
| 孤立 `mouseup`、空输入 | 直接丢弃 |

> 组合键的归属按「本轮第一个抬起」结算：`ctrl` 按住不动、先后配 `a` 再配 `b`，会正确拆成 `ctrl+a` 与 `ctrl+b` 两个节点，而不是误并成 `ctrl+a+b`。

拆分后的节点就是**普通节点**：连线自动重排（原入线接到首节点、原出线接自尾节点），之后可以随便改坐标、换键、插节点、删节点。算法是纯函数（`frontend/src/lib/macroSplit.ts` 的 `compileMacroPieces` / `expandPieces`），不依赖 Vue，用 `.\tools\test_macro_split.ps1` 可脱离浏览器跑断言验证（见 [9.6](#96-录制拆分与打包算法回归测试)）。

#### 拆分后的排版（v0.6.2）

v0.6.0/0.6.1 是把所有新节点**沿一列往下排**（`y += 76`）：十几步就拖出去很远，还会盖住下面的节点，后继节点的连线绕回来穿过整块，看起来就是一团。

现在改成**蛇形网格**：

- 行数由**编辑区可见高度**决定（`(高度-40)/78`，限制在 3~14 行），一列排满再向右折
- 列数凑成**奇数**：偶数列自上而下、奇数列自下而上，于是**块内每一条连线都首尾相接**——相邻两步不是同列上下相邻，就是换列时同一行相邻，**不会出现长对角线**
- 会被方块压到的原有节点**整体下移同一个距离**，既让开位置又保持它们彼此的相对排布
- 拆完自动 `fitView()`，整块直接落在视野里

实测：12 步 → `3 列 × 4 行`（原来是一列 12 行）；40 步 → `7 列 × 6 行`；5 步以内仍是一列。这些几何规则都有断言（见 [9.6](#96-录制拆分与打包算法回归测试)）。

#### 打包合并：拆分的逆操作（v0.6.2）

选中一串**相邻**步骤 → 顶栏 **📦 打包合并**，合并回一个「键鼠录制」步骤。

| 选中的步骤 | 打包成的事件 |
|---|---|
| 鼠标点击 | `mousedown` + `mouseup`（保留坐标与按键；`clicks>1` 按时重复若干下） |
| 键盘按键 | 组合键按顺序按下、**逆序**抬起 |
| 延时 | 时间轴向前推进（不产生事件） |
| 键鼠录制 | 其事件按自身 `speed` 折算成真实时间后**内联**进来（支持多段录制并成一段） |
| 找图 / 判断 / 文本 / 终止 | **无法**表达成键鼠事件 → 整体拒绝并说明原因 |

选择方式：`Shift`+拖拽框选，或按住 `Ctrl` 逐个点击加选（左侧步骤面板底部有提示）。

几条刻意的取舍：

- **只接受"一条连续链"**：选中集合内必须恰好有一个没有入边的头；成环、有分支（判断节点两条出边）、或者隔着没选的节点（选 A、C 而漏掉 B）都会被拒绝并提示
- **不做部分打包**：只要有一个步骤不能打包就整体拒绝，避免悄悄丢掉动作
- **勾了「单次执行」的步骤拒绝打包**：录制步骤表达不了"仅第一轮"，请先取消勾选
- 拆分是**有损**的——点击节点没有"按时长"字段，按下→抬起之间的间隔被丢弃，所以反向打包统一按 60 ms 约定值补齐。**"拆分→打包"能还原步骤序列、坐标、按键与延时长度**；只有"按住多久"这一项是约定值
- `mousemove` 会被丢弃（本来也不再录），所以打包不会把轨迹写回去

> 拆分与打包共用同一套纯函数（`packStepsToMacro` / `orderChain`），往返等价与"非连续选择应被拒绝"都有断言覆盖。

> ⚠️ 拆分与打包都是**就地替换**。v0.7.0 起可以用 **Ctrl+Z 撤销**（顶栏也有 ↶/↷ 按钮），但历史只保留最近 60 步、且拖动/连续输入会合并成一步；跨度较大的改动仍建议先保存一份 `.agflow`。

### 10.13 启停状态为什么不会再分叉（v0.7.0 起）

v0.6.x 及更早的启停链路是这样的：

```
点悬浮框「启动/停止」或按 alt+f1 → 引擎广播 {type:"hotkey"} → 前端按**自己那份** store.running 决定启动还是停止
```

问题在于**方向判断发生在前端**，而前端那份状态是轮询来的、可能慢一拍：

- **悬浮框只在流程起跑和结束时才被更新**（`executor._state()` 的两处调用）。任何绕过这两处的改动——`/run` 里先置位的 `running`、`stop()`/`reconcile()` 的兜底复位——悬浮框都不知道。于是出现"WebUI 显示运行中、悬浮框还显示停止"
- 两边一旦分叉就**再也回不来**：点悬浮框的「停止」，前端按自己那份状态判断成"没在运行 → 该启动"，于是又发一次 `/run`（或被 409 挡掉）。表现就是**反复点停止没反应**
- 按住 `alt` 连按两次 `f1` 时，第二次按下的瞬间 `alt` 还没松开，`HotkeyManager` 的「已触发」锁没复位 → **只触发第一次**

v0.7.0 改成「引擎是唯一事实来源」：

| 措施 | 解决什么 |
|---|---|
| **停止一律在引擎侧直接执行**，不再广播让前端决定方向 | 方向判断不再依赖前端那份可能过期的状态；启动才交给前端（因为要用画布上最新的流程，消息改成语义明确的 `run_request`） |
| `_sync_run_state()` 统一推送，`/run`、`/run/stop`、`/run/state` 都调用它 | 悬浮框与 WebUI 拿到的是同一个值 |
| **1 秒状态看门狗**兜底 | 任何漏掉同步的代码路径都会在 1 秒内被纠正——给悬浮框补上前端早就有的自愈能力 |
| `/run/stop` 等流程**真正收尾**再返回（最多 2 秒） | 前端按钮在"确实已停止"的那一刻翻转，不留"还亮着停止"的窗口 |
| `delay` 节点改为每 250 ms 检查停止标志 | 挂机时单个延时动辄几十秒，旧版整段睡死，点停止要等它走完才生效 |
| 组合键里的**非修饰键**一抬起就解锁 | 按住 `alt` 连按两次 `f1` 能触发两次；长按 `f1`（只有重复 keydown）仍只触发一次 |

> 顺带把「这次动作是谁发起的」写进日志：`悬浮框：停止脚本` / `全局快捷键：启动脚本`。以后再出现"点了没反应"，看一眼日志就能分清是**按键没识别**还是**流程没停**。

### 10.14 页面离开时后端怎么办（v0.7.0 起；v0.8.1 重做判定）

关掉浏览器页面后后端不该残留，但**「页面不见了」不等于「用户关了页面」**——这个区别是 v0.8.1 的核心修复。判定规则：

| 情形 | 行为 |
|---|---|
| 页面**主动告别**（关标签页/跳转离开，前端 `pagehide` 时 `sendBeacon` 打 `/goodbye`） | 5 秒宽限后若没有页面重连 → 停止流程并优雅退出（走 lifespan 清理：关悬浮框、注销钩子） |
| 页面**静默掉线**（浏览器挂起/丢弃后台标签页、崩溃、网络抖动） | **不退出**：后端与悬浮框继续跑，页面回来随时重连 |
| 收到告别但**流程仍在运行** | **不退出**（挂机优先），只记一条日志 |
| 从未有页面连过（`AUTOGAMETOOL_NO_BROWSER=1` 无人值守、冒烟测试） | 永不自动退出 |
| `AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE=1` | 永远不退出（连告别也不退） |
| `AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1` | 恢复 v0.7.x 旧行为：静默掉线也在 6 秒后退出 |

为什么必须区分（实测事故）：浏览器会把长时间在后台的标签页**挂起甚至丢弃**（Edge 的睡眠标签页）。挂起时 WebSocket 仍由浏览器网络层代答 ping，连接能撑很久；真正被丢弃时 socket 断开，而**页面只有在用户回到浏览器时才会重新加载并重连**——挂机时用户不在，旧的 6 秒宽限期必然不够，于是每次都会「后端与悬浮框一起消失」。日志里那 9 次 `WebUI 已断开` + `引擎退出：…6 秒内没有重连` 就是这么来的。

对应回归测试 `tools\test_webui_close.py`（见 [9.7](#97-引擎行为回归测试)）：静默掉线、刷新式重连、主动告别、运行中告别、旧行为开关，五种时序都有断言。

### 10.15 撤销 / 重做为什么用「快照 + 防抖」（v0.7.0 起）

直觉做法是「每个会改动画布的函数里手动入栈一次」。这里**没有**那么做，因为画布上会改 `nodes` / `edges` 的地方远不止自己的那几个函数：

- Vue Flow 自己就会改：按 `Delete` 删节点/删连线、拖动节点坐标
- 右侧属性面板有一堆直接 `v-model` 到 `params` 的输入框
- 拆分、打包、加载脚本各改一次

逐个包起来必然漏，而漏掉的那部分表现就是**「撤销时灵时不灵」**——比没有撤销更让人不信任。

所以改成统一的机制：

| 环节 | 做法 |
|---|---|
| 捕获 | 深度监听 `nodes` / `edges`，350 ms 防抖后拍一张快照 |
| 快照内容 | 只留**流程语义字段**（id / type / 坐标取整 / 完整 data；连线的 source·target·sourceHandle）。Vue Flow 会往节点上挂 `dimensions`、`selected`、`dragging`、`handleBounds` 等运行时属性，不剔除的话「点一下选中」都会产生假快照，把真正要撤销的改动挤出历史 |
| 去重 | 新快照与当前位置内容相同则不记录（撤销/重做本身不会被记成一步） |
| 分支 | 撤销后又做新改动 → 丢弃原来的「未来」分支 |
| 应用 | 整份替换节点与连线，并把 `nodeSeq` 计数器对齐到历史里的最大 id（否则撤销后新增节点会撞 id） |
| 上限 | 60 步；加载脚本时清空历史（撤销不跨脚本） |

代价是"粒度"由时间决定而不是由操作决定：连续拖动、连续打字会合并成一步（这通常正是用户期望的）。想精确回退单个字符，输入框内仍用浏览器原生的 `Ctrl+Z`（编辑器不拦截输入框里的快捷键）。

### 10.16 暂停的语义与生效位置（v0.7.1 起）

「暂停」和「停止」是两件事：停止会结束这次运行（下次从流程开头重跑），暂停只是**冻住**，继续后从原地接着跑。

实现上，暂停是一个协作式标志（`Executor.paused`），只在**检查点**生效，检查点只有两处：

| 检查点 | 为什么放这里 |
|---|---|
| **节点边界**（每个节点开始前） | 这里不存在"做到一半"的状态，恢复后从当前节点继续即可，**不会重复执行已完成的动作** |
| **延时的小睡之间**（每 250ms） | 挂机脚本里单个延时动辄几十秒；暂停期间余下的延时**不再流逝**，恢复后把剩余时间睡完 |

刻意**不**放进找图 / 判断的轮询与宏回放里：

- 找图/判断的超时是按 `time.time()` 算的。在里面停住会把暂停时长也算进超时，恢复后立刻误判超时——那是个很难查的怪 bug
- 宏回放的时序基准是一次性算好的 `base`，中途停住再恢复会试图"追帧"，把剩余事件一次性倾倒出去

代价是：暂停在**当前节点结束后**才真正停下（找图/判断最长等它的超时窗口，宏回放等这一段放完）。这两类节点都是有界的，不像延时那样可以任意长，所以这个取舍是划算的。

状态一致性沿用 v0.7.0 的单一事实来源：`/run/state`、`/overlay/state` 都带 `paused`，`_sync_run_state()` 与 1 秒看门狗保证 WebUI 和悬浮框同时看到「已暂停」。边界情况也一并处理了：空闲时 `pause()` 不生效（不会出现"已暂停但空闲"的矛盾状态）、`stop()` 会清掉暂停（否则暂停等待循环会一直挂着）、恢复后 `reconcile()` 不会误清正在跑的暂停。

### 10.17 自定义背景：选图 → 按屏幕比例截取 → 透明度（v0.7.1 起）

入口在编辑器顶栏 **⚙ 设定**。三步：

1. **选择本地图片**（png / jpg / webp…）
2. **截取**：取景框的比例 = **当前窗口比例**，用 cover 方式铺满，可拖动平移、滑块缩放（1×~3×），带三分线参考
3. **透明度**：5%~100%，实时生效

几个刻意的决定：

- **图片只存本机浏览器**（`localStorage`），不上传引擎、不写进 `.agflow`——背景是"这台电脑这个窗口"的显示偏好，跟脚本内容无关；换台机器打开同一个脚本不该跟着变样
- **导出分辨率有上限**（默认 1920×1080 以内）：base64 存在 localStorage 里，不留上限很容易撞 5MB 配额。真要存不下会**自动逐档降质**（0.88 → 0.75 → 0.6 → 0.45）并在设置面板里说明
- **几何算法抽成纯函数** `frontend/src/lib/bgCrop.ts`：界面里显示的取景结果与导出到 canvas 的裁剪区域**共用同一个 `drawRect()`**。如果写成两份（一份给 CSS、一份给 `drawImage`），迟早会漂移，而且差几个像素肉眼看不出来。用 `.\tools\test_bg_crop.ps1` 断言（23 条）把"必须完全覆盖取景框""平移必须被夹住""等比缩放不变性""异常输入不产生 NaN"钉死
- **可读性优先**：背景铺在最底层，画布与面板各自再压一层半透明暗色（画布压得更暗），所以无论透明度调到多高，节点、连线、文字始终清晰

> 没有设置背景时，界面的外观与之前完全一致（相关样式只在 `has-bg` 类下生效）。

### 10.18 外观：浅色 / 深色 / 跟随系统（v0.8.0 起）

入口在 **⚙ 设定 → 外观**，三个选项：**跟随系统（默认）** / 浅色 / 深色。

- **默认跟随系统**，跟的是 Windows 的浅色/深色设置（`prefers-color-scheme`），系统切换时界面**立刻**跟着变（监听 `matchMedia` 的 `change`，不是只在启动时读一次）
- **取不到系统偏好时按深色处理**：深色是 AutoGameTool 一直以来的外观，宁可维持原样也不要突然刷白
- **显式选择优先于系统**，并且**只存本机浏览器**（`localStorage` 的 `agt.appearance`，默认值不写盘）——与自定义背景同一个理由：这是"这台电脑这个浏览器"的显示偏好，跟脚本内容无关，不该随 `.agflow` 换机变样
- 实现上分两层：**Naive UI 的浅色/深色主题**（组件库自带，见 `App.vue` 的 `n-config-provider`）+ **自己的 CSS token**（`style.css` 里 `:root` 是深色，`:root[data-theme='light']` 只覆盖变量）。组件样式一律只用这些变量，避免出现"浅色下某块还是黑的"这种半吊子主题
- 判定逻辑抽成纯函数 `frontend/src/lib/appearance.ts`，用 `.\tools\test_appearance.ps1` 断言（28 条）；界面层用无头浏览器跑 `.\tools\test_ui_appearance.py`（28 项）
- 同一处还把 Naive 的 `locale` 设成中文：否则**内置文案是英文**的（新建确认框的按钮就是 `Confirm` / `Cancel`），这正是 v0.8.0 修掉的一个观感问题

### 10.19 为什么只允许一个 WebUI 窗口（v0.8.0 起）

后端本来就只有一份（单实例互斥量），但**页面**可以开很多个：再点一次桌面快捷方式、或者手动粘贴地址，都会多出一个连上同一引擎的标签页。两个页面同时存在会带来一堆含糊：两边都显示运行状态、各自把流程同步给引擎（互相覆盖）、日志与悬浮框事件重复消费。所以 v0.8.0 起：

- 引擎侧：`/ws` 在**已有页面连接**时先发一条 `{"type":"busy"}`，然后以 **4409** 关闭新连接（`ws_manager.connections` 是唯一判据）
- 前端侧：收到 4409 就显示「已在另一个窗口打开」的提示，并**每 1.5 秒后台重试**一次
- **刷新页面（F5）必须永远能用**：刷新时旧连接会先断开，新页面通常第一次重试就成功；即使抢在旧连接清理之前连上被拒，也会在 1~2 秒内自动接管。这是刻意用"重试"而不是"直接抢断旧页面"换来的——否则刷新会把自己锁在外面
- 被拒绝的页面**不影响正在工作的那个**：`test_single_page.py` 里专门断言了这一点（拒绝之后原连接仍活着、`/run/state` 仍然可用）

---

## 11. 常见问题与排错

| 现象 | 原因 / 解决 |
|---|---|
| 双击 exe 提示"程序已在运行" | 已有实例在跑。检查任务管理器结束残留 `AutoGameTool.exe` |
| 手动打开 8765 页面后功能全部 401 | v0.3.0 起 API 需要令牌。用引擎控制台打印的带 `?token=` 地址进入（见 [10.8](#108-本地访问令牌v030-起)） |
| 「悬浮框」按钮置灰 | 当前运行环境缺少 `tkinter`。源码运行请安装带 Tcl/Tk 的 Python；官方发行版已内置 |
| 悬浮框没有盖在游戏上 | 独占全屏（DirectX exclusive）下任何窗口都无法置顶，请把游戏改成「无边界窗口 / 窗口化」 |
| 最小化浏览器偶尔失败/被弹回 | v0.5.0 已修正两处：截图不再无条件恢复最小化窗口（见 [10.11](#1011-窗口最小化与截图v050-修正)），悬浮框也不再每 2 秒重写 Z 序；v0.6.0 又移除了悬浮框的周期性 topmost 重写并改用不激活恢复。若仍复发，请把日志面板里 `…目标窗口原本处于最小化，已恢复显示…` 那条发出来定位 |
| 录制的宏里没有鼠标移动轨迹了 | v0.6.0 起的**有意变更**：轨迹点既无法编辑又拖慢回放，改为只记点击坐标（回放时直接落到该点）。旧脚本的轨迹事件仍可正常回放，见 [10.12](#1012-录制模型的拆分与打包) |
| 「📦 打包合并」按钮是灰的 | 需要先选中 **≥2 个相邻步骤**：`Shift`+拖拽框选，或按住 `Ctrl` 逐个点击加选（左侧步骤面板底部有提示）。选中后按钮上会显示数量 |
| 打包合并提示"只能打包连成一串的相邻步骤" | 选中的步骤必须首尾相接。隔着没选的步骤、成环、或有分支（判断节点两条出边）都会被拒绝 |
| 打包合并提示"没法打包进录制" | 找图 / 判断 / 输入文本 / 终止条件不是键鼠动作，录制步骤表达不了；或某些步骤勾了「单次执行」，请先取消 |
| **看不到「拆分录制」入口** | 先看顶栏右上角的版本号：**没有版本号就是旧页面**，按 `Ctrl+F5` 强制刷新（引擎重启不会让已打开的页面换掉旧 JS）。v0.6.1 起顶栏有常驻的 **✂ 拆分录制** 按钮（无录制步骤时置灰）；v0.6.0 只有属性面板里那个，且必须先选中录制节点才出现 |
| 悬浮框点右上角图标没反应 | 只认**浏览器**窗口，且标题需含 `AutoGameTool`：确认标签页还开着；若该标签页没被激活（标题不含它），先手动切一下。日志面板会给出提示。鼠标移上去图标会变成青色，说明可点击 |
| 点右上角图标把后端控制台弹出来了 | v0.7.2 已修：旧实现把「像不像浏览器」只当排序键、没有过滤，一个浏览器都没匹配上时会退而返回任意同名窗口（承载后端的终端标题里就含 `AutoGameTool`）。现在只接受真正的浏览器窗口，并且显式排除控制台/终端/解释器进程与窗口类 |
| 关掉页面后程序也退出了 | v0.8.1 起的规则：**你主动关页面**（5 秒宽限内没重连）才会退；页面只是**静默掉线**（被系统挂起/丢弃、浏览器崩了）**不会退**。想永不退出设 `AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE=1`；想恢复旧行为设 `AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1`。见 [10.14](#1014-页面离开时后端怎么办v070-起v081-重做判定) |
| 挂机时后端和悬浮框突然消失 | 旧版本（≤0.8.0）的已知问题：浏览器把后台标签页挂起/丢弃 → socket 断开 → 6 秒宽限内页面回不来 → 引擎按「关页面」处理而退出。**v0.8.1 已修**（静默掉线不退后端），日志里会写「后端继续运行，等待页面重连」 |
| 悬浮框点「启动」没反应 | v0.8.1 前：启动被委托给页面，页面被系统挂起时连点也没用。现在会等 1.2 秒后**用引擎侧缓存的流程兜底启动**，日志里会写「编辑器页面没有响应启动请求…」 |
| 再次启动程序后，新页面显示已断开/一直重连 | v0.8.1 前的令牌问题（每次启动新令牌，旧引擎不认）。现在令牌持久化在 `%APPDATA%\AutoGameTool\engine.token`，任何一次启动打开的页面都能连上 |
| 悬浮框和界面的启停状态对不上 | v0.7.0 已修（引擎为唯一事实来源 + 1 秒看门狗，见 [10.13](#1013-启停状态为什么不会再分叉v070-起)）。旧版请升级 |
| 反复点「停止」没反应 | 同上。旧版还多一个成因：`delay` 节点整段睡死不检查停止标志，长延时期间点了要等它走完；v0.7.0 改为每 250ms 检查一次 |
| 循环结束后右上角仍显示「停止」 | v0.4.0 起前端每秒自愈；v0.7.0 起引擎侧看门狗让悬浮框也一起自愈。旧版可先点一次「停止」或重启引擎 |
| 快捷键没反应 | v0.7.0 起每次触发都会记日志：有 `全局快捷键：启动脚本/停止脚本` 说明按键已识别、问题在后续链路；**完全没有**则检查是否多开、或有残留实例。v0.8.0 起还要看那条快捷键**是否被停用**（顶栏「⌨ 快捷键」里右侧开关），以及是否和别的功能撞了同一组键 |
| 想改快捷键 / 某个快捷键不想用 | 顶栏 **⌨ 快捷键** → 点键位显示区 → 按下组合键 → 保存。三条（启动停止 / 键鼠录制 / 坐标拾取）都能改、都能单独停用；停用只影响按键，界面按钮照常可用。见 [7.1](#71-快捷键) |
| 坐标拾取原来按 F8，现在换成什么了 | v0.8.0 起默认 `alt+F3`（三条全局快捷键统一按 alt+F1/F2/F3 排列）。想用回 F8：在「⌨ 快捷键」里给「拾取屏幕坐标」录成 `f8` |
| 界面太亮 / 想要回原来的深色 | v0.8.0 起默认「跟随系统」。想要固定深色：**⚙ 设定 → 外观 → 深色**；浅色同理。偏好只存本机浏览器，见 [10.18](#1018-外观浅色--深色--跟随系统v080-起) |
| 新开的标签页显示「已在另一个窗口打开」 | 有意行为（v0.8.0 起只允许一个 WebUI，见 [10.19](#1019-为什么只允许一个-webui窗口v080-起)）。用原来那个窗口；若已关掉，本页会在 1~2 秒内自动接管，刷新页面也不受影响 |
| 「关于」点了会不会把界面关掉 | 不会。它用**新标签页**打开 GitHub 发布页，当前页面的连接不受影响（当前页跳走的话，引擎会在宽限期后自动退出，所以刻意这么做） |
| 按住 alt 连按 f1 只有第一次生效 | v0.7.0 已修（组合键里非修饰键一抬起就解锁，见 [10.13](#1013-启停状态为什么不会再分叉v070-起)） |
| Ctrl+Z 撤销没反应 | 历史只在画布上生效，且光标在输入框里时不拦截（那里让浏览器做文本撤销）；另外 v0.7.0 之前加载的旧工程要把历史从加载那一刻重新开始，加载后第一次改动才有可撤销点 |
| 找不到「首页 / 新建脚本 / 编辑脚本」入口 | v0.7.2 起**首页已彻底移除**，界面只有一个：编辑器。`/` 与任何未匹配路径都进编辑器；新建脚本在右上角「保存」左边 |
| 暂停点了没马上停 | 暂停在**检查点**生效（节点边界 / 延时的 250ms 小睡）。如果当前正在找图或回放宏，会等这个节点结束才停——这两类节点都有超时/时长上界。见 [10.16](#1016-暂停的语义与生效位置v071-起) |
| 暂停后进度条不动，是卡死了吗 | 不是。悬浮框会显示 `⏸ 已暂停 · 第 n/m 轮`，日志也会记「已暂停」。点「▶ 继续」从原地接着跑 |
| **后端突然不见了，怎么查原因** | 打开 `%APPDATA%\AutoGameTool\engine.log`（v0.7.3 起）。它会记下启动信息、全部运行日志、WebUI 连接/断开、以及**退出原因**。常见几行：`WebUI 已断开（剩余 0 个页面）` + `引擎退出：WebUI 页面全部断开且 6 秒内没有重连` = 页面断连触发了自动退出（想禁掉就设 `AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE=1`）；`清理完成，引擎退出` = 正常优雅退出；日志末尾停在某一步且没有退出记录 = 进程被外部终止（例如被结束进程）。共 4 个文件：`engine.log` 与 `engine.log.1~.3`（各 2MB 轮转） |
| 背景图设置了但换台电脑就没了 | 有意为之：背景只存本机浏览器 `localStorage`，不上传引擎、不写进 `.agflow`。见 [10.17](#1017-自定义背景选图--按屏幕比例截取--透明度v071-起) |
| 设了背景后文字看不清 | 把「设定 → 透明度」调低；画布与面板本身有一层暗色底，正常不会影响可读性 |
| 背景图保存失败/重启后丢失 | 图片太大撞了 `localStorage` 约 5MB 的配额。设置面板会提示；换一张更小的图，或调低分辨率再选 |
| 键盘突然不能用了 | **旧版本的多监听器缺陷**。请用最新版并重启电脑清掉残留钩子；新版已用事件总线修复 |
| 找图超时 | 提高阈值容差（降低阈值）、缩小识别区域、确认分辨率未变 |
| 中文模板识别失败 | 旧版缺陷，新版已修复 |
| 模拟输入无效 | 见 [12. 已知限制](#12-已知限制)；先用 `/input/probe` 诊断 |
| 窗口列表里没有目标窗口 | 只列出"任务栏窗口"；若游戏是子窗口/无标题窗口则不会出现 |
| 截图黑屏 | 独占全屏游戏 GDI 无法截取；请改「无边框窗口」模式 |
| exe 启动慢 / 弹 could not create temporary directory | v0.8.2 起已改为文件夹形态（`--onedir`），不再解压、也不再依赖 `%TEMP%`。若你还在用旧版单文件：把它放到一个可写目录，或直接换新安装包 |
| 杀软误报 | PyInstaller / NSIS 常见现象；正式分发建议**代码签名** |
| 安装包被 SmartScreen 拦截 | 安装包未签名，出现「Windows 已保护你的电脑」时点「更多信息 → 仍要运行」 |
| 构建安装包时找不到 makensis | `build_installer.ps1` 会自动下载 NSIS 3.10 到 `tools\nsis`；离线环境可手动安装 NSIS，再用环境变量 `AUTOGAMETOOL_MAKENSIS` 指向 `makensis.exe` |
| 改了 `.ps1` / `.nsi` 后脚本报「字符串缺少终止符」 | 文件被存成了「UTF-8 无 BOM」，执行 `.\tools\to-utf8-bom.ps1` 修复（见 [9.3](#93-源码编码约定重要)） |
| 安装后快捷方式图标空白 | 图标缓存问题，执行 `ie4uinit.exe -show` 或重建快捷方式 |

**诊断命令**

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health          # 引擎存活（免令牌）
# 以下接口 v0.3.0 起需令牌（AUTOGAMETOOL_TOKEN 固定令牌时测试更方便）：
Invoke-RestMethod "http://127.0.0.1:8765/debug/kb?token=<令牌>"      # 键盘钩子状态
Invoke-RestMethod "http://127.0.0.1:8765/windows/list?token=<令牌>"  # 窗口列表
```

---

## 12. 已知限制

1. **真后台挂机**
   - `PostMessage` 模拟输入**只对"用 Windows 消息循环收输入"的程序有效**。
   - 使用 **DirectInput / Raw Input** 的游戏（含浏览器内核网页游戏）通常会**无视**合成消息。
   - 多数游戏在**被遮挡 / 最小化时停止渲染**，导致图像识别无新画面。
   - 如需"游戏窗口被遮挡甚至最小化仍挂机"，可选方案：驱动级虚拟输入（Interception）、隐藏桌面、虚拟机隔离、云机，或（网页游戏）浏览器自动化。**详见项目讨论记录。**
2. **独占全屏**游戏无法用 GDI/PrintWindow 截图。
3. **OCR 尚未接入**（依赖已装好，节点待实现）。
4. **反作弊**：本项目不涉及也不应涉及任何绕过反作弊的手段。
5. **撤销/重做的粒度由时间决定**：连续拖动、连续输入会被合并成一步（见 [10.15](#1015-撤销--重做为什么用快照--防抖v070-起)）；历史上限 60 步，且**不跨脚本**（加载工程后从该状态重新开始）。想逐字符回退请在输入框内用浏览器原生 `Ctrl+Z`。
6. **停止是协作式的**：引擎置停止标志，节点在检查点退出。目前所有节点都会检查（延时 250ms、找图/判断在轮询里、宏回放在每个事件之间），但一次已进入的阻塞调用（如 `PostMessage` 发送）仍需等它返回。
7. **暂停只在检查点生效**：节点边界与延时片段内立即生效；找图/判断会等它的超时窗口结束、宏回放会等这一段放完（见 [10.16](#1016-暂停的语义与生效位置v071-起)）。这样取舍是为了不让暂停时长被算进超时、也不让宏回放"追帧"。
8. **背景图存在本机浏览器**：换浏览器或清缓存会丢；`localStorage` 约 5MB 配额，导出时已限制在 1920×1080 以内并在装不下时自动降质（见 [10.17](#1017-自定义背景选图--按屏幕比例截取--透明度v071-起)）。

---

## 13. 路线图

- [ ] 后台输入方案落地（驱动级 / 隐藏桌面 / 浏览器自动化，按游戏形态选型）
- [ ] DXGI 桌面复制截图（支持被遮挡窗口）
- [ ] OCR 文本识别节点
- [ ] 像素颜色判断节点（扩充判断条件）
- [ ] 子流程 / 复用组件
- [ ] 撤销历史的可视化（当前只显示可用/不可用，看不到具体是哪一步）
- [ ] 工程资源依赖校验与一键修复
- [ ] 区域识别（限定搜索区域，降低 OpenCV 匹配耗时）
- [ ] 社区项目导入导出（`.agflow` 打包与依赖声明）
- [ ] 代码签名与自动更新

---

## 14. 更新日志

### v0.9.0 —— 2026-10-02

**从浏览器 WebUI 迁移为 Tauri 2 桌面版（Python 引擎作为 sidecar）**。界面、脚本格式与用户数据目录全部保持不变，老脚本 `\.agflow` 与找图模板零改动可用。

- **桌面壳（Tauri 2）**：原生窗口显示同一个编辑器界面；壳负责「拉起引擎 → 等它就绪 → 开窗」，关闭窗口时结束引擎
  - 引擎仍是本地 `127.0.0.1:8765` 的 HTTP/WS 服务，前端由引擎同源提供（因此不需要处理 CORS，也不需要在页面里注入令牌）
  - 开发模式窗口开在 vite（1420）上，改前端即时热更新；发布模式窗口开在引擎入口 URL（带持久令牌）
  - 单实例：第二次启动把已有窗口提到前台，而不是再开一个
  - 壳自带诊断日志 `%APPDATA%\AutoGameTool\shell.log`（可用 `AUTOGAMETOOL_SHELL_LOG` 指定路径）
- **引擎新增桌面模式** `AUTOGAMETOOL_DESKTOP=1`：不自动开浏览器，且**永不因为「页面没了」退出**（关窗、刷新、WebView 崩溃都由壳收尾）
- **引擎新增** `POST /open_external`（令牌保护，只放行 http/https）：顶栏「关于 → GitHub 发布页」交给系统默认浏览器打开 —— 桌面壳里的 `window.open` 会开出一个没有地址栏、没有前进后退的子窗口
- **打包**：新增 `build_desktop.ps1`（前端 → 引擎 onedir → `tauri build` → NSIS，安装包免管理员）；引擎作为 Tauri `resources` 随包分发，**仍用 onedir（不回到 onefile）**，避免重新引入 `%TEMP%` 解压那类启动失败
- **清理**：移除 WebUI 时期的 17 个回归测试脚本（合计约 300 条断言）与临时/构建产物约 1.38 GB
  - 取舍说明：这些脚本大量围绕「浏览器页面/多窗口/关闭页面即退出」的行为编写，桌面版语义已不同；引擎侧可复用的部分后续按新架构重建
- 环境要求（本机实测通过）：Rust stable + MSVC 工具链、Node/pnpm、WebView2 运行时、Python 3.13 venv + PyInstaller、NSIS（Tauri 自带）

### v0.8.2 —— 2026-10-01

修「装了却起不来、想升级又装不上」这条真实故障链：**程序不再依赖系统临时目录**（打包形态从单文件改为文件夹），**安装器遇到被占用的主程序会给出可照做的提示**。

#### 🐛 修复

- **双击后弹 `could not create temporary directory`，程序起不来**
  - 根因：单文件版（`--onefile`）每次启动都要在 `%TEMP%` 下解压出 `_MEIxxxx`。一旦启动进程的 `%TEMP%` 不可用（被清理掉、或环境异常，例如从 SmartScreen 点「仍要运行」拉起时），Windows 的 `GetTempPath` 会**退回「当前目录」**——那时往往是 `C:\Windows\System32`——解压失败，于是弹这个框，进程还挂在错误框上不放
  - 修复：打包改为 **文件夹形态（`--onedir`）**，启动不再解压，整条链路消失；顺带启动更快、不再在 `%TEMP%` 里留 `_MEI` 残留（本机实测曾累积 27 个、4.66 GB）
  - 回归测试：`tools\test_broken_temp.ps1` —— 故意把 `TEMP`/`TMP` 指向一个**不存在**的目录，要求程序照样起来（旧单文件构建必然失败，新构建全绿）
- **升级安装报「无法打开要写入的文件: …\AutoGameTool.exe」**
  - 根因：AutoGameTool 还在运行（尤其是上面那种**卡在错误框上的进程**）时主程序文件被占用，NSIS 覆盖不了；而它默认只给「中止/重试/忽略」——点「忽略」会装出一个坏版本
  - 修复：安装器改成 `AllowSkipFiles off` + 自己的**重试循环**：先杀进程，仍失败就明确提示「请先退出 AutoGameTool（或重启电脑）再点重试」，不再让用户面对系统原始报错

#### 📝 文档

- 发行形态相关说明全部更新为「文件夹形态（exe + `_internal`）」，安装包体积按实测重写
- FAQ 新增：双击报 could not create temporary directory、升级安装报无法打开要写入的文件、SmartScreen「发布者未知」怎么处理
- 回归测试新增 `tools\test_broken_temp.ps1`（7 条断言）

### v0.8.1 —— 2026-10-01

三个「挂机被中断」的真问题一起修掉：**页面掉线不再杀掉后端**、**悬浮框/快捷键的「启动」不再依赖页面**、**再次启动不再是废页面**。

#### 🐛 修复

- **页面掉线导致后端自杀（挂机被中断、悬浮框消失）**
  - 现象（日志实证，共 9 次）：`WebUI 已断开（剩余 0 个页面）` → 6 秒后 `引擎退出：WebUI 页面全部断开且 6 秒内没有重连`，悬浮框随进程一起消失
  - 根因：旧规则把「页面不见了」等同于「用户关了页面」。但浏览器把**后台标签页挂起/丢弃**（Edge 的睡眠标签页）时 socket 也会断，而页面要等你回到浏览器才会重连——挂机时你不在，6 秒必然不够
  - 修复：**区分「页面主动告别」与「页面不见了」**
    - 静默掉线（挂起/丢弃/崩溃）→ **后端继续运行**，悬浮框保留，页面回来还能连上（`AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1` 可恢复旧行为）
    - 用户真的关页面 → 前端在 `pagehide` 用 `sendBeacon` 发 `POST /goodbye` → 5 秒宽限后优雅退出（「关页面即关后端」这个功能保留）
    - **流程运行中一律不退**：哪怕收到告别，只要流程还在跑就保住后端与悬浮框
- **悬浮框/快捷键点「启动」没反应（页面被挂起时连点十几次都无效）**
  - 根因：启动被**无条件委托给页面**（要取画布上最新流程）。页面被系统挂起时它收得到 socket、却执行不了 JS，引擎那边「以为有页面连着」，于是启动请求石沉大海
  - 修复：广播 `run_request` 后**最多等 1.2 秒**，流程仍未起来就用**引擎侧缓存的流程**兜底启动（缓存由前端每秒 `/flow/load` 同步，永远最新）；日志会写明「编辑器页面没有响应启动请求…已改用引擎侧缓存的流程启动」
- **程序已在运行时再启动一次，新开的页面永远连不上**
  - 根因：访问令牌以前**每次启动都新生成**，第二次启动的进程用它自己那份新令牌打开页面，而真正在跑的引擎用的是旧令牌 → 页面只会反复 `WebSocket 令牌校验失败`
  - 修复：令牌**持久化**到 `%APPDATA%\AutoGameTool\engine.token`（`AUTOGAMETOOL_TOKEN` 环境变量仍优先），之后任何一次启动打开的页面都能连上

#### 📝 文档

- FAQ 新增：关页面还会不会被后端一起关、页面被挂起怎么办、启动按钮没反应、重复启动后页面连不上
- 环境变量补充 `AUTOGAMETOOL_EXIT_ON_PAGE_LOSS`（恢复旧行为）与 `AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE`（永不退出）
- 回归测试总量：拆分/打包 52 + 背景几何 23 + 外观判定 28 + 引擎状态 89 + 启停/暂停 32 + 页面离开策略 17 + 单 WebUI 19 + 悬浮框编辑 19 + 运行日志 16 = **295 条断言**

### v0.8.0 —— 2026-09-27

七项界面与快捷键改动：外观支持浅色/深色/跟随系统、顶栏与设置栏按钮重新排布、**三条全局快捷键全部可改键且可单独停用**、循环轮数支持五位数、版本号位置改成「关于」、确认框文案中文化、并只允许一个 WebUI 窗口。

#### ✨ 新增

- **外观：浅色 / 深色 / 跟随系统**（**⚙ 设定 → 外观**，默认跟随系统）
  - 跟随系统时监听 `prefers-color-scheme`，Windows 切主题界面**立刻**跟着变；取不到系统偏好时保持深色，不突然刷白
  - 显式选择优先于系统，并且只存本机浏览器（`localStorage`），换浏览器/清缓存会回到默认
  - 实现在两层：Naive UI 的浅/深主题 + 自己的 CSS token（`:root` 深色、`:root[data-theme='light']` 覆盖变量），组件样式一律只用变量，避免"浅色下某块还是黑的"
  - 判定逻辑是纯函数 `lib/appearance.ts`（28 条断言），界面层另有无头浏览器回归（33 项）。详见 [10.18](#1018-外观浅色--深色--跟随系统v080-起)
- **三条全局快捷键都能改键、都能单独停用**（顶栏 **⌨ 快捷键**）
  - 默认依次为 `alt+F1` 启动/停止、`alt+F2` 键鼠录制、`alt+F3` 坐标拾取（**注意：坐标拾取从 `F8` 改为 `alt+F3`**，想用回 F8 在面板里录一次即可）
  - 每条都有启用开关；同一组按键不能给两个功能用，**冲突与「启用却没键」会被引擎直接拒绝并说明原因**
  - 改键写在 `config.json` 的 `hotkeys` 里；旧版本只存过一条 `hotkey`，升级时**自动迁移**到新表
  - 实现上把散在三处的按键匹配（启停 / 录制 / 拾取各自一份）合并成一个注册表 `engine/hotkey.py`：这是"为什么只有启停能改键"的根因。见 [7.1](#71-快捷键)
- **「关于」**：顶栏原来的版本号徽标换成 `关于 v0.8.0`，点一下在**新标签页**打开 GitHub 发布页（刻意用新标签页：当前页跳走会让引擎在宽限期后自动退出）

#### 🔧 变更

- **顶栏与设置栏的按钮对调**：**⌨ 快捷键** 与 **🪟 悬浮框** 移到最上方顶栏（和「设定 / 新建 / 保存 / 加载 / 运行」一起），**↶ 撤销 / ↷ 重做**下移到设置栏（原来快捷键/悬浮框所在的位置）
- **循环轮数支持五位数**：编辑器的输入框加宽到能完整显示 5 位数字，上限从 9999 提到 **99999**（悬浮框里的那个数字同样加宽到 5 位）
- **只允许一个 WebUI 窗口**：已有编辑器窗口时，第二个连接被引擎以 **4409** 拒绝并给出提示，**不影响正在工作的那个窗口**；被拒的页面会每 1.5 秒后台重试，所以**刷新页面（F5）仍然正常**（原窗口关掉后新页面自动接管）。详见 [10.19](#1019-为什么只允许一个-webui窗口v080-起)

#### 🐛 修复

- **新建脚本的确认框按钮是英文 `Confirm` / `Cancel`**：`n-config-provider` 没有设置 `locale`，Naive UI 的内置文案全都走英文。现在注入 `zhCN`（并把该确认框显式写成「确定 / 取消」），顺带修掉其它内置文案的语种问题
- **录制结果里会带上录制快捷键本身**：快捷键改由统一注册表匹配后，按 `alt+F2` 开始/停止的那几下按键会被录进宏里。收尾清理改为「**凑齐整组快捷键才剔**」——既去掉残留，又不会误删录制中段的合法 `alt` 组合（比如"按住 alt + 点击"）
- **悬浮框编辑失败时的半途状态**：进入编辑要先清掉 `WS_EX_NOACTIVATE` 再激活窗口，中间任何一步抛异常都会被原来的 `except: pass` 吞掉，结果是窗口停在"可被点成前台"、而编辑态又没建立（此后点数字永远没反应）。现在失败会**回滚窗口样式并打印原因**（测试里也据此定位到"合成回车需要真实焦点"这件事）

#### 📝 文档

- 新增 [10.18 外观](#1018-外观浅色--深色--跟随系统v080-起)、[10.19 只允许一个 WebUI](#1019-为什么只允许一个-webui窗口v080-起)、[9.9 外观判定回归测试](#99-外观判定回归测试)、[9.10 界面回归测试（无头浏览器）](#910-界面回归测试无头浏览器)、[9.7](#97-引擎行为回归测试) 补 `test_single_page.py`
- FAQ 新增：改键怎么用、坐标拾取从 F8 换成 alt+F3、想要固定深色、「已在另一个窗口打开」是什么意思、「关于」会不会关掉界面
- 回归测试总量：拆分/打包 52 + 背景几何 23 + 外观判定 28 + 引擎状态 80 + 启停/暂停 32 + 关闭页面 7 + 单 WebUI 19 + 悬浮框编辑 19 + 运行日志 16 = **276 条断言**；另有打包产物冒烟 12 项、打包产物核验 10 项、**界面（无头浏览器）33 项**

### v0.7.3 —— 2026-09-27

后端意外退出后**查不到任何日志** —— 这一版把这件事补上：运行日志落盘 + 打包去掉控制台窗口。

#### ✨ 新增

- **运行日志落盘**：`%APPDATA%\AutoGameTool\engine.log`（UTF-8，2MB 轮转，保留 3 份备份）
  - 记录内容：启动信息（版本、悬浮框可用性）、**推给前端的全部运行日志**（含步骤名与级别）、状态 / 悬浮框 / 轮数事件、WebUI 连接与断开、以及**退出原因**
  - 前端那份日志是内存态，页面一关就没了；现在即使 WebSocket 断开、页面被关掉，运行过程仍可在文件里事后查看
  - 刻意**不**记录键鼠录制的完整事件数组（`recorded`）：体积大，写进去只会把有用信息挤出轮转窗口
  - 刻意**关掉 uvicorn 访问日志**：前端每秒两个轮询请求，开着会以每秒两行冲掉轮转窗口；WS 连接/断开与退出原因改为显式记录
  - `print()` / 第三方库写 stdout、stderr 的内容也会被接管进日志；**子线程（Tk、钩子）的未捕获异常**与 asyncio 未处理异常都会记下来——这类异常默认是静默消失的
  - 🔒 **日志里绝不出现访问令牌**：`token=xxx`、`Authorization: Bearer xxx`，以及引擎启动时登记的本地令牌字面量，全部掩成 `***`（引擎打印的编辑器地址、uvicorn 访问日志都带 `token=`，不掩就等于把令牌写进文件）
  - 日志不可用时（目录不可写等）引擎照常运行，失败原因记录在 `enginelog.last_error()`
- **关于运行日志怎么用**，见 [11. 常见问题](#11-常见问题与排错) 的「后端突然不见了，怎么查原因」

#### 🔧 变更

- **打包不再创建控制台窗口**（PyInstaller `--noconsole`）
  - 理由一：那是个**可以被点掉的窗口**。流程回放是「真实输入 + 绝对坐标点击」，脚本完全可能点到自己的控制台 ✕ 上，把后端当场杀掉
  - 理由二：挂机时它还会占屏幕、抢焦点
  - 代价与配套：stdout/stderr 不再存在，**所有输出只进日志文件**（所以本版必须先有落盘日志）；启动期致命错误（如端口被占用）改为弹原生错误框，否则「双击了没反应」将无从判断

#### 🐛 修复

- **悬浮框「点开循环次数后立刻打字，输入会丢」**（本版回归测试里发现的竞态）
  - 成因：点开数字时窗口要被临时激活，OS 激活本身会送来一次失焦。旧实现用「悬浮框是否还是前台窗口」来区分「激活造成的失焦」与「用户点到别处」，而**激活刚发生时悬浮框还没拿到前台**，于是被误判成后者：拿编辑框里上一次的残留数字抢先提交，并当场结束编辑态，用户紧接着敲进去的数字全部丢失
  - 修复：进入编辑后的 400 毫秒内，失焦一律判定为激活造成——只把焦点抢回输入框，绝不提交；同时给每次编辑编号，丢弃上一次编辑遗留的延时判定（否则它会用旧文本提交）
  - 只有在「点击数字后 400 毫秒仍然拿不到前台」这种极端情况下行为才有差别，真实点击路径不受影响

#### 📝 文档

- FAQ 新增「后端突然不见了，怎么查原因」；目录结构补 `engine/enginelog.py`、`tools/test_engine_log.py` 与 `tools/test_noconsole_log.ps1`（在打包产物上核验「无控制台 + 日志落盘 + 令牌掩码」）
- 回归测试总量：拆分/打包 52 + 背景几何 23 + 引擎状态 50 + 启停/暂停 32 + 关闭页面 7 + 悬浮框编辑 16 + **运行日志 16** = **196 条断言**

### v0.7.2 —— 2026-09-26

五项修复与调整：悬浮框「回到界面」不再弹出后端控制台、背景取景框不再超出弹窗、首页彻底移除、运行日志也透出自定义背景、悬浮框循环次数可直接编辑。

#### 🐛 修复

- **悬浮框「回到界面」有时会把后端控制台弹出来**
  - 根因：`find_webui_window` 把「像不像浏览器」只当成**排序键**、没有做过滤。于是当浏览器窗口一个都没匹配上（标签页被切走、页面标题变了）时，`matched[0]` 会退而返回**任意同名窗口**——而承载后端的终端/控制台窗口标题里就含 `AutoGameTool`
  - 修复：只接受真正的浏览器窗口（类名 `Chrome_WidgetWin*` / `MozillaWindowClass`，或常见浏览器进程名），并显式排除控制台 / 终端 / 解释器（`conhost.exe`、`windowsterminal.exe`、`pwsh.exe`、`cmd.exe`、`python.exe`、`AutoGameTool.exe` 等进程，以及 `ConsoleWindowClass`、`CASCADIA_HOSTING_WINDOW_CLASS` 等窗口类）。找不到就返回 `None`、只记一条提示日志，**不再乱切窗口**
- **选背景图时取景框超出弹窗（看起来像"图片超出选择框"）**
  - 根因：用 `clientWidth` 当可用宽度，而它**包含 padding**。弹窗宽 720 时取景框做到了 718，比正文内容盒（约 670）宽出约 46px，视觉上压过标题 / 说明 / 按钮
  - 修复：改用**内容盒**宽度（`clientWidth - paddingLeft - paddingRight`）；并给取景框加 `ResizeObserver` 监听弹窗内容盒尺寸变化——比只听 `window.resize` 可靠（弹窗打开动画、面板拖拽都会改变它，却不一定触发 window resize）
  - 实测：弹窗 720 时取景框 670×377，比例与窗口一致（1.777 vs 1.778），不再超出
- **运行日志区不透出自定义背景**
  - 根因：样式选择器写成了 `.log-wrap`，而日志面板的实际类名是 `.logpanel` —— 选择器从未命中
  - 修复：改正选择器，日志面板与其它面板一样压一层 `rgba(22, 26, 34, 0.82)`
- **悬浮框循环次数编辑自身的两个缺陷**（新增功能自查时发现并修掉）
  - `_begin_repeat_edit` 里使用了未定义的 `user32`，`NameError` 被 `except` 吞掉 → 点击数字**毫无反应**（这种错靠肉眼观察只会得到"点了没反应"，定位不到原因）
  - **第二次编辑必然失败**：`focus_force()` 会把 Tk 焦点从输入框挪走、触发 `<FocusOut>`，于是当场把**上一次的残留文本**提交掉。改为不再 `focus_force`，并把"失焦"改成**延时判定**：只有窗口真的不再是前台才算用户走开（提交），否则把焦点抢回来继续编辑
  - 另一个必要步骤：光清 `WS_EX_NOACTIVATE` 不够，非活动窗口拿不到键盘焦点（Tk 仍以为输入框有焦点，按键却打给了别人），必须 `SetForegroundWindow` + **`SetFocus`**

#### 🔧 变更

- **首页彻底移除**：删除 `Home.vue` 与 `/home` 路由，`/` 与任何未匹配路径都进编辑器 —— 界面只剩唯一一个主界面
- **悬浮框循环次数可直接编辑**：中间那个数字是输入框（不再只有 ±）。点它 → 临时解除 `WS_EX_NOACTIVATE` 并真正激活窗口 → 输入数字 → `Enter` 提交 / `Esc` 放弃 / 点别处提交 → 立刻恢复"不抢焦点"。非法与越界输入夹到 1–9999 并回显真实值；运行中禁用（与 ± 一致）
  - 新增动作 `repeat_set:<n>`；引擎侧 `_set_repeat_to()` 成为 ± 与直接输入的**共同实现**（夹取范围、同步悬浮框显示、更新引擎侧流程轮数三件事必须一起做，否则会出现"悬浮框改了但执行时还是旧轮数"）
- **回归测试不再注入系统输入**：新增 `tools/test_overlay_edit.py`（13 条断言），用 Tk 内部合成事件（`widget.event_generate`）驱动**真实控件与真实绑定**，不再移动用户光标、不再把按键打进当前前台窗口 —— 那种做法既打扰用户，又只要用户此刻在用电脑就必然测不稳。为此给 `Overlay` 增加了 `call_in_tk()`（在 Tk 线程里执行并取回结果）

#### 📝 文档

- 更新悬浮框界面示意与按钮表（含"循环次数可直接编辑"的交互说明）、路由说明、目录结构（移除 `Home.vue`，补 `SettingsModal.vue`）
- FAQ 增补「点右上角图标把后端控制台弹出来了」「找不到首页入口了」两条
- 回归测试总量：拆分/打包 52 + 背景几何 23 + 引擎状态 50 + 启停/暂停 32 + 关闭页面 7 + 悬浮框编辑 13 = **177 条断言**

### v0.7.1 —— 2026-09-26

界面动线整理 + 两个新功能：打开即进编辑器、暂停、自定义背景。

#### ✨ 新增

- **暂停 / 继续**（界面顶栏与悬浮框都有）
  - 与「停止」的区别：停止结束本次运行，暂停只是冻住，**继续后从原地接着跑**
  - 只在**检查点**生效：节点边界、以及延时的 250ms 小睡之间。暂停期间延时**不再流逝**，恢复后睡完剩余时间
  - 刻意不放进找图/判断的轮询与宏回放：那里的超时/时序基准按 `time.time()` 算，中途停住会把暂停时长算进去，恢复后立刻误判超时或"追帧"倾倒剩余事件（见 [10.16](#1016-暂停的语义与生效位置v071-起)）
  - 悬浮框：新增 `⏸ 暂停 / ▶ 继续` 按钮（运行中才可用），暂停时进度显示 `⏸ 已暂停 · 第 n/m 轮`、按钮转为琥珀色
  - 新增接口 `POST /run/pause`、`POST /run/resume`；`/run/state`、`/overlay/state`、WS `state` 消息都带上 `paused`
  - 边界情况一并处理：空闲时暂停无效（不会出现"已暂停但空闲"）、停止会清掉暂停（否则暂停等待循环会挂着）、新一轮开跑不带上一轮遗留的暂停、任务结束后 `reconcile` 复位暂停
- **自定义背景**（顶栏 **⚙ 设定**）
  - 选本地图片 → **按当前窗口比例截取**（cover 铺满 + 拖动平移 + 1×~3× 缩放 + 三分线参考）→ **透明度** 5%~100% 实时生效
  - 背景铺在整个界面最底层（首页/编辑器都生效），画布与面板各压一层半透明暗色，保证节点、连线、文字始终可读；未设置背景时外观与之前完全一致
  - 图片只存本机浏览器 `localStorage`：不上传引擎、不写进 `.agflow`（换台机器打开同一个脚本不该跟着变样）；导出限制在 1920×1080 以内，装不下时自动逐档降质并给出说明
  - 几何算法抽成纯函数 `frontend/src/lib/bgCrop.ts`，界面显示与 canvas 导出**共用同一个 `drawRect()`**；新增 `.\tools\test_bg_crop.ps1`（23 条断言）

#### 🔧 变更

- **打开即进编辑器**：`/` 直接重定向到 `/editor`，不再需要先点「新建脚本 / 编辑脚本」两步。旧首页仍保留在 `/home`（旧链接可用），编辑器顶栏的「← 返回」随之下线
- **「新建脚本」移到编辑器顶栏右上角**（「保存」左边）：清空画布与脚本名，并带二次确认；刻意**不清空撤销历史**，误点一次 `Ctrl+Z` 就能找回原来的流程

#### 🐛 修复

- **顶栏「＋ 新建」按钮不显示**
  - 根因：`<n-popconfirm>` 用了但**忘了 `import { NPopconfirm }`**。Naive UI 按需引入、没有全局注册，Vue 对无法解析的组件会当未知元素渲染，**具名插槽里的内容被整个丢掉**——按钮就凭空消失了
  - 同一个根因还影响了 v0.6.0 就存在的属性面板「✂ 拆分为可编辑步骤」按钮（一直没显示过，因为顶栏的「✂ 拆分录制」入口掩盖了它）
  - 更麻烦的是 `vue-tsc` 与 `vite build` **都不会报错**——这正是它长期没被发现的原因
  - 除了补上 import，还新增 `tools\check_ui_imports.mjs` 静态检查并接进 `build_exe.ps1`：以后构建期就会直接失败并指出缺哪个组件

#### 📝 文档

- 新增 [10.16 暂停的语义与生效位置](#1016-暂停的语义与生效位置v071-起)、[10.17 自定义背景](#1017-自定义背景选图--按屏幕比例截取--透明度v071-起)；新增 9.8 背景截取几何回归测试
- 更新功能列表、API 表、WebSocket 消息表、目录结构；FAQ 增补 7 条；已知限制新增"暂停只在检查点生效""背景图存在本机浏览器"
- 回归测试总量：拆分/打包 52 + 引擎状态 31 + 启停状态 32 + 关闭页面 7 + 背景几何 23 = **145 条断言**；另附端到端实测（打开即进编辑器、顶栏按钮顺序、设定面板、背景层生效）

### v0.7.0 —— 2026-09-26

一次以**状态一致性**为核心的修复批次：WebUI 与悬浮框不再各说各话，快捷键与「停止」都变得可信任、可诊断；另外补上编辑器撤销/重做，并让关闭页面时后端一起退出。

#### 🐛 修复

- **WebUI 与悬浮框的启停状态不一致**
  - 根因：悬浮框只在流程**起跑和结束**两处被更新（`executor._state()`），任何绕过它的状态改动（`/run` 里先置位的 `running`、`stop()`/`reconcile()` 的兜底复位）悬浮框都不知道；而前端有 `/run/state` 每秒自愈，悬浮框没有，于是两边一旦分叉就再也回不来
  - 修复：`_sync_run_state()` 成为唯一推送口（`/run`、`/run/stop`、`/run/state` 都调用），再加一个 **1 秒状态看门狗**给悬浮框补上前端早就有的自愈能力
- **反复点悬浮框「停止」没反应**
  - 根因一：启停方向由**前端**按自己那份可能过期的 `store.running` 决定，两边一有偏差，「停止」就变成"再启动一次"或被 409 挡掉
  - 根因二：`delay` 节点整段睡死、不检查停止标志，挂机脚本里几十秒的延时期间点停止要等它走完
  - 修复：**停止一律由引擎直接执行**（不再广播让前端决定方向；启动才发语义明确的 `run_request`）；`delay` 改为每 250ms 检查一次；`/run/stop` 等流程真正收尾（最多 2 秒）再返回，按钮不会先亮着"停止"
- **全局快捷键疑似对悬浮框无效**
  - 根因一：同上的方向判断问题，快捷键走的也是这条链路，而且**成功与否完全没有日志**，无法判断按键有没有被识别
  - 根因二：`HotkeyManager` 只在「所有键都松开」时才复位「已触发」锁——按住 `alt` 连按两次 `f1`，第二次按下时 `alt` 还按着，于是**只触发第一次**
  - 修复：组合键里的**非修饰键**一抬起就解锁（长按 `f1` 的自动重复仍只触发一次）；每次触发都记日志 `全局快捷键：启动脚本 / 停止脚本`，并区分动作来源（悬浮框 / 全局快捷键）

#### ✨ 新增

- **脚本编辑器撤销 / 重做**（顶栏 ↶ ↷ 按钮，`Ctrl+Z` / `Ctrl+Y` / `Ctrl+Shift+Z`）
  - 覆盖所有改动路径：增删节点、连线、拖动坐标、属性面板改参数、拆分、打包、加载
  - 采用**快照 + 350ms 防抖 + 按内容去重**，而不是在每个修改点手动入栈——因为 Vue Flow 自己也会改 `nodes`/`edges`（`Delete` 键删除、拖动），逐个包起来必然漏，漏掉的部分会表现为"撤销时灵时不灵"
  - 快照只保留流程语义字段（剔除 `dimensions`/`selected` 等运行时属性），上限 60 步，加载脚本时清空（撤销不跨脚本）
- **关闭 WebUI 即关闭后端**：最后一个页面断开且 6 秒内没有重连 → 停止流程并优雅退出（走完 lifespan 清理，钩子正常注销）
  - 宽限期是必需的：刷新页面（F5）、前端热更新都会先断开再重连，否则"刷新一下"会变成"把后端也关了"
  - 边界：**从未有页面连过则永不自动退出**（无人值守 / 冒烟测试）；`AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE=1` 可关闭该行为
- **三个回归测试**（合计 49 条断言，见 [9.7](#97-引擎行为回归测试)）：`test_engine_state.py`（快捷键锁 + 状态去重，纯逻辑）、`test_state_sync.py`（两处状态必须一致 + 停止真能停）、`test_webui_close.py`（三种断开时序）

#### 🎨 界面

- **悬浮框「界面」按钮改为右上角矢量图标**：不再占用底部操作行，也不再和启停按钮抢注意力。造型是一个左上角开口的方框 + 指向左上角的箭头 + 右下角实心方块，用 Tk `Canvas` 画线绘制（不引入图片资源、任意 DPI 清晰），悬停变主题青色；点击行为与原「界面」按钮完全一致
  - 底部操作行因此只剩「▶ 启动 / ● 录制」与「循环 － n ＋」，横向更宽松

#### 📝 文档

- 新增 [10.13 启停状态为什么不会再分叉](#1013-启停状态为什么不会再分叉v070-起)、[10.14 关闭 WebUI 即关闭后端](#1014-关闭-webui-即关闭后端v070-起)、[10.15 撤销/重做为什么用快照+防抖](#1015-撤销--重做为什么用快照--防抖v070-起)；重写 10.6 快捷键执行链路；更新悬浮框界面示意图与按钮表
- 已知限制新增"撤销粒度由时间决定"与"停止是协作式的"；FAQ 增补 6 条排错项

### v0.6.2 —— 2026-09-22

补齐拆分的**逆操作**（打包合并），并修掉拆分后把流程排成一条长竖线的问题。

#### ✨ 新增

- **打包合并（拆分的逆操作）**：`Shift`+拖拽框选或 `Ctrl`+点击选中一串相邻步骤 → 顶栏 **📦 打包合并**，合并回一个「键鼠录制」步骤
  - 点击 → `mousedown`/`mouseup`（保留坐标与按键，`clicks>1` 按时重复）；按键 → 组合键按顺序按下、**逆序**抬起；延时 → 推进时间轴；**嵌套录制** → 其事件按自身 `speed` 折算后内联（多段录制可并成一段）
  - 只接受**一条连续链**：成环、有分支（判断节点两条出边）、隔着没选的节点都会拒绝并说明原因
  - 找图 / 判断 / 文本 / 终止**无法**表达成键鼠事件 → **整体拒绝**，不做部分打包（避免悄悄丢动作）
  - 勾了「单次执行」的步骤也拒绝打包（录制步骤表达不了"仅第一轮"）
- 新增 `orderChain`（链序判定）与 `packStepsToMacro` 两个纯函数，回归测试从 15 条扩到 **52 条**，含「打包 → 再拆分」往返等价

#### 🐛 修复

- **拆分后所有步骤竖向排成一列**：原实现固定 `x = base.x`、`y` 每步加 76，十几步就拖出去很远，还会盖住下方的节点，后继节点的连线绕回来横穿整块
  - 改为**蛇形网格**：行数由编辑区可见高度决定（3~14 行），排满一列再向右折；列数凑成**奇数**，使块内每条相邻连线都首尾相接（同列上下相邻、换列同一行相邻），不出现长对角线
  - 会被方块压到的原有节点**整体下移同一距离**，让位的同时保持它们彼此的相对排布
  - 拆完自动 `fitView()`。实测 12 步 → `3 列 × 4 行`（原来 1 列 12 行），40 步 → `7 列 × 6 行`，5 步以内仍是单列
- **多选事件名用错会导致打包入口永远是灰的**（开发过程中发现并修掉）：`@vue-flow/core` 1.48 的 emits 列表里**没有** `selectionChange`，只有 `selectionStart` / `selectionDrag` / `selectionEnd` / `nodeClick` / `paneClick`。改为在这些真实事件里主动调用 `getSelectedNodes()` 刷新选中集合，并用节点自身的 `selected` 标记兜底

#### 🔧 变更

- 左侧步骤面板底部补上多选操作提示（`Shift+拖拽` 框选、`Ctrl+点击` 加选）
- 录制节点的属性面板补一行说明：拆开的步骤可以用「📦 打包合并」合回去

### v0.6.1 —— 2026-09-22

修一个**可用性缺陷**：v0.6.0 的「拆分录制」只在选中录制节点时才出现在右侧属性面板里，不在工具栏、也不在左侧步骤面板，导致功能做了却找不到。本版补顶栏常驻入口，并加了版本号显示。

#### 🐛 修复

- **找不到「拆分录制」的入口**
  - 原因：v0.6.0 只把按钮放在属性面板的 `macro` 分支里（渲染条件是 `selectedNode.data.stepType === 'macro'`）。左侧步骤面板与顶栏都没有任何入口，没选中录制节点时整个功能不可见
  - 修复：顶栏设置条新增**常驻**按钮 **✂ 拆分录制**（在「⏺ 开始录制」右侧）。流程里有录制步骤时按钮可用——选中了就直接拆它，只有一个时不必先选中，有多个且未选中会提示先选一个；一个都没有时置灰并提示先录一段
  - 右侧属性面板那个按钮保留（作用于该节点），旁边加了一行说明指向顶栏入口
  - 录制完成后的提示改为「已录制 N 个事件，并生成一个录制步骤（可点顶栏「✂ 拆分录制」拆成可编辑节点）」，停留 6 秒

#### ✨ 新增

- **顶栏显示引擎版本号**（右上角 `v0.6.1`）：确认"界面里看到的到底是不是最新版"不用再翻发布页。它取 `/health` 的 `version`，界面与引擎同包发布，所以等于当前程序版本
  - 顺带解决一个常见困惑：**引擎重启不会让已打开的页面换掉旧 JS**。如果顶栏没有版本号，说明页面还是旧版，`Ctrl+F5` 即可

### v0.6.0 —— 2026-09-22

录制模型大改：不再记录鼠标轨迹、只记点击坐标，录到的一段操作可以**一键拆分成可编辑的流程节点**；同时继续收敛「最小化后被弹出来」的可能性。

#### ✨ 新增

- **录制一键拆分**（选中「键鼠录制」节点 → `✂ 拆分为可编辑步骤`，带二次确认）
  - 拆出的是**普通节点**：鼠标点击（保留按下时的坐标与左右中键）、键盘按键（`ctrl+shift+a` 这类组合键合成一个节点）、滚轮、延时，都可单独修改
  - 连线自动重排：原入线接到首节点、原出线接自尾节点，上下游不受影响
  - 相邻动作间隔 ≥ 80 ms 自动插入**延时节点**，保留原本的操作节奏
  - 合并规则抽成纯函数 `frontend/src/lib/macroSplit.ts`（`compileMacroPieces` / `expandPieces`），不依赖 Vue
  - 新增回归测试 `.\tools\test_macro_split.ps1`（15 条断言全绿，含「`ctrl` 按住不动、先后配 `a` 和 `b`」这类组合键边界），见 [9.6](#96-录制拆分与打包算法回归测试)

#### 🔧 变更

- **录制不再记录鼠标轨迹**（`mousemove` 不入库）
  - 现在只记录：鼠标按下 / 抬起（含**按下时的坐标**与按键）、滚轮、键盘按下 / 抬起
  - 回放不再逐点移动光标，而是由点击事件**直接把光标落到该坐标**再按下（`inputctl.mouse_down`），效果等价，事件数下降一到两个数量级
  - 兼容性：回放端未改，**旧脚本里的 `mousemove` 事件仍能正常回放**；只是重新录制的新脚本不再包含轨迹点
- **窗口最小化加固**（针对「最小化后又弹出来」的反馈，详见 [10.11](#1011-窗口最小化与截图v050-修正)）
  - 移除悬浮框的**周期性** topmost 重写，只保留「鼠标移入悬浮框」「显示时」与首次创建——这是应用内**唯一**一处会周期性写窗口 Z 序的代码
  - 用户主动触发的窗口恢复改用 `SW_SHOWNOACTIVATE`，恢复时**不激活**窗口，不再抢前台焦点
  - 删除死代码 `window.set_foreground`（已无调用方）
  - `/screen/screenshot`、`/vision/match` 恢复最小化窗口时补一条 warn 日志（`截图：目标窗口原本处于最小化，已恢复显示（不激活到前台）`），万一复发可直接从日志面板定位来源

#### 🐛 修复

- **组合键拆分退化成单键**：原按「最后一个键抬起」结算，而那时候选集合已被逐步过滤得只剩最后按下的那个键，`ctrl+shift+a` 会变成 `ctrl`。改为按「本轮第一个抬起」结算，并让新一轮组合键继承仍按住不放的修饰键

### v0.5.1 —— 2026-09-13

三项修复：悬浮框「界面」弹错窗口、加载脚本名显示成占位名、用悬浮框录制会把点击悬浮框自身录进宏。

#### 🐛 修复

- **悬浮框「界面」弹出的是资源管理器，而不是 WebUI**
  - 根因：项目目录常被文件资源管理器开着，其窗口标题恰好就是「AutoGameTool」。旧实现只按标题匹配、还优先选**未最小化**的窗口，于是永远抢到资源管理器，而最小化的浏览器永远排在后面
  - 修复：`find_webui_window` 额外要求「窗口类名或进程名看起来像浏览器」（`Chrome_WidgetWin*` / `MozillaWindowClass`，或常见浏览器 exe），并排除 `explorer.exe` 与自身进程；排序改为 浏览器 → 未最小化 → 面积最大
- **加载脚本后左上角仍显示「未命名脚本」**
  - 根因：保存时若没改名，文件里记录的 `name` 就是占位名「未命名脚本」，加载时被原样恢复
  - 修复：文件内的名字若为空或等于占位名，则改用**文件名**（去掉 `.agflow` 后缀），方便按脚本名继续修改
- **用悬浮框开始/停止录制会把这些点击录进宏，回放时递归录制**
  - 根因：录制期间点悬浮框按钮本身是真实鼠标点击，被一并录进宏；回放时又点到同一个按钮 → 再次开启录制
  - 修复：录制时过滤掉落在悬浮框矩形内的鼠标事件（移动 / 按下 / 抬起 / 滚轮）；按下被过滤时会记住该按键，把它配对的抬起一并丢弃，避免留下孤立的 `mouseup`

### v0.5.0 —— 2026-09-13

悬浮框加入四个快捷操作，并修掉「最小化浏览器偶尔失败」的两个成因。

#### ✨ 新增

- **悬浮框快捷操作**（不必切回浏览器即可操作）
  - **启动 / 停止**：与全局快捷键、界面按钮**同一条链路**，始终使用画布上最新的流程
  - **录制 / 停录**：开始或结束键鼠录制，录到的事件照常推给前端并生成「键鼠录制」节点
  - **循环 － / ＋**：调整循环轮数（1–9999），同步前端并广播给所有页面；运行中禁用，改动下次运行生效
  - **界面**：把 WebUI 所在浏览器窗口恢复并切到前台（按页面标题匹配，最小化状态也能唤回）
  - 按钮文字与配色跟随真实状态（启动/停止、录制/停录），状态由引擎统一下发
  - `/overlay/state` 增加 `repeat` / `running` / `recording` 字段；新增 WebSocket `repeat` 消息用于跨页面同步轮数

#### 🐛 修复

- **最小化浏览器偶尔失败**
  - **成因一**：`capture_window` 在窗口最小化时**无条件** `ShowWindow(SW_RESTORE)`。挂机时用户常故意最小化游戏/浏览器，于是每个找图/判断节点都把它弹回前台，看起来就是"最小化失败"（本次修掉）。现在流程执行默认 `restore_minimized=False`，最小化时直接报错结束该节点而不弹窗；只有用户主动点击的「截取」/「测试匹配」才显式传 `True` 恢复窗口
  - **成因二**：悬浮框旧版每 2 秒**无条件** `SetWindowPos(HWND_TOPMOST)`，会在别的窗口播放最小化动画时搅动 Z 序，造成偶发失败。现改为先读扩展样式，仅在确实丢失 topmost 时才写 Z 序
- **悬浮框不再抢焦点**：窗口加 `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`，点击按钮不会夺走前台焦点，也不会出现在 Alt-Tab 列表里

### v0.4.0 —— 2026-09-13

三项改进：修复运行状态卡死、脚本加载改为默认全局绑定、新增置顶悬浮框。

#### 🐛 修复

- **流程结束后右上角按钮卡在「停止」**
  - 根因：`executor.run()` 中 `self.running = True` 之后、`try:` 之前还夹着「开跑日志 + 分辨率换算」。这段一旦抛异常（例如 `.agflow` 里的 `screen.width` 是非数字串，`float()` 抛 `ValueError`），`finally` 不会执行，`running` 就永久停在 `True`；而 `/run/stop` 又原样回传 `running`，于是点按钮也切不回来
  - 修复：置位 `running` 之后的**全部逻辑**纳入 `try/finally`；分辨率换算单独容错（失败则按原坐标继续执行并记警告）；`Executor` 记录当前任务，`stop()` 与 `reconcile()` 在「没有实际任务在跑」时直接复位 `running`，`/run/state` 每次读取都做一次自愈
- **加载脚本时默认绑定一个已失效的窗口**
  - 根因：`onLoadFile` 把 `.agflow` 里保存的 `window.hwnd` 直接恢复为绑定，而该句柄早已不存在，下拉框于是显示成一个空进程，必须手动重选
  - 修复：加载脚本一律**默认全局绑定**（「不绑定窗口」），并丢弃文件里的窗口 rect 参考，避免之后手动绑定窗口时误用旧 rect；文件的分辨率参考 `screen` 仍然保留，跨分辨率坐标换算不受影响

#### ✨ 新增

- **置顶悬浮框**（默认关闭，界面 `🪟 悬浮框` 一键开关）
  - 显示 `第 N/M 轮` 与当前正在执行的节点（带模板名 / 按键 / 延时 / 文本摘要）
  - 无边框 + 始终置顶 + 可拖拽；点 `✕` 收起并同步回前端；开关持久化到 `config.json`
  - 由引擎用 `tkinter` 在独立线程创建**原生窗口**（浏览器无法做出真正盖在游戏之上的窗口），执行器只往队列投递进度，Tk 线程定时消费
  - `tkinter` 不可用时自动降级：`/overlay/state` 返回 `available=false`，前端按钮置灰，绝不影响流程执行
  - 新增接口 `GET /overlay/state`、`POST /overlay/enable`，以及 WebSocket `overlay` 消息（多标签页同步）

#### 🔧 内部

- 新增 `engine/appconfig.py`：`%APPDATA%\AutoGameTool\config.json` 的统一读写入口（原子写入）；`hotkey.py` 改为复用它，消除多处「读-改-写」互相覆盖的隐患

### v0.3.0 —— 2026-09-12

本版修复了此前排查出的全部 P0–P2 问题与部分 P3 项，并新增多分辨率 / DPI 自适应。

#### 🔒 安全

> 引擎具备操控键鼠与截屏的能力，而浏览器里任何网页都能访问 `127.0.0.1`。以下改动是本版最重要的部分。

- **移除 CORS 通配符**：此前 `allow_origins=["*"]` 意味着任意网页都能跨域调用本地引擎。打包版前后端同源、本不需要 CORS，现仅在开发模式（`AUTOGAMETOOL_DEV=1`）放行 Vite 端口
- **全接口令牌鉴权**：启动时生成随机令牌，随浏览器地址 `?token=` 传入前端（存 sessionStorage 后从地址栏抹除）；HTTP 支持 `Authorization: Bearer` 与 `?token=` 双通道，WebSocket 握手同样校验，无令牌一律 401
- **Host 头白名单**：仅放行 `127.0.0.1:8765` / `localhost:8765` / `[::1]:8765`，防 DNS rebinding
- **SPA 兜底路由路径遍历修复**：`resolve()` + 归属校验，越界一律回退 `index.html`。此前用 `%2e%2e%2f` 编码即可读取引擎源码乃至磁盘上任意文件
- **`/debug/kb` 不再返回最后按键内容**：只保留计数与钩子存活状态。此前叠加 CORS 通配符，任意网页轮询该接口就能拼出用户全局敲击的字符——一个开箱即用的远程键盘记录器
- **模板名白名单校验**：仅允许中英文、数字、空格与 `-_.`，禁止 `..` 与 Windows 保留名，并对 `resolve()` 结果做父目录断言。此前模板名可用于向任意路径写 / 删 / 改文件
- **模板重名保存报错**（不再静默覆盖）；请求体加 64 MB 上限，避免超大 base64 图片造成内存 DoS

#### 🐛 正确性

- **流程前置校验**（`validate_flow`）：`repeat` / 节点 / 连线非法时直接返回 400。此前 `repeat: "abc"` 会让引擎永久卡在"运行中"，之后所有 `/run` 都返回 409，只能重启进程
- **组合键回放**：`_split_combo` 正确拆分 `ctrl+shift+a`——修饰键先按、主键居中、逆序抬起，真实与模拟两种模式均生效。此前模拟模式静默无效、真实模式直接抛错
- **Win 键快捷键修复**：`_norm` 把 pynput 的 `cmd*` 归一为 `win`，`win+x` 不再永远无法触发
- **模拟模式滚轮**：改用 `PostMessage(WM_MOUSEWHEEL)`，宏回放不再滚动用户的真实桌面
- **后台任务强引用**：统一 `_spawn()` 持有 `create_task` 引用，避免任务被 GC 中途回收导致流程"无声消失"
- **节点 ID 不再冲突**：加载脚本后取现有 ID 的最大数字后缀（此前 `n1, n2, n5` 会新生成 `n5`）
- **`/run` 原子化**：检查与置位加 `asyncio.Lock`，消除并发双启动窗口
- **模板重命名 / 删除联动 `.meta.json` 侧车文件**
- **前端错误提示**：解析 FastAPI 的 `detail` 字段，不再直接展示原始 JSON
- **截图框选补偿滚动偏移**：大图滚动后框选不再偏移

#### ⚡ 性能

- **截图 / 匹配 / 键鼠输入全部 `asyncio.to_thread`**：不再阻塞事件循环。此前窗口最小化时每次截图都会让 WebSocket 日志与所有前端请求额外卡 300 ms
- **流程同步按指纹去重**：不再每秒向引擎全量重发流程
- **WebSocket 广播并发化**（`asyncio.gather`）并兜底清理异常连接

#### ✨ 新增

- **多分辨率 / DPI 自适应**
  - 保存模板时记录参考画面尺寸（`模板名.meta.json`），匹配时按相同比例自动缩放（`match_template_auto`，0.3x–3x，横纵比一致才启用），得分不理想则自动回退原尺寸取高分
  - `.agflow` 写入参考主屏分辨率（`screen`）与绑定窗口 rect（`window.rect`），执行时点击 / 宏坐标按比例换算：绑定窗口优先走「参考 rect → 当前 rect」，未绑定则按主屏分辨率
  - 实测同分辨率 / 1.5x / 0.5x 缩放均能命中且坐标正确
- **执行保护**：单轮步数上限，防止"无终止环"空转；多起始节点与不可达节点在启动时告警
- **快捷键配置原子写入**（临时文件 + rename）并校验空值

#### 当时遗留的技术项

以下项当时未处理、列入后续迭代（部分已在后续版本完成）：`mss` 实例单例复用、最小化窗口截图的自动恢复副作用、DWM 边框坐标基准注释、录制停止时刻的残留事件边界、快捷键双触发观感，以及构建脚本与供应链加固（NSIS 下载校验和、依赖哈希锁定）。

### v0.1.0 —— 首个公开版本

- 可视化流程编辑器（Vue 3 + Vue Flow）与节点式编排：找图 / 判断分支 / 点击 / 按键 / 输入文本 / 键鼠宏回放 / 终止
- Python 引擎（FastAPI + OpenCV）：灰度模板匹配、窗口枚举与绑定、真实与仿真（PostMessage）双输入模式、全局快捷键
- PyInstaller 打包（文件夹形态）+ NSIS 安装包（免管理员、含开始菜单与桌面快捷方式、标准卸载器）

---

## 15. 开源协议

本项目**自有代码**基于 **MIT License** 开源，详见 [`LICENSE`](LICENSE) —— 你可以自由使用、修改、分发甚至商用，只需保留版权与许可声明。

需要注意的是，MIT 只覆盖本仓库自有的代码。发行版安装包里还打包了若干第三方组件，其中 `pynput` 采用 **LGPL-3.0**，另有 OpenCV（Apache-2.0）、PyInstaller（GPL-2.0+ 含 Bootloader 例外）等。各组件的版本、许可与相应义务见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

如果你打算二次分发或商用本项目的发行版，请一并遵守上述第三方许可。

---

<div align="center">

**AutoGameTool** · Windows 优先 · 本地引擎 + 一键安装

</div>
