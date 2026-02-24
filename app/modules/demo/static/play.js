const Shared = window.DemoShared;
const {
  mustEl,
  cloneJson,
  setElementMessage,
  formatStoryPathLines,
  bindAsyncClick,
} = Shared;

const state = {
  viewMode: "boot_loading",
  stories: [],
  selectedStory: null,
  activeRunSession: null,
  currentState: {},
  bootstrap: null,
  stepController: null,
  stepInFlight: false,
  stepUiStatus: "idle",
  busyRequestKind: null,
  busyPhase: null,
  stageLabel: "",
  stageCode: "",
  busyLongWait: false,
  busyPhaseTimer: null,
  longWaitTimer: null,
  stepAckTimer: null,
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

const FREE_INPUT_PHASE2_DELAY_MS = 900;
const LONG_WAIT_HINT_MS = 12000;
const STEP_ACK_HOLD_MS = 1200;
const IMPACT_MAX_ROWS = 4;
const PLAY_BUSY_STAGE_CLASS_BY_CODE = {
  "play.selection.start": "play-busy--selection",
  "play.narration.start": "play-busy--narration",
  "llm.retry": "play-busy--retry",
};
const PLAY_BUSY_STAGE_CLASSES = Object.values(PLAY_BUSY_STAGE_CLASS_BY_CODE);

const numberFormatter = new Intl.NumberFormat("en-US");

const refs = {
  storyMetaPillEl: mustEl("storyMetaPill"),
  currentStoryTitleEl: mustEl("currentStoryTitle"),
  narrativeTextEl: mustEl("narrativeText"),
  choiceButtonsEl: mustEl("choiceButtons"),
  storyListEl: mustEl("storyList"),
  storySelectErrorEl: mustEl("storySelectError"),
  playErrorEl: mustEl("playError"),
  storySelectSectionEl: mustEl("storySelectSection"),
  playSectionEl: mustEl("playSection"),
  pendingStatusEl: mustEl("pendingStatus"),
  startStoryBtnEl: mustEl("startStoryBtn"),
  runSummaryPanelEl: mustEl("runSummaryPanel"),
  sendInputBtnEl: mustEl("sendInputBtn"),
  retryPendingBtnEl: mustEl("retryPendingBtn"),
  playerInputEl: mustEl("playerInput"),
  stepBusyHintEl: mustEl("stepBusyHint"),
  stepBusyPhaseEl: mustEl("stepBusyPhase"),
  stepBusyTextEl: mustEl("stepBusyText"),
  stepAckEl: mustEl("stepAck"),
  refreshStoriesBtnEl: mustEl("refreshStoriesBtn"),
  newRunBtnEl: mustEl("newRunBtn"),
  refreshBtnEl: mustEl("refreshBtn"),
  replayBtnEl: mustEl("replayBtn"),

  energyValueEl: mustEl("energyValue"),
  energyBarEl: mustEl("energyBar"),
  moneyValueEl: mustEl("moneyValue"),
  moneyTierEl: mustEl("moneyTier"),
  knowledgeValueEl: mustEl("knowledgeValue"),
  knowledgeBarEl: mustEl("knowledgeBar"),
  knowledgeTierEl: mustEl("knowledgeTier"),
  affectionValueEl: mustEl("affectionValue"),
  affectionBarEl: mustEl("affectionBar"),
  affectionToneEl: mustEl("affectionTone"),

  activeQuestListEl: mustEl("activeQuestList"),
  completedQuestListEl: mustEl("completedQuestList"),
  questRecentListEl: mustEl("questRecentList"),

  runStepValueEl: mustEl("runStepValue"),
  runFallbackValueEl: mustEl("runFallbackValue"),
  runEndingValueEl: mustEl("runEndingValue"),
  runEventValueEl: mustEl("runEventValue"),
  lastImpactListEl: mustEl("lastImpactList"),

  replayStoryPathEl: mustEl("replayStoryPath"),
  replayKeyDecisionsEl: mustEl("replayKeyDecisions"),
  replayRunSummaryEl: mustEl("replayRunSummary"),
};

function setViewMode(nextPhase) {
  state.viewMode = String(nextPhase || "unknown");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)));
}

