export type LandingVisualTone = "hero" | "scandal" | "boardroom" | "evidence" | "corridor"

export type LandingVisualCandidate = {
  id: string
  title: string
  eyebrow: string
  note: string
  futureAssetName: string
  tone: LandingVisualTone
  asset?: string | null
}

export const LANDING_VISUAL_SLOTS = {
  hero: [
    {
      id: "hero-a",
      title: "午夜宴会厅",
      eyebrow: "Hero Slot A",
      note: "首屏门面图，建议保留左侧大面积标题留白。",
      futureAssetName: "landing-hero-a.jpg",
      tone: "hero",
      asset: null,
    },
    {
      id: "hero-b",
      title: "雨夜顶层",
      eyebrow: "Hero Slot B",
      note: "更适合做黑金、酒红、落地窗天际线方向。",
      futureAssetName: "landing-hero-b.jpg",
      tone: "hero",
      asset: null,
    },
    {
      id: "hero-c",
      title: "失控前一秒",
      eyebrow: "Hero Slot C",
      note: "可以更近一点，强调桌面证物和模糊人影的压迫感。",
      futureAssetName: "landing-hero-c.jpg",
      tone: "hero",
      asset: null,
    },
  ],
  scandal: [
    {
      id: "scandal-a",
      title: "闪光灯门口",
      eyebrow: "Public Slot A",
      note: "适合热搜、偷拍、保镖、车门、围观人群的公开失控感。",
      futureAssetName: "landing-scandal-a.jpg",
      tone: "scandal",
      asset: null,
    },
    {
      id: "scandal-b",
      title: "红毯侧拍",
      eyebrow: "Public Slot B",
      note: "更偏娱乐圈壳子，适合做镜头外的暧昧危险。",
      futureAssetName: "landing-scandal-b.jpg",
      tone: "scandal",
      asset: null,
    },
    {
      id: "scandal-c",
      title: "酒店出入口",
      eyebrow: "Public Slot C",
      note: "更适合做“被拍到之前”的悬停瞬间。",
      futureAssetName: "landing-scandal-c.jpg",
      tone: "scandal",
      asset: null,
    },
  ],
  boardroom: [
    {
      id: "boardroom-a",
      title: "冷光会议室",
      eyebrow: "Power Slot A",
      note: "适合董事会、并购、黑账、签字前沉默对峙。",
      futureAssetName: "landing-boardroom-a.jpg",
      tone: "boardroom",
      asset: null,
    },
    {
      id: "boardroom-b",
      title: "深夜玻璃墙",
      eyebrow: "Power Slot B",
      note: "更强调雨夜反光和权力边界模糊的压迫气氛。",
      futureAssetName: "landing-boardroom-b.jpg",
      tone: "boardroom",
      asset: null,
    },
    {
      id: "boardroom-c",
      title: "文件落桌",
      eyebrow: "Power Slot C",
      note: "可以偏静物，让权力压力从桌面细节溢出来。",
      futureAssetName: "landing-boardroom-c.jpg",
      tone: "boardroom",
      asset: null,
    },
  ],
  evidence: [
    {
      id: "evidence-a",
      title: "酒杯与请柬",
      eyebrow: "Evidence Slot A",
      note: "适合作为 still-life 证物图，突出奢华与危险共存。",
      futureAssetName: "landing-evidence-a.jpg",
      tone: "evidence",
      asset: null,
    },
    {
      id: "evidence-b",
      title: "录音笔与合同",
      eyebrow: "Evidence Slot B",
      note: "适合做更强的信息密度和‘翻供前夜’质感。",
      futureAssetName: "landing-evidence-b.jpg",
      tone: "evidence",
      asset: null,
    },
    {
      id: "evidence-c",
      title: "亮屏手机",
      eyebrow: "Evidence Slot C",
      note: "适合做讯息刚弹出的瞬间，强调传播性和爆点。",
      futureAssetName: "landing-evidence-c.jpg",
      tone: "evidence",
      asset: null,
    },
  ],
  corridor: [
    {
      id: "corridor-a",
      title: "无人走廊",
      eyebrow: "Shadow Slot A",
      note: "适合做过渡镜位，突出风声先到、人还没到场。",
      futureAssetName: "landing-corridor-a.jpg",
      tone: "corridor",
      asset: null,
    },
    {
      id: "corridor-b",
      title: "门缝暗影",
      eyebrow: "Shadow Slot B",
      note: "更适合做暧昧、窃听、偷看、临界停顿的氛围。",
      futureAssetName: "landing-corridor-b.jpg",
      tone: "corridor",
      asset: null,
    },
  ],
} as const
