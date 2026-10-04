<script setup lang="ts">
import { computed, inject } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { STEP_META } from '../types'

const props = defineProps<{
  data: { stepType: string; label: string; params: Record<string, any>; once?: boolean }
  selected?: boolean
}>()

/**
 * 「调用脚本」节点要判断被调用的子脚本是否还在。
 * 由编辑器 provide 进来（而不是往 data 里塞一个字段）—— data 会进撤销快照，
 * 塞进去就会因为"扫描结果变了"产生一堆假的历史记录。
 */
const scriptExists = inject<(id: string) => boolean>('scriptExists', () => true)

const meta = computed(() => STEP_META[props.data.stepType as keyof typeof STEP_META])

const isJudge = computed(() => props.data.stepType === 'judge')
const isTerminate = computed(() => props.data.stepType === 'terminate')
const isScriptCall = computed(() => props.data.stepType === 'script_call')

/** 子脚本缺失（被删掉 / 导入时没带上）——节点上要显示出来，别让问题藏到运行时 */
const scriptMissing = computed(() => {
  if (!isScriptCall.value) return false
  const id = String(props.data.params?.script_id || '')
  return !!id && !scriptExists(id)
})

const summary = computed(() => {
  const p = props.data.params || {}
  switch (props.data.stepType) {
    case 'delay':
      return `${p.ms ?? 1000} ms`
    case 'find_image':
      return p.template ? `模板：${p.template}` : '未选择模板'
    case 'click':
      return `(${p.x ?? 0}, ${p.y ?? 0}) · ${p.button ?? 'left'}`
    case 'key':
      return p.key || '未设置按键'
    case 'text':
      return p.text ? `"${p.text}"` : '空文本'
    case 'judge':
      return p.template ? `判断：${p.template}` : '判断：未选择模板'
    case 'macro':
      return `${(p.events || []).length} 个事件 · x${p.speed ?? 1}`
    case 'autoclick':
      return `(${p.x ?? 0}, ${p.y ?? 0}) · ${p.count ?? 10} 次 · ${p.interval_ms ?? 100}ms`
    case 'script_call': {
      if (!p.script_id) return '未选择子脚本'
      const name = p.name || p.script_id
      return scriptMissing.value ? `脚本不存在：${name}` : `调用：${name}`
    }
    case 'terminate':
      return '立即停止运行'
    default:
      return ''
  }
})
</script>

<template>
  <!-- 步骤类型色走 CSS 变量下发，而不是直接写在 border-color 上：
       内联样式优先级高于样式表，一旦写死就没法用 .is-selected 类覆盖了。 -->
  <div
    class="step-node"
    :class="{ 'is-selected': selected, 'is-broken': scriptMissing }"
    :style="{ '--node-color': meta.color }"
  >
    <Handle type="target" :position="Position.Left" />
    <div class="step-icon" :style="{ background: meta.color }">{{ meta.icon }}</div>
    <div class="step-body">
      <div class="step-title">
        {{ data.label }}
        <span v-if="data.once" class="once-badge">单次</span>
      </div>
      <div class="step-summary" :class="{ broken: scriptMissing }">{{ summary }}</div>
      <div v-if="isJudge" class="branch-legend">
        <span class="branch-yes">● 成功</span>
        <span class="branch-no">● 失败</span>
      </div>
    </div>
    <!-- 选中角标：放在节点框外右上角，用绝对定位，不参与布局（否则会改节点尺寸、
         触发 Vue Flow 的尺寸重测，节点会自己抖一下）。 -->
    <span v-if="selected" class="sel-badge" aria-hidden="true">✓</span>
    <!-- 子脚本缺失角标：同样绝对定位 -->
    <span v-if="scriptMissing" class="warn-badge" aria-hidden="true">!</span>
    <template v-if="isJudge">
      <Handle type="source" id="yes" :position="Position.Right" :style="{ top: '28%' }" class="handle-yes" />
      <Handle type="source" id="no" :position="Position.Right" :style="{ top: '72%' }" class="handle-no" />
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
/* ---------- 选中反馈 ----------
   只换边框颜色在深色底上根本认不出来（尤其是本来边框就有步骤类型色的时候）。
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
   错误信息在日志里一闪而过，用户根本对不上是哪个节点。 */
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
.handle-yes {
  background: #22c55e !important;
  border-color: #0a3d20 !important;
}
.handle-no {
  background: #ef4444 !important;
  border-color: #4c1111 !important;
}
</style>
