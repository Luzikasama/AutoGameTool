# AutoGameTool 代码审查报告

> 审查范围：engine/（11 个 Python 模块）、frontend/src/（11 个 TS/Vue 文件）、build_exe.ps1、build_installer.ps1、installer/AutoGameTool.nsi、run_*.ps1、README.md
> 审查日期：2026-09-12

---

## 〇、修复状态（v0.3.0，2026-09-12）

以下问题已在 v0.3.0 中修复并通过验证（引擎实测 + vue-tsc + vite build）：

| 编号 | 修复内容 | 验证结果 |
|---|---|---|
| S1 | CORS `*` 已移除（仅 `AUTOGAMETOOL_DEV=1` 时放行 vite 1420）；所有 API 增加随机令牌鉴权（启动生成，随浏览器 URL `?token=` 传给前端，`Authorization: Bearer` / `?token=` 双通道，WS 同样校验）；Host 头白名单防 DNS rebinding；请求体 64MB 上限 | 无令牌 401 / 错令牌 401 / 伪造 Host 403 / 带令牌 200 ✅ |
| S2 | SPA 兜底路由 `resolve()` + `relative_to` 归属校验，越界回退 index.html | 冒烟测试含遍历回归项 ✅ |
| S3 | `/debug/kb` 移除 `last` 按键内容字段 | 实测返回仅计数与 alive ✅ |
| S4 | 模板名白名单校验（中英文/数字/空格/-_.，禁 `..`/保留名）+ resolve 双重防遍历；`save_template` 重名报错 | `..\..\evil` 删除请求 400 ✅ |
| B1 | `validate_flow()` 前置校验（repeat/节点/连线），非法流程 400 拒绝，`running` 不再卡死 | `repeat:"abc"` → 400；正常流程执行完后可再次运行 ✅ |
| B2 | 组合键回放：`_split_combo` 拆分 `ctrl+shift+a`，修饰键按下→主键→逆序抬起（真实/模拟两种模式） | 单测通过 ✅ |
| B3 | `hotkey._norm` 把 pynput `cmd*` 归一为 `win`，前后端命名一致 | 单测通过 ✅ |
| B4 | 模拟模式滚轮改为 `PostMessage(WM_MOUSEWHEEL)`（wParam 高位 delta，lParam 屏幕坐标） | 代码审查 ✅ |
| B5 | `_spawn()` 统一持有 `create_task` 强引用（`_bg_tasks` 集合 + done_callback） | 代码审查 ✅ |
| B6 | 加载脚本后 `nodeSeq` 取现有 ID 最大数字后缀，不再撞 ID | vue-tsc ✅ |
| B7 | `/run` 检查-启动加 `asyncio.Lock` 原子化 | 代码审查 ✅ |
| B8 | 截图/匹配/键鼠输入全部 `asyncio.to_thread`，事件循环不再被同步阻塞 | 代码审查 ✅ |
| B9 | 模板重名保存报错；重命名/删除联动处理 `.meta.json` 侧车文件 | 代码审查 ✅ |
| B10 | 版本统一为 0.3.0（main.py / health / NSI / VIProductVersion） | 实测 health 返回 0.3.0 ✅ |
| R1 | 流程同步按指纹去重，不再每秒全量空打 | 代码审查 ✅ |
| R5/R6 | 单轮步数上限防无终止环空转；多起始节点/不可达节点启动时告警 | 代码审查 ✅ |
| R7 | WS 广播改 `asyncio.gather` 并发，异常连接兜底清理 | 代码审查 ✅ |
| R8 | 快捷键配置原子写入 + 空值校验 | 代码审查 ✅ |
| R11 | `_key_lparam` 补充扩展键位（bit 24） | 代码审查 ✅ |
| R13 | 前端解析 FastAPI `detail` 错误，不再展示原始 JSON | 代码审查 ✅ |
| R14 | 截图框选补偿 stage 滚动偏移 | 代码审查 ✅ |
| **新增** | **多分辨率/DPI 自适应**：模板保存时记录参考画面尺寸（`.meta.json`），匹配时按比例自动缩放模板（`match_template_auto`，支持 0.3x~3x）；`.agflow` 记录参考屏幕分辨率与窗口 rect，执行时点击/宏坐标按比例换算（窗口绑定优先按窗口 rect，否则按主屏分辨率） | 同分辨率/1.5x/0.5x 缩放匹配全部命中且坐标正确 ✅ |

