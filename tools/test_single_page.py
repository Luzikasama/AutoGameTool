"""端到端测试：只允许一个 WebUI + 全部快捷键可配置。

两条都是「写错了会让用户很困惑」的行为，所以起真引擎实测：

  1. 已有页面连接时，第二个 WebSocket 必须被拒绝（close code 4409 并先发一条 busy），
     而**第一个页面完全不受影响**；第一个关掉之后，新的连接必须能连上
     （否则刷新页面就会把自己锁在外面）
  2. `/config/hotkeys` 能读回三条默认绑定（alt+F1/F2/F3）、能改键、能单独停用；
     重复组合与「启用却没有键」必须被 400 拒绝；旧的 `/config/hotkey` 仍然可用

APPDATA 指向项目内 .tmp 目录：**绝不碰用户自己的 %APPDATA%\\AutoGameTool**
（顺带保证悬浮框是关闭的，测试期间不弹窗）。

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_single_page.py

     # 也可以直接验打包后的 exe
     $env:AUTOGAMETOOL_TEST_EXE = ".\\AutoGameTool.exe"
     engine\\.venv\\Scripts\\python.exe tools\\test_single_page.py
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
PY = ENGINE / ".venv" / "Scripts" / "python.exe"
TEST_EXE = os.environ.get("AUTOGAMETOOL_TEST_EXE", "").strip()
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/ws"
TOKEN = "e2e-single-page"
TMP = ROOT / ".tmp"
APPDATA = TMP / "e2e-appdata"

_pass = 0
_fail = 0


def check(name: str, cond: bool, extra: object = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print("  PASS  " + name)
    else:
        _fail += 1
        print("  FAIL  " + name + (("  -> " + str(extra)) if extra != "" else ""))


def engine_env() -> dict:
    env = dict(os.environ)
    env["APPDATA"] = str(APPDATA)
    env["AUTOGAMETOOL_NO_BROWSER"] = "1"
    env["AUTOGAMETOOL_TOKEN"] = TOKEN
    env.pop("AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE", None)
    return env


def port_free() -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_engine() -> tuple:
    log_path = TMP / "e2e-single.log"
    log = open(log_path, "w", encoding="utf-8")
    if TEST_EXE:
        exe = Path(TEST_EXE)
        if not exe.is_absolute():
            exe = (ROOT / TEST_EXE).resolve()
        cmd, cwd = [str(exe)], str(exe.parent)
    else:
        cmd, cwd = [str(PY), "main.py"], str(ENGINE)
    proc = subprocess.Popen(cmd, cwd=cwd, env=engine_env(), stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            break
        try:
            urllib.request.urlopen(BASE + "/health", timeout=1).read()
            return proc, log, log_path
        except Exception:
            time.sleep(0.4)
    log.close()
    tail = ""
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
    except Exception:
        pass
    raise RuntimeError(f"引擎未能就绪（exit={proc.poll()}）\n{tail}")


def stop_engine(proc) -> None:
    if proc.poll() is None:
        if TEST_EXE:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def api(path: str, method: str = "GET", body: dict | None = None) -> tuple:
    """返回 (status, 解析后的 JSON 或文本)。4xx 不抛异常，方便断言错误信息。"""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


async def ws_open():
    import websockets

    return await websockets.connect(f"{WS_URL}?token={TOKEN}", open_timeout=6)


async def ws_close_code(ws) -> int | None:
    """读一条消息（引擎拒绝时会先发 busy 再关），返回 close code。"""
    try:
        while True:
            await asyncio.wait_for(ws.recv(), timeout=5)
    except Exception:
        pass
    return ws.close_code


async def scenario() -> None:
    print("== 1. 快捷键：全部可配置 + 启用开关 ==")
    st, body = api("/config/hotkeys")
    bindings = body.get("bindings", []) if isinstance(body, dict) else []
    check("GET /config/hotkeys 可用", st == 200 and len(bindings) == 3, (st, body))
    check("默认是 alt+F1 / alt+F2 / alt+F3",
          [b.get("keys") for b in bindings] == [["alt", "f1"], ["alt", "f2"], ["alt", "f3"]],
          [b.get("keys") for b in bindings])
    check("默认全部启用", all(b.get("enabled") for b in bindings))
    check("带中文标签（界面直接显示引擎给的标签）",
          all(isinstance(b.get("label"), str) and b["label"] for b in bindings), bindings)
    check("三条绑定 id 稳定", [b.get("id") for b in bindings] == ["toggle_run", "record", "pick"])

    st, body = api("/config/hotkeys", "POST", {"bindings": [
        {"id": "toggle_run", "keys": ["ctrl", "F8"], "enabled": True},
        {"id": "record", "keys": ["alt", "f2"], "enabled": False},
        {"id": "pick", "keys": ["alt", "f3"], "enabled": True},
    ]})
    got = body.get("bindings", []) if isinstance(body, dict) else []
    check("改键成功（含键名规整 ctrl+f8）", st == 200 and got[0]["keys"] == ["ctrl", "f8"], (st, body))
    check("可以单独停用某一条", st == 200 and got[1]["enabled"] is False, got[1] if got else body)
    st2, body2 = api("/config/hotkeys")
    check("改键已生效（重新读取仍是新键）", body2["bindings"][0]["keys"] == ["ctrl", "f8"], body2)

    st, body = api("/config/hotkeys", "POST", {"bindings": [
        {"id": "toggle_run", "keys": ["ctrl", "f8"], "enabled": True},
        {"id": "record", "keys": ["ctrl", "f8"], "enabled": True},
    ]})
    detail = str(body.get("detail", body)) if isinstance(body, dict) else str(body)
    check("重复组合被 400 拒绝且说明原因", st == 400 and "相同" in detail, (st, detail))

    st, body = api("/config/hotkeys", "POST", {"bindings": [
        {"id": "record", "keys": [], "enabled": True}]})
    detail = str(body.get("detail", body)) if isinstance(body, dict) else str(body)
    check("启用却没有键被 400 拒绝", st == 400 and "快捷键" in detail, (st, detail))

    st, body = api("/config/hotkey")
    check("旧的单条接口仍返回启停快捷键", st == 200 and body.get("hotkey") == ["ctrl", "f8"], body)
    st, body = api("/config/hotkey", "POST", {"hotkey": ["alt", "f1"]})
    check("旧的单条接口仍可写入", st == 200 and body.get("hotkey") == ["alt", "f1"], body)

    print("== 2. 只允许一个 WebUI ==")
    import websockets

    ws1 = await ws_open()
    await asyncio.sleep(0.6)
    check("第一个页面连接成功", ws1.close_code is None, ws1.close_code)

    ws2 = await ws_open()
    code2 = await ws_close_code(ws2)
    check("第二个页面被拒绝（close code 4409）", code2 == 4409, code2)

    await asyncio.sleep(0.4)
    check("被拒绝不影响已连接的页面", ws1.close_code is None, ws1.close_code)
    st, body = api("/run/state")
    check("被拒绝后引擎功能正常（/run/state 可访问）", st == 200 and "running" in body, (st, body))

    await ws1.close()
    await asyncio.sleep(0.8)
    ws3 = await ws_open()
    await asyncio.sleep(0.6)
    check("原窗口关闭后新连接可以接管（刷新页面不会被锁死）", ws3.close_code is None, ws3.close_code)
    await ws3.close()

    print("== 3. 引擎日志留下线索 ==")
    log_file = APPDATA / "AutoGameTool" / "engine.log"
    text = ""
    if log_file.is_file():
        text = log_file.read_text(encoding="utf-8", errors="replace")
    check("日志记录了「只允许一个 WebUI」的拒绝",
          "只允许一个 WebUI" in text, text[-300:] if text else "（没有日志文件）")
    check("日志记录了快捷键已更新", "全局快捷键已更新" in text or "全局快捷键:" in text,
          text[-300:] if text else "")


def main() -> int:
    if not PY.is_file():
        print(f"未找到解释器：{PY}")
        return 1
    if not port_free():
        print(f"端口 {PORT} 已被占用：请先退出正在运行的 AutoGameTool 再跑本测试")
        return 1
    TMP.mkdir(parents=True, exist_ok=True)
    cfg = APPDATA / "AutoGameTool" / "config.json"
    if cfg.is_file():
        cfg.unlink()  # 从干净配置开始，避免上次跑留下的改键影响默认值断言

    proc, log, log_path = start_engine()
    try:
        asyncio.run(scenario())
    finally:
        stop_engine(proc)
        log.close()

    print("")
    print("结果: PASS=" + str(_pass) + "  FAIL=" + str(_fail))
    if _fail:
        print(f"引擎输出留在 {log_path}，日志留在 {APPDATA}\\AutoGameTool\\engine.log")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
