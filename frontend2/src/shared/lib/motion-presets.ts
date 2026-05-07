/**
 * Shared motion variants and easing for all pages.
 *
 * Goal: every page feels like it belongs to the same product. Pick a
 * couple of timing constants and reuse them everywhere instead of
 * letting each page hand-tune its own animation.
 *
 * Adding a new timing? Reach for an existing entry first. If you must
 * add one, add it here as a NAMED constant and update the call site
 * to import it — don't inline. Hand-tuned `duration: 0.42` calls were
 * the previous version's biggest consistency leak.
 */

import type { Transition, Variants } from "motion/react"

// =============================================================================
// Easing curves
// =============================================================================
// Every animation in the product runs on EASE_OUT_CURVE — a snappy "exit
// fast, settle slow" cubic-bezier that reads as decisive without feeling
// abrupt. The duration ladder below picks the speed; everything else
// stays on this curve.

export const EASE_OUT_CURVE = [0.16, 1, 0.3, 1] as const

// =============================================================================
// Duration ladder
// =============================================================================
// 4 named tiers + 2 special-purpose entries. Pick the shortest tier
// that still reads as a deliberate change, not a glitch.
//
//   instant  80ms   — tap press, button click feedback
//   snap     180ms  — small UI shifts (hover, chip in, tab switch)
//   base     280ms  — default (page section enter, item cascade child)
//   medium   420ms  — emphasized state change (modal, sidechat slide)
//   slow     700ms  — story-beat reveal, hero scale, ending hero
//   ceremony 950ms  — once-per-session moments (ending splash overlay)

export const DURATIONS = {
  instant: 0.08,
  snap: 0.18,
  base: 0.28,
  medium: 0.42,
  slow: 0.7,
  ceremony: 0.95,
} as const

// Convenience Transitions at each tier — ALL on EASE_OUT_CURVE.

const tier = (duration: number): Transition => ({
  duration,
  ease: EASE_OUT_CURVE,
})

export const transitions = {
  instant: tier(DURATIONS.instant),
  snap: tier(DURATIONS.snap),
  base: tier(DURATIONS.base),
  medium: tier(DURATIONS.medium),
  slow: tier(DURATIONS.slow),
  ceremony: tier(DURATIONS.ceremony),
} as const

// Backwards-compatible aliases — older code reaches for these names.
export const ease = {
  out: transitions.base,
  fast: transitions.snap,
  slow: transitions.medium,
} as const

// =============================================================================
// Variants for common surfaces
// =============================================================================

// Page-level fade+slide on route change.
export const pageVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
}
export const pageTransition: Transition = transitions.base

// Single item appearing (a story beat, a card, a chip).
export const itemVariants: Variants = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 8 },
}
export const itemTransition: Transition = transitions.base

// Slide-in panels (sidechat, sidebar).
export const slideInRightVariants: Variants = {
  initial: { x: "100%", opacity: 0 },
  animate: { x: 0, opacity: 1 },
  exit: { x: "100%", opacity: 0 },
}
export const slideInRightTransition: Transition = transitions.medium

// Backdrop fade (paired with slide-in panels).
export const fadeVariants: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
}
export const fadeTransition: Transition = transitions.snap

// Collapse / expand (diary toggle, free-input toggle, advanced
// settings). Auto-height isn't reliable across motion versions, so we
// animate opacity + height + slight y shift.
export const collapseVariants: Variants = {
  initial: { opacity: 0, height: 0, marginTop: 0 },
  animate: { opacity: 1, height: "auto", marginTop: undefined },
  exit: { opacity: 0, height: 0, marginTop: 0 },
}
export const collapseTransition: Transition = transitions.snap

// =============================================================================
// Inline gestures
// =============================================================================

// Hover for card-like buttons (template cards, session cards).
export const hoverLift = {
  scale: 1.018,
  y: -2,
  transition: { duration: DURATIONS.snap, ease: EASE_OUT_CURVE },
}

// Hover for inline option buttons (story choices).
export const hoverNudge = {
  x: 4,
  transition: { duration: 0.16, ease: EASE_OUT_CURVE },
}

// Tap feedback — slight press-down feel.
export const tapPress = {
  scale: 0.98,
  transition: { duration: DURATIONS.instant },
}

// =============================================================================
// Stagger / cascade
// =============================================================================

// Stagger container — used to children-cascade lists.
export const staggerContainer: Variants = {
  initial: {},
  animate: {
    transition: { staggerChildren: 0.05 },
  },
}

// Helper: per-child delay for hand-cascaded lists. Use this instead
// of inlining `delay: 0.05 * i + 0.1` everywhere.
export const cascadeDelay = (index: number, base = 0.05, offset = 0): number =>
  base * index + offset

// =============================================================================
// Ad-hoc animations (kept for compat — call sites still using these
// will be migrated to the duration ladder above incrementally).
// =============================================================================

// Distribution bar width animate from 0 to actual.
export const barFillVariants = (targetWidth: string): Variants => ({
  initial: { width: 0 },
  animate: { width: targetWidth },
})
export const barFillTransition: Transition = transitions.medium

// Pulse for "approaching finale" attention banner.
export const pulseVariants: Variants = {
  initial: { opacity: 0.6 },
  animate: {
    opacity: [0.6, 1, 0.6],
    transition: { duration: 2.4, repeat: Infinity, ease: "easeInOut" },
  },
}

// Spring used for the ending label chip — only place a non-easing
// curve makes sense (the bounce IS the effect).
export const labelChipSpring: Transition = {
  type: "spring",
  stiffness: 320,
  damping: 18,
  delay: 0.45,
}
