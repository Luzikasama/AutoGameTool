"""全局鼠标事件总线：整个进程只创建一个常驻 pynput 鼠标监听器。

同样严禁反复创建/销毁，避免破坏 Windows 低级鼠标钩子链。
所有需要鼠标事件的模块都通过 register() 注册回调，回调内自行判断是否处理。
"""
from pynput import mouse

_move_cbs: list = []
_click_cbs: list = []
_scroll_cbs: list = []
_listener = None


def _ensure() -> None:
    global _listener
    if _listener is None:
        _listener = mouse.Listener(
            on_move=_dispatch_move, on_click=_dispatch_click, on_scroll=_dispatch_scroll
        )
        _listener.daemon = True
        _listener.start()


def _dispatch_move(x, y) -> None:
    for cb in tuple(_move_cbs):
        try:
            cb(x, y)
        except Exception:
            pass


def _dispatch_click(x, y, button, pressed) -> None:
    for cb in tuple(_click_cbs):
        try:
            cb(x, y, button, pressed)
        except Exception:
            pass


def _dispatch_scroll(x, y, dx, dy) -> None:
    for cb in tuple(_scroll_cbs):
        try:
            cb(x, y, dx, dy)
        except Exception:
            pass


def register(on_move=None, on_click=None, on_scroll=None) -> None:
    if on_move is not None and on_move not in _move_cbs:
        _move_cbs.append(on_move)
    if on_click is not None and on_click not in _click_cbs:
        _click_cbs.append(on_click)
    if on_scroll is not None and on_scroll not in _scroll_cbs:
        _scroll_cbs.append(on_scroll)
    _ensure()


def unregister(on_move=None, on_click=None, on_scroll=None) -> None:
    for lst, cb in ((_move_cbs, on_move), (_click_cbs, on_click), (_scroll_cbs, on_scroll)):
        if cb is not None and cb in lst:
            lst.remove(cb)
