"""窗口模块：枚举任务栏窗口、获取窗口区域、截图指定窗口（ctypes + mss）。"""
import ctypes
import os
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi
gdi32 = ctypes.windll.gdi32

# Win32 常量
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
DWMWA_CLOAKED = 14
SW_RESTORE = 9


class WindowMinimizedError(ValueError):
    """目标窗口已最小化，且调用方不允许引擎自动把它弹出来。

    继承 ValueError，使既有的 `except ValueError` 分支无需改动也能捕获。
    """


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


def capture_window(hwnd: int, restore_minimized: bool = False) -> np.ndarray:
    """截取指定窗口内容（PrintWindow，可捕获被遮挡/DirectX 窗口），返回 BGR。

    `restore_minimized=False`（默认）时，若窗口已最小化就抛 WindowMinimizedError，
    **不**自动把窗口弹出来。原因：挂机时用户常常故意把窗口最小化，旧版无条件
    ShowWindow(SW_RESTORE) 会让窗口反复弹回前台，表现为"最小化失败"
    （代码审查报告 R3）。需要弹窗的调用方（用户主动点击的预览/取模板）显式传 True。
    """
    if user32.IsIconic(hwnd):
        if not restore_minimized:
            raise WindowMinimizedError(
                "目标窗口已最小化。为避免打断你正在做的事，引擎不会自动把它弹到前台；"
                "请先恢复该窗口，或在界面里用「截取」手动抓取。"
            )
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


def _process_exe(pid: int) -> str:
    """取进程可执行文件名（小写，仅文件名），失败返回空串。"""
    try:
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


# 常见浏览器进程名 / 窗口类名（Chromium 系与 Firefox 系的类名很稳定，
# 比只认 exe 名字更能覆盖改了名的 Chromium 套壳浏览器）
_BROWSER_EXES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "vivaldi.exe", "chromium.exe", "thorium.exe", "arc.exe", "iexplore.exe",
    "360se.exe", "360chrome.exe", "qqbrowser.exe", "sogouexplorer.exe",
    "maxthon.exe", "ucbrowser.exe", "liebao.exe", "theworld.exe", "avastbrowser.exe",
}
_BROWSER_CLASSES = ("Chrome_WidgetWin", "MozillaWindowClass")


def find_webui_window(page_title: str, exclude_pids: set[int] | None = None) -> dict | None:
    """定位 WebUI 所在的**浏览器**窗口。

    为什么不能只按标题匹配：项目目录经常被资源管理器打开着，其窗口标题恰好就是
    「AutoGameTool」。旧实现只按标题找、还优先选未最小化的窗口，于是「界面」按钮
    永远弹出资源管理器而不是最小化的浏览器。因此这里再加两道约束：

    1. 类名或进程名必须看起来像浏览器；
    2. 排除自身进程与 explorer.exe。

    排序：先浏览器 → 再未最小化 → 最后取面积最大的（主窗口而非小面板）。
    """
    hint = (page_title or "").strip().lower()
    if not hint:
        return None
    exclude = set(exclude_pids or ())
    exclude.add(os.getpid())

    matched: list[dict] = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if hint not in title.lower():
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in exclude:
            return True
        exe = _process_exe(pid.value)
        if exe == "explorer.exe":
            return True
        cls = _class_name(hwnd)
        is_browser = exe in _BROWSER_EXES or any(cls.startswith(c) for c in _BROWSER_CLASSES)
        rect = get_window_rect(hwnd)
        matched.append(
            {
                "hwnd": hwnd,
                "title": title,
                "rect": rect,
                "minimized": bool(user32.IsIconic(hwnd)),
                "exe": exe,
                "class": cls,
                "browser": is_browser,
            }
        )
        return True

    try:
        user32.EnumWindows(proc_type(_cb), 0)
    except Exception:
        return None
    if not matched:
        return None
    matched.sort(
        key=lambda w: (
            not w["browser"],
            w["minimized"],
            -(w["rect"]["width"] * w["rect"]["height"]),
        )
    )
    return matched[0]


def focus_window(hwnd: int) -> bool:
    """把窗口恢复（若已最小化）并切到前台，成功返回 True。

    用同步的 ShowWindow 而不是 ShowWindowAsync：后者只是把请求投递到目标线程的
    消息队列，若目标线程没有在跑消息泵就永远不会生效。
    """
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        if user32.SetForegroundWindow(hwnd):
            return True
        # 兜底：把本线程输入附加到当前前台线程后再切换（Windows 限制前台切换权限）
        fg = user32.GetForegroundWindow()
        if fg and fg != hwnd:
            tid_fg = user32.GetWindowThreadProcessId(fg, None)
            tid_self = kernel32.GetCurrentThreadId()
            if tid_fg and tid_fg != tid_self:
                user32.AttachThreadInput(tid_self, tid_fg, True)
                try:
                    user32.SetForegroundWindow(hwnd)
                finally:
                    user32.AttachThreadInput(tid_self, tid_fg, False)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False
