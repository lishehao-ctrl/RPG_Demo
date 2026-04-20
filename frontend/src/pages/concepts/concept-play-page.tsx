import { useState, type CSSProperties } from "react"
import { motion } from "motion/react"
import { STORYLINE_ASSETS } from "../../shared/lib/storyline-assets"
import { CONCEPT_REVIEW_WORLD } from "../../shared/lib/concept-review-fixtures"
import type { ConceptVariant } from "../../shared/lib/concept-review-types"
import {
  ConceptCastRail,
  ConceptChoiceCards,
  ConceptConsequenceCards,
  ConceptPanel,
  ConceptRelationshipGraph,
  ConceptStateMeter,
  ConceptVariantSwitcher,
} from "../../shared/ui/concept-review-primitives"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

const PLAY_VARIANT_COPY: Record<
  ConceptVariant,
  {
    rail: string
    eyebrow: string
    title: string
    subtitle: string
    authorButton: string
    sceneTitle: string
    relationTitle: string
    consequenceTitle: string
    choiceTitle: string
    inputTitle: string
    feedbackTitle: string
    barsTitle: string
  }
> = {
  casefile: {
    rail: "Concept Review",
    eyebrow: "案卷现场",
    title: "Play 应该像在一间快要失控的房间里做决定，而不是操作状态机。",
    subtitle: "这一版把场面、关系图、余波和证据板拼成同一张桌面，让人觉得自己真的身处签字夜之前。",
    authorButton: "切回案卷起草台",
    sceneTitle: "当前场面",
    relationTitle: "证据板与关系图",
    consequenceTitle: "余波账本",
    choiceTitle: "下一手走法",
    inputTitle: "下一句试探",
    feedbackTitle: "刚刚发生了什么",
    barsTitle: "补充状态条",
  },
  series: {
    rail: "Series Concept",
    eyebrow: "本集场面",
    title: "Play 应该像追一集互动剧，主镜头永远先给人物和下一手。",
    subtitle: "这一版把 scene、角色关系、本集余波和下一手 choice 做成更像剧集 UI 的阅读顺序。",
    authorButton: "切回剧集路线起稿",
    sceneTitle: "本集主场面",
    relationTitle: "人物关系",
    consequenceTitle: "本集余波",
    choiceTitle: "下一手",
    inputTitle: "本集下一句",
    feedbackTitle: "上一手反馈",
    barsTitle: "补充信号",
  },
}

function formatHistorySpeaker(speaker: "gm" | "player") {
  return speaker === "gm" ? "场面旁白" : "你的动作"
}

