"""视觉模块：截图 + 模板匹配（OpenCV + mss）。"""
import base64
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


def save_template(image_bgr: np.ndarray, name: str | None = None) -> str:
    tpl_id = name or uuid.uuid4().hex[:12]
    _imwrite_unicode(_templates_dir() / f"{tpl_id}.png", image_bgr)
    return tpl_id


def load_template(tpl_id: str) -> np.ndarray:
    img = _imread_unicode(_templates_dir() / f"{tpl_id}.png")
    if img is None:
        raise FileNotFoundError(f"模板不存在: {tpl_id}")
    return img


def list_templates() -> list[dict]:
    return [{"id": p.stem, "file": p.name} for p in sorted(_templates_dir().glob("*.png"))]


def get_template_image(tpl_id: str) -> np.ndarray:
    path = _templates_dir() / f"{tpl_id}.png"
    if not path.is_file():
        raise FileNotFoundError(f"模板不存在: {tpl_id}")
    img = _imread_unicode(path)
    if img is None:
        raise ValueError(f"模板图像读取失败: {tpl_id}")
    return img


def rename_template(tpl_id: str, new_name: str) -> str:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("模板名不能为空")
    old = _templates_dir() / f"{tpl_id}.png"
    if not old.is_file():
        raise FileNotFoundError(f"模板不存在: {tpl_id}")
    new = _templates_dir() / f"{new_name}.png"
    if new.exists():
        raise ValueError(f"模板名已存在: {new_name}")
    old.rename(new)
    return new_name


def delete_template(tpl_id: str) -> None:
    path = _templates_dir() / f"{tpl_id}.png"
    if path.is_file():
        path.unlink()


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


def annotate_match(frame_bgr: np.ndarray, template_bgr: np.ndarray, x: int, y: int) -> np.ndarray:
    """在截图副本上画出匹配框（返回 BGR）。"""
    th, tw = template_bgr.shape[:2]
    vis = frame_bgr.copy()
    cv2.rectangle(vis, (x - tw // 2, y - th // 2), (x + tw // 2, y + th // 2), (0, 0, 255), 2)
    return vis
