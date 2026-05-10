import React from "react"
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion"

const captures = {
  reviewer: "captures/01-reviewer-entry.png",
  create: "captures/02-create-seed-filled.png",
  createTyping: "captures/02-create-real-typing.mp4",
  runtime: "captures/03-play-runtime-top.png",
  options: "captures/04-play-options-bottom.png",
  advisor: "captures/05-advisor-open.png",
  ending: "captures/06-ending-proof.png",
  portfolio: "captures/07-portfolio-case-study.png",
}

const keyframes = {
  hook: "keyframes/01-wedding-hook.jpg",
  engine: "keyframes/02-story-engine.jpg",
  choice: "keyframes/03-choice-moment.jpg",
  reveal: "keyframes/04-evidence-reveal.jpg",
  ending: "keyframes/05-ending-share.jpg",
  system: "keyframes/06-system-showcase.jpg",
  build: "keyframes/07-build-compiler.jpg",
  advisor: "keyframes/08-advisor-boundary.jpg",
  portfolio: "keyframes/09-portfolio-dawn.jpg",
}

const overlays = {
  titleRibbon: "overlays/title-ribbon-alpha.png",
  evidencePanel: "overlays/evidence-panel-alpha.png",
}

export const admissionsDemoFrames = 2250
const scenes = {
  coldOpen: [0, 190],
  input: [190, 450],
  build: [450, 690],
  runtime: [690, 970],
  choices: [970, 1235],
  freeform: [1235, 1490],
  advisor: [1490, 1760],
  ending: [1760, 2025],
  reflection: [2025, admissionsDemoFrames],
} as const

function clampInterpolate(frame: number, range: [number, number], output: [number, number]) {
  return interpolate(frame, range, output, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  })
}

function sceneOpacity(start: number, end: number) {
  const frame = useCurrentFrame()
  const a = clampInterpolate(frame, [start, start + 24], [0, 1])
  const b = clampInterpolate(frame, [end - 24, end], [1, 0])
  return Math.min(a, b)
}

const Scene: React.FC<{
  range: readonly [number, number]
  children: React.ReactNode
}> = ({range, children}) => {
  const frame = useCurrentFrame()
  if (frame < range[0] || frame >= range[1]) return null
  return <>{children}</>
}

