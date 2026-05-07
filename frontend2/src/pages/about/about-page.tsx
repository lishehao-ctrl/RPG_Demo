import { type CSSProperties, type ReactNode } from "react"
import { Header } from "../../shared/ui/header"
import { useLanguage } from "../../shared/lib/i18n"

/**
 * Minimal "About / Terms / Privacy" stub. Single page covering:
 *   - what this product is
 *   - what we store / don't share
 *   - how to report broken / inappropriate content
 *   - contact
 *
 * Pre-launch this is enough to satisfy a basic legal floor and
 * give users somewhere to link from a footer. Replace with a real
 * legal review before any commercial launch.
 *
 * Content is bilingual: zh and en branches render entirely separate
 * paragraph blocks rather than translating field-by-field, because
 * the prose flow matters and word-level translation produces a
 * stilted page.
 */
export function AboutPage({
  onBackHome,
  onOpenCreate,
}: {
  onBackHome: () => void
  onOpenCreate: () => void
}) {
  const { lang } = useLanguage()
  const content = lang === "en" ? aboutContentEn : aboutContentZh
  return (
    <div style={apStyles.page}>
      <Header onHome={onBackHome} onCreate={onOpenCreate} />
      <main style={apStyles.main}>
        <h1 style={apStyles.title}>{content.title}</h1>
        {content.sections.map((section, i) => (
          <section style={apStyles.section} key={i}>
            <h2 style={apStyles.h2}>{section.heading}</h2>
            {section.body}
          </section>
        ))}
        <div style={apStyles.footer}>
          <button
            className="ts-btn ts-btn--ghost"
            onClick={onBackHome}
            type="button"
          >
            {content.backToHome}
          </button>
        </div>
      </main>
    </div>
  )
}

type AboutContent = {
  title: string
  sections: ReadonlyArray<{ heading: string; body: ReactNode }>
  backToHome: string
}

const apStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)" },
  main: { maxWidth: 720, margin: "0 auto", padding: "56px 32px 80px" },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 36,
    fontWeight: 400,
    margin: "0 0 36px",
  },
  section: { marginBottom: 36 },
  h2: {
    fontFamily: "var(--font-narrative)",
    fontSize: 20,
    fontWeight: 500,
    margin: "0 0 14px",
    color: "var(--text)",
  },
  p: {
    fontSize: 15,
    lineHeight: 1.75,
    color: "var(--text-muted)",
    margin: "0 0 14px",
  },
  ul: {
    fontSize: 15,
    lineHeight: 1.75,
    color: "var(--text-muted)",
    paddingLeft: 22,
    margin: "0 0 14px",
  },
  link: { color: "var(--accent)", textDecoration: "underline" },
  footer: {
    paddingTop: 32,
    borderTop: "1px dashed var(--line)",
    marginTop: 24,
  },
}