遗留（未修，建议后续迭代）：R2（mss 单例复用）、R3（最小化窗口截图自动恢复的副作用）、R4（DWM 边框注释）、R9（`_norm` 跨模块私有引用）、R10（录制残留事件边界）、R12（快捷键双触发观感）、R15-R17（构建脚本与供应链加固）。

---

## 一、安全漏洞（按严重程度排序）

### 🔴 S1. 本地 API 完全无鉴权 + CORS 全开：任意网页可远程操控键鼠（高危）

**位置**：`engine/main.py:164-170`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # ← 允许任意来源
    allow_methods=["*"],
    allow_headers=["*"],
)
```

引擎监听 `127.0.0.1:8765` 且**没有任何鉴权**。CORS 通配符意味着：用户浏览器里打开的**任何一个恶意网页**都可以直接 `fetch("http://127.0.0.1:8765/...")` 并读取响应。可被远程调用的能力包括：

- `POST /run`：执行任意自动化流程（在用户电脑上移动鼠标、点击、敲键盘——包括向其他应用窗口注入文本）
- `POST /input/click`、`/input/key`、`/input/text`：直接注入键鼠事件
- `GET /screen/screenshot`、`/windows/list`：截取屏幕、枚举窗口标题（隐私泄露）
- `GET /vision/templates`、`/vision/template/{id}/image`：读取用户保存的模板图片

这相当于给所有网站开放了一个"RPA 后门"。攻击示例：诱导用户打开一个网页，该网页静默调用 `/run` 执行一段预先构造的流程，向终端/聊天窗口输入命令并发送。

**建议**：
1. 打包版前端与引擎同源，**根本不需要 CORS**——删掉 CORSMiddleware，或仅在开发模式（环境变量控制）允许 `http://localhost:1420`。
2. 引擎启动时生成随机 token，自动打开浏览器时以 `http://127.0.0.1:8765/?token=xxx` 传入，前端存入 sessionStorage 并在所有请求头中携带 `Authorization`；WS 握手同样校验。无 token 的请求返回 401。
3. 校验 `Host`/`Origin` 头，防御 DNS rebinding。

### 🔴 S2. SPA 兜底路由存在路径遍历：任意文件读取（高危）

**位置**：`engine/main.py:373-379`

```python
@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path:
        candidate = _frontend_dir / full_path
        if candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(_frontend_dir / "index.html")
```

`full_path` 未做归一化与归属校验。URL 中 URL 编码的 `%2e%2e%2f`（`../`）或 `%5c`（`\`，Windows 路径分隔符）会被 Starlette 解码后进入 `Path` 拼接，`..` 可逃出 `frontend_dist`；浏览器不会规范化编码过的点段，因此可直接利用：

```
GET http://127.0.0.1:8765/x/%2e%2e/main.py        → 读到引擎源码
GET http://127.0.0.1:8765/x/%2e%2e%2f..%2f..%2f某文件 → 读盘上任意可读文件
```

**叠加 S1 的 CORS `*`，任何网页都能把响应读回去**——这是一个可被浏览器远程利用的任意文件读取漏洞。

**建议**：

```python
base = _frontend_dir.resolve()
candidate = (base / full_path).resolve()
if candidate.is_file() and str(candidate).startswith(str(base) + os.sep):
    return FileResponse(candidate)
```

（顺便建议直接改用 `StaticFiles(directory=..., html=True)`，Starlette 对其已内置遍历防护。）

### 🔴 S3. `/debug/kb` 泄露全局最后按键：远程键盘记录（高危，隐私）

**位置**：`engine/keybus.py:28-31`、`engine/main.py:178-182`

```python
def _dispatch_press(key) -> None:
    global _press_count, _last_key
    _press_count += 1
    _last_key = str(key)        # ← 记录了按键内容（含可打印字符）
