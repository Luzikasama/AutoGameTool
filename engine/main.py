"""AutoGameTool 引擎入口：FastAPI + WebSocket + 全局快捷键。"""
import ctypes as _ctypes

# 设置 DPI 感知，保证窗口坐标与截图像素一致
try:
    _ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        _ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# 日志要尽早接管：打包成无控制台后 stdout/stderr 都是 None，代码里原有的 print 会直接抛异常；
# 而且放在重依赖导入之前，才能把「导入失败」这类启动期异常也记进日志文件。
try:
    import enginelog

    _LOG_PATH = enginelog.setup()
except Exception:  # 日志不可用时引擎照常运行
    _LOG_PATH = None

import asyncio
import os
import secrets
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import appconfig
import hotkey
import overlay
import vision
from executor import Executor, validate_flow
from hotkey import HotkeyManager
from picker import CoordinatePicker
from recorder import Recorder
from window import capture_window, find_webui_window, focus_window, get_window_rect, is_minimized, list_windows
from ws_manager import manager

# 把「推给前端的日志」同时落盘：这样页面关掉/WebSocket 断开之后，运行过程仍然可查
try:
    manager.on_broadcast = enginelog.note_broadcast if _LOG_PATH else None
except Exception:  # 日志模块不可用（导入失败）时不影响引擎
    manager.on_broadcast = None


def get_frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend_dist"
    return Path(__file__).resolve().parent / "frontend_dist"


class TemplateCapture(BaseModel):
    name: str | None = None
    image: str
    # 捕获时的参考画面尺寸等元数据（分辨率自适应用），由前端随截图一起上报
    meta: dict | None = None


class RenameTemplateRequest(BaseModel):
    id: str
    new_name: str


class DeleteTemplateRequest(BaseModel):
    id: str


class MatchRequest(BaseModel):
    template: str
    threshold: float = 0.85
    window: int | None = None


class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"
    clicks: int = 1
    mode: str = "real"
    window: int | None = None


class KeyRequest(BaseModel):
    key: str
    mode: str = "real"
    window: int | None = None


class TextRequest(BaseModel):
    text: str
    mode: str = "real"
    window: int | None = None


class RunRequest(BaseModel):
    flow: dict


class HotkeyRequest(BaseModel):
    hotkey: list[str]


class HotkeysRequest(BaseModel):
    bindings: list[dict]


class OverlayRequest(BaseModel):
    enabled: bool


executor = Executor(manager.broadcast)
hotkey_manager: HotkeyManager | None = None
picker: CoordinatePicker | None = None
recorder: Recorder | None = None
_loop: asyncio.AbstractEventLoop | None = None


_REPEAT_MIN, _REPEAT_MAX = 1, 99999
_repeat_value = 1
# 页面标题（frontend/index.html 的 <title>），用于定位 WebUI 所在窗口
_WEBUI_TITLE_HINT = "AutoGameTool"

# 上一次广播出去的运行状态（None = 还没广播过），用于去重
_last_run_state: bool | None = None
_last_paused: bool | None = None

# 关闭 WebUI 后同步关闭后端的宽限期。
# 必须留宽限：刷新页面(F5)、前端热更新、短暂网络抖动都会先断开 WebSocket 再立刻重连，
# 若一断开就退出，「刷新一下」会变成「把后端也关了」。
_CLOSE_GRACE_SEC = 6.0
# 页面**主动告别**时的宽限（收到 /goodbye 之后）。比刷新所需的时间长一点即可：
# 刷新时新页面 2 秒内就连回来了，而用户真关页面时这点等待无感。
_GOODBYE_GRACE_SEC = 5.0
# 是否曾经有页面连上过。从未连过（NO_BROWSER 无人值守、冒烟测试）时永不自动退出
_ever_connected = False
_close_task: "asyncio.Task | None" = None
# 由 __main__ 注入：拿到 uvicorn Server 才能请求优雅退出（走完 lifespan 清理钩子）
_server = None


def _overlay_closed() -> None:
    """悬浮框上点 ✕：同步开关到前端并持久化。

    该回调由 Tk 线程触发，因此必须切回事件循环线程再做广播。
    """
    appconfig.update(overlay=False)
    if _loop is None:
        return
    _loop.call_soon_threadsafe(
        lambda: _spawn(manager.broadcast({"type": "overlay", "enabled": False, "ts": time.time()}))
    )


async def _sync_run_state(force: bool = False) -> bool:
    """把「真实运行状态」统一推给悬浮框与所有页面。

    这是启停状态的**唯一事实来源**：任何会改动 executor.running 的路径
    （/run、/run/stop、/run/pause、全局快捷键、悬浮框按钮、流程自然结束）都收敛到这里。
    前端本来就有 /run/state 轮询自愈，悬浮框却没有，于是两边一旦分叉就再也回不来：
    新版给悬浮框同等的自愈能力（配合 _state_watchdog 每秒兜底）。
    """
    global _last_run_state, _last_paused
    running = executor.reconcile()
    paused = bool(executor.paused) if running else False
    try:
        overlay.set_run_state(running)
        overlay.set_paused(paused)
    except Exception:
        pass
    if force or running != _last_run_state or paused != _last_paused:
        _last_run_state = running
        _last_paused = paused
        await manager.broadcast(
            {
                "type": "state",
                "state": "running" if running else "idle",
                "paused": paused,
                "ts": time.time(),
            }
        )
    return running


