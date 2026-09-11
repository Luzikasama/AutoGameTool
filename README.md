# AutoGameTool

> 轻量级游戏自动化脚本工具 —— **零代码可视化编排** + **本地 Python 引擎**
>
> 像搭积木一样"画"出游戏脚本：找图、点击、按键、判断分支、循环挂机，全程不写一行代码。

## 前言

- 此项目完全由 **DeepSeek Harness** 完成，使用模型为 **DeepSeek V4.1 Flash**。
- 原本是为**造梦西游4**设计的挂机脚本程序，主要为了解决360游戏大厅固定流程，游戏加载卡住等问题。
- 实测opencv运行识别有时偏慢，但总体效果良好，10+小时挂机无问题
- todo：后台模拟输入、区域识别（减少opencv识别时间）、快捷键统一管理


## 下载

| 方式 | 说明 |
|---|---|
| **[⬇ 安装包（Releases）](https://github.com/Luzikasama/AutoGameTool/releases/latest)** | `AutoGameTool-Setup.exe`，Windows 10 / 11，免管理员，约 68 MB |
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
- [14. 开源协议](#14-开源协议)

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
| 键鼠录制 | ⏺ | **alt+9** 开始/停止，录制鼠标(移动/点击/滚轮)与键盘(按下/抬起)，打包为**一个步骤**，支持 0.25x~4x 变速回放 |
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
| 坐标拾取 | **F8** 进入拾取 → **左键单击** → 捕获**真实屏幕坐标**（全局鼠标监听，无换算误差） |
| 输入模式 | **键鼠输入**（真实设备）/ **模拟输入**（PostMessage 后台消息，不占用物理键鼠） |

### 2.5 运行与调试

- **全局快捷键启停**：默认 `alt+f1`，可在界面中录制修改
- **实时日志**：WebSocket 推送，带**毫秒级时间戳**
- **循环执行**：整图按轮次循环
- **急停**：界面按钮 / 快捷键 / 引擎侧停止
- **单步容错**：单个节点失败只记日志，不中断整个流程（挂机更稳）
- **单实例保护**：重复启动会被拦截并提示（避免多开导致键盘钩子互相干扰）

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
| 路由 | **Vue Router** | ^4.6.4 | 首页 / 编辑器 |
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
| 桌面壳 | **Tauri 2.0**（Rust） | 已配置 `frontend/src-tauri/`，可编译原生窗口 |
| 当前发行方式 | **PyInstaller `--onefile`** | 引擎 + 内嵌前端 → 单个 `AutoGameTool.exe`（约 68 MB） |
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
│                    AutoGameTool.exe（单文件）                  │
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
├─ AutoGameTool.exe           # 发行版单文件（PyInstaller 产物）
├─ AutoGameTool-Setup.exe     # 安装包（NSIS 产物）
├─ README.md
├─ build_exe.ps1              # 一键打包：前端构建 + PyInstaller 单文件
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
│  │  ├─ App.vue              # 全局 Provider + 布局
│  │  ├─ style.css            # 暗色主题 / 全局样式
│  │  ├─ types.ts             # 节点 / 流程 / 日志类型
│  │  ├─ router/index.ts      # 路由
│  │  ├─ stores/project.ts    # Pinia：流程名/循环/输入模式/绑定窗口/日志
│  │  ├─ api/client.ts        # 引擎 HTTP 客户端
│  │  ├─ views/
│  │  │  ├─ Home.vue          # 首页
│  │  │  └─ Editor.vue        # 编辑器（画布 / 属性 / 日志 / 录制）
│  │  └─ components/
│  │     ├─ StepNode.vue      # 自定义流程节点（判断节点双出口）
│  │     └─ ScreenCapture.vue # 截图框选 / 单点拾取
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
   ├─ hotkey.py               # 全局启停快捷键
   ├─ picker.py               # F8 坐标拾取
   ├─ recorder.py             # alt+9 键鼠录制
   └─ ws_manager.py           # WebSocket 广播
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
> 若 pnpm 因依赖状态检查中止（`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`），见 [9.4 关于 pnpm 11](#94-关于-pnpm-11)。

---

## 7. 使用指南

### 7.1 快捷键

| 快捷键 | 功能 | 可配置 |
|---|---|---|
| `alt+f1` | 启动 / 停止脚本（全局，游戏窗口聚焦时也生效） | ✅ 界面「⌨ 快捷键」 |
| `F8` | 坐标拾取：进入选取 → 左键单击捕获坐标 | ❌（固定） |
| `alt+9` | 键鼠录制：开始 / 停止 | ❌（固定） |

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
  "window": { "hwnd": 123456, "title": "造梦西游4" },
  "nodes": [
    { "id": "n1", "type": "find_image",
      "params": { "template": "任务", "threshold": 0.85,
                  "timeout_ms": 5000, "on_timeout": "skip", "click": true },
      "once": false },
    { "id": "n2", "type": "judge",
      "params": { "template": "返回地图（成功）", "threshold": 0.85, "timeout_ms": 3000 } },
    { "id": "n3", "type": "macro",
      "params": { "events": [ { "t": 0, "type": "mousemove", "x": 900, "y": 500 } ], "speed": 1 } },
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

---

## 8. 引擎 API 参考

引擎默认监听 `http://127.0.0.1:8765`（开发文档 `/docs`）。

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
| POST | `/run/stop` | 停止执行 |

### 配置与工具

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/config/hotkey` | 读取 / 设置启停快捷键 |
| POST | `/pick/start` · `/pick/cancel` | 坐标拾取启用 / 取消 |
| POST | `/record/start` · `/record/stop` | 键鼠录制开始 / 停止 |

### WebSocket 消息类型

| type | 载荷 | 说明 |
|---|---|---|
| `log` | `{level, message, step, ts}` | 执行日志 |
| `state` | `{state: "running"\|"idle"}` | 运行状态 |
| `hotkey` | `{ts}` | 快捷键按下（前端据此调用 `/run` 或停止） |
| `picked` | `{x, y}` | 坐标拾取结果 |
| `recording` | `{recording: bool}` | 录制状态 |
| `recorded` | `{events: [...]}` | 录制完成的事件列表 |

---

## 9. 打包与发布

### 9.1 打包单文件 exe

```powershell
# 一键（推荐）：类型检查 + 前端构建 + PyInstaller 打包 + 复制到根目录
.\build_exe.ps1
```

脚本做三件事：

1. `vue-tsc --noEmit` 类型检查，再 `vite build` 产出 `frontend\dist`
2. 调用 `engine\.venv\Scripts\pyinstaller.exe` 打成单文件（带应用图标）
3. 把产物复制为项目根目录的 `AutoGameTool.exe`

等价的 PyInstaller 命令：

```powershell
cd engine
.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --name AutoGameTool `
  --icon ..\assets\AutoGameTool.ico `
  --add-data "..\frontend\dist;frontend_dist" `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on `
  main.py
```

产物：`engine\dist\AutoGameTool.exe` → 复制为 `AutoGameTool.exe`（约 68 MB）

**打包要点**

- 前端 `dist` 通过 `--add-data` 打进 `frontend_dist`，运行时由引擎同源提供
- opencv / onnxruntime 等含动态库的包建议加 `--collect-all`
- 使用 `--onefile` 单文件分发；如需更快启动可改 `--onedir`
- 图标取自 `assets\AutoGameTool.ico`，缺失时脚本会先调用 `tools\make_icon.py` 生成

### 9.2 制作安装包（NSIS）

```powershell
.\build_exe.ps1        # 1) 先产出 AutoGameTool.exe
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

> **关于体积**：安装包大小基本等于 `AutoGameTool.exe`（约 68 MB）。因为 PyInstaller `--onefile` 的载荷本身已是 deflate 压缩过的，NSIS 的 LZMA 几乎压不动（实测压缩率 99.7%）。若希望安装包显著变小，可把打包改成 `--onedir`，让未压缩的 DLL 交给 NSIS 压缩，代价是分发形态从单文件变成一个目录。

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

脚本会启动 exe，逐项校验 `/health`、`/debug/kb`（键盘钩子是否存活）、`/windows/list`、`/vision/templates`、`/config/hotkey`、`POST /flow/load` 以及内嵌前端页面与 favicon，最后关闭进程并输出 PASS/FAIL（有失败项时返回 1，可直接用于 CI）。

它顺带处理了两个常见的"假失败"：

- 把 `TEMP` / `TMP` 指向一个**可写的解压目录**（优先系统临时目录，不可写时才退到 exe 同级的 `.smoketmp`，并在结束时清理）——`--onefile` 需要一个可写的解压目录，受限环境下会报 `Failed to extract VCRUNTIME140.dll: ... Permission denied` 并秒退
- 设置 `AUTOGAMETOOL_NO_BROWSER=1`，避免测试期间弹出浏览器

### 9.6 安装包端到端验证

```powershell
.\tools\test_installer.ps1                  # 验证完自动卸载
.\tools\test_installer.ps1 -KeepInstalled   # 验证后保留安装
```

脚本按真实用户路径跑一遍完整闭环，共 25 项断言：

1. 静默安装（`/S`）到 `%LOCALAPPDATA%\AutoGameTool`
2. 校验主程序 / README / Uninstall.exe 是否落盘
3. 校验开始菜单 3 个快捷方式与桌面快捷方式
4. 校验注册表：`DisplayName`、`DisplayVersion`、`UninstallString`、`QuietUninstallString`、`InstallLocation`、`DisplayIcon`、`EstimatedSize`、`App Paths`
5. 对**已安装的 exe** 跑一遍 `smoke_test.ps1`
6. 静默卸载，校验安装目录 / 快捷方式 / 注册表项均已清理，且**用户数据被保留**

> 注意：该脚本会写注册表与「开始菜单 / 桌面」，需要相应权限；它不会删除 `%APPDATA%\AutoGameTool`（模板与配置）。

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
按 alt+f1 → 引擎广播 {type:"hotkey"} → 前端收到 → 调用 POST /run（与点「运行」完全一致）
```

好处：始终使用**前端当前最新流程**，不依赖引擎侧的流程缓存；同时会产生清晰的 `POST /run` 日志。

### 10.7 无人值守启动

引擎启动后默认会自动打开浏览器到 `http://127.0.0.1:8765`。设置环境变量后可以跳过：

```powershell
$env:AUTOGAMETOOL_NO_BROWSER = '1'
.\AutoGameTool.exe
```

适用于自动化测试、开机自启、由其他程序拉起的场景；界面上仍可手动访问该地址。

---

## 11. 常见问题与排错

| 现象 | 原因 / 解决 |
|---|---|
| 双击 exe 提示"程序已在运行" | 已有实例在跑。检查任务管理器结束残留 `AutoGameTool.exe` |
| 快捷键没反应 | 看前端日志面板是否有「收到快捷键：启动脚本」；无则检查是否多开、或有残留实例 |
| 键盘突然不能用了 | **旧版本的多监听器缺陷**。请用最新版并重启电脑清掉残留钩子；新版已用事件总线修复 |
| 找图超时 | 提高阈值容差（降低阈值）、缩小识别区域、确认分辨率未变 |
| 中文模板识别失败 | 旧版缺陷，新版已修复 |
| 模拟输入无效 | 见 [12. 已知限制](#12-已知限制)；先用 `/input/probe` 诊断 |
| 窗口列表里没有目标窗口 | 只列出"任务栏窗口"；若游戏是子窗口/无标题窗口则不会出现 |
| 截图黑屏 | 独占全屏游戏 GDI 无法截取；请改「无边框窗口」模式 |
| exe 启动慢 | `--onefile` 每次需解压到临时目录；可改 `--onedir` |
| 杀软误报 | PyInstaller / NSIS 常见现象；正式分发建议**代码签名** |
| 安装包被 SmartScreen 拦截 | 安装包未签名，出现「Windows 已保护你的电脑」时点「更多信息 → 仍要运行」 |
| 构建安装包时找不到 makensis | `build_installer.ps1` 会自动下载 NSIS 3.10 到 `tools\nsis`；离线环境可手动安装 NSIS，再用环境变量 `AUTOGAMETOOL_MAKENSIS` 指向 `makensis.exe` |
| 改了 `.ps1` / `.nsi` 后脚本报「字符串缺少终止符」 | 文件被存成了「UTF-8 无 BOM」，执行 `.\tools\to-utf8-bom.ps1` 修复（见 [9.3](#93-源码编码约定重要)） |
| 安装后快捷方式图标空白 | 图标缓存问题，执行 `ie4uinit.exe -show` 或重建快捷方式 |

**诊断命令**

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health          # 引擎存活
Invoke-RestMethod http://127.0.0.1:8765/debug/kb        # 键盘钩子状态
Invoke-RestMethod http://127.0.0.1:8765/windows/list    # 窗口列表
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

---

## 13. 路线图

- [ ] 后台输入方案落地（驱动级 / 隐藏桌面 / 浏览器自动化，按游戏形态选型）
- [ ] DXGI 桌面复制截图（支持被遮挡窗口）
- [ ] OCR 文本识别节点
- [ ] 像素颜色判断节点（扩充判断条件）
- [ ] 子流程 / 复用组件
- [ ] 快捷键可配置化（F8 拾取、alt+9 录制）
- [ ] 工程资源依赖校验与一键修复
- [ ] 社区项目导入导出（`.agflow` 打包与依赖声明）
- [ ] 代码签名与自动更新

---

## 14. 开源协议

本项目**自有代码**基于 **MIT License** 开源，详见 [`LICENSE`](LICENSE) —— 你可以自由使用、修改、分发甚至商用，只需保留版权与许可声明。

需要注意的是，MIT 只覆盖本仓库自有的代码。发行版安装包里还打包了若干第三方组件，其中 `pynput` 采用 **LGPL-3.0**，另有 OpenCV（Apache-2.0）、PyInstaller（GPL-2.0+ 含 Bootloader 例外）等。各组件的版本、许可与相应义务见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

如果你打算二次分发或商用本项目的发行版，请一并遵守上述第三方许可。

---

<div align="center">

**AutoGameTool** · Windows 优先 · 本地引擎 + 单文件分发

</div>
