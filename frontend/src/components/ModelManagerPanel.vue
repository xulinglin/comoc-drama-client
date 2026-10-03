<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import UiSelect from './UiSelect.vue'

const props = defineProps({ token: { type: String, default: '' } })
const tabs = [
  { key: 'text', label: '文本模型' }, { key: 'image', label: '图片模型' },
  { key: 'video', label: '视频模型' }, { key: 'audio', label: '音频模型' },
]
const modelTypeOptions = tabs.map(tab => ({ value: tab.key, label: tab.label }))
const defaultIcons = {
  text: '<svg viewBox="0 0 24 24"><path d="M4 7V4h16v3M9 21h6M12 4v17"/></svg>',
  image: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>',
  video: '<svg viewBox="0 0 24 24"><path d="m6 4 13 8-13 8V4Z"/></svg>',
  audio: '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
}
const activeTab = ref('text')
const models = ref([])
const loading = ref(true)
const saving = ref(false)
const showForm = ref(false)
const editingId = ref('')
const iconDragOver = ref(false)
const revealKey = ref(false)
const pendingDeleteId = ref('')
const notice = ref({ type: '', text: '' })
const firstInput = ref(null)
const emptyForm = () => ({ name: '', modelType: activeTab.value, provider: '', apiUrl: '', apiKey: '', modelName: '', icon: '', sortOrder: 0, enabled: true })
const form = ref(emptyForm())
const filteredModels = computed(() => models.value.filter(model => model.modelType === activeTab.value))
const typeCounts = computed(() => Object.fromEntries(tabs.map(tab => [tab.key, models.value.filter(model => model.modelType === tab.key).length])))
const providerRows = computed(() => {
  const rows = {}; let lastProvider = null; let startIndex = 0
  for (let index = 0; index <= filteredModels.value.length; index += 1) {
    const provider = index < filteredModels.value.length ? (filteredModels.value[index].provider || '') : null
    if (provider !== lastProvider) {
      if (lastProvider !== null) rows[startIndex] = index - startIndex
      lastProvider = provider; startIndex = index
    }
  }
  return rows
})
const canSave = computed(() => form.value.name.trim() && form.value.provider.trim() && form.value.modelName.trim() && form.value.apiUrl.trim() && !saving.value)

