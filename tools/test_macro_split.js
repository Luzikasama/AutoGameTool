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
const { compileMacroPieces, expandPieces } = require(
  path.join(__dirname, '.macro_split_build', 'lib', 'macroSplit.js')
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

console.log('')
console.log('结果: PASS=' + pass + '  FAIL=' + fail)
process.exit(fail === 0 ? 0 : 1)
