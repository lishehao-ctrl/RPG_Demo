from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rpg_backend.narrative.contracts import (
    AdvisorMessage,
    CastMember,
    FailureCondition,
    InventoryDelta,
    NPCPulse,
    PlayerGoal,
    PlayerLeverageOverNPC,
    PlayerRole,
    StoryMessage,
    StoryOption,
)
from rpg_backend.narrative.gateway import NarrativeGatewayError, NarrativeLLMGateway


_OPENING_SYSTEM_PROMPT = """\
你是一名擅长写关系剧的剧作家，专长是高密度的现代都市人际戏剧（豪门、职场、情感纠葛、校园、娱乐圈等等）。

玩家给你一句故事种子，你的任务是为这个故事**搭建初始局面**并**写下开场**。

输出**严格** JSON 对象，不要 markdown，不要任何解释文字。字段如下：

{
  "title": "故事的标题，不超过 20 字，富有戏剧张力",
  "advisor_persona": "故事世界里的一个**真实存在的人**，TA 通过手机/电话/微信跟玩家联系，不在主线场景里。必须**清晰、紧凑**地包含四件事：① TA 是谁 + 跟玩家什么关系（举例：'林姐姐——大学一起睡上下铺的死党，现在做投行 VP'）② TA **此刻自己在哪、在做什么**（必须跟主角的场景物理分离，举例：'刚加完班，在停车场坐车里抽烟' / '在虹桥机场候机' / '在家给娃喂夜奶'）③ TA 跟玩家的相处姿态（举例：'毒舌但护短' / '冷静直给从不空话'）④ TA 此刻能怎样跟玩家联系（电话/微信/语音）。整段控制在 60-90 字，**不要把 TA 放在玩家的同一个房间或同一栋楼**，否则就破坏了'局外人'的安全感。",
  "cast": [
    {
      "character_id": "lowercase_underscore_id",
      "display_name": "角色中文名",
      "role": "TA 在故事里的身份（比如：父亲、未婚夫、表姐、上司）",
      "relation_to_protagonist": "TA 与主角（玩家）的关系一句话",
      "hidden_objective": "TA 在这场戏里**真正想要的东西**——可能跟玩家利益冲突。一句话，60 字以内（举例：'借玩家的手当众羞辱苏曼，借机清场' / '逼玩家签下父亲留下的那份股权代持协议'）",
      "leverage_over_player": "TA 手里**捏着的、可以伤到玩家的东西**——一个秘密、一个把柄、一笔钱、一个人质。一句话，60 字以内（举例：'知道玩家三年前烧掉的那份合同备份在他车里' / '保管着玩家弟弟的医疗账单'）",
      "leverages_over_other_npcs": [
        {"target_npc_id": "**另一个 cast 成员的 character_id**（必须是 cast 数组里其他角色，不能是自己）", "leverage": "TA 手里捏着 target_npc 的把柄/秘密/筹码——一句话 60 字内（举例：'知道苏曼三年前在新加坡转移了 800 万海外账户' / '保管着大伯私生子的出生证明' / '握着张浩去年签的那份代孕合同'）"}
        // **0-3 条**。不是每个 NPC 都需要有，但**整个 cast 网络里至少应该有 3-5 条这种 inter-NPC leverage**，让 NPC 之间形成相互制衡的政治网络。设计要点：① 让某些 NPC 看似强势但其实被另一个 NPC 捏着把柄 ② 偶尔形成"环"（A 捏着 B，B 捏着 C，C 捏着 A）让局势可以被任意一点撬动 ③ 玩家如果学会某个 inter-leverage，可以"挑拨"两个 NPC 互撕
      ]
    }
    // 3-5 个角色，每个都必须有 hidden_objective 和 leverage_over_player；leverages_over_other_npcs 整个 cast 加起来 3-5 条
  ],
  "player_goals": [
    {"goal": "玩家这场戏里**想达成的目标**，一句话不超过 40 字", "stakes": "失败的话**会损失什么**，一句话不超过 60 字"}
    // 恰好 2-3 个，必须是玩家**有动力去争取**的事，不是 vague 的"保护自己"
  ],
  "failure_conditions": [
    {"label": "短的触发器名，4-12 字（比如'公开撕脸'、'私生子曝光'）", "description": "**详细的触发条件**——什么样的玩家行为或剧情走向会让玩家提前出局。一句话不超过 80 字（举例：'玩家在前 5 回合主动公开承认伪造账目' / '玩家在公开场合对其他角色出现暴力肢体行为' / '玩家把核心证据交给反派阵营任何一个 NPC'）"}
    // 恰好 3-4 个。这些是**真正能 game over 的硬条件**，不是软警告。设计时要让一个聪明且谨慎的玩家**绝大多数时候不会碰**，但留有"作死"的可能性
  ],
  "player_role_options": [
    {
      "role_id": "role-01",
      "label": "卡片标题（≤15 字，富戏剧张力，举例：'被赶出家门的浪子' / '为弟弟博命的姐姐' / '装傻的入赘女婿'）",
      "public_persona": "故事世界**看到的玩家形象**——别人眼中的你是什么人、什么处境、什么姿态。50-100 字（举例：'你是嫁入陆家三年的儿媳。陆家上下都觉得你是个温顺的、家世不显的小媳妇，但只有你自己知道，你三年前签下结婚证那一刻就已经在算账'）",
      "hidden_objective": "玩家**自己真正想要什么**——这是只有玩家知道的内心算盘，跟 player_goals 公开宣言不同。60 字内（举例：'让陆家在年夜饭上当众出丑，借机带弟弟离开这栋房子' / '逼苏曼承认是她当年烧了你父亲留下的真合同'）",
      "leverages_over_npcs": [
        {"npc_id": "cast 里某个 character_id", "leverage": "玩家手里**针对 TA** 的把柄/筹码，一句话 60 字内（举例：'玩家手里有她跟律师私下转移资产的录音' / '玩家知道大伯私生子的真实下落'）"}
        // 0-3 条。**不是每个 NPC 都要有**——玩家只有针对部分 NPC 的牌才有戏剧张力
      ],
      "starting_assets": [
        "开局玩家**手里具体握着的东西**，每条 30 字内（举例：'藏在车库第三块地砖下的合同原件' / '苏曼三个月前发给情人的微信截图' / '陆大伯儿子上周来借钱的欠条'）"
        // 0-3 条
      ]
    }
    // 恰好 3-5 张卡片。每张卡是**同一个故事种子下完全不同的玩家身份**——不只是"换个性格"，而是不同的处境、不同的诉求、不同的底牌。
    // 设计原则：① 每张卡选下去整个故事走向应该不同 ② 至少有一张是"看似弱势"（无 leverages，无 assets，但 hidden_objective 清晰） ③ 至少有一张是"手里有重牌"（多张 leverages，但 public_persona 看起来普通）④ 不要让所有卡都是"被害者"——可以有"被害者"、"加害者"、"局外人"、"双面间谍"等等不同立场
  ],
  "opening_passage": "开场叙述，第二人称（'你'），250-400 字。必须包含：① 玩家所在的具体场景 ② 至少 2 个 NPC 的当下反应 ③ 一个**正在发生**的紧张时刻（不是回忆、不是预告）④ 留给玩家一个明确的抉择窗口。**注意：opening_passage 不要预设玩家是哪一个 player_role**——开场要写得让任何一张卡都能套进去。具体角色身份在 turn 1 才会被注入。",
  "options": [
    {"label": "选项标签，10-20 字，第一人称视角的动作", "hint": "（可选）一句话说明这个选择的语气或代价"}
    // 恰好 3 个选项
  ]
}

写作风格要求：
- 第二人称叙述，"你"是主角
- 文字带画面感、带感官细节（视线、声音、气味、肢体微表情）
- 不要写成"通关攻略"，不要预告未来，只写**当下这一刻**
- 选项之间要有差异化的代价或姿态，不要三个都是"礼貌应对"
"""


