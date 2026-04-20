import type { PlayLengthPreset } from "../../index"

export const PLAY_LENGTH_OPTIONS: Array<{
  value: PlayLengthPreset
  label: string
  minutesLabel: string
  descriptor: string
}> = [
  { value: "5_8", label: "短局", minutesLabel: "5-8 分钟", descriptor: "一记狠准的丑闻钩子" },
  { value: "10_12", label: "紧凑局", minutesLabel: "10-12 分钟", descriptor: "短而狠的档案篇幅" },
  { value: "12_15", label: "标准局", minutesLabel: "12-15 分钟", descriptor: "完整的关系起承转合" },
  { value: "15_20", label: "长局", minutesLabel: "15-20 分钟", descriptor: "让压力慢慢沸腾" },
  { value: "20_25", label: "旗舰局", minutesLabel: "20-25 分钟", descriptor: "群像级大案卷" },
  { value: "30_45", label: "超级旗舰", minutesLabel: "30-45 分钟", descriptor: "8 beat 长篇群像主线" },
]

export function formatPlayLengthPreset(value: PlayLengthPreset | string | null | undefined): string {
  const option = PLAY_LENGTH_OPTIONS.find((entry) => entry.value === value)
  return option?.minutesLabel ?? "12-15 分钟"
}

export function storylineToneFromText(value: string): "ember" | "noir" | "gold" {
  const lowered = value.toLowerCase()
  if (/(wedding|engagement|gala|宴|婚|继承|luxury|heir)/.test(lowered)) {
    return "gold"
  }
  if (/(night|secret|forbidden|betray|noir|黑|秘|失控)/.test(lowered)) {
    return "noir"
  }
  return "ember"
}

export function storylineMonogram(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) {
    return "01"
  }
  const first = trimmed[0]
  const second = trimmed.split(/\s+/)[1]?.[0]
  return `${first}${second ?? ""}`.slice(0, 2).toUpperCase()
}

const VALUE_TRANSLATIONS: Record<string, string> = {
  "gossip & glory": "流言与荣光",
  "wealth families": "豪门丑闻",
  "heir scandal": "豪门丑闻",
  "entertainment scandal": "热搜失控",
  "celebrity collapse": "热搜失控",
  "office power": "董事会修罗场",
  office_power: "董事会修罗场",
  "boardroom seduction": "董事会修罗场",
  "campus romance": "校园修罗场",
  campus_romance: "校园修罗场",
  "campus pressure cooker": "校园修罗场",
  "urban supernatural": "夜色契约",
  urban_supernatural: "夜色契约",
  "nocturne pact": "夜色契约",
  "chinese gossip noir": "都市绯闻黑色戏",
  chinese_gossip_noir: "都市绯闻黑色戏",
  "premium urban pressure drama": "都市高压关系戏",
  premium_urban_pressure_drama: "都市高压关系戏",
  "luxury gossip spiral": "奢华绯闻漩涡",
  luxury_gossip_spiral: "奢华绯闻漩涡",
  "5-figure scandal web": "五人修罗场",
  "4-route power ring": "四角权力环",
  wealth_families: "豪门丑闻",
  entertainment_scandal: "热搜失控",
  "four_route_ring": "四角权力环",
  "five_figure_web": "五人修罗场",
  "relationship drama v2": "关系戏 V2",
  "langgraph play runtime": "LangGraph 运行时",
  "the one everyone is reading": "被所有人拿来解读的人",
  "survive the room, choose a line, and decide who gets humiliated in public.": "活着走出这间屋子，选定一条线，并决定谁要在众目睽睽下出丑。",
  "you are the emotional and political center of the issue. every named figure wants something from you before the night is over.": "你是这份案卷里的情绪中心，也是权力中心。每个被点名的人，都想在今晚从你身上拿到一点什么。",
  "the elegant one everyone is watching": "被所有人盯着的体面中心",
  "the dangerous protector with leverage": "握着筹码却仍想护住她的人",
  "the rival who knows too much": "知道太多、也最会逼人失态的对手",
  "the social force who can tilt the room": "一句话就能让整个房间改风向的人",
  "the witness who can burn it all down": "只要开口，就能把所有人一起拖下水的见证者",
  "opening tension": "暗流初起",
  "public pressure": "公众压力",
  "secret turn": "秘密转折",
  "final detonation": "最终引爆",
  "test who is already leaning toward betrayal.": "先看清谁已经悄悄把背叛写进表情里。",
  "keep the room from turning into open humiliation too early.": "别让这间屋子太早变成公开羞辱的现场。",
  "force the hidden leverage into the light.": "逼那份一直躲在暗处的筹码见光。",
  "choose who walks out with power and who burns alone.": "决定谁能带着筹码离场，谁又要独自烧毁。",
  queued: "等待开始",
  running: "进行中",
  "theme confirmed": "主题已确认",
  "cast planned": "角色已规划",
  "beat plan ready": "章节已就绪",
  "ending ready": "结局已就绪",
  completed: "已完成",
  "brief parsed": "简报已解析",
  "brief classified": "简报已归档",
  "story frame ready": "故事骨架已成形",
  "cast ready": "角色已就绪",
  "route ready": "路线已就绪",
  reveal: "揭露",
  containment: "压住",
  commitment: "落子",
  exposure: "曝光",
  "private": "私密",
  "public": "公开",
  "mine": "我的",
  "accessible": "可见",
}

const LABEL_TRANSLATIONS: Record<string, string> = {
  Theme: "主题",
  Tone: "气质",
  "NPC Count": "人物数",
  "Beat Count": "章节数",
  "Cast Structure": "关系结构",
  "Working Title": "暂定标题",
  "Core Conflict": "核心冲突",
  "Story Shape": "故事形态",
  "Story Premise": "故事前提",
  "Story Stakes": "代价与筹码",
  "Cast Anchor": "人物锚点",
  "Opening Beat": "开篇章节",
  "Final Beat": "结尾章节",
  "Generation Status": "生成状态",
  "Token Budget": "预算",
}

export function localizeStorylineValue(value: string | null | undefined): string {
  if (!value) {
    return ""
  }
  return VALUE_TRANSLATIONS[value.trim().toLowerCase()] ?? value
}

export function localizeStorylineLabel(value: string | null | undefined): string {
  if (!value) {
    return ""
  }
  return LABEL_TRANSLATIONS[value.trim()] ?? value
}
