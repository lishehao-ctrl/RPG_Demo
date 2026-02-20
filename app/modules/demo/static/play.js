const Shared = window.DemoShared;

const state = {
  viewMode: "boot_loading",
  stories: [],
  selectedStory: null,
  activeRunSession: null,
  currentState: {},
  bootstrap: null,
  stepController: null,
  stepInFlight: false,
};

const CHOICE_TYPE_LABEL = {
  study: "Study",
  work: "Work",
  rest: "Rest",
  date: "Social",
  gift: "Gift",
};

const LOCK_REASON_LABEL = {
  BLOCKED_MIN_MONEY: "Need more money",
  BLOCKED_MIN_ENERGY: "Need more energy",
  BLOCKED_MIN_AFFECTION: "Relationship not high enough",
  BLOCKED_DAY_AT_LEAST: "Available on later days",
  BLOCKED_SLOT_IN: "Not available at this time of day",
  FALLBACK_CONFIG_INVALID: "Temporarily unavailable",
  BLOCKED: "Unavailable for now",
};

const QUEST_EVENT_LABEL = {
  milestone_completed: "Milestone reached",
  stage_completed: "Stage completed",
  stage_activated: "New stage started",
  quest_completed: "Quest completed",
};

const numberFormatter = new Intl.NumberFormat("en-US");

const el = (id) => document.getElementById(id);

const storyMetaPillEl = el("storyMetaPill");
const narrativeTextEl = el("narrativeText");
const choiceButtonsEl = el("choiceButtons");
const storyListEl = el("storyList");
const storySelectErrorEl = el("storySelectError");
const playErrorEl = el("playError");
const storySelectSectionEl = el("storySelectSection");
const playSectionEl = el("playSection");
const pendingStatusEl = el("pendingStatus");
const startStoryBtnEl = el("startStoryBtn");
const runSummaryPanelEl = el("runSummaryPanel");

const energyValueEl = el("energyValue");
const energyBarEl = el("energyBar");
const moneyValueEl = el("moneyValue");
const moneyTierEl = el("moneyTier");
const knowledgeValueEl = el("knowledgeValue");
const knowledgeBarEl = el("knowledgeBar");
const knowledgeTierEl = el("knowledgeTier");
const affectionValueEl = el("affectionValue");
const affectionBarEl = el("affectionBar");
const affectionToneEl = el("affectionTone");

const activeQuestListEl = el("activeQuestList");
const completedQuestListEl = el("completedQuestList");
const questRecentListEl = el("questRecentList");

const runStepValueEl = el("runStepValue");
const runFallbackValueEl = el("runFallbackValue");
const runEndingValueEl = el("runEndingValue");
const runEventValueEl = el("runEventValue");

const replayStoryPathEl = el("replayStoryPath");
const replayKeyDecisionsEl = el("replayKeyDecisions");
const replayRunSummaryEl = el("replayRunSummary");

function setViewMode(nextPhase) {
  state.viewMode = String(nextPhase || "unknown");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)));
}

function cloneState(input) {
  return JSON.parse(JSON.stringify(input || {}));
}

function showError(targetEl, message) {
  if (!targetEl) return;
  const text = String(message || "").trim();
  targetEl.textContent = text;
  targetEl.classList.toggle("hidden", !text);
}

function clearError(targetEl) {
  showError(targetEl, "");
}

function setSummaryList(listEl, items, emptyText) {
  listEl.innerHTML = "";
  if (!items || !items.length) {
    const row = document.createElement("li");
    row.className = "summary-list--empty";
    row.textContent = emptyText;
    listEl.appendChild(row);
    return;
  }
  items.forEach((line) => {
    const row = document.createElement("li");
    row.textContent = line;
    listEl.appendChild(row);
  });
}

function lockReasonLabel(code) {
  if (!code) return "Unavailable for now";
  return LOCK_REASON_LABEL[code] || "Unavailable for now";
}

function choiceTypeLabel(type) {
  const key = String(type || "").toLowerCase();
  return CHOICE_TYPE_LABEL[key] || "Action";
}

