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
  const accounts = [{ id: 'cn', name: '国内', generatedToday: 1 }, { id: 'global', name: '国际', accountType: 'dola', generatedToday: 1 }]
  const saves = []
  const cached = []
  const context = vm.createContext({
    URL, computed, ref, watch: () => {}, onMounted: () => {}, onBeforeUnmount: () => {},
    window: { localStorage: { setItem: (...args) => cached.push(args) }, pywebview: { api: {
      list_accounts: async () => accounts,
      save_settings: async settings => { saves.push({ ...settings }); return { ...settings } },
    } } },
  })
  vm.runInContext(script + '\nglobalThis.form = { accounts, selectedAccountId, settings, dailyVideoQuota, accountQuotaRemaining, accountOptions, updateDailyVideoQuota };', context)
  const form = context.form
  form.accounts.value = accounts
  form.selectedAccountId.value = 'cn'
  return { form, saves, cached }
}

test('Dola defaults to four and domestic remains three regardless of toolbar selection', () => {
  const { form } = setup()
  const [domestic, dola] = form.accounts.value
  assert.equal(form.dailyVideoQuota(domestic), 3)
  assert.equal(form.dailyVideoQuota(dola), 4)
  assert.equal(form.accountQuotaRemaining(domestic), 2)
  assert.equal(form.accountQuotaRemaining(dola), 3)
  assert.match(form.accountOptions.value[0].label, /2\/3/)
  assert.match(form.accountOptions.value[1].label, /3\/4/)
  form.selectedAccountId.value = 'global'
  assert.equal(form.dailyVideoQuota(), 3)
  assert.equal(form.dailyVideoQuota(dola), 4)
  assert.equal(form.dailyVideoQuota(domestic), 3)
})

test('domestic quota updates preserve Dola quota regardless of the selected account', async () => {
  const { form, saves, cached } = setup()
  form.selectedAccountId.value = 'global'
  await form.updateDailyVideoQuota(3)
  assert.equal(saves[0].dolaDailyVideoQuota, 4)
  assert.equal(saves[0].dailyVideoQuota, 3)
  assert.deepEqual(cached, [['cdtv.dailyVideoQuota', '3']])
  form.selectedAccountId.value = 'cn'
  await form.updateDailyVideoQuota(5)
  assert.equal(saves[1].dolaDailyVideoQuota, 4)
  assert.equal(saves[1].dailyVideoQuota, 5)
  assert.deepEqual(cached, [['cdtv.dailyVideoQuota', '3'], ['cdtv.dailyVideoQuota', '5']])
})

test('Dola quota saves independently without overwriting the domestic cache', async () => {
  const { form, saves, cached } = setup()
  await form.updateDailyVideoQuota(7, 'dola')
  assert.equal(saves[0].dolaDailyVideoQuota, 7)
  assert.equal(saves[0].dailyVideoQuota, 3)
  assert.equal(form.dailyVideoQuota(form.accounts.value[1]), 7)
  assert.deepEqual(cached, [])
})

test('Dola exhaustion shows zero while the fourth generation remains available after three uses', () => {
  const { form } = setup()
  const dola = form.accounts.value[1]
  dola.generatedToday = 3
  dola.quotaRemainingToday = 1
  assert.equal(form.accountQuotaRemaining(dola), 1)
  dola.generatedToday = 4
  dola.quotaExhaustedToday = true
  assert.equal(form.accountQuotaRemaining(dola), 0)
})