```

`GET /debug/kb` 返回 `{"last": "'a'", ...}`。叠加 S1（CORS `*`），**任意网页可以每 50ms 轮询该接口，把用户全局敲击的可打印字符拼出来**——一个开箱即用的远程键盘记录器。这虽是"诊断接口"，但泄露内容超出了诊断所需。

**建议**：
1. `counts()` 中去掉 `last`，只保留计数与 `alive`；或对 `last` 做脱敏（只记录按键类别，不记录字符）。
2. 该接口同样纳入 S1 的 token 保护。

### 🟠 S4. 模板 ID/名称未做路径校验：路径遍历写/删/改文件（中高危）

**位置**：`engine/vision.py:89-133`

`save_template` / `load_template` / `rename_template` / `delete_template` / `get_template_image` 全部直接拼接：

```python
_templates_dir() / f"{tpl_id}.png"
```

未消毒的 `tpl_id`/`name` 可以包含 `..`、`\`、`/` 以及 Windows 非法文件名字符：

- `POST /vision/capture_template` `{"name": "..\\..\\evil"}` → 向任意可写路径写 PNG 文件
- `POST /vision/template/delete` `{"id": "..\\..\\x"}` → 删除任意 `.png` 文件
- `POST /vision/template/rename` → 把任意 `.png` 移动到任意位置

叠加 S1 可被网页远程调用。另外，用户输入含 `/:*?"<>|` 等字符时会抛出未处理异常（500），中文以外的特殊名也未过滤。

**建议**：统一在入口校验：`re.fullmatch(r"[\w\- \u4e00-\u9fff]{1,64}", name)`（`\w` 已含中文需注意 Python `\w` 匹配 Unicode 字母，可接受），并 `resolve()` 后断言父目录就是模板目录；`save_template` 增加重名检查（当前会静默覆盖同名模板）。

### 🟡 S5. 其他安全相关

| 问题 | 位置 | 说明 |
|---|---|---|
| WS 无 Origin 校验 | `main.py:358-365` | 任意网页可连 `/ws` 接收日志/状态推送，也能触发 `hotkey` 消息诱导前端执行 |
| 请求体无大小限制 | `main.py` | `capture_template` 接收 base64 大图，可被用于内存 DoS |
| 互斥体 GetLastError 用法 | `main.py:391-392` | ctypes 调用间可能覆盖 `GetLastError`，稳妥做法是检查 `ctypes.get_last_error()`（需 `use_last_error=True`）或 `CreateMutexW` 返回句柄后再 `GetLastError` 立即读取（当前写法勉强可用，但脆） |
| 端口被占用未处理 | `main.py:408` | 8765 被占时 uvicorn 启动失败，但浏览器已被拉起，用户看到打不开的页面；建议失败时给出提示或改用动态端口 + 写入配置 |

---

## 二、功能性 Bug（正确性）

### 🟠 B1. `/run` 的 `repeat` 解析在 try 之外：恶意/错误流程会让引擎永久"卡在运行态"

**位置**：`engine/executor.py:41-56`

```python
async def run(self, flow: dict) -> None:
    self.current_flow = flow
    self.stopped = False
    self.running = True          # ← 先置 True
    ...
    repeat = max(1, int(flow.get("repeat", 1)))   # ← 在 try 之外！
```

`flow["repeat"]` 若为 `"abc"` 或 `None`，`int()` 抛 `ValueError`；此时 `try/finally` 尚未进入，`self.running` **永远停留在 True**，之后所有 `/run` 都返回 409，只能重启引擎。`nodes`/`edges` 非列表等畸形数据同样可能触发。

**建议**：把整个解析移入 `try`，或用 Pydantic 模型在 `/run`、`/flow/load` 入口做 schema 校验（当前这两个接口接受任意 `dict`，完全没有校验）。

