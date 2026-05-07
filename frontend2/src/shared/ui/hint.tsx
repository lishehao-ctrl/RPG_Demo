/**
 * <Hint> — small info-icon affordance that surfaces a short
 * explanation on hover/focus. Used to teach product-specific
 * vocabulary (NPC pulse colors, intent tags, oracle) to first-time
 * players without filling the page with tutorial copy.
 *
 * The icon doesn't replace the surface label — it sits next to it.
 * Reading flow: <h3>NPC mood <Hint>...</Hint></h3>. Designed for
 * instant recognition (the small `?` is universal) and zero space
 * impact (16px round chip). Native `title` for keyboard / screen
 * reader; custom popover for mouse hover.
 */

import {
  type CSSProperties,
  type ReactNode,
  useId,
  useState,
} from "react"
import { AnimatePresence, motion } from "motion/react"
import { transitions } from "../lib/motion-presets"

type HintProps = {
  children: ReactNode
  /** Plain-text fallback used as the native `title` attr. Match the
   *  visible content; required for keyboard / screen reader. */
  text: string
  /** Where the popover floats relative to the icon. */
  side?: "top" | "bottom" | "right"
}

export function Hint({ children, text, side = "top" }: HintProps) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const popId = `hint-${id}`

  return (
    <span
      style={baseWrap}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        type="button"
        aria-describedby={popId}
        aria-label={text}
        title={text}
        style={iconStyle}
        // Click toggles for mobile / touch — hover doesn't exist there.
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
      >
        ?
      </button>
      <AnimatePresence>
        {open ? (
          <motion.span
            id={popId}
            role="tooltip"
            style={{ ...popoverBase, ...popoverSide[side] }}
            initial={{ opacity: 0, y: side === "bottom" ? -4 : 4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: side === "bottom" ? -4 : 4, scale: 0.96 }}
            transition={transitions.snap}
          >
            {children}
          </motion.span>
        ) : null}
      </AnimatePresence>
    </span>
  )
}

const baseWrap: CSSProperties = {
  position: "relative",
  display: "inline-flex",
  alignItems: "center",
  marginLeft: 4,
}

const iconStyle: CSSProperties = {
  width: 16,
  height: 16,
  padding: 0,
  borderRadius: "50%",
  background: "var(--bg-elev-2)",
  color: "var(--text-muted)",
  border: "1px solid var(--line-strong)",
  fontSize: 10.5,
  fontWeight: 700,
  lineHeight: 1,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "help",
  fontFamily: "var(--font-ui)",
}

const popoverBase: CSSProperties = {
  position: "absolute",
  zIndex: 50,
  width: "max-content",
  maxWidth: 260,
  padding: "10px 12px",
  background: "var(--bg-elev-2)",
  border: "1px solid var(--line-strong)",
  borderRadius: 8,
  boxShadow: "0 16px 36px rgba(0,0,0,0.48)",
  fontSize: 12,
  lineHeight: 1.55,
  color: "var(--text)",
  fontStyle: "normal" as const,
  fontWeight: 400,
  whiteSpace: "normal" as const,
  textAlign: "left" as const,
  pointerEvents: "none" as const,
}

const popoverSide: Record<"top" | "bottom" | "right", CSSProperties> = {
  top: {
    bottom: "calc(100% + 6px)",
    left: "50%",
    transform: "translateX(-50%)",
  },
  bottom: {
    top: "calc(100% + 6px)",
    left: "50%",
    transform: "translateX(-50%)",
  },
  right: {
    left: "calc(100% + 6px)",
    top: "50%",
    transform: "translateY(-50%)",
  },
}
