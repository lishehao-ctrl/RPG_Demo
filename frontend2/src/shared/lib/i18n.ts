// Lightweight i18n layer for Tiny Stories.
//
// Two locales today: "zh" (canonical) and "en" (mirror). The active
// locale is stored in localStorage under `tiny-stories-lang` and
// exposed via the `LanguageProvider` context.
//
// Usage:
//   import { useLanguage } from "../../shared/lib/i18n"
//   const { lang, setLang, t } = useLanguage()
//   <h1>{t("home.hero_title")}</h1>
//
// Adding a new key: append it to STRINGS_ZH and STRINGS_EN with the
// same key. If a key is missing in the active locale, the hook falls
// back to zh, then to the literal key (so you'll see the key string
// on screen and know to fix it).
//
// Adding a new locale: add a new STRINGS_XX bundle, expand the Lang
// union, list it in LANGUAGE_OPTIONS, and add a prompt-language branch
// in `rpg_backend/narrative/engine.py`.

import { createContext, createElement, useContext, useEffect, useMemo, useState, type ReactNode } from "react"

export type Lang = "zh" | "en"

export const LANGUAGE_OPTIONS: ReadonlyArray<{ value: Lang; label: string }> = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
]

const STORAGE_KEY = "tiny-stories-lang"
const DEFAULT_LANG: Lang = "zh"

// ---------------------------------------------------------------------------
// String bundles. Keep keys in dot.notation, grouped by surface.
//
// Convention:
//   <surface>.<role>     e.g. "header.write_story"
//   <surface>.<role>_v2  if you need to break out a variant
//
// Pluralization / interpolation: keep it simple for now. If you need
// {count} substitutions, prefer formatting at the call site or extend
// the `t()` helper to take a record of placeholders.
// ---------------------------------------------------------------------------

