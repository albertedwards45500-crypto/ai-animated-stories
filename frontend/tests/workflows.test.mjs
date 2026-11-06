import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'

// Exercise the actual SFC setup logic with controlled APIs and timers. No server,
// database, network or paid generation calls are used by these workflow checks.
const require = createRequire(import.meta.url)
const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((a, b) => { resolve = a; reject = b })
  return { promise, resolve, reject }
}
const flush = () => new Promise((resolve) => setImmediate(resolve))

function mountView(name, api, store = {}) {
  const mounted = []
  const unmounted = []
  const timers = new Map()
  let timerId = 0
  const file = new URL(name === 'App' ? '../src/App.vue' : `../src/views/${name}.vue`, import.meta.url)
  const { descriptor } = parse(readFileSync(file, 'utf8'))
  const script = compileScript(descriptor, { id: name })
  const code = ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, {
    module,
    exports: module.exports,
    require(id) {
      if (id === '@vueuse/core') return { useDark: () => vue.ref(false), useToggle: () => () => {}, useMediaQuery: () => vue.ref(false) }
      if (id === 'vue') return { ...vue, onMounted: (fn) => mounted.push(fn), onUnmounted: (fn) => unmounted.push(fn) }
      if (id === 'vue-router') return {
        useRoute: () => ({ params: { id: '1' }, query: {} }),
        useRouter: () => ({ push() {} }),
      }
      if (id === '@/api/modules') return api
      if (id === '@/stores/task') return { useTaskStore: () => store }
      if (id === '@/composables/useTaskSSE') return { useTaskSSE() {} }
      if (id === 'element-plus') return { ElMessage: { warning() {}, success() {}, error() {}, info() {} }, ElMessageBox: { confirm: async () => {} } }
      if (id.endsWith('.vue')) return { default: {} }
      return require(id)
    },
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id },
    clearTimeout(id) { timers.delete(id) },
  }, { filename: file.pathname })
  const state = module.exports.default.setup({}, { expose() {} })
  return {
    state, timers,
    async mount() { for (const fn of mounted) await fn() },
    unmount() { for (const fn of unmounted) fn() },
    async tick() {
      const [id, fn] = timers.entries().next().value
      timers.delete(id)
      fn()
      await flush()
    },
  }
}

const job = (status) => ({ job_id: 'render-1', status, progress: status === 'succeeded' ? 100 : 30 })

test('preview follows queued → processing → succeeded, then stops polling', async () => {
  const statuses = ['queued', 'processing', 'succeeded']
  let requests = 0
  const view = mountView('PreviewView', { listEpisodeJobs: async () => [job(statuses[requests++])] })
  await view.mount()
  assert.equal(view.state.current.value.status, 'queued')
  assert.equal(view.timers.size, 1)
  await view.tick()
  assert.equal(view.state.current.value.status, 'processing')
  await view.tick()
  assert.equal(view.state.current.value.status, 'succeeded')
  assert.equal(view.timers.size, 0)
  assert.equal(requests, 3)
})

test('preview retry resumes polling after an initial network error', async () => {
  let fail = true
  const view = mountView('PreviewView', {
    listEpisodeJobs: async () => { if (fail) throw new Error('offline'); return [job('processing')] },
  })
  await view.mount()
  assert.equal(view.state.loadError.value, true)
  assert.equal(view.state.loading.value, false)
  fail = false
  await view.state.loadJobs()
  assert.equal(view.state.loadError.value, false)
  assert.equal(view.timers.size, 1)
  view.unmount()
  assert.equal(view.timers.size, 0)
})

test('preview prevents overlapping requests and does not restart after unmount', async () => {
  const request = deferred()
  let calls = 0
  const view = mountView('PreviewView', { listEpisodeJobs: () => { calls++; return request.promise } })
  const mounting = view.mount()
  await view.state.loadJobs()
  assert.equal(calls, 1)
  view.unmount()
  request.resolve([job('queued')])
  await mounting
  assert.equal(view.timers.size, 0)
})

test('empty project finishes loading even when task restoration fails', async () => {
  const view = mountView('ProjectDetailView', {
    getProject: async () => ({ id: 1, name: 'Empty project' }),
    listEpisodes: async () => [], listCharacters: async () => [],
  }, { restore: async () => { throw new Error('tasks unavailable') } })
  await view.mount()
  assert.equal(view.state.loading.value, false)
  assert.equal(view.state.loadError.value, false)
  assert.equal(view.state.episodes.value.length, 0)
})

