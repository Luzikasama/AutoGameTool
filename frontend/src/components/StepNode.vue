<script setup lang="ts">
import { computed, inject } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { BRANCH_BODY, BRANCH_NEXT, BRANCH_NO, BRANCH_YES, CATEGORY_META, GROUP_META, GROUP_TYPE, NODE_META } from '../types'
import { UNARY_OPS } from '../lib/nodeSchema'

const props = defineProps<{
  data: { nodeType: string; label: string; params: Record<string, any>; once?: boolean }
  selected?: boolean
}>()

/**
 * 「调用脚本」节点要判断被调用的子脚本是否还在。
 * 由编辑器 provide 进来（而不是往 data 里塞一个字段）—— data 会进撤销快照，
 * 塞进去就会因为"扫描结果变了"产生一堆假的历史记录。
 */
const scriptExists = inject<(id: string) => boolean>('scriptExists', () => true)

/** 组合节点：不属于六大类，用一整套独立的外观（配色 + 图标 + 双击提示） */
const isGroup = computed(() => props.data.nodeType === GROUP_TYPE)
const meta = computed(() =>
  isGroup.value ? undefined : NODE_META[props.data.nodeType as keyof typeof NODE_META],
)
const cat = computed(() => (meta.value ? CATEGORY_META[meta.value.category] : undefined))
const color = computed(() => (isGroup.value ? GROUP_META.color : cat.value?.color || '#888'))

const isJudge = computed(() => props.data.nodeType === 'judge')
const isLoop = computed(() => props.data.nodeType === 'loop')
/** 终止节点没有出口：它的作用就是断在这里 */
const isTerminate = computed(() => props.data.nodeType === 'terminate')
const isScriptCall = computed(() => props.data.nodeType === 'script_call')

/** 组合节点内部有多少个节点（内部图存在 params.nodes 里） */
const groupSize = computed(() => (props.data.params?.nodes || []).length)

/** 子脚本缺失（被删掉 / 导入时没带上）——节点上要显示出来，别让问题藏到运行时 */
const scriptMissing = computed(() => {
  if (!isScriptCall.value) return false
  const id = String(props.data.params?.script_id || '')
  return !!id && !scriptExists(id)
})

/** 条件的紧凑写法：`found == yes` */
function condText(c: any): string {
  if (!c || typeof c !== 'object') return '未设置条件'
  const left = String(c.left ?? '').trim() || '?'
  const op = String(c.op ?? '==')
  if (UNARY_OPS.includes(op)) return `${left} ${op}`
  const right = String(c.right ?? '')
  return `${left} ${op} ${right}`
}

