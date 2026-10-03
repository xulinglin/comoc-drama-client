<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
// 项目文件目录树：浏览本机项目目录。
// - 默认隐藏 target / node_modules 等构建目录（可开"显示构建目录"）
// - 左键点击文件 → 在资源管理器中打开所在文件夹并选中（跳转）
// - 右键点击文件 → 复制文件本身 / 复制路径 / 在资源管理器中显示
const visible = defineModel('visible', { type: Boolean, default: false })

const roots = ref([])
const rootPath = ref('')
// 用户通过"换目录"选择的自定义根目录；'' 表示使用后端默认项目根。
let treeRootPath = ''
const rootLoading = ref(false)
const showBuild = ref(false)
const notice = ref({ type: '', text: '' })
const menu = ref({ visible: false, x: 0, y: 0, entry: null })
const apiError = ref('')

const available = computed(() => Boolean(window.pywebview?.api))

// 扁平化的可见行：按深度优先顺序展开所有 expanded 目录，递归层级不受限。
const visibleRows = computed(() => {
  const rows = []
  const walk = (nodes) => {
    for (const node of nodes) {
      rows.push(node)
      if (!node.isDir || !node.expanded) continue
      if (node.loaded && !node.children.length) {
        rows.push({ emptyHint: true, key: `${node.path}::empty`, depth: node.depth + 1 })
        continue
      }
      walk(node.children)
    }
  }
  walk(roots.value)
  return rows
})

let noticeTimer = 0
function flash(type, text) {
  notice.value = { type, text }
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = { type: '', text: '' } }, 3200)
}

function cleanError(value) {
  return String(value?.message || value || '未知错误').replace(/^Error:\s*/, '')
}

function formatBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0)
  if (!value) return ''
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = value
  let unit = 'B'
  for (const next of units) {
    if (size < 1024) break
    size /= 1024
    unit = next
  }
  return `${size >= 100 ? Math.round(size) : size.toFixed(1)} ${unit}`
}

function makeNode(entry, depth) {
  return {
    name: entry.name,
    path: entry.path,
    isDir: Boolean(entry.isDir),
    size: Number(entry.size) || 0,
    depth,
    expanded: false,
    loaded: false,
    loading: false,
    children: [],
  }
}

async function loadInto(node) {
  const target = node ? node.path : treeRootPath
  if (node) node.loading = true
  try {
    const result = await window.pywebview.api.list_directory(target, showBuild.value)
    const children = (result?.entries || []).map(entry => makeNode(entry, (node?.depth ?? -1) + 1))
    if (node) {
      node.children = children
      node.loaded = true
    } else {
      roots.value = children
      rootPath.value = String(result?.path || '')
    }
  } catch (error) {
    flash('error', cleanError(error))
    if (node) { node.loaded = true; node.children = [] }
  } finally {
    if (node) node.loading = false
  }
}

async function initTree() {
  // pywebview 注入可能晚于首次打开（pywebviewready），短暂等待桥接就绪。
  for (let attempt = 0; attempt < 20 && !available.value; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 400))
  }
  if (!available.value) return
  rootLoading.value = true
  apiError.value = ''
  try {
    await loadInto(null)
  } finally {
    rootLoading.value = false
  }
}

async function toggleDir(node) {
  if (!node.isDir) return
  if (node.expanded) {
    node.expanded = false
    return
  }
  if (!node.loaded) await loadInto(node)
  node.expanded = true
}

function onRowClick(node) {
  if (node.isDir) {
    toggleDir(node)
    return
  }
  revealEntry(node)
}

async function revealEntry(node) {
  try {
    await window.pywebview.api.reveal_path(node.path)
    flash('success', '已在资源管理器中定位')
  } catch (error) {
    flash('error', cleanError(error))
  }
}

async function copyEntryFile(node) {
  try {
    await window.pywebview.api.copy_files_to_clipboard([node.path])
    flash('success', `已复制「${node.name}」，可在文件夹中 Ctrl+V 粘贴`)
  } catch (error) {
    flash('error', cleanError(error))
  }
}

