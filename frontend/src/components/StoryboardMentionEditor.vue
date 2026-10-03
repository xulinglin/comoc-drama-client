<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useAttrs, watch } from 'vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: String, default: '' },
  assets: { type: Array, default: () => [] },
  labels: { type: Object, default: () => ({}) },
  placeholder: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'selectAsset'])
const attrs = useAttrs()
const editor = ref(null)
const mentionMenu = ref(null)
const savedRange = ref(null)
const showMentionMenu = ref(false)
const mentionIndex = ref(0)
const mentionMenuStyle = ref({})

const availableAssets = computed(() => props.assets.filter(asset => asset?.id))

const assetMap = computed(() => {
  const map = new Map()
  props.assets.forEach((asset) => {
    const id = String(asset?.id || '')
    if (!id) return
    map.set(id, asset)
    map.set(id.toLowerCase(), asset)
  })
  return map
})

const visualSignature = computed(() => props.assets.map(asset => [
  asset?.id,
  asset?.name,
  asset?.category,
  asset?.type,
  asset?.cover,
  asset?.image,
  asset?.imageUrl,
  asset?.audioUrl,
].join('\u0001')).join('\u0002'))

function assetFor(id) {
  return assetMap.value.get(String(id)) || assetMap.value.get(String(id).toLowerCase())
}

function assetCover(asset) {
  return [asset?.cover, asset?.image, asset?.imageUrl, asset?.image_url, asset?.audioUrl, asset?.audio_url]
    .find(value => typeof value === 'string' && value.trim()) || ''
}

function createMentionChip(id) {
  const asset = assetFor(id)
  const label = String(asset?.name || props.labels?.[id] || props.labels?.[String(id).toLowerCase()] || id)
  const chip = document.createElement('span')
  chip.className = 'storyboard-mention-chip'
  chip.contentEditable = 'false'
  chip.dataset.assetId = id
  chip.title = `素材引用 {{${id}}}`

  const cover = assetCover(asset)
  if (cover && asset?.category !== 'audio' && asset?.type !== 'audio') {
    const image = document.createElement('img')
    image.src = cover
    image.alt = ''
    chip.appendChild(image)
  } else {
    const icon = document.createElement('span')
    icon.className = 'storyboard-mention-icon'
    icon.textContent = asset?.category === 'audio' || asset?.type === 'audio' ? '♫' : '◇'
    chip.appendChild(icon)
  }

  const text = document.createElement('span')
  text.className = 'storyboard-mention-label'
  text.textContent = label
  chip.appendChild(text)
  return chip
}

