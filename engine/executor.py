"""流程执行器：图执行（支持判断分支、单次执行、终止条件、循环与全局启停）。

分辨率自适应：
- 流程可携带 screen={width,height}（保存时的主显示器物理分辨率）与
  window.rect（保存时绑定窗口的位置尺寸）。
- 运行时若当前分辨率/窗口尺寸与参考值不同，点击与宏坐标按比例换算，
  使脚本可跨分辨率/跨 DPI 复用；模板匹配的分辨率自适应见 vision.match_template_auto。
"""
import asyncio
import time
import traceback
from typing import Any, Callable

import inputctl
import overlay
import vision
import window

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
}


def validate_flow(flow: dict) -> None:
    """校验流程结构，非法时抛 ValueError（避免执行器带着脏数据运行）。"""
    if not isinstance(flow, dict):
        raise ValueError("流程必须是 JSON 对象")
    nodes = flow.get("nodes", [])
    edges = flow.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("流程 nodes/edges 必须是数组")
    try:
        repeat = int(flow.get("repeat", 1))
    except (TypeError, ValueError):
        raise ValueError(f"循环轮数无效: {flow.get('repeat')!r}")
    if not 1 <= repeat <= 100000:
        raise ValueError(f"循环轮数超出范围(1~100000): {repeat}")
    ids = set()
    for n in nodes:
        if not isinstance(n, dict) or not n.get("id"):
            raise ValueError("存在缺少 id 的节点")
        ids.add(n["id"])
    for e in edges:
        if not isinstance(e, dict) or e.get("source") not in ids or e.get("target") not in ids:
            raise ValueError(f"存在指向不存在节点的连线: {e!r}")


class Executor:
    def __init__(self, broadcast: Callable[[dict], Any]) -> None:
        self.broadcast = broadcast
        self.stopped = False
        self.running = False
        self.current_flow: dict | None = None
        # 当前执行任务的强引用，供 stop()/reconcile() 判断「是否真有流程在跑」
        self.task: "asyncio.Task | None" = None

    def stop(self) -> None:
        self.stopped = True
        # 没有真正在跑的任务（例如任务已异常退出但状态残留）时直接复位，
        # 否则前端的「停止」按钮会一直卡住，点也点不回来
        if self.task is None or self.task.done():
            self.running = False

    def reconcile(self) -> bool:
        """把 running 与实际任务状态对齐，返回修正后的 running。

        兜底任何让 run() 的 finally 未能执行的异常路径：任务已结束却仍标记运行中时
        自动复位，前端靠 1 秒轮询 /run/state 即可自愈。
        """
        if self.running and (self.task is None or self.task.done()):
            self.running = False
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
        await self.broadcast({"type": "state", "state": state, "ts": time.time()})

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

    @staticmethod
    def _step_text(node: dict) -> str:
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
        self.running = True
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

            nodes = flow.get("nodes", [])
            edges = flow.get("edges", [])
            input_mode = flow.get("input_mode", "real")
            win = flow.get("window")
            hwnd = win.get("hwnd") if isinstance(win, dict) else None

            await self.log(
                "info",
                f"开始执行「{flow.get('name', '未命名')}」：{len(nodes)} 节点 × {repeat} 轮，输入模式={input_mode}",
            )
            # 分辨率换算容错：屏幕/窗口数据畸形时退化为不做换算，而不是中断整个流程
            try:
                scale_fn, scale_desc = self._make_scaler(flow, hwnd)
            except Exception as e:
                scale_fn, scale_desc = None, None
                await self.log("warn", f"分辨率适配计算失败，将按原坐标执行: {e}")
            if scale_fn:
                await self.log("info", f"分辨率/窗口尺寸适配已启用（{scale_desc}），坐标将按比例换算")
            node_map = {n["id"]: n for n in nodes}
            adj: dict[str, list[tuple[str, str]]] = {}
            for e in edges:
                adj.setdefault(e["source"], []).append((e.get("sourceHandle") or "", e["target"]))
            targets = {e["target"] for e in edges}
            starts = [n["id"] for n in nodes if n["id"] not in targets]
            if not starts:
                await self.log("error", "流程缺少起始节点")
                return
            if len(starts) > 1:
                await self.log("warn", f"存在 {len(starts)} 个起始节点，仅从 {starts[0]} 开始执行")
            unreachable = [nid for nid in node_map if nid not in self._reachable(adj, starts[0])]
            if unreachable:
                await self.log("warn", f"{len(unreachable)} 个节点从起始节点不可达，不会执行: {unreachable}")
            start_id = starts[0]
            executed_once: set[str] = set()

            for r in range(repeat):
                if self.stopped:
                    await self.log("warn", "已手动停止")
                    self._ov(r + 1, repeat, "已手动停止")
                    return
                await self.log("info", f"--- 第 {r + 1}/{repeat} 轮 ---")
                self._ov(r + 1, repeat, "本轮开始")
                current = start_id
                visited = 0
                max_steps = max(1000, len(node_map) * 100)  # 单轮步数上限，防无终止环空转
                while current and not self.stopped:
                    visited += 1
                    if visited > max_steps:
                        await self.log("error", f"单轮执行超过 {max_steps} 步（疑似无终止条件的环），已停止")
                        return
                    node = node_map.get(current)
                    if not node:
                        break
                    ntype = node.get("type")
                    params = node.get("params") or {}
                    once = bool(node.get("once"))

                    if ntype == "terminate":
                        await self.log("info", "触发终止条件，立即停止运行")
                        self._ov(r + 1, repeat, "触发终止条件")
                        self.stopped = True
                        return

                    if ntype == "judge":
                        self._ov(r + 1, repeat, self._step_text(node))
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

                    await self.log("info", f"节点: {ntype}", current)
                    self._ov(r + 1, repeat, self._step_text(node))
                    try:
                        await self._run_step(node, input_mode, hwnd, scale_fn)
                    except Exception as e:
                        # 单步失败只记录，不中断整个流程（挂机场景更稳）
                        await self.log("error", f"节点执行失败({ntype}): {e}", current)
                    executed_once.add(current)
                    nxt = adj.get(current, [])
                    current = nxt[0][1] if nxt else None
            await self.log("info", "流程执行完成")
            self._ov(repeat, repeat, "流程执行完成")
        except Exception as e:
            await self.log("error", f"执行异常: {e}")
            self._ov(0, 0, f"执行异常：{e}")
            traceback.print_exc()
        finally:
            self.running = False
            # 广播失败不应把异常抛回调用方（此时 running 已复位，状态本来就正确）
            try:
                await self._state("idle")
            except Exception:
                pass

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
                await self.log("debug", f"正在延时… 剩余 {remaining}ms")
                chunk = min(1000, remaining)
                await asyncio.sleep(chunk / 1000)
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
        else:
            await self.log("warn", f"未知节点类型: {stype}")

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
