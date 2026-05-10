import React from "react"
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion"

const keyframes = {
  hook: "keyframes/01-wedding-hook.jpg",
  engine: "keyframes/02-story-engine.jpg",
  choice: "keyframes/03-choice-moment.jpg",
  reveal: "keyframes/04-evidence-reveal.jpg",
  ending: "keyframes/05-ending-share.jpg",
}

const assets = {
  bride: "webtoons/avatars/bride-01.jpg",
  lawyer: "webtoons/avatars/lawyer-01.jpg",
  idol: "webtoons/avatars/idol-01.jpg",
  advisor: "webtoons/advisors/advisor-12.jpg",
  ring: "webtoons/peaks/peak_ring_crack.jpg",
  phone: "webtoons/peaks/peak_message_seen.jpg",
  stamp: "webtoons/peaks/peak_contract_stamp.jpg",
  eye: "webtoons/peaks/peak_cold_eye.jpg",
  wedding: "webtoons/shells/wedding-04.jpg",
  courtroom: "webtoons/shells/courtroom-04.jpg",
  cctv: "webtoons/segments/reveal_cctv_room.jpg",
}

type TimedProps = {
  start: number
  end: number
  children: React.ReactNode
}

const Timed: React.FC<TimedProps> = ({start, end, children}) => {
  const frame = useCurrentFrame()
  if (frame < start || frame >= end) return null
  return <>{children}</>
}

function localFrame(start: number) {
  return Math.max(0, useCurrentFrame() - start)
}

function fitOpacity(start: number, end: number) {
  const frame = useCurrentFrame()
  const fadeIn = interpolate(frame, [start, start + 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  })
  const fadeOut = interpolate(frame, [end - 18, end], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  })
  return Math.min(fadeIn, fadeOut)
}

const Background: React.FC<{src: string; start: number; end: number; push?: number}> = ({
  src,
  start,
  end,
  push = 1,
}) => {
  const frame = useCurrentFrame()
  const opacity = fitOpacity(start, end)
  const progress = interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  })
  const scale = 1.06 + progress * 0.045 * push
  const x = interpolate(progress, [0, 1], [-18 * push, 18 * push])
  return (
    <AbsoluteFill style={{opacity, overflow: "hidden", background: "#050607"}}>
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `translateX(${x}px) scale(${scale})`,
          filter: "contrast(1.08) saturate(1.08)",
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(90deg, rgba(2,4,7,.86), rgba(2,4,7,.28) 48%, rgba(2,4,7,.75)), radial-gradient(circle at 70% 40%, rgba(151, 17, 37, .18), transparent 38%)",
        }}
      />
      <AbsoluteFill
        style={{
          boxShadow: "inset 0 0 180px rgba(0,0,0,.84)",
          border: "1px solid rgba(255,255,255,.035)",
        }}
      />
    </AbsoluteFill>
  )
}

const Kicker: React.FC<{children: React.ReactNode}> = ({children}) => (
  <div
    style={{
      fontSize: 23,
      letterSpacing: 2.4,
      textTransform: "uppercase",
      color: "#8ee8ff",
      fontWeight: 700,
    }}
  >
    {children}
  </div>
)

const Title: React.FC<{children: React.ReactNode; size?: number}> = ({children, size = 92}) => (
  <div
    style={{
      marginTop: 26,
      fontSize: size,
      lineHeight: 1,
      maxWidth: 1040,
      color: "#f8f3ea",
      fontWeight: 760,
      letterSpacing: 0,
      textShadow: "0 18px 48px rgba(0,0,0,.55)",
    }}
  >
    {children}
  </div>
)

const Body: React.FC<{children: React.ReactNode; width?: number}> = ({children, width = 820}) => (
  <div
    style={{
      marginTop: 28,
      maxWidth: width,
      color: "rgba(244, 239, 226, .82)",
      fontSize: 33,
      lineHeight: 1.35,
      fontWeight: 450,
    }}
  >
    {children}
  </div>
)

