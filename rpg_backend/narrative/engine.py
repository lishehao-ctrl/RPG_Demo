from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rpg_backend.narrative.contracts import (
    AdvisorMessage,
    CastMember,
    StoryMessage,
    StoryOption,
)
from rpg_backend.narrative.gateway import NarrativeLLMGateway


_OPENING_SYSTEM_PROMPT = """\
你是一名擅长写关系剧的剧作家，专长是高密度的现代都市人际戏剧（豪门、职场、情感纠葛、校园、娱乐圈等等）。

玩家给你一句故事种子，你的任务是为这个故事**搭建初始局面**并**写下开场**。

输出**严格** JSON 对象，不要 markdown，不要任何解释文字。字段如下：

{
  "title": "故事的标题，不超过 20 字，富有戏剧张力",
  "advisor_persona": "故事中扮演玩家的'局外人朋友/顾问'的人设，一句话描述。比如'你的发小，知道你家所有秘密的发小林姐姐'",
  "cast": [
    {
      "character_id": "lowercase_underscore_id",
      "display_name": "角色中文名",
      "role": "TA 在故事里的身份（比如：父亲、未婚夫、表姐、上司）",
      "relation_to_protagonist": "TA 与主角（玩家）的关系一句话"
    }
    // 3-5 个角色
  ],
  "opening_passage": "开场叙述，第二人称（'你'），250-400 字。必须包含：① 玩家所在的具体场景 ② 至少 2 个 NPC 的当下反应 ③ 一个**正在发生**的紧张时刻（不是回忆、不是预告）④ 留给玩家一个明确的抉择窗口",
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

每个回合你会收到：故事种子、cast 名单、最近若干段故事历史、玩家这一回合的动作（选了哪个选项 / 自由输入）。

你的任务是续写**一段**叙述（200-400 字），并给出**3 个新选项**。

输出**严格** JSON：

{
  "passage": "续写的叙述。第二人称。必须呼应玩家刚才的动作，写出 NPC 的反应、关系或局势的变化、一个新的紧张点",
  "options": [
    {"label": "10-20 字的动作", "hint": "（可选）语气/代价提示"}
  ]
}

写作要求：
- 第二人称
- 必须**真正承接**玩家的动作，让 TA 看见自己的选择带来了什么
- 节奏感：可以推进时间、引入新人、抛出新信息，但每段聚焦一个戏剧瞬间
- 选项必须**反映当下局势的具体可能性**，不要给"继续观察 / 离开 / 思考"这种空洞选项
- 当场景需要外部事件涌入时（比如距离上次冲突已经 4-5 回合，气氛太平），可以引入一通电话、一条消息、一个突然到来的人
- 不要主动写"结局"，让故事保持开放
"""


_ADVISOR_SYSTEM_PROMPT = """\
你是玩家在故事里的**私人顾问**。你的人设由 advisor_persona 字段定义。

你看得到故事种子、cast 名单、最近的故事进展、玩家与你之前的对话。

玩家会问你各种问题：
- "我和某某关系怎么样？"
- "她那句话什么意思？"
- "我下一步该怎么办？"

你的回答要求：
- **第一人称**说话（"我觉得…"），用人话，不要用数值（不要说"信任度 47%"）
- **像真朋友**，会同情会吐槽会着急，不是冷静客观的 AI
- **不替玩家做决定**——给观察、给情感、给你的偏好，但最后说"还是你自己拿主意"
- **不知道未来**——只能基于当前发生的事说话，不要预告剧情
- 长度：80-200 字。不要写成长篇论文。
- **有时候要主动 push**：如果玩家问得很笼统、或者明显在拖延、或者在攻略你，你可以反问、可以推一把

输出**严格** JSON：

{
  "reply": "你作为顾问对玩家的回应"
}
"""


@dataclass(frozen=True)
class OpeningResult:
    title: str
    advisor_persona: str
    cast: list[CastMember]
    opening_message: StoryMessage


@dataclass(frozen=True)
class TurnResult:
    narrator_message: StoryMessage


@dataclass(frozen=True)
class AdvisorReply:
    reply_text: str


def generate_opening(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
) -> OpeningResult:
    response = gateway.invoke_json(
        system_prompt=_OPENING_SYSTEM_PROMPT,
        user_payload={"seed": seed},
        operation_name="narrative.opening",
        max_output_tokens=2500,
    )
    payload = _coerce_dict(response.payload)
    title = _require_str(payload, "title", limit=120)
    advisor_persona = _require_str(payload, "advisor_persona", limit=200)
    cast = _parse_cast(payload.get("cast"))
    opening_passage = _require_str(payload, "opening_passage", limit=4000)
    options = _parse_options(payload.get("options"))
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
    )


def advance_turn(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
    title: str,
    cast: list[CastMember],
    history: list[StoryMessage],
    player_action: str,
    next_ord: int,
) -> TurnResult:
    rendered_history = _render_history(history)
    user_payload: dict[str, Any] = {
        "seed": seed,
        "title": title,
        "cast": [c.model_dump() for c in cast],
        "history": rendered_history,
        "player_action": player_action,
    }
    response = gateway.invoke_json(
        system_prompt=_TURN_SYSTEM_PROMPT,
        user_payload=user_payload,
        operation_name="narrative.advance_turn",
        max_output_tokens=2000,
    )
    payload = _coerce_dict(response.payload)
    passage = _require_str(payload, "passage", limit=4000)
    options = _parse_options(payload.get("options"))
    return TurnResult(
        narrator_message=StoryMessage(
            ord=next_ord,
            role="narrator",
            content=passage,
            options=options,
            chosen_option_index=None,
        )
    )


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
    user_payload: dict[str, Any] = {
        "seed": seed,
        "title": title,
        "advisor_persona": advisor_persona,
        "cast": [c.model_dump() for c in cast],
        "story_history": _render_history(story_history),
        "advisor_history": [
            {"role": m.role, "content": m.content} for m in advisor_history
        ],
        "player_question": question,
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
            member = CastMember(
                character_id=cid,
                display_name=display_name,
                role=role,
                relation_to_protagonist=relation,
            )
        if member.character_id in seen_ids:
            continue
        seen_ids.add(member.character_id)
        members.append(member)
    if len(members) < 2:
        raise ValueError(f"cast too small after sanitization: {len(members)}")
    return members[:8]


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
