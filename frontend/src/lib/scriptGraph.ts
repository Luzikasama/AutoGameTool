/**
 * 脚本调用关系图（Script Dependency Graph）——防递归的纯逻辑部分。
 *
 * 这里处理的**不是**单个脚本内部的流程连线（那是 Vue Flow 的事），而是
 * 「脚本 A 调用了脚本 B」这一层关系。把这一层单独建成有向图之后：
 *
 *  - 编辑时：准备加一条 A → B，先问「从 B 出发能不能走回 A」，能走回就拒绝；
 *  - 加载/运行前：整图做一次拓扑判定，无法完成拓扑排序即存在循环；
 *  - 环的报错要能说清完整调用链，面向的是零代码用户。
 *
 * 保持纯函数（不依赖 Vue / DOM），方便单独断言，也便于和引擎侧的实现对照。
 */
import type { SubScript } from '../types'

/** 调用图里代表「根脚本」的虚拟节点。
 *  根脚本不可被调用（没有任何节点能指向它），所以它只会出现在边的起点。 */
export const ROOT_NODE = '__root__'

/** 一段流程里被调用的脚本 id（按出现顺序、去重）。 */
export function collectCalls(flow: { nodes?: any[] } | null | undefined): string[] {
  const out: string[] = []
  for (const n of flow?.nodes || []) {
    if (n?.data?.stepType !== 'script_call' && n?.type !== 'script_call') continue
    const id = String(n?.data?.params?.script_id ?? n?.params?.script_id ?? '').trim()
    if (id && !out.includes(id)) out.push(id)
  }
  return out
}

/** 脚本注册表：id → 子脚本（缺 id 的会被忽略）。 */
export function normalizeScripts(raw: unknown): Record<string, SubScript> {
  const out: Record<string, SubScript> = {}
  if (!raw || typeof raw !== 'object') return out
  for (const [key, value] of Object.entries(raw as Record<string, any>)) {
    const id = String(value?.id || key || '').trim()
    if (!id) continue
    out[id] = {
      id,
      name: String(value?.name || id),
      nodes: Array.isArray(value?.nodes) ? value.nodes : [],
      edges: Array.isArray(value?.edges) ? value.edges : [],
    }
  }
  return out
}

export type Graph = Record<string, string[]>

/**
 * 建图：key = 脚本 id（根用 ROOT_NODE），value = 它直接调用的脚本 id 列表。
 * 只有出现在注册表里的目标才会成为图中的边——指向不存在的脚本不算依赖
 * （那是"脚本缺失"，单独报错，不该被当成环）。
 */
export function buildGraph(
  rootFlow: { nodes?: any[] } | null | undefined,
  scripts: Record<string, SubScript> | null | undefined,
  includeRoot = true,
): Graph {
  const reg = normalizeScripts(scripts)
  const graph: Graph = {}
  if (includeRoot) graph[ROOT_NODE] = []
  for (const id of Object.keys(reg)) graph[id] = []

  const link = (from: string, flow: { nodes?: any[] } | null | undefined) => {
    for (const to of collectCalls(flow)) {
      if (graph[to] !== undefined && !graph[from].includes(to)) graph[from].push(to)
    }
  }
  if (includeRoot) link(ROOT_NODE, rootFlow)
  for (const [id, s] of Object.entries(reg)) link(id, s)
  return graph
}

/** 从 from 出发能否走到 to；能则返回路径 [from, …, to]，不能返回 null。 */
export function findPath(graph: Graph, from: string, to: string): string[] | null {
  if (from === to) return [from]
  const prev = new Map<string, string>()
  const seen = new Set<string>([from])
  const queue = [from]
  while (queue.length) {
    const cur = queue.shift() as string
    for (const next of graph[cur] || []) {
      if (seen.has(next)) continue
      seen.add(next)
      prev.set(next, cur)
      if (next === to) {
        const path = [to]
        let p = cur
        while (p !== from) {
          path.unshift(p)
          p = prev.get(p) as string
        }
        path.unshift(from)
        return path
      }
      queue.push(next)
    }
  }
  return null
}

/**
 * 准备添加一条 `from → to` 的调用关系，判断会不会成环。
 *
 * 成环的充要条件是「从 to 出发已经能回到 from」——那时加上这条边就闭合成环。
 * 返回值是**闭合后的完整环路径**（用于提示用户），不成环则返回 null。
 *
 * 注意不能只判断 `from !== to`：那是"直接递归"这一种情况，
 * `A → B → C → A`、`A → B → C → D → B` 这类间接环必须靠可达性判定。
 */
export function wouldCreateCycle(graph: Graph, from: string, to: string): string[] | null {
  if (!from || !to) return null
  if (from === to) return [from, to]
  const back = findPath(graph, to, from)
  return back ? [from, ...back] : null
}

/** 整图找一条环（找不到返回 null）。加载/运行前的完整性校验用它。 */
export function findAnyCycle(graph: Graph): string[] | null {
  const WHITE = 0
  const GRAY = 1
  const BLACK = 2
  const color = new Map<string, number>()
  for (const k of Object.keys(graph)) color.set(k, WHITE)

  const dfs = (node: string, stack: string[]): string[] | null => {
    color.set(node, GRAY)
    stack.push(node)
    for (const next of graph[node] || []) {
      const c = color.get(next) ?? WHITE
      if (c === GRAY) {
        // next 正在当前递归栈里 → 栈中从 next 到栈顶就是那个环
        const at = stack.indexOf(next)
        return [...stack.slice(at), next]
      }
      if (c === WHITE) {
        const found = dfs(next, stack)
        if (found) return found
      }
    }
    stack.pop()
    color.set(node, BLACK)
    return null
  }

  for (const k of Object.keys(graph)) {
    if ((color.get(k) ?? WHITE) === WHITE) {
      const found = dfs(k, [])
      if (found) return found
    }
  }
  return null
}

/** 把一串脚本 id 写成「A → B → C」，便于直接塞进提示语。 */
export function chainText(ids: string[], nameOf: (id: string) => string): string {
  return ids.map((id) => (id === ROOT_NODE ? '主脚本' : nameOf(id))).join(' → ')
}

/** 顶层结束的调用节点类型名，便于在图上定位出边。 */
export function scriptNameMap(scripts: Record<string, SubScript> | null | undefined): Map<string, string> {
  const map = new Map<string, string>()
  for (const [id, s] of Object.entries(normalizeScripts(scripts))) map.set(id, s.name)
  return map
}
