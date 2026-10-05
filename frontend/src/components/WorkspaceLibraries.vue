<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import BaseMediaPreview from './BaseMediaPreview.vue'
import { PROJECT_STYLE_GROUPS, PROJECT_RATIO_OPTIONS, getProjectStyleDescription } from './projectFormOptions'

const props = defineProps({
  section: { type: String, required: true },
  token: { type: String, required: true },
  apiBase: { type: String, default: 'http://127.0.0.1:8080' },
  storageBase: { type: String, default: 'http://127.0.0.1:18081' },
})
const emit = defineEmits(['openProject'])

const projects = ref([])
const prompts = ref([])
const assets = ref([])
const allProjects = ref([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const activeFilter = ref('all')
const assetProjectFilter = ref('all')
const assetPage = ref(1)
const assetPageSize = ref(8)
const assetPageSizeOptions = [
  { value: 8, label: '每页 8 条' },
  { value: 16, label: '每页 16 条' },
  { value: 24, label: '每页 24 条' },
  { value: 32, label: '每页 32 条' },
  { value: 48, label: '每页 48 条' },
]
const assetTotal = ref(0)
const assetTotalPages = ref(1)
const modalOpen = ref(false)
const submitting = ref(false)
const editingId = ref('')
const deleteTarget = ref(null)
const selectedAssetIds = ref([])
const batchDeleteOpen = ref(false)
const copiedId = ref('')
const previewAsset = ref(null)
const promptCoverPreviewSrc = ref('')
// BaseMediaPreview 接口：visible (v-model) + src + type
const previewVisible = computed({
  get: () => previewAsset.value !== null || promptCoverPreviewSrc.value !== '',
  set: (v) => { if (!v) { previewAsset.value = null; promptCoverPreviewSrc.value = '' } },
})
const previewSrc = computed(() => {
  if (promptCoverPreviewSrc.value) return promptCoverPreviewSrc.value
  return previewAsset.value ? assetUrl(previewAsset.value) : ''
})
const previewType = computed(() => {
  if (promptCoverPreviewSrc.value) return 'image'
  const t = previewAsset.value?.type
  if (t === 'audio') return 'audio'
  if (t === 'video') return 'video'
  return 'image'
})

const audioPlayer = ref(null)
const activeAudioId = ref('')
const activeAudioUrl = ref('')
const audioPlaying = ref(false)
const audioCurrent = ref(0)
const audioDuration = ref(0)
const audioError = ref('')

const projectForm = reactive({ name: '', description: '', style: '3d-xiuxian', styleDesc: '', ratio: '16:9' })
const projectStyleGroups = PROJECT_STYLE_GROUPS
const projectRatioOptions = PROJECT_RATIO_OPTIONS
const projectStyleDescription = computed(() => getProjectStyleDescription(projectForm.style))
const promptForm = reactive({ title: '', description: '', content: '', tag: 'role', shared: false, image: '' })
const promptScope = ref('all')
const viewingPrompt = ref(null)
const viewDialogOpen = ref(false)
const coverUploading = ref(false)
const assetForm = reactive({ name: '', description: '', tags: '', type: 'image', boundProjectIds: [] })

const sectionMeta = computed(() => ({
  projects: { eyebrow: 'PROJECT WORKSPACE', title: '项目', subtitle: '管理剧本、角色、场景与分镜制作进度', action: '新建项目' },
  prompts: { eyebrow: 'PROMPT LIBRARY', title: '提示词', subtitle: '沉淀角色、场景与故事版创作指令', action: '新建提示词' },
  assets: { eyebrow: 'ASSET LIBRARY', title: '我的资产', subtitle: '集中管理图片、场景、音频与道具', action: '上传资产' },
})[props.section])

const currentItems = computed(() => ({ projects: projects.value, prompts: prompts.value, assets: assets.value })[props.section] || [])
const filters = computed(() => props.section === 'prompts'
  ? [{ value: 'all', label: '全部' }, { value: 'role', label: '角色' }, { value: 'scene', label: '场景' }, { value: 'storyboard', label: '故事版' }]
  : props.section === 'assets'
    ? [{ value: 'all', label: '全部' }, { value: 'image', label: '图片' }, { value: 'scene', label: '场景' }, { value: 'audio', label: '音频' }, { value: 'prop', label: '道具' }]
    : [])
const displayedItems = computed(() => {
  // 资产走服务端分页，assets.value 已经是当前页数据，无需再次切片
  if (props.section === 'assets') return assets.value
  const query = keyword.value.trim().toLowerCase()
  return currentItems.value.filter(item => {
    const matchesFilter = activeFilter.value === 'all' || item.tag === activeFilter.value || item.type === activeFilter.value
    const haystack = [item.name, item.title, item.description, item.content, item.tags].join(' ').toLowerCase()
    return matchesFilter && (!query || haystack.includes(query))
  })
})
const assetPageNumbers = computed(() => {
  const total = assetTotalPages.value
  const current = assetPage.value
  const maxButtons = 5
  let start = Math.max(1, current - Math.floor(maxButtons / 2))
  const end = Math.min(total, start + maxButtons - 1)
  start = Math.max(1, end - maxButtons + 1)
  const pages = []
  for (let i = start; i <= end; i += 1) pages.push(i)
  return pages
})
const assetProjectOptions = computed(() => [
  { value: 'all', label: '全部项目' },
  ...allProjects.value.map(project => ({ value: String(project.id || ''), label: project.name || '未命名项目' })),
])
const selectedCount = computed(() => selectedAssetIds.value.length)
const allCurrentPageSelected = computed(() => assets.value.length > 0 && assets.value.every(item => selectedAssetIds.value.includes(String(item.id))))
const someCurrentPageSelected = computed(() => assets.value.some(item => selectedAssetIds.value.includes(String(item.id))))
function isSelected(id) {
  return selectedAssetIds.value.includes(String(id))
}
function toggleSelect(id) {
  const key = String(id)
  const next = selectedAssetIds.value.filter(item => item !== key)
  if (next.length === selectedAssetIds.value.length) next.push(key)
  selectedAssetIds.value = next
}
function toggleSelectAll() {
  const pageIds = assets.value.map(item => String(item.id))
  if (allCurrentPageSelected.value) {
    selectedAssetIds.value = selectedAssetIds.value.filter(id => !pageIds.includes(id))
  } else {
    selectedAssetIds.value = Array.from(new Set([...selectedAssetIds.value, ...pageIds]))
  }
}
function clearSelection() {
  selectedAssetIds.value = []
}
watch([keyword, activeFilter, assetProjectFilter, assetPageSize, () => props.section], () => { assetPage.value = 1 })
watch([keyword, activeFilter, assetProjectFilter, assetPage, assetPageSize], () => { loadSection() })
function goAssetPage(page) {
  const target = Math.min(Math.max(1, page), assetTotalPages.value)
  if (target === assetPage.value) return
  assetPage.value = target
}

function cleanError(err) {
  return String(err).replace(/^Error:\s*/, '')
}

async function request(method, path, body = null) {
  if (import.meta.env.DEV && !window.pywebview?.api) {
    if (path.startsWith('/project/list')) return [
      { id: 'p1', name: '我不是丹神', description: '顾卿之，京城第一纨绔，镇国公嫡孙', ratio: '16:9', style: '3D国漫 · 修仙玄幻', updateTime: '2026-08-06' },
      { id: 'p2', name: '小师妹的符箓作坊', description: '符箓、灵兽与一场意外的冒险', ratio: '16:9', style: '3D国漫 · 修仙玄幻', updateTime: '2026-07-30' },
      { id: 'p3', name: '满朝文武都在我脑子里看广告', description: '顾卿之，京城第一纨绔，镇国公嫡孙', ratio: '16:9', style: '3D国漫 · 武侠', updateTime: '2026-07-24' },
      { id: 'p4', name: '重生之老太也要为自己活', description: '林舒是个寡妇，生前全为八个子女活着', ratio: '16:9', style: '真人写实 · 重生', updateTime: '2026-07-18' },
    ]
    if (path.startsWith('/prompt/list')) return [
      { id: 't1', title: '东方角色设定', description: '稳定生成国风人物形象', content: '角色正面全身设定，统一服装纹样与色彩……', tag: 'role', shared: false, owned: true, updateTime: '2026-08-16' },
      { id: 't2', title: '电影感夜景', description: '霓虹城市环境提示词', content: '雨夜街道，青色与品红色霓虹倒影，电影级光影……', tag: 'scene', shared: true, owned: false, updateTime: '2026-08-14' },
    ]
    if (path.startsWith('/asset/list')) return { items: [
      { id: 'a1', name: '小师妹', description: '图片', type: 'image', cover: demoAssetCover('#d9edf0', '#253b42', '小师妹 · 角色设定'), boundProjectIds: ['p2'], updateTime: '2026-08-03' },
      { id: 'a2', name: '女主-青色', description: '图片', type: 'image', cover: demoAssetCover('#dcecee', '#334a50', '女主 · 青色服装'), boundProjectIds: ['p1'], updateTime: '2026-07-30' },
      { id: 'a4', name: '女主', description: '图片', type: 'image', cover: demoAssetCover('#f0dfdf', '#563942', '女主 · 粉色服装'), boundProjectIds: ['p1'], updateTime: '2026-07-30' },
      { id: 'a5', name: '古城长街', description: '场景图', type: 'scene', cover: demoAssetCover('#1f3340', '#df8745', '古城长街 · 夜景'), boundProjectIds: ['p1', 'p2'], updateTime: '2026-07-28' },
      { id: 'a3', name: '环境氛围音', description: '街道人群环境声', type: 'audio', duration: '00:32', updateTime: '2026-08-14' },
    ], total: 5, page: 1, pageSize: 12, totalPages: 1 }
    return null
  }
  return window.pywebview.api.backend_request(method, path, props.token, body)
}

async function loadSection() {
  loading.value = true
  error.value = ''
  try {
    if (props.section === 'projects') projects.value = await request('GET', '/project/list') || []
    if (props.section === 'prompts') prompts.value = await request('GET', `/prompt/list?scope=${promptScope.value}&limit=50`) || []
    if (props.section === 'assets') {
      const params = new URLSearchParams({ page: String(assetPage.value), pageSize: String(assetPageSize.value) })
      const typeFilter = activeFilter.value === 'all' ? '' : activeFilter.value
      if (typeFilter) params.set('type', typeFilter)
      if (assetProjectFilter.value !== 'all') params.set('projectId', assetProjectFilter.value)
      if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
      const [assetData, projectData] = await Promise.all([request('GET', `/asset/list?${params.toString()}`), request('GET', '/project/list')])
      const envelope = Array.isArray(assetData) ? { items: assetData } : (assetData || {})
      assets.value = envelope.items || []
      const pageIds = assets.value.map(item => String(item.id))
      selectedAssetIds.value = selectedAssetIds.value.filter(id => pageIds.includes(id))
      assetTotal.value = envelope.total ?? assets.value.length
      assetTotalPages.value = envelope.totalPages ?? 1
      allProjects.value = projectData || []
    }
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    loading.value = false
  }
}

watch(() => props.section, () => {
  keyword.value = ''
  activeFilter.value = 'all'
  modalOpen.value = false
  promptScope.value = 'all'
  clearSelection()
  batchDeleteOpen.value = false
  loadSection()
}, { immediate: true })

watch(promptScope, () => { if (props.section === 'prompts') loadSection() })

function resetForms() {
  Object.assign(projectForm, { name: '', description: '', style: '3d-xiuxian', styleDesc: '', ratio: '16:9' })
  Object.assign(promptForm, { title: '', description: '', content: '', tag: activeFilter.value === 'all' ? 'role' : activeFilter.value, shared: false, image: '' })
  Object.assign(assetForm, { name: '', description: '', tags: '', type: activeFilter.value === 'all' ? 'image' : activeFilter.value, boundProjectIds: [] })
  editingId.value = ''
  error.value = ''
}

function openCreate() {
  resetForms()
  modalOpen.value = true
}

function editPrompt(item) {
  editingId.value = String(item.id)
  Object.assign(promptForm, {
    title: item.title || '',
    description: item.description || '',
    content: item.content || '',
    tag: item.tag || 'role',
    shared: Boolean(item.shared),
    image: item.image || '',
  })
  modalOpen.value = true
}

function editAsset(item) {
  editingId.value = String(item.id)
  Object.assign(assetForm, {
    name: item.name || '', description: item.description || '', tags: item.tags || '', type: item.type || 'image',
    boundProjectIds: Array.isArray(item.boundProjectIds) ? item.boundProjectIds.map(String) : [],
  })
  modalOpen.value = true
}

async function submitForm() {
  error.value = ''
  submitting.value = true
  try {
    if (props.section === 'projects') {
      if (!projectForm.name.trim()) throw new Error('请输入项目名称')
      await request('POST', '/project', {
        name: projectForm.name.trim(),
        description: projectForm.description.trim(),
        style: projectForm.style,
        styleDesc: projectStyleDescription.value,
        ratio: projectForm.ratio,
        coverId: '',
      })
    } else if (props.section === 'prompts') {
      if (!promptForm.title.trim() || !promptForm.content.trim()) throw new Error('请输入提示词标题和内容')
      const path = editingId.value ? `/prompt/${editingId.value}` : '/prompt'
      await request(editingId.value ? 'PUT' : 'POST', path, { ...promptForm, title: promptForm.title.trim(), content: promptForm.content.trim(), image: promptForm.image.trim() })
    } else if (editingId.value) {
      if (!assetForm.name.trim()) throw new Error('请输入资产名称')
      await request('PUT', `/asset/${editingId.value}`, { ...assetForm, name: assetForm.name.trim() })
    } else {
      if (!window.pywebview?.api) throw new Error('请从桌面客户端选择文件上传')
      await window.pywebview.api.select_and_upload_asset(props.token, { ...assetForm })
    }
    modalOpen.value = false
    await loadSection()
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    submitting.value = false
  }
}

function askDelete(item) {
  deleteTarget.value = item
}

function askBatchDelete() {
  if (!selectedAssetIds.value.length) return
  batchDeleteOpen.value = true
}

async function confirmBatchDelete() {
  const ids = selectedAssetIds.value.slice()
  if (!ids.length) return
  submitting.value = true
  error.value = ''
  try {
    await Promise.all(ids.map(id => request('DELETE', `/asset/${encodeURIComponent(id)}`)))
    batchDeleteOpen.value = false
    clearSelection()
    await loadSection()
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    submitting.value = false
  }
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  const item = deleteTarget.value
  const base = props.section === 'projects' ? '/project/' : props.section === 'prompts' ? '/prompt/' : '/asset/'
  submitting.value = true
  try {
    await request('DELETE', base + encodeURIComponent(item.id))
    deleteTarget.value = null
    await loadSection()
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    submitting.value = false
  }
}

async function copyPrompt(item) {
  await navigator.clipboard.writeText(item.content || '')
  copiedId.value = String(item.id)
  window.setTimeout(() => { copiedId.value = '' }, 1200)
}

async function selectPromptCover() {
  if (coverUploading.value) return
  try {
    const selected = await window.pywebview.api.select_image()
    if (!selected?.path) return
    coverUploading.value = true
    const uploaded = await window.pywebview.api.upload_local_file(props.token, selected.path)
    if (uploaded?.id) {
      promptForm.image = `/file/${uploaded.id}/download`
    }
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    coverUploading.value = false
  }
}

function removePromptCover() { promptForm.image = '' }

function openPromptView(item) { viewingPrompt.value = item; viewDialogOpen.value = true }
function openCoverPreview(item) { promptCoverPreviewSrc.value = promptImageUrl(item) }

function fileUrl(id) {
  if (!id) return ''
  const base = String(id).startsWith('local_') ? props.storageBase : props.apiBase
  return `${base}/file/${encodeURIComponent(id)}/download`
}

function assetUrl(item) { return item?.cover || fileUrl(item?.coverId) }
// 规范化提示词封面 URL：数据库存的是相对路径 /file/xxx/download，前端 img 需要拼 apiBase
function promptImageUrl(item) {
  const url = item?.image || ''
  if (!url) return ''
  if (/^https?:\/\//.test(url)) return url
  const base = /\/file\/local_[^/]+\/download/.test(url) ? props.storageBase : props.apiBase
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`
}
// 表单封面预览 URL（promptForm.image 存的是相对路径，img 需要完整 URL）
const promptFormCoverUrl = computed(() => {
  const url = promptForm.image
  if (!url) return ''
  if (/^https?:\/\//.test(url)) return url
  const base = /\/file\/local_[^/]+\/download/.test(url) ? props.storageBase : props.apiBase
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`
})

function formatAudioTime(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

function audioTimeLabel(item) {
  if (String(item?.id) === activeAudioId.value && audioDuration.value > 0) {
    return `${formatAudioTime(audioCurrent.value)} / ${formatAudioTime(audioDuration.value)}`
  }
  const savedDuration = String(item?.duration || '').trim()
  if (/^\d{1,3}:\d{2}$/.test(savedDuration)) return savedDuration
  if (/^\d+(\.\d+)?$/.test(savedDuration)) return formatAudioTime(savedDuration)
  return assetUrl(item) ? '点击播放' : '音频文件不可用'
}

function audioBarPlayed(item, index) {
  if (String(item?.id) !== activeAudioId.value || !audioDuration.value) return false
  return index / 24 <= audioCurrent.value / audioDuration.value
}

async function toggleAudio(item) {
  const url = assetUrl(item)
  if (!url || !audioPlayer.value) return
  const player = audioPlayer.value
  audioError.value = ''
  if (activeAudioId.value === String(item.id)) {
    if (player.paused) {
      try { await player.play() } catch { audioError.value = '音频暂时无法播放' }
    } else player.pause()
    return
  }
  player.pause()
  activeAudioId.value = String(item.id)
  activeAudioUrl.value = url
  audioCurrent.value = 0
  audioDuration.value = 0
  await nextTick()
  player.load()
  try { await player.play() } catch { audioError.value = '音频暂时无法播放' }
}

function syncAudioMetadata(event) {
  audioDuration.value = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0
}

function syncAudioTime(event) {
  audioCurrent.value = Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0
}

function stopAudio() {
  audioPlayer.value?.pause()
  audioPlaying.value = false
}

onBeforeUnmount(stopAudio)

function demoAssetCover(background, accent, label) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="460" viewBox="0 0 960 460"><rect width="960" height="460" fill="${background}"/><circle cx="210" cy="175" r="74" fill="${accent}" opacity=".86"/><path d="M90 440c18-145 76-220 124-220s111 75 133 220" fill="${accent}" opacity=".75"/><g fill="none" stroke="${accent}" stroke-width="18" opacity=".62"><path d="M430 110h390M430 165h300M430 220h350M430 275h250"/></g><text x="430" y="370" fill="${accent}" font-family="sans-serif" font-size="31" font-weight="700">${label}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

function projectName(id) { return allProjects.value.find(item => String(item.id) === String(id))?.name || '未命名项目' }

function formatDate(value) {
  return value ? String(value).slice(0, 10) : ''
}

function typeLabel(type) {
  return ({ image: '图片', scene: '场景', audio: '音频', prop: '道具', role: '角色', storyboard: '故事版' })[type] || '未分类'
}
</script>

<template>
  <section class="library-page" :class="{ 'project-workspace-page': section === 'projects', 'prompt-library-page': section === 'prompts', 'asset-library-page': section === 'assets' }">
    <template v-if="section === 'projects'">
      <header class="project-workspace-head">
        <div class="project-head-copy">
          <span class="project-eyebrow">PROJECT WORKSPACE</span>
          <div class="project-title-row"><h1>全部项目</h1><b>{{ projects.length }} 个项目</b></div>
          <p>管理剧本、角色、场景与分镜制作进度。</p>
        </div>

        <div class="project-head-art" aria-hidden="true">
          <span class="hero-script"><i></i><i></i><i></i></span>
          <span class="hero-shot hero-shot-top"></span>
          <span class="hero-shot hero-shot-bottom"></span>
          <svg viewBox="0 0 250 130"><path d="M90 65 C125 65 122 32 164 32M90 68 C125 68 122 98 164 98" /></svg>
        </div>

        <div class="project-head-actions">
          <label class="project-search">
            <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
            <input v-model="keyword" type="search" placeholder="搜索项目" aria-label="搜索项目" />
          </label>
          <button class="project-create-button" @click="openCreate">
            <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>新建项目
          </button>
        </div>
      </header>

      <p v-if="error && !modalOpen" class="library-error" role="alert">{{ error }}</p>
      <div v-if="loading" class="project-workspace-grid">
        <article v-for="index in 4" :key="index" class="client-project-card project-skeleton"><i></i><b></b><span></span></article>
      </div>
      <div v-else class="project-workspace-grid">
        <article v-if="!keyword" class="client-create-project">
          <button class="client-create-panel" @click="openCreate">
            <span class="client-new-project-visual" aria-hidden="true">
              <span class="client-new-script"><i></i><i></i><i></i></span>
              <span class="client-new-frame"><i></i><b></b></span>
              <span class="client-new-plus"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg></span>
            </span>
            <strong>开始创作</strong>
          </button>
          <div class="client-studio-bar">
            <svg viewBox="0 0 18 18"><path d="M3 6.5v5M6 4.5v9M9 7v4M12 5.5v7M15 3.5v11" /></svg><span>CDTV Studio</span>
          </div>
        </article>

        <article v-for="(item, index) in displayedItems" :key="item.id" class="client-project-card" role="button" tabindex="0" @click="emit('openProject', item)" @keydown.enter="emit('openProject', item)">
          <div class="client-project-cover">
            <img v-if="item.coverId" :src="fileUrl(item.coverId)" :alt="item.name" />
            <div v-else class="client-generated-cover" :class="`client-generated-cover-${index % 3}`" aria-hidden="true">
              <span class="client-generated-script"><i></i><i></i><i></i></span>
              <svg class="client-generated-flow" viewBox="0 0 226 128" preserveAspectRatio="none"><path d="M75 64 C101 64 101 38 126 38"/><path d="M75 67 C101 67 101 92 126 92"/></svg>
              <span class="client-generated-frame client-generated-frame-top"><i></i><b></b></span>
              <span class="client-generated-frame client-generated-frame-bottom"><i></i><b></b></span>
              <span class="client-generated-play"><svg viewBox="0 0 16 16"><path d="m6 4 6 4-6 4V4Z" /></svg></span>
            </div>
          </div>
          <div class="client-project-info">
            <div class="client-project-name-row"><h2>{{ item.name || '未命名项目' }}</h2><button aria-label="删除项目" data-tooltip="删除项目" @click.stop="askDelete(item)"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></button></div>
            <p>{{ item.description || '暂未添加项目描述' }}</p>
            <footer><time>{{ formatDate(item.updateTime) }}</time><span>{{ item.style || item.ratio || '16:9' }}</span></footer>
          </div>
        </article>

        <div v-if="keyword && !displayedItems.length" class="project-search-empty">
          <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg><strong>没有找到相关项目</strong><span>换一个关键词试试</span>
        </div>
      </div>
    </template>

    <template v-else-if="section === 'assets'">
      <audio ref="audioPlayer" class="asset-audio-engine" :src="activeAudioUrl" preload="metadata" @loadedmetadata="syncAudioMetadata" @durationchange="syncAudioMetadata" @timeupdate="syncAudioTime" @play="audioPlaying = true" @pause="audioPlaying = false" @ended="audioPlaying = false; audioCurrent = 0" @error="audioError = '音频暂时无法播放'; audioPlaying = false"></audio>
      <header class="asset-library-head">
        <div class="asset-head-copy">
          <span class="asset-eyebrow">ASSET LIBRARY</span>
          <div class="asset-title-line"><h1>我的资产</h1><b>{{ assetTotal }} 个资产</b></div>
          <p>集中管理创作中使用的图片、场景、音频与道具</p>
        </div>
        <div class="asset-head-art" aria-hidden="true">
          <span class="asset-art-card asset-art-card-image"><i></i><b></b></span>
          <span class="asset-art-card asset-art-card-scene"><i></i><b></b></span>
          <span class="asset-art-card asset-art-card-audio"><i></i><b></b></span>
          <svg viewBox="0 0 220 120"><path d="M40 60 C70 60 75 35 110 35M40 62 C70 62 75 88 110 88M115 35 C150 35 155 60 185 60M115 88 C150 88 155 62 185 62" /></svg>
        </div>
        <div class="asset-head-actions">
          <div class="asset-project-filter"><UiSelect v-model="assetProjectFilter" :options="assetProjectOptions" aria-label="按项目筛选资产" /></div>
          <label class="asset-search">
            <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
            <input v-model="keyword" type="search" placeholder="搜索资产" aria-label="搜索资产" />
          </label>
          <button class="asset-upload-button" @click="openCreate">
            <svg viewBox="0 0 24 24"><path d="M12 4v12M8 8l4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>上传资产
          </button>
        </div>
      </header>
      <div class="asset-library-toolbar">
        <div class="asset-filter-tabs"><button v-for="filter in filters" :key="filter.value" :class="[`asset-filter-${filter.value}`, { active: activeFilter === filter.value }]" @click="activeFilter = filter.value"><i v-if="filter.value !== 'all'"></i>{{ filter.label === '场景' ? '场景图' : filter.label }}</button></div>
        <div class="asset-toolbar-side">
          <label v-if="assets.length" class="asset-select-all"><input type="checkbox" :checked="allCurrentPageSelected" :indeterminate="someCurrentPageSelected && !allCurrentPageSelected" @change="toggleSelectAll" /><span>全选本页</span></label>
          <button v-if="selectedCount" class="asset-batch-delete" @click="askBatchDelete"><svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M5 7l1 13a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-13M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/></svg>删除选中（{{ selectedCount }}）</button>
          <span v-else class="asset-toolbar-meta">共 {{ assetTotal }} 项 · 按更新时间排序</span>
        </div>
      </div>
      <p v-if="error && !modalOpen" class="library-error" role="alert">{{ error }}</p>
      <div v-if="loading && !assets.length" class="asset-client-grid" aria-label="正在加载我的资产">
        <article v-for="n in 4" :key="n" class="asset-client-card asset-loading-card" aria-hidden="true">
          <i class="asset-loading-cover"></i>
          <div class="asset-loading-info"><b></b><span></span><footer><i></i><em></em></footer></div>
        </article>
      </div>
      <div v-else-if="displayedItems.length" class="asset-client-grid" :class="{ 'is-refreshing': loading }">
        <article v-for="item in displayedItems" :key="item.id" class="asset-client-card" :class="{ 'is-selected': isSelected(item.id) }" :data-type="item.type">
          <label class="asset-select-box" :aria-label="`选择 ${item.name}`" @click.stop>
            <input type="checkbox" :checked="isSelected(item.id)" @change="toggleSelect(item.id)" />
          </label>
          <button class="asset-client-main" type="button" :aria-label="item.type === 'audio' ? `${audioPlaying && activeAudioId === String(item.id) ? '暂停' : '播放'} ${item.name}` : `放大预览 ${item.name}`" @click="item.type === 'audio' ? toggleAudio(item) : (assetUrl(item) ? previewAsset = item : null)">
            <div class="asset-client-cover">
              <img v-if="assetUrl(item) && item.type !== 'audio'" :src="assetUrl(item)" :alt="item.name" />
              <div v-else-if="item.type === 'audio'" class="asset-audio-cover" :class="{ 'is-active': activeAudioId === String(item.id), 'is-playing': audioPlaying && activeAudioId === String(item.id), 'is-unavailable': !assetUrl(item) }">
                <svg class="asset-audio-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg>
                <button type="button" class="asset-audio-play" :aria-label="audioPlaying && activeAudioId === String(item.id) ? '暂停' : '播放'"><svg v-if="audioPlaying && activeAudioId === String(item.id)" viewBox="0 0 24 24"><path d="M7 6h3.5v12H7zM13.5 6H17v12h-3.5z" /></svg><svg v-else viewBox="0 0 24 24"><path d="m9 6 9 6-9 6V6Z" /></svg></button>
                <span class="asset-audio-time">{{ audioTimeLabel(item) }}</span>
              </div>
              <div v-else class="cover-placeholder"><svg viewBox="0 0 24 24"><path d="M4 5h16v14H4zM7 15l3-3 3 3 2-2 3 3"/></svg></div>
              <span v-if="item.type !== 'audio' && assetUrl(item)" class="asset-zoom-hint" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4M11 8v6M8 11h6"/></svg></span>
            </div>
            <div class="asset-client-info">
              <div class="asset-client-title"><h2>{{ item.name || '未命名资产' }}</h2><span v-if="item.boundProjectIds?.length" class="asset-project-count" :data-tooltip="item.boundProjectIds.map(projectName).join('、')"><svg viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z" /></svg>{{ item.boundProjectIds.length }} 个项目</span><span class="asset-type-pill"><i></i>{{ typeLabel(item.type) }}</span></div>
              <footer><span>{{ item.description || typeLabel(item.type) }}</span><time>{{ formatDate(item.updateTime) }}</time></footer>
            </div>
          </button>
          <div class="asset-card-actions-client"><button data-tooltip="编辑资产" aria-label="编辑资产" @click="editAsset(item)"><svg viewBox="0 0 24 24"><path d="m4 16.5-.5 4 4-.5L19 8.5 15.5 5 4 16.5Z"/><path d="m13.5 7 3.5 3.5"/></svg></button><button class="danger" data-tooltip="删除资产" aria-label="删除资产" @click="askDelete(item)"><svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M5 7l1 13a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-13M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/></svg></button></div>
        </article>
      </div>
      <nav v-if="!loading && assetTotalPages > 1" class="asset-pagination" aria-label="资产分页">
        <div class="asset-page-size">
          <span>每页</span>
          <UiSelect v-model="assetPageSize" :options="assetPageSizeOptions" drop="up" :searchable="false" aria-label="每页显示数量" />
        </div>
        <div class="asset-page-controls">
          <button class="asset-page-nav" :disabled="assetPage <= 1" aria-label="上一页" @click="goAssetPage(assetPage - 1)">上一页</button>
          <button v-for="page in assetPageNumbers" :key="page" class="asset-page-num" :class="{ active: page === assetPage }" :aria-current="page === assetPage ? 'page' : undefined" @click="goAssetPage(page)">{{ page }}</button>
          <button class="asset-page-nav" :disabled="assetPage >= assetTotalPages" aria-label="下一页" @click="goAssetPage(assetPage + 1)">下一页</button>
        </div>
      </nav>
      <div v-if="!loading && !displayedItems.length" class="library-empty"><svg viewBox="0 0 64 64"><rect x="12" y="13" width="40" height="38" rx="9"/><path d="M20 40l9-10 7 7 5-5 5 8"/><circle cx="25" cy="25" r="3"/></svg><strong>还没有我的资产</strong><span>点击“上传资产”添加第一份素材</span></div>
    </template>

    <template v-else>
      <header class="library-page-head">
        <div>
          <span>{{ sectionMeta.eyebrow }}</span>
          <div class="library-title-row"><h1>{{ sectionMeta.title }}</h1><b>{{ displayedItems.length }}</b></div>
          <p>{{ sectionMeta.subtitle }}</p>
        </div>
        <div class="library-head-actions">
          <div class="prompt-scope-switch">
            <button :class="{ active: promptScope === 'all' }" @click="promptScope = 'all'">全部</button>
            <button :class="{ active: promptScope === 'mine' }" @click="promptScope = 'mine'">我的</button>
            <button :class="{ active: promptScope === 'shared' }" @click="promptScope = 'shared'">共享</button>
          </div>
          <button class="library-primary" @click="openCreate"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>{{ sectionMeta.action }}</button>
        </div>
      </header>

      <div class="library-toolbar">
        <div class="library-filters"><button v-for="filter in filters" :key="filter.value" :class="{ active: activeFilter === filter.value }" @click="activeFilter = filter.value"><i v-if="filter.value !== 'all'" class="filter-dot" :class="`filter-dot-${filter.value}`"></i>{{ filter.label }}</button></div>
        <label class="library-search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg><input v-model="keyword" type="search" :placeholder="`搜索${sectionMeta.title}`" :aria-label="`搜索${sectionMeta.title}`" /></label>
      </div>

      <p v-if="error && !modalOpen" class="library-error" role="alert">{{ error }}</p>
      <div v-if="loading" class="library-grid library-grid-prompts prompt-skeleton-grid" role="status" aria-label="正在加载提示词">
        <article v-for="n in 6" :key="n" class="library-card prompt-skeleton-card" aria-hidden="true">
          <div class="prompt-skeleton-accent"><i></i><span></span></div>
          <div class="prompt-skeleton-body"><b></b><i></i><i></i><pre></pre><footer><span></span><em></em></footer></div>
        </article>
      </div>
      <div v-else-if="displayedItems.length" class="library-grid" :class="`library-grid-${section}`">
        <article v-for="item in displayedItems" :key="item.id" class="library-card prompt-card-v2" :data-category="item.tag" :class="{ 'is-viewable': !item.owned }" @click="!item.owned && openPromptView(item)">
          <button v-if="item.image" type="button" class="prompt-card-cover" @click.stop="openCoverPreview(item)">
            <img :src="promptImageUrl(item)" :alt="item.title" loading="lazy" />
            <span class="prompt-card-cover-zoom"><svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4 4M10.5 7.5v6M7.5 10.5h6"/></svg></span>
          </button>
          <div class="prompt-card-text">{{ item.content }}</div>
          <div class="prompt-card-footer">
            <div class="prompt-card-footer-info">
              <span class="prompt-card-category"><i class="filter-dot" :class="`filter-dot-${item.tag}`"></i>{{ typeLabel(item.tag) }}</span>
              <span class="prompt-card-footer-name">
                <svg v-if="item.shared" class="prompt-card-shared-icon" viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M3 10h14M10 3c2 2 3 4.3 3 7s-1 5-3 7c-2-2-3-4.3-3-7s1-5 3-7Z"/></svg>
                <strong>{{ item.title || '未命名提示词' }}</strong>
              </span>
              <span class="prompt-card-footer-desc">{{ item.description || '暂无简介' }}</span>
            </div>
            <div class="prompt-inline-actions">
              <button type="button" :class="{ copied: copiedId === String(item.id) }" :aria-label="copiedId === String(item.id) ? '已复制' : '复制'" @click.stop="copyPrompt(item)">
                <svg v-if="copiedId !== String(item.id)" viewBox="0 0 20 20"><rect x="6" y="6" width="10" height="10" rx="2"/><path d="M4 13H3a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/></svg>
                <svg v-else viewBox="0 0 20 20"><path d="m4 10 4 4 8-9"/></svg>
              </button>
              <button v-if="item.owned" type="button" aria-label="编辑" @click.stop="editPrompt(item)"><svg viewBox="0 0 20 20"><path d="m4 13-.7 3.7L7 16l8.8-8.8-3-3L4 13Z"/><path d="m11.8 5.2 3 3"/></svg></button>
              <button v-if="item.owned" type="button" class="danger" aria-label="删除" @click.stop="askDelete(item)"><svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M5 7l1 13a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-13M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/></svg></button>
              <span v-if="!item.owned" class="prompt-card-open-hint">查看<svg viewBox="0 0 16 16"><path d="M3 8h10M9 4l4 4-4 4"/></svg></span>
            </div>
          </div>
        </article>
      </div>
      <div v-else class="library-empty"><svg viewBox="0 0 64 64"><rect x="12" y="13" width="40" height="38" rx="9"/><path d="M20 40l9-10 7 7 5-5 5 8"/><circle cx="25" cy="25" r="3"/></svg><strong>还没有{{ sectionMeta.title }}</strong><span>点击右上角按钮开始创建</span></div>
    </template>

    <div v-if="modalOpen" class="library-modal-backdrop" @click.self="modalOpen = false">
      <form class="library-modal" @submit.prevent="submitForm">
        <header><div><span>{{ sectionMeta.eyebrow }}</span><h2>{{ editingId ? (section === 'assets' ? '编辑资产' : '编辑提示词') : sectionMeta.action }}</h2></div><button type="button" aria-label="关闭" @click="modalOpen = false">×</button></header>
        <template v-if="section === 'projects'">
          <label class="library-field">项目名称<input v-model="projectForm.name" maxlength="100" placeholder="例如：夏日奇遇" /></label>
          <label class="library-field">项目简介<textarea v-model="projectForm.description" placeholder="简单描述项目内容（选填）"></textarea></label>
          <fieldset class="library-style-field">
            <legend>风格</legend>
            <div class="library-style-groups">
              <div v-for="group in projectStyleGroups" :key="group.label" class="library-style-group">
                <span class="library-style-group-title">{{ group.label }}</span>
                <div class="library-style-group-options">
                  <label v-for="option in group.options" :key="option.value" :data-tooltip="option.desc">
                    <input v-model="projectForm.style" type="radio" :value="option.value" />
                    <span>{{ option.label }}</span>
                  </label>
                </div>
              </div>
            </div>
            <p v-if="projectStyleDescription" class="library-style-desc">{{ projectStyleDescription }}</p>
          </fieldset>
          <fieldset class="library-ratio-field">
            <legend>视频比例</legend>
            <div class="library-ratio-options">
              <label v-for="option in projectRatioOptions" :key="option.value">
                <input v-model="projectForm.ratio" type="radio" :value="option.value" />
                <span class="library-ratio-card">
                  <i class="library-ratio-shape" :class="`library-ratio-${option.shape}`"></i>
                  <em class="library-ratio-label">{{ option.label }}</em>
                </span>
              </label>
            </div>
          </fieldset>
        </template>
        <template v-else-if="section === 'prompts'">
          <label>标题<input v-model="promptForm.title" maxlength="255" placeholder="提示词标题" /></label>
          <label>分类<UiSelect v-model="promptForm.tag" class="project-ratio-select" :options="[{ label: '角色', value: 'role' }, { label: '场景', value: 'scene' }, { label: '故事版', value: 'storyboard' }]" /></label>
          <label>简介<input v-model="promptForm.description" placeholder="一句话说明用途" /></label>
          <label>提示词内容<textarea v-model="promptForm.content" class="content-editor" placeholder="输入完整提示词"></textarea></label>
          <label>封面图片
            <div class="prompt-cover-upload" :class="{ 'has-cover': promptForm.image, 'is-uploading': coverUploading }" @click="selectPromptCover">
              <template v-if="promptForm.image">
                <img :src="promptFormCoverUrl" alt="封面预览" />
                <div class="prompt-cover-overlay">
                  <strong>{{ coverUploading ? '上传中…' : '点击替换' }}</strong>
                </div>
                <button type="button" class="prompt-cover-remove" @click.stop="removePromptCover"><svg viewBox="0 0 20 20"><path d="M5 5l10 10M15 5 5 15"/></svg></button>
              </template>
              <template v-else>
                <svg class="prompt-cover-icon" viewBox="0 0 24 24"><path d="M12 16V5m0 0L8 9m4-4 4 4"/><path d="M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"/></svg>
                <span><strong>{{ coverUploading ? '上传中…' : '点击上传封面' }}</strong></span>
              </template>
            </div>
          </label>
          <label class="library-check"><input v-model="promptForm.shared" type="checkbox" />公开共享</label>
        </template>
        <template v-else>
          <p class="upload-help">{{ editingId ? '修改资产信息和绑定项目。' : '填写信息后选择本地文件，上传完成后会自动加入“我的资产”。' }}</p>
          <label>资产类型<UiSelect v-model="assetForm.type" class="project-ratio-select" :options="[{ label: '图片', value: 'image' }, { label: '场景', value: 'scene' }, { label: '音频', value: 'audio' }, { label: '道具', value: 'prop' }]" /></label>
          <label>名称<input v-model="assetForm.name" :placeholder="editingId ? '资产名称' : '不填写则使用文件名'" /></label>
          <label>描述<input v-model="assetForm.description" placeholder="资产用途或内容" /></label>
          <label>标签<input v-model="assetForm.tags" placeholder="多个标签用逗号分隔" /></label>
          <fieldset class="asset-project-field"><legend>绑定项目（可选多个）</legend><div v-if="allProjects.length" class="asset-project-options"><label v-for="project in allProjects" :key="project.id"><input v-model="assetForm.boundProjectIds" type="checkbox" :value="String(project.id)" /><span>{{ project.name || '未命名项目' }}</span></label></div><p v-else>暂无项目，请先创建项目</p></fieldset>
        </template>
        <p v-if="error" class="library-error" role="alert">{{ error }}</p>
        <footer><button type="button" @click="modalOpen = false">取消</button><button class="library-primary" type="submit" :disabled="submitting">{{ submitting ? '处理中…' : section === 'assets' && !editingId ? '选择文件并上传' : '保存' }}</button></footer>
      </form>
    </div>

    <BaseMediaPreview
      v-model:visible="previewVisible"
      :src="previewSrc"
      :type="previewType"
    />

    <div v-if="deleteTarget" class="library-modal-backdrop" @click.self="deleteTarget = null">
      <section class="delete-dialog"><span>DELETE</span><h2>确认删除？</h2><p>“{{ deleteTarget.name || deleteTarget.title || '未命名内容' }}”删除后无法恢复。</p><footer><button @click="deleteTarget = null">取消</button><button class="danger" :disabled="submitting" @click="confirmDelete">删除</button></footer></section>
    </div>

    <div v-if="batchDeleteOpen" class="library-modal-backdrop" @click.self="batchDeleteOpen = false">
      <section class="delete-dialog"><span>DELETE</span><h2>确认批量删除？</h2><p>已选中 {{ selectedCount }} 个资产，删除后无法恢复。</p><footer><button @click="batchDeleteOpen = false">取消</button><button class="danger" :disabled="submitting" @click="confirmBatchDelete">{{ submitting ? '删除中…' : '删除' }}</button></footer></section>
    </div>

    <div v-if="viewDialogOpen" class="library-modal-backdrop" @click.self="viewDialogOpen = false">
      <section class="library-modal prompt-viewer-modal">
        <header><div><span>{{ sectionMeta.eyebrow }}</span><h2>{{ viewingPrompt?.title || '查看提示词' }}</h2></div><button type="button" aria-label="关闭" @click="viewDialogOpen = false">×</button></header>
        <div v-if="viewingPrompt" class="prompt-viewer" :data-category="viewingPrompt.tag">
          <div class="prompt-viewer-meta">
            <span><i class="filter-dot" :class="`filter-dot-${viewingPrompt.tag}`"></i>{{ typeLabel(viewingPrompt.tag) }}</span>
            <span v-if="viewingPrompt.shared" class="prompt-viewer-public"><svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M3 10h14M10 3c2 2 3 4.3 3 7s-1 5-3 7c-2-2-3-4.3-3-7s1-5 3-7Z"/></svg>公开共享</span>
          </div>
          <img v-if="viewingPrompt.image" class="prompt-viewer-cover" :src="promptImageUrl(viewingPrompt)" :alt="viewingPrompt.title" />
          <p v-if="viewingPrompt.description" class="prompt-viewer-description">{{ viewingPrompt.description }}</p>
          <div class="prompt-viewer-content">{{ viewingPrompt.content }}</div>
        </div>
        <footer><button type="button" @click="viewDialogOpen = false">关闭</button><button class="library-primary" type="button" @click="copyPrompt(viewingPrompt)">{{ copiedId === String(viewingPrompt?.id) ? '已复制' : '复制提示词' }}</button></footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
:global(body:has(.prompt-library-page)) { min-width: 0; }
.library-page { position: relative; z-index: 1; max-width: 1120px; min-height: calc(100vh - 120px); margin: 0 auto; padding: 28px 0 60px; }
.project-workspace-page { max-width: 1540px; padding-top: 24px; }
.prompt-library-page { width: 100%; max-width: none; box-sizing: border-box; padding: 28px clamp(16px,3vw,48px) 60px; container-type: inline-size; }
.asset-library-page { max-width: 1540px; padding: 34px clamp(18px,3vw,46px) 60px; }
.asset-library-head { position: relative; display: flex; min-height: 148px; align-items: center; justify-content: space-between; gap: 32px; padding: 26px clamp(22px,3vw,42px); border: 1px solid #2e2e2e; border-radius: 20px; background: #191919; box-shadow: 0 18px 50px #0000001c; }
.asset-library-head::before { position: absolute; inset: 0; overflow: hidden; border-radius: inherit; opacity: .28; background-image: radial-gradient(circle,#404040 1px,transparent 1px); background-size: 18px 18px; content: ''; mask-image: linear-gradient(90deg,transparent 18%,#000 52%,transparent 94%); -webkit-mask-image: linear-gradient(90deg,transparent 18%,#000 52%,transparent 94%); }
.asset-head-copy,.asset-head-actions { position: relative; z-index: 3; }
.asset-head-copy { min-width: 260px; }
.asset-eyebrow { display: inline-flex; align-items: center; gap: 9px; color: #9a9a9a; font-size: 12px; font-weight: 850; letter-spacing: .12em; }
.asset-eyebrow::before { width: 20px; height: 2px; border-radius: 2px; background: #60a5fa; content: ''; }
.asset-title-line { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.asset-title-line h1 { margin: 0; color: #f4f4f4; font-size: clamp(26px,2.6vw,34px); font-weight: 850; line-height: 1.1; letter-spacing: -.04em; }
.asset-title-line b { padding: 4px 9px; border: 1px solid #3a3a3a; border-radius: 999px; color: #9b9b9b; background: #202020; font-size: 12px; white-space: nowrap; }
.asset-head-copy p { margin: 12px 0 0; color: #8b8b8b; font-size: 13px; }
.asset-head-art { position: absolute; z-index: 1; top: 22px; left: 40%; width: 220px; height: 120px; opacity: .5; transform: translateX(-50%); pointer-events: none; }
.asset-head-art > svg { position: absolute; inset: 0; width: 100%; height: 100%; fill: none; stroke: #3a6a8a; stroke-width: 1.4; }
.asset-art-card { position: absolute; z-index: 2; display: block; border: 1px solid #404040; border-radius: 8px; background: #1d1d1d; box-shadow: 0 8px 18px #0006; }
.asset-art-card i { display: block; width: 100%; height: 60%; border-radius: 4px; margin: 4px 4px 0; width: calc(100% - 8px); }
.asset-art-card b { display: block; height: 3px; margin: 5px 4px; border-radius: 2px; background: #3a3a3a; width: calc(100% - 8px); }
.asset-art-card-image { top: 14px; left: 18px; width: 52px; height: 62px; border-color: #2e5a7a; transform: rotate(-5deg); }
.asset-art-card-image i { background: linear-gradient(135deg,#2a4a5e,#4a7a9e); }
.asset-art-card-scene { top: 12px; right: 18px; width: 56px; height: 58px; border-color: #7a4e2e; transform: rotate(4deg); }
.asset-art-card-scene i { background: linear-gradient(135deg,#5e3a2a,#9e6a4a); }
.asset-art-card-audio { bottom: 12px; left: 50%; width: 50px; height: 54px; border-color: #2e6a4e; transform: translateX(-50%) rotate(-1deg); }
.asset-art-card-audio i { background: linear-gradient(135deg,#2a5e3e,#4a9e6a); }
.asset-head-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; padding: 7px; border: 1px solid #393939; border-radius: 14px; background: #222222e6; box-shadow: 0 12px 30px #0003; backdrop-filter: blur(12px); }
.asset-search { display: flex; width: clamp(190px,18vw,260px); height: 38px; align-items: center; gap: 9px; padding: 0 13px; border: 1px solid #3a3a3a; border-radius: 20px; background: #1a1a1a; }
input[type="search"]::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
.asset-search:focus-within { border-color: #5c5c5c; }
.asset-search svg { width: 15px; flex: 0 0 auto; fill: none; stroke: #787878; stroke-width: 1.7; }
.asset-search input { min-width: 0; flex: 1; border: 0; outline: 0; color: #eee; background: transparent; font-size: 13px; }
.asset-upload-button { display: inline-flex; min-height: 38px; align-items: center; gap: 7px; padding: 0 15px; border: 1px solid #494949; border-radius: 10px; color: #fff; background: #252525; cursor: pointer; font-size: 13px; font-weight: 700; white-space: nowrap; transition: .16s; }
.asset-upload-button:hover,.asset-upload-button:focus-visible { border-color: #e8e8e8; outline: 0; background: #2b2b2b; box-shadow: 0 0 0 3px #ffffff12; }
.asset-upload-button svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.asset-library-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 20px 0 16px; }
.asset-project-filter { width: clamp(132px,14vw,180px); flex: 0 1 auto; }
.asset-project-filter :deep(.ui-select-trigger) { min-height: 38px; border-radius: 20px; background: #1a1a1a; }
.asset-filter-tabs { display: flex; flex-wrap: wrap; gap: 7px; }
.asset-filter-tabs button { height: 32px; padding: 0 13px; border: 1px solid #343434; border-radius: 9px; color: #898989; background: #1c1c1c; cursor: pointer; font-size: 12px; transition: .16s; }
.asset-filter-tabs button:hover { border-color: #4a4a4a; color: #d0d0d0; background: #242424; }
.asset-filter-tabs button.active { border-color: #515151; color: #f0f0f0; background: #2a2a2a; }
.asset-filter-tabs button i { display: inline-block; width: 6px; height: 6px; margin-right: 6px; border-radius: 50%; background: #555; vertical-align: middle; }
.asset-filter-tabs button.asset-filter-image i { background: #60a5fa; }
.asset-filter-tabs button.asset-filter-scene i { background: #fb923c; }
.asset-filter-tabs button.asset-filter-audio i { background: #34d399; }
.asset-filter-tabs button.asset-filter-prop i { background: #eab308; }
.asset-filter-tabs button.asset-filter-role i { background: #f472b6; }
.asset-filter-tabs button.asset-filter-storyboard i { background: #a78bfa; }
.asset-filter-tabs button.active i { box-shadow: 0 0 0 3px rgba(255,255,255,.08); }
.asset-toolbar-meta { color: #6a6a6a; font-size: 12px; white-space: nowrap; }
.asset-toolbar-side { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.asset-select-all { display: inline-flex; align-items: center; gap: 7px; color: #a8a8a8; font-size: 12px; cursor: pointer; user-select: none; }
.asset-select-all input { appearance: none; -webkit-appearance: none; width: 16px; height: 16px; margin: 0; border: 1.5px solid #4a4a4a; border-radius: 4px; background: #1a1a1a; cursor: pointer; position: relative; transition: background-color .15s, border-color .15s; }
.asset-select-all:hover input { border-color: #6a6a6a; }
.asset-select-all input:checked { border-color: #60a5fa; background: #60a5fa; }
.asset-select-all input:indeterminate { border-color: #60a5fa; background: #60a5fa; }
.asset-select-all input:checked::after { content: ''; position: absolute; left: 4px; top: 1px; width: 4px; height: 8px; border: solid #10141c; border-width: 0 2px 2px 0; transform: rotate(45deg); }
.asset-select-all input:indeterminate::after { content: ''; position: absolute; left: 3px; top: 6px; width: 8px; height: 2px; border-radius: 1px; background: #10141c; }
.asset-batch-delete { display: inline-flex; min-height: 32px; align-items: center; gap: 7px; padding: 0 13px; border: 1px solid #ff5b7d44; border-radius: 9px; color: #ff8ba3; background: #ff3f6814; cursor: pointer; font-size: 12px; font-weight: 700; transition: .16s; }
.asset-batch-delete:hover { border-color: #ff678566; color: #ffaebf; background: #ff3f6826; }
.asset-batch-delete svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; }
.asset-select-box { position: absolute; z-index: 6; top: 9px; left: 9px; display: grid; width: 24px; height: 24px; place-items: center; border-radius: 7px; background: #101216d9; box-shadow: 0 4px 12px #0008; cursor: pointer; opacity: 0; transform: translateY(-4px); transition: .15s; backdrop-filter: blur(8px); }
.asset-client-card:hover .asset-select-box,.asset-client-card:focus-within .asset-select-box,.asset-client-card.is-selected .asset-select-box { opacity: 1; transform: none; }
.asset-select-box input { appearance: none; -webkit-appearance: none; width: 16px; height: 16px; margin: 0; border: 1.5px solid #ffffff52; border-radius: 4px; background: transparent; cursor: pointer; position: relative; transition: background-color .15s, border-color .15s; }
.asset-select-box:hover input { border-color: #fff; }
.asset-select-box input:checked { border-color: #60a5fa; background: #60a5fa; }
.asset-select-box input:checked::after { content: ''; position: absolute; left: 4px; top: 1px; width: 4px; height: 8px; border: solid #10141c; border-width: 0 2px 2px 0; transform: rotate(45deg); }
.asset-client-card.is-selected { border-color: rgba(var(--asset-rgb),.75); box-shadow: 0 0 0 1px rgba(var(--asset-rgb),.5),0 14px 36px #0006; }
.asset-client-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 14px; }
.asset-client-grid.is-refreshing { opacity: .55; pointer-events: none; transition: opacity .18s; }
.asset-client-card { --asset-rgb: 96,165,250; position: relative; min-width: 0; overflow: hidden; border: 1px solid rgba(var(--asset-rgb),.18); border-radius: 14px; background: linear-gradient(160deg,#1e1e1e 0%,#161616 100%); transition: .22s cubic-bezier(.22,1,.36,1); }
.asset-client-card[data-type=scene] { --asset-rgb:251,146,60; }.asset-client-card[data-type=audio] { --asset-rgb:52,211,153; }.asset-client-card[data-type=prop] { --asset-rgb:234,179,8; }
.asset-client-card::after { position: absolute; inset: 0; border-radius: 14px; box-shadow: inset 0 1px 0 rgba(255,255,255,.04); pointer-events: none; content: ''; }
.asset-client-card:hover,.asset-client-card:focus-within { border-color: rgba(var(--asset-rgb),.5); box-shadow: 0 14px 36px #0006, 0 0 0 1px rgba(var(--asset-rgb),.08); transform: translateY(-3px); }
.asset-client-main { display: flex; width: 100%; height: 100%; flex-direction: column; padding: 0; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.asset-client-cover { position: relative; width: 100%; height: 172px; overflow: hidden; border-bottom: 1px solid rgba(var(--asset-rgb),.16); background: #141414; }
.asset-client-cover::before { position: absolute; inset: 0; z-index: 1; background: linear-gradient(180deg,transparent 60%,rgba(0,0,0,.35)); pointer-events: none; content: ''; }
.asset-client-cover>img { width: 100%; height: 100%; object-fit: cover; transition: .3s; }
.asset-client-card:hover .asset-client-cover>img { transform: scale(1.045); }
.asset-client-info { padding: 11px 13px 10px; }
.asset-client-title { display: flex; min-width: 0; height: 38px; align-items: center; gap: 7px; }
.asset-client-title h2 { min-width: 0; flex: 1; margin: 0; overflow: hidden; color: #eee; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.asset-type-pill,.asset-project-count { display: inline-flex; height: 20px; flex: 0 0 auto; align-items: center; gap: 5px; padding: 0 7px; border: 1px solid rgba(var(--asset-rgb),.22); border-radius: 99px; color: rgba(var(--asset-rgb),.88); background: rgba(var(--asset-rgb),.08); font-size: 11px; }
.asset-type-pill::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: rgba(var(--asset-rgb),.95); }
.asset-project-count { border-color: #393939; color: #888; background: #222; }
.asset-client-info footer { display: flex; align-items: center; gap: 8px; padding: 8px 0 2px; margin-top: 8px; border-top: 1px dashed #333; color: #888; font-size: 12px; }
.asset-client-info footer span { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #a8a8a8; letter-spacing: .1px; }
.asset-client-info footer time { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 99px; background: rgba(var(--asset-rgb), .12); color: rgba(var(--asset-rgb), .92); font-size: 11px; font-variant-numeric: tabular-nums; }
.asset-client-info footer time::before { content: ''; width: 4px; height: 4px; border-radius: 50%; background: rgba(var(--asset-rgb), .95); box-shadow: 0 0 0 2px rgba(var(--asset-rgb), .18); }
@media (max-width: 1280px) { .asset-client-grid { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@media (max-width: 900px) { .asset-client-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } .asset-head-art { display: none; } }
@media (max-width: 560px) { .asset-client-grid { grid-template-columns: 1fr; } .asset-library-head { flex-direction: column; align-items: stretch; } .asset-head-actions { width: 100%; } .asset-search { flex: 1; width: auto; } }
.asset-pagination { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 12px; margin: 22px 0 4px; }
.asset-pagination button { min-width: 34px; height: 34px; padding: 0 12px; border: 1px solid #343434; border-radius: 9px; color: #a8a8a8; background: #1c1c1c; cursor: pointer; font-size: 12px; transition: .16s; }
.asset-pagination button:hover:not(:disabled) { border-color: #4a4a4a; color: #f0f0f0; background: #242424; }
.asset-pagination button:disabled { opacity: .4; cursor: not-allowed; }
.asset-pagination .asset-page-num { padding: 0; }
.asset-pagination .asset-page-num.active { border-color: #515151; color: #f0f0f0; background: #2a2a2a; font-weight: 600; }
.asset-page-controls { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 8px; }
.asset-page-size { display: flex; align-items: center; gap: 8px; }
.asset-page-size > span { color: #6a6a6a; font-size: 12px; white-space: nowrap; }
.asset-page-size :deep(.ui-select) { width: 118px; }
.asset-page-size :deep(.ui-select-trigger) { min-height: 34px; border-radius: 9px; background: #1c1c1c; }
.asset-loading-card { min-height: 242px; pointer-events: none; animation: asset-skeleton-pulse 1.4s ease-in-out infinite; }
.asset-loading-card:hover { border-color: rgba(var(--asset-rgb),.2); box-shadow: none; transform: none; }
.asset-loading-cover { display: block; height: 168px; border-bottom: 1px solid #303030; background: linear-gradient(100deg,#232323 25%,#303030 50%,#232323 75%); background-size: 220% 100%; animation: asset-skeleton-shimmer 1.5s linear infinite; }
.asset-loading-info { padding: 13px 12px 10px; }
.asset-loading-info b,.asset-loading-info > span,.asset-loading-info footer i,.asset-loading-info footer em { display: block; border-radius: 5px; background: linear-gradient(100deg,#292929 25%,#363636 50%,#292929 75%); background-size: 220% 100%; animation: asset-skeleton-shimmer 1.5s linear infinite; }
.asset-loading-info b { width: 56%; height: 12px; }
.asset-loading-info > span { width: 34%; height: 8px; margin-top: 8px; }
.asset-loading-info footer { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; padding-top: 9px; border-top: 1px solid #2e2e2e; }
.asset-loading-info footer i { width: 42%; height: 7px; }
.asset-loading-info footer em { width: 24%; height: 7px; }
@keyframes asset-skeleton-pulse { 50% { opacity: .68; } }
@keyframes asset-skeleton-shimmer { to { background-position: -220% 0; } }
.asset-card-actions-client { position: absolute; z-index: 5; top: 9px; right: 9px; display: flex; gap: 4px; opacity: 0; transform: translateY(4px); transition: .15s; }.asset-client-card:hover .asset-card-actions-client,.asset-client-card:focus-within .asset-card-actions-client { opacity: 1; transform: none; }.asset-card-actions-client button { display: grid; width: 27px; height: 27px; place-items: center; border: 1px solid #ffffff38; border-radius: 7px; color: #aaa; background: #101216d9; box-shadow: 0 4px 12px #0008; cursor: pointer; backdrop-filter: blur(8px); }.asset-card-actions-client button:hover { color: #fff; background: #303030; }.asset-card-actions-client button.danger:hover { border-color: #ff678544; color: #ff8299; background: #ff486015; }.asset-card-actions-client svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; }.asset-zoom-hint { position: absolute; z-index: 2; right: 10px; bottom: 9px; padding: 5px 8px; border-radius: 7px; color: #fff; background: #090b0fc2; font-size: 11px; opacity: 0; }.asset-client-card:hover .asset-zoom-hint { opacity: 1; }.cover-placeholder { display: grid; width: 100%; height: 100%; place-items: center; background: #141414; }
.asset-audio-engine { position: fixed; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; }
.asset-audio-cover { position: relative; display: grid; width: 100%; height: 100%; place-items: center; overflow: hidden; background: #161616; }
.asset-audio-icon { position: relative; z-index: 1; width: 48px; height: 48px; fill: none; stroke: rgba(var(--asset-rgb),.42); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; transition: stroke .2s ease,transform .2s ease,filter .2s ease; }
.asset-audio-cover.is-active .asset-audio-icon { stroke: rgba(var(--asset-rgb),.95); filter: drop-shadow(0 0 10px rgba(var(--asset-rgb),.28)); }
.asset-audio-cover.is-playing .asset-audio-icon { animation: audio-pulse 1.2s ease-in-out infinite; }
.asset-audio-play { position: absolute; z-index: 2; right: 8px; bottom: 38px; display: grid; width: 34px; height: 34px; place-items: center; padding: 0; border: 1px solid rgba(var(--asset-rgb),.28); border-radius: 50%; color: rgba(var(--asset-rgb),.95); background: rgba(12,17,16,.9); box-shadow: 0 7px 20px #0008,inset 0 1px #ffffff0d; cursor: pointer; transform: scale(.82); opacity: 0; backdrop-filter: blur(8px); transition: opacity .2s ease,transform .2s ease,background .2s ease,border-color .2s ease,box-shadow .2s ease; }
.asset-client-card:hover .asset-audio-play { opacity: 1; transform: scale(1); }
.asset-audio-play:hover { border-color: rgba(var(--asset-rgb),.68); background: rgba(17,27,24,.96); box-shadow: 0 10px 28px #0009,0 0 0 4px rgba(var(--asset-rgb),.08); }
.asset-audio-play svg { width: 18px; fill: currentColor; }
.asset-audio-cover.is-active .asset-audio-play { opacity: 1; transform: scale(1); border-color: rgba(var(--asset-rgb),.62); color: rgb(var(--asset-rgb)); background: rgba(12,22,19,.94); box-shadow: 0 7px 20px #0009,0 0 16px rgba(var(--asset-rgb),.14),inset 0 1px rgba(var(--asset-rgb),.16); }
.asset-audio-cover.is-unavailable .asset-audio-play { opacity: 0 !important; pointer-events: none; }
.asset-audio-time { position: absolute; z-index: 2; right: 8px; bottom: 8px; padding: 2px 7px; border: 1px solid rgba(var(--asset-rgb),.12); border-radius: 5px; color: #929b98; background: rgba(7,10,9,.72); font: 600 10px/16px monospace; font-variant-numeric: tabular-nums; backdrop-filter: blur(6px); }
.asset-audio-cover.is-active .asset-audio-time { border-color: rgba(var(--asset-rgb),.24); color: rgba(var(--asset-rgb),.9); }
@keyframes audio-pulse { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.1); opacity: .8; } }
@media (prefers-reduced-motion: reduce) { .asset-audio-cover.is-playing .asset-audio-icon { animation: none; } }
@keyframes asset-wave-breathe { to { transform: scaleY(.62); } }
.project-workspace-head { position: relative; display: flex; min-height: 176px; align-items: center; justify-content: space-between; gap: 38px; overflow: hidden; padding: 30px clamp(26px,4vw,50px); border: 1px solid #333; border-radius: 22px; background: #191919; box-shadow: 0 22px 60px #00000024; }
.project-workspace-head::before { position: absolute; inset: 0; opacity: .32; background-image: radial-gradient(circle,#454545 1px,transparent 1px); background-size: 18px 18px; content: ''; mask-image: linear-gradient(90deg,transparent 22%,#000 54%,transparent 92%); }
.project-head-copy,.project-head-actions { position: relative; z-index: 3; }
.project-head-copy { min-width: 300px; }
.project-eyebrow { display: inline-flex; align-items: center; gap: 9px; color: #9a9a9a; font-size: 12px; font-weight: 850; letter-spacing: .12em; }
.project-eyebrow::before { width: 20px; height: 2px; border-radius: 2px; background: #45d7ff; content: ''; }
.project-title-row { display: flex; align-items: center; gap: 12px; margin-top: 11px; }
.project-title-row h1 { margin: 0; color: #f4f4f4; font-size: clamp(30px,3vw,40px); font-weight: 850; line-height: 1.1; letter-spacing: -.04em; }
.project-title-row b { padding: 4px 9px; border: 1px solid #3a3a3a; border-radius: 999px; color: #9b9b9b; background: #202020; font-size: 13px; white-space: nowrap; }
.project-head-copy p { margin: 13px 0 0; color: #8b8b8b; font-size: 13px; }
.project-head-actions { display: flex; align-items: center; gap: 10px; padding: 7px; border: 1px solid #393939; border-radius: 14px; background: #222222e6; box-shadow: 0 12px 30px #0003; backdrop-filter: blur(12px); }
.project-search { display: flex; width: clamp(190px,20vw,280px); height: 40px; align-items: center; gap: 10px; padding: 0 14px; border: 1px solid #3b3b3b; border-radius: 22px; background: #1a1a1a; }
.project-search:focus-within { border-color: #5c5c5c; }
.project-search svg { width: 17px; flex: 0 0 auto; fill: none; stroke: #787878; stroke-width: 1.7; }
.project-search input { min-width: 0; flex: 1; border: 0; outline: 0; color: #eee; background: transparent; font-size: 14px; }
.project-create-button { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 7px; padding: 0 16px; border: 1px solid #494949; border-radius: 10px; color: #fff; background: #252525; cursor: pointer; font-size: 13px; font-weight: 700; white-space: nowrap; transition: .16s; }
.project-create-button:hover,.project-create-button:focus-visible { border-color: #e8e8e8; outline: 0; background: #2b2b2b; box-shadow: 0 0 0 3px #ffffff12; }
.project-create-button svg { width: 16px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.project-head-art { position: absolute; z-index: 1; top: 24px; left: 51%; width: 250px; height: 130px; opacity: .46; transform: translateX(-50%); pointer-events: none; }
.project-head-art > svg { position: absolute; inset: 0; width: 100%; height: 100%; fill: none; stroke: #328ca3; stroke-width: 1.4; }
.hero-script,.hero-shot { position: absolute; z-index: 2; display: block; border: 1px solid #414141; border-radius: 8px; background: #202020e8; }
.hero-script { top: 31px; left: 25px; width: 66px; height: 72px; padding: 20px 11px 8px; border-color: #2e6674; }
.hero-script::before { position: absolute; top: 11px; left: 11px; width: 20px; height: 4px; border-radius: 3px; background: #45d7ff; content: ''; }
.hero-script i { display: block; width: 100%; height: 3px; margin-top: 7px; border-radius: 3px; background: #414141; }
.hero-script i:nth-child(2) { width: 78%; }.hero-script i:nth-child(3) { width: 55%; }
.hero-shot { right: 20px; width: 67px; height: 43px; }.hero-shot::before { position: absolute; inset: 6px; border-radius: 4px; background: #2d2d2d; content: ''; }.hero-shot-top { top: 10px; }.hero-shot-bottom { bottom: 9px; border-color: #643b50; }
.project-workspace-grid { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 18px; margin-top: 24px; }
.client-create-project,.client-project-card { min-width: 0; overflow: hidden; border: 1px solid #282828; border-radius: 16px; background: linear-gradient(150deg,#1e1e1e 0%,#161616 100%); box-shadow: 0 4px 16px #00000010; transition: border-color .25s ease,transform .25s cubic-bezier(.22,1,.36,1),box-shadow .25s ease; }
.client-project-card { cursor: pointer; outline: none; }.client-project-card:focus-visible { border-color:#e8e8e8; box-shadow:0 0 0 3px #ffffff12; }
.client-create-project:hover,.client-project-card:hover { border-color: #4b4b4b; transform: translateY(-4px); box-shadow: 0 16px 40px #00000040; }
.client-create-panel { display: flex; width: 100%; aspect-ratio: 16/9; align-items: center; justify-content: center; flex-direction: column; gap: 12px; border: 0; border-bottom: 1px solid #313131; color: #f1f1f1; background: radial-gradient(circle at 50% 45%,#222,#191919 70%); cursor: pointer; }
.client-create-panel strong { font-size: 15px; }.client-new-project-visual { position: relative; display: block; width: 132px; height: 65px; }
.client-new-script,.client-new-frame { position: absolute; display: block; border: 1px solid #444; background: #1d1d1d; box-shadow: 0 7px 15px #0005; transition: .18s; }
.client-new-script { top: 10px; left: 2px; width: 50px; height: 54px; padding: 16px 9px 7px; border-radius: 7px; transform: rotate(-4deg); }
.client-new-script::before { position: absolute; top: 8px; left: 9px; width: 14px; height: 3px; border-radius: 3px; background: #f2f2f2; content: ''; }
.client-new-script i { display: block; width: 100%; height: 3px; margin-top: 5px; border-radius: 3px; background: #444; }.client-new-script i:nth-child(2){width:80%}.client-new-script i:nth-child(3){width:58%}
.client-new-frame { top: 12px; right: 0; width: 66px; height: 45px; padding: 5px; border-radius: 7px; transform: rotate(3deg); }.client-new-frame i { display:block;width:100%;height:100%;border-radius:4px;background:linear-gradient(145deg,#2e3840 55%,#5a354b 56%); }.client-new-frame b{position:absolute;right:8px;top:8px;width:5px;height:5px;border-radius:50%;background:#ffd469}
.client-new-plus { position: absolute; z-index: 3; top: 18px; left: 49px; display: grid; width: 39px; height: 39px; place-items: center; border: 3px solid #191919; border-radius: 50%; color: #151515; background: #f2f2f2; box-shadow: 0 6px 16px #0006; transition: .18s; }.client-new-plus svg{width:21px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}.client-create-panel:hover .client-new-plus{transform:rotate(90deg) scale(1.05)}
.client-studio-bar { display: flex; height: 88px; align-items: center; justify-content: center; gap: 5px; color: #efefef; font-size: 14px; font-weight: 650; }.client-studio-bar svg{width:14px;fill:none;stroke:currentColor;stroke-width:1.4;stroke-linecap:round}
.client-project-cover { position: relative; aspect-ratio: 16/9; overflow: hidden; border-bottom: 1px solid #313131; background: #151515; }.client-project-cover>img{width:100%;height:100%;object-fit:cover;transition:.35s}.client-project-card:hover .client-project-cover>img{transform:scale(1.05)}
.client-generated-cover { --project-accent:#45d7ff;--project-secondary:#ff6db1;position:relative;width:100%;height:100%;overflow:hidden;background-color:#202323;background-image:radial-gradient(circle,#4a4a4a73 1px,transparent 1px);background-size:15px 15px }.client-generated-cover::after{position:absolute;inset:0;background:linear-gradient(118deg,#45d7ff12,transparent 44%,#ff6db114);content:''}.client-generated-cover-1{--project-accent:#ffd75a;--project-secondary:#45d7ff;background-color:#24241f}.client-generated-cover-2{--project-accent:#ff6db1;--project-secondary:#9d8cff;background-color:#252126}
.client-generated-script,.client-generated-frame{position:absolute;z-index:2;display:block;border:1px solid color-mix(in srgb,var(--project-accent) 40%,#444);border-radius:7px;background:#1b1b1bef;box-shadow:0 8px 18px #0006;transition:.22s}.client-generated-script{top:50%;left:11%;width:27%;min-width:52px;height:70px;padding:21px 10px 9px;transform:translateY(-50%) rotate(-2deg)}.client-generated-script::before{position:absolute;top:10px;left:10px;width:38%;height:4px;border-radius:4px;background:var(--project-accent);content:''}.client-generated-script i{display:block;width:100%;height:3px;margin-top:7px;border-radius:3px;background:#484848}.client-generated-script i:nth-child(2){width:82%}.client-generated-script i:nth-child(3){width:58%}
.client-generated-flow{position:absolute;z-index:1;inset:0;width:100%;height:100%;fill:none;stroke:color-mix(in srgb,var(--project-accent) 55%,#4b4b4b);stroke-width:1.4}.client-generated-frame{right:10%;width:31%;min-width:58px;height:42px;padding:5px}.client-generated-frame-top{top:14%}.client-generated-frame-bottom{bottom:14%;border-color:color-mix(in srgb,var(--project-secondary) 40%,#444)}.client-generated-frame i{display:block;width:100%;height:100%;border-radius:4px;background:linear-gradient(145deg,transparent 50%,color-mix(in srgb,var(--project-accent) 25%,#252525) 51%),#34454a}.client-generated-frame-bottom i{background:linear-gradient(35deg,transparent 47%,color-mix(in srgb,var(--project-secondary) 25%,#252525) 48%),#453541}.client-generated-frame b{position:absolute;top:9px;right:10px;width:6px;height:6px;border-radius:50%;background:color-mix(in srgb,var(--project-accent) 70%,#fff)}.client-generated-frame-bottom b{background:color-mix(in srgb,var(--project-secondary) 70%,#fff)}
.client-generated-play{position:absolute;z-index:4;top:50%;right:21%;display:grid;width:24px;height:24px;place-items:center;border:1px solid #ffffff26;border-radius:50%;color:#fff;background:#0d1015bd;transform:translate(50%,-50%);box-shadow:0 5px 14px #0006}.client-generated-play svg{width:13px;fill:currentColor}.client-project-card:hover .client-generated-script{transform:translate(-2px,-50%) rotate(-4deg)}.client-project-card:hover .client-generated-frame-top{transform:translate(2px,-2px)}.client-project-card:hover .client-generated-frame-bottom{transform:translate(2px,2px)}
.client-project-info { min-height: 92px; padding: 14px 16px 12px; background: transparent; }.client-project-name-row{display:flex;align-items:center;gap:6px}.client-project-name-row h2{min-width:0;flex:1;margin:0;overflow:hidden;color:#f1f1f1;font-size:16px;font-weight:700;line-height:22px;text-overflow:ellipsis;white-space:nowrap}.client-project-name-row button{display:grid;width:24px;height:24px;place-items:center;border:0;border-radius:6px;color:#666;background:transparent;cursor:pointer;opacity:0;transition:.15s}.client-project-card:hover .client-project-name-row button{opacity:1}.client-project-name-row button:hover{color:#ff7c97;background:#ff446018}.client-project-name-row svg{width:14px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}.client-project-info>p{margin:3px 0 0;overflow:hidden;color:#7a7a7a;font-size:12px;line-height:17px;text-overflow:ellipsis;white-space:nowrap}.client-project-info footer{display:flex;min-width:0;align-items:center;justify-content:space-between;gap:8px;margin-top:10px;padding-top:9px;border-top:1px solid #232323}.client-project-info time{color:#5a5a5a;font-size:11px;letter-spacing:.02em}.client-project-info footer span{max-width:120px;height:18px;padding:0 8px;overflow:hidden;border:1px solid #3a3a3a;border-radius:9px;color:#c2c2c2;background:#222;font-size:11px;font-weight:600;line-height:16px;text-overflow:ellipsis;white-space:nowrap}
.project-search-empty{display:grid;min-height:260px;grid-column:1/-1;place-content:center;justify-items:center;gap:8px;border:1px dashed #3f3f3f;border-radius:18px;color:#777}.project-search-empty svg{width:28px;fill:none;stroke:currentColor;stroke-width:1.5}.project-search-empty strong{color:#ddd;font-size:14px}.project-search-empty span{font-size:13px}.project-skeleton{min-height:260px;padding:14px;animation:client-project-pulse 1.3s ease-in-out infinite}.project-skeleton i,.project-skeleton b,.project-skeleton span{display:block;border-radius:7px;background:#292929}.project-skeleton i{height:145px}.project-skeleton b{width:72%;height:14px;margin-top:16px}.project-skeleton span{width:45%;height:9px;margin-top:10px}@keyframes client-project-pulse{50%{opacity:.55}}
.library-page-head { display: flex; align-items: end; justify-content: space-between; gap: 24px; padding-bottom: 22px; border-bottom: 1px solid #2a2a2a; }
.library-page-head > div > span,.library-modal header span,.delete-dialog > span { color: #2eddff; font: 800 12px/1 monospace; letter-spacing: .18em; }
.library-title-row { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.library-title-row h1 { margin: 0; font-size: 30px; letter-spacing: -.04em; }
.library-title-row b { padding: 3px 8px; border: 1px solid #3b3b3b; border-radius: 99px; color: #999; font-size: 12px; }
.library-page-head p { margin: 8px 0 0; color: #777; font-size: 14px; }
.library-primary { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 7px; padding: 0 14px; border: 1px solid #494949; border-radius: 10px; color: #fff; background: #252525; cursor: pointer; font-size: 13px; font-weight: 700; transition: .16s; }
.library-primary:hover,.library-primary:focus-visible { border-color: #e8e8e8; outline: 0; background: #2b2b2b; box-shadow: 0 0 0 3px #ffffff12; }
.library-primary:disabled { cursor: wait; opacity: .6; box-shadow: none; }
.library-primary svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.library-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 18px 0; }
.library-filters { display: flex; gap: 6px; }
.library-filters button { height: 31px; padding: 0 12px; border: 1px solid #323232; border-radius: 9px; color: #888; background: #191919; cursor: pointer; font-size: 12px; }
.library-filters button.active { border-color: #555; color: #fff; background: #2b2b2b; }
.library-search { display: flex; width: 230px; height: 35px; align-items: center; gap: 8px; padding: 0 11px; border: 1px solid #333; border-radius: 10px; background: #171717; }
.library-search:focus-within { border-color: #666; }
.library-search svg { width: 15px; fill: none; stroke: #777; stroke-width: 1.7; }
.library-search input { min-width: 0; flex: 1; border: 0; outline: 0; color: #eee; background: transparent; font-size: 12px; }
.library-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px; }
.library-grid-prompts { grid-template-columns: repeat(auto-fill,minmax(min(100%,280px),1fr)); align-items: stretch; }
.library-grid-assets { grid-template-columns: repeat(4,minmax(0,1fr)); }
.library-card { min-width: 0; overflow: hidden; border: 1px solid #2d2d2d; border-radius: 14px; background: #191919; transition: .18s; }
.library-grid-prompts .library-card { display: flex; min-height: 245px; flex-direction: column; }
.library-card:hover { border-color: #4b4b4b; background: #1d1d1d; transform: translateY(-2px); }
.library-cover { position: relative; height: 145px; overflow: hidden; border-bottom: 1px solid #2c2c2c; background: #101010; }
.library-cover img { width: 100%; height: 100%; object-fit: cover; }
.library-cover > span { position: absolute; right: 9px; bottom: 8px; padding: 3px 7px; border: 1px solid #ffffff1f; border-radius: 99px; color: #ddd; background: #080a10bb; font-size: 11px; }
.cover-placeholder { display: grid; width: 100%; height: 100%; place-items: center; color: #555; background: radial-gradient(circle at 50% 45%,#252537,#111 65%); }
.cover-placeholder svg { width: 38px; fill: none; stroke: currentColor; stroke-width: 1.35; stroke-linecap: round; stroke-linejoin: round; }
.library-card-body { display: flex; min-width: 0; flex: 1; flex-direction: column; padding: 13px; }
.library-card-body h2 { margin: 0; overflow: hidden; color: #eee; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.library-card-body > p { height: 32px; margin: 7px 0 10px; overflow: hidden; color: #777; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.library-card-body pre { height: 78px; margin: 0 0 11px; overflow: hidden; white-space: pre-wrap; overflow-wrap: anywhere; color: #aaa; font: 12px/1.55 inherit; }
.library-card-body footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-top: 9px; border-top: 1px solid #292929; }
.library-card-body footer time { color: #5f5f5f; font-size: 11px; }
.library-card-body footer div { display: flex; gap: 3px; }
.library-card-body footer button { padding: 3px 6px; border: 0; border-radius: 5px; color: #8d8d8d; background: transparent; cursor: pointer; font-size: 11px; }
.library-card-body footer button:hover { color: #fff; background: #303030; }
.prompt-accent { display: flex; align-items: center; gap: 7px; padding: 12px 13px 0; color: #888; font-size: 12px; }
.prompt-accent i { width: 6px; height: 6px; border-radius: 50%; background: #2eddff; box-shadow: 0 0 9px #2eddff; }
.prompt-accent b { margin-left: auto; padding: 3px 6px; border-radius: 5px; color: #ff9bcc; background: #ff3fa817; font-size: 11px; }
.prompt-skeleton-grid { pointer-events: none; }
.prompt-skeleton-card { border-color: #303030; animation: prompt-skeleton-pulse 1.5s ease-in-out infinite; }
.prompt-skeleton-accent { display: flex; align-items: center; gap: 8px; padding: 15px 13px 2px; }
.prompt-skeleton-accent i,.prompt-skeleton-accent span,.prompt-skeleton-body b,.prompt-skeleton-body > i,.prompt-skeleton-body pre,.prompt-skeleton-body footer span,.prompt-skeleton-body footer em { display: block; border-radius: 6px; background: linear-gradient(100deg,#242424 20%,#343434 48%,#242424 76%); background-size: 240% 100%; animation: prompt-skeleton-shimmer 1.45s linear infinite; }
.prompt-skeleton-accent i { width: 7px; height: 7px; border-radius: 50%; }
.prompt-skeleton-accent span { width: 42px; height: 9px; }
.prompt-skeleton-body { display: flex; flex: 1; flex-direction: column; padding: 13px; }
.prompt-skeleton-body b { width: 58%; height: 15px; margin-bottom: 12px; }
.prompt-skeleton-body > i { width: 88%; height: 8px; margin-bottom: 7px; }
.prompt-skeleton-body > i:nth-of-type(2) { width: 66%; }
.prompt-skeleton-body pre { flex: 1; min-height: 74px; margin: 10px 0 13px; }
.prompt-skeleton-body footer { display: flex; align-items: center; justify-content: space-between; padding-top: 11px; border-top: 1px solid #2d2d2d; }
.prompt-skeleton-body footer span { width: 66px; height: 8px; }
.prompt-skeleton-body footer em { width: 76px; height: 18px; }
@keyframes prompt-skeleton-shimmer { to { background-position: -240% 0; } }
@keyframes prompt-skeleton-pulse { 50% { opacity: .72; } }
.library-loading,.library-empty { display: grid; min-height: 340px; place-items: center; align-content: center; gap: 12px; color: #777; font-size: 13px; }
.library-empty svg { width: 62px; fill: none; stroke: #555; stroke-width: 1.5; }
.library-empty strong { color: #bbb; font-size: 13px; }
.library-error { margin: 12px 0; padding: 10px 12px; border: 1px solid #ff5b7d35; border-radius: 9px; color: #ff829d; background: #ff3f6812; font-size: 12px; }
.library-modal-backdrop { position: fixed; z-index: 90; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; place-items: center; padding: 24px; background: #05070cc9; backdrop-filter: blur(10px); }
.library-modal,.delete-dialog { width: min(520px,92vw); padding: 24px; border: 1px solid #343b4d; border-radius: 20px; background: #151925; box-shadow: 0 30px 90px #000b; }
.library-modal header { display: flex; align-items: start; justify-content: space-between; margin-bottom: 18px; }
.library-modal header h2,.delete-dialog h2 { margin: 7px 0 0; font-size: 19px; }
.library-modal header button { border: 0; color: #778198; background: none; cursor: pointer; font-size: 24px; }
.library-modal > label { display: grid; gap: 7px; margin-top: 12px; color: #aab2c2; font-size: 12px; font-weight: 700; }
.library-form-field { display: grid; gap: 7px; margin-top: 12px; color: #aab2c2; font-size: 12px; font-weight: 700; }
.project-ratio-select { --select-accent: #2eddff; --select-border: #30384b; --select-border-hover: #46516a; --select-border-focus: #2eddff73; --select-bg: #0e121d; --select-bg-hover: #111725; --select-bg-focus: #111725; --select-menu-border: #30384b; --select-menu-bg: #111725fa; --select-focus-ring: #2eddff0d; }
.library-modal input:not([type=checkbox]),.library-modal select,.library-modal textarea { width: 100%; padding: 11px 12px; border: 1px solid #30384b; border-radius: 10px; outline: 0; color: #eee; background: #0e121d; font-size: 13px; }
.library-modal textarea { min-height: 80px; resize: vertical; }
.library-modal .content-editor { min-height: 145px; }
.library-modal input:focus,.library-modal select:focus,.library-modal textarea:focus { border-color: #2eddff73; box-shadow: 0 0 0 3px #2eddff0d; }
.library-modal select { appearance: none; -webkit-appearance: none; padding-right: 36px; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23778198' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; cursor: pointer; transition: border-color .15s, background-color .15s; }
.library-modal select:hover { border-color: #46516a; background-color: #111725; }
.library-modal select option { padding: 8px 12px; background: #111725; color: #eee; }
.asset-project-field { margin: 14px 0 0; padding: 0; border: 0; }
.asset-project-field legend { margin-bottom: 9px; padding: 0; color: #aab2c2; font-size: 12px; font-weight: 700; }
.asset-project-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; max-height: 188px; padding: 2px; overflow-y: auto; }
.asset-project-options::-webkit-scrollbar { width: 6px; }
.asset-project-options::-webkit-scrollbar-thumb { background: #2c3447; border-radius: 99px; }
.asset-project-options::-webkit-scrollbar-thumb:hover { background: #3a445c; }
.asset-project-options label { display: flex; align-items: center; gap: 9px; min-width: 0; padding: 9px 11px; border: 1px solid #2c3447; border-radius: 9px; background: #0e121d; cursor: pointer; transition: border-color .15s, background-color .15s, box-shadow .15s; }
.asset-project-options label:hover { border-color: #46516a; background: #131a28; }
.asset-project-options label:has(input:checked) { border-color: #2eddff73; background: rgba(46, 221, 255, .08); box-shadow: inset 0 0 0 1px #2eddff26; }
.asset-project-options input[type=checkbox] { appearance: none; -webkit-appearance: none; flex: 0 0 auto; width: 16px; height: 16px; margin: 0; border: 1.5px solid #4a5468; border-radius: 4px; background: #0a0e18; cursor: pointer; position: relative; transition: background-color .15s, border-color .15s; }
.asset-project-options input[type=checkbox]:checked { background: #2eddff; border-color: #2eddff; }
.asset-project-options input[type=checkbox]:checked::after { content: ''; position: absolute; left: 4px; top: 1px; width: 4px; height: 8px; border: solid #0a0e18; border-width: 0 2px 2px 0; transform: rotate(45deg); }
.asset-project-options span { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #c8ced9; font-size: 13px; }
.asset-project-options label:has(input:checked) span { color: #e6f9ff; }
.library-check { display: flex !important; grid-template-columns: auto 1fr; align-items: center; justify-content: start; }
.library-check input { accent-color: #2eddff; }
.upload-help,.delete-dialog p { color: #7c879c; font-size: 13px; line-height: 1.7; }
.library-modal > footer,.delete-dialog footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.library-modal > footer > button:not(.library-primary),.delete-dialog footer button { min-height: 36px; padding: 0 13px; border: 1px solid #353c4d; border-radius: 9px; color: #aaa; background: #202635; cursor: pointer; font-size: 12px; }
.delete-dialog .danger { border-color: #ff5b7d44; color: #ff8ba3; background: #ff3f6814; }
/* Keep asset controls out of the metadata row. */
.asset-card-actions-client { top: 9px; right: 9px; bottom: auto; }
.asset-card-actions-client button { border-color: #ffffff38; background: #101216d9; box-shadow: 0 4px 12px #0008; backdrop-filter: blur(8px); }
.asset-project-count,.asset-type-pill { white-space: nowrap; }
.asset-project-count { border-color: #45d7ff32; color: #8d9fa3; background: #45d7ff0c; }
.asset-project-count svg { width: 12px; flex: 0 0 auto; fill: none; stroke: #45d7ff; stroke-width: 1.7; }
.asset-type-pill i { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: rgb(var(--asset-rgb)); box-shadow: 0 0 0 3px rgba(var(--asset-rgb),.1); }
.asset-zoom-hint { top: 9px; right: auto; bottom: auto; left: 9px; display: grid; width: 27px; height: 27px; place-items: center; box-sizing: border-box; padding: 0; border: 1px solid #ffffff32; background: #101216d9; box-shadow: 0 4px 12px #0008; backdrop-filter: blur(8px); }.asset-zoom-hint svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; }
.asset-preview-backdrop { position: fixed; z-index: 120; inset: 0; display: grid; place-items: center; padding: 40px; background: #030509df; backdrop-filter: blur(14px); }.asset-preview-dialog { display: flex; width: min(1120px,92vw); height: min(780px,88vh); overflow: hidden; flex-direction: column; border: 1px solid #3c4455; border-radius: 20px; background: #11151f; box-shadow: 0 35px 100px #000d; }.asset-preview-dialog>header { display: flex; min-height: 62px; align-items: center; justify-content: space-between; padding: 0 18px; border-bottom: 1px solid #2b3240; }.asset-preview-dialog>header div { display: grid; gap: 3px; }.asset-preview-dialog>header strong { font-size: 14px; }.asset-preview-dialog>header span { color: #778198; font-size: 12px; }.asset-preview-dialog>header button { border: 0; color: #8790a2; background: transparent; cursor: pointer; font-size: 26px; }.asset-preview-stage { display: grid; min-height: 0; flex: 1; place-items: center; padding: 18px; overflow: auto; background: radial-gradient(circle at center,#232936,#080a0f 75%); }.asset-preview-stage img { display: block; max-width: 100%; max-height: 100%; object-fit: contain; box-shadow: 0 12px 40px #0008; }.asset-preview-dialog>footer { display: flex; min-height: 64px; align-items: center; justify-content: space-between; gap: 20px; padding: 0 18px; border-top: 1px solid #2b3240; }.asset-preview-dialog>footer p { margin: 0; color: #98a1b2; font-size: 12px; }.asset-preview-dialog>footer div { display: flex; align-items: center; gap: 6px; }.asset-preview-dialog>footer div>span { color: #6f788a; font-size: 12px; }.asset-preview-dialog>footer b { padding: 5px 8px; border: 1px solid #354353; border-radius: 6px; color: #9fb2c0; background: #1a222d; font-size: 11px; }
.asset-preview-backdrop { padding: clamp(16px,4vw,48px); background: #040507e8; }.asset-preview-dialog { width: min(1260px,94vw); height: min(820px,90vh); border-color: #ffffff1c; border-radius: 24px; background: #0d0f14; box-shadow: 0 30px 110px #000d,0 0 0 1px #ffffff08 inset; }.asset-preview-dialog>header { min-height: 70px; padding: 0 22px; border-color: #ffffff0f; background: linear-gradient(110deg,#171a22,#0d0f14); }.asset-preview-dialog>header strong { color: #f1f3f7; font-size: 15px; letter-spacing: -.01em; }.asset-preview-dialog>header span { color: #7f899a; font-size: 12px; }.asset-preview-dialog>header button { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid #ffffff16; border-radius: 50%; color: #abb3c1; background: #ffffff08; font-size: 23px; line-height: 1; transition: .18s; }.asset-preview-dialog>header button:hover { color: #fff; background: #ffffff18; transform: rotate(90deg); }.asset-preview-stage { padding: clamp(14px,2vw,28px); background: radial-gradient(circle at 50% 46%,#252b37 0,#10131a 44%,#08090d 100%); }.asset-preview-stage img { border: 1px solid #ffffff14; border-radius: 12px; box-shadow: 0 22px 60px #000a; }.asset-preview-dialog>footer { min-height: 58px; padding: 0 22px; border-color: #ffffff0f; background: #101219; }.asset-preview-dialog>footer p { overflow: hidden; max-width: 60%; color: #8993a4; text-overflow: ellipsis; white-space: nowrap; }.asset-preview-dialog>footer b { border-color: #ffffff16; color: #aeb8c8; background: #ffffff08; }

/* Asset lightbox */
.asset-preview-backdrop { padding: clamp(18px,3vw,42px); background: rgba(4,5,8,.88); backdrop-filter: blur(20px) saturate(.8); animation: asset-preview-fade .18s ease-out; }
.asset-preview-dialog { position: relative; display: grid; width: min(1380px,96vw); height: min(900px,92vh); grid-template-rows: auto minmax(0,1fr) auto; overflow: hidden; border: 1px solid rgba(255,255,255,.13); border-radius: 22px; background: #0d0f13; box-shadow: 0 38px 120px rgba(0,0,0,.72),0 0 0 1px rgba(255,255,255,.035) inset; animation: asset-preview-rise .24s cubic-bezier(.2,.75,.25,1); }
.asset-preview-dialog::before { position: absolute; z-index: 3; top: 0; right: 12%; left: 12%; height: 1px; background: linear-gradient(90deg,transparent,#58ddff 42%,#ff75bc 62%,transparent); content: ''; opacity: .75; pointer-events: none; }
.asset-preview-dialog > header { display: flex; min-height: 82px; align-items: center; justify-content: space-between; padding: 0 24px 0 26px; border-bottom: 1px solid rgba(255,255,255,.08); background: linear-gradient(110deg,#171a20 0,#111319 62%,#17131a 100%); }
.asset-preview-heading { display: grid; gap: 4px; min-width: 0; }
.asset-preview-heading .asset-preview-eyebrow { display: flex; align-items: center; gap: 7px; color: #7c8795; font: 700 12px/1.2 ui-monospace,monospace; letter-spacing: .18em; }
.asset-preview-eyebrow i { width: 18px; height: 2px; border-radius: 2px; background: #58ddff; box-shadow: 0 0 10px #58ddff88; }
.asset-preview-heading > div { display: flex; min-width: 0; align-items: center; gap: 9px; }
.asset-preview-heading > div strong { overflow: hidden; color: #f5f7fa; font-size: 17px; font-weight: 750; letter-spacing: -.015em; text-overflow: ellipsis; white-space: nowrap; }
.asset-preview-heading > div b { flex: 0 0 auto; padding: 3px 7px; border: 1px solid #58ddff31; border-radius: 99px; color: #9aeaff; background: #58ddff0d; font-size: 12px; font-weight: 700; }
.asset-preview-heading small { color: #747e8d; font-size: 12px; }
.asset-preview-dialog > header .asset-preview-close { display: grid; width: 38px; height: 38px; flex: 0 0 auto; place-items: center; border: 1px solid rgba(255,255,255,.12); border-radius: 11px; color: #aeb6c2; background: rgba(255,255,255,.055); cursor: pointer; transition: border-color .18s,color .18s,background .18s,transform .18s; }
.asset-preview-dialog > header .asset-preview-close:hover { border-color: rgba(255,255,255,.24); color: #fff; background: rgba(255,255,255,.11); transform: none; }
.asset-preview-close svg { width: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.asset-preview-stage { position: relative; display: grid; min-height: 0; place-items: center; overflow: auto; padding: clamp(22px,3vw,42px); background-color: #090b0f; background-image: radial-gradient(circle at 50% 45%,rgba(54,67,82,.48),transparent 54%),linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px); background-size: auto,24px 24px,24px 24px; }
.asset-preview-stage::after { position: absolute; inset: 0; background: linear-gradient(180deg,rgba(0,0,0,.22),transparent 16%,transparent 82%,rgba(0,0,0,.24)); content: ''; pointer-events: none; }
.asset-preview-frame { position: relative; z-index: 1; display: grid; max-width: 100%; max-height: 100%; place-items: center; padding: 10px; }
.asset-preview-frame img { display: block; max-width: 100%; max-height: calc(92vh - 210px); border: 1px solid rgba(255,255,255,.12); border-radius: 8px; object-fit: contain; background: #111; box-shadow: 0 26px 72px rgba(0,0,0,.56); }
.frame-corner { position: absolute; z-index: 2; width: 18px; height: 18px; border-color: rgba(88,221,255,.75); pointer-events: none; }
.frame-corner-tl { top: 0; left: 0; border-top: 1px solid; border-left: 1px solid; }.frame-corner-tr { top: 0; right: 0; border-top: 1px solid; border-right: 1px solid; }.frame-corner-bl { bottom: 0; left: 0; border-bottom: 1px solid; border-left: 1px solid; }.frame-corner-br { right: 0; bottom: 0; border-right: 1px solid; border-bottom: 1px solid; }
.asset-preview-dialog > footer { display: flex; min-height: 70px; align-items: center; justify-content: space-between; gap: 28px; padding: 12px 26px; border-top: 1px solid rgba(255,255,255,.08); background: #11141a; }
.asset-preview-description { display: grid; min-width: 0; gap: 4px; }
.asset-preview-description > span,.asset-preview-projects > span { color: #707a88; font-size: 12px; font-weight: 750; letter-spacing: .08em; }
.asset-preview-dialog > footer .asset-preview-description p { overflow: hidden; max-width: min(620px,52vw); margin: 0; color: #bdc4ce; font-size: 14px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.asset-preview-projects { display: grid; flex: 0 0 auto; gap: 6px; justify-items: end; }
.asset-preview-projects > div { display: flex; max-width: 420px; gap: 6px; overflow-x: auto; }
.asset-preview-dialog > footer .asset-preview-projects b { flex: 0 0 auto; padding: 5px 9px; border: 1px solid rgba(255,255,255,.1); border-radius: 7px; color: #c3cad4; background: rgba(255,255,255,.055); font-size: 12px; font-weight: 650; }
@keyframes asset-preview-fade { from { opacity: 0; } }
@keyframes asset-preview-rise { from { opacity: 0; transform: translateY(12px) scale(.985); } }

/* Readability layer shared by projects, prompts and assets. */
.library-page { color: #e8e8e8; -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }
.project-eyebrow,.library-page-head > div > span { color: #71e8ff; font-size: 13px; }
.project-head-copy p,.library-page-head p,.asset-library-head p { color: #a6a6a6; font-size: 13px; line-height: 1.55; }
.project-title-row b,.library-title-row b,.asset-title-line b { color: #c0c0c0; font-size: 13px; }
.project-search input,.library-search input,.asset-search input { color: #f2f2f2; font-size: 14px; }
.project-search input::placeholder,.library-search input::placeholder,.asset-search input::placeholder { color: #929292; opacity: 1; }
.project-search input[type=search]::-webkit-search-cancel-button,.library-search input[type=search]::-webkit-search-cancel-button,.asset-search input[type=search]::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; width: 15px; height: 15px; margin-left: 6px; border-radius: 50%; background-color: #3a3a3a; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='8' viewBox='0 0 8 8'%3E%3Cpath d='M1.5 1.5l5 5M6.5 1.5l-5 5' stroke='%23eee' stroke-width='1.4' stroke-linecap='round'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: center; cursor: pointer; transition: background-color .15s, transform .12s; }
.project-search input[type=search]::-webkit-search-cancel-button:hover,.library-search input[type=search]::-webkit-search-cancel-button:hover,.asset-search input[type=search]::-webkit-search-cancel-button:hover { background-color: #5a5a5a; transform: scale(1.08); }
.library-filters button,.asset-filter-tabs button { color: #b5b5b5; font-size: 14px; }
.library-filters button.active,.asset-filter-tabs button.active { color: #fff; }
.client-project-name-row h2,.library-card-body h2,.asset-client-title h2 { color: #f5f5f5; font-size: 15px; }
.client-project-info > p { color: #7a7a7a; font-size: 12px; line-height: 17px; }
.client-project-info time { color: #5a5a5a; font-size: 11px; }
.client-project-info footer span { color: #9ad8e8; font-size: 11px; }
.prompt-accent { color: #b8b8b8; font-size: 13px; }
.prompt-accent b { color: #ffb0d4; font-size: 12px; }
.library-card-body > p { height: 38px; color: #aaa; font-size: 14px; line-height: 1.6; }
.library-card-body pre { height: 96px; color: #d0d0d0; font-size: 14px; line-height: 1.65; }
.library-card-body footer time { color: #909090; font-size: 12px; }
.library-card-body footer button { color: #b9b9b9; font-size: 12px; }
.asset-type-pill,.asset-project-count { color: #b8b8b8; font-size: 12px; }
.asset-client-info footer { color: #aaa; font-size: 13px; line-height: 1.45; }
.library-loading,.library-empty { color: #aaa; font-size: 14px; }
.library-empty strong { color: #ddd; font-size: 14px; }
.library-modal > label,.library-form-field { color: #c8ced9; font-size: 14px; }
.library-modal input:not([type=checkbox]),.library-modal select,.library-modal textarea { font-size: 14px; line-height: 1.5; }
@media (max-width:1450px) { .project-workspace-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } }
@media (max-width:1350px) { .asset-client-grid{grid-template-columns:repeat(3,minmax(0,1fr))} }
@media (max-width:1180px) { .project-head-art{display:none}.project-workspace-grid{grid-template-columns:repeat(3,minmax(0,1fr))} }
@media (max-width:900px) { .project-workspace-head{align-items:flex-start;flex-direction:column;gap:22px}.project-head-actions{width:100%}.project-search{width:auto;flex:1}.project-workspace-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.asset-library-toolbar{align-items:stretch;flex-direction:column}.asset-client-grid{grid-template-columns:repeat(2,minmax(0,1fr))} }
@media (max-width:1100px) { .library-grid:not(.library-grid-prompts),.library-grid-assets { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@container (max-width:540px) {
  .library-page-head { align-items: stretch; flex-direction: column; gap: 16px; }
  .library-page-head .library-primary { align-self: flex-start; }
  .library-toolbar { align-items: stretch; flex-direction: column; gap: 12px; }
  .library-filters { max-width: 100%; overflow-x: auto; padding-bottom: 2px; }
  .library-filters button { flex: 0 0 auto; }
  .library-search { width: auto; }
  .prompt-library-page { padding-right: 12px; padding-left: 12px; }
}
@media (max-width:700px) {
  .asset-preview-backdrop { padding: 10px; }
  .asset-preview-dialog { width: 100%; height: min(94vh,900px); border-radius: 16px; }
  .asset-preview-dialog > header { min-height: 72px; padding: 0 15px 0 17px; }
  .asset-preview-heading > div strong { max-width: 56vw; font-size: 15px; }
  .asset-preview-stage { padding: 16px; }
  .asset-preview-frame img { max-height: calc(94vh - 220px); }
  .asset-preview-dialog > footer { align-items: flex-start; flex-direction: column; gap: 10px; padding: 13px 17px; }
  .asset-preview-dialog > footer .asset-preview-description p { max-width: calc(100vw - 54px); }
  .asset-preview-projects { max-width: 100%; justify-items: start; }
}

/* ===== 新建项目：风格 + 比例选择（对齐 vue ProjectFormModal） ===== */
.library-style-field,
.library-ratio-field { margin: 14px 0 0; padding: 0; border: 0; }
.library-style-field > legend,
.library-ratio-field > legend { padding: 0; margin-bottom: 10px; color: #aab2c2; font-size: 12px; font-weight: 700; letter-spacing: .04em; }
.library-style-groups { display: grid; gap: 10px; }
.library-style-group { display: grid; grid-template-columns: 72px 1fr; align-items: center; gap: 12px; }
.library-style-group-title { color: #aab2c2; font-size: 12px; font-weight: 700; }
.library-style-group-options { display: flex; flex-wrap: wrap; gap: 8px; }
.library-style-group-options label { cursor: pointer; }
.library-style-group-options input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.library-style-group-options span { display: inline-flex; height: 32px; padding: 0 12px; align-items: center; border: 1px solid #30384b; border-radius: 8px; color: #aab2c2; background: #0e121d; font-size: 13px; transition: color 160ms ease, border-color 160ms ease, background-color 160ms ease; }
.library-style-group-options input:checked + span { color: var(--theme-accent); border-color: var(--theme-accent); background: var(--theme-accent-soft); }
.library-style-group-options label:hover span { color: #f2f2f2; border-color: #4a5468; }
.library-style-desc { margin: 10px 0 0; padding: 9px 12px; border-left: 2px solid var(--theme-accent); border-radius: 0 6px 6px 0; color: #aab2c2; background: #0e121d; font-size: 12px; line-height: 1.6; }

.library-ratio-options { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.library-ratio-options label { cursor: pointer; }
.library-ratio-options input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.library-ratio-card { display: flex; height: 78px; flex-direction: column; align-items: center; justify-content: center; gap: 8px; border: 1px solid #30384b; border-radius: 10px; color: #aab2c2; background: #0e121d; transition: color 160ms ease, border-color 160ms ease, background-color 160ms ease; }
.library-ratio-options input:checked + .library-ratio-card { color: var(--theme-accent); border-color: var(--theme-accent); background: var(--theme-accent-soft); }
.library-ratio-options label:hover .library-ratio-card { color: #f2f2f2; border-color: #4a5468; }
.library-ratio-shape { display: block; background: currentColor; opacity: .7; border-radius: 3px; transition: opacity 160ms ease; }
.library-ratio-options input:checked + .library-ratio-card .library-ratio-shape { opacity: 1; }
.library-ratio-landscape { width: 32px; height: 18px; }
.library-ratio-ultrawide { width: 36px; height: 15px; }
.library-ratio-classic { width: 28px; height: 21px; }
.library-ratio-square { width: 24px; height: 24px; }
.library-ratio-portrait3 { width: 21px; height: 28px; }
.library-ratio-portrait9 { width: 18px; height: 32px; }
.library-ratio-label { font-style: normal; font-size: 12px; font-weight: 600; }

@media (max-width: 560px) {
  .library-style-group { grid-template-columns: 1fr; gap: 6px; }
  .library-ratio-options { grid-template-columns: repeat(3, 1fr); }
}

/* ===== Prompts v2: scope switcher / colored dots / cards / viewer / cover upload ===== */
.library-head-actions { display: flex; align-items: center; gap: 10px; }
.prompt-scope-switch { display: flex; gap: 2px; padding: 3px; border: 1px solid #383838; border-radius: 9px; background: #1b1b1b; }
.prompt-scope-switch button { height: 27px; padding: 0 10px; border: 0; border-radius: 6px; color: #888; background: transparent; font-size: 11px; cursor: pointer; transition: .15s; }
.prompt-scope-switch button.active { color: #f0f0f0; background: #2a2a2a; box-shadow: inset 0 0 0 1px #444; }
.filter-dot { width: 6px; height: 6px; border-radius: 2px; display: inline-block; vertical-align: middle; margin-right: 5px; }
.filter-dot-role { background: #f47aaf; }
.filter-dot-scene { background: #4fd4c6; }
.filter-dot-storyboard { background: #9b8af5; }
.library-filters button .filter-dot { margin-right: 5px; }

/* Prompt card v2 — overrides the shared .library-card styling inside prompts grid */
.prompt-card-v2 { --prompt-rgb: 155,138,245; display: flex; flex-direction: column; min-height: 254px; padding: 0; overflow: hidden; border: 1px solid #2a2a2a; border-radius: 12px; background: #1b1b1b; transition: .2s; }
.prompt-card-v2[data-category='role'] { --prompt-rgb: 244,122,175; }
.prompt-card-v2[data-category='scene'] { --prompt-rgb: 79,212,198; }
.prompt-card-v2[data-category='storyboard'] { --prompt-rgb: 155,138,245; }
.prompt-card-v2:hover { border-color: rgba(var(--prompt-rgb),.4); box-shadow: 0 10px 28px #0004; transform: translateY(-2px); }
.prompt-card-v2.is-viewable { cursor: pointer; }
.prompt-card-cover { position: relative; display: block; width: 100%; height: 118px; padding: 0; border: 0; border-bottom: 1px solid #2a2a2a; background: #141414; cursor: pointer; overflow: hidden; }
.prompt-card-cover img { width: 100%; height: 100%; object-fit: cover; transition: .3s; }
.prompt-card-v2:hover .prompt-card-cover img { transform: scale(1.035); }
.prompt-card-cover-zoom { position: absolute; top: 10px; left: 10px; display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid rgba(255,255,255,.3); border-radius: 7px; color: #fff; background: rgba(0,0,0,.5); opacity: 0; transition: .18s; backdrop-filter: blur(6px); }
.prompt-card-cover:hover .prompt-card-cover-zoom { opacity: 1; }
.prompt-card-cover-zoom svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; }
.prompt-card-text { display: -webkit-box; min-height: 82px; padding: 12px 13px; overflow: hidden; border-bottom: 1px solid #2a2a2a; color: #a8a8a8; background: #181818; font-size: 11px; line-height: 20px; white-space: pre-wrap; -webkit-box-orient: vertical; -webkit-line-clamp: 4; }
.prompt-card-v2:not(:has(.prompt-card-cover)) .prompt-card-text { flex: 1; -webkit-line-clamp: 10; }
.prompt-card-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 13px; }
.prompt-card-footer-info { display: flex; min-width: 0; flex: 1; align-items: center; gap: 7px; overflow: hidden; white-space: nowrap; }
.prompt-card-category { display: inline-flex; align-items: center; gap: 5px; color: #888; font-size: 10px; font-weight: 700; flex: 0 0 auto; }
.prompt-card-footer-name { display: flex; min-width: 0; align-items: center; gap: 4px; }
.prompt-card-footer-name strong { overflow: hidden; color: #e8e8e8; font-size: 11px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.prompt-card-shared-icon { width: 11px; height: 11px; flex: 0 0 auto; fill: none; stroke: #888; stroke-width: 1.45; }
.prompt-card-footer-desc { overflow: hidden; color: #666; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; flex: 1 1 auto; min-width: 0; }
.prompt-card-footer-info > * + * { position: relative; padding-left: 8px; }
.prompt-card-footer-info > * + *::before { position: absolute; top: 50%; left: 0; width: 2px; height: 2px; border-radius: 50%; background: #555; content: ''; transform: translateY(-50%); }
.prompt-inline-actions { display: flex; align-items: center; gap: 2px; flex: 0 0 auto; }
.prompt-inline-actions button { display: grid; width: 26px; height: 26px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 6px; color: #888; background: transparent; cursor: pointer; transition: .15s; }
.prompt-inline-actions button:hover { color: #f0f0f0; background: #2a2a2a; border-color: #333; }
.prompt-inline-actions button.copied { color: #4fd4c6; background: rgba(79,212,198,.08); }
.prompt-inline-actions button.danger:hover { color: #fb7185; background: rgba(251,113,133,.08); }
.prompt-inline-actions svg { width: 13px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.prompt-card-open-hint { display: inline-flex; align-items: center; gap: 3px; padding-left: 4px; color: rgba(var(--prompt-rgb),.7); font-size: 9px; font-weight: 650; }
.prompt-card-open-hint svg { width: 11px; fill: none; stroke: currentColor; stroke-width: 1.6; }

/* Viewer modal */
.prompt-viewer-modal { max-width: 680px; }
.prompt-viewer { display: grid; gap: 13px; }
.prompt-viewer-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.prompt-viewer-meta > span { display: inline-flex; align-items: center; gap: 6px; color: #888; font-size: 11px; }
.prompt-viewer-public { height: 26px; padding: 0 9px; border: 1px solid #2a2a2a; border-radius: 999px; background: #1e1e1e; }
.prompt-viewer-public svg { width: 12px; fill: none; stroke: currentColor; stroke-width: 1.5; }
.prompt-viewer-cover { display: block; width: 100%; max-height: 260px; object-fit: cover; border: 1px solid #2a2a2a; border-radius: 10px; }
.prompt-viewer-description { margin: 0; padding: 10px 12px; border-left: 2px solid #333; border-radius: 0 8px 8px 0; color: #aaa; background: #1a1a1a; font-size: 12px; line-height: 19px; }
.prompt-viewer-content { min-height: 160px; max-height: 45vh; padding: 14px 16px; overflow-y: auto; border: 1px solid #2a2a2a; border-radius: 10px; color: #ddd; background: #161616; font-size: 13px; line-height: 22px; white-space: pre-wrap; overflow-wrap: anywhere; }

/* Cover upload */
.prompt-cover-upload { position: relative; display: flex; min-height: 90px; align-items: center; justify-content: center; gap: 10px; padding: 14px; overflow: hidden; border: 1px dashed #3a3a3a; border-radius: 10px; color: #888; background: #181818; cursor: pointer; transition: .18s; }
.prompt-cover-upload:hover { border-color: #2eddff; background: #1e1e1e; }
.prompt-cover-upload.is-uploading { cursor: wait; opacity: .7; }
.prompt-cover-upload.has-cover { min-height: 120px; padding: 0; border-style: solid; }
.prompt-cover-upload > img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.prompt-cover-icon { width: 26px; height: 26px; flex: 0 0 auto; fill: none; stroke: #2eddff; stroke-width: 1.6; }
.prompt-cover-upload strong { color: #ccc; font-size: 12px; }
.prompt-cover-overlay { position: absolute; z-index: 1; right: 0; bottom: 0; left: 0; padding: 16px 12px 10px; background: linear-gradient(transparent, rgba(0,0,0,.76)); }
.prompt-cover-overlay strong { color: #fff; }
.prompt-cover-remove { position: absolute; z-index: 2; top: 8px; right: 8px; display: grid; width: 26px; height: 26px; place-items: center; padding: 0; border: 1px solid rgba(255,255,255,.22); border-radius: 50%; color: #fff; background: rgba(0,0,0,.58); cursor: pointer; }
.prompt-cover-remove:hover { background: rgba(0,0,0,.78); }
.prompt-cover-remove svg { width: 13px; fill: none; stroke: currentColor; stroke-width: 1.8; }
</style>
