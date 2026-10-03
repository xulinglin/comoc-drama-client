<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import BaseLoadingState from './BaseLoadingState.vue'

const props = defineProps({
  projectId: { type: [String, Number], required: true },
  token: { type: String, required: true },
})
const emit = defineEmits(['back'])

const project = ref(null)
const chapters = ref([])
const selectedChapterId = ref('')
const loading = ref(true)
const error = ref('')
const chapterError = ref('')
const content = ref('')
const viewMode = ref('text')
const saveStatus = ref('')
let saveTimer = null
let savedTimer = null

const selectedChapter = computed(() => chapters.value.find(item => String(item.id) === String(selectedChapterId.value)) || null)
const characterCount = computed(() => content.value.replace(/\s/g, '').length)

// markdown 渲染：解析章节原文为 HTML，并提取 h1/h2/h3 作为左侧目录锚点
marked.setOptions({ breaks: true, gfm: true })
const markdownDocument = computed(() => {
  const source = content.value || ''
  if (!source.trim()) return { html: '', headings: [] }
  try {
    const html = marked.parse(source)
    // 用 template 解析 HTML，给每个标题加 id 用于锚点跳转
    const template = document.createElement('template')
    template.innerHTML = html
    const headings = Array.from(template.content.querySelectorAll('h1, h2, h3'))
      .map((heading, index) => {
        const id = `client-markdown-heading-${index + 1}`
        heading.id = id
        return {
          id,
          text: heading.textContent?.trim() || `标题 ${index + 1}`,
          level: Number(heading.tagName.slice(1)),
        }
      })
    return { html: template.innerHTML, headings }
  } catch {
    return { html: '', headings: [] }
  }
})
const renderedMarkdown = computed(() => markdownDocument.value.html)
const markdownHeadings = computed(() => markdownDocument.value.headings)

function scrollToMarkdownHeading(headingId) {
  document.getElementById(headingId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function cleanError(err) { return String(err).replace(/^Error:\s*/, '') }
async function request(method, path, body = null) {
  if (import.meta.env.DEV && !window.pywebview?.api) {
    if (path === `/project/${props.projectId}`) return { id: props.projectId, name: '我不是丹神', description: '顾卿之，京城第一纨绔，镇国公嫡孙', style: '3D国漫 · 修仙玄幻', ratio: '16:9', updateTime: '2026-08-06' }
    if (path.endsWith('/chapter/list')) return [
      { id: 'c1', title: '第一章 丹神觉醒', content: '夜色沉沉，长安城的钟声刚刚响过三更。\n\n顾卿之推开丹房的门，发现那只失传百年的青铜丹炉正在发光……', workflow: {} },
      { id: 'c2', title: '第二章 城中异象', content: '', workflow: {} },
      { id: 'c3', title: '第三章 故人来访', content: '', workflow: {} },
    ]
    if (method === 'POST') return { id: `c${Date.now()}`, title: '新章节', content: '', workflow: {} }
    return body
  }
  return window.pywebview.api.backend_request(method, path, props.token, body)
}

function selectChapter(chapter) {
  if (saveTimer) saveChapter()
  selectedChapterId.value = String(chapter.id)
  content.value = chapter.workflow?.novel || chapter.content || ''
  saveStatus.value = ''
  chapterError.value = ''
}

async function loadDetail() {
  loading.value = true
  error.value = ''
  try {
    const [projectData, chapterData] = await Promise.all([
      request('GET', `/project/${props.projectId}`),
      request('GET', `/project/${props.projectId}/chapter/list`),
    ])
    project.value = projectData
    chapters.value = chapterData || []
    if (chapters.value.length) selectChapter(chapters.value[0])
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    loading.value = false
  }
}

async function addChapter() {
  chapterError.value = ''
  try {
    const created = await request('POST', `/project/${props.projectId}/chapter`, { title: '新章节', content: '', workflow: {} })
    chapters.value.push(created)
    selectChapter(created)
  } catch (err) { chapterError.value = cleanError(err) }
}

async function deleteChapter(chapter) {
  if (!window.confirm(`确认删除章节“${chapter.title || '未命名章节'}”？`)) return
  try {
    await request('DELETE', `/chapter/${chapter.id}`)
    chapters.value = chapters.value.filter(item => String(item.id) !== String(chapter.id))
    if (String(selectedChapterId.value) === String(chapter.id)) {
      selectedChapterId.value = ''
      content.value = ''
      if (chapters.value.length) selectChapter(chapters.value[0])
    }
  } catch (err) { chapterError.value = cleanError(err) }
}

async function saveChapter() {
  const chapter = selectedChapter.value
  if (!chapter) return
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = null
  const savedContent = content.value
  saveStatus.value = 'saving'
  const workflow = { ...(chapter.workflow || {}), novel: savedContent }
  Object.assign(chapter, { content: savedContent, workflow })
  try {
    const saved = await request('PUT', `/chapter/${chapter.id}`, { title: chapter.title || '未命名章节', content: savedContent, script: chapter.script || '', workflow })
    if (chapter.content === savedContent) Object.assign(chapter, saved || {}, { content: savedContent, workflow })
    if (String(selectedChapterId.value) === String(chapter.id) && content.value === savedContent) {
      saveStatus.value = 'saved'
      if (savedTimer) window.clearTimeout(savedTimer)
      savedTimer = window.setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = '' }, 1800)
    }
  } catch (err) {
    if (String(selectedChapterId.value) === String(chapter.id)) {
      saveStatus.value = 'error'
      chapterError.value = cleanError(err)
    }
  }
}

