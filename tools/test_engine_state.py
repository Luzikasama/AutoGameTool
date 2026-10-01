"""引擎状态逻辑回归测试（无需 GUI、无需起服务、不装键盘钩子）

覆盖几处「出过问题、又很容易再写错」的状态逻辑：

1. HotkeyManager 的「已触发」锁（每条绑定各有一把锁）
   - 按住 alt 连按两次 f1 → 必须触发两次（旧实现只触发第一次，手感就是"快捷键时灵时不灵"）
   - 长按 f1（系统重复 keydown、没有 keyup）→ 必须只触发一次
   - 两条绑定互不干扰、停用的绑定不触发
2. 快捷键绑定表：默认值、旧配置迁移、改键/启停的校验（重复组合、启用却没键）
3. Overlay 状态去重
   - 状态看门狗每秒调用一次 set_run_state，值没变时不能产生多余推送，
     否则悬浮框每秒重绘一次

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_engine_state.py
"""
import json
import asyncio
import os
import sys
from pathlib import Path

# Windows 下 stdout 默认按系统代码页（如 cp936）编码，重定向时中文会变乱码；
# 统一按 UTF-8 输出，断言结果和标题都能正常阅读。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = _ROOT / "engine"
sys.path.insert(0, str(_ENGINE))

# 配置读写要隔离：绑定表测试会写 config.json，绝不能碰用户真实的
# %APPDATA%\AutoGameTool（跟其它端到端脚本一个规矩）
_APPDATA = _ROOT / ".tmp" / "state-appdata"
_APPDATA.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(_APPDATA)

from pynput import keyboard  # noqa: E402

import appconfig  # noqa: E402
import hotkey as hotkey_mod  # noqa: E402
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


def make_hotkey(keys=("alt", "f1"), binding_id="toggle_run", enabled=True) -> HotkeyManager:
    """绕过 __init__ 构造实例：__init__ 会 register() 真的去装 Windows 键盘钩子，
    测试里不需要（也绝不该）碰系统钩子。"""
    h = object.__new__(HotkeyManager)
    h.bindings = [{"id": binding_id, "label": "测试绑定", "keys": list(keys), "enabled": enabled}]
    h.pressed = set()
    h._fired = set()
    h.calls = 0
    h.handlers = {binding_id: lambda: setattr(h, "calls", h.calls + 1)}
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
check("全部松开后锁复位", h._fired == set())

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
check("锁已复位", h._fired == set())
h._on_press(ALT)
h._on_press(F1)
check("可再次触发", h.calls == 2, h.calls)

print("== 快捷键 6：停用的绑定不触发、也不占锁 ==")
h = make_hotkey(enabled=False)
h._on_press(ALT)
h._on_press(F1)
check("停用的绑定按了也不触发", h.calls == 0, h.calls)
check("停用时锁不被占用", h._fired == set(), h._fired)

print("== 快捷键 7：两条绑定各按各的锁 ==")
h = object.__new__(HotkeyManager)
h.bindings = [
    {"id": "toggle_run", "label": "启停", "keys": ["alt", "f1"], "enabled": True},
    {"id": "record", "label": "录制", "keys": ["alt", "f2"], "enabled": True},
]
h.pressed = set()
h._fired = set()
h.hit = []
h.handlers = {"toggle_run": lambda: h.hit.append("toggle_run"), "record": lambda: h.hit.append("record")}
h._on_press(ALT)
h._on_press(F1)
h._on_release(F1)
h._on_press(keyboard.Key.f2)     # 同一个 alt 按住，换成 f2 → 触发另一条
check("两条绑定都能触发", h.hit == ["toggle_run", "record"], h.hit)
h._on_press(F1)                  # f2 还没松，f1 再按一次 → 只有启停那条能再触发
check("各自独立计锁", h.hit == ["toggle_run", "record", "toggle_run"], h.hit)

