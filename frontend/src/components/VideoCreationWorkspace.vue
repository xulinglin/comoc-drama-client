<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import StoryboardMentionEditor from './StoryboardMentionEditor.vue'
import BaseLoadingState from './BaseLoadingState.vue'
import BaseMediaPreview from './BaseMediaPreview.vue'
import FinishedVideoTrackPreview from './FinishedVideoTrackPreview.vue'
import { watchForDecodedVideoFrame } from '../utils/videoCompatibility.js'

const props = defineProps({
  token: { type: String, required: true },
  apiBase: { type: String, default: 'http://127.0.0.1:8080' },
  storageBase: { type: String, default: 'http://127.0.0.1:18081' },
  selectedAccountId: { type: String, default: '' },
  videoModel: { type: String, default: 'Seedance 2.0 Fast' },
})

const categories = [
  { key: 'all', label: '全部' },
  { key: 'role', label: '人物' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
  { key: 'layout', label: '白模' },
  { key: 'audio', label: '音频' },
]
const generationModes = [
  { value: 'reference', label: '参考生成' },
  { value: 'firstLast', label: '首尾帧' },
]
const videoRatios = ['21:9', '16:9', '4:3', '1:1', '3:4', '9:16', '智能']
const videoQualities = ['480P', '720P', '1080P', '4K']
const videoDurations = Array.from({ length: 15 }, (_, index) => index + 1)
const defaultVideoSettings = Object.freeze({ ratio: '16:9', quality: '720P', duration: 10 })
const generationCounts = [1, 2, 3, 4, 5, 6, 7, 8]
const DEFAULT_AUDIO_PROMPT = '你好，很高兴认识你，今天过得怎么样？'
const DEFAULT_ROLE_IMAGE_PROMPT = '16:9 横版角色设定图构图。画面左侧为超大高清半身面部特写，突出人物脸部、发型、发饰与上半身服装细节；画面中部为角色全身三视图，从左到右依次展示正面、侧面、背面，三视图严格对齐，比例一致，人物保持完全统一；'
const assets = ref([])
const imageModels = ref([])
const videoApiModels = ref([])
const selectedImageModel = ref('')
const defaultSeedanceModel = ref('')
const importedFileName = ref('')
const importedProjectTitle = ref('')
const importedSchemaVersion = ref('')
const importError = ref('')
const importDialogOpen = ref(false)
const jsonText = ref('')
const assetDetailOpen = ref(false)
const assetDetailTarget = ref(null)
const assetDraft = ref({ name: '', description: '', prompt: '', useDefaultRoleLayout: true })
const assetReferencesCopying = ref(false)
const assetReferencesCopied = ref(false)
const audioPreview = ref(null)
const audioPreviewPlaying = ref(false)
const audioPreviewCurrent = ref(0)
const audioPreviewDuration = ref(0)
const videoProjects = ref([])
const videoProjectKeyword = ref('')
const availableProjects = ref([])
const activeVideoProject = ref(null)
const videoProjectCreateOpen = ref(false)
const newProjectName = ref('')
const newProjectDescription = ref('')
const newProjectId = ref('')
const projectListLoading = ref(false)
const projectCreating = ref(false)
const projectToDelete = ref(null)
const deletingProjectId = ref('')
const projectDetailLoading = ref(false)
const projectSaveStatus = ref('')
const projectError = ref('')
const activeCategory = ref('all')
const loading = ref(false)
const error = ref('')
const assetActionsOpen = ref(false)
const assetActionsPinned = ref(false)
const bulkGenerating = ref(false)
const bulkGenerationStatus = ref('')
// 媒体放大预览（BaseMediaPreview，支持图片+视频）
const mediaPreviewVisible = ref(false)
const mediaPreviewSrc = ref('')
const mediaPreviewType = ref('image')
const mediaPreviewFileId = ref('')
const mediaPreviewReferences = ref([])
const finishedPreviewVisible = ref(false)
const finishedPreviewProjectTitle = ref('')
const finishedPreviewVideos = ref([])
const finishedPreviewLoading = ref(false)
const finishedPreviewError = ref('')
const compatibleVideoRequests = new Map()
const compatibleVideoInFlight = new Set()
const videoFrameWatchers = new WeakMap()

async function compatibleVideoUrl(fileId, fallbackUrl) {
  const id = String(fileId || '').trim()
  if (!id || !window.pywebview?.api?.compatible_video_preview) return fallbackUrl
  if (!compatibleVideoRequests.has(id)) {
    compatibleVideoRequests.set(id, window.pywebview.api.compatible_video_preview(props.token, id)
      .then(result => String(result?.url || fallbackUrl))
      .catch(() => fallbackUrl))
  }
  return compatibleVideoRequests.get(id)
}

async function handleShotVideoError(shot) {
  const fileId = String(shot?.resultFileId || '').trim()
  const attemptKey = `shot:${shot.id}:${fileId}`
  if (!fileId || compatibleVideoInFlight.has(attemptKey)) return
  compatibleVideoInFlight.add(attemptKey)
  try {
    const fallback = shot.resultUrl
    const compatible = await compatibleVideoUrl(fileId, fallback)
    if (compatible && compatible !== fallback) shot.resultUrl = compatible
  } finally {
    compatibleVideoInFlight.delete(attemptKey)
  }
}

function verifyShotVideoFrame(shot, event) {
  const video = event.currentTarget
  videoFrameWatchers.get(video)?.()
  videoFrameWatchers.set(video, watchForDecodedVideoFrame(video, () => handleShotVideoError(shot)))
}

function ensureShotVideoRenderable(shot, event) {
  const video = event.currentTarget
  window.setTimeout(() => {
    if (!video.isConnected || video.currentSrc !== shot.resultUrl) return
    if (video.videoWidth <= 0 || video.videoHeight <= 0) handleShotVideoError(shot)
  }, 250)
}

async function handleMediaPreviewVideoError() {
  const fileId = mediaPreviewFileId.value
  const attemptKey = `preview:${fileId}`
  if (!fileId || compatibleVideoInFlight.has(attemptKey)) return
  compatibleVideoInFlight.add(attemptKey)
  try {
    mediaPreviewSrc.value = await compatibleVideoUrl(fileId, mediaPreviewSrc.value)
  } finally {
    compatibleVideoInFlight.delete(attemptKey)
  }
}

async function handleFinishedVideoError(item) {
  const fileId = String(item?.fileId || '').trim()
  const attemptKey = `finished:${fileId}`
  if (!fileId || compatibleVideoInFlight.has(attemptKey)) return
  compatibleVideoInFlight.add(attemptKey)
  try {
    const compatible = await compatibleVideoUrl(fileId, item.src)
    if (!compatible || compatible === item.src) return
    finishedPreviewVideos.value = finishedPreviewVideos.value.map(video => video.id === item.id ? { ...video, src: compatible } : video)
  } finally {
    compatibleVideoInFlight.delete(attemptKey)
  }
}

function openVideoPreview(shot) {
  if (!shot.resultUrl) return
  mediaPreviewSrc.value = shot.resultUrl
  mediaPreviewType.value = 'video'
  mediaPreviewFileId.value = String(shot.resultFileId || '')
  mediaPreviewVisible.value = true
}

async function downloadShotVideo(shot) {
  if (shot.downloadingVideo || (!shot.resultFileId && !shot.resultPath && !shot.resultUrl)) return
  shot.downloadingVideo = true
  shot.videoReplaceError = ''
  try {
    const suggestedName = `${String(shot.title || '视频').trim() || '视频'}.mp4`
    if (shot.resultFileId && window.pywebview?.api?.save_server_video_as) {
      await window.pywebview.api.save_server_video_as(props.token, String(shot.resultFileId), suggestedName)
      return
    }
    if (shot.resultPath && window.pywebview?.api?.save_video_as) {
      await window.pywebview.api.save_video_as(shot.resultPath, suggestedName)
      return
    }
    if (!shot.resultUrl) throw new Error('当前视频没有可下载地址')
    const response = await fetch(shot.resultUrl)
    if (!response.ok) throw new Error(`服务器返回 HTTP ${response.status}`)
    const blob = await response.blob()
    if (!blob.size) throw new Error('服务器返回了空视频文件')
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = suggestedName
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000)
  } catch (err) {
    shot.videoReplaceError = `视频下载失败：${cleanError(err)}`
  } finally {
    shot.downloadingVideo = false
  }
}

function fileDownloadUrl(fileId) {
  const id = String(fileId || '').trim()
  if (!id) return ''
  const base = id.startsWith('local_') ? props.storageBase : props.apiBase
  return `${base}/file/${encodeURIComponent(id)}/download`
}

function storedProjectMediaUrl(item, ...keys) {
  const fileId = String(item?.fileId || item?.coverId || item?.resultFileId || '').trim()
  if (fileId) return fileDownloadUrl(fileId)
  const raw = keys.map(key => item?.[key]).find(value => String(value || '').trim())
  return raw ? absoluteMediaUrl(String(raw)) : ''
}

async function openProjectFinishedPreview(project) {
  if (!project?.id) return
  finishedPreviewVisible.value = true
  finishedPreviewProjectTitle.value = project.name || '未命名任务'
  finishedPreviewVideos.value = []
  finishedPreviewError.value = ''
  finishedPreviewLoading.value = true
  try {
    const detail = await videoProjectRequest('GET', `/video-project/${encodeURIComponent(project.id)}`)
    finishedPreviewProjectTitle.value = detail?.name || project.name || '未命名任务'
    finishedPreviewVideos.value = (Array.isArray(detail?.storyboards) ? detail.storyboards : []).flatMap((shot, index) => {
      const src = storedProjectMediaUrl(shot, 'resultUrl')
      if (!src) return []
      return [{
        id: String(shot.id || `video-${index}`),
        title: String(shot.title || `成片 ${index + 1}`),
        src,
        fileId: String(shot.resultFileId || shot.fileId || ''),
        duration: Number(shot.videoDuration || (shot.durationMode === 'seconds' ? shot.duration : 0) || 0),
      }]
    })
  } catch (err) {
    finishedPreviewError.value = cleanError(err)
  } finally {
    finishedPreviewLoading.value = false
  }
}

function openReferencePreview(asset, ownerAsset = asset) {
  const url = assetUrl(asset)
  if (!url) return
  mediaPreviewSrc.value = url
  mediaPreviewType.value = 'image'
  const state = assetReferenceState(ownerAsset)
  mediaPreviewReferences.value = [ownerAsset, ...state.readyItems]
    .filter(item => item && assetUrl(item))
    .map((item, index) => ({ id: item.id, name: item.name || item.id || '参考图', label: index === 0 ? '主图' : `图${index}`, src: assetUrl(item) }))
  mediaPreviewVisible.value = true
}

// ===== 精简视频控件 =====
const videoRefs = new Map()
function setVideoRef(shot, el) {
  if (el) videoRefs.set(shot.id, el)
  else videoRefs.delete(shot.id)
}
function getVideo(shot) { return videoRefs.get(shot.id) }

