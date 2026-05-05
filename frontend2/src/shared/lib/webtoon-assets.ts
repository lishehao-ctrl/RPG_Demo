// Maps stable story / character / theme keys to webtoon-style illustrations
// in /webtoons/. Keep all path strings here so design output and runtime
// resolution stay in sync — Claude Design references the same URLs verbatim.

const SHELLS = [
  "campus_romance",
  "urban_supernatural",
  "wealth_families",
  "entertainment_scandal",
  "office_power",
] as const
type Shell = (typeof SHELLS)[number]

const AVATAR_FEMALE = [
  "female-01",
  "female-02",
  "female-03",
  "female-04",
  "female-05",
  "female-06",
] as const
const AVATAR_MALE = [
  "male-01",
  "male-02",
  "male-03",
  "male-04",
  "male-05",
  "male-06",
] as const

// Dedicated advisor portrait pool — visually distinct from the cast pool so
// the player's outsider-friend never collides with an NPC face.
const ADVISOR_AVATARS = [
  "advisor-01",
  "advisor-02",
  "advisor-03",
  "advisor-04",
  "advisor-05",
  "advisor-06",
] as const

const SEGMENT_PHASES = ["opening", "pressure", "reversal", "reveal", "terminal"] as const
type SegmentPhase = (typeof SEGMENT_PHASES)[number]

const ENDING_VARIANTS = [
  "burned_alone",
  "burst_reckoning",
  "side",
  "pyrrhic_control",
  "relationship",
] as const

// Backend themes (string-y from the LLM) routed to a closest-fit shell.
// Anything not listed falls back to a stable hash over SHELLS.
const THEME_TO_SHELL: Record<string, Shell> = {
  campus_romance: "campus_romance",
  urban_supernatural: "urban_supernatural",
  wealth_families: "wealth_families",
  entertainment_scandal: "entertainment_scandal",
  office_power: "office_power",
  romance_drama: "campus_romance",
  power_struggle: "office_power",
  family_secret: "wealth_families",
  workplace_intrigue: "office_power",
  betrayal: "entertainment_scandal",
  redemption: "campus_romance",
  mystery: "urban_supernatural",
}

