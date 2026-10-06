/**
 * 25 个核心节点的**参数模式表**（《节点设计规范 V1》第 17 节）。
 *
 * 为什么要把参数模式抽成数据，而不是像 0.1.2 那样在属性面板里手写 25 段模板：
 *  - 0.1.2 是「一个节点一段 v-if」，10 个节点就已经让 EditorPane 涨到 2400 行；
 *    扩到 25 个节点后，再手写就是 4000+ 行且改一个参数要动三处（默认值/面板/摘要）。
 *  - 抽成模式表后：**默认值、属性面板、节点摘要、迁移补参** 全部由同一份数据推导，
 *    新增一个节点 = 往这里加一条 + 引擎里加一个处理分支。
 *
 * 字段类型（渲染在属性面板里的控件）：
 *  - text / textarea / number / switch / select          —— 基础控件
 *  - template  从已保存的识别模板里选（下拉 + 缩略图）
 *  - color     '#RRGGBB'，带取色器
 *  - region    矩形区域（l/t/w/h），带「框选」按钮
 *  - keys      键位捕获输入（点一下按下组合键即可录入）
 *  - condition 单条条件（左值 / 运算符 / 右值）
 *  - command   命令行（等宽字体 + 多行）
 *
 * showIf 让「同一个节点按模式显示不同参数」成为可能（例如连点器只在
 * mode=coord 时显示坐标）。它是**渲染层**规则，不影响默认值——默认值一律全带，
 * 引擎读到不相关的键会忽略，这样切换 mode 时之前填的值不会丢。
 */
import type { NodeType } from '../types'

export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'switch'
  | 'select'
  | 'template'
  | 'color'
  | 'region'
  | 'keys'
  | 'condition'
  | 'command'

export interface NodeField {
  key: string
  label: string
  type: FieldType
  /** select / condition 的候选项 */
  options?: Array<{ label: string; value: any }>
  default?: any
  min?: number
  max?: number
  step?: number
  /** 输入框占位提示 */
  placeholder?: string
  /** 参数下方的灰色说明 */
  hint?: string
  /** 只在满足条件时显示（渲染层规则） */
  showIf?: { key: string; equals?: any; in?: any[]; not?: any }
}

export interface NodeSchema {
  fields: NodeField[]
  /** 该节点会写进「运行变量」的键（给用户看，说明这个节点能提供什么数据） */
  outputs?: Array<{ key: string; label: string }>
  /** 属性面板顶部的一句话用法 */
  help?: string
}

/** 常用运算符（判断 / 等待 / 循环共用） */
export const CONDITION_OPS: Array<{ label: string; value: string }> = [
  { label: '等于', value: '==' },
  { label: '不等于', value: '!=' },
  { label: '大于', value: '>' },
  { label: '大于等于', value: '>=' },
  { label: '小于', value: '<' },
  { label: '小于等于', value: '<=' },
  { label: '包含', value: 'contains' },
  { label: '不包含', value: 'not_contains' },
  { label: '为空', value: 'is_empty' },
  { label: '不为空', value: 'not_empty' },
  { label: '为真', value: 'is_true' },
  { label: '为假', value: 'is_false' },
]

/** 只需要一个左值的运算符（右值输入框会被隐藏） */
export const UNARY_OPS = ['is_empty', 'not_empty', 'is_true', 'is_false']

const MOUSE_ACTIONS = [
  { label: '单击', value: 'click' },
  { label: '双击', value: 'double_click' },
  { label: '右键单击', value: 'right_click' },
  { label: '中键单击', value: 'middle_click' },
  { label: '移动到坐标', value: 'move' },
  { label: '按下不放', value: 'down' },
  { label: '松开', value: 'up' },
  { label: '滚轮', value: 'wheel' },
]

const BUTTONS = [
  { label: '左键', value: 'left' },
  { label: '右键', value: 'right' },
  { label: '中键', value: 'middle' },
]

const TIMEOUT_ON = [
  { label: '超时后继续（走「否」分支也可自行判断）', value: 'continue' },
  { label: '超时后终止工作流', value: 'terminate' },
]

/**
 * 参数模式表。
 *
 * 约定：每个节点的字段顺序 = 属性面板里的显示顺序，也大致是"先选做什么、再填参数"。
 */
