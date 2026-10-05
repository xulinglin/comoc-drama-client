<template>
  <section class="image-chat-workspace">
    <aside class="image-chat-sidebar">
      <button class="image-chat-new" type="button" @click="newConversation" :disabled="generating">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
        新建对话
      </button>
      <div class="image-chat-conversations" role="list">
        <p v-if="conversationsLoading && !conversations.length" class="image-chat-conversations-tip">正在加载…</p>
        <p v-else-if="!conversations.length" class="image-chat-conversations-tip">还没有历史对话</p>
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="image-chat-conversation"
          :class="{ active: conversation.id === activeConversationId }"
          role="listitem"
          @click="openConversation(conversation.id)"
        >
          <div class="image-chat-conversation-main">
            <strong>{{ conversation.title || '新对话' }}</strong>
            <span>{{ conversationPreview(conversation) }}</span>
          </div>
          <div class="image-chat-conversation-meta">
            <time>{{ formatConversationTime(conversation.updatedAt || conversation.createdAt) }}</time>
            <button type="button" aria-label="删除对话" :disabled="generating" @click.stop="removeConversation(conversation.id)">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>
            </button>
          </div>
        </div>
      </div>
    </aside>

    <div class="image-chat-panel">
      <div class="image-chat-heading">
        <div class="image-chat-heading-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4" width="17" height="16" rx="3"/><circle cx="9" cy="9" r="1.5"/><path d="m5.5 17 4.2-4.2 3.1 3.1 2.5-2.5 3.2 3.6"/></svg></div>
        <div><h1>图片生成</h1><p>用对话，让想象成为画面</p></div>
        <button class="image-chat-clear" type="button" @click="clearConversation" :disabled="!messages.length || generating">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5m4-5v5"/></svg>
          清空本对话
        </button>
      </div>

      <div ref="scrollArea" class="image-chat-scroll" role="log" aria-label="图片创作对话" aria-live="polite">
        <div v-if="!messages.length" class="image-chat-empty">
          <div class="image-chat-empty-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/></svg></div>
          <strong>今天，想创作什么？</strong>
          <span>描述脑海中的画面，或上传参考图。<br />从第一句话开始，一起打磨你的灵感。</span>
          <div class="image-chat-suggestions">
            <button v-for="suggestion in suggestions" :key="suggestion.label" type="button" @click="fillPrompt(suggestion.prompt)">{{ suggestion.label }}<span aria-hidden="true">↗</span></button>
          </div>
        </div>

        <div v-for="message in messages" :key="message.id" v-show="message.role !== 'system-status'" class="image-chat-message" :class="message.role">
          <div v-if="message.role !== 'system-status'" class="image-chat-avatar" aria-hidden="true">
            <svg v-if="message.role === 'user'" viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20v-2a7 7 0 0 1 14 0v2"/></svg>
            <svg v-else viewBox="0 0 24 24"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/></svg>
          </div>
          <div class="image-chat-message-content">
            <span v-if="message.role !== 'system-status'" class="image-chat-message-name">{{ message.role === 'user' ? '你' : '图片助手' }}</span>
            <div class="image-chat-bubble" :class="{ 'is-generating': message.generating }">
              <img v-if="message.reference" class="image-chat-reference" :src="message.reference" alt="参考图" />
              <p v-if="message.text" class="image-chat-text">{{ message.text }}</p>
              <div v-if="message.images.length" class="image-chat-result-grid">
                <figure v-for="(url, index) in message.images" :key="index" class="image-chat-result-card">
                  <img class="image-chat-result" :src="url" alt="生成结果" @click="previewImage = url" />
                  <figcaption class="image-chat-result-tools">
                    <button class="image-chat-tool" type="button" title="下载到本地" @click="saveImage(url)">
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v10m0 0-4-4m4 4 4-4M5 18h14"/></svg>
                      下载
                    </button>
                    <button class="image-chat-tool" type="button" title="作为参考图" @click="useAsReference(url)">
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/></svg>
                      参考图
                    </button>
                    <button
                      class="image-chat-tool"
                      type="button"
                      :disabled="assetSaving[url] === 'saving' || assetSaving[url] === 'saved'"
                      title="保存到素材库"
                      @click="saveToLibrary(url)"
                    >
                      <span v-if="assetSaving[url] === 'saving'" class="spinner"></span>
                      <svg v-else-if="assetSaving[url] === 'saved'" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 13 4 4L19 7"/></svg>
                      <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h9L20 9.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5Z"/><path d="M14 4v5h5M12 11v6m0 0-3-3m3 3 3-3"/></svg>
                      {{ assetSaving[url] === 'saving' ? '保存中' : assetSaving[url] === 'saved' ? '已入库' : '素材库' }}
                    </button>
                  </figcaption>
                </figure>
              </div>
              <div v-if="message.generating" class="image-chat-generating" role="status" aria-label="正在生成图片" aria-busy="true">
                <div class="image-chat-generating-placeholder" aria-hidden="true">
                  <ParticleWaveCanvas :count="196" :speed="0.2" />
                </div>
              </div>
              <p v-if="message.error" class="image-chat-error">{{ message.error }}</p>
              <p v-if="message.assetNotice" class="image-chat-asset-notice" :class="message.assetNotice.type">{{ message.assetNotice.text }}</p>
            </div>
          </div>
        </div>
      </div>

      <div class="image-chat-composer-area">
        <div class="image-chat-composer">
          <div v-if="pendingReference" class="image-chat-attachment">
            <img :src="pendingReference.preview" :alt="pendingReference.name" />
            <div><strong>参考图</strong><span>{{ pendingReference.name }}</span></div>
            <button type="button" aria-label="移除参考图" @click="removeReference">×</button>
          </div>
          <input ref="fileInput" type="file" accept="image/*" class="image-chat-file" @change="onFilePicked" />
          <textarea
            ref="draftInput"
            v-model="draft"
            rows="3"
            maxlength="2000"
            aria-label="图片提示词"
            :placeholder="pendingReference ? '描述你想要的修改效果……' : '描述你想要的画面……'"
            @keydown="handleComposerKeydown"
          ></textarea>
          <div class="image-chat-composer-tools">
            <UiSelect
              class="image-chat-model-select"
              v-model="selectedModel"
              :options="modelOptions"
              :placeholder="loadingModels ? '正在加载模型…' : '选择生成方式'"
              :disabled="loadingModels || !modelOptions.length"
              status
              badge="IMAGE"
            />
            <button class="image-chat-attach" type="button" :disabled="generating" @click="pickReference">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/></svg>
              上传参考图
            </button>
            <span class="image-chat-draft-count">{{ draft.length }} / 2000</span>
            <button class="image-chat-send" type="button" :disabled="!canSubmit" @click="submit">
              <span v-if="generating" class="spinner"></span>
              {{ generating ? '生成中' : '发送' }}
              <svg v-if="!generating" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-5 5 5-5 5 5" /></svg>
            </button>
          </div>
        </div>
        <p class="image-chat-composer-hint">Enter 发送<span>·</span>Shift + Enter 换行</p>
      </div>
    </div>

    <div v-if="previewImage" class="image-chat-lightbox" @click="previewImage = ''">
      <img :src="previewImage" alt="预览" />
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import ParticleWaveCanvas from './ParticleWaveCanvas.vue'

