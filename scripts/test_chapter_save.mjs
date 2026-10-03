import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { computed, ref, watch, nextTick } = require('vue')
const { parse } = require('@vue/compiler-sfc')
const source = readFileSync(new URL('../frontend/src/components/ProjectDetail.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
  .replace(/^import .* from .*$/gm, '')
  .replaceAll('import.meta.env.DEV', 'false')

test('switching chapters and leaving the editor flush pending drafts without mixing content', async () => {
  const requests = []
  const pending = new Map()
  const disposers = []
  const watchers = []
  let timer = 0
  const context = vm.createContext({
    computed, ref,
    marked: { setOptions: () => {} },
    watch: (...args) => { const stop = watch(...args); watchers.push(stop); return stop },
    onMounted: () => {}, onBeforeUnmount: fn => disposers.push(fn),
    defineProps: () => ({ projectId: 'project', token: 'fixture' }), defineEmits: () => () => {},
    window: {
      setTimeout: fn => { pending.set(++timer, fn); return timer },
      clearTimeout: id => pending.delete(id),
      pywebview: { api: { backend_request: (method, path, token, body) => new Promise(resolve => {
        requests.push({ method, path, body, resolve })
      }) } },
    },
  })
  vm.runInContext(script + '\nglobalThis.editor = { chapters, content, loading, selectChapter };', context)
  const editor = context.editor
  editor.loading.value = false
  editor.chapters.value = [{ id: 'one', title: '一', content: '原文一' }, { id: 'two', title: '二', content: '原文二' }]
  editor.selectChapter(editor.chapters.value[0])
  await nextTick()
  editor.content.value = '第一章未保存的修改'
  await nextTick()
  editor.selectChapter(editor.chapters.value[1])
  assert.equal(requests[0].path, '/chapter/one')
  assert.equal(requests[0].body.content, '第一章未保存的修改')
  editor.selectChapter(editor.chapters.value[0])
  assert.equal(editor.content.value, '第一章未保存的修改')
  editor.selectChapter(editor.chapters.value[1])
  requests[0].resolve({ id: 'one', revision: 2 })
  await new Promise(setImmediate)
  await nextTick()
  assert.equal(editor.chapters.value[0].content, '第一章未保存的修改')
  assert.equal(editor.content.value, '原文二')
  editor.content.value = '第二章未保存的修改'
  await nextTick()
  disposers.forEach(dispose => dispose())
  assert.equal(requests[1].path, '/chapter/two')
  assert.equal(requests[1].body.content, '第二章未保存的修改')
  requests[1].resolve({ id: 'two', revision: 2 })
  await new Promise(setImmediate)
  watchers.forEach(stop => stop())
})
