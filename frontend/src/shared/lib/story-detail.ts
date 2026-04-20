import type { AuthorPreviewResponse, PublishedStoryCard } from "../../index"

export function buildDossierRef(story: PublishedStoryCard): string {
  return `案卷号 ${story.story_id.slice(0, 3).toUpperCase()}`
}

export function buildClassificationLabel(preview: AuthorPreviewResponse): string {
  return (preview.story_shell_id ?? preview.theme.primary_theme).replace(/_/g, " ")
}
