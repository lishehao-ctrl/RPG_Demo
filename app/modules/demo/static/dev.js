const Shared = window.DemoShared;
const {
  mustEl,
  cloneJson,
  formatStoryPathLines,
  bindAsyncClick,
} = Shared;

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

const refs = {
  sessionEl: mustEl("sessionId"),
  tokenTotalsEl: mustEl("tokenTotals"),
  narrativeTextEl: mustEl("narrativeText"),
  choiceButtonsEl: mustEl("choiceButtons"),
  timelineEl: mustEl("stepTimeline"),
  snapshotSelectEl: mustEl("snapshotSelect"),
  replayHighlightsEl: mustEl("replayHighlights"),
  replayRawEl: mustEl("replayRaw"),
  statePanelEl: mustEl("statePanel"),
  questSummaryEl: mustEl("questSummary"),
  questRecentEl: mustEl("questRecent"),
  runStatePanelEl: mustEl("runStatePanel"),
  pendingStatusEl: mustEl("pendingStatus"),
  layerInspectorSummaryEl: mustEl("layerInspectorSummary"),
  layerInspectorStepsEl: mustEl("layerInspectorSteps"),
  refreshLayerInspectorBtnEl: mustEl("refreshLayerInspectorBtn"),
  noticeEl: mustEl("devNotice"),

  storyIdEl: mustEl("storyId"),
  storyVersionEl: mustEl("storyVersion"),
  createSessionBtnEl: mustEl("createSessionBtn"),
  refreshSessionBtnEl: mustEl("refreshSessionBtn"),
  sendInputBtnEl: mustEl("sendInputBtn"),
  playerInputEl: mustEl("playerInput"),
  retryPendingBtnEl: mustEl("retryPendingBtn"),
  clearPendingBtnEl: mustEl("clearPendingBtn"),
  snapshotNameEl: mustEl("snapshotName"),
  snapshotBtnEl: mustEl("snapshotBtn"),
  rollbackBtnEl: mustEl("rollbackBtn"),
  endBtnEl: mustEl("endBtn"),
  replayBtnEl: mustEl("replayBtn"),
  copySessionBtnEl: mustEl("copySessionBtn"),
};

const hasLayerInspectorPanel = Boolean(refs.layerInspectorSummaryEl && refs.layerInspectorStepsEl);

const nowIso = () => new Date().toISOString();

function setNotice(message, type = "info") {
  const text = String(message || "").trim();
  refs.noticeEl.textContent = text;
  refs.noticeEl.classList.toggle("hidden", !text);
  refs.noticeEl.classList.toggle("dev-notice--error", type === "error");
}

function clearNotice() {
  setNotice("");
}

function setSessionId(value) {
  state.sessionId = value;
  refs.sessionEl.textContent = value || "(none)";
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
    refs.pendingStatusEl.className = "pending-panel";
    refs.pendingStatusEl.textContent = "(idle)";
    return;
  }

  const status = Number(pending.lastStatus || 0);
  refs.pendingStatusEl.className = pending.uncertain ? "pending-panel pending-panel--error" : "pending-panel pending-panel--active";
  refs.pendingStatusEl.textContent = [
    `idempotency_key: ${pending.idempotencyKey}`,
    `attempts: ${pending.attempts}${maxAttempts ? ` / ${maxAttempts}` : ""}`,
    `last_status: ${status || "n/a"}`,
    `last_code: ${pending.lastErrorCode || "n/a"}`,
    `last_message: ${pending.lastErrorMessage || "n/a"}`,
    `uncertain: ${String(Boolean(pending.uncertain))}`,
  ].join("\n");
}

function renderStatePanel(stats) {
  state.currentState = cloneJson(stats || {});
  const day = state.currentState.day ?? "n/a";
  const slot = state.currentState.slot ?? "n/a";
  refs.statePanelEl.textContent = `day: ${day} | slot: ${slot}\n${JSON.stringify(state.currentState, null, 2)}`;
  renderQuestPanel(state.currentState.quest_state || {});
  renderRunPanel(state.currentState.run_state || {});
}

