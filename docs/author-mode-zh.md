# Story Author Mode 使用手册（中文）

本文档面向作者（非后端开发者），解释如何在 `/demo/author` 中从一个 seed 快速写出可玩的 RPG 草稿。

适用版本：
- Authoring 协议：`ASF v4`
- Runtime 编译目标：`StoryPack v10`

---

## 1. 你会看到什么页面

打开：`http://127.0.0.1:8000/demo/author`

Author Mode 主要有两层结构：

1. 顶部双标签
- `Author`：日常创作用（默认）
- `Debug`：排查/诊断用（默认隐藏，需开启 `Show Debug`）

2. Author 下的 3 页工作流
- `Compose`：写 seed/source、让 AI 生成和续写
- `Shape`：逐场景精修结构
- `Build`：校验、编译、保存、试玩

---

## 2. 最快上手流程（推荐）

### 步骤 1：选择入口

在 `Compose` 页选择：
- `Spark Mode`：一句话灵感开局
- `Ingest Mode`：粘贴整段故事导入

输入区：
- `Spark Seed`：你的创作种子
- `Ingest Source Text`：整段故事
- `Global Brief`：世界/冲突/目标补充说明

### 步骤 2：点击 `Parse All Layers`

行为说明（当前实现）：
- Assist 成功后会**自动应用 patch**到草稿（不需要再点 Apply）
- 你可以随时点 `Undo Last Apply` 回滚最近一批自动改动
- 对 `seed_expand / story_ingest / continue_write`，后端会在一次点击里执行“条件分阶段生成”：
  1) 先扩写创意蓝图（冲突、分支策略、节奏）
  2) 若检测到 NPC 数量/角色多样性不足，再执行角色蓝图补全（cast blueprint）
  3) 最后结构化生成可落稿 patch（`suggestions + patch_preview`）
- 角色策略是“保留已有 + 自动补齐”：优先保留已有命名 NPC，再补齐到 `3-5`（硬上限 `6`）。

### 步骤 3：继续创作（增量）

在 `Compose` 的 `Continue Writing` 区继续输入并调用：
- `Continue Write`：向后续写，追加可玩节点
- `Trim Content`：删减内容并自动修复引用
- `Spice Branch`：增强分支差异
- `Rebalance Tension`：重平衡压力/恢复节奏

### 步骤 4：必要时去 `Shape` 微调

只在你需要精修时展开：
- Scene 核心字段（`scene_key/title/setup`）
- Option 核心字段（`label/go_to`）
- Advanced 区（action/effects/requirements 等）
- Characters / Action 现在优先使用“自然语言模板行”编辑（更易读），不是主流程 JSON 编辑器。
- Consequence / Ending 在主流程显示自然语言摘要，复杂结构细改建议走 `Refine This Layer` 或 Debug Raw。

### 步骤 5：在 `Build` 完成闭环

依次执行：
1. `Validate ASF v4`
2. `Compile StoryPack`
3. `Save Draft`
4. `Create Session + Open Play`

---

## 3. Parse 后到底发生了什么

当 `seed_expand` 成功时，系统会产出并规范化为 4 节点张力环（tension loop）：

1. `pressure_open`
2. `pressure_escalation`
3. `recovery_window`
4. `decision_gate`

目标是让故事天然具备：
- 压力上升
- 恢复窗口
- 关键决断

这样可玩性通常比“2 场景模板”更好。

另外，若本轮改动了 `flow.scenes[].scene_key`，系统会自动同步修复 `ending.ending_rules[*].trigger.scene_key_is`，
避免出现 `AUTHOR_UNKNOWN_SCENE_REF` 这类悬挂引用错误。

---

## 4. Assist 成功 / 失败语义

### 成功时
- 返回 `suggestions + patch_preview + warnings + model`
- 前端会自动应用 patch
- `Story Overview` 会用自然语言段落展示当前冲突、分支与最近更新
- `Writer Turn Feed` 仍保留，但迁移到 `Debug` 标签用于排障

### 失败时（重要）
- `POST /stories/author-assist` 现在不会再返回 deterministic 模板兜底
- 模型不可用或输出无效时，接口返回 `503`
- 常见错误码：
  - `ASSIST_LLM_UNAVAILABLE`
  - `ASSIST_INVALID_OUTPUT`
- Author 页会提示：`Model unavailable. Please retry.`
- Debug 页可以看更细的 `hint`/诊断

---

## 5. Build 页怎么看“好不好玩”

Build 页有两类信息：

1. `Creative Quality Snapshot`（作者友好）
- `Conflict Clarity`
- `Branch Contrast`
- `Recovery Coverage`
- `Deadline Pressure`

2. `Playability Blocking`（硬门禁）
- 结构错误、不可达、死路、严重失衡会在这里阻断

建议：
- 先看 `Creative Quality Snapshot` 快速判断玩法张力
- 再看 `Playability Blocking` 做硬修复

---

## 6. Debug 什么时候用