const ArtBackground: React.FC<{
  src: string
  start: number
  end: number
  tint?: "red" | "blue" | "gold"
  dim?: number
}> = ({src, start, end, tint = "blue", dim = .72}) => {
  const frame = useCurrentFrame()
  const progress = clampInterpolate(frame, [start, end], [0, 1])
  const opacity = sceneOpacity(start, end)
  const tintColor =
    tint === "red" ? "rgba(168, 24, 50, .28)" : tint === "gold" ? "rgba(213, 171, 82, .20)" : "rgba(38, 138, 170, .20)"
  return (
    <AbsoluteFill style={{opacity, background: "#050506", overflow: "hidden"}}>
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${1.05 + progress * 0.055}) translateX(${interpolate(progress, [0, 1], [-18, 18])}px)`,
          filter: "contrast(1.08) saturate(1.05)",
        }}
      />
      <AbsoluteFill
        style={{
          background: `linear-gradient(90deg, rgba(2,4,8,${dim}), rgba(2,4,8,.16) 48%, rgba(2,4,8,${Math.max(.46, dim - .12)})), radial-gradient(circle at 72% 34%, ${tintColor}, transparent 40%)`,
        }}
      />
      <AbsoluteFill style={{boxShadow: "inset 0 0 138px rgba(0,0,0,.70)"}} />
    </AbsoluteFill>
  )
}

const ScreenFrame: React.FC<{
  src: string
  start: number
  end: number
  x?: number
  y?: number
  width?: number
  scaleFrom?: number
  scaleTo?: number
  crop?: React.CSSProperties
}> = ({src, start, end, x = 170, y = 118, width = 1380, scaleFrom = .98, scaleTo = 1.02, crop}) => {
  const frame = useCurrentFrame()
  const local = Math.max(0, frame - start)
  const {fps: videoFps} = useVideoConfig()
  const enter = spring({
    frame: local,
    fps: videoFps,
    config: {damping: 22, stiffness: 70, mass: .9},
  })
  const progress = clampInterpolate(frame, [start, end], [0, 1])
  const opacity = sceneOpacity(start, end)
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        height: width * 9 / 16,
        overflow: "hidden",
        borderRadius: 24,
        border: "1px solid rgba(255,255,255,.24)",
        boxShadow: "0 34px 120px rgba(0,0,0,.56), 0 0 0 1px rgba(255,255,255,.08) inset, 0 0 54px rgba(142,232,255,.10)",
        opacity,
        transform: `translateY(${interpolate(enter, [0, 1], [34, 0])}px) scale(${scaleFrom + (scaleTo - scaleFrom) * progress})`,
        background: "#08090d",
      }}
    >
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          filter: "brightness(1.2) contrast(1.08) saturate(1.08)",
          ...crop,
        }}
      />
    </div>
  )
}

const ScreenVideo: React.FC<{
  src: string
  start: number
  end: number
  x?: number
  y?: number
  width?: number
  scaleFrom?: number
  scaleTo?: number
}> = ({src, start, end, x = 170, y = 118, width = 1380, scaleFrom = .98, scaleTo = 1.02}) => {
  const frame = useCurrentFrame()
  const local = Math.max(0, frame - start)
  const {fps: videoFps} = useVideoConfig()
  const enter = spring({
    frame: local,
    fps: videoFps,
    config: {damping: 22, stiffness: 70, mass: .9},
  })
  const progress = clampInterpolate(frame, [start, end], [0, 1])
  const opacity = sceneOpacity(start, end)
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        height: width * 9 / 16,
        overflow: "hidden",
        borderRadius: 24,
        border: "1px solid rgba(255,255,255,.24)",
        boxShadow: "0 34px 120px rgba(0,0,0,.56), 0 0 0 1px rgba(255,255,255,.08) inset, 0 0 54px rgba(142,232,255,.10)",
        opacity,
        transform: `translateY(${interpolate(enter, [0, 1], [34, 0])}px) scale(${scaleFrom + (scaleTo - scaleFrom) * progress})`,
        background: "#08090d",
      }}
    >
      <Sequence from={start} durationInFrames={end - start} layout="none">
        <OffthreadVideo
          src={staticFile(src)}
          muted
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            filter: "brightness(1.2) contrast(1.08) saturate(1.08)",
          }}
        />
      </Sequence>
    </div>
  )
}

const Label: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
  <div
    style={{
      color: "#d7ad50",
      fontSize: 22,
      fontWeight: 800,
      letterSpacing: 2.6,
      textTransform: "uppercase",
      ...style,
    }}
  >
    {children}
  </div>
)

const Headline: React.FC<{children: React.ReactNode; size?: number; style?: React.CSSProperties}> = ({
  children,
  size = 72,
  style,
}) => (
  <div
    style={{
      marginTop: 22,
      color: "#fbf5ea",
      fontSize: size,
      lineHeight: 1.02,
      fontWeight: 780,
      letterSpacing: 0,
      maxWidth: 950,
      textShadow: "0 20px 54px rgba(0,0,0,.58)",
      ...style,
    }}
  >
    {children}
  </div>
)

const Body: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
  <div
    style={{
      marginTop: 24,
      color: "rgba(245,239,229,.82)",
      fontSize: 30,
      lineHeight: 1.34,
      maxWidth: 850,
      ...style,
    }}
  >
    {children}
  </div>
)

const CopyBlock: React.FC<{
  start: number
  label: string
  title: React.ReactNode
  body?: React.ReactNode
  x?: number
  y?: number
  size?: number
  maxWidth?: number
  matte?: boolean
}> = ({start, label, title, body, x = 108, y = 122, size, maxWidth = 950, matte = true}) => {
  const frame = useCurrentFrame()
  const local = Math.max(0, frame - start)
  const {fps: videoFps} = useVideoConfig()
  const enter = spring({frame: local, fps: videoFps, config: {damping: 20, stiffness: 78}})
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`,
        padding: matte ? "26px 34px 30px" : undefined,
      }}
    >
      {matte ? (
        <Img
          src={staticFile(overlays.titleRibbon)}
          style={{
            position: "absolute",
            left: -54,
            top: -74,
            width: maxWidth + 240,
            height: body ? 342 : 236,
            objectFit: "fill",
            opacity: .86,
            filter: "drop-shadow(0 30px 80px rgba(0,0,0,.42))",
            pointerEvents: "none",
          }}
        />
      ) : null}
      <div style={{position: "relative"}}>
        <Label style={{fontSize: 17, letterSpacing: 2.2}}>{label}</Label>
        <Headline size={size} style={{maxWidth}}>{title}</Headline>
        {body ? <Body style={{maxWidth: Math.max(320, maxWidth - 80), fontSize: 25}}>{body}</Body> : null}
      </div>
    </div>
  )
}