async function copyEntryPath(node) {
  try {
    await navigator.clipboard.writeText(node.path)
    flash('success', '已复制路径')
  } catch {
    flash('error', '复制路径失败')
  }
}

async function openEntryFolder(node) {
  try {
    await window.pywebview.api.open_path(node.path)
  } catch (error) {
    flash('error', cleanError(error))
  }
}

function openMenu(event, node) {
  event.preventDefault()
  menu.value = {
    visible: true,
    x: Math.min(event.clientX, window.innerWidth - 194),
    y: Math.min(event.clientY, window.innerHeight - 150),
    entry: node,
  }
}

function closeMenu() {
  menu.value = { visible: false, x: 0, y: 0, entry: null }
}

async function changeRoot() {
  try {
    const picked = await window.pywebview.api.select_tree_directory()
    if (!picked) return
    treeRootPath = String(picked)
    rootPath.value = treeRootPath
    roots.value = []
    await loadInto(null)
  } catch (error) {
    flash('error', cleanError(error))
  }
}

async function refreshTree() {
  closeMenu()
  if (!rootPath.value) {
    await initTree()
    return
  }
  // 记录当前展开的目录，重建后恢复展开状态。
  const expandedPaths = []
  const walk = (nodes) => {
    for (const node of nodes) {
      if (node.isDir && node.expanded) {
        expandedPaths.push(node.path)
        walk(node.children || [])
      }
    }
  }
  walk(roots.value)
  rootLoading.value = true
  try {
    await loadInto(null)
    const byPath = new Map()
    const index = (nodes) => {
      for (const node of nodes) {
        byPath.set(node.path, node)
        index(node.children || [])
      }
    }
    index(roots.value)
    for (const path of expandedPaths) {
      const node = byPath.get(path)
      if (!node) continue
      await loadInto(node)
      node.expanded = true
    }
  } finally {
    rootLoading.value = false
  }
}

async function toggleShowBuild() {
  showBuild.value = !showBuild.value
  await refreshTree()
}

function onDocumentClick(event) {
  if (menu.value.visible && !event.target.closest?.('.file-tree-menu')) closeMenu()
}

function onKeydown(event) {
  if (event.key !== 'Escape') return
  if (menu.value.visible) closeMenu()
  else if (visible.value) visible.value = false
}

watch(visible, (value) => {
  if (!value) return
  closeMenu()
  if (!roots.value.length) initTree()
})

watch(available, (value) => {
  if (value && visible.value && !roots.value.length) initTree()
})

