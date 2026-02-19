const state = {
  sessionId: null,
  steps: [],
  snapshots: [],
  currentState: {},
  totals: { tokensIn: 0, tokensOut: 0 },
};

const el = (id) => document.getElementById(id);
const sessionEl = el("sessionId");
const tokenTotalsEl = el("tokenTotals");
const narrativeTextEl = el("narrativeText");
const choiceButtonsEl = el("choiceButtons");
const timelineEl = el("stepTimeline");
const snapshotSelectEl = el("snapshotSelect");
const replayHighlightsEl = el("replayHighlights");
const replayRawEl = el("replayRaw");
const statePanelEl = el("statePanel");
const questSummaryEl = el("questSummary");
const questRecentEl = el("questRecent");

const nowIso = () => new Date().toISOString();

function authHeaders() {
  const mode = el("authMode").value;
  const value = el("authValue").value.trim();
  if (!value) {
    return { "X-User-Id": "00000000-0000-0000-0000-000000000001" };
  }
  if (mode === "bearer") {
    return { Authorization: `Bearer ${value}` };
  }
  return { "X-User-Id": value };
}

async function callApi(method, url, body) {
  const headers = { ...authHeaders() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const resp = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let parsed;
  try {
    parsed = text ? JSON.parse(text) : {};
  } catch {
    parsed = text;
  }
  if (!resp.ok) {
    const error = typeof parsed === "object" ? JSON.stringify(parsed) : parsed;
    throw new Error(`${resp.status}: ${error}`);
  }
  return parsed;
}

function setSessionId(value) {
  state.sessionId = value;
  sessionEl.textContent = value || "(none)";
}

function cloneState(input) {
  return JSON.parse(JSON.stringify(input || {}));
}

function computeDelta(before, after) {
  const out = {};
  const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  keys.forEach((key) => {
    const beforeRaw = (before || {})[key];
    const afterRaw = (after || {})[key];
    if (typeof beforeRaw === "number" && typeof afterRaw === "number") {
      const diff = afterRaw - beforeRaw;
      if (diff !== 0) out[key] = diff;
      return;
    }
    if (JSON.stringify(beforeRaw) !== JSON.stringify(afterRaw)) {
      out[key] = afterRaw;
    }
  });
  return out;
}

function renderStatePanel(stats) {
  state.currentState = cloneState(stats || {});
  const day = state.currentState.day ?? "n/a";
  const slot = state.currentState.slot ?? "n/a";
  statePanelEl.textContent = `day: ${day} | slot: ${slot}\n${JSON.stringify(state.currentState, null, 2)}`;
  renderQuestPanel(state.currentState.quest_state || {});
}

function renderQuestPanel(questState) {
  const data = questState || {};
  const quests = data.quests || {};
  const active = Array.isArray(data.active_quests) ? data.active_quests : [];
  const completed = Array.isArray(data.completed_quests) ? data.completed_quests : [];

  if (!Object.keys(quests).length) {
    questSummaryEl.textContent = "(no quests)";
    questRecentEl.textContent = "(no recent quest events)";
    return;
  }

  const formatQuestLine = (questId) => {
    const entry = quests[questId] || {};
    const stages = entry.stages || {};
    const currentStageId = entry.current_stage_id || null;
    const currentStage = currentStageId ? stages[currentStageId] || {} : {};
    const milestones = currentStage.milestones || {};
    const milestoneIds = Object.keys(milestones);
    const doneMilestones = milestoneIds.filter((id) => milestones[id] && milestones[id].done);
    const status = entry.status || "inactive";
    const stageLabel = currentStageId || "-";
    return `- ${questId} [${status}] stage: ${stageLabel} progress: ${doneMilestones.length}/${milestoneIds.length}`;
  };

  const activeLines = active.length ? active.map(formatQuestLine).join("\n") : "(none)";
  const completedLines = completed.length ? completed.map(formatQuestLine).join("\n") : "(none)";
  questSummaryEl.textContent = `active (${active.length})\n${activeLines}\n\ncompleted (${completed.length})\n${completedLines}`;

  const recentEvents = Array.isArray(data.recent_events) ? data.recent_events.slice(-5) : [];
  if (!recentEvents.length) {
    questRecentEl.textContent = "(no recent quest events)";
    return;
  }
  questRecentEl.textContent = recentEvents
    .map((row) => {
      const seq = row.seq ?? "n/a";
      const type = row.type || "event";
      const questId = row.quest_id || "unknown";
      const stageId = row.stage_id ? `/${row.stage_id}` : "";
      const milestoneId = row.milestone_id ? `/${row.milestone_id}` : "";
      return `#${seq} ${type} ${questId}${stageId}${milestoneId}`;
    })
    .join("\n");
}

function updateTokenTotals(cost) {
  const tokensIn = Number(cost.tokens_in || 0);
  const tokensOut = Number(cost.tokens_out || 0);
  state.totals.tokensIn += tokensIn;
  state.totals.tokensOut += tokensOut;
  tokenTotalsEl.textContent = `in: ${state.totals.tokensIn}, out: ${state.totals.tokensOut}`;
}

function renderNarrative(narrativeText, choices) {
  narrativeTextEl.textContent = narrativeText || "(empty)";
  choiceButtonsEl.innerHTML = "";
  (choices || []).forEach((choice) => {
    const btn = document.createElement("button");
    const unavailable = choice.is_available === false;
    const reason = choice.unavailable_reason ? ` (locked: ${choice.unavailable_reason})` : "";
    btn.textContent = `${choice.text} (${choice.type})${reason}`;
    btn.classList.toggle("choice--locked", unavailable);
    btn.onclick = () => sendStep({ choice_id: choice.id });
    choiceButtonsEl.appendChild(btn);
  });
}

function renderStepCard(step) {
  const card = document.createElement("div");
  card.className = "step-card";
  const stateDeltaText = Object.keys(step.state_delta || {}).length ? JSON.stringify(step.state_delta) : "{}";
  const stateAfterText = Object.keys(step.state_after || {}).length ? JSON.stringify(step.state_after) : "{}";
  const dayText = step.state_after && step.state_after.day !== undefined ? step.state_after.day : "n/a";
  const slotText = step.state_after && step.state_after.slot !== undefined ? step.state_after.slot : "n/a";
  card.innerHTML = `
    <header>
      <span>${step.timestamp}</span>
      <span>node: ${step.node_id || "n/a"}</span>
    </header>
    <div class="meta">
      <div><strong>story_node_id</strong>: ${step.story_node_id || "n/a"}</div>
      <div><strong>provider</strong>: ${step.cost.provider || "none"}</div>
      <div><strong>tokens</strong>: ${step.cost.tokens_in || 0} in / ${step.cost.tokens_out || 0} out</div>
      <div><strong>attempted_choice_id</strong>: ${step.attempted_choice_id || "n/a"}</div>
      <div><strong>executed_choice_id</strong>: ${step.executed_choice_id || "n/a"}</div>
      <div><strong>resolved_choice_id</strong>: ${step.resolved_choice_id || "n/a"}</div>
      <div><strong>fallback_used</strong>: ${step.fallback_used === null ? "n/a" : String(step.fallback_used)}</div>
      <div><strong>fallback_reason</strong>: ${step.fallback_reason || "n/a"}</div>
      <div><strong>mapping_confidence</strong>: ${step.mapping_confidence === null ? "n/a" : step.mapping_confidence}</div>
      <div><strong>day</strong>: ${dayText}</div>
      <div><strong>slot</strong>: ${slotText}</div>
      <div><strong>state_delta</strong>: ${stateDeltaText}</div>
      <div><strong>state_after</strong>: ${stateAfterText}</div>
    </div>
    <details>
      <summary>Raw response</summary>
      <pre>${JSON.stringify(step.raw, null, 2)}</pre>
    </details>
  `;
  timelineEl.prepend(card);
}

function updateSnapshotsDropdown() {
  snapshotSelectEl.innerHTML = '<option value="">(none)</option>';
  state.snapshots.forEach((snap) => {
    const option = document.createElement("option");
    option.value = snap.id;
    option.textContent = `${snap.name} (${snap.id})`;
    snapshotSelectEl.appendChild(option);
  });
}

function appendStep(raw, stateDelta, stateAfter) {
  const step = {
    timestamp: nowIso(),
    node_id: raw.node_id,
    story_node_id: raw.story_node_id,
    cost: raw.cost || { provider: "none", tokens_in: 0, tokens_out: 0 },
    attempted_choice_id: raw.attempted_choice_id || null,
    executed_choice_id: raw.executed_choice_id || null,
    resolved_choice_id: raw.resolved_choice_id || null,
    fallback_used: raw.fallback_used ?? null,
    fallback_reason: raw.fallback_reason || null,
    mapping_confidence: raw.mapping_confidence ?? null,
    state_delta: stateDelta || {},
    state_after: stateAfter || {},
    raw,
  };
  state.steps.push(step);
  renderStepCard(step);
  updateTokenTotals(step.cost);
}

async function createSession() {
  const storyId = el("storyId").value.trim();
  if (!storyId) {
    throw new Error("story_id is required");
  }
  const versionRaw = el("storyVersion").value.trim();
  const body = { story_id: storyId };
  if (versionRaw) body.version = Number(versionRaw);
  const out = await callApi("POST", "/sessions", body);
  setSessionId(out.id);
  state.steps = [];
  timelineEl.innerHTML = "";
  state.snapshots = [];
  updateSnapshotsDropdown();
  state.currentState = {};
  state.totals = { tokensIn: 0, tokensOut: 0 };
  tokenTotalsEl.textContent = "in: 0, out: 0";
  renderQuestPanel({});
  await refreshSession();
}

async function refreshSession() {
  if (!state.sessionId) return;
  const out = await callApi("GET", `/sessions/${state.sessionId}`);
  narrativeTextEl.textContent = out.current_node ? out.current_node.narrative_text : "(no current node narrative)";
  renderStatePanel(out.state_json || {});
  return out;
}

async function sendStep(payloadOverride) {
  if (!state.sessionId) return;
  const stateBefore = cloneState(state.currentState);
  const inputText = el("playerInput").value.trim();
  const payload = payloadOverride || {};
  if (!payload.choice_id && inputText) {
    payload.player_input = inputText;
  }
  if (Object.keys(payload).length === 0) return;

  const out = await callApi("POST", `/sessions/${state.sessionId}/step`, payload);
  const refreshed = await refreshSession();
  const stateAfter = cloneState((refreshed || {}).state_json || state.currentState);
  const stateDelta = computeDelta(stateBefore, stateAfter);
  renderNarrative(out.narrative_text, out.choices);
  appendStep(out, stateDelta, stateAfter);
}

async function takeSnapshot() {
  if (!state.sessionId) return;
  const name = el("snapshotName").value.trim() || "manual";
  const out = await callApi("POST", `/sessions/${state.sessionId}/snapshot?name=${encodeURIComponent(name)}`);
  state.snapshots.push({ id: out.snapshot_id, name });
  updateSnapshotsDropdown();
}

async function rollbackSession() {
  if (!state.sessionId) return;
  const snapshotId = snapshotSelectEl.value;
  if (!snapshotId) return;
  await callApi("POST", `/sessions/${state.sessionId}/rollback?snapshot_id=${encodeURIComponent(snapshotId)}`);
  await refreshSession();
}

async function endSession() {
  if (!state.sessionId) return;
  await callApi("POST", `/sessions/${state.sessionId}/end`);
}

function renderReplayHighlights(payload) {
  if (!payload) {
    replayHighlightsEl.innerHTML = "<div class=\"card__body\">No replay yet.</div>";
    replayRawEl.textContent = "{}";
    return;
  }

  const storyPath = (payload.story_path || []).slice(0, 6).map((row) => `#${row.step}: ${row.node_id} -> ${row.choice_id}`).join("\n");
  const keyDecisions = (payload.key_decisions || []).slice(0, 6).map((row) => `#${row.step_index}: ${JSON.stringify(row.final_action || {})}`).join("\n");
  const fallbackSummary = payload.fallback_summary ? JSON.stringify(payload.fallback_summary, null, 2) : "{}";
  const stateTimeline = (payload.state_timeline || []).slice(0, 6).map((row) => `#${row.step}: delta=${JSON.stringify(row.delta || {})} after=${JSON.stringify(row.state_after || {})}`).join("\n");

  replayHighlightsEl.innerHTML = `
    <div class="card__body">
      <strong>Story Path</strong>\n${storyPath || "(none)"}\n\n
      <strong>Key Decisions</strong>\n${keyDecisions || "(none)"}\n\n
      <strong>Fallback Summary</strong>\n${fallbackSummary}\n\n
      <strong>State Timeline</strong>\n${stateTimeline || "(none)"}
    </div>
  `;
  replayRawEl.textContent = JSON.stringify(payload, null, 2);
}

async function replaySession() {
  if (!state.sessionId) return;
  const payload = await callApi("GET", `/sessions/${state.sessionId}/replay`);
  renderReplayHighlights(payload);
}

el("createSessionBtn").addEventListener("click", () => createSession().catch(alert));
el("refreshSessionBtn").addEventListener("click", () => refreshSession().catch(alert));
el("sendInputBtn").addEventListener("click", () => sendStep().catch(alert));
el("snapshotBtn").addEventListener("click", () => takeSnapshot().catch(alert));
el("rollbackBtn").addEventListener("click", () => rollbackSession().catch(alert));
el("endBtn").addEventListener("click", () => endSession().catch(alert));
el("replayBtn").addEventListener("click", () => replaySession().catch(alert));
el("copySessionBtn").addEventListener("click", async () => {
  if (!state.sessionId) return;
  try {
    await navigator.clipboard.writeText(state.sessionId);
  } catch {
    alert("Copy failed");
  }
});

renderReplayHighlights(null);
