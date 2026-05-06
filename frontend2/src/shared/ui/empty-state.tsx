/**
 * Shared EmptyState — used for "not found", "blocked", "auth required"
 * fallback screens. Borrows the empty-plaza visual language from the
 * home page so all dead-end screens feel like the same product family.
 *
 * Variant `notFound`: page-level fallback when a session/template is
 *   missing or inaccessible.
 * Variant `auth`: page-level fallback when login is required.
 *
 * Both render a hero image (plaza), a title, a hint, and an optional
 * primary button.
 */

import type { CSSProperties, ReactNode } from "react"
import { motion } from "motion/react"
import { itemTransition } from "../lib/motion-presets"
import { getEmptyPlazaImage } from "../lib/webtoon-assets"

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <motion.div
      style={styles.wrap}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={itemTransition}
    >
      <div
        style={{
          ...styles.hero,
          backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.05) 0%, rgba(20,16,12,0.55) 75%, var(--bg-elev) 100%), url(${getEmptyPlazaImage()})`,
        }}
      />
      <div style={styles.body}>
        <h2 style={styles.title}>{title}</h2>
        {hint ? <p style={styles.hint}>{hint}</p> : null}
        {action ? <div style={styles.action}>{action}</div> : null}
      </div>
    </motion.div>
  )
}

const styles: Record<string, CSSProperties> = {
  wrap: {
    maxWidth: 520,
    margin: "60px auto",
    background: "var(--bg-elev)",
    borderRadius: "var(--radius-md)",
    border: "1px solid var(--line)",
    overflow: "hidden",
  },
  hero: {
    width: "100%",
    height: 160,
    backgroundSize: "cover",
    backgroundPosition: "center",
  },
  body: {
    padding: "20px 28px 28px",
    textAlign: "center" as const,
    color: "var(--text-muted)",
  },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 22,
    fontWeight: 500,
    color: "var(--text)",
    margin: "0 0 10px",
    lineHeight: 1.35,
  },
  hint: {
    fontSize: 13.5,
    lineHeight: 1.7,
    margin: "0 0 18px",
    fontStyle: "italic" as const,
  },
  action: {
    display: "flex",
    justifyContent: "center",
    gap: 8,
  },
}
