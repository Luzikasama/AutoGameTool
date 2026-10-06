"""应用数据目录：`%APPDATA%\\AutoTool`，以及从旧名 `AutoGameTool` 的自动迁移。

背景：本工具在 0.1.2 及更早叫 AutoGameTool，用户数据（`config.json`、`engine.token`、
`templates/`、`engine.log`）都写在 `%APPDATA%\\AutoGameTool` 下。0.1.3 正式改名后
必须把这份数据带过来 —— 否则老用户升级一次就"配置没了、模板全空"。

设计取舍：
  - **复制，不是移动**：老版本可能还装着、偶尔还会打开，搬走了那边就空了。数据很小
    （配置几 KB、模板若干张图），复制一份最省心，也天然可回滚。
  - **目标非空就不动**：新目录已经有内容说明用户已经在新版里配置过了，不能覆盖。
  - **全程 try/except**：迁移失败（权限、占用、磁盘满）绝不影响引擎启动 ——
    大不了就是回到"新目录空着"，功能照常，只是配置需要重设。
  - **先写临时目录再改名**：中途失败不会留下一个半截的 `AutoTool/`，
    否则下次启动会因为"目标非空"而永远不再重试。
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

APP_DIR_NAME = "AutoTool"
# 0.1.2 及更早用的数据目录名（**不要改**，这是历史事实）
LEGACY_DIR_NAME = "AutoGameTool"

_migrate_lock = threading.Lock()
_migrate_done = False
_migrate_note = ""


def appdata_root() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home())))


def app_dir() -> Path:
    """用户数据目录（首次调用时尝试把旧目录的内容迁过来）。"""
    global _migrate_done
    if not _migrate_done:
        with _migrate_lock:
            if not _migrate_done:
                try:
                    migrate_from_legacy()
                except Exception:
                    pass
                _migrate_done = True
    return appdata_root() / APP_DIR_NAME


def legacy_dir() -> Path:
    return appdata_root() / LEGACY_DIR_NAME


def migrate_from_legacy() -> int:
    """把 `%APPDATA%\\AutoGameTool` 里**新目录还没有的**东西补齐过来。

    为什么是"补齐"而不是"整体搬家"：壳（autotool.exe）在拉起引擎之前就会去读写
    `engine.token`，所以新目录往往是**壳先建好的**。若按"目标非空就跳过"，
    迁移就永远不会发生。逐项补缺与谁先启动无关，而且天然幂等 ——
    新目录里已经有的（用户在新版里新配的）一律不动。

    返回补过来的条目数；任何异常都吞掉（迁移失败不影响启动）。
    """
    global _migrate_note
    try:
        old = legacy_dir()
        if not old.is_dir():
            return 0
        new = appdata_root() / APP_DIR_NAME
        moved = _copy_missing(old, new)
        if moved:
            _migrate_note = f"已从旧数据目录 {old} 补齐 {moved} 项到 {new}"
        return moved
    except Exception as e:
        _migrate_note = f"迁移旧数据目录失败（忽略，改用新目录）：{type(e).__name__}: {e}"
        return 0


def _copy_missing(src: Path, dst: Path) -> int:
    """递归把 src 中 dst 缺失的文件复制过去；dst 已有的（文件或目录）一律不覆盖。"""
    count = 0
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except Exception:
        return 0
    for entry in src.iterdir():
        try:
            target = dst / entry.name
            if entry.is_dir():
                if target.is_file():
                    continue
                count += _copy_missing(entry, target)
            else:
                if target.exists():
                    continue
                shutil.copy2(entry, target)
                count += 1
        except Exception:
            continue
    return count


def migration_note() -> str:
    """最近一次迁移的结果说明（空串表示没有需要迁移的东西）。"""
    return _migrate_note