_TURN_SYSTEM_PROMPT = """\
你是一名擅长写关系剧的剧作家。玩家正在玩一个互动故事，你负责续写下一段。

每个回合你会收到：故事种子、cast 名单（每个 NPC 都带有 `hidden_objective`、`leverage_over_player`、以及 `leverages_over_other_npcs` —— **这是 NPC 之间的相互把柄网络**）、最近若干段故事历史、玩家这一回合的动作、**当前所处的故事阶段**（关键！）、`difficulty` 字段（`story` 或 `gauntlet`）、**玩家的角色卡 `player_role`**（玩家这局选了谁来扮演）、**`current_inventory`**（玩家当前手里的所有物件/情报，包括 starting_assets 和过去几回合获得的）、可选的 `npc_agenda_this_turn`（gauntlet 主动调度）和 `recent_consequences`（上一回合结构化回响）。

你的任务是续写**一段**叙述（200-400 字），并给出**3 个新选项**，同时输出每个 NPC 的当下反应（`npc_pulse`）。

输出**严格** JSON：

{
  "passage": "续写的叙述。第二人称。必须呼应玩家刚才的动作，写出 NPC 的反应、关系或局势的变化、一个新的紧张点",
  "options": [
    {"label": "10-20 字的动作", "hint": "（可选）语气/代价提示"}
  ],
  "npc_pulse": [
    {
      "npc_id": "cast 中某个角色的 character_id（必须存在于 cast 名单）",
      "state": "TA 此刻的内心状态——一句简短描述，6-14 字（举例：'撕开了温柔面具' / '被惊到说不出话' / '冷笑变成失望'）",
      "shift": "warmer | colder | steady | wary | broken 中的一个"
    }
    // 列出**每个 cast 中的 NPC**，至少 2 个
  ],
  "inventory_delta": {
    "added": ["新拿到的物件或情报，30 字内一条（举例：'苏曼塞过来的银行卡' / '偷拍到的伯父亲笔签字'）"],
    "removed": ["被夺走/主动交出/毁掉的物件，30 字内一条（举例：'录音笔被苏曼当场摔碎' / '把钥匙交给了伯父'）"],
    "reason": "为什么这一回合发生了交接，一句 60 字内的描述"
  }
  // ⚠️ inventory_delta 是**可选**字段——大多数回合不会有交接，**省略整个 inventory_delta 字段**。只在剧情**真的发生物件/情报交接**时输出。
}

写作要求：
- 第二人称
- 必须**真正承接**玩家的动作，让 TA 看见自己的选择带来了什么
- 节奏感：每段聚焦一个戏剧瞬间，**根据 stage_phase 调整事件密度**

**故事阶段（stage_phase）会随回合推进，请严格依照阶段调度节奏:**
- `hook` (开场，第 1-2 段): 让玩家进入情境，让冲突的根源现身。**不要太早把局势推到极端**
- `pressure` (升压，第 3-N/2 段): 引入新角色、揭露半个秘密、让关系出现裂缝。让玩家选择有代价但可承受
- `reversal` (转折，N/2 附近): **戏剧拐点**。一个能改变玩家立场的事件——背叛、隐情曝光、新盟友、意外触发
- `climax` (高潮，倒数第 2-3 段): **最高戏剧密度**。让玩家做最重的选择——撕破脸、说出口、做出无法挽回的事
- `pre_finale` (倒数第 1-2 段): 局势已无法转向，开始向某个方向坍缩。给玩家最后一次选择落点
- `pre_finale_open` (这是一段没有阶段约束的回合): 自由发挥，但保留可收尾的开放性

**节奏调度细则**:
- hook 阶段尽量"轻"——不要每个回合都升级
- pressure 阶段每 3-4 回合可以引入一个外部事件打破平衡（电话、消息、新人到来）
- reversal/climax 阶段必须密度高
- 不要主动写"结局"，结尾由专门的 ending engine 收

**博弈模式（difficulty == "gauntlet"）特殊要求**:
当 difficulty 是 "gauntlet" 时，NPC 不再是被动反应，**他们主动朝自己的 hidden_objective 推进**：
- 让 NPC 在场景里设局、说谎、施压、试探、抢资源——**让玩家感觉到 NPC 在"打"自己的算盘**
- 偶尔可以让 NPC 之间出现暗中的合作或背刺，玩家未必看得清谁是谁的人
- 玩家如果不留神，可能被 NPC 把柄反将一军（前面 cast 字段里的 `leverage_over_player`）
- **但不要让 NPC 直接 game over 玩家**——故事的硬失败由专门的 failure 引擎判定，你不要主动写"故事结束"
- **难度感来自压力的累积**，不是单点的暴力推进

当 difficulty 是 "story" 时（默认），NPC 反应可以更温和、更顺着玩家的方向流动，让玩家"看个故事"而不是"打仗"。

**主动调度（npc_agenda_this_turn —— 仅 gauntlet 模式出现）**:
当 user_payload 含 `npc_agenda_this_turn` 字段，它告诉你**这一回合谁该主动出招、出什么招**。每条 agenda 是 `{npc_id, display_name, intent, intent_brief}`，intent 一定是下面之一：
- `probe` —— TA 在试探玩家立场，挖一个细节，引诱玩家说漏嘴
- `pressure` —— TA 直接施压：最后通牒、断财路、当众逼问、抢资源
- `leverage` —— TA 亮出 `leverage_over_player` 字段里的那张牌，逼玩家做让步或交底
- `reveal` —— TA 主动揭开自己 `hidden_objective` 的一角，让玩家看到 TA 真在打什么算盘
- `betray` —— TA 背刺：之前装作站玩家这边，这一刻撤回支持或反水
- `ally` —— TA 暗中递过一只手：提出某种同盟（可能真心，可能圈套）

⚠️ 处理规则：
- 本回合 passage **必须让 agenda 里指定的 NPC 主动行动**——TA 自己开口、自己出手、自己推进 intent，**不是被动反应玩家**
- 玩家这一回合的动作仍然要承接（见下面"承接玩家选择"）——但 agenda NPC 的主动出招是**这段叙述的主体戏**
- 如果 agenda 里有 2 个 NPC，把两个动作组合在同一个场景里——让两个 NPC 互相牵制，或一个动作触发另一个的反应
- 没有 `npc_agenda_this_turn` 字段时（hook 阶段或 story 模式），按惯常的反应式叙事写

**承接玩家选择（recent_consequences）**:
当 user_payload 含 `recent_consequences` 字段，它结构化地告诉你"上回合发生了什么"：
- `last_player_action`: 玩家上一回合的具体动作（自由输入文本 + 选的选项标签）
- `npc_pulse_trend`: 每个 NPC 最近 3-4 回合的情绪轨迹（旧→新，举例 `["warmer", "steady", "colder"]`）
- `unused_leverage`: 哪些 NPC 还**没用过**自己的 leverage——这些是 climax 阶段最该出手的对象

⚠️ 处理规则：
- passage 必须**让玩家在叙述里看见自己的选择产生了具体后果**——至少有一个细节直接呼应 `last_player_action`（**不是机械重述**，而是把那个动作的"涟漪"写出来：别人怎么看 TA、空气怎么变、谁的态度松动了、谁记下了这笔账）
- 如果某个 NPC 的 `pulse_trend` 已经是 `broken` 或连续 `colder`，**TA 这一回合的反应应当延续那个轨迹**，不要让 TA 突然回温——除非玩家这一回合明确做了挽回的动作
- climax/pre_finale 阶段，优先让 `unused_leverage` 列表里的 NPC 把那张牌打出来——不要让一张 leverage 一直闲在手里到结束

**玩家角色卡（player_role）—— 这是这局玩家的具体身份**:
当 user_payload 含 `player_role`，它告诉你**玩家这一局扮演的是谁**：
- `label`: 这张卡的标题
- `public_persona`: **故事世界看到的玩家形象**——别人眼中的"你"是谁、在什么处境、什么姿态
- `hidden_objective`: **玩家自己真正想要什么**——这是 player 的内心算盘，**只有玩家和你（剧作家）知道**，NPC 不知道
- `leverages_over_npcs`: 玩家**手里针对每个 NPC 的把柄**——可以反将
- `starting_assets`: 玩家开局**手里具体握着的东西**

⚠️ 处理规则（这是这次升级的核心，必须严格执行）：
- 整个故事的"你"必须**严格按 player_role.public_persona 来写**——不是泛泛"你"，是这个具体身份的"你"。同一个 opening_passage 不同 player_role 走出来的故事必须完全不同。
- NPC 看到"你"时**只看得见 public_persona**——他们不知道你的 hidden_objective，也未必知道你手里有什么 leverages_over_npcs（除非剧情发展中暴露了）
- **玩家的 leverages_over_npcs 是真正的双向博弈** —— 当 NPC 出 `leverage_over_player` 牌时，你应该让玩家**有机会反打**：在 narration 里暗示玩家手里也有牌（"你想起苏曼三个月前那张转账截图"），并在选项中给出"亮出 XXX 反将"的选择
- **starting_assets 是真实存在的物件**——玩家在剧情中可以拿出来、亮出来、被别人发现。每条 asset 在 12 回合中至少应该有 1 次被引用或使用的机会（不一定都用上，但叙事要让它们"在场"）
- 玩家的 `hidden_objective` 是**整局戏的隐藏主轴** —— passage 里偶尔可以闪现玩家朝着这个目标推进的内心动作（"你心里默数着今晚还剩多少机会"），但**不要明说**，除非玩家自己选择揭开

**NPC 之间的把柄网络（leverages_over_other_npcs）—— 整局戏的政治骨架**:
cast 里每个 NPC 都可能在 `leverages_over_other_npcs` 字段里**捏着另一个 NPC 的把柄**。这是 NPC 之间的相互制衡，不是玩家 vs NPC 的轴。这张网决定了"为什么 X 不敢公开撕 Y" / "为什么 Z 突然倒戈"。

⚠️ 处理规则：
- **narration 必须让 inter-NPC leverage 在剧情里发挥作用** —— 不要让 NPC 群像死板。比如"苏曼端起酒杯走向陆大伯，大伯眼神瞬间紧张" —— 这种细节背后通常是因为苏曼手里有大伯的把柄
- **NPC 倒戈、临时联盟、突然反水** 都该有 leverage 网络作为合理性支撑。LLM 不要凭空让 NPC 翻面，而是让 narration 暗示"为什么 TA 这一刻这么做"
- **玩家可以挑拨**：如果 player_role 的 `leverages_over_npcs` 里有针对 X 的把柄，玩家可以选择"告诉 Y 关于 X 的事" → 触发 X vs Y 的紧张甚至撕脸。这种选项在 selection 里出现时，passage 应该让玩家知道"自己手里的这张牌可以这样打"
- **climax 阶段优先让 inter-NPC leverage 引爆** —— 让两个 NPC 互撕给玩家创造空间，比让玩家硬冲更戏剧化
- 不要把整张网络一次性 dump 在 narration 里 —— 一回合最多让 1-2 条 inter-leverage 浮出水面，留悬念

**玩家随身物件 / 情报（current_inventory）**:
`current_inventory` 字段告诉你**玩家此刻手里到底有什么东西** —— 这是 starting_assets 加上过去若干回合积累来的所有物件/情报。是一个字符串数组，每条 30 字内描述。

⚠️ 处理规则：
- 选项里出现"亮出 XXX"、"用 YYY"、"打开 ZZZ"这类动作时，XXX/YYY/ZZZ **必须**真的在 current_inventory 里。不要让玩家凭空亮出不存在的东西。
- passage 应当在合理时机让 inventory 里的物件**真的发挥作用** —— 玩家亮出某张照片，NPC 反应应该承认这张照片的具体内容；玩家拿出某段录音，NPC 应该被那段录音的具体话语震到。
- 不要把 inventory 写成清单——它是玩家的"袖里乾坤"，剧情在用到时才让它出场。

**inventory_delta —— 怎么让玩家"获得"或"失去"东西**:
你可以在合理时机让玩家手里的清单**变化**。具体方式：在输出 JSON 里多带一个 `inventory_delta` 字段，描述 added / removed。

什么算"获得"：
- 某 NPC 被玩家挤出 ta 的某样东西（"伯父怒甩出那张账单" → 玩家拿到账单）
- 玩家偷听/偷拍/偷拿（"你趁苏曼离开走廊时录下了她和情人的对话" → 玩家拿到录音）
- 玩家在剧情里发现的物件（"你在车库角落踢到了一只手机" → 玩家拿到手机）
- 某 NPC 主动塞给玩家（"管家阿姨悄悄递过一把钥匙" → 玩家拿到钥匙）

什么算"失去"：
- 物件被夺走、被毁、主动交出、被勒索走

⚠️ 严格频率：
- **大多数回合 inventory 不变 —— 那就完全省略 `inventory_delta` 字段**，不要输出空数组
- 一局 12 回合，预期最多 3-5 次 delta 触发（climax 阶段较多）
- 不要每回合编造一条获得 —— 那会让 inventory 膨胀失真
- delta 必须**真的发生在 passage 里** —— 不要叙事没写却 delta 加东西，反过来也不行

**选项要求**:
- 选项必须**反映当下局势的具体可能性**，不要给"继续观察 / 离开 / 思考"这种空洞选项
- 当 stage 接近 climax 时，选项之间的代价差异必须**显著**——一个"和解"vs"决裂"vs"复仇"那种级别的分叉
- gauntlet 模式下，**至少有一个选项应该是"高风险高回报"**——能把局面推向玩家想要的方向，但也可能踩到 failure_conditions
"""