export const NODE_SCHEMA: Record<NodeType, NodeSchema> = {
  // =====================================================================
  // ① 输入
  // =====================================================================
  mouse: {
    help: '在指定坐标执行一次鼠标动作。坐标是屏幕绝对坐标，可用「拾取坐标」抓取。',
    fields: [
      { key: 'action', label: '动作', type: 'select', options: MOUSE_ACTIONS, default: 'click' },
      { key: 'x', label: 'X 坐标', type: 'number', default: 0, min: -100000, max: 100000 },
      { key: 'y', label: 'Y 坐标', type: 'number', default: 0, min: -100000, max: 100000 },
      { key: 'button', label: '按键', type: 'select', options: BUTTONS, default: 'left', showIf: { key: 'action', in: ['down', 'up'] } },
      { key: 'clicks', label: '连击次数', type: 'number', default: 1, min: 1, max: 10, hint: '仅「单击」时生效；双击请直接用「双击」动作', showIf: { key: 'action', equals: 'click' } },
      { key: 'dx', label: '水平滚动', type: 'number', default: 0, hint: '正数向右', showIf: { key: 'action', equals: 'wheel' } },
      { key: 'dy', label: '垂直滚动', type: 'number', default: -3, hint: '正数向上、负数向下（一格 = 120）', showIf: { key: 'action', equals: 'wheel' } },
      { key: 'duration_ms', label: '移动耗时', type: 'number', default: 0, min: 0, max: 60000, hint: '仅「移动到坐标」时生效，0 表示瞬移', showIf: { key: 'action', equals: 'move' } },
    ],
  },

  keyboard: {
    help: '按下 / 松开按键，支持组合键（ctrl+shift+a）。「按下不放 + 后续松开」可做长按与拖拽。',
    fields: [
      { key: 'action', label: '动作', type: 'select', default: 'press', options: [
        { label: '按一下（按下并抬起）', value: 'press' },
        { label: '按下不放', value: 'down' },
        { label: '松开', value: 'up' },
      ] },
      { key: 'keys', label: '按键', type: 'keys', default: 'enter', hint: '点击输入框后直接按下组合键即可录入' },
      { key: 'hold_ms', label: '按住时长', type: 'number', default: 30, min: 0, max: 60000, hint: '仅「按一下」时生效', showIf: { key: 'action', equals: 'press' } },
    ],
  },

  text_input: {
    help: '把一段文本输入到当前焦点窗口。含中文/特殊符号时建议用剪贴板方式。',
    fields: [
      { key: 'text', label: '文本内容', type: 'textarea', default: '', placeholder: '支持 {{变量名}} 引用运行变量' },
      { key: 'method', label: '输入方式', type: 'select', default: 'direct', options: [
        { label: '直接输入（逐字符模拟按键）', value: 'direct' },
        { label: '剪贴板粘贴（快，适合中文长文本）', value: 'clipboard' },
      ] },
      { key: 'interval_ms', label: '字符间隔', type: 'number', default: 10, min: 0, max: 1000, hint: '仅「直接输入」时生效', showIf: { key: 'method', equals: 'direct' } },
      { key: 'restore_clipboard', label: '粘贴后恢复原剪贴板', type: 'switch', default: true, showIf: { key: 'method', equals: 'clipboard' } },
    ],
  },

  clipboard: {
    help: '读写系统剪贴板。常用于"复制 → 读出来当变量用"或"把变量粘到别的程序"。',
    fields: [
      { key: 'action', label: '动作', type: 'select', default: 'set', options: [
        { label: '写入剪贴板', value: 'set' },
        { label: '读取剪贴板', value: 'get' },
        { label: '清空剪贴板', value: 'clear' },
      ] },
      { key: 'text', label: '写入内容', type: 'textarea', default: '', placeholder: '支持 {{变量名}}', showIf: { key: 'action', equals: 'set' } },
      { key: 'var', label: '读取到变量', type: 'text', default: 'clip', hint: '读取到的文本会存进这个变量，后续用 {{clip}} 引用', showIf: { key: 'action', equals: 'get' } },
    ],
    outputs: [{ key: '读取到变量', label: '剪贴板文本' }],
  },

  // =====================================================================
  // ② 视觉
  // =====================================================================
  find_image: {
    help: '在屏幕（或绑定窗口）里寻找模板图。只负责"看见"，找到后由「判断」节点决定怎么走。',
    fields: [
      { key: 'template', label: '识别模板', type: 'template', default: '' },
      { key: 'threshold', label: '相似度阈值', type: 'number', default: 0.85, min: 0.3, max: 1, step: 0.01, hint: '0.85 适合大多数场景；画面有闪烁可降到 0.8' },
      { key: 'timeout_ms', label: '超时', type: 'number', default: 5000, min: 0, max: 3600000, hint: '毫秒。0 表示只截一帧就返回' },
      { key: 'scope', label: '搜索范围', type: 'select', default: 'auto', options: [
        { label: '自动（绑定了窗口就用窗口，否则全屏）', value: 'auto' },
        { label: '整个屏幕', value: 'screen' },
        { label: '绑定窗口', value: 'window' },
      ] },
      { key: 'save_found', label: '找到与否存入变量', type: 'text', default: 'found', hint: '值为 yes / no，供「判断」节点使用' },
      { key: 'save_x', label: '位置 X 存入变量', type: 'text', default: 'found_x' },
      { key: 'save_y', label: '位置 Y 存入变量', type: 'text', default: 'found_y' },
      { key: 'save_score', label: '相似度存入变量', type: 'text', default: 'found_score' },
    ],
    outputs: [
      { key: 'save_found', label: '是否找到（yes/no）' },
      { key: 'save_x / save_y', label: '匹配中心屏幕坐标' },
      { key: 'save_score', label: '相似度 0~1' },
    ],
  },

  ocr: {
    help: '对指定区域做文字识别（RapidOCR，中英文混排）。识别结果存进变量，供后续判断或运算。',
    fields: [
      { key: 'source', label: '识别来源', type: 'select', default: 'auto', options: [
        { label: '自动（绑定了窗口就用窗口，否则全屏）', value: 'auto' },
        { label: '整个屏幕', value: 'screen' },
        { label: '绑定窗口', value: 'window' },
        { label: '自定义区域', value: 'region' },
      ] },
      { key: 'region', label: '识别区域', type: 'region', default: null, showIf: { key: 'source', equals: 'region' } },
      { key: 'save_text', label: '识别文本存入变量', type: 'text', default: 'ocr_text' },
      { key: 'save_found', label: '是否有文字存入变量', type: 'text', default: 'ocr_found' },
      { key: 'join', label: '多行合并方式', type: 'select', default: 'newline', options: [
        { label: '保留换行', value: 'newline' },
        { label: '用空格连成一行', value: 'space' },
        { label: '直接拼接', value: 'none' },
      ] },
    ],
    outputs: [
      { key: 'save_text', label: '识别到的全部文本' },
      { key: 'save_found', label: '是否识别到文字（yes/no）' },
    ],
  },

  color_check: {
    help: '检测区域内是否出现指定颜色（容差可调）。适合判断按钮高亮、血条颜色等。',
    fields: [
      { key: 'source', label: '检测范围', type: 'select', default: 'auto', options: [
        { label: '自动（绑定了窗口就用窗口，否则全屏）', value: 'auto' },
        { label: '整个屏幕', value: 'screen' },
        { label: '绑定窗口', value: 'window' },
        { label: '自定义区域', value: 'region' },
      ] },
      { key: 'region', label: '检测区域', type: 'region', default: null, showIf: { key: 'source', equals: 'region' } },
      { key: 'color', label: '目标颜色', type: 'color', default: '#ff0000' },
      { key: 'tolerance', label: '容差', type: 'number', default: 12, min: 0, max: 255, hint: '每个通道允许的偏差 0~255' },
      { key: 'min_pixels', label: '最少像素数', type: 'number', default: 1, min: 1, max: 10000000, hint: '命中的像素达到这个数量才算"出现"' },
      { key: 'save_found', label: '是否出现存入变量', type: 'text', default: 'color_found' },
      { key: 'save_x', label: '命中点 X 存入变量', type: 'text', default: '' },
      { key: 'save_y', label: '命中点 Y 存入变量', type: 'text', default: '' },
    ],
    outputs: [
      { key: 'save_found', label: '是否出现（yes/no）' },
      { key: 'save_x / save_y', label: '第一个命中点的屏幕坐标' },
    ],
  },

  pixel_check: {
    help: '精确比对一个点（或 N×N 小方块）的颜色。比「颜色检测」更快更准，适合固定位置的指示灯。',
    fields: [
      { key: 'x', label: 'X 坐标', type: 'number', default: 0, min: -100000, max: 100000 },
      { key: 'y', label: 'Y 坐标', type: 'number', default: 0, min: -100000, max: 100000 },
      { key: 'size', label: '取样边长', type: 'number', default: 1, min: 1, max: 31, hint: '取以该点为中心的 N×N 方块的平均色，抗锯齿/抗闪烁' },
      { key: 'color', label: '目标颜色', type: 'color', default: '#00ff00' },
      { key: 'tolerance', label: '容差', type: 'number', default: 12, min: 0, max: 255 },
      { key: 'save_found', label: '是否匹配存入变量', type: 'text', default: 'pixel_found' },
      { key: 'save_color', label: '实际颜色存入变量', type: 'text', default: '' },
    ],
    outputs: [
      { key: 'save_found', label: '是否匹配（yes/no）' },
      { key: 'save_color', label: '实际颜色（#RRGGBB）' },
    ],
  },

  region_analysis: {
    help: '区域级分析：判断画面有没有变化、取平均颜色、或把区域截图存盘。',
    fields: [
      { key: 'mode', label: '分析方式', type: 'select', default: 'changed', options: [
        { label: '是否变化（与参考图对比）', value: 'changed' },
        { label: '平均颜色', value: 'average_color' },
        { label: '截图存盘', value: 'screenshot' },
      ] },
      { key: 'source', label: '区域范围', type: 'select', default: 'auto', options: [
        { label: '自动（绑定了窗口就用窗口，否则全屏）', value: 'auto' },
        { label: '整个屏幕', value: 'screen' },
        { label: '绑定窗口', value: 'window' },
        { label: '自定义区域', value: 'region' },
      ] },
      { key: 'region', label: '自定义区域', type: 'region', default: null, showIf: { key: 'source', equals: 'region' } },
      { key: 'reference', label: '参考图模板', type: 'template', default: '', showIf: { key: 'mode', equals: 'changed' }, hint: '与当前画面的差异超过阈值即算"有变化"' },
      { key: 'diff_threshold', label: '变化阈值', type: 'number', default: 0.02, min: 0.001, max: 1, step: 0.001, hint: '差异像素占比超过这个值算"有变化"', showIf: { key: 'mode', equals: 'changed' } },
      { key: 'save_path', label: '截图保存到', type: 'text', default: '', placeholder: '如 D:\\shots\\{{time}}.png', showIf: { key: 'mode', equals: 'screenshot' } },
      { key: 'save_value', label: '结果存入变量', type: 'text', default: 'region_value' },
    ],
    outputs: [{ key: 'save_value', label: '变化：yes/no；平均颜色：#RRGGBB' }],
  },

  // =====================================================================
  // ③ 流程
  // =====================================================================
  judge: {
    help: '按条件走「是 / 否」两条分支。左值可直接写变量名（如 found），右值写常量或 {{变量名}}。',
    fields: [
      { key: 'logic', label: '多条件关系', type: 'select', default: 'and', options: [
        { label: '全部满足（并且）', value: 'and' },
        { label: '满足任意一个（或者）', value: 'or' },
      ] },
      { key: 'condition', label: '条件', type: 'condition', default: { left: 'found', op: '==', right: 'yes' } },
      { key: 'condition2', label: '附加条件（左值留空表示不用）', type: 'condition', default: { left: '', op: '==', right: '' } },
    ],
  },

  loop: {
    help: '固定次数 / 条件 / 无限循环。循环体从「body」出口出去，走完回到本节点进入下一轮，循环结束后从「next」出口继续。',
    fields: [
      { key: 'mode', label: '循环方式', type: 'select', default: 'times', options: [
        { label: '固定次数', value: 'times' },
        { label: '条件循环（条件为真时继续）', value: 'condition' },
        { label: '无限循环', value: 'forever' },
      ] },
      { key: 'times', label: '循环次数', type: 'number', default: 10, min: 1, max: 1000000, showIf: { key: 'mode', equals: 'times' } },
      { key: 'condition', label: '继续条件', type: 'condition', default: { left: 'found', op: '==', right: 'yes' }, showIf: { key: 'mode', equals: 'condition' } },
      { key: 'max_iterations', label: '最大轮数（安全阀）', type: 'number', default: 1000, min: 1, max: 10000000, hint: '条件/无限循环必须设上限，避免脚本卡死', showIf: { key: 'mode', in: ['condition', 'forever'] } },
      { key: 'interval_ms', label: '每轮间隔', type: 'number', default: 0, min: 0, max: 3600000, hint: '毫秒。0 表示不额外等待' },
      { key: 'index_var', label: '当前轮次存入变量', type: 'text', default: '', hint: '从 1 开始计数，可在循环体里用 {{变量名}} 引用' },
    ],
    outputs: [{ key: 'index_var', label: '当前第几轮（从 1 开始）' }],
  },

  delay: {
    help: '无条件等待指定时间。期间可暂停 / 可停止。',
    fields: [
      { key: 'ms', label: '等待时长', type: 'number', default: 1000, min: 0, max: 3600000, hint: '毫秒' },
    ],
  },

  wait: {
    help: '等到条件满足再继续；超时后按设置继续或终止。轮询间隔固定 200ms。',
    fields: [
      { key: 'mode', label: '等待什么', type: 'select', default: 'image', options: [
        { label: '等图片出现', value: 'image' },
        { label: '等颜色出现', value: 'color' },
        { label: '等像素颜色匹配', value: 'pixel' },
        { label: '等变量满足条件', value: 'variable' },
        { label: '等窗口出现', value: 'window' },
      ] },
      { key: 'template', label: '识别模板', type: 'template', default: '', showIf: { key: 'mode', equals: 'image' } },
      { key: 'threshold', label: '相似度阈值', type: 'number', default: 0.85, min: 0.3, max: 1, step: 0.01, showIf: { key: 'mode', equals: 'image' } },
      { key: 'color', label: '目标颜色', type: 'color', default: '#ff0000', showIf: { key: 'mode', in: ['color', 'pixel'] } },
      { key: 'tolerance', label: '容差', type: 'number', default: 12, min: 0, max: 255, showIf: { key: 'mode', in: ['color', 'pixel'] } },
      { key: 'region', label: '检测区域', type: 'region', default: null, showIf: { key: 'mode', equals: 'color' } },
      { key: 'x', label: 'X 坐标', type: 'number', default: 0, showIf: { key: 'mode', equals: 'pixel' } },
      { key: 'y', label: 'Y 坐标', type: 'number', default: 0, showIf: { key: 'mode', equals: 'pixel' } },
      { key: 'condition', label: '等待条件', type: 'condition', default: { left: 'found', op: '==', right: 'yes' }, showIf: { key: 'mode', equals: 'variable' } },
      { key: 'title', label: '窗口标题关键字', type: 'text', default: '', showIf: { key: 'mode', equals: 'window' } },
      { key: 'timeout_ms', label: '超时', type: 'number', default: 15000, min: 0, max: 3600000, hint: '毫秒。0 表示一直等（不推荐）' },
      { key: 'on_timeout', label: '超时后', type: 'select', default: 'continue', options: TIMEOUT_ON },
      { key: 'save_found', label: '结果存入变量', type: 'text', default: 'wait_ok' },
    ],
    outputs: [{ key: 'save_found', label: '是否在超时前满足（yes/no）' }],
  },

  terminate: {
    help: '主动终止。可只结束当前循环、结束当前脚本（子脚本返回调用方），或整个工作流停止。',
    fields: [
      { key: 'level', label: '终止范围', type: 'select', default: 'workflow', options: [
        { label: '结束当前循环这一轮（相当于 break）', value: 'loop' },
        { label: '结束当前脚本（子脚本返回调用方）', value: 'script' },
        { label: '终止整个工作流', value: 'workflow' },
      ] },
      { key: 'message', label: '结束原因（写进日志）', type: 'text', default: '', placeholder: '如：检测到异常颜色' },
    ],
  },

  // =====================================================================
  // ④ 工具
  // =====================================================================
  record: {
    help: '一段录制的键鼠操作，可按速度整体回放。用「拆分」按钮可摊成普通节点继续编辑。',
    fields: [
      { key: 'speed', label: '回放速度', type: 'number', default: 1, min: 0.1, max: 10, step: 0.1, hint: '2 表示两倍速' },
      { key: 'repeat', label: '重复次数', type: 'number', default: 1, min: 1, max: 1000 },
    ],
  },

  autoclick: {
    help: '在固定坐标按指定节奏连点 N 次。整个过程可暂停、可停止。',
    fields: [
      { key: 'x', label: 'X 坐标', type: 'number', default: 0, min: -100000, max: 100000 },
      { key: 'y', label: 'Y 坐标', type: 'number', default: 0, min: -100000, max: 100000 },
      { key: 'button', label: '按键', type: 'select', options: BUTTONS, default: 'left' },
      { key: 'count', label: '点击次数', type: 'number', default: 10, min: 1, max: 100000 },
      { key: 'interval_ms', label: '点击间隔', type: 'number', default: 100, min: 0, max: 600000, hint: '毫秒，两次点击之间' },
    ],
  },

  script_call: {
    help: '执行本文件里的另一个脚本（子脚本）。脚本之间不允许互相调用成环。',
    fields: [
      { key: 'script_id', label: '要调用的脚本', type: 'text', default: '', hint: '在属性面板里点「选择脚本」挑选' },
      { key: 'name', label: '显示名', type: 'text', default: '' },
    ],
  },

  external_tool: {
    help: '调用外部能力：启动程序、请求 HTTP 接口。返回值可存进变量。',
    fields: [
      { key: 'mode', label: '调用方式', type: 'select', default: 'program', options: [
        { label: '运行程序', value: 'program' },
        { label: 'HTTP 请求', value: 'http' },
      ] },
      { key: 'path', label: '程序路径', type: 'text', default: '', placeholder: '如 notepad.exe 或 D:\\tools\\x.exe', showIf: { key: 'mode', equals: 'program' } },
      { key: 'args', label: '命令行参数', type: 'text', default: '', showIf: { key: 'mode', equals: 'program' } },
      { key: 'cwd', label: '工作目录', type: 'text', default: '', showIf: { key: 'mode', equals: 'program' } },
      { key: 'wait', label: '等待程序结束', type: 'switch', default: false, showIf: { key: 'mode', equals: 'program' } },
      { key: 'url', label: 'URL', type: 'text', default: '', placeholder: 'https://…', showIf: { key: 'mode', equals: 'http' } },
      { key: 'method', label: '请求方法', type: 'select', default: 'GET', options: [
        { label: 'GET', value: 'GET' }, { label: 'POST', value: 'POST' },
        { label: 'PUT', value: 'PUT' }, { label: 'DELETE', value: 'DELETE' },
      ], showIf: { key: 'mode', equals: 'http' } },
      { key: 'headers', label: '请求头', type: 'textarea', default: '', placeholder: '每行一条：Content-Type: application/json', showIf: { key: 'mode', equals: 'http' } },
      { key: 'body', label: '请求体', type: 'textarea', default: '', showIf: { key: 'mode', equals: 'http' } },
      { key: 'timeout_ms', label: '超时', type: 'number', default: 10000, min: 100, max: 600000 },
      { key: 'save_var', label: '输出存入变量', type: 'text', default: '', hint: '程序模式存 stdout，HTTP 模式存响应体' },
      { key: 'save_code', label: '状态码存入变量', type: 'text', default: '' },
    ],
    outputs: [
      { key: 'save_var', label: 'stdout / 响应体' },
      { key: 'save_code', label: '退出码 / HTTP 状态码' },
    ],
  },

  // =====================================================================
  // ⑤ 数据
  // =====================================================================
  variable: {
    help: '新建 / 赋值 / 删除一个运行变量。变量在整个工作流（含子脚本）内共享。',
    fields: [
      { key: 'action', label: '动作', type: 'select', default: 'set', options: [
        { label: '赋值（不存在则创建）', value: 'set' },
        { label: '读取到另一个变量', value: 'get' },
        { label: '删除', value: 'delete' },
      ] },
      { key: 'name', label: '变量名', type: 'text', default: 'my_var' },
      { key: 'value', label: '值', type: 'textarea', default: '', placeholder: '支持 {{其他变量}}；纯数字会自动识别为数字', showIf: { key: 'action', equals: 'set' } },
      { key: 'var_type', label: '类型', type: 'select', default: 'auto', options: [
        { label: '自动识别', value: 'auto' },
        { label: '文本', value: 'string' },
        { label: '数字', value: 'number' },
        { label: '真/假', value: 'bool' },
      ], showIf: { key: 'action', equals: 'set' } },
      { key: 'target', label: '复制到变量', type: 'text', default: '', showIf: { key: 'action', equals: 'get' } },
    ],
  },

  calculate: {
    help: '对数值做运算，结果存进变量。支持 + - * / %（取余）( ) 与变量引用。',
    fields: [
      { key: 'expr', label: '表达式', type: 'text', default: '1 + 1', hint: '例：({{a}} + 5) * 2' },
      { key: 'precision', label: '保留小数位', type: 'number', default: 4, min: 0, max: 10 },
      { key: 'save_var', label: '结果存入变量', type: 'text', default: 'result' },
    ],
    outputs: [{ key: 'save_var', label: '运算结果（数字）' }],
  },

  text_process: {
    help: '文本加工：拼接、截取、替换、正则提取、转数字等。结果存进变量。',
    fields: [
      { key: 'action', label: '处理方式', type: 'select', default: 'replace', options: [
        { label: '拼接', value: 'concat' },
        { label: '截取', value: 'substr' },
        { label: '替换', value: 'replace' },
        { label: '正则提取', value: 'regex' },
        { label: '转数字', value: 'to_number' },
        { label: '去空白', value: 'trim' },
        { label: '大小写', value: 'case' },
        { label: '分割取值', value: 'split' },
      ] },
      { key: 'input', label: '输入文本', type: 'textarea', default: '', placeholder: '支持 {{变量名}}' },
      { key: 'input2', label: '要拼接的文本', type: 'textarea', default: '', placeholder: '支持 {{变量名}}', showIf: { key: 'action', equals: 'concat' } },
      { key: 'start', label: '起始位置', type: 'number', default: 0, min: 0, showIf: { key: 'action', equals: 'substr' } },
      { key: 'length', label: '长度', type: 'number', default: 10, min: 0, showIf: { key: 'action', equals: 'substr' } },
      { key: 'find', label: '查找内容', type: 'text', default: '', showIf: { key: 'action', equals: 'replace' } },
      { key: 'replace', label: '替换为', type: 'text', default: '', showIf: { key: 'action', equals: 'replace' } },
      { key: 'use_regex', label: '查找内容按正则解释', type: 'switch', default: false, showIf: { key: 'action', equals: 'replace' } },
      { key: 'pattern', label: '正则表达式', type: 'text', default: '', showIf: { key: 'action', equals: 'regex' } },
      { key: 'group', label: '取第几个捕获组', type: 'number', default: 0, min: 0, showIf: { key: 'action', equals: 'regex' } },
      { key: 'mode', label: '大小写', type: 'select', default: 'upper', options: [
        { label: '转大写', value: 'upper' }, { label: '转小写', value: 'lower' },
      ], showIf: { key: 'action', equals: 'case' } },
      { key: 'sep', label: '分隔符', type: 'text', default: ',', showIf: { key: 'action', equals: 'split' } },
      { key: 'index', label: '取第几段', type: 'number', default: 0, min: 0, showIf: { key: 'action', equals: 'split' } },
      { key: 'save_var', label: '结果存入变量', type: 'text', default: 'text_result' },
    ],
    outputs: [{ key: 'save_var', label: '处理结果' }],
  },

  // =====================================================================
  // ⑥ 系统
  // =====================================================================
  window: {
    help: '按标题关键字查找窗口，并激活 / 最小化 / 移动 / 读取信息。hwnd 可存进变量供后续节点使用。',
    fields: [
      { key: 'action', label: '动作', type: 'select', default: 'activate', options: [
        { label: '查找并记录 hwnd', value: 'find' },
        { label: '激活到前台', value: 'activate' },
        { label: '最小化', value: 'minimize' },
        { label: '最大化', value: 'maximize' },
        { label: '还原', value: 'restore' },
        { label: '移动 / 改尺寸', value: 'move' },
        { label: '关闭窗口', value: 'close' },
      ] },
      { key: 'title', label: '标题关键字', type: 'text', default: '', placeholder: '留空则用当前绑定窗口' },
      { key: 'hwnd_var', label: 'hwnd 存入变量', type: 'text', default: 'hwnd' },
      { key: 'x', label: 'X', type: 'number', default: 0, showIf: { key: 'action', equals: 'move' } },
      { key: 'y', label: 'Y', type: 'number', default: 0, showIf: { key: 'action', equals: 'move' } },
      { key: 'width', label: '宽', type: 'number', default: 800, showIf: { key: 'action', equals: 'move' } },
      { key: 'height', label: '高', type: 'number', default: 600, showIf: { key: 'action', equals: 'move' } },
      { key: 'save_found', label: '是否找到存入变量', type: 'text', default: 'win_found' },
    ],
    outputs: [
      { key: 'hwnd_var', label: '窗口句柄' },
      { key: 'save_found', label: '是否找到（yes/no）' },
    ],
  },

  process: {
    help: '启动 / 结束进程，或检查某个进程是否在运行。',
    fields: [
      { key: 'action', label: '动作', type: 'select', default: 'is_running', options: [
        { label: '启动进程', value: 'start' },
        { label: '结束进程', value: 'kill' },
        { label: '是否在运行', value: 'is_running' },
      ] },
      { key: 'name', label: '进程名', type: 'text', default: '', placeholder: '如 notepad.exe', showIf: { key: 'action', in: ['kill', 'is_running'] } },
      { key: 'path', label: '程序路径', type: 'text', default: '', showIf: { key: 'action', equals: 'start' } },
      { key: 'args', label: '启动参数', type: 'text', default: '', showIf: { key: 'action', equals: 'start' } },
      { key: 'save_var', label: '结果存入变量', type: 'text', default: 'proc_result' },
      { key: 'save_pid', label: 'PID 存入变量', type: 'text', default: 'proc_pid' },
    ],
    outputs: [
      { key: 'save_var', label: '启动：PID；是否运行：yes/no' },
      { key: 'save_pid', label: '进程号' },
    ],
  },

  file: {
    help: '读写文件、复制移动删除、判断存在性、列目录。路径支持 {{变量名}}。',
    fields: [
      { key: 'action', label: '动作', type: 'select', default: 'read', options: [
        { label: '读取文本', value: 'read' },
        { label: '写入（覆盖）', value: 'write' },
        { label: '追加写入', value: 'append' },
        { label: '复制', value: 'copy' },
        { label: '移动 / 改名', value: 'move' },
        { label: '删除', value: 'delete' },
        { label: '是否存在', value: 'exists' },
        { label: '列出目录', value: 'list' },
        { label: '创建目录', value: 'mkdir' },
      ] },
      { key: 'path', label: '路径', type: 'text', default: '', placeholder: '如 D:\\data\\log.txt' },
      { key: 'path2', label: '目标路径', type: 'text', default: '', showIf: { key: 'action', in: ['copy', 'move'] } },
      { key: 'content', label: '要写入的内容', type: 'textarea', default: '', placeholder: '支持 {{变量名}}', showIf: { key: 'action', in: ['write', 'append'] } },
      { key: 'encoding', label: '编码', type: 'select', default: 'utf-8', options: [
        { label: 'UTF-8', value: 'utf-8' }, { label: 'GBK', value: 'gbk' },
      ], showIf: { key: 'action', in: ['read', 'write', 'append'] } },
      { key: 'save_var', label: '结果存入变量', type: 'text', default: 'file_result' },
    ],
    outputs: [{ key: 'save_var', label: '读取内容 / 是否存在的 yes-no / 文件数' }],
  },

  command: {
    help: '执行命令行指令并（可选）取回输出。默认走系统 cmd，也可选 PowerShell。',
    fields: [
      { key: 'shell', label: 'Shell', type: 'select', default: 'cmd', options: [
        { label: 'CMD', value: 'cmd' },
        { label: 'PowerShell', value: 'powershell' },
        { label: 'Bash', value: 'bash' },
      ] },
      { key: 'command', label: '命令', type: 'command', default: '' },
      { key: 'cwd', label: '工作目录', type: 'text', default: '' },
      { key: 'timeout_ms', label: '超时', type: 'number', default: 30000, min: 100, max: 3600000 },
      { key: 'save_var', label: '输出存入变量', type: 'text', default: 'cmd_output' },
      { key: 'save_code', label: '退出码存入变量', type: 'text', default: 'cmd_code' },
    ],
    outputs: [
      { key: 'save_var', label: '标准输出 + 标准错误' },
      { key: 'save_code', label: '退出码' },
    ],
  },
}

