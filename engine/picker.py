"""坐标拾取：F8 触发，监听真实鼠标左键，捕获屏幕坐标。

基于常驻键盘/鼠标事件总线，不创建、不销毁任何监听器。
"""
from pynput import mouse

import keybus
import mousebus


def _norm_key(key) -> str:
    if hasattr(key, "name"):
        return key.name or ""
    return str(key).lower()


class CoordinatePicker:
    def __init__(self, on_picked) -> None:
        self.on_picked = on_picked
        self._enabled = False  # 允许 F8 触发
        self._armed = False  # 已进入拾取，等待左键单击
        keybus.register(on_press=self._on_key)
        mousebus.register(on_click=self._on_click)

    def _on_key(self, key):
        if _norm_key(key) == "f8" and self._enabled:
            self._armed = True

    def _on_click(self, x, y, button, pressed):
        if self._armed and pressed and button == mouse.Button.left:
            self._armed = False
            self._enabled = False
            self.on_picked(int(x), int(y))

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._armed = False

    def cancel(self) -> None:
        self._armed = False

    def stop(self) -> None:
        keybus.unregister(on_press=self._on_key)
        mousebus.unregister(on_click=self._on_click)
