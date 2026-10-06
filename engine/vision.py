"""视觉模块：截图 + 模板匹配（OpenCV + mss）。"""
import base64
import json
import sys
import uuid
from pathlib import Path

import cv2
import numpy as np
import mss

import apppaths


def _templates_dir() -> Path:
    """识别模板存放目录：打包后写 AppData，开发时在 engine/assets/templates。"""
    if getattr(sys, "frozen", False):
        base = apppaths.app_dir() / "templates"
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


def write_image(path, img: np.ndarray) -> bool:
    """公开的"把 BGR 图写到任意路径"入口（对非 ASCII 路径安全）。"""
    return _imwrite_unicode(path, img)


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


# ---------------------------------------------------------------------------
# OCR（RapidOCR / onnxruntime）
# ---------------------------------------------------------------------------
_ocr_engine = None
_ocr_failed = ''


def _get_ocr():
    """懒加载 OCR 引擎。

    首次构造要加载 onnx 模型（几百毫秒~数秒），所以**只在真的用到「文字识别」节点时才加载**：
    没用到 OCR 的脚本不该为它付出启动时间；打包体积也能靠「可选依赖」的思路处理。
    加载失败只记一次原因，后续直接抛同样的错误，避免每次轮询都重试一遍。
    """
    global _ocr_engine, _ocr_failed
    if _ocr_engine is not None:
        return _ocr_engine
    if _ocr_failed:
        raise RuntimeError(_ocr_failed)
    try:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
        return _ocr_engine
    except Exception as e:  # pragma: no cover - 依赖缺失/模型缺失时的分支
        _ocr_failed = f'OCR 引擎不可用（{e}）。请确认已安装 rapidocr_onnxruntime 且模型文件完整。'
        raise RuntimeError(_ocr_failed)


def ocr_frame(frame_bgr: np.ndarray) -> list[dict]:
    """识别一帧里的所有文字，返回 [{text, score, cx, cy, box}]（坐标为帧内像素）。"""
    engine = _get_ocr()
    result, _elapse = engine(frame_bgr)
    out: list[dict] = []
    for item in result or []:
        try:
            box, text, score = item[0], item[1], float(item[2])
        except (IndexError, TypeError, ValueError):
            continue
        if not str(text).strip():
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        out.append(
            {
                'text': str(text),
                'score': score,
                'cx': int(round(sum(xs) / len(xs))),
                'cy': int(round(sum(ys) / len(ys))),
                'box': [[int(round(p[0])), int(round(p[1]))] for p in box],
            }
        )
    return out


# ---------------------------------------------------------------------------
# 颜色 / 像素 / 区域分析
# ---------------------------------------------------------------------------

def parse_hex_color(text: str) -> tuple[int, int, int]:
    """'#RRGGBB' / 'RRGGBB' → (B, G, R)。非法输入抛 ValueError。"""
    s = str(text or '').strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f'颜色格式不正确（应为 #RRGGBB）：{text!r}')
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        raise ValueError(f'颜色格式不正确（应为 #RRGGBB）：{text!r}')
    return b, g, r


def to_hex_color(bgr) -> str:
    b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
    return f'#{r:02x}{g:02x}{b:02x}'


def pixel_bgr(frame_bgr: np.ndarray, x: int, y: int, size: int = 1) -> tuple[int, int, int] | None:
    """取以 (x, y) 为中心、边长 size 的方块平均色（越界返回 None）。

    取平均色是为了抗抗锯齿与抗渲染抖动：单点取样在缩放/半透明控件上会随机失败。
    """
    h, w = frame_bgr.shape[:2]
    size = max(1, int(size))
    half = size // 2
    x0, x1 = max(0, int(x) - half), min(w, int(x) - half + size)
    y0, y1 = max(0, int(y) - half), min(h, int(y) - half + size)
    if x0 >= x1 or y0 >= y1:
        return None
    patch = frame_bgr[y0:y1, x0:x1]
    mean = patch.reshape(-1, 3).mean(axis=0)
    return int(round(mean[0])), int(round(mean[1])), int(round(mean[2]))


def color_within(bgr, target, tolerance: int) -> bool:
    t = max(0, int(tolerance))
    return all(abs(int(bgr[i]) - int(target[i])) <= t for i in range(3))


def count_color(frame_bgr: np.ndarray, target, tolerance: int) -> tuple[int, int, int]:
    """统计区域内与目标色（在容差内）的像素数与第一个命中点坐标（帧内）。"""
    t = max(0, int(tolerance))
    diff = np.abs(frame_bgr.astype(np.int16) - np.array(target, dtype=np.int16))
    mask = (diff <= t).all(axis=2)
    count = int(np.count_nonzero(mask))
    if count == 0:
        return 0, -1, -1
    ys, xs = np.nonzero(mask)
    return count, int(xs[0]), int(ys[0])


def region_average_color(frame_bgr: np.ndarray) -> tuple[int, int, int]:
    mean = frame_bgr.reshape(-1, 3).mean(axis=0)
    return int(round(mean[0])), int(round(mean[1])), int(round(mean[2]))


def region_diff_ratio(frame_bgr: np.ndarray, reference_bgr: np.ndarray) -> float:
    """两幅画面的差异比例（0~1）：逐像素灰度差的绝对值超过 25 才算"这个像素变了"。

    阈值 25 是经验值：低于它多半是压缩噪声/抖动，高于它通常是真实的界面变化。
    两图尺寸不同时先把参考图缩放到当前尺寸。
    """
    h, w = frame_bgr.shape[:2]
    ref = reference_bgr
    if ref.shape[0] != h or ref.shape[1] != w:
        ref = cv2.resize(reference_bgr, (w, h), interpolation=cv2.INTER_AREA)
    g1 = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
    g2 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.int16)
    changed = np.count_nonzero(np.abs(g1 - g2) > 25)
    total = max(1, h * w)
    return float(changed) / float(total)


def crop_region(frame_bgr: np.ndarray, region: dict) -> np.ndarray:
    """按帧内坐标裁一块区域（越界自动收敛到有效范围）。"""
    h, w = frame_bgr.shape[:2]
    x0 = max(0, min(w, int(region.get('left', 0))))
    y0 = max(0, min(h, int(region.get('top', 0))))
    x1 = max(x0, min(w, x0 + int(region.get('width', 0))))
    y1 = max(y0, min(h, y0 + int(region.get('height', 0))))
    return frame_bgr[y0:y1, x0:x1]

