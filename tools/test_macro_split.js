/* 录制拆分算法断言（配合 tools\test_macro_split.ps1 使用）
 *
 * 被测模块是 frontend/src/lib/macroSplit.ts：它是纯函数、不依赖 Vue，
 * 因此可以单独编译出来在 node 里直接跑断言，不必起浏览器或测试框架。
 *
 * 注意：本文件里的中文字符串在 Windows PowerShell 5.1 下需要文件带 BOM 才能正确
 * 传给 node；tools\test_macro_split.ps1 会先把编译产物与断言都交给 node 执行，
 * 控制台若显示乱码不影响 PASS/FAIL 判定（判定基于模块返回值，不基于输出文本）。
 */
const path = require('path')
const {
  compileMacroPieces,
  expandPieces,
  packStepsToMacro,
  canPack,
  splitGridLayout,
  splitGridPositions,
  orderChain,
  COL_PITCH,
  ROW_PITCH,
  CLICK_HOLD_MS,
  KEY_HOLD_MS,
} = require(path.join(__dirname, '.macro_split_build', 'lib', 'macroSplit.js'))

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
function stepsOf(events, speed) {
  return expandPieces(compileMacroPieces(events || [], speed === undefined ? 1.0 : speed))
}
function brief(steps) {
  return steps
    .map(
      (s) =>
        s.stepType +
        (s.params.key ? ':' + s.params.key : '') +
        (s.params.x !== undefined ? ':' + s.params.x + ',' + s.params.y : '')
    )
    .join(' | ')
}

console.log('== 用例1：轨迹 + 左右键点击 + 组合键 + 滚轮 ==')
const s1 = stepsOf([
  { t: 0, type: 'mousemove', x: 10, y: 10 },
  { t: 100, type: 'mousemove', x: 500, y: 400 },
  { t: 200, type: 'mousedown', x: 500, y: 400, button: 'left' },
  { t: 260, type: 'mouseup', x: 500, y: 400, button: 'left' },
  { t: 900, type: 'mousedown', x: 700, y: 300, button: 'right' },
  { t: 960, type: 'mouseup', x: 700, y: 300, button: 'right' },
  { t: 2000, type: 'keydown', key: 'ctrl' },
  { t: 2050, type: 'keydown', key: 'shift' },
  { t: 2100, type: 'keydown', key: 'a' },
  { t: 2200, type: 'keyup', key: 'a' },
  { t: 2250, type: 'keyup', key: 'shift' },
  { t: 2300, type: 'keyup', key: 'ctrl' },
  { t: 3000, type: 'scroll', x: 400, y: 300, dx: 0, dy: -1 },
  { t: 3050, type: 'scroll', x: 400, y: 300, dx: 0, dy: -1 },
])
console.log('  -> ' + brief(s1))
check('没有 mousemove 残留', !s1.some((s) => s.params.type === 'mousemove'))
check(
  '左键点击保留按下坐标 (500,400)',
  s1.some((s) => s.stepType === 'click' && s.params.x === 500 && s.params.y === 400 && s.params.button === 'left')
)
check('右键点击保留 (700,300)', s1.some((s) => s.stepType === 'click' && s.params.button === 'right' && s.params.x === 700))
check('组合键合并为 ctrl+shift+a', s1.some((s) => s.stepType === 'key' && s.params.key === 'ctrl+shift+a'))
check('滚轮合并为一个录制步骤', s1.some((s) => s.stepType === 'macro' && s.params.events.length === 2))
check('点击数量 = 2', s1.filter((s) => s.stepType === 'click').length === 2)
check('插入延时节点保留节奏', s1.some((s) => s.stepType === 'delay' && s.params.ms >= 600))

console.log('== 用例2：长按单键 ==')
const s2 = stepsOf([
  { t: 0, type: 'keydown', key: 'w' },
  { t: 1500, type: 'keyup', key: 'w' },
])
console.log('  -> ' + brief(s2))
check('长按化简为一个 key 节点', s2.filter((s) => s.stepType === 'key').length === 1 && s2[0].params.key === 'w')

