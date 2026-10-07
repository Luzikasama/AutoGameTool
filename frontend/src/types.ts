export interface FlowNode {
  id: string
  /** 节点的类型标识；老脚本里可能是 0.1.2 的节点，加载时由迁移层转换 */
  type: NodeType | (string & {})
  params: Record<string, any>
  once?: boolean
}

/**
 * 多出口节点的连线口（Vue Flow 的 sourceHandle）。
 *
 * 约定（前端画布与引擎侧共用）：
 *   · 判断：`yes` / `no`
 *   · 循环：`body`（循环体入口）/ `next`（循环结束后继续）
 *   · 其余节点只有一个默认出口（sourceHandle 为空串）
 *
 * 循环体末尾连回循环节点自身，即表示"这一轮结束、进入下一轮"。
 */
export const BRANCH_YES = 'yes'
export const BRANCH_NO = 'no'
export const BRANCH_BODY = 'body'
export const BRANCH_NEXT = 'next'

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
  /** 这个子脚本自己的「局部变量」声明（0.1.4 起；旧文件没有，按空处理） */
  variables?: VarItem[]
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
  input_mode?: 'real' | 'simulated'
  window: { hwnd: number; title: string } | null
  nodes: FlowNode[]
  edges: FlowEdge[]
}

/**
 * 六大节点类别（《节点设计规范 V1》第 2 节）。
 *
 * 类目决定画布上的**配色**：同一类的节点长得一样，一眼就能看出这段流程在干什么
 * （输入=蓝 / 视觉=绿 / 流程=青 / 工具=橙 / 数据=紫 / 系统=灰）。
 */
export type NodeCategory = 'input' | 'vision' | 'flow' | 'tool' | 'data' | 'system'

/**
 * 「组合节点」的类型名（0.1.4 起，「合并节点」的产物）。
 *
 * 它**不属于六大类**里的任何一类 —— 只是一个把若干节点装起来的「流程容器」：
 *  · 单击选中 → 右侧参数页可以改名字等属性
 *  · 双击     → 新开一个编辑标签，进去编辑它内部那张图
 *  · 内部图与自己的「局部变量」都存在节点参数的 `nodes / edges / variables` 里
 *
 * 因此它既不在左侧节点面板里出现（不靠拖拽创建，只能由「合并节点」产生），
 * 也不参与 CATEGORY_META 的配色体系，而是单给它一个色。
 */
export const GROUP_TYPE = 'group'

export const GROUP_META = {
  label: '组合节点',
  icon: '🧩',
  color: '#ec4899',
  desc: '把一串节点收成一个；双击进入编辑',
} as const

/** 组合节点内部那张图 + 局部变量的参数形状（存在节点的 params 里） */
export interface GroupParams {
  name: string
  nodes: any[]
  edges: any[]
  /** 这个组合节点自己的「局部变量」声明 */
  variables: VarItem[]
}

/**
 * 一条变量声明（右侧「变量」标签页里管理）。
 *
 * 全局变量属于主脚本、局部变量属于子脚本 / 组合节点；运行时按层级作用域初始化：
 * 读逐级往上找，写只落本层（要共享就显式写全局，见「变量」节点的作用域参数）。
 */
export interface VarItem {
  name: string
  /** auto / string / number / bool */
  type: string
  /** 初始值（文本；按 type 转换） */
  value: string
}

export const VAR_TYPES = [
  { label: '自动识别', value: 'auto' },
  { label: '文本', value: 'string' },
  { label: '数字', value: 'number' },
  { label: '真/假', value: 'bool' },
]

export const CATEGORY_ORDER: NodeCategory[] = [
  'input',
  'vision',
  'flow',
  'tool',
  'data',
  'system',
]

export const CATEGORY_META: Record<
  NodeCategory,
  { label: string; index: string; icon: string; color: string; desc: string }
