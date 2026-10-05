import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { computed, ref } = require('vue')
const { parse } = require('@vue/compiler-sfc')
const script = parse(readFileSync(new URL('../frontend/src/App.vue', import.meta.url), 'utf8')).descriptor.scriptSetup.content
  .replace(/^import .* from .*$/gm, '').replaceAll('import.meta.env.DEV', 'false')

function setup() {
  const context = vm.createContext({
    URL, computed, ref, watch: () => {}, onMounted: () => {}, onBeforeUnmount: () => {},
    window: { pywebview: { api: {} } },
  })
  vm.runInContext(script + '\nglobalThis.form = { accounts, selectedAccountId, conversionLink, conversionPlatform, canConvertLink, conversionAccountMismatch };', context)
  const form = context.form
  form.accounts.value = [{ id: 'dola', accountType: 'dola' }, { id: 'doubao', accountType: 'doubao' }]
  form.selectedAccountId.value = 'dola'
  return form
}

test('Dola CDN links enable conversion with the Dola account', () => {
  const form = setup()
  form.conversionLink.value = 'https://v16-dola.dola.com/hash/video/tos/mya/file/?lr=cici_ai&download=true'
  assert.equal(form.conversionPlatform.value, 'dola')
  assert.equal(form.canConvertLink.value, true)
  form.selectedAccountId.value = 'doubao'
  assert.equal(form.conversionAccountMismatch.value, true)
  assert.equal(form.canConvertLink.value, false)
})

test('domestic links require a domestic account and reject expired or busy accounts', () => {
  const form = setup()
  form.conversionLink.value = 'https://www.doubao.com/video-sharing?video_id=fixture'
  assert.equal(form.canConvertLink.value, false)
  form.selectedAccountId.value = 'doubao'
  assert.equal(form.canConvertLink.value, true)
  form.accounts.value[1].loginExpired = true
  assert.equal(form.canConvertLink.value, false)
  form.accounts.value[1].loginExpired = false
  form.accounts.value[1].inUse = true
  assert.equal(form.canConvertLink.value, false)
})

test('Dola chat links are classified without accepting spoofed domains', () => {
  const form = setup()
  form.conversionLink.value = 'https://www.dola.com/chat/123'
  assert.equal(form.canConvertLink.value, true)
  form.conversionLink.value = 'https://v16-dola.dola.com.evil.test/video/tos/file'
  assert.equal(form.conversionPlatform.value, '')
})