console.log('== 用例3：孤立抬起 / 空输入 ==')
check('孤立 mouseup 被忽略', stepsOf([{ t: 0, type: 'mouseup', x: 1, y: 2, button: 'left' }]).length === 0)
check('空事件 -> 空步骤', stepsOf([]).length === 0)
check('mousemove 单独存在 -> 空步骤', stepsOf([{ t: 0, type: 'mousemove', x: 1, y: 2 }]).length === 0)

console.log('== 用例4：连续单键（无组合）==')
const s4 = stepsOf([
  { t: 0, type: 'keydown', key: 'a' },
  { t: 50, type: 'keyup', key: 'a' },
  { t: 400, type: 'keydown', key: 'b' },
  { t: 450, type: 'keyup', key: 'b' },
])
console.log('  -> ' + brief(s4))
check('两个独立按键', s4.filter((s) => s.stepType === 'key').length === 2)
check('第二键前有延时', s4.some((s) => s.stepType === 'delay'))

console.log('== 用例5：同一个 ctrl 连续配两个键（ctrl+a、ctrl+b）==')
const s5 = stepsOf([
  { t: 0, type: 'keydown', key: 'ctrl' },
  { t: 40, type: 'keydown', key: 'a' },
  { t: 80, type: 'keyup', key: 'a' },
  { t: 200, type: 'keydown', key: 'b' },
  { t: 240, type: 'keyup', key: 'b' },
  { t: 280, type: 'keyup', key: 'ctrl' },
])
console.log('  -> ' + brief(s5))
const keys5 = s5.filter((s) => s.stepType === 'key').map((s) => s.params.key)
check(
  '拆成 ctrl+a 与 ctrl+b 两个节点',
  keys5.length === 2 && keys5[0] === 'ctrl+a' && keys5[1] === 'ctrl+b',
  JSON.stringify(keys5)
)

console.log('== 用例6：组合键按住不放时录制结束 ==')
const s6 = stepsOf([
  { t: 0, type: 'keydown', key: 'alt' },
  { t: 30, type: 'keydown', key: 'f4' },
])
console.log('  -> ' + brief(s6))
check('收尾结算 alt+f4', s6.some((s) => s.stepType === 'key' && s.params.key === 'alt+f4'))

// ---------------------------------------------------------------------------
// 打包（拆分的逆操作）
// ---------------------------------------------------------------------------
console.log('== 用例7：打包 点击 + 延时 + 按键 ==')
const packIn = [
  { stepType: 'click', params: { x: 500, y: 400, button: 'left', clicks: 1 } },
  { stepType: 'delay', params: { ms: 600 } },
  { stepType: 'key', params: { key: 'ctrl+shift+a' } },
]
const p7 = packStepsToMacro(packIn)
check('打包成功', p7.ok, JSON.stringify(p7.badTypes))
check(
  '事件类型序列 = mousedown,mouseup,keydown*3,keyup*3',
  JSON.stringify(p7.events.map((e) => e.type)) ===
    JSON.stringify([
      'mousedown',
      'mouseup',
      'keydown',
      'keydown',
      'keydown',
      'keyup',
      'keyup',
      'keyup',
    ]),
  JSON.stringify(p7.events.map((e) => e.type))
)
check(
  '点击坐标保留 (500,400)',
  p7.events[0].x === 500 && p7.events[0].y === 400 && p7.events[0].button === 'left'
)
check(
  `按下→抬起间隔 = ${CLICK_HOLD_MS}ms`,
  p7.events[1].t - p7.events[0].t === CLICK_HOLD_MS
)
check(
  '组合键按顺序按下、逆序抬起',
  JSON.stringify(p7.events.filter((e) => e.type === 'keydown').map((e) => e.key)) ===
    JSON.stringify(['ctrl', 'shift', 'a']) &&
    JSON.stringify(p7.events.filter((e) => e.type === 'keyup').map((e) => e.key)) ===
      JSON.stringify(['a', 'shift', 'ctrl'])
)
check(
  '延时体现在时间轴：组合键起点 = 点击耗时 + 600',
  p7.events[2].t === CLICK_HOLD_MS + 600,
  String(p7.events[2].t)
)