只在以下情况打开 `Show Debug`：
- 你想确认 AI 具体建议了什么（`AI Assist Suggestions`）
- 你要看每条 patch 路径（`Patch Preview`）
- 你要看 Writer Turn 明细与 Raw Layer Data（高级兜底）
- 你在排查为什么验证/编译失败（diagnostics/mappings/raw JSON）

平时写作建议只留在 `Author` 页，避免信息噪声。

---

## 7. 常见问题（FAQ）

### Q1：我点 `Parse All Layers` 会自动补全吗？
会。当前 UI 策略是 Assist 成功即自动应用 patch。  
不满意直接 `Undo Last Apply`。

### Q2：为什么我看不到 suggestions/patch？
它们在 Debug 区。默认是作者模式优先，所以会隐藏。  
打开 `Show Debug` 后切到 `Debug` 标签即可查看。

### Q3：第一次 Parse 后，我还想加内容或删内容怎么办？
直接在 `Continue Input` 写自然语言，然后用：
- `Continue Write`（加）
- `Trim Content`（删）
- `Spice Branch`（增强分支）
- `Rebalance Tension`（调节节奏）

### Q4：我什么时候必须进 Shape 页？
当你需要“精确控制”时再进，例如：
- 指定某个 `go_to`
- 微调 option 的 `requirements/effects`
- 人工打磨具体场景文本

### Q5：Assist 报错 503 怎么处理？
优先检查：
1. `.env` 里的模型配置是否正确
2. 模型服务是否可达（网络/DNS/网关）
3. 重试同一按钮

### Q6：分阶段生成太慢/太贵，可以调吗？
可以。可通过 `.env` 调整：
- `LLM_AUTHOR_ASSIST_EXPAND_MAX_TOKENS`（默认 1400）
- `LLM_AUTHOR_ASSIST_BUILD_MAX_TOKENS`（默认 2048）
- `LLM_AUTHOR_ASSIST_REPAIR_MAX_TOKENS`（默认 900）
- 说明：当前后端调用链已强制 `temperature=0`（fail-fast 生产模式），温度相关配置不会影响线上请求。

### Q7：提示词协议层可以调吗？
当前运行策略是固定代理调用（不可切到 Responses API）：
- `POST https://api.xiaocaseai.cloud/v1/chat/completions`
- 固定 system prompt：`Return STRICT JSON. No markdown. No explanation.`
- `temperature=0`
- 失败重试 2 次（`0.5s`、`1s`）后直接报错
- 不使用 `response_format/json_schema`
- `provider` 配置项已移除，不需要在 `.env` 里设置 `LLM_PROVIDER_PRIMARY`
- 日常只需配置 API Key + `LLM_MODEL_GENERATE`（模型名）

可调的是上下文压缩和长度预算：
- `LLM_PROMPT_AUTHOR_MAX_CHARS=14000`
- `LLM_PROMPT_PLAY_MAX_CHARS=7000`
- `LLM_PROMPT_COMPACTION_LEVEL=aggressive`（可改 `safe`）

---

## 8. 作者实战建议（高可玩性）

1. Seed 里尽量写清四件事
- 谁是冲突对象
- 你最稀缺的资源是什么
- 截止时间
- 不可逆后果

2. 每轮只改一个目标
- 例如“先提升分支差异”，不要一次同时改世界观+经济+结局

3. 每做 1-2 轮 assist 就跑一次 Validate
- 小步快跑，避免后面集中返工

4. 把 Debug 当“诊断工具”
- 不要让 patch 细节打断写作节奏

---

## 9. 快速命令（开发环境）

```bash
# 启动
./scripts/dev.sh

# 作者页相关 smoke
pytest -q tests/test_demo_author_ui.py tests/test_demo_routes.py -k author

# assist API
pytest -q tests/test_story_author_assist_api.py
```

---

## 10. 边界与排障定位（避免误诊）

作者模式里最容易混淆的是“文本问题”和“后果问题”。

1. 如果是 `author-assist` 失败（503）：
- `ASSIST_LLM_UNAVAILABLE`：优先查网络/模型可达性/网关配置。
- `ASSIST_INVALID_OUTPUT`：优先查结构化输出契约（prompt + adapter parse/repair）。
- 重点看：`app/modules/story/author_assist.py` 与 `app/modules/llm/adapter.py`。

2. 如果是 Play 叙事文本不理想，但数值变化正常：
- 先查叙事 payload 与提示词，不要先改状态引擎。
- 重点看：`app/modules/session/story_runtime/pipeline.py` 与 `app/modules/llm/prompts.py`。

3. 如果是后果结算/任务推进/结局触发异常：
- 这是确定性引擎问题，不应先改 prompt。
- 重点看：`app/modules/narrative/state_engine.py`、`app/modules/narrative/quest_engine.py`、
  `app/modules/narrative/event_engine.py`、`app/modules/narrative/ending_engine.py`。

完整边界文档：
- `docs/architecture-llm-boundary-zh.md`
