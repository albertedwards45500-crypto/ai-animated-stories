# AI 漫剧生产系统

基于 Vue 3、TypeScript 和 FastAPI 的 AI 漫剧项目，支持项目与剧集管理、剧本拆分、角色与素材管理、图片/视频/语音生成、任务进度查看、字幕与成片合成。

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Element Plus、Pinia。
- 后端：FastAPI、SQLAlchemy、Alembic、Dramatiq。
- 数据与任务：MySQL、Redis；本地 Mock 模式使用 SQLite 和线程任务队列。
- 音视频处理：FFmpeg；AI 接口支持 Mock 与真实供应商配置。

## 本地快速启动（Windows）

1. 安装 Python 3.11+、Node.js 20+ 和 FFmpeg。
2. 将 FFmpeg 加入系统 PATH，或将 `ffmpeg.exe`、`ffprobe.exe` 放入项目的 `tools/` 目录。这些程序不随源码提交。
3. 在项目根目录执行 `Copy-Item .env.example .env`，根据需要填写本地配置。
4. 双击 `start-mock.bat` 运行本地 Mock 模式。首次启动会安装前后端依赖。
5. 打开 <http://localhost:5188/projects>；接口文档为 <http://127.0.0.1:8000/docs>。
6. 双击 `stop.bat` 停止服务。

Mock 模式不需要 MySQL、Redis 或真实 AI 密钥，运行数据保存在 `.runtime/mock/`。

## 使用真实服务

按 [本地开发环境.md](本地开发环境.md) 配置 MySQL、Redis 和数据库迁移，然后运行 `start.bat`。真实 AI 调用需要在本地 `.env` 中配置相应密钥、供应商及运行模式；调用可能产生供应商费用。

## 目录

| 路径 | 内容 |
| --- | --- |
| `frontend/` | 前端页面与测试 |
| `backend/` | API、数据模型、AI 供应商、任务与测试 |
| `docs/` | 开发决策、实现计划与验证记录 |
| `.env.example` | 本地配置模板 |
| `launcher.ps1` | Windows 启动与依赖检查 |

## 验证

```powershell
# 后端（在 backend 目录，使用已安装依赖的 Python）
python -m pytest

# 前端（在 frontend 目录）
npm test
npm run build
```

数据库密码与 API 密钥只保存在本地配置中。运行环境、数据库、日志、生成媒体和个人输出文件不随源码上传。
