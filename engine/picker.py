"""坐标拾取：快捷键触发后，监听真实鼠标左键，捕获屏幕坐标。

基于常驻鼠标事件总线，不创建、不销毁任何监听器。
触发键本身由 `hotkey.HotkeyManager` 统一匹配（默认 alt+F3，可在界面里改），
本模块只提供 `arm()`：进入「等一次左键单击」的状态。
"""
from pynput import mouse

import mousebus


class CoordinatePicker:
    def __init__(self, on_picked) -> None:
        self.on_picked = on_picked
        self._enabled = False  # 允许快捷键触发（由「拾取」按钮/接口打开）
        self._armed = False  # 已进入拾取，等待左键单击
        mousebus.register(on_click=self._on_click)

    def arm(self) -> None:
        """快捷键按下：进入拾取等待（未启用时什么都不做）。"""
        if self._enabled:
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
        mousebus.unregister(on_click=self._on_click)
