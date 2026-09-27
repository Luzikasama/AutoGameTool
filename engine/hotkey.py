"""全局快捷键：所有命令都在这里匹配，可在界面里改键、单独启用/停用。

默认 alt+F1 / alt+F2 / alt+F3（按界面顺序依次排列）。

为什么集中在这一处：旧实现把「匹配按键」写了三份——启停在本模块、键鼠录制在
`recorder.py`、坐标拾取在 `picker.py`（各自维护一份按下集合与子集判断）。于是
「哪些快捷键能改」完全取决于当初写在哪个文件里：只有启停那条能改，另两条写死。
现在只有这一个匹配器，绑定表来自配置 `hotkeys`；recorder / picker 只暴露动作
（`toggle()` / `arm()`），不再自己看键盘。
"""
from __future__ import annotations

from typing import Callable

from pynput import keyboard

import appconfig
import enginelog
import keybus

# 纯修饰键：它们不用于「解除已触发锁」，否则按住 alt 连按 f1 会重复触发
_MODIFIERS = {"ctrl", "alt", "shift", "win"}

# 全部可配置的全局快捷键。顺序 = 界面里的顺序；`id` 是前后端与配置里的稳定标识，
# 不要改（改了等于把用户已保存的改键丢掉）。label 由引擎提供，前端只负责显示。
DEFAULT_BINDINGS: list[dict] = [
    {"id": "toggle_run", "label": "启动 / 停止脚本", "keys": ["alt", "f1"], "enabled": True},
    {"id": "record", "label": "开始 / 停止键鼠录制", "keys": ["alt", "f2"], "enabled": True},
    {"id": "pick", "label": "拾取屏幕坐标", "keys": ["alt", "f3"], "enabled": True},
]

# 前端合成事件与 pynput 的键名差异（只有这几个需要翻译，其余两边一致）
_KEY_ALIASES = {
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "escape": "esc", "return": "enter", "del": "delete", "control": "ctrl", "meta": "win",
}


def normalize_key(name: str) -> str:
    """把前端传来的键名统一成 pynput 的写法（alt+f1 这种）。"""
    k = str(name or "").strip().lower()
    return _KEY_ALIASES.get(k, k)


def _norm(key) -> str:
    if isinstance(key, keyboard.Key):
        name = key.name or ""
        if name.startswith("alt"):
            return "alt"
        if name.startswith("ctrl"):
            return "ctrl"
        if name.startswith("shift"):
            return "shift"
        if name.startswith("cmd"):  # pynput 的 Win 键叫 cmd/cmd_l/cmd_r，前端记为 win
            return "win"
        return name
    if isinstance(key, keyboard.KeyCode):
        return (key.char or "").lower()
    return str(key).lower()


def clean_keys(keys) -> list[str]:
    """规整一组按键：去空、小写、翻译别名、去重（保持顺序）。"""
    out: list[str] = []
    for k in keys or []:
        k = normalize_key(k)
        if k and k not in out:
            out.append(k)
    return out


def load_bindings() -> list[dict]:
    """读绑定表；缺失或非法一律回退到默认值。

    兼容 v0.7.x 的旧配置：那时只存过一条 `hotkey`（启停）。读到它就迁移到
    `toggle_run` 上并立即落盘，避免每次启动都走这段兼容分支。
    """
    out = [{**b, "keys": list(b["keys"])} for b in DEFAULT_BINDINGS]
    saved = appconfig.get("hotkeys", None)
    by_id: dict[str, dict] = {}
    if isinstance(saved, list):
        by_id = {str(b.get("id")): b for b in saved if isinstance(b, dict)}
    else:
        old = clean_keys(appconfig.get("hotkey", None))
        if old:
            by_id = {"toggle_run": {"keys": old, "enabled": True}}
    for b in out:
        src = by_id.get(b["id"])
        if not isinstance(src, dict):
            continue
        keys = clean_keys(src.get("keys"))
        if keys:
            b["keys"] = keys
        b["enabled"] = bool(src.get("enabled", True))
    for b in out:
        # 启用但没键 = 永远不可能触发，直接按停用处理（脏配置不该让「启用了却没反应」）
        if b["enabled"] and not b["keys"]:
            b["enabled"] = False
    if by_id and not isinstance(saved, list):
        appconfig.update(hotkeys=[_dump(b) for b in out])
    return out


def _dump(binding: dict) -> dict:
    return {"id": binding["id"], "keys": list(binding["keys"]), "enabled": bool(binding["enabled"])}


