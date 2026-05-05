import { type CSSProperties, useEffect, useState } from "react"
import type { NarrativeTemplateVisibility } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"

const PLACEHOLDER = `比如 —
公司年会的红毯上，前任的现任搂着前任向我走来...

或者 —
分手那天晚上，他给我妹妹打了一通电话...

写一句故事的开端，越具体越好。AI 会立刻为你搭起人物、关系、第一个戏剧时刻。`

const VISIBILITY_OPTIONS: Array<{
  id: NarrativeTemplateVisibility
  label: string
  desc: string
}> = [
  { id: "private", label: "只有我", desc: "只有你能玩这个故事" },
  { id: "unlisted", label: "凭链接", desc: "把链接发给朋友，他们能玩出自己的剧情" },
  { id: "public", label: "广场公开", desc: "任何人都能看到、玩你的故事" },
]

export function CreatePage({
  onBackHome,
  onSessionStarted,
}: {
  onBackHome: () => void
  onSessionStarted: (sessionId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const [seed, setSeed] = useState("")
  const [visibility, setVisibility] = useState<NarrativeTemplateVisibility>("private")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Author flow requires a real account.
  useEffect(() => {
    if (auth.loading) return
    if (auth.isAnonymous) {
      window.location.hash = "#/login?next=create"
    }
  }, [auth.loading, auth.isAnonymous])

  const handleCreate = async () => {
    const trimmed = seed.trim()
    if (!trimmed) {
      setError("先写一句开头吧。")
      return
    }
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const response = await api.createNarrativeTemplate({ seed: trimmed, visibility })
      onSessionStarted(response.session.session_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法创建故事，请稍后再试。")
      setBusy(false)
    }
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
          <span className="ts-tag" style={{ marginBottom: 28 }}>新故事</span>
          <h1 style={cpStyles.title}>
            写下开头，
            <br />
            剩下的交给 AI。
          </h1>
          <p style={cpStyles.sub}>
            一句话即可。AI 会为你搭好人物、关系、第一个戏剧时刻——
            然后你立刻接手往下玩。
          </p>

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

          <div style={cpStyles.fieldLabel}>谁能玩这个故事</div>
          <div style={cpStyles.visibility}>
            {VISIBILITY_OPTIONS.map((o) => (
              <button
                key={o.id}
                style={{
                  ...cpStyles.visBtn,
                  ...(visibility === o.id ? cpStyles.visBtnActive : {}),
                }}
                onClick={() => setVisibility(o.id)}
                disabled={busy}
                type="button"
              >
                <div style={cpStyles.visBtnLabel}>{o.label}</div>
                <div style={cpStyles.visBtnDesc}>{o.desc}</div>
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
              onClick={() => void handleCreate()}
            >
              {busy ? "AI 正在搭建故事..." : "开始这个故事 →"}
            </button>
            <button className="ts-btn ts-btn--ghost ts-btn--lg" onClick={onBackHome} disabled={busy}>
              返回
            </button>
          </div>

          {busy ? (
            <div style={cpStyles.busyHint}>
              第一次需要 5–10 秒：AI 正在为你的种子搭建场景、人物和顾问。
            </div>
          ) : null}
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

  visibility: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 32 },
  visBtn: {
    textAlign: "left",
    padding: "16px 18px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    color: "var(--text)",
    transition: "all 180ms",
  },
  visBtnActive: {
    borderColor: "var(--accent)",
    background: "var(--accent-soft)",
  },
  visBtnLabel: { fontSize: 15, fontWeight: 600, marginBottom: 6 },
  visBtnDesc: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.4 },

  error: { marginBottom: 16, fontSize: 13, color: "var(--warn)" },
  actions: { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" },
  busyHint: {
    marginTop: 24,
    fontSize: 13,
    color: "var(--text-faint)",
    lineHeight: 1.5,
  },
}