print("== 快捷键 8：键名别名与规整 ==")
check("arrowup → up", hotkey_mod.normalize_key("ArrowUp") == "up", hotkey_mod.normalize_key("ArrowUp"))
check("control → ctrl", hotkey_mod.normalize_key("Control") == "ctrl")
check("escape → esc", hotkey_mod.normalize_key("Escape") == "esc")
check("去空格 / 小写 / 去重",
      hotkey_mod.clean_keys([" ALT ", "", "f1", "F1"]) == ["alt", "f1"],
      hotkey_mod.clean_keys([" ALT ", "", "f1", "F1"]))

print("== 快捷键绑定表：默认值 / 旧配置迁移 / 校验 ==")
_cfg = appconfig.config_path()
if _cfg.exists():
    _cfg.unlink()

defaults = hotkey_mod.load_bindings()
check("默认三条：alt+F1 / alt+F2 / alt+F3",
      [b["keys"] for b in defaults] == [["alt", "f1"], ["alt", "f2"], ["alt", "f3"]],
      [b["keys"] for b in defaults])
check("默认全部启用", all(b["enabled"] for b in defaults))
check("默认绑定 id 固定（改键靠它对齐）",
      [b["id"] for b in defaults] == ["toggle_run", "record", "pick"], [b["id"] for b in defaults])

# 旧配置（v0.7.x 只存过一条 hotkey）必须迁移过来，而不是被丢掉重置成默认
appconfig.update(hotkey=["ctrl", "F9"])
migrated = hotkey_mod.load_bindings()
check("旧 hotkey 迁移到启停", migrated[0]["keys"] == ["ctrl", "f9"], migrated[0]["keys"])
check("迁移后写进新字段（下次启动不走兼容分支）",
      isinstance(appconfig.get("hotkeys"), list), appconfig.get("hotkeys"))
appconfig.update(hotkey=["alt", "f1"])

h = object.__new__(HotkeyManager)
h.bindings = hotkey_mod.load_bindings()
h.pressed = set()
h._fired = set()
h.handlers = {}
changed = h.set_bindings([
    {"id": "toggle_run", "keys": ["ctrl", "F8"]},
    {"id": "record", "keys": ["alt", "f2"], "enabled": False},
])
check("改键生效（含别名规整）", changed[0]["keys"] == ["ctrl", "f8"], changed[0]["keys"])
check("可以单独停用某条", changed[1]["enabled"] is False)
check("未提交的绑定保持原值", changed[2]["keys"] == ["alt", "f3"], changed[2]["keys"])
check("落盘只写稳定字段",
      set(json.loads(_cfg.read_text(encoding="utf-8"))["hotkeys"][0]) == {"id", "keys", "enabled"})
check("改键后锁被清空（旧按键不残留）", h._fired == set())

try:
    h.set_bindings([
        {"id": "toggle_run", "keys": ["ctrl", "f8"], "enabled": True},
        {"id": "record", "keys": ["ctrl", "f8"], "enabled": True},
    ])
    check("重复组合被拒绝", False, "没有报错")
except ValueError as e:
    check("重复组合被拒绝", "相同" in str(e), str(e))

try:
    h.set_bindings([{"id": "toggle_run", "keys": [], "enabled": True}])
    check("启用却没有键被拒绝", False, "没有报错")
except ValueError as e:
    check("启用却没有键被拒绝", "快捷键" in str(e), str(e))

cleared = h.set_bindings([{"id": "record", "keys": [], "enabled": False}])
check("停用的绑定允许留空键", cleared[1]["keys"] == [] and cleared[1]["enabled"] is False, cleared[1])
try:
    h.set_bindings([{"id": "record", "keys": [], "enabled": True}])
    check("清空后想启用会被要求先设键", False, "没有报错")
except ValueError as e:
    check("清空后想启用会被要求先设键", "快捷键" in str(e), str(e))

check("兼容接口 get/set 只动启停那一条",
      (h.set(["alt", "f1"]), h.get())[1] == ["alt", "f1"], h.get())