async def _state_watchdog() -> None:
    """每秒兜底同步一次运行状态。

    任何一条漏掉状态同步的代码路径，都会在 1 秒内被这里纠正，
    因此「WebUI 显示运行中、悬浮框还显示停止」这类分叉不会长期存在。
    """
    while True:
        try:
            await _sync_run_state()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(1.0)


async def _await_stop(timeout: float = 2.0) -> None:
    """等正在收尾的流程真正结束（最多 timeout 秒）。

    停止是协作式的：stop() 只置标志，流程要跑到下一个检查点才会退出。
    不等它的话，接口会在「还在收尾」时就返回 running=true，前端按钮继续亮着
    「停止」——那几百毫秒正是用户会反复点「停止」的窗口。
    shield 保证超时只放弃等待，绝不取消正在收尾的任务。
    """
    task = executor.task
    if task is None or task.done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except Exception:
        pass


async def _toggle_run(source: str = "快捷键") -> None:
    """启停流程：全局快捷键、悬浮框按钮与界面按钮共用这一条链路。

    关键设计：**「停止」一律在引擎侧直接执行，绝不委托给前端**。
    旧实现无论启停都只广播一个 hotkey、由前端按自己的 store.running 决定方向，
    一旦两边状态有偏差（流程异常结束、前端还没轮询到），
    「停止」就会变成"再启动一次"或被 409 挡掉——表现正是"反复点停止没反应"。

    启动优先让前端发起 /run（要用画布上最新的流程），但**不再盲目依赖它**：
    v0.8.1 起会等一小会儿看流程是否真的起来了，没起来就用引擎侧缓存的流程兜底。
    缓存流程由前端每秒 `/flow/load` 同步，永远是最新的；这条兜底正是为了
    「页面被系统挂起/丢弃时悬浮框启动按钮失灵」（实测踩到：连点 14 次毫无反应）。

    source 只用于日志：出问题时能一眼看出这次动作是快捷键还是悬浮框发起的。
    """
    if executor.reconcile():
        await executor.log("warn", f"{source}：停止脚本")
        executor.stop()
        await _await_stop()
        executor.reconcile()
        await _sync_run_state()
    else:
        await executor.log("info", f"{source}：启动脚本")
        started = False
        if manager.connections:
            await manager.broadcast({"type": "run_request", "ts": time.time()})
            # 最多等 1.2 秒：页面活着的话 /run 早就到了
            for _ in range(6):
                await asyncio.sleep(0.2)
                if executor.running:
                    started = True
                    break
            if not started:
                msg = (f"{source}：编辑器页面没有响应启动请求（可能被系统挂起/丢弃），"
                       "已改用引擎侧缓存的流程启动")
                enginelog.warn(msg)
                await executor.log("warn", msg)
        if not started:
            await executor.toggle()


def _toggle_record() -> None:
    if recorder is not None:
        recorder.toggle()


def _sync_repeat(flow: dict) -> None:
    """把流程里的循环轮数同步到引擎侧阴影值与悬浮框显示。"""
    global _repeat_value
    try:
        value = int(flow.get("repeat", 1))
    except (TypeError, ValueError):
        value = 1
    _repeat_value = max(_REPEAT_MIN, min(_REPEAT_MAX, value))
    overlay.set_repeat(_repeat_value)


def _set_repeat_to(value: int) -> int:
    """把循环轮数设为指定值（± 按钮与悬浮框里直接输入共用这一条）。

    夹取范围、同步悬浮框显示、更新引擎侧流程阴影值，三件事必须一起做，
    否则「悬浮框改了但真正执行时还是旧轮数」。
    """
    global _repeat_value
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = _repeat_value
    _repeat_value = max(_REPEAT_MIN, min(_REPEAT_MAX, v))
    overlay.set_repeat(_repeat_value)
    flow = executor.current_flow
    if isinstance(flow, dict):
        # 无前端连接时，引擎侧也能按新的轮数执行
        flow["repeat"] = _repeat_value
    return _repeat_value


def _change_repeat(delta: int) -> int:
    return _set_repeat_to(_repeat_value + delta)


async def _restore_audit(hwnd: int | None, why: str) -> None:
    """记录「是谁恢复了最小化的窗口」。

    这类操作只应发生在用户主动点击时（截取 / 测试匹配 / 悬浮框「界面」）。
    打一条醒目日志，万一再出现「最小化后又被弹出来」可以直接从日志定位来源。
    """
    if not hwnd:
        return
    try:
        if await asyncio.to_thread(is_minimized, hwnd):
            await manager.broadcast(
                {
                    "type": "log",
                    "level": "warn",
                    "message": f"{why}：目标窗口原本处于最小化，已恢复显示（不激活到前台）",
                    "step": None,
                    "ts": time.time(),
                }
            )
    except Exception:
        pass


