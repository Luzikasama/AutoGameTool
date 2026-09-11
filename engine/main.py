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
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import vision
from executor import Executor
from hotkey import HotkeyManager
from picker import CoordinatePicker
from recorder import Recorder
from window import capture_window, get_window_rect, list_windows
from ws_manager import manager


def get_frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend_dist"
    return Path(__file__).resolve().parent / "frontend_dist"


class TemplateCapture(BaseModel):
    name: str | None = None
    image: str


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


executor = Executor(manager.broadcast)
hotkey_manager: HotkeyManager | None = None
picker: CoordinatePicker | None = None
recorder: Recorder | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _setup_hotkey() -> None:
    global hotkey_manager, picker, recorder, _loop
    _loop = asyncio.get_running_loop()

    def _cb() -> None:
        def _notify() -> None:
            # 有前端连接时通知前端执行（前端调用 /run，与点击“运行”完全一致）
            if manager.connections:
                asyncio.create_task(manager.broadcast({"type": "hotkey", "ts": time.time()}))
            else:
                asyncio.create_task(executor.toggle())

        if _loop:
            _loop.call_soon_threadsafe(_notify)

    hotkey_manager = HotkeyManager(_cb)
    print(
        f"[AutoGameTool] 全局快捷键已注册: 启停={'+'.join(hotkey_manager.get())} 录制=alt+9",
        flush=True,
    )

    def _on_picked(x: int, y: int) -> None:
        if _loop:
            _loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    manager.broadcast({"type": "picked", "x": x, "y": y, "ts": time.time()})
                )
            )

    picker = CoordinatePicker(_on_picked)

    def _record_state(recording: bool) -> None:
        if _loop:
            _loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    manager.broadcast({"type": "recording", "recording": recording, "ts": time.time()})
                )
            )

    def _on_recorded(events: list) -> None:
        if _loop:
            _loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    manager.broadcast({"type": "recorded", "events": events, "ts": time.time()})
                )
            )

    recorder = Recorder(_record_state, _on_recorded)


@asynccontextmanager
async def lifespan(_: FastAPI):
    vision.ensure_template_dir()
    _setup_hotkey()
    yield
    executor.stop()
    if hotkey_manager:
        hotkey_manager.stop()
    if picker:
        picker.stop()
    if recorder:
        recorder.stop_all()


app = FastAPI(title="AutoGameTool Engine", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "autogametool", "version": "0.2.0"}


@app.get("/debug/kb")
async def debug_kb():
    import keybus as _kb

    return _kb.counts()


@app.get("/windows/list")
async def api_list_windows():
    return {"windows": list_windows()}


@app.get("/screen/screenshot")
async def screenshot(window: int | None = None):
    if window:
        frame = capture_window(window)
    else:
        frame = vision.grab_frame()
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
    vision.delete_template(req.id)
    return {"ok": True}


@app.post("/vision/capture_template")
async def capture_template(req: TemplateCapture):
    try:
        img = vision.decode_image_b64(req.image)
    except Exception as e:
        raise HTTPException(400, f"图像解码失败: {e}")
    tpl_id = vision.save_template(img, req.name)
    return {"id": tpl_id}


@app.post("/vision/match")
async def match(req: MatchRequest):
    try:
        template = vision.load_template(req.template)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    offset_x = offset_y = 0
    if req.window:
        rect = get_window_rect(req.window)
        offset_x, offset_y = rect["left"], rect["top"]
        frame = capture_window(req.window)
    else:
        frame = vision.grab_frame()
    found, x, y, score = vision.match_template(frame, template, req.threshold)
    result = {"found": found, "x": x + offset_x, "y": y + offset_y, "score": score}
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
    executor.current_flow = req.flow
    return {"ok": True}


@app.post("/run")
async def run(req: RunRequest):
    if executor.running:
        raise HTTPException(409, "已有流程在运行")
    asyncio.create_task(executor.run(req.flow))
    return {"ok": True}


@app.post("/run/stop")
async def stop():
    executor.stop()
    return {"ok": True}


@app.get("/config/hotkey")
async def get_hotkey():
    return {"hotkey": hotkey_manager.get() if hotkey_manager else ["alt", "f1"]}


@app.post("/config/hotkey")
async def set_hotkey(req: HotkeyRequest):
    if hotkey_manager:
        hotkey_manager.set(req.hotkey)
        return {"hotkey": hotkey_manager.get()}
    return {"hotkey": req.hotkey}


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
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ---- 前端静态资源（打包后由引擎同源提供）----
_frontend_dir = get_frontend_dir()
if (_frontend_dir / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dir / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path:
            candidate = _frontend_dir / full_path
            if candidate.is_file():
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
        threading.Thread(target=lambda: webbrowser.open("http://127.0.0.1:8765"), daemon=True).start()
        time.sleep(0.5)
        sys.exit(0)

    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8765")

    # 设置 AUTOGAMETOOL_NO_BROWSER=1 可禁止自动打开浏览器（自动化测试 / 无人值守场景）
    if os.environ.get("AUTOGAMETOOL_NO_BROWSER", "").strip().lower() in ("1", "true", "yes", "on"):
        print("[AutoGameTool] 已按 AUTOGAMETOOL_NO_BROWSER 跳过自动打开浏览器。", flush=True)
    else:
        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=8765)
