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
    "set_run_state", "set_recording", "set_repeat", "hit_test", "state",
):
    check(f"overlay.{fn} 可调用", callable(getattr(overlay_mod, fn, None)))

print("")
print("结果: PASS=" + str(_pass) + "  FAIL=" + str(_fail))
sys.exit(0 if _fail == 0 else 1)