watch(content, () => {
  if (!selectedChapter.value || loading.value) return
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(saveChapter, 1200)
})

onMounted(loadDetail)
onBeforeUnmount(() => { if (saveTimer) saveChapter(); if (savedTimer) window.clearTimeout(savedTimer) })
</script>

<template>
  <section class="client-detail-page">
    <header class="client-detail-header">
      <button class="client-detail-back" @click="emit('back')"><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6" /></svg>返回</button>
      <div v-if="project" class="client-detail-heading">
        <h1>{{ project.name || '未命名项目' }}</h1>
        <div class="client-detail-meta">
          <span v-if="project.style" class="style-pill">{{ project.style }}</span><span v-if="project.ratio" class="ratio-pill">{{ project.ratio }}</span>
          <p>{{ project.description || '暂未添加项目简介' }}</p><time v-if="project.updateTime">更新于 {{ String(project.updateTime).slice(0, 10) }}</time>
        </div>
      </div>
    </header>

    <div v-if="loading" class="client-detail-state" role="status" aria-live="polite">
      <BaseLoadingState size="lg" panel text="正在打开项目" description="正在同步项目详情与章节内容…" />
    </div>
    <div v-else-if="error" class="client-detail-state error">{{ error }}</div>
    <div v-else class="client-detail-body">
      <aside class="client-chapter-sidebar">
        <header><div><strong>章节目录</strong><span>{{ chapters.length }}</span></div><button data-tooltip="新增章节" aria-label="新增章节" @click="addChapter"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg></button></header>
        <p v-if="!chapters.length" class="client-chapter-empty">还没有章节<br>点击右上角 + 新增第一个章节</p>
        <ul v-else>
          <li v-for="(chapter, index) in chapters" :key="chapter.id" :class="{ active: String(chapter.id) === String(selectedChapterId) }">
            <button class="chapter-select" @click="selectChapter(chapter)"><span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ chapter.title || '未命名章节' }}</strong></button>
            <button class="chapter-remove" data-tooltip="删除章节" aria-label="删除章节" @click="deleteChapter(chapter)"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></svg></button>
          </li>
        </ul>
      </aside>

      <main class="client-chapter-main">
        <div v-if="!selectedChapter" class="client-main-empty">从左侧选择一个章节开始编辑</div>
        <template v-else>
          <p v-if="chapterError" class="client-detail-error">{{ chapterError }}</p>
          <nav class="client-stage-stepper"><button class="active"><span>1</span>原文</button></nav>
          <div class="client-stage-header">
            <div><h2>原文</h2><p>输入或粘贴需要改编的内容 <span>{{ characterCount.toLocaleString() }} 字</span></p></div>
            <div class="client-stage-tools"><span class="client-save-status" :class="saveStatus">{{ saveStatus === 'saving' ? '保存中…' : saveStatus === 'saved' ? '✓ 已保存' : saveStatus === 'error' ? '保存失败' : '' }}</span><div class="client-view-tabs"><button :class="{ active: viewMode === 'text' }" @click="viewMode = 'text'">文本</button><button :class="{ active: viewMode === 'preview' }" @click="viewMode = 'preview'">预览</button></div></div>
          </div>
          <textarea v-if="viewMode === 'text'" v-model="content" class="client-stage-editor" placeholder="在这里写「原文」…" @blur="saveChapter"></textarea>
          <div v-else class="client-markdown-shell">
            <aside v-if="markdownHeadings.length" class="client-markdown-toc" aria-label="Markdown 目录">
              <strong>目录</strong>
              <nav>
                <button
                  v-for="heading in markdownHeadings"
                  :key="heading.id"
                  type="button"
                  :class="`is-level-${heading.level}`"
                  :data-tooltip="heading.text"
                  @click="scrollToMarkdownHeading(heading.id)"
                >{{ heading.text }}</button>
              </nav>
            </aside>
            <div class="client-markdown-view">
              <article
                v-if="renderedMarkdown"
                class="client-markdown-content"
                v-html="renderedMarkdown"
              ></article>
              <p v-else class="client-markdown-empty">暂无原文，切到「文本」输入内容</p>
            </div>
          </div>
        </template>
      </main>
    </div>
  </section>
