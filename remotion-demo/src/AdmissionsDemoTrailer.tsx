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
}

const fps = 30
const scenes = {
  coldOpen: [0, 240],
  input: [240, 520],
  build: [520, 790],
  runtime: [790, 1110],
  choices: [1110, 1410],
  freeform: [1410, 1720],
  advisor: [1720, 2050],
  ending: [2050, 2390],
  reflection: [2390, 2700],
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
}> = ({src, start, end, tint = "blue"}) => {
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
          background: `linear-gradient(90deg, rgba(2,4,8,.90), rgba(2,4,8,.34) 48%, rgba(2,4,8,.82)), radial-gradient(circle at 72% 34%, ${tintColor}, transparent 40%)`,
        }}
      />
      <AbsoluteFill style={{boxShadow: "inset 0 0 190px rgba(0,0,0,.88)"}} />
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
}> = ({start, label, title, body, x = 108, y = 122, size}) => {
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
      }}
    >
      <Label>{label}</Label>
      <Headline size={size}>{title}</Headline>
      {body ? <Body>{body}</Body> : null}
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
        padding: "16px 20px",
        borderRadius: 16,
        border: `1px solid ${color}66`,
        background: "rgba(8, 11, 17, .72)",
        color: "#fbf5ea",
        fontSize: 24,
        fontWeight: 720,
        boxShadow: `0 0 38px ${color}24`,
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
  const steps = ["Seed", "Build", "State", "Play", "Advise", "Ending"]
  const active =
    frame < scenes.input[0] ? 0 :
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
        padding: "14px 18px",
        borderRadius: 14,
        border: `1px solid ${color}88`,
        background: "rgba(5,7,12,.82)",
        color: "#fff8ed",
        fontSize: 23,
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
      <ArtBackground src={keyframes.engine} start={start} end={end} tint="blue" />
      <CopyBlock
        start={22}
        label="Admissions Demo"
        title={<>A playable LLM system, not a prompt demo.</>}
        body="Tiny Stories turns one seed into a stateful drama runtime: roles, hidden objectives, choices, advisor context, and a compiled ending."
        size={76}
      />
      <div style={{position: "absolute", right: 116, bottom: 116, display: "grid", gap: 14, width: 440}}>
        <ProofChip delay={82}>Full-stack prototype</ProofChip>
        <ProofChip delay={104} tone="gold">Structured generation</ProofChip>
        <ProofChip delay={126} tone="red">Stateful play loop</ProofChip>
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
      <CropCallout left={118} top={850} delay={start + 164} tone="gold">One dramatic premise enters the real UI.</CropCallout>
    </>
  )
}

const BuildScene: React.FC = () => {
  const [start, end] = scenes.build
  return (
    <>
      <ArtBackground src={keyframes.engine} start={start} end={end} tint="blue" />
      <CopyBlock
        start={start + 24}
        label="Build Phase"
        title="Generation becomes structured runtime data."
        body="The backend compiles a seed into cast, private goals, leverage, inventory, pressure, and the first playable turn."
        size={66}
      />
      <SystemDiagram start={start + 120} />
    </>
  )
}

const RuntimeScene: React.FC = () => {
  const [start, end] = scenes.runtime
  return (
    <>
      <ArtBackground src={keyframes.reveal} start={start} end={end} tint="blue" />
      <ScreenFrame src={captures.runtime} start={start + 10} end={end} x={88} y={96} width={1660} scaleFrom={1} scaleTo={1.018} />
      <CropCallout left={1018} top={186} delay={start + 70} tone="blue">Reviewer runtime inspector</CropCallout>
      <CropCallout left={1088} top={406} delay={start + 106}>Role, stage, turns, inventory</CropCallout>
      <CropCallout left={392} top={800} delay={start + 138} tone="red">The player has position, motive, and leverage.</CropCallout>
    </>
  )
}

const ChoiceScene: React.FC = () => {
  const [start, end] = scenes.choices
  return (
    <>
      <ArtBackground src={keyframes.choice} start={start} end={end} tint="red" />
      <ScreenFrame src={captures.options} start={start + 8} end={end} x={104} y={110} width={1580} scaleFrom={1.012} scaleTo={1.035} />
      <CopyBlock
        start={start + 38}
        label="Play Loop"
        title="A choice becomes input to the next state transition."
        body="The UI keeps choices readable, then locks the selected action before continuing the story."
        x={116}
        y={118}
        size={54}
      />
      <div style={{position: "absolute", right: 116, bottom: 96, display: "grid", gap: 12, width: 490}}>
        <ProofChip delay={start + 150} tone="blue">Option click</ProofChip>
        <ProofChip delay={start + 174} tone="gold">Narrator beat updates</ProofChip>
        <ProofChip delay={start + 198} tone="red">Next choice appears</ProofChip>
      </div>
    </>
  )
}

