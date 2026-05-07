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

  // Play page
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

  // Stage labels
  "stage.hook": "开场",
  "stage.pressure": "施压",
  "stage.reversal": "翻转",
  "stage.climax": "高潮",
  "stage.pre_finale": "终局前",
} as const

type StringKey = keyof typeof STRINGS_ZH

export const STRINGS_EN: Record<StringKey, string> = {
  "header.write_story": "Write a story",
  "header.login": "Sign in",
  "header.logout": "Sign out",
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

  "stage.hook": "Hook",
  "stage.pressure": "Pressure",
  "stage.reversal": "Reversal",
  "stage.climax": "Climax",
  "stage.pre_finale": "Pre-finale",
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
