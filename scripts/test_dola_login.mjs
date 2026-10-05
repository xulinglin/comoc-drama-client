import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { computed, ref } = require('vue')
const { parse } = require('@vue/compiler-sfc')
const descriptor = parse(readFileSync(new URL('../frontend/src/App.vue', import.meta.url), 'utf8')).descriptor
const script = descriptor.scriptSetup.content.replace(/^import .* from .*$/gm, '').replaceAll('import.meta.env.DEV', 'false')

function setup(api) {
  const context = vm.createContext({
    computed, ref, watch: () => {}, onMounted: () => {}, onBeforeUnmount: () => {},
    window: { pywebview: { api } },
  })
  vm.runInContext(script + '\nglobalThis.form = { accounts, selectedAccountId, accountMessage, openingAccountId, completingAccountId, openSelectedAccount, completeSelectedAccountLogin, accountVerifyState, checkableAccounts, loadAccounts };', context)
  context.form.accounts.value = [{ id: 'global', name: '国际', accountType: 'dola', hasLoggedIn: false }]
  context.form.selectedAccountId.value = 'global'
  return context.form
}

test('opening Dola enables completion immediately and ignores duplicate clicks', async () => {
  let resolve, calls = 0
  const form = setup({ open_account_login: () => {
    calls++
    return new Promise(done => { resolve = done })
  } })
  const pending = form.openSelectedAccount()
  await form.openSelectedAccount()
  assert.equal(calls, 1)
  resolve({ status: 'manual', message: '点击完成登录' })
  await pending
  assert.equal(form.accounts.value[0].manualLoginPending, true)
  assert.equal(form.openingAccountId.value, '')
  assert.equal(form.checkableAccounts.value.length, 0)
})

test('completion reports actual result for the originating account despite selection changes', async () => {
  let resolve, calls = 0
  const form = setup({ complete_account_login: id => {
    assert.equal(id, 'global')
    calls++
    return new Promise(done => { resolve = done })
  } })
  form.accounts.value[0].manualLoginPending = true
  form.accounts.value.push({ id: 'cn', name: '国内', accountType: 'doubao' })
  const pending = form.completeSelectedAccountLogin()
  await form.completeSelectedAccountLogin()
  assert.equal(calls, 1)
  form.selectedAccountId.value = 'cn'
  resolve({ loggedIn: true, method: 'browser', message: 'Dola 登录成功' })
  await pending
  assert.equal(form.accounts.value[0].hasLoggedIn, true)
  assert.equal(form.accounts.value[0].manualLoginPending, false)
  assert.equal(form.accounts.value[1].hasLoggedIn, undefined)
  assert.equal(form.accountVerifyState.value.global.status, 'ok')
  assert.equal(form.completingAccountId.value, '')
})

test('failed login and close errors never imply success', async () => {
  const failed = setup({ complete_account_login: async () => ({ loggedIn: false, message: '未检测到有效登录' }) })
  failed.accounts.value[0].manualLoginPending = true
  await failed.completeSelectedAccountLogin()
  assert.equal(failed.accounts.value[0].hasLoggedIn, false)
  assert.equal(failed.accountVerifyState.value.global.status, 'failed')
  const blocked = setup({ complete_account_login: async () => { throw new Error('请手动关闭窗口') } })
  blocked.accounts.value[0].manualLoginPending = true
  await blocked.completeSelectedAccountLogin()
  assert.equal(blocked.accounts.value[0].manualLoginPending, true)
  assert.match(blocked.accountMessage.value, /手动关闭/)
})

test('polling keeps pending relogin selected even when its previous session expired', async () => {
  const rows = [{ id: 'global', accountType: 'dola', manualLoginPending: true, loginExpired: true }, { id: 'other', accountType: 'dola' }]
  const form = setup({ list_accounts: async () => rows })
  await form.loadAccounts()
  assert.equal(form.selectedAccountId.value, 'global')
})

test('domestic login does not expose manual completion', async () => {
  const form = setup({ open_account_login: async () => ({ status: 'opening', message: '正在打开登录窗口' }) })
  form.accounts.value[0].accountType = 'doubao'
  await form.openSelectedAccount()
  assert.equal(form.accounts.value[0].manualLoginPending, undefined)
  assert.match(descriptor.template.content, /v-if="account.accountType === 'dola' && account.manualLoginPending"/)
})
