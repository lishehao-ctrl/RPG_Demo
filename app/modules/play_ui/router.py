from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["play-ui"])


_PLAY_HTML = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>RPG Play</title>
    <style>
      :root {
        --bg: #eff2ea;
        --surface: #f9fbf5;
        --ink: #132016;
        --muted: #59675a;
        --line: #d2dacd;
        --accent: #145343;
        --accent-soft: #d8ebe4;
        --danger: #af3434;
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        color: var(--ink);
        font-family: "Space Grotesk", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", "Avenir Next", "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at 10% -20%, rgba(255, 255, 255, 0.75), transparent 40%),
          linear-gradient(170deg, #e9eee6 0%, #f4f5ee 60%, #e3e9df 100%);
      }

      .shell {
        max-width: 1160px;
        margin: 0 auto;
        padding: 22px 18px 38px;
      }

      .hero {
        border: 1px solid var(--line);
        background: var(--surface);
        border-radius: 18px;
        padding: 14px 16px;
        margin-bottom: 14px;
        box-shadow: 0 12px 26px rgba(26, 40, 31, 0.07);
      }

      .hero h1 {
        margin: 0;
        font-size: 1.4rem;
        letter-spacing: 0.02em;
      }

      .hero p {
        margin: 7px 0 0;
        color: #2f3d31;
        line-height: 1.45;
      }

      .chip {
        margin-top: 8px;
        display: inline-block;
        border-radius: 999px;
        padding: 6px 10px;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        background: var(--accent-soft);
        color: var(--accent);
      }

      .grid {
        display: grid;
        gap: 14px;
        grid-template-columns: 1.7fr 1fr;
      }

      @media (max-width: 940px) {
        .grid { grid-template-columns: 1fr; }
      }

      .panel {
        border: 1px solid var(--line);
        border-radius: 16px;
        background: var(--surface);
        padding: 13px;
        box-shadow: 0 10px 24px rgba(26, 40, 31, 0.05);
      }

      .panel h2 {
        margin: 0 0 9px;
        font-size: 0.88rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }

      .narrative {
        border-left: 4px solid var(--accent);
        background: #eaf5f1;
        border-radius: 10px;
        padding: 10px 12px;
        line-height: 1.55;
        margin-bottom: 12px;
        min-height: 56px;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        word-break: break-word;
        unicode-bidi: plaintext;
      }

      .narrative.loading {
        position: relative;
        overflow: hidden;
      }

      .narrative.loading::after {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(110deg, rgba(255, 255, 255, 0) 20%, rgba(255, 255, 255, 0.48) 45%, rgba(255, 255, 255, 0) 70%);
        animation: shimmer 1.25s linear infinite;
      }

      .narrative-line {
        display: inline;
      }

      .choices {
        display: grid;
        gap: 8px;
        margin-bottom: 12px;
      }

      .choice-card {
        border: 1px solid var(--line);
        border-radius: 11px;
        background: #fff;
        padding: 9px;
        display: grid;
        gap: 6px;
      }

      .choice-btn {
        border: none;
        border-radius: 9px;
        background: var(--accent);
        color: #fff;
        font-weight: 700;
        padding: 9px 11px;
        text-align: left;
        cursor: pointer;
      }

      .choice-btn:disabled { opacity: 0.45; cursor: not-allowed; }

      .lock {
        color: var(--danger);
        font-size: 0.82rem;
      }

      .field {
        display: grid;
        gap: 6px;
        margin-bottom: 9px;
      }

      .field label {
        font-size: 0.77rem;
        color: var(--muted);
      }

      .field input,
      .field textarea {
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 9px 10px;
        background: #fff;
        color: var(--ink);
      }

      .field textarea {
        min-height: 88px;
        resize: vertical;
      }

      .btn-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }

      button.ctrl {
        border: none;
        border-radius: 10px;
        padding: 8px 11px;
        font-weight: 700;
        font-size: 0.83rem;
        cursor: pointer;
      }

      .btn-main { background: var(--accent); color: #fff; }
      .btn-muted { background: #5f6e62; color: #fff; }
      .btn-main:disabled,
      .btn-muted:disabled { opacity: 0.5; cursor: not-allowed; }

      button.ctrl.pending {
        animation: pulse 1s ease-in-out infinite;
      }

      .stats {
        display: grid;
        gap: 7px;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .stat {
        border: 1px solid var(--line);
        border-radius: 10px;
        background: #fff;
        padding: 8px;
      }

      .k {
        font-size: 0.72rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }

      .v {
        margin-top: 3px;
        font-size: 1.03rem;
        font-weight: 700;
      }

      .ending {
        border: 1px solid #ccd9f4;
        border-radius: 10px;
        background: #f2f6ff;
        padding: 9px;
        line-height: 1.45;
      }

      .ending ul { margin: 6px 0 0 18px; padding: 0; }

      .error {
        min-height: 1.1rem;
        margin-top: 8px;
        color: var(--danger);
        font-size: 0.86rem;
      }

      .info {
        margin-top: 9px;
        color: var(--muted);
        font-size: 0.84rem;
      }

      details.adv {
        margin-top: 12px;
        border: 1px solid var(--line);
        border-radius: 10px;
        background: #fff;
        padding: 8px 10px;
      }

      details.adv summary {
        cursor: pointer;
        font-weight: 700;
        color: #2b3b2e;
      }

      @keyframes shimmer {
        from { transform: translateX(-120%); }
        to { transform: translateX(120%); }
      }

      @keyframes pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(20, 83, 67, 0.35); }
        50% { box-shadow: 0 0 0 5px rgba(20, 83, 67, 0); }
      }

      @media (prefers-reduced-motion: reduce) {
        .narrative.loading::after,
        button.ctrl.pending {
          animation: none;
        }
      }
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="panel" id="story-select-screen">
        <h2>Choose Story</h2>
        <p class="info">Select a published story, then start the run.</p>
        <div class="field">
          <label for="story-select">Story</label>
          <select id="story-select"></select>
        </div>
        <p class="info" id="story-select-meta"></p>
        <div class="btn-row">
          <button class="ctrl btn-main" id="start-story-btn">Start Story</button>
        </div>
        <div class="error" id="story-select-error"></div>
      </section>

      <section id="play-screen">
        <section class="hero">
          <h1 id="scene-title">No active scene</h1>
          <p id="scene-brief">Start a run to begin your story.</p>
          <div class="chip" id="story-chip">Story: -</div>
        </section>

        <section class="grid">
          <section class="panel">
            <h2>Narrative</h2>
            <div class="narrative" id="narrative">
              <span class="narrative-line" id="narrative-line">Your story response will appear here.</span>
            </div>

            <h2>Actions</h2>
            <div class="choices" id="choices"></div>

            <div class="field">
              <label for="free-input">Free Input</label>
              <textarea id="free-input" placeholder="Describe what you want to do..."></textarea>
            </div>
            <div class="btn-row">
              <button class="ctrl btn-main" id="free-step-btn">Submit Free Input</button>
            </div>

            <details class="adv" id="advanced">
              <summary>Advanced details</summary>
              <p class="info" id="advanced-meta">No session metadata yet.</p>
            </details>
          </section>

          <aside class="panel">
            <h2>Run Controls</h2>
            <div class="btn-row">
              <button class="ctrl btn-main" id="change-story-btn">Change Story</button>
              <button class="ctrl btn-muted" id="reset-btn">Reset Run</button>
            </div>
            <div class="error" id="error"></div>

            <h2 style="margin-top: 12px">Status</h2>
            <div class="stats" id="stats"></div>

            <h2 style="margin-top: 12px">Ending</h2>
            <div class="ending" id="ending">Run not ended.</div>
          </aside>
        </section>
      </section>
    </main>

    <script>
      const queryStoryId = (new URLSearchParams(window.location.search).get("story_id") || "").trim();

      const state = {
        mode: "story_select",
        pending: false,
        session: null,
        lastStep: null,
        error: "",
        storySelectError: "",
        catalogLoading: false,
        catalog: [],
        idemCounter: 0,
        sessionMeta: {
          session_id: null,
          story_id: queryStoryId || "",
          story_version: null,
          story_node_id: null,
        },
      };

      const el = {
        storySelectScreen: document.getElementById("story-select-screen"),
        playScreen: document.getElementById("play-screen"),
        storySelect: document.getElementById("story-select"),
        storySelectMeta: document.getElementById("story-select-meta"),
        storySelectError: document.getElementById("story-select-error"),
        startStoryBtn: document.getElementById("start-story-btn"),
        sceneTitle: document.getElementById("scene-title"),
        sceneBrief: document.getElementById("scene-brief"),
        storyChip: document.getElementById("story-chip"),
        narrative: document.getElementById("narrative"),
        narrativeLine: document.getElementById("narrative-line"),
        choices: document.getElementById("choices"),
        freeInput: document.getElementById("free-input"),
        freeStepBtn: document.getElementById("free-step-btn"),
        advancedMeta: document.getElementById("advanced-meta"),
        changeStoryBtn: document.getElementById("change-story-btn"),
        resetBtn: document.getElementById("reset-btn"),
        error: document.getElementById("error"),
        stats: document.getElementById("stats"),
        ending: document.getElementById("ending"),
      };

      function setError(message) {
        state.error = message || "";
        el.error.textContent = state.error;
      }

      function setStorySelectError(message) {
        state.storySelectError = message || "";
        el.storySelectError.textContent = state.storySelectError;
      }

      function playerHeaders(contentType = true) {
        const out = {};
        if (contentType) out["Content-Type"] = "application/json";
        return out;
      }

      async function requestJSON(url, options = {}) {
        const res = await fetch(url, options);
        const text = await res.text();
        let payload;
        try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = { raw: text }; }
        if (!res.ok) {
          const detail = payload && payload.detail ? payload.detail : payload;
          const code = detail && detail.code ? detail.code : `HTTP_${res.status}`;
          const message = detail && detail.message ? detail.message : JSON.stringify(detail);
          throw new Error(`${code}: ${message}`);
        }
        return payload;
      }

      function resolveDefaultStory(catalog, preferredStoryId) {
        const list = Array.isArray(catalog) ? catalog : [];
        if (!list.length) return "";
        const preferred = String(preferredStoryId || "").trim();
        if (preferred && list.some((item) => item && item.story_id === preferred)) {
          return preferred;
        }
        return String(list[0].story_id || "");
      }

      function updateStoryQuery(storyId) {
        const url = new URL(window.location.href);
        const normalized = String(storyId || "").trim();
        if (normalized) {
          url.searchParams.set("story_id", normalized);
        } else {
          url.searchParams.delete("story_id");
        }
        history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
      }

      async function loadStoryCatalog() {
        state.catalogLoading = true;
        setStorySelectError("");
        try {
          const payload = await requestJSON("/api/v1/stories/catalog/published", { method: "GET" });
          state.catalog = Array.isArray(payload.stories) ? payload.stories : [];
          const selected = resolveDefaultStory(state.catalog, state.sessionMeta.story_id);
          if (queryStoryId && selected && queryStoryId !== selected) {
            setStorySelectError(`story_id '${queryStoryId}' was not found. Fallback to '${selected}'.`);
          }
          state.sessionMeta.story_id = selected;
          updateStoryQuery(selected);
        } catch (err) {
          state.catalog = [];
          state.sessionMeta.story_id = "";
          setStorySelectError(err && err.message ? err.message : String(err));
        } finally {
          state.catalogLoading = false;
        }
      }

      function enterPlayingMode() {
        state.mode = "playing";
        setStorySelectError("");
      }

      function backToStorySelect() {
        state.mode = "story_select";
        state.pending = false;
        state.session = null;
        state.lastStep = null;
        state.error = "";
        state.idemCounter = 0;
        state.sessionMeta.session_id = null;
        state.sessionMeta.story_version = null;
        state.sessionMeta.story_node_id = null;
        el.freeInput.value = "";
        setNarrativeLoading(false);
        setError("");
      }

      function setNarrativeLoading(enabled) {
        el.narrative.classList.toggle("loading", Boolean(enabled));
      }

      function setPendingNarrativePlaceholder() {
        if (!state.session) return;
        el.narrativeLine.textContent = "Generating narration...";
      }

      function nextIdempotencyKey() {
        state.idemCounter += 1;
        const random = crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(16).slice(2);
        return `play-${Date.now()}-${state.idemCounter}-${random}`;
      }

      function activeNode() {
        if (state.lastStep && state.lastStep.current_node) return state.lastStep.current_node;
        if (state.session && state.session.current_node) return state.session.current_node;
        return null;
      }

      function applySessionCreated(created) {
        state.session = {
          session_id: created.session_id,
          story_id: created.story_id,
          story_version: created.story_version,
          story_node_id: created.story_node_id,
          status: created.status,
          state_json: created.state_json || {},
          current_node: created.current_node || null,
        };
        state.lastStep = null;
        state.sessionMeta = {
          session_id: created.session_id,
          story_id: created.story_id,
          story_version: created.story_version,
          story_node_id: created.story_node_id,
        };
      }

      function applyStep(step) {
        if (!state.session) return;

        const prevState = state.session.state_json && typeof state.session.state_json === "object"
          ? state.session.state_json
          : {};
        const stateExcerpt = step.state_excerpt && typeof step.state_excerpt === "object" ? step.state_excerpt : {};
        const nextState = {
          ...prevState,
          ...stateExcerpt,
        };

        state.session = {
          ...state.session,
          status: step.session_status || (step.run_ended ? "ended" : "active"),
          story_node_id: step.story_node_id,
          current_node: step.current_node || state.session.current_node,
          state_json: nextState,
        };
        state.lastStep = step;
        state.sessionMeta.story_node_id = step.story_node_id;
      }

      async function runAction(actionFn) {
        if (state.pending) return;
        state.pending = true;
        setError("");
        setPendingNarrativePlaceholder();
        render();
        try {
          await actionFn();
        } catch (err) {
          setError(err && err.message ? err.message : String(err));
        } finally {
          state.pending = false;
          render();
        }
      }

      async function runSelectAction(actionFn) {
        if (state.pending) return;
        state.pending = true;
        setStorySelectError("");
        render();
        try {
          await actionFn();
        } catch (err) {
          setStorySelectError(err && err.message ? err.message : String(err));
        } finally {
          state.pending = false;
          render();
        }
      }

      async function startRun() {
        const storyId = String(state.sessionMeta.story_id || "").trim();
        if (!storyId) {
          throw new Error("No published story available. Please publish a story first.");
        }
        const created = await requestJSON("/api/v1/sessions", {
          method: "POST",
          headers: playerHeaders(true),
          body: JSON.stringify({ story_id: storyId }),
        });
        applySessionCreated(created);
      }

      async function stepOnce(payload, idemKey) {
        return requestJSON(`/api/v1/sessions/${state.session.session_id}/step`, {
          method: "POST",
          headers: {
            ...playerHeaders(true),
            "X-Idempotency-Key": idemKey,
          },
          body: JSON.stringify(payload),
        });
      }

      async function stepWithOneShot(payload) {
        if (!state.session || !state.session.session_id) {
          throw new Error("Start a session first");
        }
        const idemKey = nextIdempotencyKey();
        const step = await stepOnce(payload, idemKey);
        if (step && typeof step.narrative_text === "string") {
          el.narrativeLine.textContent = step.narrative_text || "";
        }
        applyStep(step);
      }

      async function stepWithChoice(choiceId) {
        await stepWithOneShot({ choice_id: choiceId });
      }

      async function stepWithInput(text) {
        await stepWithOneShot({ player_input: text });
      }

      function resetAll() {
        backToStorySelect();
        render();
      }

      function renderScene() {
        const node = activeNode();
        if (!node) {
          el.sceneTitle.textContent = "No active scene";
          el.sceneBrief.textContent = "Start a run to begin your story.";
          el.narrativeLine.textContent = "Your story response will appear here.";
          return;
        }

        el.sceneTitle.textContent = node.title || "Current Scene";
        el.sceneBrief.textContent = node.scene_brief || "";
        if (state.pending && state.session) {
          el.narrativeLine.textContent = "Generating narration...";
        } else if (state.lastStep && state.lastStep.narrative_text) {
          el.narrativeLine.textContent = state.lastStep.narrative_text;
        } else {
          el.narrativeLine.textContent = "Choose an action to advance the story.";
        }
      }

      function renderChoices() {
        const node = activeNode();
        const list = node && Array.isArray(node.choices) ? node.choices : [];
        const runEnded = Boolean(state.lastStep && state.lastStep.run_ended) || (state.session && state.session.status === "ended");

        el.choices.innerHTML = "";
        if (!list.length) {
          el.choices.innerHTML = '<p class="info">No choices available in this scene.</p>';
          return;
        }

        for (const item of list) {
          const card = document.createElement("div");
          card.className = "choice-card";

          const btn = document.createElement("button");
          btn.className = "choice-btn";
          btn.textContent = item.text;
          btn.disabled = state.pending || !item.available || runEnded;
          btn.addEventListener("click", () => runAction(() => stepWithChoice(item.id)));
          card.appendChild(btn);

          if (!item.available && item.locked_reason) {
            const lock = document.createElement("div");
            lock.className = "lock";
            lock.textContent = item.locked_reason.message || "This choice is currently locked.";
            card.appendChild(lock);
          }

          el.choices.appendChild(card);
        }
      }

      function renderStatus() {
        const stateJson = state.session && state.session.state_json ? state.session.state_json : {};
        const run = stateJson && stateJson.run_state ? stateJson.run_state : {};
        const items = [
          ["Energy", stateJson.energy != null ? String(stateJson.energy) : "-"],
          ["Day / Slot", stateJson.day != null && stateJson.slot != null ? `${stateJson.day} / ${stateJson.slot}` : "-"],
          ["Step", run.step_index != null ? String(run.step_index) : "0"],
          ["Fallbacks", run.fallback_count != null ? String(run.fallback_count) : "0"],
        ];

        el.stats.innerHTML = "";
        for (const [key, value] of items) {
          const div = document.createElement("div");
          div.className = "stat";
          div.innerHTML = `<div class="k">${key}</div><div class="v">${value}</div>`;
          el.stats.appendChild(div);
        }
      }

      function renderEnding() {
        const step = state.lastStep;
        if (!step || !step.run_ended) {
          el.ending.textContent = "Run not ended.";
          return;
        }

        const report = step.ending_report || null;
        const highlights = report && Array.isArray(report.highlights) ? report.highlights : [];
        const shortHighlights = highlights
          .slice(0, 3)
          .map((h) => `<li>${h.title}: ${h.detail}</li>`)
          .join("");

        el.ending.innerHTML = `
          <strong>${report ? report.title : (step.ending_id || "Ending")}</strong><br/>
          ${report ? report.one_liner : "Run ended."}<br/>
          <span class="info">Outcome: ${step.ending_outcome || "-"} | Camp: ${step.ending_camp || "-"}</span>
          ${shortHighlights ? `<ul>${shortHighlights}</ul>` : ""}
        `;
      }

      function renderAdvanced() {
        const status = state.session ? state.session.status : "idle";
        const meta = [
          `session_id=${state.sessionMeta.session_id || "-"}`,
          `story_id=${state.sessionMeta.story_id || "-"}`,
          `story_version=${state.sessionMeta.story_version != null ? state.sessionMeta.story_version : "-"}`,
          `story_node_id=${state.sessionMeta.story_node_id || "-"}`,
          `status=${status}`,
        ];
        el.advancedMeta.textContent = meta.join(" | ");
      }

      function renderStorySelect() {
        const list = Array.isArray(state.catalog) ? state.catalog : [];
        el.storySelect.innerHTML = "";
        for (const item of list) {
          const option = document.createElement("option");
          option.value = String(item.story_id || "");
          option.textContent = `${item.title || item.story_id} (${item.story_id})`;
          el.storySelect.appendChild(option);
        }

        const selected = resolveDefaultStory(list, state.sessionMeta.story_id);
        state.sessionMeta.story_id = selected;
        if (selected) {
          el.storySelect.value = selected;
        }

        const selectedItem = list.find((item) => item && item.story_id === selected) || null;
        if (state.catalogLoading) {
          el.storySelectMeta.textContent = "Loading published stories...";
        } else if (!selectedItem) {
          el.storySelectMeta.textContent = "No published stories found.";
        } else {
          el.storySelectMeta.textContent = `story_id=${selectedItem.story_id} | version=${selectedItem.published_version} | updated_at=${selectedItem.updated_at}`;
        }
      }

      function renderButtons() {
        const runEnded = Boolean(state.lastStep && state.lastStep.run_ended) || (state.session && state.session.status === "ended");
        const hasPublished = Array.isArray(state.catalog) && state.catalog.some((item) => item && item.story_id === state.sessionMeta.story_id);
        el.startStoryBtn.disabled = state.pending || !hasPublished;
        el.storySelect.disabled = state.pending || state.catalogLoading || !state.catalog.length;
        el.changeStoryBtn.disabled = state.pending;
        el.resetBtn.disabled = state.pending;
        el.freeStepBtn.disabled = state.pending || !state.session || runEnded;
        el.startStoryBtn.classList.toggle("pending", state.pending && state.mode === "story_select");
        el.changeStoryBtn.classList.toggle("pending", state.pending && state.mode === "playing");
        el.freeStepBtn.classList.toggle("pending", state.pending);
      }

      function render() {
        const inPlaying = state.mode === "playing";
        el.storySelectScreen.style.display = inPlaying ? "none" : "block";
        el.playScreen.style.display = inPlaying ? "block" : "none";
        setNarrativeLoading(inPlaying && state.pending && Boolean(state.session));
        el.storyChip.textContent = `Story: ${state.sessionMeta.story_id}`;
        renderStorySelect();
        renderScene();
        renderChoices();
        renderStatus();
        renderEnding();
        renderAdvanced();
        renderButtons();
      }

      el.startStoryBtn.addEventListener("click", () => runSelectAction(async () => {
        await startRun();
        enterPlayingMode();
      }));
      el.storySelect.addEventListener("change", () => {
        state.sessionMeta.story_id = String(el.storySelect.value || "").trim();
        updateStoryQuery(state.sessionMeta.story_id);
        setStorySelectError("");
        render();
      });
      el.changeStoryBtn.addEventListener("click", resetAll);
      el.resetBtn.addEventListener("click", resetAll);
      el.freeStepBtn.addEventListener("click", () => {
        runAction(async () => {
          const text = String(el.freeInput.value || "").trim();
          if (!text) {
            throw new Error("Free input cannot be empty");
          }
          await stepWithInput(text);
        });
      });

      (async function bootstrap() {
        resetAll();
        await loadStoryCatalog();
        render();
      })();
    </script>
  </body>
