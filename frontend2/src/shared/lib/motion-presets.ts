/**
 * Shared motion variants and easing for all pages.
 *
 * Goal: every page feels like it belongs to the same product. Pick a
 * couple of timing constants and reuse them everywhere instead of
 * letting each page hand-tune its own animation.
 */

import type { Transition, Variants } from "motion/react"

// 280ms is the eyeline for "this just happened" feel — fast enough not
// to delay action, slow enough that the eye registers the change.
const EASE_OUT: Transition = { duration: 0.28, ease: [0.16, 1, 0.3, 1] }
const EASE_OUT_SLOW: Transition = { duration: 0.5, ease: [0.16, 1, 0.3, 1] }
const EASE_OUT_FAST: Transition = { duration: 0.18, ease: [0.16, 1, 0.3, 1] }

// Page-level fade+slide on route change.
export const pageVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
}
export const pageTransition: Transition = EASE_OUT

// Single item appearing (a story beat, a card, a chip).
export const itemVariants: Variants = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 8 },
}
export const itemTransition: Transition = EASE_OUT

// Slide-in panels (sidechat, sidebar).
export const slideInRightVariants: Variants = {
  initial: { x: "100%", opacity: 0 },
  animate: { x: 0, opacity: 1 },
  exit: { x: "100%", opacity: 0 },
}
export const slideInRightTransition: Transition = EASE_OUT

// Backdrop fade (paired with slide-in panels).
export const fadeVariants: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
}
export const fadeTransition: Transition = EASE_OUT_FAST

// Hover for card-like buttons (template cards, session cards).
export const hoverLift = {
  scale: 1.018,
  y: -2,
  transition: { duration: 0.18, ease: [0.16, 1, 0.3, 1] as const },
}

// Hover for inline option buttons (story choices).
export const hoverNudge = {
  x: 4,
  transition: { duration: 0.16, ease: [0.16, 1, 0.3, 1] as const },
}

// Tap feedback — slight press-down feel.
export const tapPress = {
  scale: 0.98,
  transition: { duration: 0.08 },
}

// Stagger container — used to children-cascade lists.
export const staggerContainer: Variants = {
  initial: {},
  animate: {
    transition: { staggerChildren: 0.05 },
  },
}

// Distribution bar width animate from 0 to actual.
export const barFillVariants = (targetWidth: string): Variants => ({
  initial: { width: 0 },
  animate: { width: targetWidth },
})
export const barFillTransition: Transition = EASE_OUT_SLOW

// Pulse for "approaching finale" attention banner.
export const pulseVariants: Variants = {
  initial: { opacity: 0.6 },
  animate: {
    opacity: [0.6, 1, 0.6],
    transition: { duration: 2.4, repeat: Infinity, ease: "easeInOut" },
  },
}

// Re-export common tokens.
export const ease = { out: EASE_OUT, slow: EASE_OUT_SLOW, fast: EASE_OUT_FAST }
