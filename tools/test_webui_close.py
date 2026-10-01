"""端到端测试：页面离开后端会不会跟着退出（v0.8.1 起的新规则）。

规则（都是被真机事故逼出来的）：
  1. 从未有页面连过            → 永不退出（NO_BROWSER 无人值守 / 冒烟测试场景）
  2. 页面**静默掉线**          → **不退出**（浏览器挂起/丢弃标签页、崩溃都长这样，
                                 挂机不能因此中断——实测踩过：6 秒后引擎自杀、悬浮框消失）
  3. 断开后立刻重连（模拟 F5）  → 不退出
  4. 页面**主动告别**（/goodbye）→ 宽限期后退出（用户确实关了页面）
  5. 流程**正在运行**时告别     → 不退出（挂机优先）
  6. AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1 → 恢复旧行为：静默掉线也退出

实现要点：
  - 用同一个解释器跑 engine/main.py，不依赖打包产物（跑得快、失败信息全）
  - APPDATA 指向项目内 .tmp 目录：**绝不碰用户自己的 %APPDATA%\\AutoGameTool**
  - 引擎输出重定向到文件而不是管道：受限环境下管道容易出问题，文件更稳

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_webui_close.py

     # 也可以直接验打包后的 exe（发布前更该跑这个）
     $env:AUTOGAMETOOL_TEST_EXE = ".\\AutoGameTool.exe"
     engine\\.venv\\Scripts\\python.exe tools\\test_webui_close.py
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
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
# 设了 AUTOGAMETOOL_TEST_EXE 就测打包产物，否则测源码（跑得快、报错更详细）
TEST_EXE = os.environ.get("AUTOGAMETOOL_TEST_EXE", "").strip()
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/ws"
TOKEN = "e2e-close-test"
GRACE = 6.0            # 旧行为的宽限期（EXIT_ON_PAGE_LOSS=1 时使用）
GOODBYE_GRACE = 5.0    # 页面主动告别后的宽限期（与 engine/main.py 的 _GOODBYE_GRACE_SEC 一致）
TMP = ROOT / ".tmp"

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


def engine_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env["APPDATA"] = str(TMP / "e2e-appdata")
    env["AUTOGAMETOOL_NO_BROWSER"] = "1"
    env["AUTOGAMETOOL_TOKEN"] = TOKEN
    env.pop("AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE", None)
    env.pop("AUTOGAMETOOL_EXIT_ON_PAGE_LOSS", None)
    if extra:
        env.update(extra)
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


def start_engine(tag: str, extra_env: dict | None = None) -> tuple:
    log_path = TMP / f"e2e-engine-{tag}.log"
    log = open(log_path, "w", encoding="utf-8")
    if TEST_EXE:
        exe = Path(TEST_EXE)
        if not exe.is_absolute():
            exe = (ROOT / TEST_EXE).resolve()
        cmd, cwd = [str(exe)], str(exe.parent)
    else:
        cmd, cwd = [str(PY), "main.py"], str(ENGINE)
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=engine_env(extra_env),
        stdout=log, stderr=subprocess.STDOUT,
    )
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
            # --onefile 的 bootloader 会派生真正的应用子进程，
            # 只 terminate 父进程会留下孤儿子进程占着 8765 端口。/T 连子进程一起结束。
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
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
                proc.wait(timeout=5)


def wait_exit(proc, seconds: float) -> float:
    """等待进程退出，返回耗时；超时返回 -1。"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        if proc.poll() is not None:
            return time.time() - t0
        time.sleep(0.25)
    return -1.0


