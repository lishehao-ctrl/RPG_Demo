/**
 * Map raw API errors to user-readable Chinese / English messages.
 *
 * Inputs: any error thrown by `createHttpApiClient`'s `requestJson` —
 * either an `ApiRequestError` (with statusCode + errorCode) or a network-
 * layer Error (e.g. "Failed to fetch" when offline).
 *
 * The goal is *not* perfect classification — it's "the user sees something
 * grounded and recoverable instead of a stack-trace fragment."
 *
 * Locale is read from localStorage directly (the `LanguageProvider` writes
 * to the same key) so this stays a pure function and call sites don't
 * need to thread `lang` through every error handler.
 */

type ApiErrorLike = {
  message?: string
  statusCode?: number
  errorCode?: string
  name?: string
}

type Lang = "zh" | "en"

const LANG_STORAGE_KEY = "tiny-stories-lang"

function readLang(): Lang {
  if (typeof window === "undefined") return "zh"
  try {
    const raw = window.localStorage.getItem(LANG_STORAGE_KEY)
    return raw === "en" ? "en" : "zh"
  } catch {
    return "zh"
  }
}

const STATUS_FALLBACKS_ZH: Record<number, string> = {
  400: "这条请求被服务端拒绝了——可能是输入太敏感或不合规。",
  401: "登录已过期，请刷新页面重新登录。",
  403: "你看不了这一项——可能是别人的私有内容。",
  404: "这条记录不存在了，可能已经被删除。",
  409: "状态对不上——可能在另一处已经做了变化，刷新一下试试。",
  422: "输入有问题，看看是不是哪一项填错了。",
  429: "请求太密了，喘口气再来一次。",
  500: "服务端出了点问题，再试一次或者一会再来。",
  502: "AI 后端连不上，再试一次。",
  503: "服务暂时维护中，过几分钟再来。",
  504: "服务端响应太慢超时了，再试一次。",
}

const STATUS_FALLBACKS_EN: Record<number, string> = {
  400: "The server rejected this request — your input may be too sensitive or invalid.",
  401: "Session expired. Please refresh and sign in again.",
  403: "You can't access this — it may be private to someone else.",
  404: "This record no longer exists. It may have been deleted.",
  409: "State conflict — something changed elsewhere. Try refreshing.",
  422: "Something in your input isn't right. Check the fields.",
  429: "Too many requests in a short time. Take a breath and try again.",
  500: "Server hit a snag. Try again, or come back in a moment.",
  502: "Can't reach the AI backend. Try again.",
  503: "Service is briefly under maintenance. Back in a few minutes.",
  504: "Server response timed out. Try again.",
}

const ERROR_CODE_FALLBACKS_ZH: Record<string, string> = {
  llm_invalid_json: "AI 一时短路了，再点一次就行。",
  llm_provider_failed: "AI 服务暂时不在线，稍等再试。",
  llm_invalid_response: "AI 回了个空白，再试一次。",
  turn_invalid: "故事一时接不上你那一步——换个动作或稍等再试。",
  session_complete: "这一局已经走完了——回首页看你的结局。",
  session_forbidden: "这是别人的局，没法直接打开。",
  template_forbidden: "这个故事是私有的。",
  seed_required: "先写一句开头吧。",
  question_required: "想问点什么再发吧。",
  action_required: "选个选项或者写一段动作。",
  option_out_of_range: "选项序号不对，刷一下页面试试。",
  no_opening: "故事还没开始呢——重新进入。",
  no_narrator: "上一段叙述丢了，刷新一下试试。",
  turn_already_advanced: "这一段已经走过了，刷新一下接着玩。",
  llm_unavailable: "AI 服务还没配置，请联系站点维护人。",
  opening_invalid: "AI 给的开场没法用——换个种子再试。",
  advisor_invalid: "顾问没说出有效的话，再问一次。",
}

const ERROR_CODE_FALLBACKS_EN: Record<string, string> = {
  llm_invalid_json: "The AI hiccuped — just click again.",
  llm_provider_failed: "AI service is briefly offline. Try again shortly.",
  llm_invalid_response: "The AI returned a blank. Try again.",
  turn_invalid: "The story can't pick up from that move — try a different action, or wait and retry.",
  session_complete: "This run is already finished — go back home to see your ending.",
  session_forbidden: "That's someone else's run; you can't open it directly.",
  template_forbidden: "This story is private.",
  seed_required: "Start with an opening line first.",
  question_required: "Type something to ask first.",
  action_required: "Pick an option or write an action.",
  option_out_of_range: "Option index is off — try refreshing the page.",
  no_opening: "The story hasn't started yet — go back in.",
  no_narrator: "Lost the previous narration. Try a refresh.",
  turn_already_advanced: "This turn already moved forward. Refresh to continue.",
  llm_unavailable: "AI service isn't configured. Contact the site maintainer.",
  opening_invalid: "The AI's opening isn't usable — try a different seed.",
  advisor_invalid: "The advisor didn't say anything usable. Ask again.",
}

const NETWORK_FALLBACK_ZH = "网络好像断了——检查一下连接再试。"
const NETWORK_FALLBACK_EN = "Network seems down — check your connection and retry."

const GENERIC_FALLBACK_ZH = "出了点问题，再试一次。"
const GENERIC_FALLBACK_EN = "Something went wrong. Try again."

const GENERIC_PREFIX_ZH = "出了点问题："
const GENERIC_PREFIX_EN = "Something went wrong: "

const NETWORK_PATTERNS = [
  "Failed to fetch",
  "NetworkError",
  "Network request failed",
  "ERR_INTERNET",
  "ERR_NETWORK",
  "ERR_NAME_NOT_RESOLVED",
  "Load failed",
]

export function friendlyError(err: unknown, fallback?: string): string {
  const lang = readLang()
  const statusMap = lang === "en" ? STATUS_FALLBACKS_EN : STATUS_FALLBACKS_ZH
  const codeMap = lang === "en" ? ERROR_CODE_FALLBACKS_EN : ERROR_CODE_FALLBACKS_ZH
  const networkMsg = lang === "en" ? NETWORK_FALLBACK_EN : NETWORK_FALLBACK_ZH
  const genericMsg = lang === "en" ? GENERIC_FALLBACK_EN : GENERIC_FALLBACK_ZH
  const genericPrefix = lang === "en" ? GENERIC_PREFIX_EN : GENERIC_PREFIX_ZH

  if (!err) return fallback ?? genericMsg

  // Network errors — these come up as DOMException / TypeError before our
  // ApiRequestError wrapping can run.
  if (typeof err === "object" && err !== null) {
    const e = err as ApiErrorLike
    const message = e.message ?? ""

    // Network detection
    if (
      e.name === "TypeError" ||
      NETWORK_PATTERNS.some((p) => message.includes(p))
    ) {
      return networkMsg
    }

    // Specific API error code first (most precise)
    if (e.errorCode && codeMap[e.errorCode]) {
      return codeMap[e.errorCode]
    }

    // HTTP status fallback
    if (typeof e.statusCode === "number" && statusMap[e.statusCode]) {
      return statusMap[e.statusCode]
    }

    // If the API gave us a sentence in the user's locale already (backend
    // sometimes returns user-facing strings), trust it. We can't reliably
    // detect language from a short sentence, so we accept any non-empty
    // string and let it through.
    if (message && /[一-龥]/.test(message) && lang === "zh") {
      return message
    }
    if (message && lang === "en" && !/[一-龥]/.test(message)) {
      return message
    }
  }

  if (err instanceof Error && err.message) {
    return fallback ?? `${genericPrefix}${err.message}`
  }

  return fallback ?? genericMsg
}
