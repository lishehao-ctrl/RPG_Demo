import type { CSSProperties } from "react"
import { motion } from "motion/react"
import { useStorylineMotion } from "./storyline-motion"

export type StorylinePosterOption = {
  id: string
  title: string
  eyebrow: string
  summary: string
  asset: string
}

export function StorylinePosterSwitcher({
  options,
  activeId,
  onSelect,
  compact = false,
}: {
  options: StorylinePosterOption[]
  activeId: string
  onSelect: (id: string) => void
  compact?: boolean
}) {
  const motionPreset = useStorylineMotion()

  return (
    <div className={`storyline-poster-switcher ${compact ? "is-compact" : ""}`} role="tablist" aria-label="海报切换">
      {options.map((option) => (
        <motion.button
          key={option.id}
          aria-selected={option.id === activeId}
          className={`storyline-poster-switcher__item ${option.id === activeId ? "is-active" : ""}`}
          onClick={() => onSelect(option.id)}
          role="tab"
          style={{ "--storyline-surface-image": `url("${option.asset}")` } as CSSProperties}
          type="button"
          whileHover={motionPreset.hoverLift}
          whileTap={motionPreset.tapPress}
        >
          <span className="storyline-poster-switcher__eyebrow">{option.eyebrow}</span>
          <strong>{option.title}</strong>
          <p>{option.summary}</p>
        </motion.button>
      ))}
    </div>
  )
}
