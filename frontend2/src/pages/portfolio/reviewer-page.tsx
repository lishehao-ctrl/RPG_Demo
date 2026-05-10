import { useRef, useState } from "react"
import { motion } from "motion/react"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { friendlyError } from "../../shared/lib/friendly-error"
import { useLanguage } from "../../shared/lib/i18n"
import {
  REVIEWER_DEMO_ACTIONS,
  REVIEWER_DEMO_SEED,
  REVIEWER_DEMO_TITLE,
} from "./portfolio-data"

export function ReviewerPage({
  onBackHome,
  onOpenCreate,
  onSessionStarted,
}: {
  onBackHome: () => void
  onOpenCreate: () => void
  onSessionStarted: (sessionId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const { setLang } = useLanguage()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inflightRef = useRef(false)

  const handleStart = async () => {
    if (inflightRef.current || auth.loading) return
    inflightRef.current = true
    setBusy(true)
    setError(null)
    setLang("en")
    try {
      if (auth.isAnonymous) {
        await auth.login("portfolio_reviewer")
      }
      const response = await api.createNarrativeTemplate({
        seed: REVIEWER_DEMO_SEED,
        visibility: "unlisted",
        turn_budget: 12,
        difficulty: "story",
        language: "en",
      })
      onSessionStarted(response.session.session_id)
    } catch (err) {
      setError(friendlyError(err, "Could not launch the reviewer demo."))
      inflightRef.current = false
      setBusy(false)
    }
  }

  return (
    <div className="reviewer-page">
      <Header onHome={onBackHome} onCreate={onOpenCreate} />
      <main className="reviewer-main">
        <motion.section
          className="reviewer-hero"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.32, ease: "easeOut" }}
        >
          <span className="ts-tag">Reviewer Mode</span>
          <h1>{REVIEWER_DEMO_TITLE}</h1>
          <p>
            A locked English demo path designed for portfolio review. It starts
            a real session, keeps the Korean-webtoon visual language, and opens
            the play surface with a live runtime inspector.
          </p>
          <blockquote>"{REVIEWER_DEMO_SEED}"</blockquote>
          <div className="reviewer-actions">
            <button
              className="ts-btn ts-btn--primary ts-btn--lg"
              type="button"
              onClick={() => void handleStart()}
              disabled={busy || auth.loading}
            >
              {busy ? "Launching demo..." : "Start curated run"}
            </button>
            <button className="ts-btn ts-btn--ghost ts-btn--lg" type="button" onClick={onOpenCreate} disabled={busy}>
              Use normal author flow
            </button>
          </div>
          {error ? <div className="reviewer-error">{error}</div> : null}
        </motion.section>

        <section className="reviewer-checklist" aria-label="Reviewer path">
          {REVIEWER_DEMO_ACTIONS.map((item, idx) => (
            <article key={item}>
              <span>{String(idx + 1).padStart(2, "0")}</span>
              <p>{item}</p>
            </article>
          ))}
        </section>
      </main>
    </div>
  )
}