def api(path: str) -> int:
    req = urllib.request.Request(BASE + path + f"?token={TOKEN}", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1


def api_no_token(path: str) -> int:
    """不带令牌调用（用于确认这些接口确实要鉴权）。"""
    req = urllib.request.Request(BASE + path, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1


def log_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def engine_log_mark() -> int:
    """产物日志（enginelog 写的那份）当前长度：断言只看本轮新增的部分。"""
    p = TMP / "e2e-appdata" / "AutoGameTool" / "engine.log"
    try:
        return p.stat().st_size
    except Exception:
        return 0


def engine_log_since(mark: int) -> str:
    """读引擎日志（enginelog 落盘那份）从 mark 开始的内容。

    为什么不用 stdout 那份：enginelog 把日志写进文件，stdout 只留 print 的内容。
    必须共享读（FileShare.ReadWrite），否则日志开着时读会报"正由另一进程使用"。
    """
    p = TMP / "e2e-appdata" / "AutoGameTool" / "engine.log"
    try:
        fs = open(p, "rb")
    except Exception:
        return ""
    try:
        fs.seek(mark)
        return fs.read().decode("utf-8", errors="replace")
    finally:
        fs.close()


async def ws_hold(seconds: float) -> None:
    """连上 WebSocket、保持一会儿、然后关闭（模拟标签页被挂起/丢弃后 socket 断掉）。"""
    import websockets

    async with websockets.connect(f"{WS_URL}?token={TOKEN}", open_timeout=6) as ws:
        await ws.send("hello")
        await asyncio.sleep(seconds)


def start_long_flow() -> None:
    """通过 HTTP 让引擎跑一个 30 秒的流程（模拟挂机中）。"""
    flow = {
        "name": "webui-close-test",
        "repeat": 1,
        "input_mode": "simulated",
        "nodes": [{"id": "n1", "type": "delay", "params": {"ms": 30000}}],
        "edges": [],
    }
    body = json.dumps({"flow": flow}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/run", data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5).read()


def main() -> int:
    if not PY.is_file():
        print(f"未找到解释器：{PY}")
        return 1
    if not port_free():
        print(f"端口 {PORT} 已被占用：请先退出正在运行的 AutoGameTool 再跑本测试")
        return 1
    TMP.mkdir(parents=True, exist_ok=True)

    print("== 用例 1：从未有页面连接过 → 不应自动退出 ==")
    proc, log, log_path = start_engine("1")
    try:
        time.sleep(GRACE + 5.0)
        check("无页面连接时进程存活", proc.poll() is None, f"exit={proc.poll()}")
    finally:
        stop_engine(proc)
        log.close()

    print("== 用例 2：页面静默掉线（挂起/丢弃/崩溃）→ 不再退出 ==")
    mark = engine_log_mark()
    proc, log, log_path = start_engine("2")
    try:
        asyncio.run(ws_hold(1.0))
        took = wait_exit(proc, GRACE + 6.0)
        check("静默掉线后进程仍存活（挂机不中断）", took < 0, f"{took:.1f}s 后退出")
        txt = engine_log_since(mark)
        check("日志写明「后端继续运行，等待页面重连」", "后端继续运行" in txt, txt[-300:])
        try:
            urllib.request.urlopen(BASE + "/health", timeout=3).read()
            check("掉线后 /health 仍可访问", True)
        except Exception as e:  # noqa: BLE001
            check("掉线后 /health 仍可访问", False, e)
        asyncio.run(ws_hold(1.0))
        check("掉线后页面重连成功且进程存活", proc.poll() is None, f"exit={proc.poll()}")
    finally:
        stop_engine(proc)
        log.close()

    print("== 用例 3：断开后重连（模拟刷新页面）→ 不退出；主动告别 → 退出 ==")
    mark = engine_log_mark()
    proc, log, log_path = start_engine("3")
    try:
        asyncio.run(ws_hold(0.5))
        time.sleep(1.5)                      # 宽限期内重连
        asyncio.run(ws_hold(GRACE + 2.0))    # 再保持超过一个旧宽限期
        check("刷新式重连后进程存活", proc.poll() is None, f"exit={proc.poll()}")
        check("告别接口需要令牌（无令牌 401）", api_no_token("/goodbye") == 401, api_no_token("/goodbye"))
        code = api("/goodbye")
        check("告别接口返回 200", code == 200, code)
        took = wait_exit(proc, GOODBYE_GRACE + 14.0)
        check("主动告别后自动退出", took >= 0, "超时未退出")
        if took >= 0:
            check(f"退出不早于告别宽限期({GOODBYE_GRACE}s)", took >= GOODBYE_GRACE - 1.5, f"{took:.1f}s")
        txt = engine_log_since(mark)
        check("日志记录了「页面主动关闭（收到告别信号）」",
              "页面主动关闭（收到告别信号）" in txt, txt[-400:])
    finally:
        stop_engine(proc)
        log.close()

    print("== 用例 4：流程正在运行时告别 → 不退出（挂机优先） ==")
    mark = engine_log_mark()
    proc, log, log_path = start_engine("4")
    try:
        # 必须真的连过一次页面：否则「从未有页面连过 → 永不退出」这条规则先挡住了，
        # 测不到「运行中不退后端」这个分支（第一版就踩了这个坑）
        asyncio.run(ws_hold(0.5))
        start_long_flow()
        check("长流程已开始运行", proc.poll() is None, f"exit={proc.poll()}")
        code = api("/goodbye")
        check("运行中也能收到告别", code == 200, code)
        time.sleep(GOODBYE_GRACE + 3.0)
        check("运行中不退后端（悬浮框与挂机保留）", proc.poll() is None, f"exit={proc.poll()}")
        txt = engine_log_since(mark)
        check("日志写明「流程仍在运行，保持后端与悬浮框（不退出）」",
              "流程仍在运行" in txt, txt[-400:])
    finally:
        stop_engine(proc)
        log.close()

    print("== 用例 5：AUTOGAMETOOL_EXIT_ON_PAGE_LOSS=1 → 恢复旧行为 ==")
    proc, log, log_path = start_engine("5", {"AUTOGAMETOOL_EXIT_ON_PAGE_LOSS": "1"})
    try:
        asyncio.run(ws_hold(1.0))
        took = wait_exit(proc, GRACE + 16.0)
        check("显式要求旧行为时，静默掉线仍会退出", took >= 0, "超时未退出")
        if took >= 0:
            check(f"退出时机不早于宽限期({GRACE}s)", took >= GRACE - 1.0, f"{took:.1f}s")
    finally:
        stop_engine(proc)
        log.close()

    print("")
    print("结果: PASS=" + str(_pass) + "  FAIL=" + str(_fail))
    if _fail:
        print("引擎日志留在 .tmp\\e2e-engine-*.log，可据此排查")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
