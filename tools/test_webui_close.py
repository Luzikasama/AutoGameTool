"""端到端测试：关闭 WebUI 页面后，后端应自动退出。

这是本次改动里「最容易误伤用户」的一条：
万一判定写错，刷新一下页面（F5）就会把后端一起关掉。因此这里把三种时序都测一遍：

  1. 从未有页面连过          → 永不退出（NO_BROWSER 无人值守 / 冒烟测试场景）
  2. 连上再断开              → 宽限期后退出
  3. 断开后立刻重连（模拟刷新）→ 不退出；最终断开后才退出

实现要点：
  - 用同一个解释器跑 engine/main.py，不依赖打包产物（跑得快、失败信息全）
  - APPDATA 指向项目内 .tmp 目录：**绝不碰用户自己的 %APPDATA%\\AutoGameTool**
    （顺带保证悬浮框是关闭的，测试期间不弹窗）
  - 引擎输出重定向到文件而不是管道：受限环境下管道容易出问题，文件更稳

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_webui_close.py

     # 也可以直接验打包后的 exe（发布前更该跑这个）
     $env:AUTOGAMETOOL_TEST_EXE = ".\\AutoGameTool.exe"
     engine\\.venv\\Scripts\\python.exe tools\\test_webui_close.py
"""
import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
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
GRACE = 6.0            # 与 engine/main.py 的 _CLOSE_GRACE_SEC 一致
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


def engine_env() -> dict:
    env = dict(os.environ)
    env["APPDATA"] = str(TMP / "e2e-appdata")
    env["AUTOGAMETOOL_NO_BROWSER"] = "1"
    env["AUTOGAMETOOL_TOKEN"] = TOKEN
    env.pop("AUTOGAMETOOL_KEEP_ALIVE_ON_CLOSE", None)  # 确保测的是默认行为
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


def start_engine(tag: str) -> tuple:
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
        cmd, cwd=cwd, env=engine_env(),
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


async def ws_hold(seconds: float) -> None:
    """连上 WebSocket、保持一会儿、然后正常关闭（模拟关掉页面）。"""
    import websockets

    async with websockets.connect(f"{WS_URL}?token={TOKEN}", open_timeout=6) as ws:
        await ws.send("hello")
        await asyncio.sleep(seconds)


class RefreshScenario(threading.Thread):
    """在独立线程里跑「断开 → 重连 → 保持 → 再断开」。

    必须放到线程里：主线程要在「已重连、且已超过一个宽限期」的那一刻
    检查进程是否还活着，不能等整个协程跑完（那时计时器已经重新开始了）。
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.reconnected = threading.Event()
        self.finished = threading.Event()
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as e:  # 传到主线程再断言，避免线程里静默失败
            self.error = e
        finally:
            self.finished.set()

    async def _run(self) -> None:
        import websockets

        ws = await websockets.connect(f"{WS_URL}?token={TOKEN}", open_timeout=6)
        await ws.send("hello")
        await ws.close()                       # 断开 → 引擎开始 6 秒倒计时
        await asyncio.sleep(2.0)               # 在宽限期内重连（相当于按了 F5）
        ws2 = await websockets.connect(f"{WS_URL}?token={TOKEN}", open_timeout=6)
        await ws2.send("hello")
        self.reconnected.set()
        # 保持连接超过一个宽限期：主线程会在这段时间里确认进程没被误杀
        await asyncio.sleep(GRACE + 3.0)
        await ws2.close()                      # 最终断开 → 引擎应退出


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

    print("== 用例 2：连上再断开 → 宽限期后退出 ==")
    proc, log, log_path = start_engine("2")
    try:
        asyncio.run(ws_hold(1.0))
        took = wait_exit(proc, GRACE + 14.0)
        check("断开后自动退出", took >= 0, "超时未退出")
        if took >= 0:
            check(f"退出时机不早于宽限期({GRACE}s)", took >= GRACE - 1.0, f"{took:.1f}s")
    finally:
        stop_engine(proc)
        log.close()

    print("== 用例 3：断开后立刻重连（模拟刷新页面）→ 不应退出，最终断开才退出 ==")
    proc, log, log_path = start_engine("3")
    try:
        th = RefreshScenario()
        th.start()
        got = th.reconnected.wait(timeout=15.0)
        check("已成功重连", got, "重连超时")
        # 重连后已经过了一个宽限期：此刻进程必须还活着
        time.sleep(GRACE + 1.0)
        check("重连后进程仍存活（刷新页面不会关掉后端）", proc.poll() is None, f"exit={proc.poll()}")
        th.finished.wait(timeout=15.0)
        check("场景线程无异常", th.error is None, th.error)
        took = wait_exit(proc, GRACE + 14.0)
        check("最终断开后自动退出", took >= 0, "超时未退出")
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
