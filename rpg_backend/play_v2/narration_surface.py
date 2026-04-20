from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from typing import Iterable, Literal

from rpg_backend.author.normalize import trim_text
from rpg_backend.author_v2.contracts import VoiceAtom
from rpg_backend.play_v2.narration_frames import NpcReactionBeat, NarrationRenderSeed, SupportingReactionBeat, ToneExampleStyleHints
from rpg_backend.play_v2.narration_variants import (
    DEFAULT_HARD_BLOCK_TERMS,
    NarrationVariantSampler,
    canonicalize_phrase,
    pattern_fingerprint,
)
from rpg_backend.play_v2.shell_propagation import edge_signal_clause, get_shell_edge


_ACTIVE_VARIANT_SAMPLER: ContextVar[NarrationVariantSampler | None] = ContextVar(
    "_ACTIVE_VARIANT_SAMPLER",
    default=None,
)


def _pick(options: tuple[str, ...], *, seed: NarrationRenderSeed, slot_name: str) -> str:
    sampler = _ACTIVE_VARIANT_SAMPLER.get()
    if sampler is not None:
        return sampler.sample_phrase(options, fallback=options[0] if options else "")
    digest = hashlib.sha1(
        f"{slot_name}|{seed.character_id}|{seed.turn_index}|{seed.segment_role}|{seed.move_family}|{seed.scene_frame}".encode("utf-8")
    ).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _contains_forbidden(text: str, forbidden_raw_phrases: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(str(phrase).strip() and str(phrase).casefold() in lowered for phrase in forbidden_raw_phrases)


def _join_fragments(*parts: str | None) -> str:
    return "".join(part.strip() for part in parts if part and part.strip())


@dataclass(frozen=True)
class _CausalClauseSkeleton:
    reason_clause: str
    signal_clause: str
    cost_clause: str


def _has_cause(reaction: SupportingReactionBeat, *tags: str) -> bool:
    return any(tag in reaction.cause_tags for tag in tags)


def _style_anchor(
    style_hints: ToneExampleStyleHints | None,
    *preferred: str,
    layer: Literal["primary", "supporting", "fallout"] = "fallout",
) -> str | None:
    if style_hints is None:
        return None
    if layer == "primary":
        source_tokens = style_hints.primary_anchor_tokens or style_hints.anchor_tokens
    elif layer == "supporting":
        source_tokens = style_hints.supporting_anchor_tokens or style_hints.anchor_tokens
    else:
        source_tokens = style_hints.fallout_anchor_tokens or style_hints.anchor_tokens
    for token in preferred:
        if token in source_tokens:
            return token
    return source_tokens[0] if source_tokens else None


def _is_expository_hint(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    return stripped.startswith(("你一", "你这一下", "你护住", "你替", "你把", "这一步已经", "这一下已经")) or "等于把" in stripped


def _ensure_key_segment_shell_anchor(
    *,
    text: str,
    beat: NpcReactionBeat,
    style_hints: ToneExampleStyleHints | None,
    segment_role: str | None,
    layer: Literal["supporting", "fallout"],
) -> str:
    if segment_role not in {"reveal", "terminal"}:
        return text
    if beat.shell_id == "entertainment_scandal":
        anchors = ("镜头", "热搜", "公关", "切割")
        if any(token in text for token in anchors):
            return text
        anchor = _style_anchor(style_hints, *anchors, layer=layer) or "镜头"
        return trim_text(f"{text}{anchor}已经先把这一下记进外面的风向了。", 520)
    if beat.shell_id == "campus_romance":
        anchors = ("台下", "评审", "名额", "社团", "熟人", "站队")
        if any(token in text for token in anchors):
            return text
        anchor = _style_anchor(style_hints, *anchors, layer=layer) or "台下"
        return trim_text(f"{text}{anchor}已经先把这一下记成公开站队了。", 520)
    return text


def _aftershock_suffix(beat: NpcReactionBeat, anchor: str | None) -> str | None:
    if not anchor:
        return None
    if beat.shell_id == "entertainment_scandal":
        if anchor in {"镜头", "公屏", "热搜"}:
            return f"{anchor}已经先把停顿、变脸和那一下失手吃满了。"
        return "场边那圈人已经顺着这个口子开始往外递版本了。"
    if beat.shell_id == "campus_romance":
        if anchor in {"台下", "评审", "名额"}:
            return f"{anchor}那边先静了一拍，接着眼色一轮轮传开。"
        return f"{anchor}那边的人已经开始默默换边了。"
    return None


def _strategic_intent_line(reaction: SupportingReactionBeat, *, primary_name: str) -> str | None:
    intent = reaction.strategic_intent
    if intent is None:
        return None
    name = reaction.beat.target_name
    if intent.public_survival_mode == "self_preserve" and _has_cause(reaction, "covering_self", "public_hit"):
        return f"{name}这会儿先护的是自己的退路，不是{primary_name}。"
    if intent.public_survival_mode == "cut_off" and _has_cause(reaction, "cutting_others", "sacrifice_window"):
        return f"{name}明显已经在替后面的切割找落点，救场根本不在她考虑里。"
    if intent.public_survival_mode == "claim_narrative" and _has_cause(reaction, "camera_pressure", "covering_self"):
        return f"{name}这会儿最想抢的是解释权，像怕版本一旦落到别人手里就再也回不来。"
    if intent.public_survival_mode == "align_early" and _has_cause(reaction, "forced_alignment", "saw_player_side"):
        return f"{name}不想再拖，明显是在挑一个最早站边也最不吃亏的位置。"
    if intent.debt_memory_bias in {"scorekeeping", "late_payback"} and _has_cause(reaction, "debt_due", "kept_score"):
        return f"{name}这一下带着记账的旧气，像终于等到能把那笔账翻回台面的时机。"
    return None


def _cost_subject_main_clause(style_hints: ToneExampleStyleHints | None) -> str | None:
    if style_hints is None or not style_hints.force_main_clause_cost_subject:
        return None
    payer = (style_hints.cost_subject_payer_name or "当事人A").strip() or "当事人A"
    beneficiary = (style_hints.cost_subject_beneficiary_name or "当事人B").strip() or "当事人B"
    if style_hints.cost_subject_focus == "who_takes_blame":
        if payer == beneficiary:
            return trim_text(f"这拍先把锅定下来：{payer}得先扛。", 180)
        return trim_text(f"这拍先把锅定下来：{payer}和{beneficiary}里，谁都躲不过接锅。", 180)
    if style_hints.cost_subject_focus == "who_gets_chased":
        if payer == beneficiary:
            return trim_text(f"这拍先把追责线拎清：{payer}会先被追着清算。", 180)
        return trim_text(f"这拍先把追责线拎清：{beneficiary}和{payer}里，有人要先被追着清算。", 180)
    if payer == beneficiary:
        return trim_text(f"这拍先把账算清：{payer}得先付账。", 180)
    return trim_text(f"这拍先把账算清：{payer}先付账，{beneficiary}先拿缓冲。", 180)


_SHELL_ROLE_LEXICON: dict[str, tuple[str, ...]] = {
    "wealth_families": ("主桌", "顺位", "家宴", "继承"),
    "office_power": ("会议桌", "席位", "口风", "背锅"),
    "entertainment_scandal": ("镜头", "热搜", "公关", "切割"),
    "campus_romance": ("台下", "评审", "名额", "社团"),
    "urban_supernatural": ("夜色", "旧债", "契约", "异象"),
}


def _normalized_lexicon_token(raw: str | None) -> str | None:
    token = canonicalize_phrase(raw)
    if not token:
        return None
    return trim_text(token, 14)


def _role_lexicon_line(beat: NpcReactionBeat, style_hints: ToneExampleStyleHints | None) -> str | None:
    sampler = _ACTIVE_VARIANT_SAMPLER.get()
    if sampler is None:
        return None
    tokens: list[str] = []
    for raw in (
        beat.public_role_hint,
        beat.charisma_hint,
        beat.status_need_hint,
        beat.speech_texture_hint,
        beat.cost_hint,
    ):
        token = _normalized_lexicon_token(raw)
        if token:
            tokens.append(token)
    tokens.extend(_SHELL_ROLE_LEXICON.get(beat.shell_id, ()))
    ordered_tokens: list[str] = []
    for token in tokens:
        if token and token not in ordered_tokens:
            ordered_tokens.append(token)
    if not ordered_tokens:
        return None
    focus_token = sampler.sample_phrase(tuple(ordered_tokens), fallback=ordered_tokens[0])
    phrase_options = (
        f"她那套围绕{focus_token}的口风还在，但每个停顿都把真实立场漏了一寸。",
        f"她试着继续拿{focus_token}稳场，可越稳越显得她已经开始失手。",
        f"她嘴上还挂着{focus_token}这层说辞，眼神却先把慌乱交代出来了。",
    )
    return sampler.sample_phrase(phrase_options, fallback=phrase_options[0])


def _anchor_line(beat: NpcReactionBeat, seed: NarrationRenderSeed, *, style_hints: ToneExampleStyleHints | None = None) -> str:
    if beat.scene_pressure.visibility_level == "public":
        options = (
            "四周的视线一下子都压过来，谁也没法把这一下当成没发生。",
            "场面已经被你推到所有人都在盯着的地方，空气像当场绷紧了一圈。",
            "这一句落下去的时候，周围人的呼吸都像跟着慢了一拍。",
        )
    elif beat.scene_pressure.visibility_level == "semi_public":
        options = (
            "旁边的人根本没真的散开，这点动静已经从半公开开始往全场人的耳朵里滚。",
            "这句话落下去之后，边上的人已经开始装作若无其事地偷听，场面根本压不回暗处。",
            "看似只是边缘位置的一句试探，可周围人已经明显竖起耳朵，等着看谁先失态。",
        )
    else:
        options = (
            "近距离的安静反而把那点裂缝衬得更响，谁都知道你是故意往最疼的地方压。",
            "这一下没有当众掀桌，可越是压低声音，越像把刀贴着人推过去。",
            "你没把场面做大，可这句落地的时候，气氛已经明显往失控那边偏了一格。",
        )
    line = _pick(options, seed=seed, slot_name="anchor")
    anchor = _style_anchor(
        style_hints,
        "镜头",
        "热搜",
        "公屏",
        "台下",
        "评审",
        "名额",
        "社团",
        "熟人",
        "站队",
        layer="primary",
    )
    if anchor and anchor not in line and beat.shell_id in {"entertainment_scandal", "campus_romance"}:
        line = trim_text(f"{line}{anchor}那边也已经在盯你这一下。", 4000)
    cost_subject_clause = _cost_subject_main_clause(style_hints)
    if cost_subject_clause:
        return trim_text(f"{cost_subject_clause}{line}", 4000)
    return line


def _visible_line(beat: NpcReactionBeat, seed: NarrationRenderSeed) -> str:
    mask_hint = beat.public_mask_hint
    texture = beat.speech_texture_hint
    tone_fragments = {
        "razor": (
            f"那股{beat.danger_hint}的锋先从字缝里露出来，连旁边的人都不敢随便插话。",
            f"她平时就是那个{beat.public_role_hint}，可这一下锋口露得太早，连装稳都显得更危险。",
            f"她那种一句话就能下刀的劲先漏出来了，场面反而比刚才更静。",
        ),
        "soft_hook": (
            f"她还在拿那种{beat.charisma_hint}的方式兜场，可越轻，越让人听出她已经慌了半寸。",
            f"她想继续靠{beat.charisma_hint}把人带过去，可这一下的轻声细语反而更像在露怯。",
            f"她还端着那股软绵绵的劲，可越像没事，越让人听出里面已经起了波纹。",
        ),
        "smiling_blade": (
            f"她甚至还留着一点笑，可那点笑已经更像把刀藏回话里，再慢慢送出来。",
            f"她还想靠{beat.charisma_hint}把这一下糊过去，可笑意已经先变成了带刺的东西。",
            f"她脸上那点会哄人的松弛没全掉，偏偏因此更像是在笑着往人伤口上压。",
        ),
        "measured": (
            f"她还在按{beat.public_role_hint}那套分寸收句子，可越整齐，越显得每个停顿都像在算人。",
            f"她一句句都还收得很稳，可那种过分克制反而把失控感衬得更明显。",
            f"她还没乱，只是每个字都太像算过，这反而让人更清楚她已经开始失手。",
        ),
        "slow_pressure": (
            f"她不抢声，可那股{beat.danger_hint}的压迫感已经顺着语速一点点往前碾过来。",
            f"她还是慢，可越慢越像在把人往墙角推，连空气都跟着重了一层。",
            f"她没提高声音，偏偏因此更像在把场面一寸寸往失控那边压。",
        ),
        "restrained": (
            f"她还想把那股劲压回去，可越忍，越像是在给下一句更狠的话蓄力。",
            f"她表面还算收着，偏偏那种硬忍反而把裂缝照得更清楚。",
            f"她还没真的失态，可那股收得太紧的样子已经让人知道她快撑不住了。",
        ),
    }
    by_mask = {
        "holding": (
            f"{beat.target_name}还端着那副{mask_hint}，可一开口就能听出{texture}，不像刚才那么稳了。",
            f"{beat.target_name}表面还在把{mask_hint}撑住，偏偏声音里的{texture}先漏了风。",
            f"{beat.target_name}还想继续演成{mask_hint}，只是那点{texture}已经压不回去了。",
        ),
        "cracking": (
            f"{beat.target_name}那层{mask_hint}已经开始裂，嘴上还稳，眼神却先漏了风。",
            f"{beat.target_name}明明还在撑{mask_hint}，可那股{texture}已经带出明显的硬撑味。",
            f"{beat.target_name}表面还算体面，可一张嘴就听得出{texture}，像在拿最后一点控制感硬顶。",
        ),
        "cornered": (
            f"{beat.target_name}被逼得只剩{mask_hint}这层壳还没掉，一开口却已经是明显的硬压失态。",
            f"{beat.target_name}还想守着{mask_hint}，但那点{texture}已经变成了被逼到墙角的卡顿。",
            f"{beat.target_name}脸上还挂着要稳场的样子，可声音里的{texture}已经像随时会断。",
        ),
        "broken": (
            f"{beat.target_name}那层{mask_hint}已经彻底撑不住了，连收声的余地都没留下。",
            f"{beat.target_name}不再装得像能稳住场面的人，整个人的反应已经先一步破了相。",
            f"{beat.target_name}那点最后的体面已经掉了，连原本藏在话里的劲儿都一并翻了出来。",
        ),
    }
    return f"{_pick(by_mask[beat.mask_state], seed=seed, slot_name='visible_mask')}{_pick(tone_fragments[beat.character_tone], seed=seed, slot_name='visible_tone')}"


def _inner_line(beat: NpcReactionBeat, seed: NarrationRenderSeed) -> str:
    impulse_lines = {
        "protect": (
            f"她嘴上还在顶，可人已经本能地往护人的方向偏，像怕你先被这场面吃掉。",
            f"她明明还想稳住自己，反应却先落在护人上，像不肯让你一个人先挨这一刀。",
            f"她那点防备没全退，可心思已经开始往护住你这边转了。",
        ),
        "betray": (
            f"她最怕的其实是{beat.shame_hint}，所以眼下更像是在盘算要不要先把别人卖出去。",
            f"她已经闻到了该甩锅的味道，下一步更像会先反手把人推出去挡刀。",
            f"她不是想认输，而是在算如果非要翻脸，先卖谁最划算。",
        ),
        "confess": (
            f"她那条关于{beat.breaking_hint}的线已经绷得发白，像差一点就会自己把最不该说的话说出来。",
            f"她嘴上还撑着，可那股要把底牌亲手说破的冲动已经顶到喉咙口了。",
            f"她像是在强行把话咽回去，可你能感觉到那点坦白已经顶到了喉咙口。",
        ),
        "retaliate": (
            f"她被你逼得起了反手的劲儿，像下一秒就会挑最疼的地方回敬回来。",
            f"她不是在退，是在找你哪一处最适合被她当场捅回去。",
            f"她那点笑意已经开始带刺，明显是在憋着一手更狠的反击。",
        ),
        "control": (
            f"她最想保住的还是{beat.status_need_hint}，所以哪怕脸色变了，也还在拼命把局面往可控里拽。",
            f"她这会儿顾的不是输赢，是别让{beat.status_need_hint}在众人眼前先掉下去。",
            f"她已经快绷不住了，可本能还是先去护{beat.status_need_hint}那根线。",
        ),
        "deflect": (
            f"她还想把真正的疼处藏回去，宁可把话绕开，也不肯先承认哪里被你戳中了。",
            f"她第一反应还是想糊过去，像只要不正面接这一句，场面就还能往回收。",
            f"她在试着把最危险的东西按回暗处，不肯让你当场把口子撕大。",
        ),
    }
    tone_overlays = {
        "razor": (
            f"她那股{beat.danger_hint}的劲已经顶到话锋上了，下一句八成会更直、更狠。",
            f"她不是会慢慢退的人，这会儿更像已经挑好了该往哪里下刀。",
            f"她心里那点要命的反击欲太锋利，连收着的时候都像在瞄准落点。",
        ),
        "soft_hook": (
            f"她还想靠{beat.charisma_hint}把你往回勾，可越想放软，越像在暴露她真正舍不得什么。",
            f"她第一反应还是想用那套柔软的办法把场子绕回去，可心已经先乱了。",
            f"她还在试图轻轻把你带开，可那点温柔现在反而更像她的破绽。",
        ),
        "smiling_blade": (
            f"她脸上那点会哄人的松弛没退，反而更像准备笑着把更狠的话送回来。",
            f"她甚至还留着一点笑，可那笑现在更像专门用来盖住翻脸前的寒气。",
            f"她不肯先撕破脸，可那股带笑的狠劲已经说明她不会白挨这一刀。",
        ),
        "measured": (
            f"她还在按{beat.public_role_hint}那套秩序算下一步，越冷静，越像在替谁安排后果。",
            f"她没让自己乱，可也正因为太稳，才更像已经把谁该付代价排好了顺序。",
            f"她不是没情绪，只是在拿分寸包住情绪，这比直接失态更危险。",
        ),
        "slow_pressure": (
            f"她不急着回手，可那股{beat.danger_hint}已经一点点压近，迟早会有人先扛不住。",
            f"她不抢着说重话，偏偏这种慢慢往前逼的劲最让人难受。",
            f"她像在故意把压力往长里拖，等别人先把自己拖垮。",
        ),
        "restrained": (
            f"她还在忍，可这股忍耐本身已经像下一句更狠的话在蓄势。",
            f"她不肯先把底牌翻开，可越压着，越像马上会换一种更重的方式还回来。",
            f"她还在试着把自己收住，可真正危险的地方反而是她还没彻底放开。",
        ),
    }
    return f"{_pick(impulse_lines[beat.dominant_impulse], seed=seed, slot_name='inner_impulse')}{_pick(tone_overlays[beat.character_tone], seed=seed, slot_name='inner_tone')}"


def _fallout_tail(
    beat: NpcReactionBeat,
    *,
    style_hints: ToneExampleStyleHints | None,
    segment_role: str | None = None,
) -> str:
    if style_hints is None:
        return ""
    reason_family = style_hints.fallout_reason_family
    if reason_family == "loss_position":
        reason_clause = "这不是普通余波，而是失位链条已经开始咬第二口。"
    elif reason_family == "self_preserve":
        reason_clause = "这拍之后，场上动作都更像自保动作，不像关系修复。"
    elif reason_family == "old_debt":
        reason_clause = "旧账在这时重新浮上来，后续每句都更容易被当成回账。"
    elif reason_family == "blame_shift":
        reason_clause = "这拍之后锅位已经开始重排，后续动作更像谁在甩锅谁在扛锅。"
    elif reason_family == "opportunity_window":
        reason_clause = "有人已经把它当成机会窗，后续会顺势改写站位。"
    else:
        reason_clause = "这一下之后，局势会按后果而不是按解释往前走。"
    if beat.shell_id == "entertainment_scandal":
        signal_clause = "镜头和热搜的外面风向不会等你解释，公关切割会先走。"
    elif beat.shell_id == "campus_romance":
        signal_clause = "台下、评审、社团和熟人传播会先把站队记住，名额压力会随后压上来。"
    elif beat.shell_id == "office_power":
        signal_clause = "会议桌和外围口风会同步改向，背锅顺序会越来越明确。"
    elif beat.shell_id == "wealth_families":
        signal_clause = "主桌顺位和家宴口风会同步偏移，谁被弃保很快就会看出来。"
    else:
        signal_clause = "场外系统已经进场，后续会比当下更快咬人。"
    signal_clause = _ensure_key_segment_shell_anchor(
        text=signal_clause,
        beat=beat,
        style_hints=style_hints,
        segment_role=segment_role,
        layer="fallout",
    )
    cost_clause = _supporting_cost_clause(beat, cost_family=style_hints.cost_family)
    return trim_text(f"{reason_clause}{signal_clause}{cost_clause}", 520)


def _fallout_line(beat: NpcReactionBeat, seed: NarrationRenderSeed, *, style_hints: ToneExampleStyleHints | None = None) -> str:
    if beat.public_event_hint and beat.no_return_hint and not _is_expository_hint(beat.public_event_hint):
        options = (
            _join_fragments(beat.public_event_hint, beat.no_return_hint),
            _join_fragments(beat.public_event_hint, beat.pain_hint, beat.no_return_hint),
            _join_fragments(beat.public_event_hint, beat.no_return_hint),
        )
        text = _pick(options, seed=seed, slot_name="fallout_directed")
        anchor = _style_anchor(style_hints, "镜头", "热搜", "公屏", "台下", "评审", "名额", "社团", "熟人", "站队", layer="fallout")
        suffix = _aftershock_suffix(beat, anchor)
        if suffix and anchor not in text:
            text = trim_text(f"{text}{suffix}", 4000)
        return trim_text(f"{text}{_fallout_tail(beat, style_hints=style_hints, segment_role=seed.segment_role)}", 4000)
    if beat.public_event_hint and not _is_expository_hint(beat.public_event_hint):
        options = (
            beat.public_event_hint,
            _join_fragments(beat.public_event_hint, beat.pain_hint),
            _join_fragments(beat.public_event_hint, beat.no_return_hint),
        )
        text = _pick(options, seed=seed, slot_name="fallout_event")
        anchor = _style_anchor(style_hints, "镜头", "热搜", "公屏", "台下", "评审", "名额", "社团", "熟人", "站队", layer="fallout")
        suffix = _aftershock_suffix(beat, anchor)
        if suffix and anchor not in text:
            text = trim_text(f"{text}{suffix}", 4000)
        return trim_text(f"{text}{_fallout_tail(beat, style_hints=style_hints, segment_role=seed.segment_role)}", 4000)
    if beat.shell_id == "wealth_families":
        vector_lines = {
            "reputation": (
                "主桌边原本还装作没听见的人都停了动作，这一下已经不可能再靠体面遮过去。",
                "这点动静已经从暗潮变成了主桌上的失态，谁再想装没看见都来不及。",
                "桌上的体面已经先裂开一道口子，接下来只会有人急着补锅，有人急着翻桌。",
            ),
            "alliance": (
                f"你和{beat.target_name}已经像被默认绑到了一边，另一边的人很快就会开始重新算账。",
                f"这一手等于先把你和{beat.target_name}挂到了同一条线上，后面谁都不会再把这层关系当成假装。",
                f"桌上的人已经在按新的站边看你和{beat.target_name}，后面再想两头留退路只会更难看。",
            ),
            "exposure": (
                f"那份最不该见光的东西已经被你顶上{beat.arena_name}的台面，后面每个人都会盯着它继续往谁脸上砸。",
                f"秘密已经不再只是暗线，整张桌子现在都在围着它重新站队。",
                f"这一下已经把最危险的真相掀到桌面中央，后面谁先碰它谁就先见血。",
            ),
            "irreversible_stance": (
                "这一步已经把站队钉得更死，谁再想回头都得先承认自己刚才在演。",
                "场面已经从试探变成了认边，后面只会有人更狠地保自己那边的人。",
                "你把桌上的关系推到不再含糊的位置了，下一句只会更伤体面。",
            ),
        }
    elif beat.shell_id == "office_power":
        vector_lines = {
            "reputation": (
                "桌边原本还在翻文件的人都停了手，连表态顺序都被你硬生生打乱了。",
                "这一下已经从私下角力变成了牌桌上的公开失衡，谁都不可能当没听见。",
                "会上的秩序先乱了一格，后面每个人说的话都要重新算价码。",
            ),
            "alliance": (
                f"你和{beat.target_name}已经像被记进同一阵营，另一边很快就会把账直接算到你头上。",
                f"这一手等于先认边了，后面谁都不会再把你和{beat.target_name}当成还能模糊的人。",
                f"局面已经把你和{beat.target_name}往同一条线上推，另一边只会更快开始找背锅位。",
            ),
            "exposure": (
                "最不该摊到桌上的东西已经被你按到会议桌中央，后面每一句都在逼人把锅认清。",
                "秘密已经进了公开翻牌的阶段，接下来谁先开口，谁就得先扛代价。",
                "你把最危险的证据直接顶上台面，会上的风向只会更硬，不会再往回松。",
            ),
            "irreversible_stance": (
                "这一下已经把站边写进场面里了，后面再想两头都留只会更像心虚。",
                "局势已经从试探进了认边，谁再想装作中立都晚了。",
                "你把这局往不可逆的方向钉死了一步，后面只会更像清算。",
            ),
        }
    elif beat.shell_id == "entertainment_scandal":
        vector_lines = {
            "reputation": (
                "旁边的镜头和手机已经追上来，这一下很快就会从现场滚到外面的风向里。",
                "这点动静已经不可能只留在后台，谁先失态谁就会先被外面的人记住。",
                "镜头没替任何人留情，后面这一幕只会越传越快。",
            ),
            "alliance": (
                f"你和{beat.target_name}已经像被镜头拍成一边，另一边很快就会开始切割。",
                f"这一手把你和{beat.target_name}往同一条热搜线里绑得更紧了，后面谁都不可能轻松抽身。",
                f"场面已经默认你和{beat.target_name}的关系站边，后面再解释只会越描越黑。",
            ),
            "exposure": (
                "最不该被看见的东西已经滚到镜头前，后面只看谁先把它彻底摁亮。",
                "秘密已经真的见了光，现场和外面的风向都在围着它继续发酵。",
                "你把那点会翻车的东西直接推到外面去了，后面谁先碰它谁就先掉下去。",
            ),
            "irreversible_stance": (
                "这一下已经把谁跟谁站一边写进镜头语言里了，回头会比你想的更难。",
                "局面已经不是还能不能圆的问题，而是谁先在公众叙事里被钉住。",
                "你把场面往不可逆的公开站边推了一格，后面每句话都更像声明。",
            ),
        }
    else:
        vector_lines = {
            "reputation": (
                "台下的人已经开始交头接耳，风向比你开口前偏得更快。",
                "旁边那些装作没在听的人已经先交换了眼神，后面消息只会跑得更快。",
                "这点动静已经够让风向变掉一截，后面谁都别想装没发生。",
            ),
            "alliance": (
                f"你和{beat.target_name}已经像被默认绑到了一边，另一头的人很快就会开始重新站位。",
                f"这一手让你和{beat.target_name}的立场更像写在脸上，后面再装模糊只会更可疑。",
                f"风向已经在把你和{beat.target_name}往同一边推，另一边马上就会跟着起反应。",
            ),
            "exposure": (
                "最不该被说破的东西已经被你顶到明面上，后面只会有人更快把它彻底翻开。",
                "秘密已经不再安稳地待在暗处，风向和视线现在都围着它转。",
                "你把最危险的那层皮已经整片扯开，后面谁想装没看见都晚了。",
            ),
            "irreversible_stance": (
                "这一下已经把站边推到更难回头的位置了，后面每个人都会照这个新位置看人。",
                "局面已经从试探变成了认边，后面再改口只会更难看。",
                "你把这局往不可逆的方向推深了一格，后面说什么都会更疼。",
            ),
        }
    vector_lines = {
        **vector_lines,
    }
    text = _pick(vector_lines[beat.fallout_vector], seed=seed, slot_name="fallout")
    anchor = _style_anchor(style_hints, "镜头", "热搜", "公屏", "台下", "评审", "名额", "社团", "熟人", "站队", layer="fallout")
    if anchor and anchor not in text and beat.shell_id in {"entertainment_scandal", "campus_romance"}:
        suffix = f"{anchor}那边也不会替任何人把这一下说轻。"
        text = trim_text(f"{text}{suffix}", 4000)
    return trim_text(f"{text}{_fallout_tail(beat, style_hints=style_hints, segment_role=seed.segment_role)}", 4000)


def _generic_counter_support_line(beat: NpcReactionBeat, seed: NarrationRenderSeed, *, primary_name: str) -> str:
    by_tone = {
        "razor": (
            f"{beat.target_name}没去替{primary_name}圆场，反而像已经盯准了下一句该往哪里下刀。",
            f"{beat.target_name}那股{beat.danger_hint}的劲先抬起来了，明显不是来救场，而是准备顺着这道口子补狠的。",
            f"{beat.target_name}没抢话，可那种随时能切到骨头上的安静已经先把人压住。",
        ),
        "soft_hook": (
            f"{beat.target_name}像是想软着把场子兜回去，可那点{beat.charisma_hint}现在更像在试谁先软下来。",
            f"{beat.target_name}没有硬顶，只是把声音放得更轻，反而让人更清楚她不是来替{primary_name}收尾的。",
            f"{beat.target_name}看上去还想温和一点，可那点软钩子现在只像在找最容易松动的人。",
        ),
        "smiling_blade": (
            f"{beat.target_name}脸上居然还留着一点笑，可那点笑明显不是来救场，更像等着看{primary_name}先露更大的破绽。",
            f"{beat.target_name}还在笑，偏偏因此更让人发冷，像她已经准备笑着把局面再往下送一寸。",
            f"{beat.target_name}那点会哄人的松弛没退，反而更像在隔着笑意给{primary_name}补第二刀。",
        ),
        "measured": (
            f"{beat.target_name}没急着开口，只是按{beat.public_role_hint}那套分寸站在那里，像已经在心里替每个人重排后果。",
            f"{beat.target_name}表面最稳，可也正因为太稳，才像已经算好谁该先替{primary_name}付账。",
            f"{beat.target_name}没有失态，反而把场子看得更冷，像后面的顺序都已经被她默默记下来了。",
        ),
        "slow_pressure": (
            f"{beat.target_name}没立刻接话，只把那股{beat.danger_hint}慢慢压上来，像在等{primary_name}自己先扛不住。",
            f"{beat.target_name}越是不急着开口，越像在把压力往每个人头上平均分过去。",
            f"{beat.target_name}只晚了半拍，偏偏这半拍最像在逼人自己往墙角退。",
        ),
        "restrained": (
            f"{beat.target_name}没有急着表态，可那种硬忍着不动的样子反而说明她不会让这事轻轻过去。",
            f"{beat.target_name}还收着，可她越收，越像在替下一句更重的话蓄势。",
            f"{beat.target_name}没先失态，但那股忍住不发的劲已经让场面更紧了。",
        ),
    }
    return _pick(by_tone[beat.character_tone], seed=seed, slot_name=f"support_counter_{beat.shell_id}")


def _generic_crowd_support_line(beat: NpcReactionBeat, seed: NarrationRenderSeed, *, primary_name: str) -> str:
    by_tone = {
        "razor": (
            f"{beat.target_name}没开口，只把目光在你和{primary_name}之间一扫，那种锋利已经够让旁边的人跟着缩一下。",
            f"{beat.target_name}只是偏头看了一眼，可那眼神太像在给局面判死刑，周围的人呼吸都跟着收住了。",
            f"{beat.target_name}一句话没说，但那股随时会补刀的安静已经让旁边的人开始重新站位。",
        ),
        "soft_hook": (
            f"{beat.target_name}没有急着出声，只是把那种{beat.charisma_hint}的温和样子摆出来，旁边的人反而更想看她会偏向谁。",
            f"{beat.target_name}只轻轻抬了一下眼，场外的人就已经开始猜她下一秒会不会替谁留面子。",
            f"{beat.target_name}看上去最像想把场子缓一下的人，可也正因为这样，旁边的人更快开始跟着她换气。",
        ),
        "smiling_blade": (
            f"{beat.target_name}没有接话，只有嘴角那点笑意轻轻一动，旁边的人就知道她不是来救人的。",
            f"{beat.target_name}还挂着那种好像没事的笑，可围观的人反而更快意识到这事已经收不回去了。",
            f"{beat.target_name}只是笑了一下，场外的风向就像被她顺手推了一把。",
        ),
        "measured": (
            f"{beat.target_name}没急着插话，只把最稳的那层样子摆出来，围观的人已经开始跟着她重新算谁更占理。",
            f"{beat.target_name}不出声时反而更像规矩本身，旁边的人已经开始照着她的表情改站位了。",
            f"{beat.target_name}越冷静，越像在替这场事故定调，周围的人很快就跟着收了口风。",
        ),
        "slow_pressure": (
            f"{beat.target_name}什么都没说，只把那股慢慢往前压的气场留在场上，围观的人已经先不敢乱动。",
            f"{beat.target_name}只晚一拍看过去，周围人的神经就像被她一起拽紧了。",
            f"{beat.target_name}没抢着表态，可那种慢吞吞的压迫感反而让场外更快安静下来。",
        ),
        "restrained": (
            f"{beat.target_name}没有立刻表态，只是沉了半拍，旁边的人就已经知道这事不可能轻轻揭过去。",
            f"{beat.target_name}把情绪收得很紧，偏偏这种收着反而让围观的人更快意识到事情变了。",
            f"{beat.target_name}只是安静了一秒，周围人就已经开始用新的眼光看你和{primary_name}。",
        ),
    }
    return _pick(by_tone[beat.character_tone], seed=seed, slot_name=f"support_crowd_{beat.shell_id}")


def _counter_support_line(reaction: SupportingReactionBeat, *, primary_name: str, style_hints: ToneExampleStyleHints | None = None) -> str:
    beat = reaction.beat
    seed = reaction.seed
    strategic_line = _strategic_intent_line(reaction, primary_name=primary_name)
    if beat.shell_id == "entertainment_scandal":
        if _has_cause(reaction, "covering_self"):
            anchor = _style_anchor(style_hints, "镜头", "公屏", "热搜", "版本", layer="supporting")
            options = (
                f"{beat.target_name}抢着替自己摆版本，根本不是在救{primary_name}，而是在抢谁先拿到解释权。{anchor or '镜头'}那边最先认的只会是她的说法。",
                f"{beat.target_name}看着像在稳场，其实先护的是自己的口径和{anchor or '镜头'}位置。",
                f"{beat.target_name}没替{primary_name}挡，反而先把最利于自己的说法往前推了一步，像在抢{anchor or '版本'}。",
            )
            text = _pick(options, seed=seed, slot_name="ent_counter_covering_self")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        if _has_cause(reaction, "cutting_others", "was_cut_out"):
            options = (
                f"{beat.target_name}这会儿根本不是想救场，而是在等谁先被切出去，好让自己先抽身。",
                f"{beat.target_name}盯着的不是怎么收尾，而是这场翻车最后该先挂到谁身上。",
                f"{beat.target_name}不肯替{primary_name}兜底，明显是在等切割线先落到别人头上。",
            )
            text = _pick(options, seed=seed, slot_name="ent_counter_cutting")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        if _has_cause(reaction, "debt_due", "kept_score"):
            options = (
                f"{beat.target_name}这时候突然更冷，像是旧账正好回头咬到这一下，她只想看谁先被拖下去。",
                f"{beat.target_name}没再装没事，倒像一直记着的那笔账终于等到了合适的反咬时机。",
                f"{beat.target_name}这会儿的不救场更像带着旧账，她显然不打算替谁把这笔账抹平。",
            )
            text = _pick(options, seed=seed, slot_name="ent_counter_debt")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        by_tone = {
            "smiling_blade": (
                f"{beat.target_name}没替{primary_name}兜场，反而像在笑着等热搜自己把人吞进去。",
                f"{beat.target_name}嘴角还挂着一点松弛，可那点松弛更像在等公关彻底来不及切。",
                f"{beat.target_name}没有救场，反而像已经在心里给这场翻车挑好了最适合发酵的角度。",
            ),
            "measured": (
                f"{beat.target_name}没去救这一下，只是按最稳的节奏收着话，像已经开始替这场事故分镜头、分责任。",
                f"{beat.target_name}没有抢着解释，反而更像在等谁先被公众叙事吞下去。",
                f"{beat.target_name}站得太稳了，稳得像已经在盘算这场事故之后谁该先被切出去。",
            ),
            "slow_pressure": (
                f"{beat.target_name}没替{primary_name}挡镜头，只把那股压迫感慢慢往场上推，像在等外面的风向自己接住这一下。",
                f"{beat.target_name}没有硬顶，只是一点点把场子压冷，冷得像在给后面的切割留空间。",
                f"{beat.target_name}越是不急，越像在等热搜和镜头替她把下一刀送出去。",
            ),
            "razor": (
                f"{beat.target_name}没救场，反而像已经挑好了要往谁身上补第二刀，镜头只会更爱这种瞬间。",
                f"{beat.target_name}那股锋利不是拿来圆场的，倒像在等谁先被公开叙事钉住。",
                f"{beat.target_name}一句话没抢，可那种随时能切责任的冷静已经让人发寒。",
            ),
            "soft_hook": (
                f"{beat.target_name}看着还像想轻轻把场子带开，可那种温柔更像在试谁最先愿意替这场事故认账。",
                f"{beat.target_name}没去兜底，只把声音放得更软，软得像在替之后的公关切割试水温。",
                f"{beat.target_name}那点轻轻带人的劲没用来救场，反而更像在找最容易先掉队的人。",
            ),
            "restrained": (
                f"{beat.target_name}没去救这一下，只是把情绪收得更紧，紧得像已经决定不替任何人分担这场翻车。",
                f"{beat.target_name}安静得太克制了，克制得像在看谁先被这场公众事故推下去。",
                f"{beat.target_name}没有多说，可那种收着的姿态已经像默认了后面只会更公开地切割。",
            ),
        }
        text = _pick(by_tone[beat.character_tone], seed=seed, slot_name=f"ent_counter_{beat.character_tone}")
        return trim_text(f"{text}{strategic_line or ''}", 4000)
    if beat.shell_id == "campus_romance":
        if _has_cause(reaction, "forced_alignment", "saw_player_side"):
            anchor = _style_anchor(style_hints, "台下", "评审", "熟人", "站队", "社团", layer="supporting")
            options = (
                f"{beat.target_name}没去替{primary_name}圆场，反而像在看{anchor or '台下'}和熟人圈会先往哪边站。",
                f"{beat.target_name}这会儿盯着的不是谁更委屈，而是谁先在{anchor or '评审'}和同学面前把边站死。",
                f"{beat.target_name}不急着开口，可那种冷眼已经像在把场上每个人都往{anchor or '站队'}里推。",
            )
            text = _pick(options, seed=seed, slot_name="campus_counter_alignment")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        if _has_cause(reaction, "debt_due", "kept_score"):
            options = (
                f"{beat.target_name}这会儿的不救场像带着旧账，明显是在等台下把以前那笔事一起翻出来。",
                f"{beat.target_name}像是终于等到熟人圈和评审都在场的时机，根本不打算替谁把旧账压回去。",
                f"{beat.target_name}这一下更像在借题翻账，借着公开场合把一直记着的那口气还回来。",
            )
            text = _pick(options, seed=seed, slot_name="campus_counter_debt")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        by_tone = {
            "soft_hook": (
                f"{beat.target_name}没替{primary_name}圆场，只是轻轻接了一句，反而像在试台下到底有多少人已经开始换边。",
                f"{beat.target_name}声音还是轻的，可那股轻已经不像救场，更像在看谁会先在同学和评审面前松口。",
                f"{beat.target_name}没有硬顶，只把话放轻，轻得像在试哪个熟人会先转身站队。",
            ),
            "measured": (
                f"{beat.target_name}没去救这一下，只是把最稳的样子摆出来，像已经在心里替评审席重新排谁更占理。",
                f"{beat.target_name}没有多说，可那种稳更像在告诉周围人：这件事该重新站队了。",
                f"{beat.target_name}她越冷静，越像在替台下和评审席默默改方向。",
            ),
            "restrained": (
                f"{beat.target_name}没去替{primary_name}挡，只是把情绪压得很紧，紧得像在等社团里的人自己先往安全那边站。",
                f"{beat.target_name}一句重话都没说，可那种忍着不发的样子已经像在跟台下划线。",
                f"{beat.target_name}没先失态，但那股收着的劲更像在看谁会先被前途和脸面吓退。",
            ),
            "razor": (
                f"{beat.target_name}没去救场，反而像已经盯准了下一句该把谁从同学和评审面前先推下去。",
                f"{beat.target_name}那股锋利不是在替{primary_name}挡刀，而是像在给站队的人群补最后一刀。",
                f"{beat.target_name}没抢话，可那种冷硬已经像在逼台下赶快做选择。",
            ),
            "smiling_blade": (
                f"{beat.target_name}甚至还留着一点笑，可那点笑更像在看谁会先在熟人圈里丢脸。",
                f"{beat.target_name}没有去救这一下，反而像在笑着等评审和同学自己把风向推偏。",
                f"{beat.target_name}那点轻松太假了，假得像故意让场面更难堪，好逼出下一轮站队。",
            ),
            "slow_pressure": (
                f"{beat.target_name}没急着接话，只是慢慢把压力往台下和评审席那边压，像在逼所有熟人一起选边。",
                f"{beat.target_name}越慢，越像故意把这点尴尬拖长，好让前途和脸面一起压到每个人头上。",
                f"{beat.target_name}没有硬顶，可那种慢慢逼近的劲已经像在把社团里的人一批批往外推。",
            ),
        }
        text = _pick(by_tone[beat.character_tone], seed=seed, slot_name=f"campus_counter_{beat.character_tone}")
        return trim_text(f"{text}{strategic_line or ''}", 4000)
    text = _generic_counter_support_line(beat, seed, primary_name=primary_name)
    return trim_text(f"{text}{strategic_line or ''}", 4000)


def _crowd_support_line(reaction: SupportingReactionBeat, *, primary_name: str, style_hints: ToneExampleStyleHints | None = None) -> str:
    beat = reaction.beat
    seed = reaction.seed
    strategic_line = _strategic_intent_line(reaction, primary_name=primary_name)
    if beat.shell_id == "entertainment_scandal":
        if _has_cause(reaction, "camera_pressure"):
            anchor = _style_anchor(style_hints, "镜头", "公屏", "热搜", "版本", layer="supporting")
            options = (
                f"{beat.target_name}一个眼神过去，旁边的手机、{anchor or '镜头'}和外面的风向就像一下全认定这事要往热搜上滚。",
                f"{beat.target_name}没开口，可{anchor or '镜头'}感已经变了，连旁边看热闹的人都像在替这场事故找传播角度。",
                f"{beat.target_name}只轻轻动了一下，场边那些人就已经像公关号一样开始替这事分{anchor or '版本'}。",
            )
            text = _pick(options, seed=seed, slot_name="ent_crowd_camera")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        if _has_cause(reaction, "debt_due"):
            options = (
                f"{beat.target_name}这会儿一沉住气，场外反而更像闻到了旧账翻出来的味道，镜头外的人已经开始接这个话头了。",
                f"{beat.target_name}什么都没说，可那种熟门熟路的冷静更像在告诉所有人：旧账现在正好能拿出来做文章。",
                f"{beat.target_name}这会儿越稳，越像在让旁边的人意识到这不只是事故，还有旧账正在一起发酵。",
            )
            text = _pick(options, seed=seed, slot_name="ent_crowd_debt")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        by_tone = {
            "smiling_blade": (
                f"{beat.target_name}只是笑了一下，旁边的手机和镜头就像一下认定了这事会往热搜上滚。",
                f"{beat.target_name}没接话，可她那点带笑的松弛反而像在提醒所有人：外面的风向马上会接住这一下。",
                f"{beat.target_name}一个眼神过去，场边那些看热闹的人已经开始像公关号一样替这场事故找角度。",
            ),
            "measured": (
                f"{beat.target_name}不出声，反而更像在替镜头定调，旁边的人已经开始顺着她的表情猜谁会先被切出去。",
                f"{beat.target_name}越冷静，越像这场事故已经被她默默交给外面的风向去处置。",
                f"{beat.target_name}只是站在那里，场记、手机和旁边的人就已经像在替这场翻车整理版本。",
            ),
            "slow_pressure": (
                f"{beat.target_name}没抢话，只把气压慢慢压低，低得像镜头和外面的风向都开始往这边收口。",
                f"{beat.target_name}只晚一拍看过去，旁边的人就已经意识到这事会一路滚到外面去。",
                f"{beat.target_name}不急着表态，可那种慢吞吞的压迫感已经像在替热搜预热。",
            ),
            "razor": (
                f"{beat.target_name}一句话没说，可那种锋利已经让旁边的人知道这事不会停在现场，迟早要滚到外面风向里。",
                f"{beat.target_name}只是看了一眼，镜头感就已经变了，像所有人都在等谁先被公开切割。",
                f"{beat.target_name}没开口，可那种冷已经够让围观的人猜到：后面只会更像事故通报。",
            ),
            "soft_hook": (
                f"{beat.target_name}只是轻轻抬了下眼，旁边的人就已经开始猜这事会不会被包装成另一种热搜叙事。",
                f"{beat.target_name}看上去最像能把场子缓住的人，可也正因为这样，旁边的人更快意识到公关已经来不及了。",
                f"{beat.target_name}没出声，只把温和样子摆出来，镜头外的人反而更快开始分谁能被切割出去。",
            ),
            "restrained": (
                f"{beat.target_name}安静了一秒，场边的手机就已经开始悄悄抬起来，这种克制反而像在替事故定调。",
                f"{beat.target_name}没表态，可那种沉着已经让人知道这事不会停在台里，外面的风向马上会接住。",
                f"{beat.target_name}只是收住情绪，旁边的人就已经知道后面多半会变成更公开的切割。",
            ),
        }
        text = _pick(by_tone[beat.character_tone], seed=seed, slot_name=f"ent_crowd_{beat.character_tone}")
        return trim_text(f"{text}{strategic_line or ''}", 4000)
    if beat.shell_id == "campus_romance":
        if _has_cause(reaction, "campus_spread"):
            anchor = _style_anchor(style_hints, "台下", "评审", "名额", "社团", "熟人", "站队", layer="supporting")
            options = (
                f"{beat.target_name}只是一沉住气，{anchor or '台下'}、评审席和熟人圈就像同时开始换眼色，这事显然会越传越开。",
                f"{beat.target_name}没开口，可那点停顿已经够让同学圈和{anchor or '社团'}群一起开始传你们这一下了。",
                f"{beat.target_name}只是看了一眼，{anchor or '台下'}那片熟人社会的呼吸就已经变了节奏。",
            )
            text = _pick(options, seed=seed, slot_name="campus_crowd_spread")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        if _has_cause(reaction, "debt_due"):
            options = (
                f"{beat.target_name}这会儿越安静，越像在提醒台下和评审：以前那笔旧账也该一起翻出来了。",
                f"{beat.target_name}没出声，可那种熟人都懂的沉默已经把旧账的影子重新拖回场上了。",
                f"{beat.target_name}只是收住了那一下，台下的人却像一下想起你们之间还有旧账没清。",
            )
            text = _pick(options, seed=seed, slot_name="campus_crowd_debt")
            return trim_text(f"{text}{strategic_line or ''}", 4000)
        by_tone = {
            "soft_hook": (
                f"{beat.target_name}只是轻轻接了一下眼神，台下那群熟人就已经开始猜她会站谁那边。",
                f"{beat.target_name}没说重话，可那种轻声细气已经够让评审席和同学圈一起换气。",
                f"{beat.target_name}只是把声音放轻，台下的人反而更快开始互相看脸色，像在试探谁先站队。",
            ),
            "measured": (
                f"{beat.target_name}不出声时反而更像评审席默认的那条线，台下和社团里的人已经开始照着她的反应改站位。",
                f"{beat.target_name}越冷静，越像在给这场公开尴尬定性，评审和同学圈很快就跟着偏过去了。",
                f"{beat.target_name}只是稳稳站着，台下那些熟人已经开始重新算谁会丢掉名额和脸面。",
            ),
            "restrained": (
                f"{beat.target_name}没有立刻接话，只是安静了一秒，台下和熟人圈就已经知道这事不可能轻轻揭过去。",
                f"{beat.target_name}那种收着不发的样子，让评审席和社团核心都开始用新的眼光看你和{primary_name}。",
                f"{beat.target_name}只是把情绪压住，台下的人却更快开始交头接耳，像在算谁会先失去前途。",
            ),
            "razor": (
                f"{beat.target_name}一句话没说，可那种锋利已经够让台下的人意识到：这不是普通争执，而是要逼人当场站队。",
                f"{beat.target_name}只扫了一眼，评审席和熟人圈就已经像被那一下切开了。",
                f"{beat.target_name}没开口，可那种冷已经够让社团里的人知道后面谁都会被迫选边。",
            ),
            "smiling_blade": (
                f"{beat.target_name}甚至还留着一点笑，可那点笑只会让台下的人更快意识到这事会在熟人圈里发酵得很难看。",
                f"{beat.target_name}只是笑了一下，评审席和同学圈就已经开始猜谁会先被这件事丢掉脸面。",
                f"{beat.target_name}那点带笑的松弛没法缓场，反而把台下人的眼神全勾到了站队上。",
            ),
            "slow_pressure": (
                f"{beat.target_name}没抢着表态，只把压力慢慢压到台下去，压得评审和同学圈都开始重新站位。",
                f"{beat.target_name}越慢，越像在把这场尴尬故意拖给每个熟人一起扛，谁都别想装没看见。",
                f"{beat.target_name}不急着开口，可那种慢慢逼近的气压已经让社团里的人先交换起眼色。",
            ),
        }
        text = _pick(by_tone[beat.character_tone], seed=seed, slot_name=f"campus_crowd_{beat.character_tone}")
        return trim_text(f"{text}{strategic_line or ''}", 4000)
    text = _generic_crowd_support_line(beat, seed, primary_name=primary_name)
    return trim_text(f"{text}{strategic_line or ''}", 4000)


def _supporting_reason_family(reaction: SupportingReactionBeat, style_hints: ToneExampleStyleHints | None) -> str:
    if style_hints is not None:
        return style_hints.counter_reason_family if reaction.role == "counter" else style_hints.crowd_reason_family
    if _has_cause(reaction, "debt_due", "kept_score"):
        return "old_debt"
    if _has_cause(reaction, "sacrifice_window", "forced_alignment"):
        return "blame_shift"
    if _has_cause(reaction, "covering_self", "cutting_others"):
        return "self_preserve"
    if _has_cause(reaction, "intent_loss_triggered"):
        return "loss_position"
    if _has_cause(reaction, "opportunity_window"):
        return "opportunity_window"
    return "mixed"


def _supporting_signal_clause(
    beat: NpcReactionBeat,
    reaction: SupportingReactionBeat,
    *,
    style_hints: ToneExampleStyleHints | None = None,
) -> str:
    segment_role = reaction.seed.segment_role
    prop_edge_id = next(
        (
            tag.split(":", 1)[1]
            for tag in reaction.cause_tags
            if isinstance(tag, str) and tag.startswith("prop_edge:")
        ),
        None,
    )
    if prop_edge_id:
        edge = get_shell_edge(beat.shell_id, prop_edge_id)
        if edge is not None:
            text = edge_signal_clause(edge=edge, role=reaction.role)
            return _ensure_key_segment_shell_anchor(
                text=text,
                beat=beat,
                style_hints=style_hints,
                segment_role=segment_role,
                layer="supporting",
            )
    if beat.shell_id == "entertainment_scandal":
        if reaction.role == "counter":
            text = "镜头和公屏已经把她这一下当成口径动作，外面风向只会顺着热搜和公关切割继续滚。"
        else:
            text = "旁边手机、镜头、公关群都在动，热搜版本和切割线几乎是同时起跑。"
        return _ensure_key_segment_shell_anchor(
            text=text,
            beat=beat,
            style_hints=style_hints,
            segment_role=segment_role,
            layer="supporting",
        )
    if beat.shell_id == "campus_romance":
        if reaction.role == "counter":
            text = "台下和评审席已经在换眼色，社团熟人圈也开始传谁先站队，名额阴影跟着压下来。"
        else:
            text = "熟人社会的传播已经跑起来了：台下、评审、社团群和名额讨论都在同步偏向。"
        return _ensure_key_segment_shell_anchor(
            text=text,
            beat=beat,
            style_hints=style_hints,
            segment_role=segment_role,
            layer="supporting",
        )
    if beat.shell_id == "office_power":
        return _ensure_key_segment_shell_anchor(
            text="会议桌和走廊口风已经改道，谁背锅、谁失位这件事正在被默默定序。",
            beat=beat,
            style_hints=style_hints,
            segment_role=segment_role,
            layer="supporting",
        )
    if beat.shell_id == "wealth_families":
        return _ensure_key_segment_shell_anchor(
            text="主桌上的顺位眼神已经变了，家宴口风会沿着认边和弃保继续扩散。",
            beat=beat,
            style_hints=style_hints,
            segment_role=segment_role,
            layer="supporting",
        )
    return _ensure_key_segment_shell_anchor(
        text="场外系统已经自己在动，这一下不会停在两个人的对话里。",
        beat=beat,
        style_hints=style_hints,
        segment_role=segment_role,
        layer="supporting",
    )


def _supporting_cost_clause(beat: NpcReactionBeat, *, cost_family: str) -> str:
    sampler = _ACTIVE_VARIANT_SAMPLER.get()
    if cost_family == "narrative_control":
        options = (
            "代价会先落在谁掌握解释权，后续每句都会被放大解读。",
            "真正被消耗的是叙事主动权，一旦丢手后面很难抢回。",
            "这拍的成本不在情绪，而在后续话语权被谁拿走。",
        )
    elif cost_family == "eligibility":
        options = (
            "代价先压到名额和前途，再慢慢反噬到关系层面。",
            "这步会先动摇资格线，后续的前途窗口会明显收窄。",
            "最先被吞掉的是机会和资格，感情账会在后面补刀。",
        )
    elif cost_family == "position":
        options = (
            "代价先砸在位置和发言顺序，后续每一步都要加倍谨慎。",
            "这拍会让席位与话语权先失衡，想撤回会越来越贵。",
            "第一层成本是位置松动，第二层才轮到情绪修补。",
        )
    elif cost_family == "relationship":
        options = (
            "代价会把关系账提前摊开，谁都很难继续装作没发生。",
            "这步会逼关系线提前表态，之后每句都带站位成本。",
            "真正的成本是信任被提前计价，后续补救空间会骤减。",
        )
    elif cost_family == "face":
        options = (
            "代价先落在公开观感，后续决定都要带着这道裂纹走。",
            "最先受损的是场面观感，后面每个选择都会被拿来对照。",
            "这拍会先伤公开体感，之后再小的动作都会被放大。",
        )
    else:
        options = (
            f"代价会沿着{beat.cost_hint}持续传导，不会停在这句反应里。",
            f"这一步会把{beat.cost_hint}提前推上台面，后续更难轻描淡写。",
            f"成本已经贴到{beat.cost_hint}这条线上，后面每拍都要继续付账。",
        )
    if sampler is not None:
        return sampler.sample_phrase(options, fallback=options[0])
    return options[0]


def _render_causal_clause_chain(
    skeleton: _CausalClauseSkeleton,
    *,
    cadence: str = "mixed",
    max_length: int = 4000,
) -> str:
    base = trim_text(
        f"{skeleton.reason_clause}{skeleton.signal_clause}{skeleton.cost_clause}",
        max_length,
    )
    if cadence not in {"broken", "staccato"}:
        return base
    reason = skeleton.reason_clause.rstrip("。")
    signal = skeleton.signal_clause.rstrip("。")
    cost = skeleton.cost_clause.rstrip("。")
    return trim_text(f"{reason}。{signal}。{cost}。", max_length)


def _supporting_reason_clause(
    reaction: SupportingReactionBeat,
    *,
    primary_name: str,
    reason_family: str,
    style_hints: ToneExampleStyleHints | None,
) -> str:
    beat = reaction.beat
    if style_hints is not None and style_hints.role_lexicon_hit:
        if reaction.role == "counter":
            verb = (style_hints.counter_action_verb or "").strip()
            receiver = (style_hints.counter_receiver_template or "").strip()
        else:
            verb = (style_hints.crowd_action_verb or "").strip()
            receiver = (style_hints.crowd_receiver_template or "").strip()
        if verb or receiver:
            if verb and receiver:
                return trim_text(f"{beat.target_name}这拍先{verb}：{receiver}。", 220)
            if receiver:
                return trim_text(f"{beat.target_name}这拍先把动作压到受体位：{receiver}。", 220)
            return trim_text(f"{beat.target_name}这拍先{verb}，不是替{primary_name}收尾。", 220)
    if reason_family == "loss_position":
        return f"{beat.target_name}这拍反应更像在防失位，不是替{primary_name}收尾。"
    if reason_family == "self_preserve":
        return f"{beat.target_name}先护的是自己的退路，连表态都在给后手留切口。"
    if reason_family == "old_debt":
        return f"{beat.target_name}这句带着旧账味，像终于等到把账翻回来的窗口。"
    if reason_family == "blame_shift":
        return f"{beat.target_name}这拍先看的是锅怎么分，不是看{primary_name}能不能体面收场。"
    if reason_family == "opportunity_window":
        return f"{beat.target_name}明显在等{primary_name}再露半寸破绽，好把局势顺手改写成对自己有利的版本。"
    return f"{beat.target_name}这会儿说话不是情绪先行，而是算盘先行。"


def _compose_supporting_line(
    reaction: SupportingReactionBeat,
    *,
    primary_name: str,
    style_hints: ToneExampleStyleHints | None,
) -> str:
    beat = reaction.beat
    reason_family = _supporting_reason_family(reaction, style_hints)
    cost_family = style_hints.cost_family if style_hints is not None else "mixed"
    cadence = style_hints.cadence if style_hints is not None else "mixed"
    reason_clause = _supporting_reason_clause(
        reaction,
        primary_name=primary_name,
        reason_family=reason_family,
        style_hints=style_hints,
    )
    signal_clause = _supporting_signal_clause(beat, reaction, style_hints=style_hints)
    cost_clause = _supporting_cost_clause(beat, cost_family=cost_family)
    skeleton = _CausalClauseSkeleton(
        reason_clause=reason_clause,
        signal_clause=signal_clause,
        cost_clause=cost_clause,
    )
    strategic_line = _strategic_intent_line(reaction, primary_name=primary_name)
    parts = [_render_causal_clause_chain(skeleton, cadence=cadence, max_length=4000)]
    if strategic_line:
        parts.append(strategic_line)
    return trim_text("".join(parts), 4000)


def _support_line(reaction: SupportingReactionBeat, *, primary_name: str, style_hints: ToneExampleStyleHints | None = None) -> str:
    return _compose_supporting_line(reaction, primary_name=primary_name, style_hints=style_hints)


def _key_segment_payoff_skeleton(
    beat: NpcReactionBeat,
    *,
    style_hints: ToneExampleStyleHints | None,
) -> _CausalClauseSkeleton:
    if beat.fallout_vector == "exposure":
        reason_clause = "这拍已经不是试探，最不该见光的东西正在直接回咬。"
    elif beat.fallout_vector == "irreversible_stance":
        reason_clause = "这拍之后站位已经开始固化，后手空间明显变窄。"
    elif beat.fallout_vector == "alliance":
        reason_clause = "这拍把关系链直接推成了认边链，后面每句都要算站位账。"
    else:
        reason_clause = "这拍已经完成落锤，后果开始接管场面节奏。"
    pseudo_reaction = SupportingReactionBeat(
        role="counter",
        beat=beat,
        seed=NarrationRenderSeed(
            character_id=beat.target_id,
            turn_index=1,
            segment_role="reveal",
            move_family="public_reveal",
            scene_frame=beat.scene_pressure.visibility_level,
        ),
    )
    signal_clause = _supporting_signal_clause(beat, pseudo_reaction, style_hints=style_hints)
    cost_family = style_hints.cost_family if style_hints is not None else "mixed"
    cost_clause = _supporting_cost_clause(beat, cost_family=cost_family)
    return _CausalClauseSkeleton(
        reason_clause=reason_clause,
        signal_clause=signal_clause,
        cost_clause=cost_clause,
    )


def _key_segment_payoff_line(
    beat: NpcReactionBeat,
    *,
    style_hints: ToneExampleStyleHints | None,
) -> str:
    skeleton = _key_segment_payoff_skeleton(beat, style_hints=style_hints)
    cadence = style_hints.cadence if style_hints is not None else "mixed"
    return _render_causal_clause_chain(skeleton, cadence=cadence, max_length=520)


def _style_case_text_map(style_hints: ToneExampleStyleHints | None) -> dict[str, str]:
    if style_hints is None:
        return {}
    mapping: dict[str, str] = {}
    for case_id, text in style_hints.style_case_text_items:
        if case_id and text and case_id not in mapping:
            mapping[case_id] = text
    return mapping


def _style_case_text_for_layer(style_hints: ToneExampleStyleHints | None, layer: Literal["primary", "supporting", "fallout"]) -> str:
    case_map = _style_case_text_map(style_hints)
    for case_id, text in case_map.items():
        if case_id.startswith(f"{layer}:"):
            return text
    return ""


def _style_case_keyword(style_hints: ToneExampleStyleHints | None, *, fallback: str) -> str:
    sampler = _ACTIVE_VARIANT_SAMPLER.get()
    candidates = tuple(style_hints.style_case_keywords) if style_hints is not None else ()
    if not candidates:
        return fallback
    if sampler is None:
        return candidates[0]
    return sampler.sample_phrase(candidates, fallback=candidates[0] or fallback) or fallback


def _compact_style_case_excerpt(text: str, *, fallback: str) -> str:
    stripped = trim_text((text or "").strip(), 120)
    if not stripped:
        return fallback
    for splitter in ("。", "，", "；", "、", "！", "？"):
        if splitter in stripped:
            fragment = stripped.split(splitter, 1)[0].strip()
            compact = trim_text(fragment, 14)
            return compact if compact else fallback
    compact = trim_text(stripped, 14)
    return compact if compact else fallback


def _reason_family_surface_label(reason_family: str) -> str:
    mapping = {
        "loss_position": "守位抢序",
        "self_preserve": "先护的是自己",
        "old_debt": "借旧账回手",
        "blame_shift": "切锅甩压",
        "opportunity_window": "等窗口翻盘",
        "mixed": "混合盘算",
    }
    return mapping.get(reason_family, "看风向")


def _style_case_fallout_slot_options(
    *,
    beat: NpcReactionBeat,
    case_fallout: str,
    shell_token: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    event_options = (
        f"{case_fallout}。",
        f"{shell_token}那边已经把这拍记进下一轮版本。",
        f"这一下的后果先落地，解释反而慢了半拍。",
        f"{beat.target_name}这步的余波已经从场内滚到场外。",
    )
    diffusion_options = (
        f"{shell_token}和关系圈会把它继续放大。",
        "这股风向不会停在原地，熟人圈会继续二次转述。",
        "它会沿着站队线继续扩散，谁都很难装作没看见。",
        "外圈会先用这拍给你们重新贴标签。",
    )
    cost_options = (
        "第一层代价先落在发言顺序和关系信用。",
        "代价先砸在解释权，第二层才轮到情绪账。",
        "真正变贵的是回撤代价，下一句都会被放大。",
        "这笔代价不会一次结清，而是会持续传导。",
    )
    uncertainty_options = (
        "现在没人敢保证下个回合还能按原计划走。",
        "后面谁先失手，已经不是谁说了算。",
        "下一拍更像会逼出更硬的站位动作。",
        "这一口余波还没到顶，真正的翻面还在后面。",
    )
    return event_options, diffusion_options, cost_options, uncertainty_options


def _style_case_fallout_line(
    *,
    beat: NpcReactionBeat,
    seed: NarrationRenderSeed,
    style_hints: ToneExampleStyleHints | None,
    shell_token: str,
    case_fallout: str,
    recent_pattern_fingerprints: tuple[str, ...],
) -> tuple[str, int]:
    event_options, diffusion_options, cost_options, uncertainty_options = _style_case_fallout_slot_options(
        beat=beat,
        case_fallout=case_fallout,
        shell_token=shell_token,
    )
    recent_patterns = {item for item in recent_pattern_fingerprints if item}
    pattern_guard_hits = 0
    fallback_line = ""
    redact_terms = [
        beat.target_name,
        beat.arena_name,
        shell_token,
        *(tuple(style_hints.anchor_tokens[:6]) if style_hints is not None else ()),
    ]
    for attempt in range(6):
        event = _pick(event_options, seed=seed, slot_name=f"style_case_fallout_event_{attempt}")
        diffusion = _pick(diffusion_options, seed=seed, slot_name=f"style_case_fallout_diffusion_{attempt}")
        cost = _pick(cost_options, seed=seed, slot_name=f"style_case_fallout_cost_{attempt}")
        uncertainty = _pick(uncertainty_options, seed=seed, slot_name=f"style_case_fallout_uncertainty_{attempt}")
        line = trim_text(f"{event}{diffusion}{cost}{uncertainty}", 4000)
        fallback_line = fallback_line or line
        pattern = pattern_fingerprint(line, redact_terms=tuple(redact_terms))
        if pattern and pattern not in recent_patterns:
            return line, pattern_guard_hits
        pattern_guard_hits += 1
    return fallback_line or trim_text(f"{case_fallout}。后果会持续传导。", 4000), pattern_guard_hits


def _style_case_narration_lines(
    *,
    beat: NpcReactionBeat,
    seed: NarrationRenderSeed,
    style_hints: ToneExampleStyleHints | None,
    supporting_reactions: tuple[SupportingReactionBeat, ...],
    include_support: bool,
    recent_pattern_fingerprints: tuple[str, ...] = (),
) -> tuple[list[str], int]:
    case_primary = _compact_style_case_excerpt(
        _style_case_text_for_layer(style_hints, "primary"),
        fallback=f"{beat.target_name}先露了半寸口风",
    )
    case_support = _compact_style_case_excerpt(
        _style_case_text_for_layer(style_hints, "supporting"),
        fallback=f"{beat.target_name}旁边的人开始算账",
    )
    case_fallout = _compact_style_case_excerpt(
        _style_case_text_for_layer(style_hints, "fallout"),
        fallback="外圈很快会把这拍当成定性",
    )
    shell_token = _style_anchor(
        style_hints,
        "镜头",
        "热搜",
        "公屏",
        "台下",
        "评审",
        "名额",
        "主桌",
        "顺位",
        layer="fallout",
    ) or ("镜头" if beat.shell_id == "entertainment_scandal" else "台下" if beat.shell_id == "campus_romance" else beat.arena_name)
    keyword = _style_case_keyword(style_hints, fallback="风向")
    pressure_phrase = {
        "low": "还没翻桌，但气压已经拧紧",
        "rising": "局面正在被推向更难回头的位置",
        "high": "场上已经有人开始提前找退路",
        "critical": "所有人都知道下一句会直接改写关系链",
    }.get(beat.scene_pressure.pressure_level, "气压已经变重")
    mask_phrase = {
        "holding": "还想把那层体面撑住",
        "cracking": "表面的镇定已经开始漏风",
        "cornered": "整个人像被逼到只剩硬撑",
        "broken": "最后那层遮掩已经掉干净",
    }.get(beat.mask_state, "表情已经先露底")
    impulse_phrase = {
        "protect": f"心里第一反应还是护住你这条线",
        "betray": "脑子已经在算该先反手卖谁、把锅甩给谁",
        "confess": "那点想自己说破的冲动已经顶到喉咙口，像随时会把底线和旧事都说出来",
        "retaliate": "下一步更像会挑最痛的位置回手",
        "control": f"她最怕失去的是{beat.status_need_hint}",
        "deflect": "她还在找能把真正疼点藏回去的缝",
    }.get(beat.dominant_impulse, "她的真实意图已经很难再藏")
    tone_signature = {
        "razor": "她的锋口已经抬起来，旁人明显不敢接茬。",
        "soft_hook": "她仍然用软钩子的方式拉人，越轻越让人上瘾。",
        "smiling_blade": "她还挂着笑，笑里带刺，像在哄人时顺手下套。",
        "measured": "她把每句都收得很稳，像在冷静地给后果排顺序。",
        "slow_pressure": "她不抢话，但压迫感在一寸寸往前推。",
        "restrained": "她把情绪按住了，克制本身反而更危险。",
    }.get(beat.character_tone, "她的口吻已经和刚才完全不同。")
    relation_signature = {
        "selling_out": "她已经在盘算反手卖人和甩锅路线。",
        "locking_side": "她的动作明显在把关系往同一边锁死。",
        "pulling_back": "她在往后撤，像随时会切断原有信任。",
        "leaning_closer": "她还在往你这边靠，说明这条线没断。",
    }.get(beat.relation_shift, "")
    anchor_line = _pick(
        (
            f"你这步刚落下，{pressure_phrase}，{case_primary}这股味道已经先浮出来。",
            f"{beat.arena_name}里先静了一拍，{beat.target_name}{mask_phrase}，{case_primary}已经把气氛推偏。",
            f"你把节奏往疼处一拧，{keyword}这条线立刻被点亮，{case_primary}不再只是暗流。",
        ),
        seed=seed,
        slot_name="style_case_anchor",
    )
    cost_subject_clause = _cost_subject_main_clause(style_hints)
    if cost_subject_clause:
        anchor_line = trim_text(f"{cost_subject_clause}{anchor_line}", 4000)
    visible_line = _pick(
        (
            f"{beat.target_name}{mask_phrase}，说话里那层{beat.speech_texture_hint}比刚才更明显。{tone_signature}{relation_signature}",
            f"{beat.target_name}还想稳场，可每个停顿都在泄露{keyword}焦虑。{tone_signature}{relation_signature}",
            f"她表面没失控，但眼神和语速已经把{keyword}这层真实立场漏出来。{tone_signature}{relation_signature}",
        ),
        seed=seed,
        slot_name="style_case_visible",
    )
    inner_line = _pick(
        (
            f"她心里其实在想：{impulse_phrase}，而不是继续装作没事。",
            f"那股要先保住{beat.status_need_hint}的本能没退，反而把每句都压得更硬。",
            f"{impulse_phrase}，所以这拍之后她很难再走回中立。",
        ),
        seed=seed,
        slot_name="style_case_inner",
    )
    if style_hints is not None and (
        style_hints.primary_reason_family == "old_debt"
        or style_hints.counter_reason_family == "old_debt"
        or style_hints.crowd_reason_family == "old_debt"
        or style_hints.fallout_reason_family == "old_debt"
    ) and "旧账" not in inner_line:
        inner_line = trim_text(f"{inner_line}旧账这口气已经翻上台面。", 4000)
    support_lines: list[str] = []
    if include_support:
        for index, reaction in enumerate(supporting_reactions[:2], start=1):
            support_reason = _reason_family_surface_label(
                reaction.reason_family or ("counter" if reaction.role == "counter" else "crowd")
            )
            support_tag = "对冲" if reaction.role == "counter" else "围观"
            support_lines.append(
                _pick(
                    (
                        f"{reaction.beat.target_name}这拍更像在做{support_tag}动作：{support_reason}，再看谁先掉位。",
                        f"{reaction.beat.target_name}没有替任何人收尾，反而顺着{case_support}把压力继续往外推。",
                        f"{reaction.beat.target_name}盯着的不是情绪，而是{shell_token}和关系账谁先定性。",
                    ),
                    seed=seed,
                    slot_name=f"style_case_support_{index}",
                )
            )
    fallout_line, pattern_guard_hits = _style_case_fallout_line(
        beat=beat,
        seed=seed,
        style_hints=style_hints,
        shell_token=shell_token,
        case_fallout=case_fallout,
        recent_pattern_fingerprints=recent_pattern_fingerprints,
    )
    if style_hints is not None and style_hints.anchor_tokens and not any(token in fallout_line for token in style_hints.anchor_tokens):
        shell_anchor_whitelist = {
            "entertainment_scandal": {"镜头", "热搜", "公关", "切割", "公屏"},
            "campus_romance": {"台下", "评审", "社团", "熟人", "站队", "名额"},
            "office_power": {"会议室", "会议桌", "席位", "口风", "主桌"},
            "wealth_families": {"主桌", "顺位", "家宴", "继承"},
        }.get(beat.shell_id, set())
        fallback_anchor = next(
            (token for token in style_hints.anchor_tokens if token in shell_anchor_whitelist),
            shell_token,
        )
        if fallback_anchor:
            fallout_line = trim_text(f"{fallout_line}{fallback_anchor}已经把这拍记成了新坐标。", 4000)
    return [anchor_line, visible_line, inner_line, *support_lines, fallout_line], pattern_guard_hits


def _resolve_texture_verbosity(
    *,
    beat: NpcReactionBeat,
    seed: NarrationRenderSeed,
    sampler: NarrationVariantSampler,
    verbosity_hint: Literal["adaptive", "short", "medium", "long"],
) -> Literal["short", "medium", "long"]:
    if verbosity_hint in {"short", "medium", "long"}:
        return verbosity_hint
    if seed.segment_role in {"reveal", "terminal"} or beat.scene_pressure.pressure_level == "critical" or beat.scene_pressure.public_event_active:
        return "long" if sampler.rng.random() < 0.7 else "medium"
    if beat.scene_pressure.visibility_level == "private" and beat.scene_pressure.scene_heat <= 2:
        return "short" if sampler.rng.random() < 0.7 else "medium"
    roll = sampler.rng.random()
    if roll < 0.3:
        return "short"
    if roll < 0.85:
        return "medium"
    return "long"


def _voice_atom_line(atom: VoiceAtom, beat: NpcReactionBeat) -> str:
    line = trim_text(atom.line_stub, 220)
    if "{target}" in line:
        line = line.replace("{target}", beat.target_name)
    if "{arena}" in line:
        line = line.replace("{arena}", beat.arena_name)
    if atom.catchphrase_hint and atom.catchphrase_hint not in line and len(line) <= 170:
        line = trim_text(f"{line}{atom.catchphrase_hint}", 220)
    return line


def _inject_voice_atoms(
    *,
    lines: list[str],
    voice_atoms: tuple[VoiceAtom, ...],
    beat: NpcReactionBeat,
    sampler: NarrationVariantSampler,
) -> tuple[list[str], str]:
    if not voice_atoms:
        return lines, "voice_atoms_missing"
    ordered = sorted(voice_atoms, key=lambda atom: (-float(atom.weight), atom.atom_id))
    chosen = ordered[0]
    line = _voice_atom_line(chosen, beat)
    if not line:
        return lines, "voice_atom_empty_line"
    insert_index = 1 if len(lines) >= 2 else 0
    if len(lines) >= 4 and sampler.rng.random() < 0.5:
        insert_index = 2
    updated = [*lines]
    updated.insert(insert_index, line)
    return updated[:6], "none"


def render_npc_texture_v2(
    beat: NpcReactionBeat,
    seed: NarrationRenderSeed,
    *,
    supporting_reactions: tuple[SupportingReactionBeat, ...] = (),
    voice_atoms: tuple[VoiceAtom, ...] = (),
    style_hints: ToneExampleStyleHints | None = None,
    recent_fingerprints: tuple[str, ...] = (),
    recent_pattern_fingerprints: tuple[str, ...] = (),
    hard_block_terms: tuple[str, ...] = (),
    verbosity_hint: Literal["adaptive", "short", "medium", "long"] = "adaptive",
    diagnostics: dict[str, int | str] | None = None,
) -> str:
    style_block_terms = tuple(style_hints.blocked_stems) if style_hints is not None else ()
    sampler = NarrationVariantSampler(
        recent_fingerprints=recent_fingerprints,
        hard_block_terms=(*DEFAULT_HARD_BLOCK_TERMS, *style_block_terms, *hard_block_terms),
    )
    context_token = _ACTIVE_VARIANT_SAMPLER.set(sampler)
    try:
        verbosity = _resolve_texture_verbosity(
            beat=beat,
            seed=seed,
            sampler=sampler,
            verbosity_hint=verbosity_hint,
        )
        include_support = verbosity != "short"
        lines, pattern_guard_hits = _style_case_narration_lines(
            beat=beat,
            seed=seed,
            style_hints=style_hints,
            supporting_reactions=supporting_reactions,
            include_support=include_support,
            recent_pattern_fingerprints=recent_pattern_fingerprints,
        )
        lexicon_line = _role_lexicon_line(beat, style_hints)
        payoff_line = _key_segment_payoff_line(beat, style_hints=style_hints) if seed.segment_role in {"reveal", "terminal"} else None
        if verbosity == "short":
            short_fallout = lines[-1]
            fallout_parts = [item.strip() for item in short_fallout.split("。") if item.strip()]
            if len(fallout_parts) > 2:
                short_fallout = "。".join(fallout_parts[:2]) + "。"
            short_lines = [lines[0], short_fallout]
            if beat.dominant_impulse in {"confess", "betray", "retaliate"} or sampler.rng.random() < 0.35:
                short_lines.insert(1, lines[2])
            lines = short_lines[:3]
        elif verbosity == "long":
            long_lines = [lines[0]]
            if lexicon_line:
                long_lines.append(lexicon_line)
            long_lines.extend(lines[1:3])
            if len(lines) > 4:
                long_lines.extend(lines[3:-1][:2])
            if payoff_line:
                long_lines.append(payoff_line)
            long_lines.append(lines[-1])
            if len(long_lines) > 6:
                middle = long_lines[1:-1][-4:]
                long_lines = [long_lines[0], *middle, long_lines[-1]]
            lines = long_lines
        else:
            medium_lines = [lines[0], lines[1], lines[2], lines[-1]]
            if len(lines) > 4 and sampler.rng.random() < 0.5:
                medium_lines.insert(3, lines[3])
            if lexicon_line and sampler.rng.random() < 0.55:
                medium_lines.insert(1, lexicon_line)
            if payoff_line and sampler.rng.random() < 0.65:
                medium_lines.insert(3, payoff_line)
            lines = medium_lines[:5]
        lines, voice_fallback_reason = _inject_voice_atoms(
            lines=lines,
            voice_atoms=voice_atoms,
            beat=beat,
            sampler=sampler,
        )
        text = trim_text("".join(lines), 4000)
        if "代价" not in text and "成本" in text:
            text = text.replace("成本", "代价", 1)
        if seed.segment_role in {"reveal", "terminal"} and "代价" not in text:
            text = trim_text(f"{text}这拍的代价已经开始明码计价。", 4000)
        forbidden = list(beat.forbidden_raw_phrases)
        for reaction in supporting_reactions:
            forbidden.extend(reaction.beat.forbidden_raw_phrases)
        if _contains_forbidden(text, forbidden):
            if diagnostics is not None:
                diagnostics["fallback_reason"] = "forbidden_raw_phrase"
                diagnostics["selected_voice_atom_ids"] = ",".join(atom.atom_id for atom in voice_atoms[:2])
                diagnostics["voice_fallback_reason"] = "forbidden_raw_phrase"
            return trim_text(
                f"{beat.target_name}这拍已经被推离安全区，下一句不是解释，而是要承担谁先付代价。",
                4000,
            )
        if diagnostics is not None:
            diagnostics["style_case_ids"] = ",".join(style_hints.style_case_ids) if style_hints is not None else ""
            diagnostics["diversity_guard_hits"] = int(sampler.diversity_guard_hits)
            diagnostics["pattern_guard_hits"] = int(pattern_guard_hits)
            diagnostics["length_profile"] = f"{verbosity}:{len(lines)}"
            diagnostics["blocked_stems"] = ",".join(style_block_terms[:6])
            diagnostics["selected_voice_atom_ids"] = ",".join(atom.atom_id for atom in voice_atoms[:2])
            diagnostics["voice_fallback_reason"] = voice_fallback_reason
            diagnostics["fallback_reason"] = "none"
        return text
    finally:
        _ACTIVE_VARIANT_SAMPLER.reset(context_token)


def render_npc_texture_emergency(
    beat: NpcReactionBeat,
    seed: NarrationRenderSeed,
    *,
    reason: str | None = None,
) -> str:
    pressure = {
        "low": "轻压",
        "rising": "升压",
        "high": "高压",
        "critical": "临界高压",
    }.get(beat.scene_pressure.pressure_level, "高压")
    frame = "公开场" if beat.scene_pressure.visibility_level == "public" else "半公开场" if beat.scene_pressure.visibility_level == "semi_public" else "私域场"
    segment_note = (
        "这拍先把关系账和后果账一起点亮，代价已经开始往外传。"
        if seed.segment_role in {"reveal", "terminal"}
        else "这拍先把关系线拉紧，后果会继续外溢。"
    )
    reason_hint = trim_text(str(reason or "").strip(), 80)
    tail = f"（{reason_hint}）" if reason_hint else ""
    return trim_text(
        f"{beat.target_name}在{frame}被推入{pressure}区，你这一手让站位和解释权同时变硬。{segment_note}{tail}",
        4000,
    )
