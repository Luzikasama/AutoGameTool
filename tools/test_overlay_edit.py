"""悬浮框「循环次数直接编辑」回归测试（**不碰真实鼠标键盘**）

为什么这样做：早期版本用真实点击 + 真实按键去验证这个功能（`/input/click` +
`/input/key`），那会移动用户的光标、把按键打进当前前台窗口——既打扰人，又只要
用户此刻在用电脑就必然测不稳。这里改为在 Tk 内部合成事件
（`widget.event_generate`）：走的是**同一套绑定与回调**，但不产生任何系统级输入。

覆盖：
  1. 点击数字 → 临时解除 WS_EX_NOACTIVATE（否则非活动窗口拿不到键盘焦点）
  2. 提交 → 发出 `repeat_set:<n>` 动作，并恢复 NOACTIVATE（"不抢焦点"是不变量）
  3. 越界/非法输入被夹到 1..9999，非法值保持原值
  4. Esc 放弃编辑并恢复显示
  5. 运行中禁用输入（与 ± 一致），且此时点击不会进入编辑态

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_overlay_edit.py
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import overlay as overlay_mod  # noqa: E402

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

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


def ex_style(hwnd: int) -> int:
    u = ctypes.windll.user32
    u.GetWindowLongW.restype = ctypes.c_long
    return u.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)


def main() -> int:
    actions: list[str] = []

    def on_action(name: str) -> None:
        """模拟引擎侧：收到动作后把真实轮数回写给悬浮框（引擎的 _set_repeat_to 就是这么做）。"""
        actions.append(name)
        if name.startswith("repeat_set:"):
            try:
                ov.set_repeat(int(name.split(":", 1)[1]))
            except ValueError:
                pass

    ov = overlay_mod.instance()
    ov._on_action = on_action

    ov.start(enabled=True)
    # 等窗口真正建好（Tk 线程构建完成）
    deadline = time.time() + 15
    hwnd = 0
    while time.time() < deadline:
        if ov.state().get("visible") and ov._hwnd:
            hwnd = ov._hwnd
            break
        time.sleep(0.2)
    if not hwnd:
        print("悬浮框未就绪，无法测试")
        return 1
    print("悬浮框 hwnd = %s  visible=%s" % (hwnd, ov.state().get("visible")))

    def in_tk(fn):
        return ov.call_in_tk(fn)

    def click_number():
        return in_tk(lambda: ov._entry_repeat.event_generate("<ButtonPress-1>", x=5, y=5))

    def type_and_enter(text: str):
        def _do():
            ov._entry_repeat.delete(0, "end")
            ov._entry_repeat.insert(0, text)
            ov._entry_repeat.event_generate("<Return>")
        return in_tk(_do)

    def mark() -> int:
        """记录基线：只比较这一步新产生的动作，避免跨步骤污染。"""
        return len(actions)

    def since(n: int) -> list:
        return actions[n:]

    print("== 1. 初始状态 ==")
    check("初始带 WS_EX_NOACTIVATE（点击不抢焦点）",
          bool(ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))

    print("== 2. 点击数字进入编辑态 ==")
    click_number()
    time.sleep(0.2)
    check("编辑期间 NOACTIVATE 被临时解除",
          not (ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))

    print("== 3. 输入 37 并回车 ==")
    n = mark()
    type_and_enter("37")
    time.sleep(0.3)
    got = since(n)
    check("发出 repeat_set:37", got == ["repeat_set:37"], got)
    check("提交后 NOACTIVATE 已恢复",
          bool(ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))
    txt = in_tk(lambda: ov._entry_repeat.get())
    check("显示值回写为 37", txt == "37", txt)

    print("== 4. 越界与非法输入 ==")
    n = mark()
    click_number()
    time.sleep(0.15)
    type_and_enter("99999")
    time.sleep(0.25)
    got = since(n)
    check("99999 夹到 9999", got == ["repeat_set:9999"], got)

    n = mark()
    click_number()
    time.sleep(0.15)
    type_and_enter("0")
    time.sleep(0.25)
    got = since(n)
    check("0 夹到 1", got == ["repeat_set:1"], got)

    n = mark()
    click_number()
    time.sleep(0.15)
    type_and_enter("abc")
    time.sleep(0.25)
    got = since(n)
    check("非数字不产生动作（保持原值）", got == [], got)
    check("非数字后 NOACTIVATE 仍恢复",
          bool(ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))

    print("== 5. Esc 放弃编辑 ==")
    ov.set_repeat(5)
    time.sleep(0.25)
    n = mark()
    click_number()
    time.sleep(0.15)
    in_tk(lambda: (ov._entry_repeat.delete(0, "end"), ov._entry_repeat.insert(0, "88")))
    in_tk(lambda: ov._entry_repeat.event_generate("<Escape>"))
    time.sleep(0.25)
    got = since(n)
    check("Esc 不产生动作", got == [], got)
    txt = in_tk(lambda: ov._entry_repeat.get())
    check("Esc 恢复为当前值 5", txt == "5", txt)

    print("== 6. 运行中禁用 ==")
    ov.set_run_state(True)
    time.sleep(0.3)
    state = in_tk(lambda: str(ov._entry_repeat.cget("state"))) or ""
    check("运行中输入框为 disabled", state == "disabled", state)
    click_number()
    time.sleep(0.2)
    check("运行中点击不会进入编辑态（NOACTIVATE 未被解除）",
          bool(ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))
    ov.set_run_state(False)

    ov.stop()
    time.sleep(0.8)
    print("")
    print("结果: PASS=%d  FAIL=%d" % (_pass, _fail))
    # Tk 在独立线程里 mainloop 时，解释器退出阶段的 Tcl 清理会报
    # "Tcl_AsyncDelete: async handler deleted by the wrong thread" 并带崩退出码；
    # 测完直接 _exit，让操作系统回收，比跟 Tcl 的析构顺序较劲可靠。
    sys.stdout.flush()
    os._exit(0 if _fail == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