const ProofChip: React.FC<{children: React.ReactNode; delay: number; tone?: "blue" | "gold" | "red"}> = ({
  children,
  delay,
  tone = "blue",
}) => {
  const frame = useCurrentFrame()
  const local = frame - delay
  const color = tone === "gold" ? "#d7ad50" : tone === "red" ? "#ff5d72" : "#8ee8ff"
  const opacity = clampInterpolate(local, [0, 18], [0, 1])
  return (
    <div
      style={{
        position: "relative",
        padding: "13px 18px 13px 22px",
        borderLeft: `3px solid ${color}`,
        background: `linear-gradient(90deg, ${color}22, rgba(6,8,13,.26) 72%, transparent)`,
        color: "#fbf5ea",
        fontSize: 22,
        fontWeight: 760,
        textShadow: "0 8px 24px rgba(0,0,0,.62)",
        opacity,
        transform: `translateY(${clampInterpolate(local, [0, 18], [22, 0])}px)`,
      }}
    >
      {children}
    </div>
  )
}

const ProgressRibbon: React.FC = () => {
  const frame = useCurrentFrame()
  const steps = ["Input", "Compile", "State", "Play", "Advisor", "Ending"]
  const active =
    frame < scenes.build[0] ? 0 :
    frame < scenes.runtime[0] ? 1 :
    frame < scenes.choices[0] ? 2 :
    frame < scenes.advisor[0] ? 3 :
    frame < scenes.ending[0] ? 4 : 5
  return (
    <div
      style={{
        position: "absolute",
        top: 32,
        left: 112,
        right: 112,
        display: "flex",
        alignItems: "center",
        gap: 10,
        opacity: frame < 140 ? clampInterpolate(frame, [80, 140], [0, 1]) : 1,
      }}
    >
      {steps.map((s, i) => (
        <React.Fragment key={s}>
          <div
            style={{
              padding: "9px 14px",
              borderRadius: 999,
              border: "1px solid rgba(255,255,255,.14)",
              background: i <= active ? "rgba(215,173,80,.16)" : "rgba(255,255,255,.05)",
              color: i <= active ? "#ffe1a0" : "rgba(245,239,229,.46)",
              fontSize: 18,
              fontWeight: 750,
              letterSpacing: .3,
            }}
          >
            {s}
          </div>
          {i < steps.length - 1 ? (
            <div style={{height: 1, flex: 1, background: i < active ? "rgba(215,173,80,.55)" : "rgba(255,255,255,.12)"}} />
          ) : null}
        </React.Fragment>
      ))}
    </div>
  )
}

const SystemDiagram: React.FC<{start: number}> = ({start}) => {
  const frame = useCurrentFrame()
  const nodes = ["Seed", "Cast", "Hidden goals", "Runtime state", "First turn"]
  return (
    <div style={{position: "absolute", left: 176, bottom: 120, right: 176, display: "flex", alignItems: "center", gap: 18}}>
      {nodes.map((node, i) => {
        const opacity = clampInterpolate(frame - start - i * 15, [0, 18], [0, 1])
        return (
          <React.Fragment key={node}>
            <div
              style={{
                opacity,
                padding: "22px 26px",
                minWidth: 190,
                textAlign: "center",
                borderRadius: 18,
                background: "rgba(6, 10, 16, .76)",
                border: "1px solid rgba(142,232,255,.26)",
                color: "#f7efe3",
                fontSize: 25,
                fontWeight: 760,
                boxShadow: "0 24px 70px rgba(0,0,0,.45)",
              }}
            >
              {node}
            </div>
            {i < nodes.length - 1 ? (
              <div style={{opacity, color: "#d7ad50", fontSize: 30, fontWeight: 900}}>{"->"}</div>
            ) : null}
          </React.Fragment>
        )
      })}
    </div>
  )
}

