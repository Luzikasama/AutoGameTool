/* 背景「按屏幕比例截取」几何断言（配合 tools\test_bg_crop.ps1 使用）
 *
 * 被测模块是 frontend/src/lib/bgCrop.ts：纯函数、不依赖 DOM，
 * 所以能脱离浏览器直接验证"取景框里看到的"和"导出到 canvas 的那块"是否一致。
 * 这类几何错误靠肉眼看截图很难发现（差几个像素看不出来），必须靠断言。
 */
const path = require('path')
// 注意：bgCrop.ts 没有任何 import，tsc 推断出的 rootDir 就是它自己所在目录，
// 所以编译产物是 <outDir>/bgCrop.js（macroSplit.ts 因为 import 了 ../types，
// 公共根目录变成 src/，产物才会落在 <outDir>/lib/ 下）。
const { clampPan, coverScale, displaySize, drawRect, outputSize } = require(
  path.join(__dirname, '.bg_crop_build', 'bgCrop.js')
)

let pass = 0
let fail = 0
function check(name, cond, extra) {
  if (cond) {
    pass++
    console.log('  PASS  ' + name)
  } else {
    fail++
    console.log('  FAIL  ' + name + (extra ? '  -> ' + extra : ''))
  }
}

const EPS = 1e-6
// 常见屏幕比例 × 常见图片比例，覆盖"图比框宽/高/同比例"三种情形
const frames = [
  { w: 1600, h: 900 },   // 16:9
  { w: 1280, h: 1024 },  // 5:4
  { w: 2560, h: 1080 },  // 21:9 带鱼屏
  { w: 1080, h: 1920 },  // 竖屏
]
const images = [
  { w: 4000, h: 3000 },  // 4:3
  { w: 1920, h: 1080 },  // 16:9
  { w: 800, h: 1200 },   // 竖图
  { w: 500, h: 500 },    // 方图
]
const zooms = [1, 1.5, 3]
// 包含远超范围的平移量：必须被夹住而不是露出空白
const pans = [
  { x: 0, y: 0 },
  { x: 5000, y: -5000 },
  { x: -37, y: 91 },
]

console.log('== 用例1：cover 缩放保证图片至少铺满取景框 ==')
{
  const f = { w: 1600, h: 900 }
  const i = { w: 800, h: 800 }
  const s = coverScale(f, i)
  check('方图放进宽屏框按高度铺满 (s=2)', Math.abs(s - 2) < EPS, s)
  const d = displaySize(f, i, 1)
  check('显示宽度也 >= 框宽', d.w >= f.w - EPS && d.h >= f.h - EPS, JSON.stringify(d))
}

console.log('== 用例2：任何比例/缩放/平移下，绘制矩形都必须完全覆盖取景框 ==')
{
  let bad = null
  for (const f of frames) {
    for (const i of images) {
      for (const z of zooms) {
        for (const p of pans) {
          const r = drawRect(f, i, z, p)
          const covers = r.x <= EPS && r.y <= EPS && r.x + r.w >= f.w - EPS && r.y + r.h >= f.h - EPS
          if (!covers && !bad) bad = { f, i, z, p, r }
        }
      }
    }
  }
  check('全部组合都无空白边', !bad, bad && JSON.stringify(bad))
}

console.log('== 用例3：平移被夹住后，图片边缘正好贴住框边（不多不少） ==')
{
  const f = { w: 1600, h: 900 }
  // cover 的贴合方向规则：图片比框"更窄"时按宽度贴合（横向无空间、纵向溢出），反之亦然。
  // (a) 方图(1:1) 比 16:9 的框更窄 -> 横向贴合
  const sq = { w: 800, h: 800 }
  const limA = clampPan(f, sq, 1, { x: 999999, y: 999999 })
  check('(a) 横向无可平移空间', Math.abs(limA.x) < EPS, limA.x)
  check('(a) 纵向富余 = (1600-900)/2 = 350', Math.abs(limA.y - 350) < EPS, limA.y)
  const rA = drawRect(f, sq, 1, { x: 999999, y: 999999 })
  check('(a) 夹住后上边缘正好贴住框顶 (y=0)', Math.abs(rA.y) < 1e-9, rA.y)
  check('(a) 宽度正好等于框宽', Math.abs(rA.w - f.w) < EPS, rA.w)

  // (b) 超宽图(4:1) 比框更宽 -> 按高度贴合
  const wide = { w: 4000, h: 1000 }
  const limB = clampPan(f, wide, 1, { x: 999999, y: 999999 })
  check('(b) 纵向无可平移空间', Math.abs(limB.y) < EPS, limB.y)
  check('(b) 横向富余 = (3600-1600)/2 = 1000', Math.abs(limB.x - 1000) < EPS, limB.x)
  const rB = drawRect(f, wide, 1, { x: 999999, y: 999999 })
  check('(b) 夹住后左边缘正好贴住框左 (x=0)', Math.abs(rB.x) < 1e-9, rB.x)
  check('(b) 高度正好等于框高', Math.abs(rB.h - f.h) < EPS, rB.h)
}