</template>

<style scoped>
.client-detail-page{position:relative;z-index:1;display:flex;width:100%;height:calc(100vh - 98px);min-height:0;flex-direction:column;padding:20px 28px 25px;overflow:hidden;box-sizing:border-box}.client-detail-header{display:flex;flex:0 0 auto;align-items:flex-start;gap:16px;margin-bottom:18px}.client-detail-back{display:inline-flex;height:32px;align-items:center;gap:6px;padding:0 10px;border:1px solid transparent;border-radius:8px;color:#aaa;background:transparent;cursor:pointer;font-size:13px}.client-detail-back:hover{color:#fff;background:#292929}.client-detail-back svg{width:15px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}.client-detail-heading{min-width:0;flex:1}.client-detail-heading h1{margin:0 0 7px;color:#f2f2f2;font-size:22px;line-height:1.3}.client-detail-meta{display:flex;align-items:center;gap:8px;min-width:0}.client-detail-meta>span{position:relative;display:inline-flex;height:23px;padding:0 9px;align-items:center;border:1px solid #3c3c3c;border-radius:6px;color:#aaa;background:#202020;font-size:11px;font-weight:600;line-height:1;white-space:nowrap;box-shadow:inset 0 1px 0 rgba(255,255,255,0.04)}.client-detail-meta .style-pill{gap:6px;padding-left:7px;max-width:160px;overflow:hidden;text-overflow:ellipsis;border-color:color-mix(in srgb, var(--theme-accent) 38%, #3c3c3c);color:#f2f2f2;background:color-mix(in srgb, var(--theme-accent) 8%, #202020)}.client-detail-meta .style-pill::before{width:3px;height:11px;flex:0 0 3px;border-radius:2px;background:var(--theme-accent);content:''}.client-detail-meta .ratio-pill{color:#8a8a8a;font-variant-numeric:tabular-nums}.client-detail-meta p{min-width:0;max-width:520px;margin:0;overflow:hidden;color:#8a8a8a;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.client-detail-meta time{margin-left:auto;color:#666;font-size:12px;white-space:nowrap}.client-detail-body{display:grid;min-height:0;flex:1;grid-template-columns:280px 1fr;gap:18px}.client-chapter-sidebar{display:flex;min-height:0;flex-direction:column;overflow:hidden;border:1px solid #383838;border-radius:9px;background:#1c1c1c}.client-chapter-sidebar>header{display:flex;min-height:54px;align-items:center;justify-content:space-between;padding:0 12px 0 15px;border-bottom:1px solid #303030}.client-chapter-sidebar>header>div{display:flex;align-items:center;gap:8px;font-size:14px}.client-chapter-sidebar>header span{display:grid;min-width:20px;height:20px;padding:0 5px;place-items:center;border:1px solid #363636;border-radius:5px;color:#777;background:#161616;font-size:12px}.client-chapter-sidebar>header button{display:grid;width:30px;height:30px;place-items:center;border:1px solid color-mix(in srgb, var(--theme-accent) 27%, transparent);border-radius:7px;color:var(--theme-accent);background:color-mix(in srgb, var(--theme-accent) 7%, transparent);cursor:pointer}.client-chapter-sidebar>header svg{width:15px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}.client-chapter-sidebar ul{min-height:0;flex:1;margin:0;padding:7px;overflow:hidden auto;list-style:none}.client-chapter-sidebar li{position:relative;display:flex;height:46px;align-items:center;border:1px solid transparent;border-radius:7px}.client-chapter-sidebar li+li{margin-top:3px}.client-chapter-sidebar li:hover{border-color:#373737;background:#242424}.client-chapter-sidebar li.active{border-color:color-mix(in srgb, var(--theme-accent) 22%, transparent);background:color-mix(in srgb, var(--theme-accent) 9%, transparent)}.client-chapter-sidebar li.active::before{position:absolute;top:10px;bottom:10px;left:0;width:3px;border-radius:0 3px 3px 0;background:var(--theme-accent);content:''}.chapter-select{display:flex;width:100%;height:100%;min-width:0;align-items:center;gap:11px;padding:0 40px 0 12px;border:0;color:#ddd;background:transparent;text-align:left;cursor:pointer}.chapter-select span{display:grid;width:24px;height:24px;flex:0 0 24px;place-items:center;border:1px solid #373737;border-radius:5px;color:#777;font-size:12px}.active .chapter-select span{border-color:color-mix(in srgb, var(--theme-accent) 33%, transparent);color:var(--theme-accent);background:color-mix(in srgb, var(--theme-accent) 12%, transparent)}.chapter-select strong{overflow:hidden;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.chapter-remove{position:absolute;right:7px;display:grid;width:28px;height:28px;place-items:center;border:0;border-radius:6px;color:#666;background:transparent;cursor:pointer;opacity:0}.client-chapter-sidebar li:hover .chapter-remove,.client-chapter-sidebar li.active .chapter-remove{opacity:1}.chapter-remove:hover{color:#ff8299;background:#ff456012}.chapter-remove svg{width:14px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}.client-chapter-empty{padding:35px 15px;color:#777;text-align:center;font-size:13px;line-height:1.8}.client-chapter-main{display:flex;min-width:0;min-height:0;flex-direction:column;gap:12px;overflow:hidden}.client-main-empty{display:grid;height:100%;place-items:center;border:1px dashed #373737;border-radius:12px;color:#777;font-size:14px}.client-stage-stepper{display:flex;padding:6px;border:1px solid #323232;border-radius:12px;background:#1c1c1c}.client-stage-stepper button{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border:1px solid var(--theme-accent);border-radius:8px;color:var(--theme-accent);background:color-mix(in srgb, var(--theme-accent) 9%, transparent);font-size:13px}.client-stage-stepper span{display:grid;width:22px;height:22px;place-items:center;border-radius:50%;color:#0b171a;background:var(--theme-accent);font-size:12px;font-weight:800}.client-stage-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:2px}.client-stage-header h2{margin:0;color:#eee;font-size:14px}.client-stage-header p{margin:3px 0 0;color:#777;font-size:12px}.client-stage-header p span{margin-left:8px;padding-left:8px;border-left:1px solid #3a3a3a}.client-stage-tools{display:flex;align-items:center;gap:10px}.client-save-status{width:62px;color:#777;font-size:12px;text-align:right}.client-save-status.saved{color:#60c99a}.client-save-status.error{color:#ff7898}.client-view-tabs{display:flex;padding:3px;border:1px solid #343434;border-radius:8px;background:#1c1c1c}.client-view-tabs button{height:26px;padding:0 12px;border:0;border-radius:6px;color:#777;background:transparent;cursor:pointer;font-size:12px}.client-view-tabs button.active{color:#eee;background:#303030}.client-stage-editor,.client-stage-preview{width:100%;min-height:0;flex:1;margin:0;padding:16px;border:1px solid #323232;border-radius:11px;outline:0;color:#ddd;background:#151515;font:14px/1.8 inherit;box-sizing:border-box}.client-stage-editor{resize:none}.client-stage-editor:focus{border-color:color-mix(in srgb, var(--theme-accent) 40%, transparent)}.client-stage-preview{overflow:auto;white-space:normal;padding:24px 28px}
.client-markdown-shell{display:grid;grid-template-columns:200px minmax(0,1fr);flex:1;min-height:0;gap:12px}
.client-markdown-toc{min-height:0;overflow-y:auto;padding:16px 12px;border:1px solid #303030;border-radius:12px;background:#181818}
.client-markdown-toc>strong{display:flex;align-items:center;gap:6px;margin:0 4px 12px;color:#f2f2f2;font-size:13px;font-weight:700;letter-spacing:.04em}
.client-markdown-toc>strong::before{content:'';width:3px;height:14px;border-radius:2px;background:var(--theme-accent)}
.client-markdown-toc nav{display:grid;gap:3px}
.client-markdown-toc button{position:relative;width:100%;overflow:hidden;padding:7px 10px 7px 14px;border:0;border-radius:7px;color:#b8b8b8;background:transparent;font:inherit;font-size:12px;font-weight:500;line-height:18px;text-align:left;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;transition:color 150ms ease,background-color 150ms ease}
.client-markdown-toc button::before{content:'';position:absolute;left:6px;top:50%;width:4px;height:4px;border-radius:50%;background:#555;transform:translateY(-50%);transition:background-color 150ms ease}
.client-markdown-toc button:hover,.client-markdown-toc button:focus-visible{color:#fff;background:#262626;outline:0}
.client-markdown-toc button:hover::before{background:var(--theme-accent)}
.client-markdown-toc button.is-level-2{padding-left:24px;color:#9a9a9a}
.client-markdown-toc button.is-level-2::before{left:16px;width:3px;height:3px;background:#444}
.client-markdown-toc button.is-level-3{padding-left:34px;color:#7a7a7a;font-size:11px}
.client-markdown-toc button.is-level-3::before{left:26px;width:3px;height:3px;background:#3a3a3a}
.client-markdown-view{min-height:0;overflow-y:auto;padding:24px 28px;border:1px solid #2a2a2a;border-radius:11px;background:#151515}
.client-markdown-empty{color:#777;font-size:14px;text-align:center;padding:40px 0}
.client-markdown-content :deep(h1),.client-markdown-content :deep(h2),.client-markdown-content :deep(h3),.client-markdown-content :deep(h4),.client-markdown-content :deep(h5),.client-markdown-content :deep(h6){margin:1.4em 0 .6em;color:#f2f2f2;font-weight:700;line-height:1.3}
.client-markdown-content :deep(h1:first-child),.client-markdown-content :deep(h2:first-child),.client-markdown-content :deep(h3:first-child){margin-top:0}
.client-markdown-content :deep(h1){font-size:24px;padding-bottom:.3em;border-bottom:1px solid #2e2e2e}
.client-markdown-content :deep(h2){font-size:20px}
.client-markdown-content :deep(h3){font-size:17px}
.client-markdown-content :deep(p){margin:0 0 1em;color:#d4d4d4;font-size:14px;line-height:1.85}
.client-markdown-content :deep(ul),.client-markdown-content :deep(ol){margin:0 0 1em;padding-left:1.6em;color:#d4d4d4;font-size:14px;line-height:1.85}
.client-markdown-content :deep(li+li){margin-top:.3em}
.client-markdown-content :deep(blockquote){margin:0 0 1em;padding:8px 14px;border-left:3px solid var(--theme-accent);color:#aaa;background:rgba(255,255,255,0.03);border-radius:0 6px 6px 0}
.client-markdown-content :deep(blockquote>:last-child){margin-bottom:0}
.client-markdown-content :deep(code){padding:2px 6px;border-radius:4px;color:#ffb6a8;background:rgba(255,109,177,0.12);font-family:"Cascadia Code","Fira Code",Consolas,monospace;font-size:.92em}
.client-markdown-content :deep(pre){margin:0 0 1em;padding:14px 16px;border:1px solid #2a2a2a;border-radius:8px;background:#0d0d0d;overflow-x:auto}
.client-markdown-content :deep(pre code){padding:0;color:#e6e6e6;background:transparent;font-size:.92em}
.client-markdown-content :deep(a){color:#8be6ee;text-decoration:none;border-bottom:1px solid #2c6166}
.client-markdown-content :deep(a:hover){color:#a8f0f6;border-bottom-color:#8be6ee}
.client-markdown-content :deep(hr){margin:1.5em 0;border:0;border-top:1px solid #2a2a2a}
.client-markdown-content :deep(table){width:100%;margin:0 0 1em;border-collapse:collapse;font-size:13px}
.client-markdown-content :deep(th),.client-markdown-content :deep(td){padding:8px 12px;border:1px solid #2a2a2a;text-align:left}
.client-markdown-content :deep(th){color:#f2f2f2;background:#1a1a1a;font-weight:700}
.client-markdown-content :deep(img){max-width:100%;height:auto;border-radius:6px}.client-detail-state{display:grid;min-height:400px;place-items:center;align-content:center;gap:12px;color:#777;font-size:13px}.client-detail-state.error,.client-detail-error{color:#ff8299}.client-detail-error{margin:0;padding:9px 11px;border:1px solid #ff45602e;border-radius:8px;background:#ff45600d;font-size:12px}@media(max-width:900px){.client-detail-page{height:auto;min-height:calc(100vh - 48px);overflow:visible}.client-detail-body{grid-template-columns:1fr}.client-chapter-sidebar{max-height:280px}.client-chapter-main{min-height:500px;overflow:visible}}
</style>
