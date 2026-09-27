/**
 * 外观（浅色 / 深色 / 跟随系统）判定逻辑的断言。
 * 被测源码：frontend/src/lib/appearance.ts（纯函数，编译后由 node 执行）
 */
const A = require('./.appearance_build/appearance.js')

let pass = 0
let fail = 0

function check(name, cond, extra = '') {
  if (cond) {
    pass++
    console.log('  PASS  ' + name)
  } else {
    fail++
    console.log('  FAIL  ' + name + (extra !== '' ? '  -> ' + JSON.stringify(extra) : ''))
  }
}

console.log('== 用例1：非法/历史值一律收敛到默认值（跟随系统） ==')
for (const v of [undefined, null, '', 'Light', 'DARK', 'auto', 'system ', 0, 1, {}, []]) {
  check('normalizeAppearance(' + JSON.stringify(v) + ') = system', A.normalizeAppearance(v) === 'system',
    A.normalizeAppearance(v))
}
check('默认值就是「跟随系统」', A.DEFAULT_APPEARANCE === 'system', A.DEFAULT_APPEARANCE)

console.log('== 用例2：合法值原样保留 ==')
check("'light' 保留", A.normalizeAppearance('light') === 'light')
check("'dark' 保留", A.normalizeAppearance('dark') === 'dark')
check("'system' 保留", A.normalizeAppearance('system') === 'system')

console.log('== 用例3：跟随系统 ==')
check('系统深色 → dark', A.resolveTheme('system', true) === 'dark')
check('系统浅色 → light', A.resolveTheme('system', false) === 'light')
check('取不到系统偏好 → 保持深色（不突然刷白）', A.resolveTheme('system', undefined) === 'dark',
  A.resolveTheme('system', undefined))

console.log('== 用例4：显式选择优先于系统 ==')
check('显式浅色 + 系统深色 → light', A.resolveTheme('light', true) === 'light')
check('显式深色 + 系统浅色 → dark', A.resolveTheme('dark', false) === 'dark')
check('非法值按跟随系统处理', A.resolveTheme('bogus', false) === 'light', A.resolveTheme('bogus', false))

console.log('== 用例5：设置面板的选项表 ==')
check('第一个选项是「跟随系统」（默认值排最前）',
  A.APPEARANCE_OPTIONS[0] && A.APPEARANCE_OPTIONS[0].value === 'system', A.APPEARANCE_OPTIONS[0])
check('三个选项：跟随系统 / 浅色 / 深色',
  A.APPEARANCE_OPTIONS.map((o) => o.value).join(',') === 'system,light,dark',
  A.APPEARANCE_OPTIONS.map((o) => o.value))
check('每个选项都有中文标签',
  A.APPEARANCE_OPTIONS.every((o) => typeof o.label === 'string' && o.label.length > 0))
check('选项值互不重复', new Set(A.APPEARANCE_OPTIONS.map((o) => o.value)).size === 3)

console.log('== 用例6：文案 ==')
check('跟随系统 + 系统深色 → 说明当前是深色',
  A.appearanceLabel('system', true).includes('跟随系统') && A.appearanceLabel('system', true).includes('深色'),
  A.appearanceLabel('system', true))
check('跟随系统 + 系统浅色 → 说明当前是浅色',
  A.appearanceLabel('system', false).includes('浅色'), A.appearanceLabel('system', false))
check('显式浅色时不啰嗦「当前」', A.appearanceLabel('light', true) === '浅色', A.appearanceLabel('light', true))

console.log('')
console.log('结果: PASS=' + pass + '  FAIL=' + fail)
process.exit(fail === 0 ? 0 : 1)
