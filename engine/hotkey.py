"""全局快捷键监听（基于常驻键盘事件总线），默认 alt+f1。"""
from pynput import keyboard

import appconfig
import keybus

# 纯修饰键：它们不用于「解除已触发锁」，否则按住 alt 连按 f1 会重复触发
_MODIFIERS = {"ctrl", "alt", "shift", "win"}


def _norm(key) -> str:
    if isinstance(key, keyboard.Key):
        name = key.name or ""
        if name.startswith("alt"):
            return "alt"
        if name.startswith("ctrl"):
            return "ctrl"
        if name.startswith("shift"):
            return "shift"
        if name.startswith("cmd"):  # pynput 的 Win 键叫 cmd/cmd_l/cmd_r，前端记为 win
            return "win"
        return name
    if isinstance(key, keyboard.KeyCode):
        return (key.char or "").lower()
    return str(key).lower()


class HotkeyManager:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.keys = self._load()
        self.pressed: set[str] = set()
        self._fired = False
        keybus.register(on_press=self._on_press, on_release=self._on_release)

    def _load(self) -> list[str]:
        keys = appconfig.get("hotkey", ["alt", "f1"])
        if isinstance(keys, list) and keys:
            return [str(k).lower() for k in keys]
        return ["alt", "f1"]

    def get(self) -> list[str]:
        return list(self.keys)

    def set(self, keys: list[str]) -> None:
        cleaned = [str(k).strip().lower() for k in keys if str(k).strip()]
        if not cleaned:
            raise ValueError("快捷键不能为空")
        self.keys = cleaned
        # 原子写入交由 appconfig 统一处理，避免多处读-改-写互相覆盖
        appconfig.update(hotkey=self.keys)

    def _on_press(self, key):
        self.pressed.add(_norm(key))
        target = set(self.keys)
        if target and target.issubset(self.pressed) and not self._fired:
            self._fired = True
            self.callback()

    def _on_release(self, key):
        k = _norm(key)
        self.pressed.discard(k)
        # 组合键里的**非修饰键**一抬起就解除「已触发」锁。
        # 旧实现只在「所有键都松开」时解锁，于是按住 alt 连按两次 f1 只会触发第一次
        # （第二次按下时 alt 仍按着，_fired 还是 True）——手感就是「快捷键时灵时不灵」。
        # 这样改仍保留原有保护：长按 f1 时系统重复发的是 keydown（没有 keyup），
        # 不会重复触发。
        if k in self.keys and k not in _MODIFIERS:
            self._fired = False
        if not self.pressed:
            self._fired = False

    def stop(self) -> None:
        """仅注销回调，绝不销毁总线监听器。"""
        keybus.unregister(on_press=self._on_press, on_release=self._on_release)
