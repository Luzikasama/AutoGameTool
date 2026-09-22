"""键鼠录制：alt+9 开始/停止，录制事件打包为一个宏步骤。

基于常驻键盘/鼠标事件总线：录制时只切换标志并注册/注销回调，
绝不创建或销毁监听器（反复创建/销毁 Windows 钩子会导致键盘全局失灵）。
"""
import time

from pynput import mouse

import keybus
import mousebus
import overlay
from hotkey import _norm


class Recorder:
    def __init__(self, on_state, on_stop, hotkey=("alt", "9")) -> None:
        self.on_state = on_state  # (recording: bool) -> None
        self.on_stop = on_stop  # (events: list) -> None
        self.hotkey = set(hotkey)
        self.recording = False
        self.events: list[dict] = []
        self._start_time = 0.0
        self._pressed: set[str] = set()
        self._fired = False
        # 已被过滤的按下键（用于把配对的抬起也一起丢掉，避免留下孤立 mouseup）
        self._suppressed: set[str] = set()
        # 键盘回调常驻（用于 alt+9 热键）
        keybus.register(on_press=self._on_press, on_release=self._on_release)

    # ---- 键盘：热键检测 + 录制 ----
    def _on_press(self, key):
        k = _norm(key)
        self._pressed.add(k)
        if self.hotkey.issubset(self._pressed) and not self._fired:
            self._fired = True
            self.toggle()
            return
        if self.recording:
            self.events.append({"t": self._ts(), "type": "keydown", "key": k})

    def _on_release(self, key):
        k = _norm(key)
        self._pressed.discard(k)
        if not self._pressed:
            self._fired = False
        if self.recording:
            self.events.append({"t": self._ts(), "type": "keyup", "key": k})

    # ---- 鼠标 ----
    # 刻意不录制鼠标轨迹（mousemove）：回放时 mouse_down 本身就会把光标移到点击坐标，
    # 轨迹既冗余，又会让录制结果臃肿、难以拆分成可编辑的步骤。
    def _on_click(self, x, y, button, pressed):
        b = "right" if button == mouse.Button.right else ("middle" if button == mouse.Button.middle else "left")
        # 点在自己身上的按下/抬起都不录：否则用悬浮框按钮开始或停止录制时，
        # 这一下点击会被录进宏里，回放时又点到同一个按钮 → 递归录制。
        if pressed:
            if overlay.hit_test(x, y):
                self._suppressed.add(b)
                return
        elif b in self._suppressed:
            self._suppressed.discard(b)
            return
        self.events.append(
            {
                "t": self._ts(),
                "type": "mousedown" if pressed else "mouseup",
                "x": int(x),
                "y": int(y),
                "button": b,
            }
        )

    def _on_scroll(self, x, y, dx, dy):
        if overlay.hit_test(x, y):
            return
        self.events.append(
            {"t": self._ts(), "type": "scroll", "x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)}
        )

    # ---- 控制 ----
    def toggle(self) -> None:
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.recording:
            return
        self.recording = True
        self.events = []
        self._suppressed.clear()
        self._start_time = time.time()
        # 只注册点击/滚轮回调（不再需要 on_move），监听器本身常驻
        mousebus.register(on_click=self._on_click, on_scroll=self._on_scroll)
        self.on_state(True)

    def stop(self) -> None:
        if not self.recording:
            return
        self.recording = False
        mousebus.unregister(on_click=self._on_click, on_scroll=self._on_scroll)
        events = list(self.events)
        self.events = []
        # 去掉因按开始/停止快捷键产生的残留事件
        while events and events[0].get("type") == "keyup" and events[0].get("key") in self.hotkey:
            events.pop(0)
        while events and events[-1].get("type") == "keydown" and events[-1].get("key") in self.hotkey:
            events.pop()
        self.on_state(False)
        self.on_stop(events)

    def _ts(self) -> int:
        return int((time.time() - self._start_time) * 1000)

    def stop_all(self) -> None:
        """仅注销回调，绝不销毁总线监听器。"""
        try:
            if self.recording:
                self.recording = False
                mousebus.unregister(on_click=self._on_click, on_scroll=self._on_scroll)
            keybus.unregister(on_press=self._on_press, on_release=self._on_release)
        except Exception:
            pass
