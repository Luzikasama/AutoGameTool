"""流程执行器：图执行（支持判断分支、单次执行、终止条件、循环与全局启停）。

分辨率自适应：
- 流程可携带 screen={width,height}（保存时的主显示器物理分辨率）与
  window.rect（保存时绑定窗口的位置尺寸）。
- 运行时若当前分辨率/窗口尺寸与参考值不同，点击与宏坐标按比例换算，
  使脚本可跨分辨率/跨 DPI 复用；模板匹配的分辨率自适应见 vision.match_template_auto。

子脚本（嵌套调用）：
- 流程可携带 scripts={id: {id, name, nodes, edges}}（子脚本库），
  「调用脚本」节点按 params.script_id 就地展开执行 —— 运行语义与"打包合并"基本一致，
  区别只是子脚本体面可复用、可单独编辑导出。
- 因此执行器里**有两层图**：当前正在跑的这张图（_run_graph），
  以及它可能在节点里调用的下一层图。二者共用同一套走图逻辑。
- 防递归共三道防线（见 scriptgraph.py 的说明）：
    1) 编辑器里加调用关系时拦截（前端）
    2) 运行前整图环检测（scriptgraph.validate_scripts，下面 run() 里调用）
    3) 运行时调用栈 + 层数上限（self.call_stack / MAX_SCRIPT_DEPTH）
"""
import asyncio
import time
import traceback
from typing import Any, Callable

import inputctl
import overlay
import vision
import window
from scriptgraph import MAX_SCRIPT_DEPTH, name_map, normalize_scripts, validate_scripts

# 悬浮框里显示的节点中文名
_STEP_LABEL = {
    "delay": "延时",
    "find_image": "找图",
    "click": "鼠标点击",
    "key": "键盘按键",
    "text": "输入文本",
    "judge": "判断分支",
    "macro": "键鼠回放",
    "terminate": "终止条件",
    "autoclick": "连点器",
    "script_call": "调用脚本",
}


def _validate_graph(nodes, edges, where: str) -> None:
    """校验一张图（根流程或某个子脚本）的节点与连线，非法时抛 ValueError。

    where 会出现在错误信息里，因为"哪张图坏了"对用户很关键：
    根流程的报错和"第 3 个子脚本里的报错"处理方式完全不同。
    """
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError(f"{where}的 nodes/edges 必须是数组")
    ids = set()
    for n in nodes:
        if not isinstance(n, dict) or not n.get("id"):
            raise ValueError(f"{where}里存在缺少 id 的节点")
        ids.add(n["id"])
    for e in edges:
        if not isinstance(e, dict) or e.get("source") not in ids or e.get("target") not in ids:
            raise ValueError(f"{where}里存在指向不存在节点的连线: {e!r}")


def validate_flow(flow: dict) -> None:
    """校验流程结构，非法时抛 ValueError（避免执行器带着脏数据运行）。

    子脚本库也一并校验：子脚本里的坏连线同样会让执行器在执行到一半时炸掉，
    而那时用户已经在挂机了 —— 早报比晚报好得多。
    """
    if not isinstance(flow, dict):
        raise ValueError("流程必须是 JSON 对象")
    nodes = flow.get("nodes", [])
    edges = flow.get("edges", [])
    try:
        repeat = int(flow.get("repeat", 1))
    except (TypeError, ValueError):
        raise ValueError(f"循环轮数无效: {flow.get('repeat')!r}")
    if not 1 <= repeat <= 100000:
        raise ValueError(f"循环轮数超出范围(1~100000): {repeat}")
    _validate_graph(nodes, edges, "主脚本")

    scripts = flow.get("scripts") or {}
    if not isinstance(scripts, dict):
        raise ValueError("脚本 scripts 必须是对象")
    for key, sub in scripts.items():
        if not isinstance(sub, dict):
            raise ValueError(f"子脚本 {key!r} 必须是对象")
        sub_nodes = sub.get("nodes") or []
        sub_edges = sub.get("edges") or []
        # 允许空脚本（刚新建、还没来得及编辑），但不允许结构损坏
        if not sub_nodes and not sub_edges:
            continue
        _validate_graph(sub_nodes, sub_edges, f"子脚本「{sub.get('name') or key}」")


