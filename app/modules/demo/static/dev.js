const Shared = window.DemoShared;

const state = {
  sessionId: null,
  steps: [],
  snapshots: [],
  currentState: {},
  totals: { tokensIn: 0, tokensOut: 0 },
  stepInFlight: false,
  bootstrap: null,
  stepController: null,
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
const runStatePanelEl = el("runStatePanel");
const pendingStatusEl = el("pendingStatus");

const nowIso = () => new Date().toISOString();

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

function renderPendingStatus(pending, meta = {}) {
  const maxAttempts = Number(meta.maxAttempts || state.stepController?.maxAttempts || 0);
  if (!pending) {
    pendingStatusEl.className = "pending-panel";
    pendingStatusEl.textContent = "(idle)";
    return;
  }

  const status = Number(pending.lastStatus || 0);
  const kind = pending.uncertain ? "pending-panel pending-panel--error" : "pending-panel pending-panel--active";
  pendingStatusEl.className = kind;
  pendingStatusEl.textContent = [
    `idempotency_key: ${pending.idempotencyKey}`,
    `attempts: ${pending.attempts}${maxAttempts ? ` / ${maxAttempts}` : ""}`,
    `last_status: ${status || "n/a"}`,
    `last_code: ${pending.lastErrorCode || "n/a"}`,
    `last_message: ${pending.lastErrorMessage || "n/a"}`,
    `uncertain: ${String(Boolean(pending.uncertain))}`,
  ].join("\n");
}

function renderStatePanel(stats) {
  state.currentState = cloneState(stats || {});
  const day = state.currentState.day ?? "n/a";
  const slot = state.currentState.slot ?? "n/a";
  statePanelEl.textContent = `day: ${day} | slot: ${slot}\n${JSON.stringify(state.currentState, null, 2)}`;
  renderQuestPanel(state.currentState.quest_state || {});
  renderRunPanel(state.currentState.run_state || {});
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

function renderRunPanel(runState) {
  const data = runState || {};
  const stepIndex = Number(data.step_index || 0);
  const triggeredEvents = Array.isArray(data.triggered_event_ids) ? data.triggered_event_ids : [];
  const eventCooldowns = data.event_cooldowns && typeof data.event_cooldowns === "object" ? data.event_cooldowns : {};
  const endingId = data.ending_id || "(none)";
  const endingOutcome = data.ending_outcome || "(none)";
  const endedAtStep = data.ended_at_step === null || data.ended_at_step === undefined ? "(none)" : data.ended_at_step;
  const fallbackCount = Number(data.fallback_count || 0);
  const lastEvent = triggeredEvents.length ? triggeredEvents[triggeredEvents.length - 1] : "(none)";

  runStatePanelEl.textContent = [
    `step_index: ${stepIndex}`,
    `triggered_events_count: ${triggeredEvents.length}`,
    `last_event: ${lastEvent}`,
    `fallback_count: ${fallbackCount}`,
    `ending_id: ${endingId}`,
    `ending_outcome: ${endingOutcome}`,
    `ended_at_step: ${endedAtStep}`,
    `event_cooldowns: ${JSON.stringify(eventCooldowns)}`,
  ].join("\n");
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
    btn.disabled = unavailable;
    if (!unavailable) {
      btn.onclick = () => sendStep({ choice_id: choice.id }).catch(alert);
    }
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
      <div><strong>run_ended</strong>: ${step.run_ended === null ? "n/a" : String(step.run_ended)}</div>
      <div><strong>ending_id</strong>: ${step.ending_id || "n/a"}</div>
      <div><strong>ending_outcome</strong>: ${step.ending_outcome || "n/a"}</div>
      <div><strong>day</strong>: ${dayText}</div>
      <div><strong>slot</strong>: ${slotText}</div>
      <div><strong>state_delta</strong>: ${stateDeltaText}</div>
      <div><strong>state_after</strong>: ${stateAfterText}</div>
      <div><strong>idempotency_key</strong>: ${step.idempotency_key || "n/a"}</div>
      <div><strong>attempts</strong>: ${step.attempts || "n/a"}</div>
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

function appendStep(raw, stateDelta, stateAfter, meta = {}) {
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
    run_ended: raw.run_ended ?? false,
    ending_id: raw.ending_id ?? null,
    ending_outcome: raw.ending_outcome ?? null,
    state_delta: stateDelta || {},
    state_after: stateAfter || {},
    idempotency_key: meta.idempotencyKey || null,
    attempts: meta.attempts ?? null,
    raw,
  };
  state.steps.push(step);
  renderStepCard(step);
  updateTokenTotals(step.cost);
}

async function loadBootstrap() {
  const payload = await Shared.callApi("GET", "/demo/bootstrap");
  state.bootstrap = payload;
  if (!el("storyId").value.trim() && payload.default_story_id) {
    el("storyId").value = String(payload.default_story_id);
  }
  if (!el("storyVersion").value.trim() && payload.default_story_version !== null && payload.default_story_version !== undefined) {
    el("storyVersion").value = String(payload.default_story_version);
  }

  state.stepController = Shared.createStepRetryController({
    maxAttempts: payload.step_retry_max_attempts,
    backoffMs: payload.step_retry_backoff_ms,
    onStatus: renderPendingStatus,
  });
}

async function createSession() {
  const storyId = el("storyId").value.trim();
  if (!storyId) {
    throw new Error("story_id is required");
  }
  const versionRaw = el("storyVersion").value.trim();
  const body = { story_id: storyId };
  if (versionRaw) body.version = Number(versionRaw);
  const out = await Shared.callApi("POST", "/sessions", body);
  state.stepController?.clearPending();
  setSessionId(out.id);
  state.steps = [];
  timelineEl.innerHTML = "";
  state.snapshots = [];
  updateSnapshotsDropdown();
  state.currentState = {};
  state.totals = { tokensIn: 0, tokensOut: 0 };
  tokenTotalsEl.textContent = "in: 0, out: 0";
  renderQuestPanel({});
  renderRunPanel({});
  await refreshSession();
}

async function refreshSession(options = {}) {
  if (!state.sessionId) return;
  const { renderNode = true } = options;
  const out = await Shared.callApi("GET", `/sessions/${state.sessionId}`);
  if (renderNode) {
    if (out.current_node) {
      renderNarrative(out.current_node.narrative_text || "(no current node narrative)", out.current_node.choices || []);
    } else {
      renderNarrative("(no current node narrative)", []);
    }
  }
  renderStatePanel(out.state_json || {});
  return out;
}

function _stepPayloadFromInput(payloadOverride) {
  const inputText = el("playerInput").value.trim();
  const payload = payloadOverride ? { ...payloadOverride } : {};
  if (!payload.choice_id && inputText) {
    payload.player_input = inputText;
  }
  return payload;
}

function _throwIfTerminalStepFailure(result) {
  if (result.reason === "LLM_UNAVAILABLE") {
    throw new Error("LLM_UNAVAILABLE: this step was not applied.");
  }
  if (result.reason === "IDEMPOTENCY_KEY_REUSED") {
    throw new Error("IDEMPOTENCY_KEY_REUSED: pending key conflicted with a different payload.");
  }
  const status = result.response ? result.response.status : "n/a";
  const code = result.response ? Shared.detailCode(result.response.data) : "n/a";
  throw new Error(`step failed (${status}) code=${code || "n/a"}`);
}

async function _executeStepPayload(payload) {
  if (!state.stepController) {
    throw new Error("step controller not initialized");
  }
  const stateBefore = cloneState(state.currentState);
  const result = await state.stepController.submit({ sessionId: state.sessionId, payload });

  if (!result.ok) {
    if (result.retryable) {
      throw new Error("Step request still uncertain after retries. Use Retry Pending to continue with the same key.");
    }
    _throwIfTerminalStepFailure(result);
  }

  const out = result.data;
  renderNarrative(out.narrative_text, out.choices);
  const refreshed = await refreshSession({ renderNode: false });
  const stateAfter = cloneState((refreshed || {}).state_json || state.currentState);
  const stateDelta = computeDelta(stateBefore, stateAfter);
  appendStep(out, stateDelta, stateAfter, result.meta || {});
  el("playerInput").value = "";
}

async function sendStep(payloadOverride) {
  if (!state.sessionId || state.stepInFlight) return;
  const payload = _stepPayloadFromInput(payloadOverride);
  if (Object.keys(payload).length === 0) return;

  state.stepInFlight = true;
  try {
    await _executeStepPayload(payload);
  } finally {
    state.stepInFlight = false;
  }
}

async function retryPendingStep() {
  if (!state.stepController || state.stepInFlight) return;
  const pending = state.stepController.getPending();
  if (!pending) {
    alert("No pending step to retry.");
    return;
  }

  state.stepInFlight = true;
  try {
    const stateBefore = cloneState(state.currentState);
    const result = await state.stepController.retryPending();
    if (!result.ok) {
      if (result.retryable) {
        throw new Error("Step remains uncertain after retry. Try again or clear pending.");
      }
      _throwIfTerminalStepFailure(result);
    }

    const out = result.data;
    renderNarrative(out.narrative_text, out.choices);
    const refreshed = await refreshSession({ renderNode: false });
    const stateAfter = cloneState((refreshed || {}).state_json || state.currentState);
    const stateDelta = computeDelta(stateBefore, stateAfter);
    appendStep(out, stateDelta, stateAfter, result.meta || {});
  } finally {
    state.stepInFlight = false;
  }
}

async function takeSnapshot() {
  if (!state.sessionId) return;
  const name = el("snapshotName").value.trim() || "manual";
  const out = await Shared.callApi("POST", `/sessions/${state.sessionId}/snapshot?name=${encodeURIComponent(name)}`);
  state.snapshots.push({ id: out.snapshot_id, name });
  updateSnapshotsDropdown();
}

async function rollbackSession() {
  if (!state.sessionId) return;
  const snapshotId = snapshotSelectEl.value;
  if (!snapshotId) return;
  await Shared.callApi("POST", `/sessions/${state.sessionId}/rollback?snapshot_id=${encodeURIComponent(snapshotId)}`);
  await refreshSession();
}

async function endSession() {
  if (!state.sessionId) return;
  await Shared.callApi("POST", `/sessions/${state.sessionId}/end`);
}

function renderReplayHighlights(payload) {
  if (!payload) {
    replayHighlightsEl.innerHTML = '<div class="card__body">No replay yet.</div>';
    replayRawEl.textContent = "{}";
    return;
  }

  const storyPath = (payload.story_path || []).slice(0, 6).map((row) => `#${row.step}: ${row.node_id} -> ${row.choice_id}`).join("\n");
  const keyDecisions = (payload.key_decisions || []).slice(0, 6).map((row) => `#${row.step_index}: ${JSON.stringify(row.final_action || {})}`).join("\n");
  const fallbackSummary = payload.fallback_summary ? JSON.stringify(payload.fallback_summary, null, 2) : "{}";
  const stateTimeline = (payload.state_timeline || []).slice(0, 6).map((row) => `#${row.step}: delta=${JSON.stringify(row.delta || {})} after=${JSON.stringify(row.state_after || {})}`).join("\n");
  const runSummary = payload.run_summary || {};

  replayHighlightsEl.innerHTML = `
    <div class="card__body">
      <strong>Story Path</strong>\n${storyPath || "(none)"}\n\n
      <strong>Key Decisions</strong>\n${keyDecisions || "(none)"}\n\n
      <strong>Fallback Summary</strong>\n${fallbackSummary}\n\n
      <strong>Run Summary</strong>\n${JSON.stringify(runSummary, null, 2)}\n\n
      <strong>State Timeline</strong>\n${stateTimeline || "(none)"}
    </div>
  `;
  replayRawEl.textContent = JSON.stringify(payload, null, 2);
}

async function replaySession() {
  if (!state.sessionId) return;
  const payload = await Shared.callApi("GET", `/sessions/${state.sessionId}/replay`);
  renderReplayHighlights(payload);
}

async function init() {
  await loadBootstrap();
  renderReplayHighlights(null);

  el("createSessionBtn").addEventListener("click", () => createSession().catch(alert));
  el("refreshSessionBtn").addEventListener("click", () => refreshSession().catch(alert));
  el("sendInputBtn").addEventListener("click", () => sendStep().catch(alert));
  el("retryPendingBtn").addEventListener("click", () => retryPendingStep().catch(alert));
  el("clearPendingBtn").addEventListener("click", () => state.stepController?.clearPending());
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
}

init().catch((error) => {
  alert(`demo init failed: ${error.message || error}`);
});