print("== 录制结果：按录制快捷键本身产生的事件要被剔掉 ==")
# 快捷键现在由 HotkeyManager 统一匹配（录制器自己不再看键盘），于是「按下快捷键」
# 的那几下按键会被顺带录进宏里；如果不在收尾时剔掉，每段录制都会自带一个 alt+f2，
# 回放时又会去切换录制状态。这里把收尾清理的规则钉死。
from recorder import Recorder  # noqa: E402


def make_recorder(hotkey=("alt", "f2")) -> Recorder:
    r = object.__new__(Recorder)
    r.hotkey = set(hotkey)
    r.recording = True
    r.events = []
    r._start_time = 0.0
    r._suppressed = set()
    r.states = []
    r.out = None
    r.on_state = lambda v: r.states.append(v)
    r.on_stop = lambda ev: setattr(r, "out", ev)
    return r


r = make_recorder()
r.events = [
    {"t": 0, "type": "keydown", "key": "alt"},     # 按下 alt+f2 开始录制
    {"t": 5, "type": "keydown", "key": "f2"},
    {"t": 20, "type": "keyup", "key": "f2"},
    {"t": 30, "type": "keyup", "key": "alt"},
    {"t": 400, "type": "mousedown", "x": 10, "y": 10, "button": "left"},
    {"t": 430, "type": "mouseup", "x": 10, "y": 10, "button": "left"},
    {"t": 900, "type": "keydown", "key": "alt"},   # 按下 alt+f2 停止录制
    {"t": 905, "type": "keydown", "key": "f2"},
]
r.stop()
check("开头的快捷键按下/抬起被剔掉", r.out and r.out[0]["type"] == "mousedown", r.out)
check("结尾的快捷键按下被剔掉", r.out and r.out[-1]["type"] == "mouseup", r.out)
check("中间的真实操作保留", len(r.out) == 2, r.out)
check("停录会推送状态", r.states == [False], r.states)

# 录制中段合法的 alt 组合（例如 alt+点击）不能被误删——它们共用 alt 这个键名
r2 = make_recorder()
r2.events = [
    {"t": 0, "type": "mousedown", "x": 1, "y": 1, "button": "left"},
    {"t": 50, "type": "keydown", "key": "alt"},
    {"t": 60, "type": "keydown", "key": "a"},
    {"t": 70, "type": "keyup", "key": "a"},
    {"t": 80, "type": "keyup", "key": "alt"},
]
r2.stop()
check("录制中段的 alt 组合完整保留", len(r2.out) == 5, r2.out)

# 用户就是想录「按住 alt + 点击」：开头那一下 alt 不是快捷键（没凑齐整组）→ 必须保留
r3 = make_recorder()
r3.events = [
    {"t": 0, "type": "keydown", "key": "alt"},
    {"t": 30, "type": "mousedown", "x": 5, "y": 5, "button": "left"},
    {"t": 60, "type": "mouseup", "x": 5, "y": 5, "button": "left"},
    {"t": 90, "type": "keyup", "key": "alt"},
]
r3.stop()
check("开头只按了 alt（不是整组快捷键）不误删", len(r3.out) == 4, r3.out)

# 快捷键停用（键集合为空）时不做任何删减
r4 = make_recorder(hotkey=())
r4.events = [
    {"t": 0, "type": "keydown", "key": "alt"},
    {"t": 10, "type": "keydown", "key": "f2"},
]
r4.stop()
check("快捷键停用时原样返回", len(r4.out) == 2, r4.out)

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
check("上界夹取：999999 -> 99999", engine_main._set_repeat_to(999999) == 99999)
before = engine_main._set_repeat_to(7)
check("非法输入保持原值", engine_main._set_repeat_to("abc") == before, before)
check("± 与直接输入共用同一套逻辑", engine_main._change_repeat(1) == 8)