async def _focus_webui() -> None:
    """把 WebUI 所在的浏览器窗口恢复并切到前台（悬浮框「界面」按钮）。

    注意只按标题找会命中同名文件夹的资源管理器窗口，因此 window.find_webui_window
    额外要求「类名/进程像浏览器」并排除 explorer.exe 与自身进程。
    """
    target = await asyncio.to_thread(find_webui_window, _WEBUI_TITLE_HINT)
    if not target:
        await manager.broadcast(
            {
                "type": "log",
                "level": "warn",
                "message": "未找到 WebUI 浏览器窗口：请确认 AutoGameTool 标签页仍开着（页面标题需含 AutoGameTool）",
                "step": None,
                "ts": time.time(),
            }
        )
        return
    ok = await asyncio.to_thread(focus_window, target["hwnd"])
    if not ok:
        await manager.broadcast(
            {
                "type": "log",
                "level": "warn",
                "message": f"无法切到 WebUI 窗口：{target['title']}",
                "step": None,
                "ts": time.time(),
            }
        )


async def _do_overlay_action(name: str) -> None:
    if name == "toggle_run":
        await _toggle_run("悬浮框")
    elif name == "toggle_pause":
        # 暂停/继续：与界面上的暂停按钮走同一套引擎侧状态
        executor.reconcile()
        if not executor.running:
            await _sync_run_state()
            return
        if executor.paused:
            executor.resume()
            await executor.log("info", "悬浮框：继续脚本")
        else:
            executor.pause()
            await executor.log("warn", "悬浮框：暂停脚本（在下一个检查点生效）")
        await _sync_run_state()
    elif name == "toggle_record":
        _toggle_record()
    elif name in ("repeat_up", "repeat_down"):
        value = _change_repeat(1 if name == "repeat_up" else -1)
        await manager.broadcast({"type": "repeat", "value": value, "ts": time.time()})
    elif name.startswith("repeat_set:"):
        # 悬浮框里直接输入循环次数（动作名带值：动作通道原本只传字符串，这里沿用它）
        try:
            wanted = int(name.split(":", 1)[1])
        except (IndexError, ValueError):
            return
        value = _set_repeat_to(wanted)
        await manager.broadcast({"type": "repeat", "value": value, "ts": time.time()})
        await executor.log("info", f"循环轮数设为 {value}")
    elif name == "focus_ui":
        await _focus_webui()


def _overlay_action(name: str) -> None:
    """悬浮框按钮回调（由 Tk 线程触发）→ 切回事件循环线程执行。"""
    if _loop is None:
        return
    _loop.call_soon_threadsafe(lambda: _spawn(_do_overlay_action(name)))


overlay.configure(on_close=_overlay_closed, on_action=_overlay_action)


