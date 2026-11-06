# 实施计划：AI 漫剧生产系统

- 文档版本：v1.0
- 创建日期：2026-10-13
- 上游文档：PRD.md（v1.0）、AI漫剧初版开发文档.md（v0.1）、数据库设计.md、API接口文档.md、前端UI设计文档.md、本地开发环境.md
- 冲突决策：见 [docs/DECISIONS.md](./DECISIONS.md)

## 1. 现状审计（阶段 0 结论）

### 1.1 工作区文件清单

| 文件/目录 | 类型 | 说明 |
|-----------|------|------|
| PRD.md | 需求文档 | v1.0，业务范围与验收标准 |
| AI漫剧初版开发文档.md | 设计文档 | v0.1，技术基线 |
| 数据库设计.md | 设计文档 | 16 张核心表结构 |
| API接口文档.md | 设计文档 | 统一响应格式 + 全部接口契约 |
| 前端UI设计文档.md | 设计文档 | 页面地图与交互规范 |
| 本地开发环境.md | 运维文档 | 环境搭建与启动方式 |
| .workbuddy/ | 工具目录 | 工作台配置，与项目无关 |

### 1.2 审计结论

- **无已有代码**：工作区不存在 backend/、frontend/、任何源码或构建配置。
- **无版本控制仓库**：不存在 `.git` 目录，阶段 1 需初始化。
- **无基础设施**：MySQL、Redis 尚未确认运行状态，阶段 1 通过 `docker-compose.dev.yml` 启动。
- **文档冲突**：共识别 6 项，全部已在 DECISIONS.md 中给出决策，无阻断性冲突。
- **结论**：项目处于「纯文档、零代码」起点，按本计划从阶段 1 开始实施。

## 2. 技术栈（锁定，不得擅换）

| 层 | 技术 | 版本约束 |
|----|------|---------|
| 后端框架 | FastAPI + Pydantic v2 | Python 3.11+ |
| ORM / 迁移 | SQLAlchemy 2.x + Alembic | — |
| 数据库 | MySQL 8.x | utf8mb4 / utf8mb4_0900_ai_ci |
| 队列 | Redis + Dramatiq | Redis 7.x |
| 前端 | Vue 3 + TypeScript + Vite | Vue Router + Pinia |
| UI 组件 | Element Plus（默认主题 + CSS Variables 定制） | — |
| 前端辅助 | Axios、VueUse、@vue-flow/core | — |
| 媒体处理 | FFmpeg 6.x+ | 阶段 2 合成 |
| 测试 | pytest（后端）、前端构建检查 | — |

## 3. 目录结构（完整规划）

```text
D:\ai漫剧\
├── PRD.md / AI漫剧初版开发文档.md / 数据库设计.md / API接口文档.md / 前端UI设计文档.md / 本地开发环境.md
├── docs/
│   ├── IMPLEMENTATION_PLAN.md          # 本文档
│   └── DECISIONS.md                    # 冲突与决策记录
├── docker-compose.dev.yml              # MySQL + Redis（阶段 1）
├── .gitignore                          # .env / media/ / node_modules/ / .venv/ 等
├── .env.example                        # 环境变量模板（不含真实密码）
├── .env                                # 本地实际配置（不入 Git）
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI 入口、统一异常处理、路由注册
│   │   ├── core/                       # 配置(Settings)、统一响应封装、错误码、安全
│   │   ├── api/                        # 路由层：projects、episodes、scenes、shots、characters、locations、style_presets、generation、tasks、assets、render、provider_configs
│   │   ├── models/                     # SQLAlchemy 2.x 模型（16 张表）
│   │   ├── schemas/                    # Pydantic v2 请求/响应模型
│   │   ├── services/                   # 业务服务层（校验、状态机、缓存、提示词拼装）
│   │   ├── providers/                  # Provider 适配层：base、mock/、record/replay、缓存
│   │   └── tasks/                      # Dramatiq actor 定义与任务执行
│   ├── alembic/                        # 迁移环境 + versions/
│   ├── tests/                          # pytest：契约测试、状态机测试、Mock 闭环 e2e
│   ├── requirements.txt
│   └── .venv/
├── frontend/
│   ├── src/
│   │   ├── api/                        # Axios 封装 + 按模块的 API 函数
│   │   ├── stores/                     # Pinia：projectStore、taskStore（SSE 状态源）等
│   │   ├── composables/                # useTaskSSE() 全局单例、usePollingFallback
│   │   ├── components/                 # TaskStatusTag、ShotCard、TaskDrawer、MediaPreview 等
│   │   ├── views/                      # /projects、/projects/:id、/episodes/:id、/episodes/:id/preview、/assets、/settings、/tasks
│   │   ├── router/
│   │   └── main.ts
│   ├── vite.config.ts                  # /api 代理到 127.0.0.1:8000
│   └── package.json
└── media/
    ├── mock/                           # images/ audio/ video/ subtitles/（阶段 2 就位）
    └── generated/                      # 生成产物输出
```

## 4. 分阶段计划

### 阶段 0：项目审计和初始化（本阶段）

- **目标**：确认起点、澄清文档冲突、锁定实施路线。
- **交付物**：本计划文档、DECISIONS.md。
- **验收**：两份文档章节完整；决策不改变任何 API 路径或数据库契约；未实现业务代码。
- **状态**：✅ 已完成。

### 阶段 1：基础工程

