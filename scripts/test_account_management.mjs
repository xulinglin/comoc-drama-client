import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { computed, ref, watch } = require('vue')
const { parse } = require('@vue/compiler-sfc')
const script = parse(readFileSync(new URL('../frontend/src/App.vue', import.meta.url), 'utf8')).descriptor.scriptSetup.content
  .replace(/^import .* from .*$/gm, '').replaceAll('import.meta.env.DEV', 'false')

function setup(api = {}) {
  const context = vm.createContext({
    URL, computed, ref, watch: (sources, callback) => watch(sources, callback, { flush: 'sync' }),
    onMounted: () => {}, onBeforeUnmount: () => {},
    window: { localStorage: { setItem: () => {} }, pywebview: { api } },
  })
  vm.runInContext(script + '\nglobalThis.form = { accounts, selectedAccountId, filteredAccounts, accountSearch, accountPlatformFilter, accountStatusFilter, accountStatusCounts, canReorderAccounts, startAccountDrag, dropAccount, draggingAccountId, clearAccountFilters, openSelectedAccount, completeSelectedAccountLogin, settings, updateDailyVideoQuota, accountMessage };', context)
  context.form.accounts.value = [
    { id: 'cn', name: '主账号', authenticated: true, hasLoggedIn: true },
    { id: 'global', name: '国际账号', accountType: 'dola', authenticated: true, hasLoggedIn: true },
    { id: 'new', name: '新账号', accountType: 'dola', authenticated: false },
    { id: 'expired', name: '过期账号', authenticated: true, loginExpired: true },
    { id: 'busy', name: '运行账号', authenticated: true, inUse: true, quotaExhaustedToday: true },
    { id: 'empty', name: '耗尽账号', authenticated: true, generatedToday: 3 },
  ]
  context.form.selectedAccountId.value = 'cn'
  return context.form
}

const ids = rows => Array.from(rows, row => row.id)
const dragEvent = id => ({ preventDefault() {}, dataTransfer: { setData() {}, getData: () => id } })

test('status counts cover every account and filters combine without changing call order', () => {
  const form = setup()
  assert.deepEqual({ ...form.accountStatusCounts.value }, { available: 2, pending: 2, running: 1, exhausted: 1 })
  form.accountSearch.value = ' DOLA '
  form.accountStatusFilter.value = 'available'
  assert.deepEqual(ids(form.filteredAccounts.value), ['global'])
  form.accountSearch.value = ''
  form.accountPlatformFilter.value = 'doubao'
  form.accountStatusFilter.value = 'pending'
  assert.deepEqual(ids(form.filteredAccounts.value), ['expired'])
  form.accountSearch.value = '不存在'
  assert.equal(form.filteredAccounts.value.length, 0)
  assert.deepEqual(ids(form.accounts.value), ['cn', 'global', 'new', 'expired', 'busy', 'empty'])
  form.clearAccountFilters()
  assert.equal(form.filteredAccounts.value.length, 6)
})

test('filtered drag and a filter change during drag never persist an unintended order', async () => {
  const orders = []
  const form = setup({ reorder_accounts: async order => { orders.push(order); return {} } })
  form.startAccountDrag(dragEvent('cn'), form.accounts.value[0])
  assert.equal(form.draggingAccountId.value, 'cn')
  form.accountPlatformFilter.value = 'dola'
  assert.equal(form.draggingAccountId.value, '')
  assert.equal(form.canReorderAccounts.value, false)
  await form.dropAccount(dragEvent('cn'), form.accounts.value[1])
  assert.equal(orders.length, 0)
  assert.deepEqual(ids(form.accounts.value), ['cn', 'global', 'new', 'expired', 'busy', 'empty'])
  form.clearAccountFilters()
  form.startAccountDrag(dragEvent('cn'), form.accounts.value[0])
  await form.dropAccount(dragEvent('cn'), form.accounts.value[1])
  assert.deepEqual(Array.from(orders[0]), ['global', 'cn', 'new', 'expired', 'busy', 'empty'])
})

test('failed reorder restores the original account order', async () => {
  const form = setup({ reorder_accounts: async () => { throw new Error('保存失败') } })
  await form.dropAccount(dragEvent('cn'), form.accounts.value[1])
  assert.deepEqual(ids(form.accounts.value), ['cn', 'global', 'new', 'expired', 'busy', 'empty'])
  assert.match(form.accountMessage.value, /保存失败/)
})

test('row login and Dola completion target the row without changing the selected account', async () => {
  const calls = []
  const form = setup({
    open_account_login: async id => { calls.push(['open', id]); return { status: 'manual' } },
    complete_account_login: async id => { calls.push(['complete', id]); return { loggedIn: true } },
  })
  await form.openSelectedAccount(form.accounts.value[1])
  await form.completeSelectedAccountLogin(form.accounts.value[1])
  assert.deepEqual(calls, [['open', 'global'], ['complete', 'global']])
  assert.equal(form.selectedAccountId.value, 'cn')
  assert.equal(form.accounts.value[1].authenticated, true)
  await form.openSelectedAccount(form.accounts.value[4])
  assert.equal(calls.length, 2)
})

test('failed quota save restores both platform limits', async () => {
  const form = setup({ save_settings: async () => { throw new Error('无法保存额度') } })
  await form.updateDailyVideoQuota(9, 'dola')
  assert.equal(form.settings.value.dolaDailyVideoQuota, 4)
  assert.equal(form.settings.value.dailyVideoQuota, 3)
  assert.match(form.accountMessage.value, /无法保存额度/)
})

test('a failed account refresh keeps a quota that was already saved', async () => {
  const form = setup({ save_settings: async value => ({ ...value }), list_accounts: async () => { throw new Error('无法刷新账号') } })
  await form.updateDailyVideoQuota(9, 'dola')
  assert.equal(form.settings.value.dolaDailyVideoQuota, 9)
  assert.match(form.accountMessage.value, /额度已保存，刷新失败/)
})