### 🟠 B2. 组合键链路断裂：前端支持录制组合键，引擎无法回放

- **前端**（`Editor.vue:311-327`）按键节点可录成 `"ctrl+shift+a"` 这样的组合串，README 也声称"支持组合键"。
- **引擎**（`inputctl.py:291-309`）：`_key_to_vk("ctrl+shift+a")` 不在 `_VK` 里、长度 > 1 → 返回 `None` → **模拟模式静默什么都不做**；真实模式 `_map_key` 原样返回 `"ctrl+shift+a"` → `pynput.Controller.press()` 抛 `ValueError` → 节点报错。

**建议**：`press_key/key_down/key_up` 先按 `+` 拆分，修饰键（ctrl/alt/shift）用 `press` 后置 `release` 的顺序处理；或前端录制时就限制为单键 + 说明。

### 🟠 B3. Win 键快捷键永远无法生效（命名不一致）

**位置**：`frontend/src/views/Editor.vue:478`（meta 把 `meta` 键记为 `win`） vs `engine/hotkey.py:16-28`（pynput 的 `Key.cmd` 被归一化为 `"cmd"`）。

用户录制的 `win+x` 保存为 `["win","x"]`，引擎侧 `target.issubset(pressed)` 中 `pressed` 里只有 `"cmd"`，永远不匹配。

**建议**：`_norm` 中把 `cmd`/`cmd_l`/`cmd_r` 归一为 `"win"`，或在保存时禁用 win 键。

### 🟠 B4. 模拟模式下滚轮回退为真实输入：宏回放会滚动用户真实桌面

**位置**：`engine/inputctl.py:173-174`

```python
def scroll(dx: int, dy: int) -> None:
    _mouse.scroll(int(dx), int(dy))   # 无 mode/hwnd 分支
```

模拟输入的卖点是"不占用物理键鼠"，但录制宏中的 `scroll` 事件回放时（`executor.py:206-207`）直接调用 `_mouse.scroll`，滚动的是**真实桌面**。**建议**：模拟模式用 `PostMessage(WM_MOUSEWHEEL, ...)` 发给焦点窗口（注意 wParam 高 16 位是 delta、需要 `POINT` 结构 lParam）。

### 🟠 B5. `asyncio.create_task` 未保存强引用：任务可能被 GC 中途取消

**位置**：`main.py:107、123、133、141、307`、`executor` 相关调度。

CPython 文档明确要求保存 `create_task` 返回值，否则事件循环只持弱引用，任务可能在执行中被垃圾回收。`/run` 的 `create_task(executor.run(...))` 一旦被回收，流程"无声消失"且 `running` 卡 True（与 B1 叠加）。

**建议**：模块级 `_bg_tasks: set[asyncio.Task]`，`t = asyncio.create_task(...); _bg_tasks.add(t); t.add_done_callback(_bg_tasks.discard)`。

### 🟡 B6. 加载脚本后新增节点可能产生 ID 冲突

**位置**：`Editor.vue:426`：`nodeSeq = nodes.value.length`。

若脚本文件中的节点 ID 是 `n1, n2, n5`（此前删过节点），`nodeSeq=3`，第二次新增节点得到 `n5` → **与既有节点撞 ID**，连线/删除/选中全部错乱。**建议**：扫描现有 ID 取最大数字后缀：`nodeSeq = Math.max(0, ...nodes.map(n => +n.id.replace(/\D/g,'') || 0))`。

### 🟡 B7. `/run` 的"检查-启动"非原子

`if executor.running: raise 409` 与 `create_task(run)` 之间存在窗口，两个并发 `/run` 都能通过检查。建议加 `asyncio.Lock` 或把检查与置位放进 `run()` 内部同步段。

### 🟡 B8. 事件循环被同步阻塞调用卡住

`executor._run_step` / `_do_judge` / `_do_find` 都是 async 函数，但内部直接同步调用：
- `inputctl.click`（内含多次 `time.sleep`）
- `window.capture_window`（PrintWindow + GetDIBits，且窗口最小化时 `time.sleep(0.3)`）
- `vision.match_template`（约 76ms/次，0.2s 轮询间隔里占比不小）

