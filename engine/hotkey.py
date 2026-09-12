"""全局快捷键监听（基于常驻键盘事件总线），默认 alt+f1。"""
import json
import os
from pathlib import Path

from pynput import keyboard

import keybus


def _config_path() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home()))) / "AutoGameTool"
    return base / "config.json"


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


class HotkeyManager:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.path = _config_path()
        self.keys = self._load()
        self.pressed: set[str] = set()
        self._fired = False
        keybus.register(on_press=self._on_press, on_release=self._on_release)

    def _load(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            keys = data.get("hotkey", ["alt", "f1"])
            if isinstance(keys, list) and keys:
                return [str(k).lower() for k in keys]
        except Exception:
            pass
        return ["alt", "f1"]

    def get(self) -> list[str]:
        return list(self.keys)

    def set(self, keys: list[str]) -> None:
        cleaned = [str(k).strip().lower() for k in keys if str(k).strip()]
        if not cleaned:
            raise ValueError("快捷键不能为空")
        self.keys = cleaned
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass
        data["hotkey"] = self.keys
        # 原子写入：先写临时文件再替换，避免崩溃时截断配置
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _on_press(self, key):
        self.pressed.add(_norm(key))
        target = set(self.keys)
        if target and target.issubset(self.pressed) and not self._fired:
            self._fired = True
            self.callback()

    def _on_release(self, key):
        self.pressed.discard(_norm(key))
        if not self.pressed:
            self._fired = False

    def stop(self) -> None:
        """仅注销回调，绝不销毁总线监听器。"""
        keybus.unregister(on_press=self._on_press, on_release=self._on_release)