console.log('== 用例8：打包 → 再拆分，往返应等价 ==')
const back8 = stepsOf(p7.events)
console.log('  -> ' + brief(back8))
check(
  '往返后步骤序列与原始一致',
  JSON.stringify(back8.map((s) => s.stepType)) ===
    JSON.stringify(['click', 'delay', 'key']),
  JSON.stringify(back8.map((s) => s.stepType))
)
check(
  '往返后延时长度不变（600ms）',
  back8[1].stepType === 'delay' && back8[1].params.ms === 600,
  JSON.stringify(back8[1] && back8[1].params)
)
check(
  '往返后点击坐标不变',
  back8[0].params.x === 500 && back8[0].params.y === 400
)
check(
  '往返后组合键不变 (ctrl+shift+a)',
  back8[2].params.key === 'ctrl+shift+a',
  String(back8[2].params.key)
)

console.log('== 用例9：打包嵌套录制（内层 2x 变速）==')
const p9 = packStepsToMacro([
  { stepType: 'click', params: { x: 1, y: 2, button: 'left', clicks: 1 } },
  {
    stepType: 'macro',
    params: {
      speed: 2,
      events: [
        { t: 0, type: 'keydown', key: 'a' },
        { t: 200, type: 'keyup', key: 'a' },
      ],
    },
  },
])
check('嵌套录制可打包', p9.ok, JSON.stringify(p9.badTypes))
const inner = p9.events.filter((e) => e.key === 'a')
check(
  '内层 200ms 按 2x 折算成 100ms 真实时间',
  inner.length === 2 && inner[1].t - inner[0].t === 100,
  JSON.stringify(inner.map((e) => e.t))
)
check(
  '内层事件整体平移（起点 = 点击耗时）',
  inner[0].t === CLICK_HOLD_MS,
  String(inner[0] && inner[0].t)
)

console.log('== 用例10：不可打包的步骤整体拒绝 ==')
const p10 = packStepsToMacro([
  { stepType: 'click', params: { x: 1, y: 2, button: 'left', clicks: 1 } },
  { stepType: 'find_image', params: { template: 'x' } },
  { stepType: 'terminate', params: {} },
])
check('返回 ok=false 而不是部分打包', p10.ok === false)
check('未产生任何事件', p10.events.length === 0)
check(
  '报出全部不可打包类型（去重）',
  JSON.stringify(p10.badTypes.slice().sort()) === JSON.stringify(['find_image', 'terminate']),
  JSON.stringify(p10.badTypes)
)
check('canPack：可/不可判定正确', canPack('click') && canPack('key') && canPack('delay') && canPack('macro') && !canPack('judge') && !canPack('text'))

console.log('== 用例11：双击打包成两组按下/抬起 ==')
const p11 = packStepsToMacro([
  { stepType: 'click', params: { x: 9, y: 9, button: 'left', clicks: 2 } },
])
check(
  'clicks=2 → mousedown,mouseup,mousedown,mouseup',
  JSON.stringify(p11.events.map((e) => e.type)) ===
    JSON.stringify(['mousedown', 'mouseup', 'mousedown', 'mouseup']),
  JSON.stringify(p11.events.map((e) => e.type))
)

console.log('== 用例12：拆分后的蛇形网格布局 ==')
// 视口高度 520 → 每列最多 6 行（(520-40)/78 = 6.15）
const L12 = splitGridLayout(12, 520)
console.log(`  12 步 -> ${L12.cols} 列 × ${L12.rows} 行`)
check('12 步不再是一条长竖线（列数 > 1）', L12.cols > 1, `cols=${L12.cols}`)
check('列数为奇数（出口方向朝下）', L12.cols % 2 === 1, `cols=${L12.cols}`)
check('总行高不超出视口太多', L12.rows * ROW_PITCH <= 520 + ROW_PITCH, `${L12.rows * ROW_PITCH}px`)