function showError(targetEl, message) {
  setElementMessage(targetEl, message, { hiddenClass: "hidden" });
}

function clearError(targetEl) {
  showError(targetEl, "");
}

function setSummaryList(listEl, items, emptyText) {
  listEl.innerHTML = "";
  if (!Array.isArray(items) || items.length === 0) {
    const row = document.createElement("li");
    row.className = "summary-list--empty";
    row.textContent = emptyText;
    listEl.appendChild(row);
    return;
  }

  items.forEach((line) => {
    const row = document.createElement("li");
    row.textContent = String(line || "");
    listEl.appendChild(row);
  });
}

function lockReasonLabel(code) {
  if (!code) return "Unavailable for now";
  return LOCK_REASON_LABEL[code] || "Unavailable for now";
}

function choiceTypeLabel(type) {
  const key = String(type || "").trim().toLowerCase();
  return CHOICE_TYPE_LABEL[key] || "Action";
}

function eventTypeLabel(type) {
  const key = String(type || "").trim();
  return QUEST_EVENT_LABEL[key] || "Progress updated";
}

function _hasPendingStep() {
  return Boolean(state.stepController && state.stepController.getPending());
}

function _updateChoiceInteractivity() {
  const busy = state.stepUiStatus !== "idle";
  refs.choiceButtonsEl.querySelectorAll(".choice-card").forEach((btn) => {
    const available = String(btn.dataset.available || "").toLowerCase() === "true";
    btn.disabled = busy ? true : !available;
  });
}

function deriveRequestKind(payload) {
  if (payload && payload.choice_id) return "choice";
  if (payload && typeof payload.player_input === "string" && payload.player_input.trim()) return "free_input";
  return "choice";
}

function _clearBusyTimers() {
  if (state.busyPhaseTimer) {
    window.clearTimeout(state.busyPhaseTimer);
    state.busyPhaseTimer = null;
  }
  if (state.longWaitTimer) {
    window.clearTimeout(state.longWaitTimer);
    state.longWaitTimer = null;
  }
}

function clearBusyFlow() {
  _clearBusyTimers();
  state.busyRequestKind = null;
  state.busyPhase = null;
  state.stageLabel = "";
  state.stageCode = "";
  refs.stepBusyHintEl.classList.remove(...PLAY_BUSY_STAGE_CLASSES);
  state.busyLongWait = false;
  refs.stepBusyPhaseEl.textContent = "";
  refs.stepBusyPhaseEl.classList.remove("play-busy__phase--visible");
}

function _clearStepAckTimer() {
  if (state.stepAckTimer) {
    window.clearTimeout(state.stepAckTimer);
    state.stepAckTimer = null;
  }
}

function clearStepAck() {
  _clearStepAckTimer();
  refs.stepAckEl.classList.add("hidden");
  refs.stepAckEl.textContent = "";
  refs.stepAckEl.setAttribute("data-state", "");
}

function showStepAck(message, stateName = "success") {
  _clearStepAckTimer();
  const text = String(message || "").trim();
  if (!text) {
    clearStepAck();
    return;
  }
  refs.stepAckEl.textContent = text;
  refs.stepAckEl.setAttribute("data-state", stateName || "success");
  refs.stepAckEl.classList.remove("hidden");
  state.stepAckTimer = window.setTimeout(() => {
    clearStepAck();
  }, STEP_ACK_HOLD_MS);
}

