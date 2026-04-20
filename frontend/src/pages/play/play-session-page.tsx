import { useState, type FormEvent } from "react"
import { motion } from "motion/react"
import { usePlaySession } from "../../features/play/session/model/use-play-session"
import { getEditorialThemeImage } from "../../shared/lib/editorial-assets"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

type PlayTab = "story" | "relations" | "signals"

function meterWidth(value: number, min: number, max: number) {
  if (max <= min) {
    return 50
  }
  return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))
}

export function PlaySessionPage({
  sessionId,
  onOpenLibrary,
}: {
  sessionId: string
  onOpenLibrary: (storyId?: string) => void
}) {
  const playSession = usePlaySession(sessionId)
  const motionPreset = useStorylineMotion()
  const [activeTab, setActiveTab] = useState<PlayTab>("story")

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void playSession.submitTurn()
  }

  if (playSession.loading) {
    return (
      <main className="mag-page">
        <div className="mag-empty">
          <div>
            <h3>正在接入当前会话</h3>
            <p>正在获取场面、转录与关系状态。</p>
          </div>
        </div>
      </main>
    )
  }

  if (!playSession.snapshot) {
    return (
      <main className="mag-page">
        <div className="mag-error">
          <div>
            <h3>会话暂不可用</h3>
            <p>{playSession.error ?? "这场会话当前不可访问。"}</p>
          </div>
        </div>
      </main>
    )
  }

  const snapshot = playSession.snapshot
  const storyActions = snapshot.story_actions?.length ? snapshot.story_actions : snapshot.suggested_actions
  const themeImage = getEditorialThemeImage(snapshot.story_shell_id ?? snapshot.story_title, 1)

  return (
    <main className="mag-page">
      <section className="mag-play-hero">
        <div className="mag-hero__media" style={{ backgroundImage: `url("${themeImage}")` }} />
        <div className="mag-hero__veil" />
        <div className="mag-play-hero__inner">
          <motion.div className="mag-play-hero__copy" {...motionPreset.reveal({ y: 24, duration: 0.76 })}>
            <div className="mag-badge-row">
              <span className="mag-chip mag-chip--accent">{snapshot.beat_title}</span>
              <span className="mag-chip mag-chip--gold">{`${snapshot.progress?.display_percent ?? 0}% 进度`}</span>
            </div>
            <span className="mag-kicker">{snapshot.protagonist?.role_label ?? "进行中的关系会话"}</span>
            <h1 className="mag-stage-title">{snapshot.story_title}</h1>
            <p>{snapshot.narration}</p>
            <div className="mag-action-row">
              <button className="mag-button mag-button--secondary" onClick={() => onOpenLibrary(snapshot.story_id)} type="button">
                返回案卷详情
              </button>
            </div>
          </motion.div>

          <motion.aside className="mag-detail-rail" {...motionPreset.reveal({ delay: 0.12, x: 18, y: 0, duration: 0.76 })}>
            <span className="mag-overline">当前主角</span>
            <div className="mag-side-stack">
              <div className="mag-mini-stat">
                <span>身份</span>
                <strong>{snapshot.protagonist?.title ?? "未知主角"}</strong>
              </div>
              <div className="mag-mini-stat">
                <span>当前任务</span>
                <strong>{snapshot.protagonist?.mandate ?? "等待后端补全"}</strong>
              </div>
              {snapshot.ending ? (
                <div className="mag-mini-stat">
                  <span>结局状态</span>
                  <strong>{snapshot.ending.label}</strong>
                </div>
              ) : null}
            </div>
          </motion.aside>
        </div>
      </section>

      <section className="mag-play-body">
        <div className="mag-section__inner">
          <div className="mag-play-tabs">
            <button className={`mag-play-tab ${activeTab === "story" ? "is-active" : ""}`} onClick={() => setActiveTab("story")} type="button">
              当前场面
            </button>
            <button className={`mag-play-tab ${activeTab === "relations" ? "is-active" : ""}`} onClick={() => setActiveTab("relations")} type="button">
              人物关系
            </button>
            <button className={`mag-play-tab ${activeTab === "signals" ? "is-active" : ""}`} onClick={() => setActiveTab("signals")} type="button">
              余波与天气
            </button>
          </div>

          <div className="mag-play-layout">
            <div className="mag-side-stack">
              <motion.section className="mag-panel" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
                <span className="mag-panel__eyebrow">场面正文</span>
                <h2 className="mag-panel__title">当前场面</h2>
                <div className="mag-transcript">
                  {playSession.transcript.map((entry) => (
                    <article className={`mag-transcript__entry ${entry.speaker === "player" ? "is-player" : ""}`} key={entry.id}>
                      <span>{entry.speaker === "player" ? "你的动作" : "场面旁白"}</span>
                      <p>{entry.text}</p>
                    </article>
                  ))}
                  {playSession.pendingTurnInput ? (
                    <article className="mag-transcript__entry is-player">
                      <span>正在提交</span>
                      <p>{playSession.pendingTurnInput}</p>
                    </article>
                  ) : null}
                </div>
              </motion.section>

              <motion.section className="mag-panel" {...motionPreset.inView({ delay: 0.08, y: 20, duration: 0.58 })}>
                <span className="mag-panel__eyebrow">下一手</span>
                <h2 className="mag-panel__title">把选择做成真正的牌面</h2>
                <div className="mag-choice-grid">
                  {storyActions.map((action) => (
                    <button
                      className={`mag-choice-card ${playSession.selectedSuggestionId === action.suggestion_id ? "is-selected" : ""}`}
                      key={action.suggestion_id}
                      onClick={() => playSession.selectSuggestedAction(action)}
                      type="button"
                    >
                      <span className="mag-label">剧情走法</span>
                      <strong>{action.label}</strong>
                      <p>{action.prompt}</p>
                    </button>
                  ))}

                  {(snapshot.control_actions ?? []).map((action) => (
                    <button
                      className={`mag-choice-card is-control ${playSession.selectedControlActionId === action.action_id ? "is-selected" : ""}`}
                      key={action.action_id}
                      onClick={() => playSession.selectControlAction(action)}
                      type="button"
                    >
                      <span className="mag-label">{action.action_type}</span>
                      <strong>{action.label}</strong>
                      <p>{action.prompt}</p>
                    </button>
                  ))}
                </div>
              </motion.section>

              <motion.section className="mag-panel" {...motionPreset.inView({ delay: 0.14, y: 20, duration: 0.58 })}>
                <span className="mag-panel__eyebrow">输入试探</span>
                <h2 className="mag-panel__title">用一句话推进这一轮</h2>
                <form className="mag-compose" onSubmit={handleSubmit}>
                  <div className="mag-form-field">
                    <label htmlFor="play-input">你的下一句</label>
                    <textarea
                      id="play-input"
                      onChange={(event) => playSession.setInputText(event.target.value)}
                      placeholder="写下你的试探、站队、安抚或引爆。"
                      value={playSession.inputText}
                    />
                  </div>
                  {playSession.error ? <p className="editorial-error">{playSession.error}</p> : null}
                  <div className="mag-compose__footer">
                    <span className="mag-label">后端 turn contract 未改，只更换前台输入壳。</span>
                    <button className="mag-button mag-button--primary" disabled={playSession.submitting} type="submit">
                      {playSession.submitting ? "发送中..." : "发送下一手"}
                    </button>
                  </div>
                </form>
              </motion.section>
            </div>

            <aside className="mag-side-stack">
              {activeTab === "story" ? (
                <motion.section className="mag-side-card" {...motionPreset.inView({ delay: 0.1, x: 18, y: 0, duration: 0.58 })}>
                  <div className="mag-section__header">
                    <span className="mag-panel__eyebrow">场面元信息</span>
                    <h2>这一轮最重要的几件事</h2>
                  </div>
                  <div className="mag-side-stack">
                    <div className="mag-mini-stat">
                      <span>当前 beat</span>
                      <strong>{snapshot.beat_title}</strong>
                    </div>
                    <div className="mag-mini-stat">
                      <span>进度</span>
                      <strong>{`${snapshot.progress?.completed_beats ?? 0}/${snapshot.progress?.total_beats ?? 0} 幕`}</strong>
                    </div>
                    <div className="mag-mini-stat">
                      <span>回合</span>
                      <strong>{`${snapshot.turn_index}/${snapshot.progress?.max_turns ?? snapshot.turn_index}`}</strong>
                    </div>
                  </div>
                </motion.section>
              ) : null}

              {activeTab === "relations" ? (
                <motion.section className="mag-side-card" {...motionPreset.inView({ delay: 0.1, x: 18, y: 0, duration: 0.58 })}>
                  <div className="mag-section__header">
                    <span className="mag-panel__eyebrow">人物关系</span>
                    <h2>这一手会影响谁</h2>
                  </div>
                  <div className="mag-relation-grid">
                    {(snapshot.relationship_state?.targets ?? []).map((target) => (
                      <article className="mag-relation-card" key={target.character_id}>
                        <span className="mag-label">{target.is_route_focus ? "路线焦点" : "关系节点"}</span>
                        <strong>{target.name}</strong>
                        <p>{`亲密 ${target.affection} / 信任 ${target.trust} / 拉扯 ${target.tension} / 怀疑 ${target.suspicion}`}</p>
                      </article>
                    ))}
                  </div>
                </motion.section>
              ) : null}

              {activeTab === "signals" ? (
                <motion.section className="mag-side-card" {...motionPreset.inView({ delay: 0.1, x: 18, y: 0, duration: 0.58 })}>
                  <div className="mag-section__header">
                    <span className="mag-panel__eyebrow">余波与天气</span>
                    <h2>后果已经如何回流</h2>
                  </div>

                  <div className="mag-side-stack">
                    {(snapshot.feedback?.last_turn_consequences ?? []).map((item) => (
                      <article className="mag-radar-item" key={item}>
                        <strong>{item}</strong>
                      </article>
                    ))}
                  </div>

                  <div className="mag-radar-list">
                    {snapshot.latent_radar.map((item) => (
                      <article className="mag-radar-item" key={item.kind}>
                        <span className="mag-label">{item.kind}</span>
                        <strong>{item.note}</strong>
                        <div className="mag-state-meter__track">
                          <div className="mag-state-meter__fill" style={{ width: `${item.pressure}%` }} />
                        </div>
                      </article>
                    ))}
                  </div>
                </motion.section>
              ) : null}

              <motion.section className="mag-side-card" {...motionPreset.inView({ delay: 0.16, x: 18, y: 0, duration: 0.58 })}>
                <div className="mag-section__header">
                  <span className="mag-panel__eyebrow">状态条</span>
                  <h2>补充判断信息</h2>
                </div>
                <div className="mag-state-list">
                  {snapshot.state_bars.map((bar) => (
                    <article className="mag-state-meter" key={bar.bar_id}>
                      <div className="mag-state-meter__head">
                        <strong>{bar.label}</strong>
                        <span>{bar.current_value}</span>
                      </div>
                      <div className="mag-state-meter__track">
                        <div className="mag-state-meter__fill" style={{ width: `${meterWidth(bar.current_value, bar.min_value, bar.max_value)}%` }} />
                      </div>
                    </article>
                  ))}
                </div>
              </motion.section>
            </aside>
          </div>
        </div>
      </section>
    </main>
  )
}
