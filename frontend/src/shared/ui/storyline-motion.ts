import { useReducedMotion, type Transition } from "motion/react"

const STORYLINE_EASE: [number, number, number, number] = [0.22, 1, 0.36, 1]

type RevealOptions = {
  delay?: number
  x?: number
  y?: number
  scale?: number
  duration?: number
}

type FadeOptions = {
  delay?: number
  duration?: number
}

export function useStorylineMotion() {
  const reduced = useReducedMotion()

  const makeTransition = (delay = 0, duration = 0.72): Transition =>
    reduced ? { duration: 0 } : { duration, delay, ease: STORYLINE_EASE }

  const reveal = ({
    delay = 0,
    x = 0,
    y = 28,
    scale = 1,
    duration = 0.72,
  }: RevealOptions = {}) =>
    reduced
      ? {
          initial: false as const,
          animate: { opacity: 1, x: 0, y: 0, scale: 1 },
          transition: { duration: 0 },
        }
      : {
          initial: { opacity: 0, x, y, scale },
          animate: { opacity: 1, x: 0, y: 0, scale: 1 },
          transition: makeTransition(delay, duration),
        }

  const fade = ({ delay = 0, duration = 0.42 }: FadeOptions = {}) =>
    reduced
      ? {
          initial: false as const,
          animate: { opacity: 1 },
          exit: { opacity: 1 },
          transition: { duration: 0 },
        }
      : {
          initial: { opacity: 0 },
          animate: { opacity: 1 },
          exit: { opacity: 0 },
          transition: makeTransition(delay, duration),
        }

  const inView = ({
    delay = 0,
    y = 24,
    duration = 0.66,
  }: RevealOptions = {}) =>
    reduced
      ? {
          initial: false as const,
          whileInView: { opacity: 1, y: 0 },
          viewport: { once: true, amount: 0.2 },
          transition: { duration: 0 },
        }
      : {
          initial: { opacity: 0, y },
          whileInView: { opacity: 1, y: 0 },
          viewport: { once: true, amount: 0.2 },
          transition: makeTransition(delay, duration),
        }

  const hoverLift = reduced
    ? {}
    : {
        y: -4,
        transition: { duration: 0.24, ease: STORYLINE_EASE },
      }

  const hoverNudge = reduced
    ? {}
    : {
        x: 4,
        transition: { duration: 0.24, ease: STORYLINE_EASE },
      }

  const tapPress = reduced ? {} : { scale: 0.985 }

  return {
    reduced,
    reveal,
    fade,
    inView,
    hoverLift,
    hoverNudge,
    tapPress,
    transition: makeTransition,
  }
}