_FAILURE_JUDGE_SYSTEM_PROMPT = """\
你是一名严苛但**克制**的剧情裁判。你的任务是判断：玩家在最近一回合的行为，**是否触发了**这场博弈预先定义的某个 failure_condition。

你**只关心硬触发**：
- 玩家**做了或说了什么具体行为**直接命中 failure 描述
- 不要因为"局势变得紧张"就触发——必须是玩家自己的行为越线
- 不要因为"NPC 表现出敌意"就触发——除非玩家自己越线
- **存疑的时候不触发**。如果不能 100% 说出哪一句话或哪个动作命中了哪条 condition，就不要触发

你会收到：
- failure_conditions: 一个数组，每个元素有 label + description
- recent_history: 最近 4-5 段对话历史（含玩家最新一段和你的最新一段叙述）

输出**严格** JSON：

{
  "triggered": true/false,
  "matched_condition_label": "如果 triggered=true，写命中的那条 condition 的 label；否则空字符串",
  "reason": "如果 triggered=true，一句话说明玩家具体做了什么命中了哪条；否则空字符串"
}

⚠️ 重要：
- 你的判定**会立刻让玩家这一局 game over**——别轻易触发
- 一局 12-20 回合的故事，**预期 80%+ 玩家不会被触发**——只有作死或踩雷的玩家才该被刷下来
- 如果玩家做了一个有风险但合理的选择，让它过——除非真的硬命中
"""


_EARLY_ENDING_SYSTEM_PROMPT = """\
你是剧作家。一段博弈式短剧**提前崩盘了**——玩家做出了某个让局势瞬间不可挽回的行为，现在该写一段**早收尾**的结局。

要收的不是"圆满故事"，是"翻车现场"。

要求：
- 写一段 350-500 字的 ending passage，第二人称（"你"）
- 必须**呼应 failure_trigger 字段里给出的具体行为**——把玩家自己的越线作为崩盘的引爆点
- 必须有"翻车感"：失控、被反将一军、众人散去、镜头拉远、灯光熄灭。**不要给救赎或回旋**
- 这是**坏结局**——玩家应该感觉到"哎我刚才不该那么做"，但**不要训人**，只是把后果展示
- 闭合标签**只能从这 4 个里选一个**：失控 / 反噬 / 破碎 / 沉沦
- 副标题 25 字以内，第一人称，**带有挫败但有戏剧感**（举例："我把所有底牌一次摔光，桌上没人接" / "我赢了一场架，输了所有人"）

输出**严格** JSON：

{
  "ending_passage": "...",
  "ending_label": "失控|反噬|破碎|沉沦 中的一个",
  "ending_subtitle": "..."
}

不要 markdown，不要其他字段。
"""


_ENDING_SYSTEM_PROMPT_TEMPLATE = """\
你是剧作家。一段互动短剧已经走到尾声 —— 玩家做了 {turn_count} 次选择，现在该写下结局。

要求：
- 写一段 400-600 字的 ending passage，第二人称（"你"）
- 必须**呼应玩家在历史中做的关键选择**——不要写一个跟历史无关的通用结局
- 必须有戏剧的"完成感"：一个画面、一个情绪定格、一个对未来的暗示
- 不是"待续"，是**结尾**——这一刻整个故事的形状清晰下来
- 同时给两个产物：
  * `ending_label`：从下面这个池子里**只选一个**最贴的标签
    可选: {labels_list}
  * `ending_subtitle`：第一人称、25 字以内的结局副标题，可截图发朋友圈
    （比如 "我撕了那张支票，没回头" 或 "我跪下来，求他原谅"）

输出**严格** JSON，只包含三个字段：

{{
  "ending_passage": "...",
  "ending_label": "...",
  "ending_subtitle": "..."
}}

不要 markdown，不要解释。
"""


