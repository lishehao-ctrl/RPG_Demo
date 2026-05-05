import type { PublishedStoryCard } from "../../api/contracts"
import { localizeTheme, relativeTime, shellCover } from "../../shared/lib/format"

// UI shape consumed by HomePage's StoryCard / StoryDrawer / friends.
// Mirrors the design's mock object but draws from the canonical PublishedStoryCard.
export type UiStory = {
  id: string
  title: string
  theme: string
  lede: string
  premise: string
  npc_count: number
  beat_count: number
  played_count: number
  unique_ending_count: number
  cover_url: string
  authorUsername: string
  createdAt: string
  visibility: string
  isOwnWorld?: boolean
  raw: PublishedStoryCard
}

export function adaptStory(card: PublishedStoryCard, ownerHandle?: string | null): UiStory {
  const endings = card.ending_distribution ? Object.keys(card.ending_distribution).length : 0
  // story_shell_id isn't on the public card today — use the theme as a fallback key.
  const shellId = (card as PublishedStoryCard & { story_shell_id?: string }).story_shell_id ?? card.theme ?? null
  return {
    id: card.story_id,
    title: card.title,
    theme: localizeTheme(card.theme),
    lede: card.one_liner,
    premise: card.premise,
    npc_count: card.npc_count,
    beat_count: card.beat_count,
    played_count: card.play_count,
    unique_ending_count: endings,
    cover_url: shellCover(shellId),
    authorUsername: ownerHandle ?? "unknown",
    createdAt: relativeTime(card.published_at) || "",
    visibility: card.visibility,
    isOwnWorld: card.viewer_can_manage,
    raw: card,
  }
}
