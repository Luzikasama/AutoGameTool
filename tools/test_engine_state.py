"""引擎状态逻辑回归测试（无需 GUI、无需起服务、不装键盘钩子）

覆盖两处「出过问题、又很容易再写错」的状态逻辑：

1. HotkeyManager 的「已触发」锁
   - 按住 alt 连按两次 f1 → 必须触发两次（旧实现只触发第一次，手感就是"快捷键时灵时不灵"）
   - 长按 f1（系统重复 keydown、没有 keyup）→ 必须只触发一次
2. Overlay 状态去重
   - 状态看门狗每秒调用一次 set_run_state，值没变时不能产生多余推送，
     否则悬浮框每秒重绘一次

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_engine_state.py
"""
import sys
from pathlib import Path

# Windows 下 stdout 默认按系统代码页（如 cp936）编码，重定向时中文会变乱码；
# 统一按 UTF-8 输出，断言结果和标题都能正常阅读。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(_ENGINE))

from pynput import keyboard  # noqa: E402

import overlay as overlay_mod  # noqa: E402
from hotkey import HotkeyManager  # noqa: E402
from overlay import Overlay  # noqa: E402

_pass = 0
_fail = 0


def check(name: str, cond: bool, extra: object = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print("  PASS  " + name)
    else:
        _fail += 1
        print("  FAIL  " + name + (("  -> " + str(extra)) if extra != "" else ""))


def make_hotkey(keys=("alt", "f1")) -> HotkeyManager:
    """绕过 __init__ 构造实例：__init__ 会 register() 真的去装 Windows 键盘钩子，
    测试里不需要（也绝不该）碰系统钩子。"""
    h = object.__new__(HotkeyManager)
    h.keys = list(keys)
    h.pressed = set()
    h._fired = False
    h.calls = 0
    h.callback = lambda: setattr(h, "calls", h.calls + 1)
    return h


ALT = keyboard.Key.alt_l
F1 = keyboard.Key.f1

print("== 快捷键 1：alt 按住不放，连按两次 f1 ==")
h = make_hotkey()
h._on_press(ALT)
h._on_press(F1)
h._on_release(F1)          # 此时 alt 仍按着
h._on_press(F1)            # 第二次按 f1
check("触发两次", h.calls == 2, h.calls)
h._on_release(F1)
h._on_release(ALT)
check("全部松开后锁复位", h._fired is False)

print("== 快捷键 2：长按 f1（系统重复 keydown）只触发一次 ==")
h = make_hotkey()
h._on_press(ALT)
h._on_press(F1)
for _ in range(5):
    h._on_press(F1)        # 自动重复：只有 keydown，没有 keyup
check("只触发一次", h.calls == 1, h.calls)
h._on_release(F1)
h._on_release(ALT)

print("== 快捷键 3：完整按下/松开三次 ==")
h = make_hotkey()
for _ in range(3):
    h._on_press(ALT)
    h._on_press(F1)
    h._on_release(F1)
    h._on_release(ALT)
check("三次都触发", h.calls == 3, h.calls)

print("== 快捷键 4：只按主键、没按修饰键 → 不触发 ==")
h = make_hotkey()
h._on_press(F1)
h._on_release(F1)
check("单独 f1 不触发", h.calls == 0, h.calls)

print("== 快捷键 5：先松修饰键、再松主键也应复位 ==")
h = make_hotkey()
h._on_press(ALT)
h._on_press(F1)
h._on_release(ALT)
h._on_release(F1)
check("锁已复位", h._fired is False)
h._on_press(ALT)
h._on_press(F1)
check("可再次触发", h.calls == 2, h.calls)

print("== 悬浮框状态去重 ==")
ov = Overlay()            # 只创建队列与字段，不碰 Tk
ov._thread = object()     # 让 _push 认为悬浮框线程已就绪
ov.set_run_state(True)
ov.set_run_state(True)
check("重复 running=True 只推一次", ov._q.qsize() == 1, ov._q.qsize())
ov.set_run_state(False)
check("状态翻转会推一次", ov._q.qsize() == 2, ov._q.qsize())
ov.set_recording(True)
ov.set_recording(True)
check("重复 recording 只推一次", ov._q.qsize() == 3, ov._q.qsize())
ov.set_repeat(3)
ov.set_repeat(3)
check("重复 repeat 只推一次", ov._q.qsize() == 4, ov._q.qsize())
st = ov.state()
check("state() 反映最新值", st["running"] is False and st["repeat"] == 3 and st["recording"] is True, st)

print("== 模块级 API 完整性 ==")
# 历史教训：overlay 模块缺过 update()，导致每次流程都在起跑处异常退出
for fn in (
    "instance", "configure", "start", "stop", "set_enabled", "update",
    "set_run_state", "set_paused", "set_recording", "set_repeat", "hit_test", "state",
):
    check(f"overlay.{fn} 可调用", callable(getattr(overlay_mod, fn, None)))

print("== Executor 的暂停状态机（纯逻辑）==")
from executor import Executor  # noqa: E402


class _FakeTask:
    def __init__(self, done=False):
        self._done = done

    def done(self):
        return self._done


async def _noop_broadcast(_msg):
    return None


ex = Executor(lambda m: None)

# 空闲时暂停：应该无效（没有流程可暂停，不能显示成"已暂停"）
ex.pause()
check("空闲时 pause() 不生效", ex.paused is False, ex.paused)

# 运行中暂停：生效
ex.running = True
ex.task = _FakeTask(done=False)
ex.pause()
check("运行中 pause() 生效", ex.paused is True, ex.paused)
ex.resume()
check("resume() 清除暂停", ex.paused is False)

# 暂停中停止：停止必须能挣脱暂停，否则会一直挂在暂停等待循环里
ex.pause()
ex.stop()
check("stop() 会清掉暂停", ex.paused is False and ex.stopped is True)

# 任务已结束时 reconcile：running 复位，暂停也一并清掉（避免"空闲但显示已暂停"）
ex.running = True
ex.paused = True
ex.stopped = False
ex.task = _FakeTask(done=True)
ex.reconcile()
check("任务结束后 reconcile 复位 running", ex.running is False, ex.running)
check("任务结束后 reconcile 清掉暂停", ex.paused is False, ex.paused)

# 在跑的流程 reconcile 不能打扰它
ex.running = True
ex.paused = True
ex.task = _FakeTask(done=False)
ex.reconcile()
check("运行中 reconcile 保留 running/paused", ex.running is True and ex.paused is True)

print("== WebUI 窗口定位：只认真正的浏览器 ==")
# 回归（v0.7.1 及更早的真实 bug）：旧实现把「像不像浏览器」只当**排序键**，
# 一个浏览器都没匹配上时会退而返回任意同名窗口——承载后端的终端窗口标题里
# 就含 AutoGameTool，于是点悬浮框「界面」会把后端控制台弹到前台。
# 这里造一个**可见的、标题唯一的**非浏览器窗口，断言它必须被拒绝。
import ctypes as _ctypes  # noqa: E402
from ctypes import wintypes as _wt  # noqa: E402

import window as window_mod  # noqa: E402

UNIQUE = "AutoGameTool-Selftest-7f3a1c"


def _visible_titled(hint: str) -> int:
    """数一数可见且标题含 hint 的顶层窗口（用来证明测试窗口确实存在）。"""
    user32 = _ctypes.windll.user32
    hits = []

    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = _ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if hint.lower() in buf.value.lower():
            hits.append(hwnd)
        return True

    user32.EnumWindows(_ctypes.WINFUNCTYPE(_wt.BOOL, _wt.HWND, _wt.LPARAM)(cb), 0)
    return len(hits)


_tk_root = None
try:
    import tkinter as _tk

    _tk_root = _tk.Tk()
    _tk_root.title(UNIQUE)
    _tk_root.geometry("260x80+40+40")
    _tk_root.update()
    _tk_root.update_idletasks()
except Exception as e:  # 无 GUI 环境就跳过这一段
    print("  SKIP  无法创建测试窗口：%s" % e)

if _tk_root is not None:
    check("测试窗口确实可见且标题含唯一串", _visible_titled(UNIQUE) >= 1, _visible_titled(UNIQUE))
    got = window_mod.find_webui_window(UNIQUE)
    check("非浏览器的同名窗口不会被当成 WebUI（旧版会返回它）", got is None, got)
    check("空标题直接返回 None", window_mod.find_webui_window("") is None)
    try:
        _tk_root.destroy()
    except Exception:
        pass

# 明确的排除名单：控制台 / 终端 / 解释器都不该被当成浏览器
for exe in ("conhost.exe", "windowsterminal.exe", "pwsh.exe", "powershell.exe",
            "cmd.exe", "python.exe", "autogametool.exe"):
    check("排除名单含 " + exe, exe in window_mod._NON_BROWSER_EXES)
for cls in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
    check("排除类名含 " + cls, cls in window_mod._NON_BROWSER_CLASSES)

print("== 悬浮框循环轮数直接编辑（引擎侧夹取与同步）==")
import main as engine_main  # noqa: E402

engine_main.executor.current_flow = {"name": "t", "repeat": 1}
check("合法值生效", engine_main._set_repeat_to(42) == 42)
check("同步到引擎侧流程阴影值", engine_main.executor.current_flow.get("repeat") == 42)
check("同步到悬浮框状态", overlay_mod.state().get("repeat") == 42)
check("下界夹取：0 -> 1", engine_main._set_repeat_to(0) == 1)
check("上界夹取：99999 -> 9999", engine_main._set_repeat_to(99999) == 9999)
before = engine_main._set_repeat_to(7)
check("非法输入保持原值", engine_main._set_repeat_to("abc") == before, before)
check("± 与直接输入共用同一套逻辑", engine_main._change_repeat(1) == 8)

print("")
print("结果: PASS=" + str(_pass) + "  FAIL=" + str(_fail))
sys.exit(0 if _fail == 0 else 1)