def _setup_hotkey() -> None:
    global hotkey_manager, picker, recorder, _loop
    _loop = asyncio.get_running_loop()
    enginelog.install_loop_handler(_loop)

    def _cb_toggle_run() -> None:
        if _loop:
            _loop.call_soon_threadsafe(lambda: _spawn(_toggle_run("全局快捷键")))

    def _cb_record() -> None:
        # 与悬浮框/界面上的录制按钮走同一条路：切状态 + 广播
        if recorder:
            recorder.toggle()

    def _cb_pick() -> None:
        # 只是「进入等待左键单击」；拾取本身仍靠真实鼠标事件（见 picker.py）
        if picker:
            picker.arm()

    hotkey_manager = HotkeyManager(
        {"toggle_run": _cb_toggle_run, "record": _cb_record, "pick": _cb_pick}
    )
    print(
        "[AutoGameTool] 全局快捷键: "
        + "；".join(
            f"{b['label']}={'+'.join(b['keys']) if b['enabled'] else '未启用'}"
            for b in hotkey_manager.get_bindings()
        ),
        flush=True,
    )

    def _on_picked(x: int, y: int) -> None:
        if _loop:
            _loop.call_soon_threadsafe(
                lambda: _spawn(manager.broadcast({"type": "picked", "x": x, "y": y, "ts": time.time()}))
            )

    picker = CoordinatePicker(_on_picked)

    def _record_state(recording: bool) -> None:
        # 悬浮框的录制按钮要跟着真实状态走（该回调可能来自按键钩子线程）
        overlay.set_recording(recording)
        if _loop:
            _loop.call_soon_threadsafe(
                lambda: _spawn(manager.broadcast({"type": "recording", "recording": recording, "ts": time.time()}))
            )

    def _on_recorded(events: list) -> None:
        if _loop:
            _loop.call_soon_threadsafe(
                lambda: _spawn(manager.broadcast({"type": "recorded", "events": events, "ts": time.time()}))
            )

    recorder = Recorder(_record_state, _on_recorded, hotkey=hotkey_manager.keys_of("record"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    vision.ensure_template_dir()
    _setup_hotkey()
    # 悬浮框：按上次的开关状态启动（不可用时内部自动降级，不影响其它功能）
    overlay.start(enabled=bool(appconfig.get("overlay", False)))
    # 运行状态看门狗：悬浮框没有前端的 /run/state 轮询，靠它自愈
    watchdog = _spawn(_state_watchdog())
    st = overlay.state()
    enginelog.info(
        "引擎就绪：监听 127.0.0.1:8765，悬浮框 enabled=%s available=%s%s",
        st.get("enabled"), st.get("available"),
        f" 错误={st.get('error')}" if st.get("error") else "",
    )
    yield
    # 走到这里说明是「优雅退出」；把清理过程记下来，便于区分正常退出与异常终止
    enginelog.info("开始清理：停悬浮框 / 停流程 / 注销钩子")
    watchdog.cancel()
    overlay.stop()
    executor.stop()
    if hotkey_manager:
        hotkey_manager.stop()
    if picker:
        picker.stop()
    if recorder:
        recorder.stop_all()
    enginelog.info("清理完成，引擎退出")


app = FastAPI(title="AutoGameTool Engine", version="0.9.0", lifespan=lifespan)

# ---- 本地访问控制（安全）----
# 引擎监听 127.0.0.1，但浏览器里任何网页都能向它发请求（CSRF/DNS rebinding），
# 而引擎具备操控键鼠、截屏的能力，因此：
# 1) 所有 API 需要随机令牌（随浏览器 URL 传给前端）；
# 2) 打包运行与前端同源，不需要 CORS——仅开发模式(AUTOGAMETOOL_DEV=1)放开 vite 端口；
# 3) 校验 Host 头，防 DNS rebinding。
# 自动化测试可设 AUTOGAMETOOL_TOKEN 固定令牌。
def _load_or_create_token() -> str:
    """取本次运行的访问令牌：环境变量 > 已保存的 > 新生成并保存。

    为什么要把令牌**存下来**（v0.8.1）：以前每次启动都是新令牌，于是「程序已在运行时
    再双击一次」那条路径会用它自己那份**新令牌**打开浏览器页面，而真正在跑的引擎用的是
    旧令牌 —— 页面永远连不上，日志里只会反复出现「WebSocket 令牌校验失败」（实测踩到）。
    令牌只保护本机回环端口（防别的网页 CSRF），存在 %APPDATA%\\AutoGameTool 下与
    config.json 同等权限，不额外扩大攻击面。
    """
    env_token = os.environ.get("AUTOGAMETOOL_TOKEN", "").strip()
    if env_token:
        return env_token
    token_file = appconfig.config_dir() / "engine.token"
    try:
        if token_file.is_file():
            saved = token_file.read_text(encoding="utf-8").strip()
            if len(saved) >= 16:
                return saved
    except Exception:
        pass
    token = secrets.token_urlsafe(24)
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token, encoding="utf-8")
    except Exception:
        pass  # 存不下就本次会话用它，不影响使用
    return token


_ENGINE_TOKEN = _load_or_create_token()
# 告诉日志层：这串字面量必须被抹掉。无论它以什么形式出现在日志里（URL 参数、请求头、
# 或某处异常把请求原样回显），都会被替换成 *** ——不只是靠 "token=" 这个模式去猜。
enginelog.register_secret(_ENGINE_TOKEN)
_DEV_MODE = os.environ.get("AUTOGAMETOOL_DEV", "").strip().lower() in ("1", "true", "yes", "on")
_ENTRY_URL = f"http://127.0.0.1:8765/?token={_ENGINE_TOKEN}"

_ALLOWED_HOSTS = {"127.0.0.1:8765", "localhost:8765", "[::1]:8765"}
# 需要令牌保护的 API 前缀（新增 API 路由时必须加入此列表）
_PROTECTED_PREFIXES = (
    "/debug", "/windows", "/screen", "/vision", "/input",
    "/flow", "/run", "/config", "/pick", "/record", "/overlay", "/goodbye",
    "/open_external",
    "/docs", "/openapi.json",
)
_MAX_BODY_BYTES = 64 * 1024 * 1024  # 请求体上限 64MB（防内存 DoS）

if _DEV_MODE:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:1420", "http://127.0.0.1:1420"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def _guard(request: Request, call_next):
    host = (request.headers.get("host") or "").lower()
    if host and host.split("/")[0] not in _ALLOWED_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    try:
        if int(request.headers.get("content-length") or 0) > _MAX_BODY_BYTES:
            return JSONResponse({"detail": "请求体过大"}, status_code=413)
    except ValueError:
        pass
    if not _DEV_MODE:
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in _PROTECTED_PREFIXES):
            auth = request.headers.get("authorization", "")
            token = request.query_params.get("token", "")
            if auth != f"Bearer {_ENGINE_TOKEN}" and token != _ENGINE_TOKEN:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


# 后台任务强引用表：防止 create_task 的任务被 GC 中途取消
_bg_tasks: set = set()


def _spawn(coro) -> "asyncio.Task":
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


_run_lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "autogametool", "version": "0.9.0"}


