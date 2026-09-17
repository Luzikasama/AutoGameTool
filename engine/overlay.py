"""悬浮框：置顶小窗显示运行进度，并提供启停 / 录制 / 循环次数 / 回到界面 四个快捷操作。

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
_TOPMOST_MS = 3000    # 检查 topmost 的间隔（仅在丢失时才写 Z 序）
_MARGIN = 24
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
        self._recording = False
        self._step = "等待运行"

        # 仅 Tk 线程使用
        self._root = None
        self._hwnd = 0
        self._geom = ""
        self._btn_run = None
        self._btn_rec = None
        self._btn_minus = None
        self._btn_plus = None
        self._lbl_repeat = None
        self._progress = None
        self._step_lbl = None
        self._drag_from = (0, 0)
        self._win_at = (0, 0)
        self._ticks = 0
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
        self._running = bool(running)
        self._push(("state", None))

    def set_recording(self, recording: bool) -> None:
        self._recording = bool(recording)
        self._push(("state", None))

    def set_repeat(self, repeat: int) -> None:
        self._repeat = int(repeat)
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
            "recording": self._recording,
            "step": self._step,
            "error": self._error,
        }

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
        close = tk.Label(head, text="✕", bg=_BG, fg=_FG_SUB, font=(_FONT, 9), cursor="hand2")
        close.pack(side="right")
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
        self._btn_rec = self._mkbtn(tk, tools, "● 录制", lambda: self._act("toggle_record"))
        self._btn_rec.pack(side="left", padx=(4, 0))

        ui_btn = self._mkbtn(tk, tools, "界面", lambda: self._act("focus_ui"))
        ui_btn.pack(side="right")
        self._btn_plus = self._mkbtn(tk, tools, "＋", lambda: self._act("repeat_up"))
        self._btn_plus.pack(side="right", padx=(3, 0))
        self._lbl_repeat = tk.Label(tools, text="1", bg=_BG, fg=_FG_MAIN,
                                    font=(_FONT, 9, "bold"), width=3, anchor="center")
        self._lbl_repeat.pack(side="right")
        self._btn_minus = self._mkbtn(tk, tools, "－", lambda: self._act("repeat_down"))
        self._btn_minus.pack(side="right", padx=(0, 3))
        tk.Label(tools, text="循环", bg=_BG, fg=_FG_SUB, font=(_FONT, 8)).pack(side="right", padx=(8, 2))

        # ---- 拖拽（整块可拖；按钮点击不受影响）----
        for w in (frame, head, title, self._progress, self._step_lbl):
            w.bind("<Button-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)

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
                elif kind in ("text", "state"):
                    dirty = True
        except queue.Empty:
            pass
        except Exception:
            pass

        if dirty:
            self._render()

        self._ticks += 1
        if self._visible and self._ticks * _POLL_MS >= _TOPMOST_MS:
            self._ticks = 0
            self._ensure_topmost()
        if not self._stopping:
            root.after(_POLL_MS, lambda: self._pump(root))

    def _render(self) -> None:
        if self._progress is None:
            return
        total = self._total or self._repeat
        if self._running and total:
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
            self._btn_rec.config(
                text="■ 停录" if self._recording else "● 录制",
                bg=_REC_BG if self._recording else _BTN_BG,
            )
            self._lbl_repeat.config(text=str(self._repeat or self._total or 1))
            btn_state = "disabled" if self._running else "normal"
            self._btn_minus.config(state=btn_state)
            self._btn_plus.config(state=btn_state)
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


def set_repeat(repeat: int) -> None:
    instance().set_repeat(repeat)


def hit_test(x: int, y: int) -> bool:
    return instance().hit_test(x, y)


def state() -> dict:
    return instance().state()
