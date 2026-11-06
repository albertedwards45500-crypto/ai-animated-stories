/**
 * Axios 客户端：统一响应解包与错误拦截。
 *
 * 后端统一返回 {code, message, data}；拦截器解包 data，
 * 非 0 code 抛出 ElMessage 错误并 reject。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

/** 全局 Axios 实例（经 Vite 代理访问后端）。 */
export const http = axios.create({
  baseURL: '/',
  timeout: 120000,
})

export function isApiUnavailable(error: unknown): boolean {
  const axiosError = error as { code?: string; response?: { status?: number } }
  return axiosError.code === 'ERR_NETWORK' || axiosError.response?.status === 502 || axiosError.response?.status === 503
}

http.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        // 40901/40002 展示后端 message（UI 规范 5.2）
        ElMessage.error(body.message || `请求失败(${body.code})`)
        return Promise.reject(body)
      }
      return body.data as never
    }
    return resp.data
  },
  (error) => {
    const body = error.response?.data as ApiResponse | undefined
    const proxyUnavailable = error.response?.status === 500 && (!body || typeof body !== 'object' || !('code' in body))
    const msg = body?.message || (isApiUnavailable(error) || proxyUnavailable
      ? '后端服务暂不可用，请查看顶部服务状态并重试'
      : error.message || '网络错误')
    ElMessage.error(msg)
    return Promise.reject(error)
  },
)

/**
 * 解包 TestClient 式响应（Promise 返回值即 data）。
 *
 * @param p - 请求 Promise。
 * @returns 解包后的 data。
 */
export async function unwrap<T>(p: Promise<T>): Promise<T> {
  return p
}
