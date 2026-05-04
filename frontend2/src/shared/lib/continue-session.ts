// Tracks the most recent in-progress play session so the Home page can offer "Continue".
// Persisted to localStorage so a refresh keeps the affordance alive.

const KEY = "tinystories.last_session_v1"

export type ContinueSession = {
  session_id: string
  story_id: string
  story_title: string
  beat_title: string
  turn_index: number
  saved_at: number
}

export function readContinueSession(): ContinueSession | null {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return null
    return JSON.parse(raw) as ContinueSession
  } catch {
    return null
  }
}

export function writeContinueSession(session: ContinueSession) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(session))
  } catch {
    // ignore quota / private mode
  }
}

export function clearContinueSession() {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // ignore
  }
}