export const STRINGS_ZH = {
  // Header / global navigation
  "header.write_story": "写一个故事",
  "header.login": "登录",
  "header.logout": "退出登录",
  "header.signout": "退出",
  "header.my_worlds": "我的故事",
  "header.lang_label": "语言",

  // Generic actions
  "action.back_home": "返回首页",
  "action.cancel": "取消",
  "action.confirm": "确定",
  "action.retry": "重试",
  "action.share": "分享",
  "action.continue": "继续",
  "action.loading": "加载中…",

  // Errors
  "error.generic": "出了点问题,请稍后再试.",
  "error.network": "网络异常,请检查连接.",
  "error.session_expired": "会话已过期,请重新登录.",

  // Home page
  "home.hero_tagline": "互动短剧 · 你来决定",
  "home.hero_title_l1": "一句话起头,",
  "home.hero_title_l2": "AI 给你一整集短剧.",
  "home.hero_sub": "15 分钟一局 · 朋友们玩同一个开场,看谁玩出什么结局.",
  "home.hero_bullet_1": "写一个戏剧瞬间,AI 立刻搭起场景、人物、第一段",
  "home.hero_bullet_2": "每回合 300 字叙述 + 选项 / 自由输入",
  "home.hero_bullet_3": "右下角私聊\"局外人朋友\" — TA 不替你做决定,会陪你想清楚",
  "home.hero_bullet_4": "结局可分享,可看朋友走出什么版本",
  "home.cta_create": "写一个新故事 →",
  "home.tab_plaza": "广场",
  "home.tab_my": "我创建的",
  "home.section_in_progress": "继续未完成的故事",
  "home.section_completed": "我玩完的故事",
  "home.empty_plaza": "还没有公开作品.写一个让所有人来玩?",
  "home.empty_my": "你还没有创建过故事.",
  "home.error_plaza": "广场加载失败.",
  "home.session_completed_meta": "完结",
  "home.session_progress_meta": "第 {current} / {total} 段",
  "home.played_count": "· 已玩 {count} 局",
  "home.is_owner": "我创建的",
  "home.visibility_public": "公开",
  "home.visibility_unlisted": "凭链接",
  "home.visibility_private": "只有我",
  "home.relative_just_now": "刚刚",
  "home.relative_minutes": "{n} 分钟前",
  "home.relative_hours": "{n} 小时前",
  "home.relative_days": "{n} 天前",
  "home.footer_about": "关于 / 隐私",
  "home.footer_contact": "联系我们",

  // Create page
  "create.title": "写一个故事",
  "create.seed_label": "故事开头",
  "create.seed_placeholder": "豪门年夜饭你回到家,妻子笑得太多",
  "create.mode_label": "玩法",
  "create.mode_story": "故事(无失败)",
  "create.mode_gauntlet": "博弈(可触发 collapse 结局)",
  "create.lang_label": "故事语言",
  "create.lang_help": "决定 NPC 对话和叙事文本用哪种语言生成",
  "create.submit": "开始写",
  "create.generating": "生成中,大约 12-20 秒",

  // === create page (v2 layout) ===
  "create.tag_new": "新故事",
  "create.heading_l1": "写下开头，",
  "create.heading_l2": "剩下的交给 AI。",
  "create.subhead": "一句话即可。AI 会为你搭好人物、关系、第一个戏剧时刻——然后你立刻接手往下玩。",
  "create.placeholder": "写一句故事的开端，越具体越好。\n\n比如：年会前夜，老板把我和实习生关在同一间会议室。\n或者：婚礼当天，伴娘的礼服里塞着一封我妹妹的字条。\n\nAI 会立刻为你搭起人物、关系、第一个戏剧时刻。",
  "create.char_count": "{n} 字",
  "create.examples_label": "试试这些：",
  "create.example_seed_1": "公司年会的红毯上，前任的现任搂着前任向我走来。",
  "create.example_seed_2": "分手那天晚上，他给我妹妹打了一通电话。",
  "create.example_seed_3": "我前任在我新公司当 HR，今天发了我的入职合同。",
  "create.example_seed_4": "高中重逢，发现初恋已经成了我妹妹的男朋友。",
  "create.field_budget": "篇幅",
  "create.budget_short_label": "短",
  "create.budget_short_time": "10 分钟",
  "create.budget_short_desc": "一个戏剧瞬间，节奏紧凑",
  "create.budget_medium_label": "中",
  "create.budget_medium_time": "15 分钟",
  "create.budget_medium_desc": "一集短剧，起承转合完整",
  "create.budget_long_label": "长",
  "create.budget_long_time": "25 分钟",
  "create.budget_long_desc": "多线索铺陈，情绪深入",
  "create.field_difficulty": "难度",
  "create.difficulty_story_label": "故事模式",
  "create.difficulty_story_tagline": "适合放松看戏",
  "create.difficulty_story_desc": "你不会真正失败，故事一定会走到一个完整结局。",
  "create.difficulty_gauntlet_label": "博弈模式",
  "create.difficulty_gauntlet_tagline": "NPC 主动跟你斗",
  "create.difficulty_gauntlet_desc": "NPC 各有目标和把柄。你可能在第 5 回合就翻车——结局也分胜利、妥协、崩盘三档。",

  // === world detail page ===
  "world.error_template_missing": "故事不见了。",
  "world.error_start_failed": "开始游戏失败，请重试。",
  "world.error_visibility_failed": "可见性修改失败。",
  "world.empty_title": "找不到这个故事",
  "world.empty_back": "回广场",
  "world.loading": "正在拉取这个故事…",
  "world.crumb_back_home": "← 回到首页",
  "world.played_count": "已被玩 {count} 局",
  "world.is_owner": "我创建的",
  "world.section_seed": "原始种子",
  "world.section_cast": "出场人物",
  "world.cast_holds_leverage": "握着 {count} 张别人的把柄",
  "world.network_label": "暗藏的把柄网络",
  "world.network_hint": "整局戏里 NPC 之间相互捏着把柄。看清这张网，你就能挑拨他们互撕。",
  "world.section_failure": "红线 · 这一局可能让你提前出局",
  "world.failure_hint": "触碰任意一条会触发 GAME OVER（崩盘结局）。事先看一眼，玩的时候才知道哪些动作不能轻易做。",
  "world.section_advisor": "你的局外人朋友",
  "world.section_endings": "玩家走出来的结局 · 共 {count} 局完结",
  "world.endings_hint": "你能玩出哪个？或者一个还没人走过的？",
  "world.section_roles": "选你的身份",
  "world.roles_hint": "同一个故事，不同的\"你\"。处境、目的、手里的牌都不同——选哪张走哪条路。",
  "world.start_busy": "开始中…",
  "world.start_cta": "开始一局新故事 →",
  "world.start_hint": "每个人的玩法都不同，开局相同，剧情走向取决于你。",
  "world.section_visibility": "谁能玩",
  "world.visibility_public": "广场公开",
  "world.role_tag_persona": "外人眼中的你",
  "world.role_summary_counters": "⚔ {count} 张反将牌",
  "world.role_summary_assets": "💼 {count} 件初始物品",
  "world.role_objective_label": "你心里真正想要的",
  "world.role_sub_leverages": "你手里的反将牌",
  "world.role_sub_assets": "开局握着",
  "world.role_card_cta": "选这个身份开始 →",
  "create.field_story_lang": "故事语言 / Story language",
  "create.field_visibility": "谁能玩这个故事",
  "create.visibility_private_label": "只有我",
  "create.visibility_private_desc": "只有你能玩这个故事",
  "create.visibility_unlisted_label": "凭链接",
  "create.visibility_unlisted_desc": "把链接发给朋友，他们能玩出自己的剧情",
  "create.visibility_public_label": "广场公开",
  "create.visibility_public_desc": "任何人都能看到、玩你的故事",
  "create.error_seed_required": "先写一句开头吧。",
  "create.error_create_failed": "无法创建故事，请稍后再试。",
  "create.cta_idle": "开始这个故事 →",
  "create.cta_busy": "AI 正在搭建故事...",
  "create.cta_back": "返回",
  "create.busy_tip_1": "在为你的种子挑选 3-5 个角色，每人都有秘密…",
  "create.busy_tip_2": "在搭建 NPC 之间相互捏着的把柄网络…",
  "create.busy_tip_3": "在为你准备 3 张玩家身份卡——每张走向不同的故事…",
  "create.busy_tip_4": "在写下开场的第一个戏剧瞬间…",
  "create.busy_tip_5": "在校对人物动机和关系合理性…",

  // Login page
  "login.tag": "登录",
  "login.title": "你叫什么?",
  "login.sub": "随便起个用户名,没有密码.",
  "login.placeholder": "比如 shehao",
  "login.submit_idle": "进入",
  "login.submit_busy": "进入中…",
  "login.error_username_format": "用户名 2-20 字符,只能用字母、数字、下划线.",
  "login.error_generic": "登录失败,请稍后再试.",
  "login.note": "这是测试期,没有密码、没有邮箱.下个月会改成正式登录.",

  // Play page — shared / generic
  "play.input_action_placeholder": "你做了什么…",
  "play.input_diary_placeholder": "你心里在想什么(NPC 看不到)",
  "play.option_pick_prefix": "选项",
  "play.advisor_open": "找朋友聊聊",
  "play.advisor_oracle": "🔮 用 1 回合换情报",
  "play.turn_remaining": "剩余回合",
  "play.send": "送出",
  "play.thinking": "推进中…",
  "play.ending_share": "复制分享链接",
  "play.ending_replay": "再玩一局",
  "play.highlights_title": "5 个关键时刻",
  "play.branches_title": "你没走过的路",

  // Play page — page chrome / loading / errors
  "play.back_home": "← 回到首页",
  "play.load_failed": "加载失败：{error}",
  "play.loading_story": "故事正在加载…",
  "play.busy_shim": "故事在续写中…",
  "play.error_load_story": "无法加载故事。",
  "play.error_advance": "续写失败，请稍后再试。",
  "play.header_turn_count": "· 第 {current} / 共 {total} 段",

  // Play page — pulse legend (NPC mood chips)
  "play.pulse_legend_aria": "NPC 情绪图例",
  "play.pulse_legend_label": "NPC 情绪",
  "play.pulse_warmer": "倾向你",
  "play.pulse_colder": "冷下来",
  "play.pulse_wary": "起疑",
  "play.pulse_broken": "崩塌",
  "play.pulse_steady": "未变",
  "play.pulse_reason_prefix": "因为：{reason}",

  // Play page — role banner (the "you" card)
  "play.role_you_tag": "这一局的你",
  "play.role_secret_objective": "心里真正想要的",
  "play.role_secret_leverage": "你手里的反将牌",
  "play.role_inventory": "手里的牌（{count}）",

  // Play page — gauntlet goals card
  "play.gauntlet_badge": "博弈模式",
  "play.gauntlet_goals_title": "你这一局想要的：",
  "play.gauntlet_goal_stakes": "失败：{stakes}",

  // Play page — finale-approaching banners
  "play.finale_wrapping": "故事正在收尾…",
  "play.finale_one_left": "下一段就是结局——慎选。",
  "play.finale_two_left": "还有 2 段就到结局——开始往那个方向收吧。",

  // Play page — share fallback prompt
  "play.share_prompt": "复制这个链接发给朋友：",

  // Play page — story-beat decorations
  "play.beat_chosen_label": "你选了",
  "play.beat_inv_added": "你拿到：{item}",
  "play.beat_inv_removed": "你失去了：{item}",
  "play.beat_player_label": "你",
  "play.beat_diary_tag": "内心独白",

  // Play page — action area (options + free input + diary)
  "play.action_no_options": "（这一段没给选项，写下你想做的事）",
  "play.action_free_placeholder": "写下你想做的事——可以是动作、对话、或者一个决定。",
  "play.action_busy": "续写中…",
  "play.action_submit": "就这么做 →",
  "play.action_cancel": "取消",
  "play.action_open_free": "+ 我想自己写一个动作",
  "play.diary_label_hint": "只有你和叙述者看得到 · NPC 听不到 · 跟下一个动作一起提交",
  "play.diary_placeholder": "你心里真正在想什么？（30-200 字最佳，留空就是不写）",
  "play.diary_close": "取消独白",
  "play.diary_open": "+ 写一句内心独白（NPC 看不到）",

  // Play page — advisor sidechat (FAB + panel)
  "play.fab_label": "聊聊",
  "play.advisor_title": "跟你的局外人朋友聊",
  "play.advisor_intro": "问 TA 任何事——你和谁的关系到了哪一步、那句话什么意思、你是不是太冲动了。TA 不会替你做决定，但会陪你想清楚。",
  "play.advisor_textarea_placeholder": "想问什么？按 ⌘/Ctrl + Enter 发送",
  "play.advisor_send": "发送",
  "play.advisor_history_failed": "顾问历史加载失败。",
  "play.advisor_ask_failed": "顾问没回上你这一句，再试一次？",
  "play.oracle_button": "🔮 用 1 回合换情报",
  "play.oracle_badge": "🔮 情报 · 消耗了 1 回合",
  "play.oracle_completed_error": "这一局已经走完了，不能再消耗回合换情报。",
  "play.oracle_confirm": "用 1 回合换 advisor 的\"看穿\"提示？\n\n• 这会让你少 1 回合时间（剩余 {before} → {after}）\n• advisor 会拿到只有 TA 才能看到的局势线索\n• 但 advisor 还是不会替你做决定\n\n继续？",
  "play.oracle_tip_complete": "故事已结束",
  "play.oracle_tip_no_turns": "回合不足，无法换情报",
  "play.oracle_tip_active": "用 1 回合换 advisor 的看穿（剩 {turns} 回合）",

  // Play page — ending screen
  "play.ending_ribbon_victory": "胜利结局",
  "play.ending_ribbon_compromised": "妥协结局",
  "play.ending_ribbon_collapsed": "崩盘结局",
  "play.ending_ribbon_early": "提前崩盘",
  "play.ending_trigger_prefix": "· 触发：{trigger}",
  "play.ending_highlights_title": "这一局的关键 {count} 个时刻",
  "play.ending_branches_title": "你没走的另外 {count} 条路",
  "play.ending_branches_hint": "如果当时换个选择，故事大概率会走向这些结局。再玩一次试试？",
  "play.ending_branch_turn": "第 {turn} 回合",
  "play.ending_branch_chosen_tag": "你那回合选了",
  "play.ending_branch_arrow": "↓ 但如果选了 ↓",
  "play.ending_branch_alt_tag": "另一条路",
  "play.ending_share_copied": "✓ 链接已复制",
  "play.ending_share_hint": "把链接发给朋友 — 他们能玩同一个开场，看自己会走出什么结局。",

  // Stage labels (textual descriptions)
  "stage.hook": "开场",
  "stage.pressure": "施压",
  "stage.reversal": "翻转",
  "stage.climax": "高潮",
  "stage.pre_finale": "终局前",

  // Stage progress bar — short visual labels
  "stage_bar.hook": "序幕",
  "stage_bar.pressure": "升压",
  "stage_bar.reversal": "转折",
  "stage_bar.climax": "高潮",
  "stage_bar.pre_finale": "收束",
  "stage_bar.aria": "第 {turn} 回合，共 {total} 回合，当前阶段：{stage}",

  // === replay page ===
  "replay.error_load_failed": "回放加载失败。",
  "replay.error_title": "这一局看不见了",
  "replay.error_back_plaza": "回广场",
  "replay.loading_label": "正在还原这一局…",
  "replay.crumb_back_home": "← 回到首页",
  "replay.badge": "回放",
  "replay.in_progress_meta": "进行中 · 已玩 {current} / {total} 段",
  "replay.cast_label": "出场人物",
  "replay.advisor_toggle_prefix_showing": "正在显示与 ",
  "replay.advisor_toggle_prefix_view": "查看与 ",
  "replay.advisor_toggle_advisor_word": "顾问",
  "replay.advisor_toggle_suffix": " 的私下对话（{count} 次）",
  "replay.chosen_label": "TA 选了",
  "replay.advisor_track_title": "玩家与顾问的私聊",
  "replay.player_label": "TA",
  "replay.ending_divider": "故事到这里",
  "replay.cta_hint": "想看自己能玩出什么结局？回到首页找广场上的同一个故事开个新一局。",
  "replay.cta_back_plaza": "回到广场",
} as const

