import { type CSSProperties, useEffect, useState } from "react"
import type { PlayLengthPreset, TargetGenderPref } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"

type LengthChoice = "short" | "medium" | "long"

const LENGTH_OPTIONS: Array<{ id: LengthChoice; label: string; time: string; desc: string; preset: PlayLengthPreset }> = [
  { id: "short", label: "短", time: "5–10 分钟", desc: "一个场景，三两次选择", preset: "5_8" },
  { id: "medium", label: "中", time: "15–25 分钟", desc: "三幕结构，节奏紧凑", preset: "12_15" },
  { id: "long", label: "长", time: "40–60 分钟", desc: "多线索，余波叠加", preset: "20_25" },
]

type GenderChoice = "any" | "f" | "m"

const GENDER_OPTIONS: Array<{ id: GenderChoice; label: string; pref: TargetGenderPref | null }> = [
  { id: "any", label: "不限", pref: null },
  { id: "f", label: "女性优先", pref: "female" },
  { id: "m", label: "男性优先", pref: "male" },
]

const PLACEHOLDER = `比如 —
凌晨两点的便利店，常客没来，但他的伞在门口…

或者 —
1987 年敦煌，年轻助理在老师傅的笔记本里，读到自己写的字…

写下任何故事的开端 — 人物、场景、悬念、矛盾。`

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
  const [gender, setGender] = useState<GenderChoice>("any")
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Author flow requires a real account.
  useEffect(() => {
    if (auth.loading) return
    if (auth.isAnonymous) {
      window.location.hash = "#/login?next=create"
    }
  }, [auth.loading, auth.isAnonymous])

  const handleSubmit = async () => {
    if (!seed.trim()) {
      setError("先写一句开头吧。")
      return
    }
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const preset = LENGTH_OPTIONS.find((o) => o.id === length)?.preset ?? "12_15"
      const job = await api.createAuthorJob({
        prompt_seed: seed.trim(),
        play_length_preset: preset,
        // TODO: backend createAuthorJob doesn't yet accept target_gender_pref;
        // gender selection is collected here for future wiring.
      })
      onJobCreated(job.job_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法开始生成，请稍后再试。")
      setSubmitting(false)
    }
  }

  // Mark gender as used until wired through to the backend job request.
  void gender

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
          <span className="ts-tag" style={{ marginBottom: 28 }}>
            新故事
          </span>
          <h1 style={cpStyles.title}>
            写下开头，
            <br />
            剩下的交给 AI。
          </h1>
          <p style={cpStyles.sub}>几分钟后，它会变成一场你可以亲自玩的剧情。</p>

          <div style={cpStyles.textareaWrap}>
            <textarea
              style={cpStyles.textarea}
              placeholder={PLACEHOLDER}
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              spellCheck={false}
              disabled={submitting}
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
                disabled={submitting}
              >
                <div style={cpStyles.chipLabel}>{o.label}</div>
                <div style={cpStyles.chipTime}>{o.time}</div>
                <div style={cpStyles.chipDesc}>{o.desc}</div>
              </button>
            ))}
          </div>

          <div style={cpStyles.advanced}>
            <button
              className="ts-link-dashed"
              style={{
                background: "none",
                border: "none",
                borderBottom: "1px dashed var(--line-strong)",
                color: "var(--text-muted)",
                fontSize: 13,
                paddingBottom: 2,
              }}
              onClick={() => setAdvancedOpen(!advancedOpen)}
            >
              高级选项 {advancedOpen ? "↑" : "↓"}
            </button>
            {advancedOpen && (
              <div style={cpStyles.advancedBody}>
                <div style={cpStyles.fieldLabelSm}>主角性别偏好</div>
                <div style={cpStyles.smallChips}>
                  {GENDER_OPTIONS.map((g) => (
                    <button
                      key={g.id}
                      style={{
                        ...cpStyles.smallChip,
                        ...(gender === g.id ? cpStyles.smallChipActive : {}),
                      }}
                      onClick={() => setGender(g.id)}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {error ? <div style={cpStyles.error}>{error}</div> : null}

          <div style={cpStyles.actions}>
            <button
              className="ts-btn ts-btn--primary ts-btn--lg"
              style={{
                minWidth: 200,
                opacity: !seed.trim() || submitting ? 0.5 : 1,
                pointerEvents: !seed.trim() || submitting ? "none" : "auto",
              }}
              onClick={() => void handleSubmit()}
            >
              {submitting ? "正在发往 AI..." : "写一个故事"}
            </button>
            <button
              className="ts-btn ts-btn--ghost ts-btn--lg"
              onClick={onBackHome}
              disabled={submitting}
            >
              返回
            </button>
          </div>
        </div>
      </main>
    </div>
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

  actions: { display: "flex", alignItems: "center", gap: 12 },
}
