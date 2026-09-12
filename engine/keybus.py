"""全局键盘事件总线：整个进程只创建一个常驻 pynput 键盘监听器。

严禁反复创建/销毁键盘监听器——那会破坏 Windows 低级键盘钩子链，导致键盘全局失灵。
所有需要键盘事件的模块都通过 register() 注册回调。
"""
from pynput import keyboard

_press_cbs: list = []
_release_cbs: list = []
_listener = None
_press_count = 0
_release_count = 0


def counts() -> dict:
    # 安全：不返回按键内容（_last_key），防止调试接口被用作远程键盘记录器
    return {"press": _press_count, "release": _release_count, "alive": bool(_listener and _listener.running)}


def _ensure() -> None:
    global _listener
    if _listener is None:
        _listener = keyboard.Listener(on_press=_dispatch_press, on_release=_dispatch_release)
        _listener.daemon = True
        _listener.start()


def _dispatch_press(key) -> None:
    global _press_count
    _press_count += 1
    for cb in tuple(_press_cbs):
        try:
            cb(key)
        except Exception:
            pass


def _dispatch_release(key) -> None:
    global _release_count
    _release_count += 1
    for cb in tuple(_release_cbs):
        try:
            cb(key)
        except Exception:
            pass


def register(on_press=None, on_release=None) -> None:
    if on_press is not None and on_press not in _press_cbs:
        _press_cbs.append(on_press)
    if on_release is not None and on_release not in _release_cbs:
        _release_cbs.append(on_release)
    _ensure()


def unregister(on_press=None, on_release=None) -> None:
    if on_press is not None and on_press in _press_cbs:
        _press_cbs.remove(on_press)
    if on_release is not None and on_release in _release_cbs:
        _release_cbs.remove(on_release)
