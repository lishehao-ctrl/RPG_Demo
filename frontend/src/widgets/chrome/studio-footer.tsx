export function StudioFooter() {
  return (
    <footer className="studio-footer">
      <div className="studio-footer__brand">
        <span className="studio-footer__wordmark">流言与荣光</span>
        <p>一座收纳都市关系戏、禁忌秘密与可游玩丑闻案卷的限制档案库。</p>
      </div>

      <div className="studio-footer__links">
        <button className="studio-footer-link" type="button">
          档案库
        </button>
        <button className="studio-footer-link" type="button">
          方法论
        </button>
        <button className="studio-footer-link" type="button">
          隐私
        </button>
      </div>

      <p className="studio-footer-copy">© 2026 流言与荣光。所有案卷，保留余波。</p>
    </footer>
  )
}
