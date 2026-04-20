import { useEffect, useMemo, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import type { PublishedStoryCard } from "../../index"
import { useApiClient } from "../../app/providers/api-client-provider"
import { buildLandingHeroSlides, getEditorialCharacterImage } from "../../shared/lib/editorial-assets"
import { toErrorMessage } from "../../shared/lib/errors"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

const HERO_ROLE_LABELS = ["主视角", "危险同盟", "失控变量"] as const

function tensionLevel(index: number) {
  return 7 + (index % 3)
}

export function LandingPage({
  authenticated,
  onOpenCreateStory,
  onOpenLibrary,
  onOpenPlaySession,
  onOpenStoryDetail,
}: {
  authenticated: boolean
  onOpenCreateStory: () => void
  onOpenLibrary: () => void
  onOpenPlaySession: (sessionId: string) => void
  onOpenStoryDetail: (storyId: string) => void
}) {
  const api = useApiClient()
  const motionPreset = useStorylineMotion()
  const [stories, setStories] = useState<PublishedStoryCard[]>([])
  const [storiesLoading, setStoriesLoading] = useState(true)
  const [currentSlide, setCurrentSlide] = useState(0)
  const [jumpLoading, setJumpLoading] = useState(false)
  const [jumpError, setJumpError] = useState<string | null>(null)

  useEffect(() => {
    let active = true

    const loadStories = async () => {
      setStoriesLoading(true)
      try {
        const response = await api.listStories({ view: "public", limit: 6 })
        if (active) {
          setStories(response.stories)
        }
      } catch {
        if (active) {
          setStories([])
        }
      } finally {
        if (active) {
          setStoriesLoading(false)
        }
      }
    }

    void loadStories()

    return () => {
      active = false
    }
  }, [api])

  const slides = useMemo(() => buildLandingHeroSlides(stories), [stories])
  const activeIndex = slides.length === 0 ? 0 : currentSlide % slides.length
  const activeSlide = slides[activeIndex]
  const activeStory = stories[activeIndex] ?? stories[0] ?? null

  useEffect(() => {
    if (slides.length <= 1) {
      return
    }

    const timer = window.setInterval(() => {
      setCurrentSlide((value) => (value + 1) % slides.length)
    }, 7000)

    return () => {
      window.clearInterval(timer)
    }
  }, [slides.length])

  const handleJumpIn = async () => {
    setJumpError(null)

    if (!authenticated) {
      onOpenLibrary()
      return
    }

    setJumpLoading(true)
    try {
      const response = await api.listStories({ view: "public", limit: 1 })
      const featured = response.stories[0]
      if (!featured) {
        onOpenLibrary()
        return
      }
      const session = await api.createPlaySession({ story_id: featured.story_id })
      onOpenPlaySession(session.session_id)
    } catch (error) {
      setJumpError(`暂时无法直接入戏：${toErrorMessage(error)}`)
    } finally {
      setJumpLoading(false)
    }
  }

  return (
    <main className="mag-page mag-page--dark">
      <section className="mag-hero">
        <AnimatePresence mode="wait">
          <motion.div
            className="mag-hero__media"
            key={activeSlide.id}
            style={{ backgroundImage: `url("${activeSlide.image}")` }}
            {...motionPreset.fade({ duration: 0.72 })}
          />
        </AnimatePresence>
        <div className="mag-hero__veil" />

        <div className="mag-hero__inner">
          <motion.div className="mag-hero__copy" {...motionPreset.reveal({ y: 28, duration: 0.84 })}>
            <div className="mag-badge-row">
              <span className="mag-chip mag-chip--accent">门面首页</span>
              <span className="mag-chip mag-chip--gold">关系戏引擎</span>
            </div>

            <span className="mag-kicker">流言与荣光 · 可游玩的关系剧场</span>
            <h1>{activeSlide.title}</h1>
            <div className="mag-hero__subtitle">{activeSlide.subtitle}</div>
            <p className="mag-hero__lead">{activeSlide.description}</p>

            <div className="mag-stat-row">
              {activeSlide.badges.map((badge) => (
                <span className="mag-stat-pill" key={badge}>
                  {badge}
                </span>
              ))}
            </div>

            <div className="mag-action-row">
              <button className="mag-button mag-button--primary" onClick={onOpenCreateStory} type="button">
                开始立案
              </button>
              <button
                className="mag-button mag-button--secondary"
                onClick={() => {
                  if (activeStory) {
                    onOpenStoryDetail(activeStory.story_id)
                    return
                  }
                  onOpenLibrary()
                }}
                type="button"
              >
                查看当前主打
              </button>
              <button
                className="mag-button mag-button--secondary"
                disabled={jumpLoading}
                onClick={() => {
                  void handleJumpIn()
                }}
                type="button"
              >
                {authenticated ? (jumpLoading ? "正在落座..." : "随机入戏") : "先看公开案卷"}
              </button>
            </div>

            {jumpError ? <p className="editorial-error">{jumpError}</p> : null}
          </motion.div>

          <motion.div className="mag-hero__rail" {...motionPreset.reveal({ delay: 0.14, x: 24, y: 0, duration: 0.8 })}>
            <div className="mag-hero__rail">
              {HERO_ROLE_LABELS.map((label, index) => (
                <article className={`mag-character-card ${index === 0 ? "mag-character-card--lead" : "mag-character-card--support"}`} key={label}>
                  <div className="mag-card-media" style={{ backgroundImage: `url("${getEditorialCharacterImage(index)}")` }} />
                  <div className="mag-character-card__overlay" />
                  <div className="mag-character-card__copy">
                    <strong>{label}</strong>
                    <span>{activeSlide.badges[index] ?? "高压关系线"}</span>
                  </div>
                </article>
              ))}
            </div>

            <div className="mag-tension">
              <span className="mag-tension__label">张力</span>
              <div className="mag-tension__bars">
                {Array.from({ length: 10 }).map((_, index) => (
                  <i
                    key={index}
                    style={{
                      backgroundColor:
                        index < tensionLevel(activeIndex) ? "rgba(212, 168, 83, 0.95)" : "rgba(251, 246, 239, 0.18)",
                    }}
                  />
                ))}
              </div>
              <span className="mag-tension__score">{tensionLevel(activeIndex)}</span>
            </div>
          </motion.div>
        </div>
      </section>

      <section className="mag-ticker">
        <div className="mag-ticker__track">
          {Array.from({ length: 2 }).map((_, copyIndex) => (
            <span key={copyIndex}>
              热播案卷 / 关系回流 / 公开试探 / 后果升级 / 都市修罗场 / 暧昧与站队 / 黑账与旧爱 / 高压关系戏 /
            </span>
          ))}
        </div>
      </section>

      <section className="mag-section">
        <div className="mag-section__inner">
          <div className="mag-section__header">
            <span className="mag-panel__eyebrow">当前主打</span>
            <h2>这不是题材列表，是不同形式的失控现场</h2>
            <p>首页不负责解释所有规则，它只负责让用户第一眼知道这里卖的是关系、后果和体面崩塌的瞬间。</p>
          </div>

          {activeStory ? (
            <motion.article className="mag-feature-card mag-library-feature__card" {...motionPreset.inView({ y: 22, duration: 0.62 })}>
              <div className="mag-card-media" style={{ backgroundImage: `url("${activeSlide.image}")` }} />
              <div className="mag-feature-card__veil" />
              <div className="mag-feature-card__content">
                <div className="mag-badge-row">
                  <span className="mag-chip mag-chip--accent">{activeStory.theme}</span>
                  <span className="mag-chip mag-chip--gold">{`${activeStory.npc_count} 人关系局`}</span>
                </div>
                <h3>{activeStory.title}</h3>
                <p>{activeStory.premise}</p>
                <div className="mag-action-row">
                  <button className="mag-button mag-button--primary" onClick={() => onOpenStoryDetail(activeStory.story_id)} type="button">
                    查看详情
                  </button>
                  <button className="mag-button mag-button--secondary" onClick={onOpenLibrary} type="button">
                    进入档案库
                  </button>
                </div>
              </div>
            </motion.article>
          ) : null}
        </div>
      </section>

      <section className="mag-section mag-section--tight">
        <div className="mag-section__inner">
          <div className="mag-section__header">
            <span className="mag-panel__eyebrow">精选案卷</span>
            <h2>{storiesLoading ? "正在整理今晚值得点开的局" : "选你的下一场关系戏"}</h2>
            <p>第一轮先直接拉公开案卷。后面如果你要做精选运营位，我们再把首页主打和库里排序拆开。</p>
          </div>

          <div className="mag-story-grid">
            {(stories.length > 0 ? stories : []).map((story, index) => (
              <article className="mag-story-card" key={story.story_id} onClick={() => onOpenStoryDetail(story.story_id)}>
                <div className="mag-story-card__visual">
                  <div className="mag-card-media" style={{ backgroundImage: `url("${buildLandingHeroSlides([story])[0].image}")` }} />
                </div>
                <div className="mag-story-card__body">
                  <div className="mag-badge-row">
                    <span className="mag-chip mag-chip--paper">{story.theme}</span>
                    <span className="mag-chip mag-chip--paper">{story.visibility === "public" ? "公开" : "私密"}</span>
                  </div>
                  <h3>{story.title}</h3>
                  <p>{story.one_liner}</p>
                  <div className="mag-story-card__meta">
                    <span>{`${story.npc_count} 人`}</span>
                    <span>{`${story.beat_count} 幕`}</span>
                    <span>{index < 2 ? "热度高" : "新上线"}</span>
                  </div>
                </div>
              </article>
            ))}

            {!storiesLoading && stories.length === 0 ? (
              <article className="mag-panel">
                <span className="mag-panel__eyebrow">档案暂空</span>
                <h3 className="mag-panel__title">先立一份案卷</h3>
                <p>当前还没有公开故事。可以直接从首页开始立案，把第一份可玩的关系戏发布出来。</p>
                <div className="mag-action-row">
                  <button className="mag-button mag-button--primary" onClick={onOpenCreateStory} type="button">
                    立即立案
                  </button>
                </div>
              </article>
            ) : null}
          </div>
        </div>
      </section>

      <section className="mag-section">
        <div className="mag-section__inner">
          <div className="mag-section__header">
            <span className="mag-panel__eyebrow">体验结构</span>
            <h2>前台主链要像一份杂志，不像后台工作流</h2>
          </div>

          <div className="mag-grid mag-grid--3">
            {[
              {
                title: "立案",
                summary: "从一句种子开始，先把人物、钩子、秘密和场面 promise 写明白。",
              },
              {
                title: "编译",
                summary: "让生成过程像在排版一期特刊，而不是冷冰冰地看进度条跑完。",
              },
              {
                title: "入戏",
                summary: "主舞台永远先给场面和下一手，让关系与后果持续回流。",
              },
            ].map((item) => (
              <article className="mag-panel" key={item.title}>
                <span className="mag-panel__eyebrow">{item.title}</span>
                <h3 className="mag-panel__title">{item.title}</h3>
                <p>{item.summary}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  )
}