function renderBusyCopy() {
  if (state.stageLabel) {
    refs.stepBusyTextEl.textContent = state.stageLabel;
    refs.stepBusyPhaseEl.textContent = "";
    refs.stepBusyPhaseEl.classList.remove("play-busy__phase--visible");
    return;
  }

  const kind = state.busyRequestKind || "choice";
  const phase = state.busyPhase || "single";
  const longWait = state.busyLongWait === true;

  if (kind === "free_input") {
    refs.stepBusyTextEl.textContent = phase === "phase_1"
      ? "Signal sent. Analyzing your input... (1/2)"
      : "Model responding. Generating narrative... (2/2)";
    if (longWait) {
      refs.stepBusyTextEl.textContent += " This may take a bit longer on busy models.";
    }
    refs.stepBusyPhaseEl.textContent = phase === "phase_1" ? "Phase 1" : "Phase 2";
    refs.stepBusyPhaseEl.classList.add("play-busy__phase--visible");
    return;
  }

  refs.stepBusyTextEl.textContent = "Signal sent. Generating narrative...";
  refs.stepBusyPhaseEl.textContent = "";
  refs.stepBusyPhaseEl.classList.remove("play-busy__phase--visible");
}

function startBusyFlow(kind) {
  clearBusyFlow();
  const normalizedKind = kind === "free_input" ? "free_input" : "choice";
  state.busyRequestKind = normalizedKind;
  state.busyPhase = normalizedKind === "free_input" ? "phase_1" : "single";
  state.busyLongWait = false;
  renderBusyCopy();

  if (normalizedKind !== "free_input") {
    return;
  }

  state.busyPhaseTimer = window.setTimeout(() => {
    if (state.stepUiStatus !== "submitting" || state.busyRequestKind !== "free_input") return;
    state.busyPhase = "phase_2";
    renderBusyCopy();
  }, FREE_INPUT_PHASE2_DELAY_MS);

  state.longWaitTimer = window.setTimeout(() => {
    if (state.stepUiStatus !== "submitting" || state.busyRequestKind !== "free_input") return;
    state.busyLongWait = true;
    renderBusyCopy();
  }, LONG_WAIT_HINT_MS);
}

function setStepUiStatus(nextStatus, options = {}) {
  const normalized = String(nextStatus || "idle");
  state.stepUiStatus = normalized;

  const submitting = normalized === "submitting";
  const pendingRetry = normalized === "pending_retry";
  const idle = normalized === "idle";

  refs.sendInputBtnEl.classList.toggle("btn--loading", submitting);
  refs.sendInputBtnEl.textContent = submitting
    ? (state.stageLabel || "Sending...")
    : "Send Input";
  refs.sendInputBtnEl.disabled = !idle;

  refs.retryPendingBtnEl.classList.remove("btn--loading");
  refs.retryPendingBtnEl.textContent = "Retry Pending";
  refs.retryPendingBtnEl.disabled = !(pendingRetry && _hasPendingStep());

  refs.playerInputEl.disabled = !idle;

  refs.playSectionEl.setAttribute("aria-busy", submitting ? "true" : "false");

  if (submitting) {
    clearStepAck();
    startBusyFlow(options.requestKind);
    refs.stepBusyHintEl.classList.add("play-busy--visible");
    refs.stepBusyHintEl.classList.remove("play-busy--pending");
  } else if (pendingRetry) {
    clearBusyFlow();
    refs.stepBusyTextEl.textContent = "Action pending. Retry with same request key.";
    refs.stepBusyHintEl.classList.add("play-busy--visible", "play-busy--pending");
  } else {
    clearBusyFlow();
    refs.stepBusyHintEl.classList.remove("play-busy--visible", "play-busy--pending");
  }

  _updateChoiceInteractivity();
}

function handleStepStage(stagePayload) {
  const label = String(stagePayload?.label || "").trim();
  const stageCode = String(stagePayload?.stage_code || "").trim();
  const stageClass = PLAY_BUSY_STAGE_CLASS_BY_CODE[stageCode] || "";
  refs.stepBusyHintEl.classList.remove(...PLAY_BUSY_STAGE_CLASSES);
  if (stageClass) {
    refs.stepBusyHintEl.classList.add(stageClass);
  }
  state.stageCode = stageCode;
  if (!label) return;
  state.stageLabel = label;
  if (state.stepUiStatus === "submitting") {
    refs.sendInputBtnEl.textContent = label;
    renderBusyCopy();
  }
}