const EvidencePanel: React.FC<{
  children: React.ReactNode
  delay: number
  left: number
  top: number
  width: number
  tone?: "blue" | "gold" | "red"
}> = ({children, delay, left, top, width, tone = "blue"}) => {
  const frame = useCurrentFrame()
  const local = frame - delay
  const color = tone === "gold" ? "#d7ad50" : tone === "red" ? "#ff5d72" : "#8ee8ff"
  const opacity = clampInterpolate(local, [0, 18], [0, 1])
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width,
        padding: "28px 32px 30px",
        color: "#fff6e8",
        opacity,
        transform: `translateY(${clampInterpolate(local, [0, 18], [22, 0])}px)`,
        filter: `drop-shadow(0 34px 90px rgba(0,0,0,.50)) drop-shadow(0 0 34px ${color}24)`,
      }}
    >
      <Img
        src={staticFile(overlays.evidencePanel)}
        style={{
          position: "absolute",
          left: -56,
          top: -62,
          width: width + 118,
          height: "calc(100% + 124px)",
          objectFit: "fill",
          opacity: .88,
          pointerEvents: "none",
        }}
      />
      <div style={{position: "relative"}}>{children}</div>
    </div>
  )
}

const PanelTitle: React.FC<{label: string; title: string; tone?: "blue" | "gold" | "red"}> = ({
  label,
  title,
  tone = "blue",
}) => {
  const color = tone === "gold" ? "#d7ad50" : tone === "red" ? "#ff5d72" : "#8ee8ff"
  return (
    <>
      <div style={{color, fontSize: 17, fontWeight: 820, letterSpacing: 1.8, textTransform: "uppercase"}}>{label}</div>
      <div style={{marginTop: 8, color: "#fff8ea", fontSize: 27, lineHeight: 1.08, fontWeight: 820}}>{title}</div>
    </>
  )
}

const ArchitectureFlow: React.FC<{start: number}> = ({start}) => {
  const frame = useCurrentFrame()
  const nodes = [
    {name: "React UI", detail: "frontend2/src/pages/play"},
    {name: "Route map", detail: "frontend2/src/api/route-map.ts"},
    {name: "FastAPI routes", detail: "rpg_backend/main.py"},
    {name: "Service + engine", detail: "narrative/service.py"},
    {name: "SQLite state", detail: "narrative/repository.py"},
  ]
  return (
    <div style={{display: "grid", gap: 10, marginTop: 20}}>
      {nodes.map((node, i) => {
        const opacity = clampInterpolate(frame - start - i * 10, [0, 16], [0, 1])
        return (
          <div key={node.name} style={{display: "flex", alignItems: "center", gap: 12, opacity}}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 17,
                display: "grid",
                placeItems: "center",
                background: "rgba(142,232,255,.16)",
                border: "1px solid rgba(142,232,255,.44)",
                color: "#8ee8ff",
                fontSize: 17,
                fontWeight: 850,
              }}
            >
              {i + 1}
            </div>
            <div style={{flex: 1}}>
              <div style={{fontSize: 24, fontWeight: 800, color: "#fff6e8"}}>{node.name}</div>
              <div style={{fontSize: 17, color: "rgba(245,239,229,.62)", marginTop: 2}}>{node.detail}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

const CodePanel: React.FC<{
  delay: number
  left: number
  top: number
  width: number
  title: string
  rows: string[]
  tone?: "blue" | "gold" | "red"
}> = ({delay, left, top, width, title, rows, tone = "blue"}) => (
  <EvidencePanel delay={delay} left={left} top={top} width={width} tone={tone}>
    <PanelTitle label="runtime evidence" title={title} tone={tone} />
    <div
      style={{
        marginTop: 16,
        padding: "12px 0 0 18px",
        borderLeft: "1px solid rgba(255,255,255,.18)",
        background: "linear-gradient(90deg, rgba(255,255,255,.055), transparent 70%)",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        fontSize: 17,
        lineHeight: 1.38,
        color: "rgba(248,246,240,.88)",
      }}
    >
      {rows.map((row) => (
        <div key={row} style={{whiteSpace: "pre"}}>{row}</div>
      ))}
    </div>
  </EvidencePanel>
)

const StateDiffPanel: React.FC<{delay: number; left: number; top: number}> = ({delay, left, top}) => {
  const rows = [
    ["turn", "2", "3"],
    ["stage", "setup", "confrontation"],
    ["inventory", "phone", "recording"],
    ["leverage", "unclear", "clause proof"],
  ]
  return (
    <EvidencePanel delay={delay} left={left} top={top} width={560} tone="gold">
      <PanelTitle label="state transition" title="Choice mutates the next turn" tone="gold" />
      <div style={{display: "grid", gridTemplateColumns: "1.1fr .9fr .9fr", gap: 8, marginTop: 18, fontSize: 17}}>
        <div style={{color: "rgba(245,239,229,.56)", fontWeight: 760}}>field</div>
        <div style={{color: "rgba(245,239,229,.56)", fontWeight: 760}}>before</div>
        <div style={{color: "#d7ad50", fontWeight: 850}}>after</div>
        {rows.map(([field, before, after]) => (
          <React.Fragment key={field}>
            <div style={{padding: "10px 0", color: "#fff6e8", fontWeight: 780}}>{field}</div>
            <div style={{padding: "10px 0", color: "rgba(245,239,229,.66)"}}>{before}</div>
            <div style={{padding: "10px 0", color: "#ffe1a0", fontWeight: 760}}>{after}</div>
          </React.Fragment>
        ))}
      </div>
    </EvidencePanel>
  )
}

const OwnershipGrid: React.FC<{start: number}> = ({start}) => {
  const frame = useCurrentFrame()
  const items = [
    "React game UI",
    "FastAPI runtime",
    "LLM state compiler",
    "Advisor side-channel",
    "Ending replay artifact",
    "High-DPR demo capture",
  ]
  return (
    <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 22}}>
      {items.map((item, i) => {
        const opacity = clampInterpolate(frame - start - i * 8, [0, 14], [0, 1])
        return (
          <div
            key={item}
            style={{
              opacity,
              padding: "13px 15px",
              borderLeft: "2px solid rgba(215,173,80,.70)",
              background: "linear-gradient(90deg, rgba(215,173,80,.14), rgba(255,255,255,.035))",
              color: "#fff7e9",
              fontSize: 20,
              fontWeight: 760,
            }}
          >
            {item}
          </div>
        )
      })}
    </div>
  )
}

const CropCallout: React.FC<{
  children: React.ReactNode
  left: number
  top: number
  delay: number
  tone?: "blue" | "gold" | "red"
}> = ({children, left, top, delay, tone = "gold"}) => {
  const frame = useCurrentFrame()
  const local = frame - delay
  const color = tone === "red" ? "#ff5d72" : tone === "blue" ? "#8ee8ff" : "#d7ad50"
  const opacity = clampInterpolate(local, [0, 18], [0, 1])
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        padding: "12px 18px",
        borderLeft: `3px solid ${color}`,
        background: `linear-gradient(90deg, ${color}26, rgba(5,7,12,.30), transparent)`,
        color: "#fff8ed",
        fontSize: 22,
        fontWeight: 760,
        opacity,
        transform: `translateY(${clampInterpolate(local, [0, 18], [18, 0])}px)`,
        boxShadow: `0 0 34px ${color}28`,
      }}
    >
      {children}
    </div>
  )
}