</html>
'''


_PLAY_DEV_HTML = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>RPG Play Dev</title>
    <style>
      :root {
        --bg: #ecefe8;
        --surface: #f8faf4;
        --ink: #131f16;
        --muted: #57655a;
        --line: #d0d8cb;
        --accent: #1b5f4d;
        --danger: #a92f2f;
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        color: var(--ink);
        font-family: "Space Grotesk", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", "Avenir Next", "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at 80% -10%, rgba(255, 255, 255, 0.75), transparent 35%),
          linear-gradient(165deg, #e9eee6 0%, #f5f6f1 48%, #e1e7de 100%);
      }

      .shell {
        max-width: 1460px;
        margin: 0 auto;
        padding: 20px 16px 34px;
      }

      .hero {
        border: 1px solid var(--line);
        border-radius: 14px;
        background: var(--surface);
        padding: 12px 14px;
        box-shadow: 0 10px 20px rgba(20, 34, 24, 0.05);
      }

      .hero h1 {
        margin: 0;
        font-size: 1.3rem;
      }

      .hero p {
        margin: 6px 0 0;
        color: #324236;
      }

      .error {
        margin-top: 8px;
        min-height: 1rem;
        color: var(--danger);
        font-size: 0.87rem;
      }

      .dev-grid {
        margin-top: 12px;
        display: grid;
        gap: 12px;
        grid-template-columns: 330px 360px 1fr;
      }

      @media (max-width: 1220px) {
        .dev-grid { grid-template-columns: 1fr; }
      }

      .panel {
        border: 1px solid var(--line);
        border-radius: 14px;
        background: var(--surface);
        padding: 12px;
      }

      .panel h2 {
        margin: 0 0 8px;
        text-transform: uppercase;
        font-size: 0.83rem;
        color: var(--muted);
        letter-spacing: 0.08em;
      }

      .field {
        display: grid;
        gap: 6px;
        margin-bottom: 8px;
      }

      .field label {
        font-size: 0.75rem;
        color: var(--muted);
      }

      .field input,
      .field textarea,
      .field select {
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 9px;
        padding: 8px 9px;
        background: #fff;
        color: var(--ink);
      }

      .field textarea {
        min-height: 80px;
        resize: vertical;
      }

      .btn-row {
        display: flex;
        gap: 7px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }

      button.ctrl {
        border: none;
        border-radius: 9px;
        padding: 8px 10px;
        font-size: 0.8rem;
        font-weight: 700;
        cursor: pointer;
      }

      .btn-main { background: var(--accent); color: #fff; }
      .btn-muted { background: #5f6d61; color: #fff; }
      .btn-light { background: #d8e1d4; color: #243026; }
      .btn-main:disabled,
      .btn-muted:disabled,
      .btn-light:disabled { opacity: 0.5; cursor: not-allowed; }

      .list {
        border: 1px solid var(--line);
        border-radius: 10px;
        background: #fff;
        max-height: 260px;
        overflow: auto;
        padding: 8px;
      }

      .item {
        border: 1px solid var(--line);
        border-radius: 9px;
        padding: 7px;
        margin: 0 0 7px;
        font-size: 0.78rem;
        background: #fafcf8;
      }

      .item button {
        margin-top: 6px;
        border: none;
        border-radius: 8px;
        background: #355f51;
        color: #fff;
        padding: 5px 8px;
        font-size: 0.74rem;
        cursor: pointer;
      }

      .k {
        color: var(--muted);
        font-size: 0.73rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }

      .v {
        font-size: 0.9rem;
        font-weight: 700;
      }

      .overview {
        display: grid;
        gap: 7px;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .card {
        border: 1px solid var(--line);
        border-radius: 9px;
        padding: 7px;
        background: #fff;
      }

      .tabs {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }

      .tab-btn {
        border: 1px solid var(--line);
        border-radius: 999px;
        background: #f2f6f0;
        color: #26432f;
        padding: 6px 10px;
        font-size: 0.76rem;
        cursor: pointer;
      }

      .tab-btn.active {
        border-color: #235e4d;
        background: #d7ebe4;
        color: #124336;
        font-weight: 700;
      }

      .tab-pane { display: none; }
      .tab-pane.active { display: block; }

      .mono {
        font-family: "IBM Plex Mono", "SF Mono", Menlo, monospace;
        background: #161f1a;
        color: #d8e7dd;
        border-radius: 9px;
        padding: 8px;
        font-size: 0.72rem;
        overflow: auto;
        max-height: 460px;
      }

      details.raw {
        margin-top: 8px;
        border: 1px solid var(--line);
        border-radius: 9px;
        background: #fff;
        padding: 7px;
      }

      details.raw summary {
        cursor: pointer;
        font-weight: 700;
      }
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <h1>Story Debug Console</h1>
        <p>Runner + Inspector mode: step the session, then sync one bundle to inspect timeline, state diff and traces.</p>
        <div class="error" id="dev-error"></div>
      </section>

      <section class="dev-grid">
        <section class="panel">
          <h2>Controls</h2>
          <div class="field">
            <label for="dev-story-id">Story ID</label>
            <input id="dev-story-id" value="campus_week_v1" />
          </div>
          <div class="field">
            <label for="dev-status-filter">Status Filter</label>
            <select id="dev-status-filter">
              <option value="">Any</option>
              <option value="active">active</option>
              <option value="ended">ended</option>
            </select>
          </div>
          <div class="field">
            <label for="dev-session-id">Session ID</label>
            <input id="dev-session-id" placeholder="Select from list or paste manually" />
          </div>
          <div class="field">
            <label for="dev-timeline-limit">Timeline Limit</label>
            <input id="dev-timeline-limit" value="50" />
          </div>

          <div class="field">
            <label for="dev-player-token">X-Player-Token (runtime)</label>
            <input id="dev-player-token" />
          </div>
          <div class="field">
            <label for="dev-author-token">X-Author-Token (debug/story/telemetry)</label>
            <input id="dev-author-token" />
          </div>

          <div class="btn-row">
            <button class="ctrl btn-main" id="dev-start-btn">Start Session</button>
            <button class="ctrl btn-muted" id="dev-list-sessions-btn">Load Sessions</button>
            <button class="ctrl btn-muted" id="dev-sync-btn">Sync</button>
            <button class="ctrl btn-light" id="dev-reset-btn">Reset</button>
          </div>

          <h2 style="margin-top: 10px">Step Controls</h2>
          <div class="field">
            <label for="dev-choice-id">Choice ID</label>
            <input id="dev-choice-id" placeholder="e.g. c_study" />
          </div>
          <div class="btn-row">
            <button class="ctrl btn-main" id="dev-step-choice-btn">Step Choice</button>
          </div>
          <div class="field">
            <label for="dev-player-input">Free Input</label>
            <textarea id="dev-player-input" placeholder="Type free action here..."></textarea>
          </div>
          <div class="btn-row">
            <button class="ctrl btn-main" id="dev-step-input-btn">Step Free Input</button>
          </div>
        </section>

        <section class="panel">
          <h2>Session List</h2>
          <div class="list" id="dev-session-list"></div>

          <h2 style="margin-top: 10px">Timeline</h2>
          <div class="list" id="dev-timeline-list"></div>
        </section>

        <section class="panel">
          <h2>Overview</h2>
          <div class="overview" id="dev-overview-cards"></div>

          <h2 style="margin-top: 10px">Telemetry</h2>
          <div class="overview" id="dev-telemetry-cards"></div>

          <h2 style="margin-top: 10px">Story Versions</h2>
          <div class="list" id="dev-versions-list"></div>

          <h2 style="margin-top: 10px">Inspector</h2>
          <div class="tabs" id="dev-tabs">
            <button class="tab-btn active" data-tab="selection">Selection</button>
            <button class="tab-btn" data-tab="state">State Diff</button>
            <button class="tab-btn" data-tab="llm">LLM Trace</button>
            <button class="tab-btn" data-tab="classification">Classification</button>
            <button class="tab-btn" data-tab="raw">Raw JSON</button>
          </div>

          <div class="tab-pane active" id="tab-selection">
            <pre class="mono" id="dev-selection-pane">{}</pre>
          </div>
          <div class="tab-pane" id="tab-state">
            <pre class="mono" id="dev-state-pane">{}</pre>
          </div>
          <div class="tab-pane" id="tab-llm">
            <pre class="mono" id="dev-llm-pane">{}</pre>
          </div>
          <div class="tab-pane" id="tab-classification">
            <pre class="mono" id="dev-classification-pane">{}</pre>
          </div>
          <div class="tab-pane" id="tab-raw">
            <details class="raw" open>
              <summary>Raw JSON payload</summary>
              <pre class="mono" id="dev-raw-pane">{}</pre>
            </details>
          </div>
        </section>
      </section>
    </main>

    <script>
      const debugState = {
        pending: false,
        sessionId: null,
        sessions: [],
        bundle: null,
        selectedStep: null,
        idemCounter: 0,
      };

      const d = {
        error: document.getElementById("dev-error"),
        storyId: document.getElementById("dev-story-id"),
        statusFilter: document.getElementById("dev-status-filter"),
        sessionId: document.getElementById("dev-session-id"),
        timelineLimit: document.getElementById("dev-timeline-limit"),
        playerToken: document.getElementById("dev-player-token"),
        authorToken: document.getElementById("dev-author-token"),
        choiceId: document.getElementById("dev-choice-id"),
        playerInput: document.getElementById("dev-player-input"),
        sessionList: document.getElementById("dev-session-list"),
        timelineList: document.getElementById("dev-timeline-list"),
        overviewCards: document.getElementById("dev-overview-cards"),
        telemetryCards: document.getElementById("dev-telemetry-cards"),
        versionsList: document.getElementById("dev-versions-list"),
        selectionPane: document.getElementById("dev-selection-pane"),
        statePane: document.getElementById("dev-state-pane"),
        llmPane: document.getElementById("dev-llm-pane"),
        classificationPane: document.getElementById("dev-classification-pane"),
        rawPane: document.getElementById("dev-raw-pane"),
        startBtn: document.getElementById("dev-start-btn"),
        listSessionsBtn: document.getElementById("dev-list-sessions-btn"),
        syncBtn: document.getElementById("dev-sync-btn"),
        resetBtn: document.getElementById("dev-reset-btn"),
        stepChoiceBtn: document.getElementById("dev-step-choice-btn"),
        stepInputBtn: document.getElementById("dev-step-input-btn"),
        tabs: document.getElementById("dev-tabs"),
      };

      function setError(message) {
        d.error.textContent = message || "";
      }

      function authorHeaders(contentType = false) {
        const out = {};
        if (contentType) out["Content-Type"] = "application/json";
        const token = String(d.authorToken.value || "").trim();
        if (token) out["X-Author-Token"] = token;
        return out;
      }

      function playerHeaders(contentType = false) {
        const out = {};
        if (contentType) out["Content-Type"] = "application/json";
        const token = String(d.playerToken.value || "").trim();
        if (token) out["X-Player-Token"] = token;
        return out;
      }

      async function requestJSON(url, options = {}) {
        const res = await fetch(url, options);
        const text = await res.text();
        let payload;
        try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = { raw: text }; }
        if (!res.ok) {
          const detail = payload && payload.detail ? payload.detail : payload;
          const code = detail && detail.code ? detail.code : `HTTP_${res.status}`;
          const message = detail && detail.message ? detail.message : JSON.stringify(detail);
          throw new Error(`${code}: ${message}`);
        }
        return payload;
      }

      function nextIdempotencyKey() {
        debugState.idemCounter += 1;
        const random = crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(16).slice(2);
        return `play-dev-${Date.now()}-${debugState.idemCounter}-${random}`;
      }

      function currentSessionId() {
        return String(d.sessionId.value || debugState.sessionId || "").trim();
      }

      function safeNumber(raw, fallback) {
        const n = Number(raw);
        return Number.isFinite(n) ? n : fallback;
      }

      function setSessionId(sessionId) {
        debugState.sessionId = sessionId || null;
        d.sessionId.value = sessionId || "";
      }

      async function runAction(actionFn) {
        if (debugState.pending) return;
        debugState.pending = true;
        setError("");
        try {
          await actionFn();
        } catch (err) {
          setError(err && err.message ? err.message : String(err));
        } finally {
          debugState.pending = false;
          renderAll();
        }
      }

      async function loadSessions() {
        const storyId = String(d.storyId.value || "").trim();
        const status = String(d.statusFilter.value || "").trim();
        const params = new URLSearchParams({ limit: "20", offset: "0" });
        if (storyId) params.set("story_id", storyId);
        if (status) params.set("status", status);

        const data = await requestJSON(`/api/v1/debug/sessions?${params.toString()}`, {
          method: "GET",
          headers: authorHeaders(false),
        });
        debugState.sessions = Array.isArray(data.sessions) ? data.sessions : [];
      }

      async function syncBundle() {
        const sid = currentSessionId();
        if (!sid) throw new Error("Session ID is required");

        const timelineLimit = safeNumber(d.timelineLimit.value, 50);
        const params = new URLSearchParams({
          timeline_limit: String(timelineLimit),
          timeline_offset: "0",
        });

        const bundle = await requestJSON(`/api/v1/debug/sessions/${sid}/bundle?${params.toString()}`, {
          method: "GET",
          headers: authorHeaders(false),
        });
        setSessionId(sid);
        debugState.bundle = bundle;
        if (bundle.latest_step_detail) {
          debugState.selectedStep = bundle.latest_step_detail;
        }
      }

      async function inspectStep(stepIndex) {
        const sid = currentSessionId();
        if (!sid) throw new Error("Session ID is required");

        const latest = debugState.bundle && debugState.bundle.latest_step_detail ? debugState.bundle.latest_step_detail : null;
        if (latest && Number(latest.step_index) === Number(stepIndex)) {
          debugState.selectedStep = latest;
          return;
        }

        const detail = await requestJSON(`/api/v1/debug/sessions/${sid}/steps/${stepIndex}`, {
          method: "GET",
          headers: authorHeaders(false),
        });
        debugState.selectedStep = detail;
      }

      async function startSession() {
        const storyId = String(d.storyId.value || "").trim();
        if (!storyId) throw new Error("Story ID is required");

        const created = await requestJSON("/api/v1/sessions", {
          method: "POST",
          headers: playerHeaders(true),
          body: JSON.stringify({ story_id: storyId }),
        });
        setSessionId(created.session_id);
        await syncBundle();
      }

      async function stepOnce(payload) {
        const sid = currentSessionId();
        if (!sid) throw new Error("Session ID is required");
        const idemKey = nextIdempotencyKey();
        const finalStep = await requestJSON(`/api/v1/sessions/${sid}/step`, {
          method: "POST",
          headers: {
            ...playerHeaders(true),
            "X-Idempotency-Key": idemKey,
          },
          body: JSON.stringify(payload),
        });

        await syncBundle();
        return finalStep;
      }

      async function stepChoice() {
        const choiceId = String(d.choiceId.value || "").trim();
        if (!choiceId) throw new Error("Choice ID is required");
        await stepOnce({ choice_id: choiceId });
      }

      async function stepInput() {
        const text = String(d.playerInput.value || "").trim();
        if (!text) throw new Error("Free input is required");
        await stepOnce({ player_input: text });
      }

      function renderSessionList() {
        d.sessionList.innerHTML = "";
        if (!debugState.sessions.length) {
          d.sessionList.innerHTML = '<p class="item">No sessions found.</p>';
          return;
        }

        for (const item of debugState.sessions) {
          const div = document.createElement("div");
          div.className = "item";
          div.innerHTML = `
            <div><strong>${item.session_id}</strong></div>
            <div>story=${item.story_id} v${item.story_version}</div>
            <div>status=${item.status} node=${item.story_node_id}</div>
            <div>step=${item.step_index} fallback=${item.fallback_count} ended=${item.run_ended}</div>
          `;
          const btn = document.createElement("button");
          btn.textContent = "Use Session";
          btn.disabled = debugState.pending;
          btn.addEventListener("click", () => {
            runAction(async () => {
              setSessionId(item.session_id);
              await syncBundle();
            });
          });
          div.appendChild(btn);
          d.sessionList.appendChild(div);
        }
      }

      function renderTimeline() {
        d.timelineList.innerHTML = "";
        const steps = debugState.bundle && debugState.bundle.timeline && Array.isArray(debugState.bundle.timeline.steps)
          ? debugState.bundle.timeline.steps
          : [];

        if (!steps.length) {
          d.timelineList.innerHTML = '<p class="item">No action logs yet.</p>';
          return;
        }

        for (const step of steps) {
          const div = document.createElement("div");
          div.className = "item";
          div.innerHTML = `
            <div><strong>Step ${step.step_index}</strong> · ${step.executed_choice_id}</div>
            <div>fallback=${step.fallback_used} reason=${step.fallback_reason || "-"}</div>
            <div>source=${step.selection_source || "-"} ended=${step.run_ended}</div>
            <div>${step.created_at}</div>
          `;
          const btn = document.createElement("button");
          btn.textContent = "Inspect";
          btn.disabled = debugState.pending;
          btn.addEventListener("click", () => {
            runAction(() => inspectStep(step.step_index));
          });
          div.appendChild(btn);
          d.timelineList.appendChild(div);
        }
      }

      function renderOverview() {
        d.overviewCards.innerHTML = "";
        const overview = debugState.bundle ? debugState.bundle.overview : null;
        if (!overview) {
          d.overviewCards.innerHTML = '<div class="card">No overview loaded.</div>';
          return;
        }

        const run = overview.run_state || {};
        const cards = [
          ["Session", overview.session_id],
          ["Status", overview.status],
          ["Node", overview.story_node_id],
          ["Step", String(run.step_index || 0)],
          ["Fallbacks", String(run.fallback_count || 0)],
          ["Run Ended", String(Boolean(run.run_ended))],
        ];

        for (const [k, v] of cards) {
          const div = document.createElement("div");
          div.className = "card";
          div.innerHTML = `<div class="k">${k}</div><div class="v">${v}</div>`;
          d.overviewCards.appendChild(div);
        }
      }

      function renderTelemetry() {
        d.telemetryCards.innerHTML = "";
        const t = debugState.bundle ? debugState.bundle.telemetry : null;
        if (!t) {
          d.telemetryCards.innerHTML = '<div class="card">No telemetry loaded.</div>';
          return;
        }

        const cards = [
          ["Total Steps", String(t.total_step_requests)],
          ["Avg Latency", `${t.avg_step_latency_ms} ms`],
          ["P95 Latency", `${t.p95_step_latency_ms} ms`],
          ["Fallback Rate", String(t.fallback_rate)],
          ["LLM Unavailable", String(t.llm_unavailable_ratio)],
          ["Failed Steps", String(t.failed_steps)],
        ];

        for (const [k, v] of cards) {
          const div = document.createElement("div");
          div.className = "card";
          div.innerHTML = `<div class="k">${k}</div><div class="v">${v}</div>`;
          d.telemetryCards.appendChild(div);
        }
      }

      function renderVersions() {
        d.versionsList.innerHTML = "";
        const versions = debugState.bundle && Array.isArray(debugState.bundle.versions) ? debugState.bundle.versions : [];
        if (!versions.length) {
          d.versionsList.innerHTML = '<p class="item">No versions loaded.</p>';
          return;
        }

        for (const item of versions) {
          const div = document.createElement("div");
          div.className = "item";
          div.innerHTML = `
            <div><strong>v${item.version}</strong> · ${item.status}</div>
            <div>${item.created_at}</div>
            <div>checksum: ${item.checksum}</div>
          `;
          d.versionsList.appendChild(div);
        }
      }

      function renderInspector() {
        const detail = debugState.selectedStep;
        if (!detail) {
          const blank = "{}";
          d.selectionPane.textContent = blank;
          d.statePane.textContent = blank;
          d.llmPane.textContent = blank;
          d.classificationPane.textContent = blank;
          d.rawPane.textContent = blank;
          return;
        }

        d.selectionPane.textContent = JSON.stringify(detail.selection_result_json || {}, null, 2);
        d.statePane.textContent = JSON.stringify(
          {
            state_before: detail.state_before || {},
            state_delta: detail.state_delta || {},
            state_after: detail.state_after || {},
          },
          null,
          2,
        );
        d.llmPane.textContent = JSON.stringify(detail.llm_trace_json || {}, null, 2);
        d.classificationPane.textContent = JSON.stringify(detail.classification_json || {}, null, 2);
        d.rawPane.textContent = JSON.stringify(detail, null, 2);
      }

      function switchTab(tabKey) {
        const buttons = d.tabs.querySelectorAll(".tab-btn");
        const panes = document.querySelectorAll(".tab-pane");
        buttons.forEach((btn) => {
          btn.classList.toggle("active", btn.getAttribute("data-tab") === tabKey);
        });
        panes.forEach((pane) => {
          pane.classList.toggle("active", pane.id === `tab-${tabKey}`);
        });
      }

      function renderButtons() {
        const disabled = debugState.pending;
        d.startBtn.disabled = disabled;
        d.listSessionsBtn.disabled = disabled;
        d.syncBtn.disabled = disabled;
        d.resetBtn.disabled = disabled;
        d.stepChoiceBtn.disabled = disabled;
        d.stepInputBtn.disabled = disabled;
      }

      function renderAll() {
        renderSessionList();
        renderTimeline();
        renderOverview();
        renderTelemetry();
        renderVersions();
        renderInspector();
        renderButtons();
      }

      function resetAll() {
        debugState.pending = false;
        debugState.sessionId = null;
        debugState.sessions = [];
        debugState.bundle = null;
        debugState.selectedStep = null;
        debugState.idemCounter = 0;

        d.sessionId.value = "";
        d.choiceId.value = "";
        d.playerInput.value = "";
        setError("");
        switchTab("selection");
        renderAll();
      }

      d.startBtn.addEventListener("click", () => runAction(startSession));
      d.listSessionsBtn.addEventListener("click", () => runAction(loadSessions));
      d.syncBtn.addEventListener("click", () => runAction(syncBundle));
      d.resetBtn.addEventListener("click", resetAll);
      d.stepChoiceBtn.addEventListener("click", () => runAction(stepChoice));
      d.stepInputBtn.addEventListener("click", () => runAction(stepInput));

      d.tabs.addEventListener("click", (evt) => {
        const target = evt.target;
        if (!(target instanceof HTMLElement)) return;
        if (!target.classList.contains("tab-btn")) return;
        const tab = target.getAttribute("data-tab");
        if (!tab) return;
        switchTab(tab);
      });

      resetAll();
    </script>
  </body>
</html>
'''


@router.get("/play", response_class=HTMLResponse)
def play_page() -> HTMLResponse:
    return HTMLResponse(_PLAY_HTML)


@router.get("/play-dev", response_class=HTMLResponse)
def play_dev_page() -> HTMLResponse:
    return HTMLResponse(_PLAY_DEV_HTML)
