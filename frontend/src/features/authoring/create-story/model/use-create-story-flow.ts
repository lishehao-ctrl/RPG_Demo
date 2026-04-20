import { useEffect, useMemo, useState } from "react"
import type { AuthorPreviewResponse, PlayLengthPreset, TargetGenderPref } from "../../../../index"
import { useApiClient } from "../../../../app/providers/api-client-provider"
import { toErrorMessage } from "../../../../shared/lib/errors"

const DEFAULT_SEED = ""
const DEFAULT_PLAY_LENGTH_PRESET: PlayLengthPreset = "12_15"
const DEFAULT_TARGET_GENDER_PREF: TargetGenderPref | null = null

export function useCreateStoryFlow() {
  const api = useApiClient()
  const [seed, setSeed] = useState(DEFAULT_SEED)
  const [playLengthPreset, setPlayLengthPreset] = useState<PlayLengthPreset>(DEFAULT_PLAY_LENGTH_PRESET)
  const [targetGenderPref, setTargetGenderPref] = useState<TargetGenderPref | null>(DEFAULT_TARGET_GENDER_PREF)
  const [preview, setPreview] = useState<AuthorPreviewResponse | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [jobLoading, setJobLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const flashcards = useMemo(() => preview?.flashcards ?? [], [preview])

  useEffect(() => {
    setPreview(null)
    setPreviewLoading(false)
    setJobLoading(false)
    setError(null)
  }, [api])

  const updateSeed = (nextSeed: string) => {
    setSeed(nextSeed)
    if (preview && preview.prompt_seed !== nextSeed) {
      setPreview(null)
    }
  }

  const updatePlayLengthPreset = (nextPreset: PlayLengthPreset) => {
    setPlayLengthPreset(nextPreset)
    if (preview && preview.play_length_preset !== nextPreset) {
      setPreview(null)
    }
  }

  const updateTargetGenderPref = (nextPref: TargetGenderPref | null) => {
    setTargetGenderPref(nextPref)
    if (preview) {
      setPreview(null)
    }
  }

  const requestPreview = async () => {
    const trimmedSeed = seed.trim()
    if (!trimmedSeed) {
      setError("先写下一句故事种子，再生成预览。")
      return null
    }

    setPreviewLoading(true)
    setError(null)

    try {
      const nextPreview = await api.createStoryPreview({
        prompt_seed: trimmedSeed,
        play_length_preset: playLengthPreset,
        target_gender_pref: targetGenderPref,
      })
      setPreview(nextPreview)
      return nextPreview
    } catch (nextError) {
      setError(toErrorMessage(nextError))
      return null
    } finally {
      setPreviewLoading(false)
    }
  }

  const createAuthorJob = async () => {
    if (!preview) {
      setError("先生成预览，再开始正式编写。")
      return null
    }

    setJobLoading(true)
    setError(null)

    try {
      const job = await api.createAuthorJob({
        prompt_seed: preview.prompt_seed,
        preview_id: preview.preview_id,
        play_length_preset: playLengthPreset,
      })
      return job.job_id
    } catch (nextError) {
      setError(toErrorMessage(nextError))
      return null
    } finally {
      setJobLoading(false)
    }
  }

  return {
    seed,
    playLengthPreset,
    targetGenderPref,
    preview,
    flashcards,
    previewLoading,
    jobLoading,
    error,
    updateSeed,
    updatePlayLengthPreset,
    updateTargetGenderPref,
    requestPreview,
    createAuthorJob,
  }
}