const props = defineProps({
  token: { type: String, default: '' },
  apiBase: { type: String, default: 'http://127.0.0.1:8080' },
  storageBase: { type: String, default: 'http://127.0.0.1:18081' },
})

const models = ref([])
const selectedModel = ref('')
const loadingModels = ref(false)
const generating = ref(false)
const draft = ref('')
const messages = ref([])
const pendingReference = ref(null)
const previewImage = ref('')
const fileInput = ref(null)
const draftInput = ref(null)
const scrollArea = ref(null)
const conversations = ref([])
const activeConversationId = ref('')
const conversationsLoading = ref(false)
const assetSaving = ref({})
const MAX_MESSAGES_PER_CONVERSATION = 50
let persistTimer = null
const suggestions = [
  { label: '电影感人像', prompt: '一张电影感人像，柔和的侧光，细腻的胶片质感，背景虚化，温暖自然的色调。' },
  { label: '梦幻风景', prompt: '一片梦幻的山间湖泊，清晨薄雾，远处雪山倒映在湖面，柔和的光线，宁静而富有诗意。' },
  { label: '产品海报', prompt: '一张极简风格的香水产品海报，磨砂玻璃瓶，干净的背景，自然光与柔和阴影，高级商业摄影。' },
]

function fillPrompt(prompt) {
  draft.value = prompt
  draftInput.value?.focus()
}

function handleComposerKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submit()
}

const modelOptions = computed(() => models.value.map(model => ({
  label: model.name || model.modelName || '图片模型',
  value: String(model.id ?? model.modelName ?? ''),
})))

const canSubmit = computed(() => !generating.value && !loadingModels.value
  && !!selectedModel.value
  && !!draft.value.trim())

function cleanError(value) {
  return String(value?.message || value || '未知错误').replace(/^Error:\s*/, '')
}

async function request(method, path, body = null) {
  if (!window.pywebview?.api) throw new Error('请从桌面客户端启动后再使用图片生成')
  return window.pywebview.api.backend_request(method, path, props.token, body)
}

function absoluteMediaUrl(value) {
  const url = String(value || '').trim()
  if (!url || /^(?:https?:|data:|blob:)/i.test(url)) return url
  const base = url.includes('/file/local_') ? props.storageBase : props.apiBase
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`
}

async function loadModels() {
  loadingModels.value = true
  try {
    const result = await request('GET', '/api/admin/models/public/list?modelType=image')
    models.value = Array.isArray(result) ? result : []
    if (!modelOptions.value.some(option => option.value === selectedModel.value)) {
      selectedModel.value = modelOptions.value[0]?.value || ''
    }
  } catch (error) {
    models.value = []
    if (!models.value.length) {
      messages.value.push({ id: Date.now(), role: 'system', text: '', images: [], error: `加载图片模型失败：${cleanError(error)}` })
    }
  } finally {
    loadingModels.value = false
  }
}

function scrollToEnd() {
  nextTick(() => {
    const el = scrollArea.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function pickReference() {
  fileInput.value?.click()
}

async function onFilePicked(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = () => reject(new Error('读取图片失败'))
      reader.readAsDataURL(file)
    })
    pendingReference.value = { name: file.name, preview: dataUrl, dataUrl }
  } catch (error) {
    messages.value.push({ id: Date.now(), role: 'system', text: '', images: [], error: cleanError(error) })
    scrollToEnd()
  }
}

function removeReference() {
  pendingReference.value = null
}

function useAsReference(url) {
  pendingReference.value = { name: '上一张结果图', preview: url, dataUrl: url }
  draftInput.value?.focus()
  scrollToEnd()
}

async function submit() {
  if (!canSubmit.value) return
  await ensureActiveConversation()
  const prompt = draft.value.trim()
  const reference = pendingReference.value
  const userMessage = {
    id: Date.now(),
    role: 'user',
    text: prompt,
    reference: reference?.preview || '',
    images: [],
  }
  const assistantMessage = reactive({
    id: `${userMessage.id}-assistant`,
    role: 'assistant',
    text: '',
    images: [],
    generating: true,
    error: '',
  })
  messages.value.push(userMessage, assistantMessage)
  draft.value = ''
  pendingReference.value = null
  generating.value = true
  scrollToEnd()
  try {
    const payload = { model: selectedModel.value, prompt, n: 1, size: '1024x1024' }
    if (reference?.dataUrl) payload.image = [reference.dataUrl]
    const result = await request('POST', '/ai/image', payload)
    const items = Array.isArray(result?.data) && result.data.length ? result.data : [result]
    const urls = items
      .map(item => item?.url || item?.content || item?.image_url)
      .filter(Boolean)
      .map(absoluteMediaUrl)
    if (!urls.length) throw new Error('图片模型没有返回图片')
    assistantMessage.images = urls
    if (urls.length === 1) previewImage.value = ''
  } catch (error) {
    assistantMessage.error = cleanError(error)
  } finally {
    assistantMessage.generating = false
    generating.value = false
    scrollToEnd()
  }
}

async function saveImage(url) {
  try {
    const response = await fetch(url)
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = `generated-${Date.now()}.png`
    link.click()
    URL.revokeObjectURL(objectUrl)
  } catch {
    previewImage.value = url
  }
}

async function saveToLibrary(url) {
  if (!window.pywebview?.api) {
    setAssetNotice(url, 'error', '请从桌面客户端启动后再保存到素材库')
    return
  }
  assetSaving.value = { ...assetSaving.value, [url]: 'saving' }
  try {
    const saved = await window.pywebview.api.save_image_data_url(url, 'generated.png')
    const path = String(saved?.path || '').trim()
    if (!path) throw new Error('图片保存失败')
    const uploaded = await window.pywebview.api.upload_local_reference_file(props.token, path, {
      imageName: `图片生成-${Date.now().toString(36)}`,
      description: '来自图片生成',
      tags: 'image-generation',
      boundProjectIds: [],
    })
    if (!uploaded || (!uploaded.id && !uploaded.coverId)) throw new Error('素材入库失败')
    assetSaving.value = { ...assetSaving.value, [url]: 'saved' }
    setAssetNotice(url, 'success', '已保存到素材库')
  } catch (error) {
    assetSaving.value = { ...assetSaving.value, [url]: '' }
    setAssetNotice(url, 'error', `保存到素材库失败：${cleanError(error)}`)
  }
}

function setAssetNotice(url, type, text) {
  const message = messages.value.find(item => Array.isArray(item.images) && item.images.includes(url))
  if (message) message.assetNotice = { type, text }
}

function clearConversation() {
  messages.value = []
  pendingReference.value = null
}

function newConversation() {
  const now = new Date().toISOString()
  const conversation = {
    id: `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    title: '新对话',
    messages: [],
    createdAt: now,
    updatedAt: now,
  }
  conversations.value.unshift(conversation)
  activeConversationId.value = conversation.id
  messages.value = []
  pendingReference.value = null
  draft.value = ''
  nextTick(() => draftInput.value?.focus())
  return conversation
}

