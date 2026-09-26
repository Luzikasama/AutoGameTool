"""悬浮框：置顶小窗显示运行进度，并提供启停 / 录制 / 循环次数 / 回到界面 四个快捷操作。

「回到界面」是标题栏右上角的矢量图标（点它把 WebUI 浏览器窗口切回前台），
其余三个是底部操作行上的按钮。

为什么由引擎而不是网页来画：浏览器无法创建真正置顶于其它程序（尤其游戏）之上的窗口。
这里用 tkinter 在独立线程里开一个无边框、置顶、可拖拽、**不抢焦点**的小窗。

线程模型：引擎主线程跑 uvicorn 事件循环，而 Tk 必须在创建它的线程里 mainloop。
因此外部只往队列投递指令/数据，Tk 线程用 after() 定时消费，双方不共享 Tk 对象。
按钮回调同理——只把动作名交给 on_action，由引擎切回事件循环线程再执行。

两处针对「最小化别的窗口失败」的专门处理：
1. 窗口加 WS_EX_NOACTIVATE，点击悬浮框不会夺走前台焦点；
2. 置顶只在**确实丢失 topmost 时**才写 Z 序（旧版每 2 秒无条件 SetWindowPos，
   会在别的窗口播放最小化动画时搅动 Z 序，导致最小化偶发失败）。

可靠性：tkinter 缺失或初始化失败时降级为空实现（available=False），
所有对外方法都变成无副作用的空操作，绝不影响引擎的其它功能。
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from typing import Callable

_POLL_MS = 120        # 队列消费间隔
_MARGIN = 24
# 循环轮数范围（与引擎侧 _REPEAT_MIN/_REPEAT_MAX 保持一致）
_REPEAT_MIN = 1
_REPEAT_MAX = 9999
_WIDTH = 300

_BG = "#0f172a"
_BORDER = "#334155"
_FG_MAIN = "#f8fafc"
_FG_SUB = "#94a3b8"
_ACCENT = "#22d3ee"
_FONT = "Microsoft YaHei UI"

_BTN_BG = "#1e293b"
_BTN_FG = "#e2e8f0"
_BTN_ACTIVE = "#334155"
_BTN_DISABLED = "#475569"
_RUN_BG = "#7f1d1d"      # 运行中：停止按钮
_IDLE_BG = "#14532d"     # 空闲：启动按钮
_REC_BG = "#7c2d12"      # 录制中
_PAUSE_BG = "#78350f"    # 已暂停：继续按钮

# --- Win32 常量 ---
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_HWND_TOPMOST = -1


class Overlay:
    def __init__(
        self,
        on_close: Callable[[], None] | None = None,
        on_action: Callable[[str], None] | None = None,
    ) -> None:
        self._q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._on_close = on_close
        self._on_action = on_action

        # 状态字段会被任意线程读写，但都是单次赋值，无需加锁
        self._enabled = False
        self._available = True
        self._visible = False
        self._error = ""
        self._loop = 0
        self._total = 0
        self._repeat = 1
        self._running = False
        self._paused = False
        self._recording = False
        self._step = "等待运行"

        # 仅 Tk 线程使用
        self._root = None
        self._hwnd = 0
        self._geom = ""
        self._btn_run = None
        self._btn_pause = None
        self._btn_rec = None
        self._btn_minus = None
        self._btn_plus = None
        self._entry_repeat = None
        self._editing_repeat = False
        self._activating = False
        self._progress = None
        self._step_lbl = None
        self._drag_from = (0, 0)
        self._win_at = (0, 0)
        self._stopping = False

    # ---------------------------------------------------- 对外接口（任意线程可调）
    def start(self, enabled: bool = False) -> None:
        if self._thread is not None:
            return
        self._enabled = bool(enabled)
        self._thread = threading.Thread(target=self._main, name="agt-overlay", daemon=True)
        self._thread.start()
        self._q.put(("enabled", self._enabled))

    def stop(self) -> None:
        self._q.put(("quit", None))

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._q.put(("enabled", self._enabled))

    def update(self, loop: int, total: int, step: str) -> None:
        """更新循环进度与当前步骤（执行器调用）。"""
        self._loop = int(loop)
        self._total = int(total)
        self._step = str(step or "")
        self._push(("text", None))

    def set_run_state(self, running: bool) -> None:
        # 值没变就不重绘：状态看门狗每秒调用一次，靠这里保证它是「免费」的
        running = bool(running)
        if running == self._running:
            return
        self._running = running
        self._push(("state", None))

    def set_recording(self, recording: bool) -> None:
        recording = bool(recording)
        if recording == self._recording:
            return
        self._recording = recording
        self._push(("state", None))

    def set_paused(self, paused: bool) -> None:
        paused = bool(paused)
        if paused == self._paused:
            return
        self._paused = paused
        self._push(("state", None))

    def set_repeat(self, repeat: int) -> None:
        repeat = int(repeat)
        if repeat == self._repeat:
            return
        self._repeat = repeat
        self._push(("state", None))

    def state(self) -> dict:
        return {
            "enabled": self._enabled,
            "available": self._available,
            "visible": self._visible,
            "loop": self._loop,
            "total": self._total,
            "repeat": self._repeat or self._total,
            "running": self._running,
            "paused": self._paused,
            "recording": self._recording,
            "step": self._step,
            "error": self._error,
        }

    def call_in_tk(self, fn: Callable[[], object], timeout: float = 5.0):
        """在 Tk 线程里执行 fn 并返回它的返回值（任意线程可调）。

        Tk 只能在创建它的线程里访问，所以外部（含测试）不能直接摸控件。这里复用
        既有的指令队列把函数投递进去，用 Event 等待并取回结果——这样测试可以驱动
        **真实控件与真实绑定**，又完全不需要注入系统级鼠标/键盘事件。

        （为什么不合成真实点击来测：那会移动用户的光标、把按键打进当前前台窗口，
        既打扰用户，又只要用户此刻在用电脑就必然测不稳。）
        """
        done = threading.Event()
        box: dict = {}

        def _run() -> None:
            try:
                box["value"] = fn()
            except Exception as e:  # 带回调用线程再抛，便于测试看到真实原因
                box["error"] = e
            finally:
                done.set()

        if self._thread is None:
            return None
        self._q.put(("call", _run))
        if not done.wait(timeout):
            return None
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def hit_test(self, x: int, y: int) -> bool:
        """屏幕坐标点是否落在悬浮框上。

        录制时用它过滤掉「点在自己身上」的事件——否则用悬浮框按钮开始/停止录制
        会把这次点击也录进宏里，回放时又点到同一个按钮，形成递归录制。

        可能被鼠标钩子线程调用，因此只用 Win32 读窗口矩形，绝不触碰 Tk 对象。
        """
        hwnd = self._hwnd
        if not hwnd or not self._visible:
            return False
        try:
            user32 = ctypes.windll.user32
            rect = wintypes.RECT()
            if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                return False
            return rect.left <= x < rect.right and rect.top <= y < rect.bottom
        except Exception:
            return False

    def _push(self, item: tuple) -> None:
        if self._thread is not None and self._available:
            self._q.put(item)

    # --------------------------------------------------------- Tk 线程内部实现
    def _main(self) -> None:
        try:
            import tkinter as tk
        except Exception as e:  # tkinter 未编译进来 / 环境缺 Tcl-Tk
            self._available = False
            self._error = f"tkinter 不可用：{e}"
            return

        try:
            root = tk.Tk()
        except Exception as e:
            self._available = False
            self._error = f"创建悬浮窗失败：{e}"
            return

        self._root = root
        try:
            self._build(tk, root)
        except Exception as e:
            self._available = False
            self._error = f"初始化悬浮窗失败：{e}"
            try:
                root.destroy()
            except Exception:
                pass
            return

        root.withdraw()
        root.after(_POLL_MS, lambda: self._pump(root))
        try:
            root.mainloop()
        except Exception:
            pass

    def _build(self, tk, root) -> None:
        root.overrideredirect(True)          # 无边框，也不进任务栏
        root.attributes("-topmost", True)    # 始终置顶
        try:
            root.attributes("-alpha", 0.94)  # 半透明，部分平台不支持，失败无妨
        except Exception:
            pass

        frame = tk.Frame(root, bg=_BG, highlightthickness=1, highlightbackground=_BORDER)
        frame.pack(fill="both", expand=True)

        # ---- 标题行 ----
        head = tk.Frame(frame, bg=_BG)
        head.pack(fill="x", padx=10, pady=(7, 0))
        title = tk.Label(head, text="● AutoGameTool", bg=_BG, fg=_ACCENT,
                         font=(_FONT, 8, "bold"), anchor="w")
        title.pack(side="left")
        # 「回到界面」放右上角，用矢量图标而不是文字按钮（见 _mk_back_icon）。
        # pack 顺序决定位置：先 pack 的在最右，因此 ✕ 仍在最外侧。
        close = tk.Label(head, text="✕", bg=_BG, fg=_FG_SUB, font=(_FONT, 9), cursor="hand2")
        close.pack(side="right")
        back = self._mk_back_icon(tk, head)
        back.pack(side="right", padx=(0, 6))
        close.bind("<Button-1>", self._on_close_click)

        # ---- 进度 ----
        self._progress = tk.Label(frame, text="等待运行", bg=_BG, fg=_FG_MAIN,
                                  font=(_FONT, 13, "bold"), anchor="w")
        self._progress.pack(fill="x", padx=10, pady=(2, 0))
        self._step_lbl = tk.Label(frame, text="—", bg=_BG, fg=_FG_SUB,
                                  font=(_FONT, 9), anchor="w",
                                  justify="left", wraplength=_WIDTH - 24)
        self._step_lbl.pack(fill="x", padx=10, pady=(0, 6))

        # ---- 操作行 ----
        tools = tk.Frame(frame, bg=_BG)
        tools.pack(fill="x", padx=8, pady=(0, 8))

        self._btn_run = self._mkbtn(tk, tools, "▶ 启动", lambda: self._act("toggle_run"), _IDLE_BG)
        self._btn_run.pack(side="left")
        self._btn_pause = self._mkbtn(tk, tools, "⏸ 暂停", lambda: self._act("toggle_pause"))
        self._btn_pause.pack(side="left", padx=(4, 0))
        self._btn_rec = self._mkbtn(tk, tools, "● 录制", lambda: self._act("toggle_record"))
        self._btn_rec.pack(side="left", padx=(4, 0))

        self._btn_plus = self._mkbtn(tk, tools, "＋", lambda: self._act("repeat_up"))
        self._btn_plus.pack(side="right", padx=(3, 0))
        # 循环次数做成可直接输入的 Entry（不只是 ± ）。
        # 注意：悬浮框平时带 WS_EX_NOACTIVATE，点击不抢焦点——那样 Entry 收不到键盘。
        # 所以只在用户点击这个数字时**临时**去掉该扩展样式并在提交/失焦后立刻恢复，
        # 见 _begin_repeat_edit / _end_repeat_edit。
        self._entry_repeat = tk.Entry(
            tools, width=4, justify="center", bg=_BTN_BG, fg=_FG_MAIN,
            insertbackground=_FG_MAIN, disabledbackground=_BTN_BG,
            disabledforeground=_BTN_DISABLED, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_ACCENT,
            font=(_FONT, 9, "bold"), takefocus=0,
        )
        self._entry_repeat.insert(0, "1")
        self._entry_repeat.pack(side="right")
        self._entry_repeat.bind("<Button-1>", self._begin_repeat_edit)
        self._entry_repeat.bind("<Return>", lambda _e: self._commit_repeat())
        self._entry_repeat.bind("<KP_Enter>", lambda _e: self._commit_repeat())
        self._entry_repeat.bind("<Escape>", lambda _e: self._cancel_repeat_edit())
        # 失焦不等于"用户走开了"：OS 激活会把 Tk 焦点重置回它记住的控件，
        # 于是刚点开编辑就会收到一次 FocusOut。这里延时判定，见 _on_repeat_focus_out。
        self._entry_repeat.bind("<FocusOut>", self._on_repeat_focus_out)
        self._btn_minus = self._mkbtn(tk, tools, "－", lambda: self._act("repeat_down"))
        self._btn_minus.pack(side="right", padx=(0, 3))
        tk.Label(tools, text="循环", bg=_BG, fg=_FG_SUB, font=(_FONT, 8)).pack(side="right", padx=(8, 2))

        # ---- 拖拽（整块可拖；按钮点击不受影响）----
        for w in (frame, head, title, self._progress, self._step_lbl):
            w.bind("<Button-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)

        # 置顶改为「按需」：只有鼠标移上来（说明用户要操作它）时才确认一次置顶。
        # 旧版每 3 秒无条件 SetWindowPos(HWND_TOPMOST)，这是应用内唯一一处周期性
        # 窗口写操作，会在别的窗口播放最小化动画时搅动 Z 序，造成最小化偶发失败。
        for w in (frame, tools):
            w.bind("<Enter>", lambda _e: self._ensure_topmost())

        root.update_idletasks()
        self._hwnd = self._resolve_hwnd(root)
        self._apply_window_flags()
        # 文字折行宽度由「工具行实际所需宽度」反推。
        # 注意：Tk 会把顶层窗口尺寸交还给内容请求（显式 geometry 宽度会被覆盖），
        # 所以这里不去强行定宽，而是保证文字永远不会比按钮行更宽而被横向裁掉。
        try:
            tools_w = tools.winfo_reqwidth()
        except Exception:
            tools_w = _WIDTH
        try:
            self._step_lbl.config(wraplength=max(180, tools_w - 20))
        except Exception:
            pass
        root.update_idletasks()
        w = root.winfo_reqwidth()
        x = max(0, root.winfo_screenwidth() - w - _MARGIN)
        # 只定位置，尺寸交给内容
        self._geom = f"+{x}+{_MARGIN}"
        root.geometry(self._geom)
        root.update_idletasks()
        self._render()

    def _mkbtn(self, tk, parent, text, cmd, bg=_BTN_BG):
        return tk.Button(
            parent, text=text, command=cmd, bg=bg, fg=_BTN_FG,
            activebackground=_BTN_ACTIVE, activeforeground=_FG_MAIN,
            disabledforeground=_BTN_DISABLED,
            relief="flat", bd=0, highlightthickness=0,
            padx=7, pady=2, font=(_FONT, 8), cursor="hand2", takefocus=0,
        )

    def _mk_back_icon(self, tk, parent):
        """「回到界面」图标：右上角，点它把 WebUI 浏览器窗口切回前台。

        用 Canvas 矢量绘制而不是图片：打包体积不变、任意 DPI 下都清晰，
        也免去给 exe 再塞一个图标资源的麻烦。
        造型是编辑器里常见的「弹回主界面」标志——一个左上角开口的方框、
        一支从缺口指向左上角的箭头，右下角一块实心方块。

        尺寸/间距是调过的：18px 时三部分会糊成一团，20px + 1.4px 线宽
        才能在 100% 缩放下看清是「箭头 + 方框 + 方块」。
        """
        cv = tk.Canvas(parent, width=20, height=20, bg=_BG,
                       highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        line = {"fill": _FG_MAIN, "width": 1.4, "capstyle": "round", "joinstyle": "round"}
        items = [
            # 左上角开口的方框（缺口留给箭头穿出）
            cv.create_line(11.5, 3.5, 17.5, 3.5, 17.5, 14, 7.5, 14, 7.5, 8, **line),
            # 箭头：杆 + 箭头尖
            cv.create_line(8, 8.5, 2.5, 3, **line),
            cv.create_line(2.5, 7, 2.5, 3, 6.5, 3, **line),
            # 右下角的实心方块（与方框留出约 1.5px 间隙，不糊在一起）
            cv.create_rectangle(11, 8.5, 16, 12.5, fill=_FG_MAIN, outline=""),
        ]

        def paint(color: str) -> None:
            for item in items:
                try:
                    cv.itemconfig(item, fill=color)
                except Exception:
                    pass

        # 悬停变主题色：没有文字标签，靠颜色变化给出「这里可以点」的反馈
        cv.bind("<Button-1>", lambda _e: self._act("focus_ui"))
        cv.bind("<Enter>", lambda _e: (paint(_ACCENT), self._ensure_topmost()))
        cv.bind("<Leave>", lambda _e: paint(_FG_MAIN))
        return cv

    def _resolve_hwnd(self, root) -> int:
        for getter in (lambda: root.frame(), lambda: root.winfo_id()):
            try:
                v = getter()
                if isinstance(v, str):
                    return int(v, 16) if v.lower().startswith("0x") else int(v)
                if isinstance(v, int) and v:
                    return v
            except Exception:
                continue
        return 0

    def _apply_window_flags(self) -> None:
        """加 WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW。

        NOACTIVATE 让点击悬浮框不再夺走前台焦点（也就不会打断别的窗口的最小化/切换），
        TOOLWINDOW 让它不出现在 Alt-Tab 列表里。
        """
        if not self._hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            hwnd = wintypes.HWND(self._hwnd)
            cur = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, cur | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER
                                | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)
        except Exception:
            pass

    def _ensure_topmost(self) -> None:
        """仅在确实丢失 topmost 时才写 Z 序。

        旧版每 2 秒无条件 SetWindowPos(HWND_TOPMOST)，会在别的窗口播放最小化动画时
        搅动 Z 序，导致最小化偶发失败；这里改成先读扩展样式，正常情况是纯读操作。
        """
        if not self._hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.restype = ctypes.c_long
            hwnd = wintypes.HWND(self._hwnd)
            if user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST:
                return
            user32.SetWindowPos(hwnd, wintypes.HWND(_HWND_TOPMOST), 0, 0, 0, 0,
                                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
        except Exception:
            pass

    # ------------------------------------------------------------- 循环次数编辑
    def _activate(self) -> None:
        """把悬浮框激活到前台并让它拿到键盘焦点。

        两个坑，缺一不可（本机实测）：
        1. 只清 WS_EX_NOACTIVATE 不会让窗口变成活动窗口——非活动窗口收不到键盘，
           而 Tk 仍以为 Entry 有焦点（`focus_get()` 返回 Entry），于是按键全打给了别人；
        2. `overrideredirect(True)` 的窗口光靠 `SetForegroundWindow` 还不够，
           必须再 `SetFocus` 把**线程的焦点窗口**也切过来，否则前台是它、键盘仍不来。
        实测：只做第 1 步，注入 "7" 得到空串；补上 SetForegroundWindow + SetFocus 后得到 "7"。

        （另一条可行路线是临时关掉 overrideredirect，但那样会换 HWND 并闪出标题栏，不用。）
        """
        try:
            u = ctypes.windll.user32
            hwnd = wintypes.HWND(self._hwnd)
            if not u.SetForegroundWindow(hwnd):
                # 后台进程默认没有前台切换权限；附加到当前前台线程再试一次
                # （与 window.focus_window 同一套兜底手法，这里不引入对 window.py 的依赖）
                k = ctypes.windll.kernel32
                fg = u.GetForegroundWindow()
                tid_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
                tid_self = k.GetCurrentThreadId()
                if tid_fg and tid_fg != tid_self:
                    u.AttachThreadInput(tid_self, tid_fg, True)
                    try:
                        u.SetForegroundWindow(hwnd)
                    finally:
                        u.AttachThreadInput(tid_self, tid_fg, False)
            # 关键的一步：SetFocus 只能对调用线程自己的窗口使用，而这里正是 Tk 线程
            u.SetFocus(hwnd)
        except Exception:
            pass

    def _begin_repeat_edit(self, _e=None):
        """点击循环次数：临时激活窗口，让 Entry 收得到键盘输入。

        悬浮框平时带 WS_EX_NOACTIVATE（点击不抢焦点，避免打断游戏里的操作），
        代价是它永远拿不到键盘焦点、Entry 打不了字。这里只在**用户主动点这个数字**时
        临时清掉该扩展样式并激活窗口，提交/失焦后立刻恢复——焦点切换是用户点出来的，
        不是后台偷偷发生的。
        """
        if self._running or self._editing_repeat:
            return "break"
        # 激活过程中会有焦点变化（可能触发 FocusOut）；这段时间内的提交请求一律忽略，
        # 否则「第二次编辑」会在用户还没输入时就把上一次的残留文本提交掉。
        self._activating = True
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            hwnd = wintypes.HWND(self._hwnd)
            cur = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, cur & ~_WS_EX_NOACTIVATE)
            self._activate()
            # 只给 Entry 设焦点：不要再 focus_force() 顶层——那会把焦点从 Entry 上挪走，
            # 反过来触发 FocusOut 并当场结束编辑（实测：第二次点击必中此坑）。
            self._entry_repeat.focus_set()
            self._editing_repeat = True
            self._entry_repeat.select_range(0, "end")
        except Exception:
            pass
        finally:
            self._activating = False
        return "break"  # 阻止继续传递给拖拽处理

    def _on_repeat_focus_out(self, _e=None) -> None:
        """失焦：延时判断是"用户点到别处"还是"被 OS 激活挤掉了焦点"。

        直接提交会在第二次编辑时立刻把上一次的残留文本提交掉（实测如此）：
        点开输入框 → `_activate()` 让窗口成为前台 → OS 发来 WM_SETFOCUS →
        Tk 把焦点重置回它记住的控件 → Entry 收到 FocusOut。这不是用户意图。
        """
        if self._activating or not self._editing_repeat:
            return
        try:
            self._root.after(120, self._recheck_repeat_focus)
        except Exception:
            pass

    def _recheck_repeat_focus(self) -> None:
        if not self._editing_repeat:
            return
        try:
            if self._root.focus_get() is self._entry_repeat:
                return
            # 判据：窗口已经不是前台 → 用户真的点到别处去了，按提交处理
            if ctypes.windll.user32.GetForegroundWindow() != self._hwnd:
                self._commit_repeat()
                return
            # 否则只是被激活过程挤掉，把焦点抢回来继续编辑
            self._entry_repeat.focus_set()
        except Exception:
            pass

    def _end_repeat_edit(self) -> None:
        """结束编辑：恢复 NOACTIVATE 扩展样式（悬浮框回到"不抢焦点"状态）。"""
        if not self._editing_repeat:
            return
        self._editing_repeat = False
        try:
            self._apply_window_flags()
        except Exception:
            pass

    def _commit_repeat(self) -> None:
        """提交输入值：非法/越界一律夹到合法范围，并把显示改回真实值。"""
        if self._activating or not self._editing_repeat:
            return
        raw = ""
        try:
            raw = self._entry_repeat.get().strip()
        except Exception:
            pass
        value = self._repeat or 1
        try:
            value = int(raw)
        except (TypeError, ValueError):
            pass  # 非数字：回退到当前值，不报错也不清空
        value = max(_REPEAT_MIN, min(_REPEAT_MAX, value))
        self._set_repeat_text(value)
        self._end_repeat_edit()
        if value != self._repeat:
            self._act(f"repeat_set:{value}")

    def _cancel_repeat_edit(self) -> None:
        """Esc：放弃本次输入，恢复成当前值。"""
        if self._activating:
            return
        self._set_repeat_text(self._repeat or 1)
        self._end_repeat_edit()

    def _set_repeat_text(self, value: int) -> None:
        """写入显示值。禁用态下 Tk 不允许改文本，所以临时切回 normal 再恢复。"""
        try:
            state = str(self._entry_repeat.cget("state"))
            if state != "normal":
                self._entry_repeat.config(state="normal")
            self._entry_repeat.delete(0, "end")
            self._entry_repeat.insert(0, str(int(value)))
            if state != "normal":
                self._entry_repeat.config(state=state)
        except Exception:
            pass

    # ------------------------------------------------------------- 事件回调
    def _act(self, name: str) -> None:
        """按钮点击：只把动作名转交引擎（由引擎切回事件循环线程执行）。"""
        if self._on_action:
            try:
                self._on_action(name)
            except Exception:
                pass

    def _on_press(self, e) -> None:
        self._drag_from = (e.x_root, e.y_root)
        try:
            self._win_at = (self._root.winfo_x(), self._root.winfo_y())
        except Exception:
            self._win_at = (0, 0)

    def _on_drag(self, e) -> None:
        if self._root is None:
            return
        dx = e.x_root - self._drag_from[0]
        dy = e.y_root - self._drag_from[1]
        try:
            self._root.geometry(f"+{self._win_at[0] + dx}+{self._win_at[1] + dy}")
        except Exception:
            pass

    def _on_close_click(self, _e=None) -> None:
        """点 ✕ 收起悬浮框，并回调通知引擎（用于同步前端开关并持久化）。"""
        self._enabled = False
        self._apply_enabled(self._root, False)
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass

    # ------------------------------------------------------------- 队列消费
    def _pump(self, root) -> None:
        dirty = False
        try:
            while True:
                kind, _payload = self._q.get_nowait()
                if kind == "quit":
                    self._stopping = True
                    try:
                        root.quit()
                        root.destroy()
                    except Exception:
                        pass
                    return
                if kind == "enabled":
                    self._apply_enabled(root, bool(_payload))
                elif kind == "call":
                    if callable(_payload):
                        _payload()
                elif kind in ("text", "state"):
                    dirty = True
        except queue.Empty:
            pass
        except Exception:
            pass

        if dirty:
            self._render()

        if not self._stopping:
            root.after(_POLL_MS, lambda: self._pump(root))

    def _render(self) -> None:
        if self._progress is None:
            return
        total = self._total or self._repeat
        if self._paused:
            # 暂停要一眼可见：否则用户看到"第 2/3 轮"不动，会以为程序卡死了
            text = f"⏸ 已暂停 · 第 {self._loop}/{total} 轮" if total else "⏸ 已暂停"
        elif self._running and total:
            text = f"第 {self._loop}/{total} 轮"
        elif total:
            text = f"共 {total} 轮 · 待运行"
        else:
            text = "等待运行"
        brief = (self._step or "").strip() or "—"
        if len(brief) > 44:
            brief = brief[:44] + "…"
        try:
            self._progress.config(text=text)
            self._step_lbl.config(text=brief)
            self._btn_run.config(
                text="■ 停止" if self._running else "▶ 启动",
                bg=_RUN_BG if self._running else _IDLE_BG,
            )
            self._btn_pause.config(
                text="▶ 继续" if self._paused else "⏸ 暂停",
                bg=_PAUSE_BG if self._paused else _BTN_BG,
                state="normal" if self._running else "disabled",
            )
            self._btn_rec.config(
                text="■ 停录" if self._recording else "● 录制",
                bg=_REC_BG if self._recording else _BTN_BG,
            )
            # 循环次数：正在输入时不覆盖用户正在敲的内容，否则每次状态刷新都会把它擦掉
            if not self._editing_repeat:
                value = self._repeat or self._total or 1
                if self._entry_repeat.get().strip() != str(value):
                    self._set_repeat_text(value)
            btn_state = "disabled" if self._running else "normal"
            self._btn_minus.config(state=btn_state)
            self._btn_plus.config(state=btn_state)
            self._entry_repeat.config(state=btn_state)
        except Exception:
            pass

    def _apply_enabled(self, root, enabled: bool) -> None:
        if root is None or enabled == self._visible:
            return
        try:
            if enabled:
                root.deiconify()
                # withdraw/deiconify 之后 Tk 会退回「按内容请求尺寸」，
                # 显式宽度会丢失（会让 wraplength 大于窗口宽度而横向裁字），这里补回来
                if self._geom:
                    root.geometry(self._geom)
                root.attributes("-topmost", True)
                self._ensure_topmost()
            else:
                root.withdraw()
            self._visible = enabled
        except Exception:
            pass


# ---------------------------------------------------------------- 模块级单例 API
# 执行器 / 引擎只关心「刷进度、同步按钮状态、转交按钮动作」，
# 因此这里提供与 keybus 同风格的模块级函数，内部代理到唯一实例。
_instance: Overlay | None = None


def instance() -> Overlay:
    global _instance
    if _instance is None:
        _instance = Overlay()
    return _instance


def configure(
    on_close: Callable[[], None] | None = None,
    on_action: Callable[[str], None] | None = None,
) -> None:
    inst = instance()
    if on_close is not None:
        inst._on_close = on_close
    if on_action is not None:
        inst._on_action = on_action


def start(enabled: bool = False) -> None:
    instance().start(enabled)


def stop() -> None:
    instance().stop()


def set_enabled(enabled: bool) -> None:
    instance().set_enabled(enabled)


def update(loop: int, total: int, step: str) -> None:
    instance().update(loop, total, step)


def set_run_state(running: bool) -> None:
    instance().set_run_state(running)


def set_recording(recording: bool) -> None:
    instance().set_recording(recording)


def set_paused(paused: bool) -> None:
    instance().set_paused(paused)


def set_repeat(repeat: int) -> None:
    instance().set_repeat(repeat)


def hit_test(x: int, y: int) -> bool:
    return instance().hit_test(x, y)


def state() -> dict:
    return instance().state()
