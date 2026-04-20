import type { CSSProperties, ReactNode } from "react"
import { motion } from "motion/react"
import type {
  AuthorPreviewBeatSummary,
  AuthorPreviewCastSlotSummary,
  PlayControlAction,
  PlayRelationshipStateSnapshot,
  PlaySuggestedAction,
} from "../../index"
import type { AuthorConceptStage, ConceptVariant } from "../lib/concept-review-types"
import { useStorylineMotion } from "./storyline-motion"

function clampPercent(value: number, min: number, max: number) {
  if (max <= min) return 50
  return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))
}

export function ConceptPanel({
  eyebrow,
  title,
  subtitle,
  children,
  className = "",
}: {
  eyebrow: string
  title: string
  subtitle?: string
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`concept-panel ${className}`.trim()}>
      <div className="concept-panel__header">
        <span className="concept-panel__eyebrow">{eyebrow}</span>
        <h3>{title}</h3>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {children}
    </section>
  )
}

export function ConceptVariantSwitcher({
  value,
  onChange,
}: {
  value: ConceptVariant
  onChange: (next: ConceptVariant) => void
}) {
  const options: Array<{ value: ConceptVariant; label: string; note: string }> = [
    { value: "casefile", label: "案卷剧场", note: "证物、机密提要、余波账本" },
    { value: "series", label: "剧集路线", note: "本集场面、路线、人物关系" },
  ]

  return (
    <div className="concept-switcher" role="tablist" aria-label="概念方案切换">
      {options.map((option) => (
        <button
          aria-selected={value === option.value}
          className={`concept-switcher__button ${value === option.value ? "is-active" : ""}`}
          key={option.value}
          onClick={() => onChange(option.value)}
          role="tab"
          type="button"
        >
          <strong>{option.label}</strong>
          <span>{option.note}</span>
        </button>
      ))}
    </div>
  )
}

export function ConceptStageSwitcher({
  value,
  onChange,
}: {
  value: AuthorConceptStage
  onChange: (next: AuthorConceptStage) => void
}) {
  const options: Array<{ value: AuthorConceptStage; label: string; note: string }> = [
    { value: "create", label: "起草台", note: "种子、关系钩子、路线承诺" },
    { value: "loading", label: "编译台", note: "进度、加载卡、终局压力" },
  ]

  return (
    <div className="concept-switcher concept-switcher--stage" role="tablist" aria-label="Author 概念阶段切换">
      {options.map((option) => (
        <button
          aria-selected={value === option.value}
          className={`concept-switcher__button ${value === option.value ? "is-active" : ""}`}
          key={option.value}
          onClick={() => onChange(option.value)}
          role="tab"
          type="button"
        >
          <strong>{option.label}</strong>
          <span>{option.note}</span>
        </button>
      ))}
    </div>
  )
}

export function ConceptCastRail({
  items,
  title,
}: {
  items: AuthorPreviewCastSlotSummary[]
  title: string
}) {
  const motionPreset = useStorylineMotion()

  return (
    <div className="concept-cast-rail">
      <div className="concept-inline-header">
        <strong>{title}</strong>
        <span>{items.length} 人</span>
      </div>
      <div className="concept-cast-rail__grid">
        {items.map((item, index) => (
          <motion.article
            className={`concept-cast-card ${index === 0 ? "is-lead" : ""}`}
            key={item.slot_label}
            {...motionPreset.inView({ delay: Math.min(index * 0.06, 0.18), y: 14, duration: 0.44 })}
          >
            <span className="concept-cast-card__index">{`0${index + 1}`}</span>
            <strong>{item.slot_label}</strong>
            <p>{item.public_role}</p>
          </motion.article>
        ))}
      </div>
    </div>
  )
}

export function ConceptBeatLadder({
  beats,
  activeIndex,
}: {
  beats: AuthorPreviewBeatSummary[]
  activeIndex?: number
}) {
  return (
    <ol className="concept-beat-ladder">
      {beats.map((beat, index) => (
        <li className={index === activeIndex ? "is-active" : ""} key={`${beat.title}-${index}`}>
          <span className="concept-beat-ladder__index">{String(index + 1).padStart(2, "0")}</span>
          <div>
            <strong>{beat.title}</strong>
            <p>{beat.goal}</p>
          </div>
        </li>
      ))}
    </ol>
  )
}