function conversationTitle(messagesList) {
  const firstUser = messagesList.find(message => message.role === 'user' && String(message.text || '').trim())
  if (!firstUser) return '新对话'
  const text = String(firstUser.text).trim().replace(/\s+/g, ' ')
  return text.length > 18 ? `${text.slice(0, 18)}…` : text
}

function serializeMessages() {
  return messages.value
    .filter(message => message.role !== 'system-status')
    .map(message => ({
      id: message.id,
      role: message.role,
      text: message.text || '',
      reference: message.reference || '',
      images: Array.isArray(message.images) ? message.images : [],
      error: message.error || '',
    }))
    .slice(-MAX_MESSAGES_PER_CONVERSATION)
}

function schedulePersist() {
  if (!activeConversationId.value) return
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(() => { persistConversation() }, 400)
}

async function persistConversation() {
  const id = activeConversationId.value
  const conversation = conversations.value.find(item => item.id === id)
  if (!conversation) return
  const payload = serializeMessages()
  conversation.messages = payload
  conversation.title = conversationTitle(payload)
  conversation.updatedAt = new Date().toISOString()
  try {
    await request('PUT', `/image-conversation/${encodeURIComponent(id)}`, {
      title: conversation.title,
      messages: conversation.messages,
      updatedAt: conversation.updatedAt,
    })
  } catch {
    // 本地列表仍保留，远端失败不打断生成流程
  }
}

async function loadConversations() {
  conversationsLoading.value = true
  try {
    const result = await request('GET', '/image-conversation/list')
    conversations.value = (Array.isArray(result) ? result : []).map(item => ({
      ...item,
      messages: Array.isArray(item.messages) ? item.messages : [],
    }))
  } catch {
    conversations.value = []
  } finally {
    conversationsLoading.value = false
  }
}

async function openConversation(id) {
  if (generating.value || id === activeConversationId.value) return
  const conversation = conversations.value.find(item => item.id === id)
  if (!conversation) return
  activeConversationId.value = id
  messages.value = (conversation.messages || []).map(message => ({
    ...message,
    images: Array.isArray(message.images) ? message.images : [],
    generating: false,
  }))
  pendingReference.value = null
  scrollToEnd()
}

async function removeConversation(id) {
  if (generating.value) return
  conversations.value = conversations.value.filter(item => item.id !== id)
  try {
    await request('DELETE', `/image-conversation/${encodeURIComponent(id)}`)
  } catch {
    // 忽略远端删除失败
  }
  if (activeConversationId.value === id) {
    activeConversationId.value = ''
    messages.value = []
    pendingReference.value = null
  }
}

function conversationPreview(conversation) {
  const list = Array.isArray(conversation.messages) ? conversation.messages : []
  const lastWithText = [...list].reverse().find(message => String(message.text || '').trim() || (message.images || []).length)
  if (!lastWithText) return '还没有内容'
  const text = String(lastWithText.text || '').trim().replace(/\s+/g, ' ')
  if (text) return text.length > 22 ? `${text.slice(0, 22)}…` : text
  return `[${(lastWithText.images || []).length} 张图片]`
}