class HotkeyManager:
    """按键匹配器：每个绑定各自维护「已触发锁」，互不影响。"""

    def __init__(self, handlers: dict[str, Callable[[], None]]) -> None:
        self.handlers = dict(handlers or {})
        self.bindings: list[dict] = load_bindings()
        self.pressed: set[str] = set()
        self._fired: set[str] = set()
        keybus.register(on_press=self._on_press, on_release=self._on_release)

    # ---- 查询 / 修改 ----
    def get_bindings(self) -> list[dict]:
        return [{**b, "keys": list(b["keys"])} for b in self.bindings]

    def keys_of(self, binding_id: str) -> list[str]:
        for b in self.bindings:
            if b["id"] == binding_id:
                return list(b["keys"])
        return []

    def get(self) -> list[str]:
        """兼容旧接口：只表示「启动 / 停止脚本」这一条。"""
        return self.keys_of("toggle_run")

    def set(self, keys: list[str]) -> None:
        """兼容旧接口：只改「启动 / 停止脚本」这一条。"""
        cleaned = clean_keys(keys)
        if not cleaned:
            raise ValueError("快捷键不能为空")
        items = [_dump(b) for b in self.bindings]
        for it in items:
            if it["id"] == "toggle_run":
                it["keys"] = cleaned
        self.set_bindings(items)

    def set_bindings(self, items: list[dict]) -> list[dict]:
        """整体替换绑定表（界面点「保存」时调用）。

        未知 id 直接忽略；缺字段沿用当前值；启用的绑定必须有键；两条启用的绑定
        不能是同一组键——否则按下去只会命中先匹配到的那条，用户会以为「另一个失灵」。
        """
        incoming = {str(x.get("id")): x for x in (items or []) if isinstance(x, dict)}
        current = {b["id"]: b for b in self.bindings}
        merged: list[dict] = []
        for base in DEFAULT_BINDINGS:
            src = incoming.get(base["id"], {})
            cur = current.get(base["id"], base)
            # 没提交 keys 字段 = 沿用当前值；提交了空数组 = 用户真的清空了它（启用时必须报错）
            keys = clean_keys(src.get("keys")) if "keys" in src else list(cur["keys"])
            enabled = bool(src.get("enabled", cur["enabled"]))
            if enabled and not keys:
                raise ValueError(f"「{base['label']}」已启用，请先设置快捷键")
            merged.append({"id": base["id"], "label": base["label"], "keys": keys, "enabled": enabled})

        seen: dict[str, str] = {}
        for b in merged:
            if not b["enabled"]:
                continue
            sig = "+".join(sorted(b["keys"]))
            if sig in seen:
                raise ValueError(
                    f"「{b['label']}」与「{seen[sig]}」的快捷键相同（{sig}），请改成不同的组合"
                )
            seen[sig] = b["label"]

        self.bindings = merged
        self._fired.clear()
        # 原子写入交由 appconfig 统一处理，避免多处读-改-写互相覆盖
        appconfig.update(hotkeys=[_dump(b) for b in merged])
        return self.get_bindings()

    # ---- 按键事件 ----
    def _fire(self, binding: dict) -> None:
        self._fired.add(binding["id"])
        cb = self.handlers.get(binding["id"])
        if cb is None:
            enginelog.warn("快捷键「%s」没有对应的动作，已忽略", binding["label"])
            return
        try:
            cb()
        except Exception as e:  # 一个动作出错不能牵连其它快捷键
            enginelog.error("快捷键「%s」执行失败：%r", binding["label"], e, exc_info=True)

    def _on_press(self, key) -> None:
        self.pressed.add(_norm(key))
        for b in self.bindings:
            if not b["enabled"] or b["id"] in self._fired:
                continue
            target = set(b["keys"])
            if target and target.issubset(self.pressed):
                self._fire(b)

    def _on_release(self, key) -> None:
        k = _norm(key)
        self.pressed.discard(k)
        # 组合键里的**非修饰键**一抬起就解除该绑定的「已触发」锁。
        # 旧实现只在「所有键都松开」时解锁，于是按住 alt 连按两次 f1 只会触发第一次
        # （第二次按下时 alt 仍按着，锁还是 True）——手感就是「快捷键时灵时不灵」。
        # 这样改仍保留原有保护：长按 f1 时系统重复发的是 keydown（没有 keyup），
        # 不会重复触发。
        for b in self.bindings:
            if b["id"] in self._fired and k in b["keys"] and k not in _MODIFIERS:
                self._fired.discard(b["id"])
        if not self.pressed:
            self._fired.clear()

    def stop(self) -> None:
        """仅注销回调，绝不销毁总线监听器。"""
        keybus.unregister(on_press=self._on_press, on_release=self._on_release)
