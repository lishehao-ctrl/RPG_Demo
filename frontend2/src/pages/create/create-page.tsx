import { type CSSProperties, useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import type { NarrativeDifficulty, NarrativeTemplateVisibility } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { friendlyError } from "../../shared/lib/friendly-error"
import { itemTransition } from "../../shared/lib/motion-presets"
import { PAGE_BG } from "../../shared/lib/webtoon-assets"

const PLACEHOLDER = `写一句故事的开端，越具体越好。

比如：年会前夜，老板把我和实习生关在同一间会议室。
或者：婚礼当天，伴娘的礼服里塞着一封我妹妹的字条。

AI 会立刻为你搭起人物、关系、第一个戏剧时刻。`

const SEED_EXAMPLES = [
  "公司年会的红毯上，前任的现任搂着前任向我走来。",
  "分手那天晚上，他给我妹妹打了一通电话。",
  "我前任在我新公司当 HR，今天发了我的入职合同。",
  "高中重逢，发现初恋已经成了我妹妹的男朋友。",
]

const VISIBILITY_OPTIONS: Array<{
  id: NarrativeTemplateVisibility
  label: string
  desc: string
}> = [
  { id: "private", label: "只有我", desc: "只有你能玩这个故事" },
  { id: "unlisted", label: "凭链接", desc: "把链接发给朋友，他们能玩出自己的剧情" },
  { id: "public", label: "广场公开", desc: "任何人都能看到、玩你的故事" },
]

const BUDGET_OPTIONS: Array<{
  budget: number
  label: string
  time: string
  desc: string
}> = [
  { budget: 8, label: "短", time: "10 分钟", desc: "一个戏剧瞬间，节奏紧凑" },
  { budget: 12, label: "中", time: "15 分钟", desc: "一集短剧，起承转合完整" },
  { budget: 20, label: "长", time: "25 分钟", desc: "多线索铺陈，情绪深入" },
]

const DIFFICULTY_OPTIONS: Array<{
  id: NarrativeDifficulty
  label: string
  tagline: string
  desc: string
}> = [
  {
    id: "story",
    label: "故事模式",
    tagline: "适合放松看戏",
    desc: "你不会真正失败，故事一定会走到一个完整结局。",
  },
  {
    id: "gauntlet",
    label: "博弈模式",
    tagline: "NPC 主动跟你斗",
    desc: "NPC 各有目标和把柄。你可能在第 5 回合就翻车——结局也分胜利、妥协、崩盘三档。",
  },
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
  const [turnBudget, setTurnBudget] = useState<number>(12)
  const [difficulty, setDifficulty] = useState<NarrativeDifficulty>("story")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Synchronous lock to prevent duplicate creates if the user manages to
  // double-click before React flushes setBusy(true). useState alone doesn't
  // guarantee that — React batches state updates, so two clicks within
  // ~16ms can both pass the `busy` check and fire two requests.
  const inflightRef = useRef(false)

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
      })
      onSessionStarted(response.session.session_id)
    } catch (err) {
      setError(friendlyError(err, "无法创建故事，请稍后再试。"))
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

          <div style={cpStyles.examplesRow}>
            <span style={cpStyles.examplesLabel}>试试这些：</span>
            {SEED_EXAMPLES.map((example) => (
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

          <div style={cpStyles.fieldLabel}>篇幅</div>
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
                  {o.label}
                  <span style={cpStyles.budgetTime}> · {o.time}</span>
                </div>
                <div style={cpStyles.visBtnDesc}>{o.desc}</div>
              </button>
            ))}
          </div>

          <div style={cpStyles.fieldLabel}>难度</div>
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
                  {o.label}
                  <span style={cpStyles.difficultyBtnTagline}> · {o.tagline}</span>
                </div>
                <div style={cpStyles.difficultyBtnDesc}>{o.desc}</div>
              </button>
            ))}
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
const BUSY_TIPS: string[] = [
  "在为你的种子挑选 3-5 个角色，每人都有秘密…",
  "在搭建 NPC 之间相互捏着的把柄网络…",
  "在为你准备 3 张玩家身份卡——每张走向不同的故事…",
  "在写下开场的第一个戏剧瞬间…",
  "在校对人物动机和关系合理性…",
]

function BusyTip() {
  const [idx, setIdx] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setIdx((v) => (v + 1) % BUSY_TIPS.length), 2200)
    return () => clearInterval(t)
  }, [])
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={idx}
        style={busyTipStyles.tip}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
      >
        {BUSY_TIPS[idx]}
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
    borderColor: "var(--accent)",
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
    borderColor: "var(--accent)",
    background: "rgba(201,90,67,0.18)",
    color: "white",
  },
  difficultyBtnGauntlet: {
    borderColor: "#dc6b4a",
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