function renderPendingStatus(pending, meta = {}) {
  const maxAttempts = Number(meta.maxAttempts || state.stepController?.maxAttempts || 0);
  if (!pending) {
    refs.pendingStatusEl.textContent = "No pending action.";
    return;
  }

  if (pending.uncertain) {
    refs.pendingStatusEl.textContent = "Previous step is still pending. Click Retry Pending to continue with the same action.";
    return;
  }

  const attemptsText = maxAttempts ? `${pending.attempts}/${maxAttempts}` : `${pending.attempts}`;
  refs.pendingStatusEl.textContent = `Processing action... attempt ${attemptsText}.`;
}

function switchToStorySelect() {
  refs.storySelectSectionEl.classList.remove("hidden");
  refs.playSectionEl.classList.add("hidden");
  setViewMode("story_select");
}

function switchToPlaying() {
  refs.storySelectSectionEl.classList.add("hidden");
  refs.playSectionEl.classList.remove("hidden");
  setViewMode("playing");
}

function _storyKey(story) {
  return `${story.story_id}@${story.version}`;
}

function _updateCurrentStoryLabel() {
  const story = state.selectedStory;
  if (!story) {
    refs.currentStoryTitleEl.innerHTML = "Current story: <strong>-</strong>";
    return;
  }
  refs.currentStoryTitleEl.innerHTML = "";
  refs.currentStoryTitleEl.append("Current story: ");
  const strong = document.createElement("strong");
  strong.textContent = `${story.title || story.story_id} (${story.version})`;
  refs.currentStoryTitleEl.appendChild(strong);
}

function _renderStoryCard(story, selected) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = `story-card story-card--button${selected ? " story-card--selected" : ""}`;

  const title = document.createElement("p");
  title.className = "story-card__title";
  title.textContent = story.title || story.story_id;

  const meta = document.createElement("p");
  meta.className = "story-card__meta";
  meta.textContent = `${story.story_id}@${story.version}`;

  const summary = document.createElement("p");
  summary.className = "story-card__summary";
  summary.textContent = story.summary || "No summary provided.";

  card.appendChild(title);
  card.appendChild(meta);
  card.appendChild(summary);

  card.addEventListener("click", () => {
    state.selectedStory = story;
    clearError(refs.storySelectErrorEl);
    renderStoryList();
  });

  return card;
}

function renderStoryList() {
  refs.storyListEl.innerHTML = "";
  const stories = Array.isArray(state.stories) ? state.stories : [];

  if (!stories.length) {
    const empty = document.createElement("div");
    empty.className = "story-card";
    const label = document.createElement("p");
    label.className = "story-card__title";
    label.textContent = "No playable stories available.";
    empty.appendChild(label);
    refs.storyListEl.appendChild(empty);
    refs.startStoryBtnEl.disabled = true;
    _updateCurrentStoryLabel();
    return;
  }

  stories.forEach((story) => {
    const selected = Boolean(state.selectedStory && _storyKey(story) === _storyKey(state.selectedStory));
    refs.storyListEl.appendChild(_renderStoryCard(story, selected));
  });

  refs.startStoryBtnEl.disabled = !state.selectedStory;
  _updateCurrentStoryLabel();
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
  refs.storyMetaPillEl.textContent = `Day ${day} • ${slot}`;
}

