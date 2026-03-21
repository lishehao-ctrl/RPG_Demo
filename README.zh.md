# RPG Demo Rebuild

<p align="center">
  <a href="./README.zh.md">
    <img alt="README 中文版" src="https://img.shields.io/badge/README-%E4%B8%AD%E6%96%87-1677ff">
  </a>
  <a href="./README.en.md">
    <img alt="README English" src="https://img.shields.io/badge/README-English-111827">
  </a>
</p>

## 项目概述

这是一个前后端同仓的 RPG Demo 项目，产品目标不是做一个通用内容平台，而是围绕一条短闭环体验来构建：

1. 用户输入英文 story seed
2. 后端生成 preview
3. 用户启动 author job
4. 前端展示 author loading 与生成进度
5. 生成完成后发布到 story library
6. 用户从 library 选择故事并开始 play session
7. 用户通过自然语言输入推进剧情

当前实现已经不是最初的“minimal backend”骨架，而是包含完整的 `author / library / play / benchmark` 四个后端域，以及一个可直接联调的 React 前端。

当前 MVP 状态与收尾数据见：

- `specs/mvp_closeout_20260321.md`

## 当前架构

### 后端

- 技术栈：FastAPI + Pydantic + LangGraph + OpenAI-compatible Responses transport
- 包目录：`rpg_backend/`
- 身份边界：真实 cookie session auth，不再使用前端自报 header actor
- 主要域：
  - `author/`
    负责 preview、异步 author job、LangGraph 工作流、质量校验、DesignBundle 产出
  - `library/`
    负责已发布故事的持久化、列表查询、关键词搜索、主题过滤
  - `play/`
    负责从 `DesignBundle` 编译 `PlayPlan`，以及 play session 的回合推进
  - `benchmark/`
    负责诊断和 benchmark 响应结构

### 前端

- 技术栈：React 19 + TypeScript + Vite
- 目录：`frontend/`
- 当前分层：
  - `app/` 应用入口、路由、provider、全局配置
  - `pages/` 页面级组装
  - `features/` 页面行为与数据获取
  - `widgets/` 复合 UI 区块
  - `entities/` 基础领域 UI
  - `api/` 前端契约、route map、HTTP client、placeholder client

## 核心数据边界

- `DesignBundle`
  author 工作流的最终产物，也是 play runtime 的输入边界
- `PublishedStory`
  已发布到 library 的故事卡片与预览信息
- `PlaySession`
  运行中的游玩会话快照

## 当前库表与状态说明

- 已发布故事持久化在 SQLite，默认路径为 `artifacts/story_library.sqlite3`
- author job、play session 和 author checkpoint 现在也持久化在 SQLite 运行时状态中
- 这意味着：
  - library 数据可持久化
  - author job 可在后端重启后继续恢复
  - play session 会在过期前跨重启保留
  - 但还不适合多实例共享；部署时应保持单后端进程

## Library 接口

当前 `library` 使用统一的 `GET /stories` 资源，同时承担列表和搜索能力，不再额外拆一套平行搜索接口。

### 已开放接口

- `GET /stories`
  - 支持 query params：
    - `q` 关键词搜索
    - `theme` 主题过滤
    - `limit` 分页大小
    - `cursor` 游标分页
    - `sort=published_at_desc|relevance`
- `GET /stories/{story_id}`
- `POST /author/jobs/{job_id}/publish`

### `GET /stories` 返回结构

返回结构包含：

- `stories`
- `meta`
- `facets`

其中：

- `meta` 提供 `query / theme / sort / limit / next_cursor / has_more / total`
- `facets.themes` 提供主题聚合，供前端 filter 使用

## 仓库结构

```text
.
├── README.md
├── README.zh.md
├── README.en.md
├── pyproject.toml
├── frontend/
│   ├── package.json
│   ├── specs/
│   └── src/
├── rpg_backend/
│   ├── author/
│   ├── benchmark/
│   ├── library/
│   ├── play/
│   └── main.py
├── tests/
├── tools/
├── specs/
└── artifacts/
```

## 本地运行

### 后端

1. 准备 Python 3.11+
2. 安装依赖：

```bash
pip install -e ".[dev]"
```

3. 启动服务：

```bash
uvicorn rpg_backend.main:app --reload
```

### 前端

1. 安装依赖：

```bash
cd frontend
npm install
```

2. 启动开发服务器：

```bash
npm run dev
```

## 配置

后端通过 `.env` 读取配置，环境变量前缀为 `APP_`。

常用配置包括：

- `APP_STORY_LIBRARY_DB_PATH`
- `APP_RUNTIME_STATE_DB_PATH`
- `APP_PLAY_SESSION_TTL_SECONDS`
- `APP_ENABLE_BENCHMARK_API`
- `APP_AUTH_SESSION_COOKIE_SECURE`
- `APP_AUTH_SESSION_COOKIE_SAMESITE`
- `APP_RESPONSES_BASE_URL`
- `APP_RESPONSES_API_KEY`
- `APP_RESPONSES_MODEL`

`APP_RUNTIME_STATE_DB_PATH` 现在用于持久化 author job、play session 和 author checkpoint；已发布 story 仍然保存在 `APP_STORY_LIBRARY_DB_PATH`。

重启后的运行时语义：

- 进行中的 author job 会在服务重新启动后基于最新 checkpoint 自动续跑
- 已完成的 author 结果在重启后仍可查询与 publish
- play session 的 snapshot、history 和 turn trace 会在过期前持续保留

## 校验与测试

后端测试：

```bash
pytest
```

前端类型检查：

```bash
cd frontend
npm run check
```

真实 HTTP 产品联调 smoke：

```bash
python tools/http_product_smoke.py --base-url http://127.0.0.1:8000
```

如果后端开启了 benchmark diagnostics，也可以一起采 author 阶段耗时和 play trace summary：

```bash
python tools/http_product_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --include-benchmark-diagnostics
```

带备份地重置本地业务数据库：

```bash
python tools/reset_local_databases.py
```

AWS Ubuntu 单机部署材料：

- `deploy/aws_ubuntu/DEPLOY.md`
- `deploy/aws_ubuntu/.env.production.example`
- `deploy/aws_ubuntu/rpg-demo-backend.service`
- `deploy/aws_ubuntu/nginx-rpg-demo.conf`

当前生产域名：

- `https://rpg.shehao.app`

Playwright 上线前浏览器联调套件：

```bash
python -m tools.playwright_launch.runner \
  --app-url http://127.0.0.1:5173 \
  --layers env,core,recovery
```

完整的 10 worker 混合并发门禁：

```bash
python -m tools.playwright_launch.runner \
  --app-url http://127.0.0.1:5173 \
  --layers env,core,recovery,parallel \
  --parallel-worker-count 10
```

## 相关文档

- `specs/interface_governance_20260319.md`
  当前前后端接口治理、公共接口边界、以及产品 API 与 benchmark API 的分层规则
- `specs/interface_stability_matrix_20260319.md`
  author / library / play 三个域的字段稳定性分层矩阵
- `frontend/README.md`
  前端 handoff 与前端接口镜像规则说明
- `frontend/specs/FRONTEND_PRODUCT_SPEC.md`
  前端产品目标、心智模型、页面流与 API 映射
- `specs/backend/`
  后端专项设计与历史交接文档
