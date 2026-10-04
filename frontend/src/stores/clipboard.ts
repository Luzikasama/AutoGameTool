/**
 * 编辑器之间的剪贴板。
 *
 * 刻意做成**应用内**剪贴板（不是系统剪贴板）：粘贴的目标是另一张画布，
 * 中间那一步不需要经过操作系统的文本剪贴板，也就不会把用户的文本内容冲掉
 * （系统剪贴板只有纯文本，写进去的是 JSON 的话，用户切到别处一粘贴就是一坨代码）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { clone, type ClipFragment } from '../lib/clipFragment'

export const useClipboardStore = defineStore('clipboard', () => {
  const fragment = ref<ClipFragment | null>(null)
  /** 来源脚本名，用于粘贴后的提示 */
  const source = ref('')

  const hasContent = computed(() => !!fragment.value?.nodes?.length)
  const count = computed(() => fragment.value?.nodes?.length || 0)

  function put(frag: ClipFragment | null, from: string) {
    fragment.value = frag ? clone(frag) : null
    source.value = from
  }

  function take(): ClipFragment | null {
    return fragment.value ? clone(fragment.value) : null
  }

  function clear() {
    fragment.value = null
    source.value = ''
  }

  return { fragment, source, hasContent, count, put, take, clear }
})
