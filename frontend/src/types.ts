export type StepType = 'delay' | 'find_image' | 'click' | 'key' | 'text' | 'judge' | 'terminate' | 'macro'

export interface FlowNode {
  id: string
  type: StepType
  params: Record<string, any>
  once?: boolean
}

export interface FlowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
}

export interface Flow {
  name: string
  repeat: number
  input_mode: 'real' | 'simulated'
  window: { hwnd: number; title: string } | null
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export const STEP_META: Record<StepType, { label: string; icon: string; color: string }> = {
  delay: { label: '延时', icon: '⏱', color: '#f59e0b' },
  find_image: { label: '找图', icon: '🎯', color: '#22c55e' },
  click: { label: '鼠标点击', icon: '🖱', color: '#3b82f6' },
  key: { label: '键盘按键', icon: '⌨', color: '#a855f7' },
  text: { label: '输入文本', icon: '📝', color: '#ec4899' },
  judge: { label: '判断分支', icon: '🔀', color: '#06b6d4' },
  terminate: { label: '终止条件', icon: '🛑', color: '#ef4444' },
  macro: { label: '键鼠录制', icon: '⏺', color: '#f97316' },
}

export interface LogEntry {
  level: string
  message: string
  step?: string | null
  ts: number
}

export interface WindowInfo {
  hwnd: number
  title: string
  pid: number
  rect: { left: number; top: number; right: number; bottom: number; width: number; height: number }
}

export interface ScreenRef {
  width: number
  height: number
}

export interface BoundWindow {
  hwnd: number
  title: string
  /** 保存/录制时窗口的位置尺寸，运行时据此做分辨率与窗口缩放适配 */
  rect?: WindowInfo['rect'] | null
}

export interface FlowFile {
  format: 'agflow'
  version: number
  name: string
  repeat: number
  input_mode: 'real' | 'simulated'
  window: BoundWindow | null
  /** 保存时的主显示器物理分辨率，跨分辨率运行时坐标按比例换算 */
  screen?: ScreenRef | null
  nodes: any[]
  edges: any[]
}