const ColdOpen: React.FC = () => {
  const [start, end] = scenes.coldOpen
  return (
    <>
      <ArtBackground src={keyframes.system} start={start} end={end} tint="blue" dim={.64} />
      <CopyBlock
        start={22}
        label="Admissions Demo"
        title={<>One seed becomes a playable AI drama system.</>}
        body="A real UI drives a backend runtime: structured state, constrained LLM turns, advisor context, and a compiled ending artifact."
        size={68}
      />
      <ScreenFrame src={captures.reviewer} start={44} end={end} x={1010} y={512} width={760} scaleFrom={.98} scaleTo={1.018} />
      <div style={{position: "absolute", left: 108, bottom: 88, display: "grid", gap: 10, width: 520}}>
        <ProofChip delay={70}>React UI + API runtime</ProofChip>
        <ProofChip delay={90} tone="gold">Schema-validated generation</ProofChip>
        <ProofChip delay={110} tone="red">Replayable state machine</ProofChip>
      </div>
    </>
  )
}

const InputScene: React.FC = () => {
  const [start, end] = scenes.input
  return (
    <>
      <ArtBackground src={keyframes.hook} start={start} end={end} tint="gold" />
      <ScreenVideo src={captures.createTyping} start={start + 8} end={end} x={132} y={92} width={1600} scaleFrom={1} scaleTo={1.012} />
      <CropCallout left={118} top={850} delay={start + 142} tone="gold">One dramatic premise enters the real UI.</CropCallout>
    </>
  )
}