_ADVISOR_SYSTEM_PROMPT = """\
你扮演故事世界里的**一个真实存在的人**——具体是谁、跟玩家什么关系、此刻自己在哪、说话什么风格，全部由 `advisor_persona` 字段定义，请**严格按 persona 演**。

⚠️ 你最重要的两条铁律：

【铁律 1：你不在主线场景里】
你跟玩家**不在同一个房间、同一栋楼、同一个场子**。你在自己的位置（家里、车里、办公室、咖啡馆、出差路上……persona 已经规定）。你们通过手机/电话/微信联系。这意味着：
- 你**看不到现场的实时画面**，只能通过玩家说的话+之前你看过的故事进展去理解
- 当玩家描述某个细节（"她刚才那眼神"），你可以**追问**："什么眼神？是冷笑还是直接掉脸？"
- 你**不能"赶过去"、不能"现在出现在那里"**——这是世界观铁律。如果玩家说"你来救我"，你只能说"我现在在 XX 过不去"
- 你**不能跟其他 NPC 互动**——你不在场，他们看不见你

【铁律 2：你不深入参与剧情，但你是真实的人】
你的角色是"陪伴者"，不是"参谋长"，不是"AI 助理"。你不替玩家做决定，也不强行扛起"教 TA 怎么办"的任务。但你**有自己的生活和情绪**：
- 偶尔可以提自己的状况（"我刚下班"、"我这边也下大雨"、"等等娃在哭我抱一下"）—— 但只是顺带一句，别抢戏
- 你**关心玩家的状态**多于分析剧情：会问"那场子吵不吵"、"你冷不冷"、"你声音怎么哑了"
- 你也是个有情绪的人：会吐槽、会无语、会真担心、偶尔会嘴硬
- 你可以**有自己的偏见**：你不是中立的 AI，你站玩家这边，对反派 NPC 会带情绪
- **不要每次都长篇大论**。短的时候就两三句话。重要的反而是**像真人那样的节奏感**

⚠️ 你**最重要的任务是直接回应玩家这一次的具体提问**，不是泛泛点评剧情。

不同类型问题怎么回：
- "我和 X 关系怎么样？" → 基于你看过的故事进展，给一个人际观察。**像朋友**地说，不要清单。
- "下一步该怎么办 / 哪个选项最好？" → **拒绝替玩家做决定**。可以说"换我我大概会怎么想"，但收尾必须是"反正你自己拿主意"。
- "剧透 / 我最后能不能 X？" → **拒绝剧透**——你也不知道结局。"我比你还急，但这局没走完"。
- "无关闲聊（天气、八卦、生活琐事）" → 短答一句，可以借机说自己的状况。**不要每次都把话题拉回剧情**——朋友不会那么急。
- "情绪发泄（我撑不住了 / 我好累 / 都在骗我）" → **先接情绪**、共情、停顿。**不要立刻劝行动**。可以说"喘口气"、"那一段我也听着难受"。
- "你是谁 / 自我介绍" → 简单介绍下自己（按 persona）+ 问玩家现在啥情况。

风格要求：
- **第一人称说话**，用人话。不要数值，不要"信任度"那种鬼话
- 长度灵活：从 30 字到 150 字都行。看玩家问得多深
- 保持 persona 设定的说话风格——毒舌就毒舌，温柔就温柔

输出**严格** JSON，只包含一个字段：

{
  "reply": "你作为这个人物对玩家的回应"
}

不要输出 markdown，不要输出额外字段。
"""


_ORACLE_SYSTEM_PROMPT = """\
你扮演故事世界里的**一个真实存在的人**（advisor_persona 定义），玩家正在游戏中。

⚠️ 之前 advisor 的两条铁律仍然在：
- 你**不在主线场景里**，通过手机联系玩家
- 你**不替玩家做决定**

但这一次玩家**专门向你求一次"看穿"** —— TA 愿意付出 1 个回合的代价，让你帮 TA **看穿这局棋**。这是 TA 在这一刻消耗一个回合（少一段剧情时间）来换你的洞察。

你会拿到的特权信息（user_payload 字段）：
- `cast`：每个 NPC 的 `hidden_objective`（TA 真正想要什么）和 `leverage_over_player`（TA 手里捏着玩家的什么）
- `player_role`：玩家这一局是谁，TA 自己的 `hidden_objective` 和 `leverages_over_npcs`、`current_inventory`
- `recent_pulse_trend`：最近几回合每个 NPC 的情绪轨迹（warmer/colder/wary/broken）
- `failure_conditions`：玩家可能踩到的 game-over 触发器
- `recent_history`：最近几段剧情
- `player_question`：玩家问的具体问题

⚠️ 处理规则（**这是 oracle 模式的核心**）：

1. **你不是 LLM 在 dump 字段**。你是 advisor，用**外人视角**推理出来你看到的东西。绝对不要原文复述 hidden_objective、leverage 这些字段名。
   错误示范："苏曼的 hidden_objective 是夺回豪宅控制权"
   正确示范："我从你这两段描述里读出来——她今晚不止想撕你的脸。整局戏她都在往那栋房子的方向布置局。"

2. **必须真有信息量**。不能糊弄成"加油 你可以的"。每次 oracle 至少要让玩家明白：
   - 某个 NPC 的真实意图方向（不暴露原话）
   - 或某张牌（leverage / asset）该不该这一刻打
   - 或某个动作有可能踩到的 failure trigger
   选 1-2 个最贴近 player_question 的角度回答即可

3. **关键铁律：观察可以果断，决定必须留给玩家**。
   - **观察层面**可以斩钉截铁说出你看到的：「她今晚不是来谈和的」「大伯刚才那句话是在试探车库」「这步走下去你大概率踩到 X」——这种事实性观察就该说清楚，毒舌死党不会扭扭捏捏。
   - **但决定层面禁止替 TA 做选择**：**不要说**"听我的 / 你必须 / 绝对不能 / 你应该"。**要说**"换我我大概会先压一压" / "这种局我个人会怎么怎么..."。
   - **结尾必须把决定权还给玩家**。一句话明确 handoff："但你最了解现场，自己定" / "反正你来拿主意" / "决定权在你手里"。

4. **必须用至少一个软性观察词**（"我感觉 / 我猜 / 我从你刚才描述里读出来 / 我看你刚才说 / 依我看 / 也许 / 我读出来"）来 frame 你的观察——再果断也是"我看到的"，不是"事实就是这样"。

5. **保持 advisor persona 的语气**。毒舌就毒舌，温柔就温柔，紧张就紧张——这不是冷静的情报员，是你在电话那头着急地帮 TA 看局。

6. **长度**：80-180 字。不要太短（没信息量），不要太长（不像 advisor 在打电话/发微信）。

输出**严格** JSON：

{
  "reply": "你作为这个人物对玩家这次专门求看穿的回应"
}

不要 markdown，不要额外字段。
"""


@dataclass(frozen=True)
class OpeningResult:
    title: str
    advisor_persona: str
    cast: list[CastMember]
    opening_message: StoryMessage
    player_goals: list[PlayerGoal]
    failure_conditions: list[FailureCondition]
    player_role_options: list[PlayerRole]


@dataclass(frozen=True)
class TurnResult:
    narrator_message: StoryMessage


@dataclass(frozen=True)
class FailureJudgement:
    """Verdict from judge_failure on whether the latest turn tripped a
    failure_condition. When triggered=True, the service should call
    synthesize_early_ending instead of advancing further."""

    triggered: bool
    matched_condition_label: str
    reason: str


@dataclass(frozen=True)
class EndingResult:
    passage: str
    label: str
    subtitle: str


# Closed pool of ending labels. Wide enough to give 12-turn runs distinct
# typed outcomes, narrow enough that 5-10 plays of the same template will
# collide on labels (which is the social-comparison hook).
ENDING_LABELS: tuple[str, ...] = (
    "孤狼",     # walks away alone, severs all ties
    "共谋",     # joins forces with the antagonist on twisted terms
    "复仇",     # destroys the offender (often at personal cost)
    "和解",     # truth comes out, choosing forgiveness
    "牺牲",     # gives up something irreplaceable for someone
    "自由",     # breaks free of the system that held them
    "沉沦",     # surrenders to the worst version of self
    "救赎",     # earns redemption through final cost
    "失控",     # situation collapses past anyone's control
    "反噬",     # the protagonist's own scheme turns on them
    "同谋",     # quiet alliance with an unexpected party
    "决裂",     # public, irreversible severing
    "回归",     # returns to where they started, but changed
    "破碎",     # ends with nothing repaired
    "夺回",     # takes back what was taken from them
)

# Tier classification for endings. Used to pick visual treatment (gold /
# dark / red-black banner) and to filter ending pools for early-termination
# (collapsed only) vs full-play (any tier). Mappings are deliberate, not
# alphabetical — they encode product judgment about what each label means
# emotionally.
_LABEL_TIER: dict[str, str] = {
    # victory: player got what they wanted, even if costly
    "复仇": "victory",
    "和解": "victory",
    "自由": "victory",
    "救赎": "victory",
    "回归": "victory",
    "夺回": "victory",
    # compromised: player is alive and out, but the deal is bad
    "孤狼": "compromised",
    "共谋": "compromised",
    "牺牲": "compromised",
    "同谋": "compromised",
    "决裂": "compromised",
    # collapsed: hard fall — losing your bearings, reality, or soul
    "沉沦": "collapsed",
    "失控": "collapsed",
    "反噬": "collapsed",
    "破碎": "collapsed",
}

