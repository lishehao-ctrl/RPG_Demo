import type { PublishedStoryCard } from "../../index"

const REMOTE_EDITORIAL_IMAGES = {
  heroSkyline:
    "https://images.unsplash.com/photo-1523609880870-c4c822e34ed4?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxsdXh1cnklMjBTaGFuZ2hhaSUyMHNreWxpbmUlMjBuaWdodCUyMGRyYW1hdGljfGVufDF8fHx8MTc3NDkxMjEzNHww&ixlib=rb-4.1.0&q=80&w=1280",
  heroRedCarpet:
    "/editorial-live/generated-20260406-redcarpet/redcarpet-d.png",
  sceneRedCarpetArrival:
    "/editorial-live/generated-20260406-redcarpet/redcarpet-b.png",
  sceneRedCarpetPress:
    "/editorial-live/generated-20260406-redcarpet/redcarpet-c.png",
  sceneRedCarpetCrowd:
    "/editorial-live/generated-20260406-redcarpet/redcarpet-a.png",
  heroPenthouse:
    "https://images.unsplash.com/photo-1760662564270-a55ad0a8df2c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxsdXh1cnklMjBwZW50aG91c2UlMjBpbnRlcmlvciUyMG5pZ2h0JTIwdmlld3xlbnwxfHx8fDE3NzQ5MTIxNDB8MA&ixlib=rb-4.1.0&q=80&w=1280",
  charWoman:
    "https://images.unsplash.com/photo-1768610285023-ab2f4c10ab63?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxkcmFtYXRpYyUyMEFzaWFuJTIwd29tYW4lMjByZWQlMjBkcmVzcyUyMG5pZ2h0JTIwY2l0eXxlbnwxfHx8fDE3NzQ5MTIxMzR8MA&ixlib=rb-4.1.0&q=80&w=960",
  charMan:
    "https://images.unsplash.com/photo-1701463387028-3947648f1337?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxBc2lhbiUyMGJ1c2luZXNzbWFuJTIwc3VpdCUyMGRhcmslMjBtb29keSUyMHBvcnRyYWl0fGVufDF8fHx8MTc3NDkxMjEzNHww&ixlib=rb-4.1.0&q=80&w=960",
  charSilhouette:
    "https://images.unsplash.com/photo-1608730178598-24bfba640fc0?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxlbGVnYW50JTIwd29tYW4lMjBzaWxob3VldHRlJTIwd2luZG93JTIwY2l0eSUyMG5pZ2h0fGVufDF8fHx8MTc3NDkxMjEzNXww&ixlib=rb-4.1.0&q=80&w=960",
  sceneChampagne:
    "https://images.unsplash.com/photo-1573830540758-68d5a242fc79?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxjaGFtcGFnbmUlMjBnbGFzcyUyMGNlbGVicmF0aW9uJTIwZGFyayUyMG1vb2R5fGVufDF8fHx8MTc3NDkxMjEzNnww&ixlib=rb-4.1.0&q=80&w=1280",
  sceneRain:
    "https://images.unsplash.com/photo-1684337566815-7fe3c14956c4?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxkcmFtYXRpYyUyMGNvdXBsZSUyMGFyZ3VtZW50JTIwbmlnaHQlMjByYWlufGVufDF8fHx8MTc3NDkxMjEzN3ww&ixlib=rb-4.1.0&q=80&w=1280",
  sceneCampus:
    "/editorial-live/generated-20260406-campus-v2/campus-a.png",
  sceneCampusArcade:
    "/editorial-live/generated-20260406-campus-v2/campus-b.png",
  sceneCampusCourtyard:
    "/editorial-live/generated-20260406-campus-v2/campus-c.png",
  sceneCampusEvidence:
    "/editorial-live/generated-20260406-campus-v2/campus-d.png",
  sceneStillLife:
    "https://images.unsplash.com/photo-1589133040700-84e1942a981e?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxicm9rZW4lMjB3aW5lJTIwZ2xhc3MlMjBkcmFtYXRpYyUyMHN0aWxsJTIwbGlmZXxlbnwxfHx8fDE3NzQ5MTIxNDB8MA&ixlib=rb-4.1.0&q=80&w=1280",
} as const

