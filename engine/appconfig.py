"""用户配置读写（%APPDATA%\\AutoGameTool\\config.json）。

所有配置项共用这一个文件，统一从这里读写，避免多个模块各自「读-改-写」互相覆盖。
写入使用「临时文件 + 替换」保证原子性，崩溃/断电不会留下截断的配置。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def config_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "AutoGameTool"


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict:
    """读取整份配置；文件缺失或损坏时返回空字典。"""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get(key: str, default: Any = None) -> Any:
    value = load().get(key, default)
    return default if value is None else value


def update(**items: Any) -> dict:
    """合并写入若干配置项并返回写入后的完整配置（原子替换）。"""
    with _LOCK:
        data = load()
        data.update(items)
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return data
