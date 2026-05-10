import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import type {
  NarrativeDifficulty,
  NarrativeTemplateLanguage,
  NarrativeTemplateVisibility,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { friendlyError } from "../../shared/lib/friendly-error"
import { useLanguage, useT, type Lang, type StringKey } from "../../shared/lib/i18n"
import { itemTransition, transitions } from "../../shared/lib/motion-presets"
import { PAGE_BG } from "../../shared/lib/webtoon-assets"

const SEED_EXAMPLE_KEYS: StringKey[] = [
  "create.example_seed_1",
  "create.example_seed_2",
  "create.example_seed_3",
  "create.example_seed_4",
]

const VISIBILITY_OPTION_IDS: NarrativeTemplateVisibility[] = ["private", "unlisted", "public"]

type BudgetOptionMeta = {
  budget: number
  labelKey: StringKey
  timeKey: StringKey
  descKey: StringKey
}

const BUDGET_OPTIONS: BudgetOptionMeta[] = [
  {
    budget: 8,
    labelKey: "create.budget_short_label",
    timeKey: "create.budget_short_time",
    descKey: "create.budget_short_desc",
  },
  {
    budget: 12,
    labelKey: "create.budget_medium_label",
    timeKey: "create.budget_medium_time",
    descKey: "create.budget_medium_desc",
  },
  {
    budget: 20,
    labelKey: "create.budget_long_label",
    timeKey: "create.budget_long_time",
    descKey: "create.budget_long_desc",
  },
]

type DifficultyOptionMeta = {
  id: NarrativeDifficulty
  labelKey: StringKey
  taglineKey: StringKey
  descKey: StringKey
}

const DIFFICULTY_OPTIONS: DifficultyOptionMeta[] = [
  {
    id: "story",
    labelKey: "create.difficulty_story_label",
    taglineKey: "create.difficulty_story_tagline",
    descKey: "create.difficulty_story_desc",
  },
  {
    id: "gauntlet",
    labelKey: "create.difficulty_gauntlet_label",
    taglineKey: "create.difficulty_gauntlet_tagline",
    descKey: "create.difficulty_gauntlet_desc",
  },
]

// Story-language options — controls the locale of generated narration
// and NPC dialogue. Immutable per template once created.
const STORY_LANGUAGE_OPTIONS: Record<Lang, Array<{
  id: NarrativeTemplateLanguage
  label: string
  desc: string
}>> = {
  zh: [
    { id: "zh", label: "中文", desc: "NPC 对白和叙述都用简体中文" },
    { id: "en", label: "英文", desc: "Narration and NPC dialogue in English" },
  ],
  en: [
    { id: "zh", label: "Chinese", desc: "Narration and NPC dialogue in Simplified Chinese" },
    { id: "en", label: "English", desc: "Narration and NPC dialogue in English" },
  ],
}

const VISIBILITY_KEY_MAP: Record<
  NarrativeTemplateVisibility,
  { labelKey: StringKey; descKey: StringKey }
> = {
  private: {
    labelKey: "create.visibility_private_label",
    descKey: "create.visibility_private_desc",
  },
  unlisted: {
    labelKey: "create.visibility_unlisted_label",
    descKey: "create.visibility_unlisted_desc",
  },
  public: {
    labelKey: "create.visibility_public_label",
    descKey: "create.visibility_public_desc",
  },
}

export function CreatePage({
  onBackHome,
  onSessionStarted,
}: {
  onBackHome: () => void
  onSessionStarted: (sessionId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const { lang: uiLang } = useLanguage()
  const t = useT()
  const [seed, setSeed] = useState("")
  const [visibility, setVisibility] = useState<NarrativeTemplateVisibility>("private")
  const [turnBudget, setTurnBudget] = useState<number>(12)
  const [difficulty, setDifficulty] = useState<NarrativeDifficulty>("story")
  // Default the story language to whatever the UI is in. The user can
  // override — the field is independent of UI language once chosen
  // (you can browse in English but write a Chinese story, etc.).
  const [storyLanguage, setStoryLanguage] = useState<NarrativeTemplateLanguage>(uiLang)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Synchronous lock to prevent duplicate creates if the user manages to
  // double-click before React flushes setBusy(true). useState alone doesn't
  // guarantee that — React batches state updates, so two clicks within
  // ~16ms can both pass the `busy` check and fire two requests.
  const inflightRef = useRef(false)

  const seedExamples = useMemo(() => SEED_EXAMPLE_KEYS.map((k) => t(k)), [t])

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
      setError(t("create.error_seed_required"))
      return
    }
    if (inflightRef.current) return
    inflightRef.current = true
    setBusy(true)
    setError(null)
    try {
      const response = await api.createNarrativeTemplate({
        seed: trimmed,
        visibility,
        turn_budget: turnBudget,
        difficulty,
        language: storyLanguage,
      })
      onSessionStarted(response.session.session_id)
    } catch (err) {
      setError(friendlyError(err, t("create.error_create_failed")))
      setBusy(false)
      inflightRef.current = false
    }
    // Note: on success we deliberately leave inflightRef=true; the navigate
    // unmounts this component anyway, and locking it prevents any late
    // re-render race.
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
        <motion.div
          style={cpStyles.inner}
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={itemTransition}
        >
          <span className="ts-tag" style={{ marginBottom: 28 }}>{t("create.tag_new")}</span>
          <h1 style={cpStyles.title}>
            {t("create.heading_l1")}
            <br />
            {t("create.heading_l2")}
          </h1>
          <p style={cpStyles.sub}>
            {t("create.subhead")}
          </p>

          <div style={cpStyles.textareaWrap}>
            <textarea
              style={cpStyles.textarea}
              placeholder={t("create.placeholder")}
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              spellCheck={false}
              disabled={busy}
            />
            <div style={cpStyles.count}>{t("create.char_count", { n: seed.length })}</div>
          </div>

          <div style={cpStyles.examplesRow}>
            <span style={cpStyles.examplesLabel}>{t("create.examples_label")}</span>
            {seedExamples.map((example) => (
              <button
                key={example}
                style={cpStyles.exampleChip}
                onClick={() => setSeed(example)}
                disabled={busy}
                type="button"
                title={example}
              >
                {example.length > 26 ? example.slice(0, 24) + "…" : example}
              </button>
            ))}
          </div>

          <div style={cpStyles.fieldLabel}>{t("create.field_budget")}</div>
          <div style={cpStyles.visibility}>
            {BUDGET_OPTIONS.map((o) => (
              <button
                key={o.budget}
                style={{
                  ...cpStyles.visBtn,
                  ...(turnBudget === o.budget ? cpStyles.visBtnActive : {}),
                }}
                onClick={() => setTurnBudget(o.budget)}
                disabled={busy}
                type="button"
              >
                <div style={cpStyles.visBtnLabel}>
                  {t(o.labelKey)}
                  <span style={cpStyles.budgetTime}> · {t(o.timeKey)}</span>
                </div>
                <div style={cpStyles.visBtnDesc}>{t(o.descKey)}</div>
              </button>
            ))}
          </div>

          <div style={cpStyles.fieldLabel}>{t("create.field_difficulty")}</div>
          <div style={cpStyles.difficultyRow}>
            {DIFFICULTY_OPTIONS.map((o) => (
              <button
                key={o.id}
                style={{
                  ...cpStyles.difficultyBtn,
                  ...(difficulty === o.id ? cpStyles.difficultyBtnActive : {}),
                  ...(o.id === "gauntlet" && difficulty === o.id ? cpStyles.difficultyBtnGauntlet : {}),
                }}
                onClick={() => setDifficulty(o.id)}
                disabled={busy}
                type="button"
              >
                <div style={cpStyles.difficultyBtnLabel}>
                  {t(o.labelKey)}
                  <span style={cpStyles.difficultyBtnTagline}> · {t(o.taglineKey)}</span>
                </div>
                <div style={cpStyles.difficultyBtnDesc}>{t(o.descKey)}</div>
              </button>
            ))}
          </div>

          <div style={cpStyles.fieldLabel}>{t("create.field_story_lang")}</div>
          <div style={cpStyles.visibility}>
            {STORY_LANGUAGE_OPTIONS[uiLang].map((o) => (
              <button
                key={o.id}
                style={{
                  ...cpStyles.visBtn,
                  ...(storyLanguage === o.id ? cpStyles.visBtnActive : {}),
                }}
                onClick={() => setStoryLanguage(o.id)}
                disabled={busy}
                type="button"
              >
                <div style={cpStyles.visBtnLabel}>{o.label}</div>
                <div style={cpStyles.visBtnDesc}>{o.desc}</div>
              </button>
            ))}
          </div>

          <div style={cpStyles.fieldLabel}>{t("create.field_visibility")}</div>
          <div style={cpStyles.visibility}>
            {VISIBILITY_OPTION_IDS.map((id) => {
              const meta = VISIBILITY_KEY_MAP[id]
              return (
                <button
                  key={id}
                  style={{
                    ...cpStyles.visBtn,
                    ...(visibility === id ? cpStyles.visBtnActive : {}),
                  }}
                  onClick={() => setVisibility(id)}
                  disabled={busy}
                  type="button"
                >
                  <div style={cpStyles.visBtnLabel}>{t(meta.labelKey)}</div>
                  <div style={cpStyles.visBtnDesc}>{t(meta.descKey)}</div>
                </button>
              )
            })}
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
              {busy ? t("create.cta_busy") : t("create.cta_idle")}
            </button>
            <button className="ts-btn ts-btn--ghost ts-btn--lg" onClick={onBackHome} disabled={busy}>
              {t("create.cta_back")}
            </button>
          </div>

          <AnimatePresence>
            {busy ? (
              <motion.div
                key="busy"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={itemTransition}
                style={cpStyles.busyCard}
              >
                <div style={cpStyles.busyDots}>
                  {[0, 1, 2, 3].map((i) => (
                    <motion.span
                      key={i}
                      style={cpStyles.busyDot}
                      animate={{
                        opacity: [0.25, 1, 0.25],
                        scale: [0.85, 1.1, 0.85],
                      }}
                      transition={{
                        duration: 1.4,
                        repeat: Infinity,
                        ease: "easeInOut",
                        delay: i * 0.16,
                      }}
                    />
                  ))}
                </div>
                <BusyTip />
              </motion.div>
            ) : null}
          </AnimatePresence>
        </motion.div>
      </main>
    </div>
  )
}

// Rotating creative tips while user waits 5-10s for opening to generate.
// Reads as "the AI is doing real work, here's what" instead of static
// "loading..." which feels frozen at second 6.
const BUSY_TIP_KEYS: StringKey[] = [
  "create.busy_tip_1",
  "create.busy_tip_2",
  "create.busy_tip_3",
  "create.busy_tip_4",
  "create.busy_tip_5",
]

function BusyTip() {
  const t = useT()
  const [idx, setIdx] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setIdx((v) => (v + 1) % BUSY_TIP_KEYS.length), 2200)
    return () => clearInterval(id)
  }, [])
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={idx}
        style={busyTipStyles.tip}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={transitions.base}
      >
        {t(BUSY_TIP_KEYS[idx])}
      </motion.div>
    </AnimatePresence>
  )
}