这些都运行在 uvicorn 事件循环线程上，期间 **WebSocket 日志推送、/run/stop、前端所有请求全部卡顿**；窗口恰好最小化时每次截图还会额外阻塞 300ms。**建议**：把截图/匹配/输入包装为 `await asyncio.to_thread(...)`（注意 pynput Controller 非线程安全的调用点需评估）。

### 🟡 B9. `save_template` 静默覆盖同名模板

`vision.py:89-92`：`name` 已存在时直接覆盖旧文件，无提示；且 `rename_template` 后前端仅更新当前画布节点引用，其他已保存 `.agflow` 文件中的引用会失效（README 声称"重命名会同步更新所有引用该模板的节点"，仅指当前画布）。建议至少重名时报错。

### 🟡 B10. 版本号不一致

`installer/AutoGameTool.nsi` `APP_VERSION "0.1.0"`、`VIProductVersion "0.1.0.0"`，而 `main.py` 与 health 接口返回 `0.2.0`。安装包元数据与实际程序版本脱节，影响升级判断（NSIS 升级逻辑只看是否安装过，不看版本，暂时无害但属隐患）。建议版本号收敛到单一来源。

---

## 三、健壮性 / 可维护性问题

| # | 位置 | 问题与建议 |
|---|---|---|
| R1 | `Editor.vue:684` | **每 1 秒全量** `POST /flow/load`（含 macro 的全部 events，可能几十 KB），叠加 150ms 防抖 watcher，空闲时也在持续打引擎。建议：仅当流程指纹（哈希）变化时同步，或只在失焦/保存/录制完成等时机同步 |
| R2 | `vision.grab_frame`、`window.capture_window_fast` | 每次调用都 `with mss.mss()` 新建实例（涉及 DC 分配），0.2s 轮询场景浪费明显。建议复用线程内单例 mss |
| R3 | `window.capture_window:115-118` | 截图函数有**副作用**：窗口最小化时自动 `ShowWindow(SW_RESTORE)` 弹出窗口。挂机场景"窗口被最小化→截图"会突然把游戏弹到前台，可能正是用户不希望的。建议改为返回明确错误，由上层（或新增参数）决定是否恢复 |
| R4 | `window.py` GetWindowRect | Win10/11 窗口 rect 含不可见 DWM 缩放边框（约 7px），`find_image` 点击坐标按"窗口 rect 左上 + 截图内偏移"换算，对 PrintWindow 截图是自洽的，但与"客户区"语义有细微偏差；若日后混用 `GetClientRect` 截图会出现系统级偏移。建议注释说明坐标基准，必要时用 `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` 校正 |
| R5 | `executor.py:75-109` | 执行器无环检测：用户画出"无 terminate 的环"时单轮永不结束（repeat 里的外层循环永远进不去）。对挂机可能是有意行为，但建议在启动时检测"环中无 terminate/终止路径"并告警 |
| R6 | `executor.py:62-66` | 多个起始节点时静默取 `starts[0]`，孤立节点（无入边也无出边）不会被任何提示。建议启动前校验连通性并列出不可达节点 |
| R7 | `ws_manager.py` | 广播是串行 `await`，某个 WS 客户端接收慢会拖慢整体日志推送；可改为 `asyncio.gather` 并发发送。`disconnect` 只在 `WebSocketDisconnect` 时调用，其他异常（如 `RuntimeError`）会留下死连接（broadcast 里虽有兜底 discard，但仍建议 ws_endpoint 捕获 `Exception`） |
| R8 | `hotkey.py:53-62` | `set()` 不校验按键名合法性，空列表会静默"关闭快捷键"；`config.json` 非原子写（断电/崩溃会截断）。建议校验 + 临时文件写后 rename |
| R9 | `recorder.py:12` | `from hotkey import _norm` 跨模块 import 私有函数，建议把 `_norm` 提为公共工具（如放 keybus） |
| R10 | `executor.py:99` / `recorder.stop` | 录制停止时清理热键残留事件只剥头尾各一个，组合键 alt+9 中途事件残留的边界情况仍可能漏；可按"时间戳接近停止时刻且 key ∈ hotkey"过滤 |
| R11 | `inputctl._key_lparam` | 未设置 extended-key 位（bit 24），方向键/Ins/Del 等扩展键在部分程序中会错乱；`_mouse_lparam` 负坐标（多显示器左侧）未处理符号位 |
| R12 | `main.py:106-108` | 快捷键回调里 `manager.connections` 为空时直接引擎侧 `executor.toggle()`，与前端链路并存；若前端 WS 已连但页面处于后台，浏览器节流可能造成双触发观感。可统一走前端链路或加 50ms 去抖 |
| R13 | `frontend/src/api/client.ts` | `apiGet/apiPost` 抛出的错误文本是 JSON 字符串（FastAPI 的 `{"detail": ...}`），前端直接 `e.message` 展示原始 JSON，不友好；建议解析 detail |
| R14 | `ScreenCapture.vue` | `stage` 可滚动时框选的坐标换算未显式补偿 `scrollTop/scrollLeft`（依赖 `getBoundingClientRect` 的行为），大截图滚动后框选可能偏移；建议用 `img` 自身的 rect 计算并在文档中固化行为 |
| R15 | `build_exe.ps1:82` | `Copy-Item -Force` 覆盖正在运行/被占用的 exe 会直接抛错中断，可先检测文件锁并提示 |
| R16 | NSIS `.onInit` | `ExecWait '"$R0" /S _?=$INSTDIR'` 中 `$INSTDIR` 依赖 `InstallDirRegKey` 时序，若旧版本装在非默认目录，`_?=` 指向的可能是新默认目录，导致旧卸载器把文件删错位置。建议从 `$R0` 反推旧安装目录再传参 |
| R17 | 依赖管理 | `engine/requirements.txt` 未在 CI 中锁定哈希；`build_installer.ps1` 自动从 SourceForge 下载 NSIS 无校验和（构建机供应链风险，建议固定 SHA256 校验） |