- **目标**：可运行的前后端骨架 + 数据层 + 项目/剧集/场景/分镜 CRUD。
- **交付物**：
  1. Git 仓库初始化，`.gitignore`、`.env.example`、`docker-compose.dev.yml`
  2. FastAPI 骨架：统一响应 `{code, message, data}`、错误码（40001/40002/40401/40901/42901/50001/50201/50401）、全局异常处理器、参数校验
  3. SQLAlchemy 模型（16 张表）+ Alembic 初始迁移
  4. CRUD：项目、剧集、场景（episodes 下 scenes）、分镜，含删除项目时进行中任务检查（40901）
  5. Vue 3 骨架：路由、Axios 拦截器、项目列表页（4.1）、项目详情页（4.2）、全局布局
  6. 后端 pytest 基础测试（CRUD + 错误码契约）、前端 `npm run build` 通过
- **验收**：`alembic upgrade head` 成功建表；`/docs` 可访问；项目和剧集 CRUD 走通；前端可访问并调用后端接口。
- **依赖**：阶段 0。

### 阶段 2：Mock 闭环（核心里程碑）

- **目标**：从创建项目到合成可播放 MP4 的端到端闭环。
- **交付物**：
  1. Provider 适配层：Provider 基类协议 + MockText/Image/Video/AudioProvider（模拟排队、处理中、成功、失败、超时、取消、重试；失败可按概率或参数触发）
  2. Dramatiq Worker + 任务状态机（queued → processing → succeeded | failed | timeout | cancelled），进度持久化，服务重启恢复策略
  3. SSE 进度接口（心跳 15s、Last-Event-ID 续传）+ 前端断线降级 5s 轮询
  4. 任务接口：查询、取消（queued/processing）、重试（failed/timeout/cancelled，retry_count+1）、项目维度任务列表
  5. 素材：上传、预览（Range）、素材库；`media/mock/` 测试素材（≥3 图、≥2 音频、≥1 视频、≥1 字幕）
  6. 字幕文件加载（SRT/ASS）；FFmpeg 合成（拼接 + 混音 + 字幕封装，合成前校验素材/时长/字幕，失败返回 40002 明确错误）
  7. 剧本生成任务（Mock，JSON Schema 校验）、剧集工作台（4.3）、任务中心（4.4 全局抽屉 + /tasks）、预览页（4.5）
  8. 请求/响应/耗时/费用/retry_count 全部落库；参数哈希（idempotency_key）缓存命中直接返回历史任务
- **验收**（对齐 PRD 第 16 节标准 1~10）：创建项目与剧集；生成 Mock 结构化剧本（含场景/角色/对白/分镜）；分镜关联图片和视频素材；对白关联音频；加载字幕文件；FFmpeg 合成可播放视频；前端实时任务进度；失败可重试、可取消；刷新页面后项目与任务状态不丢失；合成失败返回明确错误。
- **依赖**：阶段 1。

### 阶段 3：文本、语音和字幕

- **交付物**：1 个真实文本 Provider、1 个真实语音 Provider；record/replay 模式落地；调用确认弹窗（require_confirm → confirm:true）；费用与调用量记录；faster-whisper 字幕生成（`/api/generation/asr`）。
- **验收**：真实调用请求/响应/费用落库；replay 不重复消费额度；Whisper 生成字幕时间轴合规。
- **依赖**：阶段 2。

### 阶段 4：图片、视频和角色一致性

- **交付物**：图片 Provider、视频 Provider（超时/取消/重试/缓存）；角色参考图上传与角色卡版本锁定引用；Provider 配置管理页（4.7）。
- **验收**：真实/Mock 可切换；confirmed 角色卡生成任务只按 version 引用；超时与取消行为正确。
- **依赖**：阶段 3。

### 阶段 5：体验优化

- **交付物**：时间轴视图（Vue Flow）、成本统计报表、素材版本管理、暗色主题（Element Plus dark）、页面性能与错误体验优化。
- **验收**：工作台可切换卡片流/时间轴；成本按 provider/模型可查。
- **依赖**：阶段 4。

## 5. 关键约束（贯穿所有阶段）

1. 所有生成任务先持久化为 `queued` 再投递 Dramatiq；API 同步只返回任务受理结果。
2. 所有 AI 能力只经 Provider 适配层；业务代码不依赖具体供应商。
3. Mock Provider 必须能模拟全部终态，不能永远成功。
4. 敏感信息（API Key、数据库密码）只经环境变量；不入前端、日志、测试数据、Git；provider_configs 只存 `api_key_ref`（变量名）。
5. 数据库变更必须提供 Alembic migration；接口必须有参数校验、统一错误响应和测试；不得为通过测试削弱业务校验。
6. FFmpeg 合成必须输出真实可播放的 MP4。
7. 任务状态从后端恢复，页面刷新不丢。
8. 提示词模板化版本化（prompts 表），不散落业务代码。

## 6. 运行方式（阶段 1 起生效）

| 终端 | 命令 | 说明 |
|------|------|------|
| 0 | `docker compose -f docker-compose.dev.yml up -d` | MySQL + Redis |
| 1 | `uvicorn app.main:app --reload --port 8000`（backend） | FastAPI |
| 2 | `dramatiq app.tasks --processes 2 --threads 4`（backend） | Worker（Windows 兼容性见 DECISIONS D-03） |
| 3 | `npm run dev`（frontend） | http://localhost:5173 |