function cleanError(value) { return String(value?.message || value || '未知错误').replace(/^Error:\s*/, '') }
function flash(type, text) {
  notice.value = { type, text }
  window.setTimeout(() => { if (notice.value.text === text) notice.value = { type: '', text: '' } }, 3200)
}
async function request(method, path, body = null) {
  if (!window.pywebview?.api && import.meta.env.DEV && method === 'GET') {
    const response = await fetch(`/local-storage${path}`); const result = await response.json()
    if (!response.ok || result?.code !== 200) throw new Error(result?.message || '读取本地模型失败')
    return result.data
  }
  if (!window.pywebview?.api) throw new Error('请从桌面客户端打开模型管理')
  return window.pywebview.api.backend_request(method, path, props.token, body)
}
async function loadModels() {
  loading.value = true
  try { const result = await request('GET', '/api/admin/models'); models.value = Array.isArray(result) ? result : [] }
  catch (error) { models.value = []; flash('error', cleanError(error)) }
  finally { loading.value = false }
}
async function copyText(text, label) {
  if (!text) return
  try { await navigator.clipboard.writeText(text); flash('success', `${label}已复制`) } catch { flash('error', '复制失败') }
}
function maskKey(key) { return !key ? '未配置' : key.length <= 8 ? '••••••••' : `${key.slice(0, 4)}••••${key.slice(-4)}` }
function openAdd() { editingId.value = ''; form.value = emptyForm(); revealKey.value = false; showForm.value = true; nextTick(() => firstInput.value?.focus()) }
function openEdit(model) {
  editingId.value = String(model.id || '')
  form.value = { name: model.name || '', modelType: model.modelType || activeTab.value, provider: model.provider || '', apiUrl: model.apiUrl || '', apiKey: '', modelName: model.modelName || '', icon: model.icon || '', sortOrder: Number(model.sortOrder || 0), enabled: model.enabled !== false }
  revealKey.value = false; showForm.value = true; nextTick(() => firstInput.value?.focus())
}
function closeForm() { if (!saving.value) showForm.value = false }
async function save() {
  if (!canSave.value) return
  saving.value = true
  const payload = { ...form.value, name: form.value.name.trim(), provider: form.value.provider.trim(), modelName: form.value.modelName.trim(), apiUrl: form.value.apiUrl.trim().replace(/\/+$/, ''), sortOrder: Math.max(0, Number(form.value.sortOrder) || 0) }
  try {
    if (editingId.value) await request('PUT', `/api/admin/models/${encodeURIComponent(editingId.value)}`, payload)
    else await request('POST', '/api/admin/models', payload)
    showForm.value = false; await loadModels(); flash('success', editingId.value ? '模型已更新' : '模型已添加')
  } catch (error) { flash('error', `保存失败：${cleanError(error)}`) } finally { saving.value = false }
}
async function copyModel(model) {
  const payload = { ...model, name: `${model.name || '模型'} (副本)` }
  for (const key of ['id', 'revision', 'createTime', 'updateTime']) delete payload[key]
  try { await request('POST', '/api/admin/models', payload); await loadModels(); flash('success', '模型已复制') }
  catch (error) { flash('error', `复制失败：${cleanError(error)}`) }
}
async function toggleModel(model) {
  try { await request('PUT', `/api/admin/models/${encodeURIComponent(model.id)}`, { enabled: !model.enabled }); await loadModels(); flash('success', model.enabled ? '模型已停用' : '模型已启用') }
  catch (error) { flash('error', cleanError(error)) }
}
async function removeModel(model) {
  if (pendingDeleteId.value !== model.id) {
    pendingDeleteId.value = model.id
    window.setTimeout(() => { if (pendingDeleteId.value === model.id) pendingDeleteId.value = '' }, 4000)
    return
  }
  try { await request('DELETE', `/api/admin/models/${encodeURIComponent(model.id)}`); pendingDeleteId.value = ''; await loadModels(); flash('success', '模型已删除') }
  catch (error) { flash('error', `删除失败：${cleanError(error)}`) }
}
async function onIconDrop(event) {
  iconDragOver.value = false
  const file = event.dataTransfer?.files?.[0]; if (!file) return
  const isSvg = file.name.toLowerCase().endsWith('.svg') || file.type === 'image/svg+xml'
  if (!isSvg) { flash('error', '图标仅支持 SVG 文件'); return }
  try {
    form.value.icon = await file.text()
    flash('success', 'SVG 图标已导入')
  } catch { flash('error', '读取图标失败') }
}
onMounted(loadModels)
</script>

