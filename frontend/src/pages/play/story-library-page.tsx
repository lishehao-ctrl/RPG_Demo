import { motion } from "motion/react"
import type { PublishedStoryListView } from "../../index"
import { useStoryLibrary } from "../../features/play/library/model/use-story-library"
import { getEditorialBackdropByView, getEditorialThemeImage } from "../../shared/lib/editorial-assets"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

const VIEW_LABELS: Record<PublishedStoryListView, string> = {
  accessible: "可访问",
  mine: "我的",
  public: "公开",
}

export function StoryLibraryPage({
  authenticated,
  initialStoryId,
  searchQuery,
  selectedTheme,
  selectedView,
  onOpenCreateStory,
  onRequireAuth,
  onOpenStoryDetail,
  onThemeChange,
  onViewChange,
}: {
  authenticated: boolean
  initialStoryId?: string
  searchQuery?: string
  selectedTheme?: string | null
  selectedView?: PublishedStoryListView
  onOpenCreateStory: () => void
  onRequireAuth: () => void
  onOpenStoryDetail: (storyId: string) => void
  onThemeChange: (theme: string | null) => void
  onViewChange: (view: PublishedStoryListView) => void
}) {
  const library = useStoryLibrary(initialStoryId, searchQuery, selectedTheme, selectedView ?? "accessible")
  const motionPreset = useStorylineMotion()
  const featured = library.selectedStory
  const featureImage = featured ? getEditorialThemeImage(featured.theme) : getEditorialBackdropByView("library")

  return (
    <main className="mag-page">
      <section className="mag-section">
        <div className="mag-section__inner mag-library-feature">
          <motion.article className="mag-library-feature__card" {...motionPreset.reveal({ y: 24, duration: 0.72 })}>
            <div className="mag-card-media" style={{ backgroundImage: `url("${featureImage}")` }} />
            <div className="mag-feature-card__veil" />
            <div className="mag-library-feature__content">
              <div className="mag-badge-row">
                <span className="mag-chip mag-chip--accent">{selectedTheme ?? featured?.theme ?? "档案库"}</span>
                <span className="mag-chip mag-chip--gold">{VIEW_LABELS[selectedView ?? "accessible"]}</span>
              </div>
              <span className="mag-kicker">档案库 / 搜索仍由顶部输入驱动</span>
              <h1 className="mag-feature-title">{featured?.title ?? "公开案卷档案库"}</h1>
              <p>{featured?.premise ?? "这里统一收纳已发布故事，主卡展示当前选中的案卷，下面是可滚动扩展的杂志卡片列表。"}</p>
              <div className="mag-action-row">
                {featured ? (
                  <button className="mag-button mag-button--primary" onClick={() => onOpenStoryDetail(featured.story_id)} type="button">
                    查看详情
                  </button>
                ) : null}
                <button
                  className="mag-button mag-button--secondary"
                  onClick={authenticated ? onOpenCreateStory : onRequireAuth}
                  type="button"
                >
                  {authenticated ? "新建案卷" : "登录后新建"}
                </button>
              </div>
            </div>
          </motion.article>

          <div className="mag-toolbar">
            <div className="mag-filter-row">
              <button className={`mag-filter-pill ${selectedTheme ? "" : "is-active"}`} onClick={() => onThemeChange(null)} type="button">
                全部题材
              </button>
              {library.themeFacets.map((facet) => (
                <button
                  className={`mag-filter-pill ${selectedTheme === facet.theme ? "is-active" : ""}`}
                  key={facet.theme}
                  onClick={() => onThemeChange(selectedTheme === facet.theme ? null : facet.theme)}
                  type="button"
                >
                  {facet.theme}
                </button>
              ))}
            </div>

            <div className="mag-filter-row">
              {(authenticated ? (["accessible", "mine", "public"] as PublishedStoryListView[]) : (["public"] as PublishedStoryListView[])).map((view) => (
                <button
                  className={`mag-filter-pill ${(selectedView ?? "accessible") === view ? "is-active" : ""}`}
                  key={view}
                  onClick={() => onViewChange(view)}
                  type="button"
                >
                  {VIEW_LABELS[view]}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="mag-section mag-section--tight">
        <div className="mag-section__inner">
          <div className="mag-section__header">
            <span className="mag-panel__eyebrow">档案列表</span>
            <h2>{library.loading ? "正在整理案卷" : `共 ${library.total} 份案卷`}</h2>
            <p>{searchQuery ? `当前搜索：${searchQuery}` : "搜索词仍由顶部输入统一驱动，这里只负责展示与切换。"}</p>
          </div>

          {library.error ? (
            <div className="mag-error">
              <div>
                <h3>档案暂不可用</h3>
                <p>{library.error}</p>
              </div>
            </div>
          ) : (
            <>
              <div className="mag-story-grid">
                {library.stories.map((story, index) => (
                  <article className="mag-story-card" key={story.story_id} onClick={() => onOpenStoryDetail(story.story_id)}>
                    <div className="mag-story-card__visual">
                      <div className="mag-card-media" style={{ backgroundImage: `url("${getEditorialThemeImage(story.theme, index)}")` }} />
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
                        <span>{story.tone}</span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>

              {library.stories.length === 0 && !library.loading ? (
                <div className="mag-empty">
                  <div>
                    <h3>暂时没有匹配案卷</h3>
                    <p>可以换一个题材筛选，或者直接新建一份故事。</p>
                  </div>
                </div>
              ) : null}

              {library.hasMore ? (
                <div className="mag-action-row" style={{ justifyContent: "center", marginTop: 28 }}>
                  <button
                    className="mag-button mag-button--secondary"
                    disabled={library.loadingMore}
                    onClick={() => {
                      void library.loadMore()
                    }}
                    type="button"
                  >
                    {library.loadingMore ? "正在加载..." : "加载更多案卷"}
                  </button>
                </div>
              ) : null}
            </>
          )}
        </div>
      </section>
    </main>
  )
}
