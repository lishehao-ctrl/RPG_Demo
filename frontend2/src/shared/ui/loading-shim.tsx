/**
 * Shared loading state — 3-dot bouncing animation in muted text color.
 *
 * Used by every page when waiting for an initial fetch (home, world
 * detail, play, replay). Replaces scattered "加载中…" plain text with
 * a single visual vocabulary so users learn one signal: dots = waiting.
 *
 * Variants:
 * - `inline`: small, sits inside flow (e.g. inside a card's center)
 * - `page`: large block, used as full-page placeholder
 */

import type { CSSProperties } from "react"
import { motion } from "motion/react"

const DOT_TRANSITION = (idx: number) => ({
  duration: 0.96,
  ease: [0.4, 0, 0.6, 1] as const,
  repeat: Infinity,
  delay: idx * 0.16,
})

export function LoadingShim({
  label,
  variant = "page",
}: {
  label?: string
  variant?: "inline" | "page"
}) {
  const wrapStyle =
    variant === "inline" ? styles.wrapInline : styles.wrapPage
  return (
    <div style={wrapStyle} role="status" aria-live="polite">
      <div style={styles.dotRow}>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            style={styles.dot}
            animate={{ y: [0, -5, 0], opacity: [0.45, 1, 0.45] }}
            transition={DOT_TRANSITION(i)}
          />
        ))}
      </div>
      {label ? <div style={styles.label}>{label}</div> : null}
    </div>
  )
}

const styles: Record<string, CSSProperties> = {
  wrapPage: {
    padding: 80,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 14,
    color: "var(--text-faint)",
  },
  wrapInline: {
    padding: "20px 24px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 10,
    color: "var(--text-faint)",
  },
  dotRow: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--text-muted)",
    display: "inline-block",
  },
  label: {
    fontSize: 13,
    color: "var(--text-faint)",
    fontStyle: "italic",
    letterSpacing: "0.04em",
  },
}