const LOCAL_EDITORIAL_VARIANTS = {
  foundation: {
    skyline: {
      activeKey: "active",
      variants: {
        // heroskyline-b: primary hero skyline with strongest left-side title space.
        active: "/editorial-live/generated-20260406-heroskyline/heroskyline-b.png",
        // heroskyline-d: balanced lounge framing with clean horizon line.
        altA: "/editorial-live/generated-20260406-heroskyline/heroskyline-d.png",
        // heroskyline-a: richer foreground prop storytelling.
        altB: "/editorial-live/generated-20260406-heroskyline/heroskyline-a.png",
        // heroskyline-c: darker fallback with stronger sofa silhouette.
        altC: "/editorial-live/generated-20260406-heroskyline/heroskyline-c.png",
      },
    },
  },
  office: {
    boardroom: {
      activeKey: "active",
      variants: {
        // officepower-c: main visual for office power topic.
        active: "/editorial-live/generated-20260406-officepower/officepower-c.png",
        // officepower-a: secondary option with clearer foreground reading.
        altA: "/editorial-live/generated-20260406-officepower/officepower-a.png",
        // officepower-d: darker alternative for high-pressure scenes.
        altB: "/editorial-live/generated-20260406-officepower/officepower-d.png",
        // officepower-b: backup with stronger screen-led composition.
        darkVariant: "/editorial-live/generated-20260406-officepower/officepower-b.png",
      },
    },
  },
  supernatural: {
    urbanNight: {
      activeKey: "active",
      variants: {
        // supernatural-urban-c: primary base with strongest atmosphere and clean left-side reading.
        active: "/editorial-live/generated-20260406-supernatural-urban/supernatural-urban-c.png",
        // supernatural-urban-a: balanced table composition with stronger skyline signal.
        altA: "/editorial-live/generated-20260406-supernatural-urban/supernatural-urban-a.png",
        // supernatural-urban-b: envelope-forward variant for evidence-driven scenes.
        altB: "/editorial-live/generated-20260406-supernatural-urban/supernatural-urban-b.png",
        // supernatural-urban-d: cleaner desk-focused variant for calmer beats.
        altC: "/editorial-live/generated-20260406-supernatural-urban/supernatural-urban-d.png",
      },
    },
  },
} as const

const FOUNDATION_SKYLINE_ACTIVE = LOCAL_EDITORIAL_VARIANTS.foundation.skyline.variants[LOCAL_EDITORIAL_VARIANTS.foundation.skyline.activeKey]
const FOUNDATION_SKYLINE_ALTERNATES = [
  LOCAL_EDITORIAL_VARIANTS.foundation.skyline.variants.altA,
  LOCAL_EDITORIAL_VARIANTS.foundation.skyline.variants.altB,
  LOCAL_EDITORIAL_VARIANTS.foundation.skyline.variants.altC,
] as const
const FOUNDATION_SKYLINE_CANDIDATES = [FOUNDATION_SKYLINE_ACTIVE, ...FOUNDATION_SKYLINE_ALTERNATES] as const
const OFFICE_BOARDROOM_ACTIVE = LOCAL_EDITORIAL_VARIANTS.office.boardroom.variants[LOCAL_EDITORIAL_VARIANTS.office.boardroom.activeKey]
const OFFICE_BOARDROOM_ALTERNATES = [
  LOCAL_EDITORIAL_VARIANTS.office.boardroom.variants.altA,
  LOCAL_EDITORIAL_VARIANTS.office.boardroom.variants.altB,
  LOCAL_EDITORIAL_VARIANTS.office.boardroom.variants.darkVariant,
] as const
const OFFICE_BOARDROOM_CANDIDATES = [OFFICE_BOARDROOM_ACTIVE, ...OFFICE_BOARDROOM_ALTERNATES] as const
const SUPERNATURAL_URBAN_ACTIVE = LOCAL_EDITORIAL_VARIANTS.supernatural.urbanNight.variants[LOCAL_EDITORIAL_VARIANTS.supernatural.urbanNight.activeKey]
const SUPERNATURAL_URBAN_ALTERNATES = [
  LOCAL_EDITORIAL_VARIANTS.supernatural.urbanNight.variants.altA,
  LOCAL_EDITORIAL_VARIANTS.supernatural.urbanNight.variants.altB,
  LOCAL_EDITORIAL_VARIANTS.supernatural.urbanNight.variants.altC,
] as const
const SUPERNATURAL_URBAN_CANDIDATES = [SUPERNATURAL_URBAN_ACTIVE, ...SUPERNATURAL_URBAN_ALTERNATES] as const

