<script setup lang="ts">
/**
 * 「调用脚本」节点的子脚本挑选面板。
 *
 * 三条路：
 *  · 选一个**已有的**子脚本（同一个父脚本下的都能复用）
 *  · 新建一个空白子脚本，并立刻在新编辑器里打开
 *  · 从文件导入一份已有脚本（连同它的子脚本一起嵌进来）
 *
 * 这里只做展示与选择，防环判定等逻辑留在调用方（EditorPane）。
 */
import { NButton, NModal } from 'naive-ui'

const show = defineModel<boolean>('show', { default: false })

defineProps<{
  scripts: { id: string; name: string }[]
  /** 当前节点已选择的子脚本 id */
  current: string
}>()

const emit = defineEmits<{
  (e: 'pick', id: string): void
  (e: 'create'): void
  (e: 'import'): void
  (e: 'open', id: string): void
}>()

function pick(id: string) {
  emit('pick', id)
}
</script>

<template>
  <n-modal v-model:show="show" preset="card" title="选择要调用的子脚本" style="width: 620px; max-width: calc(100vw - 32px)">
    <p class="hint">
      子脚本会保存在**当前脚本文件内部**，跟着脚本一起走。运行时它会被就地展开执行，效果与「组合节点」基本相同，
      区别是子脚本可以单独编辑、单独导出，也能被多个脚本复用。
    </p>

    <div v-if="scripts.length" class="list">
      <div v-for="s in scripts" :key="s.id" class="row" :class="{ active: s.id === current }">
        <span class="icon">📦</span>
        <span class="name">{{ s.name }}</span>
        <span class="sid">{{ s.id }}</span>
        <n-button size="tiny" quaternary @click="emit('open', s.id)">编辑</n-button>
        <n-button size="tiny" type="primary" :disabled="s.id === current" @click="pick(s.id)">
          {{ s.id === current ? '当前' : '选择' }}
        </n-button>
      </div>
    </div>
    <p v-else class="hint">本脚本里还没有子脚本，可以直接新建一个，或从文件导入。</p>

    <div class="actions">
      <n-button size="small" @click="emit('create')">＋ 新建空白子脚本</n-button>
      <n-button size="small" @click="emit('import')">📂 从文件导入…</n-button>
      <div class="spacer" />
      <n-button size="small" @click="show = false">取消</n-button>
    </div>
  </n-modal>
</template>

<style scoped>
.hint {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.7;
  margin: 0 0 10px;
}
.list {
  max-height: 300px;
  overflow-y: auto;
  margin-bottom: 12px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: 0.15s;
}
.row:hover {
  background: var(--hover);
}
.row.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.icon {
  flex: none;
}
.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.sid {
  font-size: 11px;
  color: var(--text-dim);
  font-family: 'Cascadia Code', Consolas, monospace;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.spacer {
  flex: 1;
}
</style>