function renderQuestPanel(questState) {
  const data = questState || {};
  const quests = data.quests || {};
  const active = Array.isArray(data.active_quests) ? data.active_quests : [];
  const completed = Array.isArray(data.completed_quests) ? data.completed_quests : [];

  if (!Object.keys(quests).length) {
    refs.questSummaryEl.textContent = "(no quests)";
    refs.questRecentEl.textContent = "(no recent quest events)";
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

  refs.questSummaryEl.textContent = `active (${active.length})\n${activeLines}\n\ncompleted (${completed.length})\n${completedLines}`;

  const recentEvents = Array.isArray(data.recent_events) ? data.recent_events.slice(-5) : [];
  if (!recentEvents.length) {
    refs.questRecentEl.textContent = "(no recent quest events)";
    return;
  }

  refs.questRecentEl.textContent = recentEvents.map((row) => {
    const seq = row.seq ?? "n/a";
    const type = row.type || "event";
    const questId = row.quest_id || "unknown";
    const stageId = row.stage_id ? `/${row.stage_id}` : "";
    const milestoneId = row.milestone_id ? `/${row.milestone_id}` : "";
    return `#${seq} ${type} ${questId}${stageId}${milestoneId}`;
  }).join("\n");
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

  refs.runStatePanelEl.textContent = [
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

function compactText(value, fallback = "n/a") {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text || fallback;
}

function summarizeWorldLayer(layer) {
  const locale = compactText(layer?.locale, "en");
  const goal = compactText(layer?.mainline_goal, "an unspecified objective");
  const brief = compactText(layer?.global_brief, "");
  if (brief && brief !== "n/a") {
    return `Locale is ${locale}. The world framing centers on "${brief}", with mainline goal "${goal}".`;
  }
  return `Locale is ${locale}. The world framing currently supports mainline goal "${goal}".`;
}

function summarizeCharactersLayer(layer) {
  const activeCharacters = Array.isArray(layer?.active_characters) ? layer.active_characters : [];
  const roster = activeCharacters.slice(0, 3).join(", ") || "no explicit active names";
  const relation = compactText(layer?.relation_signal, "neutral relation signal");
  return `Active characters this step: ${roster}. Relationship pressure is ${relation}.`;
}

function summarizePlotLayer(layer) {
  const act = compactText(layer?.active_act, "unmapped act");
  const thread = compactText(layer?.active_thread, "no explicit sideline thread");
  const urgency = compactText(layer?.urgency, "steady");
  return `Plot focus is ${act} with thread "${thread}" and urgency "${urgency}".`;
}

function summarizeSceneLayer(layer) {
  const fromScene = compactText(layer?.from_scene, "unknown");
  const toScene = compactText(layer?.to_scene, "unknown");
  const question = compactText(layer?.dramatic_question, "no dramatic question available");
  return `Scene moved from ${fromScene} to ${toScene}. Current dramatic question: ${question}.`;
}

function summarizeActionLayer(layer) {
  const selectedAction = compactText(layer?.selected_action_id, "fallback action");
  const choice = compactText(layer?.resolved_choice_id, "no resolved choice");
  const confidence = typeof layer?.mapping_confidence === "number" ? layer.mapping_confidence.toFixed(2) : "n/a";
  return `Action execution resolved to ${selectedAction} via choice ${choice} (mapping confidence ${confidence}).`;
}

function summarizeConsequenceLayer(layer) {
  const delta = layer?.state_delta && typeof layer.state_delta === "object" ? layer.state_delta : {};
  const keys = Object.keys(delta);
  const deltaText = keys.length
    ? keys.slice(0, 4).map((key) => `${key}:${delta[key]}`).join(", ")
    : "no material state delta";
  const guardSignals = [];
  if (layer?.all_blocked_guard_triggered) guardSignals.push("all-blocked guard triggered");
  if (layer?.stall_guard_triggered) guardSignals.push("stall guard triggered");
  const guardText = guardSignals.length ? guardSignals.join("; ") : "no guard escalation";
  return `Consequence update: ${deltaText}. Guard status: ${guardText}.`;
}

function summarizeEndingLayer(layer) {
  const runEnded = layer?.run_ended === true;
  const endingId = compactText(layer?.ending_id, "none");
  const endingOutcome = compactText(layer?.ending_outcome, "in_progress");
  if (runEnded) {
    return `Run ended with ending ${endingId} (${endingOutcome}).`;
  }
  return `Run is still in progress; latest ending check is ${endingId} (${endingOutcome}).`;
}

function summarizeLayerPayload(name, payload) {
  switch (name) {
    case "world_layer":
      return summarizeWorldLayer(payload);
    case "characters_layer":
      return summarizeCharactersLayer(payload);
    case "plot_layer":
      return summarizePlotLayer(payload);
    case "scene_layer":
      return summarizeSceneLayer(payload);
    case "action_layer":
      return summarizeActionLayer(payload);
    case "consequence_layer":
      return summarizeConsequenceLayer(payload);
    case "ending_layer":
      return summarizeEndingLayer(payload);
    default:
      return "No narrative summary available for this layer.";
  }
}

function renderLayerStepCard(step) {
  const card = document.createElement("article");
  card.className = "layer-step-card";
  const stepIndex = Number(step?.step_index || 0);
  const rawRefs = step?.raw_refs || {};
  const consequence = step?.consequence_layer || {};
  const guardNotes = [];
  if (consequence.all_blocked_guard_triggered) guardNotes.push("all-blocked-guard");
  if (consequence.stall_guard_triggered) guardNotes.push("stall-guard");

  const header = document.createElement("header");
  header.innerHTML = `
    <span>step_index: ${stepIndex}</span>
    <span>action_log_id: ${rawRefs.action_log_id || "n/a"}</span>
    <span>guards: ${guardNotes.length ? guardNotes.join(", ") : "none"}</span>
  `;
  card.appendChild(header);

  const layers = [
    ["world_layer", step?.world_layer || {}],
    ["characters_layer", step?.characters_layer || {}],
    ["plot_layer", step?.plot_layer || {}],
    ["scene_layer", step?.scene_layer || {}],
    ["action_layer", step?.action_layer || {}],
    ["consequence_layer", step?.consequence_layer || {}],
    ["ending_layer", step?.ending_layer || {}],
  ];

  const grid = document.createElement("div");
  grid.className = "layer-step-grid";

  layers.forEach(([name, payload]) => {
    const block = document.createElement("section");
    block.className = "layer-step-block";

    const title = document.createElement("h4");
    title.textContent = name.replace("_layer", "").replaceAll("_", " ");
    block.appendChild(title);

    const summary = document.createElement("p");
    summary.textContent = summarizeLayerPayload(name, payload);
    block.appendChild(summary);

    const details = document.createElement("details");
    const detailSummary = document.createElement("summary");
    detailSummary.textContent = "Raw payload";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(payload || {}, null, 2);
    details.appendChild(detailSummary);
    details.appendChild(pre);
    block.appendChild(details);

    grid.appendChild(block);
  });

  card.appendChild(grid);
  return card;
}

function renderLayerInspector(payload) {
  if (!hasLayerInspectorPanel) return;
  if (!payload) {
    refs.layerInspectorSummaryEl.textContent = "(no layer summary)";
    refs.layerInspectorStepsEl.textContent = "(no layer steps)";
    return;
  }

  const summary = payload.summary || {};
  const fallbackRate = Number(summary.fallback_rate ?? 0);
  const mismatchCount = Number(summary.mismatch_count ?? 0);
  const eventTurns = Number(summary.event_turns ?? 0);
  const blockedTurns = Number(summary.guard_all_blocked_turns ?? 0);
  const stallTurns = Number(summary.guard_stall_turns ?? 0);
  const endingState = summary.ending_state || "in_progress";
  refs.layerInspectorSummaryEl.textContent = [
    `Session ${payload.session_id || "n/a"} is running in ${payload.env || "n/a"} mode.`,
    `Fallback rate is ${fallbackRate}, with ${mismatchCount} intent-action mismatches and ${eventTurns} event-heavy turns.`,
    `Guard pressure shows ${blockedTurns} all-blocked turns and ${stallTurns} stall turns.`,
    `Ending state is currently ${endingState}.`,
  ].join(" ");

  refs.layerInspectorStepsEl.innerHTML = "";
  const steps = Array.isArray(payload.steps) ? payload.steps : [];
  if (!steps.length) {
    refs.layerInspectorStepsEl.textContent = "(no layer steps)";
    return;
  }
  steps.forEach((step) => {
    refs.layerInspectorStepsEl.appendChild(renderLayerStepCard(step));
  });
}

async function refreshLayerInspector() {
  if (!hasLayerInspectorPanel) return null;
  if (!state.sessionId) {
    renderLayerInspector(null);
    return null;
  }

  try {
    const payload = await Shared.callApi("GET", `/sessions/${state.sessionId}/debug/layer-inspector`);
    renderLayerInspector(payload);
    return payload;
  } catch (error) {
    const status = Number(error?.response?.status || 0);
    const code = Shared.detailCode(error?.response?.data);

    if (status === 404 && code === "DEBUG_DISABLED") {
      refs.layerInspectorSummaryEl.textContent = "Layer inspector debug is disabled outside ENV=dev.";
      refs.layerInspectorStepsEl.textContent = "(debug disabled)";
      return null;
    }

    refs.layerInspectorSummaryEl.textContent = `Failed to load layer inspector: ${error.message || error}`;
    refs.layerInspectorStepsEl.textContent = "(layer inspector unavailable)";
    setNotice(`Layer inspector failed: ${error.message || error}`, "error");
    return null;
  }
}

function renderNarrative(narrativeText, choices) {
  refs.narrativeTextEl.textContent = narrativeText || "(empty)";
  refs.choiceButtonsEl.innerHTML = "";

  (choices || []).forEach((choice) => {
    const btn = document.createElement("button");
    const unavailable = choice.is_available === false;
    const reason = choice.unavailable_reason ? ` (locked: ${choice.unavailable_reason})` : "";
    btn.textContent = `${choice.text} (${choice.type})${reason}`;
    btn.classList.toggle("choice--locked", unavailable);
    btn.disabled = unavailable;
    if (!unavailable) {
      btn.addEventListener("click", () => {
        sendStep({ choice_id: choice.id }).catch((error) => {
          setNotice(error.message || String(error), "error");
        });
      });
    }
    refs.choiceButtonsEl.appendChild(btn);
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
      <span>story node: ${step.story_node_id || "n/a"}</span>
    </header>
    <div class="meta">
      <div><strong>story_node_id</strong>: ${step.story_node_id || "n/a"}</div>
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

  refs.timelineEl.prepend(card);
}

function updateSnapshotsDropdown() {
  refs.snapshotSelectEl.innerHTML = '<option value="">(none)</option>';
  state.snapshots.forEach((snap) => {
    const option = document.createElement("option");
    option.value = snap.id;
    option.textContent = `${snap.name} (${snap.id})`;
    refs.snapshotSelectEl.appendChild(option);
  });
}

function appendStep(raw, stateDelta, stateAfter, meta = {}) {
  const step = {
    timestamp: nowIso(),
    story_node_id: raw.story_node_id,
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
}

async function loadBootstrap() {
  const payload = await Shared.callApi("GET", "/demo/bootstrap");
  state.bootstrap = payload;

  if (!refs.storyIdEl.value.trim() && payload.default_story_id) {
    refs.storyIdEl.value = String(payload.default_story_id);
  }
  if (!refs.storyVersionEl.value.trim() && payload.default_story_version !== null && payload.default_story_version !== undefined) {
    refs.storyVersionEl.value = String(payload.default_story_version);
  }

  state.stepController = Shared.createStepRetryController({
    maxAttempts: payload.step_retry_max_attempts,
    backoffMs: payload.step_retry_backoff_ms,
    onStatus: renderPendingStatus,
  });
}

function resetSessionPanels() {
  state.steps = [];
  refs.timelineEl.innerHTML = "";
  state.snapshots = [];
  updateSnapshotsDropdown();
  state.currentState = {};
  state.totals = { tokensIn: 0, tokensOut: 0 };
  refs.tokenTotalsEl.textContent = "in: 0, out: 0";
  renderQuestPanel({});
  renderRunPanel({});
  renderReplayHighlights(null);
  renderLayerInspector(null);
}

async function createSession() {
  const storyId = refs.storyIdEl.value.trim();
  if (!storyId) {
    throw new Error("story_id is required");
  }

  const versionRaw = refs.storyVersionEl.value.trim();
  const body = { story_id: storyId };
  if (versionRaw) body.version = Number(versionRaw);

  const out = await Shared.callApi("POST", "/sessions", body);
  state.stepController?.clearPending();
  setSessionId(out.id);
  resetSessionPanels();
  await refreshSession();
  await refreshLayerInspector();
  setNotice(`Session ready: ${out.id}`);
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

function stepPayloadFromInput(payloadOverride) {
  const inputText = refs.playerInputEl.value.trim();
  const payload = payloadOverride ? { ...payloadOverride } : {};
  if (!payload.choice_id && inputText) {
    payload.player_input = inputText;
  }
  return payload;
}

function throwIfTerminalStepFailure(result) {
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

async function executeStepPayload(payload) {
  if (!state.stepController) {
    throw new Error("step controller not initialized");
  }

  const stateBefore = cloneJson(state.currentState);
  const result = await state.stepController.submit({ sessionId: state.sessionId, payload });

  if (!result.ok) {
    if (result.retryable) {
      throw new Error("Step request still uncertain after retries. Use Retry Pending to continue with the same key.");
    }
    throwIfTerminalStepFailure(result);
  }

  const out = result.data;
  renderNarrative(out.narrative_text, out.choices);

  const refreshed = await refreshSession({ renderNode: false });
  const stateAfter = cloneJson((refreshed || {}).state_json || state.currentState);
  const stateDelta = computeDelta(stateBefore, stateAfter);
  appendStep(out, stateDelta, stateAfter, result.meta || {});
  await refreshLayerInspector();

  refs.playerInputEl.value = "";
}

async function sendStep(payloadOverride) {
  if (!state.sessionId || state.stepInFlight) return;
  const payload = stepPayloadFromInput(payloadOverride);
  if (Object.keys(payload).length === 0) return;

  state.stepInFlight = true;
  try {
    await executeStepPayload(payload);
    clearNotice();
  } finally {
    state.stepInFlight = false;
  }
}

async function retryPendingStep() {
  if (!state.stepController || state.stepInFlight) return;
  const pending = state.stepController.getPending();
  if (!pending) {
    throw new Error("No pending step to retry.");
  }

  state.stepInFlight = true;
  try {
    const stateBefore = cloneJson(state.currentState);
    const result = await state.stepController.retryPending();

    if (!result.ok) {
      if (result.retryable) {
        throw new Error("Step remains uncertain after retry. Try again or clear pending.");
      }
      throwIfTerminalStepFailure(result);
    }

    const out = result.data;
    renderNarrative(out.narrative_text, out.choices);
    const refreshed = await refreshSession({ renderNode: false });
    const stateAfter = cloneJson((refreshed || {}).state_json || state.currentState);
    const stateDelta = computeDelta(stateBefore, stateAfter);
    appendStep(out, stateDelta, stateAfter, result.meta || {});
    await refreshLayerInspector();
    clearNotice();
  } finally {
    state.stepInFlight = false;
  }
}

async function takeSnapshot() {
  if (!state.sessionId) return;
  const name = refs.snapshotNameEl.value.trim() || "manual";
  const out = await Shared.callApi("POST", `/sessions/${state.sessionId}/snapshot?name=${encodeURIComponent(name)}`);
  state.snapshots.push({ id: out.snapshot_id, name });
  updateSnapshotsDropdown();
  setNotice(`Snapshot created: ${out.snapshot_id}`);
}

async function rollbackSession() {
  if (!state.sessionId) return;
  const snapshotId = refs.snapshotSelectEl.value;
  if (!snapshotId) return;
  await Shared.callApi("POST", `/sessions/${state.sessionId}/rollback?snapshot_id=${encodeURIComponent(snapshotId)}`);
  await refreshSession();
  await refreshLayerInspector();
  setNotice(`Rolled back to: ${snapshotId}`);
}

async function endSession() {
  if (!state.sessionId) return;
  await Shared.callApi("POST", `/sessions/${state.sessionId}/end`);
  setNotice("Session marked as ended.");
}

function renderReplayHighlights(payload) {
  if (!payload) {
    refs.replayHighlightsEl.innerHTML = '<div class="card__body">No replay yet.</div>';
    refs.replayRawEl.textContent = "{}";
    return;
  }

  const storyPath = formatStoryPathLines(payload.story_path, 6).join("\n");
  const keyDecisions = (payload.key_decisions || []).slice(0, 6).map((row) => `#${row.step_index}: ${JSON.stringify(row.final_action || {})}`).join("\n");
  const fallbackSummary = payload.fallback_summary ? JSON.stringify(payload.fallback_summary, null, 2) : "{}";
  const stateTimeline = (payload.state_timeline || []).slice(0, 6).map((row) => {
    return `#${row.step}: delta=${JSON.stringify(row.delta || {})} after=${JSON.stringify(row.state_after || {})}`;
  }).join("\n");
  const runSummary = payload.run_summary || {};

  refs.replayHighlightsEl.innerHTML = `
    <div class="card__body">
      <strong>Story Path</strong>\n${storyPath || "(none)"}\n\n
      <strong>Key Decisions</strong>\n${keyDecisions || "(none)"}\n\n
      <strong>Fallback Summary</strong>\n${fallbackSummary}\n\n
      <strong>Run Summary</strong>\n${JSON.stringify(runSummary, null, 2)}\n\n
      <strong>State Timeline</strong>\n${stateTimeline || "(none)"}
    </div>
  `;
  refs.replayRawEl.textContent = JSON.stringify(payload, null, 2);
}

async function replaySession() {
  if (!state.sessionId) return;
  const payload = await Shared.callApi("GET", `/sessions/${state.sessionId}/replay`);
  renderReplayHighlights(payload);
  setNotice("Replay refreshed.");
}

function bindAsync(button, handler) {
  bindAsyncClick(button, handler, (error) => {
    setNotice(error.message || String(error), "error");
  });
}

async function init() {
  await loadBootstrap();
  renderReplayHighlights(null);
  renderLayerInspector(null);

  bindAsync(refs.createSessionBtnEl, createSession);
  bindAsync(refs.refreshSessionBtnEl, async () => {
    await refreshSession();
    await refreshLayerInspector();
    setNotice("Session refreshed.");
  });
  bindAsync(refs.refreshLayerInspectorBtnEl, async () => {
    await refreshLayerInspector();
    setNotice("Layer inspector refreshed.");
  });
  bindAsync(refs.sendInputBtnEl, () => sendStep());
  bindAsync(refs.retryPendingBtnEl, () => retryPendingStep());

  refs.clearPendingBtnEl.addEventListener("click", () => {
    state.stepController?.clearPending();
    setNotice("Pending request cleared.");
  });

  bindAsync(refs.snapshotBtnEl, takeSnapshot);
  bindAsync(refs.rollbackBtnEl, rollbackSession);
  bindAsync(refs.endBtnEl, endSession);
  bindAsync(refs.replayBtnEl, replaySession);

  refs.copySessionBtnEl.addEventListener("click", async () => {
    if (!state.sessionId) return;
    try {
      await navigator.clipboard.writeText(state.sessionId);
      setNotice("Session ID copied.");
    } catch {
      setNotice("Copy failed.", "error");
    }
  });
}

init().catch((error) => {
  setNotice(`demo init failed: ${error.message || error}`, "error");
});