---

## 四、做得好的地方（保持）

- **事件总线**（keybus/mousebus 单例常驻钩子）是对 Windows 低级钩子易碎性的正确工程化，注释清晰。
- `np.fromfile + cv2.imdecode` 规避 OpenCV 非 ASCII 路径缺陷，处理到位。
- `inputctl` 对所有 ctypes 函数显式设置 restype/argtypes，避免 64 位句柄截断——很多同类项目都栽在这里。
- PrintWindow 失败/黑屏的显式错误提示、模拟输入的 `/input/probe` 诊断接口，排错体验好。
- NSIS 安装脚本考虑了旧版静默卸载、非默认安装目录的防误删（目录名校验），测试脚本（smoke_test / test_installer）齐备。
- UTF-8 BOM 编码约定 + `to-utf8-bom.ps1` 检查工具，规避 PowerShell 5.1 乱码坑。

---

## 五、修复优先级建议

| 优先级 | 事项 |
|---|---|
| P0（发布阻断） | S1 去掉 CORS `*`/加 token；S2 路径遍历修复；S3 去掉 `/debug/kb` 的 `last` 字段 |
| P1（尽快） | S4 模板名消毒；B1 `/run` 校验与 running 卡死；B2 组合键；B5 create_task 引用 |
| P2 | B3 win 键；B4 模拟模式滚轮；B6 节点 ID 冲突；B8 事件循环阻塞；B10 版本统一 |
| P3 | R1–R17 按需排入迭代 |

**总体评价**：工程结构清晰、注释和文档质量高于平均水平，"关键设计说明"一节显示了对 Windows 平台坑的认真对待。主要短板集中在**本地服务的攻击面**（无鉴权 + CORS 全开 + 两处路径遍历 + 调试接口泄露按键）——对一个能"代替人敲键盘"的工具来说，这是发布前必须补上的一课；其次是执行器对畸形输入的容错和几个前后端契约不一致的组合键链路。
