/**
 * 界面外观（浅色 / 深色 / 跟随系统）的纯逻辑。
 *
 * 抽成纯函数是为了能脱离浏览器跑断言（见 tools/test_appearance.ps1）：
 * 这里出错的表现是「选了浅色还是黑的」「跟随系统时系统换了主题界面不跟着变」，
 * 靠肉眼很难覆盖到，而判定逻辑本身只有几行。
 */
export type Appearance = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

/** 设置面板里的选项。跟随系统放第一个：它是默认值。 */
export const APPEARANCE_OPTIONS: { label: string; value: Appearance }[] = [
  { label: '跟随系统', value: 'system' },
  { label: '浅色', value: 'light' },
  { label: '深色', value: 'dark' },
]

export const DEFAULT_APPEARANCE: Appearance = 'system'

/** 任何来路不明的值（旧版本存的、手改 localStorage 的）都收敛成默认值 */
export function normalizeAppearance(value: unknown): Appearance {
  return value === 'light' || value === 'dark' || value === 'system' ? value : DEFAULT_APPEARANCE
}

/**
 * 解析出真正要用的主题。
 * 「跟随系统」时用系统偏好；系统偏好取不到（老浏览器 / 无 matchMedia）时按深色处理
 * ——深色是 AutoTool 一直以来的外观，宁可维持原样也不要突然刷白。
 */
export function resolveTheme(appearance: unknown, systemPrefersDark: boolean | undefined): ResolvedTheme {
  const a = normalizeAppearance(appearance)
  if (a === 'light' || a === 'dark') return a
  return systemPrefersDark === false ? 'light' : 'dark'
}

/** 面板上显示的当前外观说明 */
export function appearanceLabel(appearance: unknown, systemPrefersDark: boolean | undefined): string {
  const a = normalizeAppearance(appearance)
  if (a === 'light') return '浅色'
  if (a === 'dark') return '深色'
  return `跟随系统（当前${resolveTheme(a, systemPrefersDark) === 'dark' ? '深色' : '浅色'}）`
}