export function ConceptPlayPage({
  variant,
  onSelectVariant,
  onOpenAuthorConcept,
}: {
  variant: ConceptVariant
  onSelectVariant: (next: ConceptVariant) => void
  onOpenAuthorConcept: (next: ConceptVariant) => void
}) {
  const copy = PLAY_VARIANT_COPY[variant]
  const motionPreset = useStorylineMotion()
  const snapshot = CONCEPT_REVIEW_WORLD.playSnapshot
  const history = CONCEPT_REVIEW_WORLD.playHistory.entries
  const heroCast = CONCEPT_REVIEW_WORLD.preview.cast_slots.slice(0, 4)
  const [selectedActionId, setSelectedActionId] = useState<string | null>(snapshot.story_actions[0]?.suggestion_id ?? null)
  const [draft, setDraft] = useState(snapshot.story_actions[0]?.prompt ?? "")
  const backdrop =
    variant === "casefile" ? STORYLINE_ASSETS.backgrounds.penthouseRainy : STORYLINE_ASSETS.backgrounds.loungeAmber

  return (
    <main className={`concept-review concept-review--play is-${variant}`}>
      <section className="concept-review__hero" style={{ "--concept-backdrop": `url("${backdrop}")` } as CSSProperties}>
        <div className="concept-review__veil" />
        <div className="concept-review__inner concept-review__inner--stack">
          <div className="concept-review__hero-shell">
            <motion.div className="concept-review__topbar" {...motionPreset.reveal({ y: 14, duration: 0.58 })}>
              <ConceptVariantSwitcher onChange={onSelectVariant} value={variant} />
              <div className="concept-review__topbar-actions">
                <span>{copy.eyebrow}</span>
                <button className="concept-review__cta" onClick={() => onOpenAuthorConcept(variant)} type="button">
                  {copy.authorButton}
                </button>
              </div>
            </motion.div>

            <motion.section className="concept-focus-card concept-focus-card--play" {...motionPreset.reveal({ delay: 0.06, y: 18, duration: 0.72 })}>
              <div className="concept-focus-card__labels">
                <span>{copy.rail}</span>
                <span>{copy.eyebrow}</span>
                <span>{snapshot.beat_title}</span>
              </div>

              <div className="concept-focus-card__headline">
                <span className="concept-focus-card__kicker">{snapshot.protagonist?.role_label ?? "关系戏主角"}</span>
                <h1>{snapshot.story_title}</h1>
                <p>{snapshot.narration}</p>
              </div>

              <div className="concept-focus-grid">
                <article className="concept-focus-card__detail">
                  <span className="concept-review__label">当前主角</span>
                  <strong>{snapshot.protagonist?.title}</strong>
                  <p>{snapshot.protagonist?.identity_summary}</p>
                </article>
                <article className="concept-focus-card__detail">
                  <span className="concept-review__label">上一手余波</span>
                  <strong>{snapshot.feedback?.last_turn_consequences[0]}</strong>
                </article>
                <article className="concept-focus-card__detail">
                  <span className="concept-review__label">风暴天气</span>
                  <strong>{snapshot.latent_radar[0]?.note}</strong>
                </article>
              </div>

              <div className="concept-focus-card__footer">
                <div className="concept-focus-cast-pills">
                  {heroCast.map((item) => (
                    <span key={item.slot_label}>{item.slot_label}</span>
                  ))}
                </div>

                <div className="concept-mini-metrics">
                  <div className="concept-mini-metrics__item">
                    <span>场面热度</span>
                    <strong>{snapshot.relationship_state?.scene_heat ?? 0}</strong>
                  </div>
                  <div className="concept-mini-metrics__item">
                    <span>秘密暴露</span>
                    <strong>{snapshot.relationship_state?.secret_exposure ?? 0}</strong>
                  </div>
                </div>
              </div>
            </motion.section>
          </div>
        </div>
      </section>

      <section className="concept-review__body">
        <div className="concept-grid concept-grid--play-refined">
          <div className="concept-play-main">
            <ConceptPanel eyebrow={copy.sceneTitle} title="当前场面" subtitle="主舞台只回答一件事: 房间里刚刚发生了什么。">
              <div className="concept-transcript">
                {history.map((entry) => (
                  <article className={`concept-transcript__entry speaker-${entry.speaker}`} key={`${entry.turn_index}-${entry.created_at}`}>
                    <span>{formatHistorySpeaker(entry.speaker)}</span>
                    <p>{entry.text}</p>
                  </article>
                ))}
              </div>
            </ConceptPanel>

            <ConceptPanel eyebrow={copy.choiceTitle} title="下一手" subtitle="把决定做成有戏的牌面，而不是一排功能按钮。">
              <ConceptChoiceCards
                controlActions={snapshot.control_actions ?? []}
                onSelect={(next) => {
                  setSelectedActionId(next.id)
                  setDraft(next.prompt)
                }}
                selectedId={selectedActionId}
                storyActions={snapshot.story_actions ?? snapshot.suggested_actions}
              />
            </ConceptPanel>

            <ConceptPanel eyebrow={copy.inputTitle} title="输入试探" subtitle="输入区只保留沉浸姿态，不执行真实 turn。">
              <div className="concept-play-input">
                <textarea onChange={(event) => setDraft(event.target.value)} rows={4} value={draft} />
                <div className="concept-play-input__footer">
                  <span>静态 concept，不触发真实 play turn。</span>
                  <button className="concept-review__cta" disabled type="button">
                    发送下一手
                  </button>
                </div>
              </div>
            </ConceptPanel>
          </div>

          <aside className="concept-play-rail">
            {snapshot.relationship_state ? (
              <ConceptPanel eyebrow={copy.relationTitle} title="人物关系" subtitle="侧栏第一块只保留会影响下一手的关系位置。">
                <ConceptRelationshipGraph protagonist={snapshot.protagonist ?? { title: "主角" }} relationshipState={snapshot.relationship_state} />
              </ConceptPanel>
            ) : null}

            <ConceptPanel eyebrow={copy.feedbackTitle} title="余波与天气" subtitle="反馈和 latent radar 放在同一判断层，帮助用户决定下一手。">
              <ConceptConsequenceCards
                consequences={snapshot.feedback?.last_turn_consequences ?? []}
                summary={[
                  { label: "场面热度", value: String(snapshot.relationship_state?.scene_heat ?? 0) },
                  { label: "公众风评", value: String(snapshot.relationship_state?.public_image ?? 0) },
                  { label: "秘密暴露", value: String(snapshot.relationship_state?.secret_exposure ?? 0) },
                  { label: "路线锁定", value: String(snapshot.relationship_state?.route_lock ?? 0) },
                ]}
              />

              <div className="concept-radar-list">
                {snapshot.latent_radar.map((item) => (
                  <article className="concept-radar-card" key={item.kind}>
                    <div>
                      <strong>{item.kind.replace(/_/g, " ")}</strong>
                      <span>{item.trend}</span>
                    </div>
                    <p>{item.note}</p>
                    <div className="concept-radar-card__track">
                      <div className="concept-radar-card__fill" style={{ width: `${item.pressure}%` }} />
                    </div>
                  </article>
                ))}
              </div>
            </ConceptPanel>

            <ConceptPanel eyebrow={copy.barsTitle} title="补充状态" subtitle="状态条退到最后，只保留对下一手真正有帮助的几个。">
              <div className="concept-state-stack">
                {snapshot.state_bars.slice(0, 4).map((bar) => (
                  <ConceptStateMeter key={bar.bar_id} label={bar.label} max={bar.max_value} min={bar.min_value} value={bar.current_value} />
                ))}
              </div>
            </ConceptPanel>
          </aside>
        </div>
      </section>
    </main>
  )
}