function eventTypeLabel(type) {
  const key = String(type || "").trim();
  return QUEST_EVENT_LABEL[key] || "Progress updated";
}

function switchToStorySelect() {
  storySelectSectionEl.classList.remove("hidden");
  playSectionEl.classList.add("hidden");
  setViewMode("story_select");
}

function switchToPlaying() {
  storySelectSectionEl.classList.add("hidden");
  playSectionEl.classList.remove("hidden");
  setViewMode("playing");
}

function renderPendingStatus(pending, meta = {}) {
  const maxAttempts = Number(meta.maxAttempts || state.stepController?.maxAttempts || 0);
  if (!pending) {
    pendingStatusEl.textContent = "No pending action.";
    return;
  }
  if (pending.uncertain) {
    pendingStatusEl.textContent = "Previous step is still pending. Click Retry Pending to continue with the same action.";
    return;
  }
  const attemptsText = maxAttempts ? `${pending.attempts}/${maxAttempts}` : `${pending.attempts}`;
  pendingStatusEl.textContent = `Processing action... attempt ${attemptsText}.`;
}

function renderStoryList() {
  storyListEl.innerHTML = "";
  const stories = Array.isArray(state.stories) ? state.stories : [];

  if (!stories.length) {
    const empty = document.createElement("div");
    empty.className = "story-card";
    empty.innerHTML = "<div class=\"story-card__title\">(no playable stories)</div>";
    storyListEl.appendChild(empty);
    startStoryBtnEl.disabled = true;
    return;
  }

  stories.forEach((story) => {
    const key = `${story.story_id}@${story.version}`;
    const selected = state.selectedStory && `${state.selectedStory.story_id}@${state.selectedStory.version}` === key;
    const card = document.createElement("button");
    card.type = "button";
    card.className = `story-card story-card--button${selected ? " story-card--selected" : ""}`;
    card.innerHTML = [
      `<div class=\"story-card__title\">${story.title}</div>`,
      `<div class=\"story-card__meta\">${story.story_id}@${story.version}</div>`,
      `<div class=\"story-card__summary\">${story.summary || "No summary provided."}</div>`,
    ].join("");
    card.onclick = () => {
      state.selectedStory = story;
      renderStoryList();
      clearError(storySelectErrorEl);
    };
    storyListEl.appendChild(card);
  });

  startStoryBtnEl.disabled = !state.selectedStory;
}

function _moneyTierLabel(money) {
  if (money < 20) return "tight";
  if (money <= 100) return "stable";
  return "comfortable";
}

function _knowledgeTierLabel(knowledge) {
  if (knowledge < 10) return "novice";
  if (knowledge <= 29) return "developing";
  return "advanced";
}

function _affectionToneLabel(affection) {
  if (affection < -20) return "distant";
  if (affection > 20) return "warm";
  return "neutral";
}

function renderMetaPill(current) {
  const day = Number(current.day || 1);
  const slotRaw = String(current.slot || "morning");
  const slot = slotRaw.charAt(0).toUpperCase() + slotRaw.slice(1);
  storyMetaPillEl.textContent = `Day ${day} • ${slot}`;
}

function renderCoreStats(current) {
  const energy = clamp(current.energy, 0, 100);
  const money = Number(current.money || 0);
  const knowledge = Math.max(0, Number(current.knowledge || 0));
  const affection = clamp(Number(current.affection || 0), -100, 100);

  energyValueEl.textContent = `${energy}/100`;
  energyBarEl.style.width = `${energy}%`;

  moneyValueEl.textContent = numberFormatter.format(money);
  moneyTierEl.textContent = _moneyTierLabel(money);

  knowledgeValueEl.textContent = numberFormatter.format(knowledge);
  knowledgeBarEl.style.width = `${clamp((knowledge / 999) * 100, 0, 100)}%`;
  knowledgeTierEl.textContent = _knowledgeTierLabel(knowledge);

  affectionValueEl.textContent = affection >= 0 ? `+${affection}` : `${affection}`;
  affectionBarEl.style.width = `${clamp(((affection + 100) / 200) * 100, 0, 100)}%`;
  affectionToneEl.textContent = _affectionToneLabel(affection);
}

