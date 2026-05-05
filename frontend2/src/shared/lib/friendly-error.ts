/**
 * Map raw API errors to user-readable Chinese messages.
 *
 * Inputs: any error thrown by `createHttpApiClient`'s `requestJson` —
 * either an `ApiRequestError` (with statusCode + errorCode) or a network-
 * layer Error (e.g. "Failed to fetch" when offline).
 *
 * The goal is *not* perfect classification — it's "the user sees something
 * grounded and recoverable instead of a stack-trace fragment."
 */

type ApiErrorLike = {
  message?: string
  statusCode?: number
  errorCode?: string
  name?: string
}

const STATUS_FALLBACKS: Record<number, string> = {
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

const ERROR_CODE_FALLBACKS: Record<string, string> = {
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
  if (!err) return fallback ?? "出了点问题，再试一次。"

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
      return "网络好像断了——检查一下连接再试。"
    }

    // Specific API error code first (most precise)
    if (e.errorCode && ERROR_CODE_FALLBACKS[e.errorCode]) {
      return ERROR_CODE_FALLBACKS[e.errorCode]
    }

    // HTTP status fallback
    if (typeof e.statusCode === "number" && STATUS_FALLBACKS[e.statusCode]) {
      return STATUS_FALLBACKS[e.statusCode]
    }

    // If the API gave us a Chinese sentence already (backend sometimes
    // returns user-facing strings), trust it.
    if (message && /[一-龥]/.test(message)) {
      return message
    }
  }

  if (err instanceof Error && err.message) {
    return fallback ?? `出了点问题：${err.message}`
  }

  return fallback ?? "出了点问题，再试一次。"
}
