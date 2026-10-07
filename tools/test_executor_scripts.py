"""executor.py / nodes.py 的行为断言测试（0.1.3 节点体系）。

跑法：
    python tools/test_executor_scripts.py

为什么必须单独测：这些路径只在"真的跑起来"时才暴露问题，而且涉及三件很难靠肉眼验证的事——
  1) 子脚本的节点有没有**真的**被执行（负载形状不对时会静默跳过）；
  2) 循环轮数由谁决定、循环体的"回到循环节点 = 下一轮"到底怎么走；
  3) 终止的三级语义（结束循环 / 结束脚本 / 停止工作流）有没有落到正确的作用域；
  4) 调用栈有没有出栈（漏 pop 会让之后所有调用被误判成"嵌套过深"）。

引擎直接 import 了按键/截图这类 Windows 专用模块，所以这里先往 sys.modules 里塞桩模块
再 import executor / nodes —— 这样能在任何 Python 上跑，也不碰真实键鼠与真实屏幕。
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

# ---- 桩模块：必须在 import executor / nodes 之前装好 ----
CALLS: list[tuple] = []


def _stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _rec(tag):
    def _fn(*a, **k):
        CALLS.append((tag, a, k))

    return _fn


_stub(
    "inputctl",
    click=_rec("click"),
    press_key=_rec("key"),
    type_text=_rec("text"),
    move=_rec("move"),
    mouse_down=_rec("mouse_down"),
    mouse_up=_rec("mouse_up"),
    scroll=_rec("scroll"),
    key_down=_rec("key_down"),
    key_up=_rec("key_up"),
    cursor_pos=lambda: (0, 0),
)
_stub(
    "overlay",
    update=lambda *a: None,
    set_run_state=lambda *a: None,
    set_paused=lambda *a: None,
    set_repeat=lambda *a: None,
    set_recording=lambda *a: None,
)
_stub(
    "vision",
    primary_monitor_size=lambda: (1920, 1080),
    grab_frame=lambda *a, **k: None,
)
_stub(
    "window",
    get_window_rect=lambda *a: {"left": 0, "top": 0, "width": 100, "height": 100},
    capture_window=lambda *a: None,
    capture_window_fast=lambda *a: None,
    find_window_by_title=lambda *a: None,
)

import vision  # noqa: E402  桩模块，下面几个用例会改它的分辨率
import executor  # noqa: E402
import nodes as nodemod  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
        return
    FAILED.append(name)
    print(f"  FAIL {name} {extra}")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def delay(nid: str, ms: int = 1) -> dict:
    return {"id": nid, "type": "delay", "params": {"ms": ms}}


def click_node(nid: str, x: int = 5, y: int = 6) -> dict:
    """0.1.3 的「鼠标操作」节点；同时顺便覆盖老 click 类型被归一的情况。"""
    return {"id": nid, "type": "mouse", "params": {"action": "click", "x": x, "y": y, "button": "left", "clicks": 1}}


def legacy_click_node(nid: str, x: int = 5, y: int = 6) -> dict:
    """0.1.2 的「鼠标点击」步骤 —— 引擎必须能直接吃下（绕过前端的入口）。"""
    return {"id": nid, "type": "click", "params": {"x": x, "y": y, "button": "left", "clicks": 1}}


def call_node(nid: str, script_id: str, name: str = "") -> dict:
    return {"id": nid, "type": "script_call", "params": {"script_id": script_id, "name": name}}


def terminate(nid: str, level: str = "workflow") -> dict:
    return {"id": nid, "type": "terminate", "params": {"level": level}}


def judge(nid: str, left: str, op: str = "==", right: str = "yes") -> dict:
    return {"id": nid, "type": "judge", "params": {"logic": "and", "condition": {"left": left, "op": op, "right": right}}}


def loop_times(nid: str, times: int) -> dict:
    return {"id": nid, "type": "loop", "params": {"mode": "times", "times": times}}


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
        # 循环体 / 子脚本里的节点日志会带「循环体·第N轮」「子脚本「x」：」这类前缀，
        # 所以用包含判断而不是前缀判断，否则这些节点会被整体漏掉。
        if "节点: " in msg:
            visited.append(m.get("step"))
    return ex, logs, visited


def texts(logs: list[dict]) -> str:
    return "\n".join(str(m.get("message", "")) for m in logs)


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

async def case_legacy_and_nodes() -> None:
    print("[1] 老的步骤类型名（click/key/text/macro）在引擎侧也能直接吃下")
    CALLS.clear()
    flow = {
        "name": "老脚本",
        "repeat": 1,
        "nodes": [
            legacy_click_node("n0", 7, 8),
            {"id": "n1", "type": "key", "params": {"key": "ctrl+a"}},
            {"id": "n2", "type": "text", "params": {"text": "hi"}},
            delay("n3"),
        ],
        "edges": [edge("n0", "n1"), edge("n1", "n2"), edge("n2", "n3")],
    }
    ex, logs, visited = await drive(flow)
    t = texts(logs)
    check("老 click → 鼠标点击", any(c[0] == "click" and c[1][:2] == (7, 8) for c in CALLS), str(CALLS[:2]))
    check("老 key → 键盘按键", any(c[0] in ("key", "key_down") and "ctrl+a" in c[1] for c in CALLS), str(CALLS))
    check("老 text → 文本输入", any(c[0] == "text" for c in CALLS), str(CALLS))
    check("没有'未知节点类型'告警", "未知节点类型" not in t, t)


async def case_judge() -> None:
    print("[2] 判断：按条件走 yes / no 两条分支")
    flow = {
        "name": "判断",
        "repeat": 1,
        "nodes": [
            {"id": "set", "type": "variable", "params": {"action": "set", "name": "found", "value": "yes"}},
            judge("j1", "found", "==", "yes"),
            delay("yes_node"),
            delay("no_node"),
        ],
        "edges": [
            edge("set", "j1"),
            edge("j1", "yes_node", "yes"),
            edge("j1", "no_node", "no"),
        ],
    }
    ex, logs, visited = await drive(flow)
    check("条件为真时走 yes", "yes_node" in visited and "no_node" not in visited, str(visited))
    check("日志里报出分支", "判断 → 是" in texts(logs), texts(logs))

    flow["nodes"][0]["params"]["value"] = "no"
    ex, logs, visited = await drive(flow)
    check("条件为假时走 no", "no_node" in visited and "yes_node" not in visited, str(visited))

    # 只有一条默认连线时，不该断流（用户在画布上还没连完是常态）
    flow2 = {
        "name": "判断-单出口",
        "repeat": 1,
        "nodes": [judge("j1", "missing", "==", "yes"), delay("tail")],
        "edges": [edge("j1", "tail")],
    }
    ex, logs, visited = await drive(flow2)
    check("只连一条线时退回默认出口", "tail" in visited, str(visited))


async def case_loop() -> None:
    print("[3] 循环：body 出口走循环体，回到循环节点 = 下一轮；跑完从 next 继续")
    CALLS.clear()
    flow = {
        "name": "固定次数循环",
        "repeat": 1,
        "nodes": [
            loop_times("L", 3),
            click_node("body", 1, 1),
            delay("after"),
        ],
        "edges": [
            edge("L", "body", "body"),
            edge("body", "L"),          # 循环体末尾连回循环节点
            edge("L", "after", "next"),
        ],
    }
    ex, logs, visited = await drive(flow)
    t = texts(logs)
    check("循环体执行 3 次", visited.count("body") == 3, str(visited))
    check("循环结束后继续走 next", "after" in visited, str(visited))
    check("日志报出循环开始/结束", "循环开始：固定 3 次" in t and "循环结束：共 3 轮" in t, t[-400:])

    print("[3b] 循环遇到「终止-结束当前循环」时立刻跳出，并继续走 next")
    flow2 = {
        "name": "break",
        "repeat": 1,
        "nodes": [
            {"id": "i", "type": "variable", "params": {"action": "set", "name": "n", "value": "0"}},
            loop_times("L", 10),
            {"id": "inc", "type": "calculate", "params": {"expr": "{{n}} + 1", "save_var": "n"}},
            judge("j", "n", ">=", "2"),
            terminate("brk", "loop"),
            delay("after"),
        ],
        "edges": [
            edge("i", "L"),
            edge("L", "inc", "body"),
            edge("inc", "j"),
            edge("j", "brk", "yes"),
            edge("j", "L", "no"),
            edge("L", "after", "next"),
        ],
    }
    ex, logs, visited = await drive(flow2)
    t = texts(logs)
    check("循环被 break（跑 2 轮而不是 10 轮）", visited.count("inc") == 2, str(visited))
    check("break 后仍走 next", "after" in visited, str(visited))
    check("日志报了被中断", "被「终止」节点中断" in t, t[-400:])

    print("[3c] 条件循环：条件为假提前结束")
    flow3 = {
        "name": "条件循环",
        "repeat": 1,
        "nodes": [
            {"id": "i", "type": "variable", "params": {"action": "set", "name": "n", "value": "0"}},
            {"id": "L", "type": "loop", "params": {"mode": "condition", "condition": {"left": "n", "op": "<", "right": "2"}, "max_iterations": 100}},
            {"id": "inc", "type": "calculate", "params": {"expr": "{{n}} + 1", "save_var": "n"}},
        ],
        "edges": [edge("i", "L"), edge("L", "inc", "body"), edge("inc", "L")],
    }
    ex, logs, visited = await drive(flow3)
    t = texts(logs)
    check("条件循环跑 2 轮后自然结束", visited.count("inc") == 2, str(visited))
    check("日志说明条件不再满足", "条件不再满足" in t, t[-300:])


async def case_terminate_levels() -> None:
    print("[4] 终止的三级语义")
    # script：子脚本被结束，主脚本继续
    CALLS.clear()
    flow = {
        "name": "终止脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "S1"), delay("n9")],
        "edges": [edge("c0", "n9")],
        "scripts": {"S1": sub("S1", [delay("s1"), terminate("t1", "script"), delay("s2")], [edge("s1", "t1"), edge("t1", "s2")])},
    }
    ex, logs, visited = await drive(flow)
    t = texts(logs)
    check("子脚本被结束（s2 未执行）", "s2" not in visited, str(visited))
    check("主脚本继续执行", "n9" in visited, str(visited))
    check("日志说明范围", "终止：结束当前脚本" in t, t[-400:])

    # workflow：跑 1 轮就停，后续节点不动
    CALLS.clear()
    flow2 = {
        "name": "终止工作流",
        "repeat": 5,
        "nodes": [call_node("c0", "S1"), delay("n9")],
        "edges": [edge("c0", "n9")],
        "scripts": {"S1": sub("S1", [terminate("t1", "workflow")], [])},
    }
    ex, logs, visited = await drive(flow2)
    t = texts(logs)
    check("只跑 1 轮就停", visited.count("c0") == 1, str(visited))
    check("终止后不再执行后续节点", visited.count("n9") == 0, str(visited))
    check("日志说明范围", "停止整个工作流" in t, t[-300:])
    check("调用栈归零", ex.call_stack == [])


async def case_subscripts() -> None:
    print("[5] 子脚本执行顺序 / 轮数 / 调用栈")
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
    check("子脚本节点 k1 执行 3 次（不是 3×3）", visited.count("k1") == 3, str(visited))
    order = [v for v in visited if v in ("n0", "c1", "k1", "n2")]
    check("就地展开顺序正确", order == ["n0", "c1", "k1", "n2"] * 3, str(order))
    check("日志里有'进入子脚本'", "进入子脚本「脚本S1」（第 1 层）" in texts(logs))
    check("调用栈跑完归零", ex.call_stack == [], str(ex.call_stack))
    check("脚本库被装载", list(ex.scripts) == ["S1"], str(list(ex.scripts)))
    check("悬浮框轮数仍是外层的（3/3）", ex._ov_total == 3, str((ex._ov_loop, ex._ov_total)))

    print("[6] 子脚本缺失 / 环 / 嵌套过深 / 空子脚本 / 坏结构")
    missing = {**flow, "scripts": {}}
    ex, logs, visited = await drive(missing)
    t = texts(logs)
    check("报出脚本找不到", "不存在" in t or "找不到" in t, t)
    check("说明了原因与办法", "重新选择" in t, t)
    check("没有执行任何节点", visited == [], str(visited))

    cyclic = {
        "name": "环形脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "A")],
        "edges": [],
        "scripts": {"A": sub("A", [call_node("a1", "B")], []), "B": sub("B", [call_node("b1", "A")], [])},
    }
    ex, logs, visited = await drive(cyclic)
    t = texts(logs)
    check("报告循环调用", "循环调用" in t, t)
    check("给出了完整调用链", "脚本A" in t and "脚本B" in t, t)
    check("没有执行任何节点", visited == [], str(visited))

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
        check("第 3 层没有被真的进入", "进入子脚本「脚本S3」" not in t, t[-400:])
        check("到上限的那一步被跳过而不是崩", CALLS == [], str(CALLS))
        check("调用栈归零", ex.call_stack == [])
    finally:
        executor.MAX_SCRIPT_DEPTH = old

    empty = {
        "name": "空脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "S1"), delay("n2")],
        "edges": [edge("c0", "n2")],
        "scripts": {"S1": sub("S1", [], [])},
    }
    ex, logs, visited = await drive(empty)
    check("空子脚本有提示", "是空的，已跳过" in texts(logs), texts(logs)[-400:])
    check("后续节点照常执行", visited.count("n2") == 1, str(visited))

    bad = {
        "name": "坏脚本",
        "repeat": 1,
        "nodes": [delay("n0")],
        "edges": [],
        "scripts": {"S1": sub("S1", [delay("a")], [edge("a", "ghost")])},
    }
    ex, logs, visited = await drive(bad)
    check("报出子脚本里的坏连线", "子脚本「脚本S1」里存在指向不存在节点的连线" in texts(logs))
    check("拒绝执行", visited == [], str(visited))


async def case_data_nodes() -> None:
    print("[7] 数据类节点：变量 / 运算 / 文本处理 + 变量插值")
    flow = {
        "name": "数据",
        "repeat": 1,
        "nodes": [
            {"id": "v1", "type": "variable", "params": {"action": "set", "name": "a", "value": "5"}},
            {"id": "c1", "type": "calculate", "params": {"expr": "({{a}} + 5) * 2", "save_var": "b"}},
            judge("j1", "b", "==", "20"),
            {"id": "ok", "type": "variable", "params": {"action": "set", "name": "ok", "value": "yes"}},
            {"id": "ng", "type": "variable", "params": {"action": "set", "name": "ok", "value": "no"}},
        ],
        "edges": [
            edge("v1", "c1"),
            edge("c1", "j1"),
            edge("j1", "ok", "yes"),
            edge("j1", "ng", "no"),
        ],
    }
    ex, logs, visited = await drive(flow)
    check("变量 + 运算 + 判断串起来是对的", "ok" in visited and "ng" not in visited, str(visited))
    check("运算结果写进了变量表", ex.vars.get("b") == 20, repr(ex.vars.get("b")))

    flow2 = {
        "name": "文本",
        "repeat": 1,
        "nodes": [
            {"id": "t1", "type": "variable", "params": {"action": "set", "name": "raw", "value": "abc-123-def"}},
            {"id": "t2", "type": "text_process", "params": {"action": "split", "input": "{{raw}}", "sep": "-", "index": 1, "save_var": "mid"}},
            {"id": "t3", "type": "text_process", "params": {"action": "concat", "input": "X", "input2": "{{mid}}", "save_var": "out"}},
        ],
        "edges": [edge("t1", "t2"), edge("t2", "t3")],
    }
    ex, logs, visited = await drive(flow2)
    check("文本处理：分割取值", ex.vars.get("mid") == "123", repr(ex.vars.get("mid")))
    check("文本处理：拼接", ex.vars.get("out") == "X123", repr(ex.vars.get("out")))


async def case_input_nodes() -> None:
    print("[8] 输入类节点：鼠标动作 / 键盘动作 / 文本输入")
    CALLS.clear()
    flow = {
        "name": "输入",
        "repeat": 1,
        "nodes": [
            {"id": "m1", "type": "mouse", "params": {"action": "double_click", "x": 10, "y": 20, "button": "left"}},
            {"id": "m2", "type": "mouse", "params": {"action": "right_click", "x": 30, "y": 40}},
            {"id": "m3", "type": "mouse", "params": {"action": "wheel", "x": 1, "y": 2, "dx": 0, "dy": -3}},
            {"id": "m4", "type": "mouse", "params": {"action": "down", "x": 5, "y": 5, "button": "left"}},
            {"id": "m5", "type": "mouse", "params": {"action": "up", "x": 5, "y": 5, "button": "left"}},
            {"id": "k1", "type": "keyboard", "params": {"action": "press", "keys": "ctrl+shift+a", "hold_ms": 0}},
            {"id": "k2", "type": "keyboard", "params": {"action": "down", "keys": "shift"}},
            {"id": "t1", "type": "text_input", "params": {"text": "你好", "method": "direct", "interval_ms": 0}},
        ],
        "edges": [
            edge("m1", "m2"), edge("m2", "m3"), edge("m3", "m4"), edge("m4", "m5"),
            edge("m5", "k1"), edge("k1", "k2"), edge("k2", "t1"),
        ],
    }
    ex, logs, visited = await drive(flow)
    tags = [c[0] for c in CALLS]
    check("双击 → click(clicks=2)", any(c[0] == "click" and c[1][3] == 2 for c in CALLS), str(CALLS))
    check("右键 → click(right)", any(c[0] == "click" and c[1][2] == "right" for c in CALLS), str(CALLS))
    check("滚轮 → scroll", "scroll" in tags, str(tags))
    check("按下/松开 → mouse_down / mouse_up", "mouse_down" in tags and "mouse_up" in tags, str(tags))
    check("组合键 → key_down + key_up", tags.count("key_down") >= 1 and tags.count("key_up") >= 1, str(tags))
    check("文本输入 → type_text", "text" in tags, str(tags))


async def case_resolution() -> None:
    print("[9] 分辨率换算：子脚本里的坐标同样按比例换算")
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


async def case_abnormal_exit() -> None:
    print("[10] 异常安全：调用栈清空 + running 复位")
    boom = {
        "name": "会炸的脚本",
        "repeat": 1,
        "nodes": [call_node("c0", "S1")],
        "edges": [],
        "scripts": {"S1": sub("S1", [delay("k1"), delay("k2")], [edge("k1", "k2")])},
    }

    def make_boom(trigger):
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

    ex7a, logs7a = make_boom(lambda msg, step: "节点: delay" in msg and step == "k2")
    await ex7a.run(boom)
    t7a = texts(logs7a)
    check("异常被记下来（不会静默消失）", "节点执行失败" in t7a, t7a[-200:])
    check("调用栈仍归零", ex7a.call_stack == [], str(ex7a.call_stack))
    check("running 已复位", ex7a.running is False)

    ex7b, logs7b = make_boom(lambda msg, step: "--- 第 1/1 轮 ---" in msg)
    await ex7b.run(boom)
    t7b = texts(logs7b)
    check("冒到顶层被记成'执行异常'", "执行异常" in t7b, t7b[-300:])
    check("调用栈仍归零", ex7b.call_stack == [], str(ex7b.call_stack))
    check("running 已复位", ex7b.running is False)


def case_node_coverage() -> None:
    """节点覆盖面：引擎真正认识 25 个节点，且与悬浮框中文名一一对应。

    为什么值得单测：前端《节点设计规范 V1》里加/改一个节点（lib/nodeSchema.ts）而
    引擎忘了同步（nodes.py / executor.py）时，运行时只会打一行「未知节点类型」警告，
    流程静默走空 —— 这种错在界面上完全看不出来。
    """
    print("[0] 节点覆盖面：25 个核心节点在引擎侧都有实现")
    handled = set(nodemod.HANDLERS) | set(nodemod.CONTROL_NODES)
    labeled = set(executor._STEP_LABEL) - {executor.GROUP_NODE}
    check("实现与中文名数量一致（25）", len(handled) == 25, f"{len(handled)} 个：{sorted(handled)}")
    check("实现集合 == 悬浮框名集合", handled == labeled, f"只在实现里：{sorted(handled - labeled)}；只在校验里：{sorted(labeled - handled)}")
    check("控制流节点不在 HANDLERS 里（避免双重处理）", not (set(nodemod.HANDLERS) & nodemod.CONTROL_NODES), str(set(nodemod.HANDLERS) & nodemod.CONTROL_NODES))
    # 组合节点是"容器"，不属于六大类，也就不在这 25 个里
    check("组合节点已登记中文名、且不算进 25 个核心节点", 'group' in executor._STEP_LABEL and 'group' not in handled)


# ---------------------------------------------------------------------------
# 0.1.4：组合节点 / 层级变量作用域 / 按节点输入方式
# ---------------------------------------------------------------------------

def group_node(nid: str, inner_nodes: list, inner_edges: list, *, name: str = "组合", variables=None) -> dict:
    return {
        "id": nid,
        "type": "group",
        "params": {"name": name, "nodes": inner_nodes, "edges": inner_edges, "variables": variables or []},
    }


async def case_group_node() -> None:
    print("[11] 组合节点：内部图就地执行，且对上层的控制流透明")
    CALLS.clear()
    flow = {
        "name": "组合",
        "repeat": 1,
        "nodes": [
            group_node("g1", [delay("a1"), click_node("a2", 11, 12)], [edge("a1", "a2")]),
            delay("tail"),
        ],
        "edges": [edge("g1", "tail")],
    }
    _ex, logs, visited = await drive(flow)
    t = texts(logs)
    check("组合节点里的鼠标操作真的执行了", any(c[0] == "click" and c[1][:2] == (11, 12) for c in CALLS), str(CALLS))
    check("日志里明确进了组合节点", "进入组合节点" in t, t)
    check("组合节点有出口、能继续往下走", "tail" in visited, str(visited))

    # 透明性：组合节点内部的「结束当前循环」要作用到**外层的循环**上
    CALLS.clear()
    flow2 = {
        "name": "循环里的组合",
        "repeat": 1,
        "nodes": [
            loop_times("lp", 5),
            group_node("g2", [delay("b1"), terminate("b2", "loop")], [edge("b1", "b2")]),
            delay("after"),
        ],
        "edges": [edge("lp", "g2", "body"), edge("g2", "lp"), edge("lp", "after", "next")],
    }
    _ex2, logs2, _v2 = await drive(flow2)
    t2 = texts(logs2)
    check(
        "组合节点里的「结束当前循环」打断了外层循环（只跑 1 轮）",
        "共 1 轮" in t2 and "共 5 轮" not in t2,
        t2,
    )

    # 嵌套组合节点
    CALLS.clear()
    nested = group_node("n-g", [click_node("n-c", 21, 22)], [])
    flow3 = {
        "name": "嵌套组合",
        "repeat": 1,
        "nodes": [group_node("g3", [delay("c1"), nested], [edge("c1", "n-g")])],
        "edges": [],
    }
    await drive(flow3)
    check("嵌套组合节点也能执行到底", any(c[0] == "click" and c[1][:2] == (21, 22) for c in CALLS), str(CALLS))

    # 空组合节点 / 内部坏连线：只报错不崩
    flow4 = {"name": "空组合", "repeat": 1, "nodes": [group_node("g4", [], [])], "edges": []}
    ex4, logs4, _v4 = await drive(flow4)
    check("空组合节点只警告、不崩", "没有节点" in texts(logs4) and ex4.running is False, texts(logs4))

    bad = {"name": "坏组合", "repeat": 1, "edges": [], "nodes": [
        group_node("g5", [delay("d1")], [{"source": "d1", "target": "不存在", "sourceHandle": None}])]}
    ex5, logs5, _v5 = await drive(bad)
    check("组合节点内部的坏连线会被校验拦下", "无效" in texts(logs5) and ex5.running is False, texts(logs5))


async def case_var_scope() -> None:
    print("[12] 层级变量作用域：全局可见 / 局部不外泄 / 可显式写全局")
    flow = {
        "name": "作用域",
        "repeat": 1,
        "variables": [{"name": "hp", "type": "number", "value": "100"}],
        "nodes": [
            judge("j1", "hp", "==", "100"),
            {"id": "ok", "type": "variable", "params": {"action": "set", "name": "seen", "value": "yes"}},
        ],
        "edges": [edge("j1", "ok", "yes")],
    }
    ex, _logs, visited = await drive(flow)
    check("声明的全局变量在开跑时已初始化（数字 100）", ex.vars.get("hp") == 100, repr(ex.vars.get("hp")))
    check("判断读得到全局变量", "ok" in visited, str(visited))

    flow2 = {
        "name": "局部不外泄",
        "repeat": 1,
        "variables": [{"name": "g", "type": "auto", "value": "G0"}],
        "nodes": [
            group_node("g1", [
                {"id": "s1", "type": "variable", "params": {"action": "set", "name": "local_only", "value": "L"}},
                {"id": "s2", "type": "variable", "params": {"action": "set", "name": "g", "value": "G1"}},
            ], [edge("s1", "s2")]),
        ],
        "edges": [],
    }
    ex2, _l2, _v2 = await drive(flow2)
    check("组合节点里新建的变量不外泄", ex2.vars.get("local_only") is None, repr(ex2.vars.get("local_only")))
    check("改同名变量默认只改本层（全局保持原值）", ex2.vars.get("g") == "G0", repr(ex2.vars.get("g")))

    flow3 = {
        "name": "显式全局",
        "repeat": 1,
        "nodes": [
            group_node("g1", [
                {"id": "s1", "type": "variable", "params": {"action": "set", "name": "g", "value": "G2", "scope": "global"}},
            ], []),
        ],
        "edges": [],
    }
    ex3, _l3, _v3 = await drive(flow3)
    check("scope=global 能写回全局作用域", ex3.vars.get("g") == "G2", repr(ex3.vars.get("g")))

    flow4 = {
        "name": "子脚本局部",
        "repeat": 1,
        "variables": [{"name": "outer", "type": "auto", "value": "O"}],
        "nodes": [call_node("c1", "S")],
        "edges": [],
        "scripts": {"S": {
            "id": "S",
            "name": "子",
            "edges": [edge("sp", "sw")],
            "variables": [{"name": "local", "type": "auto", "value": "LV"}],
            "nodes": [
                judge("sp", "outer", "==", "O"),
                {"id": "sw", "type": "variable", "params": {"action": "set", "name": "leak", "value": "X"}},
            ],
        }},
    }
    ex4, logs4, _v4 = await drive(flow4)
    check("子脚本读得到外层的全局变量", "判断 → 是" in texts(logs4), texts(logs4))
    check("子脚本里写的变量不外泄到主脚本", ex4.vars.get("leak") is None, repr(ex4.vars.get("leak")))


async def case_input_mode_per_node() -> None:
    print("[13] 输入方式跟着节点走（0.1.4 起不再有流程级单选）")
    CALLS.clear()
    flow = {
        "name": "输入方式",
        "repeat": 1,
        "nodes": [
            {"id": "m1", "type": "mouse", "params": {"action": "click", "x": 1, "y": 2, "button": "left", "clicks": 1, "input_mode": "simulated"}},
            {"id": "m2", "type": "mouse", "params": {"action": "click", "x": 3, "y": 4, "button": "left", "clicks": 1}},
        ],
        "edges": [edge("m1", "m2")],
    }
    await drive(flow)
    m1 = [c for c in CALLS if c[0] == "click" and c[1][:2] == (1, 2)]
    m2 = [c for c in CALLS if c[0] == "click" and c[1][:2] == (3, 4)]
    check("节点写了 simulated → 用后台消息", bool(m1) and m1[0][1][4] == "simulated", str(m1))
    check("节点没写 → 回落到默认（真实键鼠）", bool(m2) and m2[0][1][4] == "real", str(m2))

    CALLS.clear()
    flow2 = {
        "name": "老默认",
        "repeat": 1,
        "input_mode": "simulated",
        "nodes": [{"id": "m", "type": "mouse", "params": {"action": "click", "x": 9, "y": 9, "button": "left", "clicks": 1}}],
        "edges": [],
    }
    await drive(flow2)
    mm = [c for c in CALLS if c[0] == "click" and c[1][:2] == (9, 9)]
    check("老脚本的流程级 input_mode 仍作为兜底默认", bool(mm) and mm[0][1][4] == "simulated", str(mm))


async def case_output_var_optional() -> None:
    """输出变量是"用户在变量页添加了才有"（0.1.5）。

    以前 calculate / text_process / clipboard 在参数为空时会**兜底**写一个
    `result` / `text_result` / `clip` 变量 —— 那就是"节点自带的变量"，
    用不到也照样塞进变量表。现在空参数 = 不写。
    """
    print("[14] 输出变量：没添加就不产生（0.1.5）")

    flow = {
        "name": "无输出变量",
        "repeat": 1,
        "nodes": [
            {"id": "c1", "type": "calculate", "params": {"expr": "1 + 1"}},
            {"id": "t1", "type": "text_process", "params": {"action": "trim", "input": "  x  "}},
            {"id": "cb1", "type": "clipboard", "params": {"action": "get"}},
        ],
        "edges": [edge("c1", "t1"), edge("t1", "cb1")],
    }
    ex, logs, _ = await drive(flow)
    for name in ("result", "text_result", "clip"):
        check(f"没添加输出变量就不产生 {name}", not ex.vars.has(name), repr(ex.vars.get(name)))

    flow2 = {
        "name": "有输出变量",
        "repeat": 1,
        "nodes": [
            {"id": "c1", "type": "calculate", "params": {"expr": "2 * 3", "save_var": "n"}},
        ],
        "edges": [],
    }
    ex2, _, _ = await drive(flow2)
    check("添加了输出变量就照常写入", ex2.vars.get("n") == 6, repr(ex2.vars.get("n")))


async def main() -> int:
    case_node_coverage()
    await case_legacy_and_nodes()
    await case_judge()
    await case_loop()
    await case_terminate_levels()
    await case_subscripts()
    await case_data_nodes()
    await case_input_nodes()
    await case_resolution()
    await case_abnormal_exit()
    await case_group_node()
    await case_var_scope()
    await case_input_mode_per_node()
    await case_output_var_optional()

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + "；".join(FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