const pos12 = splitGridPositions(12, 520)
check('12 个位置互不重叠', new Set(pos12.map((p) => p.x + ',' + p.y)).size === 12)
check('横向铺开而不是一直向下', Math.max(...pos12.map((p) => p.x)) === (L12.cols - 1) * COL_PITCH)
check(
  '最高点就是每列的行数（不再单列堆 12 行）',
  Math.max(...pos12.map((p) => p.y)) === (L12.rows - 1) * ROW_PITCH,
  String(Math.max(...pos12.map((p) => p.y)))
)

// 关键：相邻两步必须"挨着"——同列上下相邻，或换列时同一行相邻（不会有长对角线）
let adjacent = true
const badPair = []
for (let i = 0; i + 1 < pos12.length; i++) {
  const a = pos12[i]
  const b = pos12[i + 1]
  const dx = Math.abs(a.x - b.x)
  const dy = Math.abs(a.y - b.y)
  const sameCol = dx === 0 && dy === ROW_PITCH
  const sameRow = dy === 0 && dx === COL_PITCH
  if (!sameCol && !sameRow) {
    adjacent = false
    badPair.push(`${i}->${i + 1}: dx=${dx} dy=${dy}`)
  }
}
check('相邻步骤首尾相接（无长对角线）', adjacent, badPair.join('; '))

console.log('== 用例13：小批量拆分仍保持单列 ==')
const L5 = splitGridLayout(5, 520)
const pos5 = splitGridPositions(5, 520)
console.log(`  5 步 -> ${L5.cols} 列 × ${L5.rows} 行`)
check('5 步 = 单列 5 行', L5.cols === 1 && L5.rows === 5)
check('单列时 x 全部相同、y 依次递增', pos5.every((p, i) => p.x === 0 && p.y === i * ROW_PITCH))

console.log('== 用例14：极端数量也不会退化成一条线 ==')
const L40 = splitGridLayout(40, 520)
console.log(`  40 步 -> ${L40.cols} 列 × ${L40.rows} 行`)
check('40 步铺成多列', L40.cols > 1 && L40.rows * L40.cols >= 40, JSON.stringify(L40))
const pos40 = splitGridPositions(40, 520)
check('40 个位置互不重叠', new Set(pos40.map((p) => p.x + ',' + p.y)).size === 40)
check('1 步也不出错', splitGridPositions(1, 520).length === 1 && splitGridLayout(1, 520).cols === 1)

console.log('== 用例15：选中的多个步骤能否排成一条链 ==')
const N = (id) => ({ id })
const E = (s, t) => ({ source: s, target: t })
check(
  'A→B→C 全选 → 按连线顺序返回',
  JSON.stringify((orderChain([N('c'), N('a'), N('b')], [E('a', 'b'), E('b', 'c')]) || []).map((n) => n.id)) ===
    JSON.stringify(['a', 'b', 'c'])
)
check(
  '隔着没选的节点（选 A、C）→ 拒绝',
  orderChain([N('a'), N('c')], [E('a', 'b'), E('b', 'c')]) === null
)
check('成环 → 拒绝', orderChain([N('a'), N('b')], [E('a', 'b'), E('b', 'a')]) === null)
check(
  '有分支（判断节点两条出边）→ 拒绝',
  orderChain([N('j'), N('x'), N('y')], [E('j', 'x'), E('j', 'y')]) === null
)
check(
  '选了两条互不相连的链 → 拒绝',
  orderChain([N('a'), N('b'), N('x'), N('y')], [E('a', 'b'), E('x', 'y')]) === null
)
check('只选 1 个 → 拒绝', orderChain([N('a')], []) === null)
check(
  '选中顺序颠倒也能排出正序',
  JSON.stringify((orderChain([N('b'), N('a')], [E('a', 'b')]) || []).map((n) => n.id)) ===
    JSON.stringify(['a', 'b'])
)

console.log('')
console.log('结果: PASS=' + pass + '  FAIL=' + fail)
process.exit(fail === 0 ? 0 : 1)
