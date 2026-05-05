import { type CSSProperties, useEffect, useState } from "react"
import type { AuthorPreviewResponse, PlayLengthPreset } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"

type LengthChoice = "short" | "medium" | "long"

const LENGTH_OPTIONS: Array<{ id: LengthChoice; label: string; time: string; desc: string; preset: PlayLengthPreset }> = [
  { id: "short", label: "短", time: "5–10 分钟", desc: "一个场景，三两次选择", preset: "5_8" },
  { id: "medium", label: "中", time: "15–25 分钟", desc: "三幕结构，节奏紧凑", preset: "12_15" },
  { id: "long", label: "长", time: "40–60 分钟", desc: "多线索，余波叠加", preset: "20_25" },
]

// Maps the backend's StoryShellId → user-facing Chinese label so the review
// card reads naturally instead of showing the raw enum.
const SHELL_LABELS: Record<string, string> = {
  wealth_families: "豪门",
  office_power: "都市职场",
  entertainment_scandal: "娱乐圈",
  campus_romance: "校园",
  urban_supernatural: "都市怪谈",
}

const PLACEHOLDER = `比如 —
公司年会前夜，我作为新晋总监被三个高管同时盯上...

或者 —
家宴主桌，未婚夫的旧爱突然带着遗嘱坐到我对面...

写下任何故事的开端 — 当前版本聚焦：豪门 / 职场 / 娱乐圈 / 校园 / 都市怪谈，五种关系剧。`

type Phase = "input" | "reviewing"

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
  const [length, setLength] = useState<LengthChoice>("medium")
  const [phase, setPhase] = useState<Phase>("input")
  const [preview, setPreview] = useState<AuthorPreviewResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Author flow requires a real account.
  useEffect(() => {
    if (auth.loading) return
    if (auth.isAnonymous) {
      window.location.hash = "#/login?next=create"
    }
  }, [auth.loading, auth.isAnonymous])

  // Step 1: send seed to the preview endpoint and surface AI's interpretation
  // for the user to confirm. The whole point of this review phase is to make
  // the "system silently rewrites your prompt" behaviour visible — when the
  // user wrote a fantasy seed and it got reshaped into wealth_families, they
  // can see it and either accept or rewrite their prompt.
  const handleReview = async () => {
    if (!seed.trim()) {
      setError("先写一句开头吧。")
      return
    }
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const preset = LENGTH_OPTIONS.find((o) => o.id === length)?.preset ?? "12_15"
      const response = await api.createStoryPreview({
        prompt_seed: seed.trim(),
        play_length_preset: preset,
      })
      setPreview(response)
      setPhase("reviewing")
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法获取 AI 解读，请稍后再试。")
    } finally {
      setBusy(false)
    }
  }

  // Step 2: user accepted the interpretation — kick off the full author job,
  // reusing the preview_id so the backend doesn't redo the normalize work.
  const handleConfirmGenerate = async () => {
    if (!preview) return
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const preset = LENGTH_OPTIONS.find((o) => o.id === length)?.preset ?? "12_15"
      const job = await api.createAuthorJob({
        prompt_seed: preview.prompt_seed,
        preview_id: preview.preview_id,
        play_length_preset: preset,
      })
      onJobCreated(job.job_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法开始生成，请稍后再试。")
      setBusy(false)
    }
  }

  const handleEditPrompt = () => {
    setPhase("input")
    setError(null)
    // Keep `preview` around so the user can flip back without losing it.
  }

  return (
    <div style={cpStyles.page}>
      <header style={cpStyles.header}>
        <button style={cpStyles.brandLink} onClick={onBackHome}>
          <span
            style={{
              color: "var(--accent)",
              fontSize: 22,
              lineHeight: 1,
              transform: "translateY(-2px)",
              display: "inline-block",
            }}
          >
            ·
          </span>
          <span style={cpStyles.brandName}>Tiny Stories</span>
        </button>
      </header>

      <main style={cpStyles.main}>
        <div style={cpStyles.inner}>
          {phase === "input" ? (
            <InputPhase
              seed={seed}
              setSeed={setSeed}
              length={length}
              setLength={setLength}
              busy={busy}
              error={error}
              onReview={handleReview}
              onBack={onBackHome}
            />
          ) : (
            <ReviewPhase
              preview={preview}
              busy={busy}
              error={error}
              onConfirm={handleConfirmGenerate}
              onEdit={handleEditPrompt}
              onBack={onBackHome}
            />
          )}
        </div>
      </main>
    </div>
  )
}

// ---------------- input phase ----------------