test('project load failure exits loading and supports retry', async () => {
  let offline = true
  const view = mountView('ProjectDetailView', {
    getProject: async () => { if (offline) throw new Error('offline'); return { id: 1 } },
    listEpisodes: async () => [], listCharacters: async () => [],
  }, { restore: async () => [] })
  await view.mount()
  assert.equal(view.state.loading.value, false)
  assert.equal(view.state.loadError.value, true)
  offline = false
  await view.state.load()
  assert.equal(view.state.loadError.value, false)
})

test('late task response cannot overwrite a newly selected project', async () => {
  const first = deferred()
  const store = {
    tasks: new Map(),
    restore: (id) => id === 1 ? first.promise : Promise.resolve([{ task_id: 'second-project' }]),
  }
  const view = mountView('TasksView', { getCostStats: async (id) => [{ project_id: id }] }, store)
  view.state.selectedProjectId.value = 1
  const stale = view.state.refresh()
  view.state.selectedProjectId.value = 2
  await view.state.refresh()
  first.resolve([{ task_id: 'first-project' }])
  await stale
  assert.equal(view.state.selectedTaskIds.value.has('second-project'), true)
  assert.equal(view.state.selectedTaskIds.value.has('first-project'), false)
  assert.equal(view.state.stats.value[0].project_id, 2)
})

test('service check keeps dependency diagnostics and recovers on retry', async () => {
  let healthy = false
  const view = mountView('App', {
    getReadiness: async () => healthy
      ? { service: 'ai-drama', status: 'up', checks: { database: { status: 'up' } } }
      : { service: 'ai-drama', status: 'down', checks: { database: { status: 'down', message: '数据库未初始化' } } },
  })
  await view.mount()
  assert.equal(view.state.readiness.value.status, 'down')
  assert.equal(view.state.readinessDetails.value, '数据库未初始化')
  assert.equal(view.timers.size, 1)
  healthy = true
  await view.state.checkReadiness()
  assert.equal(view.state.readiness.value.status, 'up')
  assert.equal(view.timers.size, 1)
  view.unmount()
  assert.equal(view.timers.size, 0)
})

test('service checks prevent overlap and discard a late response after unmount', async () => {
  const request = deferred()
  let calls = 0
  const view = mountView('App', { getReadiness: () => { calls++; return request.promise } })
  const mounting = view.mount()
  await view.state.checkReadiness()
  assert.equal(calls, 1)
  view.unmount()
  request.resolve({ service: 'ai-drama', status: 'up', checks: {} })
  await mounting
  assert.equal(view.state.readiness.value, null)
  assert.equal(view.timers.size, 0)
})

test('service connection failure exits loading and schedules a retry', async () => {
  const view = mountView('App', { getReadiness: async () => { throw new Error('offline') } })
  await view.mount()
  assert.equal(view.state.readiness.value.status, 'down')
  assert.equal(view.state.checkingReadiness.value, false)
  assert.match(view.state.readinessDetails.value, /后端服务不可达/)
  assert.equal(view.timers.size, 1)
  view.unmount()
})

test('workbench summarizes keyframe, video and character readiness per shot', async () => {
  const shots = [
    { id: 1, shot_no: 1, duration: 4, character_ids: [7], keyframe_asset_id: null, video_asset_id: null },
    { id: 2, shot_no: 2, duration: 5, character_ids: [7], keyframe_asset_id: 12, video_asset_id: null },
    { id: 3, shot_no: 3, duration: 6, character_ids: [7], keyframe_asset_id: 13, video_asset_id: 14 },
  ]
  const view = mountView('EpisodeWorkbenchView', {
    getEpisode: async () => ({ id: 1, project_id: 9, episode_no: 2, title: '夜航', scenes: [] }),
    listEpisodeShots: async () => shots,
    listCharacters: async () => [{ id: 7, name: '林夏', version: 3, confirmed: 1, reference_assets: [] }],
    listLocations: async () => [],
    listStylePresets: async () => [],
  }, { tasks: new Map(), restore: async () => [] })
  await view.mount()
  assert.equal(view.state.readyShots.value, 1)
  assert.equal(view.state.totalDuration.value, 15)
  assert.equal(view.state.shotState(shots[0]).label, '待生成')
  assert.equal(view.state.shotState(shots[1]).label, '关键帧就绪')
  assert.equal(view.state.shotState(shots[2]).label, '视频就绪')
  assert.equal(view.state.shotCharacters(shots[2])[0].name, '林夏')
})
