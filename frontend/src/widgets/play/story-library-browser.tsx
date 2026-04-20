import type { CSSProperties } from "react"
import { motion, useScroll, useTransform } from "motion/react"
import type { PublishedStoryCard, PublishedStoryListView } from "../../index"
import { StoryLibraryCard } from "../../entities/story/ui/story-library-card"
import { STORYLINE_ASSETS, featuredArchiveAsset } from "../../shared/lib/storyline-assets"
import { localizeStorylineValue } from "../../shared/lib/storyline"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"
import { StorylineActionRow, StorylineMetaStrip, StorylineSectionHeader, StorylineTag } from "../../shared/ui/storyline-primitives"
import { StudioFooter } from "../chrome/studio-footer"

export function StoryLibraryBrowser({
  authenticated,
  stories,
  selectedStory,
  selectedStoryId,
  query,
  theme,
  selectedTheme,
  selectedView,
  themeFacets,
  total,
  hasMore,
  loading,
  loadingMore,
  error,
  onSelectStory,
  onOpenStoryDetail,
  onOpenCreateStory,
  onThemeChange,
  onViewChange,
  onLoadMore,
}: {
  authenticated: boolean
  stories: PublishedStoryCard[]
  selectedStory: PublishedStoryCard | null
  selectedStoryId: string | null
  query: string
  theme: string | null
  selectedTheme: string | null
  selectedView: PublishedStoryListView
  themeFacets: Array<{ theme: string; count: number }>
  total: number
  hasMore: boolean
  loading: boolean
  loadingMore: boolean
  error: string | null
  onSelectStory: (storyId: string) => void
  onOpenStoryDetail: (storyId: string) => void
  onOpenCreateStory: () => void
  onThemeChange: (theme: string | null) => void
  onViewChange: (view: PublishedStoryListView) => void
  onLoadMore: () => void
}) {
  const motionPreset = useStorylineMotion()
  const { scrollY } = useScroll()
  const stageImage = STORYLINE_ASSETS.backgrounds.boardroomObsidian
  const stageY = useTransform(scrollY, [0, 560], motionPreset.reduced ? [0, 0] : [0, 84])
  const stageScale = useTransform(scrollY, [0, 560], motionPreset.reduced ? [1, 1] : [1, 1.05])
  const copyY = useTransform(scrollY, [0, 420], motionPreset.reduced ? [0, 0] : [0, 72])
  const copyOpacity = useTransform(scrollY, [0, 420], motionPreset.reduced ? [1, 1] : [1, 0.22])
  const statsY = useTransform(scrollY, [0, 420], motionPreset.reduced ? [0, 0] : [0, 42])
  const teaserY = useTransform(scrollY, [0, 420], motionPreset.reduced ? [0, 0] : [0, 28])

  const featuredStory = selectedStory ?? stories[0] ?? null
  const hasActiveFilters = query.length > 0 || Boolean(theme)

  return (
    <div className="editorial-page editorial-page--library storyline-page storyline-page--library">
      <section className="storyline-archive-stage">
        <motion.div
          aria-hidden="true"
          className="storyline-archive-stage__background"
          style={{
            ["--storyline-surface-image" as string]: `url("${stageImage}")`,
            y: stageY,
            scale: stageScale,
          }}
        />
        <div aria-hidden="true" className="storyline-archive-stage__veil" />

        <div className="storyline-archive-stage__inner">
          <motion.div
            className="storyline-archive-stage__copy storyline-poster-stage"
            style={{
              y: copyY,
              opacity: copyOpacity,
            }}
          >
            <div className="storyline-archive-stage__issue">
              <StorylineTag tone="danger">受限档案</StorylineTag>
              <span>今夜头版</span>
            </div>
            <h1>
              案卷
              <br />
              陈列
            </h1>
            <p>都市、豪门、夜色房间与最昂贵的关系事故，都在这里先被整理成一张可翻开的绯闻头版。</p>
          </motion.div>

          <motion.div className="storyline-archive-stage__bottom" style={{ y: teaserY }}>
            <motion.div className="storyline-archive-stage__stats" style={{ y: statsY }}>
              <div>
                <span className="storyline-field-label">可见案卷</span>
                <strong>{total}</strong>
              </div>
              <div>
                <span className="storyline-field-label">当前视图</span>
                <strong>{localizeStorylineValue(selectedView)}</strong>
              </div>
              <div>
                <span className="storyline-field-label">主题筛选</span>
                <strong>{selectedTheme ? localizeStorylineValue(selectedTheme) : "全部主题"}</strong>
              </div>
            </motion.div>

            {featuredStory ? (
              <motion.div className="storyline-archive-stage__teaser" {...motionPreset.reveal({ delay: 0.1, y: 18, duration: 0.72 })}>
                <div>
                  <StorylineTag tone="gold">本周主案卷</StorylineTag>
                  <strong>{featuredStory.title}</strong>
                  <p>{featuredStory.one_liner}</p>
                </div>
                <StorylineActionRow>
                  <motion.button
                    className="studio-button studio-button--primary"
                    onClick={() => onOpenStoryDetail(featuredStory.story_id)}
                    type="button"
                    whileHover={motionPreset.hoverLift}
                    whileTap={motionPreset.tapPress}
                  >
                    打开主案卷
                  </motion.button>
                </StorylineActionRow>
                <p className="storyline-archive-stage__teaser-note">
                  {authenticated ? "想写新的危险关系，可以从页头的新建入口直接起草。" : "想写新的危险关系，先登录后再开启自己的第一份案卷。"}
                </p>
              </motion.div>
            ) : null}
          </motion.div>
        </div>
      </section>

      {featuredStory ? (
        <motion.section className="storyline-library-featured" {...motionPreset.inView({ y: 24, duration: 0.64 })}>
          <div
            className="storyline-library-featured__cover"
            style={{ "--storyline-surface-image": `url("${featuredArchiveAsset(featuredStory.theme)}")` } as CSSProperties}
          >
            <StorylineTag tone="danger">主案卷</StorylineTag>
            <strong>{featuredStory.title}</strong>
          </div>
          <div className="storyline-library-featured__body">
            <StorylineSectionHeader
              eyebrow={<StorylineTag tone="muted">本周重点</StorylineTag>}
              title={featuredStory.title}
              subtitle={featuredStory.premise}
            />
            <StorylineMetaStrip
              items={[
                { label: "主题", value: localizeStorylineValue(featuredStory.theme) },
                { label: "气质", value: localizeStorylineValue(featuredStory.tone) },
                { label: "结构", value: localizeStorylineValue(featuredStory.topology) },
              ]}
            />
            <p className="storyline-library-featured__lede">{featuredStory.one_liner}</p>
            <StorylineActionRow>
              <motion.button
                className="studio-button studio-button--primary"
                onClick={() => onOpenStoryDetail(featuredStory.story_id)}
                type="button"
                whileHover={motionPreset.hoverLift}
                whileTap={motionPreset.tapPress}
              >
                进入案卷
              </motion.button>
              <motion.button
                className="studio-button studio-button--secondary"
                onClick={() => onSelectStory(featuredStory.story_id)}
                type="button"
                whileHover={motionPreset.hoverLift}
                whileTap={motionPreset.tapPress}
              >
                固定为主案卷
              </motion.button>
            </StorylineActionRow>
          </div>
        </motion.section>
      ) : null}

      <motion.section className="storyline-library-browser" {...motionPreset.inView({ y: 20, duration: 0.62 })}>
        <div className="storyline-library-browser__header">
          <StorylineSectionHeader
            eyebrow={<StorylineTag tone="muted">档案库</StorylineTag>}
            title="连载案卷"
            subtitle={hasActiveFilters ? "已按关键词、主题和可见范围重新整理。" : "所有可游玩的绯闻档案都在这里继续排开。"}
          />

          <div className="storyline-library-controls">
            <label className="storyline-input-inline">
              <span className="storyline-field-label">视图</span>
              <select onChange={(event) => onViewChange(event.target.value as PublishedStoryListView)} value={selectedView}>
                {authenticated ? <option value="accessible">可见</option> : null}
                {authenticated ? <option value="mine">我的</option> : null}
                <option value="public">公开</option>
              </select>
            </label>
            <label className="storyline-input-inline">
              <span className="storyline-field-label">主题</span>
              <select onChange={(event) => onThemeChange(event.target.value || null)} value={selectedTheme ?? ""}>
                <option value="">全部主题</option>
                {themeFacets.map((facet) => (
                  <option key={facet.theme} value={facet.theme}>
                    {localizeStorylineValue(facet.theme)} ({facet.count})
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {hasActiveFilters ? (
          <div className="storyline-chip-grid">
            {query ? <StorylineTag tone="default">关键词：{query}</StorylineTag> : null}
            {theme ? <StorylineTag tone="gold">{localizeStorylineValue(theme)}</StorylineTag> : null}
            <StorylineTag tone="muted">视图：{localizeStorylineValue(selectedView)}</StorylineTag>
          </div>
        ) : null}

        {error ? <p className="editorial-error">{error}</p> : null}

        {loading ? (
          <div className="editorial-empty-state">
            <h3>正在装载档案库</h3>
            <p>正在调取最新的绯闻案卷。</p>
          </div>
        ) : stories.length === 0 ? (
          <div className="editorial-empty-state">
            <h3>没有找到匹配案卷</h3>
            <p>
              {hasActiveFilters
                ? "换一个关键词、主题或可见范围再试一次。"
                : authenticated
                  ? "当前档案库里还没有可见案卷。"
                  : "登录后就能建立自己的私密档案库，并浏览公开案卷。"}
            </p>
          </div>
        ) : (
          <>
            <div className="storyline-archive-grid">
              {stories.map((story, index) => (
                <motion.div
                  key={story.story_id}
                  {...motionPreset.inView({ delay: Math.min(index * 0.04, 0.18), y: 18, duration: 0.54 })}
                >
                  <StoryLibraryCard
                    onSelect={() => {
                      onSelectStory(story.story_id)
                      onOpenStoryDetail(story.story_id)
                    }}
                    selected={selectedStoryId === story.story_id}
                    story={story}
                  />
                </motion.div>
              ))}

              <motion.button
                className="storyline-archive-card storyline-archive-card--cta"
                onClick={onOpenCreateStory}
                type="button"
                whileHover={motionPreset.hoverLift}
                whileTap={motionPreset.tapPress}
                {...motionPreset.inView({ delay: 0.16, y: 18, duration: 0.54 })}
              >
                <div className="storyline-archive-card__cover storyline-archive-card__cover--plain">
                  <div className="storyline-archive-card__eyebrow-row">
                    <StorylineTag tone="danger">开启新案卷</StorylineTag>
                    <span className="storyline-archive-card__issue">入口</span>
                  </div>
                  <div className="storyline-archive-card__headline">
                    <span className="storyline-field-label">下一份档案</span>
                    <h4>写下新的危险关系</h4>
                  </div>
                </div>
                <div className="storyline-archive-card__body">
                  <p>故事封面留白，但整座城市会继续给出新的房间、新的把柄和新的失控方式。</p>
                  <div className="storyline-chip-grid">
                    <StorylineTag tone="gold">{authenticated ? "开启新案卷" : "登录后新建"}</StorylineTag>
                    <StorylineTag tone="muted">进入工作台</StorylineTag>
                  </div>
                </div>
              </motion.button>
            </div>

            {hasMore ? (
              <div className="storyline-library-pagination">
                <button className="studio-button studio-button--secondary" disabled={loadingMore} onClick={onLoadMore} type="button">
                  {loadingMore ? "正在加载..." : "从档案库加载更多"}
                </button>
              </div>
            ) : null}
          </>
        )}
      </motion.section>

      <StudioFooter />
    </div>
  )
}
