/**
 * 全局单例 useTaskSSE：按 task_id 订阅任务进度事件。
 *
 * 事件类型 progress / status / error；断线自动降级为
 * taskStore 的 5s 轮询（UI 规范 5.3）。
 */
import { taskEventsUrl } from '@/api/modules'
import { useTaskStore } from '@/stores/task'

/** 活跃的 EventSource 集合。 */
const sources = new Map<string, EventSource>()

/**
 * 订阅任务进度（全局单例复用连接）。
 *
 * @param taskId - 任务 UUID。
 */
export function useTaskSSE(taskId: string) {
  const store = useTaskStore()
  if (sources.has(taskId)) return

  const es = new EventSource(taskEventsUrl(taskId))
  sources.set(taskId, es)

  es.addEventListener('progress', (e) => {
    const data = JSON.parse((e as MessageEvent).data) as { status: string; progress: number }
    store.update(taskId, { status: data.status, progress: data.progress })
  })
  es.addEventListener('status', (e) => {
    const data = JSON.parse((e as MessageEvent).data) as { status: string; output_asset_ids: number[] }
    store.update(taskId, { status: data.status, progress: 100, output_asset_ids: data.output_asset_ids })
    es.close()
    sources.delete(taskId)
  })
  es.addEventListener('error', (e) => {
    if (e instanceof MessageEvent) {
      const data = JSON.parse(e.data) as { status: string; error_message: string }
      store.update(taskId, { status: data.status, error_message: data.error_message })
      es.close()
      sources.delete(taskId)
    }
    // EventSource 连接错误：关闭并依赖 5s 轮询降级
    es.close()
    sources.delete(taskId)
  })

  // 生成操作发生在点击事件内；连接由全局任务持有，终态或断线时关闭。
}
