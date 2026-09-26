import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 界面外观（目前只有自定义背景）。
 *
 * 为什么存 localStorage 而不是引擎配置：
 *  - 背景是**这台电脑这个浏览器**的显示偏好，跟脚本内容无关，写进 .agflow 会让
 *    "换台机器打开同一个脚本"也跟着变样
 *  - 图片是 base64，几十到几百 KB，走 HTTP 每次启动都传一遍不划算
 * 所以：不上传引擎、不写进工程文件，只在本机浏览器里留着。
 */
const KEY = 'agt.bg'

export const useUiStore = defineStore('ui', () => {
  // data URL（已在裁剪步骤里按屏幕比例裁好）
  const bgImage = ref('')
  // 背景图不透明度 0.05~1
  const bgOpacity = ref(0.5)
  /** 最近一次持久化失败的提示（配额不足等），供设置面板展示 */
  const bgWarn = ref('')

  function load() {
    try {
      const raw = localStorage.getItem(KEY)
      if (!raw) return
      const j = JSON.parse(raw)
      if (typeof j?.image === 'string') bgImage.value = j.image
      if (typeof j?.opacity === 'number') bgOpacity.value = Math.min(1, Math.max(0.05, j.opacity))
    } catch {
      /* 存储损坏时用默认值，不影响使用 */
    }
  }

  /** 持久化；配额不足时返回 false 并给出提示（调用方可降质重试） */
  function save(image: string, opacity: number): boolean {
    try {
      localStorage.setItem(KEY, JSON.stringify({ image, opacity }))
      bgWarn.value = ''
      return true
    } catch (e: any) {
      bgWarn.value =
        '背景图保存失败（本机浏览器存储空间不足）：' +
        (e?.name === 'QuotaExceededError' ? '图片太大，请换一张更小的' : String(e?.message || e))
      return false
    }
  }

  function setBackground(image: string, opacity = bgOpacity.value) {
    bgImage.value = image
    bgOpacity.value = opacity
    save(image, opacity)
  }

  /**
   * 应用一张背景图，并尝试持久化。
   * 返回 false 表示"图能用但存不下"（localStorage 配额不足），
   * 调用方据此降低画质重试——所以这里不直接弹提示，由调用方决定措辞。
   */
  function applyImage(image: string): boolean {
    bgImage.value = image
    return save(image, bgOpacity.value)
  }

  function setOpacity(opacity: number) {
    bgOpacity.value = Math.min(1, Math.max(0.05, opacity))
    if (bgImage.value) save(bgImage.value, bgOpacity.value)
  }

  function clearBackground() {
    bgImage.value = ''
    bgWarn.value = ''
    try {
      localStorage.removeItem(KEY)
    } catch {
      /* 忽略 */
    }
  }

  load()

  return { bgImage, bgOpacity, bgWarn, setBackground, applyImage, setOpacity, clearBackground }
})
