/**
 * 键鼠录制的「拆分」与「打包」：两者互为逆操作，都是纯函数。
 *
 * 拆分（录制事件 → 流程步骤）的合并规则
 *  - mousedown + 紧随的 mouseup（同键） → 一个鼠标点击（保留按下时的坐标）
 *  - 一段连续的按键（含组合键 ctrl+shift+a）→ 一个键盘按键
 *  - 连续滚轮 → 合并成一个录制步骤（引擎暂无独立滚轮节点）
 *  - mousemove 一律丢弃：点击节点自带坐标，回放时会把光标移到该坐标
 *  - 事件之间的间隔 >= minGapMs（见 expandPieces）时插入一个延时节点，保留原有节奏
 *
 * 打包（选中的相邻流程步骤 → 一个录制步骤）见 packStepsToMacro。
 */
import type { StepType } from '../types'

export interface MacroPiece {
  stepType: StepType
  params: Record<string, any>
  /** 该动作之前需要等待的毫秒数 */
  gapMs: number
}

export interface MacroStep {
  stepType: StepType
  params: Record<string, any>
}

/** 把录制事件编译成动作片段（不含延时节点；间隔信息记录在 gapMs 上）。 */
export function compileMacroPieces(events: any[], speed = 1.0): MacroPiece[] {
  const pieces: MacroPiece[] = []
  if (!Array.isArray(events) || events.length === 0) return pieces

  let lastT = 0
  const takeGap = (t: number): number => {
    const gap = Math.max(0, Math.round(t - lastT))
    if (t > lastT) lastT = t
    return gap
  }

  let scrolls: any[] = []
  // held：当前仍按着的键；group：本轮组合键（自上次结算以来按下的键）。
  // 结算时机是「本轮第一个抬起」——那时 group 才完整；
  // 若等到最后一个键抬起，group 会被逐渐过滤得只剩最后一个键。
  let held: string[] = []
  let group: string[] = []
  let groupAt = 0

  const flushScrolls = (t: number): void => {
    if (!scrolls.length) return
    pieces.push({ stepType: 'macro', params: { events: scrolls, speed }, gapMs: takeGap(t) })
    scrolls = []
  }

  for (let i = 0; i < events.length; i++) {
    const ev = events[i] || {}
    const t = Number(ev.t) || 0
    const type = String(ev.type || '')

    if (type === 'mousemove') continue

    if (type === 'scroll') {
      scrolls.push(ev)
      continue
    }
    flushScrolls(t)

    if (type === 'mousedown') {
      const gap = takeGap(t)
      const up = events[i + 1]
      if (up && up.type === 'mouseup' && (up.button || 'left') === (ev.button || 'left')) {
        i += 1
        // 被吃掉的抬起也要推进时间轴：否则「按下→抬起」这几十毫秒会落进后面那个
        // 延时的间隔里，来回转换（拆分↔打包）就不等长了。
        const upT = Number(up.t) || 0
        if (upT > lastT) lastT = upT
      }
      pieces.push({
        stepType: 'click',
        params: {
          x: Math.round(Number(ev.x) || 0),
          y: Math.round(Number(ev.y) || 0),
          button: ev.button || 'left',
          clicks: 1,
        },
        gapMs: gap,
      })
      continue
    }

    if (type === 'mouseup') continue // 孤立的抬起（无配对按下）

    if (type === 'keydown') {
      const key = String(ev.key || '')
      if (!key) continue
      if (!group.length) {
        // 新一轮组合键开始：把此刻仍按着不放的键（如「ctrl+a、ctrl+b」中的 ctrl）也纳入
        group = held.slice()
        groupAt = t
      }
      if (!group.includes(key)) group.push(key)
      if (!held.includes(key)) held.push(key)
      continue
    }

    if (type === 'keyup') {
      const key = String(ev.key || '')
      held = held.filter((k) => k !== key)
      if (group.length) {
        // 本轮第一个抬起 → 此刻 group 完整，结算成一个组合键节点（如 ctrl+shift+a）
        pieces.push({ stepType: 'key', params: { key: group.join('+') }, gapMs: takeGap(groupAt) })
        group = []
      }
      continue
    }
  }

  // 录制在按键尚未抬起时结束：把仍按着的键也结算掉
  if (group.length) {
    pieces.push({ stepType: 'key', params: { key: group.join('+') }, gapMs: takeGap(groupAt) })
  }
  const lastEventT = Number(events[events.length - 1]?.t) || lastT
  flushScrolls(lastEventT)

  return pieces
}

