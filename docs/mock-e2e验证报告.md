# 本地 Mock 闭环验证

- 日期：2026-10-27
- 用途：在不连接 MySQL、Redis、真实 AI Provider 的情况下验证全流程
- 隔离数据：项目根目录下的 `.runtime/mock/app.db` 与 `.runtime/mock/media/`
- 前端：http://localhost:5188/projects
- 后端：http://127.0.0.1:8000

## 启动和验收

运行根目录的 `start-mock.bat` 会启动独立 Mock 模式。就绪检查覆盖数据库连接与表结构、本地任务队列、FFmpeg；首页服务状态可检查依赖并显示具体故障。

启动器使用项目根目录的 `.venv` 虚拟环境。完成启动后，可在 backend 目录执行：

```powershell
..\.venv\Scripts\python.exe -m app.tools.e2e_verify
..\.venv\Scripts\python.exe -m pytest -q
```

端到端脚本首先确认 `profile=mock` 和 thread 队列，然后保留一个验收项目，运行剧本、三镜头图片/视频/语音、字幕、FFmpeg 成片、SSE、失败/超时/重试/取消和费用统计；最后读取预览/下载并校验 MP4 响应。开发人员再次运行启动器时，后端源码变更会自动重启 API。

测试每次重新创建临时 SQLite 数据和生成有效音视频文件；测试媒体不会进入项目 Mock 目录。

## 回归范围

- API readiness 的数据库、队列、FFmpeg 诊断及敏感信息隐藏
- 结构化 Mock 剧本生成角色、场景、分镜及可合成对白
- 参数缓存命中后不重复创建音频轨，取消中的任务不会被旧 worker 覆盖
- SQLite 耗时与成本聚合回归；MySQL 保留对应方言实现，尚未进行在线验证
- 字幕可选择或自动使用当前剧集已生成的对白/旁白轨
- 烧录字幕、MP4 软字幕、视频/音频轨、Range 预览与下载
- 任务重试和本地服务重启后的状态恢复

## 本次结果

- `backend/.venv/Scripts/python.exe -m pytest -q`：31 passed
- `frontend/npm test`：9 passed
- `frontend/npm run build`：成功；最大 JavaScript chunk 约 397 KB
- HTTP Mock E2E：全项通过，下载 MP4 为 4,213,198 bytes；验收项目 ID 2、剧集 ID 2
- MP4 已通过 FFprobe 流信息检查、完整解码和 HTTP Range 预览检查；pytest 另外覆盖烧录字幕和软字幕两种输出
- 仅有第三方 Starlette 测试客户端弃用提示，无失败
