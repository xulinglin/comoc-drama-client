<template>
  <Teleport to="body">
    <Transition name="preview-fade">
      <div
        v-if="visible"
        class="preview-overlay"
        @click.self="close"
        @wheel.prevent="onWheel"
      >
        <!-- 顶部：关闭按钮 -->
        <button type="button" class="preview-close" aria-label="关闭" @click="close">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>

        <!-- 内容区：图片/视频 + 工具栏，流式垂直布局，永不重叠 -->
        <div class="preview-content" @click.stop>
          <!-- 图片：支持缩放/旋转/拖动 -->
          <div
            v-if="type === 'image'"
            class="preview-stage"
            @mousedown="startDrag"
            :class="{ 'preview-stage--grabbing': isDragging }"
          >
            <img
              :src="activeSrc"
              class="preview-image"
              :style="imageStyle"
              draggable="false"
              alt="预览"
            />
          </div>

          <!-- 视频：原生 controls -->
          <video
            v-else-if="type === 'video'"
            :key="src"
            :src="src"
            class="preview-video"
            controls
            autoplay
            playsinline
            preload="metadata"
            @play="verifyVideoFrame"
            @error="emit('video-error')"
          />

          <div v-else-if="type === 'audio'" class="preview-audio">
            <span class="preview-audio-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M9 18V6l9-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="15.5" cy="16" r="2.5"/></svg>
            </span>
            <audio :src="src" controls autoplay />
          </div>

          <div v-if="type === 'image' && previewImages.length > 1" class="preview-reference-strip" aria-label="主图和参考图">
            <button v-for="(item, index) in previewImages" :key="`${item.src}-${index}`" type="button" :class="{ active: item.src === activeSrc }" :aria-label="`查看${item.name}`" @click="selectPreviewImage(item.src)">
              <img :src="item.src" :alt="item.name" />
              <span>{{ item.label || (index === 0 ? '主图' : `图${index}`) }}</span>
            </button>
          </div>

          <!-- 图片工具栏 -->
          <div v-if="type === 'image'" class="preview-toolbar">
            <button type="button" class="tool-btn" aria-label="缩小" @click="zoomOut">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" /></svg>
            </button>
            <button type="button" class="tool-btn" aria-label="放大" @click="zoomIn">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            </button>
            <span class="tool-divider" />
            <button type="button" class="tool-btn" aria-label="左旋转" @click="rotateLeft">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5" /></svg>
            </button>
            <button type="button" class="tool-btn" aria-label="右旋转" @click="rotateRight">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" /></svg>
            </button>
            <span class="tool-divider" />
            <button type="button" class="tool-btn" aria-label="重置" @click="reset">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0ZM12 8v8M8 12h8" /></svg>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { watchForDecodedVideoFrame } from '../utils/videoCompatibility.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  src: { type: String, default: '' },
  type: {
    type: String,
    default: 'image',
    validator: v => ['image', 'video', 'audio'].includes(v),
  },
  references: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'video-error'])

// 图片变换状态
const scale = ref(1)
const rotation = ref(0)
const pos = ref({ x: 0, y: 0 })
const isDragging = ref(false)
const activeSrc = ref(props.src)
let dragStart = { x: 0, y: 0, posX: 0, posY: 0 }
let stopVideoFrameWatch = null

const imageStyle = computed(() => ({
  transform: `translate(${pos.value.x}px, ${pos.value.y}px) scale(${scale.value}) rotate(${rotation.value}deg)`,
  cursor: isDragging.value ? 'grabbing' : (scale.value > 1 ? 'grab' : 'default'),
}))
const previewImages = computed(() => {
  const source = props.references.map((item, index) => typeof item === 'string'
    ? { src: item, name: `参考图${index + 1}`, label: index === 0 ? '主图' : `图${index}` }
    : { src: String(item?.src || item?.url || ''), name: item?.name || `参考图${index + 1}`, label: item?.label || (index === 0 ? '主图' : `图${index}`) })
  if (!source.some(item => item.src === props.src)) source.unshift({ src: props.src, name: '当前图片', label: '当前' })
  const seen = new Set()
  return source.filter((item) => {
    if (!item.src || seen.has(item.src)) return false
    seen.add(item.src)
    return true
  })
})

// 打开时重置状态
watch(() => props.visible, v => {
  if (v) {
    activeSrc.value = props.src
    reset()
    window.addEventListener('keydown', onKeyDown)
  } else {
    stopVideoFrameWatch?.()
    stopVideoFrameWatch = null
    window.removeEventListener('keydown', onKeyDown)
  }
})

watch(() => props.src, (value) => {
  activeSrc.value = value
  stopVideoFrameWatch?.()
  stopVideoFrameWatch = null
})

onBeforeUnmount(() => {
  stopVideoFrameWatch?.()
  window.removeEventListener('keydown', onKeyDown)
})

function verifyVideoFrame(event) {
  stopVideoFrameWatch?.()
  stopVideoFrameWatch = watchForDecodedVideoFrame(event.currentTarget, () => emit('video-error'))
}

function close() {
  emit('update:visible', false)
}