const summary = computed(() => {
  const p = props.data.params || {}
  switch (props.data.nodeType) {
    case GROUP_TYPE:
      return groupSize.value ? `${groupSize.value} 个节点 · 双击编辑` : '（空）双击编辑'
    case 'mouse': {
      const act = String(p.action || 'click')
      const label: Record<string, string> = {
        click: '单击', double_click: '双击', right_click: '右键',
        middle_click: '中键', move: '移动', down: '按下', up: '松开', wheel: '滚轮',
      }
      if (act === 'wheel') return `滚轮 (${p.dx ?? 0}, ${p.dy ?? 0})`
      return `${label[act] || act} (${p.x ?? 0}, ${p.y ?? 0})`
    }
    case 'keyboard': {
      const act: Record<string, string> = { press: '按一下', down: '按下', up: '松开' }
      return `${act[String(p.action || 'press')] || ''} ${p.keys || '未设置按键'}`.trim()
    }
    case 'text_input':
      return p.text ? `"${String(p.text).slice(0, 14)}"` : '空文本'
    case 'clipboard': {
      const a: Record<string, string> = { set: '写入剪贴板', get: '读取剪贴板', clear: '清空剪贴板' }
      return a[String(p.action || 'set')] || ''
    }
    case 'find_image':
      return p.template ? `模板：${p.template}` : '未选择模板'
    case 'ocr':
      return p.source === 'region' ? '识别自定义区域' : '识别画面文字'
    case 'color_check':
      return `${p.color || '#000000'} ±${p.tolerance ?? 0}`
    case 'pixel_check':
      return `(${p.x ?? 0}, ${p.y ?? 0}) · ${p.color || '#000000'}`
    case 'region_analysis': {
      const m: Record<string, string> = { changed: '判断是否变化', average_color: '取平均颜色', screenshot: '截图存盘' }
      return m[String(p.mode || 'changed')] || ''
    }
    case 'judge': {
      const c1 = condText(p.condition)
      const c2 = p.condition2 && String(p.condition2.left ?? '').trim() ? condText(p.condition2) : ''
      if (!c2) return c1
      const joiner = p.logic === 'or' ? ' 或 ' : ' 且 '
      return `${c1}${joiner}${c2}`
    }
    case 'loop': {
      const mode = String(p.mode || 'times')
      if (mode === 'times') return `固定 ${p.times ?? 1} 次`
      if (mode === 'condition') return `条件：${condText(p.condition)}`
      return `无限循环（上限 ${p.max_iterations ?? 0}）`
    }
    case 'delay':
      return `${p.ms ?? 1000} ms`
    case 'wait': {
      const m: Record<string, string> = {
        image: '等图片出现', color: '等颜色出现', pixel: '等像素匹配',
        variable: '等变量条件', window: '等窗口出现',
      }
      return m[String(p.mode || 'image')] || ''
    }
    case 'terminate': {
      const l: Record<string, string> = { loop: '结束当前循环', script: '结束当前脚本', workflow: '终止整个工作流' }
      return l[String(p.level || 'workflow')] || ''
    }
    case 'record':
      return `${(p.events || []).length} 个事件 · x${p.speed ?? 1}`
    case 'autoclick':
      return `(${p.x ?? 0}, ${p.y ?? 0}) · ${p.count ?? 10} 次 · ${p.interval_ms ?? 100}ms`
    case 'script_call': {
      if (!p.script_id) return '未选择子脚本'
      const name = p.name || p.script_id
      return scriptMissing.value ? `脚本不存在：${name}` : `调用：${name}`
    }
    case 'external_tool':
      return p.mode === 'http' ? `${p.method || 'GET'} ${String(p.url || '').slice(0, 24)}` : String(p.path || '未设置程序')
    case 'variable':
      return p.action === 'set' ? `${p.name || '?'} = ${String(p.value ?? '').slice(0, 12)}` : `${p.name || '?'}`
    case 'calculate':
      return `${String(p.expr || '').slice(0, 18)} → ${p.save_var || '?'}`
    case 'text_process':
      return `${p.action || ''} → ${p.save_var || '?'}`
    case 'window':
      return `${p.action || ''} ${String(p.title || '').slice(0, 14)}`.trim()
    case 'process':
      return `${p.action || ''} ${String(p.name || p.path || '').slice(0, 14)}`.trim()
    case 'file':
      return `${p.action || ''} ${String(p.path || '').slice(0, 16)}`.trim()
    case 'command':
      return `${p.shell || 'cmd'}: ${String(p.command || '').slice(0, 18)}`
    default:
      return ''
  }
})

const icon = computed(() => (isGroup.value ? GROUP_META.icon : meta.value?.icon || '❓'))
const title = computed(
  () =>
    (isGroup.value ? String(props.data.params?.name || '') : props.data.label) ||
    (isGroup.value ? GROUP_META.label : meta.value?.label) ||
    props.data.nodeType,
)
</script>

<template>
  <!-- 节点配色走 CSS 变量下发，而不是直接写在 border-color 上：
       内联样式优先级高于样式表，一旦写死就没法用 .is-selected 类覆盖了。 -->
  <div
    class="step-node"
    :class="{ 'is-selected': selected, 'is-broken': scriptMissing, 'is-group': isGroup }"
    :style="{ '--node-color': color }"
  >
    <Handle type="target" :position="Position.Left" />
    <div class="step-icon" :style="{ background: color }">{{ icon }}</div>
    <div class="step-body">
      <div class="step-title">
        {{ title }}
        <span v-if="data.once" class="once-badge">单次</span>
      </div>
      <div class="step-summary" :class="{ broken: scriptMissing }">{{ summary }}</div>
      <div v-if="isJudge" class="branch-legend">
        <span class="branch-yes">● 是</span>
        <span class="branch-no">● 否</span>
      </div>
      <div v-else-if="isLoop" class="branch-legend">
        <span class="branch-body">● 循环体</span>
        <span class="branch-next">● 结束</span>
      </div>
    </div>
    <!-- 选中角标：放在节点框外右上角，用绝对定位，不参与布局（否则会改节点尺寸、
         触发 Vue Flow 的尺寸重测，节点会自己抖一下）。 -->
    <span v-if="selected" class="sel-badge" aria-hidden="true">✓</span>
    <!-- 子脚本缺失角标：同样绝对定位 -->
    <span v-if="scriptMissing" class="warn-badge" aria-hidden="true">!</span>

    <template v-if="isJudge">
      <Handle type="source" :id="BRANCH_YES" :position="Position.Right" :style="{ top: '28%' }" class="handle-yes" />
      <Handle type="source" :id="BRANCH_NO" :position="Position.Right" :style="{ top: '72%' }" class="handle-no" />
    </template>
    <template v-else-if="isLoop">
      <Handle type="source" :id="BRANCH_BODY" :position="Position.Right" :style="{ top: '28%' }" class="handle-yes" />
      <Handle type="source" :id="BRANCH_NEXT" :position="Position.Right" :style="{ top: '72%' }" class="handle-no" />
    </template>
    <Handle v-else-if="!isTerminate" type="source" :position="Position.Right" />
  </div>
