<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiSelect from './components/UiSelect.vue'
import WorkspaceLibraries from './components/WorkspaceLibraries.vue'
import ProjectDetail from './components/ProjectDetail.vue'
import VideoCreationWorkspace from './components/VideoCreationWorkspace.vue'
import BaseLoadingState from './components/BaseLoadingState.vue'
import ModelManagerPanel from './components/ModelManagerPanel.vue'
import ProjectFileTree from './components/ProjectFileTree.vue'

const image = ref(null)
const prompt = ref('让画面中的主体自然移动，镜头缓慢推进，光影柔和，细节清晰。')
const ratio = ref('自动')
const duration = ref(10)
const model = ref('Seedance 2.0 Fast')
const generationProjects = ref([])
const selectedProjectId = ref('')
const task = ref(null)
const error = ref('')
const conversionLink = ref('')
const convertingLink = ref(false)
const conversionError = ref('')
const conversionResult = ref(null)
const savingConversion = ref(false)
const conversionSaveMessage = ref('')
const appInfo = ref(null)
const accounts = ref([])
let accountStatusTimer = null
const selectedAccountId = ref('')
let accountSelectionReady = false
const showSettings = ref(false)
const showProjectFiles = ref(false)
const settingsTab = ref('accounts')
const newAccountName = ref('')
const accountMessage = ref('')
const settings = ref({ defaultAccountId: '', outputDir: '', storageDir: '', autoDownload: true, dailyVideoQuota: 3 })
const settingsMessage = ref('')
const editingAccountId = ref('')
const editingAccountName = ref('')
const renamingAccountId = ref('')
const deletingAccountId = ref('')
const accountStateAction = ref('')
const draggingAccountId = ref('')
const dragOverAccountId = ref('')
const accountOrderSaving = ref(false)
// 单账号粒度的校验状态：{ [id]: { status: 'checking'|'ok'|'expired'|'failed', message, detail, at } }
// status 不含 idle——没记录过就是没校验过，避免与卡片本身状态混淆。
const accountVerifyState = ref({})
// 正在校验中的账号 id 集合，用于禁用对应卡片按钮（不阻塞其他账号操作）。
const accountVerifyingIds = ref(new Set())
// 批量校验整体进度：{ running, total, done, ok, expired, failed, cancelled }
const accountVerifyBatch = ref(null)
// 当前展开详情的账号 id（点击 chip 切换）。
const accountVerifyDetailId = ref('')
const accountToDelete = ref(null)
const isWindowMaximized = ref(false)
const activeMenu = ref('projects')
const activeProjectId = ref('')
const sidebarCollapsed = ref(false)
const platformUser = ref({ username: 'local', nickname: '本地工作区' })
const authToken = ref('local-storage')
const authChecking = ref(false)
const authLoading = ref(false)
const authError = ref('')
let pollTimer = null

const authenticated = computed(() => Boolean(platformUser.value && authToken.value))
const isRunning = computed(() => task.value && !['succeeded', 'failed'].includes(task.value.status))
const canGenerate = computed(() => image.value && prompt.value.trim() && accounts.value.some(account => !account.quotaExhaustedToday && !account.inUse && !account.loginExpired) && !isRunning.value)
const canConvertLink = computed(() => conversionLink.value.trim() && selectedAccountId.value && !selectedAccount.value?.inUse && !convertingLink.value)
const selectedAccount = computed(() => accounts.value.find(item => item.id === selectedAccountId.value))
const accountOptions = computed(() => accounts.value.map(account => ({
  label: account.inUse
    ? `${account.name}（运行中）`
    : account.loginExpired
      ? `${account.name}（登录已过期）`
      : `${account.name}（今日 ${accountQuotaRemaining(account)}/${dailyVideoQuota()}）`,
  value: account.id,
  disabled: account.inUse || account.quotaExhaustedToday || account.loginExpired,
})))
// 只有曾经登录过的账号才需要校验登录状态；从未登录的账号直接跳过。
const checkableAccounts = computed(() => accounts.value.filter(account => account.hasLoggedIn))
const generationProjectOptions = computed(() => generationProjects.value.map(project => ({ label: project.name || '未命名项目', value: String(project.id) })))

function apiReady() {
  return window.pywebview?.api
}

function dailyVideoQuota() {
  return Math.max(1, Number(settings.value.dailyVideoQuota) || 3)
}

function accountQuotaRemaining(account) {
  const limit = dailyVideoQuota()
  if (account?.quotaExhaustedToday) return 0
  const rawRemaining = account?.quotaRemainingToday
  const remaining = Number(rawRemaining)
  if (rawRemaining !== null && rawRemaining !== undefined && rawRemaining !== '' && Number.isFinite(remaining)) {
    return Math.max(0, Math.min(remaining, limit))
  }
  const rawGenerated = account?.generatedToday
  const generated = Number(rawGenerated)
  if (rawGenerated !== null && rawGenerated !== undefined && rawGenerated !== '' && Number.isFinite(generated)) {
    return Math.max(0, limit - generated)
  }
  return limit
}

function cachedDailyVideoQuota() {
  const value = Number.parseInt(window.localStorage.getItem('cdtv.dailyVideoQuota') || '', 10)
  return Number.isFinite(value) ? Math.max(1, Math.min(value, 99)) : null
}

async function initializeAuth() {
  try {
    await loadAppInfo()
  } catch (err) {
    authError.value = cleanError(err)
  }
}

async function handleLogin(credentials) {
  authLoading.value = true
  authError.value = ''
  try {
    const authMethod = credentials.mode === 'register' ? 'register' : 'login'
    const session = await window.pywebview.api[authMethod](
      credentials.username,
      credentials.password,
      credentials.remember,
    )
    platformUser.value = session.user
    authToken.value = session.token
    await loadAppInfo()
  } catch (err) {
    authError.value = cleanError(err)
  } finally {
    authLoading.value = false
  }
}

async function logoutPlatform() {
  try {
    await window.pywebview.api.logout(authToken.value)
  } finally {
    platformUser.value = null
    authToken.value = ''
    accountSelectionReady = false
    selectedAccountId.value = ''
    accounts.value = []
    showSettings.value = false
    startNewProject()
  }
}

async function runWindowAction(action) {
  if (!apiReady()) return
  if (action === 'minimize') await window.pywebview.api.minimize_window()
  if (action === 'close') await window.pywebview.api.close_window()
  if (action === 'maximize') {
    isWindowMaximized.value = await window.pywebview.api.toggle_maximize_window()
  }
}