> = {
  input: { label: '输入', index: '①', icon: '🖱', color: '#3b82f6', desc: '执行动作：鼠标、键盘、文本、剪贴板' },
  vision: { label: '视觉', index: '②', icon: '🎯', color: '#22c55e', desc: '看到什么：图像、文字、颜色、像素、区域' },
  flow: { label: '流程', index: '③', icon: '🔀', color: '#06b6d4', desc: '控制执行：判断、循环、延时、等待、终止' },
  tool: { label: '工具', index: '④', icon: '⚡', color: '#f97316', desc: '组合与外部能力：录制、连点、脚本调用、外部工具' },
  data: { label: '数据', index: '⑤', icon: '🧮', color: '#a855f7', desc: '信息本身：变量、运算、文本处理' },
  system: { label: '系统', index: '⑥', icon: '🪟', color: '#64748b', desc: '操作系统资源：窗口、进程、文件、命令' },
}

/** 25 个核心节点的类型标识（规范第 17 节） */
export type NodeType =
  // ① 输入
  | 'mouse'
  | 'keyboard'
  | 'text_input'
  | 'clipboard'
  // ② 视觉
  | 'find_image'
  | 'ocr'
  | 'color_check'
  | 'pixel_check'
  | 'region_analysis'
  // ③ 流程
  | 'judge'
  | 'loop'
  | 'delay'
  | 'wait'
  | 'terminate'
  // ④ 工具
  | 'record'
  | 'autoclick'
  | 'script_call'
  | 'external_tool'
  // ⑤ 数据
  | 'variable'
  | 'calculate'
  | 'text_process'
  // ⑥ 系统
  | 'window'
  | 'process'
  | 'file'
  | 'command'

export interface NodeMeta {
  label: string
  icon: string
  category: NodeCategory
  /** 属性面板里的一句话说明（鼠标悬停/分组标题用） */
  hint?: string
}

export const NODE_META: Record<NodeType, NodeMeta> = {
  // ---------- ① 输入 ----------
  mouse: { label: '鼠标操作', icon: '🖱', category: 'input', hint: '点击 / 双击 / 右键 / 移动 / 按下松开 / 滚轮' },
  keyboard: { label: '键盘按键', icon: '⌨', category: 'input', hint: '单键 / 组合键 / 按下 / 松开' },
  text_input: { label: '文本输入', icon: '📝', category: 'input', hint: '直接输入或经剪贴板输入到当前窗口' },
  clipboard: { label: '剪贴板', icon: '📋', category: 'input', hint: '写入 / 读取 / 清空' },
  // ---------- ② 视觉 ----------
  find_image: { label: '图像识别', icon: '🎯', category: 'vision', hint: '在屏幕或指定区域内寻找模板图' },
  ocr: { label: '文字识别', icon: '🔍', category: 'vision', hint: '对指定区域做 OCR，输出文本' },
  color_check: { label: '颜色检测', icon: '🎨', category: 'vision', hint: '区域内是否出现指定颜色' },
  pixel_check: { label: '像素检测', icon: '📍', category: 'vision', hint: '精确比对一个点（或小方块）的颜色' },
  region_analysis: { label: '区域分析', icon: '🖼', category: 'vision', hint: '区域是否变化 / 平均颜色 / 截图' },
  // ---------- ③ 流程 ----------
  judge: { label: '判断', icon: '🔀', category: 'flow', hint: '按条件走「是 / 否」分支' },
  loop: { label: '循环', icon: '🔁', category: 'flow', hint: '固定次数 / 条件循环 / 无限循环' },
  delay: { label: '延时', icon: '⏱', category: 'flow', hint: '无条件等待指定时间' },
  wait: { label: '等待', icon: '⏳', category: 'flow', hint: '等到条件满足（图片出现、变量达标…）' },
  terminate: { label: '终止', icon: '🛑', category: 'flow', hint: '终止当前节点 / 循环 / 脚本 / 整个工作流' },
  // ---------- ④ 工具 ----------
  record: { label: '键鼠录制', icon: '⏺', category: 'tool', hint: '录一段操作，停止后生成普通节点' },
  autoclick: { label: '连点器', icon: '⚡', category: 'tool', hint: '高频连点：坐标 + 次数 + 间隔' },
  script_call: { label: '调用脚本', icon: '📦', category: 'tool', hint: '执行另一个脚本（子脚本嵌套）' },
  external_tool: { label: '外部工具', icon: '🔌', category: 'tool', hint: '调用外部程序 / HTTP 接口 / 插件' },
  // ---------- ⑤ 数据 ----------
  variable: { label: '变量', icon: '🏷', category: 'data', hint: '新建 / 赋值 / 读取 / 删除' },
  calculate: { label: '运算', icon: '🧮', category: 'data', hint: '数学、比较、逻辑、赋值' },
  text_process: { label: '文本处理', icon: '🔤', category: 'data', hint: '拼接、截取、替换、正则、转数字…' },
  // ---------- ⑥ 系统 ----------
  window: { label: '窗口', icon: '🪟', category: 'system', hint: '查找 / 激活 / 最小化 / 移动 / 取信息' },
  process: { label: '进程', icon: '⚙', category: 'system', hint: '启动 / 关闭 / 是否在运行 / 取信息' },
  file: { label: '文件', icon: '📁', category: 'system', hint: '读 / 写 / 复制 / 移动 / 删除 / 存在性' },
  command: { label: '命令', icon: '⌘', category: 'system', hint: '执行 CMD / PowerShell / Bash 命令' },
}