function placeholderPattern() {
  // Compatible with {{CHAR-001}}, {CHAR-001}, and full-width braces pasted from Chinese IMEs.
  return /[{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2}/g
}

function renderEditor(force = false) {
  const element = editor.value
  if (!element || (!force && document.activeElement === element)) return
  const fragment = document.createDocumentFragment()
  const source = String(props.modelValue || '')
  const pattern = placeholderPattern()
  let cursor = 0
  let match
  while ((match = pattern.exec(source))) {
    if (match.index > cursor) fragment.appendChild(document.createTextNode(source.slice(cursor, match.index)))
    fragment.appendChild(createMentionChip(String(match[1] || '').trim()))
    cursor = match.index + match[0].length
  }
  if (cursor < source.length) fragment.appendChild(document.createTextNode(source.slice(cursor)))
  element.replaceChildren(fragment)
}

function syncEditorFromModel() {
  const element = editor.value
  if (!element) return
  const modelValue = String(props.modelValue || '')
  const hasUnrenderedMentions = placeholderPattern().test(modelValue)
    && !element.querySelector('.storyboard-mention-chip')
  if (document.activeElement === element && editorValue() === modelValue && !hasUnrenderedMentions) return
  renderEditor(true)
}

function readNode(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent || ''
  if (node.nodeType !== Node.ELEMENT_NODE) return ''
  if (node.classList?.contains('storyboard-mention-chip')) return `{{${node.dataset.assetId || ''}}}`
  if (node.tagName === 'BR') return '\n'
  const content = Array.from(node.childNodes).map(readNode).join('')
  return ['DIV', 'P'].includes(node.tagName) ? `${content}\n` : content
}

function editorValue() {
  return Array.from(editor.value?.childNodes || []).map(readNode).join('').replace(/\n+$/, '')
}

function syncValue() {
  const value = editorValue()
  if (value !== props.modelValue) emit('update:modelValue', value)
}

function saveRange() {
  const selection = window.getSelection()
  const element = editor.value
  if (!selection?.rangeCount || !element?.contains(selection.anchorNode)) return
  savedRange.value = selection.getRangeAt(0).cloneRange()
}

function restoreRange() {
  const element = editor.value
  const selection = window.getSelection()
  if (!element || !selection) return false
  element.focus({ preventScroll: true })
  if (savedRange.value && element.contains(savedRange.value.commonAncestorContainer)) {
    selection.removeAllRanges()
    selection.addRange(savedRange.value.cloneRange())
    return true
  }
  const range = document.createRange()
  range.selectNodeContents(element)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
  savedRange.value = range.cloneRange()
  return true
}

function textBeforeCursor() {
  const selection = window.getSelection()
  const element = editor.value
  if (!selection?.rangeCount || !element?.contains(selection.anchorNode)) return ''
  const range = selection.getRangeAt(0).cloneRange()
  range.selectNodeContents(element)
  range.setEnd(selection.anchorNode, selection.anchorOffset)
  return range.toString()
}

function mentionTriggerRange() {
  const selection = window.getSelection()
  const element = editor.value
  if (!selection?.rangeCount || !element) return null
  const cursor = selection.getRangeAt(0).cloneRange()
  if (!element.contains(cursor.endContainer) || cursor.endContainer.nodeType !== Node.TEXT_NODE) return null
  const text = cursor.endContainer.textContent || ''
  const atIndex = text.lastIndexOf('@', cursor.endOffset - 1)
  if (atIndex < 0 || /[\s\u00a0]/.test(text.slice(atIndex + 1, cursor.endOffset))) return null
  const range = document.createRange()
  range.setStart(cursor.endContainer, atIndex)
  range.setEnd(cursor.endContainer, cursor.endOffset)
  return range
}

function updateMentionMenuPosition() {
  const selection = window.getSelection()
  const element = editor.value
  if (!selection?.rangeCount || !element) return
  const cursor = selection.getRangeAt(0).cloneRange()
  let rect = cursor.getBoundingClientRect()
  if (!rect.width && !rect.height) rect = element.getBoundingClientRect()
  const width = 248
  const height = Math.min(286, availableAssets.value.length * 48 + 48)
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.left))
  const belowTop = rect.bottom + 8
  const top = belowTop + height < window.innerHeight - 8
    ? belowTop
    : Math.max(8, rect.top - height - 8)
  mentionMenuStyle.value = { left: `${left}px`, top: `${top}px`, width: `${width}px` }
}

function openMentionMenuIfNeeded() {
  saveRange()
  showMentionMenu.value = textBeforeCursor().endsWith('@') && availableAssets.value.length > 0
  mentionIndex.value = 0
  if (showMentionMenu.value) nextTick(updateMentionMenuPosition)
}

function insertMention(asset) {
  if (!asset || !restoreRange()) return
  const selection = window.getSelection()
  if (!selection?.rangeCount) return
  const range = mentionTriggerRange() || selection.getRangeAt(0)
  range.deleteContents()
  const chip = createMentionChip(String(asset.id))
  const space = document.createTextNode('\u00a0')
  const fragment = document.createDocumentFragment()
  fragment.append(chip, space)
  range.insertNode(fragment)
  const after = document.createRange()
  after.setStartAfter(space)
  after.collapse(true)
  selection.removeAllRanges()
  selection.addRange(after)
  savedRange.value = after.cloneRange()
  showMentionMenu.value = false
  mentionIndex.value = 0
  syncValue()
  emit('selectAsset', asset)
}

function handleEnter(event) {
  event.preventDefault()
  document.execCommand('insertLineBreak')
  syncValue()
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    showMentionMenu.value = false
    return
  }
  if (showMentionMenu.value) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      mentionIndex.value = Math.min(mentionIndex.value + 1, availableAssets.value.length - 1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      mentionIndex.value = Math.max(mentionIndex.value - 1, 0)
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      insertMention(availableAssets.value[mentionIndex.value])
      return
    }
  }
  if (event.key === 'Enter') handleEnter(event)
}

function handlePaste(event) {
  event.preventDefault()
  document.execCommand('insertText', false, event.clipboardData?.getData('text/plain') || '')
  syncValue()
}

function handleDocumentPointerDown(event) {
  if (editor.value?.contains(event.target) || mentionMenu.value?.contains(event.target)) return
  showMentionMenu.value = false
}