function scrollToSection(section) {
  activeProjectId.value = ''
  activeMenu.value = section
  document.getElementById(section)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function openProjectDetail(project) {
  activeProjectId.value = String(project?.id || '')
  activeMenu.value = 'projects'
}

function closeProjectDetail() {
  activeProjectId.value = ''
  activeMenu.value = 'projects'
}

function startWindowResize(edge) {
  if (apiReady()) window.pywebview.api.start_window_resize(edge)
}

function startNewProject() {
  image.value = null
  task.value = null
  error.value = ''
  scrollToSection('projects')
}

async function selectImage() {
  error.value = ''
  if (!apiReady()) {
    error.value = '桌面接口尚未就绪，请从 Python 启动应用。'
    return
  }
  try {
    const selected = await window.pywebview.api.select_image()
    if (selected) image.value = selected
  } catch (err) {
    error.value = String(err)
  }
}

async function generate() {
  if (!canGenerate.value) return
  error.value = ''
  task.value = null
  try {
    const result = await window.pywebview.api.start_generation({
      imagePath: image.value.path,
      prompt: prompt.value,
      ratio: ratio.value,
      duration: duration.value,
      model: model.value,
      accountId: selectedAccountId.value,
      autoAssignAccount: true,
      projectId: selectedProjectId.value,
    })
    await pollTask(result.taskId)
    pollTimer = window.setInterval(() => pollTask(result.taskId), 650)
  } catch (err) {
    error.value = cleanError(err)
  }
}

async function convertOriginalDoubaoLink() {
  if (!canConvertLink.value) return
  conversionError.value = ''
  conversionSaveMessage.value = ''
  conversionResult.value = null
  convertingLink.value = true
  try {
    conversionResult.value = await window.pywebview.api.convert_original_doubao_link(
      conversionLink.value.trim(),
      selectedAccountId.value,
    )
  } catch (err) {
    conversionError.value = cleanError(err)
  } finally {
    convertingLink.value = false
  }
}

async function pollTask(taskId) {
  try {
    const latest = await window.pywebview.api.get_task(taskId)
    if (latest) task.value = latest
    if (latest && ['succeeded', 'failed'].includes(latest.status)) {
      window.clearInterval(pollTimer)
      pollTimer = null
      await loadAccounts()
    }
  } catch (err) {
    error.value = cleanError(err)
    window.clearInterval(pollTimer)
  }
}

function cleanError(err) {
  return String(err).replace(/^Error:\s*/, '')
}

async function loadAppInfo() {
  if (!apiReady()) return
  accountSelectionReady = false
  appInfo.value = await window.pywebview.api.get_app_info()
  const apiSettings = await window.pywebview.api.get_settings()
  const cachedQuota = cachedDailyVideoQuota()
  settings.value = { ...apiSettings, dailyVideoQuota: cachedQuota ?? (Number(apiSettings.dailyVideoQuota) || 3) }
  if (cachedQuota !== null && cachedQuota !== Number(apiSettings.dailyVideoQuota)) {
    const savedSettings = await window.pywebview.api.save_settings(settings.value)
    settings.value = { ...savedSettings, dailyVideoQuota: cachedQuota }
  }
  await loadAccounts()
  await loadGenerationProjects()
  if (settings.value.defaultAccountId && accounts.value.some(item => item.id === settings.value.defaultAccountId && !item.quotaExhaustedToday && !item.inUse && !item.loginExpired)) {
    selectedAccountId.value = settings.value.defaultAccountId
  } else {
    selectedAccountId.value = accounts.value.find(item => !item.quotaExhaustedToday && !item.inUse && !item.loginExpired)?.id || ''
  }
  accountSelectionReady = true
}

async function loadGenerationProjects() {
  try {
    if (!apiReady()) {
      generationProjects.value = [
        { id: 'p1', name: '我不是丹神' }, { id: 'p2', name: '小师妹的符箓作坊' },
        { id: 'p3', name: '满朝文武都在我脑子里看广告' },
      ]
    } else {
      generationProjects.value = await window.pywebview.api.backend_request('GET', '/project/list', authToken.value, null) || []
    }
    if (!selectedProjectId.value && generationProjects.value.length) selectedProjectId.value = String(generationProjects.value[0].id)
  } catch {
    generationProjects.value = []
  }
}

async function loadAccounts() {
  if (draggingAccountId.value || accountOrderSaving.value) return
  // 编辑/删除/重命名进行中时跳过轮询刷新，避免覆盖内联编辑态或与操作结果竞争。
  if (editingAccountId.value || deletingAccountId.value || renamingAccountId.value) return
  accounts.value = await window.pywebview.api.list_accounts()
  const selected = accounts.value.find(item => item.id === selectedAccountId.value)
  if (!selected || selected.quotaExhaustedToday || selected.inUse || selected.loginExpired) {
    selectedAccountId.value = accounts.value.find(item => !item.quotaExhaustedToday && !item.inUse && !item.loginExpired)?.id || ''
  }
}

function startAccountDrag(event, account) {
  if (accountOrderSaving.value || editingAccountId.value) {
    event.preventDefault()
    return
  }
  draggingAccountId.value = account.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', account.id)
}

function enterAccountDropTarget(account) {
  if (draggingAccountId.value && draggingAccountId.value !== account.id) {
    dragOverAccountId.value = account.id
  }
}

async function dropAccount(event, targetAccount) {
  event.preventDefault()
  const sourceId = draggingAccountId.value || event.dataTransfer.getData('text/plain')
  const targetId = targetAccount.id
  dragOverAccountId.value = ''
  draggingAccountId.value = ''
  if (!sourceId || sourceId === targetId || accountOrderSaving.value) return
  if (typeof window.pywebview?.api?.reorder_accounts !== 'function') {
    accountMessage.value = '客户端后台尚未更新，请完全退出并重新启动客户端后再调整顺序'
    return
  }

  const previousAccounts = [...accounts.value]
  const sourceIndex = previousAccounts.findIndex(account => account.id === sourceId)
  const targetIndex = previousAccounts.findIndex(account => account.id === targetId)
  if (sourceIndex < 0 || targetIndex < 0) return
  const reorderedAccounts = [...previousAccounts]
  const [movedAccount] = reorderedAccounts.splice(sourceIndex, 1)
  reorderedAccounts.splice(targetIndex, 0, movedAccount)
  accounts.value = reorderedAccounts
  accountOrderSaving.value = true
  accountMessage.value = '正在保存账号顺序…'
  try {
    const result = await window.pywebview.api.reorder_accounts(reorderedAccounts.map(account => account.id))
    accountMessage.value = result.cloudSynced
      ? '账号顺序已保存并同步云端'
      : '账号顺序已在本机保存，云端暂未同步'
  } catch (err) {
    accounts.value = previousAccounts
    accountMessage.value = cleanError(err)
  } finally {
    accountOrderSaving.value = false
  }
}

function endAccountDrag() {
  draggingAccountId.value = ''
  dragOverAccountId.value = ''
}

async function createAccount() {
  error.value = ''
  try {
    const account = await window.pywebview.api.create_account(newAccountName.value)
    newAccountName.value = ''
    await loadAccounts()
    selectedAccountId.value = account.id
    accountMessage.value = `已创建 ${account.name}`
  } catch (err) {
    error.value = cleanError(err)
  }
}

async function openSelectedAccount() {
  if (!selectedAccountId.value) {
    accountMessage.value = '请先创建并选择一个账号'
    return
  }
  try {
    const result = await window.pywebview.api.open_account_login(selectedAccountId.value)
    accountMessage.value = result.message
  } catch (err) {
    accountMessage.value = cleanError(err)
  }
}

function openSettings(tab = 'accounts') {
  settingsTab.value = tab
  showSettings.value = true
  accountMessage.value = ''
  settingsMessage.value = ''
}

watch([showSettings, settingsTab], ([open, tab]) => {
  if (accountStatusTimer) {
    window.clearInterval(accountStatusTimer)
    accountStatusTimer = null
  }
  if (open && tab === 'accounts' && apiReady()) {
    loadAccounts().catch(() => {})
    accountStatusTimer = window.setInterval(() => loadAccounts().catch(() => {}), 2500)
  }
})

watch(selectedAccountId, accountId => {
  if (!accountSelectionReady || !authenticated.value || !apiReady()) return
  if (typeof window.pywebview.api.select_account === 'function') {
    window.pywebview.api.select_account(accountId).catch(() => {})
    return
  }
  // 兼容仍在运行的旧版 Python 进程：通过原有设置接口保存最后选择。
  settings.value.defaultAccountId = accountId
  window.pywebview.api.save_settings(settings.value).catch(() => {})
})

function beginRename(account) {
  editingAccountId.value = account.id
  editingAccountName.value = account.name
  accountMessage.value = ''
}

async function finishRename() {
  const accountId = editingAccountId.value
  const accountName = editingAccountName.value.trim()
  if (!accountId || renamingAccountId.value) return
  if (!accountName) {
    accountMessage.value = '账号名称不能为空'
    return
  }
  const previousAccounts = accounts.value
  renamingAccountId.value = accountId
  try {
    const account = await window.pywebview.api.rename_account(accountId, accountName)
    editingAccountId.value = ''
    editingAccountName.value = ''
    // 就地更新单条记录，避免全量 loadAccounts 触发整列表重渲染与轮询叠加造成的卡顿。
    accounts.value = accounts.value.map(item => (
      item.id === accountId ? { ...item, name: account.name } : item
    ))
    accountMessage.value = `名称已修改为 ${account.name}`
  } catch (err) {
    accounts.value = previousAccounts
    accountMessage.value = cleanError(err)
  } finally {
    renamingAccountId.value = ''
  }
}

function cancelRename() {
  if (renamingAccountId.value) return
  editingAccountId.value = ''
  editingAccountName.value = ''
  accountMessage.value = ''
}

function deleteAccount(account) {
  if (deletingAccountId.value) return
  accountToDelete.value = account
}

function cancelDeleteAccount() {
  if (deletingAccountId.value) return
  accountToDelete.value = null
}

async function confirmDeleteAccount() {
  const account = accountToDelete.value
  if (!account || deletingAccountId.value) return
  deletingAccountId.value = account.id
  accountMessage.value = ''
  try {
    const deleted = await window.pywebview.api.delete_account(account.id)
    if (selectedAccountId.value === account.id) selectedAccountId.value = ''
    if (editingAccountId.value === account.id) {
      editingAccountId.value = ''
      editingAccountName.value = ''
    }
    // 就地移除该账号并重排序号，避免全量 loadAccounts 触发整列表重渲染。
    accounts.value = accounts.value
      .filter(item => item.id !== account.id)
      .map((item, index) => ({ ...item, sortOrder: index }))
    accountMessage.value = `已删除 ${deleted.name}`
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    deletingAccountId.value = ''
    accountToDelete.value = null
  }
}

async function releaseAccount(account) {
  const actionKey = `release:${account.id}`
  if (accountStateAction.value) return
  accountStateAction.value = actionKey
  accountMessage.value = ''
  try {
    const result = await window.pywebview.api.release_account(account.id)
    await loadAccounts()
    accountMessage.value = result.released ? `已释放 ${account.name}` : `${account.name} 当前未被占用`
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    accountStateAction.value = ''
  }
}

async function toggleAccountQuota(account) {
  const exhausted = !account.quotaExhaustedToday
  const actionKey = `quota:${account.id}`
  if (accountStateAction.value) return
  accountStateAction.value = actionKey
  accountMessage.value = ''
  try {
    await window.pywebview.api.set_account_quota(account.id, exhausted)
    await loadAccounts()
    accountMessage.value = exhausted
      ? `已将 ${account.name} 标记为今日无额度`
      : `已恢复 ${account.name} 今日额度`
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    accountStateAction.value = ''
  }
}

async function updateDailyVideoQuota(value) {
  const dailyQuota = Math.max(1, Math.min(Number.parseInt(value, 10) || 3, 99))
  if (accountStateAction.value === 'daily-limit') return
  accountStateAction.value = 'daily-limit'
  accountMessage.value = ''
  try {
    settings.value.dailyVideoQuota = dailyQuota
    window.localStorage.setItem('cdtv.dailyVideoQuota', String(dailyQuota))
    settings.value.defaultAccountId = selectedAccountId.value
    const savedSettings = await window.pywebview.api.save_settings(settings.value)
    settings.value = { ...savedSettings, dailyVideoQuota: dailyQuota }
    await loadAccounts()
    accountMessage.value = `每日视频额度已自动保存为 ${dailyQuota}`
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    accountStateAction.value = ''
  }
}

function stepDailyVideoQuota(delta) {
  const current = Number(settings.value.dailyVideoQuota) || 3
  updateDailyVideoQuota(current + delta)
}

function verifyChip(accountId) {
  const state = accountVerifyState.value[accountId]
  if (!state) return null
  if (state.status === 'checking') return { tone: 'checking', icon: 'spinner', label: '校验中', clickable: false }
  if (state.status === 'ok') return { tone: 'ok', icon: 'ok', label: '正常', clickable: false }
  if (state.status === 'expired') return { tone: 'expired', icon: 'expired', label: '登录过期', clickable: true }
  if (state.status === 'failed') return { tone: 'failed', icon: 'failed', label: '校验失败', clickable: true }
  return null
}

function isAccountVerifying(accountId) {
  return accountVerifyingIds.value.has(accountId)
}

function isBatchVerifying() {
  return Boolean(accountVerifyBatch.value?.running)
}

// 单账号校验：仅禁用该账号卡片，不影响其他账号操作。
async function verifyAccountLogin(account) {
  const accountId = account.id
  if (isAccountVerifying(accountId) || isBatchVerifying()) return
  if (typeof window.pywebview?.api?.check_account_login !== 'function') {
    accountMessage.value = '客户端后台尚未更新，请完全退出并重新启动客户端后再校验登录'
    return
  }
  if (account.inUse) {
    accountMessage.value = `${account.name} 运行中，请等待任务结束或先手动释放`
    return
  }
  if (!account.hasLoggedIn) {
    accountMessage.value = `${account.name} 从未登录过，请先打开登录页完成登录`
    return
  }
  const verifyingIds = new Set(accountVerifyingIds.value)
  verifyingIds.add(accountId)
  accountVerifyingIds.value = verifyingIds
  accountVerifyState.value = {
    ...accountVerifyState.value,
    [accountId]: { status: 'checking', message: '', detail: null, at: Date.now() },
  }
  accountMessage.value = `正在校验 ${account.name}…`
  try {
    const result = await window.pywebview.api.check_account_login(accountId)
    const method = result.method === 'http' ? 'HTTP 探活' : '浏览器校验'
    const next = {
      status: result.loggedIn ? 'ok' : 'expired',
      message: result.message || (result.loggedIn ? '登录状态正常' : '登录已过期'),
      detail: {
        method,
        hasLoginText: result.hasLoginText,
        hasSessionCookie: result.hasSessionCookie,
        url: result.url,
      },
      at: Date.now(),
    }
    accountVerifyState.value = { ...accountVerifyState.value, [accountId]: next }
    accountMessage.value = next.message
  } catch (err) {
    const msg = cleanError(err)
    accountVerifyState.value = {
      ...accountVerifyState.value,
      [accountId]: { status: 'failed', message: msg, detail: null, at: Date.now() },
    }
    accountMessage.value = `${account.name} 校验失败：${msg}`
  } finally {
    const rest = new Set(accountVerifyingIds.value)
    rest.delete(accountId)
    accountVerifyingIds.value = rest
    loadAccounts().catch(() => {})
  }
}

function toggleVerifyDetail(accountId) {
  accountVerifyDetailId.value = accountVerifyDetailId.value === accountId ? '' : accountId
}

// 过期账号直接在卡片上提供「重新登录」入口，省一步选中再点登录。
async function reloginAccount(account) {
  selectedAccountId.value = account.id
  await openSelectedAccount()
}

// 并发上限 3 的批量校验；支持取消——已发起的请求等其返回，未启动的不再发起。
async function verifyAllAccountsLogin() {
  if (isBatchVerifying()) return
  if (typeof window.pywebview?.api?.check_account_login !== 'function') {
    accountMessage.value = '客户端后台尚未更新，请完全退出并重新启动客户端后再校验登录'
    return
  }
  const targets = [...checkableAccounts.value]
  const skipped = accounts.value.length - targets.length
  if (!targets.length) {
    accountMessage.value = accounts.value.length
      ? '没有已登录过的账号可校验（从未登录的账号已跳过）'
      : '还没有账号可校验'
    return
  }
  accountVerifyState.value = {}
  accountVerifyDetailId.value = ''
  accountVerifyBatch.value = {
    running: true,
    total: targets.length,
    done: 0,
    ok: 0,
    expired: 0,
    failed: 0,
    cancelled: false,
  }
  accountMessage.value = `正在校验 0/${targets.length}…`
  const CONCURRENCY = 3
  let cursor = 0
  const runOne = async () => {
    while (true) {
      if (accountVerifyBatch.value?.cancelled) return
      const idx = cursor++
      if (idx >= targets.length) return
      const account = targets[idx]
      const verifyingIds = new Set(accountVerifyingIds.value)
      verifyingIds.add(account.id)
      accountVerifyingIds.value = verifyingIds
      accountVerifyState.value = {
        ...accountVerifyState.value,
        [account.id]: { status: 'checking', message: '', detail: null, at: Date.now() },
      }
      const batch = { ...accountVerifyBatch.value }
      accountVerifyBatch.value = batch
      try {
        const result = await window.pywebview.api.check_account_login(account.id)
        const method = result.method === 'http' ? 'HTTP 探活' : '浏览器校验'
        if (accountVerifyBatch.value?.cancelled) {
          // 取消后到账的结果不再计入统计，但仍保留 chip 状态供查看。
          accountVerifyState.value = {
            ...accountVerifyState.value,
            [account.id]: {
              status: result.loggedIn ? 'ok' : 'expired',
              message: result.message || '',
              detail: { method, hasLoginText: result.hasLoginText, hasSessionCookie: result.hasSessionCookie, url: result.url },
              at: Date.now(),
            },
          }
          return
        }
        const status = result.loggedIn ? 'ok' : 'expired'
        accountVerifyState.value = {
          ...accountVerifyState.value,
          [account.id]: {
            status,
            message: result.message || (result.loggedIn ? '登录状态正常' : '登录已过期'),
            detail: { method, hasLoginText: result.hasLoginText, hasSessionCookie: result.hasSessionCookie, url: result.url },
            at: Date.now(),
          },
        }
        if (status === 'ok') batch.ok += 1
        else batch.expired += 1
      } catch (err) {
        if (accountVerifyBatch.value?.cancelled) {
          accountVerifyState.value = {
            ...accountVerifyState.value,
            [account.id]: { status: 'failed', message: cleanError(err), detail: null, at: Date.now() },
          }
          return
        }
        accountVerifyState.value = {
          ...accountVerifyState.value,
          [account.id]: { status: 'failed', message: cleanError(err), detail: null, at: Date.now() },
        }
        batch.failed += 1
      } finally {
        const rest = new Set(accountVerifyingIds.value)
        rest.delete(account.id)
        accountVerifyingIds.value = rest
        batch.done += 1
        accountVerifyBatch.value = { ...batch }
        accountMessage.value = `正在校验 ${batch.done}/${batch.total}…`
      }
    }
  }
  const workers = []
  for (let i = 0; i < Math.min(CONCURRENCY, targets.length); i++) workers.push(runOne())
  try {
    await Promise.all(workers)
  } finally {
    const final = { ...accountVerifyBatch.value, running: false }
    accountVerifyBatch.value = final
    const parts = []
    if (final.ok) parts.push(`${final.ok} 个正常`)
    if (final.expired) parts.push(`${final.expired} 个登录过期`)
    if (final.failed) parts.push(`${final.failed} 个校验失败`)
    let message = final.cancelled
      ? `已取消校验：完成 ${final.done}/${final.total}（${parts.join('，') || '无结果'}）`
      : `${final.total} 个账号校验完成：${parts.join('，') || '无结果'}`
    if (skipped) message += `（另有 ${skipped} 个从未登录的账号已跳过）`
    accountMessage.value = message
    loadAccounts().catch(() => {})
  }
}

function cancelVerifyAll() {
  if (!accountVerifyBatch.value?.running) return
  accountVerifyBatch.value = { ...accountVerifyBatch.value, cancelled: true }
  accountMessage.value = '正在取消校验，等待已发起的请求返回…'
}

async function chooseOutputDirectory() {
  const selected = await window.pywebview.api.select_output_directory()
  if (selected) settings.value.outputDir = selected
}

async function chooseStorageDirectory() {
  const selected = await window.pywebview.api.select_storage_directory()
  if (selected) settings.value.storageDir = selected
}

async function saveSettings() {
  settings.value.defaultAccountId = selectedAccountId.value
  settings.value = await window.pywebview.api.save_settings(settings.value)
  settingsMessage.value = settings.value.storageRestartRequired
    ? '设置已保存，请重启客户端以使用新的项目存储目录'
    : '设置已保存'
}

async function openOutputDirectory() {
  await window.pywebview.api.open_output_directory()
}


async function openStorageDirectory() {
  await window.pywebview.api.open_storage_directory()
}

async function saveConversionVideoAs() {
  if (!conversionResult.value?.path || savingConversion.value) return
  conversionError.value = ''
  conversionSaveMessage.value = ''
  savingConversion.value = true
  try {
    const saved = await window.pywebview.api.save_video_as(
      conversionResult.value.path,
      conversionResult.value.name,
    )
    if (saved?.saved) conversionSaveMessage.value = `已另存为：${saved.path}`
  } catch (err) {
    conversionError.value = cleanError(err)
  } finally {
    savingConversion.value = false
  }
}

onMounted(() => {
  if (apiReady()) initializeAuth()
  else {
    if (import.meta.env.DEV && new URLSearchParams(window.location.search).has('preview-auth')) {
      platformUser.value = { username: 'preview', nickname: 'CDTV 用户' }
      authToken.value = 'preview-token'
      authChecking.value = false
      loadGenerationProjects()
      return
    }
    window.addEventListener('pywebviewready', initializeAuth, { once: true })
    if (import.meta.env.DEV) {
      window.setTimeout(() => {
        if (!apiReady()) authChecking.value = false
      }, 300)
    }
  }
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (accountStatusTimer) window.clearInterval(accountStatusTimer)
})
</script>

<template>
  <main class="app-shell" :class="{ 'auth-mode': !authenticated, 'video-workbench-mode': authenticated && activeMenu === 'create' }">
    <div class="window-titlebar" @dblclick="runWindowAction('maximize')">
      <div class="window-identity pywebview-drag-region" aria-hidden="true"></div>
      <div class="window-controls" @dblclick.stop>
        <button data-tooltip="最小化" aria-label="最小化" @click="runWindowAction('minimize')">
          <svg viewBox="0 0 12 12"><path d="M2 6.5h8" /></svg>
        </button>
        <button data-tooltip="最大化" aria-label="最大化或还原" @click="runWindowAction('maximize')">
          <svg v-if="!isWindowMaximized" viewBox="0 0 12 12"><rect x="2.2" y="2.2" width="7.6" height="7.6" rx=".6" /></svg>
          <svg v-else viewBox="0 0 12 12"><path d="M4 3V2.2h5.8V8H9M2.2 4H8v5.8H2.2z" /></svg>
        </button>
        <button class="window-close" data-tooltip="关闭" aria-label="关闭" @click="runWindowAction('close')">
          <svg viewBox="0 0 12 12"><path d="m2.5 2.5 7 7m0-7-7 7" /></svg>
        </button>
      </div>
    </div>
    <i v-for="edge in ['top', 'right', 'bottom', 'left', 'top-left', 'top-right', 'bottom-left', 'bottom-right']" :key="edge" :class="['resize-handle', `resize-${edge}`]" @mousedown.prevent="startWindowResize(edge)"></i>

    <div v-if="authChecking" class="auth-loading" role="status" aria-live="polite">
      <BaseLoadingState size="lg" text="正在验证登录状态…" description="CDTV Studio" />
    </div>

    <template v-else>

    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-brand">
        <button class="sidebar-logo" :data-tooltip="sidebarCollapsed ? '展开菜单' : 'CDTV'" @click="sidebarCollapsed && (sidebarCollapsed = false)">
          <svg viewBox="0 0 1024 1024" aria-hidden="true">
            <rect x="64" y="64" width="896" height="896" rx="220" fill="#0f121c"/>
            <rect x="132" y="214" width="760" height="600" rx="120" fill="none" stroke="#ffffff" stroke-opacity="0.10" stroke-width="12"/>
            <path d="M421 285a231 231 0 0 0 0 453" fill="none" stroke="#2eddff" stroke-width="78" stroke-linecap="round"/>
            <path d="M535 738a231 231 0 0 0 0-453" fill="none" stroke="#ff3fa8" stroke-width="78" stroke-linecap="round"/>
            <path d="M555 425v180l153-90z" fill="#ffda5a"/>
            <circle cx="246" cy="274" r="18" fill="#ffda5a"/>
            <circle cx="784" cy="302" r="14" fill="#2eddff"/>
            <circle cx="810" cy="734" r="18" fill="#ff3fa8"/>
            <circle cx="226" cy="764" r="12" fill="#f6f8ff"/>
          </svg>
        </button>
        <span class="sidebar-brand-copy"><strong>CDTV</strong><small>AI VIDEO STUDIO</small></span>
        <button class="collapse-button" :data-tooltip="sidebarCollapsed ? '展开菜单' : '收起菜单'" :aria-label="sidebarCollapsed ? '展开菜单' : '收起菜单'" @click="sidebarCollapsed = !sidebarCollapsed">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9.67272 0.522841C10.8339 0.522841 11.76 0.522714 12.4963 0.602493C13.2453 0.683657 13.8789 0.854248 14.4264 1.25197C14.7504 1.48739 15.0355 1.77247 15.2709 2.0965C15.6686 2.64394 15.8392 3.27758 15.9204 4.02655C16.0002 4.7629 16 5.68895 16 6.85014V9.14986C16 10.3111 16.0002 11.2371 15.9204 11.9735C15.8392 12.7224 15.6686 13.3561 15.2709 13.9035C15.0355 14.2275 14.7504 14.5126 14.4264 14.748C13.8789 15.1458 13.2453 15.3163 12.4963 15.3975C11.76 15.4773 10.8339 15.4772 9.67272 15.4772H6.3273C5.16611 15.4772 4.24006 15.4773 3.50371 15.3975C2.75474 15.3163 2.1211 15.1458 1.57366 14.748C1.24963 14.5126 0.964549 14.2275 0.729131 13.9035C0.331407 13.3561 0.160817 12.7224 0.0796529 11.9735C-0.000126137 11.2371 1.25338e-09 10.3111 1.25338e-09 9.14986V6.85014C1.25329e-09 5.68895 -0.000126137 4.7629 0.0796529 4.02655C0.160817 3.27758 0.331407 2.64394 0.729131 2.0965C0.964549 1.77247 1.24963 1.48739 1.57366 1.25197C2.1211 0.854248 2.75474 0.683657 3.50371 0.602493C4.24006 0.522714 5.16611 0.522841 6.3273 0.522841H9.67272ZM5.54303 1.88715V14.1118C5.78636 14.1128 6.04709 14.1169 6.3273 14.1169H9.67272C10.8639 14.1169 11.7032 14.1164 12.3493 14.0465C12.9824 13.9779 13.3497 13.8494 13.6268 13.6482C13.8354 13.4966 14.0195 13.3125 14.1711 13.1039C14.3723 12.8268 14.5007 12.4595 14.5693 11.8264C14.6393 11.1803 14.6398 10.341 14.6398 9.14986V6.85014C14.6398 5.65896 14.6393 4.81967 14.5693 4.1736C14.5007 3.54048 14.3723 3.17318 14.1711 2.89609C14.0195 2.68747 13.8354 2.50337 13.6268 2.35179C13.3497 2.1506 12.9824 2.02212 12.3493 1.95353C11.7032 1.88358 10.8639 1.88307 9.67272 1.88307H6.3273C6.04709 1.88307 5.78636 1.8862 5.54303 1.88715ZM4.1828 1.91166C3.99125 1.9216 3.8148 1.93577 3.65076 1.95353C3.01764 2.02212 2.65034 2.1506 2.37325 2.35179C2.16463 2.50337 1.98052 2.68747 1.82895 2.89609C1.62776 3.17318 1.49928 3.54048 1.43069 4.1736C1.36074 4.81967 1.36023 5.65896 1.36023 6.85014V9.14986C1.36023 10.341 1.36074 11.1803 1.43069 11.8264C1.49928 12.4595 1.62776 12.8268 1.82895 13.1039C1.98052 13.3125 2.16463 13.4966 2.37325 13.6482C2.65034 13.8494 3.01764 13.9779 3.65076 14.0465C3.81478 14.0642 3.99127 14.0774 4.1828 14.0873V1.91166Z" /></svg>
        </button>
      </div>

      <button class="new-project-button" @click="startNewProject">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 8.5v7M8.5 12h7" /></svg>
        <span>新建项目</span>
      </button>

      <div class="workspace-label">
        <span>工作区</span>
        <div>
          <button data-tooltip="项目文件" @click="showProjectFiles = true"><svg viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z"/><path d="M7 11h10M7 14.5h7"/></svg></button>
          <button data-tooltip="搜索项目" @click="scrollToSection('projects')"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg></button>
          <button data-tooltip="设置" @click="openSettings('general')"><svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6"/></svg></button>
        </div>
      </div>

      <nav class="sidebar-nav" aria-label="主菜单">
        <button :class="{ active: activeMenu === 'projects' }" @click="activeProjectId = ''; activeMenu = 'projects'">
          <svg viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z"/><path d="M7 11h10M7 14.5h7"/></svg><span>项目</span>
        </button>
        <button :class="{ active: activeMenu === 'assets' }" @click="activeProjectId = ''; activeMenu = 'assets'">
          <svg viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><circle cx="9" cy="9" r="1.5"/><path d="m5.5 17 4.2-4.2 3.1 3.1 2.5-2.5 3.2 3.6"/></svg><span>我的资产</span>
        </button>
        <button :class="{ active: activeMenu === 'create' }" @click="scrollToSection('create')">
          <svg viewBox="0 0 24 24"><rect x="3" y="5" width="14" height="14" rx="2.5"/><path d="m17 10 4-2v8l-4-2v-4Z"/></svg><span>视频生成</span>
        </button>
        <button :class="{ active: activeMenu === 'convert' }" @click="scrollToSection('convert')">
          <svg viewBox="0 0 24 24"><path d="M8.5 14.5 6 17a3.5 3.5 0 0 1-5-5l3.5-3.5a3.5 3.5 0 0 1 5 0"/><path d="m15.5 9.5 2.5-2.5a3.5 3.5 0 0 1 5 5l-3.5 3.5a3.5 3.5 0 0 1-5 0"/><path d="m8 16 8-8"/></svg><span>链接转换</span>
        </button>
      </nav>

      <div class="sidebar-bottom">
        <div class="sidebar-account-row">
          <div class="sidebar-platform-account" :data-tooltip="`已登录：${platformUser.nickname || platformUser.username}`">
            <span class="sidebar-platform-avatar">{{ (platformUser.nickname || platformUser.username || '?').slice(0, 1) }}</span>
            <span class="sidebar-platform-copy"><strong>{{ platformUser.nickname || platformUser.username }}</strong><small>CDTV 账号</small></span>
          </div>
          <button class="sidebar-inline-action sidebar-settings-action" data-tooltip="设置" aria-label="设置" @click="openSettings('general')">
            <svg viewBox="0 0 24 24"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.2h-4v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3v-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.5V3h4v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.1v4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg><span>设置</span>
          </button>
        </div>
      </div>
    </aside>

    <div class="ambient ambient-one"></div>
    <div class="ambient ambient-two"></div>

    <header v-if="activeMenu === 'home'" class="topbar">
      <div class="topbar-actions">
      <button class="account-switch" @click="openSettings('accounts')">
        <span class="account-avatar">{{ selectedAccount?.name?.slice(0, 1) || '+' }}</span>
        <span>{{ selectedAccount?.name || '添加生成账号' }}</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4" /></svg>
      </button>
      </div>
    </header>

    <template v-if="['projects', 'prompts', 'assets'].includes(activeMenu)">
      <Transition name="project-detail-fade">
        <ProjectDetail
          v-if="activeMenu === 'projects' && activeProjectId"
          :project-id="activeProjectId"
          :token="authToken"
          @back="closeProjectDetail"
        />
      </Transition>

      <WorkspaceLibraries
        v-show="!(activeMenu === 'projects' && activeProjectId)"
        :section="activeMenu"
        :token="authToken"
        :api-base="appInfo?.apiBase"
        :storage-base="appInfo?.storageBase"
        @open-project="openProjectDetail"
      />
    </template>

    <template v-else-if="activeMenu === 'home'">

    <section id="home" class="hero">
      <p class="eyebrow">VIDEO GENERATION</p>
      <h1>视频生成</h1>
      <p class="subtitle">上传参考画面，通过 OriginalDoubao 或 Seedance 生成视频。</p>
    </section>

    <section id="create" class="workspace section-anchor">
      <div class="panel media-panel">
        <div class="panel-heading">
          <div><span class="step">01</span><h2>参考画面</h2></div>
          <button v-if="image" class="text-button" @click="selectImage">更换</button>
        </div>

        <button class="upload-zone" :class="{ filled: image }" @click="selectImage">
          <img v-if="image" :src="image.preview" :alt="image.name" />
          <template v-else>
            <div class="upload-icon">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
              </svg>
            </div>
            <strong>选择一张图片</strong>
            <span>支持 JPG、PNG、WEBP</span>
          </template>
          <div v-if="image" class="image-caption">{{ image.name }}</div>
        </button>
      </div>

      <div class="panel controls-panel">
        <div class="panel-heading">
          <div><span class="step">02</span><h2>动态描述</h2></div>
          <span class="char-count">{{ prompt.length }} / 500</span>
        </div>

        <textarea v-model="prompt" maxlength="500" placeholder="描述镜头、动作、光影和氛围……"></textarea>

        <div class="model-field">
          <label>关联项目</label>
          <UiSelect v-model="selectedProjectId" :options="generationProjectOptions" :placeholder="generationProjectOptions.length ? '选择项目' : '暂无项目，请先新建项目'" />
        </div>

        <div class="model-field">
          <label>生成模型</label>
          <UiSelect v-model="model" :options="['Seedance 2.0 Fast']" status badge="FAST" />
        </div>

        <div class="option-row">
          <div class="option-group">
            <label>画面比例</label>
            <div class="segmented">
              <button v-for="item in ['自动', '16:9', '9:16', '1:1']" :key="item" :class="{ active: ratio === item }" @click="ratio = item">{{ item }}</button>
            </div>
          </div>
          <div class="option-group">
            <label>视频时长</label>
            <div class="duration-control">
              <input v-model.number="duration" type="range" min="4" max="15" step="1" />
              <strong>{{ duration }} 秒</strong>
            </div>
          </div>
        </div>

        <button class="generate-button" :disabled="!canGenerate" @click="generate">
          <span v-if="isRunning" class="spinner"></span>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Zm6.5 12 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" /></svg>
          {{ isRunning ? '正在生成' : '开始生成视频' }}
        </button>

        <p v-if="error" class="error-message">{{ error }}</p>
      </div>
    </section>

    <footer>
      <span>浏览器自动化模式 · 页面更新后可能需要重新适配控件</span>
      <span v-if="appInfo">登录状态目录：{{ appInfo.profileDir }}</span>
    </footer>
    </template>

    <VideoCreationWorkspace
      v-else-if="activeMenu === 'create'"
      :token="authToken"
      :api-base="appInfo?.apiBase"
      :storage-base="appInfo?.storageBase"
      :selected-account-id="selectedAccountId"
      :video-model="model"
    />

    <template v-else-if="activeMenu === 'convert'">
      <section id="convert" class="hero link-convert-hero">
        <p class="eyebrow">VIDEO LINK CONVERTER</p>
        <h1>链接转换</h1>
        <p class="subtitle">粘贴视频分享链接，转换并保存无水印视频。</p>
      </section>

      <section class="link-convert-workspace">
        <div class="panel link-convert-panel">
          <div class="panel-heading">
            <div><span class="step">01</span><h2>视频分享链接</h2></div>
          </div>

          <label class="link-convert-field">
            <span>视频链接</span>
            <div class="link-convert-input-shell">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 14.5 6 17a3.5 3.5 0 0 1-5-5l3.5-3.5a3.5 3.5 0 0 1 5 0"/><path d="m15.5 9.5 2.5-2.5a3.5 3.5 0 0 1 5 5l-3.5 3.5a3.5 3.5 0 0 1-5 0"/><path d="m8 16 8-8"/></svg>
              <input v-model="conversionLink" type="url" autocomplete="off" placeholder="视频分享链接或抖音视频直链" @keyup.enter="convertOriginalDoubaoLink" />
              <button v-if="conversionLink" type="button" aria-label="清空链接" @click="conversionLink = ''; conversionError = ''">×</button>
            </div>
          </label>

          <button class="generate-button link-convert-button" :disabled="!canConvertLink" @click="convertOriginalDoubaoLink">
            <span v-if="convertingLink" class="spinner"></span>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19h14"/></svg>
            {{ convertingLink ? '正在解析并下载…' : '转换无水印视频' }}
          </button>
          <p class="link-convert-help">支持官方视频分享链接和 *.douyin.com 视频直链，结果将保存到视频输出目录。</p>
          <p v-if="conversionLink.trim() && !selectedAccountId" class="error-message">暂无可用生成账号，请先在设置中心添加并登录账号</p>
          <p v-if="conversionError && !conversionResult" class="error-message">{{ conversionError }}</p>
        </div>

        <div class="panel link-preview-panel" :class="{ ready: conversionResult }">
          <div class="panel-heading">
            <div><span class="step">02</span><h2>转换结果</h2></div>
          </div>

          <div v-if="conversionResult" class="link-preview-ready">
            <video :key="conversionResult.previewUrl" :src="conversionResult.previewUrl" controls playsinline preload="metadata"></video>
            <div class="link-preview-meta">
              <span class="link-success-mark"><svg viewBox="0 0 16 16"><path d="m3 8 3 3 7-7"/></svg></span>
              <span><strong>{{ conversionResult.name }}</strong><small>{{ conversionResult.message }}</small></span>
            </div>
            <div class="link-preview-actions">
              <button class="link-save-button" type="button" :disabled="savingConversion" @click="saveConversionVideoAs">
                <span v-if="savingConversion" class="spinner"></span>
                <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19h14"/></svg>
                {{ savingConversion ? '正在另存…' : '下载 / 另存为' }}
              </button>
              <button class="link-open-button" type="button" @click="openOutputDirectory">打开所在目录</button>
            </div>
            <p v-if="conversionSaveMessage" class="link-save-message">{{ conversionSaveMessage }}</p>
            <p v-if="conversionError" class="error-message">{{ conversionError }}</p>
          </div>
          <div v-else class="link-preview-empty">
            <span class="link-preview-icon"><svg viewBox="0 0 24 24"><path d="m9 7 8 5-8 5V7Z"/></svg></span>
            <strong>等待转换</strong>
            <small>完成后可直接在这里播放无水印视频</small>
          </div>
        </div>
      </section>

      <footer>
        <span>仅支持官方视频分享链接</span>
        <span v-if="settings.outputDir">输出目录：{{ settings.outputDir }}</span>
      </footer>
    </template>

    <div v-if="showSettings" class="modal-backdrop settings-backdrop" @click.self="showSettings = false">
      <section class="account-modal settings-modal">
        <div class="modal-heading">
          <div><span>APPLICATION SETTINGS</span><h2>设置中心</h2></div>
          <button @click="showSettings = false">×</button>
        </div>

        <div class="settings-layout">
          <nav class="settings-tabs" aria-label="设置分类">
            <button :class="{ active: settingsTab === 'accounts' }" :aria-current="settingsTab === 'accounts' ? 'page' : undefined" @click="settingsTab = 'accounts'">
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/></svg>
              <span><strong>账号中心</strong><small>生成账号与额度</small></span>
            </button>
            <button :class="{ active: settingsTab === 'models' }" :aria-current="settingsTab === 'models' ? 'page' : undefined" @click="settingsTab = 'models'">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4h8l4 4v8l-4 4H8l-4-4V8l4-4Z"/><circle cx="9" cy="10" r="1"/><circle cx="15" cy="10" r="1"/><path d="M9 15h6"/></svg>
              <span><strong>模型管理</strong><small>API 与生成模型</small></span>
            </button>
            <button :class="{ active: settingsTab === 'general' }" :aria-current="settingsTab === 'general' ? 'page' : undefined" @click="settingsTab = 'general'">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6"/></svg>
              <span><strong>运行设置</strong><small>输出与自动化</small></span>
            </button>
          </nav>

          <div class="settings-content">
        <template v-if="settingsTab === 'accounts'">
        <section class="account-control-bar">
          <div class="account-control-copy">
            <span class="account-control-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"/><path d="M4 5v14"/></svg></span>
            <span><strong>每日生成额度</strong><small>为所有生成账号设定统一的每日可用次数</small></span>
          </div>
          <div class="daily-quota-control" :class="{ saving: accountStateAction === 'daily-limit' }">
            <span class="quota-control-label"><small>单账号上限</small><strong>每日</strong></span>
            <span class="quota-stepper">
              <button type="button" :disabled="accountStateAction === 'daily-limit' || settings.dailyVideoQuota <= 1" aria-label="减少每日生成额度" @click="stepDailyVideoQuota(-1)">−</button>
              <input type="number" min="1" max="99" :value="settings.dailyVideoQuota ?? 3" :disabled="accountStateAction === 'daily-limit'" aria-label="每日视频生成额度" @change="updateDailyVideoQuota($event.target.value)" />
              <button type="button" :disabled="accountStateAction === 'daily-limit' || settings.dailyVideoQuota >= 99" aria-label="增加每日生成额度" @click="stepDailyVideoQuota(1)">+</button>
            </span>
            <span class="quota-control-unit"><strong>次</strong><small>/ 天</small></span>
          </div>
        </section>

        <div class="account-section-heading">
          <span><strong>生成账号</strong><small>{{ accounts.length }} 个独立账号 · 拖动调整调用顺序</small></span>
          <span class="account-legend"><i></i>状态正常</span>
        </div>

        <div class="account-list">
          <div
            v-for="account in accounts"
            :key="account.id"
            class="account-row"
            :class="{ selected: selectedAccountId === account.id, authenticated: account.authenticated, 'quota-exhausted': account.quotaExhaustedToday, 'in-use': account.inUse, 'not-logged-in': !account.hasLoggedIn, dragging: draggingAccountId === account.id, 'drag-over': dragOverAccountId === account.id }"
            @click="selectedAccountId = account.id"
            @dragenter.prevent="enterAccountDropTarget(account)"
            @dragover.prevent
            @drop="dropAccount($event, account)"
          >
            <span
              class="account-drag-handle"
              :class="{ disabled: accountOrderSaving }"
              :draggable="!accountOrderSaving"
              role="button"
              :aria-label="`拖动调整 ${account.name} 的顺序`"
              title="拖动调整顺序"
              @click.stop
              @dragstart.stop="startAccountDrag($event, account)"
              @dragend="endAccountDrag"
            ><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="5" cy="4" r="1"/><circle cx="11" cy="4" r="1"/><circle cx="5" cy="8" r="1"/><circle cx="11" cy="8" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="11" cy="12" r="1"/></svg></span>
            <span class="account-avatar">{{ account.name.slice(0, 1) }}</span>
            <span class="account-details">
              <span class="account-name-row">
                <input
                  v-if="editingAccountId === account.id"
                  v-model="editingAccountName"
                  class="rename-input"
                  maxlength="30"
                  autofocus
                  aria-label="账号名称"
                  @click.stop
                  @keyup.enter.stop="finishRename"
                  @keyup.esc.stop="cancelRename"
                />
                <strong v-else>{{ account.name }}</strong>
                <span v-if="editingAccountId !== account.id" class="account-card-actions">
                  <button class="account-icon-action verify-action" type="button" :data-tooltip="isAccountVerifying(account.id) ? '正在校验…' : '校验此账号登录状态'" :aria-label="`校验 ${account.name} 登录状态`" :disabled="isAccountVerifying(account.id) || isBatchVerifying() || account.inUse || !account.hasLoggedIn" @click.stop="verifyAccountLogin(account)">
                    <span v-if="isAccountVerifying(account.id)" class="account-icon-spinner" aria-hidden="true"></span>
                    <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v6c0 4.5 3.4 7.8 8 9 4.6-1.2 8-4.5 8-9V6l-8-3Z"/><path d="m9.2 12 2 2 3.6-3.6"/></svg>
                  </button>
                  <button class="account-icon-action rename-action" type="button" data-tooltip="修改账号名称" aria-label="修改账号名称" @click.stop="beginRename(account)">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16.5-.8 4.3 4.3-.8L18.8 8.7l-3.5-3.5L4 16.5Z"/><path d="m13.8 6.7 3.5 3.5"/></svg>
                  </button>
                  <button class="account-icon-action rename-action delete-account-action" type="button" data-tooltip="删除账号" aria-label="删除账号" :disabled="Boolean(deletingAccountId)" @click.stop="deleteAccount(account)">
                    <span v-if="deletingAccountId === account.id" class="account-icon-spinner" aria-hidden="true"></span>
                    <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg>
                  </button>
                </span>
                <span v-else class="account-card-actions">
                  <button class="account-icon-action rename-action" type="button" :data-tooltip="renamingAccountId === account.id ? '保存中…' : '保存账号名称'" aria-label="保存账号名称" :disabled="Boolean(renamingAccountId)" @click.stop="finishRename">
                    <span v-if="renamingAccountId === account.id" class="account-icon-spinner" aria-hidden="true"></span>
                    <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.2 4.2L19 7"/></svg>
                  </button>
                  <button class="account-icon-action rename-action" type="button" data-tooltip="取消修改" aria-label="取消修改" :disabled="Boolean(renamingAccountId)" @click.stop="cancelRename">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>
                  </button>
                </span>
              </span>
              <small class="account-status-copy">{{ account.status }}</small>
              <span class="account-quota-summary" :class="{ exhausted: account.quotaExhaustedToday }">
                <span class="quota-number"><strong>{{ accountQuotaRemaining(account) }}</strong><em>/ {{ dailyVideoQuota() }}</em></span>
                <span class="quota-meta"><span>今日剩余</span><span class="quota-track"><i :style="{ width: `${(accountQuotaRemaining(account) / dailyVideoQuota()) * 100}%` }"></i></span></span>
              </span>
              <template v-if="verifyChip(account.id)">
                <button
                  class="account-verify-chip"
                  :class="verifyChip(account.id).tone"
                  :disabled="!verifyChip(account.id).clickable"
                  :aria-expanded="accountVerifyDetailId === account.id"
                  @click.stop="verifyChip(account.id).clickable && toggleVerifyDetail(account.id)"
                >
                  <i v-if="verifyChip(account.id).icon === 'spinner'" class="account-verify-spinner" aria-hidden="true"></i>
                  <em>{{ verifyChip(account.id).label }}</em>
                </button>
                <span v-if="accountVerifyDetailId === account.id && accountVerifyState[account.id]" class="account-verify-detail">
                  <span class="account-verify-detail-row">{{ accountVerifyState[account.id].message }}</span>
                  <template v-if="accountVerifyState[account.id].detail">
                    <span class="account-verify-detail-row" v-if="accountVerifyState[account.id].detail.method">校验方式：{{ accountVerifyState[account.id].detail.method }}</span>
                    <span class="account-verify-detail-row" v-if="accountVerifyState[account.id].detail.hasSessionCookie !== undefined">会话 Cookie：{{ accountVerifyState[account.id].detail.hasSessionCookie ? '存在' : '缺失' }}</span>
                    <span class="account-verify-detail-row" v-if="accountVerifyState[account.id].detail.hasLoginText !== undefined">页面登录入口：{{ accountVerifyState[account.id].detail.hasLoginText ? '出现' : '未出现' }}</span>
                    <span class="account-verify-detail-row" v-if="accountVerifyState[account.id].detail.url">当前 URL：{{ accountVerifyState[account.id].detail.url }}</span>
                  </template>
                  <span class="account-verify-detail-row" v-if="accountVerifyState[account.id].at">校验时间：{{ new Date(accountVerifyState[account.id].at).toLocaleTimeString() }}</span>
                </span>
              </template>
              <span class="account-state-actions">
                <button v-if="verifyChip(account.id)?.tone === 'expired'" type="button" class="relogin-action" :disabled="Boolean(accountStateAction)" @click.stop="reloginAccount(account)">重新登录</button>
                <button v-if="account.inUse" type="button" :disabled="Boolean(accountStateAction)" @click.stop="releaseAccount(account)">{{ accountStateAction === `release:${account.id}` ? '释放中…' : '释放账号' }}</button>
                <button type="button" :disabled="Boolean(accountStateAction)" @click.stop="toggleAccountQuota(account)">{{ accountStateAction === `quota:${account.id}` ? '设置中…' : account.quotaExhaustedToday ? '恢复今日额度' : '设为今日无额度' }}</button>
              </span>
            </span>
            <svg v-if="account.inUse" class="account-lock-icon" viewBox="0 0 24 24" aria-label="账号运行中并已锁定"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
            <i v-else class="account-status-dot" aria-hidden="true"></i>
          </div>
          <div v-if="!accounts.length" class="no-accounts">还没有账号配置</div>
        </div>

        <section class="account-footer-panel">
          <div class="new-account">
            <input v-model="newAccountName" maxlength="30" aria-label="新账号名称" placeholder="输入账号名称，例如：主账号" @keyup.enter="createAccount" />
            <button @click="createAccount"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>添加账号</button>
          </div>
          <div class="account-footer-actions">
            <button class="login-button" :disabled="!selectedAccountId" @click="openSelectedAccount">{{ selectedAccount?.authenticated ? '打开所选账号' : '登录所选账号' }}</button>
            <div class="verify-login-row">
          <button class="verify-login-button" type="button" :disabled="isBatchVerifying() || !checkableAccounts.length" @click="verifyAllAccountsLogin">
            <span v-if="isBatchVerifying()" class="verify-button-spinner" aria-hidden="true"></span>
            <span>{{ isBatchVerifying() ? `正在校验 ${accountVerifyBatch.done}/${accountVerifyBatch.total}…` : `校验全部登录${checkableAccounts.length ? `（${checkableAccounts.length}）` : ''}` }}</span>
          </button>
          <button v-if="isBatchVerifying()" class="verify-cancel-button" type="button" @click="cancelVerifyAll">取消</button>
            </div>
          </div>
        </section>
        <div v-if="accountVerifyBatch" class="account-verify-progress">
          <div class="account-verify-progress-bar">
            <span class="account-verify-progress-fill" :style="{ width: `${accountVerifyBatch.total ? (accountVerifyBatch.done / accountVerifyBatch.total) * 100 : 0}%` }"></span>
          </div>
          <div class="account-verify-progress-legend">
            <span class="ok">正常 {{ accountVerifyBatch.ok }}</span>
            <span class="expired">过期 {{ accountVerifyBatch.expired }}</span>
            <span class="failed">失败 {{ accountVerifyBatch.failed }}</span>
            <span class="muted">{{ accountVerifyBatch.done }} / {{ accountVerifyBatch.total }}</span>
          </div>
        </div>
        <p v-if="accountMessage" class="account-message">{{ accountMessage }}</p>
        </template>

        <ModelManagerPanel v-else-if="settingsTab === 'models'" :token="authToken" />

        <template v-else>
          <div class="settings-form">
            <label>默认账号</label>
            <UiSelect v-model="selectedAccountId" :options="accountOptions" placeholder="未选择" />

            <label>视频输出目录</label>
            <div class="directory-row">
              <input v-model="settings.outputDir" readonly />
              <button @click="chooseOutputDirectory">选择</button>
              <button @click="openOutputDirectory">打开</button>
            </div>

            <label>项目存储目录</label>
            <div class="directory-row">
              <input v-model="settings.storageDir" readonly />
              <button @click="chooseStorageDirectory">选择</button>
              <button @click="openStorageDirectory">打开</button>
            </div>
            <p class="settings-storage-hint">项目数据与素材保存在此目录。修改后重启客户端生效；不会自动搬移原目录的数据。</p>

            <label class="toggle-row"><span><strong>自动下载结果</strong><small>任务完成后保存到输出目录</small></span><input v-model="settings.autoDownload" type="checkbox" /></label>
          </div>
          <button class="login-button" @click="saveSettings">保存设置</button>
          <p v-if="settingsMessage" class="account-message">{{ settingsMessage }}</p>
        </template>
          </div>
        </div>
      </section>
    </div>

    <ProjectFileTree v-model:visible="showProjectFiles" />

    <Transition name="account-confirm">
      <div v-if="accountToDelete" class="account-confirm-backdrop" @click.self="cancelDeleteAccount">
        <section class="account-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-account-title" aria-describedby="delete-account-description">
          <span class="account-confirm-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M12 8v5M12 16.5v.1"/><path d="M10.2 3.8 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.8 3.8a2 2 0 0 0-3.6 0Z"/></svg>
          </span>
          <div class="account-confirm-copy">
            <span>DELETE ACCOUNT</span>
            <h3 id="delete-account-title">删除生成账号？</h3>
            <p id="delete-account-description">账号 <strong>{{ accountToDelete.name }}</strong> 的本地登录状态将一并删除。</p>
            <small>此操作无法撤销。</small>
          </div>
          <div class="account-confirm-actions">
            <button type="button" :disabled="Boolean(deletingAccountId)" autofocus @click="cancelDeleteAccount">取消</button>
            <button class="danger" type="button" :disabled="Boolean(deletingAccountId)" @click="confirmDeleteAccount">
              <span v-if="deletingAccountId" class="spinner"></span>
              {{ deletingAccountId ? '正在删除…' : '确认删除' }}
            </button>
          </div>
        </section>
      </div>
    </Transition>
    </template>
  </main>
</template>
