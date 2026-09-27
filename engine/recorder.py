"""键鼠录制：录制事件打包为一个宏步骤。

基于常驻键盘/鼠标事件总线：录制时只切换标志并注册/注销回调，
绝不创建或销毁监听器（反复创建/销毁 Windows 钩子会导致键盘全局失灵）。

触发键（默认 alt+F2，可在界面里改）由 `hotkey.HotkeyManager` 统一匹配；
本模块只用 `hotkey` 记住**当前录制快捷键是哪几个键**，好在停止时把「按快捷键
本身产生的那几下按键」从录制结果里剔掉（否则每段录制都会自带 alt+f2）。
"""
import time

from pynput import mouse

import keybus
import mousebus
import overlay
from hotkey import _norm, normalize_key


class Recorder:
    def __init__(self, on_state, on_stop, hotkey=("alt", "f2")) -> None:
        self.on_state = on_state  # (recording: bool) -> None
        self.on_stop = on_stop  # (events: list) -> None
        self.hotkey = set(normalize_key(k) for k in hotkey)
        self.recording = False
        self.events: list[dict] = []
        self._start_time = 0.0
        # 已被过滤的按下键（用于把配对的抬起也一起丢掉，避免留下孤立 mouseup）
        self._suppressed: set[str] = set()
        # 键盘回调常驻（录制按键；快捷键匹配不在这里）
        keybus.register(on_press=self._on_press, on_release=self._on_release)

    def set_hotkey(self, keys) -> None:
        """快捷键改键后同步过来（只影响录制结果的收尾清理）。"""
        self.hotkey = set(normalize_key(k) for k in (keys or []))

    # ---- 键盘：录制 ----
    def _on_press(self, key):
        if self.recording:
            self.events.append({"t": self._ts(), "type": "keydown", "key": _norm(key)})

    def _on_release(self, key):
        if self.recording:
            self.events.append({"t": self._ts(), "type": "keyup", "key": _norm(key)})

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
        events = self._strip_hotkey_events(events)
        self.on_state(False)
        self.on_stop(events)

    def _strip_hotkey_events(self, events: list) -> list:
        """剔掉因按「录制快捷键本身」而产生的按键事件。

        开始那一下落在开头（快捷键匹配先触发录制，紧接着同一次按键才被录进来），
        停止那一下的 keydown 落在结尾（keyup 在录制结束之后，不会被录到）。
        必须「凑齐整组快捷键」才剔：否则用户录制时开头就按住 alt（比如 alt+点击）
        的那一下会被误删——它与快捷键共用 alt 这个键名。
        """
        starts = 0
        for ev in events:
            if ev.get("type") in ("keydown", "keyup") and ev.get("key") in self.hotkey:
                starts += 1
            else:
                break
        if self.hotkey and self.hotkey.issubset({e.get("key") for e in events[:starts]}):
            events = events[starts:]

        ends = 0
        for ev in reversed(events):
            if ev.get("type") == "keydown" and ev.get("key") in self.hotkey:
                ends += 1
            else:
                break
        if self.hotkey and self.hotkey.issubset({e.get("key") for e in events[len(events) - ends:]}):
            events = events[: len(events) - ends]
        return events

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
