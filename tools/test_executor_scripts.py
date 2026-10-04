"""executor.py 子脚本执行 / 防递归的断言测试。

跑法：
    python tools/test_executor_scripts.py

为什么必须单独测：子脚本的执行路径只在"真的跑起来"的时候才暴露问题，
而它涉及的三件事都很难靠肉眼验证——
  1) 子脚本的步骤有没有**真的**被执行（负载形状不对时会静默跳过）；
  2) 循环轮数由谁决定（子脚本每次被调用只走一遍，而不是每轮再乘以 repeat）；
  3) 调用栈有没有出栈（漏 pop 会让之后所有调用被误判成"嵌套过深"）。

引擎直接 import 了按键/截图这类 Windows 专用模块，所以这里先往 sys.modules 里塞
桩模块再 import executor —— 这样能在任何 Python 上跑，也不碰真实键鼠。
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

# ---- 桩模块：必须在 import executor 之前装好 ----
CALLS: list[tuple] = []


def _stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


_stub(
    "inputctl",
    click=lambda *a, **k: CALLS.append(("click", a, k)),
    press_key=lambda *a, **k: CALLS.append(("key", a, k)),
    type_text=lambda *a, **k: CALLS.append(("text", a, k)),
    move=lambda *a, **k: None,
    mouse_down=lambda *a, **k: None,
    mouse_up=lambda *a, **k: None,
    scroll=lambda *a, **k: None,
    key_down=lambda *a, **k: None,
    key_up=lambda *a, **k: None,
)
_stub(
    "overlay",
    update=lambda *a: None,
    set_run_state=lambda *a: None,
    set_paused=lambda *a: None,
    set_repeat=lambda *a: None,
    set_recording=lambda *a: None,
)
_stub("vision", primary_monitor_size=lambda: (1920, 1080), grab_frame=lambda: None)
_stub(
    "window",
    get_window_rect=lambda *a: {"left": 0, "top": 0, "width": 100, "height": 100},
    capture_window=lambda *a: None,
    capture_window_fast=lambda *a: None,
)

import vision  # noqa: E402  桩模块，下面几个用例会改它的分辨率
import executor  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
        return
    FAILED.append(name)
    print(f"  FAIL {name} {extra}")


def delay(nid: str, ms: int = 1) -> dict:
    return {"id": nid, "type": "delay", "params": {"ms": ms}}


def click_node(nid: str, x: int = 5, y: int = 6) -> dict:
    return {"id": nid, "type": "click", "params": {"x": x, "y": y, "button": "left", "clicks": 1}}


def call_node(nid: str, script_id: str, name: str = "") -> dict:
    return {"id": nid, "type": "script_call", "params": {"script_id": script_id, "name": name}}


def sub(sid: str, nodes: list, edges: list) -> dict:
    return {"id": sid, "name": f"脚本{sid}", "nodes": nodes, "edges": edges}


def edge(a: str, b: str, handle=None) -> dict:
    return {"source": a, "target": b, "sourceHandle": handle}


async def drive(flow: dict):
    """跑一次流程，返回 (executor, 日志, 节点访问序列)。"""
    logs: list[dict] = []

    async def broadcast(msg: dict) -> None:
        logs.append(msg)

    ex = executor.Executor(broadcast)
    await ex.run(flow)
    visited = []
    for m in logs:
        msg = str(m.get("message", ""))
        if "节点: click" in msg or "节点: delay" in msg or "节点: script_call" in msg:
            visited.append(m.get("step"))
    return ex, logs, visited


def texts(logs: list[dict]) -> str:
    return "\n".join(str(m.get("message", "")) for m in logs)


async def main() -> int:
    print("[1] 子脚本的步骤真的被执行，且顺序正确、轮数由最外层决定")
    CALLS.clear()
    flow = {
        "name": "主脚本",
        "repeat": 3,
        "nodes": [delay("n0"), call_node("c1", "S1"), delay("n2")],
        "edges": [edge("n0", "c1"), edge("c1", "n2")],
        "scripts": {"S1": sub("S1", [click_node("k1", 11, 22)], [])},
    }
    ex, logs, visited = await drive(flow)
    check("子脚本里的点击被执行过", len(CALLS) == 3, f"{len(CALLS)} 次（应为每轮 1 次）")
    check("点击坐标传到 inputctl", bool(CALLS) and CALLS[0][1][:2] == (11, 22), str(CALLS[:1]))
    check("父节点各执行 3 次", visited.count("n0") == 3 and visited.count("n2") == 3, str(visited))
    check("调用节点执行 3 次", visited.count("c1") == 3, str(visited))
    check("子脚本节点 k1 执行 3 次（= 每轮一次，不是 3×3）", visited.count("k1") == 3, str(visited))
    order = [v for v in visited if v in ("n0", "c1", "k1", "n2")]
    check("就地展开的顺序 n0,c1,k1,n2 ×3", order == ["n0", "c1", "k1", "n2"] * 3, str(order))
    check("日志里有'进入子脚本'", "进入子脚本「脚本S1」（第 1 层）" in texts(logs))
    check("调用栈跑完归零", ex.call_stack == [], str(ex.call_stack))
    check("脚本库被装载", list(ex.scripts) == ["S1"], str(list(ex.scripts)))
    check("悬浮框轮数仍是外层的（3/3）", ex._ov_total == 3, str((ex._ov_loop, ex._ov_total)))

    print("[2] 子脚本缺失 → 运行前就明确拒绝（说清在哪个脚本的哪个步骤）")
    CALLS.clear()
    missing = {**flow, "scripts": {}}
    ex, logs, visited = await drive(missing)
    t = texts(logs)
    check("报出脚本找不到", "不存在" in t or "找不到" in t, t)
    check("说明了原因与办法", "重新选择" in t, t)
    check("没有执行任何节点", visited == [], str(visited))
    check("调用栈归零", ex.call_stack == [])

    print("[3] 运行时兜底：直接调 _call_script（模拟运行中脚本库被换掉）只跳过这一步")
    CALLS.clear()
    logs3: list[dict] = []

    async def b3(msg: dict) -> None:
        logs3.append(msg)

    ex3 = executor.Executor(b3)
    ex3.scripts = {"S1": sub("S1", [delay("x")], [])}
    await ex3._call_script({"script_id": "GONE", "name": "被删掉的脚本"}, "real", None, None)
    t3 = texts(logs3)
    check("报出找不到", "找不到要调用的脚本「被删掉的脚本」" in t3, t3)
    check("列出本文件里现有的子脚本", "「脚本S1」" in t3, t3)
    check("给出了处理办法", "重新选择" in t3 or "导入回来" in t3, t3)
    check("未选择子脚本也有提示", await probe_unselected())

    print("[4] 存在环 → 运行前拒绝，一个步骤都不执行")
    CALLS.clear()
    cyclic = {
        "name": "环形脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "A")],
        "edges": [],
        "scripts": {
            "A": sub("A", [call_node("a1", "B")], []),
            "B": sub("B", [call_node("b1", "A")], []),
        },
    }
    ex, logs, visited = await drive(cyclic)
    t = texts(logs)
    check("报告循环调用", "循环调用" in t, t)
    check("给出了完整调用链", "脚本A" in t and "脚本B" in t, t)
    check("明确说了拒绝执行", "拒绝执行" in t, t)
    check("没有执行任何节点", visited == [], str(visited))
    check("调用栈归零", ex.call_stack == [])

    print("[5] 运行时第三道防线：调用栈 + 层数上限")
    # 临时把 executor 里的上限改小（scriptgraph 的校验仍用 16），
    # 这条链因此能通过"运行前整图检测"，只能在运行时被拦下 —— 正好测第三道防线
    deep = {
        "name": "深层脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "S1")],
        "edges": [],
        "scripts": {
            "S1": sub("S1", [call_node("c1", "S2")], []),
            "S2": sub("S2", [call_node("c2", "S3")], []),
            "S3": sub("S3", [click_node("k3")], []),
        },
    }
    old = executor.MAX_SCRIPT_DEPTH
    executor.MAX_SCRIPT_DEPTH = 2
    try:
        CALLS.clear()
        ex, logs, visited = await drive(deep)
        t = texts(logs)
        check("运行时报嵌套超上限", "嵌套层数超过上限" in t, t[-400:])
        check("给出了到上限为止的调用链", "「脚本S1」 → 「脚本S2」 → 「脚本S3」" in t, t[-400:])
        check("第 3 层没有被真的进入", "进入子脚本「脚本S3」" not in t, t[-400:])
        check("前两层正常进入", "进入子脚本「脚本S1」" in t and "进入子脚本「脚本S2」" in t, t[-400:])
        check("到上限的那一步被跳过而不是崩", CALLS == [], str(CALLS))
        check("调用栈归零", ex.call_stack == [], str(ex.call_stack))
    finally:
        executor.MAX_SCRIPT_DEPTH = old

    print("[6] 自调用 S1→S1")
    self_call = {
        "name": "自调用",
        "repeat": 1,
        "nodes": [call_node("c0", "S1")],
        "edges": [],
        "scripts": {"S1": sub("S1", [call_node("c1", "S1")], [])},
    }
    ex, logs, visited = await drive(self_call)
    check("被拦下", "循环调用" in texts(logs), texts(logs)[-300:])
    check("调用栈归零", ex.call_stack == [])

    print("[7] 异常安全出栈：两条异常路径都要把调用栈清干净")
    boom = {
        "name": "会炸的脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "S1")],
        "edges": [],
        "scripts": {"S1": sub("S1", [delay("k1"), delay("k2")], [edge("k1", "k2")])},
    }

    def make_boom(trigger):
        """造一个会在指定消息上抛异常的 executor，返回 (executor, 日志)。"""
        logs: list[dict] = []

        async def b(msg: dict) -> None:
            logs.append(msg)

        ex = executor.Executor(b)
        orig = ex.log

        async def log_and_boom(level: str, msg: str, step=None):
            await orig(level, msg, step)
            if trigger(msg, step):
                raise RuntimeError("模拟广播层异常")

        ex.log = log_and_boom  # type: ignore[method-assign]
        return ex, logs

    # 7a：异常在子脚本的走图骨架里 —— 会穿过 _call_script 的 finally，
    #     然后被"单步失败只记录"兜住（挂机场景宁可继续跑，不要整晚任务因为一步失败就停）
    ex7a, logs7a = make_boom(lambda msg, step: "节点: delay" in msg and step == "k2")
    await ex7a.run(boom)
    t7a = texts(logs7a)
    check("异常被记成'节点执行失败'（不会静默消失）", "节点执行失败(script_call)" in t7a, t7a[-200:])
    check("调用栈仍归零", ex7a.call_stack == [], str(ex7a.call_stack))
    check("running 已复位", ex7a.running is False)
    check("子脚本内部确实进过第 1 层", "进入子脚本「脚本S1」" in t7a, t7a[-200:])

    # 7b：异常在顶层走图骨架里（不在任何单步 try 内）—— 才会冒到 run() 的兜底 handler
    ex7b, logs7b = make_boom(lambda msg, step: "--- 第 1/1 轮 ---" in msg)
    await ex7b.run(boom)
    t7b = texts(logs7b)
    check("冒到顶层被记成'执行异常'", "执行异常" in t7b, t7b[-300:])
    check("调用栈仍归零", ex7b.call_stack == [], str(ex7b.call_stack))
    check("running 已复位", ex7b.running is False)

    print("[8] 子脚本里触发终止条件 → 整个流程停止")
    CALLS.clear()
    term = {
        "name": "终止",
        "repeat": 5,
        "nodes": [call_node("c0", "S1"), delay("n9")],
        "edges": [edge("c0", "n9")],
        "scripts": {"S1": sub("S1", [{"id": "t1", "type": "terminate", "params": {}}], [])},
    }
    ex, logs, visited = await drive(term)
    check("只跑了 1 轮就停", visited.count("c0") == 1, str(visited))
    check("终止后不再执行后续节点", visited.count("n9") == 0, str(visited))
    check("日志里有终止提示", "触发终止条件" in texts(logs), texts(logs)[-300:])
    check("调用栈归零", ex.call_stack == [])

    print("[9] 空子脚本：跳过并提示，不中断")
    CALLS.clear()
    empty = {
        "name": "空脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "S1"), delay("n2")],
        "edges": [edge("c0", "n2")],
        "scripts": {"S1": sub("S1", [], [])},
    }
    ex, logs, visited = await drive(empty)
    t = texts(logs)
    check("空子脚本有提示", "是空的，已跳过" in t, t[-400:])
    check("后续节点照常执行", visited.count("n2") == 1, str(visited))

    print("[10] 子脚本结构损坏 → 运行前被 validate_flow 拒绝")
    bad = {
        "name": "坏脚本",
        "repeat": 1,
        "nodes": [delay("n0")],
        "edges": [],
        "scripts": {"S1": sub("S1", [delay("a")], [edge("a", "ghost")])},
    }
    ex, logs, visited = await drive(bad)
    t = texts(logs)
    check("报出子脚本里的坏连线", "子脚本「脚本S1」里存在指向不存在节点的连线" in t, t[-400:])
    check("拒绝执行", visited == [], str(visited))

    print("[11] 分辨率换算：子脚本里的坐标同样按比例换算")
    CALLS.clear()
    vision.primary_monitor_size = lambda: (1920, 1080)  # 当前分辨率
    scaled = {
        "name": "换算",
        "repeat": 1,
        "screen": {"width": 960, "height": 540},  # 参考分辨率 = 当前的一半
        "nodes": [call_node("c0", "S1")],
        "edges": [],
        "scripts": {"S1": sub("S1", [click_node("k1", 100, 200)], [])},
    }
    ex, logs, visited = await drive(scaled)
    check("子脚本里的坐标也被换算", bool(CALLS) and CALLS[0][1][:2] == (200, 400), str(CALLS[:1]))

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + "；".join(FAILED))
        return 1
    print("全部通过")
    return 0


async def probe_unselected() -> bool:
    """未选择子脚本时的运行时提示（返回断言结果）。"""
    logs: list[dict] = []

    async def b(msg: dict) -> None:
        logs.append(msg)

    ex = executor.Executor(b)
    await ex._call_script({"script_id": ""}, "real", None, None)
    return "还没有选择要调用的子脚本" in texts(logs)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
