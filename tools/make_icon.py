"""生成 AutoGameTool 应用图标（多尺寸 ICO + PNG）。

图标含义：深色圆角底板 + 青色「循环」圆弧 + 白色播放三角 = 自动循环执行。

用法：
    engine\\.venv\\Scripts\\python tools\\make_icon.py

产物：
    assets/AutoGameTool.ico            # 多尺寸（16~256），供 exe / 安装包 / 快捷方式使用
    assets/AutoGameTool.png            # 512px 主图
    frontend/public/favicon.ico        # 网页标签页图标
    frontend/src-tauri/icons/*         # Tauri 桌面壳图标（覆盖默认 logo）
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TAURI_ICONS = ROOT / "frontend" / "src-tauri" / "icons"
PUBLIC = ROOT / "frontend" / "public"

S = 1024  # 超采样画布，最后降采样以获得抗锯齿
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

BG_TOP = (40, 53, 76)
BG_BOTTOM = (13, 18, 28)
ACCENT = (34, 211, 238)       # cyan-400
ACCENT_DEEP = (37, 99, 235)   # blue-600
GLYPH = (246, 250, 253)

RING_R = 0.300   # 圆弧半径（相对画布）
RING_W = 0.105   # 圆弧粗细
RING_A0, RING_A1 = 20.0, 310.0  # 起始/结束角度（留出右上角缺口）
TRI_LEFT = 0.112   # 三角左侧距中心
TRI_TIP = 0.212    # 三角尖端距中心
TRI_HALF = 0.172   # 三角半高


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _background() -> Image.Image:
    """圆角底板：垂直线性渐变 + 左上角蓝色氛围光。"""
    strip = Image.new("RGB", (1, S))
    px = strip.load()
    for y in range(S):
        t = y / (S - 1)
        px[0, y] = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
    grad = strip.resize((S, S), Image.BILINEAR)

    glow_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow_mask).ellipse(
        (-S * 0.38, -S * 0.48, S * 0.98, S * 0.88), fill=115
    )
    glow_mask = glow_mask.filter(ImageFilter.GaussianBlur(S * 0.085))
    tint = Image.new("RGB", (S, S), ACCENT_DEEP)
    grad = Image.composite(tint, grad, glow_mask.point(lambda v: int(v * 0.6)))

    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), _rounded_mask(S, int(S * 0.225)))

    # 内侧 1px 高光描边，提升立体感
    d = ImageDraw.Draw(img)
    inset = S * 0.012
    d.rounded_rectangle(
        (inset, inset, S - 1 - inset, S - 1 - inset),
        radius=int(S * 0.215),
        outline=(255, 255, 255, 34),
        width=max(1, int(S * 0.006)),
    )
    return img


def _ring_layer() -> Image.Image:
    """青色循环圆弧（带外发光与圆头端点）。"""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c = S / 2
    r = S * RING_R
    w = int(S * RING_W)
    box = (c - r, c - r, c + r, c + r)

    halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(halo).arc(box, RING_A0, RING_A1, fill=ACCENT + (72,), width=int(w * 2.2))
    layer = Image.alpha_composite(layer, halo.filter(ImageFilter.GaussianBlur(S * 0.032)))

    d = ImageDraw.Draw(layer)
    d.arc(box, RING_A0, RING_A1, fill=ACCENT + (255,), width=w)
    for ang in (RING_A0, RING_A1):
        rad = math.radians(ang)
        x, y = c + r * math.cos(rad), c + r * math.sin(rad)
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=ACCENT + (255,))
    return layer


def _glyph_layer() -> Image.Image:
    """白色播放三角（视觉居中，略微右移）。"""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c = S / 2
    left = c - S * TRI_LEFT
    ImageDraw.Draw(layer).polygon(
        [
            (left, c - S * TRI_HALF),
            (left, c + S * TRI_HALF),
            (c + S * TRI_TIP, c),
        ],
        fill=GLYPH + (255,),
    )
    return layer


def build_master() -> Image.Image:
    img = _background()
    img = Image.alpha_composite(img, _ring_layer())
    img = Image.alpha_composite(img, _glyph_layer())
    return img


def main() -> None:
    master = build_master()

    for d in (ASSETS, TAURI_ICONS, PUBLIC):
        d.mkdir(parents=True, exist_ok=True)

    # 主图
    master.resize((512, 512), Image.LANCZOS).save(ASSETS / "AutoGameTool.png")

    # 多尺寸 ICO
    ico_targets = [ASSETS / "AutoGameTool.ico", PUBLIC / "favicon.ico", TAURI_ICONS / "icon.ico"]
    for path in ico_targets:
        master.save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])

    # Tauri 图标集
    png_targets = {
        TAURI_ICONS / "icon.png": 512,
        TAURI_ICONS / "128x128@2x.png": 256,
        TAURI_ICONS / "128x128.png": 128,
        TAURI_ICONS / "32x32.png": 32,
    }
    for path, size in png_targets.items():
        master.resize((size, size), Image.LANCZOS).save(path)

    print("图标已生成：")
    for p in [ASSETS / "AutoGameTool.ico", ASSETS / "AutoGameTool.png", *ico_targets[1:], *png_targets]:
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