function InputPhase({
  seed,
  setSeed,
  length,
  setLength,
  busy,
  error,
  onReview,
  onBack,
}: {
  seed: string
  setSeed: (v: string) => void
  length: LengthChoice
  setLength: (v: LengthChoice) => void
  busy: boolean
  error: string | null
  onReview: () => void
  onBack: () => void
}) {
  return (
    <>
      <span className="ts-tag" style={{ marginBottom: 28 }}>新故事</span>
      <h1 style={cpStyles.title}>
        写下开头，
        <br />
        剩下的交给 AI。
      </h1>
      <p style={cpStyles.sub}>下一步会让你确认 AI 怎么理解你的设定，再正式生成。</p>

      <div style={cpStyles.textareaWrap}>
        <textarea
          style={cpStyles.textarea}
          placeholder={PLACEHOLDER}
          value={seed}
          onChange={(e) => setSeed(e.target.value)}
          spellCheck={false}
          disabled={busy}
        />
        <div style={cpStyles.count}>{seed.length} 字</div>
      </div>

      <div style={cpStyles.fieldLabel}>篇幅</div>
      <div style={cpStyles.chips}>
        {LENGTH_OPTIONS.map((o) => (
          <button
            key={o.id}
            style={{
              ...cpStyles.chip,
              ...(length === o.id ? cpStyles.chipActive : {}),
            }}
            onClick={() => setLength(o.id)}
            disabled={busy}
          >
            <div style={cpStyles.chipLabel}>{o.label}</div>
            <div style={cpStyles.chipTime}>{o.time}</div>
            <div style={cpStyles.chipDesc}>{o.desc}</div>
          </button>
        ))}
      </div>

      {error ? <div style={cpStyles.error}>{error}</div> : null}

      <div style={cpStyles.actions}>
        <button
          className="ts-btn ts-btn--primary ts-btn--lg"
          style={{
            minWidth: 240,
            opacity: !seed.trim() || busy ? 0.5 : 1,
            pointerEvents: !seed.trim() || busy ? "none" : "auto",
          }}
          onClick={() => void onReview()}
        >
          {busy ? "AI 正在解读..." : "看看 AI 怎么理解 →"}
        </button>
        <button className="ts-btn ts-btn--ghost ts-btn--lg" onClick={onBack} disabled={busy}>
          返回
        </button>
      </div>
    </>
  )
}

// ---------------- review phase ----------------

function ReviewPhase({
  preview,
  busy,
  error,
  onConfirm,
  onEdit,
  onBack,
}: {
  preview: AuthorPreviewResponse | null
  busy: boolean
  error: string | null
  onConfirm: () => void
  onEdit: () => void
  onBack: () => void
}) {
  if (!preview) {
    return <div style={cpStyles.error}>预览数据丢失，请回到上一步重试。</div>
  }

  const shellLabel = SHELL_LABELS[preview.story_shell_id ?? ""] ?? preview.story_shell_id ?? "关系剧"
  const tone = preview.story?.tone ?? preview.focused_brief?.tone_signal ?? ""
  const cast = preview.cast_slots?.length ?? preview.structure?.expected_npc_count ?? 0
  const beats = preview.beats?.length ?? preview.structure?.expected_beat_count ?? 0

  return (
    <>
      <span className="ts-tag" style={{ marginBottom: 28 }}>AI 解读</span>
      <h1 style={cpStyles.title}>AI 把你的设定理解成这样。</h1>
      <p style={cpStyles.sub}>
        看一眼系统的解读 — 觉得对路就生成；想要别的味道就改 prompt 再试。
      </p>

      {/* Original seed quoted back */}
      <div style={cpStyles.reviewBlock}>
        <div style={cpStyles.reviewBlockLabel}>你写的</div>
        <div style={cpStyles.reviewSeedQuote}>{preview.prompt_seed}</div>
      </div>

      {/* Shell + tone + cast/beats tags */}
      <div style={cpStyles.reviewTags}>
        <span className="ts-tag" style={{ background: "var(--accent-softer)" }}>
          {shellLabel}
        </span>
        {tone ? <span className="ts-tag ts-tag--muted">{tone}</span> : null}
        <span className="ts-tag ts-tag--muted">{cast} 个角色</span>
        <span className="ts-tag ts-tag--muted">{beats} 幕</span>
      </div>

      {/* AI's working title + premise */}
      <div style={cpStyles.reviewBlock}>
        <div style={cpStyles.reviewBlockLabel}>暂定标题</div>
        <div style={cpStyles.reviewTitle}>{preview.story?.title ?? "(未生成标题)"}</div>
      </div>

      {preview.story?.premise ? (
        <div style={cpStyles.reviewBlock}>
          <div style={cpStyles.reviewBlockLabel}>故事前提</div>
          <div style={cpStyles.reviewProse}>{preview.story.premise}</div>
        </div>
      ) : null}

      {preview.relationship_hook ? (
        <div style={cpStyles.reviewBlock}>
          <div style={cpStyles.reviewBlockLabel}>关系钩子</div>
          <div style={cpStyles.reviewProse}>{preview.relationship_hook}</div>
        </div>
      ) : null}

      {preview.secret_hook ? (
        <div style={cpStyles.reviewBlock}>
          <div style={cpStyles.reviewBlockLabel}>秘密钩子</div>
          <div style={cpStyles.reviewProse}>{preview.secret_hook}</div>
        </div>
      ) : null}

      {preview.surface_signal_summary ? (
        <div style={cpStyles.reviewBlock}>
          <div style={cpStyles.reviewBlockLabel}>场景</div>
          <div style={cpStyles.reviewProse}>{preview.surface_signal_summary}</div>
        </div>
      ) : null}

      {preview.story?.route_fantasy ? (
        <div style={cpStyles.reviewBlock}>
          <div style={cpStyles.reviewBlockLabel}>玩法核心</div>
          <div style={cpStyles.reviewProse}>{preview.story.route_fantasy}</div>
        </div>
      ) : null}

      {error ? <div style={cpStyles.error}>{error}</div> : null}

      <div style={cpStyles.actions}>
        <button
          className="ts-btn ts-btn--primary ts-btn--lg"
          style={{
            minWidth: 200,
            opacity: busy ? 0.5 : 1,
            pointerEvents: busy ? "none" : "auto",
          }}
          onClick={() => void onConfirm()}
        >
          {busy ? "正在发往 AI..." : "用这个生成 →"}
        </button>
        <button className="ts-btn ts-btn--ghost ts-btn--lg" onClick={onEdit} disabled={busy}>
          ← 改 prompt
        </button>
        <button
          className="ts-btn ts-btn--ghost ts-btn--lg"
          onClick={onBack}
          disabled={busy}
          style={{ marginLeft: "auto" }}
        >
          返回
        </button>
      </div>
    </>
  )
}

const cpStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)" },
  header: { padding: "18px 40px", borderBottom: "1px solid var(--line)" },
  brandLink: { display: "inline-flex", alignItems: "center", gap: 8 },
  brandName: { fontFamily: "var(--font-narrative)", fontSize: 17 },

  main: { padding: "72px 40px 80px", display: "flex", justifyContent: "center" },
  inner: { width: "100%", maxWidth: 720 },

  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 40,
    lineHeight: 1.15,
    letterSpacing: "-0.005em",
    fontWeight: 400,
    margin: "0 0 16px",
  },
  sub: {
    fontSize: 16,
    lineHeight: 1.55,
    color: "var(--text-muted)",
    margin: "0 0 40px",
  },

  textareaWrap: { position: "relative", marginBottom: 36 },
  textarea: {
    width: "100%",
    minHeight: 200,
    padding: "20px 22px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    fontFamily: "var(--font-narrative)",
    fontSize: 16,
    lineHeight: 1.65,
    color: "var(--text)",
    resize: "vertical",
    outline: "none",
    transition: "border-color 200ms",
  },
  count: {
    position: "absolute",
    right: 16,
    bottom: 12,
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.04em",
  },

  fieldLabel: {
    fontSize: 12,
    color: "var(--text-muted)",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    marginBottom: 12,
  },
  fieldLabelSm: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    marginBottom: 10,
  },

  chips: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 32 },
  chip: {
    textAlign: "left",
    padding: "16px 18px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    color: "var(--text)",
    transition: "all 180ms",
  },
  chipActive: {
    borderColor: "var(--accent)",
    background: "var(--accent-soft)",
  },
  chipLabel: { fontSize: 15, fontWeight: 600, marginBottom: 4 },
  chipTime: { fontSize: 12, color: "var(--accent)", marginBottom: 6, fontWeight: 500 },
  chipDesc: { fontSize: 12, color: "var(--text-muted)" },

  advanced: { marginBottom: 36 },
  advancedBody: {
    marginTop: 16,
    padding: "16px 18px",
    background: "var(--bg-elev)",
    borderRadius: "var(--radius-md)",
    border: "1px solid var(--line)",
  },
  smallChips: { display: "flex", gap: 8 },
  smallChip: {
    padding: "8px 14px",
    background: "transparent",
    border: "1px solid var(--line)",
    borderRadius: 999,
    fontSize: 13,
    color: "var(--text-muted)",
    transition: "all 160ms",
  },
  smallChipActive: { borderColor: "var(--accent)", color: "var(--accent)", background: "var(--accent-softer)" },

  error: {
    marginBottom: 16,
    fontSize: 13,
    color: "var(--warn)",
  },

  actions: { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" },

  // ---------------- review phase ----------------
  reviewBlock: {
    marginBottom: 22,
  },
  reviewBlockLabel: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    marginBottom: 8,
  },
  reviewSeedQuote: {
    fontSize: 14,
    color: "var(--text-muted)",
    lineHeight: 1.6,
    padding: "12px 16px",
    borderLeft: "2px solid var(--line-strong)",
    background: "var(--bg-elev)",
    borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
    fontFamily: "var(--font-narrative)",
    fontStyle: "italic",
  },
  reviewTags: {
    display: "flex",
    gap: 8,
    flexWrap: "wrap",
    marginBottom: 28,
  },
  reviewTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 24,
    lineHeight: 1.25,
    color: "var(--text)",
  },
  reviewProse: {
    fontFamily: "var(--font-narrative)",
    fontSize: 15,
    lineHeight: 1.7,
    color: "var(--text)",
  },
}
