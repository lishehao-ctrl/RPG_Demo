import { motion } from "motion/react"
import type { PublishedStoryCard } from "../../../index"
import { localizeStorylineValue, storylineMonogram, storylineToneFromText } from "../../../shared/lib/storyline"
import { formatPublishedAt } from "../../../shared/lib/formatting"
import { StorylineTag } from "../../../shared/ui/storyline-primitives"
import { useStorylineMotion } from "../../../shared/ui/storyline-motion"

export function StoryLibraryCard({
  story,
  selected,
  onSelect,
}: {
  story: PublishedStoryCard
  selected: boolean
  onSelect: () => void
}) {
  const motionPreset = useStorylineMotion()
  const ownershipLabel = story.viewer_can_manage
    ? story.visibility === "private"
      ? "我的私密案卷"
      : "我的公开案卷"
    : "公开案卷"
  const tone = storylineToneFromText(`${story.title} ${story.theme} ${story.tone}`)
  const monogram = storylineMonogram(story.title)

  return (
    <motion.button
      className={`storyline-archive-card storyline-archive-card--${tone} ${selected ? "is-selected" : ""}`}
      onClick={onSelect}
      type="button"
      whileHover={motionPreset.hoverLift}
      whileTap={motionPreset.tapPress}
    >
      <div className="storyline-archive-card__cover storyline-archive-card__cover--plain">
        <div className="storyline-archive-card__eyebrow-row">
          <StorylineTag tone="danger">{ownershipLabel}</StorylineTag>
          <span className="storyline-archive-card__issue">留白封面</span>
        </div>

        <div className="storyline-archive-card__identity">
          <strong className="storyline-archive-card__monogram">{monogram}</strong>
          <div className="storyline-archive-card__headline">
            <span className="storyline-field-label">案卷标题</span>
            <h4>{story.title}</h4>
          </div>
        </div>
      </div>

      <div className="storyline-archive-card__body">
        <div className="storyline-archive-card__meta">
          <span>{formatPublishedAt(story.published_at)}</span>
          <span>{story.npc_count} 位人物</span>
          <span>{story.beat_count} 章</span>
        </div>
        <p>{story.one_liner}</p>
        <div className="storyline-chip-grid">
          <StorylineTag tone="gold">{localizeStorylineValue(story.theme)}</StorylineTag>
          <StorylineTag tone="default">{localizeStorylineValue(story.tone)}</StorylineTag>
        </div>
      </div>
    </motion.button>
  )
}