function renderQuestSummary(questState) {
  const data = questState || {};
  const quests = data.quests || {};
  const activeIds = Array.isArray(data.active_quests) ? data.active_quests : [];
  const completedIds = Array.isArray(data.completed_quests) ? data.completed_quests : [];

  const activeRows = activeIds.map((questId) => {
    const entry = quests[questId] || {};
    const currentStageId = entry.current_stage_id || "-";
    const stageMap = entry.stages || {};
    const stageEntry = stageMap[currentStageId] || {};
    const milestones = stageEntry.milestones || {};
    const milestoneIds = Object.keys(milestones);
    const doneCount = milestoneIds.filter((id) => milestones[id]?.done).length;
    return `${questId}: ${currentStageId} (${doneCount}/${milestoneIds.length})`;
  });

  const completedRows = completedIds.map((questId) => `${questId}`);

  const recent = Array.isArray(data.recent_events) ? data.recent_events.slice(-3) : [];
  const recentRows = recent.map((event) => {
    const eventLabel = eventTypeLabel(event.type);
    const questId = event.quest_id || "Quest";
    const milestone = event.milestone_id ? ` · ${event.milestone_id}` : "";
    return `${eventLabel}: ${questId}${milestone}`;
  });

  setSummaryList(activeQuestListEl, activeRows, "No active quests.");
  setSummaryList(completedQuestListEl, completedRows, "No completed quests yet.");
  setSummaryList(questRecentListEl, recentRows, "No recent quest updates.");
}

function renderRunSummary(runState) {
  const data = runState || {};
  const stepIndex = Number(data.step_index || 0);
  const fallbackCount = Number(data.fallback_count || 0);
  const endingId = String(data.ending_id || "").trim();
  const endingOutcome = String(data.ending_outcome || "").trim();
  const triggeredCount = Array.isArray(data.triggered_event_ids) ? data.triggered_event_ids.length : 0;

  runStepValueEl.textContent = String(stepIndex);
  runFallbackValueEl.textContent = String(fallbackCount);
  runEventValueEl.textContent = String(triggeredCount);

  if (!endingId) {
    runEndingValueEl.textContent = "In progress";
  } else if (endingOutcome) {
    runEndingValueEl.textContent = `${endingId} (${endingOutcome})`;
  } else {
    runEndingValueEl.textContent = endingId;
  }
}

function renderState(stateJson) {
  const current = cloneState(stateJson || {});
  state.currentState = current;
  renderMetaPill(current);
  renderCoreStats(current);
  renderQuestSummary(current.quest_state || {});
  renderRunSummary(current.run_state || {});
}

function renderNarrative(text, choices) {
  narrativeTextEl.textContent = text || "(empty)";
  choiceButtonsEl.innerHTML = "";
  (choices || []).forEach((choice) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "choice-card";

    const unavailable = choice.is_available === false;
    const typeLabel = choiceTypeLabel(choice.type);
    const lockLabel = unavailable ? lockReasonLabel(choice.unavailable_reason) : "";

    btn.innerHTML = [
      `<div class=\"choice-card__title\">${choice.text}</div>`,
      "<div class=\"choice-card__meta\">",
      `<span class=\"choice-badge\">${typeLabel}</span>`,
      unavailable ? `<span class=\"choice-lock\">${lockLabel}</span>` : "",
      "</div>",
    ].join("");

    btn.disabled = unavailable;
    if (!unavailable) {
      btn.onclick = () => sendStep({ choice_id: choice.id }).catch((error) => showError(playErrorEl, error.message || String(error)));
    }
    choiceButtonsEl.appendChild(btn);
  });
}

async function loadBootstrap() {
  const payload = await Shared.callApi("GET", "/demo/bootstrap");
  state.bootstrap = payload;
  state.stepController = Shared.createStepRetryController({
    maxAttempts: payload.step_retry_max_attempts,
    backoffMs: payload.step_retry_backoff_ms,
    onStatus: renderPendingStatus,
  });
}

