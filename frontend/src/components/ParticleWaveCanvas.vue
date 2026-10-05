<template>
  <canvas ref="canvas" class="particle-wave-canvas" aria-hidden="true"></canvas>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  count: { type: Number, default: 196 },
  // 灰色亮度波的循环速度，点阵位置保持固定。
  speed: { type: Number, default: 0.2 },
})

const canvas = ref(null)
let ctx = null
let rafId = 0
let observer = null
let width = 0
let height = 0
let dpr = 1
let columns = 1
let rows = 1
let startTime = 0
let reducedMotion = null

function resize() {
  const element = canvas.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  width = rect.width
  height = rect.height
  element.width = Math.max(1, Math.round(width * dpr))
  element.height = Math.max(1, Math.round(height * dpr))
  ctx = element.getContext('2d')
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const total = Math.max(1, props.count)
  columns = Math.max(1, Math.round(Math.sqrt(total)))
  rows = Math.max(1, Math.ceil(total / columns))
  paint(0)
}

function paint(elapsed) {
  if (!ctx || !width || !height) return
  ctx.clearRect(0, 0, width, height)
  const inset = Math.min(width, height) * 0.065
  const stepX = (width - inset * 2) / Math.max(1, columns - 1)
  const stepY = (height - inset * 2) / Math.max(1, rows - 1)
  const radius = Math.min(stepX, stepY) * 0.06
  const center = 0.5 + Math.sin(elapsed * props.speed * Math.PI * 2) * 0.42

  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      if (row * columns + column >= props.count) return
      const u = columns === 1 ? 0.5 : column / (columns - 1)
      const v = rows === 1 ? 0.5 : row / (rows - 1)
      const diagonal = (u + v) / 2
      const wave = Math.exp(-Math.pow((diagonal - center) / 0.2, 2))
      const edge = Math.sin(Math.PI * (0.08 + u * 0.84)) * Math.sin(Math.PI * (0.08 + v * 0.84))
      const alpha = 0.025 + wave * edge * 0.42
      ctx.beginPath()
      ctx.arc(inset + column * stepX, inset + row * stepY, radius, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(110, 110, 115, ${alpha.toFixed(3)})`
      ctx.fill()
    }
  }
}

function draw(timestamp) {
  rafId = window.requestAnimationFrame(draw)
  if (!startTime) startTime = timestamp
  if (!document.hidden) paint((timestamp - startTime) / 1000)
}

function start() {
  if (rafId || reducedMotion?.matches) return
  startTime = 0
  rafId = window.requestAnimationFrame(draw)
}

function stop() {
  if (rafId) {
    window.cancelAnimationFrame(rafId)
    rafId = 0
  }
}

function updateMotionPreference() {
  stop()
  paint(0)
  start()
}

onMounted(() => {
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion.addEventListener('change', updateMotionPreference)
  resize()
  const element = canvas.value
  if (element && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(resize)
    observer.observe(element)
  }
  start()
})

onBeforeUnmount(() => {
  stop()
  reducedMotion?.removeEventListener('change', updateMotionPreference)
  observer?.disconnect()
  observer = null
})
</script>

<style scoped>
.particle-wave-canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
}
</style>