export function ConceptRelationshipGraph({
  protagonist,
  relationshipState,
}: {
  protagonist: { title: string; role_label?: string | null; core_desire?: string | null }
  relationshipState: PlayRelationshipStateSnapshot
}) {
  const positions = [
    { x: 50, y: 10 },
    { x: 85, y: 55 },
    { x: 15, y: 55 },
    { x: 50, y: 88 },
  ]

  return (
    <div className="concept-relationship-graph">
      <svg aria-hidden="true" className="concept-relationship-graph__lines" viewBox="0 0 100 100">
        {relationshipState.targets.map((target, index) => {
          const pos = positions[index] ?? positions[positions.length - 1]
          return <line key={target.character_id} x1="50" y1="50" x2={String(pos.x)} y2={String(pos.y)} />
        })}
      </svg>

      <article className="concept-relationship-node concept-relationship-node--center" style={{ left: "50%", top: "50%" } as CSSProperties}>
        <span>主角</span>
        <strong>{protagonist.title}</strong>
        <p>{protagonist.role_label ?? protagonist.core_desire ?? "风暴中心"}</p>
      </article>

      {relationshipState.targets.map((target, index) => {
        const pos = positions[index] ?? positions[positions.length - 1]
        return (
          <article
            className={`concept-relationship-node ${target.is_route_focus ? "is-focus" : ""}`}
            key={target.character_id}
            style={{ left: `${pos.x}%`, top: `${pos.y}%` } as CSSProperties}
          >
            <span>{target.is_route_focus ? "路线焦点" : "关系节点"}</span>
            <strong>{target.name}</strong>
            <p>{`亲密 ${target.affection} · 信任 ${target.trust} · 拉扯 ${target.tension}`}</p>
          </article>
        )
      })}
    </div>
  )
}

export function ConceptConsequenceCards({
  consequences,
  summary,
}: {
  consequences: string[]
  summary: Array<{ label: string; value: string }>
}) {
  return (
    <div className="concept-consequence-board">
      <div className="concept-consequence-board__list">
        {consequences.map((item) => (
          <article className="concept-consequence-card" key={item}>
            <p>{item}</p>
          </article>
        ))}
      </div>
      <div className="concept-mini-metrics">
        {summary.map((item) => (
          <div className="concept-mini-metrics__item" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}

export function ConceptChoiceCards({
  storyActions,
  controlActions,
  selectedId,
  onSelect,
}: {
  storyActions: PlaySuggestedAction[]
  controlActions: PlayControlAction[]
  selectedId: string | null
  onSelect: (next: { id: string; prompt: string }) => void
}) {
  const motionPreset = useStorylineMotion()

  return (
    <div className="concept-choice-grid">
      {storyActions.map((action, index) => (
        <motion.button
          className={`concept-choice-card ${selectedId === action.suggestion_id ? "is-selected" : ""}`}
          key={action.suggestion_id}
          onClick={() => onSelect({ id: action.suggestion_id, prompt: action.prompt })}
          type="button"
          whileHover={motionPreset.hoverLift}
          whileTap={motionPreset.tapPress}
          {...motionPreset.inView({ delay: Math.min(index * 0.05, 0.18), y: 12, duration: 0.4 })}
        >
          <span className="concept-choice-card__mode">剧情走法</span>
          <strong>{action.label}</strong>
          <p>{action.prompt}</p>
        </motion.button>
      ))}

      {controlActions.map((action, index) => (
        <motion.button
          className={`concept-choice-card concept-choice-card--control ${selectedId === action.action_id ? "is-selected" : ""}`}
          key={action.action_id}
          onClick={() => onSelect({ id: action.action_id, prompt: action.prompt })}
          type="button"
          whileHover={motionPreset.hoverLift}
          whileTap={motionPreset.tapPress}
          {...motionPreset.inView({ delay: Math.min((storyActions.length + index) * 0.05, 0.24), y: 12, duration: 0.4 })}
        >
          <span className="concept-choice-card__mode">{action.action_type}</span>
          <strong>{action.label}</strong>
          <p>{action.prompt}</p>
        </motion.button>
      ))}
    </div>
  )
}

export function ConceptStateMeter({
  label,
  value,
  min,
  max,
}: {
  label: string
  value: number
  min: number
  max: number
}) {
  const width = clampPercent(value, min, max)
  return (
    <div className="concept-state-meter">
      <div className="concept-state-meter__head">
        <strong>{label}</strong>
        <span>{value}</span>
      </div>
      <div className="concept-state-meter__track">
        <div className="concept-state-meter__fill" style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}