async function loadStories() {
  clearError(storySelectErrorEl);
  const payload = await Shared.listStories({ publishedOnly: true, playableOnly: true });
  const stories = Array.isArray(payload?.stories) ? payload.stories : [];
  state.stories = stories;

  if (!state.selectedStory && stories.length > 0) {
    state.selectedStory = stories[0];
  } else if (
    state.selectedStory
    && !stories.some((item) => item.story_id === state.selectedStory.story_id && Number(item.version) === Number(state.selectedStory.version))
  ) {
    state.selectedStory = stories.length ? stories[0] : null;
  }
  renderStoryList();
}

function resetReplaySummary() {
  setSummaryList(replayStoryPathEl, [], "Run not ended yet.");
  setSummaryList(replayKeyDecisionsEl, [], "No decision summary yet.");
  setSummaryList(replayRunSummaryEl, [], "No run summary yet.");
  runSummaryPanelEl.open = false;
}

async function createSessionFromSelection() {
  if (!state.selectedStory) {
    throw new Error("Please select a story first.");
  }

  clearError(storySelectErrorEl);
  clearError(playErrorEl);
  setViewMode("creating_session");

  const body = { story_id: state.selectedStory.story_id };
  if (state.selectedStory.version !== null && state.selectedStory.version !== undefined) {
    body.version = Number(state.selectedStory.version);
  }

  const out = await Shared.callApi("POST", "/sessions", body);
  state.activeRunSession = out.id;
  state.stepController?.clearPending();
  resetReplaySummary();
  switchToPlaying();
  await refreshSession({ renderNode: true });
}

async function refreshSession(options = {}) {
  if (!state.activeRunSession) return null;
  const { renderNode = true } = options;
  const out = await Shared.callApi("GET", `/sessions/${state.activeRunSession}`);
  if (renderNode) {
    const node = out.current_node || {};
    renderNarrative(node.narrative_text || "(no current node narrative)", node.choices || []);
  }
  renderState(out.state_json || {});
  if (String(out.status || "").toLowerCase() === "ended") {
    setViewMode("ended");
  } else if (state.viewMode !== "pending_retry") {
    setViewMode("playing");
  }
  return out;
}

function _stepPayload(payloadOverride) {
  const inputText = el("playerInput").value.trim();
  const payload = payloadOverride ? { ...payloadOverride } : {};
  if (!payload.choice_id && inputText) {
    payload.player_input = inputText;
  }
  return payload;
}

function _terminalError(result) {
  if (result.reason === "LLM_UNAVAILABLE") {
    return "Narration is temporarily unavailable. This step was not applied.";
  }
  if (result.reason === "IDEMPOTENCY_KEY_REUSED") {
    return "Request conflict detected. Please start a new run.";
  }
  if (result.reason === "REQUEST_IN_PROGRESS") {
    return "Previous step is still processing. Please retry pending action.";
  }
  return "Action could not be completed. Please try again.";
}

async function sendStep(payloadOverride) {
  if (!state.activeRunSession || state.stepInFlight) return;
  const payload = _stepPayload(payloadOverride);
  if (Object.keys(payload).length === 0) return;

  clearError(playErrorEl);
  state.stepInFlight = true;
  try {
    const submitInput = { payload };
    submitInput["session" + "Id"] = state.activeRunSession;
    const result = await state.stepController.submit(submitInput);
    if (!result.ok) {
      if (result.retryable) {
        setViewMode("pending_retry");
        throw new Error("Action is still pending. Click Retry Pending to continue.");
      }
      throw new Error(_terminalError(result));
    }

    const step = result.data;
    renderNarrative(step.narrative_text, step.choices || []);
    await refreshSession({ renderNode: false });
    if (step.run_ended) {
      setViewMode("ended");
    }
    el("playerInput").value = "";
  } finally {
    state.stepInFlight = false;
  }
}