export const EDITORIAL_IMAGES = {
  remote: REMOTE_EDITORIAL_IMAGES,
  scenes: {
    heroSkyline: FOUNDATION_SKYLINE_ACTIVE,
    heroRedCarpet: REMOTE_EDITORIAL_IMAGES.heroRedCarpet,
    sceneRedCarpetArrival: REMOTE_EDITORIAL_IMAGES.sceneRedCarpetArrival,
    sceneRedCarpetPress: REMOTE_EDITORIAL_IMAGES.sceneRedCarpetPress,
    sceneRedCarpetCrowd: REMOTE_EDITORIAL_IMAGES.sceneRedCarpetCrowd,
    heroPenthouse: REMOTE_EDITORIAL_IMAGES.heroPenthouse,
    sceneBoardroom: OFFICE_BOARDROOM_ACTIVE,
    sceneChampagne: REMOTE_EDITORIAL_IMAGES.sceneChampagne,
    sceneRain: SUPERNATURAL_URBAN_ALTERNATES[0],
    sceneCampus: REMOTE_EDITORIAL_IMAGES.sceneCampus,
    sceneCampusArcade: REMOTE_EDITORIAL_IMAGES.sceneCampusArcade,
    sceneCampusCourtyard: REMOTE_EDITORIAL_IMAGES.sceneCampusCourtyard,
    sceneCampusEvidence: REMOTE_EDITORIAL_IMAGES.sceneCampusEvidence,
    sceneStillLife: SUPERNATURAL_URBAN_ACTIVE,
  },
  portraits: {
    woman: REMOTE_EDITORIAL_IMAGES.charWoman,
    man: REMOTE_EDITORIAL_IMAGES.charMan,
    silhouette: REMOTE_EDITORIAL_IMAGES.charSilhouette,
  },
  office: {
    boardroom: {
      activeKey: LOCAL_EDITORIAL_VARIANTS.office.boardroom.activeKey,
      active: OFFICE_BOARDROOM_ACTIVE,
      alternates: OFFICE_BOARDROOM_ALTERNATES,
      variants: LOCAL_EDITORIAL_VARIANTS.office.boardroom.variants,
    },
  },
  supernatural: {
    urbanNight: {
      activeKey: LOCAL_EDITORIAL_VARIANTS.supernatural.urbanNight.activeKey,
      active: SUPERNATURAL_URBAN_ACTIVE,
      alternates: SUPERNATURAL_URBAN_ALTERNATES,
      variants: LOCAL_EDITORIAL_VARIANTS.supernatural.urbanNight.variants,
    },
  },
  foundation: {
    skyline: {
      activeKey: LOCAL_EDITORIAL_VARIANTS.foundation.skyline.activeKey,
      active: FOUNDATION_SKYLINE_ACTIVE,
      alternates: FOUNDATION_SKYLINE_ALTERNATES,
      variants: LOCAL_EDITORIAL_VARIANTS.foundation.skyline.variants,
    },
  },
} as const

export type EditorialHeroSlide = {
  id: string
  title: string
  subtitle: string
  description: string
  image: string
  badges: string[]
}

