export const STORYLINE_ASSETS = {
  backgrounds: {
    forbiddenTable: "/storyline/backgrounds/forbidden-table.png",
    skylineSofa: "/storyline/backgrounds/skyline-sofa.png",
    penthouseRainy: "/storyline/backgrounds/penthouse-rainy.png",
    corridorShadow: "/storyline/backgrounds/corridor-shadow.png",
    premiumStillLife: "/storyline/backgrounds/premium-still-life.png",
    evidenceDark: "/storyline/backgrounds/evidence-dark.png",
    loungeObsidian: "/storyline/backgrounds/lounge-obsidian.png",
    loungeAmber: "/storyline/backgrounds/lounge-amber.png",
    boardroomObsidian: "/storyline/backgrounds/boardroom-obsidian.png",
    boardroomMarble: "/storyline/backgrounds/boardroom-marble.png",
    exteriorBuilding: "/storyline/backgrounds/exterior-building.png",
  },
  portraits: {
    femaleProfile: "/storyline/portraits/female-profile-reference.png",
    maleProfile: "/storyline/portraits/male-profile-reference.png",
    noirVariant: "/storyline/portraits/noir-variant-reference.png",
  },
} as const

function normalizeTheme(value: string | null | undefined): "wealth" | "office" | "entertainment" | "campus" | "supernatural" | "generic" {
  const lowered = (value ?? "").toLowerCase()
  if (/(wealth|heir|豪门|继承)/.test(lowered)) return "wealth"
  if (/(office|boardroom|董事会|修罗场)/.test(lowered)) return "office"
  if (/(entertainment|celebrity|热搜|绯闻)/.test(lowered)) return "entertainment"
  if (/(campus|校园|校庆|学生)/.test(lowered)) return "campus"
  if (/(supernatural|契约|夜色)/.test(lowered)) return "supernatural"
  return "generic"
}

export function detailHeroAsset(theme: string | null | undefined): string {
  switch (normalizeTheme(theme)) {
    case "wealth":
      return STORYLINE_ASSETS.backgrounds.forbiddenTable
    case "office":
      return STORYLINE_ASSETS.backgrounds.boardroomObsidian
    case "entertainment":
      return STORYLINE_ASSETS.backgrounds.loungeObsidian
    case "campus":
      return STORYLINE_ASSETS.backgrounds.skylineSofa
    case "supernatural":
      return STORYLINE_ASSETS.backgrounds.penthouseRainy
    default:
      return STORYLINE_ASSETS.backgrounds.skylineSofa
  }
}

export function featuredArchiveAsset(theme: string | null | undefined): string {
  switch (normalizeTheme(theme)) {
    case "wealth":
      return STORYLINE_ASSETS.backgrounds.forbiddenTable
    case "office":
      return STORYLINE_ASSETS.backgrounds.boardroomMarble
    case "entertainment":
      return STORYLINE_ASSETS.backgrounds.loungeObsidian
    case "campus":
      return STORYLINE_ASSETS.backgrounds.loungeAmber
    case "supernatural":
      return STORYLINE_ASSETS.backgrounds.penthouseRainy
    default:
      return STORYLINE_ASSETS.backgrounds.loungeObsidian
  }
}

export function loadingHeroAsset(): string {
  return STORYLINE_ASSETS.backgrounds.penthouseRainy
}

export function createHeroAsset(): string {
  return STORYLINE_ASSETS.backgrounds.skylineSofa
}

export function detailEvidenceAsset(theme: string | null | undefined): string {
  return normalizeTheme(theme) === "office"
    ? STORYLINE_ASSETS.backgrounds.evidenceDark
    : STORYLINE_ASSETS.backgrounds.premiumStillLife
}

export function detailProfileAssets(): string[] {
  return [
    STORYLINE_ASSETS.portraits.femaleProfile,
    STORYLINE_ASSETS.portraits.maleProfile,
    STORYLINE_ASSETS.portraits.noirVariant,
  ]
}

