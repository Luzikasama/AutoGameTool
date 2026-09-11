<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { STEP_META } from '../types'

const props = defineProps<{
  data: { stepType: string; label: string; params: Record<string, any>; once?: boolean }
  selected?: boolean
}>()

const meta = computed(() => STEP_META[props.data.stepType as keyof typeof STEP_META])

const isJudge = computed(() => props.data.stepType === 'judge')
const isTerminate = computed(() => props.data.stepType === 'terminate')

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
    case 'terminate':
      return '立即停止运行'
    default:
      return ''
  }
})
</script>

<template>
  <div class="step-node" :style="{ borderColor: selected ? 'var(--accent)' : meta.color }">
    <Handle type="target" :position="Position.Left" />
    <div class="step-icon" :style="{ background: meta.color }">{{ meta.icon }}</div>
    <div class="step-body">
      <div class="step-title">
        {{ data.label }}
        <span v-if="data.once" class="once-badge">单次</span>
      </div>
      <div class="step-summary">{{ summary }}</div>
      <div v-if="isJudge" class="branch-legend">
        <span class="branch-yes">● 成功</span>
        <span class="branch-no">● 失败</span>
      </div>
    </div>
    <template v-if="isJudge">
      <Handle type="source" id="yes" :position="Position.Right" :style="{ top: '28%' }" class="handle-yes" />
      <Handle type="source" id="no" :position="Position.Right" :style="{ top: '72%' }" class="handle-no" />
    </template>
    <Handle v-else-if="!isTerminate" type="source" :position="Position.Right" />
  </div>
</template>

<style scoped>
.step-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-panel);
  border: 1.5px solid var(--border);
  border-radius: 10px;
  min-width: 150px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.4);
  transition: border-color 0.15s;
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
  color: #f59e0b;
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
  color: #22c55e;
}
.branch-no {
  color: #ef4444;
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