function renderCoreStats(current) {
  const energy = clamp(current.energy, 0, 100);
  const money = Number(current.money || 0);
  const knowledge = Math.max(0, Number(current.knowledge || 0));
  const affection = clamp(Number(current.affection || 0), -100, 100);

  refs.energyValueEl.textContent = `${energy}/100`;
  refs.energyBarEl.style.width = `${energy}%`;

  refs.moneyValueEl.textContent = numberFormatter.format(money);
  refs.moneyTierEl.textContent = _moneyTierLabel(money);

  refs.knowledgeValueEl.textContent = numberFormatter.format(knowledge);
  refs.knowledgeBarEl.style.width = `${clamp((knowledge / 999) * 100, 0, 100)}%`;
  refs.knowledgeTierEl.textContent = _knowledgeTierLabel(knowledge);

  refs.affectionValueEl.textContent = affection >= 0 ? `+${affection}` : `${affection}`;
  refs.affectionBarEl.style.width = `${clamp(((affection + 100) / 200) * 100, 0, 100)}%`;
  refs.affectionToneEl.textContent = _affectionToneLabel(affection);
}

function renderQuestSummary(questState) {
  const data = questState || {};
  const quests = data.quests || {};
  const activeIds = Array.isArray(data.active_quests) ? data.active_quests : [];
  const completedIds = Array.isArray(data.completed_quests) ? data.completed_quests : [];

  const activeRows = activeIds.map((questId) => {
    const entry = quests[questId] || {};
    const stageId = entry.current_stage_id || "-";
    const stageMap = entry.stages || {};
    const stageEntry = stageMap[stageId] || {};
    const milestones = stageEntry.milestones || {};
    const milestoneIds = Object.keys(milestones);
    const doneCount = milestoneIds.filter((id) => milestones[id]?.done).length;
    return `${questId}: ${stageId} (${doneCount}/${milestoneIds.length})`;
  });

  const completedRows = completedIds.map((questId) => `${questId}`);

  const recent = Array.isArray(data.recent_events) ? data.recent_events.slice(-3) : [];
  const recentRows = recent.map((event) => {
    const eventLabel = eventTypeLabel(event.type);
    const questId = event.quest_id || "Quest";
    const milestone = event.milestone_id ? ` · ${event.milestone_id}` : "";
    return `${eventLabel}: ${questId}${milestone}`;
  });

  setSummaryList(refs.activeQuestListEl, activeRows, "No active quests.");
  setSummaryList(refs.completedQuestListEl, completedRows, "No completed quests yet.");
  setSummaryList(refs.questRecentListEl, recentRows, "No recent quest updates.");
}

function renderRunSummary(runState) {
  const data = runState || {};
  const stepIndex = Number(data.step_index || 0);
  const fallbackCount = Number(data.fallback_count || 0);
  const endingId = String(data.ending_id || "").trim();
  const endingOutcome = String(data.ending_outcome || "").trim();
  const triggeredCount = Array.isArray(data.triggered_event_ids) ? data.triggered_event_ids.length : 0;

  refs.runStepValueEl.textContent = String(stepIndex);
  refs.runFallbackValueEl.textContent = String(fallbackCount);
  refs.runEventValueEl.textContent = String(triggeredCount);

  if (!endingId) {
    refs.runEndingValueEl.textContent = "In progress";
    return;
  }

  refs.runEndingValueEl.textContent = endingOutcome ? `${endingId} (${endingOutcome})` : endingId;
}

function _asFiniteNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric;
}

function _computeImpactRows(beforeState, afterState) {
  const before = cloneJson(beforeState || {});
  const after = cloneJson(afterState || {});
  const rows = [];

  for (const [key, label] of [
    ["energy", "Energy"],
    ["money", "Money"],
    ["knowledge", "Knowledge"],
    ["affection", "Affection"],
  ]) {
    const beforeValue = _asFiniteNumber(before[key]);
    const afterValue = _asFiniteNumber(after[key]);
    if (beforeValue === null || afterValue === null) continue;
    const delta = afterValue - beforeValue;
    if (!delta) continue;
    rows.push(`${label} ${delta > 0 ? "+" : ""}${delta}`);
  }

  const beforeDay = _asFiniteNumber(before.day);
  const afterDay = _asFiniteNumber(after.day);
  if (beforeDay !== null && afterDay !== null && beforeDay !== afterDay) {
    rows.push(`Day ${beforeDay} -> ${afterDay}`);
  }

  const beforeSlot = String(before.slot || "").trim();
  const afterSlot = String(after.slot || "").trim();
  if (beforeSlot && afterSlot && beforeSlot !== afterSlot) {
    rows.push(`Time ${beforeSlot} -> ${afterSlot}`);
  }

  return rows.slice(0, IMPACT_MAX_ROWS);
}