<template>
  <section class="model-manager" aria-labelledby="model-manager-title">
    <header class="model-manager-head">
      <div><span class="model-manager-kicker">MODEL CONFIGURATION</span><h3 id="model-manager-title">模型管理</h3><p>管理客户端生成服务使用的模型、接口与调用顺序。</p></div>
      <button class="add-model-button" type="button" @click="openAdd"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>添加模型</button>
    </header>
    <nav class="model-tabs" role="tablist" aria-label="模型类型">
      <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="activeTab === tab.key" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key">{{ tab.label }}<span>{{ typeCounts[tab.key] }}</span></button>
    </nav>
    <div class="model-notice" aria-live="polite"><span v-if="notice.text" :class="notice.type">{{ notice.text }}</span></div>
    <div v-if="loading" class="model-state"><i></i><strong>正在读取模型配置…</strong></div>
    <div v-else-if="!filteredModels.length" class="model-state empty"><span v-html="defaultIcons[activeTab]"></span><strong>暂无{{ tabs.find(tab => tab.key === activeTab)?.label }}</strong><small>添加后即可在对应的生成页面中选择。</small><button type="button" @click="openAdd">添加模型</button></div>
    <div v-else class="model-table-shell">
      <table class="model-table">
        <thead><tr><th>图标</th><th>供应商</th><th>API 地址</th><th>API Key</th><th>名称</th><th>模型名</th><th>排序</th><th>启用</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="(model, index) in filteredModels" :key="model.id" :class="{ disabled: !model.enabled }">
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell icon-column"><span class="model-icon" :class="{ empty: !model.icon }" v-html="model.icon"></span></td>
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell provider-column"><strong>{{ model.provider || '未命名' }}</strong><small>{{ providerRows[index] }} 个模型</small></td>
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell api-column"><button class="copy-value url" type="button" :title="model.apiUrl" @click="copyText(model.apiUrl, 'API 地址')">{{ model.apiUrl }}</button></td>
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell key-column"><button class="copy-value key" type="button" title="点击复制 API Key" @click="copyText(model.apiKey, 'API Key')">{{ maskKey(model.apiKey) }}</button></td>
            <td class="name-column"><button class="copy-value name" type="button" @click="copyText(model.name, '名称')">{{ model.name }}</button></td>
            <td class="model-name-column"><button class="copy-value code" type="button" :title="model.modelName" @click="copyText(model.modelName, '模型名')">{{ model.modelName }}</button></td>
            <td class="number-column">{{ model.sortOrder ?? 0 }}</td>
            <td class="status-column"><button class="status-switch" :class="{ on: model.enabled }" type="button" :aria-label="model.enabled ? '停用模型' : '启用模型'" @click="toggleModel(model)"><i></i></button></td>
            <td class="action-column"><div class="row-actions">
              <button type="button" title="编辑" @click="openEdit(model)"><svg viewBox="0 0 24 24"><path d="m4 16.5-.8 4.3 4.3-.8L18.8 8.7l-3.5-3.5L4 16.5Z"/><path d="m13.8 6.7 3.5 3.5"/></svg></button>
              <button type="button" title="复制" @click="copyModel(model)"><svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/></svg></button>
              <button class="delete" :class="{ confirming: pendingDeleteId === model.id }" type="button" :title="pendingDeleteId === model.id ? '再次点击确认删除' : '删除'" @click="removeModel(model)"><span v-if="pendingDeleteId === model.id">确认</span><svg v-else viewBox="0 0 24 24"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13"/></svg></button>
            </div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="showForm" class="model-form-backdrop" @click.self="closeForm" @keydown.esc="closeForm">
      <form class="model-form" role="dialog" aria-modal="true" aria-labelledby="model-form-title" @submit.prevent="save">
        <header><div><span>{{ editingId ? 'EDIT MODEL' : 'NEW MODEL' }}</span><h3 id="model-form-title">{{ editingId ? '编辑模型' : '添加模型' }}</h3></div><button type="button" aria-label="关闭" @click="closeForm">×</button></header>
        <div class="model-form-body">
          <label class="model-type-field"><span>类型</span><UiSelect v-model="form.modelType" :options="modelTypeOptions" badge="TYPE" /></label>
          <label><span>显示名称 <b>*</b></span><input ref="firstInput" v-model="form.name" required placeholder="如：DeepSeek V3" /></label>
          <label><span>供应商 <b>*</b></span><input v-model="form.provider" required placeholder="如：DeepSeek" /></label>
          <label><span>模型名（API 参数）<b>*</b></span><input v-model="form.modelName" required placeholder="如：deepseek-chat" /></label>
          <label class="wide"><span>API 地址 <b>*</b></span><input v-model="form.apiUrl" required type="url" placeholder="https://api.example.com" /></label>
          <label class="wide"><span>API Key</span><span class="key-input"><input v-model="form.apiKey" :type="revealKey ? 'text' : 'password'" autocomplete="off" :placeholder="editingId ? '留空则保留原 Key' : 'sk-...'"/><button type="button" @click="revealKey = !revealKey">{{ revealKey ? '隐藏' : '显示' }}</button></span></label>
          <label class="wide"><span>SVG 图标（可选）</span><span class="icon-drop-zone" :class="{ over: iconDragOver }" @dragover.prevent="iconDragOver = true" @dragleave.prevent="iconDragOver = false" @drop.prevent="onIconDrop"><textarea v-model="form.icon" rows="3" placeholder="粘贴你的 SVG 代码，也可将 SVG 文件拖到这里"></textarea><i v-if="form.icon" v-html="form.icon"></i><em v-if="iconDragOver">释放以保存 SVG</em></span></label>
          <div class="form-numbers wide"><label><span>排序</span><input v-model.number="form.sortOrder" type="number" min="0" /></label><label class="enabled-field"><span><strong>启用</strong><small>在生成页面显示</small></span><input v-model="form.enabled" type="checkbox" /></label></div>
        </div>
        <footer><button type="button" @click="closeForm">取消</button><button class="save" type="submit" :disabled="!canSave">{{ saving ? '正在保存…' : '保存' }}</button></footer>
      </form>
    </div>
  </section>
</template>