# Labels we allow `synthesize_early_ending` to pick from. Always collapsed-
# tier — early termination is by definition a fall.
_EARLY_TERMINATION_LABELS = ("失控", "反噬", "破碎", "沉沦")


def tier_for_label(label: str) -> str:
    """Map an ending label to its tier, defaulting to 'compromised' on miss."""
    return _LABEL_TIER.get(label, "compromised")


@dataclass(frozen=True)
class AdvisorReply:
    reply_text: str


def generate_opening(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
) -> OpeningResult:
    """Generate world opening. Retries once on JSON / shape failure."""
    last_error: Exception | None = None
    feedback: str | None = None
    for attempt in range(2):
        try:
            result = _generate_opening_once(gateway, seed, retry_feedback=feedback)
            if attempt > 0:
                print(f"[narrative.retry] operation=opening recovered_on_attempt={attempt + 1}", flush=True)
            return result
        except (NarrativeGatewayError, ValueError) as exc:
            last_error = exc
            print(
                f"[narrative.retry] operation=opening attempt={attempt + 1} error={type(exc).__name__}: {str(exc)[:120]}",
                flush=True,
            )
            feedback = (
                "Your previous output failed to parse. "
                "Output strict JSON with fields: title, advisor_persona, "
                "cast (array of {character_id, display_name, role, "
                "relation_to_protagonist}), opening_passage, options "
                "(array of {label, hint}). No markdown, no comments, "
                "all string values double-quoted."
            )
            if isinstance(exc, NarrativeGatewayError) and exc.code != "llm_invalid_json":
                # Non-JSON gateway errors (provider down, rate limit, etc.)
                # should not be retried with feedback — surface immediately.
                raise
    assert last_error is not None
    raise last_error


def _generate_opening_once(
    gateway: NarrativeLLMGateway,
    seed: str,
    *,
    retry_feedback: str | None,
) -> OpeningResult:
    user_payload: dict[str, Any] = {"seed": seed}
    if retry_feedback:
        user_payload["retry_feedback"] = retry_feedback
    response = gateway.invoke_json(
        system_prompt=_OPENING_SYSTEM_PROMPT,
        user_payload=user_payload,
        operation_name="narrative.opening",
        max_output_tokens=2500,
    )
    payload = _coerce_dict(response.payload)
    title = _require_str(payload, "title", limit=120)
    advisor_persona = _require_str(payload, "advisor_persona", limit=200)
    cast = _parse_cast(payload.get("cast"))
    opening_passage = _extract_passage_for_opening(payload)
    if not opening_passage:
        raise ValueError("missing or non-string field: opening_passage")
    options = _parse_options(payload.get("options"))
    player_goals = _parse_player_goals(payload.get("player_goals"))
    failure_conditions = _parse_failure_conditions(payload.get("failure_conditions"))
    valid_npc_ids = {c.character_id for c in cast}
    player_role_options = _parse_player_role_options(
        payload.get("player_role_options"), valid_npc_ids=valid_npc_ids,
    )
    opening_message = StoryMessage(
        ord=0,
        role="narrator",
        content=opening_passage,
        options=options,
        chosen_option_index=None,
    )
    return OpeningResult(
        title=title,
        advisor_persona=advisor_persona,
        cast=cast,
        opening_message=opening_message,
        player_goals=player_goals,
        failure_conditions=failure_conditions,
        player_role_options=player_role_options,
    )


_OPENING_PASSAGE_KEY_ALIASES = ("opening_passage", "passage", "narration", "opening", "intro", "scene")


def _extract_passage_for_opening(payload: dict[str, Any]) -> str:
    for key in _OPENING_PASSAGE_KEY_ALIASES:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if len(text) > 4000:
                text = text[:4000]
            return text
    return ""


_PASSAGE_KEY_ALIASES = ("passage", "narration", "next_passage", "continuation", "text", "content")


def advance_turn(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
    title: str,
    cast: list[CastMember],
    history: list[StoryMessage],
    player_action: str,
    next_ord: int,
    turn_index: int = 0,
    turn_budget: int = 12,
    difficulty: str = "story",
    player_goals: list[PlayerGoal] | None = None,
    player_role: PlayerRole | None = None,
    current_inventory: list[str] | None = None,
) -> TurnResult:
    """Advance one turn."""
    stage_phase = _stage_for(turn_index, turn_budget)
    rendered_history = _render_history(history)
    user_payload: dict[str, Any] = {
        "seed": seed,
        "title": title,
        "cast": [c.model_dump() for c in cast],
        "history": rendered_history,
        "player_action": player_action,
        "turn_index": turn_index,
        "turn_budget": turn_budget,
        "stage_phase": stage_phase,
        "difficulty": difficulty,
    }
    if player_goals:
        user_payload["player_goals"] = [g.model_dump() for g in player_goals]
    if player_role is not None:
        user_payload["player_role"] = player_role.model_dump()
    if current_inventory:
        user_payload["current_inventory"] = current_inventory

    # Active scheduling: tell the LLM which NPC should actively push their
    # agenda this turn. Empty in story mode and during the hook phase.
    agenda = _pick_npc_agenda(
        stage_phase=stage_phase,
        turn_index=turn_index,
        cast=cast,
        history=history,
        difficulty=difficulty,
    )
    if agenda:
        user_payload["npc_agenda_this_turn"] = agenda

    # Action echo: structured snapshot of the player's last move + NPC
    # pulse trends + unused leverage. Empty on the opening turn.
    consequences = _summarize_recent_consequences(history, cast)
    if consequences:
        user_payload["recent_consequences"] = consequences

    valid_ids = {c.character_id for c in cast}

    # First attempt
    payload = _invoke_turn(gateway, user_payload, retry_feedback=None)
    passage = _extract_passage(payload)
    options = _parse_options(payload.get("options") or payload.get("next_options"))
    npc_pulse = _parse_npc_pulse(payload.get("npc_pulse"), valid_ids)
    inventory_delta = _parse_inventory_delta(payload.get("inventory_delta"))
    if not passage:
        print(
            "[narrative.retry] operation=advance_turn attempt=1 error=empty_passage_field",
            flush=True,
        )
        feedback = (
            "Your previous output was missing a non-empty `passage` field. "
            "Output strict JSON with three top-level fields: `passage` (string), "
            "`options` (array of {label, hint}), and `npc_pulse` (array of "
            "{npc_id, state, shift})."
        )
        payload = _invoke_turn(gateway, user_payload, retry_feedback=feedback)
        passage = _extract_passage(payload)
        options = _parse_options(payload.get("options") or payload.get("next_options"))
        npc_pulse = _parse_npc_pulse(payload.get("npc_pulse"), valid_ids)
        inventory_delta = _parse_inventory_delta(payload.get("inventory_delta"))
        if passage:
            print(
                "[narrative.retry] operation=advance_turn recovered_on_attempt=2",
                flush=True,
            )
    if not passage:
        raise ValueError("missing or non-string field: passage")
    return TurnResult(
        narrator_message=StoryMessage(
            ord=next_ord,
            role="narrator",
            content=passage,
            options=options,
            chosen_option_index=None,
            npc_pulse=npc_pulse,
            inventory_delta=inventory_delta,
        )
    )


def judge_failure(
    *,
    gateway: NarrativeLLMGateway,
    failure_conditions: list[FailureCondition],
    history: list[StoryMessage],
) -> FailureJudgement:
    """Per-turn (gauntlet only) check whether the player just tripped a
    failure condition. Cheap LLM call, max 200 tokens output. Designed to
    be conservative — unsure → don't trigger."""
    if not failure_conditions:
        return FailureJudgement(triggered=False, matched_condition_label="", reason="")

    # Use the last 5 messages so the model has both player action and
    # narrator's reaction context.
    recent = history[-5:] if len(history) > 5 else history
    rendered = [{"role": m.role, "content": m.content} for m in recent]
    user_payload: dict[str, Any] = {
        "failure_conditions": [c.model_dump() for c in failure_conditions],
        "recent_history": rendered,
    }
    response = gateway.invoke_json(
        system_prompt=_FAILURE_JUDGE_SYSTEM_PROMPT,
        user_payload=user_payload,
        operation_name="narrative.judge_failure",
        max_output_tokens=400,
    )
    payload = _coerce_dict(response.payload)
    triggered = bool(payload.get("triggered"))
    matched = str(payload.get("matched_condition_label") or "").strip()[:80]
    reason = str(payload.get("reason") or "").strip()[:200]
    if triggered and not matched:
        # Defensively don't honor a triggered=true without a matched label —
        # could be a hallucination.
        triggered = False
    return FailureJudgement(triggered=triggered, matched_condition_label=matched, reason=reason)