watch(() => props.modelValue, () => nextTick(syncEditorFromModel), { immediate: true, flush: 'post' })
watch(visualSignature, () => nextTick(() => renderEditor(true)))
watch(() => props.labels, () => nextTick(() => renderEditor(true)), { deep: true })
onMounted(() => {
  nextTick(() => renderEditor(true))
  document.addEventListener('pointerdown', handleDocumentPointerDown)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', handleDocumentPointerDown))
</script>

<template>
  <div
    ref="editor"
    v-bind="attrs"
    class="storyboard-mention-editor"
    contenteditable="true"
    role="textbox"
    aria-multiline="true"
    :data-placeholder="placeholder"
    spellcheck="false"
    @focus="renderEditor(true); saveRange()"
    @mouseup="saveRange"
    @keyup="saveRange"
    @input="syncValue(); openMentionMenuIfNeeded()"
    @blur="syncValue"
    @keydown="handleKeydown"
    @paste="handlePaste"
  ></div>
  <Teleport to="body">
    <div v-if="showMentionMenu" ref="mentionMenu" class="storyboard-mention-menu" :style="mentionMenuStyle" @pointerdown.stop>
      <header><strong>选择已上传素材</strong><small>↑↓ 选择 · Enter 确认</small></header>
      <button
        v-for="(asset, index) in availableAssets"
        :key="asset.id"
        type="button"
        :class="{ active: index === mentionIndex }"
        @mouseenter="mentionIndex = index"
        @mousedown.prevent="insertMention(asset)"
      >
        <img v-if="assetCover(asset) && asset?.category !== 'audio' && asset?.type !== 'audio'" :src="assetCover(asset)" alt="" />
        <span v-else class="storyboard-mention-menu-icon">{{ asset?.category === 'audio' || asset?.type === 'audio' ? '♫' : '◇' }}</span>
        <span class="storyboard-mention-menu-copy"><strong>{{ asset.name || asset.id }}</strong><small>{{ asset.category === 'audio' || asset.type === 'audio' ? '音频' : ['character', 'role'].includes(asset.category) ? '人物' : asset.category === 'scene' ? '场景' : asset.category === 'prop' ? '道具' : asset.category === 'layout' ? '白模' : '素材' }}</small></span>
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.storyboard-mention-editor {
  min-width: 0;
  min-height: 78px;
  box-sizing: border-box;
  overflow: auto;
  outline: 0;
  color: #ddd;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  caret-color: #f2f2f2;
  scrollbar-width: thin;
  scrollbar-color: #555 transparent;
}
.storyboard-mention-editor:empty::before {
  color: #656565;
  content: attr(data-placeholder);
  pointer-events: none;
}
.storyboard-mention-editor::-webkit-scrollbar { width: 7px; }
.storyboard-mention-editor::-webkit-scrollbar-track { background: transparent; }
.storyboard-mention-editor::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 999px; background: #555; background-clip: padding-box; }
.storyboard-mention-editor :deep(.storyboard-mention-chip) {
  display: inline-flex;
  height: 25px;
  box-sizing: border-box;
  align-items: center;
  gap: 5px;
  margin: 0 3px;
  padding: 0 8px 0 4px;
  border: 1px solid #4a4a4a;
  border-radius: 7px;
  color: #f2f2f2;
  background: #303030;
  box-shadow: inset 0 1px #ffffff0a;
  font-size: 12px;
  line-height: 23px;
  vertical-align: middle;
  white-space: nowrap;
  user-select: none;
}
.storyboard-mention-editor :deep(.storyboard-mention-chip img),
.storyboard-mention-editor :deep(.storyboard-mention-icon) {
  display: grid;
  width: 17px;
  height: 17px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 4px;
  object-fit: cover;
  color: #bfc5cc;
  background: #202329;
  font-size: 11px;
  line-height: 1;
}
.storyboard-mention-editor :deep(.storyboard-mention-label) { line-height: 1; }
.storyboard-mention-menu {
  position: fixed;
  z-index: 2147483000;
  max-height: 286px;
  overflow: auto;
  box-sizing: border-box;
  padding: 6px;
  border: 1px solid #454545;
  border-radius: 11px;
  color: #ddd;
  background: #242424;
  box-shadow: 0 18px 45px #000b, inset 0 1px #ffffff0a;
}
.storyboard-mention-menu > header { display: flex; align-items: center; justify-content: space-between; padding: 6px 8px 8px; }
.storyboard-mention-menu > header strong { color: #f2f2f2; font-size: 12px; }
.storyboard-mention-menu > header small { color: #777; font-size: 11px; }
.storyboard-mention-menu > button { display: flex; width: 100%; height: 44px; align-items: center; gap: 9px; padding: 5px 7px; border: 0; border-radius: 8px; color: #ddd; background: transparent; cursor: pointer; text-align: left; }
.storyboard-mention-menu > button:hover,.storyboard-mention-menu > button.active { background: #343434; }
.storyboard-mention-menu > button > img,.storyboard-mention-menu-icon { display: grid; width: 32px; height: 32px; flex: 0 0 auto; place-items: center; border-radius: 7px; object-fit: cover; color: #aaa; background: #171717; }
.storyboard-mention-menu-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 2px; }
.storyboard-mention-menu-copy strong { overflow: hidden; color: #eee; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.storyboard-mention-menu-copy small { color: #777; font-size: 11px; }
</style>
