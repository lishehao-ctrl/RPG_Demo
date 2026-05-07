/**
 * Stage Progression Bar — 5-segment visual map of the dramatic arc.
 *
 * The 12-turn structure (hook → pressure → reversal → climax →
 * pre_finale) was invisible to players, who only saw the bare turn
 * count. This bar makes the arc structural: each segment shows
 * which dramatic phase it represents, the current segment glows,
 * past segments dim, future segments fade.
 *
 * Mirror of backend `_stage_for(turn_index, turn_budget)`.
 */

import type { CSSProperties } from "react"
import { motion } from "motion/react"
import { useT } from "../lib/i18n"

const STAGES = [
  { key: "hook", labelKey: "stage_bar.hook" },
  { key: "pressure", labelKey: "stage_bar.pressure" },
  { key: "reversal", labelKey: "stage_bar.reversal" },
  { key: "climax", labelKey: "stage_bar.climax" },
  { key: "pre_finale", labelKey: "stage_bar.pre_finale" },
] as const

type StageKey = (typeof STAGES)[number]["key"]

function stageForTurn(turnIndex: number, turnBudget: number): StageKey {
  if (turnIndex <= 1) return "hook"
  const midpoint = turnBudget / 2
  if (turnIndex < midpoint - 0.5) return "pressure"
  if (turnIndex < midpoint + 0.5) return "reversal"
  if (turnIndex < turnBudget - 1) return "climax"
  return "pre_finale"
}

// Approximate turn span per stage on a turn_budget=12 arc:
// hook: 0-1 (2 turns)
// pressure: 2 to mid-0.5 (~3 turns)
// reversal: mid±0.5 (~1 turn)
// climax: mid+0.5 to budget-1 (~5 turns)
// pre_finale: last turn
// We compute proportional widths so a 20-turn arc still feels balanced.
function segmentSpans(turnBudget: number): Record<StageKey, number> {
  const mid = turnBudget / 2
  return {
    hook: 2,
    pressure: Math.max(1, Math.floor(mid - 0.5) - 2),
    reversal: 1,
    climax: Math.max(1, turnBudget - 1 - Math.ceil(mid + 0.5)),
    pre_finale: 1,
  }
}

export function StageProgressBar({
  turnIndex,
  turnBudget,
}: {
  turnIndex: number
  turnBudget: number
}) {
  // turn_index here is the most recent COMPLETED narrator beat ord/2
  // (i.e. session.turn_count). Mark the current stage as the one for
  // (turn_count + 1) — the upcoming turn — so the bar reads as "where
  // the story is heading next" rather than "where it just was".
  const t = useT()
  const upcoming = Math.min(turnBudget - 1, turnIndex + 1)
  const currentStage = stageForTurn(upcoming, turnBudget)
  const spans = segmentSpans(turnBudget)
  const totalSpan = Object.values(spans).reduce((a, b) => a + b, 0)
  const stageOrder = STAGES.map((s) => s.key)
  const currentIdx = stageOrder.indexOf(currentStage)
  const currentLabel = STAGES[currentIdx]
    ? t(STAGES[currentIdx].labelKey as Parameters<typeof t>[0])
    : ""

  return (
    <div style={styles.row}>
      <div style={styles.label}>
        <span style={styles.stageName}>{currentLabel}</span>
        <span style={styles.turnCount}>
          {Math.min(turnIndex, turnBudget)}/{turnBudget}
        </span>
      </div>
      <div
        style={styles.bar}
        aria-label={t("stage_bar.aria", {
          turn: turnIndex,
          total: turnBudget,
          stage: currentLabel,
        })}
      >
        {STAGES.map((stage, idx) => {
          const span = spans[stage.key]
          const widthPct = (span / totalSpan) * 100
          const state =
            idx < currentIdx
              ? "past"
              : idx === currentIdx
                ? "current"
                : "future"
          const stateStyle =
            state === "current"
              ? styles.segCurrent
              : state === "past"
                ? styles.segPast
                : styles.segFuture
          return (
            <div
              key={stage.key}
              style={{ ...styles.segment, ...stateStyle, flex: `${widthPct} 0 0%` }}
            >
              {state === "current" ? (
                <motion.div
                  style={styles.currentGlow}
                  animate={{ opacity: [0.55, 0.9, 0.55] }}
                  transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
                />
              ) : null}
              <span style={styles.segLabel}>{t(stage.labelKey as Parameters<typeof t>[0])}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const styles: Record<string, CSSProperties> = {
  row: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
    marginBottom: 26,
  },
  label: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    fontSize: 12,
  },
  stageName: {
    fontFamily: "var(--font-narrative)",
    fontSize: 15,
    color: "var(--text)",
    letterSpacing: "0.04em",
    fontWeight: 500,
  },
  // Turn count rendered tabular-nums so the digits don't shift width
  // as the count climbs. Larger + brighter than before — was 11/faint,
  // hard to spot.
  turnCount: {
    color: "var(--text-muted)",
    fontSize: 13,
    letterSpacing: "0.04em",
    fontVariantNumeric: "tabular-nums",
    fontWeight: 500,
  },
  // 28px bar (was 22) — enough for the segment label glyphs to read
  // without squinting. Slight bg lift so empty future segments aren't
  // invisible against the page background.
  bar: {
    display: "flex",
    width: "100%",
    height: 28,
    background: "rgba(255,255,255,0.025)",
    border: "1px solid var(--line)",
    borderRadius: 6,
    overflow: "hidden",
  },
  segment: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minWidth: 0,
    transition: "background 0.4s ease, color 0.4s ease",
  },
  segCurrent: {
    background:
      "linear-gradient(180deg, rgba(212,168,83,0.22), rgba(212,168,83,0.08))",
    color: "rgba(245,210,140,0.96)",
    fontWeight: 600,
  },
  // Past stages — read as "completed". Brighter than the previous
  // 0.10 fill so finished stages are clearly visible at a glance.
  segPast: {
    background: "rgba(140,100,200,0.18)",
    color: "rgba(200,170,235,0.82)",
  },
  segFuture: {
    background: "transparent",
    color: "var(--text-faint)",
  },
  currentGlow: {
    position: "absolute",
    inset: 0,
    background:
      "linear-gradient(90deg, transparent, rgba(245,210,140,0.18), transparent)",
    pointerEvents: "none",
  },
  segLabel: {
    position: "relative",
    zIndex: 1,
    fontSize: 11,
    letterSpacing: "0.06em",
  },
}