function formatConversationTime(value) {
  const time = new Date(value || Date.now())
  if (Number.isNaN(time.getTime())) return ''
  const diff = Date.now() - time.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return `${time.getMonth() + 1}月${time.getDate()}日`
}

async function ensureActiveConversation() {
  if (activeConversationId.value) return
  const conversation = {
    id: `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    title: '新对话',
    messages: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
  conversations.value.unshift(conversation)
  activeConversationId.value = conversation.id
  try {
    await request('POST', '/image-conversation', {
      id: conversation.id,
      title: conversation.title,
      messages: conversation.messages,
    })
  } catch {
    // 远端创建失败也保留本地会话，后续持久化会重试
  }
}

watch(messages, () => { scrollToEnd(); schedulePersist() }, { deep: true })

function flushPersist() {
  if (!persistTimer) return
  clearTimeout(persistTimer)
  persistTimer = null
  persistConversation()
}

onMounted(async () => {
  loadModels()
  await loadConversations()
  if (conversations.value.length) {
    await openConversation(conversations.value[0].id)
  }
})
onActivated(() => { scrollToEnd() })
onDeactivated(() => { flushPersist() })
onBeforeUnmount(() => { flushPersist() })
</script>

<style scoped>
.image-chat-workspace { display: flex; gap: 16px; width: min(1200px, 100%); margin: 0 auto; padding: 20px 24px; min-height: 0; }
.image-chat-sidebar { display: flex; flex-direction: column; gap: 10px; flex: 0 0 236px; min-height: 0; height: clamp(520px, calc(100dvh - 144px), 900px); }
.image-chat-new { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 11px 14px; border: 1px solid #3a3a42; border-radius: 12px; color: #ededf0; background: #ffffff08; font-size: 13px; font-weight: 500; cursor: pointer; transition: border-color .15s, background .15s; }
.image-chat-new svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; }
.image-chat-new:hover:not(:disabled) { border-color: #ffffff33; background: #ffffff12; }
.image-chat-new:disabled { opacity: .45; cursor: not-allowed; }
.image-chat-conversations { display: flex; flex: 1; flex-direction: column; gap: 4px; min-height: 0; overflow-y: auto; padding-right: 2px; scrollbar-width: thin; scrollbar-color: #39393f transparent; }
.image-chat-conversations-tip { margin: 12px 4px; color: #6f6f78; font-size: 12px; text-align: center; }
.image-chat-conversation { display: flex; align-items: center; gap: 8px; padding: 9px 10px 9px 12px; border: 1px solid transparent; border-radius: 10px; cursor: pointer; transition: background .15s, border-color .15s; }
.image-chat-conversation:hover { background: #ffffff06; }
.image-chat-conversation.active { border-color: #ffffff16; background: #ffffff0c; }
.image-chat-conversation-main { display: grid; gap: 3px; flex: 1; min-width: 0; }
.image-chat-conversation-main strong { color: #dcdce1; font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.image-chat-conversation-main span { color: #7b7b85; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.image-chat-conversation-meta { display: grid; justify-items: end; gap: 4px; flex: 0 0 auto; }
.image-chat-conversation-meta time { color: #66666f; font-size: 10px; white-space: nowrap; }
.image-chat-conversation-meta button { display: grid; place-items: center; width: 22px; height: 22px; border: 1px solid transparent; border-radius: 6px; color: #7b7b85; background: transparent; opacity: 0; cursor: pointer; transition: opacity .15s, color .15s, background .15s; }
.image-chat-conversation:hover .image-chat-conversation-meta button { opacity: 1; }
.image-chat-conversation-meta button:hover:not(:disabled) { color: #ff8f8f; background: #ff7a7a14; }
.image-chat-conversation-meta button:disabled { cursor: not-allowed; }
.image-chat-conversation-meta button svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.image-chat-panel { display: flex; flex: 1; flex-direction: column; min-width: 0; height: clamp(520px, calc(100dvh - 144px), 900px); min-height: 0; border: 1px solid #303035; border-radius: 22px; background: #141416; box-shadow: 0 20px 60px #0003, inset 0 1px 0 #ffffff04; }
.image-chat-heading { display: flex; align-items: center; gap: 12px; padding: 20px 24px 0; }
.image-chat-heading-icon, .image-chat-avatar { display: grid; place-items: center; flex: 0 0 auto; border: 1px solid #ffffff10; color: #dedee3; background: #242428; }
.image-chat-heading-icon { width: 38px; height: 38px; border-radius: 12px; }
.image-chat-heading-icon svg, .image-chat-avatar svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.image-chat-heading h1 { margin: 0; color: #ededf0; font-size: 16px; font-weight: 600; }
.image-chat-heading p { margin: 4px 0 0; color: #89898f; font-size: 12px; }
.image-chat-clear { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: auto; padding: 8px 10px; border: 1px solid transparent; border-radius: 8px; color: #a4a4ab; background: transparent; font-size: 12px; cursor: pointer; }
.image-chat-clear svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.image-chat-clear:hover:not(:disabled) { color: #ededf0; background: #ffffff08; }
.image-chat-clear:disabled { opacity: .4; cursor: not-allowed; }
.image-chat-scroll { display: flex; flex: 1; flex-direction: column; gap: 24px; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 16px 28px; scrollbar-width: thin; scrollbar-color: #39393f transparent; }
.image-chat-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; flex-shrink: 0; margin: auto; padding: 2px 0; text-align: center; }
.image-chat-empty-icon { display: grid; place-items: center; width: 44px; height: 44px; border: 1px solid #ffffff15; border-radius: 14px; color: #e4e4e9; background: linear-gradient(145deg, #303037, #1c1c20); box-shadow: 0 8px 28px #0003, inset 0 1px 0 #ffffff08; }
.image-chat-empty-icon svg { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linejoin: round; }
.image-chat-empty strong { color: #ededf0; font-size: 20px; font-weight: 600; line-height: 1.3; letter-spacing: .02em; }
.image-chat-empty > span { color: #94949d; font-size: 12px; line-height: 1.65; }
.image-chat-suggestions { display: flex; justify-content: center; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.image-chat-suggestions button { display: flex; align-items: center; gap: 18px; padding: 6px 12px; border: 1px solid #ffffff10; border-radius: 10px; color: #b5b5bd; background: #ffffff03; font-size: 12px; cursor: pointer; transition: border-color .15s, background .15s; }
.image-chat-suggestions button span { color: #73737e; }
.image-chat-suggestions button:hover { border-color: #ffffff26; color: #eee; background: #ffffff08; }
.image-chat-message { display: flex; align-items: flex-start; gap: 10px; flex-shrink: 0; }
.image-chat-message.user { flex-direction: row-reverse; }
.image-chat-avatar { width: 30px; height: 30px; margin-top: 22px; border-radius: 10px; }
.image-chat-message.user .image-chat-avatar { color: #a8a8b1; background: #202024; }
.image-chat-message-content { min-width: 0; max-width: 80%; }
.image-chat-message-name { display: block; margin: 0 0 7px 2px; color: #93939d; font-size: 11px; line-height: 1.4; }
.image-chat-message.user .image-chat-message-name { margin-right: 2px; text-align: right; }
.image-chat-message.system-status { justify-content: center; }
.image-chat-message.system-status .image-chat-bubble { padding: 7px 12px; border-radius: 999px; color: #9e9ea8; background: #ffffff04; font-size: 12px; }
.image-chat-bubble { display: grid; gap: 12px; min-width: 0; padding: 14px 16px; border: 1px solid #ffffff0b; border-radius: 4px 16px 16px 16px; color: #e4e4e9; background: #1c1c21; font-size: 13px; line-height: 1.75; }
.image-chat-message.user .image-chat-bubble { border-color: #ffffff12; border-radius: 16px 4px 16px 16px; background: #303038; }
.image-chat-message.system .image-chat-bubble { border-color: #ff7a7a20; background: #ff7a7a08; }
.image-chat-bubble.is-generating { padding: 0; border: 0; border-radius: 0; background: transparent; }
.image-chat-text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.image-chat-reference { display: block; width: min(200px, 100%); border-radius: 10px; }
.image-chat-result-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.image-chat-result-card { position: relative; display: block; margin: 0; overflow: hidden; border: 1px solid #ffffff14; border-radius: 14px; background: #17171b; box-shadow: 0 10px 30px #0004, inset 0 1px 0 #ffffff08; transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease; }
.image-chat-result-card:hover { border-color: #ffffff2e; box-shadow: 0 14px 38px #0006, inset 0 1px 0 #ffffff0f; transform: translateY(-2px); }
.image-chat-result { display: block; width: min(320px, 100%); max-height: 400px; object-fit: contain; cursor: zoom-in; }
.image-chat-result-tools { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-top: 1px solid #ffffff0f; background: linear-gradient(180deg, #1f1f24, #1a1a1e); }
.image-chat-tool { display: inline-flex; align-items: center; gap: 6px; flex: 1; justify-content: center; padding: 7px 8px; border: 1px solid #ffffff12; border-radius: 9px; color: #c2c2cc; background: #ffffff05; font-size: 12px; cursor: pointer; white-space: nowrap; transition: border-color .15s, color .15s, background .15s; }
.image-chat-tool svg { width: 14px; height: 14px; flex: 0 0 14px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.image-chat-tool:hover:not(:disabled) { border-color: #ffffff2e; color: #fff; background: #ffffff12; }
.image-chat-tool:disabled { cursor: default; opacity: .7; }
.image-chat-tool .spinner { width: 13px; height: 13px; flex: 0 0 13px; border-width: 2px; }
.image-chat-generating { width: 180px; max-width: 100%; }
.image-chat-generating-placeholder { position: relative; width: 100%; aspect-ratio: 1; overflow: hidden; border: 1px solid #ffffff10; border-radius: 17px; background: linear-gradient(180deg, #232329, #1c1c21); }
.image-chat-error { margin: 0; color: #ff9999; overflow-wrap: anywhere; }
.image-chat-asset-notice { margin: 0; font-size: 12px; line-height: 1.6; }
.image-chat-asset-notice.success { color: #8fd6a6; }
.image-chat-asset-notice.error { color: #ff9999; }
.image-chat-composer-area { flex-shrink: 0; padding: 14px 24px 16px; background: linear-gradient(0deg, #141416 78%, transparent); border-radius: 0 0 22px 22px; }
.image-chat-composer { position: relative; display: flex; flex-direction: column; gap: 6px; padding: 16px 16px 12px; border: 1px solid #3b3b44; border-radius: 20px; background: linear-gradient(180deg, #232329, #1c1c21); box-shadow: 0 10px 34px #0004, inset 0 1px 0 #ffffff0a; transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease; }
.image-chat-composer:focus-within { border-color: #5c5c6b; box-shadow: 0 14px 40px #0005, 0 0 0 3px #ffffff07, inset 0 1px 0 #ffffff10; }
.image-chat-file { display: none; }
.image-chat-composer textarea { display: block; flex: none; width: 100%; min-width: 0; min-height: 84px; max-height: 200px; padding: 2px 4px 0; border: 0; border-radius: 0; outline: none; color: #f0f0f3; background: transparent; box-shadow: none; font-size: 14px; line-height: 1.85; letter-spacing: .01em; resize: none; }
.image-chat-composer textarea:focus { border: 0; box-shadow: none; }
.image-chat-composer textarea::placeholder { color: #83838f; }
.image-chat-composer-tools { display: flex; align-items: center; gap: 8px; padding-top: 2px; }
.image-chat-model-select { flex: 0 1 auto; width: clamp(150px, 28%, 240px); min-width: 0; }
.image-chat-model-select :deep(.ui-select-trigger) { min-height: 34px; padding: 0 11px; border-radius: 999px; border-color: #ffffff12; background: #ffffff05; box-shadow: none; }
.image-chat-model-select :deep(.ui-select-trigger:hover) { border-color: #ffffff2e; background: #ffffff0e; }
.image-chat-model-select :deep(.ui-select-value) { font-size: 12px; font-weight: 500; }
.image-chat-attach { display: flex; align-items: center; justify-content: center; gap: 7px; flex: 0 0 auto; height: 34px; padding: 0 11px; border: 1px solid #ffffff12; border-radius: 999px; color: #c2c2cc; background: #ffffff05; font-size: 12px; cursor: pointer; transition: border-color .15s, color .15s, background .15s; }
.image-chat-attach svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.image-chat-attach:hover:not(:disabled) { border-color: #ffffff2e; color: #fff; background: #ffffff0e; }
.image-chat-attach:disabled { opacity: .4; cursor: not-allowed; }
.image-chat-draft-count { margin-left: auto; padding-right: 2px; color: #7c7c88; font-size: 11px; font-variant-numeric: tabular-nums; }
.image-chat-send { display: flex; align-items: center; justify-content: center; gap: 8px; flex: 0 0 auto; width: auto; min-width: 88px; height: 38px; padding: 0 16px; border: 1px solid #ffffff; border-radius: 999px; color: #17171b; background: linear-gradient(180deg, #ffffff, #e2e2e8); font-size: 13px; font-weight: 600; cursor: pointer; box-shadow: 0 6px 18px #0003; transition: transform .15s, box-shadow .15s, background .15s; }
.image-chat-send svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
.image-chat-send:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 10px 24px #0004; background: #fff; }
.image-chat-send:active:not(:disabled) { transform: translateY(0); }
.image-chat-send:disabled { border-color: #ffffff0a; color: #80808c; background: #33333b; box-shadow: none; cursor: not-allowed; }
.image-chat-send .spinner { width: 14px; height: 14px; border: 2px solid #ffffff25; border-top-color: #bdbdc7; border-radius: 50%; animation: image-chat-spin .8s linear infinite; }
@keyframes image-chat-spin { to { transform: rotate(360deg); } }
.image-chat-composer-hint { display: flex; justify-content: center; gap: 8px; margin: 10px 0 0; color: #7d7d87; font-size: 11px; }
.image-chat-composer-hint span { color: #56565e; }
.image-chat-attachment { display: flex; align-items: center; gap: 10px; align-self: flex-start; max-width: 100%; margin-bottom: 10px; padding: 8px 10px; border: 1px solid #ffffff14; border-radius: 12px; background: #ffffff07; box-shadow: inset 0 1px 0 #ffffff08; }
.image-chat-attachment img { width: 44px; height: 44px; flex-shrink: 0; border-radius: 8px; object-fit: cover; }
.image-chat-attachment > div { display: grid; gap: 3px; min-width: 0; }
.image-chat-attachment strong { color: #e2e2e8; font-size: 11px; font-weight: 600; }
.image-chat-attachment span { overflow: hidden; color: #97979f; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.image-chat-attachment button { display: grid; place-items: center; align-self: center; flex-shrink: 0; width: 24px; height: 24px; border: 0; border-radius: 999px; color: #b0b0ba; background: transparent; font-size: 18px; line-height: 1; cursor: pointer; transition: color .15s, background .15s; }
.image-chat-attachment button:hover { color: #fff; background: #ffffff14; }
.image-chat-clear:focus-visible, .image-chat-suggestions button:focus-visible, .image-chat-attach:focus-visible, .image-chat-send:focus-visible, .image-chat-attachment button:focus-visible { outline: 2px solid #b7b7c5; outline-offset: 3px; }
.image-chat-lightbox { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 32px; background: #000c; cursor: zoom-out; }
.image-chat-lightbox img { max-width: 92vw; max-height: 92vh; border-radius: 12px; }
@media (max-width: 640px) {
  .image-chat-workspace { flex-direction: column; gap: 10px; padding: 20px 12px 24px; }
  .image-chat-sidebar { flex: 0 0 auto; height: auto; }
  .image-chat-conversations { flex-direction: row; gap: 8px; overflow-x: auto; overflow-y: hidden; padding-bottom: 4px; }
  .image-chat-conversation { flex: 0 0 200px; }
  .image-chat-conversation-meta button { opacity: 1; }
  .image-chat-panel { height: max(580px, 75vh); border-radius: 18px; }
  .image-chat-heading { gap: 10px; padding: 16px 14px 0; }
  .image-chat-heading p { font-size: 11px; }
  .image-chat-heading-icon { width: 32px; height: 32px; border-radius: 10px; }
  .image-chat-clear { gap: 4px; padding: 8px 4px; font-size: 11px; }
  .image-chat-scroll { gap: 20px; padding: 20px 14px; }
  .image-chat-empty strong { font-size: 20px; }
  .image-chat-empty > span { font-size: 12px; }
  .image-chat-suggestions { gap: 6px; }
  .image-chat-suggestions button { gap: 8px; padding: 8px 9px; font-size: 11px; }
  .image-chat-message-content { max-width: calc(100% - 40px); }
  .image-chat-bubble { padding: 12px; }
  .image-chat-composer-area { padding: 8px 12px 12px; }
  .image-chat-composer { padding: 12px; }
  .image-chat-composer-tools { gap: 8px; }
  .image-chat-send { min-width: 72px; padding: 0 10px; }
}
</style>
