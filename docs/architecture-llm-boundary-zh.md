# LLM 边界（V2）

## 1. 三条固定调用策略
1. `selection`
- `chat/completions`
- `stream=false`
- `response_format.json_schema`
- 本地 grammarcheck（JSON parse + JSON Schema + top-level object）

2. `narration`
- `chat/completions`
- `stream=true`
- 服务端拼接 `choices[0].delta.content`
- 默认忽略 `reasoning_content`

3. `ending`
- `chat/completions`
- `stream=false`
- `story_ending_bundle_v1`（`narrative_text + ending_report`）

## 2. free-input 选择映射（V2）
- schema：`story_selection_mapping_v2`
- 必填字段：
  - `target_type` (`choice|fallback`)
  - `target_id`
  - `confidence`
  - `intensity_tier` (`-2|-1|0|1|2`)
  - `top_candidates`

语义约束：
- free-input 必须调用 LLM 映射
- runtime 外层最多尝试 3 次：
  - 触发条件：网络/调用失败、grammar/schema/shape 失败、`target_id` 不在当前白名单
  - 重试注入纠偏上下文：`last_error_code` + `allowed_target_ids`
  - selection 通道单次传输尝试固定为 1（避免 3x3 放大）
- LLM/grammar/schema 任一失败 -> `LLM_UNAVAILABLE`
- 本步回滚，不做降级 fallback 提交

## 3. 失败语义（统一）
- structured 输出 parse/schema/shape 失败 -> `LLM_UNAVAILABLE`
- streaming 空输出或中断 -> `LLM_UNAVAILABLE`
- selection 三次重试仍失败 -> `LLM_UNAVAILABLE`
- runtime 捕获后回滚 step（state/node 不提交）

## 4. 配置极简化
仅保留 3 个环境变量：
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY`

自动模式：
- `LLM_API_KEY` 为空：`fake_auto`
- `LLM_API_KEY` 非空：`real_auto`

固定默认（代码常量）：
- path: `/chat/completions`
- selection/ending strict schema: `true`
- narration: stream 聚合文本
- timeout: selection 8s, narration/ending 30s