function stableHash(input: string): number {
  let h = 5381
  for (let i = 0; i < input.length; i += 1) {
    h = ((h << 5) + h + input.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

function pick<T>(pool: readonly T[], key: string): T {
  return pool[stableHash(key) % pool.length] as T
}

// ───────── covers ─────────

/** Cover image for a world card / story drawer / world detail hero. */
export function getCoverByStoryId(storyId: string, theme?: string | null): string {
  const shell = (theme && THEME_TO_SHELL[theme]) ?? pick(SHELLS, storyId)
  return `/webtoons/shells/${shell}.jpg`
}

// ───────── portraits ─────────

/** Stable per-character avatar. Hash is derived from (storyId + characterId)
 *  so the same character keeps the same face across renders. */
export function getPortraitForCharacter(
  storyId: string,
  characterId: string,
  gender?: "female" | "male" | null,
): string {
  const key = `${storyId}|${characterId}`
  const pool = gender === "male" ? AVATAR_MALE : AVATAR_FEMALE
  return `/webtoons/avatars/${pick(pool, key)}.jpg`
}

export function getDefaultAvatar(gender?: "female" | "male"): string {
  return gender === "male"
    ? "/webtoons/ui/default-avatar-male.jpg"
    : "/webtoons/ui/default-avatar-female.jpg"
}

// ───────── scenes / segments ─────────

/** Background art for the play stage, picked by the current beat phase. */
export function getSceneByPhase(phase: string | null | undefined): string {
  const slug = (SEGMENT_PHASES.find((p) => p === phase) ?? "opening") as SegmentPhase
  return `/webtoons/segments/${slug}.jpg`
}

// ───────── endings ─────────

/** Ending artwork. Hash by ending_id so each ending always uses the same canvas. */
export function getEndingArtwork(endingId: string | null | undefined): string {
  const key = endingId ?? "default"
  return `/webtoons/endings/${pick(ENDING_VARIANTS, key)}.jpg`
}

// ───────── page-level backgrounds ─────────

export const PAGE_BG = {
  splash: "/webtoons/ui/splash.jpg",
  home: "/webtoons/ui/library_bg.jpg",
  create: "/webtoons/ui/create_bg.jpg",
  generating: "/webtoons/ui/loading_bg.jpg",
  login: "/webtoons/ui/auth_bg.jpg",
} as const

export const LOGO_URL = "/webtoons/ui/logo.png"

// ───────── catalog (handy for design review / debugging) ─────────

export const ASSET_CATALOG = {
  shells: SHELLS.map((s) => `/webtoons/shells/${s}.jpg`),
  avatars: {
    female: AVATAR_FEMALE.map((s) => `/webtoons/avatars/${s}.jpg`),
    male: AVATAR_MALE.map((s) => `/webtoons/avatars/${s}.jpg`),
  },
  advisors: ADVISOR_AVATARS.map((s) => `/webtoons/advisors/${s}.jpg`),
  segments: SEGMENT_PHASES.map((s) => `/webtoons/segments/${s}.jpg`),
  endings: ENDING_VARIANTS.map((s) => `/webtoons/endings/${s}.jpg`),
} as const

// ───────── narrative (template/session) helpers ─────────
// The narrative engine doesn't expose shell_id directly, so we infer
// from seed + role text using lightweight keyword matching. Same for
// gender (used to pick a female vs. male portrait pool).

type LooseCast = { character_id: string; display_name: string; role: string; relation_to_protagonist: string }
type LooseTemplate = {
  template_id: string
  seed: string
  title?: string
  cast: LooseCast[]
}

const SHELL_KEYWORDS: Record<Shell, readonly string[]> = {
  wealth_families: [
    "豪门", "霸总", "总裁", "继承", "豪宅", "联姻", "家族", "夫人", "千金", "少爷",
    "宴会", "婆媳", "继母", "私生子", "年夜饭", "嫁入", "遗嘱", "红毯",
  ],
  office_power: [
    "总监", "副总", "经理", "项目", "职场", "公司", "高管", "实习", "客户",
    "汇报", "会议", "权力博弈", "竞标", "年会", "述职",
  ],
  entertainment_scandal: [
    "颁奖", "明星", "搭档", "经纪人", "娱乐圈", "出道", "粉丝", "片场",
    "通告", "代言", "热搜", "狗仔", "发布会", "导演",
  ],
  campus_romance: [
    "高中", "大学", "校园", "同学", "学姐", "学长", "学妹", "教室",
    "宿舍", "毕业", "重逢", "初恋", "妹妹", "哥哥", "校服",
  ],
  urban_supernatural: [
    "都市", "怪谈", "灵异", "鬼", "诡异", "失踪", "深夜", "电话", "梦",
    "凶杀", "目击", "怨灵", "诅咒",
  ],
}

function inferShell(template: LooseTemplate): Shell {
  const corpus = [
    template.seed,
    template.title ?? "",
    template.cast.map((c) => `${c.role} ${c.relation_to_protagonist}`).join(" "),
  ].join(" ")
  let bestShell: Shell = "wealth_families"
  let bestHits = 0
  for (const shell of SHELLS) {
    const hits = SHELL_KEYWORDS[shell].reduce(
      (n, kw) => n + (corpus.includes(kw) ? 1 : 0),
      0,
    )
    if (hits > bestHits) {
      bestHits = hits
      bestShell = shell
    }
  }
  // No keyword hits → stable hash over the template_id keeps cards visually
  // distinct without misleading the user about subgenre.
  if (bestHits === 0) {
    return pick(SHELLS, template.template_id)
  }
  return bestShell
}

const FEMALE_ROLE_HINTS = [
  "妻", "妻子", "夫人", "母", "妈", "女儿", "妹", "姐", "姑娘", "小姐", "千金",
  "公主", "皇后", "继母", "学姐", "学妹", "女主", "少奶奶", "新娘", "未婚妻",
  "经纪人", "助理", "闺蜜", "情人",
]
const MALE_ROLE_HINTS = [
  "夫", "丈夫", "父", "爸", "儿子", "弟", "哥", "少爷", "总裁", "霸总",
  "皇帝", "王", "继父", "学长", "男主", "新郎", "未婚夫",
]

function inferGender(role: string, relation: string): "female" | "male" {
  const corpus = `${role} ${relation}`
  const female = FEMALE_ROLE_HINTS.some((kw) => corpus.includes(kw))
  const male = MALE_ROLE_HINTS.some((kw) => corpus.includes(kw))
  if (female && !male) return "female"
  if (male && !female) return "male"
  // Tie / no signal — split by character_id hash for a stable spread.
  return stableHash(`${role}|${relation}`) % 2 === 0 ? "female" : "male"
}

/** Cover for a template card / hero. */
export function getCoverForTemplate(template: LooseTemplate): string {
  return `/webtoons/shells/${inferShell(template)}.jpg`
}

/** Stable per-character avatar within a template. */
export function getAvatarForCastMember(
  templateId: string,
  member: LooseCast,
): string {
  const gender = inferGender(member.role, member.relation_to_protagonist)
  const pool = gender === "male" ? AVATAR_MALE : AVATAR_FEMALE
  const key = `${templateId}|${member.character_id}`
  return `/webtoons/avatars/${pick(pool, key)}.jpg`
}

/** Avatar for the advisor FAB / sidechat header. Pulls from a dedicated
 *  /webtoons/advisors/ pool so the advisor never collides with a cast NPC.
 *  The pool already mixes genders, so persona text isn't needed for the
 *  selection — we just hash by template_id for stability. */
export function getAdvisorAvatar(templateId: string, _persona: string): string {
  return `/webtoons/advisors/${pick(ADVISOR_AVATARS, `advisor|${templateId}`)}.jpg`
}
