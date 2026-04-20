import type { CSSProperties } from "react"
import { motion } from "motion/react"
import { STORYLINE_ASSETS } from "../../shared/lib/storyline-assets"
import { CONCEPT_REVIEW_WORLD } from "../../shared/lib/concept-review-fixtures"
import type { AuthorConceptStage, ConceptVariant } from "../../shared/lib/concept-review-types"
import {
  ConceptBeatLadder,
  ConceptCastRail,
  ConceptPanel,
  ConceptStageSwitcher,
  ConceptVariantSwitcher,
} from "../../shared/ui/concept-review-primitives"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

const AUTHOR_VARIANT_COPY: Record<
  ConceptVariant,
  {
    label: string
    railLabel: string
    eyebrow: string
    title: string
    subtitle: string
    authorTag: string
    playButton: string
    stageLabels: Record<AuthorConceptStage, { eyebrow: string; title: string; subtitle: string }>
    cardsTitle: string
    signalsTitle: string
    beatsTitle: string
    castTitle: string
    publishTitle: string
    publishCopy: string
  }
> = {
  casefile: {
    label: "案卷剧场",
    railLabel: "Concept Review",
    eyebrow: "机密提要",
    title: "先把关系、秘密和站队压力写进同一份危险案卷。",
    subtitle: "这一版保留案卷感，但不再像后台系统。它应该像一份精致、危险、可游玩的关系案卷。",
    authorTag: "编剧室预演",
    playButton: "查看配套案卷现场",
    stageLabels: {
      create: {
        eyebrow: "起草台",
        title: "让第一屏先卖掉这场危险关系",
        subtitle: "这里展示 seed、路线幻想、关系钩子和角色落位，不展示后台术语。",
      },
      loading: {
        eyebrow: "编译台",
        title: "把编写过程做成桌面上逐渐成形的案卷",
        subtitle: "这里强调加载卡、场面编排和终局压力，让“编译”像一场有质感的收束。",
      },
    },
    cardsTitle: "机密卡片",
    signalsTitle: "表层信号",
    beatsTitle: "关键场面编排",
    castTitle: "被写进案卷的人",
    publishTitle: "发布前最后一眼",
    publishCopy: "按钮保留静态 review 形态，不触发真实 author 流程。",
  },
  series: {
    label: "剧集路线",
    railLabel: "Series Concept",
    eyebrow: "新剧开发",
    title: "先把人物拉进同一场夜色，再决定谁会先失控。",
    subtitle: "这一版弱化案卷口吻，更像在开发一部可追更的互动剧，强调路线、人物和场面感。",
    authorTag: "剧情导演预演",
    playButton: "查看配套本集场面",
    stageLabels: {
      create: {
        eyebrow: "路线起稿",
        title: "让用户先闻到人物关系会怎么失控",
        subtitle: "这里把 seed 变成 route promise、人物张力和场面预告，而不是工作台配置。",
      },
      loading: {
        eyebrow: "片段收口",
        title: "把生成过程包装成一集剧正在被剪出来",
        subtitle: "这里强调场面卡、角色落位和终局悬念，让编写像在收片而不是跑流水线。",
      },
    },
    cardsTitle: "场面卡",
    signalsTitle: "本集气味",
    beatsTitle: "本集大场面",
    castTitle: "本集主要人物",
    publishTitle: "上线前最后确认",
    publishCopy: "静态概念稿只展示上线姿态，不触发真实生成或发布。",
  },
}