const BuildScene: React.FC = () => {
  const [start, end] = scenes.build
  return (
    <>
      <ArtBackground src={keyframes.build} start={start} end={end} tint="blue" dim={.58} />
      <CopyBlock
        start={start + 24}
        label="Build Phase"
        title="The backend compiles story into runnable state."
        body="The demo is not a free chat box: every generated turn is shaped into a state object the UI can replay and inspect."
        size={58}
      />
      <EvidencePanel delay={start + 78} left={106} top={555} width={560} tone="blue">
        <PanelTitle label="full-stack path" title="UI to runtime to replay" />
        <ArchitectureFlow start={start + 98} />
      </EvidencePanel>
      <CodePanel
        delay={start + 110}
        left={1090}
        top={202}
        width={610}
        title="Generated output is parsed before play"
        rows={[
          "POST /narrative/templates/:id/sessions",
          "GET  /narrative/sessions/:id/story",
          "POST /narrative/sessions/:id/story/turns",
          "StoryHistoryResponse -> React render",
          "AdvanceTurnResponse -> persisted turn",
        ]}
      />
    </>
  )
}

const RuntimeScene: React.FC = () => {
  const [start, end] = scenes.runtime
  return (
    <>
      <ArtBackground src={keyframes.reveal} start={start} end={end} tint="blue" dim={.70} />
      <ScreenFrame src={captures.runtime} start={start + 8} end={end} x={74} y={86} width={1160} scaleFrom={1} scaleTo={1.025} />
      <StateDiffPanel delay={start + 58} left={1260} top={166} />
      <CodePanel
        delay={start + 98}
        left={1260}
        top={610}
        width={548}
        title="Inspector proves state is real"
        tone="blue"
        rows={[
          "route-map.ts:getNarrativeStory",
          "main.py:get_narrative_story",
          "service.py:get_story_history",
          "repository.py:list_story_messages",
        ]}
      />
    </>
  )
}

const ChoiceScene: React.FC = () => {
  const [start, end] = scenes.choices
  return (
    <>
      <ArtBackground src={keyframes.choice} start={start} end={end} tint="red" dim={.64} />
      <ScreenFrame src={captures.options} start={start + 8} end={end} x={720} y={148} width={1060} scaleFrom={1.0} scaleTo={1.018} />
      <CopyBlock
        start={start + 38}
        label="Play Loop"
        title="A player choice feeds the next state transition."
        body="The interface keeps the action readable, then the runtime locks it into the run history before generating the next beat."
        x={96}
        y={124}
        size={44}
        maxWidth={560}
      />
      <div style={{position: "absolute", left: 96, bottom: 108, display: "grid", gap: 12, width: 560}}>
        <ProofChip delay={start + 96} tone="blue">selected_action_id persisted</ProofChip>
        <ProofChip delay={start + 116} tone="gold">turn_count increments</ProofChip>
        <ProofChip delay={start + 136} tone="red">next choices regenerated from state</ProofChip>
      </div>
    </>
  )
}

const FreeformScene: React.FC = () => {
  const [start, end] = scenes.freeform
  const action = "I ask the lawyer to read the clause aloud, then secretly record his answer."
  return (
    <>
      <ArtBackground src={keyframes.system} start={start} end={end} tint="gold" dim={.60} />
      <ScreenFrame src={captures.options} start={start + 10} end={end} x={744} y={140} width={1030} scaleFrom={1.0} scaleTo={1.016} />
      <CopyBlock
        start={start + 28}
        label="Open Action"
        title="Structured choices lower friction. Free-form input keeps agency."
        body="This is the product tradeoff: readable options for most players, custom tactics for advanced play."
        x={96}
        y={122}
        size={42}
        maxWidth={590}
      />
      <div
        style={{
          position: "absolute",
          left: 96,
          bottom: 116,
          width: 590,
          padding: "20px 24px 22px",
          borderLeft: "3px solid rgba(215,173,80,.82)",
          background: "linear-gradient(90deg, rgba(215,173,80,.18), rgba(7,9,14,.34), transparent)",
          color: "#fff6e7",
          fontSize: 25,
          lineHeight: 1.35,
          textShadow: "0 10px 32px rgba(0,0,0,.70)",
        }}
      >
        <div style={{color: "#d7ad50", fontSize: 17, fontWeight: 820, letterSpacing: 1.6, textTransform: "uppercase", marginBottom: 10}}>
          advanced tactic example
        </div>
        {action}
      </div>
    </>
  )
}