function toggleVideo(shot) {
  const v = getVideo(shot)
  if (!v) return
  if (v.paused) v.play().catch(() => {})
  else v.pause()
}
function seekVideo(shot, event) {
  const v = getVideo(shot)
  if (!v || !v.duration) return
  v.currentTime = Number(event.target.value) || 0
}
function toggleMute(shot) {
  const v = getVideo(shot)
  if (!v) return
  v.muted = !v.muted
}
function syncVideoMeta(shot, event) {
  shot.videoDuration = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0
}
function syncVideoTime(shot, event) {
  shot.videoCurrent = Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0
}
function fmtTime(value) {
  const s = Math.max(0, Math.floor(Number(value) || 0))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
const assetLibrarySyncing = ref(false)
const assetLibraryStatus = ref('')
const storyboards = ref([createStoryboard(1)])
const activeShotId = ref(storyboards.value[0].id)
const visibleStoryboardAnchorId = ref(storyboards.value[0].id)
const storyboardColumnRef = ref(null)
const storyboardCardRefs = new Map()
let storyboardAnchorFrame = 0
const pollTimers = new Map()
// 后端任务表快照，用于悬浮窗展示（名称/ID/状态/进度）
const activeTasks = ref([])
let taskRefreshTimer = null
let projectSaveTimer = null
let hydratingProject = false

function setStoryboardCardRef(element, shotId) {
  if (element) storyboardCardRefs.set(shotId, element)
  else storyboardCardRefs.delete(shotId)
}

function updateVisibleStoryboardAnchor() {
  storyboardAnchorFrame = 0
  const container = storyboardColumnRef.value
  if (!container || !storyboards.value.length) return
  const viewport = container.getBoundingClientRect()
  const viewportTop = viewport.top + 52
  let bestId = storyboards.value[0].id
  let bestVisibleHeight = -1
  let nearestDistance = Number.POSITIVE_INFINITY
  storyboards.value.forEach((shot) => {
    const card = storyboardCardRefs.get(shot.id)
    if (!card) return
    const rect = card.getBoundingClientRect()
    const visibleHeight = Math.max(0, Math.min(viewport.bottom, rect.bottom) - Math.max(viewportTop, rect.top))
    const distance = Math.abs((rect.top + rect.bottom) / 2 - (viewportTop + viewport.bottom) / 2)
    if (visibleHeight > bestVisibleHeight || (visibleHeight === bestVisibleHeight && distance < nearestDistance)) {
      bestId = shot.id
      bestVisibleHeight = visibleHeight
      nearestDistance = distance
    }
  })
  visibleStoryboardAnchorId.value = bestId
}

function scheduleVisibleStoryboardAnchorUpdate() {
  if (storyboardAnchorFrame) return
  storyboardAnchorFrame = window.requestAnimationFrame(updateVisibleStoryboardAnchor)
}

function jumpToStoryboardAnchor(shot) {
  const container = storyboardColumnRef.value
  const card = storyboardCardRefs.get(shot.id)
  if (!container || !card) return
  activeShotId.value = shot.id
  visibleStoryboardAnchorId.value = shot.id
  const viewport = container.getBoundingClientRect()
  const rect = card.getBoundingClientRect()
  container.scrollTo({
    top: Math.max(0, container.scrollTop + rect.top - viewport.top - 66),
    behavior: 'smooth',
  })
}

const displayedAssets = computed(() => assets.value.filter(asset => {
  return activeCategory.value === 'all' || asset.category === activeCategory.value
}))

// 悬浮窗已上移到全局（App.vue），这里只保留任务状态判断等业务逻辑。
const projectSaveLabel = computed(() => {
  const status = projectSaveStatus.value
  if (status.startsWith('正在')) return '保存中…'
  if (status.startsWith('保存失败')) return '保存失败'
  if (status.includes('待保存')) return '待保存'
  return '已保存'
})

const projectSaveTone = computed(() => {
  const status = projectSaveStatus.value
  if (status.startsWith('正在')) return 'saving'
  if (status.startsWith('保存失败')) return 'error'
  if (status.includes('待保存')) return 'pending'
  return 'saved'
})
const canonicalAssetsById = computed(() => {
  const map = new Map()
  assets.value.forEach((asset) => {
    const id = String(asset?.id || '')
    if (!id) return
    map.set(id, asset)
    map.set(id.toLowerCase(), asset)
  })
  return map
})
const imageModelOptions = computed(() => imageModels.value.map(model => ({
  label: model.name || model.modelName || '图片模型',
  value: String(model.id ?? model.modelName ?? ''),
})))
const seedanceModelOptions = computed(() => videoApiModels.value
  .filter(model => String(model.provider || '').toLowerCase() === 'seedance')
  .map(model => ({
    label: model.name || model.modelName || 'Seedance',
    value: String(model.id ?? model.modelName ?? ''),
  })))
const generationEngineOptions = [
  { label: 'OriginalDoubao', value: 'doubao' },
  { label: 'Seedance', value: 'seedance' },
]
const importedSummary = computed(() => {
  if (!importedFileName.value) return '支持最终 JSON 2.0：资产、提示词和分镜一次导入'
  const project = importedProjectTitle.value || importedFileName.value
  const version = importedSchemaVersion.value ? ` · v${importedSchemaVersion.value}` : ''
  return `${project}${version} · ${assets.value.length} 项资产 · ${storyboards.value.length} 个分镜`
})
const assetRawDetails = computed(() => {
  if (!assetDetailTarget.value) return ''
  const hidden = new Set(['cover', 'content', 'image', 'imageUrl', 'image_url', 'url', 'audioUrl', 'audio_url', 'generating', 'generationError'])
  return JSON.stringify(Object.fromEntries(Object.entries(assetDetailTarget.value).filter(([key]) => !hidden.has(key))), null, 2)
})

function createStoryboard(index) {
  return {
    id: `shot-${Date.now()}-${index}`,
    title: `分镜 ${String(index).padStart(2, '0')}`,
    prompt: '',
    references: [],
    referenceLabels: {},
    mode: 'reference',
    generationEngine: 'doubao',
    seedanceModel: defaultSeedanceModel.value,
    seedanceTaskId: '',
    seedanceTaskCreatedAt: 0,
    ratio: defaultVideoSettings.ratio,
    quality: defaultVideoSettings.quality,
    duration: defaultVideoSettings.duration,
    durationMode: 'seconds',
    sound: true,
    count: 1,
    modeOpen: false,
    settingsOpen: false,
    expanded: false,
    sendPreview: false,
    playerExpanded: false,
    videoPlaying: false,
    videoCurrent: 0,
    videoDuration: 0,
    videoMuted: false,
    referencesExpanded: false,
    taskId: '',
    status: '',
    statusText: '',
    progress: 0,
    conversationId: '',
    conversationUrl: '',
    generationSubmittedAt: 0,
    resultUrl: '',
    resultPath: '',
    resultWatermarked: false,
    downloadingVideo: false,
    replacingVideo: false,
    videoReplaceError: '',
    generationError: '',
  }
}

function cleanError(err) {
  return String(err).replace(/^Error:\s*/, '')
}

async function videoProjectRequest(method, path, body = null) {
  if (!window.pywebview?.api) throw new Error('请从桌面客户端打开视频生成工作台')
  return window.pywebview.api.backend_request(method, path, props.token, body)
}

async function loadVideoProjects() {
  projectListLoading.value = true
  projectError.value = ''
  try {
    const result = await videoProjectRequest('GET', '/video-project/list')
    videoProjects.value = Array.isArray(result) ? result : []
    await refreshTasks('')
  } catch (err) {
    projectError.value = cleanError(err)
  } finally {
    projectListLoading.value = false
  }
}

// 卡片上的“生成中 N”以实时任务表为准：按 projectId 统计未结束任务。
const videoProjectCards = computed(() => {
  const liveCounts = new Map()
  activeTasks.value.forEach(task => {
    if (!isActiveTask(task)) return
    const projectId = String(task.projectId || '')
    if (!projectId) return
    liveCounts.set(projectId, (liveCounts.get(projectId) || 0) + 1)
  })
  return videoProjects.value.map(project => ({
    ...project,
    runningCount: liveCounts.get(String(project.id || '')) || 0,
  }))
})

const filteredVideoProjectCards = computed(() => {
  const keyword = videoProjectKeyword.value.trim().toLowerCase()
  if (!keyword) return videoProjectCards.value
  return videoProjectCards.value.filter(project => [project.name, project.description]
    .some(field => String(field || '').toLowerCase().includes(keyword)))
})

async function loadAvailableProjects() {
  try {
    const result = await videoProjectRequest('GET', '/project/list')
    availableProjects.value = Array.isArray(result) ? result : []
    if (!newProjectId.value && availableProjects.value.length === 1) {
      newProjectId.value = String(availableProjects.value[0].id || '')
    }
  } catch (err) {
    projectError.value = cleanError(err)
  }
}

const projectLinkOptions = computed(() => availableProjects.value.map(project => ({
  value: String(project.id || ''),
  label: project.name || '未命名项目',
})))

function linkedProjectName(projectId = activeVideoProject.value?.projectId) {
  const id = String(projectId || '')
  return availableProjects.value.find(project => String(project.id || '') === id)?.name || '未关联项目'
}

function activeLinkedProjectId() {
  return String(activeVideoProject.value?.projectId || '').trim()
}

async function createVideoProject() {
  const name = newProjectName.value.trim()
  if (!name) {
    projectError.value = '请输入任务名称'
    return
  }
  projectCreating.value = true
  projectError.value = ''
  try {
    const project = await videoProjectRequest('POST', '/video-project', {
      name,
      projectId: newProjectId.value || '',
      description: newProjectDescription.value.trim(),
      assets: [],
      storyboards: [],
    })
    newProjectName.value = ''
    newProjectDescription.value = ''
    newProjectId.value = ''
    videoProjectCreateOpen.value = false
    await loadVideoProjects()
    await openVideoProject(project)
  } catch (err) {
    projectError.value = cleanError(err)
  } finally {
    projectCreating.value = false
  }
}

function restoreAssetMedia(asset) {
  // 资产的生成是同步请求，退出后无法续跑，重进即视为已结束
  const restored = { ...asset, generating: false, generationError: '' }
  delete restored.generatingStartedAt
  const fileId = restored.fileId || restored.coverId
  if (!restored.cover && fileId) restored.cover = fileDownloadUrl(fileId)
  delete restored.path
  return restored
}

function resolveAssetReference(asset) {
  const id = String(asset?.id || '')
  if (!id) return asset
  return canonicalAssetsById.value.get(id)
    || canonicalAssetsById.value.get(id.toLowerCase())
    || asset
}

const ACTIVE_TASK_STATUSES = new Set(['queued', 'pending', 'preparing', 'opening', 'configuring', 'uploading', 'submitting', 'generating', 'processing', 'running', 'sharing', 'downloading', 'finalizing', 'returning_to_conversation', 'confirming_authorization', 'waiting_confirmation'])

function isActiveTask(task) {
  return ACTIVE_TASK_STATUSES.has(String(task?.status || '').toLowerCase())
}

async function refreshTasks(projectId = '') {
  if (!window.pywebview?.api?.list_tasks) return []
  try {
    const tasks = await window.pywebview.api.list_tasks(String(projectId || ''))
    activeTasks.value = Array.isArray(tasks) ? tasks : []
  } catch (err) {
    activeTasks.value = []
  }
  return activeTasks.value
}

// 进入任务时按后端任务表恢复：进行中的任务接上轮询并显示进度；
// 已结束的任务由后端 _apply_task_result 回写业务数据，这里只需重新拉取详情。
async function hydrateRunningTasks(detail) {
  const projectId = String(detail?.id || activeVideoProject.value?.id || '')
  const tasks = await refreshTasks(projectId)
  const runningOwners = new Set(
    tasks.filter(task => isActiveTask(task) && task.ownerType === 'videoShot')
      .map(task => String(task.ownerId || '')),
  )
  storyboards.value.forEach(shot => {
    const task = tasks.find(item => item.ownerType === 'videoShot' && String(item.ownerId || '') === String(shot.id || ''))
    if (!task) return
    if (isActiveTask(task)) {
      const engine = String(task.generationEngine || '')
      if (engine === 'seedance') {
        // Seedance 轮询依赖分镜自带的 seedanceTaskId/seedanceModel，
        // 不能用任务表 id 覆盖分镜的 taskId。
        if (engine) shot.generationEngine = engine
        shot.status = task.status || 'generating'
        shot.statusText = task.statusText || '正在生成'
        shot.progress = Number(task.progress || 0)
        return
      }
      shot.taskId = String(task.id || '')
      shot.status = task.status || 'generating'
      shot.statusText = task.statusText || '正在生成'
      shot.progress = Number(task.progress || 0)
      shot.accountId = String(task.accountId || '')
      return
    }
    if (task.status === 'failed') {
      shot.status = 'failed'
      shot.statusText = task.statusText || '生成失败'
      shot.generationError = task.statusText || '生成失败'
    }
  })
  // 启动轮询：仍在跑的分镜
  storyboards.value
    .filter(shot => runningOwners.has(String(shot.id || '')))
    .forEach(shot => {
      if (shot.generationEngine === 'seedance') {
        if (shot.seedanceTaskId) pollSeedanceShot(shot)
      } else if (shot.taskId) {
        pollShot(shot)
      }
    })
}

async function openVideoProject(project) {
  if (!project?.id) return
  projectError.value = ''
  projectDetailLoading.value = true
  try {
    const detail = await videoProjectRequest('GET', `/video-project/${encodeURIComponent(project.id)}`)
    hydratingProject = true
    activeVideoProject.value = detail
    assets.value = (Array.isArray(detail.assets) ? detail.assets : []).map(restoreAssetMedia)
    const storedStoryboards = Array.isArray(detail.storyboards) ? detail.storyboards : []
    storyboards.value = storedStoryboards.length
      ? storedStoryboards.map((stored, index) => {
          const shot = { ...createStoryboard(index + 1), ...stored }
          shot.references = (Array.isArray(stored.references) ? stored.references : []).map((reference) => {
            const restoredReference = restoreAssetMedia(reference)
            return resolveAssetReference(restoredReference)
          })
          shot.modeOpen = false
          shot.settingsOpen = false
          shot.expanded = false
          shot.sendPreview = false
          shot.playerExpanded = false
          shot.referencesExpanded = false
          shot.replacingVideo = false
          shot.videoReplaceError = ''
          if (shot.resultFileId) shot.resultUrl = fileDownloadUrl(shot.resultFileId)
          else if (!shot.resultUrl?.startsWith('http')) shot.resultUrl = ''
          shot.resultPath = ''
          // 任务状态由后端任务表统一管理，恢复见下方 hydrateRunningTasks。
          shot.taskId = ''
          shot.status = ''
          shot.statusText = ''
          shot.progress = 0
          return shot
        })
      : [createStoryboard(1)]
    activeShotId.value = storyboards.value[0].id
    activeCategory.value = 'all'
    importedProjectTitle.value = detail.name || ''
    importedFileName.value = ''
    importedSchemaVersion.value = ''
    await nextTick()
    scheduleVisibleStoryboardAnchorUpdate()
    hydratingProject = false
    await hydrateRunningTasks(detail)
  } catch (err) {
    hydratingProject = false
    projectError.value = cleanError(err)
  } finally {
    projectDetailLoading.value = false
  }
}

function persistedAsset(asset) {
  const saved = { ...asset }
  delete saved.path
  delete saved.uploading
  // 生成中的资产记录 startedAt 时间戳，重进任务时据此恢复“正在生成”态
  if (saved.generating) saved.generatingStartedAt = Number(saved.generatingStartedAt || Date.now())
  else delete saved.generatingStartedAt
  delete saved.generating
  delete saved.generationError
  if (saved.fileId || saved.coverId) delete saved.cover
  return saved
}

function projectPayload() {
  return {
    name: activeVideoProject.value?.name || importedProjectTitle.value || '未命名任务',
    projectId: activeLinkedProjectId(),
    description: activeVideoProject.value?.description || '',
    assets: assets.value.map(persistedAsset),
    storyboards: storyboards.value.map(shot => {
      const saved = { ...shot, references: shot.references.map(persistedAsset) }
      delete saved.modeOpen
      delete saved.settingsOpen
      delete saved.settingsPopoverStyle
      delete saved.expanded
      delete saved.sendPreview
      delete saved.playerExpanded
      delete saved.videoPlaying
      delete saved.videoCurrent
      delete saved.videoDuration
      delete saved.videoMuted
      delete saved.referencesExpanded
      // 任务状态由后端任务表统一管理（list_tasks 恢复），业务数据里不再落库
      // taskId/status/progress，避免两套状态打架。
      delete saved.taskId
      delete saved.status
      delete saved.statusText
      delete saved.progress
      delete saved.resultPath
      delete saved.downloadingVideo
      delete saved.replacingVideo
      delete saved.videoReplaceError
      delete saved.generationError
      return saved
    }),
  }
}

async function saveActiveVideoProject() {
  if (!activeVideoProject.value?.id || hydratingProject) return
  if (projectSaveTimer) {
    window.clearTimeout(projectSaveTimer)
    projectSaveTimer = null
  }
  projectSaveStatus.value = '正在保存…'
  try {
    const saved = await videoProjectRequest(
      'PUT',
      `/video-project/${encodeURIComponent(activeVideoProject.value.id)}`,
      projectPayload(),
    )
    activeVideoProject.value = { ...activeVideoProject.value, ...saved }
    projectSaveStatus.value = '已保存到本地'
  } catch (err) {
    projectSaveStatus.value = `保存失败：${cleanError(err)}`
  }
}

function scheduleProjectSave() {
  if (!activeVideoProject.value?.id || hydratingProject) return
  projectSaveStatus.value = '有修改待保存'
  if (projectSaveTimer) window.clearTimeout(projectSaveTimer)
  projectSaveTimer = window.setTimeout(saveActiveVideoProject, 400)
}

async function backToVideoProjects() {
  await saveActiveVideoProject()
  storyboards.value.forEach(shot => stopPolling(shot.id))
  activeVideoProject.value = null
  assets.value = []
  storyboards.value = [createStoryboard(1)]
  activeShotId.value = storyboards.value[0].id
  projectSaveStatus.value = ''
  await loadVideoProjects()
}

async function loadGenerators() {
  loading.value = true
  error.value = ''
  try {
    if (!window.pywebview?.api) {
      error.value = '图片生成接口尚未就绪，请从桌面客户端打开'
      return
    }
    const [imageResult, videoResult] = await Promise.all([
      window.pywebview.api.backend_request('GET', '/api/admin/models/public/list?modelType=image', props.token, null),
      window.pywebview.api.backend_request('GET', '/api/admin/models/public/list?modelType=video', props.token, null),
    ])
    imageModels.value = Array.isArray(imageResult) ? imageResult : []
    videoApiModels.value = Array.isArray(videoResult) ? videoResult : []
    selectedImageModel.value = String(imageModels.value[0]?.id ?? imageModels.value[0]?.modelName ?? '')
    defaultSeedanceModel.value = String(seedanceModelOptions.value[0]?.value || '')
    storyboards.value.forEach((shot) => {
      if (!shot.seedanceModel) shot.seedanceModel = defaultSeedanceModel.value
    })
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    loading.value = false
  }
}

function absoluteMediaUrl(value) {
  const url = String(value || '').trim()
  if (!url || /^(?:https?:|data:|blob:)/i.test(url)) return url
  const fileId = fileIdFromUrl(url)
  const base = fileId.startsWith('local_') ? props.storageBase : props.apiBase
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`
}

function fileIdFromUrl(value) {
  return decodeURIComponent(String(value || '').match(/\/file\/([^/]+)\/download/)?.[1] || '')
}

function assetMediaValue(item) {
  const candidates = [item?.cover, item?.content, item?.image, item?.imageUrl, item?.image_url, item?.url, item?.audioUrl, item?.audio_url]
  return candidates.find(value => typeof value === 'string' && value.trim()) || ''
}

function assetPromptFor(item, category) {
  const fields = category === 'role'
    ? ['name', 'gender_age', 'appearance', 'face_features', 'body_features', 'hair', 'outfit', 'clothing', 'accessories', 'temperament', 'personality', 'description', 'prompt']
    : category === 'scene'
      ? ['name', 'environment', 'atmosphere', 'architecture', 'lighting', 'color', 'key_elements', 'continuity', 'front_view', 'left_view', 'right_view', 'back_view', 'ceiling', 'ground', 'description', 'prompt']
      : category === 'prop'
        ? ['name', 'appearance', 'material', 'color', 'texture', 'key_details', 'tags', 'scene', 'holder', 'continuity', 'function', 'description', 'prompt']
        : category === 'layout'
          ? ['name', 'spatial_state', 'camera_composition', 'ui_placeholders', 'characters', 'character_instances', 'props', 'reuse_shots', 'description', 'prompt']
          : ['name', 'character', 'voice', 'speed', 'tone', 'catchphrase', 'style', 'emotion', 'description', 'prompt']
  return fields
    .flatMap(key => Array.isArray(item?.[key]) ? item[key] : [item?.[key]])
    .filter(value => typeof value === 'string' && value.trim())
    .join('，')
}

function requestDeleteVideoProject(project) {
  if (!project?.id || deletingProjectId.value) return
  projectToDelete.value = project
  projectError.value = ''
}

function cancelDeleteVideoProject() {
  if (deletingProjectId.value) return
  projectToDelete.value = null
}

async function confirmDeleteVideoProject() {
  const project = projectToDelete.value
  if (!project?.id || deletingProjectId.value) return
  deletingProjectId.value = String(project.id)
  projectError.value = ''
  try {
    await videoProjectRequest('DELETE', `/video-project/${encodeURIComponent(project.id)}`)
    videoProjects.value = videoProjects.value.filter(item => String(item.id) !== String(project.id))
    projectToDelete.value = null
  } catch (err) {
    projectError.value = cleanError(err)
  } finally {
    deletingProjectId.value = ''
  }
}

function rolePromptWithoutDefaultLayout(value) {
  const prompt = String(value || '').trim()
  return prompt.startsWith(DEFAULT_ROLE_IMAGE_PROMPT)
    ? prompt.slice(DEFAULT_ROLE_IMAGE_PROMPT.length).trim()
    : prompt
}

function rolePromptHasThreeViews(value) {
  return String(value || '').includes('三视图')
}

function roleGenerationPrompt(value) {
  const prompt = rolePromptWithoutDefaultLayout(value)
  if (rolePromptHasThreeViews(prompt)) return prompt
  return prompt ? `${prompt}\n${DEFAULT_ROLE_IMAGE_PROMPT}` : DEFAULT_ROLE_IMAGE_PROMPT
}

function normalizeAssetGroup(items, category, promptMap = new Map()) {
  return (Array.isArray(items) ? items : []).map((item, index) => {
    const source = item && typeof item === 'object' ? item : { name: String(item || '') }
    const sourceId = String(source.id || `${category}-${Date.now()}-${index}`)
    const referencePrompt = promptMap.get(sourceId) || promptMap.get(sourceId.toLowerCase())
    const mergedSource = referencePrompt ? { ...source, prompt: referencePrompt.prompt || referencePrompt } : source
    const media = assetMediaValue(source)
    return {
      ...mergedSource,
      id: sourceId,
      name: String(source.name || source.character || source.title || source.id || `未命名${categories.find(entry => entry.key === category)?.label || '资产'}`),
      category,
      type: ['role', 'layout'].includes(category) ? 'image' : category,
      description: String(source.description || source.summary || ''),
      useDefaultRoleLayout: category === 'role' ? source.useDefaultRoleLayout !== false : undefined,
      prompt: category === 'audio'
        ? DEFAULT_AUDIO_PROMPT
        : category === 'role'
          ? rolePromptWithoutDefaultLayout(assetPromptFor(mergedSource, category))
          : assetPromptFor(mergedSource, category),
      cover: media ? absoluteMediaUrl(media) : '',
      fileId: String(source.fileId || source.coverId || fileIdFromUrl(media) || ''),
      generating: false,
      generationError: '',
    }
  })
}

function buildReferencePromptMap(referencePrompts) {
  const map = new Map()
  Object.values(referencePrompts && typeof referencePrompts === 'object' ? referencePrompts : {}).forEach(group => {
    ;(Array.isArray(group) ? group : []).forEach(item => {
      if (!item?.id) return
      map.set(String(item.id), item)
      map.set(String(item.id).toLowerCase(), item)
    })
  })
  return map
}

function shotPromptFor(shot) {
  const acts = (Array.isArray(shot?.acts) ? shot.acts : []).map(act => {
    const audio = (Array.isArray(act?.audio) ? act.audio : [])
      .filter(item => !['none', '无'].includes(String(item?.type || '').toLowerCase()))
      .map(item => [item.type, item.desc, item.description, item.detail, item.text].filter(Boolean).join('：'))
      .filter(Boolean)
      .join('；')
    return [
      [act?.time ? `【${act.time}】` : '', act?.name].filter(Boolean).join(' '),
      act?.visual ? `画面：${act.visual}` : '',
      act?.camera ? `运镜：${act.camera}` : '',
      audio ? `音频：${audio}` : '',
    ].filter(Boolean).join('\n')
  }).filter(Boolean)
  return [shot?.title, ...acts].filter(Boolean).join('\n')
}

function inferredShotDuration(source) {
  const explicitDuration = Number(source?.duration_s ?? source?.duration)
  if (Number.isFinite(explicitDuration) && explicitDuration > 0) return explicitDuration

  const timelineTexts = [
    source?.time,
    source?.timeline,
    source?.prompt,
    source?.description,
    ...(Array.isArray(source?.acts) ? source.acts.map(act => act?.time) : []),
  ].filter(value => value !== undefined && value !== null).map(String)
  const endSeconds = []
  const timecodeRange = /(\d{1,2}):([0-5]\d)(?:\.\d+)?\s*(?:-|–|—|~|～|至)\s*(\d{1,2}):([0-5]\d)(?:\.(\d+))?/g
  const secondRange = /(?:^|[^\d])(\d{1,2}(?:\.\d+)?)\s*(?:-|–|—|~|～|至)\s*(\d{1,2}(?:\.\d+)?)\s*秒/g
  timelineTexts.forEach((text) => {
    for (const match of text.matchAll(timecodeRange)) {
      const fraction = match[5] ? Number(`0.${match[5]}`) : 0
      endSeconds.push(Number(match[3]) * 60 + Number(match[4]) + fraction)
    }
    for (const match of text.matchAll(secondRange)) endSeconds.push(Number(match[2]))
  })
  return endSeconds.length ? Math.ceil(Math.max(...endSeconds)) : defaultVideoSettings.duration
}

function normalizeImportedShots(items, assetIndex) {
  return (Array.isArray(items) ? items : []).map((source, index) => {
    const shot = createStoryboard(index + 1)
    const rawDuration = inferredShotDuration(source)
    const duration = Math.min(15, Math.max(1, Math.ceil(Number.isFinite(rawDuration) ? rawDuration : defaultVideoSettings.duration)))
    shot.id = `json-shot-${String(source?.id || index + 1)}`
    shot.title = String(source?.title || source?.name || source?.id || shot.title)
    const consistencyText = (Array.isArray(source?.references) ? source.references : [])
      .filter(reference => reference?.id)
      .map(reference => `${reference.label || reference.id} {{${reference.id}}}`)
      .join('，')
    shot.prompt = [consistencyText ? `一致性引用：${consistencyText}` : '', shotPromptFor(source)].filter(Boolean).join('\n')
    shot.duration = duration
    shot.sound = source?.sound ?? source?.output_sound ?? true
    shot.references = (Array.isArray(source?.references) ? source.references : [])
      .map(reference => assetIndex.get(String(reference?.id || reference)) || assetIndex.get(String(reference?.id || reference).toLowerCase()))
      .filter(Boolean)
    shot.referenceLabels = Object.fromEntries((Array.isArray(source?.references) ? source.references : [])
      .filter(reference => reference?.id)
      .map(reference => [String(reference.id), String(reference.label || '')]))
    return shot
  })
}

function applyImportedDocument(document, sourceName) {
    if (!document || typeof document !== 'object') throw new Error('JSON 顶层必须是创作任务对象')
    const root = document.consistency && typeof document.consistency === 'object'
      ? document.consistency
      : document.assets && typeof document.assets === 'object'
        ? document.assets
        : document
    const promptMap = buildReferencePromptMap(root.reference_prompts)
    const nextAssets = [
      ...normalizeAssetGroup(root.characters || root.roles || root.people, 'role', promptMap),
      ...normalizeAssetGroup(root.scenes, 'scene', promptMap),
      ...normalizeAssetGroup(root.props || root.items, 'prop', promptMap),
      ...normalizeAssetGroup(root.layouts || root.white_models || root.whiteModels || root.blockings, 'layout', promptMap),
      ...normalizeAssetGroup(root.audio || root.audios, 'audio', promptMap),
    ]
    if (!nextAssets.length) throw new Error('没有找到 characters、scenes、props、layouts 或 audio 数据')
    assets.value = nextAssets
    const assetIndex = new Map()
    nextAssets.forEach(asset => {
      assetIndex.set(String(asset.id), asset)
      assetIndex.set(String(asset.id).toLowerCase(), asset)
    })
    const importedShots = normalizeImportedShots(document.shots || root.shots, assetIndex)
    if (importedShots.length) {
      pollTimers.forEach(timer => window.clearTimeout(timer))
      pollTimers.clear()
      storyboards.value = importedShots
      activeShotId.value = importedShots[0].id
    }
    importedFileName.value = sourceName || '已导入 JSON'
    importedProjectTitle.value = String(document.title || document.project || '')
    if (activeVideoProject.value && importedProjectTitle.value) activeVideoProject.value.name = importedProjectTitle.value
    importedSchemaVersion.value = String(document.schema_version || '')
    activeCategory.value = 'all'
}

function openImportDialog() {
  importError.value = ''
  importDialogOpen.value = true
  nextTick(() => document.querySelector('.json-import-textarea')?.focus())
}

function closeImportDialog() {
  importDialogOpen.value = false
  importError.value = ''
}

function importJsonText() {
  importError.value = ''
  try {
    const raw = jsonText.value.replace(/^\uFEFF/, '').trim()
    if (!raw) throw new Error('请粘贴完整 JSON 内容')
    applyImportedDocument(JSON.parse(raw), '粘贴的 JSON')
    jsonText.value = ''
    importDialogOpen.value = false
  } catch (err) {
    importError.value = err instanceof SyntaxError ? `JSON 格式错误：${err.message}` : cleanError(err)
  }
}

async function importAssetJson() {
  importError.value = ''
  if (!window.pywebview?.api) {
    importError.value = '请从桌面客户端选择 JSON 文件'
    return
  }
  try {
    const selected = await window.pywebview.api.select_json_data()
    if (!selected) return
    applyImportedDocument(selected.data, selected.name)
    importDialogOpen.value = false
  } catch (err) {
    importError.value = cleanError(err)
  }
}

async function generateAsset(asset) {
  const isAudio = asset.category === 'audio'
  const isLayout = asset.category === 'layout'
  const sourcePrompt = String(asset.prompt || asset.description || asset.name || '').trim()
  let prompt = isAudio
    ? DEFAULT_AUDIO_PROMPT
    : asset.category === 'role'
      ? asset.useDefaultRoleLayout === false
        ? rolePromptWithoutDefaultLayout(sourcePrompt)
        : roleGenerationPrompt(sourcePrompt)
      : sourcePrompt
  let editImages = []
  let resolvedReferences = []
  asset.generationError = ''
  if (!prompt) {
    asset.generationError = '该资产缺少可用于生成的描述字段'
    return
  }
  if (!window.pywebview?.api) {
    asset.generationError = '请从桌面客户端启动后再生成'
    return
  }
  if (asset.category !== 'audio' && !selectedImageModel.value) {
    asset.generationError = '没有可用的图片模型，请先配置'
    return
  }
  const referenceState = isAudio ? null : assetReferenceState(asset)
  if (isLayout || referenceState?.total) {
    const { resolved, unresolved } = layoutDependencies(asset)
    if (unresolved.length) {
      asset.generationError = `${isLayout ? '白模依赖' : '参考图'}不存在：${unresolved.join('、')}`
      return
    }
    if (!resolved.length) {
      asset.generationError = isLayout ? '白模缺少人物或道具图片依赖' : '资产缺少可用参考图'
      return
    }
    const missing = resolved.filter(dependency => !assetUrl(dependency))
    if (missing.length) {
      asset.generationError = `请先生成${isLayout ? '白模依赖图片' : '参考图'}：${missing.map(item => item.name || item.id).join('、')}`
      return
    }
    resolvedReferences = resolved
    prompt = referenceEditPrompt(asset, resolved, sourcePrompt)
  }
  asset.generating = true
  asset.generatingStartedAt = Date.now()
  await saveActiveVideoProject()
  await nextTick()
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
  try {
    if (resolvedReferences.length) editImages = await Promise.all(resolvedReferences.map(imageEditDataUrl))
    // 提交为后台任务：立即返回 taskId，生成在后台线程执行，
    // 完成后由后端 _apply_task_result 回写到当前资产，切页面/切客户端都不会丢。
    const body = isAudio
      ? { prompt: DEFAULT_AUDIO_PROMPT, preview_text: DEFAULT_AUDIO_PROMPT }
      : { model: selectedImageModel.value, prompt, ...(editImages.length ? { image: editImages } : {}), n: 1, size: '1024x1024' }
    const submitted = await window.pywebview.api.start_asset_image_generation({
      path: isAudio ? '/ai/audio' : '/ai/image',
      body,
      token: props.token,
      ownerType: 'imageAsset',
      ownerId: String(asset.id || ''),
      projectId: String(activeVideoProject.value?.id || ''),
      taskName: asset.name || (isAudio ? '资产音频' : '资产图片'),
    })
    asset.taskId = String(submitted?.taskId || '')
    await saveActiveVideoProject()
    refreshTasks(String(activeVideoProject.value?.id || ''))
    // 返回的 Promise 在任务进入终态时 resolve：单点生成可忽略，批量生成需要
    // await 它以保证"参考图→白模"这类依赖顺序。
    return await pollAssetTask(asset)
  } catch (err) {
    asset.generationError = cleanError(err)
    asset.generating = false
    delete asset.generatingStartedAt
    await saveActiveVideoProject()
  }
}

function pollAssetTask(asset) {
  return new Promise(resolve => {
    const tick = async () => {
      try {
        const latest = await window.pywebview.api.get_task(asset.taskId)
        if (latest && latest.status === 'succeeded') {
          const rawUrl = String(latest.resultUrl || '')
          asset.cover = absoluteMediaUrl(rawUrl)
          asset.fileId = String(latest.resultFileId || fileIdFromUrl(rawUrl) || '')
          if (asset.category === 'audio') asset.duration = '已生成'
          asset.generationError = ''
          asset.generating = false
          delete asset.generatingStartedAt
          await saveActiveVideoProject()
          refreshTasks(String(activeVideoProject.value?.id || ''))
          resolve()
          return
        }
        if (latest && ['failed', 'cancelled', 'canceled'].includes(latest.status)) {
          asset.generationError = latest.statusText || '生成失败'
          asset.generating = false
          delete asset.generatingStartedAt
          await saveActiveVideoProject()
          refreshTasks(String(activeVideoProject.value?.id || ''))
          resolve()
          return
        }
        pollTimers.set(`asset:${asset.id}`, window.setTimeout(tick, 1200))
      } catch (err) {
        asset.generationError = cleanError(err)
        asset.generating = false
        delete asset.generatingStartedAt
        await saveActiveVideoProject()
        resolve()
      }
    }
    tick()
  })
}

function showAssetActions() {
  assetActionsOpen.value = true
}

function hideAssetActions() {
  if (!assetActionsPinned.value && !bulkGenerating.value && !assetLibrarySyncing.value) assetActionsOpen.value = false
}

function toggleAssetActions() {
  assetActionsPinned.value = !assetActionsPinned.value
  assetActionsOpen.value = assetActionsPinned.value
}

async function generateAllMissingAssets() {
  if (bulkGenerating.value) return
  const scope = activeCategory.value === 'all'
    ? [...assets.value]
    : assets.value.filter(asset => asset.category === activeCategory.value)
  const scopeLabel = categories.find(category => category.key === activeCategory.value)?.label || '当前分类'
  const pending = scope.filter(asset => !assetUrl(asset))
  if (!pending.length) {
    bulkGenerationStatus.value = scope.length ? `${scopeLabel}资产均已生成` : `${scopeLabel}下没有资产`
    return
  }
  if (pending.some(asset => asset.category !== 'audio') && !selectedImageModel.value) {
    bulkGenerationStatus.value = '请先选择图片模型'
    return
  }
  bulkGenerating.value = true
  assetActionsOpen.value = true
  assetActionsPinned.value = true
  let completed = 0
  try {
    bulkGenerationStatus.value = `正在生成${scopeLabel} 0/${pending.length}`
    const generateStage = stage => Promise.all(stage.map(async (asset) => {
      await generateAsset(asset)
      completed += 1
      bulkGenerationStatus.value = `正在生成 ${completed}/${pending.length}`
    }))
    let remaining = [...pending]
    while (remaining.length) {
      const remainingIds = new Set(remaining.map(asset => String(asset.id || '').toLowerCase()))
      const blocked = remaining.filter((asset) => {
        const { resolved } = layoutDependencies(asset)
        return resolved.some(dependency => !assetUrl(dependency) && !remainingIds.has(String(dependency.id || '').toLowerCase()))
      })
      if (blocked.length) {
        blocked.forEach((asset) => {
          const missing = layoutDependencies(asset).resolved.filter(dependency => !assetUrl(dependency))
          asset.generationError = `参考图生成失败或缺失，未执行：${missing.map(item => item.name || item.id).join('、')}`
          completed += 1
        })
        const blockedIds = new Set(blocked.map(asset => asset.id))
        remaining = remaining.filter(asset => !blockedIds.has(asset.id))
        bulkGenerationStatus.value = `正在生成 ${completed}/${pending.length}`
        continue
      }

      const stage = remaining.filter((asset) => {
        const { resolved, unresolved } = layoutDependencies(asset)
        return unresolved.length > 0 || resolved.every(dependency => Boolean(assetUrl(dependency)))
      })
      if (!stage.length) {
        remaining.forEach((asset) => {
          asset.generationError = '参考图依赖循环或无法满足，未执行生成'
          completed += 1
        })
        remaining = []
        break
      }
      bulkGenerationStatus.value = `正在生成第 ${completed + 1}-${completed + stage.length} 项，共 ${pending.length} 项`
      await generateStage(stage)
      const stageIds = new Set(stage.map(asset => asset.id))
      remaining = remaining.filter(asset => !stageIds.has(asset.id))
    }
    const succeeded = pending.filter(asset => assetUrl(asset)).length
    const failed = pending.length - succeeded
    bulkGenerationStatus.value = `${scopeLabel}已生成 ${succeeded} 项${failed ? `，${failed} 项因依赖或生成失败未完成` : ''}，跳过 ${scope.length - pending.length} 项已有资产`
  } finally {
    bulkGenerating.value = false
  }
}

function libraryTypeForAsset(asset) {
  if (['role', 'layout'].includes(asset.category)) return 'image'
  return ['scene', 'prop', 'audio'].includes(asset.category) ? asset.category : (asset.type || 'image')
}

function assetMatchKey(name, type) {
  return `${String(name || '').trim().toLocaleLowerCase()}::${String(type || '').trim().toLocaleLowerCase()}`
}

function libraryDescriptionForAsset(asset) {
  const description = String(asset.description || '').trim()
  const prompt = String(asset.prompt || '').trim()
  if (!prompt || description.includes(prompt)) return description
  return [description, `提示词：${prompt}`].filter(Boolean).join('\n')
}

async function syncAssetsToLibrary() {
  if (assetLibrarySyncing.value) return
  if (!window.pywebview?.api) {
    assetLibraryStatus.value = '请从桌面客户端同步资产'
    return
  }
  const linkedProjectId = activeLinkedProjectId()
  if (!linkedProjectId) {
    assetLibraryStatus.value = '请先在任务详情顶部选择关联项目'
    return
  }
  const syncable = assets.value.filter(asset => assetUrl(asset) && (asset.fileId || fileIdFromUrl(assetUrl(asset))))
  if (!syncable.length) {
    assetLibraryStatus.value = '没有可同步的已生成资产'
    return
  }
  assetLibrarySyncing.value = true
  assetLibraryStatus.value = `正在同步 0/${syncable.length}`
  try {
    const libraryAssets = await window.pywebview.api.backend_request('GET', '/asset/list', props.token, null) || []
    const libraryMap = new Map(libraryAssets
      .filter(item => (Array.isArray(item.boundProjectIds) ? item.boundProjectIds : []).map(String).includes(linkedProjectId))
      .map(item => [assetMatchKey(item.name, item.type), item]))
    let completed = 0
    await Promise.all(syncable.map(async (asset) => {
      const type = libraryTypeForAsset(asset)
      const payload = {
        name: String(asset.name || ''),
        type,
        coverId: String(asset.fileId || fileIdFromUrl(assetUrl(asset)) || ''),
        description: libraryDescriptionForAsset(asset),
        tags: type,
        duration: String(asset.duration || ''),
        boundProjectIds: [linkedProjectId],
      }
      const existing = libraryMap.get(assetMatchKey(payload.name, type))
      if (existing) {
        payload.boundProjectIds = [...new Set([...(existing.boundProjectIds || []).map(String), linkedProjectId])]
      }
      const result = await window.pywebview.api.backend_request(existing ? 'PUT' : 'POST', existing ? `/asset/${encodeURIComponent(existing.id)}` : '/asset', props.token, payload)
      if (!existing && result) libraryMap.set(assetMatchKey(payload.name, type), result)
      completed += 1
      assetLibraryStatus.value = `正在同步 ${completed}/${syncable.length}`
    }))
    assetLibraryStatus.value = `已同步 ${syncable.length} 项，并绑定项目“${linkedProjectName()}”`
  } catch (err) {
    assetLibraryStatus.value = `同步失败：${cleanError(err)}`
  } finally {
    assetLibrarySyncing.value = false
  }
}

async function restoreAssetsFromLibrary() {
  if (assetLibrarySyncing.value) return
  if (!window.pywebview?.api) {
    assetLibraryStatus.value = '请从桌面客户端回显资产'
    return
  }
  const linkedProjectId = activeLinkedProjectId()
  if (!linkedProjectId) {
    assetLibraryStatus.value = '请先在任务详情顶部选择关联项目'
    return
  }
  assetLibrarySyncing.value = true
  assetLibraryStatus.value = `正在从项目“${linkedProjectName()}”匹配资产…`
  try {
    const libraryAssets = await window.pywebview.api.backend_request('GET', '/asset/list', props.token, null) || []
    const libraryMap = new Map(libraryAssets
      .filter(item => (Array.isArray(item.boundProjectIds) ? item.boundProjectIds : []).map(String).includes(linkedProjectId))
      .map(item => [assetMatchKey(item.name, item.type), item]))
    let restored = 0
    assets.value.forEach((asset) => {
      const match = libraryMap.get(assetMatchKey(asset.name, libraryTypeForAsset(asset)))
      const coverId = String(match?.coverId || '')
      if (!match || (!coverId && !match.cover)) return
      asset.cover = match.cover || absoluteMediaUrl(`/file/${encodeURIComponent(coverId)}/download`)
      asset.fileId = coverId || fileIdFromUrl(match.cover)
      if (asset.category === 'audio' && match.duration) asset.duration = match.duration
      asset.generationError = ''
      restored += 1
    })
    assetLibraryStatus.value = `已从项目“${linkedProjectName()}”回显 ${restored} 项资产`
  } catch (err) {
    assetLibraryStatus.value = `回显失败：${cleanError(err)}`
  } finally {
    assetLibrarySyncing.value = false
  }
}

function openAssetDetail(asset) {
  const isAudio = asset.category === 'audio'
  const isRole = asset.category === 'role'
  if (isAudio) asset.prompt = DEFAULT_AUDIO_PROMPT
  if (isRole) asset.prompt = rolePromptWithoutDefaultLayout(asset.prompt)
  assetDetailTarget.value = asset
  assetReferencesCopied.value = false
  assetDraft.value = {
    name: String(asset.name || ''),
    description: String(asset.description || ''),
    prompt: isAudio ? DEFAULT_AUDIO_PROMPT : String(asset.prompt || ''),
    useDefaultRoleLayout: isRole ? asset.useDefaultRoleLayout !== false : true,
  }
  audioPreviewPlaying.value = false
  audioPreviewCurrent.value = 0
  audioPreviewDuration.value = 0
  assetDetailOpen.value = true
}

function closeAssetDetail() {
  if (audioPreview.value) audioPreview.value.pause()
  assetDetailOpen.value = false
  assetDetailTarget.value = null
  audioPreviewPlaying.value = false
  audioPreviewCurrent.value = 0
  audioPreviewDuration.value = 0
}

function formatAudioTime(value) {
  const seconds = Number.isFinite(Number(value)) ? Math.max(0, Math.floor(Number(value))) : 0
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function syncAudioPreviewMetadata(event) {
  audioPreviewDuration.value = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0
}

function syncAudioPreviewTime(event) {
  audioPreviewCurrent.value = Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0
}

async function toggleAudioPreview() {
  const player = audioPreview.value
  if (!player) return
  if (player.paused) {
    try { await player.play() } catch (err) { assetDetailTarget.value.generationError = cleanError(err) }
  } else {
    player.pause()
  }
}

function seekAudioPreview(event) {
  const player = audioPreview.value
  if (!player) return
  player.currentTime = Number(event.target.value) || 0
  audioPreviewCurrent.value = player.currentTime
}

function saveAssetDetail() {
  if (!assetDetailTarget.value) return
  const isAudio = assetDetailTarget.value.category === 'audio'
  const isRole = assetDetailTarget.value.category === 'role'
  Object.assign(assetDetailTarget.value, {
    name: assetDraft.value.name.trim() || assetDetailTarget.value.name,
    description: assetDraft.value.description.trim(),
    prompt: isAudio
      ? DEFAULT_AUDIO_PROMPT
      : assetDraft.value.prompt.trim(),
    ...(isRole ? { useDefaultRoleLayout: assetDraft.value.useDefaultRoleLayout } : {}),
  })
  closeAssetDetail()
}

async function generateAssetFromDetail() {
  if (!assetDetailTarget.value) return
  const isAudio = assetDetailTarget.value.category === 'audio'
  const isRole = assetDetailTarget.value.category === 'role'
  Object.assign(assetDetailTarget.value, {
    name: assetDraft.value.name.trim() || assetDetailTarget.value.name,
    description: assetDraft.value.description.trim(),
    prompt: isAudio
      ? DEFAULT_AUDIO_PROMPT
      : assetDraft.value.prompt.trim(),
    ...(isRole ? { useDefaultRoleLayout: assetDraft.value.useDefaultRoleLayout } : {}),
  })
  await generateAsset(assetDetailTarget.value)
}

async function copyAssetReferences(asset) {
  if (!asset || assetReferencesCopying.value) return
  const state = assetReferenceState(asset)
  asset.generationError = ''
  assetReferencesCopied.value = false
  if (!state.total) {
    asset.generationError = '当前资产没有参考图'
    return
  }
  if (state.ready !== state.total) {
    asset.generationError = '请先生成或补齐全部参考图后再复制'
    return
  }
  const api = window.pywebview?.api
  if (!api?.prepare_generation_asset || !api?.copy_files_to_clipboard) {
    asset.generationError = '桌面客户端缺少参考图复制能力，请重启客户端后重试'
    return
  }

  assetReferencesCopying.value = true
  try {
    const paths = []
    for (const reference of state.items) {
      const prepared = await api.prepare_generation_asset(reference, props.token)
      const path = String(prepared?.path || '')
      if (!path) throw new Error(`无法准备参考图：${reference.name || reference.id}`)
      paths.push(path)
    }
    const copied = await api.copy_files_to_clipboard(paths)
    if (Number(copied?.count || 0) !== paths.length) throw new Error('参考图未能完整写入剪贴板')
    assetReferencesCopied.value = true
    window.setTimeout(() => { assetReferencesCopied.value = false }, 1600)
  } catch (err) {
    asset.generationError = cleanError(err)
  } finally {
    assetReferencesCopying.value = false
  }
}

async function selectLocalImageForAsset(asset) {
  if (!window.pywebview?.api) {
    asset.generationError = '请从桌面客户端选择本地图片'
    return
  }
  try {
    const selected = await window.pywebview.api.select_and_upload_asset(props.token, {
      name: asset.name || '任务资产',
      description: asset.description || '',
      tags: asset.category || 'image',
      type: 'image',
      boundProjectIds: activeLinkedProjectId() ? [activeLinkedProjectId()] : [],
    })
    if (!selected) return
    asset.fileId = String(selected.coverId || '')
    asset.coverId = asset.fileId
    asset.cover = fileDownloadUrl(asset.fileId)
    delete asset.path
    asset.generationError = ''
  } catch (err) {
    asset.generationError = cleanError(err)
  }
}

function clearAssetImage(asset) {
  if (!asset || asset.category === 'audio') return
  const currentUrl = assetUrl(asset)
  ;['cover', 'fileId', 'coverId', 'content', 'image', 'imageUrl', 'image_url', 'url'].forEach((key) => {
    asset[key] = ''
  })
  delete asset.path
  delete asset.previewFailed
  asset.generationError = ''
  if (currentUrl && mediaPreviewSrc.value === currentUrl) {
    mediaPreviewVisible.value = false
    mediaPreviewSrc.value = ''
  }
  scheduleProjectSave()
}

function assetUrl(asset) {
  const resolvedAsset = resolveAssetReference(asset)
  if (resolvedAsset?.cover) return absoluteMediaUrl(resolvedAsset.cover)
  const id = resolvedAsset?.coverId || resolvedAsset?.fileId
  return fileDownloadUrl(id)
}

function isAudioAsset(asset) {
  const hints = [asset?.mediaType, asset?.type, asset?.category, asset?.mimeType, asset?.contentType, asset?.tags]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  if (/audio|音频/.test(hints) || asset?.audioUrl || asset?.audio_url) return true
  const pathHint = String(asset?.path || asset?.originalFileName || '').toLowerCase()
  if (/\.(?:mp3|wav|m4a|aac|ogg|flac)(?:$|[?#])/.test(pathHint)) return true
  return Boolean(asset?.previewFailed && asset?.category === 'local')
}

function handleReferencePreviewError(asset) {
  asset.previewFailed = true
}

function addReference(asset) {
  if (!assetUrl(asset)) {
    asset.generationError = asset.category === 'audio' ? '请先生成音频' : '请先生成图片'
    return
  }
  const shot = storyboards.value.find(item => item.id === activeShotId.value) || storyboards.value[0]
  if (!shot || shot.references.some(item => String(item.id) === String(asset.id))) return
  shot.references.push(asset)
  shot.referenceLabels[String(asset.id)] = `${asset.name}参考`
  const referenceText = `${asset.name}参考 {{${asset.id}}}`
  if (!shot.prompt.includes(`{{${asset.id}}}`)) {
    const lines = shot.prompt.split('\n')
    const lineIndex = lines.findIndex(line => /^一致性引用[：:]/.test(line.trim()))
    if (lineIndex >= 0) lines[lineIndex] = `${lines[lineIndex].replace(/[，,\s]+$/, '')}，${referenceText}`
    else lines.unshift(`一致性引用：${referenceText}`)
    shot.prompt = lines.join('\n')
  }
  shot.referencesExpanded = true
}

function selectMentionAsset(shot, asset) {
  if (!shot || !asset || shot.references.some(item => String(item.id) === String(asset.id))) return
  if (assetUrl(asset)) shot.references.push(asset)
  shot.referenceLabels[String(asset.id)] = asset.name || String(asset.id)
  shot.referencesExpanded = true
}

function mentionAssets(shot) {
  return (Array.isArray(shot?.references) ? shot.references : [])
    .map(resolveAssetReference)
    .filter(asset => asset?.id && assetUrl(asset))
}

function sendAttachments(shot) {
  const result = (Array.isArray(shot?.references) ? shot.references : [])
    .map(resolveAssetReference)
    .filter(asset => asset?.id)
  const seen = new Set(result.map(asset => String(asset.id).toLowerCase()))
  const prompt = String(shot?.prompt || '')
  const pattern = /[{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2}/g
  let match
  while ((match = pattern.exec(prompt))) {
    const id = String(match[1] || '')
    const key = id.toLowerCase()
    if (!id || seen.has(key)) continue
    const asset = canonicalAssetsById.value.get(id) || canonicalAssetsById.value.get(key)
    if (!asset) continue
    result.push(asset)
    seen.add(key)
  }
  return result
}

function promptForOriginalDoubao(prompt, references, omittedReferences = []) {
  const attachmentNames = new Map()
  const omittedNames = new Map(omittedReferences.map(asset => [
    String(asset?.id || '').toLowerCase(),
    asset?.name || asset?.title || '音频参考',
  ]))
  const imageNames = []
  const audioNames = []
  references.forEach((asset, index) => {
    const audio = isAudioAsset(asset)
    const attachmentName = `${audio ? '文件' : '图'}${index + 1}`
    attachmentNames.set(String(asset.id).toLowerCase(), attachmentName)
    if (audio) audioNames.push(attachmentName)
    else imageNames.push(attachmentName)
  })
  const source = String(prompt || '')
  const tokenPattern = /[{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2}/g
  const directlyUsed = new Set([...source.matchAll(tokenPattern)]
    .map(match => attachmentNames.get(String(match[1] || '').toLowerCase()))
    .filter(Boolean))
  const availableAudioNames = audioNames.filter(name => !directlyUsed.has(name))
  const availableImageNames = imageNames.filter(name => !directlyUsed.has(name))
  const fallbackNames = new Map()
  return source.replace(tokenPattern, (token, id) => {
    const key = String(id).toLowerCase()
    const directName = attachmentNames.get(key)
    if (directName) return directName
    if (omittedNames.has(key)) return omittedNames.get(key)
    if (fallbackNames.has(key)) return fallbackNames.get(key)
    const isAudioToken = /^(?:audio|voice|sound)[-_.:]/i.test(String(id))
    const isImageToken = /^(?:char|character|role|scene|prop|image|img)[-_.:]/i.test(String(id))
    if (!isAudioToken && !isImageToken) return token
    const fallbackName = isAudioToken ? availableAudioNames.shift() : availableImageNames.shift()
    if (!fallbackName) return token
    fallbackNames.set(key, fallbackName)
    return fallbackName
  })
}

function layoutDependencyIds(asset) {
  const values = [
    ...(asset?.category === 'layout' && Array.isArray(asset?.characters) ? asset.characters : []),
    ...(asset?.category === 'layout' && Array.isArray(asset?.character_instances) ? asset.character_instances.map(item => item?.character_id || item?.id) : []),
    ...(asset?.category === 'layout' && Array.isArray(asset?.props) ? asset.props : []),
    ...(Array.isArray(asset?.dependencies) ? asset.dependencies : []),
    ...(Array.isArray(asset?.references) ? asset.references : []),
    ...(Array.isArray(asset?.reference_ids) ? asset.reference_ids : []),
    ...(Array.isArray(asset?.referenceIds) ? asset.referenceIds : []),
  ]
  const seen = new Set()
  return values.flatMap((value) => {
    const id = String(value?.id || value || '').trim()
    const key = id.toLowerCase()
    if (!id || key === String(asset?.id || '').toLowerCase() || seen.has(key)) return []
    seen.add(key)
    return [id]
  })
}

function layoutDependencies(asset) {
  const resolved = []
  const unresolved = []
  const excluded = []
  layoutDependencyIds(asset).forEach((id) => {
    const dependency = canonicalAssetsById.value.get(id) || canonicalAssetsById.value.get(id.toLowerCase())
    if (asset?.category === 'scene' && dependency?.category === 'role') excluded.push(dependency)
    else if (!dependency || dependency.category === 'audio' || dependency.category === 'layout') unresolved.push(id)
    else resolved.push(dependency)
  })
  return { resolved, unresolved, excluded }
}

function assetReferenceState(asset) {
  const { resolved, unresolved, excluded } = layoutDependencies(asset)
  const readyItems = resolved.filter(item => Boolean(assetUrl(item)))
  return {
    items: resolved,
    readyItems,
    unresolved,
    excluded,
    ready: readyItems.length,
    total: resolved.length + unresolved.length,
  }
}

function referenceEditPrompt(asset, dependencies, sourcePrompt) {
  const imageMap = dependencies.map((dependency, index) => `图${index + 1}=${dependency.name || dependency.id}`).join('，')
  return [
    `参考图对应关系（严格按上传顺序）：${imageMap}。`,
    '请使用以上全部参考图片进行图片编辑生成，严格保持各图主体的身份、造型、身体比例和关键道具外形一致；不要重新设计主体。',
    sourcePrompt,
  ].filter(Boolean).join('\n')
}

async function imageEditDataUrl(asset) {
  const media = assetUrl(asset)
  if (media.startsWith('data:')) return media
  const api = window.pywebview?.api
  if (!api?.prepare_generation_asset || !api?.read_local_media_data_url) throw new Error('桌面客户端缺少参考图读取能力，请重启客户端后重试')
  const prepared = await api.prepare_generation_asset(asset, props.token)
  const encoded = await api.read_local_media_data_url(prepared?.path)
  const dataUrl = String(encoded?.url || encoded?.dataUrl || encoded?.data_url || '')
  if (!dataUrl.startsWith('data:')) throw new Error(`无法读取参考图片：${asset.name || asset.id}`)
  return dataUrl
}

function seedanceReferenceDescriptors(shot, references) {
  let imageIndex = 0
  let audioIndex = 0
  return references.map((asset, sourceIndex) => {
    if (isAudioAsset(asset)) {
      audioIndex += 1
      return {
        asset,
        sourceIndex,
        type: 'audio_url',
        urlField: 'audio_url',
        role: 'reference_audio',
        marker: `[Audio ${audioIndex}]`,
      }
    }
    imageIndex += 1
    return {
      asset,
      sourceIndex,
      type: 'image_url',
      urlField: 'image_url',
      role: shot.mode === 'firstLast'
        ? (imageIndex === 1 ? 'first_frame' : imageIndex === 2 ? 'last_frame' : 'reference_image')
        : 'reference_image',
      marker: `[Image ${imageIndex}]`,
    }
  })
}

function promptForSeedance(prompt, descriptors) {
  const markers = new Map(descriptors.map(item => [String(item.asset?.id || '').toLowerCase(), item.marker]))
  const tokenPattern = /[{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2}/g
  return String(prompt || '').replace(tokenPattern, (token, id) => markers.get(String(id).toLowerCase()) || token)
}

function orderSeedanceContent(shot, mediaContent, textContent) {
  return shot.mode === 'firstLast' ? [textContent, ...mediaContent] : [...mediaContent, textContent]
}

function originalDoubaoSendPreview(shot) {
  const allReferences = sendAttachments(shot).filter(asset => assetUrl(asset))
  const references = allReferences.filter(asset => !isAudioAsset(asset))
  const omittedAudio = allReferences.filter(asset => isAudioAsset(asset))
  const attachments = references.map((asset, index) => {
    const name = `${isAudioAsset(asset) ? '文件' : '图'}${index + 1}`
    return `${name} ← ${asset.name || asset.id || '未命名素材'}`
  })
  return [
    '【发送方式】OriginalDoubao 桌面会话',
    `【附件】${attachments.length ? `\n${attachments.join('\n')}` : '无'}`,
    `【过滤规则】音频附件不发送${omittedAudio.length ? `（已过滤 ${omittedAudio.length} 个）` : ''}`,
    `【实际文本】\n${promptForOriginalDoubao(shot.prompt, references, omittedAudio).trim()}`,
    `【生成设置】\n模型：${props.videoModel || '默认'}\n比例：${shot.ratio === '智能' ? '16:9' : shot.ratio}\n时长：${shot.duration}s\n清晰度：${shot.quality}\n声音：${shot.sound ? '开启' : '关闭'}`,
  ].join('\n\n')
}

function seedanceSendPreview(shot) {
  const references = sendAttachments(shot).filter(asset => assetUrl(asset))
  const descriptors = seedanceReferenceDescriptors(shot, references)
  const mediaContent = descriptors.map((item) => ({
    type: item.type,
    [item.urlField]: { url: `data:${item.type === 'audio_url' ? 'audio' : 'image'}/*;base64,<${item.asset.name || item.asset.id || '本地素材'} 内容已省略>` },
    role: item.role,
  }))
  const textContent = { type: 'text', text: promptForSeedance(shot.prompt, descriptors).trim() }
  return JSON.stringify({
    model: shot.seedanceModel || defaultSeedanceModel.value || '',
    content: orderSeedanceContent(shot, mediaContent, textContent),
    generate_audio: Boolean(shot.sound),
    ratio: shot.ratio === '智能' ? '16:9' : shot.ratio,
    resolution: String(shot.quality || defaultVideoSettings.quality).toLowerCase(),
    duration: Number(shot.duration || 5),
    return_last_frame: true,
    watermark: false,
  }, null, 2)
}

function sendPreviewText(shot) {
  return shot.generationEngine === 'seedance' ? seedanceSendPreview(shot) : originalDoubaoSendPreview(shot)
}

function sendPreviewSummary(shot) {
  const references = sendAttachments(shot).filter(asset => assetUrl(asset))
  if (shot.generationEngine === 'seedance') {
    return `${references.length} 个媒体内容 · 图片和音频均发送`
  }
  const imageCount = references.filter(asset => !isAudioAsset(asset)).length
  const audioCount = references.length - imageCount
  return `${imageCount} 个图片附件${audioCount ? ` · 已过滤 ${audioCount} 个音频` : ''}`
}

async function uploadLocalReference(shot) {
  if (!window.pywebview?.api) {
    shot.generationError = '请从桌面客户端选择本地图片'
    return
  }
  try {
    const selected = await window.pywebview.api.select_local_reference_file()
    if (!selected) return
    const mediaType = String(selected.mediaType || selected.type || '').toLowerCase() === 'audio' ? 'audio' : 'image'
    const imageIndex = shot.references.filter(asset => !isAudioAsset(asset)).length + 1
    const audioIndex = shot.references.filter(isAudioAsset).length + 1
    const id = `LOCAL-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const asset = {
      id,
      name: mediaType === 'audio' ? `音${audioIndex}` : `图${imageIndex}`,
      category: mediaType === 'audio' ? 'audio' : 'local',
      type: mediaType,
      path: selected.path,
      cover: selected.preview || '',
      uploading: true,
      generationError: '',
    }
    shot.references.push(asset)
    shot.referenceLabels[id] = asset.name
    shot.referencesExpanded = true
    try {
      // 加 60 秒超时兜底：防止 Python 端卡死导致 uploading 永远为 true
      const uploadPromise = window.pywebview.api.upload_local_reference_file(props.token, selected.path, {
        imageName: `图${imageIndex}`,
        audioName: `音${audioIndex}`,
        description: '视频生成任务本地上传参考素材',
        tags: 'video-reference',
        boundProjectIds: activeLinkedProjectId() ? [activeLinkedProjectId()] : [],
      })
      const timeoutPromise = new Promise((_, reject) =>
        window.setTimeout(() => reject(new Error('上传超时（60秒），请检查网络或后端服务')), 60000)
      )
      const uploaded = await Promise.race([uploadPromise, timeoutPromise])
      const uploadedId = String(uploaded?.id || id)
      const fileId = String(uploaded?.coverId || uploaded?.fileId || '')
      if (uploadedId !== id) {
        delete shot.referenceLabels[id]
        asset.id = uploadedId
        shot.referenceLabels[uploadedId] = asset.name
      }
      asset.coverId = fileId
      asset.fileId = fileId
      asset.generationError = ''
    } catch (uploadError) {
      asset.generationError = cleanError(uploadError)
      shot.generationError = `“${asset.name}”上传失败：${asset.generationError}`
    } finally {
      // finally 确保 uploading 必定清除，无论成功/失败/超时
      asset.uploading = false
    }
  } catch (err) {
    shot.generationError = cleanError(err)
  }
}

function removeReference(shot, assetId) {
  shot.references = shot.references.filter(item => String(item.id) !== String(assetId))
  delete shot.referenceLabels[String(assetId)]
  const lines = shot.prompt.split('\n')
  const lineIndex = lines.findIndex(line => /^一致性引用[：:]/.test(line.trim()))
  if (lineIndex >= 0) {
    const references = lines[lineIndex]
      .replace(/^一致性引用[：:]\s*/, '')
      .split(/[，,]/)
      .map(item => item.trim())
      .filter(item => item && !item.includes(`{{${assetId}}}`))
    if (references.length) lines[lineIndex] = `一致性引用：${references.join('，')}`
    else lines.splice(lineIndex, 1)
    shot.prompt = lines.join('\n').replace(/^\n+/, '')
  }
}

