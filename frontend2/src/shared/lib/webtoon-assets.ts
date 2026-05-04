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
  segments: SEGMENT_PHASES.map((s) => `/webtoons/segments/${s}.jpg`),
  endings: ENDING_VARIANTS.map((s) => `/webtoons/endings/${s}.jpg`),
} as const
