# 贡献 / Contributing

感谢愿意来一起做这个项目.项目由小团队维护,我们会读每一个 issue 和大部分
PR.

> Language: 本文是中文版 · English mirror at [CONTRIBUTING.en.md](./CONTRIBUTING.en.md)

## 我们想要什么

项目处于 **OSS preview / alpha** 阶段.机制设计(9 层 narrative engine
+ 后游戏 highlights / branches)基本固化,但围绕它的所有东西 — UX 打磨、
部署故事、provider 支持、国际化 — 都有大量空间.

按 leverage 大致降序的高价值贡献方向:

1. **真人玩家反馈**.开 issue 描述你这一局发生了什么:哪里让你迷惑、哪里
   让你有"我影响了故事"的感觉、几回合放弃.我们目前**真人测试数据约为
   0**,这种反馈比代码 patch 更有用.写中英文都行.

2. **scheduler 加确定性单测**.narrative engine 的几个 scheduler
   (`_pick_npc_agenda`、`_pick_twist_directive`、
   `compute_current_inventory`、`_summarize_recent_consequences`、
   `_parse_branches`、`_parse_player_role_options`)是输入输出结构化的
   纯函数,**目前确定性测试覆盖为 0**.加 `tests/test_narrative_schedulers.py`
   可以让我们带信心地重构.工程价值最高.

3. **Provider 抽象**.gateway 层假定 OpenAI-compatible Responses API;
   实测 DashScope / OpenAI / OpenRouter / Ollama 都能跑.但 Anthropic-
   native / Gemini-native 等形状没有干净的 fallback 路径.在
   `gateway.py` 加一个小的 adapter 接口能拓宽用户群.

4. **多 locale**.前端已有 zh/en 双语 string bundle 层
   (`frontend2/src/shared/lib/i18n.ts`),后端 `engine.py` prompt 接
   language hint.加第三个 locale(如 `ja`、`es`)需要扩展
   `STRINGS_*` bundle + prompt 语言分支.ending label 的规范 ID 保留
   中文,只需翻译 display map.

5. **流式 narration**.目前 `passage` 是 5-8s 后整段返回.流式可以显著
   改善感知响应.`responses_transport.py` 已有流式代码路径,engine
   层需要暴露 token chunks.

6. **持久化 in-game HUD**.role banner 现在显示 `current_inventory`,
   但没有把 inter-NPC leverage 状态或 NPC pulse 历史汇总到一处.侧栏 /
   抽屉能帮 hardcore 玩家不滚动地追踪政治 map.

如果你想做不在上面列表的事,**请先开 issue 描述方案**.prompt-driven 设计
有些不显眼的不变量,从代码看不出来 — maintainer 提前 review,能避免双方
浪费几周.

## 怎么提 PR

1. fork 仓库.
2. 从 `main` 分支.分支名描述具体内容(`feat/anthropic-gateway`,不要
   `patch-1`).
3. **push 前本地跑通这两步:**
   ```bash
   # backend
   pytest -q

   # frontend
   cd frontend2
   npm run check
   npm run build
   ```
   CI 跑同一套.
4. 开 PR.描述里 link 你解决的 issue(没有就描述问题).
5. PR 保持小且 focused.一个 feature 一个 PR,一个 bugfix 一个 PR.
   2000 行的 PR touch 20 个无关地方,我们不会 merge.

## 风格

- **后端 Python**:新公开函数必须有 type hints.`narrative/contracts.py`
  是 canonical schema; 新增字段必须在同一个 PR 里 mirror 到
  `frontend2/src/api/contracts.ts`.
- **前端 TypeScript**:strict mode 开着.新代码不允许 `any`.风格跟现有
  文件,不强制 formatter.
- **注释**:写 *why*,不是 *what*.codebase 里有大量例子 — `engine.py`
  的 prompt 段是"如何 inline 文档化不变量"的范本.
- **commit**:推荐原子 commit.conventional-commit 风格(`feat:`、
  `fix:`、`docs:`、`polish:`)欢迎但不强制.

## 测试哲学

narrative engine 有**两套互补的测试面**:

- **确定性单测**覆盖纯函数(scheduler、parser、helper).不调 LLM,跑得快.
- **LLM smoke 测试**覆盖端到端正确性.调真实 LLM,验证契约
  (例如 `npc_pulse[].reason` 在 shift != steady 时必填).这套手动跑,
  不进 CI.

加新机制时,至少给 scheduler / parser 层加一个确定性单测.端到端 LLM
验证欢迎但不强制 merge.

## 行为准则

友善.不发布私人用户数据.不提交美化暴力 / 骚扰 / 针对真人的内容.我们
保留删除越线 issue / PR / 评论的权利.

## 问题咨询

带 `question` label 开 issue,或者 email hello@tinystories.app(若已在
`frontend2/src/pages/about/` 里列出).
