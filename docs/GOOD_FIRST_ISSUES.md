# Good first issues

> Language: 本文是中文版 · English mirror at [GOOD_FIRST_ISSUES.en.md](./GOOD_FIRST_ISSUES.en.md)

为新贡献者准备的小任务清单.每条都拆得足够小,1-3 小时能落地,不需要
深入理解 prompt-driven 引擎的内在.

开始做的时候,**先在对应 tracking issue 下留言**避免撞车.如果还没有
issue,请新开一个引用本文.

---

## 后端(Python)

### 1. `_pick_npc_agenda` 单测
**文件**:`tests/test_narrative_schedulers.py`(新建)
**预计耗时**:2h

写确定性测试覆盖 agenda scheduler 的 stage 逻辑:

- `hook` 阶段 → 空 list
- `pressure` 阶段 + `turn_index % 2 == 0` → 1 个 NPC,intent="probe"
- `pressure` 阶段 + 奇数 turn_index → 空
- `reversal` → 2 个 NPC,intent 含 `leverage` + `pressure`
- `climax` → 2 个 NPC,leverage / reveal 交替
- `pre_finale` → 2 个 NPC,leverage / reveal
- story 模式 → 永远空

用 `narrative/contracts.py` 里的 CastMember 合成对象.无 LLM.

### 2. `compute_current_inventory` 单测
**文件**:`tests/test_narrative_inventory.py`(新建)
**预计耗时**:1h

验证 walk-on-read 行为:

- 空 history + 非空 `starting_assets` → 返回 starting_assets
- history 含一个 narrator beat 有 `inventory_delta.added` → starting + added
- 大小写不敏感 substring 匹配 removed → drop
- 重复 `removed` 同一个 item → 不会 double-drop crash

### 3. `_parse_branches` label normalize 单测
**文件**:`tests/test_narrative_branches_parser.py`(新建)
**预计耗时**:1h

验证:
- off-pool label 通过 `_normalize_ending_label` snap 到合法 label
- `alternate_ending_label == actual_ending_label` 的 branch 被过滤
- 重复 `pivot_beat_ord` 去重(只保留第一个)
- 输出按 `pivot_beat_ord` 升序
- 输入超过 4 条会被 cap 在 4 条

### 4. `tools/http_product_smoke.py` 加 `--dry-run` 标志
**文件**:`tools/http_product_smoke.py`
**预计耗时**:1h

目前 smoke 端到端跑真实服务器 + 真实 LLM(花钱).加 `--dry-run`,跑
完整 HTTP 路由但 stub 掉 LLM 调用,这样 CI 能用,没有 API key 的 OSS
贡献者也能跑.

---

## 前端(TypeScript / React)

### 5. 给新增页面扩展 i18n string bundle
**文件**:`frontend2/src/shared/lib/i18n.ts`
**预计耗时**:1-2h

zh/en string bundle 已有.新页面 / 新组件加硬编码文案时,在
`STRINGS_ZH` / `STRINGS_EN` 加 key,把字面量替换成 `useT('your.key')`.
两个 bundle 保持同步 — 如果 key 只有 zh,en bundle 应该 graceful fallback.

### 6. 给 `LoadingShim` 加键盘可访问性
**文件**:`frontend2/src/shared/ui/loading-shim.tsx`
**预计耗时**:30 min

loading shim 已有 `role="status"` 和 `aria-live="polite"`,但 dot 动画
没有 `prefers-reduced-motion` fallback.加 media query,在用户偏好减少
动画时降低 y-bounce 动画.

### 7. player diary 字数计数器
**文件**:`frontend2/src/pages/play/play-page.tsx`
**预计耗时**:30 min

diary textarea 有 `maxLength={600}` 但没有可见计数器.在 textarea 下面
加一个 `{N} / 600` 的小 chip,`N > 540` 时变暖色.参考 create page 的
seed 输入计数实现.

### 8. EndingScreen 加 "回顾这局" 按钮
**文件**:`frontend2/src/pages/play/play-page.tsx`
**预计耗时**:1h

ending screen 现在显示 passage + highlights + branches + share 按钮,
但没法滚回 12 回合的完整故事.加一个按钮把页面滚回 cast strip / 第一
turn 让玩家重读.确保 `zh` 和 `en` bundle 都有按钮文案.

---

## 文档 / 社区

### 9. 加第三个 locale(例如 `ja` 或 `es`)
**文件**:`frontend2/src/shared/lib/i18n.ts` + `rpg_backend/narrative/engine.py`
**预计耗时**:3-4h

扩现有 zh/en scaffold:

- 加 `STRINGS_JA`(或你的 locale)bundle,镜像所有 key
- 在 create page 的 `LANGUAGE_OPTIONS` 加该 locale
- `_OPENING_SYSTEM_PROMPT` / `_TURN_SYSTEM_PROMPT` 加 prompt 语言分支
- ending label 规范 ID 保留中文,只需翻译 display map

开始前请开 issue 说你想加哪个 locale,我们好对齐用词选择.

### 10. 加更多架构图
**文件**:`ARCHITECTURE.md` + `ARCHITECTURE.en.md`
**预计耗时**:2h

doc 已有 per-turn pipeline + session lifecycle 两个 mermaid block.
价值最高的下一个图:**4-NPC 样本 cast 的 inter-NPC leverage graph**.
帮新读者理解为什么 `leverages_over_other_npcs` 是 N×N 而不只是
leverage_over_player.

mermaid 图最简单.zh 和 en 两份内容保持一致(mermaid 与语言无关).

---

## 怎么 claim

1. 选一个上面的任务.
2. 开 GitHub issue,标题 `[GFI N] <task description>`(例如
   `[GFI 1] _pick_npc_agenda 单测`).
3. 留言 "I'm working on this" 让别人知道.
4. 7 天内提 PR; 否则我们会 un-assign.
