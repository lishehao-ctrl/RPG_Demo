import { type FormEvent, useEffect, useState } from "react"
import { motion } from "motion/react"
import type { PlayLengthPreset, TargetGenderPref } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { Button, ErrorState, Tag } from "../../shared/ui/primitives"

const LENGTH_OPTIONS: Array<{ value: PlayLengthPreset; label: string; minutes: string; hint: string }> = [
  { value: "5_8", label: "短", minutes: "5–8 分钟", hint: "一场冲突，快速到结局" },
  { value: "12_15", label: "中", minutes: "12–15 分钟", hint: "几个角色，几幕节奏" },
  { value: "20_25", label: "长", minutes: "20–25 分钟", hint: "更复杂的关系网与转折" },
]

const GENDER_OPTIONS: Array<{ value: TargetGenderPref | null; label: string }> = [
  { value: null, label: "不限" },
  { value: "female", label: "女性优先" },
  { value: "male", label: "男性优先" },
]

const PLACEHOLDER = `比如：
深夜的便利店，三个旧同学在店外重逢，每个人都带着一个不能说的近况...

或者：
一个考古学家收到了一封 30 年前寄出的信，落款是她自己。

写下任何故事的开端 — 人物、场景、悬念、矛盾。AI 会把它编成一场可玩的剧情。`

export function CreatePage({
  onBackHome,
  onJobCreated,
}: {
  onBackHome: () => void
  onJobCreated: (jobId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const [seed, setSeed] = useState("")
  const [length, setLength] = useState<PlayLengthPreset>("12_15")
  const [gender, setGender] = useState<TargetGenderPref | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Authoring is the only flow that requires a real account: anonymous viewers
  // can browse and play, but writing a world needs to be attributable.
  useEffect(() => {
    if (auth.loading) return
    if (auth.isAnonymous) {
      window.location.hash = "#/login?next=create"
    }
  }, [auth.loading, auth.isAnonymous])

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (submitting) return
    if (!seed.trim()) {
      setError("先写一句开头吧。")
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      // Single-step: skip the manual preview round-trip. The backend resolves
      // preview→compile internally when no preview_id is supplied.
      const job = await api.createAuthorJob({
        prompt_seed: seed.trim(),
        play_length_preset: length,
      })
      onJobCreated(job.job_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法开始生成，请稍后再试。")
      setSubmitting(false)
    }
  }

  return (
    <div className="page page-create">
      <Header onHome={onBackHome} onCreate={() => undefined} showCreateButton={false} />

      <main className="create-main">
        <motion.form
          className="create-form"
          onSubmit={handleSubmit}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <div className="create-form__heading">
            <Tag tone="accent">新故事</Tag>
            <h1>写下开头，剩下的交给 AI。</h1>
            <p className="create-form__sub">几分钟后，它会变成一场你可以亲自玩的剧情。</p>
          </div>

          <label className="create-seed">
            <textarea
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder={PLACEHOLDER}
              rows={10}
              autoFocus
              disabled={submitting}
            />
            <span className="create-seed__count">{seed.length} 字</span>
          </label>

          <div className="create-length">
            <span className="create-length__label">篇幅</span>
            <div className="create-length__options">
              {LENGTH_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`length-chip ${length === option.value ? "is-active" : ""}`}
                  onClick={() => setLength(option.value)}
                  disabled={submitting}
                >
                  <strong>{option.label}</strong>
                  <span>{option.minutes}</span>
                  <em>{option.hint}</em>
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            className="create-advanced-toggle"
            onClick={() => setAdvancedOpen((v) => !v)}
          >
            {advancedOpen ? "收起" : "高级选项"}
          </button>
          {advancedOpen ? (
            <div className="create-advanced">
              <div>
                <span className="create-length__label">主角性别偏好</span>
                <div className="create-length__options create-length__options--row">
                  {GENDER_OPTIONS.map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      className={`length-chip length-chip--small ${gender === option.value ? "is-active" : ""}`}
                      onClick={() => setGender(option.value)}
                      disabled={submitting}
                    >
                      <strong>{option.label}</strong>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          {error ? <ErrorState message={error} /> : null}

          <div className="create-actions">
            <Button type="submit" variant="primary" size="lg" disabled={submitting || !seed.trim()}>
              {submitting ? "正在开始..." : "写一个故事"}
            </Button>
            <Button type="button" variant="ghost" onClick={onBackHome} disabled={submitting}>
              返回
            </Button>
          </div>
        </motion.form>
      </main>
    </div>
  )
}
