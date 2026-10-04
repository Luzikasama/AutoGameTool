export type StepType =
  | 'delay'
  | 'find_image'
  | 'click'
  | 'key'
  | 'text'
  | 'judge'
  | 'terminate'
  | 'macro'
  | 'autoclick'
  | 'script_call'

export interface FlowNode {
  id: string
  type: StepType
  params: Record<string, any>
  once?: boolean
}

/**
 * 子脚本：一段可以被其他脚本调用的可复用流程。
 *
 * 存储位置刻意放在**父脚本文件内部**（`FlowFile.scripts`），而不是各自的文件：
 *  - 一个 .agflow 拖到别的机器上就能完整跑起来，不会"少了一个子脚本"
 *  - 导出时把其中一项单独写成一个 .agflow 即可（子脚本本身也是一份合法脚本）
 *  - `id` 是稳定标识（如 `s1`），**不要用名字当身份** —— 改名不该切断调用关系
 */
export interface SubScript {
  id: string
  name: string
  nodes: any[]
  edges: any[]
}

/** 调用脚本节点的参数：只认 script_id（name 仅用于显示，丢了也能靠注册表补回来）。 */
export interface ScriptCallParams {
  script_id: string
  name?: string
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
  autoclick: { label: '连点器', icon: '⚡', color: '#14b8a6' },
  // 调用脚本：本质是"把另一段脚本内联到这里执行"，与打包合并的运行语义接近，
  // 区别只是子脚本可以单独导出、单独编辑、被多个脚本复用。
  script_call: { label: '调用脚本', icon: '📦', color: '#8b5cf6' },
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
  /** 1 = 0.1.1 及更早（无 scripts）；2 = 0.1.2 起（可携带子脚本）。读取时两者都接受。 */
  version: number
  name: string
  repeat: number
  input_mode: 'real' | 'simulated'
  window: BoundWindow | null
  /** 保存时的主显示器物理分辨率，跨分辨率运行时坐标按比例换算 */
  screen?: ScreenRef | null
  nodes: any[]
  edges: any[]
  /** 本脚本内嵌的子脚本（脚本库）。旧文件没有这个字段，按空处理。 */
  scripts?: Record<string, SubScript>
}
