/**
 * 老脚本 → 0.1.3 节点体系的**就地升级**。
 *
 * 0.1.3 把「步骤」改名成「节点」，类型从 10 个扩到 25 个。为了让 0.1.2 及更早
 * 保存的 .agflow 还能正常打开，加载时统一走这里升级。要处理三类差异：
 *
 *  1. **字段改名**：画布节点的 `data.stepType` → `data.nodeType`
 *  2. **类型改名 / 参数变形**：click→mouse、key→keyboard、text→text_input、macro→record…
 *     （见 types.ts 的 LEGACY_TYPE_MAP + 下面的 upgradeParams）
 *  3. **类型拆开**（用户明确要求按规范拆开的两处）：
 *     - 老的「找图」（find_image）：只做识别。若它当年带 `click` / `on_timeout=exit`，
 *       现在按规范摊成  图像识别 → 判断 →（是）鼠标点击 → 继续
 *                                          └（否）终止
 *     - 老的「判断」（judge，当年语义是"找图 + 分支"）：
 *       拆成 图像识别 → 判断（条件 found == yes），后继连线原样保留在判断上
 *
 * 设计原则：**升级是幂等的**，且不丢用户填过的任何值。
 *  - 判断"是不是老节点"看的是**类型名**（mouse/ocr/… 这些新名字绝不会被再升级一次）
 *  - 参数升级一律"老值优先、缺的补默认"，不认识的键原样留着
 *  - 节点 id 尽量复用（被插入的新节点才用新 id），这样外部引用的 id 不会失效
 */
import { LEGACY_TYPE_MAP, NODE_META, type NodeType } from '../types'
import { mergeWithDefaults } from './nodeSchema'

const COL_PITCH_FALLBACK = 212

/** 升级结果（notes 非空时值得给用户看一眼） */
export interface MigrateResult {
  nodes: any[]
  edges: any[]
  notes: string[]
}

/** 老节点类型 → 新节点参数：把老字段翻译成新字段（老的键保留，不删） */
function upgradeParams(oldType: string, newType: NodeType, old: Record<string, any>): Record<string, any> {
  const p: Record<string, any> = { ...(old || {}) }

  if (oldType === 'click' && newType === 'mouse') {
    // 老的 click 只有单击 + clicks 次数；双击仍用 click + clicks=2 表达
    if (p.action === undefined) p.action = 'click'
    if (p.button === undefined) p.button = 'left'
  }
  if (oldType === 'key' && newType === 'keyboard') {
    if (p.action === undefined) p.action = 'press'
    if (p.keys === undefined && p.key !== undefined) p.keys = p.key
  }
  if (oldType === 'text' && newType === 'text_input') {
    if (p.method === undefined) p.method = 'direct'
  }
  if (oldType === 'macro' && newType === 'record') {
    if (p.speed === undefined) p.speed = 1
  }
  if (newType === 'terminate') {
    // 老的 terminate 语义就是"停掉整次运行"
    if (p.level === undefined) p.level = 'workflow'
  }
  if (newType === 'find_image') {
    // 老找图的 click / on_timeout 已由拆图处理；这里只补输出变量名
    if (p.save_found === undefined) p.save_found = 'found'
    if (p.save_x === undefined) p.save_x = 'found_x'
    if (p.save_y === undefined) p.save_y = 'found_y'
    if (p.save_score === undefined) p.save_score = 'found_score'
  }

  return mergeWithDefaults(newType, p)
}

/** 生成一个在 sets 里不冲突的新 id */
function freshId(prefix: string, used: Set<string>): string {
  let n = 1
  let id = `${prefix}-m${n}`
  while (used.has(id)) {
    n += 1
    id = `${prefix}-m${n}`
  }
  used.add(id)
  return id
}

/** 读出一个节点当前（老或新）的类型名 */
function readType(node: any): string {
  const data = node?.data
  if (data && typeof data === 'object') {
    return String(data.nodeType ?? data.stepType ?? node.type ?? '')
  }
  return String(node?.type ?? '')
}

/** 写回类型名（画布节点写 data.nodeType；扁平节点写 type） */
function writeType(node: any, t: NodeType): void {
  if (node?.data && typeof node.data === 'object') {
    node.data.nodeType = t
    node.data.label = NODE_META[t]?.label || String(t)
    delete node.data.stepType
  } else {
    node.type = t
  }
}

function readParams(node: any): Record<string, any> {
  const data = node?.data
  if (data && typeof data === 'object') return (data.params as Record<string, any>) || {}
  return (node?.params as Record<string, any>) || {}
}

function writeParams(node: any, params: Record<string, any>): void {
  if (node?.data && typeof node.data === 'object') node.data.params = params
  else node.params = params
}

/** 建一个画布节点（带位置）；扁平输入时位置字段忽略 */
function mkNode(id: string, t: NodeType, params: Record<string, any>, pos: { x: number; y: number }): any {
  return {
    id,
    type: 'step',
    position: { ...pos },
    data: { nodeType: t, label: NODE_META[t]?.label || t, params, once: false },
  }
}

