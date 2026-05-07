# Tiny Stories 设计笔记 — 我用 9 层 prompt 机制把 LLM 变成博弈剧导演

> 这是 [Tiny Stories](https://github.com/...) 的设计文档,讲我为什么这样设计这个引擎,**不是技术教程**.如果你只想读代码,跳到 [ARCHITECTURE.md](../../ARCHITECTURE.md).

---

## 核心矛盾

LLM 写故事很厉害.但 LLM-driven 互动叙事产品(AI Dungeon / Character.AI)有一个共同的弱点:

**玩家是观众,不是主角.**

你写一句话,LLM 给你回一段华丽的散文.你再写一句,它再回一段.你的"选择"在 prompt 里只是一行 free input 文本,LLM 主要靠自己的 stylistic preferences 和 history pattern 推进.结果是:

- 每一段读起来都很好
- 但你做了什么不重要,故事都会朝同一个方向走
- 玩 5 分钟你就明白了,然后弃坑

我做 Tiny Stories 是想解决这个矛盾的一个具体子问题:**做一个 12 回合的"博弈剧",在这个紧凑的 form factor 里让玩家真正感受到"我的选择改变了什么"**.

为了让玩家感受到 agency,我堆了 9 层机制.下面是设计思路.

---

## 起手式:为什么是 12 回合?

不是 100 回合,不是无穷.

- **12 回合 ≈ 15 分钟**:手机时代的注意力上限
- **够长能讲完一个有起承转合的故事**:hook → pressure → reversal → climax → pre_finale,5 个戏剧阶段每段 2-3 回合
- **够短可以重玩**:玩完一局可以马上重玩另一个 role,不会"已经看过了不想再看"
- **够短可以分享**:微信发个链接,朋友 15 分钟玩完会回你"我的结局是 X 你呢"

这个 form factor 决定了之后所有的设计.如果是 100 回合,机制堆叠会过载;如果是 5 回合,故事弧线展不开.

---

## 9 层机制 — 为什么是这 9 层

我把每层机制对应到玩家的一个具体疑问:

### 1. NPC 调度 (`_pick_npc_agenda`)
**玩家疑问**:"为什么这一回合是 X 在跟我说话,不是 Y?"
**机制**:每个 NPC 有 `hidden_objective`.gauntlet 模式下,scheduler 按 stage_phase 决定**这一回合谁该主动出招**(probe / pressure / leverage / reveal / betray / ally).Stale NPCs(最近 npc_pulse 都是 steady)优先被推到前面,airtime 自然均衡.

没有调度的 LLM 会让某一个 NPC 抢戏,其他 NPC 沦为背景板.

### 2. Reversal 强制翻转 (`_pick_twist_directive`)
**玩家疑问**:"剧情会有真正的转折吗?还是 LLM 一直在加压?"
**机制**:reversal 阶段(turn 6 左右)scheduler 强制注入一个 twist directive — `secret_inter_leverage_revealed` / `betrayal_realignment` / `player_persona_crack` / `hidden_npc_arrival` / `external_event_intrusion`.LLM 必须 honor 这个指令,不能只升压.

LLM 的天性是渐进升压,不是结构性翻转.必须 hard-code.

### 3. 玩家身份卡 (`PlayerRole`)
**玩家疑问**:"我每次玩同一个故事都一样吗?"
**机制**:每个 template 有 3-5 张 player role 卡,每张是不同身份(`public_persona` 别人看到的你 + `hidden_objective` 你真正想要的 + `leverages_over_npcs` 你手里的反将牌 + `starting_assets` 开局握着的物件).同一个 seed 选不同 role 走出截然不同的故事.

这是把"重玩有意义"从修辞变成结构的关键.单 role 你只是看 LLM 写不同结局;多 role 你是用不同身份重活一遍.

### 4. NPC 之间的 N×N 政治网络 (`leverages_over_other_npcs`)
**玩家疑问**:"NPC 们彼此什么关系?他们会互相揭穿吗?"
**机制**:每个 NPC 不只对玩家有 leverage,还可能握着别的 NPC 的把柄.整个 cast 形成 4-9 条 edge 的政治网络.LLM 在 narration 中可以让 NPCs 互相威胁、临时联手、突然反水,**有结构性合理性支撑**.

加上这层,玩家从"vs N 个 NPC"切到"在 N×N 网络中找位置"——可以挑拨而不是硬刚.

### 5. Inventory 累积
**玩家疑问**:"我在游戏里得到的东西,系统记得吗?"
**机制**:每个 narrator beat 可选输出 `inventory_delta` (added/removed).walk-on-read:`current_inventory = starting_assets + Σ(narrator deltas)`.从不 desync,因为没有 cached state.

每回合 LLM 看到玩家手里所有牌,选项里"亮出 X"才有依据.

### 6. Advisor Oracle (pay-1-turn)
**玩家疑问**:"我能不能问'告诉我这个 NPC 真的想要什么'?"
**机制**:advisor 平时是普通陪聊朋友.玩家可以选择**消耗 1 个 turn budget** 让 advisor 进入 oracle 模式 — 看到所有 NPC 的 `hidden_objective` + leverage + 玩家 inventory + failure_conditions,给一段 vague-but-useful hint.

代价是真的:`turn_budget` 减 1,故事被压缩.玩家做"该不该问"的资源决策.

### 7. Player Diary (内心独白)
**玩家疑问**:"我心里真正想的事 LLM 知道吗?"
**机制**:每回合玩家可选写 30-200 字 diary.NPC **看不到**.LLM 用它 calibrate 内心动作描写("演 vs 真"的缝隙).完局后回看 12 条独白 = 心路历程.

### 8. 三层结局 + 15 closed pool
**玩家疑问**:"我赢了还是输了?"
**机制**:15 个固定 ending labels,映射到 3 tier(victory / compromised / collapsed).LLM 必须从池里选,off-pool 自动 snap.5 个人玩同一个 template 会出现 label 碰撞,**这就是社交比较的钩子**("你居然走到了和解?我撕到了反噬").

### 9. Failure Judge + Early Collapse
**玩家疑问**:"做错了会真的失败吗?"
**机制**:gauntlet 模式每回合跑一次 failure judge LLM call,看玩家最近行为是否触发某条 failure_condition.触发 → 强制 early ending,label 限定在 collapsed tier 池.

让"失败"是真的失败,不是"再走一步看看".

### Bonus 后游戏 — Highlight Reel + Branches
**玩家疑问**:"我刚刚到底走过什么?"
**机制**:完局后 LLM 挑 5 个 pivotal beats(headline + body excerpt + why_pivotal),再挑 2-3 个**没走的另一条路**(pivot turn + alternate option + alternate ending label).Highlight 是"你走过的",Branches 是"你没走过的"—— 完整 closing loop.

---

## 跨层契约:为什么这 9 层不互相打架

每个机制单独看都不复杂.挑战在 9 层叠起来不冲突.

我用了 3 个原则:

**1. 单一真值源 (Pydantic contracts)**

所有跨模块/跨层数据用 `narrative/contracts.py` 的 Pydantic 类型.前端 TypeScript 是这个的 mirror,任何后端改动必须同步前端.LLM 输出也校验到这层,不合规字段被 parser 丢弃.

这避免了"前后端契约漂移"的常见陷阱.

**2. Walk-on-read,不缓存中间状态**

`current_inventory` 不存,每次 advance 时从 history walk 一遍算出来.`pulse_trend` 同理,每回合从最近 4 个 narrator beats 抽出来.

代价是每回合 O(N) 计算.收益是永远不会 desync,代码层面也容易理解("这个值的 source of truth 是什么"永远有清晰答案).

**3. Prompt 是契约**

每个机制的 LLM 行为不是"训练出来的".是 `_TURN_SYSTEM_PROMPT` 里的几行硬规则:

```
**Reversal 强制翻转(twist_directive)—— 仅在 reversal 阶段出现**:
当 user_payload 含 `twist_directive: {kind, hint}`,这表示**当前回合是 reversal 拐点**...
该回合 passage **必须真正 honor 指定的 twist kind**...
```

调试不工作的机制,90% 的修复在 prompt 里加一句"⚠️ 必须" 而不是改 Python 代码.

---

## 我学到了什么

做这个项目让我对 prompt-driven LLM app 有几个真切的体感:

**1. LLM 是黑盒,但可以用结构化字段把它"锚定"住**

直接喂 free text 的 LLM 输出不可控.但**给它一个 JSON 输出 schema + 每个字段的硬规则**,它的输出就变得 90% 可靠.剩下 10% 用 retry 兜底.

**2. 用 LLM 模拟玩家测试机制效果非常便宜**

我用 LLM-as-cooperative-player 跑了几十次 12-turn 模拟,验证 9 个机制叠起来不打架.这种实验**用真人测试需要 $千 + 几周**,LLM 模拟只要 $十几 + 几小时.

但要注意:**LLM player 极度配合**.它按 persona 严格演.真实用户会乱选、跳过 diary、5 回合就走人.LLM 模拟只能验证"机制能否 work",不能验证"用户会不会喜欢".

**3. Persona-driven LLM player 暴露真实问题**

我后来用 3 个 sonnet subagent 模拟 3 种"新用户类型"(casual / hardcore / skeptic),让他们独立写 UX review.skeptic 那条最锋利的反馈:**"我感觉我是观众,不是主角.我选 0 还是选 1,叙事都在往一个方向走"** — 这是产品的灵魂诊断,我自己写 100 个测试用例都得不出来.

---

## 还没解决的核心问题

诚实说:9 层机制 + 2 轮视觉 polish + 3 轮回归测试之后,**最深的产品问题没解决**:

> Skeptic: "我的输入是装饰性的."

机制全在后端正确执行 — npc_pulse 在变,inventory delta 在累积,branches 在生成.但玩家选项的 **narrative weight 太轻**.LLM 主要被 stage scheduler / agenda / twist 驱动,玩家选项是 trigger 不是 director.

skeptic 全选 [0],故事还是按 LLM 预设节奏推进.因为 LLM 在按 stage 目标演,你选什么不重要.

这是下一个版本要解决的根本问题.可能需要重写 turn prompt,要求"option 0 / 1 / 2 必须导向截然不同的 narrative 走向",或者引入 player_pick 作为 narrative weight 的 first-class signal.

---

## 你能学到什么(如果你也做 LLM 产品)

1. **结构化 schema + Pydantic + JSON-mode LLM = 90% 可控的 LLM**.先做这个,再做 prompt engineering.
2. **scheduler 是免费的可控性**.把"什么时候让 LLM 做什么"写成 Python,LLM 只负责"具体怎么做",可控性大幅提升.
3. **walk-on-read 比缓存中间状态简单**.LLM 应用的状态结构通常不复杂,但容易 desync.从 source 重算.
4. **LLM 模拟玩家是 alpha 期最便宜的验证手段**.派几个 subagent 用不同 persona 玩,比写 unit test 信号丰富.
5. **真人测试早期不可替代**.LLM player 太合作.找 5 个真朋友玩,数据信号 > 100 次 LLM 模拟.

---

## Repo

[github.com/...](https://github.com/...) — MIT licensed.贡献欢迎.具体方向见 [CONTRIBUTING.md](../../CONTRIBUTING.md) 和 [docs/GOOD_FIRST_ISSUES.md](../GOOD_FIRST_ISSUES.md).

---

*写于 2026-05.项目处于 OSS preview / alpha 状态.*