function zoomIn() {
  scale.value = Math.min(scale.value + 0.2, 5)
}
function zoomOut() {
  scale.value = Math.max(scale.value - 0.2, 0.2)
}
function rotateLeft() {
  rotation.value -= 90
}
function rotateRight() {
  rotation.value += 90
}
function reset() {
  scale.value = 1
  rotation.value = 0
  pos.value = { x: 0, y: 0 }
}

function selectPreviewImage(src) {
  activeSrc.value = src
  reset()
}

function onWheel(e) {
  if (e.deltaY < 0) zoomIn()
  else zoomOut()
}

function startDrag(e) {
  // 仅当放大时才允许拖动
  if (scale.value <= 1) return
  isDragging.value = true
  dragStart = { x: e.clientX, y: e.clientY, posX: pos.value.x, posY: pos.value.y }
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', stopDrag)
}
function onDrag(e) {
  if (!isDragging.value) return
  pos.value = {
    x: dragStart.posX + (e.clientX - dragStart.x),
    y: dragStart.posY + (e.clientY - dragStart.y),
  }
}
function stopDrag() {
  isDragging.value = false
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', stopDrag)
}

function onKeyDown(e) {
  switch (e.key) {
    case 'Escape': close(); break
    case '+':
    case '=': zoomIn(); break
    case '-':
    case '_': zoomOut(); break
    case '0': reset(); break
    case 'r':
    case 'R':
      if (e.shiftKey) rotateRight()
      else rotateLeft()
      break
    case 'ArrowLeft':  rotateLeft(); break
    case 'ArrowRight': rotateRight(); break
  }
}
</script>

<style scoped>
.preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 15000;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  user-select: none;
}

.preview-close {
  position: absolute;
  top: 20px;
  right: 24px;
  z-index: 2;
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 50%;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
  cursor: pointer;
  transition: background-color 160ms ease, transform 160ms ease;
}

.preview-close:hover {
  background: rgba(255, 255, 255, 0.18);
  transform: rotate(90deg);
}

.preview-close svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
}

/* 内容区：垂直流式布局，图片/视频在上，工具栏在下，永不重叠 */
.preview-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  width: 100%;
  height: 100%;
  max-width: 95vw;
  max-height: 100vh;
  padding: 24px;
  box-sizing: border-box;
}

/* 图片舞台 */
.preview-stage {
  flex: 1;
  min-height: 0;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  min-width: 0;
}

.preview-stage--grabbing {
  cursor: grabbing !important;
}

.preview-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  transition: transform 100ms ease-out;
  user-select: none;
  pointer-events: none;
}

.preview-reference-strip {
  display: flex;
  max-width: min(900px, 86vw);
  flex: 0 0 auto;
  gap: 8px;
  padding: 8px;
  overflow-x: auto;
  border: 1px solid rgba(255, 255, 255, .1);
  border-radius: 12px;
  background: rgba(15, 17, 22, .88);
  scrollbar-width: thin;
}

.preview-reference-strip button {
  position: relative;
  width: 72px;
  height: 54px;
  flex: 0 0 72px;
  padding: 0;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, .14);
  border-radius: 8px;
  background: #111;
  cursor: pointer;
}

.preview-reference-strip button.active {
  border-color: #fff;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, .18);
}

.preview-reference-strip img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.preview-reference-strip span {
  position: absolute;
  right: 3px;
  bottom: 3px;
  padding: 2px 4px;
  border-radius: 4px;
  color: #fff;
  background: rgba(0, 0, 0, .72);
  font-size: 9px;
}

/* 视频 */
.preview-video {
  max-width: 100%;
  max-height: calc(100vh - 140px);
  background: #000;
  border-radius: 8px;
}

.preview-audio {
  display: grid;
  width: min(520px, calc(100vw - 48px));
  gap: 24px;
  place-items: center;
  padding: 36px 28px 28px;
  border: 1px solid rgba(255, 255, 255, .12);
  border-radius: 8px;
  background: rgba(20, 22, 28, .92);
  box-shadow: 0 20px 60px rgba(0, 0, 0, .45);
}

.preview-audio-icon {
  display: grid;
  width: 76px;
  height: 76px;
  place-items: center;
  border-radius: 50%;
  color: #fbbf24;
  background: rgba(245, 158, 11, .12);
}

.preview-audio-icon svg {
  width: 38px;
  height: 38px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.preview-audio audio {
  width: 100%;
}

/* 工具栏：流式定位，跟随内容区，不再 absolute */
.preview-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(20, 22, 28, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.tool-btn {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: #ffffff;
  background: transparent;
  cursor: pointer;
  transition: background-color 150ms ease;
}

.tool-btn:hover {
  background: rgba(255, 255, 255, 0.12);
}

.tool-btn svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.tool-divider {
  width: 1px;
  height: 18px;
  margin: 0 4px;
  background: rgba(255, 255, 255, 0.15);
}

/* 淡入淡出 */
.preview-fade-enter-active,
.preview-fade-leave-active {
  transition: opacity 220ms ease;
}

.preview-fade-enter-from,
.preview-fade-leave-to {
  opacity: 0;
}
</style>
