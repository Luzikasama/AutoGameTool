/**
 * 老脚本 → 当前节点体系的**就地升级**（0.1.3 节点体系 + 0.1.4 变量/输入方式）。
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
 * 0.1.4 又加了两条**语义兼容**升级（都只在 version < 3 时做）：
 *  4. 脚本级的 `input_mode` 分发到各输入节点的 `params.input_mode`
 *     （0.1.4 起设置栏里那个全局单选被去掉了）
 *  5. 子脚本里的「变量」节点标成 `scope: global`。0.1.4 起变量改成层级作用域
 *     （子脚本 / 组合节点的写入默认不回流外层），老脚本原本是全共享，
 *     不显式标一次就会**悄悄改变行为**。
 *
 * 设计原则：**升级是幂等的**，且不丢用户填过的任何值。
 *  - 判断"是不是老节点"看的是**类型名**（mouse/ocr/… 这些新名字绝不会被再升级一次）
 *  - 参数升级一律"老值优先、缺的补默认"，不认识的键原样留着
 *  - 节点 id 尽量复用（被插入的新节点才用新 id），这样外部引用的 id 不会失效
 */
import { GROUP_META, GROUP_TYPE, LEGACY_TYPE_MAP, NODE_META, type NodeType } from '../types'
import { mergeWithDefaults } from './nodeSchema'

const COL_PITCH_FALLBACK = 212

/** 升级结果（notes 非空时值得给用户看一眼） */
export interface MigrateResult {
  nodes: any[]
  edges: any[]
  notes: string[]
}

/**
 * 老节点类型 → 新节点参数：把老字段翻译成新字段（老的键保留，不删）。
 *
 * `legacy`：这份文件是不是 `version < 3` 的老文件。**只有老文件才补输出变量名** ——
 * 0.1.2 的找图节点是"隐式"写 `found / found_x / …` 的，为了不改变老脚本的行为，
 * 升级时必须把变量名补成明文。而 0.1.5 起输出变量是"用户添加了才有"，
 * 新文件里这些键本来就存在（值可能是空串），再补 = 又把"自带变量"塞回去。
 */
