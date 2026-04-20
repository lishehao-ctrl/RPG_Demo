import type { AuthorLoadingCard } from "../../../index"
import { localizeStorylineLabel, localizeStorylineValue } from "../../../shared/lib/storyline"

export function LoadingCardSpotlight({
  activeCard,
  cardPool,
}: {
  activeCard: AuthorLoadingCard | null
  cardPool: AuthorLoadingCard[]
}) {
  if (!activeCard) {
    return null
  }

  const activeIndex = Math.max(
    cardPool.findIndex((card) => card.card_id === activeCard.card_id),
    0,
  )

  return (
    <div aria-live="polite" className="loading-spotlight">
      <div className={`loading-spotlight-card emphasis-${activeCard.emphasis}`}>
        <span className="loading-spotlight-label">{localizeStorylineLabel(activeCard.label)}</span>
        <strong>{localizeStorylineValue(activeCard.value)}</strong>
      </div>
      <div className="loading-spotlight-meta">
        <span>
          卡片 {activeIndex + 1} / {cardPool.length}
        </span>
      </div>
    </div>
  )
}
