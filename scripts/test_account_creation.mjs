import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { computed, ref } = require('vue')
const { parse } = require('@vue/compiler-sfc')
const source = readFileSync(new URL('../frontend/src/App.vue', import.meta.url), 'utf8')
const descriptor = parse(source).descriptor
const script = descriptor.scriptSetup.content
  .replace(/^import .* from .*$/gm, '')
  .replaceAll('import.meta.env.DEV', 'false')

function setup(api) {
  const context = vm.createContext({
    computed, ref, watch: () => {}, onMounted: () => {}, onBeforeUnmount: () => {},
    window: { pywebview: { api } },
  })
  vm.runInContext(script + '\nglobalThis.form = { createAccount, newAccountName, newAccountType, accountMessage, accounts, selectedAccountId };', context)
  return context.form
}

test('blank account name shows an error in the account panel without calling the bridge', async () => {
  let calls = 0
  const form = setup({ create_account: async () => { calls++ } })
  form.newAccountType.value = 'dola'
  form.newAccountName.value = '   '
  await form.createAccount()
  assert.match(form.accountMessage.value, /请输入账号名称/)
  assert.equal(calls, 0)
})

test('legacy backend tells Dola users to restart and never creates a domestic account', async () => {
  let calls = 0
  const form = setup({ create_account: async () => { calls++; return { id: 'wrong', name: 'Dola' } } })
  form.newAccountType.value = 'dola'
  form.newAccountName.value = '国际主账号'
  await form.createAccount()
  assert.match(form.accountMessage.value, /重新启动/)
  assert.equal(calls, 0)
})

test('failed creation shows the backend error in the account panel and retains the name', async () => {
  const form = setup({ create_account: async () => { throw new Error('磁盘写入失败') } })
  form.newAccountName.value = '主账号'
  await form.createAccount()
  assert.match(form.accountMessage.value, /磁盘写入失败/)
  assert.equal(form.newAccountName.value, '主账号')
})

test('successful Dola creation appears immediately without waiting for list polling', async () => {
  const calls = []
  const form = setup({
    create_generation_account: async (...args) => {
      calls.push(args)
      return { id: 'dola-1', name: '国际主账号', accountType: 'dola', hasLoggedIn: false }
    },
    list_accounts: () => { throw new Error('list refresh unavailable') },
  })
  form.newAccountType.value = 'dola'
  form.newAccountName.value = ' 国际主账号 '
  await form.createAccount()
  assert.deepEqual(calls, [['国际主账号', 'dola']])
  assert.equal(form.accounts.value[0].accountType, 'dola')
  assert.equal(form.selectedAccountId.value, 'dola-1')
  assert.equal(form.newAccountName.value, '')
  assert.match(form.accountMessage.value, /已创建 Dola/)
})

test('repeated clicks during creation submit only once and show progress', async () => {
  let calls = 0
  let resolve
  const form = setup({ create_generation_account: () => {
    calls++
    return new Promise(done => { resolve = done })
  } })
  form.newAccountName.value = '主账号'
  const pending = form.createAccount()
  assert.match(form.accountMessage.value, /正在添加/)
  await form.createAccount()
  assert.equal(calls, 1)
  resolve({ id: 'one', name: '主账号', accountType: 'doubao' })
  await pending
  assert.equal(form.accounts.value.length, 1)
})

test('legacy domestic account creation keeps the original one-argument bridge call', async () => {
  const calls = []
  const form = setup({ create_account: async (...args) => {
    calls.push(args)
    return { id: 'one', name: '主账号' }
  } })
  form.newAccountName.value = '主账号'
  await form.createAccount()
  assert.deepEqual(calls, [['主账号']])
  assert.equal(form.accounts.value[0].accountType, 'doubao')
})

test('account panel renders feedback and disables the add button while creating', () => {
  assert.match(descriptor.template.content, /role="status"[^>]*>\s*\{\{ accountMessage \}\}/)
  assert.match(descriptor.template.content, /<button[^>]*:disabled="creatingAccount"[^>]*@click="createAccount"/)
})
