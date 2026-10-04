import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LogEntry } from '../types'

/**
 * 运行日志与运行状态。
 *
 * 这两个是**整个应用一份**的：引擎只跑一个流程，日志面板也只有一个。
 * 各个脚本自己的内容（名称、循环轮数、节点、历史）不在这里 —— 见 stores/docs.ts。
 */
export const useProjectStore = defineStore('project', () => {
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

  return { logs, running, paused, addLog, clearLogs }
})