const FreeformScene: React.FC = () => {
  const [start, end] = scenes.freeform
  const frame = useCurrentFrame()
  const action = "I ask the lawyer to read the clause aloud, then secretly record his answer."
  const chars = Math.round(clampInterpolate(frame - start - 88, [0, 90], [0, action.length]))
  const blink = Math.floor((frame - start) / 13) % 2 === 0
  return (
    <>
      <ArtBackground src={keyframes.choice} start={start} end={end} tint="gold" />
      <ScreenFrame src={captures.options} start={start + 10} end={end} x={88} y={98} width={1600} scaleFrom={1.02} scaleTo={1.04} />
      <CopyBlock
        start={start + 28}
        label="Open Action"
        title="Structured choices lower friction. Free-form input keeps agency."
        body="This is the product tradeoff: readable options for most players, custom tactics for advanced play."
        x={108}
        y={110}
        size={52}
      />
      <div
        style={{
          position: "absolute",
          left: 396,
          bottom: 110,
          width: 810,
          padding: "26px 30px",
          borderRadius: 20,
          border: "1px solid rgba(215,173,80,.42)",
          background: "rgba(7,9,14,.88)",
          color: "#fff6e7",
          fontSize: 29,
          lineHeight: 1.35,
          boxShadow: "0 28px 90px rgba(0,0,0,.56)",
        }}
      >
        {action.slice(0, chars)}
        <span style={{opacity: blink ? 1 : 0, color: "#d7ad50"}}>|</span>
      </div>
    </>
  )
}

const AdvisorScene: React.FC = () => {
  const [start, end] = scenes.advisor
  return (
    <>
      <ArtBackground src={keyframes.reveal} start={start} end={end} tint="blue" />
      <ScreenFrame src={captures.advisor} start={start + 8} end={end} x={92} y={102} width={1640} scaleFrom={1} scaleTo={1.018} />
      <CopyBlock
        start={start + 34}
        label="Advisor Channel"
        title="A second LLM surface with bounded authority."
        body="The advisor reads run context and helps the player reason, but it does not take over the decision."
        x={114}
        y={122}
        size={54}
      />
      <CropCallout left={1208} top={190} delay={start + 116} tone="blue">Context-aware, role-separated sidechat</CropCallout>
      <CropCallout left={998} top={820} delay={start + 154} tone="gold">Player keeps control</CropCallout>
    </>
  )
}

const EndingScene: React.FC = () => {
  const [start, end] = scenes.ending
  return (
    <>
      <ArtBackground src={keyframes.ending} start={start} end={end} tint="red" />
      <ScreenFrame src={captures.ending} start={start + 8} end={end} x={96} y={88} width={1580} scaleFrom={1.012} scaleTo={1.032} />
      <CopyBlock
        start={start + 28}
        label="Ending Compiler"
        title="The result is compiled from the path actually played."
        body="The final screen turns a run into a shareable artifact: ending label, highlights, paths not taken, and replay loop."
        x={110}
        y={110}
        size={54}
      />
      <div style={{position: "absolute", right: 98, bottom: 90, display: "grid", gap: 12, width: 500}}>
        <ProofChip delay={start + 142} tone="red">Pivotal moments</ProofChip>
        <ProofChip delay={start + 166} tone="gold">Alternate branches</ProofChip>
        <ProofChip delay={start + 190} tone="blue">Shareable ending</ProofChip>
      </div>
    </>
  )
}

const ReflectionScene: React.FC = () => {
  const [start, end] = scenes.reflection
  const frame = useCurrentFrame()
  const metrics = [
    "Full-stack prototype",
    "Structured LLM generation",
    "Stateful gameplay loop",
    "Advisor context",
    "Shareable ending",
  ]
  return (
    <>
      <ArtBackground src={keyframes.engine} start={start} end={end} tint="gold" />
      <ScreenFrame src={captures.portfolio} start={start + 8} end={end} x={900} y={142} width={880} scaleFrom={1} scaleTo={1.01} />
      <CopyBlock
        start={start + 28}
        label="Engineering Reflection"
        title="I use this project to study reliable AI product systems."
        body="Next layer: measure latency, recover from failed turns, and benchmark quality across many seeds."
        x={108}
        y={150}
        size={62}
      />
      <div style={{position: "absolute", left: 108, bottom: 112, width: 760, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14}}>
        {metrics.map((m, i) => {
          const opacity = clampInterpolate(frame - start - 130 - i * 14, [0, 20], [0, 1])
          return (
            <div
              key={m}
              style={{
                opacity,
                padding: "18px 20px",
                borderRadius: 16,
                border: "1px solid rgba(255,255,255,.13)",
                background: "rgba(8,10,15,.72)",
                color: "#fff5e7",
                fontSize: 25,
                fontWeight: 760,
              }}
            >
              {m}
            </div>
          )
        })}
      </div>
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
          width: `${clampInterpolate(useCurrentFrame(), [0, 2700], [0, 100])}%`,
          background: "linear-gradient(90deg, #8ee8ff, #d7ad50, #ff5d72)",
        }}
      />
    </div>
  </AbsoluteFill>
)