/** 把片段展开成最终步骤序列：间隔足够大的位置插入延时节点。 */
export function expandPieces(pieces: MacroPiece[], minGapMs = 80): MacroStep[] {
  const steps: MacroStep[] = []
  for (const p of pieces) {
    if (p.gapMs >= minGapMs) steps.push({ stepType: 'delay', params: { ms: p.gapMs } })
    steps.push({ stepType: p.stepType, params: p.params })
  }
  return steps
}

// ---------------------------------------------------------------------------
// 反向操作：把一串相邻步骤打包回一个「键鼠录制」步骤
// ---------------------------------------------------------------------------

/** 打包时一次点击的按下时长。
 *  拆分是**有损**的：点击节点没有"按时长"字段，按下→抬起之间的间隔被有意丢弃，
 *  所以反向打包只能用一个约定值（测试用例里的录制就在这个量级）。 */
export const CLICK_HOLD_MS = 60
/** 一次点击节点里 clicks > 1 时，两下之间的间隔 */
export const CLICK_GAP_MS = 40
/** 打包时一次按键的按下时长 */
export const KEY_HOLD_MS = 60

export interface PackStep {
  stepType: StepType
  params: Record<string, any>
}

export interface PackResult {
  ok: boolean
  /** 打包出的事件序列（ok=false 时为空） */
  events: any[]
  /** 无法打包进录制的步骤类型（去重） */
  badTypes: StepType[]
}

/** 这些步骤类型表达不了"键鼠事件"，因此不能被打包进录制步骤。 */
const UNPACKABLE: StepType[] = ['find_image', 'judge', 'text', 'terminate']

/** 某个步骤类型能否被打包进录制。 */
export function canPack(stepType: StepType): boolean {
  return !UNPACKABLE.includes(stepType)
}

/**
 * 把一串**按执行顺序排列**的步骤打包成一个录制事件序列（拆分的逆操作）。
 *
 *  - 延时节点 → 时间轴向前推进（不产生事件）
 *  - 点击节点 → mousedown + mouseup（保留坐标与按键；clicks>1 时重复若干下）
 *  - 按键节点 → 组合键按顺序按下、逆序抬起
 *  - 录制节点 → 其事件按自身 speed 换算成真实时间后内联进来（可嵌套合并）
 *  - 找图 / 判断 / 文本 / 终止 → 无法表达为键鼠事件，整体拒绝打包
 *
 * 只要有一个步骤不能打包就返回 ok=false（不做部分打包），调用方据此提示用户。
 */
export function packStepsToMacro(steps: PackStep[]): PackResult {
  const events: any[] = []
  const bad: StepType[] = []
  let t = 0

  for (const s of steps || []) {
    const p = s?.params || {}
    switch (s?.stepType) {
      case 'delay': {
        const ms = Math.max(0, Number(p.ms) || 0)
        t += ms
        break
      }
      case 'click': {
        const x = Math.round(Number(p.x) || 0)
        const y = Math.round(Number(p.y) || 0)
        const button = p.button || 'left'
        const clicks = Math.max(1, Math.min(10, Number(p.clicks) || 1))
        for (let i = 0; i < clicks; i++) {
          events.push({ t, type: 'mousedown', x, y, button })
          t += CLICK_HOLD_MS
          events.push({ t, type: 'mouseup', x, y, button })
          if (i + 1 < clicks) t += CLICK_GAP_MS
        }
        break
      }
      case 'key': {
        const parts = String(p.key || '')
          .split('+')
          .map((k) => k.trim().toLowerCase())
          .filter(Boolean)
        if (!parts.length) break
        for (const k of parts) events.push({ t, type: 'keydown', key: k })
        t += KEY_HOLD_MS
        for (const k of [...parts].reverse()) events.push({ t, type: 'keyup', key: k })
        break
      }
      case 'macro': {
        const inner: any[] = Array.isArray(p.events) ? p.events : []
        const innerSpeed = Number(p.speed) > 0 ? Number(p.speed) : 1
        let last = 0
        for (const ev of inner) {
          // 内层事件按它自己的播放速度换算成真实时间，外层用 1.0x 回放即等价
          const et = Math.max(0, Math.round((Number(ev?.t) || 0) / innerSpeed))
          if (et > last) last = et
          events.push({ ...ev, t: t + et })
        }
        t += last
        break
      }
      default:
        bad.push(s?.stepType)
        break
    }
  }

  const badTypes = [...new Set(bad)]
  if (badTypes.length) return { ok: false, events: [], badTypes }
  if (!events.length) return { ok: false, events: [], badTypes: [] }
  return { ok: true, events, badTypes: [] }
}