/** 某个节点的默认参数（字段默认值拼起来；未声明默认值的字段为 null） */
export function defaultsFor(nodeType: NodeType): Record<string, any> {
  const schema = NODE_SCHEMA[nodeType]
  const out: Record<string, any> = {}
  if (!schema) return out
  for (const f of schema.fields) {
    out[f.key] = typeof f.default === 'object' && f.default !== null ? { ...f.default } : (f.default ?? null)
  }
  return out
}

/** 字段在当前参数下是否应当显示（showIf 求值） */
export function fieldVisible(f: NodeField, params: Record<string, any>): boolean {
  const cond = f.showIf
  if (!cond) return true
  const v = params?.[cond.key]
  if (cond.equals !== undefined) return v === cond.equals
  if (cond.in !== undefined) return Array.isArray(cond.in) && cond.in.includes(v)
  if (cond.not !== undefined) return v !== cond.not
  return true
}

/** 该节点的全部字段 key（含隐藏的）——迁移补参、默认值合并用 */
export function schemaKeys(nodeType: NodeType): string[] {
  return (NODE_SCHEMA[nodeType]?.fields || []).map((f) => f.key)
}

/**
 * 把老参数补齐成新节点的完整参数集：
 *  - 老参数里有、新模式里也有的键 → **保留老值**（用户填过的东西不能丢）
 *  - 新模式里有、老参数没有的键   → 用默认值补齐
 *  - 老参数里多出来的键           → 保留（引擎可能仍认，或用于兼容）
 */
export function mergeWithDefaults(nodeType: NodeType, params: Record<string, any> | undefined): Record<string, any> {
  const base = defaultsFor(nodeType)
  const old = params && typeof params === 'object' ? params : {}
  return { ...base, ...old }
}
