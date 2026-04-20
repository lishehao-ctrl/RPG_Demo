import type { CSSProperties, ReactNode } from "react"

export function StorylineTag({
  children,
  tone = "default",
}: {
  children: ReactNode
  tone?: "default" | "muted" | "gold" | "danger"
}) {
  return <span className={`storyline-tag storyline-tag--${tone}`}>{children}</span>
}

export function StorylineSectionHeader({
  eyebrow,
  title,
  subtitle,
  action,
  align = "left",
}: {
  eyebrow?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  align?: "left" | "center"
}) {
  return (
    <div className={`storyline-section-header storyline-section-header--${align}`}>
      <div className="storyline-section-header__copy">
        {eyebrow ? <div className="storyline-section-header__eyebrow">{eyebrow}</div> : null}
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {action ? <div className="storyline-section-header__action">{action}</div> : null}
    </div>
  )
}

export function StorylineMetaStrip({
  items,
}: {
  items: Array<{ label: ReactNode; value: ReactNode }>
}) {
  return (
    <div className="storyline-meta-strip">
      {items.map((item) => (
        <div className="storyline-meta-strip__item" key={`${item.label}:${item.value}`}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  )
}

export function StorylineActionRow({ children }: { children: ReactNode }) {
  return <div className="storyline-action-row">{children}</div>
}

export function StorylineAtmosphereTile({
  asset,
  eyebrow,
  title,
  summary,
  compact = false,
}: {
  asset: string
  eyebrow: ReactNode
  title: ReactNode
  summary: ReactNode
  compact?: boolean
}) {
  return (
    <article
      className={`storyline-atmosphere-tile ${compact ? "is-compact" : ""}`}
      style={{ "--storyline-surface-image": `url("${asset}")` } as CSSProperties}
    >
      <span className="storyline-atmosphere-tile__eyebrow">{eyebrow}</span>
      <strong>{title}</strong>
      <p>{summary}</p>
    </article>
  )
}