@app.get("/debug/kb")
async def debug_kb():
    import keybus as _kb

    return _kb.counts()


@app.get("/windows/list")
async def api_list_windows():
    return {"windows": list_windows()}


@app.get("/screen/screenshot")
async def screenshot(window: int | None = None):
    try:
        if window:
            # 用户主动点击的截图/取模板：允许把最小化的窗口恢复出来（但不激活到前台）
            await _restore_audit(window, "截图")
            frame = await asyncio.to_thread(capture_window, window, True)
        else:
            frame = await asyncio.to_thread(vision.grab_frame)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "image": vision.frame_to_data_url(frame),
        "width": frame.shape[1],
        "height": frame.shape[0],
    }


@app.get("/vision/templates")
async def api_list_templates():
    return {"templates": vision.list_templates()}


@app.get("/vision/template/{tpl_id}/image")
async def api_get_template_image(tpl_id: str):
    try:
        img = vision.get_template_image(tpl_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))
    return {"image": vision.frame_to_data_url(img)}


@app.post("/vision/template/rename")
async def api_rename_template(req: RenameTemplateRequest):
    try:
        new_id = vision.rename_template(req.id, req.new_name)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"id": new_id}


@app.post("/vision/template/delete")
async def api_delete_template(req: DeleteTemplateRequest):
    try:
        vision.delete_template(req.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/vision/capture_template")
async def capture_template(req: TemplateCapture):
    try:
        img = vision.decode_image_b64(req.image)
    except Exception as e:
        raise HTTPException(400, f"图像解码失败: {e}")
    try:
        tpl_id = vision.save_template(img, req.name, req.meta)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": tpl_id}


@app.post("/vision/match")
async def match(req: MatchRequest):
    try:
        template = vision.load_template(req.template)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))
    meta = vision.load_template_meta(req.template)
    offset_x = offset_y = 0
    try:
        if req.window:
            rect = get_window_rect(req.window)
            offset_x, offset_y = rect["left"], rect["top"]
            # 用户主动点击的“测试匹配”：允许把最小化的窗口恢复出来（但不激活到前台）
            await _restore_audit(req.window, "测试匹配")
            frame = await asyncio.to_thread(capture_window, req.window, True)
        else:
            frame = await asyncio.to_thread(vision.grab_frame)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 分辨率自适应匹配：模板捕获分辨率与当前不同则自动缩放模板
    found, x, y, score, scale = await asyncio.to_thread(
        vision.match_template_auto, frame, template, meta, req.threshold
    )
    result = {"found": found, "x": x + offset_x, "y": y + offset_y, "score": score, "scale": scale}
    if found:
        result["annotated"] = vision.frame_to_data_url(vision.annotate_match(frame, template, x, y))
    return result


@app.post("/input/click")
async def api_click(req: ClickRequest):
    import inputctl

    inputctl.click(req.x, req.y, req.button, req.clicks, req.mode, req.window)
    return {"ok": True}


@app.post("/input/probe")
async def api_probe(req: ClickRequest):
    """诊断模拟输入：报告目标子窗口/焦点窗口/客户区坐标/PostMessage 结果。"""
    import inputctl

    if not req.window:
        raise HTTPException(400, "未绑定窗口")
    return inputctl.probe(req.window, req.x, req.y)


@app.post("/input/key")
async def api_key(req: KeyRequest):
    import inputctl

    inputctl.press_key(req.key, req.mode, req.window)
    return {"ok": True}


@app.post("/input/text")
async def api_text(req: TextRequest):
    import inputctl

    inputctl.type_text(req.text, req.mode, req.window)
    return {"ok": True}


@app.post("/flow/load")
async def load_flow(req: RunRequest):
    """仅加载流程（不执行），供快捷键启停使用。"""
    try:
        validate_flow(req.flow)
    except ValueError as e:
        raise HTTPException(400, str(e))
    executor.current_flow = req.flow
    _sync_repeat(req.flow)
    return {"ok": True}


@app.post("/run")
async def run(req: RunRequest):
    try:
        validate_flow(req.flow)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 加锁保证「检查-启动」原子性，防止并发 /run 双双通过检查
    async with _run_lock:
        if executor.running:
            raise HTTPException(409, "已有流程在运行")
        # 先置 running 再派生任务：/run/state 在任务起跑前就能反映真实状态，
        # 避免前端轮询在「POST 已返回、任务未起跑」的缝隙里读到假 idle 造成按钮闪烁
        executor.running = True
        executor.paused = False  # 新一轮不带上一轮遗留的暂停状态
        _sync_repeat(req.flow)
        executor.task = _spawn(executor.run(req.flow))
    # 立即把状态推给悬浮框：不等 executor.run() 被调度到，悬浮框按钮马上变「停止」
    await _sync_run_state()
    return {"ok": True}


@app.post("/run/stop")
async def stop():
    executor.stop()
    # 等流程真正收尾再返回，前端按钮就会在"确实已停止"的那一刻翻转
    await _await_stop()
    # stop() 会在「没有实际任务在跑」时直接复位 running；这里再 reconcile 兜底，
    # 保证返回的是真实状态，前端按钮不会卡在「停止」
    executor.reconcile()
    await _sync_run_state()
    return {"ok": True, "running": executor.running, "paused": executor.paused}


