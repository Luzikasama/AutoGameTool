import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LogEntry } from '../types'

export const useProjectStore = defineStore('project', () => {
  const flowName = ref('未命名脚本')
  const repeat = ref(1)
  const inputMode = ref<'real' | 'simulated'>('real')
  const boundWindow = ref<{ hwnd: number; title: string } | null>(null)
  const logs = ref<LogEntry[]>([])
  const running = ref(false)
  // 暂停：与停止不同，暂停保留执行位置，继续后从原地接着跑
  const paused = ref(false)

  function addLog(e: LogEntry) {
    logs.value.push(e)
    if (logs.value.length > 500) logs.value.shift()
  }

  function clearLogs() {
    logs.value = []
  }

  return { flowName, repeat, inputMode, boundWindow, logs, running, paused, addLog, clearLogs }
})
