"""悬浮框「循环次数直接编辑」回归测试（**不碰真实鼠标键盘**）

为什么这样做：早期版本用真实点击 + 真实按键去验证这个功能（`/input/click` +
`/input/key`），那会移动用户的光标、把按键打进当前前台窗口——既打扰人，又只要
用户此刻在用电脑就必然测不稳。这里改为在 Tk 内部合成事件
（`widget.event_generate`）：走的是**同一套绑定与回调**，但不产生任何系统级输入。

覆盖：
  1. 点击数字 → 临时解除 WS_EX_NOACTIVATE（否则非活动窗口拿不到键盘焦点）
  2. 提交 → 发出 `repeat_set:<n>` 动作，并恢复 NOACTIVATE（"不抢焦点"是不变量）
  3. 越界/非法输入被夹到 1..99999，非法值保持原值
  4. Esc 放弃编辑并恢复显示
  5. 运行中禁用输入（与 ± 一致），且此时点击不会进入编辑态
  6. 激活期内（窗口拿不到前台时）的延时判定绝不能拿旧值抢跑提交、把用户的输入吃掉

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
        """写入文本并提交（**不走合成 Return**）。

        为什么不用 `event_generate("<Return>")`：Tk 会把**键盘事件重定向到当前焦点窗口**，
        而这个测试里悬浮框拿不到真实焦点（自动化环境下 SetForegroundWindow 常被系统拒绝，
        实测 `focus_get()` 会是 None），于是 Return 会被丢到别处、提交根本不发生——
        那是环境限制，不是产品缺陷。真实键盘路径（点数字 → 手敲 → 回车）按项目约定
        由用户手工确认；这里改为调用 Return 绑定执行的那个回调（`_commit_repeat`），
        并另外断言绑定确实还在（见用例 2 之后的绑定检查）。
        """
        def _do():
            ov._entry_repeat.delete(0, "end")
            ov._entry_repeat.insert(0, text)
            ov._commit_repeat()
        return in_tk(_do)

    def mark() -> int:
        """记录基线：只比较这一步新产生的动作，避免跨步骤污染。"""
        return len(actions)

    def since(n: int) -> list:
        return actions[n:]

    def diag(tag: str) -> None:
        """失败时最需要的是内部状态：编辑态、激活中、焦点、前台窗口、输入框文本。
        这里的每个字段都曾经是「看起来没反应」的怀疑对象。"""
        def _d():
            return {
                "activating": ov._activating,
                "editing": ov._editing_repeat,
                "gen": ov._edit_gen,
                "text": ov._entry_repeat.get(),
                "state": str(ov._entry_repeat.cget("state")),
                "focus": str(ov._root.focus_get()),
                "fg": ctypes.windll.user32.GetForegroundWindow(),
                "hwnd": ov._hwnd,
                "repeat": ov._repeat,
            }
        try:
            print("        [diag %s] %s" % (tag, in_tk(_d)))
        except Exception as e:  # noqa: BLE001
            print("        [diag %s] 取值失败 %r" % (tag, e))

    print("== 1. 初始状态 ==")
    check("初始带 WS_EX_NOACTIVATE（点击不抢焦点）",
          bool(ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))
    width = int(in_tk(lambda: ov._entry_repeat.cget("width")) or 0)
    check(f"输入框宽度能显示 5 位数字（width={width}）", width >= 5, width)

    print("== 2. 点击数字进入编辑态 ==")
    click_number()
    time.sleep(0.2)
    check("编辑期间 NOACTIVATE 被临时解除",
          not (ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))

    # 真实按键走的是这些绑定；它们被删掉的话，功能会"看起来完全正常"却敲不进去
    binds = in_tk(lambda: [
        bool(ov._entry_repeat.bind(seq))
        for seq in ("<Button-1>", "<Return>", "<KP_Enter>", "<Escape>", "<FocusOut>")
    ])
    check("点击 / 回车 / 小键盘回车 / Esc / 失焦 都绑了处理函数", all(binds), binds)

    print("== 3. 输入 37 并回车 ==")
    n = mark()
    type_and_enter("37")
    time.sleep(0.3)
    got = since(n)
    check("发出 repeat_set:37", got == ["repeat_set:37"], got)
    if got != ["repeat_set:37"]:
        diag("case3")
    check("提交后 NOACTIVATE 已恢复",
          bool(ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))
    txt = in_tk(lambda: ov._entry_repeat.get())
    check("显示值回写为 37", txt == "37", txt)

    print("== 4. 越界与非法输入 ==")
    n = mark()
    click_number()
    time.sleep(0.15)
    type_and_enter("999999")
    time.sleep(0.25)
    got = since(n)
    check("999999 夹到 99999", got == ["repeat_set:99999"], got)

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
    # 同上：Esc 也走"绑定里的那个回调"，避免依赖真实键盘焦点
    in_tk(ov._cancel_repeat_edit)
    time.sleep(0.25)
    got = since(n)
    check("Esc 不产生动作", got == [], got)
    txt = in_tk(lambda: ov._entry_repeat.get())
    check("Esc 恢复为当前值 5", txt == "5", txt)
    check("Esc 后 NOACTIVATE 已恢复",
          bool(ex_style(hwnd) & WS_EX_NOACTIVATE), hex(ex_style(hwnd)))

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

    print("== 7. 激活期内（刚点开数字的头几百毫秒）延时判定绝不能提交 ==")
    ov.set_repeat(5)
    time.sleep(0.25)
    # 复现真实场景：点击后 SetForegroundWindow 被系统拒绝，前台仍是别的程序，于是
    # Tk 的 focus_set 也落不到 Entry 上。旧实现会把这种「激活造成的失焦」误判成
    # 「用户点到别处」，拿旧值 5 抢先提交并关掉编辑态——紧接着敲进去的数字全部丢失
    # （v0.7.3 回归里表现为随机 FAIL，且只在窗口拿不到前台时出现）。
    # 这里把前台窗口固定为 0 并把 Tk 焦点挪出 Entry，让这条判定路径稳定复现。
    _fg = overlay_mod.ctypes.windll.user32.GetForegroundWindow
    overlay_mod.ctypes.windll.user32.GetForegroundWindow = lambda: 0
    try:
        n = mark()
        click_number()                                # 进入编辑态
        in_tk(lambda: ov._root.focus_set())           # 模拟 focus_set 没落到 Entry
        in_tk(lambda: ov._entry_repeat.delete(0, "end"))
        in_tk(lambda: ov._entry_repeat.insert(0, "123"))
        time.sleep(0.15)                              # 越过 120ms 的延时判定点
        in_tk(ov._recheck_repeat_focus)               # 手动触发那次延时判定
        got = since(n)
        editing = in_tk(lambda: ov._editing_repeat)
        check("宽限期内不提交、也不退出编辑态", got == [] and editing, (got, editing))
        check("用户已经敲进去的内容还在", in_tk(lambda: ov._entry_repeat.get()) == "123",
              in_tk(lambda: ov._entry_repeat.get()))
        in_tk(ov._commit_repeat)
        time.sleep(0.3)
        check("随后的提交按新值生效（没有被旧值抢跑）",
              since(n) == ["repeat_set:123"], since(n))
    finally:
        overlay_mod.ctypes.windll.user32.GetForegroundWindow = _fg
        # 兜底：万一上面把它留成"可抢焦点"的状态，恢复不变量（后续断言也依赖它）
        in_tk(lambda: ov._entry_repeat.delete(0, "end"))
        in_tk(lambda: ov._apply_window_flags())

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
