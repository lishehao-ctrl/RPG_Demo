/**
 * Per-session bookmarks for "this beat hit me, remember it" moments.
 *
 * Persists to localStorage keyed by sessionId, so re-opening a run
 * (refresh, back nav) shows the same marked moments. Returns a hook
 * with a stable Set + toggle so consumers can render the marker
 * state and respond to clicks.
 *
 * The bookmarks are merged into the LLM's highlight list at end-of-
 * run — user-marked beats appear at the top, with their own visual
 * badge so they read as "your call" rather than "what the system
 * thought was important."
 */

import { useCallback, useEffect, useState } from "react"

const KEY_PREFIX = "tiny-stories-bookmarks-"

function readBookmarks(sessionId: string): Set<number> {
  if (typeof window === "undefined") return new Set()
  try {
    const raw = window.localStorage.getItem(`${KEY_PREFIX}${sessionId}`)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    const out = new Set<number>()
    for (const v of parsed) {
      if (typeof v === "number" && Number.isFinite(v)) out.add(v)
    }
    return out
  } catch {
    return new Set()
  }
}

function writeBookmarks(sessionId: string, marked: Set<number>): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      `${KEY_PREFIX}${sessionId}`,
      JSON.stringify(Array.from(marked).sort((a, b) => a - b)),
    )
  } catch {
    // Silently no-op on storage quota / private mode.
  }
}

export function useBookmarks(sessionId: string) {
  const [marked, setMarked] = useState<Set<number>>(() => readBookmarks(sessionId))

  // If sessionId changes (e.g. user navigates between sessions
  // without unmounting the host component), re-load from storage.
  useEffect(() => {
    setMarked(readBookmarks(sessionId))
  }, [sessionId])

  const toggle = useCallback(
    (ord: number) => {
      setMarked((prev) => {
        const next = new Set(prev)
        if (next.has(ord)) next.delete(ord)
        else next.add(ord)
        writeBookmarks(sessionId, next)
        return next
      })
    },
    [sessionId],
  )

  return { marked, toggle, count: marked.size }
}