type StringKey = keyof typeof STRINGS_ZH

export const STRINGS_EN: Record<StringKey, string> = {
  "header.write_story": "Write a story",
  "header.login": "Sign in",
  "header.logout": "Sign out",
  "header.signout": "Sign out",
  "header.my_worlds": "My stories",
  "header.lang_label": "Language",

  "action.back_home": "Back to home",
  "action.cancel": "Cancel",
  "action.confirm": "Confirm",
  "action.retry": "Retry",
  "action.share": "Share",
  "action.continue": "Continue",
  "action.loading": "Loading…",

  "error.generic": "Something went wrong. Please try again.",
  "error.network": "Network error. Check your connection.",
  "error.session_expired": "Session expired. Please sign in again.",

  "home.hero_tagline": "Interactive drama · You decide",
  "home.hero_title_l1": "One sentence opens it.",
  "home.hero_title_l2": "AI builds the rest of the episode.",
  "home.hero_sub": "15 min a run · friends play the same opening, see whose ending wins.",
  "home.hero_bullet_1": "Write a dramatic moment — AI sets the scene, the cast, the opening passage.",
  "home.hero_bullet_2": "Each turn: ~300 words of narration plus choices and free-form action.",
  "home.hero_bullet_3": "Side-chat your \"outsider friend\" — they won't decide for you, but they'll think it through with you.",
  "home.hero_bullet_4": "Endings are shareable. See which version your friends ended up in.",
  "home.cta_create": "Write a new story →",

  // === world detail page ===
  "world.error_template_missing": "This story isn't around anymore.",
  "world.error_start_failed": "Couldn't start a session. Try again.",
  "world.error_visibility_failed": "Couldn't update visibility.",
  "world.empty_title": "Story not found",
  "world.empty_back": "Back to plaza",
  "world.loading": "Loading this story…",
  "world.crumb_back_home": "← Back to home",
  "world.played_count": "Played {count} times",
  "world.is_owner": "Mine",
  "world.section_seed": "Original seed",
  "world.section_cast": "Cast",
  "world.cast_holds_leverage": "Holds {count} pieces of leverage",
  "world.network_label": "The leverage web",
  "world.network_hint": "NPCs hold dirt on each other. See the web — and you can play them against each other.",
  "world.section_failure": "Red lines · could end the run early",
  "world.failure_hint": "Crossing any of these triggers GAME OVER (a collapsed ending). Skim them before you start so you know which moves are too risky.",
  "world.section_advisor": "Your outsider friend",
  "world.section_endings": "Endings players have reached · {count} runs finished",
  "world.endings_hint": "Which one will you reach? Or one nobody has?",
  "world.section_roles": "Pick your identity",
  "world.roles_hint": "Same story, different \"you\". Different situation, goals, cards in hand — pick a card, walk that path.",
  "world.start_busy": "Starting…",
  "world.start_cta": "Start a new run →",
  "world.start_hint": "Same opening, different paths. Where it goes is up to you.",
  "world.section_visibility": "Who can play",
  "world.visibility_public": "Public",
  "world.role_tag_persona": "How others see you",
  "world.role_summary_counters": "⚔ {count} counter-cards",
  "world.role_summary_assets": "💼 {count} starting items",
  "world.role_objective_label": "What you actually want",
  "world.role_sub_leverages": "Your counter-cards",
  "world.role_sub_assets": "You start with",
  "world.role_card_cta": "Start as this identity →",
  "home.tab_plaza": "Plaza",
  "home.tab_my": "My stories",
  "home.section_in_progress": "Continue an unfinished story",
  "home.section_completed": "Stories I've finished",
  "home.empty_plaza": "No public stories yet. Write one for everyone to play?",
  "home.empty_my": "You haven't created a story yet.",
  "home.error_plaza": "Failed to load the plaza.",
  "home.session_completed_meta": "Finished",
  "home.session_progress_meta": "Turn {current} of {total}",
  "home.played_count": "· {count} plays",
  "home.is_owner": "Mine",
  "home.visibility_public": "Public",
  "home.visibility_unlisted": "Unlisted",
  "home.visibility_private": "Private",
  "home.relative_just_now": "just now",
  "home.relative_minutes": "{n}m ago",
  "home.relative_hours": "{n}h ago",
  "home.relative_days": "{n}d ago",
  "home.footer_about": "About / Privacy",
  "home.footer_contact": "Contact",

  "create.title": "Write a story",
  "create.seed_label": "Story seed",
  "create.seed_placeholder": "Lunar New Year dinner at the in-laws — the wife is smiling a little too much.",
  "create.mode_label": "Mode",
  "create.mode_story": "Story (no failure state)",
  "create.mode_gauntlet": "Gauntlet (can trigger a collapsed ending)",
  "create.lang_label": "Story language",
  "create.lang_help": "Decides which language NPCs speak and the narration is written in.",
  "create.submit": "Start writing",
  "create.generating": "Generating, ~12–20s",

  // === create page (v2 layout) ===
  "create.tag_new": "New story",
  "create.heading_l1": "Write the opening,",
  "create.heading_l2": "AI takes the rest.",
  "create.subhead": "One sentence is enough. AI sets up the cast, the relationships, the first dramatic moment — then you take over and play.",
  "create.placeholder": "Write the opening line. The more specific, the better.\n\nLike: The night before the year-end gala, my boss locks me in a meeting room with the new intern.\nOr: On the wedding day, there's a note from my sister tucked inside the bridesmaid's dress.\n\nAI will instantly build the cast, the relationships, the first dramatic moment.",
  "create.char_count": "{n} chars",
  "create.examples_label": "Try one:",
  "create.example_seed_1": "At the company gala, my ex's new partner walks toward me with their arm around my ex.",
  "create.example_seed_2": "The night we broke up, he called my younger sister.",
  "create.example_seed_3": "My ex is now HR at my new company — and just sent over my offer letter.",
  "create.example_seed_4": "High-school reunion: turns out my first love is now my sister's boyfriend.",
  "create.field_budget": "Length",
  "create.budget_short_label": "Short",
  "create.budget_short_time": "10 min",
  "create.budget_short_desc": "One dramatic moment, tight pacing.",
  "create.budget_medium_label": "Medium",
  "create.budget_medium_time": "15 min",
  "create.budget_medium_desc": "A full episode, complete arc.",
  "create.budget_long_label": "Long",
  "create.budget_long_time": "25 min",
  "create.budget_long_desc": "Multiple threads, deeper emotion.",
  "create.field_difficulty": "Difficulty",
  "create.difficulty_story_label": "Story mode",
  "create.difficulty_story_tagline": "Sit back and watch",
  "create.difficulty_story_desc": "You can't really lose. The story always lands on a complete ending.",
  "create.difficulty_gauntlet_label": "Gauntlet mode",
  "create.difficulty_gauntlet_tagline": "NPCs fight back",
  "create.difficulty_gauntlet_desc": "NPCs have agendas and leverage. You might crash by turn 5 — endings split into win, compromise, and collapse.",
  "create.field_story_lang": "Story language",
  "create.field_visibility": "Who can play this",
  "create.visibility_private_label": "Just me",
  "create.visibility_private_desc": "Only you can play this story.",
  "create.visibility_unlisted_label": "Link only",
  "create.visibility_unlisted_desc": "Send the link to friends — they'll play out their own version.",
  "create.visibility_public_label": "Public",
  "create.visibility_public_desc": "Anyone can find and play your story.",
  "create.error_seed_required": "Write an opening line first.",
  "create.error_create_failed": "Couldn't create the story. Please try again.",
  "create.cta_idle": "Start this story →",
  "create.cta_busy": "AI is building the story…",
  "create.cta_back": "Back",
  "create.busy_tip_1": "Picking 3–5 characters from your seed — each with their own secret…",
  "create.busy_tip_2": "Wiring up the leverage NPCs hold over each other…",
  "create.busy_tip_3": "Drafting 3 player identity cards — each leads to a different story…",
  "create.busy_tip_4": "Writing the first dramatic moment of the opening…",
  "create.busy_tip_5": "Cross-checking motives and relationships for plausibility…",

  "login.tag": "Sign in",
  "login.title": "What's your name?",
  "login.sub": "Pick any handle. No password.",
  "login.placeholder": "e.g. shehao",
  "login.submit_idle": "Enter",
  "login.submit_busy": "Entering…",
  "login.error_username_format": "Handle must be 2-20 chars, letters / numbers / underscore.",
  "login.error_generic": "Sign-in failed. Please try again.",
  "login.note": "Testing phase — no password, no email. Real auth coming next month.",

  "play.input_action_placeholder": "What you do…",
  "play.input_diary_placeholder": "What you're really thinking (NPCs can't see this)",
  "play.option_pick_prefix": "Option",
  "play.advisor_open": "Call your friend",
  "play.advisor_oracle": "🔮 Trade 1 turn for a hint",
  "play.turn_remaining": "Turns left",
  "play.send": "Send",
  "play.thinking": "Composing…",
  "play.ending_share": "Copy share link",
  "play.ending_replay": "Play again",
  "play.highlights_title": "5 pivotal moments",
  "play.branches_title": "Paths you didn't take",

  "play.back_home": "← Back to home",
  "play.load_failed": "Failed to load: {error}",
  "play.loading_story": "Loading the story…",
  "play.busy_shim": "Continuing the story…",
  "play.error_load_story": "Couldn't load the story.",
  "play.error_advance": "Couldn't continue the story. Try again.",
  "play.header_turn_count": "· Turn {current} of {total}",

  "play.pulse_legend_aria": "NPC mood legend",
  "play.pulse_legend_label": "NPC mood",
  "play.pulse_warmer": "warming to you",
  "play.pulse_colder": "cooling off",
  "play.pulse_wary": "suspicious",
  "play.pulse_broken": "shattered",
  "play.pulse_steady": "unchanged",
  "play.pulse_reason_prefix": "because: {reason}",

  "play.role_you_tag": "You, this run",
  "play.role_secret_objective": "What you actually want",
  "play.role_secret_leverage": "Your trump cards",
  "play.role_inventory": "In hand ({count})",

  "play.gauntlet_badge": "Gauntlet",
  "play.gauntlet_goals_title": "What you want this run:",
  "play.gauntlet_goal_stakes": "Cost of failure: {stakes}",

  "play.finale_wrapping": "Story wrapping up…",
  "play.finale_one_left": "Next turn is the ending — choose carefully.",
  "play.finale_two_left": "Two turns until the ending — start steering toward it.",

  "play.share_prompt": "Copy this link and send it to a friend:",

  "play.beat_chosen_label": "You chose",
  "play.beat_inv_added": "You got: {item}",
  "play.beat_inv_removed": "You lost: {item}",
  "play.beat_player_label": "You",
  "play.beat_diary_tag": "Inner monologue",

  "play.action_no_options": "(No options this turn — write what you want to do.)",
  "play.action_free_placeholder": "Write what you do — an action, a line, or a decision.",
  "play.action_busy": "Continuing…",
  "play.action_submit": "Do that →",
  "play.action_cancel": "Cancel",
  "play.action_open_free": "+ Write your own action",
  "play.diary_label_hint": "Only you and the narrator see this · NPCs can't · sent with your next action",
  "play.diary_placeholder": "What are you really thinking? (30–200 chars works best; leave blank to skip.)",
  "play.diary_close": "Cancel monologue",
  "play.diary_open": "+ Add an inner monologue (NPCs can't see)",

  "play.fab_label": "Chat",
  "play.advisor_title": "Talk to your outsider friend",
  "play.advisor_intro": "Ask them anything — where you stand with someone, what that line really meant, whether you're being reckless. They won't decide for you, but they'll think it through with you.",
  "play.advisor_textarea_placeholder": "What's on your mind? Press ⌘/Ctrl + Enter to send.",
  "play.advisor_send": "Send",
  "play.advisor_history_failed": "Couldn't load advisor history.",
  "play.advisor_ask_failed": "Your friend didn't answer that one. Try again?",
  "play.oracle_button": "🔮 Trade 1 turn for a hint",
  "play.oracle_badge": "🔮 Insight · cost 1 turn",
  "play.oracle_completed_error": "This run is over — no more turns to trade.",
  "play.oracle_confirm": "Trade 1 turn for the advisor's \"insider read\"?\n\n• You'll lose 1 turn ({before} → {after}).\n• The advisor sees behind-the-curtain cues.\n• They still won't decide for you.\n\nContinue?",
  "play.oracle_tip_complete": "Story has ended",
  "play.oracle_tip_no_turns": "Not enough turns left to trade",
  "play.oracle_tip_active": "Trade 1 turn for an insider read ({turns} turns left)",

  "play.ending_ribbon_victory": "Victory ending",
  "play.ending_ribbon_compromised": "Compromised ending",
  "play.ending_ribbon_collapsed": "Collapse ending",
  "play.ending_ribbon_early": "Early collapse",
  "play.ending_trigger_prefix": "· Triggered by: {trigger}",
  "play.ending_highlights_title": "{count} pivotal moments from this run",
  "play.ending_branches_title": "{count} paths you didn't take",
  "play.ending_branches_hint": "Pick differently here and the story would likely land on these endings instead. Want another run?",
  "play.ending_branch_turn": "Turn {turn}",
  "play.ending_branch_chosen_tag": "You chose",
  "play.ending_branch_arrow": "↓ but if you'd picked ↓",
  "play.ending_branch_alt_tag": "The other path",
  "play.ending_share_copied": "✓ Link copied",
  "play.ending_share_hint": "Send the link to a friend — they'll play the same opening and see what ending they land on.",

  "stage.hook": "Hook",
  "stage.pressure": "Pressure",
  "stage.reversal": "Reversal",
  "stage.climax": "Climax",
  "stage.pre_finale": "Pre-finale",

  "stage_bar.hook": "Prelude",
  "stage_bar.pressure": "Build",
  "stage_bar.reversal": "Turn",
  "stage_bar.climax": "Climax",
  "stage_bar.pre_finale": "Coda",
  "stage_bar.aria": "Turn {turn} of {total}, current stage: {stage}",

  // === replay page ===
  "replay.error_load_failed": "Couldn't load this replay.",
  "replay.error_title": "This run isn't viewable",
  "replay.error_back_plaza": "Back to plaza",
  "replay.loading_label": "Restoring this run…",
  "replay.crumb_back_home": "← Back home",
  "replay.badge": "Replay",
  "replay.in_progress_meta": "In progress · {current} / {total} turns played",
  "replay.cast_label": "Cast",
  "replay.advisor_toggle_prefix_showing": "Showing the side-chat with ",
  "replay.advisor_toggle_prefix_view": "View the side-chat with ",
  "replay.advisor_toggle_advisor_word": "their advisor",
  "replay.advisor_toggle_suffix": " ({count} exchanges)",
  "replay.chosen_label": "They picked",
  "replay.advisor_track_title": "Player and advisor side-chat",
  "replay.player_label": "They",
  "replay.ending_divider": "End of the story",
  "replay.cta_hint": "Curious what ending you'd land on? Head home and start a fresh run from the same story on the plaza.",
  "replay.cta_back_plaza": "Back to plaza",
}

