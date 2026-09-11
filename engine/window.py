"""窗口模块：枚举任务栏窗口、获取窗口区域、截图指定窗口（ctypes + mss）。"""
import ctypes
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
gdi32 = ctypes.windll.gdi32

# Win32 常量
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
DWMWA_CLOAKED = 14
SW_RESTORE = 9


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def get_window_rect(hwnd: int) -> dict:
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return {
        "left": r.left,
        "top": r.top,
        "right": r.right,
        "bottom": r.bottom,
        "width": r.right - r.left,
        "height": r.bottom - r.top,
    }


def _get_exstyle(hwnd: int) -> int:
    return user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def _is_cloaked(hwnd: int) -> bool:
    """是否被 DWM 隐藏（最小化/虚拟桌面等）。"""
    try:
        val = wintypes.DWORD()
        hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
        return hr == 0 and val.value != 0
    except Exception:
        return False


def _is_taskbar_window(hwnd: int) -> bool:
    """只保留出现在任务栏（Alt-Tab）里的真实应用窗口。"""
    if not user32.IsWindowVisible(hwnd):
        return False
    exstyle = _get_exstyle(hwnd)
    # 显式标记为 APPWINDOW 的优先保留
    if exstyle & WS_EX_APPWINDOW:
        return not _is_cloaked(hwnd)
    # 有属主的窗口（对话框、子窗等）排除
    owner = user32.GetWindow(hwnd, GW_OWNER)
    if owner:
        return False
    # 工具窗口排除
    if exstyle & WS_EX_TOOLWINDOW:
        return False
    # DWM 隐藏窗口排除
    if _is_cloaked(hwnd):
        return False
    return True


def list_windows() -> list[dict]:
    """枚举任务栏上的应用窗口。"""
    result: list[dict] = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if not _is_taskbar_window(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = get_window_rect(hwnd)
        if rect["width"] <= 0 or rect["height"] <= 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.append({"hwnd": hwnd, "title": buf.value, "pid": pid.value, "rect": rect})
        return True

    user32.EnumWindows(proc_type(_cb), 0)
    return result


def get_window(hwnd: int) -> dict | None:
    for w in list_windows():
        if w["hwnd"] == hwnd:
            return w
    return None


def capture_window(hwnd: int) -> np.ndarray:
    """截取指定窗口内容（PrintWindow，可捕获被遮挡/DirectX 窗口），返回 BGR。"""
    # 最小化则先恢复
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.3)
    rect = get_window_rect(hwnd)
    w, h = rect["width"], rect["height"]
    if w <= 0 or h <= 0:
        raise ValueError("窗口不可见或尺寸无效，请先让目标窗口正常显示")

    # 仅用 PrintWindow（直接抓取窗口内容，避免 mss 截到遮挡窗口的屏幕区域）
    frame = _capture_printwindow(hwnd, w, h)
    if frame is None:
        raise ValueError("无法截取该窗口，请确认窗口可见且非独占全屏")
    if float(frame.mean()) <= 0.5:
        raise ValueError("窗口截图为黑屏，可能是独占全屏模式，请改用无边框窗口")
    return frame


def _capture_printwindow(hwnd: int, w: int, h: int):
    """用 PrintWindow(PW_RENDERFULLCONTENT) + ctypes 截取窗口内容，失败返回 None。"""
    try:
        user32.GetWindowDC.restype = ctypes.c_void_p
        user32.GetWindowDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.PrintWindow.restype = wintypes.BOOL
        user32.PrintWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT]
        gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
        gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        gdi32.SelectObject.restype = ctypes.c_void_p
        gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        gdi32.GetDIBits.restype = ctypes.c_int
        gdi32.GetDIBits.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
        ]

        hwnd_dc = user32.GetWindowDC(hwnd)
        if not hwnd_dc:
            return None
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        old = gdi32.SelectObject(mem_dc, bmp)
        ok = user32.PrintWindow(hwnd, mem_dc, 2)  # PW_RENDERFULLCONTENT
        if not ok:
            gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(hwnd, hwnd_dc)
            return None

        class _BMIH(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class _BMI(ctypes.Structure):
            _fields_ = [("bmiHeader", _BMIH)]

        bmi = _BMI()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # 负值：top-down，免垂直翻转
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)

        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)

        if not got:
            return None
        img = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except Exception:
        return None


def capture_window_fast(hwnd: int) -> np.ndarray:
    """用 mss 区域截图（快，要求窗口可见/未被遮挡），返回 BGR。"""
    rect = get_window_rect(hwnd)
    if rect["width"] <= 0 or rect["height"] <= 0:
        raise ValueError("窗口不可见或尺寸无效")
    with mss.mss() as sct:
        mon = {"left": rect["left"], "top": rect["top"], "width": rect["width"], "height": rect["height"]}
        raw = sct.grab(mon)
        return cv2.cvtColor(np.array(raw), cv2.COLOR_BGRA2BGR)


def set_foreground(hwnd: int) -> None:
    user32.SetForegroundWindow(hwnd)
