"""视觉模块：截图 + 模板匹配（OpenCV + mss）。"""
import base64
import json
import os
import sys
import uuid
from pathlib import Path

import cv2
import numpy as np
import mss


def _templates_dir() -> Path:
    """识别模板存放目录：打包后写 AppData，开发时在 engine/assets/templates。"""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "AutoGameTool" / "templates"
    else:
        base = Path(__file__).resolve().parent / "assets" / "templates"
    base.mkdir(parents=True, exist_ok=True)
    return base


def ensure_template_dir() -> Path:
    return _templates_dir()


# ---- 模板名校验（安全：黑名单制，防路径遍历；允许中英文及全角标点等合法文件名字符）----
_INVALID_CHARS = frozenset('/\\:*?"<>|')  # Windows 文件系统禁用字符
_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _validate_tpl_id(tpl_id: str) -> str:
    """校验模板名/ID 可安全用作文件名，非法时抛 ValueError。"""
    s = str(tpl_id or "").strip()
    if not s or len(s) > 64:
        raise ValueError(f"模板名不能为空且不超过 64 字: {tpl_id!r}")
    bad = sorted({c for c in s if c in _INVALID_CHARS or ord(c) < 0x20 or ord(c) == 0x7F})
    if bad:
        raise ValueError(f"模板名含非法字符 {bad}（禁止 / \\ : * ? \" < > | 和控制字符）: {tpl_id!r}")
    if ".." in s or s.startswith(".") or s.endswith(".") or s.lower() in _RESERVED_NAMES:
        raise ValueError(f"非法模板名: {tpl_id!r}")
    return s


def _tpl_path(tpl_id: str) -> Path:
    """返回模板 PNG 的安全绝对路径（双重防遍历：白名单 + resolve 归属校验）。"""
    safe = _validate_tpl_id(tpl_id)
    base = _templates_dir().resolve()
    p = (base / f"{safe}.png").resolve()
    if p.parent != base:
        raise ValueError(f"非法模板路径: {tpl_id!r}")
    return p


def _meta_path(tpl_id: str) -> Path:
    safe = _validate_tpl_id(tpl_id)
    base = _templates_dir().resolve()
    return base / f"{safe}.meta.json"


def grab_frame(region: dict | None = None) -> np.ndarray:
    """截取屏幕（或指定区域），返回 BGR numpy 数组。region: {left, top, width, height}"""
    with mss.mss() as sct:
        if region:
            mon = {
                "left": int(region["left"]),
                "top": int(region["top"]),
                "width": int(region["width"]),
                "height": int(region["height"]),
            }
        else:
            mon = sct.monitors[1]  # 主显示器
        raw = sct.grab(mon)
        return cv2.cvtColor(np.array(raw), cv2.COLOR_BGRA2BGR)