/** 把打包结果再拆一次，用于「拆分↔打包」往返测试与自检。 */
export function splitAgain(events: any[], minGapMs = 80): MacroStep[] {
  return expandPieces(compileMacroPieces(events), minGapMs)
}

/**
 * 把选中的节点按连线顺序排成一条链；不是「一条连续链」时返回 null。
 *
 * 打包合并要求选中的步骤首尾相接，判定条件：
 *  - 选中集合内部恰好有一个"没有入边"的头（0 个 = 成环，多个 = 不是一条链）
 *  - 顺流而下时中间不能有分支（判断节点有两条出边，表达不了先后顺序）
 *  - 这条链必须覆盖**全部**选中节点（否则有游离在外的）
 */
export function orderChain<T extends { id: string }>(
  selected: T[],
  edges: { source: string; target: string }[],
): T[] | null {
  if (!Array.isArray(selected) || selected.length < 2) return null
  const ids = new Set(selected.map((n) => n.id))
  const byId = new Map(selected.map((n) => [n.id, n]))
  const inDeg = new Map<string, number>()
  const outTo = new Map<string, string[]>()
  for (const id of ids) {
    inDeg.set(id, 0)
    outTo.set(id, [])
  }
  for (const e of edges || []) {
    if (ids.has(e.source) && ids.has(e.target)) {
      inDeg.set(e.target, (inDeg.get(e.target) || 0) + 1)
      outTo.get(e.source)!.push(e.target)
    }
  }
  const heads = [...ids].filter((id) => (inDeg.get(id) || 0) === 0)
  if (heads.length !== 1) return null
  const chain: T[] = []
  const seen = new Set<string>()
  let cur: string | null = heads[0]
  while (cur) {
    if (seen.has(cur)) return null
    seen.add(cur)
    chain.push(byId.get(cur)!)
    const outs: string[] = outTo.get(cur) || []
    if (outs.length > 1) return null
    cur = outs.length ? outs[0] : null
  }
  return chain.length === selected.length ? chain : null
}

// ---------------------------------------------------------------------------
// 拆分结果的布局：蛇形网格（原先是一条一直往下的长竖线）
// ---------------------------------------------------------------------------

/** 节点大致尺寸与间距（StepNode 的 min-width:150 + 内边距 ≈ 170 宽，行高约 56） */
export const NODE_W = 176
export const NODE_H = 56
export const COL_PITCH = 212
export const ROW_PITCH = 78

/**
 * 网格行列数：先用满可视高度得到 rows，再向右折行得到 cols。
 *
 * 列数刻意凑成**奇数**：蛇形走位下偶数列自上而下、奇数列自下而上，列数为奇数时
 * 最后一个步骤落在最右一列的下行方向上，更靠近原来的后继节点。
 *
 * 注意：最后一列不一定填满（count 不是 cols 的整数倍时），此时"出口"会停在那一列
 * 的中间。这是为了让**块内每一条连线都首尾相接**（相邻两步不是同列上下相邻、就是
 * 换列时同一行相邻）而做的取舍——块内绝不出现长对角线。
 */
export function splitGridLayout(count: number, viewportH = 520): { rows: number; cols: number } {
  const n = Math.max(1, Math.floor(count) || 1)
  const rowsFit = Math.max(3, Math.min(14, Math.floor((viewportH - 40) / ROW_PITCH)))
  const firstRows = Math.max(1, Math.min(n, rowsFit))
  let cols = Math.max(1, Math.ceil(n / firstRows))
  if (cols > 1 && cols % 2 === 0) cols += 1
  return { rows: Math.ceil(n / cols), cols }
}

/** 第 i 个步骤在蛇形网格里的行列：偶数列自上而下，奇数列自下而上。 */
export function gridSlot(i: number, rows: number): { col: number; row: number } {
  const col = Math.floor(i / rows)
  const pos = i % rows
  return { col, row: col % 2 === 0 ? pos : rows - 1 - pos }
}

/** 直接给出 count 个步骤相对原点的网格坐标（编辑器用它摆位，也可单独断言）。 */
export function splitGridPositions(count: number, viewportH = 520): { x: number; y: number }[] {
  const { rows } = splitGridLayout(count, viewportH)
  const out: { x: number; y: number }[] = []
  for (let i = 0; i < count; i++) {
    const s = gridSlot(i, rows)
    out.push({ x: s.col * COL_PITCH, y: s.row * ROW_PITCH })
  }
  return out
}