@app.post("/run/pause")
async def pause():
    """暂停：流程在下一个检查点停下，/run/resume 后从原地继续（与 /run/stop 不同）。"""
    executor.reconcile()
    if not executor.running:
        # 没在跑就没有可暂停的流程；明确回传真实状态，前端不会点亮「继续」
        await _sync_run_state()
        return {"ok": True, "running": False, "paused": False}
    executor.pause()
    await _sync_run_state()
    await executor.log("warn", "已暂停（在下一个检查点生效）")
    return {"ok": True, "running": executor.running, "paused": executor.paused}


@app.post("/run/resume")
async def resume():
    executor.resume()
    await _sync_run_state()
    if executor.running:
        await executor.log("info", "已继续")
    return {"ok": True, "running": executor.running, "paused": executor.paused}


@app.get("/run/state")
async def run_state():
    """前端 WS 重连 / 定时轮询时同步真实运行状态。

    reconcile() 兜底任何让 executor.run() 的 finally 未能执行的异常路径：
    任务已结束却仍标记运行中时自动复位，前端 1 秒轮询即可自愈。
    悬浮框侧由 _sync_run_state 一并纠正（它没有自己的轮询）。
    """
    running = await _sync_run_state()
    return {"running": running, "paused": bool(executor.paused) if running else False}


@app.get("/config/hotkey")
async def get_hotkey():
    return {"hotkey": hotkey_manager.get() if hotkey_manager else ["alt", "f1"]}


@app.post("/config/hotkey")
async def set_hotkey(req: HotkeyRequest):
    if hotkey_manager:
        try:
            hotkey_manager.set(req.hotkey)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if recorder:
            recorder.set_hotkey(hotkey_manager.keys_of("record"))
        return {"hotkey": hotkey_manager.get()}
    return {"hotkey": req.hotkey}


@app.get("/config/hotkeys")
async def get_hotkeys():
    """全部全局快捷键（含标签、当前键、是否启用），界面据此渲染设置列表。

    同时返回默认值：界面上的「恢复默认」直接用引擎这一份，避免前端再抄一遍默认表
    （抄一份就迟早会和引擎不一致）。
    """
    return {
        "bindings": hotkey_manager.get_bindings() if hotkey_manager else hotkey.DEFAULT_BINDINGS,
        "defaults": [{**b, "keys": list(b["keys"])} for b in hotkey.DEFAULT_BINDINGS],
    }


@app.post("/config/hotkeys")
async def set_hotkeys(req: HotkeysRequest):
    if not hotkey_manager:
        raise HTTPException(503, "引擎尚未就绪，请稍后重试")
    try:
        bindings = hotkey_manager.set_bindings(req.bindings)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if recorder:
        # 录制结果收尾时要把「按录制快捷键本身产生的按键」剔掉，改键后同步过去
        recorder.set_hotkey(hotkey_manager.keys_of("record"))
    enginelog.info(
        "全局快捷键已更新：%s",
        "；".join(f"{b['label']}={'+'.join(b['keys']) if b['enabled'] else '（未启用）'}" for b in bindings),
    )
    return {"bindings": bindings}


@app.get("/overlay/state")
async def get_overlay():
    """悬浮框状态：开关、是否可用、当前循环/总循环与正在执行的步骤。"""
    return overlay.state()


@app.post("/overlay/enable")
async def set_overlay(req: OverlayRequest):
    overlay.set_enabled(req.enabled)
    appconfig.update(overlay=req.enabled)
    state = overlay.state()
    if not state["available"]:
        raise HTTPException(500, state["error"] or "悬浮框不可用")
    # 广播给所有已连接页面，多标签页开关状态保持一致
    await manager.broadcast({"type": "overlay", "enabled": req.enabled, "ts": time.time()})
    return state


@app.post("/pick/start")
async def pick_start():
    if picker:
        picker.enable()
    return {"ok": True}


@app.post("/pick/cancel")
async def pick_cancel():
    if picker:
        picker.disable()
    return {"ok": True}


@app.post("/record/start")
async def record_start():
    if recorder:
        recorder.start()
    return {"ok": True, "recording": bool(recorder and recorder.recording)}


@app.post("/record/stop")
async def record_stop():
    if recorder:
        recorder.stop()
    return {"ok": True}