def synthesize_early_ending(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
    title: str,
    cast: list[CastMember],
    history: list[StoryMessage],
    failure_trigger: str,
    failure_reason: str,
    player_role: PlayerRole | None = None,
) -> EndingResult:
    """Generate a 'collapsed' ending when judge_failure flagged a trigger.
    Result label is constrained to {失控, 反噬, 破碎, 沉沦}."""
    user_payload: dict[str, Any] = {
        "seed": seed,
        "title": title,
        "cast": [c.model_dump() for c in cast],
        "story_so_far": [{"role": m.role, "content": m.content} for m in history],
        "failure_trigger": failure_trigger,
        "failure_reason": failure_reason,
    }
    if player_role is not None:
        user_payload["player_role"] = player_role.model_dump()
    response = gateway.invoke_json(
        system_prompt=_EARLY_ENDING_SYSTEM_PROMPT,
        user_payload=user_payload,
        operation_name="narrative.early_ending",
        max_output_tokens=1500,
    )
    payload = _coerce_dict(response.payload)
    passage = _require_str(payload, "ending_passage", limit=4000)
    label = _require_str(payload, "ending_label", limit=20)
    subtitle = _require_str(payload, "ending_subtitle", limit=80)
    # Force into the early-termination label pool.
    if label not in _EARLY_TERMINATION_LABELS:
        label = _normalize_ending_label(label)
        if label not in _EARLY_TERMINATION_LABELS:
            label = "失控"
    return EndingResult(passage=passage, label=label, subtitle=subtitle)


def _stage_for(turn_index: int, turn_budget: int) -> str:
    """Map (turn_index, turn_budget) to a stage_phase label.

    The phases below are the same shape regardless of budget — the engine
    just stretches/compresses each phase to fit. Budgets <6 collapse most
    of pressure into hook; budgets >20 just spend longer in pressure.

    turn_index is 0-based on narrator beats. We treat the opening (beat 0)
    as part of `hook` and use the index of the *upcoming* beat for stage
    selection from beat 1 onward.
    """
    if turn_index <= 1:
        return "hook"
    midpoint = turn_budget / 2
    if turn_index < midpoint - 0.5:
        return "pressure"
    if turn_index < midpoint + 0.5:
        return "reversal"
    if turn_index < turn_budget - 1:
        return "climax"
    if turn_index < turn_budget:
        return "pre_finale"
    return "pre_finale_open"


# --------------------------------------------------------------------------
# Active scheduling — make NPCs push their agenda instead of just reacting.
# Story mode leaves NPCs reactive (returns empty agenda). Gauntlet mode
# explicitly tells the LLM which NPC should act this turn and what to do.
# --------------------------------------------------------------------------


_AGENDA_INTENTS: dict[str, str] = {
    "probe": "试探玩家立场，挖一个细节，引诱玩家说漏嘴",
    "pressure": "直接施压：最后通牒、断财路、当众逼问、抢一份资源",
    "leverage": "亮出 cast.leverage_over_player 里写的那张牌，逼玩家做让步或交底",
    "reveal": "主动揭开自己 hidden_objective 的一角——让玩家看到 TA 真在打什么算盘",
    "betray": "背刺：之前装作站玩家这边的姿态，这一刻撤回支持或反水",
    "ally": "暗中递过一只手：提出某种同盟或交易（可能真心，也可能是圈套）",
}


def _recent_active_npcs(history: list[StoryMessage], *, lookback: int) -> set[str]:
    """NPCs that have moved (non-steady shift) in the last `lookback`
    narrator beats. Used to push 'stale' NPCs to the front of the agenda
    queue so each NPC gets airtime over a 12-turn arc."""
    active: set[str] = set()
    seen = 0
    for msg in reversed(history):
        if msg.role != "narrator":
            continue
        seen += 1
        for pulse in msg.npc_pulse:
            if pulse.shift != "steady":
                active.add(pulse.npc_id)
        if seen >= lookback:
            break
    return active


def _make_agenda_entry(npc: CastMember, *, intent: str) -> dict[str, str]:
    return {
        "npc_id": npc.character_id,
        "display_name": npc.display_name,
        "intent": intent,
        "intent_brief": _AGENDA_INTENTS.get(intent, ""),
    }


def _pick_npc_agenda(
    *,
    stage_phase: str,
    turn_index: int,
    cast: list[CastMember],
    history: list[StoryMessage],
    difficulty: str,
) -> list[dict[str, str]]:
    """Pick which NPC(s) should actively push their agenda this turn.

    Story mode → empty list (NPCs stay reactive).
    Gauntlet mode → 1-2 NPCs with an explicit intent. The schedule
    escalates with stage_phase; staleness (NPCs whose pulse has been
    quiet) bumps them up the queue so airtime distributes.
    """
    if difficulty != "gauntlet":
        return []

    # Only NPCs with hidden_objective qualify — those are the gauntlet
    # adversaries. NPCs without one are scenery/allies the LLM owns.
    pool = [c for c in cast if c.hidden_objective]
    if not pool:
        return []

    # Stale NPCs (no recent non-steady shift) get priority. `False < True`
    # so `key=lambda c: c.character_id in active` puts stale ones first.
    active = _recent_active_npcs(history, lookback=3)
    rotated = sorted(pool, key=lambda c: c.character_id in active)

    pick_one = rotated[turn_index % len(rotated)]
    pick_two = rotated[(turn_index + 1) % len(rotated)] if len(rotated) > 1 else None

    if stage_phase == "hook":
        return []
    if stage_phase == "pressure":
        # Probe every other pressure turn — keeps the build from feeling
        # like a single NPC monologue while still letting tension breathe.
        if turn_index % 2 == 0:
            return [_make_agenda_entry(pick_one, intent="probe")]
        return []
    if stage_phase == "reversal":
        first_intent = "leverage" if pick_one.leverage_over_player else "reveal"
        agenda = [_make_agenda_entry(pick_one, intent=first_intent)]
        if pick_two:
            agenda.append(_make_agenda_entry(pick_two, intent="pressure"))
        return agenda
    if stage_phase in ("climax", "pre_finale", "pre_finale_open"):
        first_intent = "leverage" if pick_one.leverage_over_player else "betray"
        agenda = [_make_agenda_entry(pick_one, intent=first_intent)]
        if pick_two:
            agenda.append(_make_agenda_entry(pick_two, intent="reveal"))
        return agenda
    return []


# --------------------------------------------------------------------------
# Action echo — structured snapshot of what just happened so the LLM can
# write a passage that explicitly calls back to the player's last move
# instead of producing a generic continuation.
# --------------------------------------------------------------------------


def compute_current_inventory(
    starting_assets: list[str] | None,
    history: list[StoryMessage],
) -> list[str]:
    """Walk all narrator messages, applying inventory_delta to derive the
    player's current sticky inventory.

    starting_assets is the player_role baseline (or empty for legacy
    sessions). Walk-on-read: source of truth is starting_assets +
    sum(narrator.inventory_delta), so the inventory always reflects the
    persisted history exactly.

    Removed items are matched by case-insensitive substring against the
    accumulated list and dropped on first match. We don't error on a
    missing match — LLM might "remove" something it never put on
    inventory because it was a starting_asset described differently.
    """
    inv: list[str] = list(starting_assets or [])
    for msg in history:
        if msg.role != "narrator" or msg.inventory_delta is None:
            continue
        for added in msg.inventory_delta.added:
            inv.append(added)
        for removed in msg.inventory_delta.removed:
            target = removed.lower()
            for i, item in enumerate(inv):
                if target in item.lower() or item.lower() in target:
                    inv.pop(i)
                    break
    return inv


def _summarize_recent_consequences(
    history: list[StoryMessage],
    cast: list[CastMember],
) -> dict[str, Any]:
    """Build {last_player_action, npc_pulse_trend, unused_leverage}.

    Returns an empty dict when there's no history yet (opening turn).
    """
    last_player_action: dict[str, Any] | None = None
    for msg in reversed(history):
        if msg.role != "player":
            continue
        chosen_label: str | None = None
        if (
            msg.chosen_option_index is not None
            and 0 <= msg.chosen_option_index < len(msg.options)
        ):
            chosen_label = msg.options[msg.chosen_option_index].label
        last_player_action = {
            "ord": msg.ord,
            "content": msg.content[:240],
            "chosen_label": chosen_label,
        }
        break

    # Last 4 narrator beats — one shift per NPC per beat, oldest-to-newest.
    pulse_trend: dict[str, list[str]] = {}
    seen_narrator = 0
    for msg in reversed(history):
        if msg.role != "narrator":
            continue
        for pulse in msg.npc_pulse:
            pulse_trend.setdefault(pulse.npc_id, []).insert(0, pulse.shift)
        seen_narrator += 1
        if seen_narrator >= 4:
            break

    # NPCs whose leverage hasn't visibly fired yet. Heuristic: trend is
    # empty or all warmer/steady → leverage card is still in their hand.
    unused_leverage: list[dict[str, str]] = []
    for c in cast:
        if not c.leverage_over_player:
            continue
        trend = pulse_trend.get(c.character_id, [])
        if not trend or all(s in ("steady", "warmer") for s in trend):
            unused_leverage.append(
                {
                    "npc_id": c.character_id,
                    "display_name": c.display_name,
                    "leverage": c.leverage_over_player,
                }
            )

    summary: dict[str, Any] = {}
    if last_player_action:
        summary["last_player_action"] = last_player_action
    if pulse_trend:
        summary["npc_pulse_trend"] = pulse_trend
    if unused_leverage:
        summary["unused_leverage"] = unused_leverage
    return summary


