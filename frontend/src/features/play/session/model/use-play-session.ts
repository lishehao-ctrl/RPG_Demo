import { useEffect, useState } from "react"
import type { PlayControlAction, PlaySessionHistoryEntry, PlaySessionSnapshot, PlaySuggestedAction } from "../../../../index"
import { useApiClient } from "../../../../app/providers/api-client-provider"
import { toErrorMessage } from "../../../../shared/lib/errors"

type TranscriptEntry = {
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

function optimisticTranscriptAppend(
  current: TranscriptEntry[],
  {
    turnIndex,
    playerText,
    gmText,
  }: {
    turnIndex: number
    playerText: string
    gmText: string
  },
): TranscriptEntry[] {
  return [
    ...current,
    {
      id: `player-${turnIndex}-${current.length}`,
      speaker: "player",
      text: playerText,
    },
    {
      id: `gm-${turnIndex}-${current.length + 1}`,
      speaker: "gm",
      text: gmText,
    },
  ]
}

export function usePlaySession(sessionId: string) {
  const api = useApiClient()
  const [snapshot, setSnapshot] = useState<PlaySessionSnapshot | null>(null)
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [inputText, setInputText] = useState("")
  const [pendingTurnInput, setPendingTurnInput] = useState<string | null>(null)
  const [selectedSuggestionId, setSelectedSuggestionId] = useState<string | null>(null)
  const [selectedStoryActionId, setSelectedStoryActionId] = useState<string | null>(null)
  const [selectedControlAction, setSelectedControlAction] = useState<PlayControlAction | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true

    const loadSession = async () => {
      setLoading(true)
      setSnapshot(null)
      setTranscript([])
      try {
        const [nextSnapshot, nextHistory] = await Promise.all([
          api.getPlaySession(sessionId),
          api.getPlaySessionHistory(sessionId),
        ])
        if (active) {
          setSnapshot(nextSnapshot)
          setTranscript(transcriptFromHistory(nextHistory.entries))
          setError(null)
        }
      } catch (nextError) {
        if (active) {
          setSnapshot(null)
          setTranscript([])
          setError(toErrorMessage(nextError))
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    void loadSession()

    return () => {
      active = false
    }
  }, [api, sessionId])

  const selectSuggestedAction = (action: PlaySuggestedAction) => {
    setSelectedSuggestionId(action.suggestion_id)
    setSelectedStoryActionId(action.suggestion_id)
    setSelectedControlAction(null)
    setInputText(action.prompt)
  }

  const selectControlAction = (action: PlayControlAction) => {
    setSelectedControlAction(action)
    setSelectedSuggestionId(null)
    setSelectedStoryActionId(null)
    setInputText(action.prompt)
  }

  const updateInputText = (nextText: string) => {
    setInputText(nextText)
    if (!nextText.trim()) {
      setSelectedSuggestionId(null)
      setSelectedStoryActionId(null)
      setSelectedControlAction(null)
      return
    }
    if (snapshot) {
      const storyPool = snapshot.story_actions?.length ? snapshot.story_actions : snapshot.suggested_actions
      const matchedStory = storyPool.find((item) => item.prompt === nextText)
      if (matchedStory) {
        setSelectedSuggestionId(matchedStory.suggestion_id)
        setSelectedStoryActionId(matchedStory.suggestion_id)
        setSelectedControlAction(null)
        return
      }

      const matchedControl = snapshot.control_actions?.find((item) => item.prompt === nextText)
      if (matchedControl) {
        setSelectedSuggestionId(null)
        setSelectedStoryActionId(null)
        setSelectedControlAction(matchedControl)
        return
      }
    }
    setSelectedSuggestionId(null)
    setSelectedStoryActionId(null)
    setSelectedControlAction(null)
  }

  const submitTurn = async () => {
    if (!snapshot) {
      return
    }

    const trimmedInput = inputText.trim()
    if (!trimmedInput) {
      setError("Write your action before sending the turn.")
      return
    }

    setSubmitting(true)
    setError(null)
    setPendingTurnInput(trimmedInput)
    setInputText("")

    try {
      const nextSnapshot = await api.submitPlayTurn(sessionId, {
        input_text: trimmedInput,
        selected_suggestion_id: selectedSuggestionId,
        selected_story_action_id: selectedStoryActionId,
        selected_control_action_id: selectedControlAction?.action_id,
        control_action: selectedControlAction?.action_type,
        control_target_kind: selectedControlAction?.target_kind ?? null,
        control_target_id: selectedControlAction?.target_id ?? null,
        control_target_mode: selectedControlAction?.target_mode ?? null,
      })
      setSnapshot(nextSnapshot)
      setPendingTurnInput(null)
      setSelectedSuggestionId(null)
      setSelectedStoryActionId(null)
      setSelectedControlAction(null)
      setTranscript((current) =>
        optimisticTranscriptAppend(current, {
          turnIndex: nextSnapshot.turn_index,
          playerText: trimmedInput,
          gmText: nextSnapshot.narration,
        }),
      )

      try {
        const nextHistory = await api.getPlaySessionHistory(sessionId)
        setTranscript(transcriptFromHistory(nextHistory.entries))
        setError(null)
      } catch (historyError) {
        setError(`Turn applied, but transcript refresh failed: ${toErrorMessage(historyError)}`)
      }
    } catch (nextError) {
      setError(toErrorMessage(nextError))
      setInputText(trimmedInput)
      setPendingTurnInput(null)
    } finally {
      setSubmitting(false)
    }
  }

  return {
    snapshot,
    transcript,
    inputText,
    pendingTurnInput,
    selectedSuggestionId,
    selectedControlActionId: selectedControlAction?.action_id ?? null,
    loading,
    submitting,
    error,
    setInputText: updateInputText,
    selectSuggestedAction,
    selectControlAction,
    submitTurn,
  }
}