const FALLBACK_HEROES: EditorialHeroSlide[] = [
  {
    id: "landing-wealth",
    title: "权力的餐桌",
    subtitle: "豪门、继承、站队、旧爱回潮",
    description: "当所有人都装作只是在赴宴，真正危险的事往往已经上桌了。",
    image: EDITORIAL_IMAGES.scenes.heroPenthouse,
    badges: ["公开案卷", "高压关系戏", "多角色拉扯"],
  },
  {
    id: "landing-office",
    title: "午夜董事会",
    subtitle: "并购、黑账、暧昧和公开后果",
    description: "最体面的会议室，最适合让关系和筹码一起失控。",
    image: EDITORIAL_IMAGES.office.boardroom.active,
    badges: ["董事会修罗场", "公开试探", "风暴回流"],
  },
  {
    id: "landing-heat",
    title: "红毯陷阱",
    subtitle: "热搜、偷拍、绯闻与公关角力",
    description: "镜头不是记录者，它会把每个人都逼成表演者。",
    image: EDITORIAL_IMAGES.scenes.heroRedCarpet,
    badges: ["热搜失控", "场面优先", "高传播性"],
  },
]

function normalizeTheme(theme?: string | null) {
  const value = (theme ?? "").toLowerCase()
  if (value.includes("office") || value.includes("董事") || value.includes("并购")) {
    return "office"
  }
  if (value.includes("wealth") || value.includes("豪门") || value.includes("继承")) {
    return "wealth"
  }
  if (value.includes("entertainment") || value.includes("热搜") || value.includes("娱乐")) {
    return "entertainment"
  }
  if (value.includes("campus") || value.includes("校园")) {
    return "campus"
  }
  if (value.includes("supernatural") || value.includes("契约") || value.includes("夜色")) {
    return "supernatural"
  }
  return "default"
}

const THEME_IMAGE_SETS: Record<string, readonly string[]> = {
  office: OFFICE_BOARDROOM_CANDIDATES,
  wealth: [EDITORIAL_IMAGES.scenes.heroPenthouse, EDITORIAL_IMAGES.scenes.heroSkyline, EDITORIAL_IMAGES.scenes.sceneChampagne],
  entertainment: [
    EDITORIAL_IMAGES.scenes.heroRedCarpet,
    EDITORIAL_IMAGES.scenes.sceneRedCarpetArrival,
    EDITORIAL_IMAGES.scenes.sceneRedCarpetPress,
  ],
  campus: [
    EDITORIAL_IMAGES.scenes.sceneCampus,
    EDITORIAL_IMAGES.scenes.sceneCampusArcade,
    EDITORIAL_IMAGES.scenes.sceneCampusCourtyard,
    EDITORIAL_IMAGES.scenes.sceneCampusEvidence,
  ],
  supernatural: SUPERNATURAL_URBAN_CANDIDATES,
  default: [FOUNDATION_SKYLINE_CANDIDATES[0], EDITORIAL_IMAGES.scenes.heroPenthouse, EDITORIAL_IMAGES.office.boardroom.active],
}

export function getEditorialThemeImage(theme?: string | null, offset = 0) {
  const key = normalizeTheme(theme)
  const set = THEME_IMAGE_SETS[key] ?? THEME_IMAGE_SETS.default
  return set[offset % set.length]
}

export function getEditorialCharacterImage(index: number) {
  const roster = [EDITORIAL_IMAGES.portraits.woman, EDITORIAL_IMAGES.portraits.man, EDITORIAL_IMAGES.portraits.silhouette]
  return roster[index % roster.length]
}

export function buildLandingHeroSlides(stories: PublishedStoryCard[]): EditorialHeroSlide[] {
  if (stories.length === 0) {
    return FALLBACK_HEROES
  }

  return stories.slice(0, 3).map((story, index) => ({
    id: story.story_id,
    title: story.title,
    subtitle: story.one_liner,
    description: story.premise,
    image: getEditorialThemeImage(story.theme, index),
    badges: [
      story.theme,
      `${story.npc_count} 人`,
      `${story.beat_count} 幕`,
    ],
  }))
}

export function getEditorialBackdropByView(view: "landing" | "auth" | "create" | "loading" | "library" | "detail" | "play", theme?: string | null) {
  if (view === "auth") {
    return EDITORIAL_IMAGES.scenes.heroPenthouse
  }
  if (view === "create") {
    return EDITORIAL_IMAGES.scenes.heroSkyline
  }
  if (view === "loading") {
    return EDITORIAL_IMAGES.scenes.sceneStillLife
  }
  if (view === "library") {
    return EDITORIAL_IMAGES.scenes.heroSkyline
  }
  return getEditorialThemeImage(theme)
}
