/**
 * 键鼠录制的「拆分」编译：把一串录制事件编译成可编辑的流程步骤。
 *
 * 合并规则
 *  - mousedown + 紧随的 mouseup（同键） → 一个鼠标点击（保留按下时的坐标）
 *  - 一段连续的按键（含组合键 ctrl+shift+a）→ 一个键盘按键
 *  - 连续滚轮 → 合并成一个录制步骤（引擎暂无独立滚轮节点）
 *  - mousemove 一律丢弃：点击节点自带坐标，回放时会把光标移到该坐标
 *  - 事件之间的间隔 >= minGapMs（见 expandPieces）时插入一个延时节点，保留原有节奏
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
      if (up && up.type === 'mouseup' && (up.button || 'left') === (ev.button || 'left')) i += 1
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
