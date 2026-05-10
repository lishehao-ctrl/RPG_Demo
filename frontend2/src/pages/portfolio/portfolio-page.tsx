import { useState } from "react"
import { motion } from "motion/react"
import { Header } from "../../shared/ui/header"
import {
  ASSET_GALLERY,
  CASE_STUDY_POINTS,
  PIPELINE_STEPS,
  PORTFOLIO_METRICS,
  REVIEWER_DEMO_ACTIONS,
  REVIEWER_DEMO_SEED,
  REVIEWER_DEMO_TITLE,
} from "./portfolio-data"

export function PortfolioPage({
  onBackHome,
  onOpenCreate,
  onOpenReviewer,
}: {
  onBackHome: () => void
  onOpenCreate: () => void
  onOpenReviewer: () => void
}) {
  const [activeStep, setActiveStep] = useState(0)
  const step = PIPELINE_STEPS[activeStep]

  return (
    <div className="portfolio-page">
      <Header onHome={onBackHome} onCreate={onOpenCreate} />
      <main className="portfolio-main">
        <motion.section
          className="portfolio-hero"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.36, ease: "easeOut" }}
        >
          <div className="portfolio-hero__content">
            <span className="ts-tag">Portfolio Case Study</span>
            <h1>Tiny Stories is an inspectable AI drama runtime.</h1>
            <p>
              A one-line seed becomes a playable Korean-webtoon-style episode:
              cast, role, consequences, advisor reasoning, ending compiler, and
              replayable branches.
            </p>
            <div className="portfolio-hero__actions">
              <button className="ts-btn ts-btn--primary ts-btn--lg" type="button" onClick={onOpenReviewer}>
                Launch reviewer demo
              </button>
              <button className="ts-btn ts-btn--ghost ts-btn--lg" type="button" onClick={onOpenCreate}>
                Try a custom seed
              </button>
            </div>
          </div>
        </motion.section>

        <section className="portfolio-proofbar" aria-label="Portfolio proof points">
          {PORTFOLIO_METRICS.map((metric) => (
            <div className="portfolio-proofbar__item" key={metric.value}>
              <strong>{metric.value}</strong>
              <span>{metric.label}</span>
            </div>
          ))}
        </section>

        <section className="portfolio-section portfolio-section--two">
          <div>
            <span className="portfolio-kicker">Curated reviewer path</span>
            <h2>{REVIEWER_DEMO_TITLE}</h2>
            <p className="portfolio-lede">
              The demo seed is intentionally dense: public stakes, private
              leverage, business betrayal, an ex with proof, and a live-stage
              deadline. It gives the generator enough dramatic structure to
              show the system at its strongest.
            </p>
            <blockquote className="portfolio-seed">"{REVIEWER_DEMO_SEED}"</blockquote>
          </div>
          <ol className="portfolio-review-list">
            {REVIEWER_DEMO_ACTIONS.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ol>
        </section>

        <section className="portfolio-section">
          <div className="portfolio-section__head">
            <span className="portfolio-kicker">System Inspector</span>
            <h2>What the evaluator should notice</h2>
          </div>
          <div className="portfolio-inspector">
            <div className="portfolio-inspector__tabs" role="tablist" aria-label="System pipeline">
              {PIPELINE_STEPS.map((item, idx) => (
                <button
                  key={item.title}
                  className={idx === activeStep ? "is-active" : ""}
                  type="button"
                  role="tab"
                  aria-selected={idx === activeStep}
                  onClick={() => setActiveStep(idx)}
                >
                  <span>{item.eyebrow}</span>
                  {item.title}
                </button>
              ))}
            </div>
            <motion.div
              className="portfolio-inspector__detail"
              key={step.title}
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
            >
              <span>{step.eyebrow}</span>
              <h3>{step.title}</h3>
              <p>{step.summary}</p>
              <div>{step.proof}</div>
            </motion.div>
          </div>
        </section>

        <section className="portfolio-gallery" aria-label="Korean webtoon visual system">
          {ASSET_GALLERY.map((asset) => (
            <article className="portfolio-gallery__item" key={asset.src}>
              <img src={asset.src} alt="" loading="lazy" />
              <div>
                <h3>{asset.title}</h3>
                <p>{asset.note}</p>
              </div>
            </article>
          ))}
        </section>

        <section className="portfolio-section portfolio-case-grid">
          {CASE_STUDY_POINTS.map((item) => (
            <article className="portfolio-case-card" key={item.title}>
              <span className="portfolio-kicker">{item.title}</span>
              <p>{item.body}</p>
            </article>
          ))}
        </section>

        <section className="portfolio-section portfolio-final">
          <span className="portfolio-kicker">Portfolio framing</span>
          <h2>Not a prompt toy. A reliable AI product surface.</h2>
          <p>
            The strongest application story is that you can turn raw generation
            into a user-facing workflow: controlled entry, typed state,
            explainable progression, visual polish, and an artifact someone can
            replay or evaluate.
          </p>
          <button className="ts-btn ts-btn--primary ts-btn--lg" type="button" onClick={onOpenReviewer}>
            Run the curated demo
          </button>
        </section>
      </main>
    </div>
  )
}
