# AutoTool

> 轻量级游戏自动化脚本工具 —— **零代码可视化编排** + **本地 Python 引擎**
>
> 像搭积木一样"画"出游戏脚本：图像识别、点击、按键、判断、循环挂机，全程不写一行代码。

## 前言

- 此项目完全由 **DeepSeek Harness** 完成，使用模型为 **DeepSeek V4.1 Flash**。
- 原本是为**造梦西游4**设计的挂机脚本程序，主要为了解决360游戏大厅固定流程，游戏加载卡住等问题。
- 实测opencv运行识别有时偏慢，但总体效果良好，10+小时挂机无问题
- todo：后台模拟输入、区域识别（减少opencv识别时间）

## 下载

| 方式 | 说明 |
|---|---|
| **[⬇ 安装包（Releases）](https://github.com/Luzikasama/AutoTool/releases/latest)** | `AutoTool-Setup.exe`，Windows 10 / 11，免管理员，双击即装，约 55 MB |
| **[⬇ 免安装绿色版（Releases）](https://github.com/Luzikasama/AutoTool/releases/latest)** | `AutoTool_0.1.4_portable_x64.zip`，解压即用、不写注册表，约 80 MB |
| 从源码构建 | 见 [9. 打包与发布](#9-打包与发布)：`.\build_desktop.ps1`（前端 → 引擎 onedir → Tauri 壳 → NSIS 安装包） |

> **当前形态：桌面版 v0.1.4** —— 原生窗口（Tauri 2）+ 本地 Python 引擎。
> 版本号自 `0.1.0` 起**按桌面版单独计数**，更新日志从桌面版 `0.1.0` 开始（见 [14. 更新日志](#14-更新日志)）。

两个包都**未做代码签名**。从浏览器下载后首次运行时，Windows 会弹蓝色的「Windows 已保护你的电脑」（SmartScreen）—— 这是**未签名程序的通用提示，不是报毒**，点 **「更多信息」→「仍要运行」** 即可，之后不再出现。

安装包已**内嵌 WebView2 引导程序**：目标机器缺少 WebView2 运行时也能由安装器自行补齐，安装过程不依赖单独联网下载。

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

AutoTool 是一款面向 **Windows** 的轻量级游戏自动化（类 RPA）工具。核心思路：

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
| 画布控制 | 放大 / 缩小 / 适应视图；**右键拖拽平移画布**，**左键拖拽框选**多个节点，`Ctrl`+点击逐个加选；**右键点击**（不拖）唤出**复制 / 剪切 / 粘贴**菜单 |
| 可缩放面板 | 日志面板高度、属性面板宽度均可拖拽调整，整体填满窗口 |
| 鼠标定位新增 | 新节点生成在**鼠标指针位置** |
| 单次执行 | 任意动作节点可勾选「单次执行」，仅第一轮循环生效 |
| 撤销 / 重做 | **Ctrl+Z / Ctrl+Y**（顶栏 ↶ ↷ 按钮），覆盖增删节点、连线、拖动、改参数、拆分、合并、加载等所有改动 |
| 新建 / 加载 / 保存 | 集中在顶栏**最左侧**：**＋ 新建**（二次确认，误删可 `Ctrl+Z` 找回）、**📂 加载**、**💾 保存**；自定义格式 `.agflow`，保存时弹出**原生保存对话框**（可覆盖 / 另存）。**保存的永远是整份根脚本**（含子脚本与组合节点），与当前停在哪个标签无关 |
| 组合节点（0.1.4） | 把一串相邻节点**合并**成一个「组合节点」：**单击**改它的名字等属性，**双击**在新标签里编辑它内部那张图。它不是输入 / 处理 / 输出里的任何一类，**只作为节点流程**存在；「取消组合」可随时拆回原节点 |
| 变量管理（0.1.4） | 右侧面板与参数配置**共用一块区域**，用「参数 / 变量」标签页切换。主脚本那份是**全局变量**，子脚本 / 组合节点各有自己的**局部变量**（读得到全局、写不外泄） |
| 无悬停说明（0.1.4） | 光标停在按钮上**不再弹说明文字**（全应用去掉了 tooltip）：按钮含义靠图标与文案本身表达 |

### 2.2 节点类型（6 大类 · 25 个核心节点）

**0.1.3 起，「步骤」升级为「节点」**：25 个核心节点按能力分成 **6 大类**，**同一类共用一种配色**（输入蓝 / 视觉绿 / 流程青 / 工具橙 / 数据紫 / 系统灰），左侧节点面板按类别分页 —— 画布上光看颜色就知道这段流程在干什么。0.1.2 及更早的 `.agflow` 打开时会**自动升级**到这套节点（见 [14. 更新日志](#14-更新日志)）。

> **0.1.4 补充两点**：
> 1. **「输入方式」不再是顶栏的全局单选**，而是**挂在每个输入节点自己的参数里**（鼠标操作 / 键盘按键 / 文本输入 / 连点器 / 键鼠录制各有一个「输入方式」）。一次流程里可以"大部分动作走真实键鼠、只有某几步走后台消息"了。老脚本仍按原样兼容：加载时会把当年的全局选择**分发到各输入节点**上。
> 2. 另有**一个不属于六大类的节点** —— **组合节点（🧩）**：由「📦 合并节点」产生，把一串相邻节点收成一个容器。它不参与上面的配色体系与 25 个核心节点计数，见 [10.12](#1012-拆分节点与合并节点)。

**① 输入（蓝）—— 执行动作：鼠标、键盘、文本、剪贴板**

| 节点 | 图标 | 说明 |
|---|---|---|
| 鼠标操作 | 🖱 | 点击 / 双击 / 右键 / 移动 / 按下松开 / 滚轮；坐标可**屏幕点选拾取**（0.1.2 的「鼠标点击」并入此节点） |
| 键盘按键 | ⌨ | 单键 / 组合键 / 按下 / 松开；**按键录制**：点「录制」后直接按下按键即可识别 |
| 文本输入 | 📝 | 输入任意文本到当前窗口（可走剪贴板，兼顾输入法） |
| 剪贴板 | 📋 | 写入 / 读取 / 清空 |

**② 视觉（绿）—— 看到什么：图像、文字、颜色、像素、区域**

| 节点 | 图标 | 说明 |
|---|---|---|
| 图像识别 | 🎯 | OpenCV 模板匹配；可设阈值、超时、**超时处理（跳过/退出）**，找到后可选自动点击（0.1.2 的「找图」） |
| 文字识别 | 🔍 | 对指定区域做 OCR（RapidOCR），输出文本 |
| 颜色检测 | 🎨 | 区域内是否出现指定颜色 |
| 像素检测 | 📍 | 精确比对一个点（或小方块）的颜色 |
| 区域分析 | 🖼 | 区域是否变化 / 平均颜色 / 截图 |

**③ 流程（青）—— 控制执行：判断、循环、延时、等待、终止**

| 节点 | 图标 | 说明 |
|---|---|---|
| 判断 | 🔀 | 按条件走「是 / 否」**双出口**（0.1.2 的「判断分支」；现在条件与识图已拆成两个节点，可自由组合） |
| 循环 | 🔁 | 固定次数 / 条件循环 / 无限循环；**「循环体」出口**走进循环体，**连回循环节点自身＝这一轮结束、进入下一轮**，**「结束」出口**在循环结束后往下走 |
| 延时 | ⏱ | 无条件等待指定时间，每 1000ms 输出一次进度日志 |
| 等待 | ⏳ | 等到条件满足（图片出现、变量达标…）再继续 |
| 终止 | 🛑 | 三级语义：终止当前**循环** / 当前**脚本** / 整个**工作流** |

**④ 工具（橙）—— 组合与外部能力：录制、连点、脚本调用、外部工具**

| 节点 | 图标 | 说明 |
|---|---|---|
| 键鼠录制 | ⏺ | **alt+F2**（可改）开始/停止，录制鼠标(点击/滚轮)与键盘(按下/抬起)，生成为**一个节点**，支持 0.25x~4x 变速回放；可**一键拆分为可编辑节点**（顶栏 **✂ 拆分节点**）。连点器是独立节点，不参与拆分 |
| 连点器 | ⚡ | **高频连点**：坐标可 **🎯 屏幕点选采集**，左/右/中键，**点击次数**与**间隔（频率）**可调；间隔低至 `0 ms` 时按"不限速、尽可能快"执行。界面实时显示换算出的**约 N 次/秒**；执行中照常响应暂停 / 停止 |
| 调用脚本 | 📦 | 执行本脚本内的一个**子脚本**（脚本嵌套），可单独编辑 / 导出 / 被多个节点复用（见 [10.21](#1021-子脚本嵌套与防递归)） |
| 外部工具 | 🔌 | 调用外部程序 / HTTP 接口 / 插件 |

> 顶栏还有一个**不属于任何一类**的 **🧩 组合节点**：由「📦 合并节点」把选中的一串相邻节点收成，单击改属性、双击进去编辑（见 [10.12](#1012-拆分节点与合并节点)）。

**⑤ 数据（紫）—— 信息本身：变量、运算、文本处理**

| 节点 | 图标 | 说明 |
|---|---|---|
| 变量 | 🏷 | 新建 / 赋值 / 读取 / 删除；写好后可在任意节点参数里用 `{{变量名}}` 插值 |
| 运算 | 🧮 | 数学、比较、逻辑、赋值 |
| 文本处理 | 🔤 | 拼接、截取、替换、正则、转数字… |

**⑥ 系统（灰）—— 操作系统资源：窗口、进程、文件、命令**

| 节点 | 图标 | 说明 |
|---|---|---|
| 窗口 | 🪟 | 查找 / 激活 / 最小化 / 移动 / 取信息 |
| 进程 | ⚙ | 启动 / 关闭 / 是否在运行 / 取信息 |
| 文件 | 📁 | 读 / 写 / 复制 / 移动 / 删除 / 存在性 |
| 命令 | ⌘ | 执行 CMD / PowerShell / Bash 命令并取回输出 |

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

- **全局快捷键统一管理**：启动/停止、键鼠录制、坐标拾取三条**都能改键、都能单独停用**，默认依次是 `alt+F1` / `alt+F2` / `alt+F3`（入口：顶栏 **⚙ 设定 → 快捷键**）
- **实时日志**：WebSocket 推送，带**毫秒级时间戳**
- **循环执行**：整图按轮次循环
- **悬浮框**：可开关的置顶小窗，显示循环进度与当前节点，并内置 **启动/停止、暂停/继续、录制、循环次数（± 与直接输入）**，以及右上角的**回到界面图标**（桌面模式下把**应用主窗口**恢复并切到前台，最小化状态也能唤回；见 [10.10](#1010-悬浮框)）
- **暂停 / 继续**：界面与悬浮框都有。暂停只让流程停在**下一个检查点**，继续后从原地接着跑（不是重新开始）；暂停期间延时不再流逝，进度显示为 `⏸ 已暂停 · 第 n/m 轮`
- **急停**：界面按钮 / 快捷键 / 引擎侧停止。**停止始终由引擎执行**，不受两边状态显示影响；长延时也会在 250ms 内被打断
- **运行状态自愈**：前端每秒以 `/run/state` 为准校正按钮，引擎侧另有 1 秒看门狗把真实状态推给悬浮框，两边不会再出现"一个显示运行中、一个显示已停止"
- **单步容错**：单个节点失败只记日志，不中断整个流程（挂机更稳）
- **单实例保护**：重复启动会被拦截并把已有窗口提到前台；编辑器页面也只允许**一个**连接，多开的那个会被以 **4409** 拒绝（桌面壳本身也只有一个窗口，见 [10.19](#1019-为什么只允许一个编辑器页面)）
- **引擎生命周期由桌面壳负责**：桌面模式下引擎**不会因为「页面没了」而退出** —— 刷新页面、WebView 崩溃、改窗口大小都由壳兜着，**关窗即结束引擎与悬浮框**。前端在桌面模式也不再发告别信号（不会误退出）；`AUTOTOOL_EXIT_ON_PAGE_LOSS=1` 仅对源码/浏览器方式运行有效（见 [10.14](#1014-页面离开时后端怎么办)）
- **录制可拆分**：录完的「键鼠录制」节点，点**顶栏常驻**的 **✂ 拆分录制**（或选中该节点后在右侧属性面板点 **✂ 拆分为可编辑节点**），自动变成 点击 / 按键 / 延时 / 滚轮 等独立节点，可单独改坐标、改键、调顺序
- **节点可打包**：反向操作。**左键拖拽框选**（或 `Ctrl`+点击）选中一串**相邻**节点，点顶栏 **📦 打包合并**，合并回一个「键鼠录制」节点
- **拆分后自动排版**：按编辑区大小铺成蛇形网格（不是一列排到底），相邻节点首尾相接、连线不交叉；会被压到的原有节点整体让位
- **多脚本编辑器（浏览器式标签页）**：可以**同时打开多个脚本**，每个标签页是一个独立的编辑器实例 —— 各自保留画布、选中状态与撤销历史。标签上有未保存标记（小圆点）与类型图标（📄 主脚本 / 📦 子脚本），关闭有未保存改动的标签会先确认（见 [10.20](#1020-多标签编辑器与跨编辑器搬流程)）
- **跨编辑器搬流程**：在画布上框选一批节点 → `Ctrl+C`（或 `Ctrl+X`）→ 切到另一个标签 → `Ctrl+V`，整段流程带内部连线一起粘过去，位置自动落在鼠标处（见 [10.20](#1020-多标签编辑器与跨编辑器搬流程)）
- **子脚本（脚本嵌套）**：节点里可以放一个「📦 调用脚本」，指向本脚本文件内部的一个**子脚本**。子脚本在**新标签页**里编辑，可以**新建空白**、也可以**从文件导入已有脚本**；运行时被**就地展开**，效果与「打包合并」基本一致，区别是子脚本能单独编辑、单独导出、被多个节点复用（见 [10.21](#1021-子脚本嵌套与防递归)）
- **防递归三道防线**：编辑时拦截（选到会成环的组合直接拒绝并给出完整调用链）、运行前整图校验（有环 / 脚本缺失 / 嵌套过深都拒绝执行）、运行时调用栈 + 层数上限。三处的报错都是中文，且带完整链路（例如 `打怪 → 回城 → 打怪`）
- **工具栏「删除」**：一键删除**所有选中**的流程（批量框选后按一下，或直接按 `Delete` / `Backspace`）
- **设置面板重做**：改成**左侧分组导航 + 右侧卡片式设置行**（通用 / 外观 / 快捷键 / 数据与安全 / 关于），找设置不用再往下翻；**「关于」从顶栏移入设置**（版本、运行形态、连接状态、项目主页与发布页）
- **顶栏「关于」已移入设置**：顶栏不再有 `关于` 按钮；当前引擎版本、GitHub 发布页入口在 **⚙ 设定 → 关于** 里，点一下用**系统默认浏览器**打开（不会影响当前窗口与连接）
- **打开即进编辑器**：不再需要先点「新建脚本 / 编辑脚本」；**新建 / 加载 / 保存**集中在顶栏**最左侧**，**悬浮框 / 运行**在最右侧，快捷键与外观挪进 **⚙ 设定**
- **外观：浅色 / 深色 / 跟随系统**：顶栏 **⚙ 设定 → 通用 → 界面主题** 里切换，**默认跟随系统**；偏好只存本机浏览器（见 [10.18](#1018-外观浅色--深色--跟随系统)）
- **自定义背景**：顶栏 **⚙ 设定 → 外观** 里选一张本地图片 → 按屏幕比例**截取** → 可调**透明度**（见 [10.17](#1017-自定义背景选图--按屏幕比例截取--透明度)）

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
| 桌面壳 | **Tauri 2**（Rust + WebView2） | 当前形态（桌面版 v0.1.0 起）：原生窗口显示编辑器，Python 引擎作为 sidecar/资源随包分发 |
| 当前发行方式 | **PyInstaller `--onedir`**（引擎）+ **Tauri NSIS 安装包**（桌面版 v0.1.0 起） | 引擎产出 `AutoTool-app\`（exe + `_internal\`），由 `build_desktop.ps1` 串起壳与安装包。<br>选文件夹形态是为了**不依赖系统临时目录**：onefile 每次启动都要往 `%TEMP%` 解压，`%TEMP%` 一旦不可用就会弹 `could not create temporary directory` 而起不来 |
| 安装包 | **NSIS**（由 Tauri bundler 内置下载与调用） | 生成带向导、快捷方式、卸载器的 `AutoTool-Setup.exe`；不再依赖手工维护的 `.nsi` 与 `build_installer.ps1` |
| 桌面壳工程 | `frontend/src-tauri/` | `tauri.conf.json` 里 `bundle.targets=["nsis"]`、`installMode="currentUser"`，并把 `../../AutoTool-app/` 作为 `resources` 打进安装包的 `engine/` |
| 图标生成 | **Pillow 12** | `tools/make_icon.py` 生成多尺寸 `.ico` 与 favicon |

### 3.4 关键依赖版本（实测）

```
fastapi 0.141.1      uvicorn 0.52.4      opencv-python 5.0.0.93
numpy 2.5.3          mss 10.2.0          pynput 1.8.2
rapidocr-onnxruntime 1.2.3   onnxruntime 1.29.0
pyinstaller 6.22.2   vue 3.5.42          naive-ui 2.45.3
pillow 12.3.0        pnpm 11.4.0         tauri-cli 2.x
```

---

## 4. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│              AutoTool.exe + _internal\（文件夹形态）        │
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
AutoTool/
├─ AutoTool-Setup.exe     # 安装包（Tauri bundler → NSIS 产物，不入库）
├─ README.md
├─ build_desktop.ps1          # ★ 一键出安装包：前端 → 引擎 onedir → Tauri 壳 → NSIS
├─ build_exe.ps1              # 只打引擎：前端构建 + PyInstaller（--onedir）→ AutoTool-app\
├─ run_engine.ps1             # 开发：只启动引擎
├─ run_frontend.ps1           # 开发：只启动前端
│
├─ AutoTool-app/          # 引擎产物（PyInstaller onedir，不入库）
│  ├─ AutoTool.exe        #   引擎主程序（约 8.4 MB）
│  └─ _internal/              #   运行库（Python、OpenCV、Tk 等，约 190 MB）
│
├─ assets/
│  ├─ AutoTool.ico        # 应用图标（多尺寸 16~256，exe / 安装包 / 快捷方式共用）
│  └─ AutoTool.png        # 512px 主图
│
├─ tools/
│  ├─ make_icon.py            # 用 Pillow 生成图标（同时输出前端 favicon 与 Tauri 图标）
│  ├─ to-utf8-bom.ps1         # 把 .ps1 统一转为 UTF-8 with BOM
│  ├─ check_ui_imports.mjs    # 静态检查：.vue 里用到的 <n-xxx> 是否都 import 了（构建期自动跑）
│  ├─ test_scriptgraph.py     # ★ 脚本调用图的环检测断言（33 项，纯 Python 图论）
│  ├─ test_executor_scripts.py # ★ 子脚本执行 / 防递归断言（47 项，桩模块驱动 Executor.run）
│  ├─ test_ui_editor.ps1      # ★ 编辑器界面回归入口（起引擎 + 无头 Chrome，跑下面的 mjs）
│  └─ ui-editor-checks.mjs    # ★ 界面结构断言（22 项，纯页面内事件，不用真实鼠标）
│
├─ frontend/                  # Vue 3 前端 + Tauri 2 桌面壳
│  ├─ package.json
│  ├─ pnpm-workspace.yaml     # pnpm v11 配置（allowBuilds 等）
│  ├─ vite.config.ts
│  ├─ index.html
│  ├─ public/favicon.ico
│  ├─ src/
│  │  ├─ main.ts              # 入口
│  │  ├─ App.vue              # 全局 Provider（主题/中文 locale）+ 布局
│  │  ├─ style.css            # 外观 token（深色默认 + 浅色覆盖）/ 全局样式
│  │  ├─ types.ts             # 节点 / 流程 / 子脚本 / 日志类型
│  │  ├─ router/index.ts      # 路由
│  │  ├─ api/client.ts        # 引擎 HTTP 客户端
│  │  ├─ lib/macroSplit.ts    # ★ 录制拆分：把录制事件编译成可编辑节点（纯函数）
│  │  ├─ lib/bgCrop.ts        # ★ 自定义背景的截取几何（纯函数，界面与导出共用）
│  │  ├─ lib/appearance.ts    # ★ 外观三态（浅色/深色/跟随系统）判定（纯函数）
│  │  ├─ lib/scriptGraph.ts   # ★ 脚本调用图：环检测 / 可达性（前端防线 1，纯函数）
│  │  ├─ lib/clipFragment.ts  # ★ 跨编辑器剪贴板片段（相对坐标，纯函数）
│  │  ├─ stores/docs.ts       # Pinia：多文档（标签页 + 文档数据 + 子脚本索引）
│  │  ├─ stores/engine.ts     # Pinia：引擎连接与全应用状态（WS/版本/悬浮框/模板/窗口）
│  │  ├─ stores/project.ts    # Pinia：运行状态与日志（全应用一份）
│  │  ├─ stores/clipboard.ts  # Pinia：应用内部剪贴板（不用系统剪贴板）
│  │  ├─ stores/ui.ts         # Pinia：界面外观 + 自定义背景（存 localStorage）
│  │  ├─ views/
│  │  │  ├─ Editor.vue        # 标签外壳（标签条 / 共享日志 / 设定 / 断连遮罩）
│  │  │  └─ EditorPane.vue    # ★ 单个文档编辑器（一个标签一份实例）
│  │  └─ components/
│  │     ├─ StepNode.vue      # 自定义流程节点（判断节点双出口 / 调用脚本节点）
│  │     ├─ ScreenCapture.vue # 截图框选 / 单点拾取
│  │     ├─ ScriptPickerModal.vue # 子脚本选择器（选已有 / 新建 / 从文件导入）
│  │     └─ SettingsModal.vue # 设定面板（左侧分组导航 + 右侧卡片式设置行）
│  └─ src-tauri/              # 桌面壳（Rust）
│     ├─ tauri.conf.json      #   Tauri 2 配置：NSIS 目标、把 AutoTool-app\ 作为 resources 打进 engine/
│     ├─ Cargo.toml           #   壳版本号（与 package.json / tauri.conf.json / engine/main.py 同步）
│     ├─ build.rs
│     └─ src/lib.rs           #   ★ 壳逻辑：拉引擎 → 等 /health 就绪 → 开窗（失败退回浏览器并写 shell.log）
│
└─ engine/                    # Python 引擎
   ├─ requirements.txt        #   直接依赖（6 项、不锁版本）
   ├─ requirements.lock.txt   #   ★ 完整锁定快照（39 个包带版本号）—— 重建 venv 请用这个
   ├─ main.py                 # FastAPI 入口（25 个端点 + WebSocket）
   ├─ executor.py             # 图执行器（分支/单次/终止/宏回放/子脚本就地展开）
   ├─ scriptgraph.py          # ★ 脚本调用图：缺失/成环/嵌套过深校验（引擎防线 2，纯函数）
   ├─ vision.py               # 截图 + 模板匹配 + 模板管理
   ├─ inputctl.py             # 真实输入 + 模拟输入（PostMessage）
   ├─ window.py               # 窗口枚举 / 截图 / 快速截图
   ├─ keybus.py               # ★ 全局键盘事件总线（唯一钩子）
   ├─ mousebus.py             # ★ 全局鼠标事件总线（唯一钩子）
   ├─ hotkey.py               # ★ 全局快捷键注册表（全部可改键 + 启用开关）
   ├─ picker.py               # 坐标拾取（快捷键由 hotkey.py 统一匹配）
   ├─ recorder.py             # 键鼠录制（快捷键由 hotkey.py 统一匹配）
   ├─ overlay.py              # ★ 悬浮框（tkinter 置顶小窗，显示循环进度与当前节点）
   ├─ appconfig.py            # 用户配置读写（%APPDATA%\AutoTool\config.json）
   ├─ enginelog.py            # ★ 运行日志落盘（轮转 + 令牌掩码 + 接管 stdout/stderr）
   └─ ws_manager.py           # WebSocket 广播（含「日志同时落盘」的钩子）
```

> 运行时用户数据（模板、配置）位于 `%APPDATA%\AutoTool\`。

---

## 6. 快速开始

### 6.1 发行版（推荐）

**方式 A：安装包**

1. 双击 `AutoTool-Setup.exe`，按向导安装（默认安装到 `%LOCALAPPDATA%\AutoTool`）
2. 从开始菜单或桌面快捷方式启动
3. 壳会先拉起引擎、等 `/health` 就绪，然后**在原生窗口里打开编辑器**（不再需要浏览器；建窗失败时会退回系统默认浏览器并把原因写进 `shell.log`，见 [11](#11-常见问题与排错)）

**方式 B：免安装（绿色）**

下载 `AutoTool_0.1.3_portable_x64.zip`，解压出 `AutoTool\` 目录后双击里面的 `AutoTool\autotool.exe` 即可（建议解压路径不含中文）。目录内容就是 `autotool.exe`（桌面壳）+ `engine\`（Python 引擎）—— **不写注册表、不建快捷方式，删掉目录即卸载**。配置与模板同样写入 `%APPDATA%\AutoTool`。

> 也可以自己动手做绿色版：把安装目录里的 `autotool.exe` 与 `engine\` 一起拷到任意位置，双击壳即可。

> 🔸 **只能运行一个实例**。重复启动会提示"程序已在运行"并退出——这是为了避免多开导致键盘钩子冲突。

### 6.2 开发环境

**前置要求**：Windows 10/11、Node.js 18+ 与 pnpm、Python 3.11+（本项目用 3.13）

```powershell
# 0) 首次（可选）：生成应用图标；打包时也会自动补齐
engine\.venv\Scripts\python tools\make_icon.py

# 1) 引擎
cd engine
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt   # 完整快照（推荐）
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
> 开发模式需先设 `$env:AUTOTOOL_DEV='1'` 再启动引擎（放行 1420 端口 CORS 并跳过令牌校验），否则 vite 页面调引擎会 401。
> 若 pnpm 因依赖状态检查中止（`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`），见 [9.4 关于 pnpm 11](#94-关于-pnpm-11)。

---

## 7. 使用指南

### 7.1 快捷键

三条全局快捷键**都能改键、都能单独停用**（入口：顶栏 **⚙ 设定 → 全局快捷键** → 点键位显示区 → 按下想要的组合键 → 保存）：

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
> 改键结果写在 `%APPDATA%\AutoTool\config.json` 的 `hotkeys` 里，升级/重装都保留。

> 撤销/重做只在画布上生效；光标在输入框里时 `Ctrl+Z` 交给浏览器做文本撤销。

### 7.2 输入模式

| 模式 | 原理 | 占用物理键鼠 | 备注 |
|---|---|---|---|
| **键鼠输入** | pynput 真实输入 | ✅ 占用 | 最兼容，需要游戏在前台 |
| **模拟输入** | `PostMessage` 向目标窗口发消息 | ❌ 不占用 | 需绑定窗口；仅对"消息循环型"程序有效 |

> 选择「模拟输入」时必须**先在顶栏绑定目标窗口**，否则自动回退为键鼠输入。

### 7.3 模板管理

在「图像识别」或「判断」节点中：

1. 点「截取」→ 弹窗内**选择窗口**（可切换目标，含刷新）→ 框选区域 → 保存
2. 选中模板后下方显示**预览图**，可**重命名 / 删除**
3. 重命名会**同步更新所有引用该模板的节点**

### 7.4 工程文件格式（`.agflow`）

```jsonc
{
  "format": "agflow",
  "version": 3,                       // 1 = 初版 / 2 = 带子脚本 / 3 = 带变量 + 输入方式下移到节点（0.1.4）
  "name": "刷副本脚本",
  "repeat": 10,                       // 循环轮数
  "variables": [                      // 【0.1.4】全局变量；子脚本 / 组合节点各有一份自己的局部 variables
    { "name": "次数", "type": "number", "value": "7" }
  ],
  "window": { "hwnd": 123456, "title": "造梦西游4",
              "rect": { "left": 100, "top": 60, "right": 1380, "bottom": 840,
                        "width": 1280, "height": 780 } },  // 保存时窗口位置尺寸（分辨率自适应用）
  "screen": { "width": 2560, "height": 1440 },  // 保存时主屏物理分辨率（跨分辨率运行按比例换算坐标）
  "nodes": [
    { "id": "n1", "type": "mouse",
      "params": { "action": "click", "x": 900, "y": 500, "button": "left", "clicks": 1,
                  "input_mode": "real" },   // 【0.1.4】输入方式挂在**每个输入节点**上，不再有流程级单选
      "once": false },
    { "id": "n2", "type": "find_image",
      "params": { "template": "任务", "threshold": 0.85, "timeout_ms": 5000, "on_timeout": "skip" } },
    { "id": "n3", "type": "judge",
      "params": { "logic": "and", "condition": { "left": "found", "op": "==", "right": "yes" } } },
    { "id": "n4", "type": "record",
      "params": { "speed": 1, "repeat": 1, "input_mode": "real",
                  "events": [               // 一段录制的键鼠动作，用「✂ 拆分节点」可摊成普通节点
                    { "t": 0,  "type": "mousedown", "x": 900, "y": 500, "button": "left" },
                    { "t": 60, "type": "mouseup",   "x": 900, "y": 500, "button": "left" }
                  ] } },
    { "id": "n5", "type": "terminate", "params": {} },
    { "id": "n6", "type": "group",       // 【0.1.4】组合节点：把一段流程**原样**装进一个容器
      "params": { "name": "我的组合",
                  "variables": [ { "name": "inner1", "type": "auto", "value": "x" } ],  // 局部变量
                  "nodes": [ /* 内部节点；坐标是相对组合节点的 */ ],
                  "edges": [ /* 内部连线 */ ] },
      "once": false }
  ],
  "edges": [
    { "id": "e1", "source": "n1", "target": "n2", "sourceHandle": null },
    { "id": "e2", "source": "n2", "target": "n3", "sourceHandle": null },
    { "id": "e3", "source": "n3", "target": "n4", "sourceHandle": "yes" },
    { "id": "e4", "source": "n3", "target": "n5", "sourceHandle": "no" }
  ],
  "scripts": {                         // 【0.1.2】子脚本（脚本 id → 自己的 nodes / edges / variables）
    "sub_1": { "name": "拾取", "nodes": [ /* … */ ], "edges": [ /* … */ ], "variables": [] }
  }
}
```

> 判断节点的两条出边用 `sourceHandle` 区分：`"yes"`（成功）/ `"no"`（失败）。
> `screen` 与 `window.rect` 由编辑器自动写入（旧版文件没有也能正常运行，只是不做分辨率换算）。
> **加载脚本默认全局绑定**——不恢复文件里保存的窗口（旧 hwnd 多半已失效），需要绑定时在顶栏手动选择。
>
> **版本号与向后兼容**：0.1.4 写 `version: 3`；更早的文件（`1` / `2`，或干脆没有 `version`）打开时会被
> **就地升级**——补上 `variables`、把流程级的 `input_mode` 下移到各输入节点、旧节点名按 0.1.3 的对应表改写。
> 升级是**幂等**的，且不会丢掉用户填过的任何参数。
> **保存的永远是整份根脚本**（0.1.4 起）：即便当前停在某个子脚本 / 组合节点标签上，保存也会把
> 根脚本的 `nodes` / `edges` / `variables` 与所有子脚本一起写出去，不会只写当前这一层。

---

## 8. 引擎 API 参考

引擎默认监听 `http://127.0.0.1:8765`（开发文档 `/docs`）。
**除 `/health` 与静态资源外所有接口需要令牌**（`Authorization: Bearer <token>` 或 `?token=`），见 [10.8](#108-本地访问令牌)。

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
| `run_request` | `{ts}` | 引擎已判定「应当启动」，前端用画布上最新的流程调 `/run`。**停止不会走这条**——引擎侧直接执行（见 [10.13](#1013-启停状态为什么不会再分叉)） |
| `hotkey` | `{ts}` | 旧版引擎的启停广播，仅为兼容保留；新版前端收到后仍按老逻辑 toggle |
| `picked` | `{x, y}` | 坐标拾取结果 |
| `recording` | `{recording: bool}` | 录制状态 |
| `recorded` | `{events: [...]}` | 录制完成的事件列表 |
| `busy` | `{ts}` | 已有另一个编辑器窗口在运行，本页即将被拒绝（随后以 **4409** 关闭，见 [10.19](#1019-为什么只允许一个编辑器页面)） |

---

## 9. 打包与发布

> **形态变更（桌面版 v0.1.0）**：本项目已从「浏览器 WebUI」迁移为 **Tauri 2 桌面版 + Python sidecar**：
> 界面在原生窗口里显示，引擎仍以本地 HTTP/WS 提供服务（`127.0.0.1:8765`），
> 用户数据目录与脚本格式完全不变（`%APPDATA%\AutoTool`、`.agflow`、图像识别模板按 id 引用）。
>
> - 开发：`pnpm tauri dev`（壳会用 venv 里的解释器拉起引擎源码，并开 DEV 模式免令牌 + 放行 vite 的 CORS）
> - 构建：`.\build_desktop.ps1`（前端 → 引擎 onedir → `tauri build` → NSIS 安装包）
> - **随迁移下线的东西**：WebUI 期的独立安装器（`build_installer.ps1` + `installer\AutoTool.nsi`）、便携版（`dist-desktop\` 与 `-便携版.zip`）、NSIS 工具链副本 `tools\nsis\`，以及 WebUI 期的回归测试脚本（`tools\test_*.py/ps1/js`、`smoke_test.ps1` 等）。
>   安装包改由 Tauri bundler 内置的 NSIS 产出；需要老脚本时仍可从 git 历史取回。
>   下面 9.3 起的若干小节为迁移前的历史说明，保留供查阅，不再对应仓库里的文件。

### 9.1 打包发行版（文件夹形态）

```powershell
# 一键（推荐）：类型检查 + 前端构建 + PyInstaller 打包 + 复制到 AutoTool-app\
.\build_exe.ps1
```

脚本做四件事：

1. `vue-tsc --noEmit` 类型检查
2. **`tools\check_ui_imports.mjs` 静态检查**：`.vue` 里用到的 `<n-xxx>` 是否都在该文件里 import 了
3. `vite build` 产出 `frontend\dist`
4. 用 `python -m PyInstaller`（**不是** `engine\.venv\Scripts\pyinstaller.exe`，原因见 `AGENTS.local.md` 第六节）打成**文件夹形态**（带应用图标），并整体复制到 `AutoTool-app\`

> 第 2 步为什么必须有（真实事故）：Naive UI 是按需 import 的，没有全局注册。如果某个 `<n-xxx>` 忘了 import，Vue 会把它当未知元素渲染，**具名插槽里的内容被整个丢掉**——那个按钮在界面上根本不存在。而 `vue-tsc` 只查类型、`vite build` 只做打包，**两者都不报错**，功能就这么无声无息地消失了（当时是 `NPopconfirm` 漏了，顶栏「＋ 新建」和属性面板的「✂ 拆分为可编辑节点」都不显示）。现在构建期会直接失败并指出缺哪个组件。

等价的 PyInstaller 命令：

```powershell
cd engine
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --noconsole --name AutoTool `
  --icon ..\assets\AutoTool.ico `
  --add-data "..\frontend\dist;frontend_dist" `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on `
  main.py
```

产物：`engine\dist\AutoTool\` → 复制为 `AutoTool-app\`（exe 8.4 MB + `_internal\`，整目录约 199 MB）

**打包要点**

- 前端 `dist` 通过 `--add-data` 打进 `frontend_dist`，运行时由引擎同源提供
- opencv / onnxruntime 等含动态库的包建议加 `--collect-all`
- **用 `--onedir` 而不是 `--onefile`**：单文件版每次启动都要往 `%TEMP%` 解压 `_MEIxxxx`，而 `%TEMP%` 可能不可用（被清理掉、或从 SmartScreen 点「仍要运行」拉起时环境异常），此时 Windows 的 `GetTempPath` 会退回「当前目录」（往往是 `C:\Windows\System32`）→ 弹 `could not create temporary directory` 起不来。文件夹形态没有解压这一步，启动也更快
- 分发时必须**整个目录一起给**（不能只复制 exe）；安装包已处理好
- 图标取自 `assets\AutoTool.ico`，缺失时脚本会先调用 `tools\make_icon.py` 生成

### 9.2 制作安装包（Tauri bundler + NSIS）

```powershell
# 一键（推荐）：前端 → 引擎 onedir → Tauri 壳 → NSIS 安装包
.\build_desktop.ps1

# 引擎产物已存在（AutoTool-app\AutoTool.exe）时，只重建壳与安装包
.\build_desktop.ps1 -SkipEngine
```

产物：`AutoTool-Setup.exe`（由 `tauri build` 输出到 `<CARGO_TARGET_DIR>\release\bundle\nsis\`，根目录那份是分发副本）

`build_desktop.ps1` 的行为：

1. `pnpm build` 构建前端（`vue-tsc` 类型检查 + `check_ui_imports.mjs` + `vite build`）
2. 引擎打成 onedir → `AutoTool-app\`（等价于单独跑 `.\build_exe.ps1`；`-SkipEngine` 用于跳过这一步）
3. `pnpm tauri build`：编译壳，把 `AutoTool-app\` 作为 `resources` 打进安装包的 `engine\`，最后调用 Tauri 内置的 NSIS 产出安装包
4. 打印壳与安装包的路径、体积与 SHA256

安装包行为全部由 `frontend\src-tauri\tauri.conf.json` 的 `bundle` 段决定（`targets: ["nsis"]`、`installMode: "currentUser"`）。

**安装包行为**

| 项 | 说明 |
|---|---|
| 安装目录 | `%LOCALAPPDATA%\AutoTool`（当前用户，**不触发 UAC**） |
| 快捷方式 | 开始菜单 + 桌面（安装向导里可选） |
| 卸载入口 | 设置 → 应用 → 已安装的应用（注册标准 `Uninstall` 键） |
| 用户数据 | `%APPDATA%\AutoTool`（模板 / 配置 / 运行日志，**卸载不动**） |
| 版本升级 | 直接覆盖安装；卸载项里的 `DisplayVersion` 取自 `tauri.conf.json` 的 `version` |
| 静默安装 | `AutoTool-Setup.exe /S`（`/D=路径` 可指定目录，须置于最后且不加引号） |
| 静默卸载 | `"%LOCALAPPDATA%\AutoTool\Uninstall.exe" /S` |
| 免安装绿色版 | Release 附带 `AutoTool_0.1.3_portable_x64.zip`；也可直接把安装目录里的 `autotool.exe` 与 `engine\` 一起拷到任意位置，双击壳即可，数据同样写入 `%APPDATA%\AutoTool` |
| WebView2 运行时 | 安装包**内嵌引导程序**（`embedBootstrapper`）：目标机器缺 WebView2 时安装器自行补齐，不需要安装期单独下载 |

> **关于体积**（0.1.2 实测）：`AutoTool-app\` 整目录约 199 MB（1084 个文件），其中大量未压缩的 DLL 会由 NSIS 以 LZMA 压掉大部分，安装包 **55.02 MiB**（57,690,093 字节，SHA256 `1E81B491…8341`）；绿色版 zip 为 **79.41 MiB**（83,266,271 字节，SHA256 `5DFC5822…3E625`）。0.1.1 对应为 55.23 MiB / 73.25 MiB。
>
> 安装包比 0.1.0 大约 1.7 MB，是**内嵌 WebView2 引导程序**（`webviewInstallMode: embedBootstrapper`）带来的 —— 换掉默认的 `downloadBootstrapper` 后，目标机器缺 WebView2 时安装器不必先联网单独去下载一个引导程序。

> 安装前建议先退出正在运行的 AutoTool（覆盖安装时旧进程会占用主程序文件）。

### 9.3 源码编码约定（重要）

项目里的 `.ps1`（`build_exe.ps1`、`build_desktop.ps1`、`run_engine.ps1`、`run_frontend.ps1`、`tools\to-utf8-bom.ps1`）内含中文，**必须保存为「UTF-8 with BOM」**：

- Windows PowerShell 5.1 对无 BOM 的 UTF-8 文件会按系统 ANSI 代码页解码，中文变乱码并抛出「字符串缺少终止符」之类的语法错误

改完脚本后跑一次即可修正：

```powershell
.\tools\to-utf8-bom.ps1            # 修复所有 .ps1
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
.\tools\smoke_test.ps1 -ExePath "$env:LOCALAPPDATA\AutoTool\AutoTool.exe"  # 测安装后的 exe
```

> 安装目录以注册表 `HKCU\Software\AutoTool\InstallDir` 为准：安装脚本里有 `InstallDirRegKey`，**装过一次之后就会沿用那个目录**（比如你当初装到了 `E:\Apps\AutoTool`，升级不会把它搬回 `%LOCALAPPDATA%`）。`.\tools\test_installer.ps1` 也是按这个规则解析安装位置的。

脚本会启动 exe，逐项校验 `/health`、`/debug/kb`（键盘钩子是否存活）、`/windows/list`、`/vision/templates`、`/config/hotkey`、`POST /flow/load` 以及内嵌前端页面与 favicon，最后关闭进程并输出 PASS/FAIL（有失败项时返回 1，可直接用于 CI）。

它顺带处理了两个常见的"假失败"：

- 把 `TEMP` / `TMP` 指向一个**可写的解压目录**（优先系统临时目录，不可写时才退到 exe 同级的 `.smoketmp`，并在结束时清理）——`--onefile` 需要一个可写的解压目录，受限环境下会报 `Failed to extract VCRUNTIME140.dll: ... Permission denied` 并秒退
- 设置 `AUTOTOOL_NO_BROWSER=1`，避免测试期间弹出浏览器

### 9.6 录制拆分与打包算法回归测试

> ⚠️ **本节脚本已随 0.1.0 的 WebUI 期清理下线**（见 [14. 更新日志](#14-更新日志)）：下面命令不再可直接运行，断言清单保留供重建时参考。

```powershell
.\tools\test_macro_split.ps1
```

`macroSplit.ts` 是不依赖 Vue 的纯函数，所以能脱离浏览器直接跑断言：脚本用前端自带的 `tsc` 把它编成 CommonJS，再由 node 执行 **52 条断言**，结束后清掉中间产物。覆盖：

- **拆分**：轨迹丢弃、左右键坐标、组合键合并、`ctrl` 连配两键、延时插入、空输入
- **打包**：点击/按键/延时/嵌套录制、双击、不可打包类型整体拒绝
- **往返等价**：`打包 → 再拆分` 后节点序列、坐标、组合键、延时长度都不变
- **网格排版**：12 步铺成 3 列 × 4 行、相邻节点必定只差一个行距或列距（无长对角线）、位置不重叠、小批量仍是单列
- **链序判定**：隔着没选的节点 / 成环 / 有分支 / 两条独立链 都应被拒绝

### 9.7 引擎行为回归测试

> ⚠️ **本节脚本已随 0.1.0 的 WebUI 期清理下线**（见 [14. 更新日志](#14-更新日志)）：下面命令不再可直接运行，断言清单保留供重建时参考（`tl;dr`：桌面模式下「页面断连」已不再是退出条件）。

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
- `test_webui_close.py`（17 条）：从未有页面连接过 → 永不退出；**静默掉线 → 不退出**（挂机不中断，`/health` 仍可用、重连可成功）；刷新式重连 → 不退出；**主动告别 → 宽限期后退出**（且 `/goodbye` 无令牌 401）；**流程运行中告别 → 也不退出**；`AUTOTOOL_EXIT_ON_PAGE_LOSS=1` 时才恢复旧行为
- `test_single_page.py`（19 条）：`/config/hotkeys` 默认值 / 改键 / 停用 / 冲突与空键被 400 拒绝；第二个 WebSocket 被 **4409** 拒绝且**不影响已连接的页面**；原窗口关闭后新连接能接管（刷新页面不会被锁死）
- `test_overlay_edit.py`（19 条）：点击数字进入编辑态（`WS_EX_NOACTIVATE` 被临时解除）；点击 / 回车 / 小键盘回车 / Esc / 失焦**都绑了处理函数**；输入框宽度能显示 5 位数字；提交发出 `repeat_set:<n>`、提交后恢复「不抢焦点」；越界夹到 1–99999、非法输入不产生动作；`Esc` 放弃、恢复显示并恢复「不抢焦点」；运行中禁用且点击不进入编辑态；**激活期内（窗口拿不到前台时）的延时判定绝不能抢跑提交**——把前台窗口固定为 0 并手动触发那次判定，断言编辑态与用户已敲进去的内容都不丢

> 端到端脚本会真起一个引擎进程，并把 `APPDATA` 指向项目内 `.tmp\`，因此**不会碰你自己的 `%APPDATA%\AutoTool` 配置**（顺带保证测试期间悬浮框是关的、不弹窗）。它们需要 8765 端口空闲：先退出正在运行的 AutoTool。
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

### 9.10 编辑器界面回归（无头浏览器）

```powershell
.\tools\test_ui_editor.ps1                 # 跑一遍
.\tools\test_ui_editor.ps1 -Refresh        # 改过引擎代码后，强制重铺一份引擎副本
```

模型和 CI 都看不到画面，所以界面改动靠**结构断言**兜底：把一个**无头 Chrome** 连到真实引擎提供的页面上，读 DOM 与计算样式，确认"确实改成了该有的样子、而且没有白屏"。目前 **22 项**，覆盖：

- **打开应用时运行日志默认收起**；点底部「日志」图标能在**画布下方**展开 / 收起原日志框（面板在 `.canvas` 之下、贴在底栏之上，不是浮层）
- **底部控制条**：三个按钮**只有图标**、没有中文文案；设定齿轮字号 > 18px
- 顶栏**不再有**「复制 / 剪切 / 粘贴」；改由**画布右键菜单**唤出 —— 右键节点得到三项、右键空白只有「粘贴」、剪贴板为空时「粘贴」置灰、点「复制」后菜单自动关闭、`Esc` 可关
- **标签拖拽排序**真的生效：三次不同方向的拖动（拖到最前 / 拖到最后 / 插到相邻标签之后）顺序都对

> ⚠️ 断言只用**页面内事件派发**（`el.click()` / `PointerEvent` / `MouseEvent('contextmenu')`），**不做真实鼠标注入**，跑起来不会干扰你正在用的电脑。派发走的是与真实操作**完全相同**的那套处理函数（`pointerdown` on `.tab` → window 上的 `pointermove` / `pointerup` → `docs.moveTab`），所以能证明业务逻辑对不对。

> 脚本会把引擎**先复制到 `%TEMP%\agt-ui-run` 再运行**（本机在 `E:\codes` 下直接执行刚构建的 exe 会被静默拦掉），并把 `frontend\dist` 覆盖进副本的资源目录 —— 因此改完前端只要 `cd frontend; pnpm build` 就能重测，**不必重新打包**。前置：`frontend\dist` 要存在。

### 9.11 安装包端到端验证

```powershell
.\tools\test_installer.ps1                  # 验证完自动卸载
.\tools\test_installer.ps1 -KeepInstalled   # 验证后保留安装
```

脚本按真实用户路径跑一遍完整闭环，共 25 项断言：

1. 静默安装（`/S`）：安装位置为注册表记录的 `InstallDir`（首次安装即 `%LOCALAPPDATA%\AutoTool`）
2. 校验主程序 / README / Uninstall.exe 是否落盘
3. 校验开始菜单 3 个快捷方式与桌面快捷方式
4. 校验注册表：`DisplayName`、`DisplayVersion`（期望值从 `frontend/src-tauri/tauri.conf.json` 的 `version` 读出，不写死）、`UninstallString`、`QuietUninstallString`、`InstallLocation`、`DisplayIcon`、`EstimatedSize`、`App Paths`
5. 对**已安装的 exe** 跑一遍 `smoke_test.ps1`
6. 静默卸载，校验安装目录 / 快捷方式 / 注册表项均已清理，且**用户数据被保留**

> 注意：该脚本会写注册表与「开始菜单 / 桌面」，需要相应权限；它不会删除 `%APPDATA%\AutoTool`（模板与配置）。
>
> 它**会先卸载本机已安装的副本再重装**（安装包自身的行为就是升级前先静默卸载旧版）。只想在已装好的副本上跑冒烟测试、不动安装的话，用 `.\tools\smoke_test.ps1 -ExePath <安装目录>\AutoTool.exe`。

### 9.12 打包产物核验（无控制台 + 日志落盘）

```powershell
.\tools\test_noconsole_log.ps1                    # 默认测 AutoTool-app\AutoTool.exe
.\tools\test_noconsole_log.ps1 -ExePath <路径>     # 测别的副本
```

针对「无控制台窗口 + 日志落盘」两条硬要求，在**打包产物**上核验（10 项检查）：

1. `AutoTool.exe` 是 **GUI 子系统**（PE 头 `Subsystem = 2`），不会分配控制台。同一段检测代码对 `engine\.venv\Scripts\python.exe` 读出 `3`（控制台）作为阳性对照——否则「没看到控制台窗口」可能只是检测本身失效
2. 启动产物后枚举它的**全部顶层窗口**（文件夹形态只有一个进程；若拿到的是旧单文件版，会同时存在「父 bootloader」与「真正跑 Python 的子进程」两个同名进程，两个都查），断言没有任何控制台类窗口（`ConsoleWindowClass` / `CASCADIA_HOSTING_WINDOW_CLASS` 等），并且确实看到了悬浮框的 `TkTopLevel`
3. `%APPDATA%\AutoTool\engine.log` 被创建、含带版本号的启动记录，且日志里的 `token=` 已掩成 `***`、**不含启动时传入的真实令牌**

> 脚本用固定令牌（`AUTOTOOL_TOKEN`）启动产物，才能断言「真令牌没有落盘」；它不注入任何真实鼠标 / 键盘，只在开始时把已有的 `engine.log` 备份到 `.tmp\`。运行前需 8765 端口空闲。

### 9.13 发布 Release

安装包构建完成后，用 GitHub CLI 上传到 Releases：

```powershell
gh release create v0.1.0-desktop .\AutoTool-Setup.exe --title "v0.1.0-desktop —— ..." --notes-file .\notes.md
gh release upload v0.1.0-desktop .\AutoTool-Setup.exe --clobber   # 补传 / 覆盖已有资产
```

约定：

- **版本号必须四处一致**：`engine/main.py`（FastAPI title + `/health`）、`frontend/package.json`、`frontend/src-tauri/tauri.conf.json`（决定安装包文件名与卸载项 `DisplayVersion`）、`frontend/src-tauri/Cargo.toml`（同步 `Cargo.lock` 里 `autotool` 的版本行）
- **Release 说明直接取自本 README 的「更新日志」对应章节**，保持单一事实来源，不在别处另写一份
- `AutoTool.exe` 与 `AutoTool-Setup.exe` **不入库**（见 `.gitignore`），只随 Release 分发；仓库里始终只有源码
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

好处：启动始终使用**前端当前最新流程**，不依赖引擎侧的流程缓存；而「停止」由引擎自己执行，不必先跟前端对齐状态（旧版正是这里出的问题，见 [10.13](#1013-启停状态为什么不会再分叉)）。两种动作都会在日志面板留下明确记录（`全局快捷键：启动脚本` / `停止脚本`），便于确认快捷键到底有没有生效。

> 每次按键都会记录，所以「快捷键疑似无效」可以直接从日志判断：**日志里没有这一行 = 按键没被识别**（检查是否多开、钩子是否被占用）；**有这一行但流程没动 = 后续链路问题**（看紧随其后的报错）。

### 10.7 无人值守启动

引擎启动后默认会自动打开浏览器到 `http://127.0.0.1:8765`。设置环境变量后可以跳过（桌面壳拉起引擎时自带 `AUTOTOOL_NO_BROWSER=1`，所以桌面版不会另外弹浏览器）：

```powershell
$env:AUTOTOOL_NO_BROWSER = '1'
.\AutoTool.exe
```

适用于自动化测试、开机自启、由其他程序拉起的场景；界面上仍可手动访问该地址。

> 注意：**桌面模式下引擎永不自行退出**（窗口由壳持有，关窗由壳收尾）。源码/浏览器方式运行时：**页面静默掉线不再关后端**（挂机安全），只有用户**主动关页面**（前端发告别信号）才会在 5 秒宽限后退出，流程运行中一律不退。详见 [10.14](#1014-页面离开时后端怎么办)。想恢复旧行为设 `AUTOTOOL_EXIT_ON_PAGE_LOSS=1`，想永不退出设 `AUTOTOOL_KEEP_ALIVE_ON_CLOSE=1`。

### 10.8 本地访问令牌

引擎具备操控键鼠、截屏的能力，而浏览器里任何网页都能向 `127.0.0.1` 发请求。为防止恶意网页把引擎当"RPA 后门"：

- **令牌持久化**：首次启动生成随机令牌并保存到 `%APPDATA%\AutoTool\engine.token`，之后每次启动复用同一串——这样「程序已在运行时再启动一次」打开的页面也能连上（旧版每次新生成，那个页面永远 401）
- 自动打开的浏览器地址形如 `http://127.0.0.1:8765/?token=xxx`，前端存 sessionStorage 后自动从地址栏抹除
- 所有 API（`/run`、`/input/*`、`/screen/*`、`/vision/*`、`/goodbye` 等）必须携带 `Authorization: Bearer <token>` 或 `?token=`；WebSocket 同样校验；无令牌一律 401
- 校验 `Host` 头白名单（仅 127.0.0.1/localhost），防 DNS rebinding
- 打包版与前端同源，**默认关闭 CORS**；仅 `AUTOTOOL_DEV=1` 时放行 vite 调试端口并跳过令牌（开发用）

相关环境变量：

| 变量 | 作用 |
|---|---|
| `AUTOTOOL_TOKEN` | 固定令牌（自动化测试用，如 `smoke_test.ps1`），优先级高于落盘的令牌 |
| `AUTOTOOL_DEV` | `=1` 开启开发模式：放行 `localhost:1420` CORS 且跳过令牌校验 |
| `AUTOTOOL_NO_BROWSER` | `=1` 不自动打开浏览器 |
| `AUTOTOOL_KEEP_ALIVE_ON_CLOSE` | `=1` 页面离开时**永不退出**后端（无人值守挂机） |
| `AUTOTOOL_EXIT_ON_PAGE_LOSS` | `=1` 恢复旧行为：静默掉线也在 6 秒后退出 |

> 直接手动访问 `http://127.0.0.1:8765`（不带 token）时页面能打开但 API 全部 401。请使用引擎控制台打印的带 token 地址，或由程序自动打开的页面进入。

### 10.9 多分辨率 / DPI 自适应

换显示器、改分辨率或 DPI 缩放变化后，旧脚本的模板和坐标不再对得上。为此引入参考基准自动适配：

- **识图**：截取模板时记录捕获画面尺寸（存为 `模板名.meta.json`）。匹配时若当前画面尺寸与参考不同（分辨率变了 / 窗口缩放），引擎先把模板按相同比例缩放（0.3x~3x，横纵比一致才启用）再匹配，得分不理想自动回退原尺寸取高分
- **点击 / 宏坐标**：`.agflow` 保存时写入参考主屏分辨率（`screen`）与绑定窗口 rect（`window.rect`）。运行时：绑定窗口优先按「参考 rect → 当前 rect」换算（同时覆盖窗口移动、缩放与分辨率变化）；未绑定按主屏分辨率比例换算
- 引擎本身 `SetProcessDpiAwareness(2)`（每显示器 DPI 感知），截图与点击始终在同一物理像素坐标系

> 注意：加载他机脚本后再用拾取快捷键（默认 `alt+F3`）新拾取的坐标按当前分辨率记录，与文件原有参考系不同——跨机复用时建议重新拾取全部坐标并重新保存（保存会把参考系更新为当前环境）。

### 10.10 悬浮框

挂机时主界面通常被游戏挡住，所以循环到了第几轮、当前卡在哪一步，需要一个**盖在游戏上面**的小窗来显示，并且最好不用切回主界面就能操作。

**为什么由引擎画、而不是网页画**：浏览器无法创建真正置顶于其它程序（尤其独占/无边框游戏）之上的窗口，任何网页内的"悬浮层"都只在自己页面内生效。因此悬浮框由 Python 侧用 `tkinter` 在**独立线程**里创建原生窗口。

**界面**

```
● AutoTool                    ↗▣  ✕
第 2/3 轮
当前：图像识别
[▶ 启动] [⏸ 暂停] [● 录制]    循环 [－][[3]][＋]
                                        ↑ 可直接输入
```

| 按钮 | 行为 |
|---|---|
| **▶ 启动 / ■ 停止** | 与全局快捷键、界面「运行」按钮**完全同一条链路**（见 [10.6](#106-快捷键执行链路)），始终使用画布上最新的流程 |
| **● 录制 / ■ 停录** | 开始/停止键鼠录制；停止后录到的事件照常推给前端并生成一个「键鼠录制」节点 |
| **循环 － / [n] / ＋** | 调整或**直接输入**循环轮数（1–99999），同步到前端并广播给所有页面；**运行中禁用**，改动在下一轮运行生效 |
| **↗▣（右上角图标）** | 把**应用主窗口**恢复并切到前台（最小化状态也能唤回）。**桌面模式**：按**父进程 PID**（`os.getppid()`）枚举顶层窗口找到壳的原生窗口，而不是去猜标题；**源码/浏览器方式运行**：退回按标题匹配真正的浏览器窗口。**只认应用自己的窗口**：同名文件夹的资源管理器、承载后端的终端/控制台窗口都不会被误选，找不到就只记一条提示日志、不乱切窗口 |

**循环次数可直接编辑**：中间那个数字是输入框（不只是 ± ）。点它 → 临时解除 `WS_EX_NOACTIVATE` 并激活窗口（否则窗口拿不到键盘焦点、输入框打不了字）→ 输入数字 → `Enter` 提交、`Esc` 放弃、点别处也会提交；提交后立刻恢复"不抢焦点"。非法输入与越界值会被夹回合法范围（1–99999，输入框宽度按 5 位数字留足）并回显真实值。

右上角的「回到界面」是**矢量图标**而不是文字按钮（更省横向空间，也不再和底部的启停按钮抢注意力）：一个左上角开口的方框 + 指向左上角的箭头 + 右下角实心方块。用 Tk `Canvas` 画线绘制，不引入图片资源、任意 DPI 都清晰；鼠标移上去会变成主题青色作为可点击反馈。

另外：无边框 + 置顶、按住可拖动、点 `✕` 收起并同步回前端开关、开关持久化到 `config.json`。

**两个刻意的设计（都与"窗口最小化"有关）**

1. **点击悬浮框不抢焦点**：窗口带 `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`，点按钮不会夺走前台焦点，也不会出现在 Alt-Tab 里。
2. **置顶只在真的丢失时才写 Z 序**：旧版每 2 秒无条件 `SetWindowPos(HWND_TOPMOST)`，会在别的窗口播放最小化动画时搅动 Z 序，导致**偶发最小化失败**；现在先读扩展样式判断，正常情况是纯读操作。

**线程模型**：引擎主线程跑 uvicorn 事件循环，Tk 必须在自己的线程里 `mainloop`。两者不共享任何 Tk 对象——执行器只往队列投递状态，Tk 线程每 120 ms 消费一次并刷新；按钮回调也只把动作名交回事件循环线程执行。

**可靠性**：`tkinter` 缺失或窗口创建失败时自动降级为「空实现」（`/overlay/state` 的 `available=false`，前端按钮置灰），**绝不影响流程执行**；执行器侧对悬浮框更新也做了兜底捕获。

开关会记录在 `%APPDATA%\AutoTool\config.json` 的 `overlay` 字段，下次启动沿用。

### 10.11 窗口最小化与截图

`capture_window` 旧版会在窗口最小化时**无条件** `ShowWindow(SW_RESTORE)` 把它弹到前台。挂机时用户常常故意最小化游戏/浏览器，于是每个图像识别/判断节点都会把它弹回来，表现为"最小化失败"。

现在改为：

- **流程执行（图像识别 / 判断）**：`restore_minimized=False`，窗口最小化时直接报 `目标窗口已最小化…` 并结束该节点，**不弹窗**
- **用户主动操作（界面「截取」/ 测试匹配）**：显式传 `restore_minimized=True`，照旧把窗口恢复出来，方便取模板

> 提示：多数游戏/浏览器在最小化后会停止渲染，此时截图本来也拿不到有效画面；所以"报错而不弹窗"既保住了你的窗口，也避免了无意义的轮询。

### 10.12 录制模型的拆分与打包

> 拆分让录制不再记鼠标轨迹；顶栏有常驻的拆分入口；打包合并是它的逆操作。

**为什么不再录鼠标轨迹**：早期录制把 `mousemove` 一并记下，一段录制里绝大部分事件是轨迹点。回放时逐点移动光标既慢又脆（受分辨率、帧率、窗口位置影响），而且**没法编辑**——想改一次点击的位置，得在成百上千个轨迹点里找。

现在改为**只记语义事件**：

| 记录 | 不记录 |
|---|---|
| 鼠标按下 / 抬起（含按键与**按下时的坐标**）、滚轮 | `mousemove` 轨迹 |
| 键盘按下 / 抬起（含组合键） | 鼠标移动的中间过程 |

回放时由 **点击节点**把光标直接落到该坐标再按下（`inputctl.mouse_down` → 真实模式 `SetCursorPos` / 模拟模式 `PostMessage`），效果等价而事件数下降一到两个数量级。

**两个入口**：

| 入口 | 位置 | 作用对象 |
|---|---|---|
| **✂ 拆分录制** | **顶栏设置条常驻**（「⏺ 开始录制」右侧） | 当前选中的录制节点；流程里只有一个录制节点时直接生效，无需先选中；有多个且未选中时会提示先选 |
| **✂ 拆分为可编辑节点** | 选中录制节点后，右侧属性面板 | 该录制节点 |

> 为什么要加顶栏入口：早先只有属性面板那一个按钮，而它**只在选中「键鼠录制」节点时才出现**——不在工具栏、也不在左侧节点面板，结果就是"功能明明做了却找不到"。顶栏入口没这个前提：流程里只要有录制节点，按钮就亮着；一个都没有时置灰并提示先录一段。

拆分把一段录制编译成普通节点：

| 录制事件 | 拆分结果 |
|---|---|
| `mousedown` + 紧随同键 `mouseup` | 一个 **鼠标操作**节点（保留按下时的坐标、按键） |
| 连续按键（如先后按下 `ctrl`/`shift`/`a` 再抬起） | 一个 **键盘按键**节点，键名为 `ctrl+shift+a` |
| 连续的 `scroll` | 一个 **键鼠录制**节点（滚轮是逐事件的增量，拆开反而失真，故按原样保留回放） |
| 相邻动作间隔 ≥ 80 ms | 中间插入一个 **延时**节点，保留原有节奏 |
| 孤立 `mouseup`、空输入 | 直接丢弃 |

> 组合键的归属按「本轮第一个抬起」结算：`ctrl` 按住不动、先后配 `a` 再配 `b`，会正确拆成 `ctrl+a` 与 `ctrl+b` 两个节点，而不是误并成 `ctrl+a+b`。

拆分后的节点就是**普通节点**：连线自动重排（原入线接到首节点、原出线接自尾节点），之后可以随便改坐标、换键、插节点、删节点。算法是纯函数（`frontend/src/lib/macroSplit.ts` 的 `compileMacroPieces` / `expandPieces`），不依赖 Vue——原本有个脱离浏览器跑断言的脚本 `tools\test_macro_split.ps1`（见 [9.6](#96-录制拆分与打包算法回归测试)），它随 WebUI 期脚本一并下线，重建时照着那一节的断言清单恢复即可。

#### 拆分后的排版

早先的做法是把所有新节点**沿一列往下排**（`y += 76`）：十几步就拖出去很远，还会盖住下面的节点，后继节点的连线绕回来穿过整块，看起来就是一团。

现在改成**蛇形网格**：

- 行数由**编辑区可见高度**决定（`(高度-40)/78`，限制在 3~14 行），一列排满再向右折
- 列数凑成**奇数**：偶数列自上而下、奇数列自下而上，于是**块内每一条连线都首尾相接**——相邻两步不是同列上下相邻，就是换列时同一行相邻，**不会出现长对角线**
- 会被方块压到的原有节点**整体下移同一个距离**，既让开位置又保持它们彼此的相对排布
- 拆完自动 `fitView()`，整块直接落在视野里

实测：12 步 → `3 列 × 4 行`（原来是一列 12 行）；40 步 → `7 列 × 6 行`；5 步以内仍是一列。这些几何规则都有断言（见 [9.6](#96-录制拆分与打包算法回归测试)）。

#### 打包合并：拆分的逆操作

选中一串**相邻**节点 → 顶栏 **📦 打包合并**，合并回一个「键鼠录制」节点。

| 选中的节点 | 打包成的事件 |
|---|---|
| 鼠标操作 | `mousedown` + `mouseup`（保留坐标与按键；`clicks>1` 按时重复若干下） |
| 键盘按键 | 组合键按顺序按下、**逆序**抬起 |
| 延时 | 时间轴向前推进（不产生事件） |
| 键鼠录制 | 其事件按自身 `speed` 折算成真实时间后**内联**进来（支持多段录制并成一段） |
| 图像识别 / 判断 / 文本输入 / 终止 / 连点器 / 调用脚本 等 | **无法**表达成键鼠事件 → 整体拒绝并说明原因 |

选择方式：在画布上**左键拖拽框选**，或按住 `Ctrl` 逐个点击加选（画布下方有提示；平移画布改用**右键拖拽**）。

几条刻意的取舍：

- **只接受"一条连续链"**：选中集合内必须恰好有一个没有入边的头；成环、有分支（判断节点两条出边）、或者隔着没选的节点（选 A、C 而漏掉 B）都会被拒绝并提示
- **不做部分打包**：只要有一个节点不能打包就整体拒绝，避免悄悄丢掉动作
- **勾了「单次执行」的节点拒绝打包**：录制节点表达不了"仅第一轮"，请先取消勾选
- 拆分是**有损**的——点击节点没有"按时长"字段，按下→抬起之间的间隔被丢弃，所以反向打包统一按 60 ms 约定值补齐。**"拆分→打包"能还原节点序列、坐标、按键与延时长度**；只有"按住多久"这一项是约定值
- `mousemove` 会被丢弃（本来也不再录），所以打包不会把轨迹写回去

> 拆分与打包共用同一套纯函数（`packStepsToMacro` / `orderChain`），往返等价与"非连续选择应被拒绝"都有断言覆盖。

> ⚠️ 拆分与打包都是**就地替换**。现在可以用 **Ctrl+Z 撤销**（顶栏也有 ↶/↷ 按钮），但历史只保留最近 60 步、且拖动/连续输入会合并成一步；跨度较大的改动仍建议先保存一份 `.agflow`。

### 10.13 启停状态为什么不会再分叉

早先的启停链路是这样的：

```
点悬浮框「启动/停止」或按 alt+f1 → 引擎广播 {type:"hotkey"} → 前端按**自己那份** store.running 决定启动还是停止
```

问题在于**方向判断发生在前端**，而前端那份状态是轮询来的、可能慢一拍：

- **悬浮框只在流程起跑和结束时才被更新**（`executor._state()` 的两处调用）。任何绕过这两处的改动——`/run` 里先置位的 `running`、`stop()`/`reconcile()` 的兜底复位——悬浮框都不知道。于是出现"界面显示运行中、悬浮框还显示停止"
- 两边一旦分叉就**再也回不来**：点悬浮框的「停止」，前端按自己那份状态判断成"没在运行 → 该启动"，于是又发一次 `/run`（或被 409 挡掉）。表现就是**反复点停止没反应**
- 按住 `alt` 连按两次 `f1` 时，第二次按下的瞬间 `alt` 还没松开，`HotkeyManager` 的「已触发」锁没复位 → **只触发第一次**

现在的做法改成「引擎是唯一事实来源」：

| 措施 | 解决什么 |
|---|---|
| **停止一律在引擎侧直接执行**，不再广播让前端决定方向 | 方向判断不再依赖前端那份可能过期的状态；启动才交给前端（因为要用画布上最新的流程，消息改成语义明确的 `run_request`） |
| `_sync_run_state()` 统一推送，`/run`、`/run/stop`、`/run/state` 都调用它 | 悬浮框与界面拿到的是同一个值 |
| **1 秒状态看门狗**兜底 | 任何漏掉同步的代码路径都会在 1 秒内被纠正——给悬浮框补上前端早就有的自愈能力 |
| `/run/stop` 等流程**真正收尾**再返回（最多 2 秒） | 前端按钮在"确实已停止"的那一刻翻转，不留"还亮着停止"的窗口 |
| `delay` 节点改为每 250 ms 检查停止标志 | 挂机时单个延时动辄几十秒，旧版整段睡死，点停止要等它走完才生效 |
| 组合键里的**非修饰键**一抬起就解锁 | 按住 `alt` 连按两次 `f1` 能触发两次；长按 `f1`（只有重复 keydown）仍只触发一次 |

> 顺带把「这次动作是谁发起的」写进日志：`悬浮框：停止脚本` / `全局快捷键：启动脚本`。以后再出现"点了没反应"，看一眼日志就能分清是**按键没识别**还是**流程没停**。

### 10.14 页面离开时后端怎么办

关掉界面后后端不该残留，但**「页面不见了」不等于「用户关了页面」**——这个区别正是判定的核心。规则如下：

| 情形 | 行为 |
|---|---|
| **桌面模式**（`AUTOTOOL_DESKTOP=1`，由桌面壳拉起） | **永不因页面消失退出**：刷新、WebView 崩溃、改窗口大小都由壳兜着；**关窗 = 壳结束引擎进程**。前端在此模式下也不再发 `/goodbye`（该请求会直接返回 `{ok, grace:0, ignored:"desktop"}`），避免误触发退出 |
| 页面**主动告别**（关标签页/跳转离开，前端 `pagehide` 时 `sendBeacon` 打 `/goodbye`） | 5 秒宽限后若没有页面重连 → 停止流程并优雅退出（走 lifespan 清理：关悬浮框、注销钩子）。**仅源码/浏览器方式运行** |
| 页面**静默掉线**（浏览器挂起/丢弃后台标签页、崩溃、网络抖动） | **不退出**：后端与悬浮框继续跑，页面回来随时重连 |
| 收到告别但**流程仍在运行** | **不退出**（挂机优先），只记一条日志 |
| 从未有页面连过（`AUTOTOOL_NO_BROWSER=1` 无人值守、冒烟测试） | 永不自动退出 |
| `AUTOTOOL_KEEP_ALIVE_ON_CLOSE=1` | 永远不退出（连告别也不退） |
| `AUTOTOOL_EXIT_ON_PAGE_LOSS=1` | 恢复旧行为：静默掉线也在 6 秒后退出（桌面模式下此开关不生效） |

为什么必须区分（实测事故）：浏览器会把长时间在后台的标签页**挂起甚至丢弃**（Edge 的睡眠标签页）。挂起时 WebSocket 仍由浏览器网络层代答 ping，连接能撑很久；真正被丢弃时 socket 断开，而**页面只有在用户回到浏览器时才会重新加载并重连**——挂机时用户不在，旧的 6 秒宽限期必然不够，于是每次都会「后端与悬浮框一起消失」。日志里那 9 次 `编辑器页面已断开` + `引擎退出：…6 秒内没有重连` 就是这么来的（这也是后来改由桌面壳接管生命周期的原因）。

对应回归测试 `tools\test_webui_close.py`（见 [9.7](#97-引擎行为回归测试)）：静默掉线、刷新式重连、主动告别、运行中告别、旧行为开关，五种时序都有断言。该脚本随 WebUI 期脚本一并下线，断言逻辑保留在此处供重建时参考（桌面模式下"页面断连"已不再是退出条件）。

### 10.15 撤销 / 重做为什么用「快照 + 防抖」

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

### 10.16 暂停的语义与生效位置

「暂停」和「停止」是两件事：停止会结束这次运行（下次从流程开头重跑），暂停只是**冻住**，继续后从原地接着跑。

实现上，暂停是一个协作式标志（`Executor.paused`），只在**检查点**生效，检查点只有两处：

| 检查点 | 为什么放这里 |
|---|---|
| **节点边界**（每个节点开始前） | 这里不存在"做到一半"的状态，恢复后从当前节点继续即可，**不会重复执行已完成的动作** |
| **延时的小睡之间**（每 250ms） | 挂机脚本里单个延时动辄几十秒；暂停期间余下的延时**不再流逝**，恢复后把剩余时间睡完 |

刻意**不**放进图像识别 / 判断的轮询与宏回放里：

- 图像识别/判断的超时是按 `time.time()` 算的。在里面停住会把暂停时长也算进超时，恢复后立刻误判超时——那是个很难查的怪 bug
- 宏回放的时序基准是一次性算好的 `base`，中途停住再恢复会试图"追帧"，把剩余事件一次性倾倒出去

代价是：暂停在**当前节点结束后**才真正停下（图像识别/判断最长等它的超时窗口，宏回放等这一段放完）。这两类节点都是有界的，不像延时那样可以任意长，所以这个取舍是划算的。

状态一致性沿用同一套单一事实来源：`/run/state`、`/overlay/state` 都带 `paused`，`_sync_run_state()` 与 1 秒看门狗保证界面和悬浮框同时看到「已暂停」。边界情况也一并处理了：空闲时 `pause()` 不生效（不会出现"已暂停但空闲"的矛盾状态）、`stop()` 会清掉暂停（否则暂停等待循环会一直挂着）、恢复后 `reconcile()` 不会误清正在跑的暂停。

### 10.17 自定义背景：选图 → 按屏幕比例截取 → 透明度

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

### 10.18 外观：浅色 / 深色 / 跟随系统

入口在 **⚙ 设定 → 外观**，三个选项：**跟随系统（默认）** / 浅色 / 深色。

- **默认跟随系统**，跟的是 Windows 的浅色/深色设置（`prefers-color-scheme`），系统切换时界面**立刻**跟着变（监听 `matchMedia` 的 `change`，不是只在启动时读一次）
- **取不到系统偏好时按深色处理**：深色是 AutoTool 一直以来的外观，宁可维持原样也不要突然刷白
- **显式选择优先于系统**，并且**只存本机浏览器**（`localStorage` 的 `agt.appearance`，默认值不写盘）——与自定义背景同一个理由：这是"这台电脑这个浏览器"的显示偏好，跟脚本内容无关，不该随 `.agflow` 换机变样
- 实现上分两层：**Naive UI 的浅色/深色主题**（组件库自带，见 `App.vue` 的 `n-config-provider`）+ **自己的 CSS token**（`style.css` 里 `:root` 是深色，`:root[data-theme='light']` 只覆盖变量）。组件样式一律只用这些变量，避免出现"浅色下某块还是黑的"这种半吊子主题
- 判定逻辑抽成纯函数 `frontend/src/lib/appearance.ts`，用 `.\tools\test_appearance.ps1` 断言（28 条）；界面层用无头浏览器跑 `.\tools\test_ui_appearance.py`（28 项）
- 同一处还把 Naive 的 `locale` 设成中文：否则**内置文案是英文**的（新建确认框的按钮就是 `Confirm` / `Cancel`），这正是修掉的一个观感问题

### 10.19 为什么只允许一个编辑器页面

后端本来就只有一份（单实例互斥量），但**页面连接**可以开很多个：源码/浏览器方式运行时再点一次、或者手动粘贴地址，都会多出一个连上同一引擎的标签页；桌面版则由壳保证只开一个窗口，正常不会遇到。两个页面同时存在会带来一堆含糊：两边都显示运行状态、各自把流程同步给引擎（互相覆盖）、日志与悬浮框事件重复消费。所以规则是：

- 引擎侧：`/ws` 在**已有页面连接**时先发一条 `{"type":"busy"}`，然后以 **4409** 关闭新连接（`ws_manager.connections` 是唯一判据）
- 前端侧：收到 4409 就显示「已在另一个窗口打开」的提示，并**每 1.5 秒后台重试**一次
- **刷新页面（F5）必须永远能用**：刷新时旧连接会先断开，新页面通常第一次重试就成功；即使抢在旧连接清理之前连上被拒，也会在 1~2 秒内自动接管。这是刻意用"重试"而不是"直接抢断旧页面"换来的——否则刷新会把自己锁在外面。**桌面版尤其依赖这条**：壳重建窗口、WebView 崩溃恢复都表现为"新连接挤掉旧连接"
- 被拒绝的页面**不影响正在工作的那个**：`test_single_page.py` 里专门断言了这一点（拒绝之后原连接仍活着、`/run/state` 仍然可用）

> **注意与「多标签编辑器」的区别**（0.1.2 起）：0.1.2 允许**一个页面内开多个脚本标签**，但**仍然只允许一个页面**。两者不矛盾 ——
> 多标签是"一个编辑器里开多份文档"（浏览器式），而 4409 拦的是"同一个引擎上挂两个页面"。前者是把状态收拢到**一个** `EditorPane` 实例集合里（引擎连接、运行状态、日志、悬浮框、模板列表全应用一份，见 `stores/engine.ts`），后者是两份互不知情的状态在抢同一个引擎。

### 10.20 多标签编辑器与跨编辑器搬流程

**为什么每个标签是一个独立的编辑器实例（而不是共用一个画布换数据）**：脚本可以很大（上千节点），共用画布意味着每次切标签都要把整张图重新塞进 Vue Flow —— 不仅慢，还会丢掉选中态、视口位置与撤销历史。所以 `EditorPane.vue` 每个标签一份实例，用 `v-show`（不是 `v-if`）保留状态，切回来时画布、选中、历史都还在。

**为什么文档数据不进 Pinia 的响应式树**：把上万个节点塞进 `reactive` 会被 Vue 深度代理一遍，光构造代理就是几百毫秒级开销，之后每次读写都要过代理。所以 `stores/docs.ts` 里文档数据放在 `markRaw` 的 `Map` 里，各 pane 自己持有 `ref` 形式的节点与连线，编辑时**镜像**回 store（保存、标签标题、子脚本下拉列表读 store）。

**踩过的坑**：`markRaw` 的数据不参与依赖收集，于是"子脚本列表"这类需要跟着增删改刷新的东西会**看起来不更新**。解决办法是把索引单独做成响应式的（`docs.scriptIndex`），需要联动的地方显式读它。

**标签栏的行为（类浏览器）**：标签栏渲染在每个编辑器自己的「新建 / 加载 / 保存」那一行的**正下方**（外壳通过 `#tabs` 插槽交给 pane），支持**拖拽调整前后顺序**（`docs.moveTab`）。**「加载」不再新开标签**：当前标签是空白脚本时就地**取代**它（`docs.replaceRoot`），空白脚本上有未保存的改动会先问要不要保存；当前标签里已经有流程时才新开一个。这样反复加载不会攒出一排空白页。

**「就地取代」的坑**：文档数据是 `markRaw` 的（见上），就地改写它**不会触发任何响应式更新**。所以 store 每次替换都会把计数 `docs.rev[tabId]` +1，对应 pane 监听这个计数、重新从存储里读一遍。

**跨编辑器复制/粘贴**的入口在**画布右键菜单**（顶栏不放这几个按钮）：右键**节点** → 复制 / 剪切 / 粘贴；右键**空白画布** → 只有粘贴，落点就是鼠标位置。键盘 `Ctrl+C` / `Ctrl+X` / `Ctrl+V` 一样可用。底层用的是一份**应用内部的剪贴板**（`stores/clipboard.ts`），不是系统剪贴板：

- 系统剪贴板会把用户真实的剪贴板内容冲掉（粘出几十 KB 的 JSON），而且非文本内容在不同浏览器/WebView 上行为不一致
- 片段里存的是**相对坐标**（相对选区外接矩形的左上角），粘到另一个画布时按当前鼠标位置落位，不会跑到很远的地方
- 只带**选区内部**的连线（两端都在选区内）；与选区外相连的线会被丢掉——粘到另一个脚本后，原来的下游节点本来也不存在

### 10.21 子脚本（嵌套）与防递归

**它解决什么**：一份脚本里反复出现的通用流程（"回城补药""清背包"）不必再复制粘贴到每个分支，抽成一个**子脚本**，用「📦 调用脚本」引用。子脚本存在**父脚本文件内部**（`.agflow` 的 `scripts` 字段），随文件一起走，不会丢。

**运行语义**：子脚本被**就地展开**执行 —— 与「打包合并」的运行效果基本相同。两点必须说清：

- **循环由最外层决定**：子脚本自己那一层固定只走**一遍**。父流程 `× 3 轮`、里面调一次子脚本，子脚本就执行 3 次（每轮一次），不是 3×子脚本自己的轮数
- **「单次执行」的作用域不同**：主流程里的"单次执行"跨轮次生效；子脚本里的"单次执行"是**每次被调用**重新计

**为什么一定要防递归**：脚本能调用脚本，就必然会出现"A 调 B、B 调 A"。这与流程内部的无终止环不同 —— 无限递归会把程序**卡死**（不断加深调用、日志刷屏），用户既看不懂也退不出来。所以做了三道防线，**任何一道单独都不够**：

| 防线 | 位置 | 拦住什么 |
|---|---|---|
| 1. 编辑时拦截 | 前端 `lib/scriptGraph.ts` → `wouldCreateCycle` | 用户在选择子脚本的**那一刻**就被拒绝，并给出闭合后的完整调用链 |
| 2. 运行前整图校验 | 引擎 `scriptgraph.validate_scripts`（`/run`、`/flow/load`） | 手改 JSON、导入别人的文件、旧版本文件 —— 前端管不到的入口；同时检查**脚本缺失**与**嵌套过深** |
| 3. 运行时调用栈 | 引擎 `Executor.call_stack` + `MAX_SCRIPT_DEPTH` | 前两道都覆盖不到的极端情况，兜底防死循环；**出栈放在 `finally`**，一次异常不会污染后续所有调用 |

判据是**可达性**而不是"自己调自己"：准备加一条 `A → B`，只要**从 B 出发能走回 A**，加上就成环（所以 `A→B→C→A` 这类间接环也能拦住，报错里会写全整条链）。

实现上还有两个刻意的选择：

- **用脚本 id 而不是名字做 key**：改名不该断开调用关系。改名时同步更新索引、标签标题与所有引用它的调用节点显示名
- **"脚本缺失"必须与"成环"分开报**：指向不存在的脚本**不算图中的边**。否则删掉一个子脚本会被报成"循环调用"，用户完全看不懂 —— 而这两种情况的处理办法截然不同

**验收用例**（`tools/test_scriptgraph.py` 与 `tools/test_executor_scripts.py` 覆盖，共 80 项断言）：

| 场景 | 期望 |
|---|---|
| A 调 B（无环） | 允许运行 |
| A 调 A | 拒绝，提示 `A → A` |
| A→B→A | 拒绝，提示 `A → B → A` |
| A→B→C→A | 拒绝，提示完整三步链 |
| A→B→C→B | 拒绝（环不在根上也要能找出来） |
| A→B, A→C, B→D, C→D（菱形） | 允许（不是环） |
| 调用了不存在的脚本 | 报"脚本不存在"，**不能**报成"循环调用" |
| 嵌套超过 `MAX_SCRIPT_DEPTH`（16） | 拒绝，并给出最深的那条链 |
| 子脚本内部执行抛异常 | 调用栈仍然被清空，下一次调用不受影响 |

跑法：`python tools/test_scriptgraph.py`、`python tools/test_executor_scripts.py`（后者用桩模块替代键鼠/截图依赖，不碰真实输入）。

---

## 11. 常见问题与排错

| 现象 | 原因 / 解决 |
|---|---|
| 桌面版**双击后没有窗口** | 桌面版 v0.1.0 起：壳会先拉引擎、就绪后才开窗。若窗口创建失败（例如系统处于**锁屏/非活动桌面**时 WebView2 会报 `拒绝访问`），壳**不会退出**：它会写日志并**退回系统默认浏览器**打开同一个界面，引擎与悬浮框继续可用。看 `%APPDATA%\AutoTool\shell.log` 确认走到哪一步 |
| 想看桌面壳的诊断日志 | `%APPDATA%\AutoTool\shell.log`（可用环境变量 `AUTOTOOL_SHELL_LOG` 改路径）。里面逐条记录：启动引擎 → 引擎就绪 → 创建窗口 → 结果 |
| 关掉桌面窗口后引擎还在吗 | 不在：关窗即结束引擎与悬浮框（壳在退出时负责收尾）。想挂机就别关窗口；最小化即可 |
| 双击 exe 提示"程序已在运行" | 已有实例在跑。检查任务管理器结束残留 `AutoTool.exe` |
| 手动打开 8765 页面后功能全部 401 | API 需要令牌。用引擎控制台打印的带 `?token=` 地址进入（见 [10.8](#108-本地访问令牌)） |
| 「悬浮框」按钮置灰 | 当前运行环境缺少 `tkinter`。源码运行请安装带 Tcl/Tk 的 Python；官方发行版已内置 |
| 悬浮框没有盖在游戏上 | 独占全屏（DirectX exclusive）下任何窗口都无法置顶，请把游戏改成「无边界窗口 / 窗口化」 |
| 最小化浏览器偶尔失败/被弹回 | 已修正过两处：截图不再无条件恢复最小化窗口（见 [10.11](#1011-窗口最小化与截图)），悬浮框也不再每 2 秒重写 Z 序；悬浮框的周期性 topmost 重写也已移除，改用不激活恢复。若仍复发，请把日志面板里 `…目标窗口原本处于最小化，已恢复显示…` 那条发出来定位 |
| 录制的宏里没有鼠标移动轨迹了 | **有意变更**：轨迹点既无法编辑又拖慢回放，改为只记点击坐标（回放时直接落到该点）。旧脚本的轨迹事件仍可正常回放，见 [10.12](#1012-录制模型的拆分与打包) |
| 「📦 打包合并」按钮是灰的 | 需要先选中 **≥2 个相邻节点**：在画布上**左键拖拽框选**，或按住 `Ctrl` 逐个点击加选（画布下方有提示）。选中后按钮上会显示数量 |
| 打包合并提示"只能打包连成一串的相邻节点" | 选中的节点必须**首尾相接成一条链**。隔着没选的节点、成环、或有分支（判断节点两条出边）都会被拒绝 |
| 打包合并提示"这些节点没法打包进录制：…（录制只表达键鼠动作）" | 图像识别 / 判断 / 文本输入 / 终止 / 连点器不是键鼠动作，录制节点表达不了（提示里会列出具体是哪几个） |
| 打包合并提示"选中的节点里有 N 个勾了「单次执行」…请先取消勾选" | 录制节点表达不了"仅第一轮"，先取消这些节点的「单次执行」再打包 |
| **看不到「拆分录制」入口** | 顶栏有常驻的 **✂ 拆分录制** 按钮（无录制节点时置灰）。若界面上没有，多半是页面缓存了旧 JS —— 按 `Ctrl+F5` 强制刷新（引擎重启不会让已打开的页面换掉旧 JS）。 |
| 悬浮框点右上角图标没反应 | **桌面模式**：按父进程 PID 认壳的窗口，正常一定找得到（找不到会在日志面板留一条提示）；**源码/浏览器方式运行**：只认真正的浏览器窗口且标题需含 `AutoTool`，确认标签页还开着。鼠标移上去图标会变成青色，说明可点击 |
| 点右上角图标把后端控制台弹出来了 | 已修：早先的实现把「像不像浏览器」只当排序键、没有过滤，一个浏览器都没匹配上时会退而返回任意同名窗口（承载后端的终端标题里就含 `AutoTool`）。现在只接受真正的浏览器窗口，并且显式排除控制台/终端/解释器进程与窗口类 |
| 关掉页面后程序也退出了 | **桌面模式不会**：关窗即结束引擎（正常行为），而刷新/崩溃都不会退。源码/浏览器方式运行时的规则：**你主动关页面**（5 秒宽限内没重连）才会退；页面只是**静默掉线**（被系统挂起/丢弃、浏览器崩了）**不会退**。想永不退出设 `AUTOTOOL_KEEP_ALIVE_ON_CLOSE=1`；想恢复旧行为设 `AUTOTOOL_EXIT_ON_PAGE_LOSS=1`。见 [10.14](#1014-页面离开时后端怎么办) |
| 挂机时后端和悬浮框突然消失 | 成因：浏览器把后台标签页挂起/丢弃 → socket 断开 → 6 秒宽限内页面回不来 → 引擎按「关页面」处理而退出。现在已改为**静默掉线不退后端**，日志里会写「后端继续运行，等待页面重连」 |
| 悬浮框点「启动」没反应 | 早先启动被委托给页面，页面被系统挂起时连点也没用。现在会等 1.2 秒后**用引擎侧缓存的流程兜底启动**，日志里会写「编辑器页面没有响应启动请求…」 |
| 再次启动程序后，新页面显示已断开/一直重连 | 早先的令牌问题（每次启动新令牌，旧引擎不认）。现在令牌持久化在 `%APPDATA%\AutoTool\engine.token`，任何一次启动打开的页面都能连上 |
| 悬浮框和界面的启停状态对不上 | 引擎为唯一事实来源 + 1 秒看门狗（见 [10.13](#1013-启停状态为什么不会再分叉)），两者只认同一份状态 |
| 反复点「停止」没反应 | 同上。另一个成因：`delay` 节点整段睡死不检查停止标志，长延时期间点了要等它走完；现已改为每 250ms 检查一次 |
| 循环结束后右上角仍显示「停止」 | 前端每秒自愈，引擎侧看门狗让悬浮框也一起自愈 |
| 快捷键没反应 | 每次触发都会记日志：有 `全局快捷键：启动脚本/停止脚本` 说明按键已识别、问题在后续链路；**完全没有**则检查是否多开、或有残留实例。还要看那条快捷键**是否被停用**（**⚙ 设定 → 全局快捷键**里右侧开关），以及是否和别的功能撞了同一组键 |
| 想改快捷键 / 某个快捷键不想用 | **⚙ 设定 → 全局快捷键** → 点键位显示区 → 按下组合键 → 保存。三条（启动停止 / 键鼠录制 / 坐标拾取）都能改、都能单独停用；停用只影响按键，界面按钮照常可用。见 [7.1](#71-快捷键) |
| 坐标拾取原来按 F8，现在换成什么了 | 默认 `alt+F3`（三条全局快捷键统一按 alt+F1/F2/F3 排列）。想用回 F8：在 **⚙ 设定 → 全局快捷键**里给「拾取屏幕坐标」录成 `f8` |
| 界面太亮 / 想要回原来的深色 | 默认「跟随系统」。想要固定深色：**⚙ 设定 → 外观 → 深色**；浅色同理。偏好只存本机浏览器，见 [10.18](#1018-外观浅色--深色--跟随系统) |
| 新开的标签页显示「已在另一个窗口打开」 | 有意行为（只允许一个编辑器连接，见 [10.19](#1019-为什么只允许一个编辑器页面)）。桌面版只有壳的那一个窗口，不会遇到；源码/浏览器方式运行时会话已满，用原来那个窗口（若已关掉，本页会在 1~2 秒内自动接管） |
| 「关于」点了会不会把界面关掉 | 不会。桌面版用**系统默认浏览器**打开 GitHub 发布页，当前窗口与连接都不受影响（刻意不在这里用 `window.open`，否则会开出一个没有地址栏的子窗口） |
| 按住 alt 连按 f1 只有第一次生效 | 组合键里非修饰键一抬起就解锁（见 [10.13](#1013-启停状态为什么不会再分叉)） |
| Ctrl+Z 撤销没反应 | 历史只在画布上生效，且光标在输入框里时不拦截（那里让浏览器做文本撤销）；另外加载的旧工程要把历史从加载那一刻重新开始，加载后第一次改动才有可撤销点 |
| 找不到「首页 / 新建脚本 / 编辑脚本」入口 | **首页已彻底移除**，界面只有一个：编辑器。`/` 与任何未匹配路径都进编辑器；**新建 / 加载 / 保存**在顶栏**最左侧**，运行与悬浮框在**最右侧** |
| 想同时打开多个脚本 | 点「新建 / 加载 / 保存」那一行**下面**标签栏右侧的 **`＋`**。每个标签是一份独立的画布与撤销历史，切标签**不丢状态**；标签可以**拖拽调整前后顺序**。见 [10.20](#1020-多标签编辑器与跨编辑器搬流程) |
| 加载脚本时又开出一个空标签 | 不会：当前标签是**空白脚本**时，「加载」直接取代它（反而会问要不要先保存那个空白脚本上的改动）。只有当前标签里已经有流程时才会新开一个 |
| 「运行日志」面板找不到了 | **打开应用时默认收起**（先给画布留满），点底部右侧的 **日志** 图标展开 —— 展开后它贴在底部控制条上方、把画布顶上去，拖它的上边沿可改高度。底栏右侧还有**悬浮框**开关、左下角是**设定**（⚙）。这三个按钮都**只有图标**，鼠标悬停会显示名称 |
| 在 A 标签复制、到 B 标签粘不出来 | 跨编辑器用的是**程序内剪贴板**（不占用系统剪贴板，也不会把你正在别处复制的东西冲掉）：在 A 标签**右键选中节点 → 复制**（或 `Ctrl+C`），切到 B 标签**右键空白处 → 粘贴**（或 `Ctrl+V`）即可 |
| 「复制 / 剪切 / 粘贴」按钮在哪 | 不在顶栏，在**画布右键菜单**里：右键**节点**给三项，右键**空白画布**只给「粘贴」（落点是鼠标位置）。剪贴板为空时「粘贴」是灰的。键盘 `Ctrl+C` / `Ctrl+X` / `Ctrl+V` 同样可用 |
| 粘贴后的流程位置/形状不对 | 有意的：片段只存**相对坐标**（相对选区外接框的左上角），所以内部布局与连线会完整保留，但整体落点由目标画布决定。想贴近原来的相对方位，先把目标画布拖到大致位置再粘 |
| 想删除多个节点 | 先在画布上**左键拖拽框选**（或按住 `Ctrl` 逐个加选），再点顶栏 **🗑 删除**（就在「撤销」左边）。误删直接 `Ctrl+Z` |
| 「删除」按钮是灰的 | 需要**至少选中一个节点**；画布下方会显示当前选中数量。框选为空时按钮自动置灰 |
| 节点里的「调用脚本」列表是空的 | 只能选**本脚本内已存在**的子脚本。先建子脚本：脚本面板 → **新建子脚本**（或**导入已有脚本**），再回节点里选。也可以直接**双击画布上的「调用脚本」节点**打开对应子脚本的编辑器（还没选子脚本时双击等于打开选择框） |
| 加了子脚本却提示「脚本不存在」 | 该「调用脚本」节点指向的子脚本被**删除或改名**了。改名/删除**不会自动更新**引用，重新选一次即可。注意这类错误在**运行前**就会被拦下，不会跑到一半才失效。见 [10.21](#1021-子脚本嵌套与防递归) |
| 添加子脚本时提示「会形成循环调用」 | 有意拦截（**编辑期环检测**）：一旦让 A 调用 B，B 就**不能再直接或间接调用 A**，否则运行时会无限递归。按提示里的调用链换一种拆法（例如把公共部分抽成第三个脚本，让 A、B 都调用它）。见 [10.21](#1021-子脚本嵌套与防递归) |
| 运行前报「存在循环调用」或「嵌套过深」 | 加载/运行前会对**整张脚本图**做校验（不只看当前脚本）。循环会给出完整链路；「嵌套过深」是调用层数超过 **16 层**，请拆分。见 [10.21](#1021-子脚本嵌套与防递归) |
| 子脚本能单独拿走吗 | 能。选中子脚本 → **导出**，得到一份独立 `.agflow`，可直接在别的工程导入。这也是它和「📦 打包合并」的关键差别：合并是**一次性展开**成节点（不可还原），子脚本是**独立可编辑、可复用**的单元 |
| 停止/暂停进不了子脚本？ | 停止与暂停标志是**全局**的，进入子脚本后照样在每个检查点生效；点停止会从子脚本里一路退到顶层结束 |
| 设定面板里找不到「关于」了 | 0.1.2 起「关于」**移进 ⚙ 设定**：打开设定，左侧导航**最下方**（与上面分组有分隔线）就是「关于」，里面有**项目主页**与**发布页**两个链接 |
| 设定面板改版后快捷键/主题在哪 | 左侧导航按组划分：**通用 / 外观 / 全局快捷键** 三组，下面是 **数据与安全**（含自定义背景等），最下方是**关于**。右侧是卡片式设置行，一行一项 |
| 暂停点了没马上停 | 暂停在**检查点**生效（节点边界 / 延时的 250ms 小睡）。如果当前正在图像识别或回放宏，会等这个节点结束才停——这两类节点都有超时/时长上界。见 [10.16](#1016-暂停的语义与生效位置) |
| 暂停后进度条不动，是卡死了吗 | 不是。悬浮框会显示 `⏸ 已暂停 · 第 n/m 轮`，日志也会记「已暂停」。点「▶ 继续」从原地接着跑 |
| **后端突然不见了，怎么查原因** | 打开 `%APPDATA%\AutoTool\engine.log`。它会记下启动信息、全部运行日志、页面连接/断开、以及**退出原因**。常见几行：`桌面模式：编辑器页面已断开…后端继续运行` = 桌面版正常（刷新/崩溃都不会退，只有当壳自己收尾时才结束进程）；`编辑器页面已断开（剩余 0 个页面）` + `引擎退出：…6 秒内没有重连` = 源码/浏览器方式运行下页面断连触发了自动退出（想禁掉就设 `AUTOTOOL_KEEP_ALIVE_ON_CLOSE=1`）；`清理完成，引擎退出` = 正常优雅退出；日志末尾停在某一步且没有退出记录 = 进程被外部终止（例如被结束进程）。共 4 个文件：`engine.log` 与 `engine.log.1~.3`（各 2MB 轮转） |
| **连点器在哪、怎么调频率** | 从左侧节点面板拖入 **⚡ 连点器**，右侧属性面板里设坐标（可点 **🎯 采集点击坐标**直接用鼠标选点）、按键、**点击次数**与**间隔（ms）**；间隔滑条旁会实时显示换算的**约 N 次/秒**，设 `0` 就是不限速。执行中暂停/停止都有效 |
| **画布拖不动了 / 框选选到一片** | 有意设计：**右键拖拽**平移画布、**左键拖拽**框选节点（`Ctrl`+点击逐个加选）。想平移却按了左键就会变成框选，松开即取消 |
| 背景图设置了但换台电脑就没了 | 有意为之：背景只存本机浏览器 `localStorage`，不上传引擎、不写进 `.agflow`。见 [10.17](#1017-自定义背景选图--按屏幕比例截取--透明度) |
| 设了背景后文字看不清 | 把「设定 → 透明度」调低；画布与面板本身有一层暗色底，正常不会影响可读性 |
| 背景图保存失败/重启后丢失 | 图片太大撞了 `localStorage` 约 5MB 的配额。设置面板会提示；换一张更小的图，或调低分辨率再选 |
| 键盘突然不能用了 | **旧版本的多监听器缺陷**。请用最新版并重启电脑清掉残留钩子；新版已用事件总线修复 |
| 图像识别超时 | 提高阈值容差（降低阈值）、缩小识别区域、确认分辨率未变 |
| 中文模板识别失败 | 旧版缺陷，新版已修复 |
| 模拟输入无效 | 见 [12. 已知限制](#12-已知限制)；先用 `/input/probe` 诊断 |
| 窗口列表里没有目标窗口 | 只列出"任务栏窗口"；若游戏是子窗口/无标题窗口则不会出现 |
| 截图黑屏 | 独占全屏游戏 GDI 无法截取；请改「无边框窗口」模式 |
| exe 启动慢 / 弹 could not create temporary directory | 当前为文件夹形态（`--onedir`），不解压、也不依赖 `%TEMP%`。若你还在用旧版单文件：把它放到一个可写目录，或直接换新安装包 |
| 杀软误报 | PyInstaller / NSIS 常见现象；正式分发建议**代码签名** |
| 安装包被 SmartScreen 拦截 | 安装包**未做代码签名**，从浏览器下载后首次运行会弹「Windows 已保护你的电脑」，点「更多信息 → 仍要运行」即可，之后不再出现。这是未签名程序的通用提示，不代表文件有问题（用命令行/`gh release download` 取到的副本没有"下载来源"标记，不会触发） |
| 安装时提示缺少 WebView2 | 0.1.1 起安装包已**内嵌 WebView2 引导程序**（`embedBootstrapper`），安装器会自行补齐。若目标机器完全离线且从未装过 WebView2，改用**免安装绿色版**，并先手动装一次 WebView2 运行时 |
| 构建安装包时找不到 makensis | 桌面版不再手工调用 `makensis`：NSIS 由 `tauri build` 的 bundler 自行下载并调用。若因网络失败，可重试或给 bundler 预置本地 NSIS |
| 改了 `.ps1` / `.nsi` 后脚本报「字符串缺少终止符」 | 文件被存成了「UTF-8 无 BOM」，执行 `.\tools\to-utf8-bom.ps1` 修复（见 [9.3](#93-源码编码约定重要)） |
| 安装后快捷方式图标空白 | 图标缓存问题，执行 `ie4uinit.exe -show` 或重建快捷方式 |

**诊断命令**

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health          # 引擎存活（免令牌）
# 以下接口需令牌（AUTOTOOL_TOKEN 固定令牌时测试更方便）：
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
3. **OCR 首次调用会慢一下**：文字识别走 RapidOCR（onnxruntime），引擎**懒加载**——第一次用到这个节点时才建引擎，首次识别会多等几秒，之后正常。模型随依赖一起装好，不需要联网。
4. **反作弊**：本项目不涉及也不应涉及任何绕过反作弊的手段。
5. **撤销/重做的粒度由时间决定**：连续拖动、连续输入会被合并成一步（见 [10.15](#1015-撤销--重做为什么用快照--防抖)）；历史上限 60 步，且**不跨脚本**（加载工程后从该状态重新开始）。想逐字符回退请在输入框内用浏览器原生 `Ctrl+Z`。
6. **停止是协作式的**：引擎置停止标志，节点在检查点退出。目前所有节点都会检查（延时 250ms、图像识别/判断在轮询里、宏回放在每个事件之间、**连点器在每次点击之前**），但一次已进入的阻塞调用（如 `PostMessage` 发送）仍需等它返回。
7. **暂停只在检查点生效**：节点边界与延时片段内立即生效；图像识别/判断会等它的超时窗口结束、宏回放会等这一段放完、连点器在两下点击之间立即停住（见 [10.16](#1016-暂停的语义与生效位置)）。这样取舍是为了不让暂停时长被算进超时、也不让宏回放"追帧"。
8. **背景图存在本机浏览器**：换浏览器或清缓存会丢；`localStorage` 约 5MB 配额，导出时已限制在 1920×1080 以内并在装不下时自动降质（见 [10.17](#1017-自定义背景选图--按屏幕比例截取--透明度)）。
9. **同时仍只允许一个编辑器页面**：多标签是"一个页面里开多份文档"，不是"开多个页面"（见 [10.19](#1019-为什么只允许一个编辑器页面)）。
10. **子脚本的三条硬边界**：① 嵌套层数上限 `MAX_SCRIPT_DEPTH = 16`；② 脚本之间**不允许互相调用成环**（A→B→A 会在选择时就被拒绝）；③ **删除子脚本不在撤销范围内** —— `Ctrl+Z` 只覆盖画布上的节点增删改，删子脚本前请先导出备份（见 [10.21](#1021-子脚本嵌套与防递归)）。
11. **子脚本导出的是"自己那一份"**：单独导出的子脚本不会带上调用它的父脚本设置（循环轮数、绑定窗口沿用导出时的值），但会带上它自己的下级子脚本。

---

## 13. 路线图

- [ ] 后台输入方案落地（驱动级 / 隐藏桌面 / 浏览器自动化，按游戏形态选型）
- [ ] DXGI 桌面复制截图（支持被遮挡窗口）
- [x] **OCR 文本识别节点** —— 0.1.3 落地（RapidOCR，见 [14](#14-更新日志)）
- [x] **像素颜色 / 颜色检测节点** —— 0.1.3 落地（颜色检测 + 像素检测）
- [x] **数据类节点与变量插值** —— 0.1.3 落地（变量 / 运算 / 文本处理 + `{{变量名}}`）
- [x] **系统类节点** —— 0.1.3 落地（窗口 / 进程 / 文件 / 命令）
- [x] **子流程 / 复用组件** —— 0.1.2 以「子脚本（嵌套）」形式落地（见 [10.21](#1021-子脚本嵌套与防递归)）
- [ ] 脚本库跨文件复用（当前子脚本存在父脚本内部，跨文件复用要整份导入）
- [ ] 撤销历史的可视化（当前只显示可用/不可用，看不到具体是哪一步）
- [ ] 工程资源依赖校验与一键修复
- [ ] 区域识别（限定搜索区域，降低 OpenCV 匹配耗时）
- [ ] 社区项目导入导出（`.agflow` 打包与依赖声明）
- [ ] 代码签名与自动更新

---

## 14. 更新日志

### v0.1.4 —— 2026-10-07

**本版 = 编辑器"结构整理"的一次升级**：把「一堆平级节点」升级成**可分层的结构**（组合节点 + 变量作用域），并顺手把两处别扭的地方掰直——**输入方式下移到节点**、**悬停说明全部删掉**。脚本格式写为 `version: 3`，老文件（`1` / `2` 或没有版本号）打开时**就地自动升级**，不丢任何填过的值。

#### ✨ 新增

- **组合节点（🧩 第 7 种节点）**：不属于输入 / 视觉 / 流程 / 工具 / 数据 / 系统任何一类，**只作为"流程容器"**存在。它把一串节点**原样**装进去（内部连线、参数、节点类型全都不动），画布上只显示成一个粉色节点，摘要写「N 个节点 · 双击编辑」
- **「📦 合并节点」把选中的一串相邻节点收成一个组合节点**：在画布上选中 ≥2 个**连成一串、中间没有分支**的节点（框选，或 `Ctrl`+逐个点击加选），顶栏按钮会显示选中数量，点一下就合并。选中的不是"一条干净的链"时会明确提示，不会乱收
- **双击组合节点进入内部编辑**：在新标签里打开它内部那张图，可以当普通脚本一样增删节点、连线、改参数。**支持逐层嵌套**（组合节点里还能再放组合节点），路径逐层累加，标签用 🧩 图标
- **单击组合节点即可改属性**：右侧面板给出**名称**（画布上显示的就是它）、**内容**（几个节点几段连接）、**「🧩 进入编辑」**与**「↩ 取消组合」**两个按钮
- **「取消组合」**：合并的逆操作，把组合节点摊回画布上的普通节点，**内部连线按 id 映射原样接回**，并把上游 / 下游的连线重新挂好
- **右侧面板新增「变量」标签页**：与「参数」**共用同一块区域**，点标签切换。面板顶部会写明这一层管的是"**全局变量**"还是"**局部变量**"，可以增删变量行、选类型（自动识别 / 文本 / 数字 / 真/假）、填初值；重名会给出行内告警
- **变量分层作用域（隔离型）**：根脚本那一层管理**全局变量**；**子脚本 / 组合节点在各自的编辑页管理自己的局部变量**。运行时规则是「**读**逐级向上找、**写**只落本层、要在各层之间共享就显式写全局变量」——局部变量不会意外漏到外面，也不会把外层污染

#### 🐛 修复 / 调整

- **输入方式（真实键鼠 / 后台消息）从"流程级单选"下移到每个输入节点**：顶栏不再有那个全局单选框，改为**鼠标操作 / 键盘按键 / 文本输入 / 连续点击 / 键鼠录制**这 5 个输入节点各自带一个「输入方式」参数。引擎执行时读节点自己的 `params.input_mode`，同一条流程里可以**混用**——比如鼠标走后台消息、键盘走真实按键。（老的流程级 `input_mode` 在加载时会自动下移到各输入节点）
- **「打包合并」→「合并节点」（📦）**：语义也换了。0.1.3 的"打包合并"是把键鼠动作**压回一个录制节点**（有损、只认键鼠）；现在是把这段流程**原样**装进容器（任意节点都能收，语义不变）
- **「拆分录制」→「拆分节点」（✂）**：仍然是"把录制节点摊成普通节点"，改名让它与「合并节点」成对，更好理解
- **悬停说明（tooltip）全部去掉**：光标停在任何按钮 / 图标上都不再弹说明文字（顶栏、底部控制条、工具栏一律没有），界面更干净，也不再挡住画布
- **保存语义修正：保存的永远是整份根脚本**：即使当前停在某个子脚本 / 组合节点标签上，保存也会把根脚本连同全部子脚本 / 组合节点一次写出去（过去在子脚本标签里保存，有可能只写当前这一层）。当前标签与所属根脚本标签会一起标成"已保存"
- **`.agflow` 写为 `version: 3`**：新增 `variables`（全局变量），节点参数里新增 `input_mode`，组合节点的内容与局部变量存在 `params.{nodes,edges,variables}` 里。加载 `1` / `2` 的老文件会**就地升级**且**幂等**

### v0.1.3 —— 2026-10-06

**本版 = 一次「命名 + 节点体系」的定型**：工具正式改名 **AutoTool**；「步骤类型」升级为**节点**，按能力分成 **6 大类、25 个核心节点**。脚本格式**继续向后兼容**：0.1.2 及更早的 `.agflow` 打开时会**自动升级**（旧的"找图判断"会被拆成规范里的两个节点），老文件照常能跑。

#### ✨ 新增

- **六大类节点体系**：节点不再是一串平级的"步骤类型"，而是按**输入 / 视觉 / 流程 / 工具 / 数据 / 系统**分类，同一类**同一种配色**（蓝/绿/青/橙/紫/灰）——一眼就能看出这段流程在干什么。左侧节点面板改为**类别分页**
- **视觉类节点补齐**：新增 **文字识别（OCR，RapidOCR 中英文混排）**、**颜色检测**（区域内找指定颜色、带容差与最少像素数）、**像素检测**（精确比对一个点或 N×N 小方块）、**区域分析**（是否变化 / 平均颜色 / 区域截图存盘），并支持**框选识别区域**（`source=region` 时在截图上拖一块，存的是屏幕绝对坐标矩形，窗口截图与全屏截图都能算对）
- **数据类节点**：**变量**（赋值/读取/删除）、**运算**（`+ - * / %` 与括号）、**文本处理**（拼接/截取/替换/正则提取/转数字/去空白/大小写/分割取值）。全流程（含所有层子脚本）**共享一份运行变量**，任何文本参数都支持 `{{变量名}}` 插值
- **系统类节点**：**窗口**（按标题关键字查找 / 激活 / 最小化 / 最大化 / 还原 / 移动 / 关闭，`hwnd` 可存变量）、**进程**（启动 / 结束 / 是否在运行）、**文件**（读 / 写 / 追加 / 复制 / 移动 / 删除 / 存在性 / 列目录 / 建目录）、**命令**（CMD / PowerShell / Bash，可回收输出与退出码）
- **等待节点**：等到「图片出现 / 颜色出现 / 像素匹配 / 变量达标 / 窗口出现」，统一带超时与"超时后继续或终止"
- **外部工具节点**：运行外部程序（可选等待结束、取 stdout）或发起 HTTP 请求（方法/请求头/请求体，取响应体与状态码）
- **流程控制升级**：**判断**（&&/|| 双条件，左值可直接写变量名）、**循环**（固定次数 / 条件 / 无限，带 `max_iterations` 安全阀与"当前轮次存入变量"，循环体从 `body` 出口出去、走完连回循环节点即下一轮）、**终止**分三级（**结束当前循环** ≈ break / **结束当前脚本**（子脚本返回调用方）/ **终止整个工作流**）
- **属性面板改为"参数模式表"驱动**：25 个节点的字段、默认值、显示条件集中在 `frontend/src/lib/nodeSchema.ts` 一份数据里，**面板 / 默认值 / 节点摘要 / 老脚本补参**四处同源。新增节点只要加一条模式 + 引擎加一个处理分支，不必再到处改 `v-if`
- **老脚本自动迁移**：加载 `.agflow` 时就地升级——`click→鼠标操作`、`key→键盘按键`、`text→文本输入`、`macro→键鼠录制`；老的「找图判断」（找图 + 分支）**按新规范拆成「图像识别 → 判断」**；老的「找图」若当年带 `click` / `on_timeout=exit`，展开为 `图像识别 → 判断 →（是）鼠标操作 /（否）终止`。**升级幂等、不丢用户填过的任何值**，并会提示改了哪些

#### 🐛 修复 / 调整

- **引擎侧也认老类型名**：`normalize_type()` 兜住 `click` / `key` / `text` / `macro` 等旧名，因此**手改过 JSON、或用旧版文件直接下发**也照样能跑，不会静默走空
- **找图与判断坐标不再对不上**：统一 `grab()` 返回 `(帧, 偏移x, 偏移y)`，绑定窗口时"识别到的位置"与"点击用到的坐标"用同一套换算
- **循环图的入口判定**：循环体末尾连回循环节点后，循环节点多了入边、过去会被判定为"找不到起始节点"。现在会先识别**环内部的边**再算入度，以循环开头的流程也能正确起跑
- **节点级异常保护**：单个节点（含日志/广播层）出错只记到该节点名下并沿默认出口继续，不再把整轮挂掉；`BreakLoop` / `EndScript` 控制信号原样穿透
- **命令执行**：改用 `subprocess` + 线程执行，绕开 Windows 上 `asyncio` 子进程的 `NotImplementedError`
- **表达式求值不用 `eval`**：运算表达式走 **AST 白名单**（只放行 `abs/min/max/round/int/float/len/str`），避免从他人处拷来的脚本执行任意代码

### v0.1.2 —— 2026-10-04

**本版 = 编辑体验的一次大改**：浏览器式**多标签编辑器** + **子脚本（嵌套）** + 设置面板重做。脚本格式向后兼容：老 `.agflow`（`version: 1`）照常打开，没有子脚本时不产生任何新字段；带子脚本的文件写为 `version: 2`，老版本读到会忽略 `scripts`（只丢子脚本，主流程仍能跑）。

#### ✨ 新增

- **多标签编辑器（浏览器式）**：可同时打开多个脚本，每个标签是一个**独立编辑器实例**（各自的画布、选中态、撤销历史互不干扰）。标签带类型图标（📄 主脚本 / 📦 子脚本）与未保存小圆点，关闭有改动的标签会先确认。**新建**从"清空当前画布"改成"开一个新标签" —— 这样"同时编辑多个脚本"才成立
- **跨编辑器复制 / 剪切 / 粘贴**：框选一批步骤 → **在画布上右键 → 复制 / 剪切**（或 `Ctrl+C` / `Ctrl+X`）→ 切标签 → **右键空白处 → 粘贴**（或 `Ctrl+V`），整段流程连同**内部连线**一起搬过去，落点在鼠标位置。用的是应用内剪贴板（不碰系统剪贴板），片段按**相对坐标**存储（见 [10.20](#1020-多标签编辑器与跨编辑器搬流程)）
- **画布右键菜单**：右键**节点**给出「复制 / 剪切 / 粘贴」，右键**空白画布**只给出「粘贴」（落点就是鼠标位置）；点到别处或按 `Esc` 关闭，剪贴板为空时「粘贴」置灰。**顶栏不再放这三个按钮**；右键的节点若不在当前选中集合里，会先把它变成唯一选中（已在集合里则保留整批，方便整批搬走）
- **子脚本 / 脚本嵌套**：新增「📦 调用脚本」步骤。子脚本在**新标签页**里编辑，可**新建空白**、可**从已有 `.agflow` 导入**（连同它的下级子脚本一起搬入并重新编号，避免 id 撞车），也可**单独导出**成文件。子脚本存在父脚本文件内部，运行时**就地展开**（见 [10.21](#1021-子脚本嵌套与防递归)）
- **防递归三道防线**：编辑时拦截 → 运行前整图校验 → 运行时调用栈 + 层数上限（`MAX_SCRIPT_DEPTH = 16`）。报错全是中文且带完整调用链；**"脚本缺失"与"循环调用"分开报**（前者根本不算依赖边，否则删个子脚本会被误报成环）
- **工具栏「删除」按钮**：放在「撤销」**之前**，一次删掉所有选中的流程（也可用 `Delete` / `Backspace`）
- **设置面板重做**：改为**左侧分组导航 + 右侧卡片式设置行**（通用 / 外观 / 快捷键 / 数据与安全 / 关于），设置项多了也不用一路往下翻
- **「关于」移入设置**：顶栏的 `关于 vX.Y.Z` 按钮撤掉，版本、运行形态、引擎连接状态、项目主页与发布页统一放在 **⚙ 设定 → 关于**
- 顶部新增**「子脚本不存在」告警条**：画布里存在指向已删除子脚本的调用时，打开这个脚本就会提示
- **标签可拖拽排序**（浏览器式）：按住标签左右拖，拖到另一个标签上就插到它的位置，拖动时会有一根竖线指示落点
- **双击「调用脚本」节点**直接在新编辑器里打开它指向的子脚本（还没选子脚本时双击等于打开选择框）；「选择…」按钮照旧
- **底部控制条**：左下角是**设定**（⚙，字号放大、不带文字），右下角是**日志**与**悬浮框**图标开关；三个按钮都只有图标，名称挂在鼠标悬停提示上
- **运行日志回到窗口下方、且默认收起**：**打开应用时不展开**（先把画布留满），点底部「日志」图标在**下方展开**原来的日志框（占据布局高度、把画布顶上去），再点收起；拖它的上边沿可改高度。不再做成浮在画布上的小窗

#### 🐛 修复 / 调整

- **子脚本负载必须扁平化**：`.agflow` 里节点是 Vue Flow 形式（带 `position` / `data`），而引擎只认 `{id, type, params, once}`。下发运行负载时按脚本逐层转换 —— 漏掉这步的表现是**子脚本静默地什么都不做**（引擎读 `node["type"]` 全是空，走到 `else` 只记一条"未知节点类型"）
- **引擎侧 `scripts` 也要校验**：子脚本里指向不存在节点的坏连线，现在会在 `/run` 时就被 `validate_flow` 拒绝，而不是等执行到一半才炸
- **顶栏去掉「关于」按钮**：它属于"看一次就够"的信息，占着顶栏最显眼的按钮位不划算
- **多标签下的状态归属重新划分**：引擎连接、运行状态、日志、悬浮框开关、模板与窗口列表是**全应用一份**（引擎只允许一条页面连接），文档数据归各自的 `EditorPane`。运行状态的 1 秒轮询也从"每个标签各轮一次"改为全应用一次
- **「加载」改为取代当前空白脚本**：不再每加载一次就多留一个空白标签；空白脚本上有未保存改动会先问要不要保存，当前标签里已经有流程时才新开标签
- **标签栏移到「新建 / 加载 / 保存」那一行下面**：标签属于编辑器，位置就该由编辑器决定（外壳用 `#tabs` 插槽传给它）
- **去掉两处说明文字**：标签栏右侧的操作提示、步骤类型区下方的操作说明
- **修掉步骤类型区的溢出**：步骤多于可用高度时改为**在它自己内部滚动**（`min-height: 0` + `overflow-y: auto`），不再压到下方的日志面板上
- **循环轮数移到顶栏右侧**，紧挨着「▶ 运行」按钮

#### ✅ 本版验证

- `vue-tsc --noEmit` 严格类型检查（含 `noUnusedLocals`）+ `vite build` 通过；项目自带的 `tools/check_ui_imports.mjs` 组件导入检查 0 缺失
- **编辑器界面回归 22 项全绿**（`.\tools\test_ui_editor.ps1`，无头 Chrome + 纯页面内事件、**不注入真实鼠标**）：日志默认收起、点图标在画布下方展开 / 收起、底栏三个按钮只有图标、齿轮字号 21px、顶栏已无「复制/剪切/粘贴」、右键节点得到三项 / 右键空白只给「粘贴」/ 剪贴板空时置灰 / `Esc` 可关、标签三次不同方向的拖拽换位顺序全对（见 [9.10](#910-编辑器界面回归无头浏览器)）
- **防递归 80 项断言全绿**：`tools/test_scriptgraph.py`（33 项，纯图论）+ `tools/test_executor_scripts.py`（47 项，用桩模块替代键鼠/截图依赖，直接驱动 `Executor.run` 验证嵌套执行、轮数语义、调用栈出栈、空/缺失子脚本、终止条件传播、坐标换算）
- **端到端实测**（真实引擎 + HTTP）：`/health` 返回 `0.1.2`；环形脚本被 `400` 拒绝并返回 `存在循环调用，无法运行：打怪 → 回城 → 打怪`；缺失子脚本被 `400` 拒绝并说明是哪一步指向了谁；正常子脚本流程 `200` 开跑，引擎日志逐行确认 `进入子脚本「脚本S1」（第 1 层）→ 子脚本内节点执行 → 子脚本执行完成`，两轮循环各展开一次
- **打包产物实测**（PyInstaller onedir + Tauri/NSIS）：
  - 冻结包里的 `/flow/load` 对照测试 —— 合法流程 / 合法子脚本调用 `200`，自环（`A → A`）`400 存在循环调用，无法运行：A → A`，缺失子脚本 `400` 并给出补救提示（证明 `scriptgraph.py` 确实打进了包，不只是源码里能跑）
  - **免安装绿色版**：解压到工作区外 → 双击 `autotool.exe` → `shell.log` 走到 `引擎 /health 已就绪`、`创建主窗口`、`主窗口已创建`，`/health` = `{"version":"0.1.2","desktop":true}`
  - **安装包**：`/S` 静默安装退出码 `0`，`%LOCALAPPDATA%\AutoTool` 下 `autotool.exe` / `engine\AutoTool.exe` / `engine\_internal\frontend_dist\` 齐全，注册表 `DisplayVersion = 0.1.2`；启动后同样走到 `主窗口已创建`

### v0.1.1 —— 2026-10-03

**本版 = 补齐「桌面化」留下的尾巴**（WebUI 期的功能在桌面模式下失效）+ **新增连点器** + **重排顶栏与画布交互**。脚本格式向后兼容：老 `.agflow` 照常打开，新节点类型 `autoclick` 只在用到时才出现。

#### ✨ 新增

- **连点器节点（⚡）**：高频连点，可设坐标（**🎯 屏幕点选采集**）、左/右/中键、**点击次数**与**间隔（频率）**。间隔可低至 `0 ms`（按"不限速、尽可能快"执行），属性面板实时显示换算的**约 N 次/秒**；执行中暂停 / 停止立即生效（每次点击前检查、间隔按 50 ms 切片），日志按「N 次 / M ms」标注。它是独立步骤，不参与「打包合并」
- **设置页新增「全局快捷键」**：原来顶栏的 `⌨ 快捷键` 弹窗整体移入 **⚙ 设定**，仍可改键、单独停用、恢复默认；设置页打开时自动拉取当前绑定

#### 🐛 修复（桌面模式下失效的 WebUI 期功能）

- **悬浮框「回到界面」点不动**：老实现只搜索**浏览器**窗口，桌面版里永远匹配不到。现在按**父进程 PID**（`os.getppid()`）枚举顶层窗口定位壳的原生窗口（过滤有属主 / 工具窗口 / 无标题 / 非浏览器类），最小化状态也能唤回；源码 / 浏览器方式运行仍退回按标题匹配浏览器窗口
- **后端跟着页面断开而退出**：桌面模式下「页面没了」（刷新页面、WebView 崩溃）与「用户关了程序」不是一回事。现在断连只记日志、后端继续跑，生命周期完全交给壳（**关窗即结束进程**）；前端在桌面模式也不再发 `/goodbye`，避免刷新时误触发 5 秒退出倒计时
- 连接 / 断开日志文案统一为「编辑器页面…」，桌面模式另给一条「后端继续运行（关窗由壳负责结束进程）」的明确提示

#### 🎨 界面调整

- **顶栏重排**：删掉最左侧的名称与 logo；**新建 / 加载 / 保存**移到**最左侧**；**悬浮框 / 运行**固定在最**右侧**；快捷键与外观收进 ⚙ 设定
- **画布鼠标逻辑**：改为**右键拖拽平移**、**左键拖拽框选**多个流程节点（`Ctrl`+点击逐个加选），并屏蔽画布上的浏览器右键菜单。原先「左键拖拽 = 平移、`Shift`+拖拽 = 框选」的组合已不再使用
  - ⚠️ 首版发出的 0.1.1 里这条**实际没生效**，本版已修：`selectionOnDrag` 是 **React Flow** 的 API，`@vue-flow/core` 里根本没有这个 prop（传进去只会变成一个没人读的 DOM 属性，不报错也不警告），而 `selectionKeyCode=null` 的语义恰好是**彻底禁用框选** —— 两者叠加导致左键框选**永远无法启动**。已改为 `selectionKeyCode=true`（左键即框选）+ `multiSelectionKeyCode=Control`
  - 同一处还有第二个 bug：实例上的 `vf.getSelectedNodes` 是**数组而非函数**（旧代码按函数调用会抛 `TypeError` 并被 `catch` 静默吞掉），于是每次都退回「遍历 nodes 找 selected」这条不可靠的兜底 —— 表现就是「框上了，但打包合并按钮不亮」。已改为直接读数组，并让右侧属性面板跟随选择集同步
  - 选中反馈不再只换边框色：改为「边框 + 标题文字变强调色 / 2px 实心光环 / 外圈柔光（多选时相邻节点连成一片）/ 右上角 ✓ 角标」四层叠加。全部用 `box-shadow` 与绝对定位实现，**刻意不动 `width/height/border-width`** —— 改了会触发 Vue Flow 的尺寸重测，节点在选中瞬间会自己抖一下
- **去掉多余的悬停提示**：快捷键 / 悬浮框 / 关于 / 设定这几个可点击按钮不再包 `NTooltip`（提示与按钮文字重复，还会在点击瞬间挡住目标）
- **「⏺ 开始录制」按钮**去掉文字后面括号里的快捷键提示（键位改到设置里查看）；**「✂ 拆分录制」**去掉警示色，并与 **📦 打包合并**放进同一行、不再换行

#### 📝 说明

- 版本号统一为 `0.1.1`，**五处一致**：`engine/main.py`（FastAPI title + `/health`）、`frontend/package.json`、`frontend/src-tauri/tauri.conf.json`、`frontend/src-tauri/Cargo.toml` 及其 `Cargo.lock` 里的版本行
- `/health` 额外返回 `desktop` 字段，前端据此判断是否需要发送告别信号
- 安装包文件名 `AutoTool_0.1.1_x64-setup.exe`（分发副本为根目录 `AutoTool-Setup.exe`）；发布 tag 用 **`v0.1.1`**（`0.1.0` 那次加 `-desktop` 后缀只是为了避开仓库里更早的同名 tag）
- 安装包改为**内嵌 WebView2 引导程序**（`bundle.windows.webviewInstallMode = embedBootstrapper`）并固定安装器图标 —— 目标机器缺少 WebView2 时不再需要安装期单独联网下载
- **重新提供免安装绿色版** `AutoTool_0.1.1_portable_x64.zip`：0.1.0「不再单独出绿色包」的决定在本版撤回 —— 真实场景里仍有既没有管理员权限、也不愿意动安装器的机器
- 两个包的安装路径已各自实测：安装包在**非工程目录**（下载目录）下 `/S` 静默安装 → 注册表 `DisplayVersion=0.1.1`、桌面快捷方式、`/health` 正常；绿色版解压后直接双击 → `引擎 /health 已就绪` → `主窗口已创建`

### v0.1.0（桌面版首版）—— 2026-10-03

**桌面版从本版起算 0.1.0。** 本版 = 「从浏览器 WebUI 迁移为 Tauri 2 桌面版」+「修掉装完打不开的构建陈旧问题」+「下线 WebUI 期的构建与分发产物」，并把版本号**重基线为桌面版号段**（此前 WebUI 期的号段与桌面版不连续，其内容全部并入本版）。界面、脚本格式与用户数据目录保持不变，老脚本 `.agflow` 与找图模板零改动可用。

#### ✨ 桌面化

- **桌面壳（Tauri 2）**：原生窗口显示同一个编辑器界面；壳负责「拉起引擎 → 等 `/health` 就绪 → 开窗」，关闭窗口时结束引擎
  - 引擎仍是本地 `127.0.0.1:8765` 的 HTTP/WS 服务，前端由引擎同源提供（不需要处理 CORS，也不需要在页面里注入令牌）
  - 开发模式窗口开在 vite（1420）上，改前端即时热更新；发布模式窗口开在引擎入口 URL（带持久令牌）
  - 单实例：第二次启动把已有窗口提到前台，而不是再开一个
  - 壳自带诊断日志 `%APPDATA%\AutoTool\shell.log`（可用 `AUTOTOOL_SHELL_LOG` 指定路径）
- **引擎新增桌面模式** `AUTOTOOL_DESKTOP=1`：不自动开浏览器，且**永不因为「页面没了」退出**（关窗、刷新、WebView 崩溃都由壳收尾）
- **引擎新增** `POST /open_external`（令牌保护，只放行 http/https）：顶栏「关于 → GitHub 发布页」交给系统默认浏览器打开 —— 桌面壳里的 `window.open` 会开出一个没有地址栏、没有前进后退的子窗口
- **打包**：新增 `build_desktop.ps1`（前端 → 引擎 onedir → `tauri build` → NSIS 安装包）；引擎作为 Tauri `resources` 随包分发，**仍用 onedir（不回到 onefile）**，避免重新引入 `%TEMP%` 解压那类启动失败

#### 🐛 修复

- **装完后双击没反应、窗口始终不出现**
  - 根因：发出去的 `AutoTool-Setup.exe` 构建于「建窗失败改为退回浏览器」那次源码改动**之前**。旧壳在 `open_main_window` 失败时直接把错误往上抛，Tauri 的 `build().expect(..)` 随之 panic；release 是无控制台子系统，于是**静默退出**——用户看到的就是「双击了，然后什么都没有」
  - 触发条件在真实环境里确实存在：系统处于**锁屏/非活动桌面**时 WebView2 建窗会报 `拒绝访问 (os error 5)`；或引擎在 90 秒内没就绪
  - 修复：按当前源码重新构建安装包。新壳建窗失败时**退回系统默认浏览器**打开同一界面，并把原因写进 `shell.log`，进程不再退出，引擎与悬浮框继续可用

#### 🧹 清理（本版下线）

- **WebUI 期独立安装器**：删除 `build_installer.ps1`、`installer\AutoTool.nsi` 与 `tools\nsis\` 工具链 —— 安装包改由 Tauri bundler 内置的 NSIS 产出，不再需要手工维护 `.nsi`
- **便携版**：删除 `dist-desktop\` 与便携版 zip。「免安装」不再单独出一个包 —— 安装包解出来的 `autotool.exe` + `engine\` 本身就是绿色的（见 [9.2](#92-制作安装包tauri-bundler--nsis)）※ 本项**已在 0.1.1 撤回**，绿色包重新提供
- **构建产物**：删除 `engine\dist\`、`engine\build\`、`engine\AutoTool.spec` 与 `engine\build.log`（下次构建自动重建）
- **WebUI 期回归测试脚本**（17 个、约 300 条断言）与临时/构建产物约 1.4 GB —— 取舍说明：这些脚本大量围绕「浏览器页面 / 多窗口 / 关闭页面即退出」编写，桌面版语义已不同；引擎侧可复用的部分后续按新架构重建
- 环境要求（本机实测通过）：Rust stable + MSVC 工具链、Node/pnpm、WebView2 运行时、Python 3.13 venv + PyInstaller、NSIS（Tauri 自带）

#### 📝 说明

- 版本号统一为 `0.1.0`，五处联动：`engine/main.py`（FastAPI title + `/health`）、`frontend/package.json`、`frontend/src-tauri/tauri.conf.json`、`frontend/src-tauri/Cargo.toml`（同步 `Cargo.lock` 里 `autotool` 的版本行）
- 安装包文件名 `AutoTool_0.1.0_x64-setup.exe`（分发副本为根目录 `AutoTool-Setup.exe`）
- 发布 tag 用 **`v0.1.0-desktop`** —— 仓库早先已有一个 `v0.1.0` tag，故加 `-desktop` 后缀区分。桌面版按 `0.x` 号段独立计数

---

## 15. 开源协议

本项目**自有代码**基于 **MIT License** 开源，详见 [`LICENSE`](LICENSE) —— 你可以自由使用、修改、分发甚至商用，只需保留版权与许可声明。

需要注意的是，MIT 只覆盖本仓库自有的代码。发行版安装包里还打包了若干第三方组件，其中 `pynput` 采用 **LGPL-3.0**，另有 OpenCV（Apache-2.0）、PyInstaller（GPL-2.0+ 含 Bootloader 例外）等。各组件的版本、许可与相应义务见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

如果你打算二次分发或商用本项目的发行版，请一并遵守上述第三方许可。

---

<div align="center">

**AutoTool** · Windows 优先 · 本地引擎 + 一键安装

</div>