const BUNDLES: Record<Lang, Record<StringKey, string>> = {
  zh: STRINGS_ZH,
  en: STRINGS_EN,
}

// ---------------------------------------------------------------------------
// Ending label display map. The canonical IDs returned by the backend
// stay Chinese (they're enum-like keys), but the EndingScreen renders
// the label below as a display string. Add new labels here when the
// backend extends ENDING_LABELS.
// ---------------------------------------------------------------------------

export const ENDING_LABEL_DISPLAY: Record<Lang, Record<string, string>> = {
  zh: {
    "复仇": "复仇",
    "和解": "和解",
    "自由": "自由",
    "救赎": "救赎",
    "回归": "回归",
    "夺回": "夺回",
    "孤狼": "孤狼",
    "共谋": "共谋",
    "牺牲": "牺牲",
    "同谋": "同谋",
    "决裂": "决裂",
    "沉沦": "沉沦",
    "失控": "失控",
    "反噬": "反噬",
    "破碎": "破碎",
  },
  en: {
    "复仇": "Vengeance",
    "和解": "Reconcile",
    "自由": "Freedom",
    "救赎": "Redemption",
    "回归": "Homecoming",
    "夺回": "Reclaim",
    "孤狼": "Lone Wolf",
    "共谋": "Conspiracy",
    "牺牲": "Sacrifice",
    "同谋": "Complicity",
    "决裂": "Rupture",
    "沉沦": "Sink",
    "失控": "Spiral",
    "反噬": "Backfire",
    "破碎": "Shatter",
  },
}