console.log('== 用例4：zoom=1 时至少一个方向正好等于框尺寸（cover 的紧致性） ==')
{
  let bad = null
  for (const f of frames) {
    for (const i of images) {
      const d = displaySize(f, i, 1)
      const tight =
        Math.abs(d.w - f.w) < 1e-6 || Math.abs(d.h - f.h) < 1e-6
      // 允许浮点误差：宽度或高度之一应当刚好贴合
      if (!tight) {
        const okW = Math.abs(d.w - f.w) < 1e-6
        const okH = Math.abs(d.h - f.h) < 1e-6
        if (!okW && !okH && !bad) bad = { f, i, d }
      }
    }
  }
  check('每个组合都有一边刚好贴合', !bad, bad && JSON.stringify(bad))
}

console.log('== 用例5：等比缩放不变性（框放大一倍，相对取景结果不变） ==')
{
  const i = { w: 3000, h: 2000 }
  const a = drawRect({ w: 800, h: 450 }, i, 1.4, { x: 100, y: -50 })
  const b = drawRect({ w: 1600, h: 900 }, i, 1.4, { x: 200, y: -100 })
  const same = (p, q) => Math.abs(p - q) < 1e-6
  check(
    '位置与尺寸都等比',
    same(a.x * 2, b.x) && same(a.y * 2, b.y) && same(a.w * 2, b.w) && same(a.h * 2, b.h),
    JSON.stringify({ a, b })
  )
  // 取景区域占原图的比例（决定实际裁到哪一块）也必须一致
  const fracA = a.w / a.h
  const fracB = b.w / b.h
  check('宽高比一致', same(fracA, fracB), `${fracA} vs ${fracB}`)
}

console.log('== 用例6：导出分辨率限制 ==')
{
  const big = outputSize({ w: 1600, h: 900 }, 2)
  check('DPR=2 的 1600x900 输出 1920x1080', big.w === 1920 && big.h === 1080, JSON.stringify(big))
  check('总像素不超过上限', big.w * big.h <= 1920 * 1080, JSON.stringify(big))
  const wide = outputSize({ w: 2560, h: 1080 }, 2)
  check('带鱼屏也被压到上限内', wide.w * wide.h <= 1920 * 1080, JSON.stringify(wide))
  check('带鱼屏比例保持', Math.abs(wide.w / wide.h - 2560 / 1080) < 0.02, JSON.stringify(wide))
  const small = outputSize({ w: 1280, h: 720 }, 1)
  check('小窗口不放大', small.w === 1280 && small.h === 720, JSON.stringify(small))
  const degenerate = outputSize({ w: 0, h: 0 }, 1)
  check('退化输入不产生 0 尺寸', degenerate.w >= 1 && degenerate.h >= 1, JSON.stringify(degenerate))
}

console.log('== 用例7：异常输入不产生 NaN（保证界面不会崩） ==')
{
  const r1 = drawRect({ w: 800, h: 450 }, { w: 0, h: 0 }, 1, { x: 0, y: 0 })
  check('图片尺寸为 0 时无 NaN', Number.isFinite(r1.w) && Number.isFinite(r1.x), JSON.stringify(r1))
  const r2 = clampPan({ w: 800, h: 450 }, { w: 100, h: 100 }, 1, { x: NaN, y: NaN })
  check('平移为 NaN 时归零', r2.x === 0 && r2.y === 0, JSON.stringify(r2))
  const r3 = displaySize({ w: 800, h: 450 }, { w: 100, h: 100 }, 0)
  check('zoom=0 不产生 0 尺寸', r3.w > 0 && r3.h > 0, JSON.stringify(r3))
}

console.log('')
console.log('结果: PASS=' + pass + '  FAIL=' + fail)
process.exit(fail === 0 ? 0 : 1)
