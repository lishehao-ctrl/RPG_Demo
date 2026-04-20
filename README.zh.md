# RPG Demo Rebuild

## 项目是什么

这是一个前后端同仓的互动叙事 Demo，产品闭环很短：

1. 输入英文 story seed
2. 生成 preview
3. 启动 author job
4. 发布到 library
5. 从 library 进入 play session
6. 用自然语言推进剧情

当前项目正在从旧的 civic procedural 叙事方向转向新的关系戏剧方向。

当前有效的产品 / 重构文档见：

- `specs/relationship_drama_pivot_strategy_20260328.md`
- `specs/backend/2026-03-28-relationship-drama-backend-refactor/SPEC.md`
- `specs/backend/2026-03-28-relationship-drama-runtime-architecture/SPEC.md`
- `specs/frontend/2026-03-28-relationship-drama-ui-refactor/SPEC.md`

## 技术栈

- 后端：FastAPI + Pydantic + LangGraph
- 前端：React 19 + TypeScript + Vite
- 存储：SQLite
- 身份：真实 cookie session auth

主要后端域：

- `rpg_backend/author/`
- `rpg_backend/library/`
- `rpg_backend/play/`
- `rpg_backend/benchmark/`

## 当前状态

- `author -> publish -> play` 全链路可用
- public library / private owned story / protected play session 权限边界已打通
- author job、play session、author checkpoint 可跨重启恢复
- 部署形态仍建议单机单进程，不支持多实例共享

## 本地运行

后端：

```bash
pip install -e ".[dev]"
uvicorn rpg_backend.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 常用验证

后端测试：

```bash
pytest -q
```

前端检查：

```bash
cd frontend
npm run check
```

真实 HTTP smoke：

```bash
python tools/http_product_smoke.py --base-url http://127.0.0.1:8000
```

带 benchmark 诊断的 smoke：

```bash
python tools/http_product_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --include-benchmark-diagnostics
```

## 部署

生产域名：

- `https://rpg.shehao.app`

AWS 单机部署材料：

- `deploy/aws_ubuntu/DEPLOY.md`
- `deploy/aws_ubuntu/.env.production.example`
- `deploy/aws_ubuntu/rpg-demo-backend.service`
- `deploy/aws_ubuntu/nginx-rpg-demo.conf`

## 相关文档

- `specs/relationship_drama_pivot_strategy_20260328.md`
- `specs/backend/2026-03-28-relationship-drama-backend-refactor/SPEC.md`
- `specs/backend/2026-03-28-relationship-drama-runtime-architecture/SPEC.md`
- `specs/frontend/2026-03-28-relationship-drama-ui-refactor/SPEC.md`
- `specs/interface_governance_20260319.md`
- `specs/interface_stability_matrix_20260319.md`
- `frontend/specs/FRONTEND_PRODUCT_SPEC.md`