const AdvisorScene: React.FC = () => {
  const [start, end] = scenes.advisor
  return (
    <>
      <ArtBackground src={keyframes.advisor} start={start} end={end} tint="blue" dim={.54} />
      <ScreenFrame src={captures.advisor} start={start + 8} end={end} x={960} y={154} width={820} scaleFrom={.99} scaleTo={1.016} />
      <CopyBlock
        start={start + 34}
        label="Advisor Channel"
        title="A second LLM surface with bounded authority."
        body="The advisor can read run context and help the player reason, but it cannot choose or mutate the story state."
        x={114}
        y={122}
        size={48}
        maxWidth={690}
      />
      <CodePanel
        delay={start + 94}
        left={116}
        top={536}
        width={610}
        title="Role-separated LLM surface"
        rows={[
          "route-map.ts:askNarrativeAdvisor",
          "main.py:ask_narrative_advisor",
          "service.py:ask_advisor",
          "advisor_messages separate from turns",
        ]}
      />
      <CropCallout left={1058} top={706} delay={start + 130} tone="gold">Player keeps control</CropCallout>
    </>
  )
}

const EndingScene: React.FC = () => {
  const [start, end] = scenes.ending
  return (
    <>
      <ArtBackground src={keyframes.ending} start={start} end={end} tint="red" dim={.64} />
      <ScreenFrame src={captures.ending} start={start + 8} end={end} x={728} y={88} width={1040} scaleFrom={1.004} scaleTo={1.022} />
      <CopyBlock
        start={start + 28}
        label="Ending Compiler"
        title="The result is compiled from the path actually played."
        body="The final screen turns selected turns into a shareable artifact: ending label, highlights, paths not taken, and replay loop."
        x={110}
        y={110}
        size={48}
        maxWidth={620}
      />
      <CodePanel
        delay={start + 94}
        left={110}
        top={526}
        width={560}
        title="Ending uses run history"
        tone="red"
        rows={[
          "GET /narrative/sessions/:id/ending",
          "service.py:get_session_ending",
          "ending_highlights_json",
          "replay page keeps advisor track",
        ]}
      />
    </>
  )
}

const ReflectionScene: React.FC = () => {
  const [start, end] = scenes.reflection
  return (
    <>
      <ArtBackground src={keyframes.portfolio} start={start} end={end} tint="gold" dim={.45} />
      <ScreenFrame src={captures.portfolio} start={start + 8} end={end} x={1040} y={178} width={720} scaleFrom={1} scaleTo={1.012} />
      <CopyBlock
        start={start + 28}
        label="Engineering Reflection"
        title="Built as a full-stack AI product case study."
        body="The demo connects product UX, backend orchestration, LLM constraints, state persistence, and a reviewer-facing proof flow."
        x={108}
        y={150}
        size={54}
        maxWidth={780}
      />
      <EvidencePanel delay={start + 84} left={108} top={492} width={800} tone="gold">
        <PanelTitle label="ownership" title="What this portfolio artifact proves" tone="gold" />
        <OwnershipGrid start={start + 104} />
      </EvidencePanel>
      <div
        style={{
          position: "absolute",
          left: 108,
          bottom: 40,
          color: "rgba(245,239,229,.62)",
          fontSize: 22,
        }}
      >
        Tiny Stories - technical AI product builder portfolio demo
      </div>
    </>
  )
}

export const AdmissionsDemoTrailer: React.FC = () => (
  <AbsoluteFill
    style={{
      background: "#030406",
      fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      overflow: "hidden",
    }}
  >
    <Scene range={scenes.coldOpen}><ColdOpen /></Scene>
    <Scene range={scenes.input}><InputScene /></Scene>
    <Scene range={scenes.build}><BuildScene /></Scene>
    <Scene range={scenes.runtime}><RuntimeScene /></Scene>
    <Scene range={scenes.choices}><ChoiceScene /></Scene>
    <Scene range={scenes.freeform}><FreeformScene /></Scene>
    <Scene range={scenes.advisor}><AdvisorScene /></Scene>
    <Scene range={scenes.ending}><EndingScene /></Scene>
    <Scene range={scenes.reflection}><ReflectionScene /></Scene>
    <ProgressRibbon />
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        height: 6,
        background: "rgba(255,255,255,.08)",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${clampInterpolate(useCurrentFrame(), [0, admissionsDemoFrames], [0, 100])}%`,
          background: "linear-gradient(90deg, #8ee8ff, #d7ad50, #ff5d72)",
        }}
      />
    </div>
  </AbsoluteFill>
)
