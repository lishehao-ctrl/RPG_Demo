import { useEffect, useRef, useState } from "react"
import type {
  PlayControlAction,
  PlaySessionHistoryEntry,
  PlaySessionSnapshot,
  PlaySuggestedAction,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { writeContinueSession } from "../../shared/lib/continue-session"

export type TranscriptEntry = {
  id: string
  speaker: "gm" | "player"
  text: string
}

function transcriptFromHistory(entries: PlaySessionHistoryEntry[]): TranscriptEntry[] {
  return entries.map((entry, index) => ({
    id: `${entry.speaker}-${entry.turn_index}-${index}-${entry.created_at}`,
    speaker: entry.speaker,
    text: entry.text,
  }))
}

type SubmitOptions = {
  inputText: string
  storyAction?: PlaySuggestedAction | null
  controlAction?: PlayControlAction | null
}

export function usePlaySession(sessionId: string) {
  const api = useApi()
  const [snapshot, setSnapshot] = useState<PlaySessionSnapshot | null>(null)
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingPlayerText, setPendingPlayerText] = useState<string | null>(null)
  const isMounted = useRef(true)

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
    }
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setSnapshot(null)
    setTranscript([])
    setError(null)

    const load = async () => {
      try {
        const [snap, hist] = await Promise.all([
          api.getPlaySession(sessionId),
          api.getPlaySessionHistory(sessionId),
        ])
        if (!active) return
        setSnapshot(snap)
        setTranscript(transcriptFromHistory(hist.entries))
      } catch (err) {
        if (!active) return
        setError(err instanceof Error ? err.message : "无法加载会话")
      } finally {
        if (active) setLoading(false)
      }
    }

    void load()
    return () => {
      active = false
    }
  }, [api, sessionId])

  // Persist continue marker whenever snapshot updates.
  useEffect(() => {
    if (!snapshot) return
    if (snapshot.status !== "active") return
    writeContinueSession({
      session_id: snapshot.session_id,
      story_id: snapshot.story_id,
      story_title: snapshot.story_title,
      beat_title: snapshot.beat_title,
      turn_index: snapshot.turn_index,
      saved_at: Date.now(),
    })
  }, [snapshot])

  const submitTurn = async ({ inputText, storyAction, controlAction }: SubmitOptions) => {
    const trimmed = inputText.trim()
    if (!trimmed) {
      setError("先写一句话或挑一张动作卡。")
      return
    }
    if (submitting) return

    setSubmitting(true)
    setError(null)
    setPendingPlayerText(trimmed)

    try {
      const next = await api.submitPlayTurn(sessionId, {
        input_text: trimmed,
        selected_suggestion_id: storyAction?.suggestion_id ?? null,
        selected_story_action_id: storyAction?.suggestion_id ?? null,
        selected_control_action_id: controlAction?.action_id ?? null,
        control_action: controlAction?.action_type,
        control_target_kind: controlAction?.target_kind ?? null,
        control_target_id: controlAction?.target_id ?? null,
        control_target_mode: controlAction?.target_mode ?? null,
      })
      if (!isMounted.current) return
      setSnapshot(next)
      try {
        const hist = await api.getPlaySessionHistory(sessionId)
        if (isMounted.current) setTranscript(transcriptFromHistory(hist.entries))
      } catch {
        // transcript fetch best-effort
      }
    } catch (err) {
      if (isMounted.current) {
        setError(err instanceof Error ? err.message : "提交失败")
      }
    } finally {
      if (isMounted.current) {
        setSubmitting(false)
        setPendingPlayerText(null)
      }
    }
  }

  return {
    snapshot,
    transcript,
    loading,
    submitting,
    error,
    pendingPlayerText,
    submitTurn,
    clearError: () => setError(null),
  }
}
