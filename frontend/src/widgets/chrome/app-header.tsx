import type { ChangeEvent } from "react"
import type { AuthUserResponse } from "../../index"

export function AppHeader({
  routeName,
  onOpenLanding,
  onOpenCreateStory,
  onOpenLibrary,
  authenticated,
  authLoading,
  user,
  onOpenAuth,
  onLogout,
  searchEnabled = false,
  searchValue = "",
  onSearchChange,
}: {
  routeName:
    | "landing"
    | "auth"
    | "create-story"
    | "author-loading"
    | "concept-author"
    | "concept-play"
    | "story-library"
    | "story-detail"
    | "play-session"
  onOpenLanding: () => void
  onOpenCreateStory: () => void
  onOpenLibrary: () => void
  authenticated: boolean
  authLoading: boolean
  user: AuthUserResponse | null
  onOpenAuth: (mode: "login" | "register") => void
  onLogout: () => void
  searchEnabled?: boolean
  searchValue?: string
  onSearchChange?: (value: string) => void
}) {
  const landingActive = routeName === "landing"
  const createActive = routeName === "create-story" || routeName === "author-loading"
  const libraryActive = routeName === "story-library" || routeName === "story-detail" || routeName === "play-session"

  const handleSearchChange = (event: ChangeEvent<HTMLInputElement>) => {
    onSearchChange?.(event.target.value)
  }

  return (
    <header className={`mag-topbar ${landingActive ? "is-landing" : ""}`}>
      <div className="mag-topbar__brand">
        <button className="mag-brand-mark" onClick={onOpenLanding} type="button">
          <span className="mag-brand-mark__kicker">流言与荣光</span>
          <strong>案卷剧场</strong>
        </button>

        <nav className="mag-topbar__nav">
          <button className={`mag-topbar__link ${landingActive ? "is-active" : ""}`} onClick={onOpenLanding} type="button">
            首页
          </button>
          <button className={`mag-topbar__link ${libraryActive ? "is-active" : ""}`} onClick={onOpenLibrary} type="button">
            档案库
          </button>
          <button className={`mag-topbar__link ${createActive ? "is-active" : ""}`} onClick={onOpenCreateStory} type="button">
            新建
          </button>
        </nav>
      </div>

      <div className="mag-topbar__tools">
        <label className="mag-search">
          <span aria-hidden="true" className="material-symbols-outlined mag-search__icon">
            search
          </span>
          <input
            disabled={!searchEnabled}
            onChange={handleSearchChange}
            placeholder="搜索案卷"
            type="text"
            value={searchEnabled ? searchValue : ""}
          />
        </label>

        {authLoading ? (
          <div className="mag-account">
            <span className="material-symbols-outlined">hourglass_top</span>
            <div className="mag-account__identity">
              <strong>验证中</strong>
              <span>档案权限核对中</span>
            </div>
          </div>
        ) : authenticated && user ? (
          <div className="mag-account">
            <span className="material-symbols-outlined">account_circle</span>
            <div className="mag-account__identity">
              <strong>{user.display_name}</strong>
              <span>{user.email}</span>
            </div>
            <button className="mag-button mag-button--secondary" onClick={onLogout} type="button">
              退出登录
            </button>
          </div>
        ) : (
          <div className="mag-account">
            <button className="mag-button mag-button--secondary" onClick={() => onOpenAuth("login")} type="button">
              登录
            </button>
            <button className="mag-button mag-button--primary" onClick={() => onOpenAuth("register")} type="button">
              注册账户
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