/** 按类目取节点（面板用它分组渲染，顺序与规范一致） */
export function nodesOfCategory(cat: NodeCategory): Array<[NodeType, NodeMeta]> {
  return (Object.entries(NODE_META) as Array<[NodeType, NodeMeta]>).filter(
    ([, m]) => m.category === cat,
  )
}

/** 节点配色 = 它所属类目的颜色；组合节点不属于任何类目，单给一个色。 */
export function nodeColor(t: string): string {
  if (t === GROUP_TYPE) return GROUP_META.color
  const m = NODE_META[t as NodeType]
  return m ? CATEGORY_META[m.category].color : '#888'
}

/**
 * 0.1.2 及更早的节点 → 新节点类型。
 *
 * 只做"换个名字"的部分；`judge`（老语义是"找图+分支"）需要拆成两个节点，
 * 由 `lib/migrateFlow.ts` 负责（要动连线，不能只靠映射表）。
 */
export const LEGACY_TYPE_MAP: Record<string, NodeType> = {
  click: 'mouse',
  key: 'keyboard',
  text: 'text_input',
  macro: 'record',
  find_image: 'find_image',
  delay: 'delay',
  judge: 'judge',
  terminate: 'terminate',
  autoclick: 'autoclick',
  script_call: 'script_call',
}

/** 老的「判断分支」（找图 + 分支）节点 —— 加载时会被拆开 */
export const LEGACY_JUDGE = 'judge'

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
  /**
   * 1 = 0.1.1 及更早（无 scripts）
   * 2 = 0.1.2 起（可携带子脚本）
   * 3 = 0.1.4 起（变量管理：主脚本的 variables + 子脚本/组合节点的局部变量；
   *     输入方式从流程级单选取下，改为挂在各输入节点上）。读取时 1/2/3 都接受。
   */
  version: number
  name: string
  repeat: number
  /** 脚本级输入方式。0.1.4 起已废弃：输入方式挂在各输入节点自己的参数上；
   *  这里只在读老文件（version < 3）时作为分发来源，新存的文件不写这个字段。 */
  input_mode?: 'real' | 'simulated'
  window: BoundWindow | null
  /** 保存时的主显示器物理分辨率，跨分辨率运行时坐标按比例换算 */
  screen?: ScreenRef | null
  nodes: any[]
  edges: any[]
  /** 本脚本内嵌的子脚本（脚本库）。旧文件没有这个字段，按空处理。 */
  scripts?: Record<string, SubScript>
  /** 主脚本的「全局变量」声明（0.1.4 起）。旧文件没有这个字段，按空处理。 */
  variables?: VarItem[]
}
