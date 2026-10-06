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
SW_SHOWNOACTIVATE = 4


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
        # 用 SW_SHOWNOACTIVATE 而不是 SW_RESTORE：SW_RESTORE 会把窗口**激活**到前台，
        # 这正是"最小化后又被弹出来"的来源。这里只把窗口恢复出来，不抢前台。
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
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

# 明确不是浏览器的宿主：控制台 / 终端 / 解释器。
# 这些窗口的标题经常带上项目名（例如承载后端的终端窗口标题就是 AutoTool），
# 一旦被当成 WebUI，点「界面」就会把后端控制台弹到前台。
_NON_BROWSER_EXES = {
    "explorer.exe", "conhost.exe", "openconsole.exe", "windowsterminal.exe", "wt.exe",
    "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe",
    "autotool.exe", "mintty.exe", "bash.exe", "wsl.exe", "code.exe",
}
_NON_BROWSER_CLASSES = (
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",   # Windows Terminal
    "PseudoConsoleWindow",
    "mintty",
)


def is_minimized(hwnd: int) -> bool:
    """窗口是否处于最小化状态（供调用方记录「是谁恢复了窗口」的审计日志）。"""
    try:
        return bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def find_webui_window(page_title: str, exclude_pids: set[int] | None = None) -> dict | None:
    """定位 WebUI 所在的**浏览器**窗口；找不到就返回 None。

    为什么不能只按标题匹配：项目目录经常被资源管理器打开着，其窗口标题恰好就是
    「AutoTool」。因此这里要求窗口**必须真的是浏览器**：

    1. 类名（`Chrome_WidgetWin*` / `MozillaWindowClass`）或进程名看起来像浏览器；
    2. 显式排除控制台/终端/解释器（它们的标题里也常带项目名，例如承载后端的终端）；
    3. 排除自身进程与 explorer.exe。

    ⚠️ 旧实现把「像不像浏览器」只当成**排序键**，没有任何过滤：于是当浏览器窗口
    一个都没匹配上（标签页被切走、标题变了）时，`matched[0]` 会退而求其次返回
    任意同名窗口——实测就是承载后端的终端窗口，表现是「点『界面』把后端控制台
    弹到了前台」。现在改为宁可返回 None（由调用方提示用户），也不乱切窗口。

    排序：未最小化优先 → 面积最大（主窗口而非小面板）。
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
        cls = _class_name(hwnd)
        if exe in _NON_BROWSER_EXES or any(cls.startswith(c) for c in _NON_BROWSER_CLASSES):
            return True
        if not (exe in _BROWSER_EXES or any(cls.startswith(c) for c in _BROWSER_CLASSES)):
            return True  # 不像浏览器：直接丢弃，不再当作后备候选
        matched.append(
            {
                "hwnd": hwnd,
                "title": title,
                "rect": get_window_rect(hwnd),
                "minimized": bool(user32.IsIconic(hwnd)),
                "exe": exe,
                "class": cls,
                "browser": True,
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
            w["minimized"],
            -(w["rect"]["width"] * w["rect"]["height"]),
        )
    )
    return matched[0]


def find_window_of_pid(pid: int, hint: str = "") -> dict | None:
    """按进程号找它的**主窗口**（桌面壳的原生窗口）。

    桌面版里悬浮框的「回到界面」要切回的是壳创建的 Tauri 窗口。它的进程名是
    `autotool.exe`，被 `find_webui_window` 的「必须像浏览器」规则明确排除，
    所以走另一条路：直接按**父进程 pid** 枚举窗口，不再猜进程名。

    只认「可见 + 有标题 + 没有 owner」的顶层窗口（有 owner 的是对话框/工具窗），
    排除工具栏样式与浏览器内核以外的控制台宿主；优先未最小化、面积最大的那个。
    """
    if not pid:
        return None
    hint_l = (hint or "").strip().lower()
    owner = None
    try:
        user32.GetWindow.restype = wintypes.HWND
        owner = user32.GetWindow
    except Exception:
        owner = None

    matched: list[dict] = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        # 有 owner 的顶层窗口是对话框/工具窗，不是主窗口
        try:
            if owner and owner(hwnd, GW_OWNER):
                return True
        except Exception:
            pass
        if _get_exstyle(hwnd) & WS_EX_TOOLWINDOW:
            return True
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if int(wpid.value) != int(pid):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        cls = _class_name(hwnd)
        if any(cls.startswith(c) for c in _NON_BROWSER_CLASSES):
            return True
        matched.append(
            {
                "hwnd": hwnd,
                "title": title,
                "rect": get_window_rect(hwnd),
                "minimized": bool(user32.IsIconic(hwnd)),
                "exe": _process_exe(int(wpid.value)),
                "class": cls,
                "browser": False,
            }
        )
        return True

    try:
        user32.EnumWindows(proc_type(_cb), 0)
    except Exception:
        return None
    if not matched:
        return None

    def _rank(w: dict) -> tuple:
        # 标题带提示词的最优先（多个窗口时不会挑错），其次未最小化、面积最大
        return (
            0 if hint_l and hint_l in w["title"].lower() else 1,
            w["minimized"],
            -(w["rect"]["width"] * w["rect"]["height"]),
        )

    matched.sort(key=_rank)
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


# ---------------------------------------------------------------------------
# 「窗口」节点需要的动作
# ---------------------------------------------------------------------------

SW_MINIMIZE = 6
SW_MAXIMIZE = 3


def find_window_by_title(keyword: str) -> dict | None:
    """按标题关键字找窗口（不区分大小写），优先未最小化、面积最大的那个。

    刻意**不**要求目标像浏览器 —— 「窗口」节点的用途就是"找到任意一个窗口"，
    与找 WebUI 那套规则完全无关。关键字为空时返回 None（由调用方退回绑定窗口）。
    """
    kw = str(keyword or '').strip().lower()
    if not kw:
        return None
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
        if kw not in title.lower():
            return True
        rect = get_window_rect(hwnd)
        if rect['width'] <= 0 or rect['height'] <= 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        matched.append(
            {
                'hwnd': hwnd,
                'title': title,
                'pid': int(pid.value),
                'rect': rect,
                'minimized': bool(user32.IsIconic(hwnd)),
            }
        )
        return True

    try:
        user32.EnumWindows(proc_type(_cb), 0)
    except Exception:
        return None
    if not matched:
        return None
    matched.sort(key=lambda w: (w['minimized'], -(w['rect']['width'] * w['rect']['height'])))
    return matched[0]


def window_rect_with_offset(hwnd: int) -> dict:
    """窗口矩形 + 客户区原点在屏幕上的位置。

    截屏坐标自窗口左上角算起，而 mss 抓的是屏幕区域 —— 两者差一个 rect.left/top。
    统一由这里提供，避免每一处调用各算一遍（旧代码里就漏过 offset）。
    """
    rect = get_window_rect(hwnd)
    return {
        **rect,
        'offset_x': rect['left'],
        'offset_y': rect['top'],
    }


def minimize_window(hwnd: int) -> bool:
    try:
        return bool(user32.ShowWindow(hwnd, SW_MINIMIZE))
    except Exception:
        return False


def maximize_window(hwnd: int) -> bool:
    try:
        return bool(user32.ShowWindow(hwnd, SW_MAXIMIZE))
    except Exception:
        return False


def restore_window(hwnd: int) -> bool:
    """还原（不抢前台）。用 SW_SHOWNOACTIVATE 避免把用户正在看的窗口顶掉。"""
    try:
        return bool(user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE))
    except Exception:
        return False


def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> bool:
    try:
        return bool(user32.MoveWindow(hwnd, int(x), int(y), int(width), int(height), True))
    except Exception:
        return False


def close_window(hwnd: int) -> bool:
    """请求关闭窗口（发 WM_CLOSE，程序可以弹"是否保存"对话框，不会硬杀）。"""
    try:
        return bool(user32.PostMessageW(hwnd, 0x0010, 0, 0))  # WM_CLOSE
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 进程（「进程」节点 / 「命令」节点用）
# ---------------------------------------------------------------------------

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', ctypes.c_wchar * 260),
    ]


def list_processes() -> list[dict]:
    """枚举进程：返回 [{pid, name}]（name 为小写文件名）。"""
    out: list[dict] = []
    try:
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == wintypes.HANDLE(-1).value:
            return out
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
                while True:
                    out.append({'pid': int(entry.th32ProcessID), 'name': str(entry.szExeFile).lower()})
                    if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        return out
    return out


def find_pids_by_name(name: str) -> list[int]:
    """按进程名（大小写不敏感，可带或不带 .exe）找 pid。"""
    target = str(name or '').strip().lower()
    if not target:
        return []
    if not target.endswith('.exe'):
        target_exe = target + '.exe'
    else:
        target_exe = target
    return [p['pid'] for p in list_processes() if p['name'] in (target, target_exe)]


def is_process_running(name: str) -> bool:
    return bool(find_pids_by_name(name))


def kill_process(name: str) -> int:
    """按名字结束所有同名进程，返回成功结束的个数。"""
    done = 0
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    for pid in find_pids_by_name(name):
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
        if not handle:
            continue
        try:
            if kernel32.TerminateProcess(handle, 1):
                done += 1
        finally:
            kernel32.CloseHandle(handle)
    return done