print("== 访问令牌持久化（修「再次启动后页面连不上」）==")
# 旧实现每次启动都新生成令牌：程序已在运行时再双击一次，那条路径会用它**自己那份新令牌**
# 打开浏览器页面，而真正在跑的引擎用旧令牌 → 页面永远连不上（实测踩到）。
_token_file = appconfig.config_dir() / "engine.token"
if _token_file.exists():
    _token_file.unlink()
os.environ.pop("AUTOGAMETOOL_TOKEN", None)
t1 = engine_main._load_or_create_token()
t2 = engine_main._load_or_create_token()
check("两次调用返回同一个令牌", t1 == t2 and len(t1) >= 16, t1[:6] + "...")
check("令牌已落盘", _token_file.is_file())
check("落盘内容与返回一致", _token_file.read_text(encoding="utf-8").strip() == t1)
_token_file.write_text("short", encoding="utf-8")   # 明显非法（太短）
check("过短的令牌会被重新生成", engine_main._load_or_create_token() not in ("short", t1))
os.environ["AUTOGAMETOOL_TOKEN"] = "env-token-wins-0123456789"
check("环境变量优先", engine_main._load_or_create_token() == "env-token-wins-0123456789")
os.environ.pop("AUTOGAMETOOL_TOKEN", None)

print("== 悬浮框/快捷键「启动」不依赖页面（页面没响应就用缓存流程兜底）==")
# 实测事故：页面标签页被系统挂起后，悬浮框连点 14 次「启动」毫无反应——因为启动被
# 无条件委托给页面，而页面已经不执行 JS 了。现在会等一小会儿再兜底。


class _FakeManager:
    def __init__(self) -> None:
        self.connections = {object()}      # 引擎「以为」有页面连着
        self.sent: list = []

    async def broadcast(self, msg) -> None:
        self.sent.append(msg)


class _FakeExecutor:
    def __init__(self) -> None:
        self.running = False
        self.toggled = 0
        self.logs: list = []
        self.current_flow = {"name": "fake"}

    def reconcile(self) -> bool:
        return self.running

    async def log(self, level, msg, step=None) -> None:
        self.logs.append((level, msg))

    async def toggle(self) -> None:
        self.toggled += 1


async def _wait_start_fallback(manager, executor):
    """用假对象跑一遍 _toggle_run 的启动分支。"""
    real_m, real_e = engine_main.manager, engine_main.executor
    engine_main.manager, engine_main.executor = manager, executor
    try:
        await engine_main._toggle_run("测试")
    finally:
        engine_main.manager, engine_main.executor = real_m, real_e


_fm, _fe = _FakeManager(), _FakeExecutor()
asyncio.run(_wait_start_fallback(_fm, _fe))
check("先广播了 run_request（页面活着的话由它启动）",
      any(m.get("type") == "run_request" for m in _fm.sent), _fm.sent)
check("页面没响应时用引擎缓存流程兜底启动", _fe.toggled == 1, _fe.toggled)
check("日志说明了「页面没有响应」",
      any("没有响应" in m for _, m in _fe.logs), _fe.logs)

# 页面正常响应（流程真的起来了）时不该再兜底启动一次，否则会重复触发
class _FakeExecutorStarted(_FakeExecutor):
    async def toggle(self) -> None:
        self.toggled += 1


_fm2, _fe2 = _FakeManager(), _FakeExecutorStarted()


async def _page_responds():
    real_m, real_e = engine_main.manager, engine_main.executor
    engine_main.manager, engine_main.executor = _fm2, _fe2
    try:
        # 模拟页面收到 run_request 后真的把流程跑起来了
        async def _mark_running():
            await asyncio.sleep(0.25)
            _fe2.running = True
        task = asyncio.create_task(_mark_running())
        await engine_main._toggle_run("测试")
        await task
    finally:
        engine_main.manager, engine_main.executor = real_m, real_e


asyncio.run(_page_responds())
check("页面正常响应时不重复兜底启动", _fe2.toggled == 0, _fe2.toggled)

print("")
print("结果: PASS=" + str(_pass) + "  FAIL=" + str(_fail))
sys.exit(0 if _fail == 0 else 1)
