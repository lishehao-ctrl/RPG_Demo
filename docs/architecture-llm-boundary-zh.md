# LLM 责任边界（ZH）

## 当前边界（Author 已移除）
1. LLM 只用于 Play Runtime：
- 输入映射（selection）
- 叙事生成（narration）
2. 结构校验、状态推进、任务/事件/结局规则均由确定性引擎负责。

## 不再存在的能力
以下 Author 侧能力已 hard-cut 移除：
- `/demo/author`
- `validate-author / compile-author / author-assist` 及其 stream/file 变体

## 设计原则
1. **Fail-fast**：LLM 不可用时，step 不提交业务变更。
2. **Deterministic-first**：状态机与规则执行不依赖 LLM。
3. **可观测**：Dev 页保留调试视图与轨迹能力。
4. **State Patch Engine**：背包/NPC/状态类变更由确定性 patch 引擎执行，LLM 不直接写核心状态。
5. **Input Policy Gate**：自由输入先过策略层（归一化、限长、注入拦截）再进入选择链路。

## 触点
- Session 选择链路：`app/modules/session/selection.py`
- Session 叙事链路：`app/modules/session/story_runtime/pipeline.py`
- Runtime 编排：`app/modules/session/service.py`