const GlassCard: React.FC<{
  children: React.ReactNode
  style?: React.CSSProperties
  delay?: number
}> = ({children, style, delay = 0}) => {
  const {fps} = useVideoConfig()
  const frame = useCurrentFrame()
  const pop = spring({
    frame: Math.max(0, frame - delay),
    fps,
    config: {damping: 18, stiffness: 95, mass: 0.8},
  })
  return (
    <div
      style={{
        border: "1px solid rgba(255,255,255,.15)",
        background: "linear-gradient(145deg, rgba(7,12,18,.76), rgba(45,16,24,.50))",
        boxShadow: "0 24px 80px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.12)",
        backdropFilter: "blur(22px)",
        borderRadius: 18,
        opacity: interpolate(pop, [0, 1], [0, 1]),
        transform: `translateY(${interpolate(pop, [0, 1], [28, 0])}px) scale(${interpolate(pop, [0, 1], [.96, 1])})`,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

const ProgressBar: React.FC<{label: string; value: number; color?: string; delay?: number}> = ({
  label,
  value,
  color = "#8ee8ff",
  delay = 0,
}) => {
  const frame = useCurrentFrame()
  const fill = interpolate(frame - delay, [0, 36], [0, value], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  })
  return (
    <div style={{marginTop: 22}}>
      <div style={{display: "flex", justifyContent: "space-between", color: "#eee7dc", fontSize: 22}}>
        <span>{label}</span>
        <span>{Math.round(fill)}</span>
      </div>
      <div style={{height: 10, marginTop: 10, background: "rgba(255,255,255,.12)", borderRadius: 999}}>
        <div
          style={{
            height: "100%",
            width: `${fill}%`,
            background: color,
            borderRadius: 999,
            boxShadow: `0 0 28px ${color}`,
          }}
        />
      </div>
    </div>
  )
}

const Portrait: React.FC<{src: string; name: string; role: string; delay?: number}> = ({
  src,
  name,
  role,
  delay = 0,
}) => (
  <GlassCard style={{width: 220, padding: 14}} delay={delay}>
    <Img
      src={staticFile(src)}
      style={{width: 192, height: 192, objectFit: "cover", borderRadius: 14, display: "block"}}
    />
    <div style={{marginTop: 14, color: "#f5efe5", fontSize: 24, fontWeight: 700}}>{name}</div>
    <div style={{marginTop: 6, color: "rgba(245,239,229,.62)", fontSize: 18}}>{role}</div>
  </GlassCard>
)

const ChoiceCard: React.FC<{label: string; body: string; accent: string; delay: number}> = ({
  label,
  body,
  accent,
  delay,
}) => (
  <GlassCard style={{width: 470, padding: "28px 30px", minHeight: 190}} delay={delay}>
    <div style={{color: accent, fontSize: 24, fontWeight: 800}}>{label}</div>
    <div style={{marginTop: 16, color: "#fff8ed", fontSize: 30, lineHeight: 1.18, fontWeight: 720}}>
      {body}
    </div>
  </GlassCard>
)

const EvidenceTile: React.FC<{src: string; title: string; delay: number}> = ({src, title, delay}) => (
  <GlassCard style={{width: 360, padding: 14}} delay={delay}>
    <Img src={staticFile(src)} style={{width: "100%", height: 202, objectFit: "cover", borderRadius: 12}} />
    <div style={{marginTop: 14, color: "#f7f1e8", fontSize: 24, fontWeight: 730}}>{title}</div>
  </GlassCard>
)

const MainCopy: React.FC<{start: number; kicker: string; title: React.ReactNode; body?: React.ReactNode; size?: number}> = ({
  start,
  kicker,
  title,
  body,
  size,
}) => {
  const f = localFrame(start)
  const {fps} = useVideoConfig()
  const enter = spring({frame: f, fps, config: {damping: 20, stiffness: 70}})
  return (
    <div
      style={{
        position: "absolute",
        left: 112,
        top: 126,
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [34, 0])}px)`,
      }}
    >
      <Kicker>{kicker}</Kicker>
      <Title size={size}>{title}</Title>
      {body ? <Body>{body}</Body> : null}
    </div>
  )
}

const HookScene: React.FC = () => (
  <>
    <Background src={keyframes.hook} start={0} end={210} push={0.7} />
    <MainCopy
      start={8}
      kicker="Tiny Stories"
      title={
        <>
          Stop writing stories.
          <br />
          Survive one.
        </>
      }
      body="A one-sentence premise becomes a playable Korean drama crisis with pressure, secrets, and consequences."
    />
    <GlassCard style={{position: "absolute", right: 112, bottom: 112, width: 520, padding: 34}} delay={68}>
      <div style={{color: "#8ee8ff", fontSize: 22, fontWeight: 800}}>Seed</div>
      <div style={{marginTop: 18, color: "#fff8ed", fontSize: 34, lineHeight: 1.2, fontWeight: 720}}>
        At my wedding, he asks me to sign away the shares.
      </div>
      <div style={{marginTop: 18, color: "rgba(255,248,237,.68)", fontSize: 24}}>
        But I know the witness is lying.
      </div>
    </GlassCard>
  </>
)

const EngineScene: React.FC = () => (
  <>
    <Background src={keyframes.engine} start={210} end={450} push={-0.6} />
    <MainCopy
      start={226}
      kicker="Author Engine"
      title="From prompt to playable board."
      body="The system builds the cast, objective, pressure meters, evidence, and an advisor before the first turn begins."
      size={78}
    />
    <div style={{position: "absolute", left: 112, bottom: 104, display: "flex", gap: 24}}>
      <Portrait src={assets.bride} name="You" role="Cornered heir" delay={260} />
      <Portrait src={assets.idol} name="Fiance" role="Public pressure" delay={280} />
      <Portrait src={assets.lawyer} name="Witness" role="Unstable ally" delay={300} />
      <Portrait src={assets.advisor} name="Advisor" role="Offstage counsel" delay={320} />
    </div>
    <GlassCard style={{position: "absolute", right: 112, top: 168, width: 520, padding: 32}} delay={310}>
      <div style={{color: "#f4b15f", fontSize: 22, fontWeight: 800}}>Live State</div>
      <ProgressBar label="Evidence" value={62} color="#8ee8ff" delay={328} />
      <ProgressBar label="Family Trust" value={36} color="#f4b15f" delay={342} />
      <ProgressBar label="Pressure" value={78} color="#e43c55" delay={356} />
    </GlassCard>
  </>
)

const ChoiceScene: React.FC = () => (
  <>
    <Background src={keyframes.choice} start={450} end={750} push={0.35} />
    <MainCopy
      start={466}
      kicker="Turn 4"
      title="Every choice is a strategy."
      body="Delay, expose, appeal, or burn leverage. The story reacts to what you spend."
      size={76}
    />
    <div style={{position: "absolute", left: 112, bottom: 106, display: "flex", gap: 26}}>
      <ChoiceCard label="Delay" body="Ask to review the contract history." accent="#8ee8ff" delay={530} />
      <ChoiceCard label="Expose" body="Force the witness to repeat the lie." accent="#ff5d72" delay={552} />
      <ChoiceCard label="Appeal" body="Signal the advisor before signing." accent="#f4b15f" delay={574} />
    </div>
    <GlassCard style={{position: "absolute", right: 112, top: 142, width: 420, padding: 30}} delay={606}>
      <div style={{color: "#8ee8ff", fontSize: 24, fontWeight: 800}}>Projected Result</div>
      <div style={{marginTop: 20, color: "#fff8ed", fontSize: 32, lineHeight: 1.14, fontWeight: 750}}>
        Pressure rises.
        <br />
        Evidence unlocks.
      </div>
    </GlassCard>
  </>
)

const RevealScene: React.FC = () => (
  <>
    <Background src={keyframes.reveal} start={750} end={1020} push={-0.4} />
    <MainCopy
      start={766}
      kicker="Reversal"
      title="The earlier turn changes the reveal."
      body="A hidden CCTV thread becomes playable leverage instead of a scripted twist."
      size={74}
    />
    <div style={{position: "absolute", right: 96, bottom: 96, display: "flex", gap: 24}}>
      <EvidenceTile src={assets.ring} title="Broken vow" delay={836} />
      <EvidenceTile src={assets.cctv} title="CCTV room" delay={858} />
      <EvidenceTile src={assets.stamp} title="Signed proof" delay={880} />
    </div>
    <GlassCard style={{position: "absolute", left: 112, bottom: 116, width: 520, padding: 30}} delay={902}>
      <div style={{color: "#ff5d72", fontSize: 25, fontWeight: 850}}>Branch unlocked</div>
      <div style={{marginTop: 16, color: "#fff8ed", fontSize: 36, lineHeight: 1.12, fontWeight: 780}}>
        Public reversal is now possible.
      </div>
    </GlassCard>
  </>
)

const MontageScene: React.FC = () => {
  const frame = useCurrentFrame()
  const local = frame - 1020
  const tiles = [assets.wedding, assets.phone, assets.eye, assets.courtroom]
  return (
    <>
      <Background src={keyframes.reveal} start={1020} end={1230} push={0.2} />
      <MainCopy
        start={1034}
        kicker="System Shape"
        title="Not a chat log. A playable drama loop."
        body="Authoring, runtime state, advisor interventions, emotional art beats, and a screenshot-ready ending."
        size={68}
      />
      <div style={{position: "absolute", left: 112, bottom: 98, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20}}>
        {tiles.map((src, i) => {
          const pop = interpolate(local, [30 + i * 16, 58 + i * 16], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })
          return (
            <div
              key={src}
              style={{
                width: 392,
                height: 220,
                borderRadius: 16,
                overflow: "hidden",
                border: "1px solid rgba(255,255,255,.16)",
                opacity: pop,
                transform: `translateY(${interpolate(pop, [0, 1], [28, 0])}px)`,
                boxShadow: "0 20px 54px rgba(0,0,0,.45)",
              }}
            >
              <Img src={staticFile(src)} style={{width: "100%", height: "100%", objectFit: "cover"}} />
            </div>
          )
        })}
      </div>
    </>
  )
}

const EndingScene: React.FC = () => (
  <>
    <Background src={keyframes.ending} start={1230} end={1530} push={0.55} />
    <MainCopy
      start={1246}
      kicker="Ending Card"
      title="The result feels earned."
      body="The demo ends with a clear route identity, visible tradeoffs, and a frame worth sharing."
      size={76}
    />
    <GlassCard style={{position: "absolute", right: 126, top: 132, width: 560, padding: 38}} delay={1298}>
      <div style={{color: "#8ee8ff", fontSize: 24, fontWeight: 850}}>S-Rank Ending</div>
      <div style={{marginTop: 16, color: "#fff8ed", fontSize: 54, lineHeight: 1.03, fontWeight: 820}}>
        Public Reversal
      </div>
      <div style={{marginTop: 24, color: "rgba(255,248,237,.72)", fontSize: 26, lineHeight: 1.28}}>
        You exposed the forged witness statement, kept the shares, and lost the family's silence.
      </div>
      <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 30}}>
        {["Truth 92", "Trust 41", "Pressure 88", "Cost 63"].map((item, i) => (
          <div
            key={item}
            style={{
              padding: "14px 16px",
              borderRadius: 12,
              background: i === 0 ? "rgba(142,232,255,.16)" : "rgba(255,255,255,.08)",
              color: "#fff8ed",
              fontSize: 24,
              fontWeight: 720,
            }}
          >
            {item}
          </div>
        ))}
      </div>
    </GlassCard>
    <div
      style={{
        position: "absolute",
        left: 112,
        bottom: 74,
        color: "rgba(245,239,229,.78)",
        fontSize: 24,
      }}
    >
      Tiny Stories · LLM interactive drama engine · 150 consistent webtoon assets
    </div>
  </>
)

export const TinyStoriesTrailer: React.FC = () => (
  <AbsoluteFill style={{background: "#030406", fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"}}>
    <Timed start={0} end={210}><HookScene /></Timed>
    <Timed start={210} end={450}><EngineScene /></Timed>
    <Timed start={450} end={750}><ChoiceScene /></Timed>
    <Timed start={750} end={1020}><RevealScene /></Timed>
    <Timed start={1020} end={1230}><MontageScene /></Timed>
    <Timed start={1230} end={1530}><EndingScene /></Timed>
  </AbsoluteFill>
)