const busyTipStyles: Record<string, CSSProperties> = {
  tip: {
    fontSize: 13,
    color: "rgba(245,210,140,0.92)",
    lineHeight: 1.7,
    fontStyle: "italic" as const,
    textAlign: "center" as const,
    fontFamily: "var(--font-narrative)",
  },
}

const cpStyles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100%",
    background: `linear-gradient(180deg, rgba(20,16,12,0.55) 0%, rgba(20,16,12,0.92) 60%, var(--bg) 100%), url(${PAGE_BG.create})`,
    backgroundSize: "cover",
    backgroundPosition: "center top",
    backgroundAttachment: "fixed",
  },
  header: {
    padding: "18px 40px",
    borderBottom: "1px solid rgba(255,255,255,0.1)",
    color: "white",
  },
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
    color: "white",
    textShadow: "0 2px 18px rgba(0,0,0,0.5)",
  },
  sub: {
    fontSize: 16,
    lineHeight: 1.55,
    color: "rgba(255,255,255,0.78)",
    margin: "0 0 40px",
  },

  textareaWrap: { position: "relative", marginBottom: 18 },
  examplesRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    marginBottom: 32,
  },
  examplesLabel: {
    fontSize: 12,
    color: "rgba(255,255,255,0.62)",
    letterSpacing: "0.04em",
    marginRight: 4,
  },
  exampleChip: {
    padding: "5px 12px",
    background: "rgba(255,255,255,0.08)",
    border: "1px solid rgba(255,255,255,0.18)",
    borderRadius: 999,
    color: "rgba(255,255,255,0.86)",
    fontSize: 12.5,
    cursor: "pointer",
    fontFamily: "var(--font-narrative)",
    backdropFilter: "blur(4px)",
  },
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
    border: "1px solid var(--accent)",
    background: "var(--accent-soft)",
  },
  visBtnLabel: { fontSize: 15, fontWeight: 600, marginBottom: 6 },
  visBtnDesc: { fontSize: 12, color: "var(--text-muted)", lineHeight: 1.4 },
  budgetTime: {
    fontSize: 12,
    color: "var(--accent)",
    fontWeight: 500,
  },

  difficultyRow: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 10,
    marginBottom: 32,
  },
  difficultyBtn: {
    textAlign: "left",
    padding: "16px 18px",
    background: "rgba(255,255,255,0.06)",
    border: "1px solid rgba(255,255,255,0.18)",
    borderRadius: "var(--radius-md)",
    color: "rgba(255,255,255,0.86)",
    transition: "all 180ms",
  },
  difficultyBtnActive: {
    border: "1px solid var(--accent)",
    background: "rgba(201,90,67,0.18)",
    color: "white",
  },
  difficultyBtnGauntlet: {
    border: "1px solid #dc6b4a",
    background: "rgba(220,80,60,0.18)",
    boxShadow: "0 0 16px rgba(220,80,60,0.3)",
  },
  difficultyBtnLabel: {
    fontSize: 15,
    fontWeight: 600,
    marginBottom: 6,
  },
  difficultyBtnTagline: {
    fontSize: 12,
    color: "var(--accent)",
    fontWeight: 500,
  },
  difficultyBtnDesc: {
    fontSize: 12,
    color: "rgba(255,255,255,0.62)",
    lineHeight: 1.45,
  },

  error: { marginBottom: 16, fontSize: 13, color: "var(--warn)" },
  actions: { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" },
  busyHint: {
    marginTop: 24,
    fontSize: 13,
    color: "var(--text-faint)",
    lineHeight: 1.5,
  },
  busyCard: {
    marginTop: 24,
    padding: "20px 24px",
    background: "linear-gradient(180deg, rgba(245,200,120,0.08), rgba(245,200,120,0.02))",
    border: "1px solid rgba(245,200,120,0.30)",
    borderRadius: "var(--radius-md)",
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    gap: 14,
    minHeight: 80,
  },
  busyDots: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  },
  busyDot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    background: "rgba(245,210,140,0.92)",
    display: "inline-block",
  },
}