<style scoped>
.model-manager{display:grid;min-width:0;gap:12px;color:#ededf2}.model-manager-head{display:flex;align-items:center;justify-content:space-between;gap:24px}.model-manager-kicker{color:#73737d;font:700 9px/1 ui-monospace,Consolas,monospace;letter-spacing:.16em}.model-manager-head h3{margin:6px 0 3px;font-size:21px}.model-manager-head p{margin:0;color:#85858e;font-size:11px}.add-model-button{display:flex;height:38px;align-items:center;gap:7px;padding:0 14px;border:1px solid #5d5674;border-radius:9px;color:#fff;background:#4a445e;cursor:pointer}.add-model-button:hover{background:#57506d}.add-model-button svg{width:16px;fill:none;stroke:currentColor;stroke-width:2}.model-tabs{display:flex;gap:5px;padding-bottom:11px;border-bottom:1px solid #303036}.model-tabs button{display:flex;height:34px;align-items:center;gap:7px;padding:0 12px;border:1px solid transparent;border-radius:8px;color:#85858e;background:transparent;font-size:11px;cursor:pointer}.model-tabs button:hover{color:#ccc;background:#242428}.model-tabs button.active{border-color:#46434f;color:#f1eff7;background:#302d37}.model-tabs span{min-width:18px;padding:2px 5px;border-radius:8px;color:#85818f;background:#1c1b20;font-size:9px}.model-notice{min-height:16px;font-size:11px}.model-notice .success{color:#64d6b1}.model-notice .error{color:#ff8fa1}.model-table-shell{min-width:0;overflow:auto;border:1px solid #34343a;border-radius:12px;background:#19191c;scrollbar-width:thin}.model-table{width:100%;min-width:1030px;border-collapse:separate;border-spacing:0;font-size:11px}.model-table th{position:sticky;z-index:2;top:0;height:34px;padding:0 10px;border-bottom:1px solid #37373d;color:#74747d;background:#202024;font-size:9px;letter-spacing:.06em;text-align:left;white-space:nowrap}.model-table td{height:48px;padding:0 10px;border-bottom:1px solid #2d2d32;vertical-align:middle}.model-table tbody tr:last-child td{border-bottom:0}.model-table tbody tr:hover td:not(.group-cell){background:#202024}.model-table tr.disabled{opacity:.55}.group-cell{border-right:1px solid #2d2d32;background:#1c1c1f}.icon-column{width:38px;text-align:center}.provider-column{width:94px}.provider-column strong,.provider-column small{display:block;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.provider-column small{margin-top:3px;color:#676770;font-size:9px}.api-column{width:165px}.key-column{width:100px}.name-column{width:125px}.model-name-column{width:145px}.number-column,.status-column{width:42px;text-align:center}.action-column{width:104px}.model-icon{display:inline-grid;width:30px;height:30px;place-items:center;border:1px solid #44414d;border-radius:8px;color:#ccc5e2;background:#2a2731}.model-icon :deep(svg){width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.7}.model-icon :deep(img){max-width:20px;max-height:20px}.copy-value{display:block;max-width:100%;overflow:hidden;padding:0;border:0;color:#b8b8c0;background:none;font:inherit;text-align:left;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}.copy-value:hover{color:#fff;text-decoration:underline dotted;text-underline-offset:3px}.copy-value.url{max-width:165px;color:#8f8f99}.copy-value.key,.copy-value.code{font-family:ui-monospace,Consolas,monospace}.copy-value.key{color:#898493;font-size:9px}.copy-value.name{color:#e1e1e6;font-weight:650}.copy-value.code{max-width:145px;color:#a7a4b2;font-size:10px}.status-switch{position:relative;width:28px;height:16px;padding:0;border:1px solid #46464c;border-radius:9px;background:#29292e;cursor:pointer}.status-switch i{position:absolute;top:3px;left:3px;width:8px;height:8px;border-radius:50%;background:#777;transition:.15s}.status-switch.on{border-color:#2d6d5a;background:#17362c}.status-switch.on i{left:15px;background:#61d8b1;box-shadow:0 0 7px #61d8b188}.row-actions{display:flex;gap:3px}.row-actions button{display:grid;min-width:28px;height:28px;place-items:center;padding:0 6px;border:1px solid transparent;border-radius:7px;color:#777;background:transparent;cursor:pointer}.row-actions button:hover{border-color:#44444b;color:#ddd;background:#29292e}.row-actions button.delete:hover,.row-actions button.confirming{border-color:#723844;color:#ff9aaa;background:#371e23}.row-actions svg{width:14px;fill:none;stroke:currentColor;stroke-width:1.7}.row-actions span{font-size:9px}.model-state{display:grid;min-height:230px;place-items:center;align-content:center;gap:9px;border:1px dashed #39393f;border-radius:12px;color:#aaa;background:#19191b}.model-state>i{width:21px;height:21px;border:2px solid #38383e;border-top-color:#aaa;border-radius:50%;animation:spin .8s linear infinite}.model-state.empty>span{display:grid;width:42px;height:42px;place-items:center;border-radius:11px;color:#d8d1ed;background:#2d2938}.model-state.empty>span :deep(svg){width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.7}.model-state small{color:#717179}.model-state button{padding:7px 11px;border:1px solid #47434f;border-radius:8px;color:#ddd;background:#29272e;cursor:pointer}.model-form-backdrop{position:fixed;z-index:140;inset:0;display:grid;place-items:center;padding:22px;background:#050507cc;backdrop-filter:blur(8px)}.model-form{width:min(650px,calc(100vw - 44px));max-height:calc(100vh - 44px);overflow:auto;border:1px solid #3e3b47;border-radius:16px;background:#1b1b1e;box-shadow:0 35px 100px #000d}.model-form>header{display:flex;align-items:center;justify-content:space-between;padding:19px 21px 15px;border-bottom:1px solid #303035}.model-form>header span{color:#74747c;font:700 8px/1 ui-monospace,monospace;letter-spacing:.15em}.model-form>header h3{margin:5px 0 0;font-size:19px}.model-form>header button{width:32px;height:32px;border:0;border-radius:8px;color:#888;background:#27272b;font-size:21px;cursor:pointer}.model-form-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;padding:18px 21px}.model-form label{display:grid;gap:5px;color:#aaa;font-size:10px}.model-form label>span:first-child b{color:#d38b99}.model-form .wide{grid-column:1/-1}.model-form input,.model-form select,.model-form textarea{box-sizing:border-box;width:100%;border:1px solid #3a3a40;border-radius:8px;outline:0;color:#ededf1;background:#141416;font:inherit}.model-form input,.model-form select{height:37px;padding:0 10px}.model-form textarea{min-height:66px;padding:8px 10px;resize:vertical;font-family:ui-monospace,Consolas,monospace}.model-form input:focus,.model-form select:focus,.model-form textarea:focus{border-color:#676079;box-shadow:0 0 0 3px #675d801d}.key-input{display:flex}.key-input input{border-radius:8px 0 0 8px}.key-input button{width:56px;border:1px solid #3a3a40;border-left:0;border-radius:0 8px 8px 0;color:#aaa;background:#27272b;cursor:pointer}.icon-drop-zone{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 42px;gap:8px}.icon-drop-zone>i{display:grid;height:100%;place-items:center;overflow:hidden;border:1px solid #39393f;border-radius:8px;color:#ccc5e2;background:#242329;font-style:normal}.icon-drop-zone>i :deep(svg){width:22px;height:22px}.icon-drop-zone>i :deep(img){max-width:26px;max-height:26px}.icon-drop-zone>em{position:absolute;inset:0;display:grid;place-items:center;border:1px solid #796f92;border-radius:8px;color:#eee;background:#40394edb;font-style:normal}.form-numbers{display:grid;grid-template-columns:1fr 1fr 1.2fr;align-items:end;gap:12px}.enabled-field{display:flex!important;height:37px;box-sizing:border-box;align-items:center;justify-content:space-between;padding:0 10px;border:1px solid #39393f;border-radius:8px;background:#222226}.enabled-field>span{display:grid;gap:1px}.enabled-field small{color:#707078;font-size:8px}.enabled-field input{width:16px;height:16px;accent-color:#776d91}.model-form>footer{display:flex;justify-content:flex-end;gap:8px;padding:0 21px 19px}.model-form>footer button{min-width:78px;height:36px;border:1px solid #3b3b41;border-radius:8px;color:#bbb;background:#252529;cursor:pointer}.model-form>footer .save{border-color:#5e5674;color:#fff;background:#4b455f}.model-form>footer .save:disabled{cursor:not-allowed;opacity:.45}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:760px){.model-manager-head{align-items:flex-start}.model-tabs{overflow:auto}.model-form-body{grid-template-columns:1fr}.model-form .wide{grid-column:auto}.form-numbers{grid-template-columns:1fr 1fr}.enabled-field{grid-column:1/-1}}
.model-table{min-width:760px;table-layout:fixed}.api-column{min-width:0;max-width:165px;overflow:hidden}.copy-value.url{display:block;width:100%;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.model-icon.empty::after{color:#65616e;font-size:12px;content:'—'}.model-type-field{position:relative;z-index:4}.model-type-field :deep(.ui-select-trigger){min-height:37px;border-radius:8px;background:#141416}.model-type-field :deep(.ui-select-menu){z-index:150}.form-numbers{grid-template-columns:1fr 1.2fr}
</style>
