import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { computed, ref, nextTick } = require('vue')
const { parse } = require('@vue/compiler-sfc')
const source = readFileSync(new URL('../frontend/src/components/VideoCreationWorkspace.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content.replace(/^import .* from .*$/gm, '')

function setup(api = {}) {
  const context = vm.createContext({
    computed, ref, nextTick, watch: () => {}, onMounted: () => {}, onBeforeUnmount: () => {},
    defineProps: () => ({ token: 'fixture', selectedAccountId: 'domestic-account', videoModel: 'Seedance 2.0 Fast' }),
    window: { pywebview: { api }, setTimeout: () => 1, clearTimeout: () => {} },
  })
  vm.runInContext(script + '\nglobalThis.workspace = { storyboards, doAccountOptions, generationEngineOptions, generationEngineLabel, selectGenerationEngine, setAllStoryboardEngines, generateShot, sendPreviewText, projectPayload, activeVideoProject, hydrateRunningTasks };', context)
  return context.workspace
}

test('Dola is selectable per shot and in bulk, and its label and platform survive saving', () => {
  const workspace = setup()
  assert.ok(workspace.generationEngineOptions.some(option => option.value === 'dola'))
  workspace.setAllStoryboardEngines('dola')
  const shot = workspace.storyboards.value[0]
  assert.equal(shot.generationEngine, 'dola')
  assert.equal(workspace.generationEngineLabel(shot), 'Dola')
  assert.match(workspace.sendPreviewText(shot), /Dola 桌面会话/)
  assert.equal(workspace.projectPayload().storyboards[0].generationEngine, 'dola')
  workspace.selectGenerationEngine(shot, 'doubao')
  assert.equal(workspace.generationEngineLabel(shot), 'OriginaDoubao')
})

test('Do defaults to automatic allocation and retains all three account choices', () => {
  const workspace = setup()
  const shot = workspace.storyboards.value[0]
  assert.equal(shot.generationEngine, 'do')
  assert.deepEqual(Array.from(workspace.doAccountOptions, option => option.label), ['自动', 'OriginaDoubao', 'Dola'])
  workspace.setAllStoryboardEngines('do')
  assert.equal(workspace.generationEngineLabel(shot), 'Do · 自动')
  assert.match(workspace.sendPreviewText(shot), /Do · 自动 桌面会话/)
  assert.equal(workspace.projectPayload().storyboards[0].generationEngine, 'do')
  assert.match(source, /<strong>Do<\/strong>/)
  assert.match(source, /:options="doAccountOptions"/)
})

test('web generation submits the selected platform even when the toolbar account belongs to another platform', async () => {
  const calls = []
  const workspace = setup({
    prepare_generation_asset: async () => ({ path: 'fixture.png' }),
    start_generation: async payload => { calls.push(payload); return { taskId: 'task', accountId: 'allocated-account' } },
    get_task: async () => ({ status: 'succeeded' }),
  })
  const shot = workspace.storyboards.value[0]
  shot.prompt = 'A landscape'
  shot.references = [{ id: 'image', cover: 'data:image/png;base64,fixture', type: 'image' }]
  for (const [engine, accountType] of [['do', 'auto'], ['dola', 'dola'], ['doubao', 'doubao']]) {
    workspace.selectGenerationEngine(shot, engine)
    await workspace.generateShot(shot)
    assert.equal(shot.generationError, '')
    assert.equal(calls.at(-1).accountType, accountType)
    assert.equal(calls.at(-1).generationEngine, engine)
    assert.equal(calls.at(-1).accountId, 'domestic-account')
    assert.equal(calls.at(-1).autoAssignAccount, true)
    assert.equal(shot.accountId, 'allocated-account')
  }
})

test('restoring running web tasks preserves automatic or fixed platform selection', async () => {
  for (const engine of ['do', 'dola', 'doubao']) {
    const workspace = setup({
      list_tasks: async () => [{ id: 'task', ownerType: 'videoShot', ownerId: workspace.storyboards.value[0].id, generationEngine: engine, status: 'queued' }],
      get_task: async () => ({ status: 'queued' }),
    })
    workspace.selectGenerationEngine(workspace.storyboards.value[0], 'seedance')
    await workspace.hydrateRunningTasks({ id: 'project' })
    assert.equal(workspace.storyboards.value[0].generationEngine, engine)
  }
})
