# MVP Closeout 2026-03-21

## 当前结论

项目当前可以按 MVP 视角收尾。

已满足：

- 真实 `author -> publish -> play` 产品闭环
- 真实 cookie session 账号体系
- public library / private owned story / protected play session 的权限边界
- 本地与生产单机部署路径
- 真实 HTTP smoke 与真实浏览器 smoke
- benchmark 诊断链路与 A/A 稳定性基线

生产地址：

- `https://rpg.shehao.app`

生产主机：

- `ubuntu@54.152.242.119`
- backend: `127.0.0.1:8010`
- nginx vhost: `/etc/nginx/sites-available/rpg-shehao-app`

## 身份与权限边界

当前身份模型已经不再依赖 `x-rpg-actor-*` header。

使用方式：

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`
- `GET /me`

真实前后端契约：

- 前端通过 cookie session 维持登录态
- 未登录可浏览 public library 和 public story detail
- 未登录不能 create author job、publish、create play session、submit play turn
- 私有 story 仅 owner 可见
- play session 仅 session owner 可访问

生产 cookie 配置：

- `APP_AUTH_SESSION_COOKIE_SECURE=true`
- `APP_AUTH_SESSION_COOKIE_SAMESITE=lax`

## 关键验证

### 代码级验证

- `pytest -q`
- `cd frontend && npm run check`

### 本地真实产品 smoke

命令：

```bash
python -m tools.http_product_smoke \
  --base-url http://127.0.0.1:8002 \
  --include-benchmark-diagnostics
```

最近一次关键结果：

- `auth` 成功
- `preview_elapsed_seconds = 8.876`
- `author poll_elapsed_seconds = 60.284`
- `publish` 成功
- `create_session_elapsed_seconds = 0.020`
- `submit_turn_elapsed_seconds = 4.476`
- `author_diagnostics_available = true`
- `play_diagnostics_available = true`

测试 seed：

- `A municipal archivist finds the blackout ration rolls were altered to punish districts that backed the reform slate.`

测试首回合输入：

- `I force the emergency council to compare the sealed ration rolls in public before any clerk can revise them again.`

### 生产真实浏览器 smoke

真实 DNS Playwright smoke 已执行，实际完成：

1. 未登录打开 `https://rpg.shehao.app/#/stories`
2. 验证 public library 正常
3. 未登录点击 `Create`，正确跳转 `#/auth`
4. 注册真实生产 smoke 账号
5. 创建 preview
6. 启动 author job
7. 发布 private story
8. 打开 story detail
9. 创建 play session
10. 提交一回合 turn
11. 删除测试 story

结果：

- 全链路成功
- 生产 smoke 测试 story 已清理
- 生产控制台未见阻塞性错误

生产 smoke seed：

- `A records clerk discovers emergency harbor manifests were altered to reward loyal districts before a relief vote.`

生产 smoke 首回合动作：

- `You press Kaelen Thorne until the concealed truth starts to surface.`

## 关键稳定性数据

下面这些数据都是已经落盘的 artifact，可用于后续回归对比。

### 1. Stage runner cleanup A/A

artifact：

- `artifacts/benchmarks/stage_runner_cleanup_aa_diag_20260321_191205.json`
- `artifacts/benchmarks/stage_runner_cleanup_aa_diag_20260321_191629.json`
- `artifacts/benchmarks/stage_runner_cleanup_aa_diag_phase_compare_20260321_191629.json`

结果摘要：

- baseline:
  - `author_publish_success_rate = 1.0`
  - `play_completed_sessions = 6`
  - `expired_sessions = 0`
  - `p95_submit_turn_seconds = 7.212`
  - `heuristic_interpret_rate = 0.087`
  - `render_fallback_rate = 0.0`
  - `mean_narration_word_count_per_turn = 77.217`
- candidate:
  - `author_publish_success_rate = 1.0`
  - `play_completed_sessions = 6`
  - `expired_sessions = 0`
  - `p95_submit_turn_seconds = 7.743`
  - `heuristic_interpret_rate = 0.167`
  - `render_fallback_rate = 0.0`
  - `mean_narration_word_count_per_turn = 79.583`

结论：

- reliability gate 通过
- transport 层统一未引入 author/play 链路失效

### 2. Workflow state cleanup A/A

artifact：

- `artifacts/benchmarks/workflow_state_cleanup_aa_diag_20260321_192301.json`
- `artifacts/benchmarks/workflow_state_cleanup_aa_diag_20260321_192811.json`
- `artifacts/benchmarks/workflow_state_cleanup_aa_diag_phase_compare_20260321_192811.json`

结果摘要：

- baseline:
  - `author_publish_success_rate = 1.0`
  - `play_completed_sessions = 6`
  - `expired_sessions = 0`
  - `p95_submit_turn_seconds = 6.938`
  - `heuristic_interpret_rate = 0.087`
  - `render_fallback_rate = 0.0`
- candidate:
  - `author_publish_success_rate = 1.0`
  - `play_completed_sessions = 6`
  - `expired_sessions = 0`
  - `p95_submit_turn_seconds = 7.294`
  - `heuristic_interpret_rate = 0.043`
  - `render_fallback_rate = 0.0`

结论：

- reliability gate 通过
- `design_bundle` 单一 canonical state 改造未造成回归

### 3. Auth backend A/A

artifact：

- `artifacts/benchmarks/auth_backend_aa_diag_20260321_204312.json`
- `artifacts/benchmarks/auth_backend_aa_diag_20260321_204754.json`
- `artifacts/benchmarks/auth_backend_aa_diag_phase_compare_20260321_204754.json`

结果摘要：

- baseline:
  - `author_publish_success_rate = 1.0`
  - `play_completed_sessions = 6`
  - `expired_sessions = 0`
  - `median_create_session_seconds = 0.014`
  - `p95_submit_turn_seconds = 6.862`
  - `render_fallback_rate = 0.0`
  - `heuristic_interpret_rate = 0.083`
  - `mean_narration_word_count_per_turn = 83.708`
- candidate:
  - `author_publish_success_rate = 1.0`
  - `play_completed_sessions = 6`
  - `expired_sessions = 0`
  - `median_create_session_seconds = 0.015`
  - `p95_submit_turn_seconds = 6.800`
  - `render_fallback_rate = 0.0`
  - `heuristic_interpret_rate = 0.182`
  - `mean_narration_word_count_per_turn = 76.864`

结论：

- reliability gate 通过
- auth/session 替换没有打断 benchmark 主链

## 当前非目标 / 已知不继续深挖项

这些不再作为 MVP 阶段阻塞项：

- 多实例部署
- 分布式 job/session locking
- Redis / Postgres 替代 SQLite
- 邮件验证
- 密码重置
- 社交登录
- 更复杂的账户资料页
- Playwright 大规模并发生产门禁常态化

## 建议的收尾状态

作为 MVP，目前建议冻结如下边界：

- 继续保持单后端进程
- 继续使用 SQLite
- 把 benchmark 作为受控环境工具，不对公网开放
- 后续只处理真实 bug 与极小幅度体验改进，不再做大重构

## 后续若要重启开发

优先级建议：

1. 账户管理细节，例如账号删除、密码修改
2. 生产观测，例如结构化 access/error logs
3. 更长期的存储升级和多实例准备
