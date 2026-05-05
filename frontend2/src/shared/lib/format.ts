import type { PlayLengthPreset, StoryShellId } from "../../api/contracts"

export function formatRelativeTime(savedAt: number): string {
  const diffMs = Date.now() - savedAt
  if (diffMs < 60_000) return "刚刚"
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}

const LENGTH_LABEL: Record<PlayLengthPreset, string> = {
  "5_8": "短 · 5–8 分钟",
  "10_12": "中 · 10–12 分钟",
  "12_15": "中 · 12–15 分钟",
  "15_20": "长 · 15–20 分钟",
  "20_25": "长 · 20–25 分钟",
  "30_45": "超长 · 30–45 分钟",
}

export function formatLengthPreset(preset: PlayLengthPreset | null | undefined): string {
  if (!preset) return "自动"
  return LENGTH_LABEL[preset] ?? preset
}

const THEME_ZH: Record<string, string> = {
  power_struggle: "权力博弈",
  romance_drama: "情感纠葛",
  family_secret: "家族秘密",
  workplace_intrigue: "职场暗流",
  betrayal: "背叛",
  redemption: "救赎",
  mystery: "悬疑",
  wealth_families: "豪门",
  entertainment_scandal: "娱乐圈",
  office_power: "职场",
  campus_romance: "校园",
  urban_supernatural: "都市怪谈",
}

export function localizeTheme(theme: string | null | undefined): string {
  if (!theme) return "未分类"
  return THEME_ZH[theme] ?? theme.replace(/_/g, " ")
}

const SHELL_COVERS: Record<string, string> = {
  wealth_families: "/webtoons/shells/wealth_families.jpg",
  entertainment_scandal: "/webtoons/shells/entertainment_scandal.jpg",
  office_power: "/webtoons/shells/office_power.jpg",
  campus_romance: "/webtoons/shells/campus_romance.jpg",
  urban_supernatural: "/webtoons/shells/urban_supernatural.jpg",
}

export function shellCover(shellId: StoryShellId | string | null | undefined): string {
  if (!shellId) return SHELL_COVERS.office_power
  return SHELL_COVERS[shellId] ?? SHELL_COVERS.office_power
}

// ISO timestamp → loose human relative ("3 天前").
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return ""
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ""
  return formatRelativeTime(t)
}
