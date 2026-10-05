<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  badge: { type: String, default: '' },
  status: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  drop: { type: String, default: 'down' },
  searchable: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'change'])
const root = ref(null)
const searchInput = ref(null)
const open = ref(false)
const highlighted = ref(-1)
const query = ref('')

const normalizedOptions = computed(() => props.options.map(option => (
  typeof option === 'object'
    ? { label: option.label, value: option.value, disabled: Boolean(option.disabled) }
    : { label: String(option), value: option }
)))
const selected = computed(() => normalizedOptions.value.find(option => option.value === props.modelValue))
const filteredOptions = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return normalizedOptions.value
  return normalizedOptions.value.filter(option => String(option.label || '').toLowerCase().includes(keyword))
})

function setOpen(value) {
  if (props.disabled) return
  open.value = value
  if (value) {
    query.value = ''
    if (props.searchable) nextTick(() => searchInput.value?.focus())
  }
  highlighted.value = normalizedOptions.value.findIndex(option => option.value === props.modelValue)
}

function choose(option) {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  emit('change', option.value)
  open.value = false
}

function handleSearchInput() {
  highlighted.value = filteredOptions.value.findIndex(option => option.value === props.modelValue)
}

function handleKeydown(event) {
  if (props.disabled) return
  if (event.key === 'Escape') {
    open.value = false
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (!open.value) setOpen(true)
    else if (filteredOptions.value[highlighted.value]) choose(filteredOptions.value[highlighted.value])
    return
  }
  if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return
  event.preventDefault()
  if (!open.value) setOpen(true)
  const direction = event.key === 'ArrowDown' ? 1 : -1
  const total = filteredOptions.value.length
  if (total) highlighted.value = (highlighted.value + direction + total) % total
}

function closeFromOutside(event) {
  if (!root.value?.contains(event.target)) open.value = false
}

onMounted(() => document.addEventListener('pointerdown', closeFromOutside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeFromOutside))
</script>