export function ConceptAuthorPage({
  variant,
  stage,
  onSelectVariant,
  onSelectStage,
  onOpenPlayConcept,
}: {
  variant: ConceptVariant
  stage: AuthorConceptStage
  onSelectVariant: (next: ConceptVariant) => void
  onSelectStage: (next: AuthorConceptStage) => void
  onOpenPlayConcept: (next: ConceptVariant) => void
}) {
  const copy = AUTHOR_VARIANT_COPY[variant]
  const motionPreset = useStorylineMotion()
  const preview = CONCEPT_REVIEW_WORLD.preview
  const loadingSnapshot = CONCEPT_REVIEW_WORLD.loadingSnapshot
  const loadingCards = CONCEPT_REVIEW_WORLD.loadingCards
  const stageCopy = copy.stageLabels[stage]
  const heroCast = preview.cast_slots.slice(0, 4)
  const heroFlashcards = preview.flashcards.slice(0, 3)
  const loadingHighlights = loadingCards.slice(0, 8)
  const backdrop =
    variant === "casefile" ? STORYLINE_ASSETS.backgrounds.boardroomObsidian : STORYLINE_ASSETS.backgrounds.loungeObsidian

  return (
    <main className={`concept-review concept-review--author is-${variant}`}>
      <section className="concept-review__hero" style={{ "--concept-backdrop": `url("${backdrop}")` } as CSSProperties}>
        <div className="concept-review__veil" />
        <div className="concept-review__inner concept-review__inner--stack">
          <div className="concept-review__hero-shell">
            <motion.div className="concept-review__topbar" {...motionPreset.reveal({ y: 14, duration: 0.58 })}>
              <ConceptVariantSwitcher onChange={onSelectVariant} value={variant} />
              <ConceptStageSwitcher onChange={onSelectStage} value={stage} />
            </motion.div>

            {stage === "create" ? (
              <motion.section className="concept-focus-card" {...motionPreset.reveal({ delay: 0.06, y: 18, duration: 0.72 })}>
                <div className="concept-focus-card__labels">
                  <span>{copy.railLabel}</span>
                  <span>{copy.eyebrow}</span>
                  <span>{stageCopy.eyebrow}</span>
                </div>

                <div className="concept-focus-card__headline">
                  <span className="concept-focus-card__kicker">{copy.authorTag}</span>
                  <h1>{preview.story.title}</h1>
                  <p>{preview.story.premise}</p>
                </div>

                <div className="concept-focus-grid">
                  <article className="concept-focus-card__detail">
                    <span className="concept-review__label">路线承诺</span>
                    <strong>{preview.story.route_fantasy}</strong>
                  </article>
                  <article className="concept-focus-card__detail">
                    <span className="concept-review__label">关系钩子</span>
                    <strong>{preview.relationship_hook}</strong>
                  </article>
                  <article className="concept-focus-card__detail">
                    <span className="concept-review__label">秘密引线</span>
                    <strong>{preview.secret_hook}</strong>
                  </article>
                </div>

                <div className="concept-support-strip">
                  {heroFlashcards.map((card) => (
                    <article className="concept-support-strip__item" key={card.card_id}>
                      <span>{card.label}</span>
                      <strong>{card.value}</strong>
                    </article>
                  ))}
                </div>

                <div className="concept-focus-card__footer">
                  <div className="concept-focus-cast-pills">
                    {heroCast.map((item) => (
                      <span key={item.slot_label}>{item.slot_label}</span>
                    ))}
                  </div>

                  <button className="concept-review__cta" onClick={() => onOpenPlayConcept(variant)} type="button">
                    {copy.playButton}
                  </button>
                </div>
              </motion.section>
            ) : (
              <motion.section className="concept-focus-card concept-focus-card--loading" {...motionPreset.reveal({ delay: 0.06, y: 18, duration: 0.72 })}>
                <div className="concept-focus-card__labels">
                  <span>{copy.railLabel}</span>
                  <span>{copy.publishTitle}</span>
                  <span>{loadingSnapshot.stage_label}</span>
                </div>

                <div className="concept-focus-card__headline">
                  <span className="concept-focus-card__kicker">{copy.authorTag}</span>
                  <h1>{preview.story.title}</h1>
                  <p>{loadingSnapshot.preview_premise}</p>
                </div>

                <div className="concept-focus-grid">
                  <article className="concept-focus-card__detail">
                    <span className="concept-review__label">编译进度</span>
                    <strong>{Math.round(loadingSnapshot.completion_ratio * 100)}%</strong>
                  </article>
                  <article className="concept-focus-card__detail">
                    <span className="concept-review__label">当前阶段</span>
                    <strong>{loadingSnapshot.stage_label}</strong>
                  </article>
                  <article className="concept-focus-card__detail">
                    <span className="concept-review__label">终局压力</span>
                    <strong>{preview.story.stakes}</strong>
                  </article>
                </div>

                <div className="concept-focus-card__footer">
                  <div className="concept-focus-cast-pills">
                    {heroCast.map((item) => (
                      <span key={item.slot_label}>{item.slot_label}</span>
                    ))}
                  </div>

                  <button className="concept-review__cta" onClick={() => onOpenPlayConcept(variant)} type="button">
                    {copy.playButton}
                  </button>
                </div>
              </motion.section>
            )}
          </div>
        </div>
      </section>

      <section className="concept-review__body">
        {stage === "create" ? (
          <>
            <div className="concept-grid concept-grid--author-refined">
              <ConceptPanel eyebrow={copy.castTitle} title="人物焦点" subtitle="人物先于配置出现，先回答这是谁的局、谁最会逼你失控。">
                <ConceptCastRail items={preview.cast_slots} title={copy.castTitle} />
              </ConceptPanel>

              <ConceptPanel eyebrow={copy.beatsTitle} title="关键场面" subtitle="场面只保留一条清晰升级线，不把用户带进工作台语境。">
                <ConceptBeatLadder activeIndex={1} beats={preview.beats} />
              </ConceptPanel>
            </div>

            <ConceptPanel eyebrow={copy.signalsTitle} title="支持信息下沉" subtitle="故事种子、表层信号和辅助卡片都降到第二阅读层，只负责补充，不争抢第一眼。">
              <div className="concept-grid concept-grid--author-support-refined">
                <label className="concept-review__field">
                  <span>故事种子</span>
                  <textarea readOnly rows={5} value={CONCEPT_REVIEW_WORLD.seed} />
                </label>

                <div className="concept-support-strip">
                  <article className="concept-support-strip__item">
                    <span>场域气味</span>
                    <strong>{preview.surface_signal_summary}</strong>
                  </article>
                  <article className="concept-support-strip__item">
                    <span>推进场域</span>
                    <strong>{preview.target_visibility_summary}</strong>
                  </article>
                  <article className="concept-support-strip__item">
                    <span>戏剧代价</span>
                    <strong>{preview.story.stakes}</strong>
                  </article>
                </div>

                <div className="concept-chip-row">
                  {preview.surface_signal_ids.map((signal) => (
                    <span className="concept-chip" key={signal}>
                      {signal.replace(/_/g, " ")}
                    </span>
                  ))}
                  {preview.flashcards.slice(0, 3).map((card) => (
                    <span className={`concept-chip ${card.kind === "draft" ? "is-draft" : ""}`} key={card.card_id}>
                      {card.label} · {card.value}
                    </span>
                  ))}
                </div>
              </div>
            </ConceptPanel>
          </>
        ) : (
          <>
            <div className="concept-grid concept-grid--author-refined">
              <ConceptPanel eyebrow={copy.cardsTitle} title="编译台只保留会改变质感的卡片" subtitle="加载不是流水线进度，而是这份故事正在如何收口。">
                <div className="concept-loading-grid concept-loading-grid--refined">
                  {loadingHighlights.map((card) => (
                    <article className={`concept-loading-card is-${card.emphasis}`} key={card.card_id}>
                      <span>{card.label}</span>
                      <strong>{card.value}</strong>
                    </article>
                  ))}
                </div>
              </ConceptPanel>

              <ConceptPanel eyebrow={copy.beatsTitle} title="终局前的场面顺序" subtitle="保留一条可读的推进线，不把注意力打散到无关状态。">
                <ConceptBeatLadder activeIndex={3} beats={preview.beats} />
              </ConceptPanel>
            </div>

            <ConceptPanel eyebrow={copy.publishTitle} title="发布前只看最关键的三件事" subtitle={copy.publishCopy}>
              <div className="concept-grid concept-grid--author-support-refined">
                <div className="concept-loading-hero">
                  <article className="concept-support-strip__item">
                    <span>对外标题</span>
                    <strong>{preview.story.title}</strong>
                  </article>
                  <article className="concept-support-strip__item">
                    <span>当前气压</span>
                    <strong>{preview.story.tone}</strong>
                  </article>
                  <article className="concept-support-strip__item">
                    <span>终局代价</span>
                    <strong>{preview.story.stakes}</strong>
                  </article>
                </div>

                <ConceptCastRail items={preview.cast_slots} title={copy.castTitle} />

                <div className="concept-static-publish">
                  <span>{stageCopy.subtitle}</span>
                  <button className="concept-review__cta" disabled type="button">
                    静态 review，不执行发布
                  </button>
                </div>
              </div>
            </ConceptPanel>
          </>
        )}
      </section>
    </main>
  )
}