function renderLastImpact(rows) {
  setSummaryList(refs.lastImpactListEl, rows, "No action applied yet.");
}

function renderState(stateJson) {
  const current = cloneJson(stateJson || {});
  state.currentState = current;
  renderMetaPill(current);
  renderCoreStats(current);
  renderQuestSummary(current.quest_state || {});
  renderRunSummary(current.run_state || {});
}

function renderNarrative(text, choices) {
  refs.narrativeTextEl.textContent = text || "(empty)";
  refs.choiceButtonsEl.innerHTML = "";

  (choices || []).forEach((choice) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "choice-card";

    const unavailable = choice.is_available === false;
    const typeLabel = choiceTypeLabel(choice.type);
    const lockLabel = unavailable ? lockReasonLabel(choice.unavailable_reason) : "";

    const title = document.createElement("div");
    title.className = "choice-card__title";
    title.textContent = choice.text;

    const meta = document.createElement("div");
    meta.className = "choice-card__meta";

    const badge = document.createElement("span");
    badge.className = "choice-badge";
    badge.textContent = typeLabel;
    meta.appendChild(badge);

    if (unavailable) {
      const lock = document.createElement("span");
      lock.className = "choice-lock";
      lock.textContent = lockLabel;
      meta.appendChild(lock);
    }

    btn.appendChild(title);
    btn.appendChild(meta);

    btn.dataset.available = String(!unavailable);
    btn.disabled = unavailable;
    if (!unavailable) {
      btn.addEventListener("click", () => {
        sendStep({ choice_id: choice.id }).catch((error) => showError(refs.playErrorEl, error.message || String(error)));
      });
    }

    refs.choiceButtonsEl.appendChild(btn);
  });

  _updateChoiceInteractivity();
}

async function loadBootstrap() {
  const payload = await Shared.callApi("GET", "/demo/bootstrap");
  state.bootstrap = payload;
  state.stepController = Shared.createStepRetryController({
    maxAttempts: payload.step_retry_max_attempts,
    backoffMs: payload.step_retry_backoff_ms,
    onStatus: renderPendingStatus,
    onStage: handleStepStage,
  });
  setStepUiStatus("idle");
}

async function loadStories() {
  clearError(refs.storySelectErrorEl);
  const payload = await Shared.listStories({ publishedOnly: true, playableOnly: true });
  const stories = Array.isArray(payload?.stories) ? payload.stories : [];
  state.stories = stories;

  if (!state.selectedStory && stories.length > 0) {
    state.selectedStory = stories[0];
  } else if (
    state.selectedStory
    && !stories.some((item) => _storyKey(item) === _storyKey(state.selectedStory))
  ) {
    state.selectedStory = stories.length ? stories[0] : null;
  }

  renderStoryList();
}

function resetReplaySummary() {
  setSummaryList(refs.replayStoryPathEl, [], "Run not ended yet.");
  setSummaryList(refs.replayKeyDecisionsEl, [], "No decision summary yet.");
  setSummaryList(refs.replayRunSummaryEl, [], "No run summary yet.");
  refs.runSummaryPanelEl.open = false;
}