const aboutContentZh: AboutContent = {
  title: "关于 Tiny Stories",
  backToHome: "← 回到首页",
  sections: [
    {
      heading: "这是什么",
      body: (
        <>
          <p style={apStyles.p}>
            一个由 AI 实时生成的互动短剧产品.你写下一个戏剧瞬间,AI
            为你搭起人物、场景、第一段叙述;你通过选择和自由输入推进剧情;
            12 回合左右走到一个有标签的结局,可以分享给朋友看,也可以邀请
            朋友玩同一个开场.
          </p>
          <p style={apStyles.p}>
            所有故事都是 LLM 实时生成的 — 意味着每一局都不一样,也意味着
            偶尔可能出现不连贯、不合理或不符合你预期的内容.这是它有趣的
            地方,也是它当前的局限.
          </p>
        </>
      ),
    },
    {
      heading: "我们存什么",
      body: (
        <>
          <ul style={apStyles.ul}>
            <li>你的用户名(仅用于登录与展示)</li>
            <li>你创建的故事模板和你玩的局(包括叙述、选择、顾问对话)</li>
            <li>你的故事是公开还是私有,由你自己决定</li>
          </ul>
          <p style={apStyles.p}>
            <strong>不会做:</strong>
            出售你的数据、把你的故事训练成第三方的模型、把你设为私有的故事公开.
            公开模板的访问者能看到你的玩法回放(这是产品核心机制);
            如果你不希望被看到,把模板设为"只有我"或"凭链接".
          </p>
        </>
      ),
    },
    {
      heading: "内容与边界",
      body: (
        <>
          <p style={apStyles.p}>
            我们使用第三方 AI 服务(阿里云 Qwen / DeepSeek 等),它们有自己
            的内容审查机制.某些种子或玩法可能被服务端拒绝 — 这通常表现为
            顾问回复 "踩到红线" 或者故事接不上某个动作.请尝试换个角度.
          </p>
          <p style={apStyles.p}>
            <strong>请不要:</strong>
            生成涉及未成年人的不当内容、教唆暴力或自残、造谣针对真实人物的
            内容.我们保留删除任何违反公序良俗或法律的故事的权利.
          </p>
          <p style={apStyles.p}>
            发现问题内容?给我们发邮件:{" "}
            <a href="mailto:hello@tinystories.app" style={apStyles.link}>
              hello@tinystories.app
            </a>
          </p>
        </>
      ),
    },
    {
      heading: "免责",
      body: (
        <p style={apStyles.p}>
          这是一个 AI 生成内容的产品.所有故事、角色、对话都是虚构的.
          如果某个情节恰好与现实人物或事件相似,那是 LLM 训练数据的副作用,
          不代表本产品的立场.剧情中的选择、顾问的建议都不是任何形式的
          生活/法律/情感建议 — 它们是戏剧的一部分.
        </p>
      ),
    },
  ],
}

const aboutContentEn: AboutContent = {
  title: "About Tiny Stories",
  backToHome: "← Back to home",
  sections: [
    {
      heading: "What this is",
      body: (
        <>
          <p style={apStyles.p}>
            An interactive short-drama product powered by real-time AI
            generation. You write a dramatic moment, the AI builds the
            cast, the scene and the opening passage. You drive the plot
            via choices and free-form actions. Around 12 turns later
            you reach a labeled ending you can share with friends, or
            invite them to play the same opening.
          </p>
          <p style={apStyles.p}>
            Every run is generated live by an LLM — every session is
            different, and occasionally the output may be incoherent,
            implausible or different from what you expected. That's the
            charm and the current limitation.
          </p>
        </>
      ),
    },
    {
      heading: "What we store",
      body: (
        <>
          <ul style={apStyles.ul}>
            <li>Your username (for sign-in and display only).</li>
            <li>The story templates you create and the sessions you play (narration, choices, advisor messages).</li>
            <li>Whether each story is public or private — your call.</li>
          </ul>
          <p style={apStyles.p}>
            <strong>What we don't do:</strong> sell your data, train
            third-party models on your stories, or make a private
            story public. Visitors to a public template can replay
            your run (that's the core social mechanic). If you don't
            want that, set the template to "private" or "link only."
          </p>
        </>
      ),
    },
    {
      heading: "Content boundaries",
      body: (
        <>
          <p style={apStyles.p}>
            We use third-party AI services (Aliyun Qwen / DeepSeek
            and similar) which apply their own content moderation.
            Some seeds or actions may be rejected at the provider —
            you'll usually see this as the advisor replying "off-limits"
            or the story not advancing on a given action. Try a
            different angle.
          </p>
          <p style={apStyles.p}>
            <strong>Please don't:</strong> generate inappropriate
            content involving minors, incite violence or self-harm,
            or post defamatory content about real people. We reserve
            the right to remove any story that violates community
            norms or applicable law.
          </p>
          <p style={apStyles.p}>
            See something concerning? Email us at{" "}
            <a href="mailto:hello@tinystories.app" style={apStyles.link}>
              hello@tinystories.app
            </a>
          </p>
        </>
      ),
    },
    {
      heading: "Disclaimer",
      body: (
        <p style={apStyles.p}>
          This product generates AI content. All stories, characters,
          and dialogue are fictional. Any resemblance to real people
          or events is an artifact of LLM training data, not an
          endorsement by us. In-story choices and advisor suggestions
          are NOT life, legal or emotional advice — they're part of
          the drama.
        </p>
      ),
    },
  ],
}