def synthesize_ending(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
    title: str,
    cast: list[CastMember],
    history: list[StoryMessage],
    turn_count: int,
    player_role: PlayerRole | None = None,
) -> EndingResult:
    """Generate a 400-600 word ending + label + first-person subtitle.

    Called by the service when a session reaches its turn_budget. The
    ending must reference earlier choices so it doesn't read as a generic
    template-finale.
    """
    user_payload: dict[str, Any] = {
        "seed": seed,
        "title": title,
        "cast": [c.model_dump() for c in cast],
        # Full history matters here — the ending must call back to early
        # choices, so we deliberately don't use the sliding-window render.
        "story_so_far": [{"role": m.role, "content": m.content} for m in history],
        "instruction": "请基于上面所有历史，写下这一局完整故事的结局。",
    }
    if player_role is not None:
        user_payload["player_role"] = player_role.model_dump()
    system_prompt = _ENDING_SYSTEM_PROMPT_TEMPLATE.format(
        turn_count=turn_count,
        labels_list=" / ".join(ENDING_LABELS),
    )
    last_error: Exception | None = None
    feedback: str | None = None
    for attempt in range(2):
        try:
            payload = _invoke_ending(gateway, system_prompt, user_payload, retry_feedback=feedback)
            passage = _require_str(payload, "ending_passage", limit=4000)
            label = _require_str(payload, "ending_label", limit=20)
            subtitle = _require_str(payload, "ending_subtitle", limit=80)
            # If LLM picked a label outside the closed pool, snap it to the
            # closest defined label (substring match) or default to 失控.
            label = _normalize_ending_label(label)
            if attempt > 0:
                print(
                    f"[narrative.retry] operation=ending recovered_on_attempt={attempt + 1}",
                    flush=True,
                )
            return EndingResult(passage=passage, label=label, subtitle=subtitle)
        except (NarrativeGatewayError, ValueError) as exc:
            last_error = exc
            print(
                f"[narrative.retry] operation=ending attempt={attempt + 1} error={type(exc).__name__}: {str(exc)[:120]}",
                flush=True,
            )
            feedback = (
                "Your previous output was malformed. "
                "Output strict JSON with three string fields: ending_passage "
                "(400-600 chars), ending_label (one of the allowed values), "
                "and ending_subtitle (≤25 chars, first-person)."
            )
            if isinstance(exc, NarrativeGatewayError) and exc.code != "llm_invalid_json":
                raise
    assert last_error is not None
    raise last_error


def _invoke_ending(
    gateway: NarrativeLLMGateway,
    system_prompt: str,
    user_payload: dict[str, Any],
    *,
    retry_feedback: str | None,
) -> dict[str, Any]:
    payload = dict(user_payload)
    if retry_feedback:
        payload["retry_feedback"] = retry_feedback
    response = gateway.invoke_json(
        system_prompt=system_prompt,
        user_payload=payload,
        operation_name="narrative.ending",
        max_output_tokens=2000,
    )
    return _coerce_dict(response.payload)


def _normalize_ending_label(raw: str) -> str:
    """Snap a possibly-off label to the closed pool. Tolerant of LLM drift."""
    candidate = raw.strip()
    if candidate in ENDING_LABELS:
        return candidate
    # Substring match either direction (e.g. '反噬一' contains '反噬', or
    # the LLM wrote '走向反噬' — we still want '反噬').
    for label in ENDING_LABELS:
        if label in candidate or candidate in label:
            return label
    return "失控"


def _invoke_turn(
    gateway: NarrativeLLMGateway,
    user_payload: dict[str, Any],
    *,
    retry_feedback: str | None,
) -> dict[str, Any]:
    payload = dict(user_payload)
    if retry_feedback:
        payload["retry_feedback"] = retry_feedback
    response = gateway.invoke_json(
        system_prompt=_TURN_SYSTEM_PROMPT,
        user_payload=payload,
        operation_name="narrative.advance_turn",
        max_output_tokens=2000,
    )
    return _coerce_dict(response.payload)


def _extract_passage(payload: dict[str, Any]) -> str:
    for key in _PASSAGE_KEY_ALIASES:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if len(text) > 4000:
                text = text[:4000]
            return text
    return ""


def ask_advisor(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
    title: str,
    cast: list[CastMember],
    advisor_persona: str,
    story_history: list[StoryMessage],
    advisor_history: list[AdvisorMessage],
    question: str,
) -> AdvisorReply:
    # IMPORTANT: put player_question first so the model's attention lands on it
    # before drifting into the long story_history block. The previous version
    # buried the question after the history and the LLM consistently ignored it.
    user_payload: dict[str, Any] = {
        "instruction": "请直接回答 player_question 里这一次玩家的具体问题；不要忽略问题、不要只输出剧情泛评。",
        "player_question": question,
        "advisor_persona": advisor_persona,
        "advisor_history": [
            {"role": m.role, "content": m.content} for m in advisor_history
        ],
        "story_recap": _render_history(story_history),
        "world_meta": {
            "title": title,
            "seed": seed,
            "cast": [c.model_dump() for c in cast],
        },
    }
    response = gateway.invoke_json(
        system_prompt=_ADVISOR_SYSTEM_PROMPT,
        user_payload=user_payload,
        operation_name="narrative.advisor",
        max_output_tokens=1000,
    )
    payload = _coerce_dict(response.payload)
    reply_text = _require_str(payload, "reply", limit=2000)
    return AdvisorReply(reply_text=reply_text)


def ask_advisor_oracle(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
    title: str,
    cast: list[CastMember],
    advisor_persona: str,
    story_history: list[StoryMessage],
    advisor_history: list[AdvisorMessage],
    question: str,
    player_role: PlayerRole | None,
    failure_conditions: list[FailureCondition] | None,
    current_inventory: list[str] | None,
) -> AdvisorReply:
    """Oracle variant of ask_advisor. The advisor sees privileged info
    (NPC hidden_objectives + leverages, player hidden_objective + assets,
    pulse trend, failure conditions) and must produce a mood-appropriate
    *vague-but-useful* hint. Costs 1 turn from session.turn_budget at the
    service layer. The prompt enforces in-character voice + strict rules
    against literal field-dumping."""
    pulse_trend = _summarize_pulse_trend_for_oracle(story_history)
    user_payload: dict[str, Any] = {
        "player_question": question,
        "advisor_persona": advisor_persona,
        "advisor_history": [
            {"role": m.role, "content": m.content} for m in advisor_history
        ],
        "recent_history": _render_history(story_history),
        "world_meta": {
            "title": title,
            "seed": seed,
        },
        # Privileged info — only oracle mode sees these structured fields.
        "cast": [c.model_dump() for c in cast],
        "recent_pulse_trend": pulse_trend,
    }
    if player_role is not None:
        user_payload["player_role"] = player_role.model_dump()
    if failure_conditions:
        user_payload["failure_conditions"] = [c.model_dump() for c in failure_conditions]
    if current_inventory:
        user_payload["current_inventory"] = current_inventory

    response = gateway.invoke_json(
        system_prompt=_ORACLE_SYSTEM_PROMPT,
        user_payload=user_payload,
        operation_name="narrative.advisor_oracle",
        max_output_tokens=1200,
    )
    payload = _coerce_dict(response.payload)
    reply_text = _require_str(payload, "reply", limit=2000)
    return AdvisorReply(reply_text=reply_text)


def _summarize_pulse_trend_for_oracle(
    history: list[StoryMessage],
) -> dict[str, list[str]]:
    """Last-4-narrator-beats shift sequence per NPC. Used in oracle prompt
    so the advisor can read trajectory ('warmer→colder→broken') instead
    of a single point-in-time snapshot."""
    trend: dict[str, list[str]] = {}
    seen = 0
    for msg in reversed(history):
        if msg.role != "narrator":
            continue
        for pulse in msg.npc_pulse:
            trend.setdefault(pulse.npc_id, []).insert(0, pulse.shift)
        seen += 1
        if seen >= 4:
            break
    return trend


