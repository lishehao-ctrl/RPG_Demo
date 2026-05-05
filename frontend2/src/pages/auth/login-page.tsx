import { type CSSProperties, type FormEvent, useState } from "react"
import { useAuth } from "../../app/auth-context"

const USERNAME_PATTERN = /^[A-Za-z0-9_]{2,20}$/

export function LoginPage({
  next,
  onBackHome,
  onOpenCreate: _onOpenCreate,
  onLoggedIn,
}: {
  next?: string
  onBackHome: () => void
  onOpenCreate: () => void
  onLoggedIn: (next?: string) => void
}) {
  void _onOpenCreate
  const auth = useAuth()
  const [name, setName] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e?: FormEvent<HTMLFormElement>) => {
    e?.preventDefault?.()
    if (submitting) return
    const trimmed = name.trim()
    if (!USERNAME_PATTERN.test(trimmed)) {
      setError("用户名 2-20 字符，只能用字母、数字、下划线。")
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await auth.login(trimmed)
      onLoggedIn(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后再试。")
      setSubmitting(false)
    }
  }

  return (
    <div style={lpStyles.page}>
      <header style={lpStyles.header}>
        <button style={lpStyles.brandLink} onClick={onBackHome}>
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
          <span style={{ fontFamily: "var(--font-narrative)", fontSize: 18 }}>Tiny Stories</span>
        </button>
      </header>

      <main style={lpStyles.main}>
        <form style={lpStyles.card} onSubmit={submit}>
          <span className="ts-tag" style={{ marginBottom: 24 }}>
            登录
          </span>
          <h1 style={lpStyles.title}>你叫什么?</h1>
          <p style={lpStyles.sub}>随便起个用户名,没有密码。</p>

          <div style={lpStyles.inputWrap}>
            <span style={lpStyles.at}>@</span>
            <input
              style={lpStyles.input}
              placeholder="比如 shehao"
              value={name}
              onChange={(e) => setName(e.target.value.replace(/^@+/, ""))}
              autoFocus
              spellCheck={false}
              autoComplete="off"
              disabled={submitting}
            />
          </div>

          {error ? <div style={lpStyles.error}>{error}</div> : null}

          <button
            type="submit"
            className="ts-btn ts-btn--primary ts-btn--lg"
            style={{
              width: "100%",
              marginTop: 14,
              opacity: !name.trim() || submitting ? 0.5 : 1,
              pointerEvents: !name.trim() || submitting ? "none" : "auto",
            }}
          >
            {submitting ? "进入中…" : "进入"}
          </button>

          <p style={lpStyles.note}>这是测试期,没有密码、没有邮箱。下个月会改成正式登录。</p>
        </form>
      </main>
    </div>
  )
}

const lpStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)" },
  header: { padding: "18px 40px", borderBottom: "1px solid var(--line)" },
  brandLink: { display: "inline-flex", alignItems: "center", gap: 8 },

  main: {
    display: "flex",
    justifyContent: "center",
    alignItems: "flex-start",
    padding: "120px 24px 80px",
  },
  card: {
    width: "100%",
    maxWidth: 360,
    display: "flex",
    flexDirection: "column",
  },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 28,
    lineHeight: 1.2,
    fontWeight: 400,
    margin: "0 0 10px",
    letterSpacing: "-0.005em",
  },
  sub: { fontSize: 14, color: "var(--text-muted)", margin: "0 0 28px", lineHeight: 1.55 },

  inputWrap: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    transition: "border-color 200ms",
  },
  at: {
    paddingLeft: 16,
    paddingRight: 4,
    color: "var(--text-faint)",
    fontSize: 16,
    fontFamily: "var(--font-narrative)",
  },
  input: {
    flex: 1,
    height: 52,
    padding: "0 16px 0 4px",
    background: "transparent",
    border: "none",
    outline: "none",
    color: "var(--text)",
    fontSize: 16,
  },

  error: {
    marginTop: 10,
    fontSize: 12,
    color: "var(--warn)",
  },

  note: {
    marginTop: 18,
    fontSize: 12,
    color: "var(--text-faint)",
    lineHeight: 1.6,
    textAlign: "center",
  },
}