def frame_to_jpeg(frame_bgr: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG 编码失败")
    return buf.tobytes()


def frame_to_data_url(frame_bgr: np.ndarray, quality: int = 80) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(frame_to_jpeg(frame_bgr, quality)).decode("ascii")


def decode_image_b64(data: str) -> np.ndarray:
    """解码 base64 图像为 BGR。"""
    if "," in data:
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("图像解码失败")
    return img


def _imread_unicode(path) -> np.ndarray | None:
    """cv2.imread 不支持中文/非 ASCII 路径，用 fromfile + imdecode 读取。"""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _imwrite_unicode(path, img: np.ndarray) -> bool:
    """cv2.imwrite 不支持中文/非 ASCII 路径，用 imencode + tofile 写入。"""
    try:
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            return False
        buf.tofile(str(path))
        return True
    except Exception:
        return False


def save_template(image_bgr: np.ndarray, name: str | None = None, meta: dict | None = None) -> str:
    tpl_id = _validate_tpl_id(name) if name else uuid.uuid4().hex[:12]
    path = _tpl_path(tpl_id)
    if name and path.exists():
        raise ValueError(f"模板名已存在: {tpl_id}")
    if not _imwrite_unicode(path, image_bgr):
        raise ValueError(f"模板图像写入失败: {tpl_id}")
    if meta:
        try:
            _meta_path(tpl_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass  # 元数据写失败不影响模板本体
    return tpl_id


def load_template(tpl_id: str) -> np.ndarray:
    img = _imread_unicode(_tpl_path(tpl_id))
    if img is None:
        raise FileNotFoundError(f"模板不存在: {tpl_id}")
    return img


def load_template_meta(tpl_id: str) -> dict:
    """读取模板元数据（捕获时的参考画面尺寸等），无则返回 {}。"""
    try:
        p = _meta_path(tpl_id)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def list_templates() -> list[dict]:
    return [{"id": p.stem, "file": p.name} for p in sorted(_templates_dir().glob("*.png"))]


def get_template_image(tpl_id: str) -> np.ndarray:
    path = _tpl_path(tpl_id)
    if not path.is_file():
        raise FileNotFoundError(f"模板不存在: {tpl_id}")
    img = _imread_unicode(path)
    if img is None:
        raise ValueError(f"模板图像读取失败: {tpl_id}")
    return img


def rename_template(tpl_id: str, new_name: str) -> str:
    new_name = _validate_tpl_id(new_name)
    old = _tpl_path(tpl_id)
    if not old.is_file():
        raise FileNotFoundError(f"模板不存在: {tpl_id}")
    new = _tpl_path(new_name)
    if new.exists():
        raise ValueError(f"模板名已存在: {new_name}")
    old.rename(new)
    old_meta = _meta_path(tpl_id)
    if old_meta.is_file():
        try:
            old_meta.rename(_meta_path(new_name))
        except Exception:
            pass
    return new_name


def delete_template(tpl_id: str) -> None:
    path = _tpl_path(tpl_id)
    if path.is_file():
        path.unlink()
    meta = _meta_path(tpl_id)
    if meta.is_file():
        try:
            meta.unlink()
        except Exception:
            pass


def match_template(frame_bgr: np.ndarray, template_bgr: np.ndarray, threshold: float = 0.85):
    """模板匹配（灰度加速），返回 (found, x, y, score)，坐标为截图内中心点。"""
    th, tw = template_bgr.shape[:2]
    if frame_bgr.shape[0] < th or frame_bgr.shape[1] < tw:
        return False, 0, 0, 0.0
    # 转灰度匹配，速度约为彩色 3 倍
    frame_g = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    tpl_g = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(frame_g, tpl_g, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    x = int(max_loc[0] + tw // 2)
    y = int(max_loc[1] + th // 2)
    return (max_val >= threshold, x, y, float(max_val))


def match_template_auto(frame_bgr: np.ndarray, template_bgr: np.ndarray, meta: dict | None,
                        threshold: float = 0.85):
    """分辨率自适应匹配：模板捕获时的参考画面尺寸（meta.frame_w/h）与当前画面
    不一致时（换了显示器分辨率 / DPI 缩放变化 / 窗口尺寸变化），先把模板按相同
    比例缩放再匹配；缩放后得分不理想时回退原始尺寸取高分者。

    返回 (found, x, y, score, scale_used)，坐标为当前截图内中心点。
    """
    cur_h, cur_w = frame_bgr.shape[:2]
    ref_w = ref_h = 0
    if isinstance(meta, dict):
        try:
            ref_w = int(meta.get("frame_w") or 0)
            ref_h = int(meta.get("frame_h") or 0)
        except Exception:
            ref_w = ref_h = 0
    if ref_w > 0 and ref_h > 0 and (ref_w != cur_w or ref_h != cur_h):
        sx, sy = cur_w / ref_w, cur_h / ref_h
        # 仅在横纵比基本一致且缩放幅度合理时缩放，防止窗口被拖大/拖小后误缩放
        if 0.3 <= sx <= 3.0 and abs(sx / sy - 1) < 0.15:
            tw = max(4, int(round(template_bgr.shape[1] * sx)))
            th = max(4, int(round(template_bgr.shape[0] * sy)))
            if tw <= cur_w and th <= cur_h:
                interp = cv2.INTER_AREA if sx < 1 else cv2.INTER_CUBIC
                scaled = cv2.resize(template_bgr, (tw, th), interpolation=interp)
                found, x, y, score = match_template(frame_bgr, scaled, threshold)
                if found or score >= threshold - 0.05:
                    return found, x, y, score, sx
                # 缩放匹配没把握，回退原始尺寸再试一次，取高分者
                f0, x0, y0, s0 = match_template(frame_bgr, template_bgr, threshold)
                if s0 > score:
                    return f0, x0, y0, s0, 1.0
                return found, x, y, score, sx
    found, x, y, score = match_template(frame_bgr, template_bgr, threshold)
    return found, x, y, score, 1.0


def primary_monitor_size() -> tuple[int, int]:
    """主显示器物理像素尺寸（进程已设 DPI 感知，与截图/点击同一坐标系）。"""
    with mss.mss() as sct:
        mon = sct.monitors[1]
        return int(mon["width"]), int(mon["height"])


def annotate_match(frame_bgr: np.ndarray, template_bgr: np.ndarray, x: int, y: int) -> np.ndarray:
    """在截图副本上画出匹配框（返回 BGR）。"""
    th, tw = template_bgr.shape[:2]
    vis = frame_bgr.copy()
    cv2.rectangle(vis, (x - tw // 2, y - th // 2), (x + tw // 2, y + th // 2), (0, 0, 255), 2)
    return vis