/** 升级整张图（根脚本或某个子脚本），幂等。 */
export function migrateFlow(nodesIn: any[] | undefined, edgesIn: any[] | undefined): MigrateResult {
  const notes: string[] = []
  const nodes: any[] = Array.isArray(nodesIn) ? nodesIn.map((n) => ({ ...n })) : []
  const edges: any[] = Array.isArray(edgesIn) ? edgesIn.map((e) => ({ ...e })) : []

  const used = new Set<string>(nodes.map((n) => String(n?.id ?? '')).filter(Boolean))
  const out: any[] = []

  for (const node of nodes) {
    const data = node?.data
    const oldType = readType(node)
    const params = readParams(node)
    const pos = {
      x: Number(node?.position?.x ?? 0) || 0,
      y: Number(node?.position?.y ?? 0) || 0,
    }

    // ---- 情况 A：老的「判断」（找图 + 分支）→ 图像识别 + 判断 ----
    if (oldType === 'judge' && (params.template !== undefined || params.threshold !== undefined)) {
      // 原来的判断节点**位置不动**、id 不动，改成新的「判断」——
      // 这样所有出边（yes/no 分支）自动继续指向它，不用改。
      const fiId = freshId(`${node.id}-find`, used)
      const fi = mkNode(
        fiId,
        'find_image',
        upgradeParams('find_image', 'find_image', {
          template: params.template,
          threshold: params.threshold,
          timeout_ms: params.timeout_ms,
        }),
        { x: pos.x - COL_PITCH_FALLBACK, y: pos.y },
      )
      // 入边改指到找图节点
      for (const e of edges) if (e.target === node.id) e.target = fiId
      edges.push({ id: `e-${fiId}-${node.id}`, source: fiId, target: node.id })

      writeType(node, 'judge')
      writeParams(node, {
        logic: 'and',
        condition: { left: params.save_found || 'found', op: '==', right: 'yes' },
        condition2: { left: '', op: '==', right: '' },
      })
      out.push(fi, node)
      notes.push('「找图判断」节点已按新规范拆成「图像识别 → 判断」两个节点')
      continue
    }

    // ---- 情况 B：老的「找图」带 click / on_timeout=exit → 图像识别 +（判断 → 点击 / 终止）----
    if (oldType === 'find_image') {
      const wantClick = params.click === true
      const wantExit = params.on_timeout === 'exit'
      writeType(node, 'find_image')
      writeParams(node, upgradeParams('find_image', 'find_image', params))
      out.push(node)
      if (!wantClick && !wantExit) continue

      const jdId = freshId(`${node.id}-judge`, used)
      const jd = mkNode(
        jdId,
        'judge',
        {
          logic: 'and',
          condition: { left: params.save_found || 'found', op: '==', right: 'yes' },
          condition2: { left: '', op: '==', right: '' },
        },
        { x: pos.x + COL_PITCH_FALLBACK, y: pos.y },
      )
      // 找图原来的出边 → 改从判断的「是」出口出去
      for (const e of edges) {
        if (e.source === node.id) {
          e.source = jdId
          if (e.sourceHandle === undefined || e.sourceHandle === null) e.sourceHandle = 'yes'
        }
      }
      edges.push({ id: `e-${node.id}-${jdId}`, source: node.id, target: jdId })
      out.push(jd)

      const branchBits: string[] = []
      if (wantClick) {
        const msId = freshId(`${node.id}-click`, used)
        const ms = mkNode(
          msId,
          'mouse',
          { action: 'click', x: '{{found_x}}', y: '{{found_y}}', button: 'left', clicks: 1 },
          { x: pos.x + COL_PITCH_FALLBACK * 2, y: pos.y },
        )
        // 「是」分支：判断 → 点击 → 原来的后继
        for (const e of edges) {
          if (e.source === jdId && e.sourceHandle === 'yes') {
            e.source = msId
            e.sourceHandle = null
          }
        }
        edges.push({ id: `e-${jdId}-${msId}`, source: jdId, target: msId, sourceHandle: 'yes' })
        out.push(ms)
        branchBits.push('找到后自动点击')
      }
      if (wantExit) {
        const tmId = freshId(`${node.id}-term`, used)
        const tm = mkNode(
          tmId,
          'terminate',
          { level: 'workflow', message: '未找到图像，按原设置退出' },
          { x: pos.x + COL_PITCH_FALLBACK * 2, y: pos.y + 90 },
        )
        edges.push({ id: `e-${jdId}-${tmId}`, source: jdId, target: tmId, sourceHandle: 'no' })
        out.push(tm)
        branchBits.push('超时未找到则终止')
      }
      notes.push(`「图像识别」的旧行为已展开为多个节点（${branchBits.join('、')}）`)
      continue
    }

    // ---- 情况 C：普通改名 / 参数升级 ----
    const mapped = LEGACY_TYPE_MAP[oldType]
    if (!mapped) {
      // 已经是新类型（或完全不认识的类型）：只补默认参数 + 清掉 stepType
      if (data && typeof data === 'object') {
        delete data.stepType
        if (!data.nodeType && node.type && node.type !== 'step') {
          data.nodeType = node.type
        }
      }
      const t = (data?.nodeType || node.type) as NodeType | undefined
      if (t && NODE_META[t]) writeParams(node, mergeWithDefaults(t, params))
      out.push(node)
      continue
    }
    writeType(node, mapped)
    writeParams(node, upgradeParams(oldType, mapped, params))
    out.push(node)
  }

  return { nodes: out, edges, notes }
}

/** 整份脚本（含子脚本库）的升级；返回新对象与说明。 */
export function migrateScript(data: any): { data: any; notes: string[] } {
  if (!data || typeof data !== 'object') return { data, notes: [] }
  const notes: string[] = []
  const root = migrateFlow(data.nodes, data.edges)
  notes.push(...root.notes)
  const scripts: Record<string, any> = {}
  const raw = data.scripts
  if (raw && typeof raw === 'object') {
    for (const [key, sub] of Object.entries<any>(raw)) {
      if (!sub || typeof sub !== 'object') {
        scripts[key] = sub
        continue
      }
      const r = migrateFlow(sub.nodes, sub.edges)
      notes.push(...r.notes)
      scripts[key] = { ...sub, nodes: r.nodes, edges: r.edges }
    }
  }
  return {
    data: { ...data, nodes: root.nodes, edges: root.edges, scripts },
    notes: Array.from(new Set(notes)),
  }
}