window.addEventListener('click', onDocumentClick, true)
window.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  window.removeEventListener('click', onDocumentClick, true)
  window.removeEventListener('keydown', onKeydown)
  window.clearTimeout(noticeTimer)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="file-tree-backdrop" @click.self="visible = false">
      <section class="file-tree-dialog" role="dialog" aria-modal="true" aria-labelledby="file-tree-title">
        <header class="file-tree-head">
          <div class="file-tree-title">
            <span class="file-tree-kicker">PROJECT FILES</span>
            <h3 id="file-tree-title">项目文件</h3>
            <p :title="rootPath">{{ rootPath || '正在读取项目目录…' }}</p>
          </div>
          <div class="file-tree-head-actions">
            <button type="button" :class="{ on: showBuild }" :title="showBuild ? '隐藏 target 等构建目录' : '显示 target 等构建目录'" @click="toggleShowBuild">
              <svg viewBox="0 0 24 24"><path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.6"/></svg>
              {{ showBuild ? '隐藏构建目录' : '显示构建目录' }}
            </button>
            <button type="button" title="更换根目录" @click="changeRoot">
              <svg viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z"/></svg>
              换目录
            </button>
            <button type="button" title="刷新" @click="refreshTree">
              <svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4"/></svg>
              刷新
            </button>
            <button type="button" class="close" aria-label="关闭" @click="visible = false">×</button>
          </div>
        </header>

        <div class="file-tree-notice" aria-live="polite"><span v-if="notice.text" :class="notice.type">{{ notice.text }}</span></div>

        <div v-if="!available" class="file-tree-state">
          <strong>请从桌面客户端打开</strong>
          <small>项目文件目录树依赖本机文件访问能力。</small>
        </div>
        <div v-else-if="rootLoading && !roots.length" class="file-tree-state">
          <i class="file-tree-spinner" aria-hidden="true"></i>
          <strong>正在读取项目目录…</strong>
        </div>
        <div v-else-if="!roots.length" class="file-tree-state">
          <strong>目录为空</strong>
          <small>换个根目录，或打开"显示构建目录"看看。</small>
        </div>

        <div v-else class="file-tree-body" role="tree" aria-label="项目文件目录树">
          <template v-for="row in visibleRows" :key="row.key || row.path">
            <div v-if="row.emptyHint" class="file-tree-empty" :style="{ paddingLeft: `${10 + row.depth * 18}px` }">空文件夹</div>
            <div
              v-else
              class="file-tree-row"
              role="treeitem"
              :aria-expanded="row.isDir ? row.expanded : undefined"
              :style="{ paddingLeft: `${10 + row.depth * 18}px` }"
              :title="row.path"
              @click="onRowClick(row)"
              @contextmenu="openMenu($event, row)"
            >
              <span class="file-tree-chevron" :class="{ open: row.expanded, loading: row.loading, leaf: !row.isDir }">
                <svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>
              </span>
              <svg v-if="row.isDir" class="file-tree-icon dir" viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z"/></svg>
              <svg v-else class="file-tree-icon file" viewBox="0 0 24 24"><path d="M6 3.5h8l4 4V20H6z"/><path d="M14 3.5V8h4"/></svg>
              <span class="file-tree-name">{{ row.name }}</span>
              <span v-if="!row.isDir && row.size" class="file-tree-size">{{ formatBytes(row.size) }}</span>
            </div>
          </template>
        </div>

        <footer class="file-tree-foot">
          <span>左键点击文件：在资源管理器中定位 · 右键：复制文件 / 路径</span>
          <span v-if="showBuild" class="build-on">正在显示构建目录</span>
        </footer>

        <div
          v-if="menu.visible && menu.entry"
          class="file-tree-menu"
          :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
          role="menu"
        >
          <button v-if="!menu.entry.isDir" type="button" role="menuitem" class="primary" @click="copyEntryFile(menu.entry); closeMenu()">
            <svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/></svg>
            复制文件
          </button>
          <button v-if="menu.entry.isDir" type="button" role="menuitem" @click="openEntryFolder(menu.entry); closeMenu()">
            <svg viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z"/></svg>
            打开文件夹
          </button>
          <button type="button" role="menuitem" @click="revealEntry(menu.entry); closeMenu()">
            <svg viewBox="0 0 24 24"><path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.6"/></svg>
            在资源管理器中显示
          </button>
          <button type="button" role="menuitem" @click="copyEntryPath(menu.entry); closeMenu()">
            <svg viewBox="0 0 24 24"><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 8l4 4-4 4M9 12h9"/></svg>
            复制路径
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.file-tree-backdrop { position: fixed; z-index: 95; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(6, 8, 14, .62); backdrop-filter: blur(6px); }
.file-tree-dialog { position: relative; display: flex; width: min(760px, 100%); height: min(640px, calc(100vh - 64px)); flex-direction: column; overflow: hidden; border: 1px solid #34343a; border-radius: 18px; color: #ededf2; background: #171717; box-shadow: 0 36px 110px #000d, inset 0 1px #ffffff12; }
.file-tree-head { display: flex; flex: 0 0 auto; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 18px 18px 10px; }
.file-tree-kicker { color: #73737d; font: 700 9px/1 ui-monospace, Consolas, monospace; letter-spacing: .16em; }
.file-tree-title h3 { margin: 6px 0 3px; font-size: 20px; letter-spacing: -.02em; }
.file-tree-title p { max-width: 420px; margin: 0; overflow: hidden; color: #85858e; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.file-tree-head-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; }
.file-tree-head-actions button { display: flex; height: 30px; align-items: center; gap: 6px; padding: 0 10px; border: 1px solid #3a3a40; border-radius: 8px; color: #a9a9b2; background: #202024; font-size: 11px; cursor: pointer; transition: color .15s ease, background-color .15s ease, border-color .15s ease; }
.file-tree-head-actions button:hover { color: #fff; border-color: #4a4a52; background: #2a2a2f; }
.file-tree-head-actions button.on { color: #64d6b1; border-color: #2c5a4b; background: #1b2b26; }
.file-tree-head-actions button.close { width: 30px; justify-content: center; padding: 0; font-size: 16px; }
.file-tree-head-actions svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.file-tree-notice { min-height: 20px; flex: 0 0 auto; padding: 0 18px; font-size: 11px; }
.file-tree-notice .success { color: #64d6b1; }
.file-tree-notice .error { color: #ff8fa1; }
.file-tree-body { min-height: 0; flex: 1; overflow: auto; padding: 4px 8px 10px; border-top: 1px solid #2b2b30; scrollbar-width: thin; scrollbar-color: #3d3d44 transparent; }
.file-tree-row { display: flex; height: 32px; align-items: center; gap: 7px; padding-right: 10px; border-radius: 8px; font-size: 12px; cursor: default; user-select: none; }
.file-tree-row:hover { background: #232327; }
.file-tree-chevron { display: grid; width: 16px; height: 16px; flex: 0 0 16px; place-items: center; color: #7b7b84; }
.file-tree-chevron svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; transition: transform .15s ease; }
.file-tree-chevron.open svg { transform: rotate(90deg); }
.file-tree-chevron.leaf { visibility: hidden; }
.file-tree-chevron.loading svg { animation: file-tree-spin 1s linear infinite; }
@keyframes file-tree-spin { to { transform: rotate(360deg); } }
.file-tree-icon { width: 15px; height: 15px; flex: 0 0 15px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.file-tree-icon.dir { color: #6fb6ff; }
.file-tree-icon.file { color: #9a9aa4; }
.file-tree-name { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-tree-size { flex: 0 0 auto; color: #7b7b84; font-size: 10px; font-variant-numeric: tabular-nums; }
.file-tree-empty { padding: 4px 10px 8px; color: #63636b; font-size: 11px; }
.file-tree-state { display: grid; min-height: 220px; flex: 1; place-items: center; align-content: center; gap: 8px; color: #85858e; }
.file-tree-state strong { color: #c9c9d2; font-size: 13px; }
.file-tree-state small { font-size: 11px; }
.file-tree-spinner { width: 22px; height: 22px; border: 2px solid #33333a; border-top-color: #64d6b1; border-radius: 50%; animation: file-tree-spin 1s linear infinite; }
.file-tree-foot { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 18px; border-top: 1px solid #2b2b30; color: #6f6f78; font-size: 10px; }
.file-tree-foot .build-on { color: #e8c46a; }
.file-tree-menu { position: fixed; z-index: 96; display: grid; min-width: 186px; gap: 2px; padding: 5px; border: 1px solid #3a3a40; border-radius: 10px; background: #222226; box-shadow: 0 18px 48px #000a; }
.file-tree-menu button { display: flex; height: 32px; align-items: center; gap: 8px; padding: 0 10px; border: 0; border-radius: 7px; color: #d6d6de; background: transparent; font-size: 12px; text-align: left; cursor: pointer; }
.file-tree-menu button:hover { color: #fff; background: #323238; }
.file-tree-menu button.primary { color: #64d6b1; }
.file-tree-menu button.primary:hover { color: #8cf0cd; background: #1e2f29; }
.file-tree-menu svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }

@media (prefers-reduced-motion: reduce) {
  .file-tree-chevron svg, .file-tree-spinner { animation: none; transition: none; }
}
</style>
