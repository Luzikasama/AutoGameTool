/* 静态检查：每个 .vue 里用到的 <n-xxx> 组件，是否都在该文件里 import 了。
 *
 * 为什么需要（真实事故，v0.7.1 修复）：
 *   Editor.vue 用了 <n-popconfirm> 但忘了 import NPopconfirm。Vue 把无法解析的
 *   组件当成未知元素渲染，**具名插槽里的内容会被整个丢掉**——于是那个按钮在界面上
 *   根本不存在。而 vue-tsc 只检查类型、vite build 只做打包，两者都不会报错：
 *   功能"消失"得悄无声息。只有截图/肉眼才能发现，所以必须用静态检查兜住。
 *
 * 用法：node tools/check_ui_imports.mjs [frontend/src]
 * 退出码：0 = 全部有导入；1 = 有缺失
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = process.argv[2] || 'frontend/src'

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}

/** n-input-number -> NInputNumber */
function pascal(tag) {
  return (
    'N' +
    tag
      .slice(2)
      .split('-')
      .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
      .join('')
  )
}

let bad = 0
let files = 0
for (const file of walk(root)) {
  const text = readFileSync(file, 'utf8')
  const tags = [...new Set([...text.matchAll(/<(n-[a-z0-9-]+)/g)].map((m) => m[1]))]
  if (tags.length === 0) continue
  files++
  const imp = (text.match(/import\s*\{[^}]*\}\s*from\s*'naive-ui'/) || [''])[0]
  const missing = tags.filter((t) => !imp.includes(pascal(t)))
  if (missing.length) {
    bad++
    const rel = relative(process.cwd(), file)
    console.log(`缺少导入  ${rel}`)
    for (const t of missing) console.log(`    <${t}> 需要 import { ${pascal(t)} } from 'naive-ui'`)
  }
}

console.log(`检查了 ${files} 个含 Naive UI 组件的 .vue 文件，缺失 ${bad} 个`)
process.exit(bad === 0 ? 0 : 1)