// ---------------------------------------------------------------------------
// React context wiring
// ---------------------------------------------------------------------------

type TFn = (key: StringKey, paramsOrFallback?: Record<string, string | number> | string, fallback?: string) => string

type LanguageContextValue = {
  lang: Lang
  setLang: (next: Lang) => void
  t: TFn
}

function applyParams(template: string, params?: Record<string, string | number>): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, key) => {
    const value = params[key]
    return value === undefined ? match : String(value)
  })
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

function readStoredLang(): Lang {
  if (typeof window === "undefined") return DEFAULT_LANG
  const raw = window.localStorage.getItem(STORAGE_KEY)
  return raw === "en" || raw === "zh" ? raw : DEFAULT_LANG
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStoredLang)

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const value = useMemo<LanguageContextValue>(() => {
    const setLang = (next: Lang) => {
      setLangState(next)
      try {
        window.localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // localStorage unavailable (private browsing) — fail silently.
      }
    }
    const t: TFn = (key, paramsOrFallback, fallback) => {
      const params = typeof paramsOrFallback === "object" ? paramsOrFallback : undefined
      const stringFallback = typeof paramsOrFallback === "string" ? paramsOrFallback : fallback
      const bundle = BUNDLES[lang]
      const value = bundle?.[key]
      if (typeof value === "string" && value.length > 0) return applyParams(value, params)
      const zhValue = STRINGS_ZH[key]
      if (typeof zhValue === "string" && zhValue.length > 0) return applyParams(zhValue, params)
      return stringFallback ?? String(key)
    }
    return { lang, setLang, t }
  }, [lang])

  return createElement(LanguageContext.Provider, { value }, children)
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext)
  if (!ctx) {
    // Fallback so non-wrapped trees don't crash. Used in tests and
    // legacy components that haven't been wired yet.
    const t: TFn = (key, paramsOrFallback, fallback) => {
      const params = typeof paramsOrFallback === "object" ? paramsOrFallback : undefined
      const stringFallback = typeof paramsOrFallback === "string" ? paramsOrFallback : fallback
      const value = STRINGS_ZH[key]
      if (typeof value === "string" && value.length > 0) return applyParams(value, params)
      return stringFallback ?? String(key)
    }
    return { lang: DEFAULT_LANG, setLang: () => undefined, t }
  }
  return ctx
}

// Convenience helper for surfaces that only want `t`.
export function useT() {
  return useLanguage().t
}

export type { StringKey }
