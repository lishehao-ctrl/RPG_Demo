export const REVIEWER_DEMO_TITLE = "The Merger Betrayal"

export const REVIEWER_DEMO_SEED =
  "Minutes before the awards livestream, my cofounder announces our secret merger onstage. My ex steps into the control room holding the recording that proves I buried the deal."

export const REVIEWER_DEMO_ACTIONS = [
  "Start from a locked English seed",
  "Inspect the generated cast and player role",
  "Play two or three turns to watch consequences accumulate",
  "Open the advisor sidechat for out-of-band reasoning",
  "Finish on a labeled ending with highlights and alternate branches",
] as const

export const PORTFOLIO_METRICS = [
  { value: "1 seed", label: "from prompt to playable runtime" },
  { value: "12 turns", label: "bounded episode arc for demo reliability" },
  { value: "5 layers", label: "seed, role, state, advisor, ending" },
  { value: "EN first", label: "portfolio-facing path and UI copy" },
] as const

export const PIPELINE_STEPS = [
  {
    eyebrow: "01",
    title: "Seed Router",
    summary: "Classifies setting, conflict, language and story shell before generation starts.",
    proof: "The reviewer seed is deliberately office + entertainment + betrayal, which routes into the existing manhwa-style business scandal asset family.",
  },
  {
    eyebrow: "02",
    title: "Playable Role Model",
    summary: "Turns the protagonist into an operational player identity with public persona, private objective, leverage and starting assets.",
    proof: "This is the piece that makes the project more than story completion: the player has a position to defend, not just text to read.",
  },
  {
    eyebrow: "03",
    title: "Stateful Consequences",
    summary: "Every chosen option or free-form action appends a narrator beat, updates turn state, and preserves inventory / pulse signals.",
    proof: "The runtime inspector exposes the current stage, option count, inventory count and ending state while the run is being played.",
  },
  {
    eyebrow: "04",
    title: "Advisor Channel",
    summary: "A parallel sidechat gives the player an outside reader without taking control away from them.",
    proof: "For portfolio review, this shows a second LLM-mediated surface that is context-aware but role-separated from the narrator.",
  },
  {
    eyebrow: "05",
    title: "Ending Compiler",
    summary: "The run resolves into a labeled ending, a subtitle, highlights, and hypothetical branches.",
    proof: "The final screen converts a free-form playthrough into a shareable artifact and a replay loop.",
  },
] as const

export const CASE_STUDY_POINTS = [
  {
    title: "Problem",
    body: "Most AI story demos feel either like a chatbot or a random text generator. They do not make the player position, system state, or ending logic visible enough to feel designed.",
  },
  {
    title: "Product Thesis",
    body: "Tiny Stories treats generation as a bounded interactive runtime: one strong seed becomes a cast, a role, staged turns, advisor context, and a replayable ending.",
  },
  {
    title: "Engineering Angle",
    body: "The useful portfolio signal is not prompt novelty. It is the product layer around generation: deterministic routing, typed contracts, state recovery, English localization, and verifiable demo flow.",
  },
] as const

export const ASSET_GALLERY = [
  {
    src: "/webtoons/shells/office_power-02.jpg",
    title: "Office power shell",
    note: "Boardroom stakes and corporate betrayal.",
  },
  {
    src: "/webtoons/shells/entertainment_scandal-02.jpg",
    title: "Entertainment shell",
    note: "Awards livestream, public collapse, reputation pressure.",
  },
  {
    src: "/webtoons/segments/reveal.jpg",
    title: "Reveal segment",
    note: "The moment private leverage becomes visible.",
  },
  {
    src: "/webtoons/endings/v2/loner.jpg",
    title: "Lone Wolf ending",
    note: "A clean portfolio-friendly conclusion for the demo path.",
  },
] as const