<template>
  <div ref="root" class="ui-select" :class="{ open, disabled, 'drop-up': drop === 'up' }">
    <button
      type="button"
      class="ui-select-trigger"
      role="combobox"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :disabled="disabled"
      @click="setOpen(!open)"
      @keydown="handleKeydown"
    >
      <span v-if="status" class="ui-select-status"></span>
      <span class="ui-select-value" :class="{ placeholder: !selected }">{{ selected?.label || placeholder }}</span>
      <span v-if="badge" class="ui-select-badge">{{ badge }}</span>
      <svg class="ui-select-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
    </button>

    <Transition name="select-popover">
      <div v-if="open" class="ui-select-menu" role="listbox">
        <div v-if="searchable" class="ui-select-search">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
          <input
            ref="searchInput"
            v-model="query"
            type="text"
            class="ui-select-search-input"
            placeholder="筛选选项"
            aria-label="筛选选项"
            autocomplete="off"
            @input="handleSearchInput"
            @keydown="handleKeydown"
          />
        </div>
        <button
          v-for="(option, index) in filteredOptions"
          :key="String(option.value)"
          type="button"
          class="ui-select-option"
          :class="{ selected: option.value === modelValue, highlighted: index === highlighted }"
          :disabled="option.disabled"
          role="option"
          :aria-selected="option.value === modelValue"
          @mouseenter="highlighted = index"
          @click="choose(option)"
        >
          <span>{{ option.label }}</span>
          <svg v-if="option.value === modelValue" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.2 2.7 2.7 6.3-6.1" /></svg>
        </button>
        <div v-if="!filteredOptions.length" class="ui-select-empty">暂无选项</div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.ui-select {
  --select-accent: #b8b8b8;
  --select-border: #3b3b3b;
  --select-border-hover: #555;
  --select-border-focus: #707070;
  --select-bg: linear-gradient(180deg,#1b1b1b 0%,#131313 100%);
  --select-bg-hover: linear-gradient(180deg,#202020 0%,#161616 100%);
  --select-bg-focus: linear-gradient(180deg,#222 0%,#171717 100%);
  --select-menu-border: #414141;
  --select-menu-bg: linear-gradient(180deg,#232323f7,#191919fa);
  --select-focus-ring: #ffffff0c;
  position: relative;
  min-width: 0;
  width: 100%;
}
.ui-select-trigger {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  box-sizing: border-box;
  min-height: 42px;
  padding: 0 12px;
  overflow: hidden;
  border: 1px solid var(--select-border);
  border-radius: 11px;
  outline: none;
  color: #ededed;
  background: var(--select-bg);
  box-shadow: inset 0 1px 0 #ffffff09,0 1px 2px #0005;
  cursor: pointer;
  text-align: left;
  transition: border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .18s ease;
}
.ui-select-trigger::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 1px;
  opacity: 0;
  background: linear-gradient(90deg,transparent,#ffffff4a,transparent);
  content: '';
  transition: opacity .18s ease;
}
.ui-select-trigger:hover { border-color: var(--select-border-hover); background: var(--select-bg-hover); }
.ui-select-trigger:active { transform: translateY(1px); }
.ui-select.open .ui-select-trigger, .ui-select-trigger:focus-visible {
  border-color: var(--select-border-focus);
  background: var(--select-bg-focus);
  box-shadow: 0 0 0 3px var(--select-focus-ring),inset 0 1px 0 #ffffff12,0 8px 24px #0005;
}
.ui-select.open .ui-select-trigger::after, .ui-select-trigger:focus-visible::after { opacity: 1; }
.ui-select.disabled { opacity: .45; }
.ui-select.disabled .ui-select-trigger { cursor: not-allowed; transform: none; }
.ui-select-status { flex: 0 0 auto; width: 7px; height: 7px; border: 1px solid #f4f4f4; border-radius: 50%; background: #bdbdbd; box-shadow: 0 0 0 3px #ffffff0b,0 0 10px #ffffff40; }
.ui-select-value { position: relative; z-index: 1; flex: 1; min-width: 0; overflow: hidden; font-size: 13px; font-weight: 600; letter-spacing: .01em; text-overflow: ellipsis; white-space: nowrap; }
.ui-select-value.placeholder { color: #777; font-weight: 450; }
.ui-select-badge { position: relative; z-index: 1; flex: 0 0 auto; padding: 4px 7px; border: 1px solid #4a4a4a; border-radius: 6px; color: #d8d8d8; background: linear-gradient(180deg,#343434,#272727); box-shadow: inset 0 1px 0 #ffffff0c; font: 700 11px/1 monospace; letter-spacing: .08em; }
.ui-select-chevron { position: relative; z-index: 1; flex: 0 0 auto; width: 14px; fill: none; stroke: #8e8e8e; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; transition: color .18s ease,transform .2s ease; }
.ui-select-trigger:hover .ui-select-chevron, .ui-select.open .ui-select-chevron { stroke: #ddd; }
.ui-select.open .ui-select-chevron { transform: rotate(180deg); }
.ui-select-menu {
  position: absolute;
  z-index: 80;
  top: calc(100% + 7px);
  right: 0;
  left: 0;
  box-sizing: border-box;
  min-width: 240px;
  max-height: 232px;
  padding: 6px;
  overflow-y: auto;
  border: 1px solid var(--select-menu-border);
  border-radius: 12px;
  background: var(--select-menu-bg);
  box-shadow: 0 22px 54px #000c,0 0 0 1px #0008,inset 0 1px 0 #ffffff0d;
  backdrop-filter: blur(18px);
}
.ui-select-menu::-webkit-scrollbar { width: 10px; height: 10px; }
.ui-select-menu::-webkit-scrollbar-track { background: transparent; }
.ui-select-menu::-webkit-scrollbar-thumb {
  min-height: 44px;
  border: 3px solid transparent;
  border-radius: 999px;
  background: #414141;
  background-clip: padding-box;
}
.ui-select-menu::-webkit-scrollbar-thumb:hover { border-width: 2px; background: #5a5a5a; background-clip: padding-box; }
.ui-select-search { position: sticky; top: -6px; z-index: 2; display: flex; align-items: center; gap: 8px; margin: -6px -6px 4px; padding: 8px 10px; border-bottom: 1px solid #333; background: linear-gradient(180deg,#232323f7,#1d1d1dfa); backdrop-filter: blur(18px); }
.ui-select-search svg { width: 15px; flex: 0 0 auto; fill: none; stroke: #7a7a7a; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.ui-select-search-input { min-width: 0; flex: 1; border: 0; outline: 0; color: #ededed; background: transparent; font-size: 13px; }
.ui-select-search-input::placeholder { color: #777; }
.ui-select-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #a8a8a8;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  transition: border-color .14s ease,color .14s ease,background .14s ease;
}
.ui-select-option + .ui-select-option { margin-top: 2px; }
.ui-select-option:hover, .ui-select-option.highlighted { border-color: #ffffff0b; color: #f1f1f1; background: #ffffff0a; }
.ui-select-option.selected { border-color: #ffffff12; color: #fff; background: linear-gradient(90deg,#ffffff14,#ffffff09); }
.ui-select-option:disabled { opacity: .38; cursor: not-allowed; }
.ui-select-option svg { flex: 0 0 auto; width: 18px; height: 18px; padding: 3px; border-radius: 50%; color: #181818; background: var(--select-accent); fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.ui-select-empty { padding: 18px 10px; color: #686868; font-size: 12px; text-align: center; }
.select-popover-enter-active, .select-popover-leave-active { transition: opacity .16s ease,transform .16s ease; transform-origin: top center; }
.select-popover-enter-from, .select-popover-leave-to { opacity: 0; transform: translateY(-5px) scale(.98); }
.ui-select.drop-up .ui-select-menu { top: auto; bottom: calc(100% + 7px); }
.ui-select.drop-up .select-popover-enter-active, .ui-select.drop-up .select-popover-leave-active { transform-origin: bottom center; }
.ui-select.drop-up .select-popover-enter-from, .ui-select.drop-up .select-popover-leave-to { transform: translateY(5px) scale(.98); }
</style>