# ------------------------------------------------------------ 关闭页面即关闭后端
def _desktop_mode() -> bool:
    """是否由桌面壳（Tauri）拉起。

    桌面模式下有两处语义必须不同：
    1) 不自动开浏览器（壳自己开原生窗口）；
    2) **永不因为「页面没了」而退出**：关窗、刷新、WebView 崩溃都由壳负责收尾，
       引擎只负责活着；否则壳还在、引擎先自杀，界面就会变成一片「已断开」。
    """
    return os.environ.get("AUTOGAMETOOL_DESKTOP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _keep_alive_on_close() -> bool:
    """是否「无论如何都不退后端」（无人值守挂机的逃生开关）。"""
    if _desktop_mode():
        return True
    return os.environ.get("AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _exit_on_page_loss() -> bool:
    """静默掉线（页面被系统挂起/标签页被丢弃/浏览器崩溃）时是否照旧退出后端。

    v0.8.1 起**默认不退出**：区分「用户主动关了页面」与「页面不见了」。
    只有页面主动告别（前端在 pagehide 时发 /goodbye）才退；静默掉线一律继续跑，
    这样挂机不会因为浏览器把后台标签页挂起而中断（实测踩过：日志里只有
    「WebUI 已断开」，6 秒后引擎自己退出、悬浮框一起消失）。
    需要旧行为时设 AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1。
    """
    return os.environ.get("AUTOGAMETOOL_EXIT_ON_PAGE_LOSS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _cancel_close_timer() -> None:
    global _close_task
    if _close_task is not None and not _close_task.done():
        _close_task.cancel()
    _close_task = None


async def _close_when_no_page(grace: float, reason: str) -> None:
    """宽限期内没有页面重连 → 停止流程并退出后端。

    grace 由调用方决定：页面主动告别用短宽限（用户确实关了页面），
    静默掉线要么不退（默认）、要么用旧的长宽限（AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1）。
    """
    try:
        await asyncio.sleep(grace)
    except asyncio.CancelledError:
        return
    if manager.connections:
        return  # 宽限期内连回来了（刷新页面 / 前端热更新）
    if executor.reconcile():
        # 流程还在跑：绝不因为它而退后端（挂机优先），只记一条日志
        enginelog.warn("页面已离开但流程仍在运行，保持后端与悬浮框（不退出）")
        return
    enginelog.log_exit(f"{reason}，且 {grace:.0f} 秒内没有重连")
    print("[AutoGameTool] WebUI 已关闭，正在停止流程并退出后端…", flush=True)
    try:
        executor.stop()
        # 给正在跑的流程一点时间走完 finally（复位 running、释放钩子）再退出
        await asyncio.sleep(0.4)
    except Exception:
        pass
    _request_shutdown()


def _schedule_close_check(grace: float, reason: str) -> None:
    global _close_task
    if not _ever_connected or _keep_alive_on_close():
        return
    _cancel_close_timer()
    _close_task = _spawn(_close_when_no_page(grace, reason))


@app.post("/goodbye")
async def goodbye():
    """页面主动告别（关闭标签页 / 跳转离开）。只有这一条路径会真的关掉后端。"""
    enginelog.info("编辑器页面主动告别：若 %.0f 秒内没有页面重连就退出后端", _GOODBYE_GRACE_SEC)
    _schedule_close_check(_GOODBYE_GRACE_SEC, "页面主动关闭（收到告别信号）")
    return {"ok": True, "grace": _GOODBYE_GRACE_SEC}


class OpenExternalRequest(BaseModel):
    url: str


@app.post("/open_external")
async def open_external(req: OpenExternalRequest):
    """用系统默认浏览器打开外链（顶栏「关于 → GitHub 发布页」）。

    为什么由引擎来做而不是前端 `window.open`：桌面壳里的 `window.open` 会开出一个
    没有地址栏/前进后退的 Tauri 子窗口（GitHub 页面在里面很难用），而引擎天然能调
    系统浏览器；顺带这条路径在浏览器模式下也更好用。只放行 http/https。
    """
    url = (req.url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="只允许打开 http/https 链接")
    try:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"打开浏览器失败：{e}") from e
    return {"ok": True}


def _request_shutdown() -> None:
    """请求进程退出。

    优先让 uvicorn 优雅退出（会走 lifespan 里的清理：关悬浮框、注销钩子），
    只有拿不到 Server 实例时才兜底强退。
    """
    srv = _server
    if srv is not None:
        srv.should_exit = True
        return
    enginelog.warn("拿不到 uvicorn Server 实例，兜底强制退出")
    os._exit(0)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global _ever_connected
    # WebSocket 同样校验令牌（网页可跨域发起 WS 连接，不校验则日志/事件全部泄露）
    if not _DEV_MODE and ws.query_params.get("token", "") != _ENGINE_TOKEN:
        enginelog.warn("WebSocket 令牌校验失败，已拒绝连接")
        await ws.close(code=4401)
        return
    # 只允许一个 WebUI：多开页面会让「谁在控制流程」变得含糊（两边都显示运行状态、
    # 各自同步流程到引擎，互相覆盖），何况后端本来就只有一份。
    # 4409 = 已有页面占用；前端收到它会显示提示并自动重试，所以刷新页面(F5)依然能用
    # （刷新时旧连接会先断开，重试通常第一次就成功）。
    if manager.connections:
        enginelog.warn("已有编辑器窗口在运行（只允许一个 WebUI），已拒绝新的连接")
        await ws.accept()
        try:
            await ws.send_json({"type": "busy", "ts": time.time()})
        except Exception:
            pass
        await ws.close(code=4409)
        return
    await manager.connect(ws)
    _ever_connected = True
    enginelog.info("WebUI 已连接（当前 %d 个页面）", len(manager.connections))
    # 有页面连上就取消退出倒计时（含刷新页面时的重连）
    _cancel_close_timer()
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(ws)
        enginelog.info("WebUI 已断开（剩余 %d 个页面）", len(manager.connections))
        if not manager.connections:
            if _keep_alive_on_close():
                enginelog.warn("已无 WebUI 页面连接；AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE=1，后端继续运行")
            elif _exit_on_page_loss():
                # 旧行为（显式要求时）：静默掉线也退出
                enginelog.warn("已无 WebUI 页面连接；若 %.0f 秒内没有重连，将停止流程并退出后端"
                               "（AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1 指定的旧行为）", _CLOSE_GRACE_SEC)
                _schedule_close_check(_CLOSE_GRACE_SEC, "WebUI 页面全部断开")
            else:
                # v0.8.1 默认：静默掉线**不退后端**。页面可能是被系统挂起/丢弃/浏览器崩了，
                # 而挂机不该因此中断。真正关页面时前端会先发 /goodbye（那条路径才退）。
                enginelog.warn("已无 WebUI 页面连接；后端继续运行，等待页面重连"
                               "（只有页面主动告别才会退出）")


# ---- 前端静态资源（打包后由引擎同源提供）----
_frontend_dir = get_frontend_dir()
if (_frontend_dir / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dir / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path:
            # 安全：resolve 后必须仍在前端目录内，防 ../ 与编码点段路径遍历
            base = _frontend_dir.resolve()
            try:
                candidate = (base / full_path).resolve()
                candidate.relative_to(base)
            except (ValueError, OSError):
                candidate = None
            if candidate and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(_frontend_dir / "index.html")


def _fatal_dialog(title: str, text: str) -> None:
    """无控制台打包后，启动期致命错误必须用弹窗告知，否则用户只会看到"双击了没反应"。"""
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


if __name__ == "__main__":
    import ctypes
    import uvicorn
    from ctypes import wintypes

    # 单实例保护：多开会创建多个键盘钩子互相干扰，导致快捷键/录制异常
    _kernel32 = ctypes.windll.kernel32
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _single_mutex = _kernel32.CreateMutexW(None, False, "AutoGameTool_SingleInstance")
    if _kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        enginelog.warn("检测到已有实例在运行，本次启动退出")
        print("[AutoGameTool] 检测到程序已在运行，本次启动退出（避免多开导致快捷键冲突）。", flush=True)
        threading.Thread(target=lambda: webbrowser.open(_ENTRY_URL), daemon=True).start()
        time.sleep(0.5)
        sys.exit(0)

    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(_ENTRY_URL)

    # 控制台若存在，这里会显示带令牌的完整地址；落盘的那份会被 enginelog 掩成 token=***
    print(f"[AutoGameTool] 编辑器地址: {_ENTRY_URL}", flush=True)
    enginelog.info("引擎启动：版本 %s，日志文件 %s", app.version, _LOG_PATH or "（不可用）")

    # 设置 AUTOGAMETOOL_NO_BROWSER=1（或由桌面壳传入 AUTOGAMETOOL_DESKTOP=1）可禁止自动打开浏览器
    _skip_browser = _desktop_mode() or os.environ.get("AUTOGAMETOOL_NO_BROWSER", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if _skip_browser:
        _why = "AUTOGAMETOOL_DESKTOP=1（桌面壳）" if _desktop_mode() else "AUTOGAMETOOL_NO_BROWSER"
        print(f"[AutoGameTool] 已按 {_why} 跳过自动打开浏览器。", flush=True)
        enginelog.info("已按 %s 跳过自动打开浏览器", _why)
    else:
        threading.Thread(target=_open_browser, daemon=True).start()

    # 用 Config/Server 而不是 uvicorn.run：需要持有 Server 实例，
    # 才能在「用户关闭 WebUI 页面」时请求优雅退出（见 _request_shutdown）。
    # access_log 关掉：前端每秒两个轮询请求，开着会以每秒两行把日志的轮转窗口冲掉，
    # 反而看不到关键事件；WS 连接/断开与退出原因都另行显式记录。
    _server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8765, access_log=False)
    )
    try:
        _server.run()
        enginelog.log_exit("uvicorn 正常结束")
    except OSError as e:
        msg = f"引擎启动失败：{e}（端口 8765 可能被其他程序占用）"
        enginelog.error("%s", msg)
        print(f"[AutoGameTool] {msg}", flush=True)
        _fatal_dialog("AutoGameTool 启动失败", msg)
        sys.exit(1)
    except BaseException as e:  # 兜底：任何异常都要留下记录（无控制台时这是唯一的线索）
        enginelog.error("引擎异常退出：%r", e, exc_info=True)
        _fatal_dialog("AutoGameTool 异常退出", f"{type(e).__name__}: {e}\n\n详见日志：{_LOG_PATH}")
        raise
