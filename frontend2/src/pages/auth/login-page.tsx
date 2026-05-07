import { type CSSProperties, type FormEvent, useEffect, useState } from "react"
import { AnimatePresence, motion, useAnimationControls } from "motion/react"
import { useAuth } from "../../app/auth-context"
import { friendlyError } from "../../shared/lib/friendly-error"
import { useT } from "../../shared/lib/i18n"
import { itemTransition } from "../../shared/lib/motion-presets"

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
  const t = useT()
  const [name, setName] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Shake the input row when an error fires, so the user's eye is
  // drawn to the field that needs fixing without us blocking with a
  // modal. Triggered each time `error` becomes truthy — even if the
  // string is identical to the previous one (so spamming the bad
  // submit re-shakes).
  const inputControls = useAnimationControls()
  useEffect(() => {
    if (!error) return
    void inputControls.start({
      x: [0, -7, 6, -4, 3, -1, 0],
      transition: { duration: 0.42 },
    })
  }, [error, inputControls])

  const submit = async (e?: FormEvent<HTMLFormElement>) => {
    e?.preventDefault?.()
    if (submitting) return
    const trimmed = name.trim()
    if (!USERNAME_PATTERN.test(trimmed)) {
      setError(t("login.error_username_format"))
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await auth.login(trimmed)
      onLoggedIn(next)
    } catch (err) {
      setError(friendlyError(err, t("login.error_generic")))
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
        <motion.form
          style={lpStyles.card}
          onSubmit={submit}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={itemTransition}
        >
          <span className="ts-tag" style={{ marginBottom: 24 }}>
            {t("login.tag")}
          </span>
          <h1 style={lpStyles.title}>{t("login.title")}</h1>
          <p style={lpStyles.sub}>{t("login.sub")}</p>

          <motion.div style={lpStyles.inputWrap} animate={inputControls}>
            <span style={lpStyles.at}>@</span>
            <input
              style={lpStyles.input}
              placeholder={t("login.placeholder")}
              value={name}
              onChange={(e) => {
                if (error) setError(null) // clear on retype
                setName(e.target.value.replace(/^@+/, ""))
              }}
              autoFocus
              spellCheck={false}
              autoComplete="off"
              disabled={submitting}
            />
          </motion.div>

          <AnimatePresence>
            {error ? (
              <motion.div
                key="login-error"
                style={lpStyles.error}
                initial={{ opacity: 0, height: 0, marginTop: 0 }}
                animate={{ opacity: 1, height: "auto", marginTop: 10 }}
                exit={{ opacity: 0, height: 0, marginTop: 0 }}
                transition={itemTransition}
              >
                {error}
              </motion.div>
            ) : null}
          </AnimatePresence>

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
            {submitting ? t("login.submit_busy") : t("login.submit_idle")}
          </button>

          <p style={lpStyles.note}>{t("login.note")}</p>
        </motion.form>
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
    fontSize: 12,
    color: "var(--warn)",
    overflow: "hidden",
  },

  note: {
    marginTop: 18,
    fontSize: 12,
    color: "var(--text-faint)",
    lineHeight: 1.6,
    textAlign: "center",
  },
}