function stackSlot(index, total) {
  return Math.max(0, Math.min(2, index + 3 - total))
}

function modeLabel(shot) {
  return generationModes.find(item => item.value === shot.mode)?.label || '参考生成'
}

function toggleModeMenu(shot) {
  storyboards.value.forEach(item => { if (item.id !== shot.id) { item.modeOpen = false; item.settingsOpen = false } })
  shot.modeOpen = !shot.modeOpen
  shot.settingsOpen = false
}

async function toggleSettings(shot, event) {
  storyboards.value.forEach(item => { if (item.id !== shot.id) { item.modeOpen = false; item.settingsOpen = false } })
  shot.settingsOpen = !shot.settingsOpen
  shot.modeOpen = false
  if (!shot.settingsOpen) {
    shot.settingsPopoverStyle = null
    return
  }
  const trigger = event?.currentTarget
  await nextTick()
  const popover = document.querySelector(`[data-settings-shot="${CSS.escape(String(shot.id))}"]`)
  if (!trigger || !popover) return
  const margin = 12
  const triggerRect = trigger.getBoundingClientRect()
  const contentRect = trigger.closest('.shot-content')?.getBoundingClientRect() || triggerRect
  const width = Math.max(280, Math.min(520, contentRect.width - 24, window.innerWidth - margin * 2))
  const spaceAbove = triggerRect.top - margin
  const spaceBelow = window.innerHeight - triggerRect.bottom - margin
  const openAbove = spaceAbove >= Math.min(320, popover.scrollHeight) || spaceAbove >= spaceBelow
  const availableHeight = Math.max(160, Math.min(420, (openAbove ? spaceAbove : spaceBelow) - 8))
  const renderedHeight = Math.min(popover.scrollHeight, availableHeight)
  const left = Math.max(margin, Math.min(contentRect.left + 12, window.innerWidth - width - margin))
  const top = openAbove
    ? Math.max(margin, triggerRect.top - renderedHeight - 8)
    : Math.min(window.innerHeight - renderedHeight - margin, triggerRect.bottom + 8)
  shot.settingsPopoverStyle = {
    position: 'fixed',
    top: `${Math.round(top)}px`,
    bottom: 'auto',
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.round(availableHeight)}px`,
  }
}

function selectMode(shot, mode) {
  shot.mode = mode
  shot.modeOpen = false
}

function closeAllPopovers() {
  assetActionsOpen.value = false
  assetActionsPinned.value = false
  storyboards.value.forEach(shot => {
    shot.modeOpen = false
    shot.settingsOpen = false
  })
}

function handlePopoverKeydown(event) {
  if (event.key === 'Escape') {
    closeAllPopovers()
    storyboards.value.forEach(shot => {
      shot.expanded = false
      shot.sendPreview = false
      shot.playerExpanded = false
    })
    if (importDialogOpen.value) closeImportDialog()
    if (assetDetailOpen.value) closeAssetDetail()
  }
}

function toggleShotExpanded(shot) {
  closeAllPopovers()
  storyboards.value.forEach(item => {
    if (item.id !== shot.id) {
      item.expanded = false
      item.sendPreview = false
    }
  })
  shot.expanded = !shot.expanded
  if (!shot.expanded) shot.sendPreview = false
}

async function togglePlayerExpanded(shot) {
  const player = document.querySelector(`[data-result-player="${shot.id}"]`)
  if (!player) return
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else if (player.requestFullscreen) await player.requestFullscreen()
  } catch (err) {
    error.value = `无法切换全屏播放：${cleanError(err)}`
  }
}

function resultVideoElement(shot) {
  return document.querySelector(`[data-result-video="${shot.id}"]`)
}

async function toggleResultVideo(shot) {
  const video = resultVideoElement(shot)
  if (!video) return
  if (video.paused) {
    try { await video.play() } catch (err) { error.value = `无法播放视频：${cleanError(err)}` }
  } else video.pause()
}

function syncResultVideoMetadata(shot, event) {
  shot.videoDuration = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0
}

function syncResultVideoTime(shot, event) {
  shot.videoCurrent = Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0
}

function seekResultVideo(shot, event) {
  const video = resultVideoElement(shot)
  if (!video) return
  video.currentTime = Number(event.currentTarget.value) || 0
  shot.videoCurrent = video.currentTime
}

function toggleResultVideoMute(shot) {
  const video = resultVideoElement(shot)
  if (!video) return
  video.muted = !video.muted
  shot.videoMuted = video.muted
}

function syncPlayerFullscreenState() {
  const activePlayerId = document.fullscreenElement?.dataset?.resultPlayer || ''
  storyboards.value.forEach(shot => {
    shot.playerExpanded = shot.id === activePlayerId
  })
}

async function replaceShotVideo(shot) {
  if (shot.replacingVideo || shotRunning(shot)) return
  if (!window.pywebview?.api) {
    shot.videoReplaceError = '请从桌面客户端选择本地视频'
    return
  }
  shot.replacingVideo = true
  shot.videoReplaceError = ''
  try {
    const selected = await window.pywebview.api.select_local_video_file()
    if (!selected?.path) return
    const uploaded = await window.pywebview.api.upload_local_file(props.token, selected.path)
    const fileId = String(uploaded?.id || '')
    if (!fileId) throw new Error('视频入库没有返回文件 ID')

    stopPolling(shot.id)
    shot.taskId = ''
    shot.resultPath = ''
    shot.resultFileId = fileId
    shot.resultUrl = fileDownloadUrl(fileId)
    shot.resultWatermarked = false
    shot.status = 'succeeded'
    shot.statusText = `已使用本地视频替换：${selected.name || '本地视频'}`
    shot.progress = 100
    shot.generationError = ''
    shot.videoPlaying = false
    shot.videoCurrent = 0
    shot.videoDuration = 0
    await nextTick()
    await saveActiveVideoProject()
  } catch (err) {
    shot.videoReplaceError = cleanError(err)
  } finally {
    shot.replacingVideo = false
  }
}

function addStoryboard() {
  const shot = createStoryboard(storyboards.value.length + 1)
  storyboards.value.push(shot)
  activeShotId.value = shot.id
  nextTick(() => jumpToStoryboardAnchor(shot))
}

function removeStoryboard(shotId) {
  if (storyboards.value.length === 1) return
  stopPolling(shotId)
  storyboards.value = storyboards.value.filter(item => item.id !== shotId)
  if (activeShotId.value === shotId) activeShotId.value = storyboards.value[0].id
  nextTick(scheduleVisibleStoryboardAnchorUpdate)
}

function shotRunning(shot) {
  const status = String(shot.status || '').toLowerCase()
  const activeStatuses = ['preparing', 'submitting', 'queued', 'pending', 'generating', 'processing', 'running']
  return Boolean(activeStatuses.includes(status) || (shot.taskId && !['succeeded', 'failed', 'cancelled', 'canceled'].includes(status)))
}

function stopPolling(shotId) {
  const timer = pollTimers.get(shotId)
  if (timer) window.clearTimeout(timer)
  pollTimers.delete(shotId)
}

async function pollShot(shot) {
  try {
    const latest = await window.pywebview.api.get_task(shot.taskId)
    if (latest) {
      shot.status = latest.status || ''
      shot.statusText = latest.statusText || ''
      shot.progress = Number(latest.progress || 0)
      shot.accountId = String(latest.accountId || shot.accountId || '')
      shot.conversationId = String(latest.conversationId || shot.conversationId || '')
      shot.conversationUrl = String(latest.conversationUrl || shot.conversationUrl || '')
      shot.generationSubmittedAt = Number(latest.generationSubmittedAt || shot.generationSubmittedAt || 0)
      shot.requiresManualVerification = Boolean(latest.requiresManualVerification)
      if (latest.resultFileId) {
        shot.resultFileId = String(latest.resultFileId)
        shot.resultUrl = fileDownloadUrl(shot.resultFileId)
      } else {
        shot.resultUrl = latest.resultUrl || ''
      }
      shot.resultPath = latest.resultPath || ''
      shot.resultWatermarked = Boolean(latest.resultWatermarked)
      if (latest.status === 'failed') shot.generationError = latest.statusText || '生成失败'
    }
    if (latest && ['succeeded', 'failed', 'cancelled', 'canceled'].includes(latest.status)) {
      if (latest.status === 'succeeded' && shot.resultFileId) {
        shot.statusText = latest.statusText || (shot.resultWatermarked
          ? '无水印解析失败，已将有水印视频保存到当前任务'
          : '视频已生成并保存到当前任务')
        await saveActiveVideoProject()
      } else if (latest.status === 'succeeded' && shot.resultPath) {
        // 兜底：worker 已生成但未入库时，由前端补一次上传。
        // 后端 _apply_task_result 会随后把结果回写到业务数据。
        shot.statusText = '视频生成完成，正在上传入库'
        try {
          const uploaded = await window.pywebview.api.upload_local_file(props.token, shot.resultPath)
          shot.resultFileId = String(uploaded?.id || '')
          if (!shot.resultFileId) throw new Error('视频入库没有返回文件 ID')
          shot.resultUrl = fileDownloadUrl(shot.resultFileId)
          shot.statusText = '视频已生成并保存到当前任务'
          await saveActiveVideoProject()
        } catch (uploadError) {
          shot.generationError = `视频已生成，但入库失败：${cleanError(uploadError)}`
        }
      }
      stopPolling(shot.id)
      refreshTasks(String(activeVideoProject.value?.id || ''))
      return
    }
    const timer = window.setTimeout(() => pollShot(shot), 700)
    pollTimers.set(shot.id, timer)
  } catch (err) {
    shot.generationError = cleanError(err)
    shot.status = 'failed'
    stopPolling(shot.id)
    await saveActiveVideoProject()
  }
}

function generationEngineLabel(shot) {
  if (shot.generationEngine !== 'seedance') return 'doubao'
  return seedanceModelOptions.value.find(option => option.value === shot.seedanceModel)?.label || 'Seedance'
}

const ORIGINAL_DOUBAO_LOCKED_DURATION = 10
const ORIGINAL_DOUBAO_LOCKED_COUNT = 1

function applyOriginalDoubaoLockedSettings(shot) {
  shot.durationMode = 'seconds'
  shot.duration = ORIGINAL_DOUBAO_LOCKED_DURATION
  shot.count = ORIGINAL_DOUBAO_LOCKED_COUNT
}

function isOriginalDoubaoEngine(shot) {
  return shot.generationEngine !== 'seedance'
}

function selectGenerationEngine(shot, engine) {
  shot.generationEngine = engine
  if (engine === 'seedance' && !shot.seedanceModel) {
    shot.seedanceModel = defaultSeedanceModel.value
  }
  if (isOriginalDoubaoEngine(shot)) {
    applyOriginalDoubaoLockedSettings(shot)
  }
}

function allStoryboardsUseEngine(engine) {
  return Boolean(storyboards.value.length && storyboards.value.every(shot => shot.generationEngine === engine))
}

function canSwitchAllStoryboardEngines() {
  return !storyboards.value.some(shot => shotRunning(shot))
}

function setAllStoryboardEngines(engine) {
  if (!canSwitchAllStoryboardEngines()) return
  storyboards.value.forEach(shot => selectGenerationEngine(shot, engine))
}

async function pollSeedanceShot(shot) {
  const taskId = String(shot.taskId || '')
  const modelId = String(shot.seedanceModel || '')
  if (!taskId || !modelId || shot.generationEngine !== 'seedance') return
  const taskCreatedAt = Number(shot.seedanceTaskCreatedAt || 0)
  if (taskCreatedAt && Date.now() - taskCreatedAt >= 60 * 60 * 1000) {
    shot.status = 'failed'
    shot.statusText = 'Seedance 任务等待超过 1 小时，请重新生成'
    shot.generationError = shot.statusText
    shot.seedanceTaskId = ''
    shot.seedanceTaskCreatedAt = 0
    stopPolling(shot.id)
    await saveActiveVideoProject()
    return
  }
  try {
    const data = await window.pywebview.api.backend_request(
      'GET',
      `/ai/video/${encodeURIComponent(taskId)}?model=${encodeURIComponent(modelId)}`,
      props.token,
      null,
    )
    const status = String(data?.status || data?.state || '').toLowerCase()
    if (['succeeded', 'completed', 'done'].includes(status)) {
      const videoUrl = String(data?.video_url || data?.content?.video_url || '')
      if (!videoUrl) throw new Error('Seedance 生成完成但没有返回视频地址')
      shot.resultFileId = fileIdFromUrl(videoUrl)
      shot.resultUrl = absoluteMediaUrl(videoUrl)
      shot.resultPath = ''
      shot.resultWatermarked = false
      shot.seedanceLastFrameUrl = absoluteMediaUrl(data?.last_frame_url || data?.content?.last_frame_url || '')
      shot.status = 'succeeded'
      shot.statusText = 'Seedance 视频已生成并保存到本地'
      shot.progress = 100
      shot.seedanceTaskId = ''
      shot.seedanceTaskCreatedAt = 0
      shot.generationError = ''
      stopPolling(shot.id)
      await saveActiveVideoProject()
      return
    }
    if (['failed', 'error', 'cancelled', 'canceled', 'expired'].includes(status)) {
      const message = data?.error?.message || data?.message || `Seedance 任务${status}`
      shot.status = 'failed'
      shot.statusText = String(message)
      shot.generationError = String(message)
      shot.seedanceTaskId = ''
      shot.seedanceTaskCreatedAt = 0
      stopPolling(shot.id)
      await saveActiveVideoProject()
      return
    }
    shot.status = status || 'generating'
    shot.statusText = status === 'queued' ? 'Seedance 任务已提交，正在排队' : 'Seedance 正在生成视频'
    const remoteProgress = Number(data?.progress || 0)
    shot.progress = Math.min(94, Math.max(8, remoteProgress, Number(shot.progress || 0) + 2))
  } catch (err) {
    shot.statusText = `Seedance 状态查询失败，将自动重试：${cleanError(err)}`
  }
  const timer = window.setTimeout(() => pollSeedanceShot(shot), 5_000)
  pollTimers.set(shot.id, timer)
}

async function submitSeedanceShot(shot, attachments, availableReferences) {
  const modelId = String(shot.seedanceModel || defaultSeedanceModel.value || '')
  if (!modelId) throw new Error('请先选择 Seedance 视频模型')
  shot.seedanceModel = modelId
  shot.status = 'submitting'
  shot.statusText = '正在向 Seedance 提交视频任务'
  shot.progress = 6

  const descriptors = seedanceReferenceDescriptors(shot, availableReferences)
  const mediaContent = []
  for (const [index, attachment] of attachments.entries()) {
    const descriptor = descriptors[index]
    const encoded = await window.pywebview.api.read_local_media_data_url(attachment.path)
    mediaContent.push({
      type: descriptor.type,
      [descriptor.urlField]: { url: encoded.url },
      role: descriptor.role,
    })
  }
  const textContent = { type: 'text', text: promptForSeedance(shot.prompt, descriptors).trim() }
  const content = orderSeedanceContent(shot, mediaContent, textContent)

  const result = await window.pywebview.api.backend_request('POST', '/ai/video', props.token, {
    model: modelId,
    content,
    generate_audio: Boolean(shot.sound),
    ratio: shot.ratio === '智能' ? '16:9' : shot.ratio,
    resolution: String(shot.quality || defaultVideoSettings.quality).toLowerCase(),
    duration: Number(shot.duration || 5),
    return_last_frame: true,
    watermark: false,
  })
  const taskId = String(result?.taskId || result?.id || result?.task_id || '')
  if (!taskId) throw new Error('Seedance 未返回任务 ID')
  shot.taskId = taskId
  shot.seedanceTaskId = taskId
  shot.seedanceTaskCreatedAt = Date.now()
  shot.status = String(result?.status || 'queued')
  shot.statusText = 'Seedance 任务已提交，正在排队'
  shot.progress = 8
  await saveActiveVideoProject()
  await pollSeedanceShot(shot)
}

async function generateShot(shot) {
  if (shotRunning(shot)) return
  stopPolling(shot.id)
  shot.taskId = ''
  shot.seedanceTaskId = ''
  shot.seedanceTaskCreatedAt = 0
  shot.generationError = ''
  shot.resultUrl = ''
  shot.resultPath = ''
  shot.resultFileId = ''
  shot.resultWatermarked = false
  shot.conversationId = ''
  shot.conversationUrl = ''
  shot.generationSubmittedAt = 0
  if (!shot.prompt.trim()) {
    shot.generationError = '请先填写当前分镜的视频描述'
    return
  }
  if (shot.generationEngine === 'seedance' && !(shot.seedanceModel || defaultSeedanceModel.value)) {
    shot.generationError = '当前没有可用的 Seedance 视频模型，请先在后台配置模型'
    return
  }
  const resolvedReferences = sendAttachments(shot)
  const imageReferences = resolvedReferences.filter((asset) => {
    return !isAudioAsset(asset)
  })
  const audioReferences = resolvedReferences.filter((asset) => {
    return isAudioAsset(asset) && assetUrl(asset)
  })
  const unavailableImages = imageReferences.filter(asset => !assetUrl(asset))
  if (unavailableImages.length) {
    shot.generationError = `${unavailableImages.map(asset => asset.name || asset.id || '未命名图片').join('、')}还没有真实文件，请先上传或生成`
    return
  }
  if (!imageReferences.length) {
    shot.generationError = '请先从左侧添加人物、场景或道具图片'
    return
  }
  const imageAssets = imageReferences.map(resolveAssetReference)
  const audioAssets = audioReferences.map(resolveAssetReference)
  const missingAssets = imageAssets.filter(asset => !assetUrl(asset))
  if (missingAssets.length) {
    shot.generationError = `${missingAssets.map(asset => asset.name || asset.id || '未命名资产').join('、')}还没有图片，请先在左侧生成或上传`
    return
  }
  if (!window.pywebview?.api) {
    shot.generationError = '请从桌面客户端启动后再生成视频'
    return
  }
  try {
    shot.status = 'preparing'
    shot.statusText = `正在准备 ${imageAssets.length} 张参考图${audioAssets.length ? `和 ${audioAssets.length} 个音频文件` : ''}`
    shot.progress = 2
    const attachments = []
    const availableReferences = resolvedReferences.filter(asset => !isAudioAsset(asset) || assetUrl(asset))
    const generationReferences = shot.generationEngine === 'seedance'
      ? availableReferences
      : availableReferences.filter(asset => !isAudioAsset(asset))
    for (const [index, asset] of generationReferences.entries()) {
      const type = isAudioAsset(asset) ? 'audio' : 'image'
      const prepared = await window.pywebview.api.prepare_generation_asset(asset, props.token)
      attachments.push({ path: prepared.path, type, name: `${type === 'audio' ? '文件' : '图'}${index + 1}` })
    }
    const imagePaths = attachments.filter(item => item.type === 'image').map(item => item.path)
    const audioPaths = attachments.filter(item => item.type === 'audio').map(item => item.path)
    if (shot.generationEngine === 'seedance') {
      shot.accountId = ''
      await submitSeedanceShot(shot, attachments, generationReferences)
      return
    }
    const omittedAudioReferences = availableReferences.filter(asset => isAudioAsset(asset))
    applyOriginalDoubaoLockedSettings(shot)
    const originalDoubaoPrompt = promptForOriginalDoubao(shot.prompt, generationReferences, omittedAudioReferences)
    const result = await window.pywebview.api.start_generation({
      attachments,
      imagePaths,
      imagePath: imagePaths[0],
      audioPaths,
      prompt: originalDoubaoPrompt.trim(),
      ratio: shot.ratio === '智能' ? '16:9' : shot.ratio,
      duration: shot.duration,
      durationMode: shot.durationMode,
      quality: shot.quality,
      sound: shot.sound,
      count: shot.count,
      mode: shot.mode,
      model: props.videoModel,
      accountId: props.selectedAccountId,
      autoAssignAccount: true,
      token: props.token,
      persistResult: true,
      ownerType: 'videoShot',
      ownerId: String(shot.id || ''),
      projectId: String(activeVideoProject.value?.id || ''),
      taskName: `分镜 ${storyboards.value.indexOf(shot) + 1} 视频`,
      generationEngine: String(shot.generationEngine || ''),
    })
    shot.taskId = result.taskId
    shot.accountId = String(result.accountId || props.selectedAccountId || '')
    await saveActiveVideoProject()
    await pollShot(shot)
  } catch (err) {
    shot.status = 'failed'
    shot.generationError = cleanError(err)
    await saveActiveVideoProject()
  }
}

// 字符串签名监听：Vue 只 diff 字符串（O(1)），不遍历对象图
// 只提取需要持久化的字段，排除 generating/progress/uploading 等瞬态属性
// 既不卡顿，又能捕获内容编辑（分镜文本、设置变更、资产重命名等）
const projectSignature = computed(() => JSON.stringify({
  name: activeVideoProject.value?.name,
  projectId: activeVideoProject.value?.projectId,
  description: activeVideoProject.value?.description,
  assets: assets.value.map(a => ({
    id: a.id, name: a.name, description: a.description, tags: a.tags,
    type: a.type, category: a.category, coverId: a.coverId, fileId: a.fileId,
    boundProjectIds: a.boundProjectIds, prompt: a.prompt,
    useDefaultRoleLayout: a.useDefaultRoleLayout,
  })),
  storyboards: storyboards.value.map(s => ({
    id: s.id, title: s.title, prompt: s.prompt, ratio: s.ratio,
    duration: s.duration, durationMode: s.durationMode, mode: s.mode,
    generationEngine: s.generationEngine, seedanceModel: s.seedanceModel,
    count: s.count, quality: s.quality, sound: s.sound,
    references: (s.references || []).map(r => ({ id: r.id, name: r.name })),
    referenceLabels: s.referenceLabels,
  })),
}))
watch(projectSignature, () => {
  if (!hydratingProject) scheduleProjectSave()
})
watch(() => storyboards.value.map(shot => shot.id).join('|'), async () => {
  await nextTick()
  scheduleVisibleStoryboardAnchorUpdate()
})
watch(() => activeVideoProject.value?.name, scheduleProjectSave)
watch(() => activeVideoProject.value?.description, scheduleProjectSave)

onMounted(() => {
  loadGenerators()
  loadVideoProjects()
  loadAvailableProjects()
  // 定时刷新任务表，驱动"生成中 N"计数
  taskRefreshTimer = window.setInterval(() => refreshTasks(String(activeVideoProject.value?.id || '')), 2000)
  document.addEventListener('click', closeAllPopovers)
  document.addEventListener('keydown', handlePopoverKeydown)
  document.addEventListener('fullscreenchange', syncPlayerFullscreenState)
  window.addEventListener('resize', closeAllPopovers)
})
onBeforeUnmount(() => {
  pollTimers.forEach(timer => window.clearTimeout(timer))
  if (taskRefreshTimer) window.clearInterval(taskRefreshTimer)
  if (storyboardAnchorFrame) window.cancelAnimationFrame(storyboardAnchorFrame)
  if (projectSaveTimer) window.clearTimeout(projectSaveTimer)
  if (activeVideoProject.value?.id) saveActiveVideoProject()
  document.removeEventListener('click', closeAllPopovers)
  document.removeEventListener('keydown', handlePopoverKeydown)
  document.removeEventListener('fullscreenchange', syncPlayerFullscreenState)
  window.removeEventListener('resize', closeAllPopovers)
})
</script>

<template>
  <section v-if="!activeVideoProject" class="video-project-hub">
    <header class="video-project-workspace-head">
      <div class="video-project-head-copy"><span>VIDEO GENERATION WORKSPACE</span><div><h1>视频创作任务</h1><b>{{ videoProjects.length }} 个任务</b></div><p>管理资产、连续分镜与视频生成进度。</p></div>
      <div class="video-project-head-art" aria-hidden="true"><span class="video-project-hero-script"><i></i><i></i><i></i></span><span class="video-project-hero-shot video-project-hero-shot-top"></span><span class="video-project-hero-shot video-project-hero-shot-bottom"></span><svg viewBox="0 0 250 130"><path d="M90 65 C125 65 122 32 164 32M90 68 C125 68 122 98 164 98"/></svg></div>
      <div class="video-project-head-actions">
        <label class="video-project-search">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
          <input v-model="videoProjectKeyword" type="search" placeholder="搜索任务" aria-label="搜索任务" />
        </label>
        <button class="video-project-new-button" type="button" @click="videoProjectCreateOpen = true"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>新建任务</button>
      </div>
    </header>
    <div v-if="projectDetailLoading" class="video-project-detail-overlay" role="status" aria-live="polite">
      <BaseLoadingState size="lg" panel text="正在打开任务…" description="加载资产与分镜数据" />
    </div>
    <p v-if="projectError" class="video-project-error">{{ projectError }}</p>
    <section class="video-project-library">
      <header><div><span>CREATION TASKS</span><h2>全部任务</h2></div><b>{{ videoProjects.length }}</b></header>
      <div v-if="projectListLoading" class="video-project-grid" role="status" aria-live="polite" aria-label="正在加载任务列表">
        <article v-for="n in 6" :key="`video-project-skeleton-${n}`" class="video-project-card video-project-card-skeleton" aria-hidden="true">
          <div class="video-project-card-body">
            <header class="video-project-skeleton-header"><i></i><i></i></header>
            <i class="video-project-skeleton-title"></i>
            <i class="video-project-skeleton-desc"></i>
            <div class="video-project-card-stats"><span><i></i><i></i></span><span><i></i><i></i></span><span><i></i><i></i></span></div>
            <footer><i class="video-project-skeleton-time"></i><i class="video-project-skeleton-cta"></i></footer>
          </div>
        </article>
      </div>
      <div v-else-if="videoProjects.length" class="video-project-grid">
        <article v-if="!videoProjectKeyword.trim()" class="video-project-create-card"><button type="button" @click="videoProjectCreateOpen = true"><span class="video-project-new-visual" aria-hidden="true"><span class="video-project-new-script"><i></i><i></i><i></i></span><span class="video-project-new-frame"><i></i><b></b></span><span class="video-project-new-plus"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></span></span><strong>开始创作</strong></button><div><svg viewBox="0 0 18 18"><path d="M3 6.5v5M6 4.5v9M9 7v4M12 5.5v7M15 3.5v11"/></svg><span>doubao Studio</span></div></article>
        <article v-for="project in filteredVideoProjectCards" :key="project.id" class="video-project-card" tabindex="0" @click="openVideoProject(project)" @keydown.enter.self="openVideoProject(project)">
          <div class="video-project-card-body">
            <header><span>CREATION TASK</span><span class="video-project-card-head-actions"><button class="video-project-delete-button" type="button" :disabled="Boolean(deletingProjectId)" :aria-label="`删除任务 ${project.name || '未命名任务'}`" data-tooltip="删除任务" @click.stop="requestDeleteVideoProject(project)" @keydown.stop><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></button><svg class="video-project-open-arrow" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 10h10m-4-4 4 4-4 4"/></svg></span></header>
            <h2>{{ project.name || '未命名任务' }}</h2>
            <p>{{ project.description || '暂未添加任务描述' }}</p>
            <span class="video-project-link-pill"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 12.5 12.5 7.5M6 9l-1.5 1.5a3 3 0 0 0 4.2 4.2l1.5-1.5M14 11l1.5-1.5a3 3 0 0 0-4.2-4.2L9.8 6.8"/></svg>{{ linkedProjectName(project.projectId) }}</span>
            <div class="video-project-card-stats">
              <div class="stat-pills">
                <span class="stat-pill stat-pill-asset"><i class="stat-dot"></i><b>{{ project.assetCount || 0 }}</b><small>资产</small></span>
                <span class="stat-pill stat-pill-shot"><i class="stat-dot"></i><b>{{ project.storyboardCount || 0 }}</b><small>分镜</small></span>
                <span v-if="project.runningCount" class="stat-pill stat-pill-running"><i class="stat-dot"></i><b>{{ project.runningCount }}</b><small>生成中</small></span>
              </div>
              <button type="button" class="video-project-finished-stat" :aria-label="`查看 ${project.name || '任务'} 的 ${project.completedCount || 0} 个成片`" @click.stop="openProjectFinishedPreview(project)" @keydown.stop>
                <i class="video-project-finished-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 7 8 5-8 5z"/></svg></i>
                <span class="video-project-finished-copy"><small>{{ project.completedCount || 0 }} 视频</small></span>
                <svg class="video-project-finished-arrow" viewBox="0 0 20 20" aria-hidden="true"><path d="m8 6 4 4-4 4"/></svg>
              </button>
            </div>
            <footer><time>更新于 {{ project.updateTime ? String(project.updateTime).replace('T', ' ').slice(0, 16) : '--' }}</time><span>继续创作</span></footer>
          </div>
        </article>
      </div>
      <div v-else-if="videoProjectKeyword.trim()" class="video-project-empty"><strong>没有匹配的任务</strong><span>试试其他关键词，或清空搜索重新查看全部任务。</span></div>
      <div v-else class="video-project-empty"><strong>还没有创作任务</strong><span>点击“新建任务”，开始你的第一个故事。</span></div>
    </section>
    <div v-if="videoProjectCreateOpen" class="video-project-create-backdrop" @click.self="videoProjectCreateOpen = false">
      <form class="video-project-create" @submit.prevent="createVideoProject">
        <div class="video-project-create-head"><span>＋</span><div><strong>新建创作任务</strong><small>创建后可导入完整 JSON 资产与分镜</small></div><button type="button" aria-label="关闭" @click="videoProjectCreateOpen = false">×</button></div>
        <label><span>任务名称</span><input v-model="newProjectName" placeholder="例如：末日 Online" maxlength="256" autocomplete="off" /></label>
        <label class="video-project-link-field"><span>关联项目 <small>选填 · 可稍后在工作台绑定</small></span><UiSelect v-model="newProjectId" :options="projectLinkOptions" :placeholder="availableProjects.length ? '不关联项目' : '暂无项目'" badge="PROJECT" /></label>
        <label><span>任务描述 <small>选填</small></span><textarea v-model="newProjectDescription" placeholder="简单描述故事主题或创作方向" maxlength="512" rows="3"></textarea></label>
        <p v-if="projectError" class="video-project-form-error">{{ projectError }}</p>
        <footer><button type="button" @click="videoProjectCreateOpen = false">取消</button><button type="submit" :disabled="projectCreating">{{ projectCreating ? '正在创建…' : '创建并进入工作台' }}</button></footer>
      </form>
    </div>
    <div v-if="projectToDelete" class="video-project-create-backdrop" @click.self="cancelDeleteVideoProject">
      <section class="video-project-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="video-project-delete-title" aria-describedby="video-project-delete-description">
        <span class="video-project-delete-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></span>
        <div><small>DELETE TASK</small><h2 id="video-project-delete-title">删除创作任务？</h2><p id="video-project-delete-description">任务 <strong>{{ projectToDelete.name || '未命名任务' }}</strong> 的资产配置和分镜记录将被删除，此操作不可撤销。</p></div>
        <footer><button type="button" :disabled="Boolean(deletingProjectId)" @click="cancelDeleteVideoProject">取消</button><button class="danger" type="button" :disabled="Boolean(deletingProjectId)" autofocus @click="confirmDeleteVideoProject">{{ deletingProjectId ? '正在删除…' : '确认删除' }}</button></footer>
      </section>
    </div>
  </section>

  <section v-else class="video-workbench">
    <header class="video-workbench-head">
      <button class="workbench-back" type="button" @click="backToVideoProjects"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14.5 6-6 6 6 6"/></svg>返回</button>
      <div class="video-workbench-title">
        <input v-model="activeVideoProject.name" class="workbench-project-name" aria-label="任务名称" />
        <div class="workbench-meta">
          <span>{{ assets.length }} 项资产</span><span>{{ storyboards.length }} 个分镜</span>
          <label class="workbench-project-link" aria-label="关联项目"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 12.5 12.5 7.5M6 9l-1.5 1.5a3 3 0 0 0 4.2 4.2l1.5-1.5M14 11l1.5-1.5a3 3 0 0 0-4.2-4.2L9.8 6.8"/></svg><UiSelect v-model="activeVideoProject.projectId" :options="projectLinkOptions" :placeholder="availableProjects.length ? '关联项目' : '暂无项目'" :disabled="!availableProjects.length" /></label>
          <input v-model="activeVideoProject.description" class="video-project-description" aria-label="任务描述" placeholder="添加任务描述…" />
          <span>OriginalDoubao / Seedance</span>
        </div>
      </div>
      <div class="workbench-head-actions">
        <span class="workbench-save-status" :class="projectSaveTone" :data-tooltip="projectSaveStatus || '任务修改会自动保存到数据库'"><i></i>{{ projectSaveLabel }}</span>
        <button class="workbench-add-shot" type="button" @click="addStoryboard"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span>新增分镜</span></button>
      </div>
    </header>

    <div class="video-workbench-layout">
      <aside class="asset-rail">
        <div class="asset-rail-head">
          <div><h2>资产数据</h2><span>JSON ASSETS</span></div>
          <div class="asset-rail-head-actions">
            <b>{{ displayedAssets.length }}</b>
            <div class="asset-actions-wrap" @mouseenter="showAssetActions" @mouseleave="hideAssetActions">
              <button type="button" class="asset-actions-trigger" :class="{ active: assetActionsOpen }" :aria-expanded="assetActionsOpen" aria-label="操作" data-tooltip="操作" @click.stop="toggleAssetActions">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/></svg>
              </button>
              <section v-if="assetActionsOpen" class="asset-actions-popover" aria-label="操作菜单" @click.stop>
                <header><div><strong>操作</strong><small>导入、模型与批量任务</small></div><span>{{ displayedAssets.filter(asset => !assetUrl(asset)).length }} 项待生成</span></header>
                <button class="asset-action-import" type="button" @click="openImportDialog">
                  <span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v4h14v-4"/></svg></span>
                  <div><strong>{{ importedFileName ? '重新导入创作数据' : '导入创作数据 JSON' }}</strong><small>{{ importedSummary }}</small></div>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
                </button>
                <label class="asset-action-model"><span>图片生成模型</span><UiSelect v-model="selectedImageModel" :options="imageModelOptions" :placeholder="loading ? '正在加载模型…' : '选择图片模型'" :disabled="loading || !imageModels.length" status badge="IMAGE" /></label>
                <fieldset class="asset-action-video-engine"><legend>视频模型切换</legend><small>一键应用到全部 {{ storyboards.length }} 个分镜</small><div><button v-for="engine in generationEngineOptions" :key="engine.value" type="button" :class="{ active: allStoryboardsUseEngine(engine.value) }" :disabled="!canSwitchAllStoryboardEngines() || (engine.value === 'seedance' && !seedanceModelOptions.length)" @click="setAllStoryboardEngines(engine.value)">{{ engine.label }}</button></div><em v-if="!canSwitchAllStoryboardEngines()">有分镜正在生成，完成后可切换</em></fieldset>
                <button class="asset-action-generate-all" type="button" :disabled="bulkGenerating || assetLibrarySyncing || !displayedAssets.length" @click="generateAllMissingAssets">
                  <span v-if="bulkGenerating" class="asset-generate-spinner"></span>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/><path d="m18 15 .8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15Z"/></svg>
                  <div><strong>{{ bulkGenerating ? '正在批量生成' : '一键生成全部' }}</strong><small>{{ activeCategory === 'all' ? '生成全部分类，自动跳过已有资产' : `仅生成当前「${categories.find(item => item.key === activeCategory)?.label || '分类'}」` }}</small></div>
                  <b>{{ displayedAssets.filter(asset => !assetUrl(asset)).length }}</b>
                </button>
                <div class="asset-action-library-grid">
                  <button type="button" :disabled="assetLibrarySyncing || bulkGenerating || !assets.length || !activeLinkedProjectId()" @click="syncAssetsToLibrary">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0-12L7.5 7.5M12 3l4.5 4.5M5 15v5h14v-5"/></svg>
                    <span><strong>同步到我的资产</strong><small>{{ activeLinkedProjectId() ? `自动绑定 · ${linkedProjectName()}` : '请先关联项目' }}</small></span>
                  </button>
                  <button type="button" :disabled="assetLibrarySyncing || bulkGenerating || !assets.length || !activeLinkedProjectId()" @click="restoreAssetsFromLibrary">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h11a5 5 0 0 1 0 10H9"/><path d="m8 4-4 4 4 4"/></svg>
                    <span><strong>从我的资产回显</strong><small>{{ activeLinkedProjectId() ? `仅匹配 · ${linkedProjectName()}` : '请先关联项目' }}</small></span>
                  </button>
                </div>
                <p v-if="assetLibraryStatus || bulkGenerationStatus || importError" :class="{ error: importError || bulkGenerationStatus === '请先选择图片模型' || assetLibraryStatus.includes('失败') }">{{ importError || assetLibraryStatus || bulkGenerationStatus }}</p>
              </section>
            </div>
          </div>
        </div>
        <nav class="asset-category-tabs" aria-label="资产分类">
          <button v-for="category in categories" :key="category.key" type="button" :class="{ active: activeCategory === category.key }" @click="activeCategory = category.key">
            <svg v-if="category.key === 'all'" viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg>
            <svg v-else-if="category.key === 'role'" viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-4.2 3.1-6.3 7-6.3s6.2 2.1 7 6.3"/></svg>
            <svg v-else-if="category.key === 'scene'" viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m5.5 17 4.3-4.2 3 3 2.5-2.5 3.2 3.7"/><circle cx="9" cy="9" r="1.4"/></svg>
            <svg v-else-if="category.key === 'prop'" viewBox="0 0 24 24"><path d="m7 17 10-10M14 5l5 5M5 14l5 5M4 20l3-3"/></svg>
            <svg v-else-if="category.key === 'layout'" viewBox="0 0 24 24"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></svg>
            <svg v-else viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg>
            <span>{{ category.label }}</span>
          </button>
        </nav>
        <div class="asset-rail-scroll">
          <p v-if="error" class="asset-rail-state error">{{ error }}</p>
          <div v-if="displayedAssets.length" class="asset-rail-grid">
            <article v-for="asset in displayedAssets" :key="asset.id" class="asset-pick-card" :class="{ missing: !assetUrl(asset), generating: asset.generating }">
              <button v-if="assetUrl(asset)" type="button" class="asset-preview-button" :data-tooltip="`查看和编辑 ${asset.name}`" @click="openAssetDetail(asset)">
                <img v-if="asset.type !== 'audio'" :src="assetUrl(asset)" :alt="asset.name" />
                <span v-else class="asset-audio-placeholder"><svg viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg></span>
              </button>
              <button v-else type="button" class="asset-missing-preview" :data-tooltip="`查看和编辑 ${asset.name}`" @click="openAssetDetail(asset)"><svg v-if="asset.category !== 'audio'" viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m6 17 4-4 3 3 2.5-2.5L19 17"/></svg><svg v-else viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg><span>{{ asset.category === 'audio' ? '暂无音频' : '暂无图片' }}</span></button>
              <span v-if="assetReferenceState(asset).total" class="asset-reference-count" :class="{ incomplete: assetReferenceState(asset).ready < assetReferenceState(asset).total }" :title="`${assetReferenceState(asset).ready}/${assetReferenceState(asset).total} 张参考图已就绪`"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="6" width="13" height="12" rx="2"/><path d="m7 15 3-3 2.5 2.5 2-2 2.5 2.5M8 6V4h12v11h-3"/></svg>{{ assetReferenceState(asset).ready }}/{{ assetReferenceState(asset).total }}</span>
              <div v-if="asset.generating && asset.category !== 'audio'" class="asset-image-generating" aria-live="polite" aria-label="正在生成图片"><i></i></div>
              <button type="button" class="asset-pick-copy"  @click="openAssetDetail(asset)"><strong>{{ asset.name }}</strong><small>{{ assetUrl(asset) ? (asset.duration || categories.find(item => item.key === asset.category)?.label || '资产') : `${categories.find(item => item.key === asset.category)?.label || '资产'} · 待生成` }}</small></button>
              <button v-if="!assetUrl(asset)" type="button" class="asset-card-generate" :disabled="asset.generating" :aria-label="asset.generating ? '正在生成资产' : asset.category === 'audio' ? '生成音频' : '生成图片'" @click="generateAsset(asset)"><span v-if="asset.generating" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/></svg><em>{{ asset.generating ? '生成中' : asset.category === 'audio' ? '生成音频' : '生成图片' }}</em></button>
              <button v-else type="button" class="asset-card-add" :aria-label="`添加 ${asset.name} 到当前分镜`" @click.stop="addReference(asset)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><em>添加到分镜</em></button>
              <p v-if="asset.generationError" class="asset-card-error" :data-tooltip="asset.generationError">{{ asset.generationError }}</p>
            </article>
          </div>
          <div v-else class="asset-rail-empty">
            <span class="asset-rail-empty-icon"><svg viewBox="0 0 64 48" aria-hidden="true"><path d="M7 40 23.4 17.5a3 3 0 0 1 4.9.1l8.1 11 5-6.4a3 3 0 0 1 4.8.1L57 40H7Z" /><circle cx="43" cy="14" r="5" /></svg></span>
            <strong>还没有资产数据</strong>
            <small>导入 JSON 文件或点击上方「上传资产」开始</small>
          </div>
        </div>
      </aside>

      <div class="storyboard-column-shell">
        <div class="storyboard-column-head"><div><h2>分镜</h2><span>STORYBOARDS</span></div><b>{{ storyboards.length }} 个分镜</b></div>
      <section ref="storyboardColumnRef" class="storyboard-column" :class="{ 'single-shot': storyboards.length === 1 }" @scroll.passive="scheduleVisibleStoryboardAnchorUpdate">

        <article v-for="(shot, shotIndex) in storyboards" :key="shot.id" :ref="element => setStoryboardCardRef(element, shot.id)" class="storyboard-card" :class="{ active: activeShotId === shot.id }" tabindex="0" @click="activeShotId = shot.id" @focusin="activeShotId = shot.id">
          <div class="shot-body-grid">
            <div class="shot-content" :class="{ expanded: shot.expanded }">
              <header class="storyboard-card-head">
                <span class="shot-number">{{ String(shotIndex + 1).padStart(2, '0') }}</span>
                <input v-model="shot.title" aria-label="分镜名称" />
                <button type="button" :disabled="storyboards.length === 1" aria-label="删除分镜" @click.stop="removeStoryboard(shot.id)">×</button>
              </header>
          <div class="storyboard-compose">
            <div class="reference-stack" :class="{ expanded: shot.referencesExpanded, 'has-references': shot.references.length }" :style="{ '--reference-expanded-width': `${Math.min(520, 78 + shot.references.length * 85)}px` }" @mouseenter="shot.references.length && (shot.referencesExpanded = true)" @mouseleave="shot.referencesExpanded = false">
              <button type="button" class="reference-add" data-tooltip="从本地上传图片或音频" @click.stop="uploadLocalReference(shot)"><span>＋</span><small>本地上传</small></button>
              <div v-for="(asset, index) in shot.references" :key="asset.id" class="reference-card" :class="{ 'stack-hidden': index < shot.references.length - 3 }" :style="{ '--stack-index': index, '--stack-x': `${stackSlot(index, shot.references.length) * 9}px`, '--stack-y': `${(2 - stackSlot(index, shot.references.length)) * -2}px`, '--stack-angle': `${(stackSlot(index, shot.references.length) - 2) * 4}deg` }">
                <img v-if="assetUrl(asset) && !isAudioAsset(asset) && !asset.previewFailed" :src="assetUrl(asset)" :alt="asset.name" data-tooltip="点击放大查看" @error="handleReferencePreviewError(asset)" @click.stop="openReferencePreview(asset)" />
                <span v-else><svg v-if="isAudioAsset(asset)" viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg><svg v-else viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m6 17 4-4 3 3 2.5-2.5L19 17"/></svg></span>
                <small>{{ asset.name }}</small>
                <em v-if="asset.uploading" class="reference-upload-state"><i></i>上传中</em>
                <em v-else-if="asset.generationError" class="reference-upload-state error" :data-tooltip="asset.generationError">上传失败</em>
                <button type="button" aria-label="移除参考资产" @click.stop="removeReference(shot, asset.id)">×</button>
              </div>
              <span v-if="shot.references.length && !shot.referencesExpanded" class="reference-stack-add">＋</span>
            </div>

            <StoryboardMentionEditor v-if="!shot.sendPreview" v-model="shot.prompt" class="storyboard-prompt-editor" :assets="mentionAssets(shot)" :labels="shot.referenceLabels" placeholder="描述分镜内容，输入 @ 选择已上传素材…" @select-asset="selectMentionAsset(shot, $event)" />
            <div v-else class="storyboard-send-preview" :class="`engine-${shot.generationEngine || 'doubao'}`" role="region" :aria-label="`实际发送给 ${generationEngineLabel(shot)} 的内容`"><header><svg viewBox="0 0 24 24"><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/></svg><strong>实际发送内容 · {{ generationEngineLabel(shot) }}</strong><span>{{ sendPreviewSummary(shot) }}</span></header><pre>{{ sendPreviewText(shot) }}</pre></div>
            <div class="shot-editor-actions">
              <button v-if="shot.expanded" class="shot-send-preview-toggle" :class="{ active: shot.sendPreview }" type="button" :aria-pressed="shot.sendPreview" :aria-label="shot.sendPreview ? '返回编辑内容' : '查看实际发送内容'" :data-tooltip="shot.sendPreview ? '返回编辑内容' : '查看实际发送内容'" @click.stop="shot.sendPreview = !shot.sendPreview"><svg v-if="!shot.sendPreview" viewBox="0 0 24 24"><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/></svg><svg v-else viewBox="0 0 24 24"><path d="m4 4 16 16M10.7 6.2A8 8 0 0 1 12 6c5.5 0 9 6 9 6a14 14 0 0 1-2.1 2.8M6.3 6.3C4.2 7.8 3 10 3 12c0 0 3.5 6 9 6a8 8 0 0 0 3.3-.7"/></svg></button>
              <button class="shot-expand" type="button" :aria-label="shot.expanded ? '退出分镜放大' : '放大分镜内容'" :data-tooltip="shot.expanded ? '退出放大' : '放大分镜内容'" @click.stop="toggleShotExpanded(shot)"><svg v-if="!shot.expanded" viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg><svg v-else viewBox="0 0 24 24"><path d="M3 8h5V3M21 8h-5V3M3 16h5v5M21 16h-5v5"/></svg></button>
            </div>
          </div>

          <footer class="storyboard-toolbar">
            <div class="toolbar-popover-wrap">
              <button type="button" :aria-expanded="shot.modeOpen" @click.stop="toggleModeMenu(shot)"><svg viewBox="0 0 24 24"><path d="M5 7h14v12H5zM8 4h8v3"/></svg>{{ modeLabel(shot) }}</button>
              <div v-if="shot.modeOpen" class="mode-popover" @click.stop>
                <label>选择模式</label>
                <button v-for="mode in generationModes" :key="mode.value" type="button" :class="{ active: shot.mode === mode.value }" @click="selectMode(shot, mode.value)">
                  <svg v-if="mode.value === 'reference'" viewBox="0 0 24 24"><path d="M5 7h14v12H5zM8 4h8v3"/></svg>
                  <svg v-else viewBox="0 0 24 24"><rect x="4" y="5" width="6" height="14"/><rect x="14" y="5" width="6" height="14"/></svg>
                  <span>{{ mode.label }}</span><b v-if="shot.mode === mode.value">✓</b>
                </button>
              </div>
            </div>
            <div class="toolbar-popover-wrap settings-wrap">
              <button type="button" class="settings-summary-btn" :aria-expanded="shot.settingsOpen" data-tooltip="视频设置" @click.stop="toggleSettings(shot, $event)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h18M3 12h18M3 17h18"/></svg><span>{{ generationEngineLabel(shot) }} · {{ shot.ratio }} · {{ shot.quality }} · {{ shot.durationMode === 'smart' ? '智能时长' : `${shot.duration}秒` }} · {{ shot.sound ? '有声' : '静音' }} · {{ shot.count }}条</span></button>
              <div v-if="shot.settingsOpen" class="settings-popover" :style="shot.settingsPopoverStyle" :data-settings-shot="shot.id" @click.stop>
                <fieldset class="settings-field-wide generation-model-field">
                  <legend>生成模型</legend>
                  <div class="generation-model-options" role="radiogroup" aria-label="选择视频生成模型">
                    <button type="button" class="generation-model-card" :class="{ active: shot.generationEngine !== 'seedance' }" :aria-pressed="shot.generationEngine !== 'seedance'" @click="selectGenerationEngine(shot, 'doubao')">
                      <span class="generation-model-icon doubao" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 6.5h14v9H9l-4 3v-12Z"/><path d="m15.5 3 .7 2.1 2.1.7-2.1.7-.7 2.1-.7-2.1-2.1-.7 2.1-.7.7-2.1Z"/></svg></span>
                      <span class="generation-model-copy"><strong>OriginalDoubao</strong><small>桌面会话 · 自动操作</small></span>
                      <em>WEB</em><i aria-hidden="true">✓</i>
                    </button>
                    <button type="button" class="generation-model-card" :class="{ active: shot.generationEngine === 'seedance' }" :aria-pressed="shot.generationEngine === 'seedance'" :disabled="!seedanceModelOptions.length" @click="selectGenerationEngine(shot, 'seedance')">
                      <span class="generation-model-icon seedance" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 17.5h10a4 4 0 0 0 .5-8A6 6 0 0 0 6.2 8.1 4.7 4.7 0 0 0 7 17.5Z"/><path d="m10 13 2-2 2 2M12 11v5"/></svg></span>
                      <span class="generation-model-copy"><strong>Seedance</strong><small>服务端接口 · 异步任务</small></span>
                      <em>API</em><i aria-hidden="true">✓</i>
                    </button>
                  </div>
                  <label v-if="shot.generationEngine === 'seedance'" class="seedance-model-select"><span>Seedance API 模型</span><UiSelect v-model="shot.seedanceModel" :options="seedanceModelOptions" :disabled="!seedanceModelOptions.length" :placeholder="seedanceModelOptions.length ? '选择具体模型' : '暂无可用模型'" status badge="API" /></label>
                </fieldset>
                <fieldset class="settings-field-wide"><legend>视频比例</legend><div class="ratio-options"><button v-for="ratioOption in videoRatios" :key="ratioOption" type="button" :class="{ active: shot.ratio === ratioOption }" @click="shot.ratio = ratioOption"><svg viewBox="0 0 24 24"><rect :x="ratioOption === '9:16' || ratioOption === '3:4' ? 8 : 5" :y="ratioOption === '9:16' || ratioOption === '3:4' ? 4 : 7" :width="ratioOption === '9:16' || ratioOption === '3:4' ? 8 : 14" :height="ratioOption === '9:16' || ratioOption === '3:4' ? 16 : 10" rx="1"/></svg><span>{{ ratioOption }}</span></button></div></fieldset>
                <fieldset><legend>分辨率</legend><div class="segmented-options four"><button v-for="qualityOption in videoQualities" :key="qualityOption" type="button" :class="{ active: shot.quality === qualityOption }" @click="shot.quality = qualityOption">{{ qualityOption }}</button></div></fieldset>
                <fieldset><legend>输出声音</legend><div class="segmented-options"><button type="button" :class="{ active: shot.sound }" @click="shot.sound = true">开</button><button type="button" :class="{ active: !shot.sound }" @click="shot.sound = false">关</button></div></fieldset>
                <fieldset class="settings-field-wide"><legend>视频时长</legend><div class="segmented-options"><button type="button" :disabled="isOriginalDoubaoEngine(shot)" :class="{ active: shot.durationMode === 'seconds' }" @click="shot.durationMode = 'seconds'">按秒数</button><button type="button" :disabled="isOriginalDoubaoEngine(shot)" :class="{ active: shot.durationMode === 'smart' }" @click="shot.durationMode = 'smart'">智能时长</button></div><div v-if="shot.durationMode === 'seconds'" class="duration-options"><button v-for="durationOption in videoDurations" :key="durationOption" type="button" :disabled="isOriginalDoubaoEngine(shot)" :class="{ active: shot.duration === durationOption }" @click="shot.duration = durationOption">{{ durationOption }}s</button></div></fieldset>
                <fieldset class="settings-field-wide"><legend>选择生成数量</legend><div class="count-options"><button v-for="countOption in generationCounts" :key="countOption" type="button" :disabled="isOriginalDoubaoEngine(shot)" :class="{ active: shot.count === countOption }" @click="shot.count = countOption">{{ countOption }}</button></div></fieldset>
              </div>
            </div>
            <button class="shot-clear" type="button" @click="shot.references = []; shot.prompt = ''">清空内容</button>
            <button class="shot-submit" type="button" :disabled="shotRunning(shot)" :aria-label="shotRunning(shot) ? '正在生成当前分镜' : '生成当前分镜'" @click.stop="generateShot(shot)"><span v-if="shotRunning(shot)" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24"><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/></svg><strong>{{ shotRunning(shot) ? '生成中' : '生成视频' }}</strong></button>
          </footer>
            </div>

          <section class="shot-result" :class="{ 'has-player': Boolean(shot.resultUrl) }" aria-label="分镜生成结果">
            <p v-if="shot.videoReplaceError" class="shot-result-replace-error">{{ shot.videoReplaceError }}</p>
            <div v-if="shot.resultUrl" class="shot-result-player" :data-result-player="shot.id">
              <video :key="shot.resultUrl" :ref="el => setVideoRef(shot, el)" :src="shot.resultUrl" playsinline preload="auto" @click.stop="toggleVideo(shot)" @play="shot.videoPlaying = true; verifyShotVideoFrame(shot, $event)" @pause="shot.videoPlaying = false" @ended="shot.videoPlaying = false; shot.videoCurrent = 0" @loadedmetadata="syncVideoMeta(shot, $event)" @loadeddata="ensureShotVideoRenderable(shot, $event)" @timeupdate="syncVideoTime(shot, $event)" @volumechange="shot.videoMuted = $event.currentTarget.muted" @error="handleShotVideoError(shot)"></video>
              <span v-if="shot.resultWatermarked" class="shot-result-watermark-badge">有水印</span>
              <button v-if="!shot.videoPlaying" type="button" class="shot-result-center-play" aria-label="播放" @click.stop="toggleVideo(shot)"><svg viewBox="0 0 24 24"><path d="m9 6 9 6-9 6V6Z"/></svg></button>
              <div class="shot-result-controls" @click.stop>
                <input type="range" min="0" :max="shot.videoDuration || 0" step="0.01" :value="shot.videoCurrent" :style="{ '--video-progress': `${shot.videoDuration ? (shot.videoCurrent / shot.videoDuration) * 100 : 0}%` }" aria-label="视频进度" @input="seekVideo(shot, $event)" />
                <div>
                  <button type="button" :aria-label="shot.videoPlaying ? '暂停' : '播放'" @click="toggleVideo(shot)"><svg v-if="shot.videoPlaying" viewBox="0 0 24 24"><path d="M8 6v12M16 6v12"/></svg><svg v-else viewBox="0 0 24 24"><path d="m9 6 9 6-9 6V6Z"/></svg></button>
                  <time>{{ fmtTime(shot.videoCurrent) }} <span>/ {{ fmtTime(shot.videoDuration) }}</span></time>
                  <button type="button" :aria-label="shot.videoMuted ? '开启声音' : '静音'" @click="toggleMute(shot)"><svg v-if="shot.videoMuted" viewBox="0 0 24 24"><path d="M5 10v4h3l4 3V7l-4 3H5M16 9l5 6M21 9l-5 6"/></svg><svg v-else viewBox="0 0 24 24"><path d="M5 10v4h3l4 3V7l-4 3H5M16 9.5a4 4 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10"/></svg></button>
                  <button type="button" class="shot-result-replace-control" :disabled="shot.replacingVideo" :aria-label="shot.replacingVideo ? '正在替换视频' : '使用本地视频替换'" data-tooltip="本地替换视频" data-tooltip-pos="top" @click="replaceShotVideo(shot)"><span v-if="shot.replacingVideo" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24"><path d="M4 7h10M11 4l3 3-3 3M20 17H10m3-3-3 3 3 3"/><rect x="4" y="12" width="4" height="8" rx="1"/><rect x="16" y="4" width="4" height="8" rx="1"/></svg></button>
                  <button type="button" class="shot-result-download-control" :disabled="shot.downloadingVideo" :aria-label="shot.downloadingVideo ? '正在下载视频' : '下载当前视频'" title="下载当前视频" data-tooltip="下载视频" data-tooltip-pos="top" @click.stop.prevent="downloadShotVideo(shot)"><span v-if="shot.downloadingVideo" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14"/></svg></button>
                  <button type="button" aria-label="放大播放" @click="openVideoPreview(shot)"><svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg></button>
                </div>
              </div>
            </div>
            <div v-else-if="shotRunning(shot)" class="shot-result-progress">
              <span class="result-spinner"></span>
              <div><strong>{{ shot.statusText || '正在生成视频' }}</strong><small>{{ shot.requiresManualVerification ? '请切换到 OriginalDoubao 浏览器手动点击确认' : '完成后将在这里直接显示并播放' }}</small></div>
              <b>{{ shot.progress }}%</b>
              <i><em :style="{ width: `${shot.progress}%` }"></em></i>
            </div>
            <div v-else-if="shot.generationError" class="shot-result-error">
              <strong>生成未完成</strong><span>{{ shot.generationError }}</span>
              <div class="shot-result-error-actions">
                <button type="button" @click.stop="generateShot(shot)">重新生成</button>
                <button type="button" :disabled="shot.replacingVideo" @click.stop="replaceShotVideo(shot)">{{ shot.replacingVideo ? '正在上传…' : '上传本地视频' }}</button>
              </div>
            </div>
            <div v-else-if="shot.status === 'succeeded'" class="shot-result-complete">
              <strong>视频生成完成</strong><span>{{ shot.statusText || '自动下载已关闭，暂时没有本地播放文件。' }}</span>
              <button class="shot-result-upload" type="button" :disabled="shot.replacingVideo" @click.stop="replaceShotVideo(shot)">{{ shot.replacingVideo ? '正在上传…' : '上传本地视频' }}</button>
            </div>
            <div v-else class="shot-result-empty">
              <span><svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="m10 9 5 3-5 3V9Z"/></svg></span>
              <div><strong>视频将在这里显示</strong><small>点击右上箭头生成当前分镜，完成后可直接播放</small></div>
              <button class="shot-result-upload" type="button" :disabled="shot.replacingVideo" aria-label="上传本地视频到当前分镜" @click.stop="replaceShotVideo(shot)">{{ shot.replacingVideo ? '正在上传…' : '上传本地视频' }}</button>
            </div>
          </section>
          </div>
        </article>
      </section>
      </div>
      <nav v-if="storyboards.length > 1" class="storyboard-anchor-nav" aria-label="分镜卡片快速定位">
        <button
          v-for="(shot, shotIndex) in storyboards"
          :key="`storyboard-anchor-${shot.id}`"
          type="button"
          :class="{ active: visibleStoryboardAnchorId === shot.id }"
          :aria-current="visibleStoryboardAnchorId === shot.id ? 'location' : undefined"
          :aria-label="`跳转到第 ${shotIndex + 1} 个分镜：${shot.title || '未命名分镜'}`"
          :data-tooltip="`${String(shotIndex + 1).padStart(2, '0')} · ${shot.title || '未命名分镜'}`"
          data-tooltip-pos="left"
          @click="jumpToStoryboardAnchor(shot)"
        ><i></i></button>
      </nav>
    </div>

    <div v-if="importDialogOpen" class="json-import-backdrop" role="presentation" @mousedown.self="closeImportDialog">
      <section class="json-import-dialog" role="dialog" aria-modal="true" aria-labelledby="json-import-title" @mousedown.stop>
        <header>
          <div><span>IMPORT CREATION DATA</span><h2 id="json-import-title">导入创作数据 JSON</h2><p>粘贴 JSON 文本，或直接选择本地 .json 文件。</p></div>
          <button type="button" aria-label="关闭导入窗口" @click="closeImportDialog">×</button>
        </header>
        <label class="json-import-editor">
          <span>JSON 文本</span>
          <textarea v-model="jsonText" class="json-import-textarea" spellcheck="false" placeholder="在这里粘贴完整 JSON 内容…"></textarea>
        </label>
        <p v-if="importError" class="json-import-error">{{ importError }}</p>
        <footer>
          <button class="json-file-button" type="button" @click="importAssetJson"><span>⇧</span><div><strong>选择 JSON 文件</strong><small>从电脑中选择 .json 文件</small></div></button>
          <button class="json-cancel-button" type="button" @click="closeImportDialog">取消</button>
          <button class="json-confirm-button" type="button" :disabled="!jsonText.trim()" @click="importJsonText">解析并导入</button>
        </footer>
      </section>
    </div>

    <div v-if="assetDetailOpen && assetDetailTarget" class="asset-detail-backdrop" role="presentation" @mousedown.self="closeAssetDetail">
      <section class="asset-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="asset-detail-title" @mousedown.stop>
        <header><div><span>ASSET DETAILS</span><h2 id="asset-detail-title">资产详情与编辑</h2><p>{{ assetDetailTarget.id }} · {{ categories.find(item => item.key === assetDetailTarget.category)?.label || '本地资产' }}</p></div><button type="button" aria-label="关闭资产详情" @click="closeAssetDetail">×</button></header>
        <div class="asset-detail-body">
          <div class="asset-detail-preview">
            <button v-if="assetUrl(assetDetailTarget) && assetDetailTarget.type !== 'audio'" class="asset-detail-image-preview" :class="{ 'is-generating': assetDetailTarget.generating }" type="button" :aria-label="`放大查看 ${assetDetailTarget.name || '资产图片'}`" @click="openReferencePreview(assetDetailTarget)">
              <img :src="assetUrl(assetDetailTarget)" :alt="assetDetailTarget.name" />
              <span class="asset-detail-zoom-hint" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4M11 8v6M8 11h6"/></svg>点击放大</span>
            </button>
            <div v-else-if="assetUrl(assetDetailTarget)" class="asset-detail-audio-player">
              <audio ref="audioPreview" :src="assetUrl(assetDetailTarget)" preload="metadata" @loadedmetadata="syncAudioPreviewMetadata" @durationchange="syncAudioPreviewMetadata" @timeupdate="syncAudioPreviewTime" @play="audioPreviewPlaying = true" @pause="audioPreviewPlaying = false" @ended="audioPreviewPlaying = false"></audio>
              <button type="button" class="asset-detail-audio-toggle" :aria-label="audioPreviewPlaying ? '暂停音频' : '播放音频'" @click="toggleAudioPreview">
                <svg v-if="!audioPreviewPlaying" viewBox="0 0 24 24"><path d="m9 7 8 5-8 5V7Z"/></svg>
                <svg v-else viewBox="0 0 24 24"><path d="M8 7h3v10H8zM14 7h3v10h-3z"/></svg>
              </button>
              <div class="asset-detail-audio-copy">
                <div><strong>音频预览</strong><span>{{ audioPreviewPlaying ? '正在播放' : '准备就绪' }}</span></div>
                <input type="range" min="0" :max="audioPreviewDuration || 0" step="0.01" :value="audioPreviewCurrent" :style="{ '--audio-progress': `${audioPreviewDuration ? (audioPreviewCurrent / audioPreviewDuration) * 100 : 0}%` }" aria-label="音频播放进度" @input="seekAudioPreview" />
              </div>
              <time>{{ formatAudioTime(audioPreviewCurrent) }} / {{ formatAudioTime(audioPreviewDuration) }}</time>
              <svg class="asset-detail-audio-volume" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10v4h3l4 3V7l-4 3H5Z"/><path d="M15 9.5a4 4 0 0 1 0 5M17.5 7a7 7 0 0 1 0 10"/></svg>
            </div>
            <div v-else class="asset-detail-empty" :class="{ 'is-generating': assetDetailTarget.generating && assetDetailTarget.category !== 'audio' }"><svg v-if="assetDetailTarget.category !== 'audio'" viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m6 17 4-4 3 3 2.5-2.5L19 17"/></svg><svg v-else viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg><span>{{ assetDetailTarget.generating && assetDetailTarget.category !== 'audio' ? '正在生成图片' : assetDetailTarget.category === 'audio' ? '尚未生成音频' : '尚未上传或生成图片' }}</span></div>
            <section v-if="assetReferenceState(assetDetailTarget).total" class="asset-detail-references">
              <header><strong>参考图</strong><div><span>{{ assetReferenceState(assetDetailTarget).ready }}/{{ assetReferenceState(assetDetailTarget).total }} 张已就绪</span><button class="asset-detail-reference-copy" type="button" :disabled="assetReferencesCopying || assetReferenceState(assetDetailTarget).ready !== assetReferenceState(assetDetailTarget).total" @click="copyAssetReferences(assetDetailTarget)">{{ assetReferencesCopying ? '复制中…' : assetReferencesCopied ? '已复制' : '复制' }}</button></div></header>
              <div>
                <button v-for="(reference, index) in assetReferenceState(assetDetailTarget).items" :key="reference.id" type="button" :disabled="!assetUrl(reference)" :aria-label="assetUrl(reference) ? `放大查看图${index + 1} ${reference.name}` : `图${index + 1} ${reference.name} 尚未生成`" @click="openReferencePreview(reference, assetDetailTarget)">
                  <img v-if="assetUrl(reference)" :src="assetUrl(reference)" :alt="reference.name" />
                  <span v-else>待生成</span>
                  <small>图{{ index + 1 }} · {{ reference.name || reference.id }}</small>
                </button>
                <span v-for="id in assetReferenceState(assetDetailTarget).unresolved" :key="id" class="asset-detail-reference-missing"><i>缺失</i><small>{{ id }}</small></span>
              </div>
            </section>
            <div class="asset-detail-media-actions">
              <button v-if="assetDetailTarget.category !== 'audio'" type="button" aria-label="从本地上传图片" data-tooltip="从本地上传图片" data-tooltip-pos="top" @click="selectLocalImageForAsset(assetDetailTarget)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg></button>
              <button v-if="assetDetailTarget.category !== 'audio' && assetUrl(assetDetailTarget)" class="asset-detail-clear-image" type="button" aria-label="清空图片" data-tooltip="清空图片" data-tooltip-pos="top" @click="clearAssetImage(assetDetailTarget)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></button>
              <button class="asset-detail-generate-media" type="button" :disabled="assetDetailTarget.generating" :aria-label="assetDetailTarget.generating ? '生成中' : assetDetailTarget.category === 'audio' ? '生成音频' : '重新生成图片'" :data-tooltip="assetDetailTarget.generating ? '生成中' : assetDetailTarget.category === 'audio' ? '生成音频' : '重新生成图片'" data-tooltip-pos="top" @click="generateAssetFromDetail"><span v-if="assetDetailTarget.generating" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/><path d="m18.5 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z"/></svg></button>
            </div>
          </div>
          <div class="asset-detail-fields">
            <label><span>资产名称</span><input v-model="assetDraft.name" /></label>
            <label><span>描述</span><textarea v-model="assetDraft.description" rows="4" placeholder="资产的外观、用途或声音说明"></textarea></label>
            <label><span>{{ assetDetailTarget.category === 'audio' ? '生成提示词（固定）' : '生成提示词' }}</span><textarea v-model="assetDraft.prompt" :readonly="assetDetailTarget.category === 'audio'" rows="8" placeholder="用于生成图片或音频的完整提示词"></textarea></label>
            <div v-if="assetDetailTarget.category === 'role'" class="asset-detail-default-prompt" :class="{ disabled: !assetDraft.useDefaultRoleLayout || rolePromptHasThreeViews(assetDraft.prompt) }">
              <div class="asset-detail-default-prompt-head"><span>默认角色构图</span><button type="button" role="switch" :aria-checked="assetDraft.useDefaultRoleLayout" :aria-label="assetDraft.useDefaultRoleLayout ? '关闭默认角色构图' : '开启默认角色构图'" @click="assetDraft.useDefaultRoleLayout = !assetDraft.useDefaultRoleLayout"><i></i></button></div>
              <textarea v-if="assetDraft.useDefaultRoleLayout && !rolePromptHasThreeViews(assetDraft.prompt)" :value="DEFAULT_ROLE_IMAGE_PROMPT" readonly rows="4"></textarea>
              <small v-if="rolePromptHasThreeViews(assetDraft.prompt)">已检测到原提示词包含“三视图”，不会追加任何默认构图词。</small>
              <small v-else-if="assetDraft.useDefaultRoleLayout">生成时自动拼接到原提示词末尾。</small>
              <small v-else>已关闭，生成时只发送你的原提示词。</small>
            </div>
            <details><summary>查看 JSON 详细字段</summary><pre>{{ assetRawDetails }}</pre></details>
            <p v-if="assetDetailTarget.generationError" class="asset-detail-error">{{ assetDetailTarget.generationError }}</p>
          </div>
        </div>
        <footer><button type="button" class="asset-detail-secondary" @click="closeAssetDetail">取消</button><button type="button" class="asset-detail-secondary" :disabled="!assetUrl(assetDetailTarget)" @click="addReference(assetDetailTarget); closeAssetDetail()">添加到当前分镜</button><button type="button" class="asset-detail-save" @click="saveAssetDetail">保存修改</button></footer>
      </section>
    </div>

    <BaseMediaPreview
      v-model:visible="mediaPreviewVisible"
      :src="mediaPreviewSrc"
      :type="mediaPreviewType"
      :references="mediaPreviewReferences"
      @video-error="handleMediaPreviewVideoError"
    />
  </section>

  <FinishedVideoTrackPreview
    v-model:visible="finishedPreviewVisible"
    :project-title="finishedPreviewProjectTitle"
    :videos="finishedPreviewVideos"
    :loading="finishedPreviewLoading"
    :error="finishedPreviewError"
    :token="props.token"
    @video-error="handleFinishedVideoError"
  />
</template>

<style scoped>
.video-project-hub { position: relative; z-index: 1; width: min(1420px,100%); box-sizing: border-box; margin: 0 auto; padding: 32px 0 44px; }
.video-project-hero { display: grid; min-height: 330px; grid-template-columns: minmax(0,1fr) minmax(360px,460px); gap: clamp(36px,6vw,100px); align-items: center; padding: clamp(26px,4vw,54px); overflow: hidden; border: 1px solid #303030; border-radius: 28px; background: radial-gradient(circle at 12% 10%,#292929 0,transparent 34%),linear-gradient(135deg,#1d1d1d 0%,#121212 68%); box-shadow: 0 26px 70px #0006; }
.video-project-hub-head > span,.video-project-library > header span { color: #969696; font: 700 12px/1 monospace; letter-spacing: .2em; }.video-project-hub-head h1 { margin: 17px 0 0; color: #f4f4f4; font-size: clamp(38px,4vw,58px); line-height: 1.06; letter-spacing: -.055em; }.video-project-hub-head h1 em { color: #9ca7ff; font-style: normal; }.video-project-hub-head p { max-width: 510px; margin: 19px 0 0; color: #929292; font-size: 14px; line-height: 1.8; }.video-project-highlights { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 27px; }.video-project-highlights span { display: flex; align-items: center; gap: 7px; padding: 8px 11px; border: 1px solid #373737; border-radius: 999px; color: #aaa; background: #ffffff05; font-size: 13px; }.video-project-highlights i { width: 6px; height: 6px; border-radius: 50%; background: #8ea0ff; box-shadow: 0 0 10px #8ea0ff; }
.video-project-create { display: grid; gap: 17px; padding: 23px; border: 1px solid #393939; border-radius: 20px; background: #151515e8; box-shadow: 0 22px 55px #0007; backdrop-filter: blur(16px); }.video-project-create-head { display: flex; align-items: center; gap: 12px; padding-bottom: 3px; }.video-project-create-head > span { display: grid; width: 38px; height: 38px; flex: 0 0 auto; place-items: center; border-radius: 11px; color: #111; background: #f1f1f1; font-size: 20px; }.video-project-create-head > div { display: grid; gap: 4px; }.video-project-create strong { color: #eee; font-size: 16px; }.video-project-create small { color: #777; font-size: 13px; }.video-project-create label { display: grid; gap: 8px; color: #aaa; font-size: 13px; }.video-project-create label > span { padding-left: 2px; }.video-project-create label small { float: right; margin-left: 5px; }.video-project-create input,.video-project-create textarea { width: 100%; box-sizing: border-box; padding: 0 13px; border: 1px solid #353535; border-radius: 10px; outline: 0; color: #eee; background: #0e0e0e; font: inherit; transition: border-color .18s ease,box-shadow .18s ease; }.video-project-create input { height: 43px; }.video-project-create textarea { min-height: 72px; padding-top: 12px; resize: none; line-height: 1.5; }.video-project-create input::placeholder,.video-project-create textarea::placeholder { color: #565656; }.video-project-create input:focus,.video-project-create textarea:focus { border-color: #777; box-shadow: 0 0 0 3px #ffffff0b; }.video-project-create > button { display: flex; height: 45px; align-items: center; justify-content: space-between; padding: 0 16px; border: 1px solid #f0f0f0; border-radius: 11px; color: #101010; background: #f0f0f0; cursor: pointer; font-size: 14px; font-weight: 700; transition: transform .18s ease,background .18s ease; }.video-project-create > button b { font-size: 18px; font-weight: 400; }.video-project-create > button:hover:not(:disabled) { transform: translateY(-1px); background: #fff; }.video-project-create > button:disabled { cursor: wait; opacity: .5; }
.video-project-error { margin: 13px 0 0; padding: 11px 13px; border: 1px solid #623d3d; border-radius: 10px; color: #dfa0a0; background: #291919; font-size: 14px; }.video-project-detail-overlay { position: fixed; z-index: 80; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; place-items: center; padding: 24px; background: rgba(8, 8, 8, 0.62); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); }.video-project-library { margin-top: 36px; }.video-project-library > header { display: flex; align-items: end; justify-content: space-between; padding: 0 3px 14px; border-bottom: 1px solid #292929; }.video-project-library > header h2 { margin: 7px 0 0; color: #e9e9e9; font-size: 22px; letter-spacing: -.025em; }.video-project-library > header b { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 9px; color: #aaa; background: #242424; font-size: 13px; }.video-project-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(360px,1fr)); gap: 18px; margin-top: 20px; }.video-project-card { min-width: 0; overflow: hidden; border: 1px solid #303030; border-radius: 20px; outline: 0; background: #171717; box-shadow: 0 14px 38px #0003; cursor: pointer; transition: border-color .2s ease,transform .2s ease,box-shadow .2s ease; }.video-project-card:hover,.video-project-card:focus-visible { border-color: #5c5c5c; transform: translateY(-3px); box-shadow: 0 24px 55px #0007; }.video-project-card-cover { position: relative; height: 116px; overflow: hidden; border-bottom: 1px solid #303030; background: radial-gradient(circle at 72% 35%,#5964a050,transparent 25%),linear-gradient(115deg,#2a2b34,#161616 58%); }.video-project-card-cover::before,.video-project-card-cover::after { position: absolute; width: 220px; height: 1px; content: ''; background: linear-gradient(90deg,transparent,#9ba5ff66,transparent); transform: rotate(-25deg); }.video-project-card-cover::before { right: -25px; top: 43px; }.video-project-card-cover::after { right: 12px; top: 72px; }.video-project-card-cover > span { position: absolute; left: 17px; top: 15px; color: #ffffff38; font: 700 13px/1 monospace; letter-spacing: .15em; }.video-project-card-cover > button { position: absolute; right: 17px; bottom: 15px; display: grid; width: 38px; height: 38px; place-items: center; border: 1px solid #ffffff22; border-radius: 50%; color: #171717; background: #ededed; font-size: 12px; }.video-project-card-mark { position: absolute; left: 18px; bottom: 20px; display: flex; align-items: end; gap: 4px; }.video-project-card-mark i { display: block; width: 4px; border-radius: 4px; background: #9ca7ff; }.video-project-card-mark i:nth-child(1) { height: 11px; opacity: .45; }.video-project-card-mark i:nth-child(2) { height: 23px; opacity: .7; }.video-project-card-mark i:nth-child(3) { height: 16px; }.video-project-card-body { padding: 18px; }.video-project-card-copy { min-width: 0; }.video-project-card-copy > span { color: #777; font: 700 12px/1 monospace; letter-spacing: .15em; }.video-project-card-copy h2 { overflow: hidden; margin: 7px 0 0; color: #eee; font-size: 19px; text-overflow: ellipsis; white-space: nowrap; }.video-project-card-copy p { overflow: hidden; min-height: 17px; margin: 7px 0 0; color: #777; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.video-project-card dl { display: grid; grid-template-columns: repeat(3,1fr); margin: 17px 0 0; padding: 13px 0; border-top: 1px solid #292929; border-bottom: 1px solid #292929; }.video-project-card dl > div { display: flex; align-items: baseline; justify-content: center; gap: 6px; border-right: 1px solid #2d2d2d; }.video-project-card dl > div:first-child { justify-content: flex-start; }.video-project-card dl > div:last-child { justify-content: flex-end; border-right: 0; }.video-project-card dt { color: #696969; font-size: 12px; }.video-project-card dd { margin: 0; color: #ddd; font-size: 14px; font-weight: 700; }.video-project-card footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 15px; }.video-project-card time { color: #5f5f5f; font-size: 12px; }.video-project-card footer button { padding: 0; border: 0; color: #aaa; background: transparent; cursor: pointer; font-size: 13px; }.video-project-card footer button span { display: inline-block; margin-left: 3px; transition: transform .18s ease; }.video-project-card:hover footer button span { transform: translateX(3px); }.video-project-empty { display: grid; min-height: 240px; place-content: center; gap: 8px; margin-top: 20px; border: 1px dashed #383838; border-radius: 17px; color: #777; background: #151515; text-align: center; font-size: 13px; }.video-project-empty strong { color: #bbb; font-size: 16px; }.video-project-empty span { font-size: 14px; }
.video-project-card-skeleton { pointer-events: none; }
.video-project-card-skeleton .video-project-card-body > header,
.video-project-card-skeleton .video-project-card-stats span,
.video-project-card-skeleton footer { gap: 0; }
.video-project-skeleton-header { display: flex; align-items: center; justify-content: space-between; }
.video-project-skeleton-header i:first-child { width: 90px; height: 12px; }
.video-project-skeleton-header i:last-child { width: 16px; height: 16px; border-radius: 50%; }
.video-project-skeleton-title,
.video-project-skeleton-desc,
.video-project-skeleton-time,
.video-project-skeleton-cta,
.video-project-skeleton-header i,
.video-project-card-skeleton .video-project-card-stats i { display: block; background: linear-gradient(90deg,#1c1c1c 25%,#262626 50%,#1c1c1c 75%); background-size: 200% 100%; animation: video-project-skeleton-shimmer 1.4s ease-in-out infinite; border-radius: 4px; }
.video-project-skeleton-title { width: 70%; height: 19px; margin: 7px 0 0; }
.video-project-skeleton-desc { width: 88%; height: 13px; margin: 7px 0 0; }
.video-project-card-skeleton .video-project-card-stats i { height: 12px; margin: 0 auto; }
.video-project-card-skeleton .video-project-card-stats span i:first-child { width: 20px; margin-bottom: 4px; }
.video-project-card-skeleton .video-project-card-stats span i:last-child { width: 28px; }
.video-project-skeleton-time { width: 90px; height: 12px; }
.video-project-skeleton-cta { width: 56px; height: 13px; margin-left: auto; }
@keyframes video-project-skeleton-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .video-project-skeleton-title, .video-project-skeleton-desc, .video-project-skeleton-time, .video-project-skeleton-cta, .video-project-skeleton-header i, .video-project-card-skeleton .video-project-card-stats i { animation: none; } }
@media (max-width: 980px) { .video-project-hero { grid-template-columns: 1fr; }.video-project-hub-head h1 br { display: none; }.video-project-create { max-width: 620px; }.video-project-grid { grid-template-columns: repeat(auto-fill,minmax(300px,1fr)); } }
.video-workbench { position: relative; z-index: 1; box-sizing: border-box; width: 100%; max-width: none; margin: 0; padding: 22px 0 20px; }
.video-workbench-head { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.video-workbench-head > div > span,.asset-rail-head span,.storyboard-column-head span { color: #8c8c8c; font: 700 12px/1 monospace; letter-spacing: .18em; }
.video-workbench-head h1 { margin: 9px 0 0; color: #f2f2f2; font-size: 34px; letter-spacing: -.04em; }
.video-workbench-title { display: grid; justify-items: start; }.video-workbench-title > button { margin: 0 0 10px; padding: 0; border: 0; color: #888; background: transparent; cursor: pointer; font-size: 14px; }.video-workbench-title > button:hover { color: #fff; }.video-workbench-title > input { width: min(560px,65vw); margin-top: 7px; padding: 0; border: 0; outline: 0; color: #f2f2f2; background: transparent; font-size: 34px; font-weight: 800; letter-spacing: -.04em; }.video-workbench-title p small { margin-left: 10px; color: #777; font-size: 12px; }
.video-workbench-title > .video-project-description { margin-top: 5px; color: #888; font-size: 13px; font-weight: 400; letter-spacing: 0; }.video-workbench-title > .video-project-description::placeholder { color: #5f5f5f; }
.video-workbench-head p { margin: 9px 0 0; color: #777; font-size: 14px; }
.video-workbench-head > button { display: flex; height: 38px; align-items: center; gap: 7px; padding: 0 14px; border: 1px solid #454545; border-radius: 10px; color: #ddd; background: #242424; cursor: pointer; font-size: 13px; }
.video-workbench-head > button:hover { border-color: #666; background: #303030; }
.video-workbench-layout { display: grid; width: 100%; min-height: calc(100vh - 185px); grid-template-columns: clamp(240px,18vw,300px) minmax(0,1fr); gap: 18px; align-items: start; }
.asset-rail,.storyboard-column { border: 1px solid #333; border-radius: 18px; background: #171717; box-shadow: 0 22px 55px #0005; }
.asset-rail { position: sticky; top: 70px; overflow: visible; }
.asset-rail-head,.storyboard-column-head { display: flex; align-items: center; justify-content: space-between; padding: 18px; }
.asset-rail-head h2,.storyboard-column-head h2 { margin: 5px 0 0; color: #e5e5e5; font-size: 16px; }
.asset-rail-head b,.storyboard-column-head b { padding: 4px 8px; border-radius: 999px; color: #999; background: #292929; font-size: 12px; }
.asset-head-actions { display: flex; align-items: center; gap: 6px; }.asset-head-actions button { display: grid; width: 25px; height: 25px; place-items: center; padding: 0; border: 1px solid #353535; border-radius: 7px; color: #888; background: #222; cursor: pointer; }.asset-head-actions button:hover:not(:disabled) { color: #fff; border-color: #555; }.asset-head-actions button:disabled { cursor: wait; opacity: .45; }
.asset-category-tabs { display: grid; grid-template-columns: repeat(6,1fr); gap: 3px; margin: 0 10px 12px; padding: 4px; border-radius: 10px; background: #101010; }
.asset-category-tabs button { display: grid; min-width: 0; height: 49px; place-items: center; align-content: center; gap: 3px; padding: 0; border: 0; border-radius: 7px; color: #777; background: transparent; cursor: pointer; font-size: 12px; }
.asset-category-tabs button:hover,.asset-category-tabs button.active { color: #eee; background: #303030; }
.asset-category-tabs svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.asset-generator { display: grid; gap: 8px; margin: 0 10px 12px; padding: 10px; border: 1px solid #303030; border-radius: 12px; background: #111; }
.asset-json-import { display: grid; min-width: 0; min-height: 48px; grid-template-columns: 28px minmax(0,1fr); align-items: center; gap: 8px; padding: 7px 9px; border: 1px dashed #484848; border-radius: 9px; color: #ccc; background: #191919; cursor: pointer; text-align: left; }.asset-json-import:hover { border-color: #777; background: #202020; }.asset-json-import > span { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 8px; color: #111; background: #ddd; font-size: 15px; }.asset-json-import > div { display: grid; min-width: 0; gap: 3px; }.asset-json-import strong { font-size: 12px; }.asset-json-import small { overflow: hidden; color: #6f6f6f; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.asset-generator-error { margin: 0; color: #d18a8a; font-size: 11px; line-height: 1.4; }
.asset-generate-spinner { width: 12px; height: 12px; border: 2px solid #999; border-top-color: #222; border-radius: 50%; animation: result-spin .7s linear infinite; }
.asset-rail-scroll { max-height: calc(100vh - 415px); min-height: 180px; padding: 0 10px 12px; overflow-y: auto; }
.asset-rail-grid { display: grid; grid-template-columns: 1fr; gap: 8px; }
.asset-pick-card { position: relative; min-width: 0; overflow: hidden; border: 1px solid #333; border-radius: 10px; padding: 0; color: #ddd; background: #202020; text-align: left; }
.asset-pick-card:hover { border-color: #666; transform: translateY(-1px); }
.asset-preview-button { display: block; width: 100%; padding: 0; border: 0; background: #111; cursor: pointer; }.asset-preview-button > img,.asset-audio-placeholder { display: grid; width: 100%; aspect-ratio: 1/1; place-items: center; object-fit: cover; background: #111; }
.asset-reference-count { position: absolute; z-index: 3; top: 10px; left: 46px; display: inline-flex; height: 20px; align-items: center; gap: 3px; padding: 0 6px; border: 1px solid #ffffff26; border-radius: 999px; color: #f2f2f2; background: #101010d9; box-shadow: 0 3px 10px #0008; font: 700 10px/1 monospace; pointer-events: none; }.asset-reference-count.incomplete { color: #f1c67b; }.asset-reference-count svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.asset-audio-placeholder svg { width: 25px; fill: none; stroke: #999; stroke-width: 1.5; }
.asset-missing-preview { display: grid; width: 100%; aspect-ratio: 1/1; place-items: center; align-content: center; gap: 7px; padding: 0; border: 0; color: #6d6d6d; background: repeating-linear-gradient(135deg,#171717,#171717 8px,#1b1b1b 8px,#1b1b1b 16px); cursor: pointer; }.asset-missing-preview:hover { color: #aaa; }.asset-missing-preview svg { width: 25px; fill: none; stroke: currentColor; stroke-width: 1.4; }.asset-missing-preview span { font-size: 11px; }
.asset-pick-copy { display: grid; width: 100%; gap: 2px; padding: 8px; border: 0; color: #ddd; background: transparent; cursor: pointer; text-align: left; }
.asset-pick-copy strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.asset-pick-copy small { color: #777; font-size: 11px; }
.asset-card-add { position: absolute; top: 6px; right: 6px; display: grid; width: 25px; height: 25px; place-items: center; padding: 0; border: 2px solid #202020; border-radius: 50%; color: #111; background: #e5e5e5; box-shadow: 0 5px 14px #0008; cursor: pointer; font-size: 16px; opacity: 0; }.asset-pick-card:hover .asset-card-add,.asset-card-add:focus-visible { opacity: 1; }.asset-card-add:hover { background: #fff; transform: scale(1.06); }
.asset-card-generate { display: flex; width: calc(100% - 12px); height: 29px; align-items: center; justify-content: center; gap: 5px; margin: 0 6px 7px; padding: 0 5px; border: 1px solid #474747; border-radius: 7px; color: #ddd; background: #2b2b2b; cursor: pointer; font-size: 11px; }
.asset-card-generate svg { width: 12px; height: 12px; flex: 0 0 12px; fill: currentColor; }
.asset-card-generate .asset-generate-spinner { flex: 0 0 12px; }.asset-card-generate:hover:not(:disabled) { border-color: #777; background: #383838; }.asset-card-generate:disabled { cursor: wait; opacity: .6; }.asset-card-error { overflow: hidden; margin: 0 7px 7px; color: #c77e7e; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.asset-rail-state { padding: 35px 10px; color: #666; font-size: 12px; text-align: center; }
.asset-rail-state.error { color: #e5848e; }
.asset-rail-empty { display: grid; padding: 44px 20px; gap: 7px; justify-items: center; text-align: center; }
.asset-rail-empty-icon { display: grid; width: 56px; height: 42px; place-items: center; margin-bottom: 6px; opacity: .3; }
.asset-rail-empty-icon svg { width: 100%; height: 100%; fill: #999; }
.asset-rail-empty strong { color: #b0b0b0; font-size: 14px; font-weight: 600; }
.asset-rail-empty small { color: #5a5a5a; font-size: 12px; line-height: 1.6; max-width: 200px; }
.storyboard-column { min-width: 0; padding-bottom: 16px; background: #141414; }
.storyboard-column-head { border-bottom: 1px solid #292929; }
.storyboard-card { --shot-card-radius: 17px; position: relative; margin: 15px; border: 1px solid #343434; border-radius: 17px; outline: none; background: linear-gradient(145deg,#202020,#181818); box-shadow: 0 14px 34px #0004; transition: border-color .18s ease,box-shadow .18s ease; }
.storyboard-card:has(.mode-popover,.settings-popover) { z-index: 40; }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: #666; box-shadow: 0 18px 46px #0007,0 0 0 3px #ffffff08; }
.storyboard-card-head { display: flex; height: 42px; align-items: center; gap: 9px; padding: 0 13px; border-bottom: 1px solid #2f2f2f; }
.shot-number { color: #777; font: 700 12px/1 monospace; }
.storyboard-card-head input { flex: 1; min-width: 0; border: 0; outline: 0; color: #ddd; background: transparent; font-size: 13px; font-weight: 700; }
.storyboard-card-head button,.shot-expand { display: grid; width: 27px; height: 27px; place-items: center; border: 0; border-radius: 7px; color: #777; background: transparent; cursor: pointer; }
.storyboard-card-head button:hover:not(:disabled),.shot-expand:hover { color: #fff; background: #303030; }
.storyboard-card-head button:disabled { opacity: .2; cursor: not-allowed; }
.shot-body-grid { display: grid; grid-template-columns: minmax(520px,1.15fr) minmax(360px,.85fr); align-items: stretch; }
.shot-content { display: flex; min-width: 0; flex-direction: column; border-right: 1px solid #2e2e2e; }
.shot-content.expanded { position: fixed; z-index: 45; top: 64px; right: 24px; bottom: 24px; left: calc(var(--sidebar-width,240px) + 24px); overflow: visible; border: 1px solid #4a4a4a; border-radius: 18px; background: linear-gradient(145deg,#202020,#151515); box-shadow: 0 32px 100px #000e,0 0 0 100vmax #080808b8; }
.shot-content.expanded .shot-content-head { min-height: 56px; padding-right: 20px; padding-left: 20px; }
.shot-content.expanded .storyboard-compose { min-height: 0; flex: 1; grid-template-columns: auto minmax(260px,1fr) 34px; align-items: stretch; padding: 20px; }
.shot-content.expanded .storyboard-compose textarea { width: 100%; height: 100%; min-height: 240px; box-sizing: border-box; padding: 8px 10px; font-size: 16px; }
.shot-content.expanded .shot-expand { align-self: start; width: 34px; height: 34px; color: #ddd; background: #2d2d2d; }
.shot-content.expanded .storyboard-toolbar { min-height: 58px; padding-right: 18px; padding-left: 18px; border-radius: 0 0 18px 18px; background: #171717; }
.shot-content.expanded .mode-popover,.shot-content.expanded .settings-popover { top: auto; bottom: calc(100% + 10px); }
.shot-content-head { display: grid; min-height: 44px; box-sizing: border-box; align-content: center; gap: 4px; padding: 0 13px; border-bottom: 1px solid #292929; }.shot-content-head span { color: #737373; font: 700 11px/1 monospace; letter-spacing: .14em; }.shot-content-head strong { color: #d8d8d8; font-size: 12px; }
.storyboard-compose { position: relative; display: grid; grid-template-columns: auto minmax(220px,1fr) 28px; gap: 12px; min-height: 112px; align-items: start; padding: 14px; }
.reference-stack { position: relative; display: flex; width: 104px; min-width: 104px; max-width: 520px; height: 82px; align-items: stretch; isolation: isolate; transition: width .34s cubic-bezier(.22,1,.36,1),max-width .34s cubic-bezier(.22,1,.36,1); }
.reference-stack.expanded { width: var(--reference-expanded-width,78px); min-width: 78px; }
.reference-add { display: grid; width: 78px; flex: 0 0 78px; place-items: center; align-content: center; gap: 4px; overflow: hidden; border: 1px dashed #484848; border-radius: 10px; color: #777; background: #171717; cursor: pointer; opacity: 1; transform: translateX(0) scale(1); transform-origin: left center; transition: width .28s cubic-bezier(.22,1,.36,1),flex-basis .28s cubic-bezier(.22,1,.36,1),opacity .18s ease,transform .28s cubic-bezier(.22,1,.36,1),border-color .18s ease,background .18s ease; }.reference-add:hover { border-color: #777; color: #eee; background: #222; }
.reference-stack.has-references:not(.expanded) .reference-add { width: 0; flex-basis: 0; border-color: transparent; opacity: 0; pointer-events: none; transform: translateX(-12px) scale(.82); }
.reference-add span { font-size: 20px; line-height: 1; }.reference-add small { font-size: 12px; }
.reference-card { position: relative; flex: 0 0 78px; width: 78px; height: 78px; margin-left: 7px; overflow: visible; border: 1px solid #555; border-radius: 10px; background: #222; box-shadow: -5px 5px 15px #0009; transform: none; transform-origin: 50% 90%; transition: margin .24s ease,transform .24s cubic-bezier(.2,.8,.2,1),opacity .18s ease; }
.reference-stack:not(.expanded) .reference-card { position: absolute; top: 2px; left: 0; z-index: calc(var(--stack-index) + 1); margin: 0; transform: translateX(var(--stack-x)) translateY(var(--stack-y)) rotate(var(--stack-angle)) scale(.86); transform-origin: 50% 88%; }
.reference-stack:not(.expanded) .reference-card.stack-hidden { visibility: hidden; opacity: 0; }
.reference-stack.expanded .reference-card { position: relative; top: auto; left: auto; z-index: auto; margin-left: 7px; transform: none; animation: reference-card-unfold .34s cubic-bezier(.22,1,.36,1) both; animation-delay: calc(var(--stack-index) * 35ms); }
.reference-card > img,.reference-card > span { display: grid; width: 100%; height: 100%; place-items: center; border-radius: 9px; object-fit: cover; background: #111; }
.reference-card > img { cursor: pointer; transition: transform .25s ease; }
.reference-card > img:hover { transform: scale(1.04); }
.reference-card > span svg { width: 24px; fill: none; stroke: #aaa; stroke-width: 1.5; }
.reference-card > small { position: absolute; right: 4px; bottom: 4px; left: 4px; overflow: hidden; padding: 3px 4px; border-radius: 4px; color: #fff; background: #000b; font-size: 11px; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.reference-stack:not(.expanded) .reference-card > small { display: none; }.reference-stack:not(.expanded) .reference-card:last-of-type > small { display: block; }
.reference-card > button { position: absolute; z-index: 3; top: -6px; right: -6px; display: block; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 50%; color: #fff; background: #3c3c3c; cursor: pointer; font-size: 13px; opacity: 0; pointer-events: none; transform: scale(.55) rotate(-35deg); transition: opacity .18s ease .12s,transform .26s cubic-bezier(.22,1,.36,1) .1s; }
.reference-stack.expanded .reference-card > button { opacity: 1; pointer-events: auto; transform: scale(1) rotate(0); }
.reference-stack-add { position: absolute; z-index: 20; left: 71px; bottom: 4px; display: grid; width: 27px; height: 27px; place-items: center; border: 3px solid #1b1b1b; border-radius: 50%; color: #222; background: #eee; box-shadow: 0 5px 12px #0007; font-size: 16px; line-height: 1; transition: transform .18s ease,background .18s ease; }.reference-stack:not(.expanded):hover .reference-stack-add { transform: scale(1.08); background: #fff; }
@keyframes reference-card-unfold { from { opacity: .72; transform: translateX(calc(var(--stack-x) * -1)) translateY(var(--stack-y)) rotate(var(--stack-angle)) scale(.86); } to { opacity: 1; transform: translateX(0) translateY(0) rotate(0) scale(1); } }
@media (prefers-reduced-motion: reduce) { .reference-stack,.reference-add,.reference-card,.reference-card > button { transition-duration: 1ms !important; animation-duration: 1ms !important; animation-delay: 0ms !important; } }
.storyboard-compose textarea { min-height: 78px; padding: 5px 8px 5px 4px; overflow-y: auto; resize: none; border: 0; outline: 0; color: #d5d5d5; background: transparent; font-size: 13px; line-height: 1.65; box-shadow: none; }
.storyboard-compose textarea::placeholder { color: #656565; }
.storyboard-compose textarea { scrollbar-width: thin; scrollbar-color: #555 transparent; }
.storyboard-compose textarea::-webkit-scrollbar { width: 7px; }
.storyboard-compose textarea::-webkit-scrollbar-track { border-radius: 999px; background: transparent; }
.storyboard-compose textarea::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 999px; background: #555; background-clip: padding-box; }
.storyboard-compose textarea::-webkit-scrollbar-thumb:hover { background: #777; background-clip: padding-box; }
.shot-expand svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.5; }
.shot-editor-actions { display: flex; align-self: start; flex-direction: column; gap: 7px; }
.shot-editor-actions > button { display: grid; width: 28px; height: 28px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 7px; color: #777; background: transparent; cursor: pointer; }
.shot-editor-actions > button:hover { border-color: #42464d; color: #f0f2f5; background: #292c31; }
.shot-editor-actions > button svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.shot-editor-actions .shot-send-preview-toggle.active { border-color: #66d9ef50; color: #bff5ff; background: #173039; }
.storyboard-toolbar { display: flex; width: 100%; min-width: 0; max-width: none; min-height: 42px; box-sizing: border-box; align-items: center; gap: 10px; margin: 0; padding: 8px 12px; border-top: 1px solid #2e2e2e; color: #9a9a9a; font-size: 12px; }
.storyboard-toolbar button { display: flex; align-items: center; gap: 5px; padding: 4px 5px; border: 0; color: #aaa; background: transparent; cursor: pointer; font-size: 12px; white-space: nowrap; }
.storyboard-toolbar button:hover { color: #fff; }.storyboard-toolbar button svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.6; }
.settings-summary-btn { padding: 4px 10px !important; border: 1px solid #333 !important; border-radius: 8px !important; color: #ccc !important; background: #1c1c1c !important; transition: border-color .18s ease,color .18s ease; }
.settings-summary-btn:hover { border-color: #555 !important; color: #fff !important; }
.settings-summary-btn[aria-expanded="true"] { border-color: #888 !important; color: #fff !important; }
.settings-summary-btn svg { width: 13px !important; stroke-width: 2; }
.storyboard-toolbar span { white-space: nowrap; }.storyboard-toolbar span i { display: inline-block; width: 11px; height: 6px; margin-right: 4px; border: 1px solid currentColor; border-radius: 2px; }
.storyboard-toolbar .shot-clear { margin-left: auto; color: #777; }
.storyboard-toolbar .shot-submit { display: grid; width: 32px; height: 32px; place-items: center; padding: 0; border-radius: 50%; color: #1b1b1b; background: #ddd; }
.storyboard-toolbar .shot-submit:hover { color: #111; background: #fff; }
.storyboard-toolbar .shot-submit:disabled { cursor: wait; opacity: .55; }
.toolbar-popover-wrap { position: relative; display: flex; flex: 0 0 auto; }
.mode-popover,.settings-popover { position: absolute; z-index: 60; top: auto; bottom: calc(100% + 8px); left: 0; border: 1px solid #454545; color: #d5d5d5; background: #1d1d1d; box-shadow: 0 18px 48px #000b; }
.mode-popover { width: 196px; padding: 10px; border-radius: 12px; }.mode-popover > label { display: block; padding: 2px 5px 9px; color: #898989; font-size: 13px; }.storyboard-toolbar .mode-popover > button { display: grid; width: 100%; height: 42px; grid-template-columns: 20px minmax(0,1fr) 18px; align-items: center; gap: 8px; padding: 0 10px; border-radius: 9px; color: #aaa; font-size: 14px; text-align: left; }.storyboard-toolbar .mode-popover > button:hover,.storyboard-toolbar .mode-popover > button.active { color: #eee; background: #2d2d2d; }.mode-popover > button b { font-size: 15px; text-align: center; }
.settings-popover { display: grid; width: min(460px,calc(100vw - 340px)); min-width: 400px; max-height: min(380px,calc(100vh - 80px)); box-sizing: border-box; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 12px; padding: 12px; overflow-y: auto; overscroll-behavior: contain; border-radius: 12px; scrollbar-width: thin; }
.settings-popover .settings-field-wide { grid-column: 1 / -1; }
.settings-popover fieldset { margin: 0; padding: 0; border: 0; }
.seedance-model-select { margin-top: 10px; }
.seedance-model-select :deep(.ui-select-trigger) { min-height: 38px; border-radius: 9px; }
.settings-popover legend { padding: 0; margin-bottom: 8px; color: #9a9a9a; font-size: 11px; font-weight: 700; letter-spacing: .04em; }.settings-popover::-webkit-scrollbar { width: 7px; }.settings-popover::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 99px; background: #555; background-clip: padding-box; }.settings-popover fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }.settings-popover fieldset:nth-child(1),.settings-popover fieldset:nth-child(3),.settings-popover fieldset:nth-child(5) { grid-column: 1 / -1; }.settings-popover legend { margin-bottom: 7px; color: #aaa; font-size: 12px; }
.ratio-options { display: grid; grid-template-columns: repeat(7,minmax(0,1fr)); overflow: hidden; border: 1px solid #303030; border-radius: 9px; background: #171717; }.storyboard-toolbar .ratio-options button { display: grid; height: 46px; place-items: center; align-content: center; gap: 3px; padding: 0; border-right: 1px solid #292929; border-radius: 0; color: #888; font-size: 12px; }.ratio-options button:last-child { border-right: 0; }.storyboard-toolbar .ratio-options button:hover,.storyboard-toolbar .ratio-options button.active { color: #171717; background: #eee; }.ratio-options svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.6; }
.segmented-options { display: grid; grid-template-columns: repeat(2,1fr); overflow: hidden; border: 1px solid #303030; border-radius: 9px; background: #171717; }.segmented-options.four { grid-template-columns: repeat(4,1fr); }.storyboard-toolbar .segmented-options button { height: 38px; justify-content: center; border-right: 1px solid #292929; border-radius: 0; color: #888; font-size: 14px; }.segmented-options button:last-child { border-right: 0; }.storyboard-toolbar .segmented-options button:hover,.storyboard-toolbar .segmented-options button.active { color: #171717; background: #eee; }
.duration-options,.count-options { display: grid; grid-template-columns: repeat(8,1fr); gap: 4px; margin-top: 9px; padding: 4px; border-radius: 9px; background: #171717; }.count-options { margin-top: 0; }.storyboard-toolbar .duration-options button,.storyboard-toolbar .count-options button { height: 32px; justify-content: center; padding: 0; border-radius: 7px; color: #888; font-size: 13px; }.storyboard-toolbar .duration-options button:hover,.storyboard-toolbar .duration-options button.active,.storyboard-toolbar .count-options button:hover,.storyboard-toolbar .count-options button.active { color: #171717; background: #eee; }
.shot-result { position: relative; display: flex; min-width: 0; margin: 12px; overflow: hidden; flex-direction: column; border: 1px solid #303030; border-radius: 13px; background: #111; box-shadow: inset 0 1px #ffffff08; }
.shot-result-replace-control:disabled,.shot-result-download-control:disabled { cursor: wait; opacity: .55; }
.shot-result-replace-control .asset-generate-spinner,.shot-result-download-control .asset-generate-spinner { width: 14px; height: 14px; }
.shot-result-replace-error { position: absolute; z-index: 8; top: 10px; right: 10px; max-width: calc(100% - 20px); margin: 0; padding: 6px 9px; border: 1px solid #704047; border-radius: 7px; color: #efabb3; background: #351d21ed; box-shadow: 0 6px 18px #0008; font-size: 11px; }
.shot-result > header { display: flex; min-height: 44px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 13px; border-bottom: 1px solid #292929; background: linear-gradient(100deg,#1a1a1a,#121212); }
.shot-result > header > div { display: grid; gap: 4px; }.shot-result > header span { color: #737373; font: 700 11px/1 monospace; letter-spacing: .14em; }.shot-result > header strong { color: #d8d8d8; font-size: 12px; }
.shot-result > header small { overflow: hidden; max-width: 180px; color: #747474; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.shot-result-player { position: relative; display: grid; min-height: 230px; overflow: hidden; flex: 1; place-items: center; isolation: isolate; background: radial-gradient(circle at 50% 35%,#1a1d2b 0,#070708 52%,#020202 100%); border-radius: 11px; }
.shot-result-player::before { position: absolute; z-index: -1; inset: 0; content: ''; opacity: .5; background-image: linear-gradient(#ffffff06 1px,transparent 1px),linear-gradient(90deg,#ffffff06 1px,transparent 1px); background-size: 28px 28px; mask-image: linear-gradient(#000,transparent 80%); }
.shot-result-player video { display: block; width: 100%; height: 100%; min-height: 230px; max-height: 480px; object-fit: cover; background: #000; border-radius: 11px; cursor: pointer; }
.shot-result-watermark-badge { position: absolute; z-index: 6; top: 10px; left: 10px; padding: 5px 8px; border: 1px solid #f3a84a66; border-radius: 7px; color: #ffd395; background: #3a210dd9; box-shadow: 0 4px 14px #0008; font-size: 11px; font-weight: 700; }
.shot-result-center-play { position: absolute; z-index: 4; top: 50%; left: 50%; display: grid; width: 56px; height: 56px; place-items: center; padding: 0; border: 0; border-radius: 50%; color: #fff; background: rgba(0,0,0,0.55); box-shadow: 0 6px 24px #0008; cursor: pointer; transform: translate(-50%,-50%); transition: transform .18s ease,background .18s ease; }
.shot-result-center-play:hover { background: rgba(0,0,0,0.75); transform: translate(-50%,-50%) scale(1.08); }
.shot-result-center-play svg { width: 26px; fill: currentColor; }
.shot-result-player .shot-result-expand { position: absolute; z-index: 5; top: 10px; right: 10px; display: inline-flex; width: 32px; height: 32px; align-items: center; justify-content: center; padding: 0; border: 0; border-radius: 8px; color: #eee; background: rgba(0,0,0,0.5); cursor: pointer; opacity: 0; transition: opacity .18s ease,background .18s ease; }
.shot-result-player .shot-result-expand svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.7; }
.shot-result-player:hover .shot-result-expand { opacity: 1; }
.shot-result-player .shot-result-expand:hover { background: rgba(0,0,0,0.75); }
/* 底部控件栏：渐变遮罩 + 毛玻璃 */
.shot-result-controls { position: absolute; z-index: 4; right: 0; bottom: 0; left: 0; display: flex; align-items: center; gap: 8px; padding: 10px 12px 8px; background: linear-gradient(transparent,rgba(0,0,0,0.75)); opacity: 0; transition: opacity .2s ease; }
.shot-result-player:hover .shot-result-controls,
.shot-result-controls:hover { opacity: 1; }
.shot-ctrl-btn { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; padding: 0; border: 0; border-radius: 6px; color: #fff; background: transparent; cursor: pointer; transition: background .15s ease; }
.shot-ctrl-btn:hover { background: rgba(255,255,255,0.15); }
.shot-ctrl-btn svg { width: 16px; fill: currentColor; }
.shot-ctrl-time { color: rgba(255,255,255,0.85); font: 600 11px/1 monospace; font-variant-numeric: tabular-nums; white-space: nowrap; user-select: none; }
/* 自定义进度条 */
.shot-ctrl-seek { flex: 1; min-width: 0; height: 4px; appearance: none; -webkit-appearance: none; background: rgba(255,255,255,0.2); border-radius: 2px; cursor: pointer; background-image: linear-gradient(#45d7ff,#45d7ff); background-size: var(--p,0%) 100%; background-repeat: no-repeat; }
.shot-ctrl-seek::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px; border: 0; border-radius: 50%; background: #45d7ff; box-shadow: 0 0 0 3px rgba(69,215,255,0.25); cursor: pointer; transition: transform .15s ease; }
.shot-ctrl-seek::-webkit-slider-thumb:hover { transform: scale(1.2); }
.shot-ctrl-seek::-moz-range-thumb { width: 12px; height: 12px; border: 0; border-radius: 50%; background: #45d7ff; cursor: pointer; }
.shot-result-empty,.shot-result-progress,.shot-result-error,.shot-result-complete { min-height: 150px; box-sizing: border-box; padding: 20px; flex: 1; }
.shot-result-empty { display: flex; align-items: center; justify-content: center; gap: 12px; color: #777; background: radial-gradient(circle at 50% 45%,#242424,#101010 65%); }
.shot-result-empty > span { display: grid; width: 40px; height: 40px; place-items: center; border: 1px solid #353535; border-radius: 12px; background: #181818; }.shot-result-empty svg { width: 20px; fill: none; stroke: #888; stroke-width: 1.5; }.shot-result-empty > div,.shot-result-progress > div { display: grid; gap: 5px; }.shot-result-empty strong,.shot-result-progress strong,.shot-result-error strong { color: #bbb; font-size: 12px; }.shot-result-empty small,.shot-result-progress small { color: #666; font-size: 12px; }
.shot-result-progress { position: relative; display: grid; grid-template-columns: 34px minmax(0,1fr) auto; align-items: center; gap: 12px; }.shot-result-progress b { color: #aaa; font: 700 12px/1 monospace; }.shot-result-progress > i { position: absolute; right: 20px; bottom: 20px; left: 66px; height: 3px; overflow: hidden; border-radius: 3px; background: #292929; }.shot-result-progress > i em { display: block; height: 100%; border-radius: inherit; background: #ddd; transition: width .3s ease; }
.result-spinner { width: 28px; height: 28px; border: 2px solid #333; border-top-color: #ddd; border-radius: 50%; animation: result-spin .8s linear infinite; }
.shot-result-error { display: grid; grid-template-columns: minmax(0,1fr) auto; align-content: center; align-items: center; gap: 7px 15px; }.shot-result-error strong { color: #dc9b9b; }.shot-result-error > span { grid-column: 1; color: #a16f6f; font-size: 12px; }.shot-result-error-actions { display: flex; grid-column: 2; grid-row: 1 / 3; gap: 7px; }.shot-result-error-actions button,.shot-result-upload { padding: 7px 10px; border: 1px solid #4b5059; border-radius: 8px; color: #d8dce3; background: #24272d; cursor: pointer; font-size: 12px; transition: border-color .16s ease,background .16s ease,opacity .16s ease; }.shot-result-error-actions button:first-child { border-color: #5a4141; color: #d9adad; background: #2a1c1c; }.shot-result-error-actions button:hover,.shot-result-upload:hover { border-color: #707784; background: #30343b; }.shot-result-error-actions button:disabled,.shot-result-upload:disabled { cursor: wait; opacity: .55; }
.shot-result-complete { display: grid; place-content: center; gap: 7px; text-align: center; }.shot-result-complete strong { color: #bbb; font-size: 12px; }.shot-result-complete span { color: #777; font-size: 12px; }.shot-result-complete .shot-result-upload { justify-self: center; margin-top: 4px; }
.shot-result-empty .shot-result-upload { margin-left: auto; white-space: nowrap; }

.json-import-backdrop { position: fixed; z-index: 200; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; box-sizing: border-box; place-items: center; padding: 28px; background: #050505c7; backdrop-filter: blur(8px); }
.json-import-dialog { width: min(680px,calc(100vw - 56px)); max-height: calc(100vh - 56px); box-sizing: border-box; overflow: auto; border: 1px solid #444; border-radius: 20px; color: #ddd; background: linear-gradient(145deg,#222,#151515); box-shadow: 0 32px 100px #000e; }
.json-import-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 24px 26px 18px; border-bottom: 1px solid #303030; }
.json-import-dialog > header span { color: #888; font: 700 12px/1 monospace; letter-spacing: .16em; }.json-import-dialog > header h2 { margin: 9px 0 0; color: #f1f1f1; font-size: 23px; }.json-import-dialog > header p { margin: 8px 0 0; color: #888; font-size: 13px; }
.json-import-dialog > header button { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 9px; color: #888; background: transparent; cursor: pointer; font-size: 22px; }.json-import-dialog > header button:hover { border-color: #444; color: #fff; background: #2b2b2b; }
.json-import-editor { display: grid; gap: 9px; padding: 20px 26px 0; color: #aaa; font-size: 13px; }.json-import-textarea { width: 100%; min-height: 290px; box-sizing: border-box; padding: 15px 16px; resize: vertical; border: 1px solid #3c3c3c; border-radius: 13px; outline: 0; color: #ddd; background: #0f0f0f; font: 14px/1.65 Consolas,"Microsoft YaHei",monospace; tab-size: 2; }.json-import-textarea::placeholder { color: #5f5f5f; }.json-import-textarea:focus { border-color: #777; box-shadow: 0 0 0 3px #ffffff0b; }
.json-import-error { margin: 12px 26px 0; padding: 10px 12px; border: 1px solid #633d3d; border-radius: 9px; color: #e3a3a3; background: #2a1919; font-size: 14px; line-height: 1.5; }
.json-import-dialog > footer { display: grid; grid-template-columns: minmax(190px,1fr) auto auto; align-items: center; gap: 10px; padding: 18px 26px 24px; }
.json-import-dialog > footer button { height: 42px; box-sizing: border-box; border-radius: 10px; cursor: pointer; font-size: 14px; }.json-file-button { display: grid; min-width: 0; grid-template-columns: 28px minmax(0,1fr); align-items: center; gap: 9px; padding: 5px 10px; border: 1px dashed #555; color: #ccc; background: #202020; text-align: left; }.json-file-button:hover { border-color: #888; background: #292929; }.json-file-button > span { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 7px; color: #111; background: #ddd; font-size: 15px; }.json-file-button > div { display: grid; min-width: 0; gap: 2px; }.json-file-button strong { font-size: 14px; }.json-file-button small { color: #777; font-size: 12px; }
.json-cancel-button { padding: 0 17px; border: 1px solid #444; color: #aaa; background: #222; }.json-cancel-button:hover { color: #fff; background: #303030; }.json-confirm-button { padding: 0 19px; border: 1px solid #eee; color: #111; background: #eee; font-weight: 700; }.json-confirm-button:hover:not(:disabled) { background: #fff; }.json-confirm-button:disabled { cursor: not-allowed; opacity: .35; }

.asset-detail-backdrop { position: fixed; z-index: 210; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; box-sizing: border-box; place-items: center; padding: 28px; background: #050505d1; backdrop-filter: blur(9px); }
.asset-detail-dialog { width: min(900px,calc(100vw - 56px)); max-height: calc(100vh - 56px); box-sizing: border-box; overflow: auto; border: 1px solid #444; border-radius: 20px; color: #ddd; background: linear-gradient(145deg,#222,#151515); box-shadow: 0 32px 110px #000f; scrollbar-width: thin; scrollbar-color: #555 transparent; }
.asset-detail-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 22px 25px 17px; border-bottom: 1px solid #303030; }.asset-detail-dialog > header span { color: #888; font: 700 12px/1 monospace; letter-spacing: .16em; }.asset-detail-dialog > header h2 { margin: 8px 0 0; color: #f1f1f1; font-size: 23px; }.asset-detail-dialog > header p { margin: 7px 0 0; color: #777; font-size: 14px; }.asset-detail-dialog > header button { display: grid; width: 34px; height: 34px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 9px; color: #888; background: transparent; cursor: pointer; font-size: 22px; }.asset-detail-dialog > header button:hover { border-color: #444; color: #fff; background: #2b2b2b; }
.asset-detail-body { display: grid; grid-template-columns: minmax(280px,.8fr) minmax(340px,1.2fr); gap: 22px; padding: 22px 25px; }.asset-detail-preview { display: flex; min-width: 0; flex-direction: column; gap: 12px; }.asset-detail-image-preview,.asset-detail-empty { width: 100%; min-height: 330px; max-height: 520px; border: 1px solid #373737; border-radius: 14px; background: #0c0c0c; }.asset-detail-image-preview { position: relative; display: grid; padding: 0; overflow: hidden; place-items: center; cursor: zoom-in; transition: border-color .18s ease,box-shadow .18s ease; }.asset-detail-image-preview:hover,.asset-detail-image-preview:focus-visible { border-color: #707070; outline: 0; box-shadow: 0 0 0 3px #ffffff0c; }.asset-detail-image-preview > img { display: block; width: 100%; min-height: 330px; max-height: 520px; object-fit: contain; transition: transform .2s ease; }.asset-detail-image-preview:hover > img { transform: scale(1.015); }.asset-detail-zoom-hint { position: absolute; right: 11px; bottom: 11px; display: inline-flex; height: 28px; align-items: center; gap: 6px; padding: 0 10px; border: 1px solid #ffffff1f; border-radius: 999px; color: #ddd; background: #111c; backdrop-filter: blur(8px); font-size: 11px; }.asset-detail-zoom-hint svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }.asset-detail-empty { display: grid; place-items: center; align-content: center; gap: 10px; color: #727272; }.asset-detail-empty svg { width: 44px; fill: none; stroke: currentColor; stroke-width: 1.3; }.asset-detail-empty span { font-size: 14px; }
.asset-detail-references { display: grid; min-width: 0; gap: 9px; padding: 11px; border: 1px solid #343434; border-radius: 12px; background: #151515; }.asset-detail-references > header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.asset-detail-references > header strong { color: #ddd; font-size: 12px; }.asset-detail-references > header > div { display: flex; align-items: center; gap: 8px; }.asset-detail-references > header span { color: #777; font-size: 11px; }.asset-detail-reference-copy { min-width: 48px; height: 25px; padding: 0 10px; border: 1px solid #494949; border-radius: 7px; color: #ccc; background: #282828; cursor: pointer; font-size: 11px; }.asset-detail-reference-copy:hover:not(:disabled) { border-color: #777; color: #fff; background: #333; }.asset-detail-reference-copy:disabled { cursor: not-allowed; opacity: .5; }.asset-detail-references > div { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 7px; }.asset-detail-references > div > button,.asset-detail-reference-missing { position: relative; display: grid; min-width: 0; aspect-ratio: 1/1; padding: 0; overflow: hidden; place-items: center; border: 1px solid #373737; border-radius: 9px; color: #777; background: #0d0d0d; }.asset-detail-references > div > button:not(:disabled) { cursor: zoom-in; }.asset-detail-references > div > button:not(:disabled):hover { border-color: #777; }.asset-detail-references > div > button:disabled { cursor: not-allowed; opacity: .58; }.asset-detail-references img { width: 100%; height: 100%; object-fit: cover; }.asset-detail-references small { position: absolute; right: 4px; bottom: 4px; left: 4px; overflow: hidden; padding: 3px 5px; border-radius: 5px; color: #eee; background: #090909d9; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.asset-detail-reference-missing i { color: #c48a8a; font: normal 11px/1 inherit; }
.asset-detail-image-preview.is-generating::after,.asset-detail-empty.is-generating::after { position: absolute; z-index: 1; top: -18%; bottom: -18%; left: 0; width: 24%; background: linear-gradient(90deg,transparent,#ffffffc9,transparent); filter: blur(.25px); content: ''; pointer-events: none; animation: assetDetailImageGenerateSweep 1.55s ease-in-out infinite; }.asset-detail-empty.is-generating { position: relative; overflow: hidden; border-color: #ffffff24; }.asset-detail-empty.is-generating > svg,.asset-detail-empty.is-generating > span { position: relative; z-index: 2; }.asset-detail-zoom-hint { z-index: 2; }
@keyframes assetDetailImageGenerateSweep { 0% { opacity: 0; transform: translateX(-140%) skewX(-12deg); } 18%,78% { opacity: .9; } 100% { opacity: 0; transform: translateX(440%) skewX(-12deg); } }
.asset-detail-audio-player { display: grid; width: 100%; min-height: 76px; box-sizing: border-box; grid-template-columns: 42px minmax(0,1fr) auto 18px; align-items: center; gap: 12px; margin: auto 0; padding: 14px 16px; border: 1px solid #383838; border-radius: 14px; background: linear-gradient(135deg,#202020,#151515); box-shadow: inset 0 1px #ffffff08,0 12px 30px #0004; }
.asset-detail-audio-player > audio { display: none; }
.asset-detail-audio-toggle { display: grid; width: 42px; height: 42px; place-items: center; padding: 0; border: 1px solid #555; border-radius: 50%; color: #151515; background: #f0f0f0; cursor: pointer; transition: background .16s ease,transform .16s ease; }
.asset-detail-audio-toggle:hover { background: #fff; transform: scale(1.04); }
.asset-detail-audio-toggle svg { width: 19px; height: 19px; fill: currentColor; stroke: none; }
.asset-detail-audio-copy { display: grid; min-width: 0; gap: 10px; }
.asset-detail-audio-copy > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.asset-detail-audio-copy strong { color: #ddd; font-size: 12px; }
.asset-detail-audio-copy span { color: #777; font-size: 11px; }
.asset-detail-audio-copy input { width: 100%; height: 4px; margin: 0; appearance: none; border-radius: 999px; outline: 0; background: linear-gradient(90deg,#ddd var(--audio-progress),#424242 var(--audio-progress)); cursor: pointer; }
.asset-detail-audio-copy input::-webkit-slider-thumb { width: 12px; height: 12px; appearance: none; border: 2px solid #171717; border-radius: 50%; background: #f1f1f1; box-shadow: 0 1px 5px #0009; }
.asset-detail-audio-copy input::-moz-range-thumb { width: 9px; height: 9px; border: 2px solid #171717; border-radius: 50%; background: #f1f1f1; }
.asset-detail-audio-player time { color: #999; font: 11px/1.2 Consolas,monospace; white-space: nowrap; }
.asset-detail-audio-volume { width: 18px; fill: none; stroke: #888; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.asset-detail-media-actions { display: flex; align-items: center; justify-content: center; gap: 8px; }.asset-detail-media-actions button { display: grid; width: 42px; height: 42px; padding: 0; place-items: center; border: 1px solid #3f3f3f; border-radius: 11px; color: #aaa; background: #232323; cursor: pointer; transition: border-color .16s ease,color .16s ease,background .16s ease,transform .16s ease; }.asset-detail-media-actions button:hover:not(:disabled) { border-color: #666; color: #eee; background: #303030; transform: translateY(-1px); }.asset-detail-media-actions button:focus-visible { outline: 2px solid #aaa; outline-offset: 2px; }.asset-detail-media-actions button:disabled { cursor: wait; opacity: .5; }.asset-detail-media-actions svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }.asset-detail-media-actions .asset-detail-generate-media { border-color: #ddd; color: #151515; background: #e5e5e5; }.asset-detail-media-actions .asset-detail-generate-media:hover:not(:disabled) { border-color: #fff; color: #080808; background: #fff; }.asset-detail-media-actions .asset-detail-clear-image:hover:not(:disabled) { border-color: #70444a; color: #e59aa2; background: #302124; }
.asset-detail-fields { display: grid; min-width: 0; align-content: start; gap: 14px; }.asset-detail-fields > label { display: grid; gap: 7px; }.asset-detail-fields > label > span { color: #aaa; font-size: 14px; }.asset-detail-fields input,.asset-detail-fields textarea { width: 100%; box-sizing: border-box; padding: 10px 11px; border: 1px solid #3b3b3b; border-radius: 9px; outline: 0; color: #ddd; background: #101010; font: 14px/1.6 inherit; }.asset-detail-fields textarea { resize: vertical; scrollbar-width: thin; scrollbar-color: #555 transparent; }.asset-detail-fields input:focus,.asset-detail-fields textarea:focus { border-color: #707070; box-shadow: 0 0 0 3px #ffffff08; }.asset-detail-fields details { overflow: hidden; border: 1px solid #363636; border-radius: 10px; background: #121212; }.asset-detail-fields summary { padding: 10px 12px; color: #999; cursor: pointer; font-size: 14px; }.asset-detail-fields pre { max-height: 210px; margin: 0; padding: 12px; overflow: auto; border-top: 1px solid #303030; color: #8f9aa5; font: 12px/1.6 Consolas,monospace; white-space: pre-wrap; word-break: break-word; }.asset-detail-error { margin: 0; color: #d99999; font-size: 13px; }
.asset-detail-fields textarea[readonly] { border-color: #333; color: #c8c8c8; background: #171717; cursor: default; }
.asset-detail-default-prompt { display: grid; gap: 7px; }.asset-detail-default-prompt-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.asset-detail-default-prompt-head > span { color: #aaa; font-size: 14px; }.asset-detail-default-prompt-head button { position: relative; width: 38px; height: 22px; flex: 0 0 38px; padding: 0; border: 1px solid #585858; border-radius: 999px; outline: 0; background: #2a2a2a; cursor: pointer; transition: border-color .18s ease,background .18s ease; }.asset-detail-default-prompt-head button i { position: absolute; top: 3px; left: 3px; width: 14px; height: 14px; border-radius: 50%; background: #888; transition: left .18s ease,background .18s ease; }.asset-detail-default-prompt-head button[aria-checked="true"] { border-color: #d8d8d8; background: #e7e7e7; }.asset-detail-default-prompt-head button[aria-checked="true"] i { left: 19px; background: #171717; }.asset-detail-default-prompt-head button:focus-visible { box-shadow: 0 0 0 3px #ffffff24; }.asset-detail-default-prompt textarea { transition: opacity .18s ease,border-color .18s ease; }.asset-detail-default-prompt small { color: #777; font-size: 12px; line-height: 1.5; }.asset-detail-default-prompt.disabled textarea { opacity: .42; }.asset-detail-default-prompt.disabled small { color: #9a8587; }
.asset-detail-dialog > footer { display: flex; justify-content: flex-end; gap: 9px; padding: 16px 25px 22px; border-top: 1px solid #303030; }.asset-detail-dialog > footer button { min-height: 40px; padding: 0 17px; border-radius: 9px; cursor: pointer; font-size: 14px; }.asset-detail-secondary { border: 1px solid #444; color: #bbb; background: #232323; }.asset-detail-secondary:hover:not(:disabled) { color: #fff; background: #303030; }.asset-detail-secondary:disabled { cursor: not-allowed; opacity: .35; }.asset-detail-save { border: 1px solid #eee; color: #111; background: #eee; font-weight: 700; }.asset-detail-save:hover { background: #fff; }

/* Readability scale for the desktop workbench. */
.video-workbench-head > div > span,.asset-rail-head span,.storyboard-column-head span { font-size: 12px; }
.video-workbench-head p { font-size: 14px; }.video-workbench-head > button { height: 42px; font-size: 13px; }
.asset-rail-head h2,.storyboard-column-head h2 { font-size: 19px; }.asset-rail-head b,.storyboard-column-head b { font-size: 13px; }
.asset-category-tabs button { height: 56px; font-size: 14px; }.asset-category-tabs svg { width: 18px; height: 18px; }
.asset-json-import strong { font-size: 14px; }.asset-json-import small { font-size: 12px; }
.asset-generator-error,.asset-card-error { font-size: 12px; }.asset-rail-state { font-size: 14px; line-height: 1.7; }
.asset-missing-preview span { font-size: 13px; }.asset-pick-copy strong { font-size: 13px; }.asset-pick-copy small { font-size: 12px; }.asset-card-generate { height: 34px; font-size: 13px; }
.shot-number { font-size: 13px; }.storyboard-card-head input { font-size: 14px; }.shot-content-head span,.shot-result > header span { font-size: 12px; }.shot-content-head strong,.shot-result > header strong { font-size: 13px; }
.reference-add small,.reference-card > small { font-size: 12px; }.storyboard-compose textarea { font-size: 14px; line-height: 1.7; }
.storyboard-toolbar { position: relative; z-index: 8; gap: 12px; overflow: visible; font-size: 14px; }.storyboard-toolbar button { font-size: 14px; }.storyboard-toolbar .shot-submit { flex: 0 0 34px; }
.shot-result > header small { font-size: 12px; }.shot-result-empty strong,.shot-result-progress strong,.shot-result-error strong,.shot-result-complete strong { font-size: 13px; }.shot-result-empty small,.shot-result-progress small,.shot-result-error span,.shot-result-complete span { font-size: 13px; line-height: 1.5; }.shot-result-error button,.shot-result-player a { font-size: 13px; }
@keyframes result-spin { to { transform: rotate(360deg); } }
@media (max-width: 1450px) { .shot-body-grid { grid-template-columns: 1fr; }.shot-content { border-right: 0; border-bottom: 1px solid #2e2e2e; border-bottom-left-radius: 0; }.shot-content:not(.expanded) .storyboard-toolbar { border-bottom-left-radius: 0; }.shot-result { min-height: 250px; } }
@media (max-width: 1100px) { .video-workbench-layout { grid-template-columns: 220px minmax(0,1fr); }.storyboard-toolbar { gap: 6px; }.storyboard-toolbar span:nth-of-type(2) { display: none; } }
@media (max-width: 720px) { .json-import-backdrop { padding: 12px; }.json-import-dialog { width: calc(100vw - 24px); max-height: calc(100vh - 24px); }.json-import-dialog > header,.json-import-editor { padding-right: 18px; padding-left: 18px; }.json-import-dialog > footer { grid-template-columns: 1fr 1fr; padding-right: 18px; padding-left: 18px; }.json-file-button { grid-column: 1 / -1; }.json-import-textarea { min-height: 230px; } }
@media (max-width: 820px) { .asset-detail-backdrop { padding: 12px; }.asset-detail-dialog { width: calc(100vw - 24px); max-height: calc(100vh - 24px); }.asset-detail-body { grid-template-columns: 1fr; }.asset-detail-image-preview,.asset-detail-image-preview > img,.asset-detail-empty { min-height: 240px; max-height: 360px; } }

/* Cinematic production workspace redesign. */
.video-project-hub,.video-workbench {
  --studio-accent: #37d8f2;
  --studio-accent-rgb: 55,216,242;
  --studio-pink: #f472b6;
  --studio-bg: #0b0d13;
  --studio-surface: #12151d;
  --studio-surface-raised: #171b25;
  --studio-border: rgba(255,255,255,.09);
  --studio-border-strong: rgba(255,255,255,.15);
  --studio-text: #f3f5f8;
  --studio-muted: #969eac;
  --studio-dim: #697180;
}
.video-project-hub { padding-top: 28px; }
.video-project-workspace-head { position: relative; display: flex; min-height: 176px; box-sizing: border-box; align-items: center; justify-content: space-between; gap: 38px; overflow: hidden; padding: 30px clamp(26px,4vw,50px); border: 1px solid #333; border-radius: 22px; background: #191919; box-shadow: 0 22px 60px #00000024; }
.video-project-workspace-head::before { position: absolute; inset: 0; opacity: .32; background-image: radial-gradient(circle,#454545 1px,transparent 1px); background-size: 18px 18px; content: ''; mask-image: linear-gradient(90deg,transparent 22%,#000 54%,transparent 92%); }
.video-project-head-copy,.video-project-head-actions { position: relative; z-index: 3; }
.video-project-head-copy { min-width: 300px; }
.video-project-head-copy > span { color: #2eddff; font: 800 12px/1 monospace; letter-spacing: .18em; }
.video-project-head-copy > div { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.video-project-head-copy h1 { margin: 0; color: #f3f3f3; font-size: 30px; letter-spacing: -.04em; }
.video-project-head-copy b { padding: 3px 8px; border: 1px solid #3b3b3b; border-radius: 99px; color: #999; font-size: 12px; }
.video-project-head-copy p { margin: 13px 0 0; color: #a6a6a6; font-size: 13px; line-height: 1.55; }
.video-project-head-actions { display: flex; align-items: center; gap: 10px; padding: 7px; border: 1px solid #393939; border-radius: 14px; background: #222222e6; box-shadow: 0 12px 30px #0003; backdrop-filter: blur(12px); }
.video-project-search { display: flex; width: clamp(190px,20vw,280px); height: 40px; align-items: center; gap: 10px; padding: 0 14px; border: 1px solid #3b3b3b; border-radius: 22px; background: #1a1a1a; }
.video-project-search:focus-within { border-color: #5c5c5c; }
.video-project-search svg { width: 17px; flex: 0 0 auto; fill: none; stroke: #787878; stroke-width: 1.7; }
.video-project-search input { min-width: 0; flex: 1; border: 0; outline: 0; color: #eee; background: transparent; font-size: 14px; }
.video-project-search input::placeholder { color: #929292; opacity: 1; }
.video-project-new-button { display: inline-flex; height: 40px; align-items: center; gap: 7px; padding: 0 14px; border: 1px solid #494949; border-radius: 10px; color: #fff; background: #252525; cursor: pointer; font-size: 13px; font-weight: 700; }
.video-project-new-button:hover,.video-project-new-button:focus-visible { border-color: #45d7ff; outline: 0; background: #2b2b2b; }
.video-project-new-button svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.video-project-head-art { position: absolute; z-index: 1; top: 24px; left: 51%; width: 250px; height: 130px; opacity: .46; transform: translateX(-50%); pointer-events: none; }
.video-project-head-art > svg { position: absolute; inset: 0; width: 100%; height: 100%; fill: none; stroke: #328ca3; stroke-width: 1.4; }
.video-project-hero-script,.video-project-hero-shot { position: absolute; z-index: 2; display: block; border: 1px solid #404040; background: #1d1d1d; box-shadow: 0 7px 18px #0005; }
.video-project-hero-script { top: 27px; left: 18px; width: 72px; height: 78px; padding: 21px 11px 8px; border-radius: 8px; transform: rotate(-3deg); }
.video-project-hero-script::before { position: absolute; top: 10px; left: 11px; width: 26px; height: 4px; border-radius: 4px; background: #45d7ff; content: ''; }
.video-project-hero-script i { display: block; height: 3px; margin-top: 8px; border-radius: 3px; background: #454545; }.video-project-hero-script i:nth-child(2) { width: 78%; }.video-project-hero-script i:nth-child(3) { width: 57%; }
.video-project-hero-shot { right: 20px; width: 67px; height: 43px; }.video-project-hero-shot::before { position: absolute; inset: 6px; border-radius: 4px; background: #2d2d2d; content: ''; }.video-project-hero-shot-top { top: 10px; }.video-project-hero-shot-bottom { bottom: 9px; border-color: #643b50; }
.video-project-create-card { min-width: 0; overflow: hidden; border: 1px solid #353535; border-radius: 18px; background: #1b1b1b; box-shadow: 0 8px 30px #00000014; transition: border-color .2s ease,transform .2s ease; }
.video-project-create-card:hover { border-color: #515151; transform: translateY(-2px); }
.video-project-create-card > button { display: flex; width: 100%; aspect-ratio: 16/9; align-items: center; justify-content: center; flex-direction: column; gap: 12px; border: 0; border-bottom: 1px solid #313131; color: #f1f1f1; background: radial-gradient(circle at 50% 45%,#222,#191919 70%); cursor: pointer; }
.video-project-create-card > button > strong { font-size: 15px; }
.video-project-new-visual { position: relative; display: block; width: 132px; height: 65px; }
.video-project-new-script,.video-project-new-frame { position: absolute; display: block; border: 1px solid #444; background: #1d1d1d; box-shadow: 0 7px 15px #0005; transition: .18s ease; }
.video-project-new-script { top: 10px; left: 2px; width: 50px; height: 54px; box-sizing: border-box; padding: 16px 9px 7px; border-radius: 7px; transform: rotate(-4deg); }.video-project-new-script::before { position: absolute; top: 8px; left: 9px; width: 14px; height: 3px; border-radius: 3px; background: #f2f2f2; content: ''; }.video-project-new-script i { display: block; width: 100%; height: 3px; margin-top: 5px; border-radius: 3px; background: #444; }.video-project-new-script i:nth-child(2) { width: 80%; }.video-project-new-script i:nth-child(3) { width: 58%; }
.video-project-new-frame { top: 12px; right: 0; width: 66px; height: 45px; box-sizing: border-box; padding: 5px; border-radius: 7px; transform: rotate(3deg); }.video-project-new-frame i { display: block; width: 100%; height: 100%; border-radius: 4px; background: linear-gradient(145deg,#2e3840 55%,#5a354b 56%); }.video-project-new-frame b { position: absolute; top: 8px; right: 8px; width: 5px; height: 5px; border-radius: 50%; background: #ffd469; }
.video-project-new-plus { position: absolute; z-index: 3; top: 18px; left: 49px; display: grid; width: 39px; height: 39px; place-items: center; border: 3px solid #191919; border-radius: 50%; color: #151515; background: #f2f2f2; box-shadow: 0 6px 16px #0006; transition: .18s ease; }.video-project-new-plus svg { width: 21px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }.video-project-create-card > button:hover .video-project-new-plus { transform: rotate(90deg) scale(1.05); }
.video-project-create-card > div { display: flex; height: 88px; align-items: center; justify-content: center; gap: 5px; color: #efefef; font-size: 14px; font-weight: 650; }.video-project-create-card > div svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linecap: round; }
.video-project-create-backdrop { position: fixed; z-index: 220; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; place-items: center; padding: 24px; background: #05070cc9; backdrop-filter: blur(10px); }
.video-project-create-backdrop .video-project-create { width: min(520px,92vw); box-sizing: border-box; padding: 24px; border-color: #343b4d; border-radius: 20px; background: #151925; box-shadow: 0 30px 90px #000b; }
.video-project-create-head > button { display: grid; width: 34px; height: 34px; margin-left: auto; place-items: center; border: 0; color: #778198; background: transparent; cursor: pointer; font-size: 24px; }
.video-project-create-backdrop .video-project-create input,.video-project-create-backdrop .video-project-create textarea { border-color: #30384b; background: #0e121d; }
.video-project-create-backdrop .video-project-create footer { display: flex; justify-content: flex-end; gap: 8px; padding-top: 3px; }
.video-project-create-backdrop .video-project-create footer button { min-height: 38px; padding: 0 14px; border: 1px solid #353c4d; border-radius: 9px; color: #aaa; background: #202635; cursor: pointer; font-size: 12px; }
.video-project-create-backdrop .video-project-create footer button[type=submit] { border: 0; color: #071019; background: linear-gradient(100deg,#2eddff,#71e8ff 48%,#ff64b5 120%); font-weight: 800; }
.video-project-hero { position: relative; isolation: isolate; border-color: var(--studio-border); background: radial-gradient(circle at 8% 0%,rgba(var(--studio-accent-rgb),.13),transparent 32%),radial-gradient(circle at 90% 100%,#f472b615,transparent 35%),linear-gradient(145deg,#161a23,#0d1017 72%); box-shadow: 0 30px 80px #0008,inset 0 1px #ffffff09; }
.video-project-hero::before { position: absolute; z-index: -1; inset: 0; opacity: .25; background-image: linear-gradient(#ffffff08 1px,transparent 1px),linear-gradient(90deg,#ffffff08 1px,transparent 1px); background-size: 36px 36px; mask-image: linear-gradient(100deg,#000,transparent 68%); content: ''; }
.video-project-hub-head > span,.video-project-library > header span { color: var(--studio-accent); }
.video-project-hub-head h1 em { color: transparent; background: linear-gradient(92deg,var(--studio-accent),#b8a7ff 52%,var(--studio-pink)); background-clip: text; }
.video-project-highlights span { border-color: var(--studio-border); color: #b7bec9; background: #ffffff07; }
.video-project-highlights i { background: var(--studio-accent); box-shadow: 0 0 12px rgba(var(--studio-accent-rgb),.65); }
.video-project-create { border-color: var(--studio-border-strong); background: #11151edb; box-shadow: 0 24px 64px #0009,inset 0 1px #ffffff09; }
.video-project-create-head > span,.video-project-create > button { border-color: transparent; color: #081116; background: linear-gradient(105deg,var(--studio-accent),#8be6ee 52%,var(--studio-pink)); box-shadow: 0 12px 30px rgba(var(--studio-accent-rgb),.16); }
.video-project-create input,.video-project-create textarea { border-color: var(--studio-border); background: #0b0e15; }
.video-project-create input:focus,.video-project-create textarea:focus { border-color: rgba(var(--studio-accent-rgb),.65); box-shadow: 0 0 0 3px rgba(var(--studio-accent-rgb),.1); }
.video-project-library > header { align-items: center; padding-bottom: 16px; border-color: #2a2a2a; }
.video-project-grid { grid-template-columns: repeat(4,minmax(0,1fr)); gap: 18px; margin-top: 24px; }
.video-project-card { min-width: 0; overflow: hidden; border: 1px solid #353535; border-radius: 18px; outline: 0; background: #1b1b1b; box-shadow: 0 8px 30px #00000014; transition: border-color .2s ease,transform .2s ease; }
.video-project-card:hover { border-color: #515151; box-shadow: 0 8px 30px #00000014; transform: translateY(-2px); }
.video-project-card:focus-visible { border-color: #45d7ff; box-shadow: 0 0 0 3px #45d7ff1c; }
.video-project-card-body { min-height: 106px; box-sizing: border-box; padding: 13px 14px 11px; background: #1b1b1b; }
.video-project-card-body h2 { min-width: 0; margin: 0; overflow: hidden; color: #f5f5f5; font-size: 15px; line-height: 22px; text-overflow: ellipsis; white-space: nowrap; }
.video-project-card-body > p { margin: 2px 0 0; overflow: hidden; color: #aaa; font-size: 14px; line-height: 19px; text-overflow: ellipsis; white-space: nowrap; }
.video-project-card-body footer { display: flex; min-width: 0; min-height: 0; align-items: center; justify-content: space-between; gap: 8px; margin-top: 7px; padding-top: 7px; border-top: 1px solid #2d2d2d; }
.video-project-card-body time { flex: 0 0 auto; color: #929292; font-size: 13px; }
.video-project-card-body footer span { min-width: 0; height: 20px; padding: 0 7px; overflow: hidden; border: 1px solid #3a3a3a; border-radius: 5px; color: #c2c2c2; background: #222; font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }

.video-workbench { padding: 18px 0 32px; color: var(--studio-text); }
.video-workbench-head { position: relative; align-items: center; margin-bottom: 16px; padding: 20px 22px; overflow: hidden; border: 1px solid var(--studio-border); border-radius: 22px; background: radial-gradient(circle at 8% 0%,rgba(var(--studio-accent-rgb),.1),transparent 34%),linear-gradient(110deg,#161a24,#10131a 72%); box-shadow: 0 18px 48px #0005,inset 0 1px #ffffff08; }
.video-workbench-head::after { position: absolute; top: 0; right: 12%; left: 12%; height: 1px; background: linear-gradient(90deg,transparent,var(--studio-accent),var(--studio-pink),transparent); content: ''; opacity: .65; }
.video-workbench-title { min-width: 0; gap: 0; }
.workbench-breadcrumb { display: flex; align-items: center; gap: 9px; color: var(--studio-dim); font: 700 12px/1 monospace; letter-spacing: .15em; }
.workbench-breadcrumb button { display: inline-flex; min-height: 30px; align-items: center; gap: 4px; margin: 0; padding: 0 7px; border: 0; border-radius: 7px; color: #a7afbd; background: transparent; cursor: pointer; font: inherit; letter-spacing: 0; }
.workbench-breadcrumb button:hover,.workbench-breadcrumb button:focus-visible { color: #fff; background: #ffffff0b; outline: 0; }
.workbench-breadcrumb svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.workbench-breadcrumb > i { width: 3px; height: 3px; border-radius: 50%; background: #525a69; }
.workbench-breadcrumb > span { color: var(--studio-accent); }
.workbench-project-row { display: flex; min-width: 0; align-items: center; gap: 13px; margin-top: 9px; }
.workbench-project-mark { display: grid; width: 42px; height: 42px; flex: 0 0 auto; place-items: center; border: 1px solid rgba(var(--studio-accent-rgb),.22); border-radius: 13px; color: var(--studio-accent); background: rgba(var(--studio-accent-rgb),.08); box-shadow: inset 0 1px #ffffff0a; }
.workbench-project-mark svg { width: 22px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.workbench-project-row > div { display: grid; min-width: 0; gap: 2px; }
.video-workbench-title .workbench-project-row input { width: min(660px,62vw); margin: 0; padding: 0; border: 0; outline: 0; color: var(--studio-text); background: transparent; font: 750 26px/1.2 inherit; letter-spacing: -.035em; }
.video-workbench-title .workbench-project-row .video-project-description { color: var(--studio-muted); font-size: 14px; font-weight: 450; letter-spacing: 0; }
.workbench-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 11px; }
.workbench-meta > span { display: inline-flex; min-height: 24px; box-sizing: border-box; align-items: center; gap: 6px; padding: 0 8px; border: 1px solid var(--studio-border); border-radius: 999px; color: #8e97a7; background: #ffffff05; font-size: 12px; }
.workbench-meta .save-state { color: #99d8ca; }
.workbench-meta .save-state i { width: 6px; height: 6px; border-radius: 50%; background: #58d3ad; box-shadow: 0 0 9px #58d3ad88; }
.video-workbench-head .workbench-add-shot { display: inline-flex; min-width: 128px; height: 44px; align-items: center; justify-content: center; gap: 8px; padding: 0 16px; border: 0; border-radius: 12px; color: #071217; background: linear-gradient(105deg,var(--studio-accent),#8ce4ec 55%,var(--studio-pink)); box-shadow: 0 13px 30px rgba(var(--studio-accent-rgb),.16); font-size: 14px; font-weight: 800; transition: filter .18s ease,transform .18s ease; }
.video-workbench-head .workbench-add-shot:hover { border-color: transparent; background: linear-gradient(105deg,var(--studio-accent),#8ce4ec 55%,var(--studio-pink)); filter: brightness(1.08); transform: translateY(-1px); }
.workbench-add-shot svg { width: 17px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; }

.video-workbench-layout { min-height: calc(100vh - 176px); grid-template-columns: clamp(280px,20vw,330px) minmax(0,1fr); gap: 16px; }
.asset-rail,.storyboard-column { border-color: var(--studio-border); background: var(--studio-surface); box-shadow: 0 18px 48px #0005,inset 0 1px #ffffff07; }
.asset-rail { top: 62px; max-height: calc(100vh - 82px); border-radius: 17px; }
.asset-rail-head,.storyboard-column-head { min-height: 62px; box-sizing: border-box; padding: 14px 16px; }
.asset-rail-head h2,.storyboard-column-head h2 { color: var(--studio-text); }
.asset-rail-head b,.storyboard-column-head b { color: #aab2c0; background: #ffffff0a; }
.asset-rail-head span,.storyboard-column-head span { color: var(--studio-accent); }
.asset-category-tabs { gap: 4px; margin: 0 10px 10px; border: 1px solid #ffffff08; background: #0b0e14; }
.asset-category-tabs button { position: relative; height: 52px; color: #7c8594; transition: color .16s ease,background .16s ease; }
.asset-category-tabs button:hover { color: #dfe4eb; background: #ffffff08; }
.asset-category-tabs button.active { color: var(--studio-accent); background: rgba(var(--studio-accent-rgb),.1); box-shadow: inset 0 0 0 1px rgba(var(--studio-accent-rgb),.08); }
.asset-category-tabs button.active::after { position: absolute; right: 13px; bottom: 2px; left: 13px; height: 2px; border-radius: 2px; background: var(--studio-accent); content: ''; box-shadow: 0 0 8px rgba(var(--studio-accent-rgb),.55); }
.asset-generator { border-color: var(--studio-border); background: #0d1017; }
.asset-json-import { min-height: 54px; border-color: rgba(var(--studio-accent-rgb),.24); color: #d7dce4; background: rgba(var(--studio-accent-rgb),.045); }
.asset-json-import:hover { border-color: rgba(var(--studio-accent-rgb),.55); background: rgba(var(--studio-accent-rgb),.08); }
.asset-json-import > span { color: var(--studio-accent); background: rgba(var(--studio-accent-rgb),.12); }
.asset-json-import > span svg { width: 16px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.asset-json-import small { color: #727b8a; }
.asset-generator { --select-accent: var(--studio-accent); --select-border: rgba(255,255,255,.1); --select-border-hover: rgba(var(--studio-accent-rgb),.35); --select-border-focus: rgba(var(--studio-accent-rgb),.62); --select-bg: #11151d; --select-bg-hover: #151a23; --select-bg-focus: #151a23; --select-menu-border: rgba(255,255,255,.12); --select-menu-bg: #141821fa; --select-focus-ring: rgba(var(--studio-accent-rgb),.1); }
.asset-rail-scroll { max-height: calc(100vh - 376px); }
.asset-pick-card { border-color: var(--studio-border); border-radius: 11px; background: #181c25; transition: border-color .18s ease,transform .18s ease,box-shadow .18s ease; }
.asset-pick-card:hover { border-color: rgba(var(--studio-accent-rgb),.38); box-shadow: 0 10px 24px #0007; }
.asset-preview-button,.asset-preview-button > img,.asset-audio-placeholder { background: #0a0c11; }
.asset-missing-preview { color: #687180; background: repeating-linear-gradient(135deg,#10131a,#10131a 8px,#141821 8px,#141821 16px); }
.asset-pick-copy strong { color: #e8ebef; }
.asset-card-add { border-color: #171b24; color: #071217; background: var(--studio-accent); }
.asset-card-generate { min-height: 34px; border-color: rgba(var(--studio-accent-rgb),.18); color: #b8e9f0; background: rgba(var(--studio-accent-rgb),.08); }
.asset-card-generate:hover:not(:disabled) { border-color: rgba(var(--studio-accent-rgb),.42); background: rgba(var(--studio-accent-rgb),.14); }
.asset-card-generate > svg { width: 13px; fill: none; stroke: currentColor; stroke-width: 1.7; }

.storyboard-column { border: 0; background: transparent; box-shadow: none; }
.storyboard-column-head { margin-bottom: 10px; border: 1px solid var(--studio-border); border-radius: 15px; background: var(--studio-surface); box-shadow: inset 0 1px #ffffff07; }
.storyboard-card { --shot-card-radius: 18px; margin: 0 0 14px; overflow: visible; border-color: var(--studio-border); border-radius: 18px; background: linear-gradient(145deg,#171b24,#11141b); box-shadow: 0 16px 42px #0005,inset 0 1px #ffffff07; }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: rgba(var(--studio-accent-rgb),.38); box-shadow: 0 18px 48px #0007,0 0 0 3px rgba(var(--studio-accent-rgb),.07); }
.storyboard-card-head { height: 48px; padding: 0 15px; border-color: var(--studio-border); background: linear-gradient(90deg,rgba(var(--studio-accent-rgb),.045),transparent 36%); border-radius: 18px 18px 0 0; }
.shot-number { display: grid; min-width: 28px; height: 24px; place-items: center; border: 1px solid rgba(var(--studio-accent-rgb),.18); border-radius: 7px; color: var(--studio-accent); background: rgba(var(--studio-accent-rgb),.07); }
.storyboard-card-head input { color: #eef1f5; }
.shot-content { border-color: var(--studio-border); }
.shot-content-head,.shot-result > header { border-color: var(--studio-border); background: #11151c; }
.shot-content-head span,.shot-result > header span { color: #6e7889; }
.shot-content-head strong,.shot-result > header strong { color: #dfe4eb; }
.storyboard-compose { min-height: 138px; padding: 16px; }
.reference-add { border-color: rgba(var(--studio-accent-rgb),.22); color: #8793a4; background: rgba(var(--studio-accent-rgb),.035); }
.reference-add:hover { border-color: rgba(var(--studio-accent-rgb),.5); color: var(--studio-accent); background: rgba(var(--studio-accent-rgb),.08); }
.reference-card { border-color: var(--studio-border-strong); background: #151923; }
.reference-stack-add { border-color: #141820; color: #071217; background: var(--studio-accent); }
.storyboard-compose textarea { padding: 8px 10px; border: 1px solid transparent; border-radius: 10px; color: #dce1e8; background: #0c0f15; transition: border-color .18s ease,box-shadow .18s ease; }
.storyboard-compose textarea:focus { border-color: rgba(var(--studio-accent-rgb),.36); box-shadow: 0 0 0 3px rgba(var(--studio-accent-rgb),.06); }
.storyboard-toolbar { min-height: 52px; gap: 5px; padding: 8px 10px; border-color: var(--studio-border); background: #0e1118; border-radius: 0 0 0 18px; }
.storyboard-toolbar > button,.storyboard-toolbar .toolbar-popover-wrap > button { min-height: 30px; padding: 0 8px; border: 1px solid transparent; border-radius: 8px; color: #8e97a6; }
.storyboard-toolbar > button:hover,.storyboard-toolbar .toolbar-popover-wrap > button:hover { border-color: #ffffff0c; color: #eef1f5; background: #ffffff08; }
.storyboard-toolbar .shot-clear { margin-left: auto; color: #77808e; }
.storyboard-toolbar .shot-submit { display: inline-flex; width: auto; min-width: 108px; height: 36px; flex: 0 0 auto; align-items: center; justify-content: center; gap: 7px; padding: 0 13px; border: 0; border-radius: 10px; color: #071217; background: linear-gradient(105deg,var(--studio-accent),#8ce4ec 58%,var(--studio-pink)); box-shadow: 0 9px 24px rgba(var(--studio-accent-rgb),.14); }
.storyboard-toolbar .shot-submit:hover { color: #071217; background: linear-gradient(105deg,var(--studio-accent),#a0edf2 58%,var(--studio-pink)); filter: brightness(1.05); }
.storyboard-toolbar .shot-submit strong { font-size: 13px; }
.storyboard-toolbar .shot-submit .asset-generate-spinner { border-color: #07121744; border-top-color: #071217; }
.mode-popover,.settings-popover { border-color: var(--studio-border-strong); color: #dce1e8; background: #171b24f7; box-shadow: 0 22px 58px #000d,inset 0 1px #ffffff09; backdrop-filter: blur(18px); }
.ratio-options,.segmented-options,.duration-options,.count-options { border-color: var(--studio-border); background: #0d1016; }
.storyboard-toolbar .ratio-options button:hover,.storyboard-toolbar .ratio-options button.active,.storyboard-toolbar .segmented-options button:hover,.storyboard-toolbar .segmented-options button.active,.storyboard-toolbar .duration-options button:hover,.storyboard-toolbar .duration-options button.active,.storyboard-toolbar .count-options button:hover,.storyboard-toolbar .count-options button.active { color: #071217; background: var(--studio-accent); }
.shot-result { margin: 14px; border-color: var(--studio-border); background: #0b0e13; }
.shot-result-player { background: radial-gradient(circle at 50% 32%,#1a2330,#07090e 58%,#030405 100%); }
.shot-result-empty { color: #778191; background: radial-gradient(circle at 50% 45%,#19202b,#0b0e13 68%); }
.shot-result-empty > span { border-color: rgba(var(--studio-accent-rgb),.16); color: var(--studio-accent); background: rgba(var(--studio-accent-rgb),.06); }
.shot-result-empty svg { stroke: currentColor; }
.shot-result-progress > i em { background: var(--studio-accent); box-shadow: 0 0 12px rgba(var(--studio-accent-rgb),.45); }
.result-spinner { border-color: #26303d; border-top-color: var(--studio-accent); }

@media (max-width: 1450px) { .video-project-grid { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@media (max-width: 1180px) { .video-project-head-art { display: none; }.video-project-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 900px) { .video-project-workspace-head { align-items: flex-start; flex-direction: column; gap: 22px; }.video-project-head-actions { width: 100%; }.video-project-search { width: auto; flex: 1; }.video-project-new-button { justify-content: center; }.video-project-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 1280px) {
  .video-workbench-layout { grid-template-columns: 260px minmax(0,1fr); }
  .asset-rail-grid { grid-template-columns: 1fr; }
  .asset-preview-button > img,.asset-audio-placeholder,.asset-missing-preview { aspect-ratio: 16/10; }
  .storyboard-toolbar { flex-wrap: wrap; }
  .storyboard-toolbar .shot-clear { margin-left: 0; }
  .storyboard-toolbar .shot-submit { margin-left: auto; }
}
@media (max-width: 940px) {
  .video-workbench-head { align-items: stretch; flex-direction: column; }
  .video-workbench-head .workbench-add-shot { width: 100%; }
  .video-workbench-layout { grid-template-columns: 1fr; }
  .asset-rail { position: relative; top: auto; max-height: none; }
  .asset-rail-scroll { max-height: 360px; }
  .asset-rail-grid { grid-template-columns: 1fr; }
  .video-workbench-title .workbench-project-row input { width: min(100%,70vw); }
}
@media (max-width: 680px) {
  .video-project-grid { grid-template-columns: 1fr; }
  .video-workbench-head { padding: 16px; border-radius: 16px; }
  .workbench-project-mark { display: none; }
  .video-workbench-title .workbench-project-row input { width: 100%; font-size: 22px; }
  .asset-rail-grid { grid-template-columns: 1fr; }
  .shot-body-grid { grid-template-columns: 1fr; }
  .storyboard-toolbar .shot-submit { width: 100%; margin-left: 0; }
}

/* Match the established project list and project detail layouts. */
.video-project-grid { align-items: start; }
.video-project-create-card > button { height: 172px; aspect-ratio: auto; }
.video-project-create-card > div { height: 60px; }
.video-project-card { border-radius: 12px; background: #1c1c1c; }
.video-project-card:hover { border-color: #4b4b4b; transform: translateY(-2px); }
.video-project-card-body { display: flex; min-height: 232px; padding: 20px 20px 16px; flex-direction: column; background: #1c1c1c; }
.video-project-card-body > header { display: flex; align-items: center; justify-content: space-between; color: #747474; }
.video-project-card-body > header span { color: #45d7ff; font: 800 12px/1 monospace; letter-spacing: .14em; }
.video-project-card-body > header svg { width: 17px; fill: none; stroke: #777; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; transition: transform .18s ease,stroke .18s ease; }
.video-project-card:hover .video-project-card-body > header svg { stroke: #45d7ff; transform: translateX(2px); }
.video-project-card-body h2 { margin-top: 16px; font-size: 18px; line-height: 24px; }
.video-project-card-body > p { min-height: 44px; margin: 4px 0 0; color: #8c8c8c; line-height: 20px; white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.video-project-card-stats { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: 14px; padding: 11px 0; border-top: 1px solid #303030; border-bottom: 1px solid #303030; }
.stat-pills { display: flex; gap: 5px; min-width: 0; }
.stat-pill { display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 7px; border-radius: 6px; background: #232323; transition: background .18s ease; flex: 0 0 auto; }
.stat-pill-asset { --stat-rgb: 69,215,255; }
.stat-pill-shot { --stat-rgb: 184,167,255; }
.stat-pill-running { --stat-rgb: 90,224,138; }
.stat-pill:hover { background: #2a2a2a; }
.stat-dot { width: 5px; height: 5px; border-radius: 50%; background: rgba(var(--stat-rgb),.95); box-shadow: 0 0 5px rgba(var(--stat-rgb),.4); flex: 0 0 auto; }
.stat-pill b { color: #f0f0f0; font-size: 12px; font-weight: 700; line-height: 1; }
.stat-pill small { color: #8a8a8a; font-size: 10px; line-height: 1; }
.video-project-finished-stat { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; height: 40px; padding: 0 10px; border: 1px solid rgba(255,255,255,.14); border-radius: 8px; color: #f2f2f2; background: linear-gradient(135deg,rgba(255,255,255,.075),rgba(255,255,255,.025)); box-shadow: inset 0 1px 0 rgba(255,255,255,.035); cursor: pointer; text-align: left; transition: border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .18s ease; }
.video-project-finished-copy { white-space: nowrap; }
.video-project-finished-copy b { color: #f3f3f3; font-size: 14px; font-weight: 800; line-height: 1; margin-right: 3px; }
.video-project-finished-copy small { color: #a8a8a8; font-size: 11px; line-height: 1; }
.video-project-finished-arrow { width: 13px; flex: 0 0 auto; fill: none; stroke: #d9d9d9; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; transition: transform .18s ease; }
.video-project-finished-stat:hover .video-project-finished-arrow,.video-project-finished-stat:focus-visible .video-project-finished-arrow { transform: translateX(2px); }
.video-project-finished-stat:hover,.video-project-finished-stat:focus-visible { border-color: rgba(255,255,255,.55); outline: 0; background: linear-gradient(135deg,rgba(255,255,255,.18),rgba(255,255,255,.075)); box-shadow: 0 7px 20px rgba(0,0,0,.26),inset 0 1px 0 rgba(255,255,255,.11); transform: translateY(-1px); }
.video-project-finished-stat:active { border-color: rgba(255,255,255,.72); background: rgba(255,255,255,.22); transform: translateY(0); }
.video-project-finished-icon { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 6px; color: #111; background: #ededed; flex: 0 0 auto; }
.video-project-finished-icon svg { width: 12px; fill: currentColor; stroke: none; }
.video-project-finished-copy { display: grid; min-width: 0; gap: 4px; }
.video-project-finished-copy small { overflow: hidden; color: #f3f3f3; font-size: 12px; font-weight: 650; line-height: 1.05; text-overflow: ellipsis; white-space: nowrap; }
.video-project-finished-copy b { overflow: hidden; margin: 0; color: #aaa; font: 10px/1.05 Consolas,monospace; text-overflow: ellipsis; white-space: nowrap; }
.video-project-finished-arrow { width: 15px; fill: none; stroke: #d9d9d9; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; transition: transform .18s ease; }
.video-project-finished-stat:hover .video-project-finished-arrow,.video-project-finished-stat:focus-visible .video-project-finished-arrow { transform: translateX(2px); }
.video-project-card-body footer { margin-top: auto; padding-top: 11px; border: 0; }
.video-project-card-body footer span { height: auto; padding: 0; border: 0; color: #d7d7d7; background: transparent; font-size: 12px; }

.video-workbench {
  display: flex;
  width: 100%;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  box-sizing: border-box;
  flex-direction: column;
  padding: 20px 28px 0;
  overflow: hidden;
  color: #e8e8e8;
  background: transparent;
}
.video-workbench-head {
  position: static;
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  gap: 16px;
  margin: 0 0 18px;
  padding: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.video-workbench-head::after { display: none; }
.workbench-back {
  display: inline-flex;
  height: 32px;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  padding: 0 10px;
  border: 1px solid #383838;
  border-radius: 7px;
  color: #aaa;
  background: #202020;
  cursor: pointer;
  font-size: 13px;
}
.workbench-back:hover { border-color: #555; color: #fff; background: #292929; }
.workbench-back svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.video-workbench-title { display: grid; min-width: 0; flex: 1; gap: 7px; }
.video-workbench-title .workbench-project-name { width: min(680px,70vw); margin: 0; padding: 0; border: 0; outline: 0; color: #f2f2f2; background: transparent; font: 750 25px/32px inherit; letter-spacing: -.035em; }
.workbench-meta { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 7px; margin: 0; }
.workbench-meta > span { min-height: 22px; padding: 0 7px; border-color: #363636; color: #858585; background: #202020; }
.workbench-meta .video-project-description { width: min(340px,30vw); min-width: 150px; height: 22px; padding: 0 7px; border: 1px solid transparent; border-radius: 5px; outline: 0; color: #929292; background: transparent; font-size: 12px; }
.workbench-meta .video-project-description:hover,.workbench-meta .video-project-description:focus { border-color: #393939; background: #1d1d1d; }
.workbench-head-actions { display: flex; width: 116px; flex: 0 0 116px; flex-direction: column; gap: 5px; }
.workbench-save-status { display: inline-flex; height: 18px; align-items: center; justify-content: center; gap: 5px; overflow: hidden; color: #777; font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.workbench-save-status i { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: #777; }
.workbench-save-status.saved { color: #8f8f8f; }.workbench-save-status.saved i { background: #aaa; }
.workbench-save-status.saving { color: #bbb; }.workbench-save-status.saving i { border: 1px solid #aaa; border-top-color: transparent; background: transparent; animation: result-spin .8s linear infinite; }
.workbench-save-status.pending { color: #a7a7a7; }.workbench-save-status.pending i { background: #ccc; }
.workbench-save-status.error { color: #e19595; }.workbench-save-status.error i { background: #d46f6f; }
.video-workbench-head .workbench-add-shot {
  display: inline-flex;
  min-width: 0;
  height: 34px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 2px;
  padding: 0 12px;
  border: 1px solid #289db2;
  border-radius: 7px;
  color: #071417;
  background: #45d7ff;
  box-shadow: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 750;
}
.video-workbench-head .workbench-add-shot:hover { border-color: #61e0ff; background: #61e0ff; filter: none; transform: none; }
.video-workbench-layout { display: grid; flex: 1; min-height: 0; grid-template-columns: 280px minmax(0,1fr); grid-template-rows: minmax(0,1fr); align-items: stretch; gap: 18px; overflow: hidden; }
.asset-rail {
  position: relative;
  top: 0;
  z-index: 30;
  display: flex;
  height: 100%;
  min-height: 0;
  max-height: 100%;
  flex-direction: column;
  overflow: visible;
  border: 1px solid #383838;
  border-radius: 9px;
  background: #1c1c1c;
  box-shadow: none;
}
.asset-rail-head,.storyboard-column-head { height: 52px; min-height: 52px; box-sizing: border-box; flex: 0 0 52px; padding: 0 14px; border-color: #343434; }
.asset-rail-head > div:first-child,.storyboard-column-head > div { display: flex; min-width: 0; align-items: center; gap: 9px; }
.asset-rail-head > div:first-child > span,.storyboard-column-head > div > span { padding: 3px 6px; border: 1px solid #343434; border-radius: 999px; color: #7e8790; background: #202020; font-size: 8px; letter-spacing: .12em; white-space: nowrap; }
.asset-rail-head h2,.storyboard-column-head h2 { margin: 0; color: #e8e8e8; font-size: 17px; line-height: 1; }
.asset-rail-head > .asset-rail-head-actions > b,.storyboard-column-head > b { display: grid; min-width: 26px; height: 26px; box-sizing: border-box; place-items: center; padding: 0 7px; border-radius: 999px; color: #929292; background: #252525; font-size: 11px; white-space: nowrap; }
.asset-rail-head-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; }
.asset-actions-wrap { position: relative; }
.asset-actions-wrap::after { position: absolute; top: 0; left: 100%; width: 12px; height: 44px; content: ''; }
.asset-actions-trigger { display: grid; width: 30px; height: 30px; place-items: center; padding: 0; border: 1px solid #363636; border-radius: 8px; color: #8c8c8c; background: #222; cursor: pointer; transition: border-color .16s ease,color .16s ease,background .16s ease; }
.asset-actions-trigger:hover,.asset-actions-trigger.active { border-color: #565656; color: #f0f0f0; background: #2b2b2b; }
.asset-actions-trigger svg { width: 17px; height: 17px; fill: currentColor; }
.asset-actions-popover { position: absolute; z-index: 80; top: -1px; right: auto; left: calc(100% + 12px); display: grid; width: 320px; max-height: calc(100vh - 110px); box-sizing: border-box; gap: 10px; padding: 13px; overflow-y: auto; overscroll-behavior: contain; border: 1px solid #424242; border-radius: 14px; color: #d8d8d8; background: #1c1c1cf7; box-shadow: 0 22px 60px #000c,inset 0 1px #ffffff0a; backdrop-filter: blur(14px); scrollbar-width: thin; scrollbar-color: #555 transparent; }
.asset-actions-popover > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 1px 2px 3px; }
.asset-actions-popover > header > div { display: grid; gap: 3px; }
.asset-actions-popover > header strong { color: #eee; font-size: 13px; }
.asset-actions-popover > header small { color: #777; font-size: 11px; }
.asset-actions-popover > header > span { padding: 4px 7px; border: 1px solid #383838; border-radius: 999px; color: #929292; background: #242424; font: 10px/1 inherit; white-space: nowrap; }
.asset-action-import { display: grid; min-width: 0; min-height: 58px; grid-template-columns: 34px minmax(0,1fr) 16px; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid #343434; border-radius: 10px; color: #d5d5d5; background: #202020; cursor: pointer; text-align: left; }
.asset-action-import:hover { border-color: #505050; background: #262626; }
.asset-action-import > span { display: grid; width: 34px; height: 34px; place-items: center; padding: 0; border: 0; border-radius: 9px; color: #d8d8d8; background: #2d2d2d; }
.asset-action-import > span svg { width: 17px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.asset-action-import > div { display: grid; min-width: 0; gap: 4px; }
.asset-action-import strong { font-size: 12px; }
.asset-action-import small { overflow: hidden; color: #777; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.asset-action-import > svg { width: 15px; fill: none; stroke: #777; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.asset-action-model { display: grid; gap: 7px; padding: 10px; border: 1px solid #333; border-radius: 10px; background: #171717; }
.asset-action-model > span { padding: 0; border: 0; color: #929292; background: transparent; font: 10px/1.2 inherit; letter-spacing: 0; }
.asset-action-model { --select-accent: #f2f2f2; --select-border-hover: #666; --select-border-focus: #e8e8e8; --select-focus-ring: #ffffff10; }
.asset-action-video-engine { display: grid; gap: 7px; margin: 0; padding: 10px; border: 1px solid #333; border-radius: 10px; background: #171717; }
.asset-action-video-engine legend { padding: 0 4px; color: #aaa; font-size: 10px; }
.asset-action-video-engine > small { color: #747474; font-size: 9px; }
.asset-action-video-engine > div { display: grid; grid-template-columns: repeat(2,1fr); gap: 5px; padding: 4px; border-radius: 8px; background: #0e0e0e; }
.asset-action-video-engine button { height: 31px; padding: 0 8px; border: 1px solid transparent; border-radius: 6px; color: #888; background: transparent; cursor: pointer; font-size: 11px; transition: border-color .16s ease,color .16s ease,background .16s ease; }
.asset-action-video-engine button:hover:not(:disabled) { border-color: #444; color: #ddd; background: #242424; }
.asset-action-video-engine button.active { border-color: #e6e6e6; color: #171717; background: #ededed; }
.asset-action-video-engine button:disabled { cursor: not-allowed; opacity: .38; }
.asset-action-video-engine > em { color: #c79272; font-size: 9px; font-style: normal; }
.asset-action-generate-all { display: grid; min-height: 58px; grid-template-columns: 34px minmax(0,1fr) 28px; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid #e4e4e4; border-radius: 10px; color: #171717; background: #ededed; cursor: pointer; text-align: left; }
.asset-action-generate-all:hover:not(:disabled) { background: #fff; }
.asset-action-generate-all:disabled { cursor: wait; opacity: .45; }
.asset-action-generate-all > svg { width: 21px; fill: none; stroke: currentColor; stroke-width: 1.55; }
.asset-action-generate-all > div { display: grid; gap: 3px; }
.asset-action-generate-all strong { font-size: 12px; }
.asset-action-generate-all small { color: #666; font-size: 9px; }
.asset-action-generate-all > b { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 50%; color: #ddd; background: #232323; font-size: 11px; }
.asset-action-library-grid { display: grid; grid-template-columns: 1fr; gap: 7px; }
.asset-action-library-grid > button { display: grid; min-height: 50px; grid-template-columns: 30px minmax(0,1fr); align-items: center; gap: 10px; padding: 7px 10px; border: 1px solid #343434; border-radius: 10px; color: #ccc; background: #202020; cursor: pointer; text-align: left; transition: border-color .16s ease,background .16s ease; }
.asset-action-library-grid > button:hover:not(:disabled) { border-color: #505050; background: #282828; }
.asset-action-library-grid > button:disabled { cursor: wait; opacity: .45; }
.asset-action-library-grid > button > svg { width: 19px; fill: none; stroke: #aaa; stroke-width: 1.65; stroke-linecap: round; stroke-linejoin: round; }
.asset-action-library-grid > button > span { display: grid; gap: 3px; padding: 0; border: 0; color: inherit; background: transparent; font: inherit; letter-spacing: 0; }
.asset-action-library-grid strong { color: #ddd; font-size: 11px; }
.asset-action-library-grid small { color: #747474; font-size: 9px; }
.asset-actions-popover > p { margin: 0; padding: 2px 3px 0; color: #999; font-size: 11px; line-height: 1.4; }
.asset-actions-popover > p.error { color: #d99292; }
.asset-category-tabs { flex: 0 0 auto; gap: 3px; margin: 0 10px 10px; padding: 4px; border: 0; border-radius: 10px; background: #151515; box-shadow: inset 0 0 0 1px #292929; }
.asset-category-tabs button { height: 44px; gap: 4px; border: 1px solid transparent; border-radius: 7px; color: #777; font-size: 11px; transition: color .16s ease,background .16s ease,border-color .16s ease; }
.asset-category-tabs button:hover { color: #bdbdbd; background: #202020; }
.asset-category-tabs svg,.asset-category-tabs button:first-child svg { width: 17px; height: 17px; stroke-width: 1.65; }
.asset-category-tabs button.active { border-color: #414141; color: #f0f0f0; background: #292929; box-shadow: inset 0 1px #ffffff0a; }
.asset-category-tabs button.active::after { display: none; }
.asset-generator { flex: 0 0 auto; border-color: #343434; background: #181818; }
.asset-json-import { border-color: #3b4446; color: #d0d0d0; background: #202426; }
.asset-json-import:hover { border-color: #397b89; background: #222a2c; }
.asset-json-import > span { color: #45d7ff; background: #45d7ff12; }
.asset-rail-scroll {
  flex: 1;
  min-height: 0;
  max-height: none;
  overflow-x: hidden;
  overflow-y: scroll;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: #555 transparent;
}
.asset-rail-scroll::-webkit-scrollbar { width: 8px; }
.asset-rail-scroll::-webkit-scrollbar-track { background: transparent; }
.asset-rail-scroll::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 999px; background: #555; background-clip: padding-box; }
.asset-rail-scroll::-webkit-scrollbar-thumb:hover { background: #707070; background-clip: padding-box; }
.asset-rail-grid { grid-template-columns: 1fr; gap: 7px; }
.asset-pick-card {
  display: grid;
  height: 76px;
  min-height: 76px;
  box-sizing: border-box;
  grid-template-columns: 62px minmax(0,1fr) 34px;
  grid-template-rows: 1fr;
  align-items: center;
  gap: 10px;
  padding: 7px;
  overflow: visible;
  border-color: #303030;
  border-radius: 10px;
  background: #1e1e1e;
  box-shadow: none;
  transition: grid-template-columns .18s ease,gap .18s ease,border-color .16s ease,background .16s ease;
}
.asset-pick-card:has(.asset-card-add:hover),.asset-pick-card:has(.asset-card-generate:hover),.asset-pick-card:has(.asset-card-add:focus-visible),.asset-pick-card:has(.asset-card-generate:focus-visible) { grid-template-columns: 62px minmax(0,1fr) 96px; gap: 7px; }
.asset-pick-card:has([data-tooltip]:hover),.asset-pick-card:has([data-tooltip]:focus-visible) { z-index: 30; }
.asset-pick-card:hover { border-color: #484848; background: #222; box-shadow: none; transform: none; }
.asset-pick-card .asset-preview-button,.asset-pick-card .asset-missing-preview {
  width: 62px;
  height: 60px;
  grid-column: 1;
  grid-row: 1;
  overflow: hidden;
  border: 1px solid #2d2d2d;
  border-radius: 8px;
}
.asset-pick-card .asset-preview-button > img,.asset-pick-card .asset-audio-placeholder,.asset-pick-card .asset-missing-preview {
  width: 62px;
  height: 60px;
  aspect-ratio: auto;
  object-fit: cover;
}
.asset-pick-card .asset-missing-preview { color: #626a74; background: #15171a; }
.asset-pick-card .asset-missing-preview span { display: none; }
.asset-pick-card .asset-missing-preview svg { width: 22px; }
.asset-pick-card .asset-pick-copy { grid-column: 2; grid-row: 1; align-self: center; gap: 4px; padding: 0; }
.asset-pick-card .asset-pick-copy strong { color: #e9e9e9; font-size: 14px; line-height: 18px; }
.asset-pick-card .asset-pick-copy small { color: #777f88; font-size: 11px; line-height: 15px; }
.asset-pick-card .asset-card-add {
  position: static;
  width: 34px;
  height: 34px;
  grid-column: 3;
  grid-row: 1;
  align-self: center;
  border-width: 1px;
  border-color: #414141;
  border-radius: 9px;
  color: #d7d7d7;
  background: #292929;
  box-shadow: none;
  opacity: 1;
  transition: border-color .16s ease,color .16s ease,background .16s ease;
}
.asset-pick-card .asset-card-add:hover { border-color: #666; color: #fff; background: #333; transform: none; }
.asset-pick-card .asset-card-generate {
  width: 34px;
  min-height: 34px;
  height: 34px;
  grid-column: 3;
  grid-row: 1;
  justify-self: center;
  margin: 0;
  padding: 0;
  border-color: #414141;
  border-radius: 9px;
  color: #d7d7d7;
  background: #292929;
  font-size: 0;
}
.asset-pick-card .asset-card-generate svg { width: 16px; height: 16px; }
.asset-pick-card .asset-card-generate:hover:not(:disabled) { border-color: #666; color: #fff; background: #333; }
.asset-pick-card .asset-card-error { position: absolute; right: 8px; bottom: 3px; left: 80px; margin: 0; font-size: 9px; }
.asset-pick-card.generating { border-color: #8992df55; box-shadow: inset 0 0 18px #9b9fe81a; }
.asset-image-generating { position: absolute; z-index: 4; top: 7px; left: 7px; width: 62px; height: 60px; overflow: hidden; border: 1px solid #ffffff18; border-radius: 8px; background: #15191c88; pointer-events: none; contain: paint; }
.asset-image-generating i { position: absolute; top: -18%; bottom: -18%; left: 0; width: 38%; background: linear-gradient(90deg,transparent,#ffffffc9,transparent); filter: blur(.2px); transform: skewX(-12deg); animation: assetImageGenerateSweep 1.55s ease-in-out infinite; }
.asset-pick-card .asset-card-add,.asset-pick-card .asset-card-generate { justify-self: end; overflow: hidden; white-space: nowrap; transition: width .18s ease,border-color .16s ease,color .16s ease,background .16s ease; }
.asset-pick-card .asset-card-add { display: flex; align-items: center; justify-content: center; gap: 0; font-size: 0; }
.asset-pick-card .asset-card-add svg { width: 16px; height: 16px; flex: 0 0 16px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.asset-pick-card .asset-card-add em,.asset-pick-card .asset-card-generate em { max-width: 0; overflow: hidden; opacity: 0; color: inherit; font-size: 11px; font-style: normal; transition: max-width .18s ease,opacity .14s ease; }
.asset-card-add:hover,.asset-card-generate:hover,.asset-card-add:focus-visible,.asset-card-generate:focus-visible { z-index: 6; width: 96px; gap: 6px; padding: 0 9px; background: #303030; }
.asset-card-add:hover em,.asset-card-generate:hover em,.asset-card-add:focus-visible em,.asset-card-generate:focus-visible em { max-width: 68px; opacity: 1; }
@keyframes assetImageGenerateSweep { 0% { opacity: 0; transform: translateX(-130%) skewX(-12deg); } 18%,78% { opacity: .9; } 100% { opacity: 0; transform: translateX(360%) skewX(-12deg); } }
@media (prefers-reduced-motion: reduce) { .asset-image-generating i,.asset-detail-image-preview.is-generating::after,.asset-detail-empty.is-generating::after { animation-duration: 1ms !important; } }
.storyboard-column-shell {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  max-height: 100%;
}
.storyboard-column {
  height: 100%;
  min-height: 0;
  max-height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  border: 1px solid #383838;
  border-radius: 9px;
  background: #171717;
  box-shadow: none;
  scrollbar-width: thin;
  scrollbar-color: #444 transparent;
}
.storyboard-anchor-nav {
  position: fixed;
  z-index: 40;
  top: 50%;
  right: 16px;
  display: flex;
  width: 30px;
  max-height: calc(100vh - 120px);
  box-sizing: border-box;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 8px 5px;
  overflow: hidden;
  border: 1px solid #3b3f46;
  border-radius: 11px;
  background: #17191ddd;
  box-shadow: 0 10px 28px #0008,inset 0 1px #ffffff09;
  backdrop-filter: blur(10px);
  transform: translateY(-50%);
}
.storyboard-anchor-nav button {
  display: grid;
  width: 20px;
  height: 11px;
  flex: 0 0 11px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 4px;
  outline: 0;
  color: #777f8a;
  background: transparent;
  cursor: pointer;
}
.storyboard-anchor-nav button i {
  display: block;
  width: 7px;
  height: 1px;
  border-radius: 99px;
  background: currentColor;
  transition: width .18s ease,height .18s ease,color .18s ease,box-shadow .18s ease;
}
.storyboard-anchor-nav button:nth-child(3n + 2) i { width: 10px; }
.storyboard-anchor-nav button:nth-child(4n) i { width: 5px; }
.storyboard-anchor-nav button:hover,.storyboard-anchor-nav button:focus-visible { color: #d9e1ea; background: #ffffff0a; }
.storyboard-anchor-nav button.active { color: #8cecff; }
.storyboard-anchor-nav button.active i { width: 18px; height: 2px; box-shadow: 0 0 9px #45d7ffaa; }
.asset-rail,.storyboard-column { align-self: stretch; height: 100%; min-height: 0; max-height: 100%; box-sizing: border-box; }
.storyboard-column-head { position: sticky; z-index: 12; top: 0; margin: 0; border: 0; border-bottom: 1px solid #383838; border-radius: 9px 9px 0 0; background: #1c1c1c; box-shadow: none; }
.storyboard-card { --shot-card-radius: 9px; margin: 14px; overflow: visible; border-color: #383838; border-radius: 9px; background: #1c1c1c; box-shadow: none; }
.storyboard-card + .storyboard-card { margin-top: 0; }
.storyboard-column.single-shot .storyboard-card { display: flex; min-height: 0; box-sizing: border-box; flex-direction: column; }
.storyboard-column.single-shot .shot-body-grid { flex: 1; min-height: 0; }
.storyboard-column.single-shot .shot-content:not(.expanded),.storyboard-column.single-shot .shot-result { min-height: 0; }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: #e8e8e8; box-shadow: 0 0 0 2px #ffffff12; }
.storyboard-card-head { border-radius: 9px 9px 0 0; background: #202020; }
.shot-number { border-color: #414141; border-radius: 5px; color: #888; background: #242424; }
.storyboard-card.active .shot-number,.storyboard-card:focus-visible .shot-number { border-color: #d8d8d8; color: #171717; background: #f0f0f0; }
.shot-content:not(.expanded) { height: 100%; }
.shot-content:not(.expanded) .shot-content-head,.shot-content:not(.expanded) .storyboard-toolbar { flex: 0 0 auto; }
.shot-content:not(.expanded) .storyboard-compose { height: clamp(160px,23vh,200px); min-height: 160px; max-height: 200px; flex: 0 0 auto; grid-template-columns: 104px minmax(260px,1fr) 28px; align-items: stretch; }
.shot-content:not(.expanded) .storyboard-compose:has(.reference-stack.expanded) { grid-template-columns: minmax(104px,280px) minmax(260px,1fr) 28px; }
.shot-content:not(.expanded) .storyboard-compose .reference-stack,.shot-content:not(.expanded) .storyboard-compose .shot-expand { align-self: start; }
.shot-content:not(.expanded) .storyboard-compose .reference-stack { z-index: 4; }
.shot-content:not(.expanded) .storyboard-compose .storyboard-prompt-editor { position: relative; z-index: 1; min-width: 0; }
.shot-content:not(.expanded) .storyboard-compose textarea,.shot-content:not(.expanded) .storyboard-compose .storyboard-prompt-editor { height: 100%; min-height: 0; max-height: 100%; box-sizing: border-box; overflow-y: auto; overscroll-behavior: contain; }
.shot-content-head,.shot-result > header { background: #191919; }
.shot-content-head,.shot-result > header > div { display: flex; align-items: center; gap: 8px; }
.shot-content-head span,.shot-result > header span { order: 2; padding: 3px 6px; border: 1px solid #30343a; border-radius: 999px; color: #7e8790; background: #202329; font-size: 8px; letter-spacing: .1em; white-space: nowrap; }
.shot-content-head strong,.shot-result > header strong { order: 1; color: #e2e2e2; font-size: 13px; line-height: 1; }
.storyboard-compose textarea { color: #ddd; background: #141414; }
.storyboard-compose .storyboard-prompt-editor { min-height: 78px; padding: 8px 10px; border: 1px solid transparent; border-radius: 10px; color: #ddd; background: #141414; transition: border-color .18s ease,box-shadow .18s ease; }
.storyboard-compose .storyboard-prompt-editor:focus,.storyboard-compose .storyboard-prompt-editor:focus-within { border-color: #555; box-shadow: 0 0 0 3px #ffffff08; }
.shot-content.expanded .storyboard-compose .storyboard-prompt-editor { width: 100%; height: 100%; min-height: 240px; box-sizing: border-box; padding: 12px; font-size: 16px; }
.storyboard-toolbar { border-radius: 0; background: #181818; }
.storyboard-toolbar .shot-submit { border-radius: 7px; color: #071417; background: #45d7ff; box-shadow: none; }
.storyboard-toolbar .shot-submit:hover { color: #071417; background: #61e0ff; filter: none; }
.storyboard-toolbar .ratio-options button.active,.storyboard-toolbar .segmented-options button.active,.storyboard-toolbar .duration-options button.active,.storyboard-toolbar .count-options button.active { color: #171717; background: #f0f0f0; }
.shot-result { background: #111; }
.shot-result:has(.shot-result-player) { align-self: center; }
.shot-result:has(.shot-result-player) .shot-result-player { width: 100%; min-height: 0; aspect-ratio: 16 / 9; flex: 0 0 auto; }
.shot-result:has(.shot-result-player) .shot-result-player video { width: 100%; height: 100%; min-height: 0; max-height: none; object-fit: cover; }

/* Primary controls use the same neutral white interaction language. */
.video-project-new-button:hover,.video-project-new-button:focus-visible,.video-project-card:focus-visible { border-color: #e8e8e8; box-shadow: 0 0 0 3px #ffffff12; }
.video-project-new-plus { color: #151515; background: #f2f2f2; box-shadow: 0 6px 16px #0006; }
.video-project-create-backdrop .video-project-create footer button[type=submit] { border: 1px solid #f2f2f2; color: #151515; background: #f2f2f2; box-shadow: none; }
.video-project-create-backdrop .video-project-create footer button[type=submit]:hover:not(:disabled) { background: #fff; }
.video-project-card-head-actions { display: inline-flex; align-items: center; gap: 7px; }
.video-project-delete-button { display: grid; width: 28px; height: 28px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 7px; color: #777; background: transparent; cursor: pointer; transition: border-color .16s ease,color .16s ease,background .16s ease; }
.video-project-delete-button svg { width: 15px !important; fill: none; stroke: currentColor !important; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.video-project-delete-button:hover:not(:disabled),.video-project-delete-button:focus-visible { border-color: #713f46; outline: 0; color: #f08c96; background: #3a2024; }
.video-project-delete-button:disabled { cursor: wait; opacity: .45; }
.video-project-card:hover .video-project-card-body > header .video-project-delete-button svg { stroke: currentColor; transform: none; }
.video-project-open-arrow { flex: 0 0 auto; }
.video-project-delete-dialog { display: grid; grid-template-columns: 50px minmax(0,1fr); gap: 16px; width: min(470px,92vw); box-sizing: border-box; padding: 24px; border: 1px solid #44353a; border-radius: 20px; color: #eee; background: #18191d; box-shadow: 0 30px 90px #000b; }
.video-project-delete-icon { display: grid; width: 48px; height: 48px; place-items: center; border: 1px solid #78434a; border-radius: 14px; color: #ed8791; background: #3b2025; }
.video-project-delete-icon svg { width: 23px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.video-project-delete-dialog small { color: #c36f78; font: 800 11px/1 monospace; letter-spacing: .15em; }
.video-project-delete-dialog h2 { margin: 8px 0 9px; color: #f2f2f2; font-size: 20px; }
.video-project-delete-dialog p { margin: 0; color: #999; font-size: 14px; line-height: 1.7; }
.video-project-delete-dialog p strong { color: #fff; }
.video-project-delete-dialog footer { display: flex; grid-column: 1 / -1; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.video-project-delete-dialog footer button { min-width: 90px; height: 38px; border: 1px solid #414141; border-radius: 9px; color: #bbb; background: #262626; cursor: pointer; }
.video-project-delete-dialog footer button.danger { border-color: #9d4d56; color: #fff; background: #b84853; }
.video-project-delete-dialog footer button:hover:not(:disabled) { border-color: #666; color: #fff; }
.video-project-delete-dialog footer button.danger:hover:not(:disabled) { border-color: #ec7c86; background: #c8525d; }
.video-project-delete-dialog footer button:disabled { cursor: wait; opacity: .55; }
.video-workbench-head .workbench-add-shot,.storyboard-toolbar .shot-submit { border-color: #e8e8e8; color: #151515; background: #f2f2f2; box-shadow: none; }
.video-workbench-head .workbench-add-shot:hover,.storyboard-toolbar .shot-submit:hover { border-color: #fff; color: #111; background: #fff; }
.asset-card-add,.reference-stack-add { color: #151515; background: #f2f2f2; }
.asset-card-generate { border-color: #444; color: #ddd; background: #292929; }
.asset-card-generate:hover:not(:disabled) { border-color: #777; color: #fff; background: #333; }
.asset-json-import:hover,.reference-add:hover { border-color: #777; color: #f2f2f2; background: #292929; }
.asset-json-import > span { color: #f2f2f2; background: #ffffff0c; }
.asset-generator { --select-accent: #f2f2f2; --select-border-hover: #666; --select-border-focus: #e8e8e8; --select-focus-ring: #ffffff10; }

/* Refined storyboard card hierarchy. */
.storyboard-card {
  --shot-accent: #66d9ef;
  --shot-card-radius: 14px;
  border: 1px solid #34373d;
  border-radius: 14px;
  background: #181a1e;
  background-clip: padding-box;
  box-shadow: 0 12px 32px #00000045,inset 0 1px #ffffff08;
  transition: border-color .18s ease,box-shadow .18s ease,transform .18s ease;
}
.storyboard-card::before { display: none; content: none; }
.storyboard-card::after {
  position: absolute;
  z-index: 30;
  right: -1px;
  bottom: -1px;
  width: 14px;
  height: 14px;
  box-sizing: border-box;
  border-right: 1px solid #4d535d;
  border-bottom: 1px solid #4d535d;
  border-radius: 0 0 14px 0;
  content: '';
  pointer-events: none;
}
.storyboard-card:hover { border-color: #444850; box-shadow: 0 15px 38px #00000055,inset 0 1px #ffffff0a; }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: #4d535d; box-shadow: 0 16px 40px #0000005c,0 0 0 1px #ffffff08,inset 0 1px #ffffff0b; }
.storyboard-card-head { height: 48px; gap: 10px; padding: 0 14px; border-color: #2d3036; border-radius: 14px 14px 0 0; background: linear-gradient(180deg,#22252a 0%,#1c1e22 100%); }
.storyboard-card-head .shot-number { display: grid; width: 29px; height: 26px; flex: 0 0 29px; box-sizing: border-box; place-items: center; padding: 0; border: 1px solid #41464f; border-radius: 7px; color: #b8c0cc; background: #15171a; font: 700 11px/1 ui-monospace,SFMono-Regular,Consolas,monospace; box-shadow: inset 0 1px #ffffff08; }
.storyboard-card.active .shot-number,.storyboard-card:focus-visible .shot-number { border-color: #66d9ef5c; color: #bff5ff; background: #172329; box-shadow: inset 0 0 0 1px #66d9ef12; }
.storyboard-card-head input { color: #f0f2f5; font-size: 14px; font-weight: 650; letter-spacing: .01em; }
.storyboard-card-head button { width: 28px; height: 28px; border-radius: 7px; color: #68707b; }
.storyboard-card-head button:hover:not(:disabled) { color: #e7e9ed; background: #ffffff0b; }
.shot-content { border-color: #2b2e34; background: #17191c; }
.shot-content-head,.shot-result > header { min-height: 44px; padding: 0 16px; border-color: #2b2e34; background: #191b1f; }
.shot-content-head strong,.shot-result > header strong { color: #eceef1; font-size: 13px; font-weight: 650; }
.shot-content-head span,.shot-result > header span { border-color: #343942; color: #7d8795; background: #202329; }
.storyboard-compose { gap: 14px; padding: 15px; background: linear-gradient(135deg,#181a1e,#15171a); }
.storyboard-compose .storyboard-prompt-editor { border-color: #292d33; border-radius: 11px; color: #e0e3e7; background: #111316; box-shadow: inset 0 1px 0 #ffffff05; }
.storyboard-compose .storyboard-prompt-editor:focus,.storyboard-compose .storyboard-prompt-editor:focus-within { border-color: #4b535e; box-shadow: 0 0 0 3px #66d9ef0b,inset 0 1px #ffffff07; }
.reference-card { border-color: #454b54; background: #15171a; box-shadow: 0 7px 18px #0008; }
.reference-card > small { right: 5px; bottom: 5px; left: 5px; padding: 4px 5px; border-radius: 5px; background: #08090bf2; }
.reference-upload-state { position: absolute; z-index: 4; top: 5px; left: 5px; display: flex; height: 20px; align-items: center; gap: 5px; padding: 0 7px; border-radius: 999px; color: #dfe7ed; background: #101318f2; font-size: 11px; font-style: normal; box-shadow: 0 3px 10px #0008; }
.reference-upload-state i { width: 8px; height: 8px; border: 1.5px solid #ffffff45; border-top-color: #fff; border-radius: 50%; animation: result-spin .7s linear infinite; }
.reference-upload-state.error { color: #ffd0d0; background: #3b1717e8; }
.reference-stack-add { border-color: #181a1e; color: #111417; background: #f1f3f5; }
.shot-content:not(.expanded) { border-bottom-left-radius: var(--shot-card-radius,14px); background-clip: padding-box; }
.storyboard-toolbar { min-height: 48px; gap: 7px; padding: 7px 10px; border-color: #2b2e34; border-radius: 0 0 0 var(--shot-card-radius,14px); background: #16181b; background-clip: padding-box; }
.storyboard-toolbar > button,.storyboard-toolbar .toolbar-popover-wrap > button { min-height: 30px; padding: 0 8px; border: 1px solid transparent; border-radius: 7px; color: #8f98a5; background: transparent; font-size: 12px; }
.storyboard-toolbar > button:hover,.storyboard-toolbar .toolbar-popover-wrap > button:hover { border-color: #353a42; color: #e9ebef; background: #22252a; }
.storyboard-toolbar .shot-clear { color: #727b87; }
.storyboard-toolbar .shot-submit { width: auto; min-width: 106px; height: 34px; flex: 0 0 auto; grid-auto-flow: column; gap: 7px; padding: 0 15px; border: 1px solid #eef1f4; border-radius: 8px; color: #111317; background: #eef1f4; font-size: 12px; box-shadow: 0 5px 16px #0005; }
.storyboard-toolbar .shot-submit:hover { border-color: #fff; color: #090a0c; background: #fff; transform: translateY(-1px); }
.storyboard-toolbar .shot-submit svg { width: 13px; }
.shot-result { margin: 14px; overflow: hidden; border-color: #30343b; border-radius: 12px; background: #101215; box-shadow: 0 8px 24px #0005,inset 0 1px #ffffff07; }
.shot-result > header { flex: 0 0 44px; border-radius: 12px 12px 0 0; background: linear-gradient(180deg,#1c1f23,#17191d); }
.shot-result-player { overflow: hidden; isolation: isolate; box-sizing: border-box; padding: 0; border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); background: #090b0e; }
.shot-result-player::after { display: none; content: none; }
.shot-result-player video { width: 100%; height: 100%; min-height: 0; overflow: hidden; border: 0; border-radius: 0; background: #000; box-shadow: none; }
.shot-result-player:fullscreen { padding: 0; }
.shot-result-player:fullscreen,.shot-result-player:fullscreen video { contain: none; border: 0; border-radius: 0; clip-path: none; transform: none; -webkit-mask-image: none; }
.shot-result-player:fullscreen::after { display: none; }
.shot-result:has(.shot-result-player) { width: 100%; height: auto; align-self: center; margin: 0; border: 0; border-radius: 0 0 var(--shot-card-radius,14px) 0; background: #050607; box-shadow: none; }
.shot-result:has(.shot-result-player) .shot-result-player { width: 100%; height: auto; min-height: 0; aspect-ratio: 16 / 9; flex: 0 0 auto; border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); }
/* 垂直布局（上下显示）：.shot-result 横跨卡片底部，两个底角都要圆角对齐卡片 */
@media (max-width: 1450px) {
  .storyboard-card .shot-result:has(.shot-result-player) { border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); }
}
.shot-result-player video { cursor: pointer; }
.shot-result-center-play { position: absolute; z-index: 5; top: 50%; left: 50%; display: grid; width: 54px; height: 54px; place-items: center; padding: 0; border: 1px solid #ffffff52; border-radius: 50%; color: #fff; background: #00000024; box-shadow: 0 8px 24px #0007,0 0 0 6px #ffffff08; backdrop-filter: blur(5px); cursor: pointer; transform: translate(-50%,-50%); transition: transform .18s ease,background .18s ease,border-color .18s ease; }.shot-result-center-play:hover { border-color: #ffffff80; background: #0000004a; transform: translate(-50%,-50%) scale(1.06); }.shot-result-center-play svg { width: 24px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; transform: translateX(1px); }
.shot-result-controls {
  position: absolute;
  z-index: 7;
  right: 0;
  bottom: 0;
  left: 0;
  display: grid;
  box-sizing: border-box;
  gap: 8px;
  padding: 46px 0 13px;
  overflow: hidden;
  border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px);
  color: #eef0f3;
  background: linear-gradient(to bottom,transparent,#050607d9 58%,#050607f2);
  clip-path: inset(0 round 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px));
}
.shot-result-player:focus-within .shot-result-controls { opacity: 1; }
.shot-result-controls > input { width: 100%; height: 14px; margin: 0; cursor: pointer; appearance: none; background: transparent; }.shot-result-controls > input::-webkit-slider-runnable-track { height: 3px; border-radius: 99px; background: linear-gradient(90deg,#f1f2f4 var(--video-progress),#ffffff3d var(--video-progress)); }.shot-result-controls > input::-webkit-slider-thumb { width: 12px; height: 12px; margin-top: -4.5px; border: 2px solid #fff; border-radius: 50%; background: #dfe2e6; box-shadow: 0 2px 8px #000a; appearance: none; opacity: 0; transition: opacity .15s ease; }.shot-result-controls:hover > input::-webkit-slider-thumb { opacity: 1; }.shot-result-controls > input::-moz-range-track { height: 3px; border-radius: 99px; background: #ffffff3d; }.shot-result-controls > input::-moz-range-progress { height: 3px; border-radius: 99px; background: #f1f2f4; }.shot-result-controls > input::-moz-range-thumb { width: 10px; height: 10px; border: 2px solid #fff; border-radius: 50%; background: #dfe2e6; }
.shot-result-controls > div { display: flex; align-items: center; gap: 7px; padding: 0 16px; }.shot-result-controls button { display: grid; width: 30px; height: 30px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 7px; color: #e6e8eb; background: transparent; cursor: pointer; }.shot-result-controls button:hover { border-color: #ffffff1c; color: #fff; background: #ffffff12; }.shot-result-controls button:first-child { margin-right: 2px; }.shot-result-controls .shot-result-replace-control { margin-left: auto; }.shot-result-controls svg { width: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }.shot-result-controls time { color: #dfe2e6; font: 650 11px/1 ui-monospace,SFMono-Regular,Consolas,monospace; }.shot-result-controls time span { color: #747b85; }
.shot-result-player:fullscreen .shot-result-controls { right: 0; bottom: 0; left: 0; padding: 70px 24px 20px; border-radius: 0; clip-path: none; }.shot-result-player:fullscreen .shot-result-center-play { width: 66px; height: 66px; }
.shot-result-expand { border-color: #ffffff24; border-radius: 7px; background: #0b0d10d9; }

/* Expanded storyboard editor must escape the card and scroll containers. */
.shot-content.expanded {
  position: fixed;
  z-index: 2147482000;
  top: 64px;
  right: 18px;
  bottom: 18px;
  left: calc(var(--sidebar-width,240px) + 18px);
  display: flex;
  min-width: 0;
  overflow: visible;
  flex-direction: column;
  border: 1px solid #4a5059;
  border-radius: 16px;
  background: #17191d;
  box-shadow: 0 32px 100px #000e,0 0 0 100vmax #08090bd1,inset 0 1px #ffffff0b;
}
.shot-content.expanded .shot-content-head { min-height: 56px; flex: 0 0 56px; padding: 0 20px; border-radius: 16px 16px 0 0; background: linear-gradient(180deg,#22252a,#1b1d21); }
.shot-content.expanded .storyboard-compose { height: auto; min-height: 0; max-height: none; flex: 1 1 auto; grid-template-columns: auto minmax(260px,1fr) 36px; align-items: stretch; gap: 16px; padding: 20px; overflow: hidden; background: #17191d; }
.shot-content.expanded .storyboard-compose .storyboard-prompt-editor { width: 100%; height: 100%; min-height: 240px; max-height: none; box-sizing: border-box; padding: 14px; overflow-y: auto; border-color: #343941; background: #101215; font-size: 16px; }
.shot-content.expanded .shot-editor-actions { align-self: start; gap: 9px; }
.shot-content.expanded .shot-editor-actions > button { width: 36px; height: 36px; border: 1px solid #3d424a; border-radius: 9px; color: #d9dde2; background: #25282d; }
.shot-content.expanded .shot-editor-actions > button:hover { border-color: #59616c; color: #fff; background: #30343a; }
.shot-content.expanded .shot-editor-actions .shot-send-preview-toggle.active { border-color: #66d9ef66; color: #c8f7ff; background: #17343e; }
.shot-content.expanded .shot-expand { align-self: start; width: 36px; height: 36px; border: 1px solid #3d424a; border-radius: 9px; color: #e3e6ea; background: #282b31; }
.storyboard-send-preview { display: flex; min-width: 0; min-height: 0; overflow: hidden; flex-direction: column; border: 1px solid #343941; border-radius: 11px; background: #101215; box-shadow: inset 0 1px #ffffff05; }
.storyboard-send-preview > header { display: flex; min-height: 42px; flex: 0 0 42px; align-items: center; gap: 8px; padding: 0 13px; border-bottom: 1px solid #292d33; color: #aeb6c1; background: #171a1f; }
.storyboard-send-preview > header svg { width: 15px; height: 15px; fill: none; stroke: #82ddec; stroke-width: 1.6; }
.storyboard-send-preview > header strong { color: #e7eaee; font-size: 12px; }
.storyboard-send-preview > header span { margin-left: auto; color: #77818e; font-size: 11px; }
.storyboard-send-preview > pre { min-height: 0; margin: 0; padding: 14px; overflow: auto; flex: 1; color: #dce1e7; font: 14px/1.75 "Microsoft YaHei",sans-serif; white-space: pre-wrap; word-break: break-word; scrollbar-width: thin; scrollbar-color: #4a4f57 transparent; }
.storyboard-send-preview.engine-seedance { border-color: #394258; background: #10131a; }
.storyboard-send-preview.engine-seedance > header { border-bottom-color: #30384a; background: #181d28; }
.storyboard-send-preview.engine-seedance > header svg { stroke: #9eb8ff; }
.storyboard-send-preview.engine-seedance > pre { color: #dce5ff; font-family: Consolas,"SFMono-Regular",monospace; }
.shot-content.expanded .storyboard-send-preview { width: 100%; height: 100%; min-height: 240px; }
.shot-content.expanded .storyboard-send-preview > pre { font-size: 16px; }
.shot-content.expanded .storyboard-toolbar { min-height: 58px; flex: 0 0 58px; padding: 9px 18px; border-radius: 0 0 16px 16px; background: #15171a; }
.shot-content.expanded .mode-popover,.shot-content.expanded .settings-popover { top: auto; bottom: calc(100% + 10px); }

/* Selection states on the video workspace use a neutral gray language. */
.asset-category-tabs button:hover,.asset-category-tabs button.active { border-color: #4b4b4b; color: #ededed; background: #303030; box-shadow: none; }
.asset-actions-trigger:hover,.asset-actions-trigger.active { border-color: #555; color: #f0f0f0; background: #303030; }
.storyboard-toolbar .mode-popover > button:hover,.storyboard-toolbar .mode-popover > button.active { color: #f2f2f2; background: #363636; }
.storyboard-toolbar .ratio-options button:hover,.storyboard-toolbar .ratio-options button.active,
.storyboard-toolbar .segmented-options button:hover,.storyboard-toolbar .segmented-options button.active,
.storyboard-toolbar .duration-options button:hover,.storyboard-toolbar .duration-options button.active,
.storyboard-toolbar .count-options button:hover,.storyboard-toolbar .count-options button.active { border-color: #555; color: #f2f2f2; background: #3a3a3a; box-shadow: inset 0 1px #ffffff0b; }
.storyboard-toolbar .segmented-options button:disabled,.storyboard-toolbar .duration-options button:disabled,.storyboard-toolbar .count-options button:disabled { opacity: .4; cursor: not-allowed; }
.asset-action-model,.asset-generator { --select-accent: #d8d8d8; --select-border-hover: #555; --select-border-focus: #777; --select-focus-ring: #ffffff0d; }

/* Keep storyboard controls inside the left pane and settings inside the viewport. */
.storyboard-toolbar > .toolbar-popover-wrap:first-child { flex: 0 0 auto; }
.storyboard-toolbar > .settings-wrap { min-width: 0; flex: 1 1 150px; }
.storyboard-toolbar .settings-summary-btn { display: flex; width: 100%; min-width: 0; max-width: 100%; box-sizing: border-box; }
.storyboard-toolbar .settings-summary-btn > svg { flex: 0 0 auto; }
.storyboard-toolbar .settings-summary-btn > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.storyboard-toolbar .shot-clear,.storyboard-toolbar .shot-submit { flex-shrink: 0; }
.settings-popover { z-index: 2147482500; min-width: 0; overscroll-behavior: contain; }
.settings-popover > fieldset:nth-child(n) { grid-column: auto; }
.settings-popover > fieldset.settings-field-wide { grid-column: 1 / -1; }
.generation-model-field { padding: 2px !important; }
.generation-model-options { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.storyboard-toolbar .generation-model-card { position: relative; display: grid; min-width: 0; min-height: 62px; grid-template-columns: 38px minmax(0,1fr) auto; grid-template-rows: 1fr; align-items: center; gap: 10px; padding: 9px 10px; overflow: hidden; border: 1px solid #343941; border-radius: 11px; color: #aeb5bf; background: linear-gradient(145deg,#171a1f,#121419); cursor: pointer; text-align: left; transition: border-color .16s ease,background .16s ease,box-shadow .16s ease,transform .16s ease; }
.storyboard-toolbar .generation-model-card:hover:not(:disabled) { border-color: #555d68; color: #e8ebef; background: linear-gradient(145deg,#1e2228,#171a1f); transform: translateY(-1px); }
.storyboard-toolbar .generation-model-card.active { border-color: #78818d; color: #f1f3f5; background: linear-gradient(145deg,#272b31,#1b1e23); box-shadow: inset 0 0 0 1px #ffffff0c,0 5px 16px #0005; }
.storyboard-toolbar .generation-model-card:disabled { cursor: not-allowed; opacity: .42; }
.generation-model-icon { display: grid; width: 38px; height: 38px; box-sizing: border-box; place-items: center; border: 1px solid #3b414a; border-radius: 10px; color: #bfc5cd; background: #22262c; }
.generation-model-icon svg { width: 21px !important; height: 21px; fill: none; stroke: currentColor; stroke-width: 1.55; stroke-linecap: round; stroke-linejoin: round; }
.generation-model-card.active .generation-model-icon.doubao { border-color: #6d7580; color: #fff; background: #353a42; }
.generation-model-card.active .generation-model-icon.seedance { border-color: #61758c; color: #d9ebff; background: #253445; }
.generation-model-copy { display: grid; min-width: 0; gap: 4px; }
.generation-model-copy strong { overflow: hidden; color: inherit; font-size: 13px; font-weight: 700; text-overflow: ellipsis; }
.generation-model-copy small { overflow: hidden; color: #747d89; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.generation-model-card > em { align-self: start; padding: 3px 5px; border: 1px solid #3b4149; border-radius: 999px; color: #818b98; background: #14171b; font: 700 8px/1 ui-monospace,SFMono-Regular,Consolas,monospace; font-style: normal; letter-spacing: .06em; }
.generation-model-card > i { position: absolute; right: 8px; bottom: 7px; display: grid; width: 16px; height: 16px; place-items: center; border-radius: 50%; color: #15171a; background: #e7eaed; font-size: 10px; font-style: normal; opacity: 0; transform: scale(.75); transition: opacity .16s ease,transform .16s ease; }
.generation-model-card.active > i { opacity: 1; transform: scale(1); }
.generation-model-field .seedance-model-select { display: grid; grid-template-columns: 132px minmax(0,1fr); align-items: center; gap: 10px; margin-top: 9px; padding: 8px 9px; border: 1px solid #30353d; border-radius: 10px; background: #12151a; }
.generation-model-field .seedance-model-select > span { overflow: hidden; color: #8a939f; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.generation-model-field .seedance-model-select :deep(.ui-select-trigger) { min-height: 36px; border-radius: 8px; }

/* In the two-column card, the generated video fills the complete result pane. */
.storyboard-column-shell { display: flex; overflow: hidden; flex-direction: column; border: 1px solid #383838; border-radius: 9px; background: #171717; }
.storyboard-column-shell > .storyboard-column-head { position: relative; z-index: 12; top: auto; width: 100%; flex: 0 0 52px; box-sizing: border-box; margin: 0; border: 0; border-bottom: 1px solid #383838; border-radius: 8px 8px 0 0; background: #1c1c1c; }
.storyboard-column-shell > .storyboard-column { height: auto !important; min-height: 0; max-height: none !important; flex: 1 1 auto; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.shot-body-grid { width: 100%; min-width: 0; max-width: 100%; box-sizing: border-box; column-gap: 0; }
.shot-body-grid > .shot-content:not(.expanded),.shot-body-grid > .shot-result { width: 100%; min-width: 0; max-width: none; justify-self: stretch; }
.shot-content:not(.expanded) { border-radius: var(--shot-card-radius,14px) 0 0 var(--shot-card-radius,14px); background-clip: padding-box; }
.shot-content > .storyboard-card-head { flex: 0 0 48px; box-sizing: border-box; }
.shot-content.expanded > .storyboard-card-head { display: none; }
.shot-body-grid > .shot-result { width: 100% !important; max-width: none !important; min-width: 0 !important; box-sizing: border-box; margin: 0 !important; padding: 0 !important; align-self: stretch !important; }
.shot-body-grid > .shot-result > .shot-result-player { width: 100% !important; max-width: none !important; box-sizing: border-box; margin: 0 !important; padding: 0 !important; }
.shot-body-grid > .shot-result > .shot-result-player > video { display: block !important; width: 100% !important; max-width: none !important; margin: 0 !important; padding: 0 !important; }
.shot-result.has-player { width: 100%; min-width: 0; align-self: stretch; margin: 0; border: 0; border-radius: 0 0 var(--shot-card-radius,14px) 0; background: #050607; box-shadow: none; }
.shot-result.has-player .shot-result-player { width: 100%; max-width: none; min-height: 0; box-sizing: border-box; margin: 0; aspect-ratio: 16 / 9; flex: 1 1 auto; border-radius: 0 0 var(--shot-card-radius,14px) 0; }
.shot-result.has-player .shot-result-player video { display: block; width: 100%; max-width: none; height: 100%; min-height: 0; margin: 0; object-fit: cover; border-radius: 0; }
@media (min-width: 1451px) {
  .shot-body-grid { grid-template-columns: minmax(0,3fr) minmax(0,2fr) !important; }
  .shot-content > .storyboard-card-head { border-radius: var(--shot-card-radius,14px) 0 0 0; }
  .shot-body-grid > .shot-result,.shot-result.has-player,.shot-result.has-player .shot-result-player { border-radius: 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px) 0; }
  .shot-result-player .shot-result-controls { border-radius: 0 0 var(--shot-card-radius,14px) 0; clip-path: inset(0 round 0 0 var(--shot-card-radius,14px) 0); }
  .shot-body-grid > .shot-result { height: 100% !important; min-height: 0 !important; }
  .shot-body-grid > .shot-result > .shot-result-player { height: 100% !important; min-height: 0 !important; aspect-ratio: auto !important; flex: 1 1 auto !important; }
  .shot-body-grid > .shot-result > .shot-result-player > video { height: 100% !important; min-height: 100% !important; object-fit: cover !important; }
}
@media (max-width: 1450px) {
  .shot-body-grid { grid-template-columns: minmax(0,1fr) !important; }
  .shot-content > .storyboard-card-head { border-radius: var(--shot-card-radius,14px) var(--shot-card-radius,14px) 0 0; }
  .shot-body-grid > .shot-result,.shot-result.has-player,.shot-result.has-player .shot-result-player { border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); }
  .shot-result-player .shot-result-controls { border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); clip-path: inset(0 round 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px)); }
}

/* Project association: a visible, editable link shared by task creation and asset sync. */
.video-project-link-pill { display: inline-flex; width: fit-content; max-width: 100%; min-height: 25px; box-sizing: border-box; align-items: center; gap: 6px; margin-top: 10px; padding: 0 9px; overflow: hidden; border: 1px solid #343d4d; border-radius: 999px; color: #9fb9ca; background: linear-gradient(100deg,#1d2732,#1b2028); font-size: 11px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.video-project-link-pill svg { width: 13px; flex: 0 0 auto; fill: none; stroke: #6bd6dd; stroke-width: 1.5; stroke-linecap: round; }
.video-project-link-field :deep(.ui-select-trigger) { min-height: 46px; border-color: #3b465a; background: linear-gradient(180deg,#151b27,#0d121c); }
.video-project-link-field :deep(.ui-select-badge) { border-color: #37515b; color: #9ee9ed; background: #172a30; }
.video-project-link-empty { margin: -6px 0 0; padding: 10px 12px; border: 1px solid #4a3833; border-radius: 9px; color: #c69d91; background: #2a1c1988; font-size: 12px; line-height: 1.55; }
.video-project-form-error { margin: -6px 0 0; color: #f08f9b; font-size: 12px; }
.workbench-project-link { display: inline-flex; min-width: 150px; max-width: 230px; height: 28px; align-items: center; gap: 5px; padding-left: 7px; border: 1px solid #35434a; border-radius: 7px; color: #65cdd0; background: #172125; }
.workbench-project-link > svg { width: 13px; flex: 0 0 auto; fill: none; stroke: currentColor; stroke-width: 1.55; stroke-linecap: round; }
.workbench-project-link :deep(.ui-select) { min-width: 0; }
.workbench-project-link :deep(.ui-select-trigger) { min-height: 26px; padding: 0 7px 0 2px; border: 0; border-radius: 6px; color: #b9e1e2; background: transparent; box-shadow: none; }
.workbench-project-link :deep(.ui-select-value) { font-size: 11px; }
.workbench-project-link :deep(.ui-select-menu) { min-width: 210px; }

@media (max-width: 940px) {
  .video-workbench { height: auto; max-height: none; min-height: calc(100vh - 98px); min-height: calc(100dvh - 98px); padding: 18px; overflow: visible; }
  .video-workbench-head { align-items: flex-start; flex-direction: row; }
  .video-workbench-head .workbench-add-shot { width: auto; }
  .video-workbench-layout { grid-template-columns: 1fr; overflow: visible; }
  .asset-rail { height: auto; max-height: 520px; }
  .asset-rail-scroll { max-height: 320px; }
  .storyboard-column-shell { height: auto; max-height: none; }
  .storyboard-column { height: auto; max-height: none; overflow: visible; }
  .storyboard-anchor-nav { display: none; }
}
@media (max-width: 680px) {
  .video-workbench { padding: 14px; }
  .video-workbench-head { flex-wrap: wrap; padding: 0; border-radius: 0; }
  .video-workbench-title { flex-basis: calc(100% - 76px); }
  .video-workbench-title .workbench-project-name { width: 100%; font-size: 21px; }
  .workbench-meta .video-project-description { order: 5; width: 100%; }
  .workbench-project-link { order: 4; max-width: 100%; }
  .workbench-head-actions { width: auto; flex: 1 0 calc(100% - 48px); margin-left: 48px; }
  .video-workbench-head .workbench-add-shot { width: 100%; margin-left: 0; }
  .video-workbench-layout { gap: 12px; }
}
</style>
