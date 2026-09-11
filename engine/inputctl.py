"""键鼠控制：真实输入（pynput）与模拟输入（PostMessage 后台消息，不占用键鼠）。

模拟输入要点：
- 鼠标消息发给「该点下最深的子窗口」并用其客户区坐标（很多程序真正接收输入的是子窗口）
- 键盘消息发给「目标窗口所在线程的焦点窗口」
- 使用完整的 lParam（含扫描码），提升兼容性
"""
import ctypes
import time
from ctypes import wintypes

from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController

_mouse = MouseController()
_keyboard = KeyboardController()

user32 = ctypes.windll.user32

# ---- 正确的 API 签名（保证 64 位句柄不被截断）----
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.ScreenToClient.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.WindowFromPoint.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.c_void_p]
user32.VkKeyScanW.restype = ctypes.c_short
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]

GA_ROOT = 2

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

_VK = {
    "enter": 0x0D, "esc": 0x1B, "space": 0x20, "tab": 0x09,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "page_up": 0x21, "page_down": 0x22,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

_KEY_MAP = {
    "enter": Key.enter, "esc": Key.esc, "space": Key.space, "tab": Key.tab,
    "shift": Key.shift, "ctrl": Key.ctrl, "alt": Key.alt,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "backspace": Key.backspace, "delete": Key.delete,
    "home": Key.home, "end": Key.end,
    "page_up": Key.page_up, "page_down": Key.page_down,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4, "f5": Key.f5, "f6": Key.f6,
    "f7": Key.f7, "f8": Key.f8, "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


# ---------- 公共入口 ----------
def click(x: int, y: int, button: str = "left", clicks: int = 1, mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        _sim_click(int(hwnd), int(x), int(y), button, int(clicks))
    else:
        _real_click(int(x), int(y), button, int(clicks))


def move(x: int, y: int, mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        target = _target_at(int(hwnd), int(x), int(y))
        cx, cy = _to_client(target, int(x), int(y))
        user32.PostMessageW(target, WM_MOUSEMOVE, 0, _mouse_lparam(cx, cy))
    else:
        _mouse.position = (int(x), int(y))


def press_key(key: str, mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        target = _focus_of(int(hwnd))
        vk = _key_to_vk(key)
        if vk:
            user32.PostMessageW(target, WM_KEYDOWN, vk, _key_lparam(vk, False))
            time.sleep(0.03)
            user32.PostMessageW(target, WM_KEYUP, vk, _key_lparam(vk, True))
    else:
        k = _map_key(key)
        _keyboard.press(k)
        _keyboard.release(k)


def type_text(text: str, mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        target = _focus_of(int(hwnd))
        for ch in str(text):
            user32.PostMessageW(target, WM_CHAR, ord(ch), 1)
            time.sleep(0.01)
    else:
        _keyboard.type(str(text))


def mouse_down(x: int, y: int, button: str = "left", mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        target = _target_at(int(hwnd), int(x), int(y))
        cx, cy = _to_client(target, int(x), int(y))
        user32.PostMessageW(target, _down_msg(button), 0, _mouse_lparam(cx, cy))
    else:
        _mouse.position = (int(x), int(y))
        _mouse.press(_btn(button))


def mouse_up(x: int, y: int, button: str = "left", mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        target = _target_at(int(hwnd), int(x), int(y))
        cx, cy = _to_client(target, int(x), int(y))
        user32.PostMessageW(target, _up_msg(button), 0, _mouse_lparam(cx, cy))
    else:
        _mouse.position = (int(x), int(y))
        _mouse.release(_btn(button))


def key_down(key: str, mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        target = _focus_of(int(hwnd))
        vk = _key_to_vk(key)
        if vk:
            user32.PostMessageW(target, WM_KEYDOWN, vk, _key_lparam(vk, False))
    else:
        _keyboard.press(_map_key(key))


def key_up(key: str, mode: str = "real", hwnd: int | None = None) -> None:
    if mode == "simulated" and hwnd:
        target = _focus_of(int(hwnd))
        vk = _key_to_vk(key)
        if vk:
            user32.PostMessageW(target, WM_KEYUP, vk, _key_lparam(vk, True))
    else:
        _keyboard.release(_map_key(key))


def scroll(dx: int, dy: int) -> None:
    _mouse.scroll(int(dx), int(dy))


def probe(hwnd: int, x: int, y: int) -> dict:
    """诊断：报告目标窗口/子窗口/坐标/PostMessage 结果。"""
    h = int(hwnd)
    valid = bool(user32.IsWindow(h))
    target = _target_at(h, int(x), int(y))
    cx, cy = _to_client(target, int(x), int(y))
    focus = _focus_of(h)
    ok = bool(user32.PostMessageW(target, WM_MOUSEMOVE, 0, _mouse_lparam(cx, cy)))
    return {
        "hwnd": h,
        "hwnd_valid": valid,
        "child": int(target),
        "child_is_hwnd": int(target) == h,
        "client": [cx, cy],
        "focus": int(focus),
        "post_ok": ok,
    }


# ---------- 真实输入 ----------
def _real_click(x: int, y: int, button: str, clicks: int) -> None:
    _mouse.position = (x, y)
    time.sleep(0.05)
    for i in range(max(1, clicks)):
        _mouse.click(_btn(button))
        if i < clicks - 1:
            time.sleep(0.05)


# ---------- 模拟输入内部 ----------
def _sim_click(hwnd: int, x: int, y: int, button: str, clicks: int) -> None:
    target = _target_at(hwnd, x, y)
    cx, cy = _to_client(target, x, y)
    lp = _mouse_lparam(cx, cy)
    down, up = _down_msg(button), _up_msg(button)
    for _ in range(max(1, clicks)):
        user32.PostMessageW(target, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.02)
        user32.PostMessageW(target, down, 0, lp)
        time.sleep(0.03)
        user32.PostMessageW(target, up, 0, lp)
        time.sleep(0.03)


def _target_at(hwnd: int, sx: int, sy: int) -> int:
    """返回该屏幕点下、与目标窗口同一根窗口的最深子窗口。"""
    try:
        pt = wintypes.POINT(int(sx), int(sy))
        child = user32.WindowFromPoint(pt)
        if child and user32.GetAncestor(child, GA_ROOT) == user32.GetAncestor(hwnd, GA_ROOT):
            return int(child)
    except Exception:
        pass
    return int(hwnd)


def _to_client(hwnd: int, sx: int, sy: int):
    pt = wintypes.POINT(int(sx), int(sy))
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def _focus_of(hwnd: int) -> int:
    """返回目标窗口所属线程的焦点窗口（键盘消息应发给它）。"""
    try:
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
            if gti.hwndFocus:
                return int(gti.hwndFocus)
            if gti.hwndActive:
                return int(gti.hwndActive)
    except Exception:
        pass
    return int(hwnd)


def _mouse_lparam(cx: int, cy: int) -> int:
    return ((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF)


def _key_lparam(vk: int, up: bool) -> int:
    scan = int(user32.MapVirtualKeyW(int(vk), 0)) & 0xFF
    lp = 1 | (scan << 16)
    if up:
        lp |= (1 << 30) | (1 << 31)
    return lp


def _btn(button: str):
    if button == "right":
        return Button.right
    if button == "middle":
        return Button.middle
    return Button.left


def _down_msg(button: str) -> int:
    if button == "right":
        return WM_RBUTTONDOWN
    if button == "middle":
        return WM_MBUTTONDOWN
    return WM_LBUTTONDOWN


def _up_msg(button: str) -> int:
    if button == "right":
        return WM_RBUTTONUP
    if button == "middle":
        return WM_MBUTTONUP
    return WM_LBUTTONUP


def _key_to_vk(key: str) -> int | None:
    k = str(key).lower()
    if k in _VK:
        return _VK[k]
    if len(k) == 1:
        # 注意：VkKeyScanW 接收「字符」而不是整数
        vk = user32.VkKeyScanW(k)
        if vk != -1:
            return int(vk) & 0xFF
    return None


def _map_key(key: str):
    k = str(key).lower()
    if k in _KEY_MAP:
        return _KEY_MAP[k]
    if len(k) == 1:
        return k
    return key
