/**
 * 全局任务 Store：任务状态唯一来源（UI 规范 5.3）。
 *
 * 组件不直接连 SSE，统一从本 Store 读状态；
 * SSE 断线自动降级为 5s 轮询。
 */
import { defineStore } from 'pinia'
import { cancelTask, getTask, listProjectTasks, retryTask, type GenTask } from '@/api/modules'

/** 全局任务状态存储。 */
export const useTaskStore = defineStore('task', {
  state: () => ({
    /** 进行中任务映射（task_id → 任务）。 */
    tasks: new Map<string, GenTask>(),
    /** 任务抽屉可见性。 */
    drawerVisible: false,
    /** 当前轮询定时器。 */
    pollTimer: null as ReturnType<typeof setInterval> | null,
    polling: false,
  }),
  getters: {
    /** 进行中任务数量（顶栏角标）。 */
    runningCount: (state): number =>
      [...state.tasks.values()].filter((t) => t.status === 'queued' || t.status === 'processing').length,
    /** 进行中任务列表。 */
    runningTasks(): GenTask[] {
      return [...this.tasks.values()].filter((t) => t.status === 'queued' || t.status === 'processing')
    },
  },
  actions: {
    /**
     * 登记新任务（发起生成后调用）。
     *
     * @param task - 任务受理数据。
     */
    track(task: { task_id: string; status: string }) {
      this.tasks.set(task.task_id, {
        task_id: task.task_id,
        type: 'unknown',
        provider: null,
        mode: null,
        status: task.status,
        progress: 0,
        error_message: null,
        retry_count: 0,
        cost: 0,
        shot_id: null,
        episode_id: null,
        project_id: null,
        output_asset_ids: [],
      })
      this.ensurePolling()
    },

    /**
     * 更新任务进度。
     *
     * @param taskId - 任务 UUID。
     * @param patch - 部分字段。
     */
    update(taskId: string, patch: Partial<GenTask>) {
      const existing = this.tasks.get(taskId)
      if (existing) {
        Object.assign(existing, patch)
      } else {
        this.tasks.set(taskId, {
          task_id: taskId,
          type: 'unknown',
          provider: null,
          mode: null,
          status: 'queued',
          progress: 0,
          error_message: null,
          retry_count: 0,
          cost: 0,
          shot_id: null,
          episode_id: null,
          project_id: null,
          output_asset_ids: [],
          ...patch,
        })
      }
      this.ensurePolling()
    },

    /**
     * 从后端恢复任务列表（页面刷新后不丢状态）。
     *
     * @param projectId - 项目 ID。
     */
    async restore(projectId: number): Promise<GenTask[]> {
      const resp = await listProjectTasks(projectId, { page: 1, page_size: 50 })
      for (const t of resp.items) {
        this.tasks.set(t.task_id, t)
      }
      this.ensurePolling()
      return resp.items
    },

    /**
     * 轮询降级：每 5 秒刷新全部进行中任务（SSE 断线时的兜底，也保证可靠性）。
     */
    ensurePolling() {
      if (this.pollTimer) return
      this.pollTimer = setInterval(async () => {
        if (this.polling) return
        const running = this.runningTasks
        if (running.length === 0) {
          if (this.pollTimer) {
            clearInterval(this.pollTimer)
            this.pollTimer = null
          }
          return
        }
        // 并发刷新进行中任务（后端真实状态兜底）
        this.polling = true
        try {
          await Promise.all(
          running.map(async (t) => {
            try {
              const fresh = await getTask(t.task_id)
              this.tasks.set(t.task_id, fresh)
            } catch {
              /* 网络异常忽略，下轮再试 */
            }
          }),
          )
        } finally {
          this.polling = false
        }
      }, 5000)
    },

    /**
     * 取消任务。
     *
     * @param taskId - 任务 UUID。
     */
    async cancel(taskId: string) {
      const t = await cancelTask(taskId)
      this.tasks.set(taskId, t)
    },

    /**
     * 重试任务。
     *
     * @param taskId - 任务 UUID。
     */
    async retry(taskId: string) {
      const t = await retryTask(taskId)
      this.tasks.set(taskId, t)
      this.ensurePolling()
    },
  },
})