</template>

<style scoped>
.step-node {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-panel);
  border: 1.5px solid var(--node-color, var(--border));
  border-radius: 10px;
  min-width: 150px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.28);
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
/* ---------- 组合节点 ----------
   它是"装了一段流程的容器"，所以刻意长得和普通节点不一样：虚线外框 + 双层投影，
   暗示"这里面还有一层"。颜色单独给（不属于六大类）。 */
.step-node.is-group {
  border-style: dashed;
  border-width: 2px;
  background: var(--bg-soft, var(--bg-panel));
  box-shadow:
    0 0 0 3px rgba(236, 72, 153, 0.12),
    0 2px 10px rgba(0, 0, 0, 0.28);
}
.step-node.is-group .step-icon {
  border-radius: 7px 7px 7px 0;
}
.step-node.is-group .step-title {
  color: #ec4899;
}
/* ---------- 选中反馈 ----------
   只换边框颜色在深色底上根本认不出来（尤其是本来边框就有节点类型色的时候）。
   这里一次性叠四层信号，保证「一眼看出来选中了谁」：
     1) 边框 + 标题文字换成主题强调色
     2) 紧贴的 2px 实心光环（box-shadow，不占布局、不改节点尺寸）
     3) 外圈柔光，多选时相邻节点的光环能连成一片，整体选区一目了然
     4) 右上角 ✓ 角标
   全部用 box-shadow / 绝对定位实现，**刻意不改 width/height/border-width**——
   那会改变节点外框尺寸，触发 Vue Flow 的尺寸重测，节点选中瞬间会自己抖一下。 */
.step-node.is-selected {
  border-color: var(--accent);
  box-shadow:
    0 0 0 2px var(--accent),
    0 0 0 7px var(--accent-soft),
    0 6px 20px rgba(0, 0, 0, 0.45);
}
.step-node.is-selected .step-title {
  color: var(--accent);
}
.sel-badge {
  position: absolute;
  top: -9px;
  right: -9px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.45);
  pointer-events: none;
}
/* ---------- 子脚本缺失 ----------
   被调用的子脚本不存在时，节点必须自己"喊出来"：否则这个问题会一直藏到运行那一刻，
   错误日志在日志里一闪而过，用户根本对不上是哪个节点。 */
.step-node.is-broken {
  border-color: var(--danger);
  border-style: dashed;
}
.step-summary.broken {
  color: var(--danger);
}
.warn-badge {
  position: absolute;
  top: -9px;
  left: -9px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--danger);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.45);
  pointer-events: none;
}
.step-icon {
  width: 26px;
  height: 26px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 7px;
  font-size: 14px;
}
.step-body {
  overflow: hidden;
}
.step-title {
  font-weight: 600;
  font-size: 13px;
  line-height: 1.2;
  display: flex;
  align-items: center;
  gap: 6px;
}
.step-summary {
  font-size: 11px;
  color: var(--text-dim);
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.once-badge {
  font-size: 10px;
  font-weight: 600;
  color: var(--warn);
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: 4px;
  padding: 0 4px;
}
.branch-legend {
  display: flex;
  gap: 8px;
  margin-top: 3px;
  font-size: 10px;
}
.branch-yes {
  color: var(--ok);
}
.branch-no {
  color: var(--danger);
}
.branch-body {
  color: #06b6d4;
}
.branch-next {
  color: var(--text-dim);
}
.handle-yes {
  background: #22c55e !important;
  border-color: #0a3d20 !important;
}
.handle-no {
  background: #ef4444 !important;
  border-color: #4c1111 !important;
}
</style>