async function createSessionFromSelection() {
  if (!state.selectedStory) {
    throw new Error("Please select a story first.");
  }

  clearError(refs.storySelectErrorEl);
  clearError(refs.playErrorEl);
  setViewMode("creating_session");

  const body = { story_id: state.selectedStory.story_id };
  if (state.selectedStory.version !== null && state.selectedStory.version !== undefined) {
    body.version = Number(state.selectedStory.version);
  }

  const out = await Shared.callApi("POST", "/sessions", body);
  state.activeRunSession = out.id;
  state.stepController?.clearPending();
  setStepUiStatus("idle");
  resetReplaySummary();
  renderLastImpact([]);
  switchToPlaying();
  await refreshSession({ renderNode: true });
}

async function refreshSession(options = {}) {
  if (!state.activeRunSession) return null;
  const { renderNode = true } = options;
  const out = await Shared.callApi("GET", `/sessions/${state.activeRunSession}`);

  if (out && out.story_id) {
    const matched = state.stories.find((item) => (
      String(item.story_id) === String(out.story_id)
      && String(item.version) === String(out.story_version)
    ));
    state.selectedStory = matched || {
      story_id: out.story_id,
      version: out.story_version,
      title: out.story_id,
    };
    _updateCurrentStoryLabel();
  }

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

function _resumeSessionIdFromLocation() {
  try {
    const params = new URLSearchParams(window.location.search || "");
    const fromQuery = String(params.get("session_id") || "").trim();
    if (fromQuery) return fromQuery;
  } catch {
    // ignore invalid URL state
  }
  const fromStorage = String(window.localStorage.getItem("demo_play_session_id") || "").trim();
  return fromStorage || null;
}

async function tryResumeSessionFromLocation() {
  const sessionId = _resumeSessionIdFromLocation();
  if (!sessionId) return false;
  state.activeRunSession = sessionId;
  state.stepController?.clearPending();
  setStepUiStatus("idle");
  clearError(refs.playErrorEl);
  switchToPlaying();
  try {
    await refreshSession({ renderNode: true });
    window.localStorage.removeItem("demo_play_session_id");
    setViewMode("playing");
    return true;
  } catch (error) {
    state.activeRunSession = null;
    switchToStorySelect();
    showError(refs.storySelectErrorEl, `Could not resume session: ${error.message || String(error)}`);
    return false;
  }
}

function stepPayload(payloadOverride) {
  const inputText = refs.playerInputEl.value.trim();
  const payload = payloadOverride ? { ...payloadOverride } : {};
  if (!payload.choice_id && inputText) {
    payload.player_input = inputText;
  }
  return payload;
}

function terminalErrorMessage(result) {
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
  const payload = stepPayload(payloadOverride);
  if (Object.keys(payload).length === 0) return;
  const requestKind = deriveRequestKind(payload);
  const stateBeforeStep = cloneJson(state.currentState || {});

  clearError(refs.playErrorEl);
  state.stepInFlight = true;
  setStepUiStatus("submitting", { requestKind });

  try {
    const result = await state.stepController.submit({
      sessionId: state.activeRunSession,
      payload,
    });

    if (!result.ok) {
      if (result.retryable) {
        setViewMode("pending_retry");
        setStepUiStatus("pending_retry");
        throw new Error("Action is still pending. Click Retry Pending to continue.");
      }
      setStepUiStatus("idle");
      throw new Error(terminalErrorMessage(result));
    }

    const step = result.data;
    renderNarrative(step.narrative_text, step.choices || []);
    await refreshSession({ renderNode: false });
    renderLastImpact(_computeImpactRows(stateBeforeStep, state.currentState || {}));

    if (step.run_ended) {
      setViewMode("ended");
    } else {
      setViewMode("playing");
    }

    refs.playerInputEl.value = "";
    setStepUiStatus("idle");
    showStepAck("Response received. World state updated.");
  } catch (error) {
    if (state.stepUiStatus === "submitting") {
      setStepUiStatus("idle");
    }
    throw error;
  } finally {
    state.stepInFlight = false;
  }
}

async function retryPendingStep() {
  if (!state.stepController || state.stepInFlight) return;
  const pending = state.stepController.getPending();

  if (!pending) {
    setStepUiStatus("idle");
    showError(refs.playErrorEl, "No pending action to retry.");
    return;
  }

  clearError(refs.playErrorEl);
  state.stepInFlight = true;
  setStepUiStatus("submitting");
  const stateBeforeStep = cloneJson(state.currentState || {});

  try {
    const result = await state.stepController.retryPending();

    if (!result.ok) {
      if (result.retryable) {
        setViewMode("pending_retry");
        setStepUiStatus("pending_retry");
        throw new Error("Action is still pending. Please retry again.");
      }
      setStepUiStatus("idle");
      throw new Error(terminalErrorMessage(result));
    }

    const step = result.data;
    renderNarrative(step.narrative_text, step.choices || []);
    await refreshSession({ renderNode: false });
    renderLastImpact(_computeImpactRows(stateBeforeStep, state.currentState || {}));

    if (step.run_ended) {
      setViewMode("ended");
    } else {
      setViewMode("playing");
    }

    setStepUiStatus("idle");
    showStepAck("Response received. World state updated.");
  } catch (error) {
    if (state.stepUiStatus === "submitting") {
      setStepUiStatus("idle");
    }
    throw error;
  } finally {
    state.stepInFlight = false;
  }
}

function renderReplay(payload) {
  if (!payload) {
    resetReplaySummary();
    return;
  }

  const storyPath = formatStoryPathLines(payload.story_path, 6);

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

  setSummaryList(refs.replayStoryPathEl, storyPath, "No story path yet.");
  setSummaryList(refs.replayKeyDecisionsEl, keyDecisions, "No key decisions yet.");
  setSummaryList(refs.replayRunSummaryEl, runRows, "No run summary yet.");
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

  refs.narrativeTextEl.textContent = "Pick a story to start.";
  refs.choiceButtonsEl.innerHTML = "";
  resetReplaySummary();
  renderLastImpact([]);
  state.stepController?.clearPending();
  setStepUiStatus("idle");
  refs.pendingStatusEl.textContent = "No pending action.";
  clearStepAck();
  refs.playerInputEl.value = "";
  _updateCurrentStoryLabel();
}

function attachEvents() {
  bindAsyncClick(
    refs.refreshStoriesBtnEl,
    () => loadStories(),
    (error) => showError(refs.storySelectErrorEl, error.message || String(error)),
  );

  bindAsyncClick(
    refs.startStoryBtnEl,
    () => createSessionFromSelection(),
    (error) => {
      switchToStorySelect();
      showError(refs.storySelectErrorEl, error.message || String(error));
      setViewMode("fatal_error");
    },
  );

  bindAsyncClick(
    refs.sendInputBtnEl,
    () => sendStep(),
    (error) => showError(refs.playErrorEl, error.message || String(error)),
  );

  bindAsyncClick(
    refs.retryPendingBtnEl,
    () => retryPendingStep(),
    (error) => showError(refs.playErrorEl, error.message || String(error)),
  );

  refs.newRunBtnEl.addEventListener("click", () => {
    resetSessionView();
    switchToStorySelect();
  });

  bindAsyncClick(
    refs.refreshBtnEl,
    () => refreshSession({ renderNode: true }),
    (error) => showError(refs.playErrorEl, error.message || String(error)),
  );

  bindAsyncClick(
    refs.replayBtnEl,
    () => replaySession(),
    (error) => showError(refs.playErrorEl, error.message || String(error)),
  );
}

async function init() {
  setViewMode("boot_loading");
  await loadBootstrap();
  await loadStories();
  resetSessionView();
  attachEvents();
  const resumed = await tryResumeSessionFromLocation();
  if (!resumed) {
    switchToStorySelect();
  }
}

init().catch((error) => {
  switchToStorySelect();
  showError(refs.storySelectErrorEl, `play demo init failed: ${error.message || error}`);
  setViewMode("fatal_error");
});
