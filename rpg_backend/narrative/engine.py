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
  "advisor_persona": "故事世界里的一个**真实存在的人**，TA 通过手机/电话/微信跟玩家联系，不在主线场景里。必须**清晰、紧凑**地包含四件事：① TA 是谁 + 跟玩家什么关系（举例：'林姐姐——大学一起睡上下铺的死党，现在做投行 VP'）② TA **此刻自己在哪、在做什么**（必须跟主角的场景物理分离，举例：'刚加完班，在停车场坐车里抽烟' / '在虹桥机场候机' / '在家给娃喂夜奶'）③ TA 跟玩家的相处姿态（举例：'毒舌但护短' / '冷静直给从不空话'）④ TA 此刻能怎样跟玩家联系（电话/微信/语音）。整段控制在 60-90 字，**不要把 TA 放在玩家的同一个房间或同一栋楼**，否则就破坏了'局外人'的安全感。",
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

每个回合你会收到：故事种子、cast 名单、最近若干段故事历史、玩家这一回合的动作、**当前所处的故事阶段**（关键！）。

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

**选项要求**:
- 选项必须**反映当下局势的具体可能性**，不要给"继续观察 / 离开 / 思考"这种空洞选项
- 当 stage 接近 climax 时，选项之间的代价差异必须**显著**——一个"和解"vs"决裂"vs"复仇"那种级别的分叉
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
) -> TurnResult:
    """Advance one turn.

    `turn_index` is 0-based: this is the index of the new narrator beat
    we're about to write (so on the very first advance, turn_index = 1
    because the opening was beat 0).

    `turn_budget` is the planned total story length in narrator beats
    (default 12 for the short-drama format). The engine derives a
    stage_phase from (turn_index, turn_budget) and injects it into the
    prompt so the model paces escalation correctly.
    """
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
    }

    # First attempt
    payload = _invoke_turn(gateway, user_payload, retry_feedback=None)
    passage = _extract_passage(payload)
    options = _parse_options(payload.get("options") or payload.get("next_options"))
    if not passage:
        print(
            "[narrative.retry] operation=advance_turn attempt=1 error=empty_passage_field",
            flush=True,
        )
        # Retry once with explicit feedback. Free-input turns occasionally trip
        # the model into outputting wrong field names or empty strings; one
        # corrective retry catches almost all of these.
        feedback = (
            "Your previous output was missing a non-empty `passage` field. "
            "Output strict JSON with two top-level fields: `passage` (string) "
            "and `options` (array of {label, hint})."
        )
        payload = _invoke_turn(gateway, user_payload, retry_feedback=feedback)
        passage = _extract_passage(payload)
        options = _parse_options(payload.get("options") or payload.get("next_options"))
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
        )
    )


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


def synthesize_ending(
    *,
    gateway: NarrativeLLMGateway,
    seed: str,
    title: str,
    cast: list[CastMember],
    history: list[StoryMessage],
    turn_count: int,
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
