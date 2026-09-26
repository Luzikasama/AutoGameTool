/**
 * 自定义背景的「按屏幕比例截取」几何计算。
 *
 * 单独抽成纯函数的原因：这段是「所见即所得」的关键——界面里显示的取景结果
 * 和导出到 canvas 的裁剪区域必须由**同一组参数**算出来。写成两份（一份给 CSS
 * transform、一份给 drawImage）迟早会漂移，而且漂移了很难用肉眼发现。
 *
 * 坐标约定：取景框坐标系，原点在框左上角，单位是 CSS 像素。
 *   1. cover 基准缩放 s0 = max(fw/iw, fh/ih) —— 保证图片至少铺满整个框
 *   2. 用户缩放 z（>=1，只放大不缩小，免得露出空白）
 *   3. 显示尺寸 d = i × s0 × z；居中后再平移 (tx, ty)，平移量被夹在 ±(d-f)/2 内
 *   4. 于是绘制矩形 x = (fw - dw)/2 + tx, y = (fh - dh)/2 + ty
 */

export interface Frame {
  w: number
  h: number
}

export interface ImageSize {
  w: number
  h: number
}

export interface Pan {
  x: number
  y: number
}

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

/** cover 基准缩放：让图片至少铺满取景框 */
export function coverScale(f: Frame, i: ImageSize): number {
  if (!f.w || !f.h || !i.w || !i.h) return 1
  return Math.max(f.w / i.w, f.h / i.h)
}

/** 应用用户缩放后的显示尺寸 */
export function displaySize(f: Frame, i: ImageSize, zoom: number): { w: number; h: number } {
  const s = coverScale(f, i) * Math.max(0.01, Number(zoom) || 1)
  return { w: i.w * s, h: i.h * s }
}

/** 平移上限（各方向），保证图片边缘不会缩进框内露出空白 */
export function panLimit(f: Frame, i: ImageSize, zoom: number): Pan {
  const d = displaySize(f, i, zoom)
  return { x: Math.max(0, (d.w - f.w) / 2), y: Math.max(0, (d.h - f.h) / 2) }
}

/** 把平移量夹到合法范围 */
export function clampPan(f: Frame, i: ImageSize, zoom: number, p: Pan): Pan {
  const lim = panLimit(f, i, zoom)
  const x = Number.isFinite(p?.x) ? p.x : 0
  const y = Number.isFinite(p?.y) ? p.y : 0
  return {
    x: Math.min(lim.x, Math.max(-lim.x, x)),
    y: Math.min(lim.y, Math.max(-lim.y, y)),
  }
}

/** 图片在取景框里的绘制矩形：DOM 定位与 canvas 导出共用这一份 */
export function drawRect(f: Frame, i: ImageSize, zoom: number, p: Pan): Rect {
  const d = displaySize(f, i, zoom)
  const c = clampPan(f, i, zoom, p)
  return { x: (f.w - d.w) / 2 + c.x, y: (f.h - d.h) / 2 + c.y, w: d.w, h: d.h }
}

/**
 * 导出分辨率：跟随屏幕 DPR，但限制总像素。
 * 背景图是以 base64 存进 localStorage 的（上限约 5MB），不设上限很容易存不下。
 */
export function outputSize(
  f: Frame,
  dpr: number,
  maxPixels = 1920 * 1080,
  maxWidth = 1920,
): { w: number; h: number } {
  const ar = f.w > 0 && f.h > 0 ? f.w / f.h : 16 / 9
  let w = Math.max(1, Math.min(maxWidth, Math.round(f.w * (Number(dpr) || 1))))
  let h = Math.max(1, Math.round(w / ar))
  if (w * h > maxPixels) {
    const k = Math.sqrt(maxPixels / (w * h))
    w = Math.max(1, Math.round(w * k))
    h = Math.max(1, Math.round(h * k))
  }
  return { w, h }
}
