"""流程执行器：图执行（支持判断分支、单次执行、终止条件、循环与全局启停）。"""
import asyncio
import time
import traceback
from typing import Any, Callable

import inputctl
import vision
import window


class Executor:
    def __init__(self, broadcast: Callable[[dict], Any]) -> None:
        self.broadcast = broadcast
        self.stopped = False
        self.running = False
        self.current_flow: dict | None = None

    def stop(self) -> None:
        self.stopped = True

    async def log(self, level: str, msg: str, step: str | None = None) -> None:
        await self.broadcast(
            {"type": "log", "level": level, "message": msg, "step": step, "ts": time.time()}
        )

    async def _state(self, state: str) -> None:
        await self.broadcast({"type": "state", "state": state, "ts": time.time()})

    async def toggle(self) -> None:
        """全局快捷键启停。"""
        if self.running:
            self.stop()
            await self.log("warn", "快捷键触发：停止")
        elif self.current_flow:
            await self.log("info", "快捷键触发：启动")
            await self.run(self.current_flow)
        else:
            await self.log("warn", "暂无已加载流程，无法通过快捷键启动")

    async def run(self, flow: dict) -> None:
        self.current_flow = flow
        self.stopped = False
        self.running = True
        await self._state("running")
        repeat = max(1, int(flow.get("repeat", 1)))
        nodes = flow.get("nodes", [])
        edges = flow.get("edges", [])
        input_mode = flow.get("input_mode", "real")
        win = flow.get("window")
        hwnd = win.get("hwnd") if isinstance(win, dict) else None
        await self.log(
            "info",
            f"开始执行「{flow.get('name', '未命名')}」：{len(nodes)} 节点 × {repeat} 轮，输入模式={input_mode}",
        )
        try:
            node_map = {n["id"]: n for n in nodes}
            adj: dict[str, list[tuple[str, str]]] = {}
            for e in edges:
                adj.setdefault(e["source"], []).append((e.get("sourceHandle") or "", e["target"]))
            targets = {e["target"] for e in edges}
            starts = [n["id"] for n in nodes if n["id"] not in targets]
            if not starts:
                await self.log("error", "流程缺少起始节点")
                return
            start_id = starts[0]
            executed_once: set[str] = set()

            for r in range(repeat):
                if self.stopped:
                    await self.log("warn", "已手动停止")
                    return
                await self.log("info", f"--- 第 {r + 1}/{repeat} 轮 ---")
                current = start_id
                while current and not self.stopped:
                    node = node_map.get(current)
                    if not node:
                        break
                    ntype = node.get("type")
                    params = node.get("params") or {}
                    once = bool(node.get("once"))

                    if ntype == "terminate":
                        await self.log("info", "触发终止条件，立即停止运行")
                        self.stopped = True
                        return

                    if ntype == "judge":
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
                    try:
                        await self._run_step(node, input_mode, hwnd)
                    except Exception as e:
                        # 单步失败只记录，不中断整个流程（挂机场景更稳）
                        await self.log("error", f"节点执行失败({ntype}): {e}", current)
                    executed_once.add(current)
                    nxt = adj.get(current, [])
                    current = nxt[0][1] if nxt else None
            await self.log("info", "流程执行完成")
        except Exception as e:
            await self.log("error", f"执行异常: {e}")
            traceback.print_exc()
        finally:
            self.running = False
            await self._state("idle")

    async def _do_judge(self, params: dict, input_mode: str, hwnd) -> bool:
        tpl_id = params.get("template")
        threshold = float(params.get("threshold", 0.85))
        timeout_ms = int(params.get("timeout_ms", 5000))
        try:
            template = vision.load_template(tpl_id)
        except FileNotFoundError:
            await self.log("error", f"判断模板不存在: {tpl_id}")
            return False
        start = time.time()
        while not self.stopped:
            try:
                frame = self._capture(hwnd, input_mode)
            except Exception as e:
                await self.log("error", f"判断截图失败: {e}")
                return False
            found, _, _, score = vision.match_template(frame, template, threshold)
            if found:
                await self.log("info", f"判断：找到「{tpl_id}」（{score:.3f}）→ 成功分支")
                return True
            if time.time() - start > timeout_ms / 1000:
                await self.log("info", f"判断：超时未找到「{tpl_id}」→ 失败分支")
                return False
            await asyncio.sleep(0.2)
        return False

    async def _run_step(self, node: dict, input_mode: str, hwnd) -> None:
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
            inputctl.click(x, y, params.get("button", "left"), int(params.get("clicks", 1)), input_mode, hwnd)
            await self.log("debug", f"点击 ({x}, {y}) 按键={params.get('button', 'left')} 模式={input_mode}")
        elif stype == "key":
            key = str(params.get("key", ""))
            inputctl.press_key(key, input_mode, hwnd)
            await self.log("debug", f"按键 {key} 模式={input_mode}")
        elif stype == "text":
            text = str(params.get("text", ""))
            inputctl.type_text(text, input_mode, hwnd)
            await self.log("debug", f"输入文本 {text!r}")
        elif stype == "macro":
            await self._run_macro(params, input_mode, hwnd)
        else:
            await self.log("warn", f"未知节点类型: {stype}")

    async def _run_macro(self, params: dict, input_mode: str, hwnd) -> None:
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
                    inputctl.move(ev.get("x", 0), ev.get("y", 0), input_mode, hwnd)
                elif etype == "mousedown":
                    inputctl.mouse_down(ev.get("x", 0), ev.get("y", 0), ev.get("button", "left"), input_mode, hwnd)
                elif etype == "mouseup":
                    inputctl.mouse_up(ev.get("x", 0), ev.get("y", 0), ev.get("button", "left"), input_mode, hwnd)
                elif etype == "scroll":
                    inputctl.scroll(ev.get("dx", 0), ev.get("dy", 0))
                elif etype == "keydown":
                    inputctl.key_down(str(ev.get("key", "")), input_mode, hwnd)
                elif etype == "keyup":
                    inputctl.key_up(str(ev.get("key", "")), input_mode, hwnd)
            except Exception as e:
                await self.log("warn", f"回放事件失败({etype}): {e}")
        await self.log("info", "录制回放完成")

    async def _do_find(self, params: dict, input_mode: str, hwnd) -> None:
        tpl_id = params.get("template")
        threshold = float(params.get("threshold", 0.85))
        timeout_ms = int(params.get("timeout_ms", 5000))
        do_click = bool(params.get("click", False))
        try:
            template = vision.load_template(tpl_id)
        except FileNotFoundError:
            await self.log("error", f"模板不存在: {tpl_id}")
            return
        offset_x = offset_y = 0
        if hwnd:
            rect = window.get_window_rect(hwnd)
            offset_x, offset_y = rect["left"], rect["top"]
        start = time.time()
        while not self.stopped:
            try:
                frame = self._capture(hwnd, input_mode)
            except Exception as e:
                await self.log("error", f"窗口截图失败: {e}")
                return
            found, x, y, score = vision.match_template(frame, template, threshold)
            if found:
                sx, sy = x + offset_x, y + offset_y
                await self.log("info", f"找到模板「{tpl_id}」位置 ({sx}, {sy}) 相似度 {score:.3f}")
                if do_click:
                    inputctl.click(sx, sy, "left", 1, input_mode, hwnd)
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
                return window.capture_window(hwnd)  # PrintWindow（后台也能截）
            return window.capture_window_fast(hwnd)  # mss（快，窗口需可见）
        return vision.grab_frame()