function upgradeParams(
  oldType: string,
  newType: NodeType,
  old: Record<string, any>,
  legacy = false,
): Record<string, any> {
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
  if (legacy && newType === 'find_image') {
    // 老找图的 click / on_timeout 已由拆图处理；这里只补输出变量名
    // （0.1.2 的找图是隐式写这几个变量的，不补成明文老脚本就断了）
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
export function migrateFlow(
  nodesIn: any[] | undefined,
  edgesIn: any[] | undefined,
  legacy = false,
): MigrateResult {
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

    // ---- 情况 A0：组合节点（0.1.4 新增）→ 递归升级它内部那张图 ----
    // 组合节点自己没有"改名"的问题，但内部节点可能还是老类型（
    // 比如把一个老文件里的节点合并后再读回来），所以要钻进去。
    if (oldType === GROUP_TYPE) {
      const gp = { ...params }
      const inner = migrateFlow(gp.nodes, gp.edges, legacy)
      gp.nodes = inner.nodes
      gp.edges = inner.edges
      if (!Array.isArray(gp.variables)) gp.variables = []
      if (!gp.name) gp.name = GROUP_META.label
      writeParams(node, gp)
      notes.push(...inner.notes)
      out.push(node)
      continue
    }

    // ---- 情况 A：老的「判断」（找图 + 分支）→ 图像识别 + 判断 ----
    if (oldType === 'judge' && (params.template !== undefined || params.threshold !== undefined)) {
      // 原来的判断节点**位置不动**、id 不动，改成新的「判断」——
      // 这样所有出边（yes/no 分支）自动继续指向它，不用改。
      const fiId = freshId(`${node.id}-find`, used)
      const fi = mkNode(
        fiId,
        'find_image',
        // 这条路径本身就是"老找图判断拆图"，必然是老文件 → 补输出变量名
        upgradeParams(
          'find_image',
          'find_image',
          {
            template: params.template,
            threshold: params.threshold,
            timeout_ms: params.timeout_ms,
          },
          true,
        ),
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
      writeParams(node, upgradeParams('find_image', 'find_image', params, legacy))
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
    writeParams(node, upgradeParams(oldType, mapped, params, legacy))
    out.push(node)
  }

  return { nodes: out, edges, notes }
}

/** 会把输入动作发给系统的节点类型（0.1.4 起输入方式挂在这些节点自己身上）。 */
const INPUT_TYPES = new Set(['mouse', 'keyboard', 'text_input', 'autoclick', 'record'])

/**
 * 把老的「脚本级输入方式」分发到各个输入节点（0.1.4 起没有全局单选了）。
 *
 * 只在老脚本（version < 3）且当初选的是「模拟输入」时才需要 —— 当初选「键鼠输入」
 * 正好等于新默认值，不用写任何东西。会钻进组合节点。
 */
function distributeInputMode(nodes: any[] | undefined, mode: string, depth = 0): void {
  if (!Array.isArray(nodes) || depth > 8) return
  for (const n of nodes) {
    const t = readType(n)
    const p = readParams(n)
    if (t === GROUP_TYPE) {
      distributeInputMode(p.nodes, mode, depth + 1)
      continue
    }
    if (INPUT_TYPES.has(t)) p.input_mode = mode
  }
}

/**
 * 老脚本（版本 < 3）里的变量是**全工作流共享**的。
 *
 * 0.1.4 改成层级作用域后，子脚本 / 组合节点里的写入默认不再回流外层 ——
 * 直接把老脚本升上来会悄悄改变它的行为。所以这里把老文件里已有的「变量」节点
 * 显式标成 `scope: global`，让它们保持原来的语义；用户想改用局部，自己在界面上改。
 */
function forceGlobalVarScope(nodes: any[] | undefined, depth = 0): number {
  if (!Array.isArray(nodes) || depth > 8) return 0
  let n = 0
  for (const node of nodes) {
    const t = readType(node)
    const p = readParams(node)
    if (t === GROUP_TYPE) {
      n += forceGlobalVarScope(p.nodes, depth + 1)
      continue
    }
    if (t === 'variable' && !p.scope) {
      p.scope = 'global'
      n += 1
    }
  }
  return n
}

/** 整份脚本（含子脚本库）的升级；返回新对象与说明。 */
export function migrateScript(data: any): { data: any; notes: string[] } {
  if (!data || typeof data !== 'object') return { data, notes: [] }
  const version = Number(data.version) || 1
  const legacy = version < 3
  const notes: string[] = []
  const root = migrateFlow(data.nodes, data.edges, legacy)
  notes.push(...root.notes)
  const scripts: Record<string, any> = {}
  const raw = data.scripts
  if (raw && typeof raw === 'object') {
    for (const [key, sub] of Object.entries<any>(raw)) {
      if (!sub || typeof sub !== 'object') {
        scripts[key] = sub
        continue
      }
      const r = migrateFlow(sub.nodes, sub.edges, legacy)
      notes.push(...r.notes)
      scripts[key] = { ...sub, nodes: r.nodes, edges: r.edges }
    }
  }

  if (legacy) {
    const mode = data.input_mode === 'simulated' ? 'simulated' : 'real'
    if (mode === 'simulated') {
      distributeInputMode(root.nodes, mode)
      for (const s of Object.values<any>(scripts)) distributeInputMode(s.nodes, mode)
      notes.push('脚本级的「模拟输入」已分发到各个输入节点（0.1.4 起输入方式按节点设定）')
    }
    let kept = 0
    for (const s of Object.values<any>(scripts)) kept += forceGlobalVarScope(s.nodes)
    if (kept) {
      notes.push(
        `子脚本里的 ${kept} 个「变量」节点已标为「全局作用域」，保持它们原来的跨层共享行为（0.1.4 起默认是局部）`,
      )
    }
  }

  return {
    data: { ...data, nodes: root.nodes, edges: root.edges, scripts },
    notes: Array.from(new Set(notes)),
  }
}