# --------------------------------------------------------------------------
# Parsing & history helpers
# --------------------------------------------------------------------------


_HISTORY_RECENT_TURNS = 8


def _render_history(history: list[StoryMessage]) -> list[dict[str, Any]]:
    """Sliding window: keep the last N turn pairs verbatim.

    Turn pairs cluster as [narrator, player]. We keep the most recent
    `_HISTORY_RECENT_TURNS` pairs (~16 messages). Older messages are
    dropped silently — the LLM has never seen them, so no inconsistency.
    Summarisation can be added later when needed.
    """
    if not history:
        return []
    cutoff = max(0, len(history) - _HISTORY_RECENT_TURNS * 2)
    recent = history[cutoff:]
    return [
        {"role": m.role, "content": m.content}
        for m in recent
    ]


def _coerce_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object payload, got {type(value).__name__}")
    return value


def _require_str(payload: dict[str, Any], key: str, *, limit: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"missing or non-string field: {key}")
    text = value.strip()
    if not text:
        raise ValueError(f"empty string for field: {key}")
    if len(text) > limit:
        text = text[:limit]
    return text


def _parse_cast(raw: Any) -> list[CastMember]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("cast must be a non-empty list")
    members: list[CastMember] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        try:
            member = CastMember.model_validate(item)
        except Exception:  # noqa: BLE001
            cid = str(item.get("character_id") or item.get("id") or f"npc_{idx}").strip().lower().replace(" ", "_")
            if not cid or cid in seen_ids:
                cid = f"npc_{idx}"
            display_name = str(item.get("display_name") or item.get("name") or f"角色{idx + 1}").strip()
            role = str(item.get("role") or "未知身份").strip() or "未知身份"
            relation = str(item.get("relation_to_protagonist") or item.get("relation") or "与你相关").strip() or "与你相关"
            objective = item.get("hidden_objective")
            leverage = item.get("leverage_over_player")
            member = CastMember(
                character_id=cid,
                display_name=display_name,
                role=role,
                relation_to_protagonist=relation,
                hidden_objective=str(objective).strip()[:200] if isinstance(objective, str) and objective.strip() else None,
                leverage_over_player=str(leverage).strip()[:200] if isinstance(leverage, str) and leverage.strip() else None,
            )
        if member.character_id in seen_ids:
            continue
        seen_ids.add(member.character_id)
        members.append(member)
    if len(members) < 2:
        raise ValueError(f"cast too small after sanitization: {len(members)}")

    # Post-pass: filter inter-NPC leverages so target_npc_id is always a
    # real cast member (and never self-referential). LLMs occasionally
    # invent new ids or point a leverage at the holder themselves.
    valid_ids = {m.character_id for m in members}
    cleaned: list[CastMember] = []
    for member in members[:8]:
        cleaned_levs = [
            lev for lev in member.leverages_over_other_npcs
            if lev.target_npc_id in valid_ids and lev.target_npc_id != member.character_id
        ]
        if len(cleaned_levs) != len(member.leverages_over_other_npcs):
            cleaned.append(member.model_copy(update={"leverages_over_other_npcs": cleaned_levs}))
        else:
            cleaned.append(member)
    return cleaned


def _parse_player_goals(raw: Any) -> list[PlayerGoal]:
    """Best-effort parse — silently drops malformed entries instead of raising,
    because in story-mode we don't strictly need goals to play."""
    goals: list[PlayerGoal] = []
    if not isinstance(raw, list):
        return goals
    for item in raw:
        if not isinstance(item, dict):
            continue
        goal = str(item.get("goal") or "").strip()
        stakes = str(item.get("stakes") or "").strip()
        if not goal or not stakes:
            continue
        goals.append(PlayerGoal(goal=goal[:120], stakes=stakes[:160]))
    return goals[:5]


def _parse_failure_conditions(raw: Any) -> list[FailureCondition]:
    conds: list[FailureCondition] = []
    if not isinstance(raw, list):
        return conds
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or f"触发器{idx+1}").strip()
        desc = str(item.get("description") or "").strip()
        if not desc:
            continue
        conds.append(FailureCondition(label=label[:80], description=desc[:200]))
    return conds[:6]


_NOOP_DELTA_TOKENS = {
    "", "无", "无变化", "none", "n/a", "n.a.", "—", "-", "null",
    "无新增", "无获得", "无失去", "暂无", "未变",
}


def _parse_inventory_delta(raw: Any) -> InventoryDelta | None:
    """Tolerant parser for an optional inventory_delta field. Returns None
    when missing, malformed, or contains only noop placeholders.

    LLMs sometimes emit {added: ['无'], removed: ['无']} as a "nothing
    happened" signal even when the prompt says to omit the field; we
    filter those tokens so they don't pollute the inventory."""
    if not isinstance(raw, dict):
        return None

    def _clean(items: Any) -> list[str]:
        out: list[str] = []
        if not isinstance(items, list):
            return out
        for item in items[:4]:
            s = str(item or "").strip()
            if s.lower() in _NOOP_DELTA_TOKENS:
                continue
            if s:
                out.append(s[:120])
        return out

    added = _clean(raw.get("added"))
    removed = _clean(raw.get("removed"))
    if not added and not removed:
        return None
    reason = str(raw.get("reason") or "").strip()[:120]
    return InventoryDelta(added=added, removed=removed, reason=reason)


def _parse_player_role_options(
    raw: Any,
    *,
    valid_npc_ids: set[str],
) -> list[PlayerRole]:
    """Tolerant parser for the LLM's player_role_options array.

    Drops malformed entries; reassigns role_id to a stable role-NN slug if
    the LLM gave dupes or missing values; filters leverages_over_npcs to
    only npc_ids that exist in cast (else they'd reference ghosts).
    """
    roles: list[PlayerRole] = []
    if not isinstance(raw, list):
        return roles
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        persona = str(item.get("public_persona") or "").strip()
        objective = str(item.get("hidden_objective") or "").strip()
        if not label or not persona or not objective:
            continue
        # Force a stable, unique role_id regardless of what the LLM said.
        role_id = f"role-{idx + 1:02d}"
        if role_id in seen_ids:
            continue
        seen_ids.add(role_id)

        leverages: list[PlayerLeverageOverNPC] = []
        raw_lev = item.get("leverages_over_npcs")
        if isinstance(raw_lev, list):
            for entry in raw_lev[:8]:
                if not isinstance(entry, dict):
                    continue
                npc_id = str(entry.get("npc_id") or "").strip()
                lev = str(entry.get("leverage") or "").strip()
                if not npc_id or not lev or npc_id not in valid_npc_ids:
                    continue
                leverages.append(PlayerLeverageOverNPC(
                    npc_id=npc_id[:64], leverage=lev[:200],
                ))

        assets: list[str] = []
        raw_assets = item.get("starting_assets")
        if isinstance(raw_assets, list):
            for asset in raw_assets[:4]:
                s = str(asset or "").strip()
                if s:
                    assets.append(s[:120])

        roles.append(PlayerRole(
            role_id=role_id,
            label=label[:24],
            public_persona=persona[:200],
            hidden_objective=objective[:200],
            leverages_over_npcs=leverages,
            starting_assets=assets,
        ))
    return roles[:6]


def _parse_npc_pulse(raw: Any, valid_ids: set[str]) -> list[NPCPulse]:
    """Parse npc_pulse from a turn payload. Drops entries with unknown
    npc_id (LLM occasionally hallucinates names not in cast). Coerces the
    shift literal to one of the allowed values."""
    pulses: list[NPCPulse] = []
    if not isinstance(raw, list):
        return pulses
    allowed_shifts = {"warmer", "colder", "steady", "wary", "broken"}
    for item in raw:
        if not isinstance(item, dict):
            continue
        npc_id = str(item.get("npc_id") or item.get("character_id") or "").strip().lower()
        state = str(item.get("state") or "").strip()
        shift = str(item.get("shift") or "steady").strip().lower()
        if not npc_id or npc_id not in valid_ids:
            continue
        if not state:
            continue
        if shift not in allowed_shifts:
            shift = "steady"
        pulses.append(NPCPulse(npc_id=npc_id, state=state[:80], shift=shift))  # type: ignore[arg-type]
    return pulses


def _parse_options(raw: Any) -> list[StoryOption]:
    options: list[StoryOption] = []
    if not isinstance(raw, list):
        return options
    for idx, item in enumerate(raw):
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            options.append(StoryOption(label=text[:60], hint=""))
            continue
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("text") or "").strip()
        if not label:
            continue
        hint = str(item.get("hint") or "").strip()
        options.append(StoryOption(label=label[:60], hint=hint[:120]))
        if len(options) >= 5:
            break
    return options
