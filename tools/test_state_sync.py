"""端到端测试：WebUI 与悬浮框的启停状态必须始终一致，且「停止」真的能停。

对应三处曾经的问题：
  - WebUI 与悬浮框的启动/停止状态不一致（悬浮框只在流程起跑/结束时才更新）
  - 反复点悬浮框的「停止」没反应（前端按自己那份 running 决定方向，一旦偏差就点不动）
  - 长延时期间点停止像是没反应（delay 节点过去整段睡死，不检查停止标志）

做法：真起一个引擎进程，用 HTTP 走一遍「装载 → 启动 → 停止」，
每一步都比对 /run/state 与 /overlay/state 两份状态，并要求它们一致。

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_state_sync.py
"""
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
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "e2e-state-test"
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
    env["APPDATA"] = str(TMP / "e2e-state-appdata")
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


def api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def start_engine(tag: str):
    log_path = TMP / f"e2e-state-{tag}.log"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(PY), "main.py"], cwd=str(ENGINE), env=engine_env(),
        stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(80):
        if proc.poll() is not None:
            break
        try:
            api("/health")
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
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def states() -> tuple:
    """返回 (WebUI 侧状态, 悬浮框侧状态)。"""
    return bool(api("/run/state").get("running")), bool(api("/overlay/state").get("running"))


def wait_both_idle(seconds: float) -> tuple:
    """等待两边都变成「未运行」，返回 (最终状态对, 耗时)；超时返回 (None, -1)。"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        web, ov = states()
        if not web and not ov:
            return (web, ov), time.time() - t0
        time.sleep(0.2)
    return None, -1.0


# 一个「长延时」流程：足够长，能观察到运行中状态，又能在停止时立刻中断
FLOW = {
    "name": "state-sync-test",
    "repeat": 1,
    "input_mode": "simulated",
    "window": None,
    "nodes": [{"id": "n1", "type": "delay", "params": {"ms": 20000}, "once": False}],
    "edges": [],
}


def main() -> int:
    if not PY.is_file():
        print(f"未找到解释器：{PY}")
        return 1
    if not port_free():
        print(f"端口 {PORT} 已被占用：请先退出正在运行的 AutoGameTool 再跑本测试")
        return 1
    TMP.mkdir(parents=True, exist_ok=True)

    proc, log, log_path = start_engine("1")
    try:
        print("== 初始：两边都应为「未运行」 ==")
        web, ov = states()
        check("初始 /run/state = false", web is False, web)
        check("初始 /overlay/state = false", ov is False, ov)

        print("== 装载并启动流程 ==")
        api("/flow/load", "POST", {"flow": FLOW})
        api("/run", "POST", {"flow": FLOW})
        web, ov = states()
        check("启动后 /run/state = true", web is True, web)
        check("启动后悬浮框同步为 true（旧版这里会滞后）", ov is True, ov)
        check("两边一致", web == ov, f"web={web} overlay={ov}")

        print("== 停止：长延时必须被立刻中断 ==")
        r = api("/run/stop", "POST")
        check("/run/stop 返回 running=false", r.get("running") is False, r)
        pair, took = wait_both_idle(6.0)
        check("两边都回到「未运行」", pair is not None, "超时未停止")
        if pair is not None:
            check("停止在 2 秒内生效（delay 可被中断）", took <= 2.0, f"{took:.2f}s")
            check("停止后两边仍一致", pair[0] == pair[1], pair)

        print("== 重复 /run/stop（幂等，不应卡住） ==")
        for _ in range(3):
            api("/run/stop", "POST")
        pair, _ = wait_both_idle(4.0)
        check("反复停止后仍是「未运行」", pair is not None, pair)

        print("== 再来一轮：确认可以再次启动（状态没有被卡死） ==")
        api("/run", "POST", {"flow": FLOW})
        web, ov = states()
        check("第二次启动成功且两边一致", web is True and ov is True, f"web={web} overlay={ov}")
        api("/run/stop", "POST")
        pair, took = wait_both_idle(6.0)
        check("第二次停止也生效", pair is not None, pair)

        print("== 悬浮框状态接口字段完整性 ==")
        st = api("/overlay/state")
        for k in ("enabled", "available", "visible", "running", "recording", "repeat", "step"):
            check(f"/overlay/state 含 {k}", k in st, list(st))
    finally:
        stop_engine(proc)
        log.close()

    print("")
    print("结果: PASS=" + str(_pass) + "  FAIL=" + str(_fail))
    if _fail:
        print("引擎日志留在 .tmp\\e2e-state-*.log，可据此排查")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
