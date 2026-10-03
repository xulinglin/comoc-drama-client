/**
 * 视频解码异常监听工具
 * 用于在视频处于播放状态但长时间未推进 currentTime（常见于编码不兼容、解码失败、容器损坏）
 * 时触发 onError 回调，避免出现"画面卡住但状态仍是 playing"的假象。
 */

const STALL_FRAMES = 3          // 连续检测到停滞的次数阈值
const STALL_EPSILON = 0.005     // 视为停滞的最大时间差（秒）
const FALLBACK_INTERVAL_MS = 200 // 不支持 requestVideoFrameCallback 时的轮询间隔

/**
 * 监听视频是否持续解码出帧
 * @param {HTMLVideoElement} video 目标视频元素
 * @param {Function} onError 异常回调，仅在解码停滞达到阈值时触发一次
 * @returns {Function} stop 函数，调用后取消监听并释放资源
 */
export function watchForDecodedVideoFrame(video, onError) {
  if (!video || typeof onError !== 'function') return () => {}

  const supportsRVF = typeof video.requestVideoFrameCallback === 'function'
  let rafId = 0
  let timerId = 0
  let lastTime = -1
  let stallCount = 0
  let fired = false

  function check() {
    if (fired) return
    // 暂停或已结束时复位统计，不视为异常
    if (video.paused || video.ended) {
      lastTime = -1
      stallCount = 0
      return false
    }
    const current = video.currentTime
    if (lastTime >= 0 && Math.abs(current - lastTime) < STALL_EPSILON) {
      stallCount += 1
      if (stallCount >= STALL_FRAMES) {
        fired = true
        try { onError() } catch (_) { /* 忽略回调异常 */ }
        return true
      }
    } else {
      stallCount = 0
    }
    lastTime = current
    return false
  }

  function onFrame() {
    if (check()) return
    rafId = video.requestVideoFrameCallback(onFrame)
  }

  function onInterval() {
    check()
  }

  if (supportsRVF) {
    rafId = video.requestVideoFrameCallback(onFrame)
  } else {
    timerId = setInterval(onInterval, FALLBACK_INTERVAL_MS)
  }

  return () => {
    if (rafId && typeof video.cancelVideoFrameCallback === 'function') {
      video.cancelVideoFrameCallback(rafId)
    }
    if (timerId) clearInterval(timerId)
    rafId = 0
    timerId = 0
  }
}