class Executor:
    def __init__(self, broadcast: Callable[[dict], Any]) -> None:
        self.broadcast = broadcast
        self.stopped = False
        self.running = False
        # 暂停：与停止不同，暂停只是让流程停在检查点上，resume() 后从原地继续
        self.paused = False
        self.current_flow: dict | None = None
        # 当前执行任务的强引用，供 stop()/reconcile() 判断「是否真有流程在跑」
        self.task: "asyncio.Task | None" = None
        # 本次运行的子脚本库（id → 子脚本），由 run() 从流程里取出
        self.scripts: dict[str, dict] = {}
        # 运行时调用栈（第三道防递归防线）：每个元素 {"id","name"}，栈深 = 当前嵌套层数。
        # 只放子脚本，根脚本不占位 —— 根脚本不可被调用，放进去反而会让层数算多一层。
        self.call_stack: list[dict] = []
        # 悬浮框当前显示的「第几轮 / 共几轮」。子脚本内部也要更新悬浮框的步骤文字，
        # 但轮数必须沿用外层循环的进度，否则一进子脚本就变成 1/1，看起来像重新开始了。
        self._ov_loop = 0
        self._ov_total = 0

    def stop(self) -> None:
        self.stopped = True
        # 停止时一并清掉暂停：否则「暂停中停止」会让暂停等待循环一直挂着
        self.paused = False
        # 没有真正在跑的任务（例如任务已异常退出但状态残留）时直接复位，
        # 否则前端的「停止」按钮会一直卡住，点也点不回来
        if self.task is None or self.task.done():
            self.running = False

    def pause(self) -> None:
        """暂停：流程会在下一个检查点停下（节点边界 / 延时片段内）。"""
        if self.running:
            self.paused = True

    def resume(self) -> None:
        self.paused = False

    async def _wait_if_paused(self) -> None:
        """暂停等待点。

        只放在「节点边界」与「延时的小睡之间」两处：
        - 这两处都不是"做到一半"的状态，恢复后从原地继续即可，不会重复已完成的动作
        - 刻意不放进找图/判断的轮询里：那里的超时是按 time.time() 算的，
          在里面停住会把暂停时长也算进超时，恢复后立刻误判超时
        """
        while self.paused and not self.stopped:
            await asyncio.sleep(0.1)

    def reconcile(self) -> bool:
        """把 running 与实际任务状态对齐，返回修正后的 running。

        兜底任何让 run() 的 finally 未能执行的异常路径：任务已结束却仍标记运行中时
        自动复位，前端靠 1 秒轮询 /run/state 即可自愈。
        """
        if self.running and (self.task is None or self.task.done()):
            self.running = False
        if not self.running:
            self.paused = False  # 没在跑就谈不上暂停，避免展示出"已暂停但空闲"的矛盾状态
        return self.running

    async def log(self, level: str, msg: str, step: str | None = None) -> None:
        await self.broadcast(
            {"type": "log", "level": level, "message": msg, "step": step, "ts": time.time()}
        )

    async def _state(self, state: str) -> None:
        # 悬浮框上的启停按钮要跟着真实状态走
        try:
            overlay.set_run_state(state == "running")
        except Exception:
            pass
        await self.broadcast(
            {"type": "state", "state": state, "paused": bool(self.paused), "ts": time.time()}
        )

    @staticmethod
    def _ov(loop: int, total: int, step: str) -> None:
        """更新悬浮框。

        必须彻底防御：悬浮框只是显示层，任何异常都不能影响流程执行
        （曾因 overlay 模块缺少模块级 update() 而让每次运行都在起跑处异常退出）。
        """
        try:
            overlay.update(loop, total, step)
        except Exception:
            pass

    def _ov_text(self, step: str) -> None:
        """只改悬浮框的步骤文字，轮数沿用当前外层循环进度。

        子脚本内部改的必须是文字：轮数由最外层循环决定，
        子脚本自己那一层是"被调用一次就走一遍"，拿它的 1/1 去覆盖会让进度显示倒退。
        """
        self._ov(self._ov_loop, self._ov_total, step)

    def _step_text(self, node: dict) -> str:
        ntype = str(node.get("type") or "?")
        label = _STEP_LABEL.get(ntype, ntype)
        p = node.get("params") or {}
        extra = ""
        if ntype in ("find_image", "judge"):
            extra = str(p.get("template") or "")
        elif ntype == "key":
            extra = str(p.get("key") or "")
        elif ntype == "delay":
            extra = f"{p.get('ms', 0)} ms"
        elif ntype == "text":
            extra = str(p.get("text") or "")[:14]
        elif ntype == "autoclick":
            extra = f"{p.get('count', 1)} 次 / {p.get('interval_ms', 100)} ms"
        elif ntype == "script_call":
            sid = str(p.get("script_id") or "")
            sub = self.scripts.get(sid)
            extra = sub["name"] if sub else (str(p.get("name") or "") or "未选择")
        return f"{label} {extra}".strip()

    async def toggle(self) -> None:
        """全局快捷键启停。"""
        if self.running and not (self.task and self.task.done()):
            self.stop()
            await self.log("warn", "快捷键触发：停止")
        elif self.current_flow:
            await self.log("info", "快捷键触发：启动")
            await self.run(self.current_flow)
        else:
            await self.log("warn", "暂无已加载流程，无法通过快捷键启动")

    def _make_scaler(self, flow: dict, hwnd):
        """构造坐标换算函数。返回 (scale_fn, 说明) 或 (None, None)。

        优先按「绑定窗口的参考 rect → 当前 rect」换算（同时覆盖窗口移动/缩放/
        分辨率变化）；未绑定窗口时按「参考屏幕分辨率 → 当前主屏分辨率」换算。
        """
        win = flow.get("window")
        ref_rect = win.get("rect") if isinstance(win, dict) else None
        if hwnd and isinstance(ref_rect, dict) and ref_rect.get("width") and ref_rect.get("height"):
            rw, rh = float(ref_rect["width"]), float(ref_rect["height"])
            rl, rt = float(ref_rect.get("left", 0)), float(ref_rect.get("top", 0))

            def scale_by_window(x, y):
                try:
                    rect = window.get_window_rect(hwnd)
                except Exception:
                    return int(x), int(y)
                if rect["width"] <= 0 or rect["height"] <= 0:
                    return int(x), int(y)
                nx = rect["left"] + (float(x) - rl) * rect["width"] / rw
                ny = rect["top"] + (float(y) - rt) * rect["height"] / rh
                return int(round(nx)), int(round(ny))

            return scale_by_window, f"窗口参考 {int(rw)}x{int(rh)}"

        ref_screen = flow.get("screen")
        if isinstance(ref_screen, dict) and ref_screen.get("width") and ref_screen.get("height"):
            rw, rh = float(ref_screen["width"]), float(ref_screen["height"])
            try:
                cur_w, cur_h = vision.primary_monitor_size()
            except Exception:
                return None, None
            if rw <= 0 or rh <= 0:
                return None, None
            if abs(cur_w / rw - 1) < 0.01 and abs(cur_h / rh - 1) < 0.01:
                return None, None  # 分辨率一致，无需换算

            def scale_by_screen(x, y):
                return int(round(float(x) * cur_w / rw)), int(round(float(y) * cur_h / rh))

            return scale_by_screen, f"屏幕参考 {int(rw)}x{int(rh)} → 当前 {cur_w}x{cur_h}"

        return None, None

    async def run(self, flow: dict) -> None:
        self.current_flow = flow
        # 关键：置位 running 之后的全部逻辑都必须落在 try/finally 内。
        # 旧版把「开跑日志 + 分辨率换算」放在 try 之外，这段一旦抛异常，
        # finally 不会执行，running 会永久卡在 True——前端右上角一直显示「停止」
        # 且点击无效（因为 /run/stop 原样回传 running）。
        self.stopped = False
        self.paused = False  # 新一轮开跑必须是"非暂停"，否则会卡在上一轮遗留的暂停里
        self.running = True
        # 每次开跑都清空调用栈、重取子脚本库：
        # 上一次运行残留的栈会让本次的第一个 script_call 就被误判成"嵌套过深"
        self.call_stack = []
        self.scripts = normalize_scripts(flow.get("scripts") if isinstance(flow, dict) else None)
        self._ov_loop, self._ov_total = 0, 0
        try:
            await self._state("running")
            self._ov(0, 0, "准备中…")

            # 先校验：畸形流程直接拒绝，不会让 running 卡死在 True
            try:
                validate_flow(flow)
                repeat = max(1, int(flow.get("repeat", 1)))
            except ValueError as e:
                await self.log("error", f"流程数据无效，已拒绝执行: {e}")
                return

            # 第二道防线：缺失脚本 / 循环调用 / 嵌套过深。
            # 前端在编辑时已经拦过一次，这里再拦一次是为了兜住「手改 JSON」
            # 「导入别人的文件」「旧版本文件」这些前端管不到的入口 ——
            # 无限递归的表现是程序卡死，用户完全无从下手，宁可重复检查。
            problems = validate_scripts(flow)
            if problems:
                for msg in problems:
                    for line in str(msg).split("\n"):
                        await self.log("error", line)
                await self.log("error", "脚本调用关系有问题，本次拒绝执行（原因见上面的日志）")
                return

            nodes = flow.get("nodes", [])
            edges = flow.get("edges", [])
            input_mode = flow.get("input_mode", "real")
            win = flow.get("window")
            hwnd = win.get("hwnd") if isinstance(win, dict) else None

            await self.log(
                "info",
                f"开始执行「{flow.get('name', '未命名')}」：{len(nodes)} 节点 × {repeat} 轮，输入模式={input_mode}"
                + (f"，内嵌 {len(self.scripts)} 个子脚本" if self.scripts else ""),
            )
            # 分辨率换算容错：屏幕/窗口数据畸形时退化为不做换算，而不是中断整个流程
            try:
                scale_fn, scale_desc = self._make_scaler(flow, hwnd)
            except Exception as e:
                scale_fn, scale_desc = None, None
                await self.log("warn", f"分辨率适配计算失败，将按原坐标执行: {e}")
            if scale_fn:
                await self.log("info", f"分辨率/窗口尺寸适配已启用（{scale_desc}），坐标将按比例换算")

            await self._run_graph(nodes, edges, input_mode, hwnd, scale_fn, repeat)
            if self.stopped:
                return
            await self.log("info", "流程执行完成")
            self._ov(repeat, repeat, "流程执行完成")
        except Exception as e:
            await self.log("error", f"执行异常: {e}")
            self._ov(0, 0, f"执行异常：{e}")
            traceback.print_exc()
        finally:
            self.running = False
            # 调用栈必须清空：这次运行里出过异常也不要留给下一次
            self.call_stack = []
            # 广播失败不应把异常抛回调用方（此时 running 已复位，状态本来就正确）
            try:
                await self._state("idle")
            except Exception:
                pass

    async def _run_graph(
        self,
        nodes: list,
        edges: list,
        input_mode: str,
        hwnd,
        scale_fn,
        repeat: int,
        scope: str = "",
    ) -> None:
        """走完一张流程图的「起点 → … → 结束」。

        根流程与每一层子脚本都走这一份实现。子脚本一律 **repeat=1**：循环由最外层决定，
        这样"调用脚本"与"把那些步骤直接合并进主流程"（打包合并）的运行语义才一致。
        scope 只影响日志与悬浮框文案：空串表示顶层，否则是「子脚本「X」」这样的前缀。
        """
        prefix = f"{scope}：" if scope else ""
        node_map = {n["id"]: n for n in nodes}
        adj: dict[str, list[tuple[str, str]]] = {}
        for e in edges:
            adj.setdefault(e["source"], []).append((e.get("sourceHandle") or "", e["target"]))
        targets = {e["target"] for e in edges}
        starts = [n["id"] for n in nodes if n["id"] not in targets]
        if not starts:
            await self.log("error", f"{prefix}流程缺少起始节点，这一段不会执行")
            return
        if len(starts) > 1:
            await self.log("warn", f"{prefix}存在 {len(starts)} 个起始节点，仅从 {starts[0]} 开始执行")
        unreachable = [nid for nid in node_map if nid not in self._reachable(adj, starts[0])]
        if unreachable:
            await self.log("warn", f"{prefix}{len(unreachable)} 个节点从起始节点不可达，不会执行: {unreachable}")
        start_id = starts[0]
        # 「单次执行」的作用域：顶层跨轮次生效；子脚本内每次被调用重新计
        executed_once: set[str] = set()

        for r in range(repeat):
            if self.stopped:
                await self.log("warn", f"{prefix}已手动停止")
                if not scope:
                    self._ov(r + 1, repeat, "已手动停止")
                return
            if not scope:
                # 只有最外层推进悬浮框的轮数：子脚本内部沿用外层的进度，
                # 否则一进子脚本悬浮框就跳回 1/1，看起来像重新开始了
                self._ov_loop, self._ov_total = r + 1, repeat
                await self.log("info", f"--- 第 {r + 1}/{repeat} 轮 ---")
                self._ov(r + 1, repeat, "本轮开始")
            else:
                await self.log("debug", f"{prefix}开始（第 {r + 1}/{repeat} 遍）")
            current = start_id
            visited = 0
            max_steps = max(1000, len(node_map) * 100)  # 单轮步数上限，防无终止环空转
            while current and not self.stopped:
                # 暂停检查点：在节点边界等待。放在这里（而不是从节点内部硬中断）
                # 是因为它天然不会重复执行已完成的动作，恢复后正好从当前节点继续。
                await self._wait_if_paused()
                if self.stopped:
                    break
                visited += 1
                if visited > max_steps:
                    await self.log(
                        "error", f"{prefix}单轮执行超过 {max_steps} 步（疑似无终止条件的环），已停止"
                    )
                    # 顶层终止整次运行；子脚本内只结束这一段，把控制权还给调用方
                    if not scope:
                        self.stopped = True
                    return
                node = node_map.get(current)
                if not node:
                    break
                ntype = node.get("type")
                params = node.get("params") or {}
                once = bool(node.get("once"))

                if ntype == "terminate":
                    await self.log("info", f"{prefix}触发终止条件，立即停止运行")
                    self._ov_text("触发终止条件")
                    self.stopped = True
                    return

                if ntype == "judge":
                    self._ov_text(f"{prefix}{self._step_text(node)}")
                    found = await self._do_judge(params, input_mode, hwnd)
                    label = "yes" if found else "no"
                    nxt = [t for (h, t) in adj.get(current, []) if h == label]
                    current = nxt[0] if nxt else None
                    continue

                # 单次执行：后续轮次跳过（但仍沿连线继续）
                if once and current in executed_once:
                    nxt = adj.get(current, [])
                    current = nxt[0][1] if nxt else None
                    continue

                await self.log("info", f"{prefix}节点: {ntype}", current)
                self._ov_text(f"{prefix}{self._step_text(node)}")
                try:
                    await self._run_step(node, input_mode, hwnd, scale_fn)
                except Exception as e:
                    # 单步失败只记录，不中断整个流程（挂机场景更稳）
                    await self.log("error", f"{prefix}节点执行失败({ntype}): {e}", current)
                executed_once.add(current)
                nxt = adj.get(current, [])
                current = nxt[0][1] if nxt else None

    @staticmethod
    def _reachable(adj: dict, start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(t for _, t in adj.get(cur, []))
        return seen

    async def _do_judge(self, params: dict, input_mode: str, hwnd) -> bool:
        tpl_id = params.get("template")
        threshold = float(params.get("threshold", 0.85))
        timeout_ms = int(params.get("timeout_ms", 5000))
        try:
            template = await asyncio.to_thread(vision.load_template, tpl_id)
        except (FileNotFoundError, ValueError) as e:
            await self.log("error", f"判断模板不可用: {e}")
            return False
        meta = await asyncio.to_thread(vision.load_template_meta, tpl_id)
        start = time.time()
        while not self.stopped:
            try:
                frame = await asyncio.to_thread(self._capture, hwnd, input_mode)
                found, _, _, score, scale = await asyncio.to_thread(
                    vision.match_template_auto, frame, template, meta, threshold
                )
            except Exception as e:
                await self.log("error", f"判断截图失败: {e}")
                return False
            if found:
                extra = f"，缩放 x{scale:.2f}" if abs(scale - 1) > 0.01 else ""
                await self.log("info", f"判断：找到「{tpl_id}」（{score:.3f}{extra}）→ 成功分支")
                return True
            if time.time() - start > timeout_ms / 1000:
                await self.log("info", f"判断：超时未找到「{tpl_id}」→ 失败分支")
                return False
            await asyncio.sleep(0.2)
        return False

    async def _run_step(self, node: dict, input_mode: str, hwnd, scale_fn=None) -> None:
        stype = node.get("type")
        params = node.get("params") or {}
        if stype == "delay":
            total_ms = max(0, int(params.get("ms", 1000)))
            if total_ms <= 0:
                await self.log("warn", "延时为 0ms，跳过")
                return
            remaining = total_ms
            while remaining > 0:
                if self.stopped:
                    await self.log("warn", f"延时被中断（剩余 {remaining}ms）")
                    return
                chunk = min(1000, remaining)
                await self.log("debug", f"正在延时… 剩余 {remaining}ms")
                # 每个 1 秒的分段再拆成 250ms 小睡并检查停止标志。
                # 挂机脚本里的单个延时动辄几十秒，若整段睡死，"停止"要等它走完才生效，
                # 表现得就像「点了停止没反应」（悬浮框与 WebUI 的停止按钮都会被拖住）。
                left = chunk
                while left > 0:
                    if self.stopped:
                        await self.log("warn", f"延时被中断（剩余 {remaining - (chunk - left)}ms）")
                        return
                    # 暂停检查点：暂停时余下的延时不再流逝，恢复后继续把剩余时间睡完
                    await self._wait_if_paused()
                    if self.stopped:
                        await self.log("warn", f"延时被中断（剩余 {remaining - (chunk - left)}ms）")
                        return
                    take = min(250, left)
                    await asyncio.sleep(take / 1000)
                    left -= take
                remaining -= chunk
        elif stype == "find_image":
            await self._do_find(params, input_mode, hwnd)
        elif stype == "click":
            x, y = int(params.get("x", 0)), int(params.get("y", 0))
            if scale_fn:
                x, y = scale_fn(x, y)
            await asyncio.to_thread(
                inputctl.click, x, y, params.get("button", "left"),
                int(params.get("clicks", 1)), input_mode, hwnd,
            )
            await self.log("debug", f"点击 ({x}, {y}) 按键={params.get('button', 'left')} 模式={input_mode}")
        elif stype == "key":
            key = str(params.get("key", ""))
            await asyncio.to_thread(inputctl.press_key, key, input_mode, hwnd)
            await self.log("debug", f"按键 {key} 模式={input_mode}")
        elif stype == "text":
            text = str(params.get("text", ""))
            await asyncio.to_thread(inputctl.type_text, text, input_mode, hwnd)
            await self.log("debug", f"输入文本 {text!r}")
        elif stype == "macro":
            await self._run_macro(params, input_mode, hwnd, scale_fn)
        elif stype == "autoclick":
            await self._do_autoclick(params, input_mode, hwnd, scale_fn)
        elif stype == "script_call":
            await self._call_script(params, input_mode, hwnd, scale_fn)
        else:
            await self.log("warn", f"未知节点类型: {stype}")

    async def _call_script(self, params: dict, input_mode: str, hwnd, scale_fn) -> None:
        """执行「调用脚本」：把子脚本那一层图就地走一遍。

        所有拒绝路径都**只跳过这一步**，不中断整个流程 —— 挂机场景里"因为一个子脚本
        缺失就把整晚的任务停掉"代价太大，而且错误信息都写清了怎么办。
        唯一的例外是 terminate（子脚本里触发终止条件），那条路径会正常向上传播停止。
        """
        sid = str(params.get("script_id") or "").strip()
        if not sid:
            await self.log("error", "调用脚本：这一步还没有选择要调用的子脚本，已跳过（请到编辑器里选择）")
            return

        sub = self.scripts.get(sid)
        if sub is None:
            have = "、".join(f"「{n}」" for n in name_map(self.scripts).values()) or "（本文件里没有任何子脚本）"
            await self.log(
                "error",
                f"调用脚本：找不到要调用的脚本「{params.get('name') or sid}」。"
                f"这份脚本里现有的子脚本是：{have}。"
                "出现这种情况通常是：子脚本被删除了，或者这份脚本是从别处拷来的、缺少内嵌的子脚本。"
                "请在编辑器里重新选择，或把缺失的子脚本导入回来。",
            )
            return

        # ---- 第三道防线：运行时调用栈 ----
        # 前两道（编辑时拦截 / 运行前整图检测）已经覆盖绝大多数情况；这里兜住的是
        # 「流程在运行途中被改」以及「环检测被某种途径绕过」的极端情况。
        chain_names = [f"「{e['name']}」" for e in self.call_stack] + [f"「{sub['name']}」"]
        chain = " → ".join(chain_names)
        for e in self.call_stack:
            if e["id"] == sid:
                await self.log(
                    "error",
                    f"调用脚本：检测到循环调用，已停止这一支，避免无限嵌套。\n调用链：{chain}\n"
                    "（脚本之间不允许互相调用成环，请打断其中一条调用）",
                )
                return
        if len(self.call_stack) >= MAX_SCRIPT_DEPTH:
            await self.log(
                "error",
                f"调用脚本：嵌套层数超过上限（{MAX_SCRIPT_DEPTH} 层），已停止这一支，避免无限嵌套。\n"
                f"调用链：{chain}\n请把其中几层合并成一层。",
            )
            return

        nodes = sub.get("nodes") or []
        if not nodes:
            await self.log("warn", f"调用脚本：子脚本「{sub['name']}」是空的，已跳过")
            return

        await self.log("info", f"进入子脚本「{sub['name']}」（第 {len(self.call_stack) + 1} 层）")
        self.call_stack.append({"id": sid, "name": sub["name"]})
        try:
            await self._run_graph(
                nodes,
                sub.get("edges") or [],
                input_mode,
                hwnd,
                scale_fn,
                1,  # 循环由最外层决定，子脚本每次被调用只走一遍
                scope=f"子脚本「{sub['name']}」",
            )
        finally:
            # 异常安全出栈：漏掉一次 pop，之后所有调用都会被误判成"嵌套过深"
            self.call_stack.pop()
        if self.stopped:
            return
        await self.log("info", f"子脚本「{sub['name']}」执行完成")

    async def _do_autoclick(self, params: dict, input_mode: str, hwnd, scale_fn=None) -> None:
        """连点器：在同一个坐标上按固定间隔点 N 次。

        与「鼠标点击」节点的区别：那个是"点一下（可连续 N 下，间隔固定很短的内部实现）"，
        本节点关心的是**节奏可控的连点**——坐标固定、间隔可调、次数可调，且整个
        过程可暂停、可停止（每次点击前都查一遍标志，长连点不会卡住停止按钮）。

        interval_ms 是**两次点击之间的间隔**（不是点击按住时长）。
        """
        try:
            x, y = int(params.get("x", 0)), int(params.get("y", 0))
            count = int(params.get("count", 10))
            interval_ms = int(params.get("interval_ms", 100))
        except (TypeError, ValueError):
            await self.log("error", "连点器参数无效（坐标 / 次数 / 间隔必须是整数）")
            return
        button = str(params.get("button", "left"))
        count = max(1, min(count, 100000))
        interval_ms = max(0, min(interval_ms, 600000))
        if scale_fn:
            x, y = scale_fn(x, y)
        rate = f"，约 {1000 / interval_ms:.1f} 次/秒" if interval_ms > 0 else ""
        await self.log(
            "info",
            f"连点器开始：坐标 ({x}, {y})，{count} 次，间隔 {interval_ms}ms{rate}",
        )
        done = 0
        for i in range(count):
            if self.stopped:
                await self.log("warn", f"连点器被中断（已完成 {done}/{count} 次）")
                return
            # 暂停检查点：放在每次点击之前，恢复后正好从下一次接着点，不会重复点
            await self._wait_if_paused()
            if self.stopped:
                await self.log("warn", f"连点器被中断（已完成 {done}/{count} 次）")
                return
            try:
                await asyncio.to_thread(inputctl.click, x, y, button, 1, input_mode, hwnd)
                done += 1
            except Exception as e:
                await self.log("warn", f"连点器第 {i + 1} 次点击失败: {e}")
            # 间隔按 50ms 切片睡，保证停止/暂停在长间隔下也能及时生效
            left = interval_ms
            while left > 0 and not self.stopped:
                await self._wait_if_paused()
                if self.stopped:
                    break
                take = min(50, left)
                await asyncio.sleep(take / 1000)
                left -= take
        if self.stopped:
            await self.log("warn", f"连点器被中断（已完成 {done}/{count} 次）")
            return
        await self.log("info", f"连点器完成：共点击 {done} 次")

    async def _run_macro(self, params: dict, input_mode: str, hwnd, scale_fn=None) -> None:
        """回放键鼠录制步骤。"""
        events = params.get("events") or []
        try:
            speed = float(params.get("speed", 1.0) or 1.0)
        except Exception:
            speed = 1.0
        if speed <= 0:
            speed = 1.0
        if not events:
            await self.log("warn", "录制步骤为空，跳过")
            return
        await self.log("info", f"回放录制步骤：{len(events)} 个事件，速度 x{speed}")
        base = time.time() * 1000.0
        for ev in events:
            if self.stopped:
                return
            target = float(ev.get("t", 0)) / speed
            wait = target - (time.time() * 1000.0 - base)
            if wait > 0:
                await asyncio.sleep(wait / 1000.0)
            etype = ev.get("type")
            try:
                if etype == "mousemove":
                    x, y = (scale_fn(ev.get("x", 0), ev.get("y", 0)) if scale_fn
                            else (ev.get("x", 0), ev.get("y", 0)))
                    await asyncio.to_thread(inputctl.move, x, y, input_mode, hwnd)
                elif etype == "mousedown":
                    x, y = (scale_fn(ev.get("x", 0), ev.get("y", 0)) if scale_fn
                            else (ev.get("x", 0), ev.get("y", 0)))
                    await asyncio.to_thread(
                        inputctl.mouse_down, x, y, ev.get("button", "left"), input_mode, hwnd
                    )
                elif etype == "mouseup":
                    x, y = (scale_fn(ev.get("x", 0), ev.get("y", 0)) if scale_fn
                            else (ev.get("x", 0), ev.get("y", 0)))
                    await asyncio.to_thread(
                        inputctl.mouse_up, x, y, ev.get("button", "left"), input_mode, hwnd
                    )
                elif etype == "scroll":
                    sx, sy = (scale_fn(ev.get("x", 0), ev.get("y", 0)) if scale_fn
                              else (ev.get("x", 0), ev.get("y", 0)))
                    await asyncio.to_thread(
                        inputctl.scroll, ev.get("dx", 0), ev.get("dy", 0), input_mode, hwnd, sx, sy
                    )
                elif etype == "keydown":
                    await asyncio.to_thread(inputctl.key_down, str(ev.get("key", "")), input_mode, hwnd)
                elif etype == "keyup":
                    await asyncio.to_thread(inputctl.key_up, str(ev.get("key", "")), input_mode, hwnd)
            except Exception as e:
                await self.log("warn", f"回放事件失败({etype}): {e}")
        await self.log("info", "录制回放完成")

    async def _do_find(self, params: dict, input_mode: str, hwnd) -> None:
        tpl_id = params.get("template")
        threshold = float(params.get("threshold", 0.85))
        timeout_ms = int(params.get("timeout_ms", 5000))
        do_click = bool(params.get("click", False))
        try:
            template = await asyncio.to_thread(vision.load_template, tpl_id)
        except (FileNotFoundError, ValueError) as e:
            await self.log("error", f"模板不可用: {e}")
            return
        meta = await asyncio.to_thread(vision.load_template_meta, tpl_id)
        offset_x = offset_y = 0
        if hwnd:
            rect = window.get_window_rect(hwnd)
            offset_x, offset_y = rect["left"], rect["top"]
        start = time.time()
        while not self.stopped:
            try:
                frame = await asyncio.to_thread(self._capture, hwnd, input_mode)
                found, x, y, score, scale = await asyncio.to_thread(
                    vision.match_template_auto, frame, template, meta, threshold
                )
            except Exception as e:
                await self.log("error", f"窗口截图失败: {e}")
                return
            if found:
                sx, sy = x + offset_x, y + offset_y
                extra = f"，缩放 x{scale:.2f}" if abs(scale - 1) > 0.01 else ""
                await self.log("info", f"找到模板「{tpl_id}」位置 ({sx}, {sy}) 相似度 {score:.3f}{extra}")
                if do_click:
                    await asyncio.to_thread(inputctl.click, sx, sy, "left", 1, input_mode, hwnd)
                    await self.log("info", f"已点击匹配位置 ({sx}, {sy})")
                return
            if time.time() - start > timeout_ms / 1000:
                if params.get("on_timeout") == "exit":
                    await self.log("warn", f"超时未找到「{tpl_id}」→ 退出运行")
                    self.stopped = True
                else:
                    await self.log("warn", f"超时未找到「{tpl_id}」→ 跳过")
                return
            await asyncio.sleep(0.2)

    def _capture(self, hwnd, input_mode: str = "real"):
        if hwnd:
            if input_mode == "simulated":
                # restore_minimized 默认 False：窗口被最小化时报错，而不是把它弹到前台。
                # 否则用户故意最小化的窗口会被每个找图/判断节点反复弹回（"最小化失败"）。
                return window.capture_window(hwnd)  # PrintWindow（后台也能截）
            return window.capture_window_fast(hwnd)  # mss（快，窗口需可见）
        return vision.grab_frame()