export function detailPosterSet(theme: string | null | undefined): Array<{
  id: string
  eyebrow: string
  title: string
  summary: string
  asset: string
}> {
  switch (normalizeTheme(theme)) {
    case "wealth":
      return [
        { id: "main", eyebrow: "主海报", title: "华丽陷阱", summary: "最体面的房间，最先酝酿失控。", asset: STORYLINE_ASSETS.backgrounds.forbiddenTable },
        { id: "private", eyebrow: "密室视角", title: "暗场试探", summary: "真正的站队，往往发生在没人开口的时候。", asset: STORYLINE_ASSETS.backgrounds.loungeObsidian },
        { id: "evidence", eyebrow: "证据视角", title: "封缄之物", summary: "一件证物，就足够让整张关系网重新站位。", asset: STORYLINE_ASSETS.backgrounds.premiumStillLife },
      ]
    case "office":
      return [
        { id: "main", eyebrow: "主海报", title: "会议桌尽头", summary: "这不是谈判桌，是体面开始碎裂的地方。", asset: STORYLINE_ASSETS.backgrounds.boardroomObsidian },
        { id: "private", eyebrow: "终局视角", title: "冷面账本", summary: "越安静的房间，越像没有退路的终局。", asset: STORYLINE_ASSETS.backgrounds.boardroomMarble },
        { id: "evidence", eyebrow: "证据视角", title: "未说破之前", summary: "一张纸、一只杯子、一个沉默，就能让人改口。", asset: STORYLINE_ASSETS.backgrounds.evidenceDark },
      ]
    case "entertainment":
      return [
        { id: "main", eyebrow: "主海报", title: "镜头之外", summary: "最贵的秘密，从来不在直播里说破。", asset: STORYLINE_ASSETS.backgrounds.loungeObsidian },
        { id: "private", eyebrow: "夜场视角", title: "余温包厢", summary: "人群散去后，真正危险的话才会开始。", asset: STORYLINE_ASSETS.backgrounds.loungeAmber },
        { id: "evidence", eyebrow: "证据视角", title: "被留在桌上", summary: "有人先离席，但并没有把秘密带走。", asset: STORYLINE_ASSETS.backgrounds.premiumStillLife },
      ]
    case "campus":
      return [
        { id: "main", eyebrow: "主海报", title: "风口边缘", summary: "最轻的心事，也会在夜色里被放大。", asset: STORYLINE_ASSETS.backgrounds.skylineSofa },
        { id: "private", eyebrow: "走廊视角", title: "无人的一层", summary: "消息总在回宿舍之前，先穿过一条空走廊。", asset: STORYLINE_ASSETS.backgrounds.corridorShadow },
        { id: "evidence", eyebrow: "证据视角", title: "桌上的线索", summary: "有些话不需要说出来，留在桌上就够了。", asset: STORYLINE_ASSETS.backgrounds.premiumStillLife },
      ]
    case "supernatural":
      return [
        { id: "main", eyebrow: "主海报", title: "夜色契约", summary: "窗外是城市，窗内是没人敢先应下的条件。", asset: STORYLINE_ASSETS.backgrounds.penthouseRainy },
        { id: "private", eyebrow: "影廊视角", title: "无人走廊", summary: "在真正见面之前，影子已经先替人做了决定。", asset: STORYLINE_ASSETS.backgrounds.corridorShadow },
        { id: "evidence", eyebrow: "证据视角", title: "静物低语", summary: "一件看似无辜的东西，也可能先替命运签字。", asset: STORYLINE_ASSETS.backgrounds.evidenceDark },
      ]
    default:
      return [
        { id: "main", eyebrow: "主海报", title: "夜色之前", summary: "每个房间都在等一句会让人后悔的话。", asset: STORYLINE_ASSETS.backgrounds.skylineSofa },
        { id: "private", eyebrow: "密室视角", title: "玻璃之后", summary: "越是看得见城市，越会听见心里那点杂音。", asset: STORYLINE_ASSETS.backgrounds.loungeObsidian },
        { id: "evidence", eyebrow: "证据视角", title: "被留下的东西", summary: "真正危险的，往往不是人，而是人离开后还留在原地的东西。", asset: STORYLINE_ASSETS.backgrounds.premiumStillLife },
      ]
  }
}