async function retryPendingStep() {
  if (!state.stepController || state.stepInFlight) return;
  const pending = state.stepController.getPending();
  if (!pending) {
    showError(playErrorEl, "No pending action to retry.");
    return;
  }

  clearError(playErrorEl);
  state.stepInFlight = true;
  try {
    const result = await state.stepController.retryPending();
    if (!result.ok) {
      if (result.retryable) {
        setViewMode("pending_retry");
        throw new Error("Action is still pending. Please retry again.");
      }
      throw new Error(_terminalError(result));
    }

    const step = result.data;
    renderNarrative(step.narrative_text, step.choices || []);
    await refreshSession({ renderNode: false });
    if (step.run_ended) {
      setViewMode("ended");
    } else {
      setViewMode("playing");
    }
  } finally {
    state.stepInFlight = false;
  }
}

function renderReplay(payload) {
  if (!payload) {
    resetReplaySummary();
    return;
  }

  const storyPath = (payload.story_path || []).slice(0, 6).map((row) => `#${row.step}: ${row.node_id} -> ${row.choice_id}`);

  const keyDecisions = (payload.key_decisions || []).slice(0, 6).map((row) => {
    const actionId = (row.final_action || {}).action_id || "action";
    return `Step ${row.step_index}: ${actionId}`;
  });

  const run = payload.run_summary || {};
  const runRows = [
    `Ending: ${run.ending_id || "In progress"}`,
    `Outcome: ${run.ending_outcome || "-"}`,
    `Total steps: ${Number(run.total_steps || 0)}`,
    `Triggered events: ${Number(run.triggered_events_count || 0)}`,
    `Fallback rate: ${typeof run.fallback_rate === "number" ? run.fallback_rate.toFixed(2) : "0.00"}`,
  ];

  setSummaryList(replayStoryPathEl, storyPath, "No story path yet.");
  setSummaryList(replayKeyDecisionsEl, keyDecisions, "No key decisions yet.");
  setSummaryList(replayRunSummaryEl, runRows, "No run summary yet.");
}

async function replaySession() {
  if (!state.activeRunSession) return;
  const payload = await Shared.callApi("GET", `/sessions/${state.activeRunSession}/replay`);
  renderReplay(payload);
}

function resetSessionView() {
  state.activeRunSession = null;
  state.currentState = {};
  renderMetaPill({ day: "-", slot: "-" });
  renderCoreStats({ energy: 0, money: 0, knowledge: 0, affection: 0 });
  renderQuestSummary({});
  renderRunSummary({});
  narrativeTextEl.textContent = "Pick a story to start.";
  choiceButtonsEl.innerHTML = "";
  resetReplaySummary();
  state.stepController?.clearPending();
  pendingStatusEl.textContent = "No pending action.";
  el("playerInput").value = "";
}

async function init() {
  setViewMode("boot_loading");
  await loadBootstrap();
  await loadStories();
  resetSessionView();
  switchToStorySelect();

  el("refreshStoriesBtn").addEventListener("click", () => {
    loadStories().catch((error) => showError(storySelectErrorEl, error.message || String(error)));
  });

  el("startStoryBtn").addEventListener("click", () => {
    createSessionFromSelection().catch((error) => {
      switchToStorySelect();
      showError(storySelectErrorEl, error.message || String(error));
      setViewMode("fatal_error");
    });
  });

  el("sendInputBtn").addEventListener("click", () => sendStep().catch((error) => showError(playErrorEl, error.message || String(error))));
  el("retryPendingBtn").addEventListener("click", () => retryPendingStep().catch((error) => showError(playErrorEl, error.message || String(error))));
  el("newRunBtn").addEventListener("click", () => {
    resetSessionView();
    switchToStorySelect();
  });
  el("refreshBtn").addEventListener("click", () => refreshSession({ renderNode: true }).catch((error) => showError(playErrorEl, error.message || String(error))));
  el("replayBtn").addEventListener("click", () => replaySession().catch((error) => showError(playErrorEl, error.message || String(error))));
}

init().catch((error) => {
  switchToStorySelect();
  showError(storySelectErrorEl, `play demo init failed: ${error.message || error}`);
  setViewMode("fatal_error");
});
