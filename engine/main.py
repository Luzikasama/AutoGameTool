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
import overlay
import vision
from executor import Executor, validate_flow
from hotkey import HotkeyManager
from picker import CoordinatePicker
from recorder import Recorder
from window import capture_window, find_webui_window, focus_window, get_window_rect, is_minimized, list_windows
from ws_manager import manager


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


class OverlayRequest(BaseModel):
    enabled: bool


executor = Executor(manager.broadcast)
hotkey_manager: HotkeyManager | None = None
picker: CoordinatePicker | None = None
recorder: Recorder | None = None
_loop: asyncio.AbstractEventLoop | None = None


_REPEAT_MIN, _REPEAT_MAX = 1, 9999
_repeat_value = 1
# 页面标题（frontend/index.html 的 <title>），用于定位 WebUI 所在窗口
_WEBUI_TITLE_HINT = "AutoGameTool"


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


async def _toggle_run() -> None:
    """启停流程：全局快捷键与悬浮框按钮共用这一条链路。

    有前端连接时通知前端执行（前端调用 /run，保证跑的是画布上最新的流程）；
    否则退化为引擎侧 toggle（使用最近一次 /flow/load 的流程）。
    """
    if manager.connections:
        await manager.broadcast({"type": "hotkey", "ts": time.time()})
    else:
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


def _change_repeat(delta: int) -> int:
    global _repeat_value
    _repeat_value = max(_REPEAT_MIN, min(_REPEAT_MAX, _repeat_value + delta))
    overlay.set_repeat(_repeat_value)
    flow = executor.current_flow
    if isinstance(flow, dict):
        # 无前端连接时，引擎侧也能按新的轮数执行
        flow["repeat"] = _repeat_value
    return _repeat_value


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
        await _toggle_run()
    elif name == "toggle_record":
        _toggle_record()
    elif name in ("repeat_up", "repeat_down"):
        value = _change_repeat(1 if name == "repeat_up" else -1)
        await manager.broadcast({"type": "repeat", "value": value, "ts": time.time()})
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

    def _cb() -> None:
        if _loop:
            _loop.call_soon_threadsafe(lambda: _spawn(_toggle_run()))

    hotkey_manager = HotkeyManager(_cb)
    print(
        f"[AutoGameTool] 全局快捷键已注册: 启停={'+'.join(hotkey_manager.get())} 录制=alt+9",
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

    recorder = Recorder(_record_state, _on_recorded)


@asynccontextmanager
async def lifespan(_: FastAPI):
    vision.ensure_template_dir()
    _setup_hotkey()
    # 悬浮框：按上次的开关状态启动（不可用时内部自动降级，不影响其它功能）
    overlay.start(enabled=bool(appconfig.get("overlay", False)))
    yield
    overlay.stop()
    executor.stop()
    if hotkey_manager:
        hotkey_manager.stop()
    if picker:
        picker.stop()
    if recorder:
        recorder.stop_all()


app = FastAPI(title="AutoGameTool Engine", version="0.6.2", lifespan=lifespan)

# ---- 本地访问控制（安全）----
# 引擎监听 127.0.0.1，但浏览器里任何网页都能向它发请求（CSRF/DNS rebinding），
# 而引擎具备操控键鼠、截屏的能力，因此：
# 1) 所有 API 需要随机令牌（启动时生成，随浏览器 URL 传给前端）；
# 2) 打包运行与前端同源，不需要 CORS——仅开发模式(AUTOGAMETOOL_DEV=1)放开 vite 端口；
# 3) 校验 Host 头，防 DNS rebinding。
# 自动化测试可设 AUTOGAMETOOL_TOKEN 固定令牌。
_ENGINE_TOKEN = os.environ.get("AUTOGAMETOOL_TOKEN", "").strip() or secrets.token_urlsafe(24)
_DEV_MODE = os.environ.get("AUTOGAMETOOL_DEV", "").strip().lower() in ("1", "true", "yes", "on")
_ENTRY_URL = f"http://127.0.0.1:8765/?token={_ENGINE_TOKEN}"

_ALLOWED_HOSTS = {"127.0.0.1:8765", "localhost:8765", "[::1]:8765"}
# 需要令牌保护的 API 前缀（新增 API 路由时必须加入此列表）
_PROTECTED_PREFIXES = (
    "/debug", "/windows", "/screen", "/vision", "/input",
    "/flow", "/run", "/config", "/pick", "/record", "/overlay",
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
    return {"status": "ok", "engine": "autogametool", "version": "0.6.2"}


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
        _sync_repeat(req.flow)
        executor.task = _spawn(executor.run(req.flow))
    return {"ok": True}


@app.post("/run/stop")
async def stop():
    executor.stop()
    # stop() 会在「没有实际任务在跑」时直接复位 running；这里再 reconcile 兜底，
    # 保证返回的是真实状态，前端按钮不会卡在「停止」
    executor.reconcile()
    return {"ok": True, "running": executor.running}


@app.get("/run/state")
async def run_state():
    """前端 WS 重连 / 定时轮询时同步真实运行状态。

    reconcile() 兜底任何让 executor.run() 的 finally 未能执行的异常路径：
    任务已结束却仍标记运行中时自动复位，前端 1 秒轮询即可自愈。
    """
    executor.reconcile()
    return {"running": executor.running}


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
        return {"hotkey": hotkey_manager.get()}
    return {"hotkey": req.hotkey}


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


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # WebSocket 同样校验令牌（网页可跨域发起 WS 连接，不校验则日志/事件全部泄露）
    if not _DEV_MODE and ws.query_params.get("token", "") != _ENGINE_TOKEN:
        await ws.close(code=4401)
        return
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


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
        print("[AutoGameTool] 检测到程序已在运行，本次启动退出（避免多开导致快捷键冲突）。", flush=True)
        threading.Thread(target=lambda: webbrowser.open(_ENTRY_URL), daemon=True).start()
        time.sleep(0.5)
        sys.exit(0)

    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(_ENTRY_URL)

    print(f"[AutoGameTool] 编辑器地址: {_ENTRY_URL}", flush=True)

    # 设置 AUTOGAMETOOL_NO_BROWSER=1 可禁止自动打开浏览器（自动化测试 / 无人值守场景）
    if os.environ.get("AUTOGAMETOOL_NO_BROWSER", "").strip().lower() in ("1", "true", "yes", "on"):
        print("[AutoGameTool] 已按 AUTOGAMETOOL_NO_BROWSER 跳过自动打开浏览器。", flush=True)
    else:
        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        uvicorn.run(app, host="127.0.0.1", port=8765)
    except OSError as e:
        print(f"[AutoGameTool] 引擎启动失败：{e}（端口 8765 可能被其他程序占用）", flush=True)
        sys.exit(1)
