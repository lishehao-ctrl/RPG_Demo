import { type FormEvent, useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import type { PlayControlAction, PlaySessionSnapshot, PlaySuggestedAction } from "../../api/contracts"
import { Header } from "../../shared/ui/header"
import { Button, Drawer, EmptyState, ErrorState, Tag } from "../../shared/ui/primitives"
import { StreamingText } from "../../shared/ui/streaming-text"
import { usePlaySession } from "./use-play-session"

export function PlayPage({
  sessionId,
  onBackHome,
}: {
  sessionId: string
  onBackHome: () => void
}) {
  const session = usePlaySession(sessionId)
  const [composerOpen, setComposerOpen] = useState(false)
  const [composerText, setComposerText] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerTab, setDrawerTab] = useState<"relations" | "state" | "echoes" | "transcript">("relations")
  const lastNarrationRef = useRef<string | null>(null)

  // Reset composer when a new turn lands.
  useEffect(() => {
    if (session.snapshot && session.snapshot.narration !== lastNarrationRef.current) {
      lastNarrationRef.current = session.snapshot.narration
      setComposerText("")
      setComposerOpen(false)
    }
  }, [session.snapshot])

  if (session.loading) {
    return (
      <div className="page page-play">
        <Header onHome={onBackHome} onCreate={() => undefined} showCreateButton={false} />
        <main className="play-main">
          <EmptyState title="正在接入会话..." hint="拉取场面、转录与状态。" />
        </main>
      </div>
    )
  }

  if (!session.snapshot) {
    return (
      <div className="page page-play">
        <Header onHome={onBackHome} onCreate={() => undefined} showCreateButton={false} />
        <main className="play-main">
          <ErrorState message={session.error ?? "这场会话当前不可访问。"} />
          <div className="play-error-actions">
            <Button onClick={onBackHome}>返回首页</Button>
          </div>
        </main>
      </div>
    )
  }

  const snapshot = session.snapshot
  const storyActions = (snapshot.story_actions?.length ? snapshot.story_actions : snapshot.suggested_actions) ?? []
  const controlActions = snapshot.control_actions ?? []
  const ended = snapshot.status === "completed" || Boolean(snapshot.ending)

  const handleStoryAction = (action: PlaySuggestedAction) => {
    if (session.submitting) return
    void session.submitTurn({ inputText: action.prompt, storyAction: action })
  }

  const handleControlAction = (action: PlayControlAction) => {
    if (session.submitting) return
    void session.submitTurn({ inputText: action.prompt, controlAction: action })
  }

  const handleComposerSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (session.submitting) return
    if (!composerText.trim()) return
    void session.submitTurn({ inputText: composerText })
  }

  return (
    <div className="page page-play">
      <Header onHome={onBackHome} onCreate={() => undefined} showCreateButton={false} />

      <main className="play-main">
        <div className="play-meta">
          <div className="play-meta__crumbs">
            <strong>{snapshot.story_title}</strong>
            <span>·</span>
            <span>{snapshot.beat_title}</span>
          </div>
          <div className="play-meta__progress">
            <span>
              {snapshot.progress?.completed_beats ?? 0}/{snapshot.progress?.total_beats ?? 0} 幕
            </span>
            <span>·</span>
            <span>第 {snapshot.turn_index} 轮</span>
            <button
              className="play-meta__drawer-toggle"
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label="查看人物与状态"
            >
              人物 · 状态
            </button>
          </div>
        </div>

        <section className="play-stage">
          <AnimatePresence mode="wait">
            <motion.div
              key={snapshot.turn_index}
              className="play-narration"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.5 }}
            >
              <StreamingText text={snapshot.narration} speedMs={18} className="play-narration__text" />
            </motion.div>
          </AnimatePresence>
        </section>

        {session.pendingPlayerText ? (
          <div className="play-player-bubble">
            <span>你刚刚</span>
            <p>{session.pendingPlayerText}</p>
          </div>
        ) : null}

        {ended ? (
          <PlayEnding
            snapshot={snapshot}
            sessionId={sessionId}
            onBackHome={onBackHome}
          />
        ) : (
          <section className="play-actions">
            <div className="play-actions__row">
              {storyActions.map((action) => (
                <button
                  key={action.suggestion_id}
                  className="action-card"
                  type="button"
                  onClick={() => handleStoryAction(action)}
                  disabled={session.submitting}
                >
                  <span className="action-card__label">下一手</span>
                  <strong>{action.label}</strong>
                  <p>{action.prompt}</p>
                </button>
              ))}
              {controlActions.map((action) => (
                <button
                  key={action.action_id}
                  className="action-card action-card--control"
                  type="button"
                  onClick={() => handleControlAction(action)}
                  disabled={session.submitting}
                >
                  <span className="action-card__label">{action.action_type}</span>
                  <strong>{action.label}</strong>
                  <p>{action.prompt}</p>
                </button>
              ))}
            </div>

            <div className="play-composer">
              {composerOpen ? (
                <form onSubmit={handleComposerSubmit} className="play-composer__form">
                  <textarea
                    autoFocus
                    rows={3}
                    placeholder="或者写下你自己的下一句..."
                    value={composerText}
                    onChange={(e) => setComposerText(e.target.value)}
                    disabled={session.submitting}
                  />
                  <div className="play-composer__row">
                    <Button type="button" variant="ghost" onClick={() => setComposerOpen(false)}>
                      收起
                    </Button>
                    <Button type="submit" variant="primary" disabled={session.submitting || !composerText.trim()}>
                      {session.submitting ? "发送中..." : "发送"}
                    </Button>
                  </div>
                </form>
              ) : (
                <button
                  type="button"
                  className="play-composer__open"
                  onClick={() => setComposerOpen(true)}
                  disabled={session.submitting}
                >
                  自由输入 ↓
                </button>
              )}
            </div>

            {session.error ? <ErrorState message={session.error} /> : null}
          </section>
        )}
      </main>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} side="right" width={420}>
        <div className="play-drawer">
          <div className="play-drawer__tabs">
            {(
              [
                { id: "relations", label: "人物" },
                { id: "state", label: "状态" },
                { id: "echoes", label: "余波" },
                { id: "transcript", label: "记录" },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                className={`play-drawer__tab ${drawerTab === tab.id ? "is-active" : ""}`}
                type="button"
                onClick={() => setDrawerTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="play-drawer__body">
            {drawerTab === "relations" ? (
              <div className="play-relations">
                {(snapshot.relationship_state?.targets ?? []).map((target) => (
                  <div key={target.character_id} className={`relation-card ${target.is_route_focus ? "is-focus" : ""}`}>
                    <div className="relation-card__head">
                      <strong>{target.name}</strong>
                      {target.is_route_focus ? <Tag tone="accent">路线焦点</Tag> : null}
                    </div>
                    <div className="relation-card__bars">
                      <RelBar label="亲密" value={target.affection} />
                      <RelBar label="信任" value={target.trust} />
                      <RelBar label="拉扯" value={target.tension} />
                      <RelBar label="怀疑" value={target.suspicion} />
                    </div>
                  </div>
                ))}
                {(snapshot.relationship_state?.targets ?? []).length === 0 ? (
                  <EmptyState title="还没有人出场" />
                ) : null}
              </div>
            ) : null}

            {drawerTab === "state" ? (
              <div className="play-state">
                {snapshot.state_bars.map((bar) => (
                  <div key={bar.bar_id} className="state-bar">
                    <div className="state-bar__head">
                      <span>{bar.label}</span>
                      <strong>{bar.current_value}</strong>
                    </div>
                    <div className="state-bar__track">
                      <div
                        className="state-bar__fill"
                        style={{
                          width: `${normalizePercent(bar.current_value, bar.min_value, bar.max_value)}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
                {snapshot.state_bars.length === 0 ? <EmptyState title="目前没有需要关注的状态" /> : null}
              </div>
            ) : null}

            {drawerTab === "echoes" ? (
              <div className="play-echoes">
                {(snapshot.feedback?.last_turn_consequences ?? []).map((c, i) => (
                  <div key={`c-${i}`} className="echo-item echo-item--past">
                    <span>上一手</span>
                    <strong>{c}</strong>
                  </div>
                ))}
                {snapshot.latent_radar.map((item) => (
                  <div key={item.kind} className="echo-item">
                    <span>{item.kind}</span>
                    <strong>{item.note}</strong>
                    <div className="echo-item__pressure">
                      <div className="echo-item__pressure-fill" style={{ width: `${Math.min(100, item.pressure)}%` }} />
                    </div>
                  </div>
                ))}
                {(snapshot.feedback?.last_turn_consequences ?? []).length === 0 && snapshot.latent_radar.length === 0 ? (
                  <EmptyState title="还没有余波" />
                ) : null}
              </div>
            ) : null}

            {drawerTab === "transcript" ? (
              <div className="play-transcript">
                {session.transcript.map((entry) => (
                  <article key={entry.id} className={`transcript-entry transcript-entry--${entry.speaker}`}>
                    <span>{entry.speaker === "player" ? "你" : "故事"}</span>
                    <p>{entry.text}</p>
                  </article>
                ))}
                {session.transcript.length === 0 ? <EmptyState title="还没有对话记录" /> : null}
              </div>
            ) : null}
          </div>
        </div>
      </Drawer>
    </div>
  )
}

function PlayEnding({
  snapshot,
  sessionId,
  onBackHome,
}: {
  snapshot: PlaySessionSnapshot
  sessionId: string
  onBackHome: () => void
}) {
  const [shareCopied, setShareCopied] = useState(false)

  const handleShare = async () => {
    const url = `${window.location.origin}${window.location.pathname}#/play/${sessionId}/replay`
    try {
      await navigator.clipboard.writeText(url)
      setShareCopied(true)
      window.setTimeout(() => setShareCopied(false), 1800)
    } catch {
      window.prompt("复制这个链接发给朋友：", url)
    }
  }

  const handlePlayAgain = () => {
    window.location.hash = `#/world/${snapshot.story_id}`
  }

  const handleNewWorld = () => {
    window.location.hash = "#/create"
  }

  return (
    <section className="play-ending">
      <Tag tone="accent">{snapshot.ending?.label ?? "结局"}</Tag>
      <h2>故事到这里了。</h2>
      {snapshot.ending?.summary ? <p>{snapshot.ending.summary}</p> : null}
      <div className="play-ending__actions">
        <Button variant="primary" onClick={() => void handleShare()}>
          {shareCopied ? "链接已复制 ✓" : "分享我的结局"}
        </Button>
        <Button variant="secondary" onClick={handlePlayAgain}>
          再玩一次
        </Button>
        <Button variant="secondary" onClick={handleNewWorld}>
          写我自己的 world
        </Button>
        <Button variant="ghost" onClick={onBackHome}>
          回首页
        </Button>
      </div>
    </section>
  )
}

function RelBar({ label, value }: { label: string; value: number }) {
  // Display range loosely [-3, 6] for affection/trust; tension/suspicion 0-6.
  const percent = normalizePercent(value, -3, 6)
  return (
    <div className="rel-bar">
      <span>{label}</span>
      <div className="rel-bar__track">
        <div className="rel-bar__fill" style={{ width: `${percent}%` }} />
      </div>
      <em>{value}</em>
    </div>
  )
}

function normalizePercent(value: number, min: number, max: number): number {
  if (max <= min) return 50
  return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))
}
