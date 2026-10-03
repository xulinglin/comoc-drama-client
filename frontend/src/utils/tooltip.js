/**
 * 全局 tooltip 浮层管理器
 *
 * 用法保持不变：给元素加 data-tooltip="提示文字" 即可。
 * 可选方向：data-tooltip-pos="top|bottom|left|right"（仅作为优先方向，空间不足时自动翻转）
 *
 * 与早期纯 CSS ::after 方案的区别：
 *  - tooltip 渲染到 <body> 末尾，position: fixed，不会被任何祖先的 overflow:hidden 裁切；
 *  - 根据视口剩余空间自动翻转上下、左右贴边，避免溢出屏幕。
 */

const FLOATING_CLASS = 'tooltip-floating'
const PADDING = 8          // tooltip 与触发元素的间距
const VIEWPORT_MARGIN = 8  // 距视口边缘的安全距离

let floatingEl = null
let hideTimer = 0
let showTimer = 0
let currentTrigger = null

function ensureFloating() {
  if (floatingEl) return floatingEl
  floatingEl = document.createElement('div')
  floatingEl.className = FLOATING_CLASS
  floatingEl.setAttribute('role', 'tooltip')
  floatingEl.style.position = 'fixed'
  floatingEl.style.zIndex = '99999'
  floatingEl.style.pointerEvents = 'none'
  floatingEl.style.opacity = '0'
  floatingEl.style.left = '0'
  floatingEl.style.top = '0'
  document.body.appendChild(floatingEl)
  return floatingEl
}

function getText(el) {
  const text = el.getAttribute('data-tooltip') || ''
  return text.trim()
}

function positionFloating(trigger, preferredPos) {
  const el = ensureFloating()
  const rect = trigger.getBoundingClientRect()
  // 先让浮层渲染出来才能拿到尺寸
  el.style.left = '0px'
  el.style.top = '0px'
  el.style.transform = 'none'
  const tipRect = el.getBoundingClientRect()
  const tipW = tipRect.width
  const tipH = tipRect.height
  const vw = window.innerWidth
  const vh = window.innerHeight

  const spaceTop = rect.top
  const spaceBottom = vh - rect.bottom
  const spaceLeft = rect.left
  const spaceRight = vw - rect.right

  let pos = preferredPos || 'bottom'
  // 优先方向放不下就翻转
  if (pos === 'bottom' && spaceBottom < tipH + PADDING + VIEWPORT_MARGIN && spaceTop > spaceBottom) pos = 'top'
  else if (pos === 'top' && spaceTop < tipH + PADDING + VIEWPORT_MARGIN && spaceBottom > spaceTop) pos = 'bottom'
  else if (pos === 'right' && spaceRight < tipW + PADDING + VIEWPORT_MARGIN && spaceLeft > spaceRight) pos = 'left'
  else if (pos === 'left' && spaceLeft < tipW + PADDING + VIEWPORT_MARGIN && spaceRight > spaceLeft) pos = 'right'
  // 上下方向空间都不够，左右又没指定时，回退到空间更大的一侧
  if ((pos === 'top' || pos === 'bottom') && Math.max(spaceTop, spaceBottom) < tipH + PADDING + VIEWPORT_MARGIN) {
    pos = spaceTop >= spaceBottom ? 'top' : 'bottom'
  }

  let left = 0
  let top = 0
  if (pos === 'top' || pos === 'bottom') {
    // 水平居中触发元素，再贴边到视口内
    left = rect.left + rect.width / 2 - tipW / 2
    left = Math.max(VIEWPORT_MARGIN, Math.min(vw - tipW - VIEWPORT_MARGIN, left))
    top = pos === 'bottom' ? rect.bottom + PADDING : rect.top - tipH - PADDING
  } else {
    // 左右方向：垂直居中并贴边
    top = rect.top + rect.height / 2 - tipH / 2
    top = Math.max(VIEWPORT_MARGIN, Math.min(vh - tipH - VIEWPORT_MARGIN, top))
    left = pos === 'right' ? rect.right + PADDING : rect.left - tipW - PADDING
  }

  el.style.left = `${Math.round(left)}px`
  el.style.top = `${Math.round(top)}px`
  el.dataset.pos = pos
}

function show(trigger) {
  const text = getText(trigger)
  if (!text) return hide()
  window.clearTimeout(hideTimer)
  window.clearTimeout(showTimer)
  currentTrigger = trigger
  const el = ensureFloating()
  el.textContent = text
  const preferred = trigger.getAttribute('data-tooltip-pos') || ''
  positionFloating(trigger, preferred)
  // 强制重排，让 transform 过渡生效
  requestAnimationFrame(() => { el.style.opacity = '1' })
}

function hide() {
  if (!floatingEl) return
  window.clearTimeout(showTimer)
  hideTimer = window.setTimeout(() => {
    if (floatingEl) {
      floatingEl.style.opacity = '0'
      floatingEl.textContent = ''
      floatingEl.removeAttribute('data-pos')
    }
    currentTrigger = null
  }, 60)
}

function onEnter(event) {
  const target = event.target.closest?.('[data-tooltip]')
  if (!target || target === currentTrigger) return
  window.clearTimeout(showTimer)
  window.clearTimeout(hideTimer)
  // 轻微延迟，避免鼠标快速划过时闪烁
  showTimer = window.setTimeout(() => show(target), 80)
}

function onLeave(event) {
  const target = event.target.closest?.('[data-tooltip]')
  if (!target) return
  // 如果鼠标移到 tooltip 自身（虽然 pointer-events:none 不可能），也忽略
  hide()
}

function onScroll() {
  if (!currentTrigger) return
  if (!currentTrigger.isConnected) { hide(); return }
  positionFloating(currentTrigger, currentTrigger.getAttribute('data-tooltip-pos') || '')
}

let installed = false
export function installTooltip() {
  if (installed) return
  installed = true
  document.addEventListener('mouseover', onEnter, true)
  document.addEventListener('mouseout', onLeave, true)
  document.addEventListener('focusin', onEnter, true)
  document.addEventListener('focusout', onLeave, true)
  window.addEventListener('scroll', onScroll, true)
  window.addEventListener('resize', onScroll, true)
}

export default installTooltip
