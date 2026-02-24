window.AuthorStudioV5App = (function createAuthorStudioV5App() {
const Shared = window.DemoShared;
const { mustEl, runAsyncWithSignal } = Shared;
const patchHelpers = window.AuthorStudioV5Patch || {};
const stateHelpers = window.AuthorStudioV5State || {};
const assistHelpers = window.AuthorStudioV5Assist || {};

const LAYER_KEYS = ["world", "characters", "plot", "flow", "action", "consequence", "ending", "systems"];

const state = {
  stepIndex: 0,
  story: null,
  compiledPack: null,
  assistSuggestions: {},
  assistPatches: [],
  assistWarnings: [],
  patchHistory: [],
  selectedSceneIndex: 0,
  selectedOptionIndex: 0,
  assistInFlight: false,
  assistStageState: "",
  assistAbortController: null,
  assistCancelableTask: null,
  overviewFromExpandRows: [],
  overviewFromExpandSource: "",
  overviewFromExpandAt: 0,
  overviewFromExpandPending: false,
  entryMode: "spark",
  playability: null,
  nextSteps: [],
  diagnostics: {
    errors: [],
    warnings: [],
  },
  ui: {
    focus_mode: true,
    show_debug: false,
    active_tab: "author",
    active_page: "compose",
    panels: {
      structure_open: false,
      review_advanced_open: false,
    },
  },
};

const refs = {
  tabAuthorBtnEl: mustEl("authorTabAuthorBtn"),
  tabDebugBtnEl: mustEl("authorTabDebugBtn"),
  debugToggleEl: mustEl("authorShowDebugToggle"),
  mainFlowEl: mustEl("authorMainFlow"),
  debugPanelEl: mustEl("authorDebugPanel"),
  nextStepsEl: mustEl("authorNextSteps"),
  assistRetryHintEl: mustEl("authorAssistRetryHint"),
  pageComposeBtnEl: mustEl("authorPageComposeBtn"),
  pageShapeBtnEl: mustEl("authorPageShapeBtn"),
  pageBuildBtnEl: mustEl("authorPageBuildBtn"),
  pageComposeEl: mustEl("authorPageCompose"),
  pageShapeEl: mustEl("authorPageShape"),
  pageBuildEl: mustEl("authorPageBuild"),

  stepperEl: mustEl("authorStepper"),
  prevStepBtnEl: mustEl("prevStepBtn"),
  nextStepBtnEl: mustEl("nextStepBtn"),
  structureCollapseEl: mustEl("authorStructureCollapse"),
  reviewAdvancedToggleEl: mustEl("authorReviewAdvancedToggle"),

  globalBriefEl: mustEl("authorGlobalBrief"),
  entrySparkBtnEl: mustEl("authorEntrySparkBtn"),
  entryIngestBtnEl: mustEl("authorEntryIngestBtn"),
  seedInputEl: mustEl("authorSeedInput"),
  sourceInputEl: mustEl("authorSourceInput"),
  continueInputEl: mustEl("authorContinueInput"),

  storyIdEl: mustEl("authorStoryId"),
  versionEl: mustEl("authorVersion"),
  titleEl: mustEl("authorTitle"),
  localeEl: mustEl("authorLocale"),
  summaryEl: mustEl("authorSummary"),

  worldEraEl: mustEl("worldEra"),
  worldLocationEl: mustEl("worldLocation"),
  worldBoundariesEl: mustEl("worldBoundaries"),
  worldSocialRulesEl: mustEl("worldSocialRules"),

  protagonistNameEl: mustEl("protagonistName"),
  protagonistRoleEl: mustEl("protagonistRole"),
  protagonistTraitsEl: mustEl("protagonistTraits"),
  npcsNarrativeEl: mustEl("charactersNpcsNarrative"),
  axesNarrativeEl: mustEl("charactersAxesNarrative"),
  npcsJsonEl: mustEl("charactersNpcsJson"),
  axesJsonEl: mustEl("charactersAxesJson"),

  mainlineGoalEl: mustEl("authorMainlineGoal"),
  sidelineThreadsEl: mustEl("authorSidelineThreads"),
  actsEl: mustEl("authorActs"),

  scenesEl: mustEl("authorScenes"),

  actionMappingPolicyEl: mustEl("actionMappingPolicy"),
  actionCatalogNarrativeEl: mustEl("actionCatalogNarrative"),
  actionCatalogJsonEl: mustEl("actionCatalogJson"),

  consequenceStateAxesEl: mustEl("consequenceStateAxes"),
  consequenceNarrativeSummaryEl: mustEl("consequenceNarrativeSummary"),
  consequenceRefineIntentEl: mustEl("consequenceRefineIntent"),
  questsJsonEl: mustEl("authorQuestsJson"),
  eventsJsonEl: mustEl("authorEventsJson"),

  endingNarrativeSummaryEl: mustEl("endingNarrativeSummary"),
  endingRefineIntentEl: mustEl("endingRefineIntent"),
  endingsJsonEl: mustEl("authorEndingsJson"),
  fallbackToneEl: mustEl("fallbackTone"),
  fallbackActionTypeEl: mustEl("fallbackActionType"),

  statusEl: mustEl("authorStatus"),
  errorsListEl: mustEl("authorErrorsList"),
  warningsListEl: mustEl("authorWarningsList"),
  mappingsEl: mustEl("authorMappings"),
  previewEl: mustEl("compiledPreview"),
  playtestInfoEl: mustEl("authorPlaytestInfo"),

  layerIntentEl: mustEl("authorLayerIntent"),
  assistStatusEl: mustEl("assistStatus"),
  assistFeedbackEl: mustEl("authorLlmFeedback"),
  assistSuggestionsEl: mustEl("assistSuggestions"),
  assistPatchPreviewEl: mustEl("assistPatchPreview"),
  storyOverviewListEl: mustEl("authorStoryOverviewList"),
  writerTurnFeedEl: mustEl("writerTurnFeed"),
  writerTurnTemplateEl: mustEl("writerTurnTemplate"),
  playabilityBlockingEl: mustEl("authorPlayabilityBlocking"),
  playabilityBlockingMainEl: mustEl("authorPlayabilityBlockingMain"),
  playabilityMetricsEl: mustEl("authorPlayabilityMetrics"),
  funConflictEl: mustEl("authorFunConflictValue"),
  funBranchEl: mustEl("authorFunBranchValue"),
  funRecoveryEl: mustEl("authorFunRecoveryValue"),
  funDeadlineEl: mustEl("authorFunDeadlineValue"),

  validateBtnEl: mustEl("validateAuthorBtn"),
  compileBtnEl: mustEl("compileAuthorBtn"),
  saveDraftBtnEl: mustEl("saveDraftBtn"),
  playtestBtnEl: mustEl("playtestBtn"),

  addActBtnEl: mustEl("addActBtn"),
  addSceneBtnEl: mustEl("addSceneBtn"),
  loadTemplateBtnEl: mustEl("loadTemplateBtn"),

  assistBootstrapBtnEl: mustEl("assistBootstrapBtn"),
  assistCancelBtnEl: mustEl("assistCancelBtn"),
  assistRefineWorldBtnEl: mustEl("assistRefineWorldBtn"),
  assistRefineCharactersBtnEl: mustEl("assistRefineCharactersBtn"),
  assistRefinePlotBtnEl: mustEl("assistRefinePlotBtn"),
  assistSceneOptionsBtnEl: mustEl("assistSceneOptionsBtn"),
  assistIntentAliasesBtnEl: mustEl("assistIntentAliasesBtn"),
  assistRefineSceneBtnEl: mustEl("assistRefineSceneBtn"),
  assistRefineActionBtnEl: mustEl("assistRefineActionBtn"),
  assistRefineConsequenceBtnEl: mustEl("assistRefineConsequenceBtn"),
  assistRefineEndingBtnEl: mustEl("assistRefineEndingBtn"),
  assistConsistencyBtnEl: mustEl("assistConsistencyBtn"),
  continueWriteBtnEl: mustEl("continueWriteBtn"),
  trimContentBtnEl: mustEl("trimContentBtn"),
  spiceBranchBtnEl: mustEl("spiceBranchBtn"),
  tensionRebalanceBtnEl: mustEl("tensionRebalanceBtn"),
  applySelectedPatchBtnEl: mustEl("applySelectedPatchBtn"),
  undoPatchBtnEl: mustEl("undoPatchBtn"),
};

const AUTHOR_DEBUG_STORAGE_KEY = "author_show_debug";
const AUTO_APPLY_ASSIST_TASKS = new Set(
  Array.isArray(assistHelpers.autoApplyTasks) && assistHelpers.autoApplyTasks.length
    ? assistHelpers.autoApplyTasks
    : [
      "story_ingest",
      "seed_expand",
      "beat_to_scene",
      "scene_deepen",
      "option_weave",
      "consequence_balance",
      "ending_design",
      "consistency_check",
      "continue_write",
      "trim_content",
      "spice_branch",
      "tension_rebalance",
    ],
);
const LONG_WAIT_ASSIST_TASKS = new Set(["story_ingest", "seed_expand", "continue_write"]);
const ASSIST_STAGE_CODE_TO_STATE = {
  "author.expand.start": "requesting",
  "author.single.start": "requesting",
  "author.build.start": "building",
  "llm.retry": "retrying",
};
const ASSIST_STAGE_CLASSES = ["assist-stage--requesting", "assist-stage--building", "assist-stage--retrying"];

function cloneJson(input) {
  if (patchHelpers.cloneJson) return patchHelpers.cloneJson(input);
  return JSON.parse(JSON.stringify(input));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function parseCsv(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseLines(value) {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

const KNOWN_ACTION_IDS = new Set(["study", "work", "rest", "date", "gift"]);

function serializeNpcsToNarrative(npcs) {
  if (!Array.isArray(npcs) || !npcs.length) return "";
  return npcs
    .map((npc) => {
      if (!npc || typeof npc !== "object") return "";
      const name = String(npc.name || "").trim();
      if (!name) return "";
      const role = String(npc.role || "").trim() || "unknown role";
      const traits = Array.isArray(npc.traits)
        ? npc.traits.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
      const traitText = traits.length ? traits.join(", ") : "none";
      return `${name} | ${role} | traits: ${traitText}`;
    })
    .filter(Boolean)
    .join("\n");
}

function parseNpcsNarrative(raw) {
  const lines = parseLines(raw);
  const out = [];
  const seen = new Set();
  lines.forEach((line, idx) => {
    const parts = line.split("|").map((part) => part.trim()).filter(Boolean);
    if (parts.length < 2) {
      throw new Error(`NPC template line ${idx + 1} is invalid. Use "Name | role | traits: trait1, trait2".`);
    }
    const name = String(parts[0] || "").trim();
    const role = String(parts[1] || "").trim();
    if (!name || !role) {
      throw new Error(`NPC template line ${idx + 1} is missing name or role.`);
    }
    const dedupeKey = name.toLowerCase();
    if (seen.has(dedupeKey)) return;
    seen.add(dedupeKey);
    const traitsPart = parts.slice(2).join(" | ");
    let traits = [];
    if (traitsPart) {
      const normalizedTraits = traitsPart.replace(/^traits\s*:\s*/i, "");
      traits = normalizedTraits
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    out.push({
      name,
      role,
      traits,
    });
  });
  return out;
}

function serializeAxesToNarrative(axes) {
  if (!axes || typeof axes !== "object" || Array.isArray(axes)) return "";
  return Object.entries(axes)
    .map(([key, value]) => {
      const axis = String(key || "").trim();
      const desc = String(value || "").trim();
      if (!axis || !desc) return "";
      return `${axis}: ${desc}`;
    })
    .filter(Boolean)
    .join("\n");
}

function parseAxesNarrative(raw) {
  const lines = parseLines(raw);
  const out = {};
  lines.forEach((line, idx) => {
    const sep = line.indexOf(":");
    if (sep <= 0) {
      throw new Error(`Relationship axis line ${idx + 1} is invalid. Use "axis: natural-language description".`);
    }
    const key = line.slice(0, sep).trim();
    const value = line.slice(sep + 1).trim();
    if (!key || !value) {
      throw new Error(`Relationship axis line ${idx + 1} is missing key or description.`);
    }
    out[key] = value;
  });
  return out;
}

function serializeActionCatalogToNarrative(actionCatalog) {
  if (!Array.isArray(actionCatalog) || !actionCatalog.length) return "";
  return actionCatalog
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const actionId = String(item.action_id || "").trim();
      if (!actionId) return "";
      const label = String(item.label || "").trim() || "General action";
      return `${actionId}: ${label}`;
    })
    .filter(Boolean)
    .join("\n");
}

function parseActionCatalogNarrative(raw) {
  const lines = parseLines(raw);
  const out = [];
  const seen = new Set();
  lines.forEach((line, idx) => {
    const sep = line.indexOf(":");
    if (sep <= 0) {
      throw new Error(`Action line ${idx + 1} is invalid. Use "action_id: natural-language label or usage note".`);
    }
    const actionId = line.slice(0, sep).trim().toLowerCase();
    const label = line.slice(sep + 1).trim();
    if (!actionId || !label) {
      throw new Error(`Action line ${idx + 1} is missing action_id or label.`);
    }
    if (!KNOWN_ACTION_IDS.has(actionId)) {
      throw new Error(`Action line ${idx + 1} uses unsupported action_id "${actionId}".`);
    }
    if (seen.has(actionId)) return;
    seen.add(actionId);
    out.push({
      action_id: actionId,
      label,
      defaults: {},
    });
  });
  return out;
}

function summarizeConsequenceNarrative(story) {
  const consequence = story?.consequence && typeof story.consequence === "object" ? story.consequence : {};
  const axes = Array.isArray(consequence.state_axes) ? consequence.state_axes.filter(Boolean) : [];
  const questRules = Array.isArray(consequence.quest_progression_rules) ? consequence.quest_progression_rules : [];
  const eventRules = Array.isArray(consequence.event_rules) ? consequence.event_rules : [];
  const questCount = questRules.length;
  const eventCount = eventRules.length;
  const axisText = axes.length ? axes.join(", ") : "no state axes configured yet";
  return [
    `State outcomes are currently tracked through ${axisText}.`,
    `Quest progression defines ${questCount} rule${questCount === 1 ? "" : "s"}, while event automation defines ${eventCount} rule${eventCount === 1 ? "" : "s"}.`,
    "Use Refine This Layer to rebalance penalties, rewards, and pacing without editing raw structures directly.",
  ].join(" ");
}

function summarizeEndingNarrative(story) {
  const ending = story?.ending && typeof story.ending === "object" ? story.ending : {};
  const systems = story?.systems && typeof story.systems === "object" ? story.systems : {};
  const endings = Array.isArray(ending.ending_rules) ? ending.ending_rules : [];
  const tone = String(systems.fallback_style?.tone || "supportive").trim();
  const fallbackAction = String(systems.fallback_style?.action_type || "rest").trim();
  const endingTitles = endings
    .map((item) => String(item?.title || item?.ending_key || "").trim())
    .filter(Boolean)
    .slice(0, 2);
  const endingText = endingTitles.length
    ? `Current ending focus includes ${endingTitles.join(" and ")}.`
    : "No explicit ending rules are configured yet.";
  return [
    endingText,
    `Fallback narration tone is ${tone}, and fallback action defaults to ${fallbackAction}.`,
    "Use Refine This Layer to tighten ending contrast while keeping compile-safe triggers.",
  ].join(" ");
}

function parseJsonText(raw, fallback, label) {
  const text = String(raw || "").trim();
  if (!text) return cloneJson(fallback);
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} format is invalid: ${error.message}`);
  }
  return parsed;
}

function parseJsonArray(raw, fallback, label) {
  const parsed = parseJsonText(raw, fallback, label);
  if (!Array.isArray(parsed)) throw new Error(`${label} must be an array.`);
  return parsed;
}

function parseJsonObject(raw, fallback, label) {
  const parsed = parseJsonText(raw, fallback, label);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be an object.`);
  }
  return parsed;
}

function intentModuleDefaults(authorInput = "") {
  return {
    author_input: authorInput,
    intent_tags: [],
    parse_notes: "",
    aliases: [],
  };
}

function actDefaults(index) {
  return {
    act_key: `act_${index}`,
    title: `Act ${index}`,
    objective: "",
    scene_keys: [],
  };
}

function optionDefaults(actionType = "rest", index = 1) {
  return {
    option_key: `opt_${index}`,
    label: actionType === "study" ? "Focus on study" : "Take a quick reset",
    intent_aliases: [],
    action_type: actionType,
    action_params: {},
    go_to: "",
    effects: {},
    requirements: {},
    is_key_decision: false,
  };
}

function sceneDefaults(index = 0) {
  const slot = index + 1;
  const isFirst = index === 0;
  const isEnd = index === 1;
  return {
    scene_key: isFirst ? "scene_intro" : `scene_${slot}`,
    title: isFirst ? "Morning Setup" : `Scene ${slot}`,
    setup: isFirst ? "Morning on campus. You only have one clean block before lunch." : `Scene ${slot} setup.`,
    dramatic_question: "",
    options: [optionDefaults("study", 1), optionDefaults("rest", 2)],
    free_input_hints: [],
    fallback: null,
    is_end: isEnd,
    intent_module: intentModuleDefaults(""),
  };
}

function storyDefaults() {
  return {
    format_version: 4,
    entry_mode: "spark",
    source_text: null,
    meta: {
      story_id: "author_story_v4",
      version: 1,
      title: "Author Demo Story v4",
      summary: "",
      locale: "en",
    },
    world: {
      era: "Contemporary semester",
      location: "University district",
      boundaries: "No supernatural powers; time and resources are limited.",
      social_rules: "People respond to consistency under pressure.",
      global_state: {
        initial_state: {
          energy: 80,
          money: 50,
          knowledge: 0,
          affection: 0,
          day: 1,
          slot: "morning",
        },
      },
      intent_module: intentModuleDefaults(""),
    },
    characters: {
      protagonist: {
        name: "You",
        role: "student",
        traits: ["driven", "adaptive"],
        resources: {},
      },
      npcs: [{ name: "Alice", role: "friend", traits: ["warm", "direct"] }],
      relationship_axes: { trust: "kept promises" },
      intent_module: intentModuleDefaults(""),
    },
    plot: {
      mainline_acts: [actDefaults(1), actDefaults(2)],
      sideline_threads: ["Protect your energy", "Keep one relationship alive"],
      mainline_goal: "Finish the week with stable momentum.",
      intent_module: intentModuleDefaults(""),
    },
    flow: {
      start_scene_key: "scene_intro",
      scenes: [sceneDefaults(0), sceneDefaults(1)],
      intent_module: intentModuleDefaults(""),
    },
    action: {
      action_catalog: [
        { action_id: "study", label: "Study", defaults: {} },
        { action_id: "work", label: "Work", defaults: {} },
        { action_id: "rest", label: "Rest", defaults: {} },
      ],
      input_mapping_policy: "intent_alias_only_visible_choice",
      intent_module: intentModuleDefaults(""),
    },
    consequence: {
      state_axes: ["energy", "money", "knowledge", "affection", "day", "slot"],
      quest_progression_rules: [],
      event_rules: [],
      intent_module: intentModuleDefaults(""),
    },
    ending: {
      ending_rules: [
        {
          ending_key: "steady_finish",
          title: "Steady Finish",
          priority: 100,
          outcome: "success",
          trigger: { scene_key_is: "scene_intro" },
          epilogue: "You close this arc with enough momentum for the next chapter.",
        },
      ],
      intent_module: intentModuleDefaults(""),
    },
    systems: {
      fallback_style: {
        tone: "supportive",
        action_type: "rest",
      },
      events: [],
      intent_module: intentModuleDefaults(""),
    },
    writer_journal: [],
    playability_policy: {
      ending_reach_rate_min: 0.6,
      stuck_turn_rate_max: 0.05,
      no_progress_rate_max: 0.25,
      branch_coverage_warn_below: 0.3,
      choice_contrast_warn_below: 0.45,
      dominant_strategy_warn_above: 0.75,
      recovery_window_warn_below: 0.55,
      tension_loop_warn_below: 0.5,
      dominant_strategy_block_above: 0.9,
      low_branch_with_dominant_block_below: 0.2,
      recovery_window_block_below: 0.25,
      rollout_strategies: 3,
      rollout_runs_per_strategy: 80,
    },
  };
}

function setStatus(message, stateName = "") {
  refs.statusEl.textContent = String(message || "").trim() || "Ready.";
  refs.statusEl.setAttribute("data-state", stateName || "");
}

function setAssistStatus(message, stateName = "") {
  refs.assistStatusEl.textContent = String(message || "").trim() || "No suggestions yet.";
  refs.assistStatusEl.setAttribute("data-state", stateName || "");
}

function setAssistFeedback(message, stateName = "idle") {
  const text = String(message || "").trim();
  const normalizedState = String(stateName || "idle");
  refs.assistFeedbackEl.textContent = text || "Idle";
  refs.assistFeedbackEl.setAttribute("data-state", normalizedState);
  refs.assistFeedbackEl.classList.toggle("hidden", !text || normalizedState === "idle");
}

function _assistStageStateFromCode(stageCode) {
  const code = String(stageCode || "").trim();
  return ASSIST_STAGE_CODE_TO_STATE[code] || "";
}

function _applyAssistStageState(stageState, activeButton = null) {
  const normalized = String(stageState || "").trim();
  const stageClass = normalized ? `assist-stage--${normalized}` : "";
  state.assistStageState = normalized;

  assistButtons().forEach((button) => {
    ASSIST_STAGE_CLASSES.forEach((className) => button.classList.remove(className));
    button.removeAttribute("data-stage");
  });

  refs.assistFeedbackEl.removeAttribute("data-stage");
  refs.assistStatusEl.removeAttribute("data-stage");
  if (!normalized) return;

  if (activeButton) {
    activeButton.classList.add(stageClass);
    activeButton.setAttribute("data-stage", normalized);
  }
  refs.assistFeedbackEl.setAttribute("data-stage", normalized);
  refs.assistStatusEl.setAttribute("data-stage", normalized);
}

function setAssistRetryHint(message = "", visible = false) {
  const text = String(message || "").trim();
  refs.assistRetryHintEl.textContent = text || "Model unavailable. Please retry.";
  refs.assistRetryHintEl.classList.toggle("hidden", !visible);
}

function setPlaytestInfo(message, stateName = "") {
  refs.playtestInfoEl.textContent = String(message || "").trim() || "No playtest session yet.";
  refs.playtestInfoEl.setAttribute("data-state", stateName || "");
}

function assistButtons() {
  return [
    refs.assistBootstrapBtnEl,
    refs.assistRefineWorldBtnEl,
    refs.assistRefineCharactersBtnEl,
    refs.assistRefinePlotBtnEl,
    refs.assistSceneOptionsBtnEl,
    refs.assistIntentAliasesBtnEl,
    refs.assistRefineSceneBtnEl,
    refs.assistRefineActionBtnEl,
    refs.assistRefineConsequenceBtnEl,
    refs.assistRefineEndingBtnEl,
    refs.assistConsistencyBtnEl,
    refs.continueWriteBtnEl,
    refs.trimContentBtnEl,
    refs.spiceBranchBtnEl,
    refs.tensionRebalanceBtnEl,
  ];
}

function setAssistButtonsDisabled(disabled, { except = null } = {}) {
  assistButtons().forEach((button) => {
    if (button === except) return;
    button.disabled = Boolean(disabled);
  });
}

function isLongWaitAssistTask(task) {
  const taskName = String(task || "").trim();
  return LONG_WAIT_ASSIST_TASKS.has(taskName);
}

function setAssistCancelVisibility(visible) {
  refs.assistCancelBtnEl.classList.toggle("hidden", !visible);
  refs.assistCancelBtnEl.disabled = !visible;
}

function clearAssistAbortState() {
  state.assistAbortController = null;
  state.assistCancelableTask = null;
  setAssistCancelVisibility(false);
}

function createAssistAbortController(task) {
  if (!isLongWaitAssistTask(task)) {
    clearAssistAbortState();
    return null;
  }
  const controller = new AbortController();
  state.assistAbortController = controller;
  state.assistCancelableTask = String(task || "");
  setAssistCancelVisibility(true);
  return controller;
}

function readShowDebugPreference() {
  try {
    return window.localStorage.getItem(AUTHOR_DEBUG_STORAGE_KEY) === "1";
  } catch (error) {
    return false;
  }
}

function persistShowDebugPreference(enabled) {
  try {
    if (enabled) {
      window.localStorage.setItem(AUTHOR_DEBUG_STORAGE_KEY, "1");
      return;
    }
    window.localStorage.removeItem(AUTHOR_DEBUG_STORAGE_KEY);
  } catch (error) {
    // Ignore persistence errors in private browsing or restricted environments.
  }
}

function renderTabUi() {
  const showDebug = Boolean(state.ui.show_debug);
  refs.debugToggleEl.checked = showDebug;
  refs.tabDebugBtnEl.classList.toggle("hidden", !showDebug);
  refs.tabDebugBtnEl.toggleAttribute("hidden", !showDebug);

  if (!showDebug && state.ui.active_tab === "debug") {
    state.ui.active_tab = "author";
  }
  const activeTab = state.ui.active_tab === "debug" && showDebug ? "debug" : "author";
  const authorActive = activeTab === "author";

  refs.tabAuthorBtnEl.classList.toggle("is-active", authorActive);
  refs.tabAuthorBtnEl.setAttribute("aria-selected", String(authorActive));
  refs.tabDebugBtnEl.classList.toggle("is-active", !authorActive);
  refs.tabDebugBtnEl.setAttribute("aria-selected", String(!authorActive));

  refs.mainFlowEl.classList.toggle("hidden", !authorActive);
  refs.debugPanelEl.classList.toggle("hidden", authorActive);
}

function renderPageUi() {
  const availablePages = Array.isArray(stateHelpers.pages) && stateHelpers.pages.length
    ? stateHelpers.pages
    : ["compose", "shape", "build"];
  if (!availablePages.includes(state.ui.active_page)) {
    state.ui.active_page = "compose";
  }
  const page = state.ui.active_page;
  const authorTabActive = !(state.ui.active_tab === "debug" && state.ui.show_debug);

  refs.pageComposeBtnEl.classList.toggle("is-active", page === "compose");
  refs.pageShapeBtnEl.classList.toggle("is-active", page === "shape");
  refs.pageBuildBtnEl.classList.toggle("is-active", page === "build");

  refs.pageComposeEl.classList.toggle("hidden", page !== "compose");
  refs.pageShapeEl.classList.toggle("hidden", page !== "shape");
  refs.pageBuildEl.classList.toggle("hidden", page !== "build");

  const shapeActive = page === "shape" && authorTabActive;
  refs.structureCollapseEl.classList.toggle("hidden", !shapeActive);
  refs.structureCollapseEl.toggleAttribute("hidden", !shapeActive);
}

function syncFocusPanelsFromState() {
  refs.structureCollapseEl.open = Boolean(state.ui?.panels?.structure_open);
  refs.reviewAdvancedToggleEl.open = Boolean(state.ui?.panels?.review_advanced_open);
}

function normalizeNextStepText(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  return value.endsWith(".") ? value : `${value}.`;
}

function actionableFromDiagnostic(item) {
  const suggestion = normalizeNextStepText(item?.suggestion);
  if (suggestion) return suggestion;

  const message = String(item?.message || "").trim();
  const code = String(item?.code || "");
  if (!message) {
    return code ? normalizeNextStepText(code.replaceAll("_", " ").toLowerCase()) : "";
  }

  if (/go_to|dangling|missing.*scene/i.test(message)) {
    return "Connect every option go_to to an existing scene key.";
  }
  if (/ending/i.test(message) && /missing|unreachable|reach/i.test(message)) {
    return "Add or connect ending rules so at least one ending is reachable.";
  }
  if (/option/i.test(message) && /2-4|required/i.test(message)) {
    return "Keep each non-end scene at 2 to 4 options.";
  }
  if (/playability|stuck|progress/i.test(message)) {
    return "Adjust scene links and effects to keep momentum and avoid dead-ends.";
  }
  return normalizeNextStepText(message);
}

function computeNextSteps({ errors = [], warnings = [], playability = null } = {}) {
  const steps = [];
  const pushStep = (value) => {
    const text = normalizeNextStepText(value);
    if (!text) return;
    if (!steps.includes(text)) steps.push(text);
  };

  (Array.isArray(errors) ? errors : []).forEach((item) => pushStep(actionableFromDiagnostic(item)));
  const blocking = Array.isArray(playability?.blocking_errors) ? playability.blocking_errors : [];
  blocking.forEach((item) => pushStep(actionableFromDiagnostic(item)));

  if (steps.length === 0) {
    (Array.isArray(warnings) ? warnings : []).forEach((item) => pushStep(actionableFromDiagnostic(item)));
  }

  if (steps.length === 0) {
    pushStep("Story is in good shape. Compile StoryPack, then save draft and playtest");
    pushStep("Open Shape page to fine-tune scene options and pacing");
  } else {
    pushStep("After applying these fixes, run Validate again to confirm");
  }
  return steps.slice(0, 6);
}

function renderNextSteps() {
  refs.nextStepsEl.innerHTML = "";
  const items = Array.isArray(state.nextSteps) ? state.nextSteps : [];
  if (!items.length) {
    const row = document.createElement("li");
    row.className = "summary-list--empty";
    row.textContent = "Use Parse All Layers to generate your first draft.";
    refs.nextStepsEl.appendChild(row);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("li");
    row.textContent = String(item || "");
    refs.nextStepsEl.appendChild(row);
  });
}

function renderDiagnosticList(targetEl, items, emptyText) {
  targetEl.innerHTML = "";
  if (!Array.isArray(items) || items.length === 0) {
    const row = document.createElement("li");
    row.className = "summary-list--empty";
    row.textContent = emptyText;
    targetEl.appendChild(row);
    return;
  }
  items.forEach((item) => {
    const code = String(item?.code || "UNKNOWN");
    const path = String(item?.path || "");
    const message = String(item?.message || "");
    const suggestion = String(item?.suggestion || "");
    const row = document.createElement("li");
    row.textContent = `${code}${path ? ` [${path}]` : ""}: ${message}${suggestion ? ` -> ${suggestion}` : ""}`;
    targetEl.appendChild(row);
  });
}

function renderStepper() {
  const items = Array.from(refs.stepperEl.querySelectorAll(".stepper__item"));
  items.forEach((item, idx) => {
    item.classList.toggle("is-active", idx === state.stepIndex);
  });

  const steps = Array.from(document.querySelectorAll(".wizard-step"));
  steps.forEach((step) => {
    const idx = Number(step.dataset.stepIndex);
    step.classList.toggle("is-active", idx === state.stepIndex);
  });

  refs.prevStepBtnEl.disabled = state.stepIndex <= 0;
  refs.nextStepBtnEl.disabled = state.stepIndex >= 7;
}

function renderWorldFields() {
  state.entryMode = String(state.story.entry_mode || state.entryMode || "spark");
  const entryContainer = document.querySelector('[data-testid="author-entry-mode"]');
  if (entryContainer) entryContainer.setAttribute("data-mode", state.entryMode);

  refs.storyIdEl.value = state.story.meta.story_id || "";
  refs.versionEl.value = String(state.story.meta.version || 1);
  refs.titleEl.value = state.story.meta.title || "";
  refs.localeEl.value = state.story.meta.locale || "en";
  refs.summaryEl.value = state.story.meta.summary || "";
  refs.seedInputEl.value = refs.seedInputEl.value || "";
  refs.sourceInputEl.value = state.story.source_text || refs.sourceInputEl.value || "";

  refs.worldEraEl.value = state.story.world.era || "";
  refs.worldLocationEl.value = state.story.world.location || "";
  refs.worldBoundariesEl.value = state.story.world.boundaries || "";
  refs.worldSocialRulesEl.value = state.story.world.social_rules || "";

  if (!refs.globalBriefEl.value.trim()) {
    refs.globalBriefEl.value = state.story.world.intent_module?.author_input || "";
  }
}

function renderCharactersFields() {
  refs.protagonistNameEl.value = state.story.characters.protagonist?.name || "";
  refs.protagonistRoleEl.value = state.story.characters.protagonist?.role || "";
  refs.protagonistTraitsEl.value = (state.story.characters.protagonist?.traits || []).join(", ");
  refs.npcsNarrativeEl.value = serializeNpcsToNarrative(state.story.characters.npcs || []);
  refs.axesNarrativeEl.value = serializeAxesToNarrative(state.story.characters.relationship_axes || {});
  refs.npcsJsonEl.value = JSON.stringify(state.story.characters.npcs || [], null, 2);
  refs.axesJsonEl.value = JSON.stringify(state.story.characters.relationship_axes || {}, null, 2);
}

function renderPlotFields() {
  refs.mainlineGoalEl.value = state.story.plot.mainline_goal || "";
  refs.sidelineThreadsEl.value = (state.story.plot.sideline_threads || []).join("\n");
}

function renderActs() {
  refs.actsEl.innerHTML = "";
  const acts = state.story.plot.mainline_acts || [];
  acts.forEach((act, index) => {
    const card = document.createElement("article");
    card.className = "act-card";
    card.dataset.actIndex = String(index);
    card.innerHTML = `
      <div class="act-card__head">
        <div class="scene-card__title">Act ${index + 1}</div>
        <button type="button" class="btn btn--ghost" data-action="remove-act">Remove Act</button>
      </div>
      <div class="author-grid">
        <label class="field">
          <span>Act Key</span>
          <input data-act-field="act_key" value="${String(act.act_key || "").replace(/"/g, "&quot;")}" />
        </label>
        <label class="field">
          <span>Title</span>
          <input data-act-field="title" value="${String(act.title || "").replace(/"/g, "&quot;")}" />
        </label>
      </div>
      <label class="field">
        <span>Objective</span>
        <textarea rows="2" data-act-field="objective">${String(act.objective || "")}</textarea>
      </label>
      <label class="field">
        <span>Scene Keys (comma separated)</span>
        <input data-act-field="scene_keys" value="${String((act.scene_keys || []).join(", ")).replace(/"/g, "&quot;")}" />
      </label>
    `;
    refs.actsEl.appendChild(card);
  });
}

function renderScenes() {
  refs.scenesEl.innerHTML = "";
  (state.story.flow.scenes || []).forEach((scene, sceneIndex) => {
    const isSelectedScene = sceneIndex === state.selectedSceneIndex;
    const card = document.createElement("article");
    card.className = `scene-card${isSelectedScene ? " is-selected" : ""}`;
    card.dataset.sceneIndex = String(sceneIndex);

    const optionsHtml = (scene.options || []).map((option, optionIndex) => {
      const isSelectedOption = isSelectedScene && optionIndex === state.selectedOptionIndex;
      const actionType = String(option.action_type || "rest");
      return `
      <div class="scene-option ${isSelectedOption ? "is-selected" : ""}" data-option-index="${optionIndex}">
        <div class="scene-option__head">
          <strong>Option ${optionIndex + 1}</strong>
          <div class="author-toolbar scene-option__actions">
            <button type="button" class="btn btn--ghost" data-action="select-option" data-option-index="${optionIndex}">Target for AI</button>
            <button type="button" class="btn btn--ghost" data-action="remove-option" data-option-index="${optionIndex}">Remove Option</button>
          </div>
        </div>
        <div class="scene-option__core-grid">
          <label class="field">
            <span>Option Label</span>
            <input data-option-field="label" value="${escapeHtml(option.label || "")}" />
          </label>
          <label class="field">
            <span>Go To Scene Key</span>
            <input data-option-field="go_to" value="${escapeHtml(option.go_to || "")}" />
          </label>
        </div>
        <details class="advanced-block scene-option__advanced" data-testid="author-scene-advanced-toggle">
          <summary>Option Advanced</summary>
          <div class="scene-option__grid">
            <label class="field">
              <span>Option Key</span>
              <input data-option-field="option_key" value="${escapeHtml(option.option_key || "")}" />
            </label>
            <label class="field">
              <span>Action Type</span>
              <select data-option-field="action_type">
                ${["study", "work", "rest", "date", "gift"].map((action) => `<option value="${action}" ${actionType === action ? "selected" : ""}>${action}</option>`).join("")}
              </select>
            </label>
            <label class="field">
              <span>Intent Aliases (comma separated)</span>
              <input data-option-field="intent_aliases" value="${escapeHtml((option.intent_aliases || []).join(", "))}" />
            </label>
            <label class="field">
              <span>Key Decision</span>
              <input data-option-field="is_key_decision" type="checkbox" ${option.is_key_decision ? "checked" : ""} />
            </label>
            <label class="field">
              <span>Min Energy</span>
              <input data-option-field="requirements.min_energy" type="number" value="${escapeHtml(option.requirements?.min_energy ?? "")}" />
            </label>
            <label class="field">
              <span>Min Money</span>
              <input data-option-field="requirements.min_money" type="number" value="${escapeHtml(option.requirements?.min_money ?? "")}" />
            </label>
            <label class="field">
              <span>Energy Delta</span>
              <input data-option-field="effects.energy" type="number" value="${escapeHtml(option.effects?.energy ?? "")}" />
            </label>
            <label class="field">
              <span>Money Delta</span>
              <input data-option-field="effects.money" type="number" value="${escapeHtml(option.effects?.money ?? "")}" />
            </label>
            <label class="field">
              <span>Knowledge Delta</span>
              <input data-option-field="effects.knowledge" type="number" value="${escapeHtml(option.effects?.knowledge ?? "")}" />
            </label>
            <label class="field">
              <span>Affection Delta</span>
              <input data-option-field="effects.affection" type="number" value="${escapeHtml(option.effects?.affection ?? "")}" />
            </label>
          </div>
        </details>
      </div>`;
    }).join("");

    card.innerHTML = `
      <div class="scene-card__head">
        <div class="scene-card__title">Scene ${sceneIndex + 1}</div>
        <div class="author-toolbar">
          <button type="button" class="btn btn--ghost" data-action="select-scene">Target for AI</button>
          <button type="button" class="btn btn--ghost" data-action="remove-scene">Remove Scene</button>
        </div>
      </div>
      <div class="scene-core-grid">
        <label class="field">
          <span>Scene Key</span>
          <input data-scene-field="scene_key" value="${escapeHtml(scene.scene_key || "")}" />
        </label>
        <label class="field">
          <span>Title</span>
          <input data-scene-field="title" value="${escapeHtml(scene.title || "")}" />
        </label>
      </div>
      <label class="field">
        <span>Setup</span>
        <textarea rows="2" data-scene-field="setup">${escapeHtml(scene.setup || "")}</textarea>
      </label>
      <details class="advanced-block scene-card__advanced" data-testid="author-scene-advanced-toggle">
        <summary>Scene Advanced</summary>
        <div class="scene-option__grid">
          <label class="field">
            <span>Dramatic Question</span>
            <input data-scene-field="dramatic_question" value="${escapeHtml(scene.dramatic_question || "")}" />
          </label>
          <label class="field">
            <span>Free Input Hints (comma separated)</span>
            <input data-scene-field="free_input_hints" value="${escapeHtml((scene.free_input_hints || []).join(", "))}" />
          </label>
          <label class="field">
            <span>End Scene</span>
            <input data-scene-field="is_end" type="checkbox" ${scene.is_end ? "checked" : ""} />
          </label>
        </div>
      </details>
      <div class="scene-card__options">${optionsHtml}</div>
      <div class="author-toolbar">
        <button type="button" class="btn btn--ghost" data-action="add-option">Add Option</button>
      </div>
    `;
    refs.scenesEl.appendChild(card);
  });
}

function renderActionFields() {
  refs.actionMappingPolicyEl.value = state.story.action.input_mapping_policy || "intent_alias_only_visible_choice";
  refs.actionCatalogNarrativeEl.value = serializeActionCatalogToNarrative(state.story.action.action_catalog || []);
  refs.actionCatalogJsonEl.value = JSON.stringify(state.story.action.action_catalog || [], null, 2);
}

function renderConsequenceFields() {
  refs.consequenceStateAxesEl.value = (state.story.consequence.state_axes || []).join(",");
  refs.consequenceNarrativeSummaryEl.value = summarizeConsequenceNarrative(state.story);
  refs.questsJsonEl.value = JSON.stringify(state.story.consequence.quest_progression_rules || [], null, 2);
  refs.eventsJsonEl.value = JSON.stringify(state.story.consequence.event_rules || [], null, 2);
}

function renderEndingFields() {
  refs.endingNarrativeSummaryEl.value = summarizeEndingNarrative(state.story);
  refs.endingsJsonEl.value = JSON.stringify(state.story.ending.ending_rules || [], null, 2);
  refs.fallbackToneEl.value = String(state.story.systems.fallback_style?.tone || "supportive");
  refs.fallbackActionTypeEl.value = String(state.story.systems.fallback_style?.action_type || "rest");
}

function renderLayerIntentPanel() {
  const payload = {};
  LAYER_KEYS.forEach((key) => {
    const layer = state.story[key];
    if (layer && typeof layer === "object" && layer.intent_module) {
      payload[key] = layer.intent_module;
    }
  });
  refs.layerIntentEl.textContent = JSON.stringify(payload, null, 2);
}

function renderAssistPanel() {
  refs.assistSuggestionsEl.textContent = JSON.stringify(state.assistSuggestions || {}, null, 2);
  refs.assistPatchPreviewEl.innerHTML = "";
  if (!Array.isArray(state.assistPatches) || state.assistPatches.length === 0) {
    refs.assistPatchPreviewEl.textContent = "No patch preview yet.";
    return;
  }

  state.assistPatches.forEach((patch, idx) => {
    const id = String(patch.id || `patch_${idx}`);
    const row = document.createElement("label");
    row.className = "assist-patch-row";
    row.innerHTML = `
      <input type="checkbox" data-patch-id="${id}" checked />
      <div>
        <strong>${String(patch.label || "Patch")}</strong>
        <div class="assist-patch-path">${String(patch.path || "")}</div>
      </div>
    `;
    refs.assistPatchPreviewEl.appendChild(row);
  });
}

function _compactOverviewText(value, maxLen = 140) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 1).trimEnd()}...`;
}

function _normalizeOverviewRows(rawRows) {
  if (!Array.isArray(rawRows)) return [];
  return rawRows
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const label = String(item.label || "").trim();
      const value = String(item.value || "").trim();
      if (!label || !value) return null;
      return {
        label: _compactOverviewText(label, 40),
        value: _compactOverviewText(value, 220),
      };
    })
    .filter(Boolean);
}

function _setExpandOverviewRows(rows, source = "") {
  state.overviewFromExpandRows = Array.isArray(rows) ? rows : [];
  state.overviewFromExpandSource = String(source || "").trim();
  state.overviewFromExpandAt = Date.now();
  state.overviewFromExpandPending = false;
}

function _isZhLocale(locale) {
  return String(locale || "").trim().toLowerCase().startsWith("zh");
}

function _storyLocale() {
  return state?.story?.meta?.locale || "en";
}

function _overviewNarrativeFromRows(rows, locale) {
  const useZh = _isZhLocale(locale);
  const byLabel = {};
  rows.forEach((row) => {
    const key = String(row?.label || "").trim().toLowerCase();
    if (!key) return;
    byLabel[key] = String(row?.value || "").trim();
  });

  const coreConflict = byLabel["core conflict"] || byLabel["current conflict"] || "";
  const tensionLoop = byLabel["tension loop"] || "";
  const branchContrast = byLabel["branch contrast"] || byLabel["branch snapshot"] || "";
  const lexicalAnchors = byLabel["lexical anchors"] || "";
  const taskFocus = byLabel["task focus"] || byLabel["latest update"] || "";

  if (useZh) {
    const sentences = [
      coreConflict
        ? `当前核心冲突是：${coreConflict}。`
        : "当前核心冲突仍在推进中，建议继续强化冲突主体与时间压力。",
      tensionLoop
        ? `叙事张力按照以下节奏推进：${tensionLoop}。`
        : "叙事节奏建议保持“施压—升级—缓冲—决断”的循环。",
      branchContrast
        ? `分支对比目前聚焦于：${branchContrast}。`
        : "分支对比仍可进一步拉开，尤其是高风险推进与恢复稳定路线。",
      lexicalAnchors
        ? `词汇锚点建议：${lexicalAnchors}。`
        : "词汇锚点建议保持具体实体词，避免泛化标签。",
      taskFocus
        ? `本轮写作重点是：${taskFocus}。`
        : "本轮建议优先完成结构闭环，再细化语言风格。",
    ];
    return sentences.join(" ");
  }

  const sentences = [
    coreConflict
      ? `The core conflict now centers on ${coreConflict}.`
      : "The core conflict is still forming, so prioritize clear pressure and stakes.",
    tensionLoop
      ? `The tension loop currently moves through ${tensionLoop}.`
      : "The narrative tempo should keep a pressure-escalation-recovery-decision rhythm.",
    branchContrast
      ? `Branch contrast is currently driven by ${branchContrast}.`
      : "Branch contrast can be strengthened by separating risk-heavy and stabilizing routes.",
    lexicalAnchors
      ? `Language anchors to keep: ${lexicalAnchors}.`
      : "Language anchors should stay concrete and avoid generic placeholders.",
    taskFocus
      ? `The current writing focus is ${taskFocus}.`
      : "The next pass should secure structural coherence before stylistic polish.",
  ];
  return sentences.join(" ");
}

function renderStoryOverview() {
  refs.storyOverviewListEl.innerHTML = "";
  const locale = _storyLocale();
  const expandRows = Array.isArray(state.overviewFromExpandRows) ? state.overviewFromExpandRows : [];
  if (expandRows.length) {
    const narrativeRow = document.createElement("li");
    narrativeRow.className = "overview-paragraph";
    narrativeRow.textContent = _overviewNarrativeFromRows(expandRows, locale);
    refs.storyOverviewListEl.appendChild(narrativeRow);
    return;
  }

  if (state.overviewFromExpandPending) {
    const waiting = document.createElement("li");
    waiting.className = "summary-list--empty";
    waiting.textContent = _isZhLocale(locale)
      ? "正在等待第一阶段扩写概要，请稍候..."
      : "Waiting for first-pass expansion narrative overview...";
    refs.storyOverviewListEl.appendChild(waiting);
    return;
  }

  if (!state.story || typeof state.story !== "object") {
    const empty = document.createElement("li");
    empty.className = "summary-list--empty";
    empty.textContent = _isZhLocale(locale)
      ? "请先运行 Parse All Layers 生成草稿概览。"
      : "Run Parse All Layers first to generate a draft narrative overview.";
    refs.storyOverviewListEl.appendChild(empty);
    return;
  }

  const flow = state.story.flow && typeof state.story.flow === "object" ? state.story.flow : {};
  const plot = state.story.plot && typeof state.story.plot === "object" ? state.story.plot : {};
  const scenes = Array.isArray(flow.scenes) ? flow.scenes : [];
  const totalSceneCount = scenes.length;
  const endSceneCount = scenes.filter((scene) => scene && scene.is_end === true).length;
  const startSceneKey = String(flow.start_scene_key || "").trim() || "n/a";

  const optionCounts = scenes.map((scene) => (Array.isArray(scene?.options) ? scene.options.length : 0));
  const totalOptions = optionCounts.reduce((sum, count) => sum + Number(count || 0), 0);
  const nonEndScenes = scenes.filter((scene) => scene && scene.is_end !== true);
  const nonEndOptions = nonEndScenes.reduce(
    (sum, scene) => sum + (Array.isArray(scene?.options) ? scene.options.length : 0),
    0,
  );
  const avgOptions = nonEndScenes.length ? (nonEndOptions / nonEndScenes.length) : 0;
  const actionTypes = new Set();
  scenes.forEach((scene) => {
    (Array.isArray(scene?.options) ? scene.options : []).forEach((option) => {
      const actionType = String(option?.action_type || "").trim();
      if (actionType) actionTypes.add(actionType);
    });
  });

  const currentConflict = _compactOverviewText(
    refs.globalBriefEl.value
      || refs.seedInputEl.value
      || refs.sourceInputEl.value
      || state.story.meta?.summary
      || "",
  ) || "Add a seed/global brief to clarify the core conflict.";

  const coreGoal = _compactOverviewText(plot.mainline_goal || "") || "Set a concrete mainline goal in Plot.";

  const recentLabels = (Array.isArray(state.assistPatches) ? state.assistPatches : [])
    .map((item) => _compactOverviewText(item?.label || "", 80))
    .filter(Boolean)
    .slice(0, 3);
  const warningCount = Array.isArray(state.assistWarnings) ? state.assistWarnings.length : 0;
  let latestUpdate = "";
  if (recentLabels.length) {
    latestUpdate = recentLabels.join(" | ");
    if (warningCount > 0) {
      latestUpdate += ` (${warningCount} warning${warningCount > 1 ? "s" : ""})`;
    }
  } else {
    const journal = Array.isArray(state.story.writer_journal) ? state.story.writer_journal : [];
    latestUpdate = _compactOverviewText(journal[journal.length - 1]?.assistant_text || "", 140);
  }
  if (!latestUpdate) {
    latestUpdate = "No recent assist updates yet.";
  }
  const structureSummary = `${totalSceneCount} scenes from ${startSceneKey}, with ${endSceneCount} ending scene${endSceneCount === 1 ? "" : "s"}.`;
  const branchSummary = `${totalOptions} options total, ${avgOptions.toFixed(1)} options per non-ending scene, and ${actionTypes.size} distinct action type${actionTypes.size === 1 ? "" : "s"}.`;

  const fallbackNarrative = _isZhLocale(locale)
    ? [
      `当前主线目标是：${coreGoal}。`,
      `当前冲突焦点是：${currentConflict}。`,
      `结构层面上，故事目前包含 ${structureSummary.replace(".", "")}。`,
      `分支层面上，故事目前有 ${branchSummary.replace(".", "")}。`,
      `最近一次更新显示：${latestUpdate}。`,
    ].join(" ")
    : [
      `The story currently aims to ${coreGoal}.`,
      `The active conflict is ${currentConflict}.`,
      `Structurally, the draft has ${structureSummary}`,
      `Branching-wise, it currently offers ${branchSummary}`,
      `The latest update indicates: ${latestUpdate}.`,
    ].join(" ");

  const narrativeRow = document.createElement("li");
  narrativeRow.className = "overview-paragraph";
  narrativeRow.textContent = fallbackNarrative;
  refs.storyOverviewListEl.appendChild(narrativeRow);
}

function renderWriterTurns() {
  refs.writerTurnFeedEl.innerHTML = "";
  const turns = Array.isArray(state.story.writer_journal) ? state.story.writer_journal : [];
  if (!turns.length) {
    refs.writerTurnFeedEl.textContent = "No writer turns yet. Run Spark or Ingest to start the co-writing loop.";
    return;
  }
  turns.forEach((turn, idx) => {
    const fragment = refs.writerTurnTemplateEl.content.cloneNode(true);
    const root = fragment.querySelector('[data-testid="author-turn-card"]');
    if (!root) return;
    const head = fragment.querySelector(".writer-turn__head");
    const author = fragment.querySelector(".writer-turn__author");
    const assistant = fragment.querySelector(".writer-turn__assistant");
    const phase = String(turn?.phase || "seed");
    if (head) head.textContent = `Turn ${idx + 1} · ${phase}`;
    if (author) author.textContent = `Author: ${String(turn?.author_text || "").trim() || "n/a"}`;
    if (assistant) assistant.textContent = `Assistant: ${String(turn?.assistant_text || "").trim() || "n/a"}`;
    refs.writerTurnFeedEl.appendChild(fragment);
  });
}

function renderPlayability() {
  const report = state.playability && typeof state.playability === "object" ? state.playability : null;
  const blocking = Array.isArray(report?.blocking_errors) ? report.blocking_errors : [];
  const metrics = report?.metrics && typeof report.metrics === "object" ? report.metrics : null;
  renderDiagnosticList(refs.playabilityBlockingEl, blocking, "No blocking playability issues.");
  renderDiagnosticList(refs.playabilityBlockingMainEl, blocking, "No blocking playability issues.");
  refs.playabilityMetricsEl.textContent = metrics
    ? JSON.stringify(metrics, null, 2)
    : "No playability metrics yet.";

  const asPct = (raw) => {
    if (typeof raw !== "number" || Number.isNaN(raw)) return "n/a";
    return `${Math.round(raw * 100)}%`;
  };
  const conflictSignal = (() => {
    if (!metrics) return "n/a";
    const contrast = Number(metrics.choice_contrast_score || 0);
    const tension = Number(metrics.tension_loop_score || 0);
    return asPct((contrast + tension) / 2);
  })();
  const branchSignal = metrics ? asPct(Number(metrics.choice_contrast_score || 0)) : "n/a";
  const recoverySignal = metrics ? asPct(Number(metrics.recovery_window_rate || 0)) : "n/a";
  const deadlineSignal = metrics ? asPct(Number(metrics.tension_loop_score || 0)) : "n/a";

  refs.funConflictEl.textContent = conflictSignal;
  refs.funBranchEl.textContent = branchSignal;
  refs.funRecoveryEl.textContent = recoverySignal;
  refs.funDeadlineEl.textContent = deadlineSignal;
}

function renderAll() {
  renderTabUi();
  renderPageUi();
  renderStepper();
  renderWorldFields();
  renderCharactersFields();
  renderPlotFields();
  renderActs();
  renderScenes();
  renderActionFields();
  renderConsequenceFields();
  renderEndingFields();
  renderLayerIntentPanel();
  renderAssistPanel();
  renderStoryOverview();
  renderWriterTurns();
  renderPlayability();
  renderNextSteps();
}

function readFormIntoState() {
  state.story.format_version = 4;
  state.story.entry_mode = state.entryMode;
  state.story.source_text = state.entryMode === "ingest" ? String(refs.sourceInputEl.value || "").trim() || null : null;

  state.story.meta.story_id = String(refs.storyIdEl.value || "").trim();
  state.story.meta.version = Number(refs.versionEl.value || 1);
  state.story.meta.title = String(refs.titleEl.value || "").trim();
  state.story.meta.summary = String(refs.summaryEl.value || "").trim() || null;
  state.story.meta.locale = String(refs.localeEl.value || "en").trim() || "en";

  state.story.world.era = String(refs.worldEraEl.value || "").trim();
  state.story.world.location = String(refs.worldLocationEl.value || "").trim();
  state.story.world.boundaries = String(refs.worldBoundariesEl.value || "").trim();
  state.story.world.social_rules = String(refs.worldSocialRulesEl.value || "").trim() || null;
  state.story.world.intent_module.author_input = String(refs.globalBriefEl.value || "").trim();

  state.story.characters.protagonist.name = String(refs.protagonistNameEl.value || "").trim();
  state.story.characters.protagonist.role = String(refs.protagonistRoleEl.value || "").trim() || null;
  state.story.characters.protagonist.traits = parseCsv(refs.protagonistTraitsEl.value);

  state.story.plot.mainline_goal = String(refs.mainlineGoalEl.value || "").trim() || null;
  state.story.plot.sideline_threads = parseLines(refs.sidelineThreadsEl.value);

  state.story.action.input_mapping_policy = String(refs.actionMappingPolicyEl.value || "").trim() || "intent_alias_only_visible_choice";

  state.story.consequence.state_axes = parseCsv(refs.consequenceStateAxesEl.value);

  state.story.systems.fallback_style = {
    tone: String(refs.fallbackToneEl.value || "supportive"),
    action_type: String(refs.fallbackActionTypeEl.value || "rest"),
  };

  if (!Array.isArray(state.story.writer_journal)) {
    state.story.writer_journal = [];
  }
  if (!state.story.playability_policy || typeof state.story.playability_policy !== "object") {
    state.story.playability_policy = {
      ending_reach_rate_min: 0.6,
      stuck_turn_rate_max: 0.05,
      no_progress_rate_max: 0.25,
      branch_coverage_warn_below: 0.3,
      choice_contrast_warn_below: 0.45,
      dominant_strategy_warn_above: 0.75,
      recovery_window_warn_below: 0.55,
      tension_loop_warn_below: 0.5,
      dominant_strategy_block_above: 0.9,
      low_branch_with_dominant_block_below: 0.2,
      recovery_window_block_below: 0.25,
      rollout_strategies: 3,
      rollout_runs_per_strategy: 80,
    };
  }
}

function readJsonFieldsIntoState() {
  state.story.characters.npcs = parseNpcsNarrative(refs.npcsNarrativeEl.value);
  state.story.characters.relationship_axes = parseAxesNarrative(refs.axesNarrativeEl.value);
  state.story.action.action_catalog = parseActionCatalogNarrative(refs.actionCatalogNarrativeEl.value);
  refs.npcsJsonEl.value = JSON.stringify(state.story.characters.npcs || [], null, 2);
  refs.axesJsonEl.value = JSON.stringify(state.story.characters.relationship_axes || {}, null, 2);
  refs.actionCatalogJsonEl.value = JSON.stringify(state.story.action.action_catalog || [], null, 2);
  state.story.consequence.quest_progression_rules = parseJsonArray(refs.questsJsonEl.value, [], "Quest progression rules");
  state.story.consequence.event_rules = parseJsonArray(refs.eventsJsonEl.value, [], "Event rules");
  state.story.ending.ending_rules = parseJsonArray(refs.endingsJsonEl.value, [], "Ending rules");
}

function buildPayload() {
  readFormIntoState();
  readJsonFieldsIntoState();
  if (!state.story.flow.start_scene_key && state.story.flow.scenes.length > 0) {
    state.story.flow.start_scene_key = state.story.flow.scenes[0].scene_key || null;
  }
  return cloneJson(state.story);
}

function applyValidateResult(response) {
  const errors = Array.isArray(response?.errors) ? response.errors : [];
  const warnings = Array.isArray(response?.warnings) ? response.warnings : [];
  state.playability = response?.playability && typeof response.playability === "object" ? response.playability : null;
  state.diagnostics.errors = errors;
  state.diagnostics.warnings = warnings;
  state.nextSteps = computeNextSteps({ errors, warnings, playability: state.playability });
  renderDiagnosticList(refs.errorsListEl, errors, "No validation errors.");
  renderDiagnosticList(refs.warningsListEl, warnings, "No warnings.");
  renderPlayability();
  if (response?.compiled_preview) {
    refs.previewEl.textContent = JSON.stringify(response.compiled_preview, null, 2);
    state.compiledPack = response.compiled_preview;
  } else if (!errors.length) {
    refs.previewEl.textContent = "No compile preview returned.";
  }

  if (errors.length) {
    setStatus(`Validation failed with ${errors.length} error(s).`, "error");
  } else if (warnings.length) {
    setStatus(`Validation passed with ${warnings.length} warning(s).`, "warn");
  } else {
    setStatus("Validation passed.", "ok");
  }
}

function applyCompileResult(pack, diagnostics) {
  const errors = Array.isArray(diagnostics?.errors) ? diagnostics.errors : [];
  const warnings = Array.isArray(diagnostics?.warnings) ? diagnostics.warnings : [];
  const mappings = diagnostics?.mappings || {};
  state.diagnostics.errors = errors;
  state.diagnostics.warnings = warnings;
  state.nextSteps = computeNextSteps({ errors, warnings, playability: state.playability });
  renderDiagnosticList(refs.errorsListEl, errors, "No compile errors.");
  renderDiagnosticList(refs.warningsListEl, warnings, "No warnings.");
  refs.mappingsEl.textContent = JSON.stringify(mappings, null, 2) || "No mappings.";
  if (pack) {
    refs.previewEl.textContent = JSON.stringify(pack, null, 2);
    state.compiledPack = pack;
  }
  if (errors.length) {
    setStatus(`Compile failed with ${errors.length} error(s).`, "error");
  } else if (warnings.length) {
    setStatus(`Compile succeeded with ${warnings.length} warning(s).`, "warn");
  } else {
    setStatus("Compile succeeded.", "ok");
  }
}

async function validateAuthorPayload() {
  let payload;
  try {
    payload = buildPayload();
  } catch (error) {
    setStatus(error.message || "Invalid narrative template or line format.", "error");
    throw error;
  }

  const response = await Shared.requestJson("POST", "/stories/validate-author", payload);
  if (!response.ok) {
    const detail = response.data?.detail || response.data || {};
    const code = detail.code || "VALIDATE_FAILED";
    const message = detail.message || Shared.detailMessage?.(detail) || JSON.stringify(detail);
    setStatus(`${code}: ${message}`, "error");
    throw new Error(message);
  }
  applyValidateResult(response.data);
  return response.data;
}

async function compileAuthorPayload() {
  let payload;
  try {
    payload = buildPayload();
  } catch (error) {
    setStatus(error.message || "Invalid narrative template or line format.", "error");
    throw error;
  }

  const response = await Shared.requestJson("POST", "/stories/compile-author", payload);
  if (response.ok) {
    applyCompileResult(response.data.pack, response.data.diagnostics || {});
    return response.data.pack;
  }
  const detail = response.data?.detail || response.data || {};
  applyCompileResult(null, {
    errors: Array.isArray(detail.errors) ? detail.errors : [],
    warnings: Array.isArray(detail.warnings) ? detail.warnings : [],
    mappings: {},
  });
  throw new Error(detail.message || detail.code || "compile failed");
}

async function ensureCompiledPack() {
  if (state.compiledPack) return state.compiledPack;
  return compileAuthorPayload();
}

async function saveDraft() {
  const compiled = await ensureCompiledPack();
  if (!compiled) {
    setStatus("Save aborted because compile failed.", "error");
    return null;
  }
  try {
    const out = await Shared.callApi("POST", "/stories", compiled);
    setStatus(`Draft saved: ${out.story_id}@${out.version}.`, "ok");
    return compiled;
  } catch (error) {
    if (error?.status === 409 && error?.code === "STORY_VERSION_EXISTS") {
      setStatus("This story version already exists; using existing draft.", "warn");
      return compiled;
    }
    setStatus(error?.message || "Save failed.", "error");
    throw error;
  }
}

async function createPlaytestSession() {
  const compiled = await saveDraft();
  if (!compiled) return;
  const out = await Shared.callApi("POST", "/sessions", {
    story_id: compiled.story_id,
    version: compiled.version,
  });
  window.localStorage.setItem("demo_play_session_id", String(out.id));
  setPlaytestInfo(`Playtest session created: ${out.id}`, "ok");
  window.location.href = `/demo/play?session_id=${encodeURIComponent(String(out.id))}`;
}

function normalizePatchPath(path) {
  let out = String(path || "");
  out = out.replaceAll("[current]", `[${state.selectedSceneIndex}]`);
  if (out.includes("options[current]")) {
    out = out.replace("options[current]", `options[${state.selectedOptionIndex}]`);
  }
  return out;
}

function parsePath(path) {
  if (patchHelpers.parsePath) return patchHelpers.parsePath(path);
  const tokens = [];
  const regex = /([^.[\]]+)|\[(\d+)\]/g;
  let match;
  while ((match = regex.exec(path)) !== null) {
    if (match[1] !== undefined) tokens.push(match[1]);
    if (match[2] !== undefined) tokens.push(Number(match[2]));
  }
  return tokens;
}

function setByPath(target, path, value) {
  if (patchHelpers.setByPath) {
    patchHelpers.setByPath(target, path, value);
    return;
  }
  const tokens = parsePath(path);
  if (!tokens.length) return;
  let current = target;
  for (let i = 0; i < tokens.length - 1; i += 1) {
    const key = tokens[i];
    const nextKey = tokens[i + 1];
    if (current[key] === undefined || current[key] === null) {
      current[key] = typeof nextKey === "number" ? [] : {};
    }
    current = current[key];
  }
  current[tokens[tokens.length - 1]] = cloneJson(value);
}

function hasWriterJournalPatch(patches) {
  return Array.isArray(patches) && patches.some((patch) => String(patch?.path || "").trim() === "writer_journal");
}

function shouldAutoApplyAssist(task, layer = null) {
  const taskName = String(task || "").trim();
  return AUTO_APPLY_ASSIST_TASKS.has(taskName);
}

function applyPatchBatch({ patches = [], selectedIds = null, sourceLabel = "assist", autoApplied = false } = {}) {
  const patchList = Array.isArray(patches) ? patches : [];
  const patchById = new Map(patchList.map((patch, idx) => [String(patch?.id || `patch_${idx}`), patch]));
  const candidateIds = Array.isArray(selectedIds) && selectedIds.length
    ? selectedIds.map((item) => String(item || "")).filter(Boolean)
    : Array.from(patchById.keys());

  const result = {
    sourceLabel: String(sourceLabel || "assist"),
    autoApplied: Boolean(autoApplied),
    appliedCount: 0,
    skippedCount: 0,
    failedPaths: [],
    appliedPatchIds: [],
  };
  if (!candidateIds.length) return result;

  const snapshot = cloneJson(state.story);
  let snapshotStored = false;

  candidateIds.forEach((id) => {
    const patch = patchById.get(id);
    if (!patch) {
      result.skippedCount += 1;
      result.failedPaths.push(`[missing:${id}]`);
      return;
    }

    const normalizedPath = normalizePatchPath(patch.path);
    if (!normalizedPath || !parsePath(normalizedPath).length) {
      result.skippedCount += 1;
      result.failedPaths.push(normalizedPath || `[empty:${id}]`);
      return;
    }

    try {
      if (!snapshotStored) {
        state.patchHistory.push(snapshot);
        snapshotStored = true;
      }
      setByPath(state.story, normalizedPath, patch.value);
      result.appliedCount += 1;
      result.appliedPatchIds.push(id);
    } catch (error) {
      result.skippedCount += 1;
      result.failedPaths.push(normalizedPath);
    }
  });

  if (result.appliedCount > 0) {
    state.compiledPack = null;
  }
  return result;
}

function recordAcceptedPatchIds(patchIds) {
  if (!Array.isArray(patchIds) || !patchIds.length) return;
  state.story.writer_journal = Array.isArray(state.story.writer_journal) ? state.story.writer_journal : [];
  if (!state.story.writer_journal.length) return;
  const lastTurn = state.story.writer_journal[state.story.writer_journal.length - 1];
  if (!lastTurn || typeof lastTurn !== "object") return;
  const previous = Array.isArray(lastTurn.accepted_patch_ids) ? lastTurn.accepted_patch_ids : [];
  const next = Array.from(new Set([...previous, ...patchIds.map((item) => String(item || "")).filter(Boolean)]));
  lastTurn.accepted_patch_ids = next;
}

function renderAssistResult(response) {
  state.assistSuggestions = response.suggestions || {};
  state.assistPatches = Array.isArray(response.patch_preview) ? response.patch_preview : [];
  state.assistWarnings = Array.isArray(response.warnings) ? response.warnings.map((item) => String(item || "")) : [];
  const warningText = Array.isArray(response.warnings) && response.warnings.length
    ? ` (${response.warnings.length} warning${response.warnings.length > 1 ? "s" : ""})`
    : "";
  setAssistStatus(`Suggestions ready from model ${response.model}${warningText}.`, "ok");
  renderAssistPanel();
  renderStoryOverview();
}

function appendWriterTurn(task, response, context) {
  const phaseByTask = {
    story_ingest: "structure",
    seed_expand: "expand",
    beat_to_scene: "structure",
    scene_deepen: "expand",
    option_weave: "structure",
    consequence_balance: "balance",
    ending_design: "ending",
    consistency_check: "balance",
    continue_write: "expand",
    trim_content: "structure",
    spice_branch: "structure",
    tension_rebalance: "balance",
  };
  const phase = phaseByTask[task] || "expand";
  const authorText = String(context?.source_text_mode ? context?.source_text : (context?.seed_text || context?.global_brief) || "").trim();
  const warningCount = Array.isArray(response?.warnings) ? response.warnings.length : 0;
  const summaryByTask = {
    seed_expand: "Expanded seed into a pressure -> escalation -> recovery -> decision loop.",
    story_ingest: "Projected imported story into a playable layered RPG draft.",
    continue_write: "Appended a follow-up beat so consequences continue after the latest decision.",
    trim_content: "Trimmed requested content and repaired references to keep flow reachable.",
    spice_branch: "Increased branch contrast between pressure and recovery choices.",
    tension_rebalance: "Rebalanced option costs/recovery windows while preserving branch differences.",
  };
  const riskHintByTask = {
    seed_expand: "Risk check: verify at least one high-risk option and one recovery path per two scenes.",
    continue_write: "Risk check: confirm newly appended scene is connected from current decision gate.",
    trim_content: "Risk check: validate no dangling go_to references remain after trimming.",
    spice_branch: "Risk check: avoid branches collapsing into the same action/effect profile.",
    tension_rebalance: "Risk check: avoid flattening all branches into low-stakes options.",
  };
  const assistantSummary = summaryByTask[task] || "Applied structured assist updates to your draft.";
  const riskHint = riskHintByTask[task] || "Risk check: run Validate to confirm structure and playability.";
  const warningHint = warningCount > 0 ? ` (${warningCount} warning${warningCount > 1 ? "s" : ""})` : "";
  const assistantText = `${assistantSummary} ${riskHint}${warningHint}`;
  const turn = {
    turn_id: `turn_${Date.now()}`,
    phase,
    author_text: authorText || "Draft iteration.",
    assistant_text: assistantText,
    accepted_patch_ids: [],
    created_at: null,
  };
  state.story.writer_journal = Array.isArray(state.story.writer_journal) ? state.story.writer_journal : [];
  state.story.writer_journal.push(turn);
  if (state.story.writer_journal.length > 30) {
    state.story.writer_journal = state.story.writer_journal.slice(-30);
  }
}

function currentAssistContext(
  layer = null,
  {
    operation = "append",
    targetScope = "global",
    targetSceneKey = null,
    targetOptionKey = null,
    preserveExisting = true,
  } = {},
) {
  const scene = state.story.flow.scenes[state.selectedSceneIndex] || state.story.flow.scenes[0] || null;
  const option = scene?.options?.[state.selectedOptionIndex] || scene?.options?.[0] || null;
  const resolvedTargetSceneKey = targetSceneKey || scene?.scene_key || null;
  const resolvedTargetOptionKey = targetOptionKey || option?.option_key || null;
  const layerKey = typeof layer === "string" ? layer : "";
  const consequenceIntent = String(refs.consequenceRefineIntentEl?.value || "").trim();
  const endingIntent = String(refs.endingRefineIntentEl?.value || "").trim();
  let authorInputValue = layer && state.story[layer]?.intent_module?.author_input
    ? state.story[layer].intent_module.author_input
    : refs.globalBriefEl.value;
  if (layerKey === "consequence" && consequenceIntent) {
    authorInputValue = consequenceIntent;
  } else if (layerKey === "ending" && endingIntent) {
    authorInputValue = endingIntent;
  }
  return {
    format_version: 4,
    layer,
    entry_mode: state.entryMode,
    operation,
    target_scope: targetScope,
    target_scene_key: resolvedTargetSceneKey,
    target_option_key: resolvedTargetOptionKey,
    preserve_existing: Boolean(preserveExisting),
    seed_text: refs.seedInputEl.value,
    source_text: refs.sourceInputEl.value,
    source_text_mode: state.entryMode === "ingest",
    continue_input: refs.continueInputEl.value,
    global_brief: refs.globalBriefEl.value,
    story_id: state.story.meta.story_id,
    locale: state.story.meta.locale,
    title: state.story.meta.title,
    premise: `${state.story.world.era} ${state.story.world.location}. ${state.story.world.boundaries}`,
    mainline_goal: state.story.plot.mainline_goal,
    scene_key: resolvedTargetSceneKey,
    scene_title: scene?.title || null,
    scene_setup: scene?.setup || null,
    next_scene_key: state.story.flow.scenes[state.selectedSceneIndex + 1]?.scene_key || scene?.scene_key || null,
    option_label: option?.label || null,
    action_type: option?.action_type || null,
    author_input: authorInputValue,
    writer_journal: cloneJson(state.story.writer_journal || []),
    draft: cloneJson(state.story),
  };
}

async function askAssist(
  task,
  {
    layer = null,
    operation = "append",
    targetScope = "global",
    targetSceneKey = null,
    targetOptionKey = null,
    preserveExisting = true,
    requestSignal = null,
    onStage = null,
  } = {},
) {
  readFormIntoState();
  readJsonFieldsIntoState();
  setAssistRetryHint("", false);
  const ctx = currentAssistContext(layer, {
    operation,
    targetScope,
    targetSceneKey,
    targetOptionKey,
    preserveExisting,
  });

  const response = await Shared.callApiStream("POST", "/stories/author-assist/stream", {
    task,
    locale: state.story.meta.locale || "en",
    context: ctx,
  }, {
    signal: requestSignal || undefined,
    onStage: typeof onStage === "function" ? onStage : undefined,
  });
  const patches = Array.isArray(response.patch_preview) ? response.patch_preview : [];
  const includesWriterJournalPatch = hasWriterJournalPatch(patches);
  if (!includesWriterJournalPatch) {
    appendWriterTurn(task, response, ctx);
  }
  renderAssistResult(response);

  if (shouldAutoApplyAssist(task, layer)) {
    const applyResult = applyPatchBatch({
      patches,
      sourceLabel: `assist:${String(task || "")}`,
      autoApplied: true,
    });
    recordAcceptedPatchIds(applyResult.appliedPatchIds);
    if (applyResult.appliedCount > 0 && applyResult.skippedCount === 0) {
      const message = `Auto-applied ${applyResult.appliedCount} change(s). Undo is available.`;
      setAssistStatus(message, "ok-auto");
      setStatus(message, "ok-auto");
      state.nextSteps = [
        "Review Story Overview to confirm goal, conflict, and branch clarity.",
        "Run Validate ASF v4 to check structure and playability.",
        "Open Shape page if you want finer action/effect tuning.",
      ];
    } else if (applyResult.appliedCount > 0) {
      const message = `Applied ${applyResult.appliedCount}, skipped ${applyResult.skippedCount}. See Debug for details.`;
      setAssistStatus(
        message,
        "warn-partial",
      );
      setStatus(message, "warn-partial");
      state.nextSteps = [
        "Open Debug tab to inspect skipped patch paths.",
        "Fix problematic fields in Shape page and run Parse again.",
        "Run Validate ASF v4 after adjustments.",
      ];
    } else {
      setAssistStatus("No patch changes to apply.", "warn");
      setStatus("No patch changes to apply.", "warn");
      state.nextSteps = [
        "Try a more specific seed or brief for stronger generation.",
        "Use Shape page to add at least one concrete scene update.",
      ];
    }
    renderAll();
    return;
  }

  setStatus("Suggestions are ready in Debug.", "ok");
  state.nextSteps = [
    "Open Debug tab to review suggestions and patch preview.",
    "Use Undo if you want to revert previous automatic changes.",
  ];
  if (!includesWriterJournalPatch) {
    renderWriterTurns();
  }
  setAssistRetryHint("", false);
}

function resolveAssistOption(value, fallback = null) {
  if (typeof value === "function") return value();
  if (value === undefined) return fallback;
  return value;
}

function bindAssistAction(
  button,
  task,
  {
    layer = null,
    operation = "append",
    targetScope = "global",
    targetSceneKey = null,
    targetOptionKey = null,
    preserveExisting = true,
  } = {},
) {
  const resolveTask = typeof task === "function" ? task : () => task;
  runAsyncWithSignal(
    button,
    async () => {
      state.assistInFlight = true;
      setAssistButtonsDisabled(true);
      _applyAssistStageState("", button);
      const resolvedTask = resolveTask();
      const controller = createAssistAbortController(resolvedTask);
      try {
        return await askAssist(resolvedTask, {
          layer: resolveAssistOption(layer, null),
          operation: resolveAssistOption(operation, "append"),
          targetScope: resolveAssistOption(targetScope, "global"),
          targetSceneKey: resolveAssistOption(targetSceneKey, null),
          targetOptionKey: resolveAssistOption(targetOptionKey, null),
          preserveExisting: Boolean(resolveAssistOption(preserveExisting, true)),
          requestSignal: controller?.signal || null,
          onStage: (stagePayload) => {
            const stageCode = String(stagePayload?.stage_code || "").trim();
            if (stageCode === "author.expand.start") {
              state.overviewFromExpandRows = [];
              state.overviewFromExpandSource = "";
              state.overviewFromExpandAt = 0;
              state.overviewFromExpandPending = true;
              renderStoryOverview();
            }
            const stageOverviewRows = _normalizeOverviewRows(stagePayload?.overview_rows);
            if (stageOverviewRows.length) {
              _setExpandOverviewRows(stageOverviewRows, stagePayload?.overview_source || "");
              renderStoryOverview();
            }
            const label = String(stagePayload?.label || "").trim();
            if (!label) return;
            const stageState = _assistStageStateFromCode(stageCode);
            _applyAssistStageState(stageState, button);
            button.textContent = label;
            setAssistFeedback(label, "waiting");
            setAssistStatus(label, "");
          },
        });
      } finally {
        clearAssistAbortState();
      }
    },
    {
      phase2DelayMs: 650,
      successHoldMs: 1200,
      sendingLabel: "Signal sent...",
      waitingLabel: "Model responding...",
      successLabel: "Response received.",
      errorLabel: "Request failed.",
      onStatusChange: (status, meta) => {
        if (status === "sending" || status === "waiting") {
          if (status === "sending" && !state.assistStageState) {
            _applyAssistStageState("requesting", button);
          }
          setAssistFeedback(meta?.label || "", status);
          return;
        }
        if (status === "success" || status === "error") {
          _applyAssistStageState("", button);
          state.assistInFlight = false;
          clearAssistAbortState();
          setAssistButtonsDisabled(false, { except: meta?.button || null });
          setAssistFeedback(meta?.label || "", status);
          return;
        }
        if (status === "idle") {
          _applyAssistStageState("", button);
          state.assistInFlight = false;
          clearAssistAbortState();
          setAssistButtonsDisabled(false);
          setAssistFeedback("", "idle");
        }
      },
      onError: (error) => {
        _applyAssistStageState("", button);
        if (String(error?.code || "") === "REQUEST_ABORTED") {
          setAssistStatus("Request canceled.", "warn");
          setStatus("Request canceled.", "warn");
          setAssistRetryHint("", false);
          state.nextSteps = [
            "You can retry Parse or Continue Write immediately.",
            "Use Shape page if you want manual fine-tuning before retrying.",
          ];
          renderNextSteps();
          return true;
        }
        const detail = (
          error?.payload
          && typeof error.payload === "object"
          && error.payload.detail
          && typeof error.payload.detail === "object"
        ) ? error.payload.detail : {};
        const detailCode = String(detail?.code || error?.code || "").trim();
        const isRetryable = Boolean(detail?.retryable || error?.status === 503);
        const fallbackHint = detailCode === "ASSIST_INVALID_OUTPUT"
          ? "Model output invalid. Please retry."
          : "Model unavailable. Please retry.";
        const hint = String(detail?.hint || fallbackHint).trim();
        if (detailCode === "ASSIST_INVALID_OUTPUT") {
          setAssistStatus("Model output invalid. Please retry.", "warn");
          setStatus("Model output invalid. Please retry.", "warn");
          setAssistRetryHint(hint, true);
          state.nextSteps = [
            "Retry the same assist action to request a valid structured response.",
            "Simplify seed/brief text if the prompt context is too broad.",
            "Open Debug tab to inspect ASSIST_INVALID_OUTPUT details.",
          ];
          renderNextSteps();
          return false;
        }
        setAssistStatus(error?.message || "Assist failed.", "error");
        if (isRetryable || detailCode === "ASSIST_LLM_UNAVAILABLE") {
          setStatus("Model unavailable. Please retry.", "warn");
          setAssistRetryHint(hint, true);
          state.nextSteps = [
            "Retry the same assist action once model connectivity is back.",
            "Open Debug tab to inspect the exact assist error code and hint.",
            "If this persists, verify model/API settings in .env.",
          ];
          renderNextSteps();
        }
        return false;
      },
    },
  );
}

function applySelectedPatches() {
  if (!Array.isArray(state.assistPatches) || state.assistPatches.length === 0) {
    setAssistStatus("No patch candidates to apply.", "warn");
    return;
  }

  const selectedIds = Array.from(refs.assistPatchPreviewEl.querySelectorAll("input[data-patch-id]:checked"))
    .map((node) => String(node.dataset.patchId || ""));
  if (!selectedIds.length) {
    setAssistStatus("Select at least one patch row to apply.", "warn");
    return;
  }

  const applyResult = applyPatchBatch({
    patches: state.assistPatches,
    selectedIds,
    sourceLabel: "manual_patch_apply",
    autoApplied: false,
  });
  recordAcceptedPatchIds(applyResult.appliedPatchIds);

  if (applyResult.appliedCount > 0 && applyResult.skippedCount === 0) {
    setAssistStatus(`Applied ${applyResult.appliedCount} patch item(s).`, "ok");
    setStatus(`Applied ${applyResult.appliedCount} patch item(s).`, "ok");
    renderAll();
    return;
  }
  if (applyResult.appliedCount > 0) {
    setAssistStatus(
      `Applied ${applyResult.appliedCount}, skipped ${applyResult.skippedCount}. See Debug for details.`,
      "warn-partial",
    );
    setStatus(
      `Applied ${applyResult.appliedCount}, skipped ${applyResult.skippedCount}. See Debug for details.`,
      "warn-partial",
    );
    renderAll();
    return;
  }
  setAssistStatus("No patch changes to apply.", "warn");
  setStatus("No patch changes to apply.", "warn");
}

function undoPatchApply() {
  const previous = state.patchHistory.pop();
  if (!previous) {
    setAssistStatus("No patch history to undo.", "warn");
    setStatus("No patch history to undo.", "warn");
    return;
  }
  state.story = previous;
  state.compiledPack = null;
  setAssistStatus("Restored previous draft state.", "ok");
  setStatus("Restored previous draft state.", "ok");
  state.nextSteps = [
    "Review Story Overview and decide whether another generation pass is needed.",
    "Run Validate ASF v4 when the draft feels stable.",
  ];
  renderAll();
}

function onActInput(event) {
  const card = event.target.closest(".act-card");
  if (!card) return;
  const actIndex = Number(card.dataset.actIndex);
  if (!Number.isInteger(actIndex) || !state.story.plot.mainline_acts[actIndex]) return;
  const field = event.target.dataset.actField;
  if (!field) return;

  if (field === "scene_keys") {
    state.story.plot.mainline_acts[actIndex].scene_keys = parseCsv(event.target.value);
  } else {
    state.story.plot.mainline_acts[actIndex][field] = event.target.value;
  }
  state.compiledPack = null;
}

function onActActions(event) {
  const action = event.target.dataset.action;
  if (!action) return;
  const card = event.target.closest(".act-card");
  const actIndex = Number(card?.dataset.actIndex);
  if (!Number.isInteger(actIndex)) return;
  if (action === "remove-act") {
    state.story.plot.mainline_acts.splice(actIndex, 1);
    if (state.story.plot.mainline_acts.length === 0) {
      state.story.plot.mainline_acts.push(actDefaults(1));
    }
    state.compiledPack = null;
    renderActs();
  }
}

function onSceneInput(event) {
  const target = event.target;
  const card = target.closest(".scene-card");
  if (!card) return;
  const sceneIndex = Number(card.dataset.sceneIndex);
  if (!Number.isInteger(sceneIndex) || !state.story.flow.scenes[sceneIndex]) return;

  const scene = state.story.flow.scenes[sceneIndex];
  const sceneField = target.dataset.sceneField;
  if (sceneField) {
    if (sceneField === "is_end") {
      scene.is_end = Boolean(target.checked);
    } else if (sceneField === "free_input_hints") {
      scene.free_input_hints = parseCsv(target.value);
    } else {
      scene[sceneField] = target.value;
    }
    state.compiledPack = null;
    return;
  }

  const optionContainer = target.closest(".scene-option");
  if (!optionContainer) return;
  const optionIndex = Number(optionContainer.dataset.optionIndex);
  if (!Number.isInteger(optionIndex) || !scene.options[optionIndex]) return;
  const option = scene.options[optionIndex];
  const optionField = target.dataset.optionField;
  if (!optionField) return;

  if (optionField === "is_key_decision") {
    option.is_key_decision = Boolean(target.checked);
  } else if (optionField === "intent_aliases") {
    option.intent_aliases = parseCsv(target.value);
  } else if (optionField.startsWith("effects.")) {
    const key = optionField.split(".", 2)[1];
    option.effects = option.effects || {};
    const value = String(target.value || "").trim();
    if (!value) delete option.effects[key];
    else option.effects[key] = Number(value);
  } else if (optionField.startsWith("requirements.")) {
    const key = optionField.split(".", 2)[1];
    option.requirements = option.requirements || {};
    const value = String(target.value || "").trim();
    if (!value) delete option.requirements[key];
    else option.requirements[key] = Number(value);
  } else {
    option[optionField] = target.value;
  }
  state.compiledPack = null;
}

function onSceneActions(event) {
  const target = event.target;
  const action = target.dataset.action;
  if (!action) return;
  const card = target.closest(".scene-card");
  const sceneIndex = Number(card?.dataset.sceneIndex);
  if (!Number.isInteger(sceneIndex) || !state.story.flow.scenes[sceneIndex]) return;

  if (action === "select-scene") {
    state.selectedSceneIndex = sceneIndex;
    state.selectedOptionIndex = 0;
    renderScenes();
    return;
  }

  if (action === "remove-scene") {
    state.story.flow.scenes.splice(sceneIndex, 1);
    if (state.story.flow.scenes.length === 0) state.story.flow.scenes.push(sceneDefaults(0));
    state.selectedSceneIndex = Math.max(0, Math.min(state.selectedSceneIndex, state.story.flow.scenes.length - 1));
    state.selectedOptionIndex = 0;
    renderScenes();
  } else if (action === "add-option") {
    const next = (state.story.flow.scenes[sceneIndex].options || []).length + 1;
    state.story.flow.scenes[sceneIndex].options.push(optionDefaults("rest", next));
    renderScenes();
  } else if (action === "remove-option") {
    const optionIndex = Number(target.dataset.optionIndex);
    if (Number.isInteger(optionIndex) && state.story.flow.scenes[sceneIndex].options[optionIndex]) {
      state.story.flow.scenes[sceneIndex].options.splice(optionIndex, 1);
      if (state.story.flow.scenes[sceneIndex].options.length === 0) {
        state.story.flow.scenes[sceneIndex].options.push(optionDefaults("rest", 1));
      }
      state.selectedSceneIndex = sceneIndex;
      state.selectedOptionIndex = Math.max(0, Math.min(state.selectedOptionIndex, state.story.flow.scenes[sceneIndex].options.length - 1));
      renderScenes();
    }
  } else if (action === "select-option") {
    const optionIndex = Number(target.dataset.optionIndex);
    if (Number.isInteger(optionIndex) && state.story.flow.scenes[sceneIndex].options[optionIndex]) {
      state.selectedSceneIndex = sceneIndex;
      state.selectedOptionIndex = optionIndex;
      renderScenes();
    }
  }
  state.compiledPack = null;
}

function loadQuickTemplate() {
  state.story = storyDefaults();
  state.entryMode = "spark";
  state.playability = null;
  state.nextSteps = [
    "Write a seed and click Parse All Layers to auto-generate your first draft.",
    "Open Shape page only when you need fine-grained scene tuning.",
  ];
  state.selectedSceneIndex = 0;
  state.selectedOptionIndex = 0;
  state.compiledPack = null;
  setStatus("Template loaded. Continue with layered steps.", "ok");
  setAssistStatus("Template loaded. Use Parse/Refine to iterate.", "");
  renderAll();
}

function attachEvents() {
  refs.tabAuthorBtnEl.addEventListener("click", () => {
    state.ui.active_tab = "author";
    renderAll();
  });
  refs.tabDebugBtnEl.addEventListener("click", () => {
    if (!state.ui.show_debug) return;
    state.ui.active_tab = "debug";
    renderAll();
  });
  refs.debugToggleEl.addEventListener("change", () => {
    state.ui.show_debug = Boolean(refs.debugToggleEl.checked);
    if (!state.ui.show_debug) state.ui.active_tab = "author";
    persistShowDebugPreference(state.ui.show_debug);
    renderAll();
  });

  refs.pageComposeBtnEl.addEventListener("click", () => {
    state.ui.active_page = "compose";
    renderPageUi();
  });
  refs.pageShapeBtnEl.addEventListener("click", () => {
    state.ui.active_page = "shape";
    renderPageUi();
  });
  refs.pageBuildBtnEl.addEventListener("click", () => {
    state.ui.active_page = "build";
    renderPageUi();
  });

  refs.structureCollapseEl.addEventListener("toggle", () => {
    state.ui.panels.structure_open = refs.structureCollapseEl.open;
  });
  refs.reviewAdvancedToggleEl.addEventListener("toggle", () => {
    state.ui.panels.review_advanced_open = refs.reviewAdvancedToggleEl.open;
  });

  refs.stepperEl.addEventListener("click", (event) => {
    const item = event.target.closest(".stepper__item");
    if (!item) return;
    const next = Number(item.dataset.stepIndex);
    if (!Number.isInteger(next)) return;
    state.stepIndex = Math.max(0, Math.min(7, next));
    renderStepper();
  });

  refs.prevStepBtnEl.addEventListener("click", () => {
    state.stepIndex = Math.max(0, state.stepIndex - 1);
    renderStepper();
  });

  refs.nextStepBtnEl.addEventListener("click", () => {
    state.stepIndex = Math.min(7, state.stepIndex + 1);
    renderStepper();
  });

  refs.addActBtnEl.addEventListener("click", () => {
    state.story.plot.mainline_acts.push(actDefaults(state.story.plot.mainline_acts.length + 1));
    state.compiledPack = null;
    renderActs();
  });
  refs.actsEl.addEventListener("input", onActInput);
  refs.actsEl.addEventListener("click", onActActions);

  refs.addSceneBtnEl.addEventListener("click", () => {
    state.story.flow.scenes.push(sceneDefaults(state.story.flow.scenes.length));
    state.selectedSceneIndex = state.story.flow.scenes.length - 1;
    state.selectedOptionIndex = 0;
    renderScenes();
    state.compiledPack = null;
  });
  refs.scenesEl.addEventListener("input", onSceneInput);
  refs.scenesEl.addEventListener("change", onSceneInput);
  refs.scenesEl.addEventListener("click", onSceneActions);

  refs.loadTemplateBtnEl.addEventListener("click", loadQuickTemplate);

  refs.validateBtnEl.addEventListener("click", () => {
    validateAuthorPayload().catch((error) => {
      setStatus(error?.message || "Validation request failed.", "error");
    });
  });

  refs.compileBtnEl.addEventListener("click", () => {
    compileAuthorPayload().catch((error) => {
      setStatus(error?.message || "Compile request failed.", "error");
    });
  });

  refs.saveDraftBtnEl.addEventListener("click", () => {
    saveDraft().catch((error) => {
      setStatus(error?.message || "Save failed.", "error");
    });
  });

  refs.playtestBtnEl.addEventListener("click", () => {
    createPlaytestSession().catch((error) => {
      setPlaytestInfo(error?.message || "Playtest session creation failed.", "error");
    });
  });

  refs.entrySparkBtnEl.addEventListener("click", () => {
    state.entryMode = "spark";
    state.story.entry_mode = "spark";
    renderWorldFields();
  });
  refs.entryIngestBtnEl.addEventListener("click", () => {
    state.entryMode = "ingest";
    state.story.entry_mode = "ingest";
    renderWorldFields();
  });

  refs.assistCancelBtnEl.addEventListener("click", () => {
    const controller = state.assistAbortController;
    if (!controller) return;
    refs.assistCancelBtnEl.disabled = true;
    try {
      controller.abort();
    } catch (error) {
      // Ignore abort races if request already settled.
    }
  });

  bindAssistAction(refs.assistBootstrapBtnEl, () => (state.entryMode === "ingest" ? "story_ingest" : "seed_expand"), {
    operation: "append",
    targetScope: "global",
    preserveExisting: true,
  });
  bindAssistAction(refs.assistRefineWorldBtnEl, "scene_deepen", { layer: "world", targetScope: "layer" });
  bindAssistAction(refs.assistRefineCharactersBtnEl, "scene_deepen", { layer: "characters", targetScope: "layer" });
  bindAssistAction(refs.assistRefinePlotBtnEl, "scene_deepen", { layer: "plot", targetScope: "layer" });
  bindAssistAction(refs.assistSceneOptionsBtnEl, "beat_to_scene", { targetScope: "scene" });
  bindAssistAction(refs.assistIntentAliasesBtnEl, "option_weave", { targetScope: "option" });
  bindAssistAction(refs.assistRefineSceneBtnEl, "scene_deepen", { layer: "flow", targetScope: "scene" });
  bindAssistAction(refs.assistRefineActionBtnEl, "option_weave", { layer: "action", targetScope: "option" });
  bindAssistAction(refs.assistRefineConsequenceBtnEl, "consequence_balance", { layer: "consequence", targetScope: "layer" });
  bindAssistAction(refs.assistRefineEndingBtnEl, "ending_design", { layer: "ending", targetScope: "layer" });
  bindAssistAction(refs.assistConsistencyBtnEl, "consistency_check", { operation: "rewrite", targetScope: "global" });

  bindAssistAction(refs.continueWriteBtnEl, "continue_write", {
    operation: "append",
    targetScope: () => (state.ui.active_page === "shape" ? "scene" : "global"),
    targetSceneKey: () => state.story.flow.scenes[state.selectedSceneIndex]?.scene_key || null,
    preserveExisting: true,
  });
  bindAssistAction(refs.trimContentBtnEl, "trim_content", {
    operation: "trim",
    targetScope: () => "scene",
    targetSceneKey: () => state.story.flow.scenes[state.selectedSceneIndex]?.scene_key || null,
    targetOptionKey: () => state.story.flow.scenes[state.selectedSceneIndex]?.options?.[state.selectedOptionIndex]?.option_key || null,
    preserveExisting: true,
  });
  bindAssistAction(refs.spiceBranchBtnEl, "spice_branch", {
    operation: "rewrite",
    targetScope: "scene",
    targetSceneKey: () => state.story.flow.scenes[state.selectedSceneIndex]?.scene_key || null,
    preserveExisting: true,
  });
  bindAssistAction(refs.tensionRebalanceBtnEl, "tension_rebalance", {
    operation: "rewrite",
    targetScope: "global",
    preserveExisting: true,
  });

  refs.applySelectedPatchBtnEl.addEventListener("click", applySelectedPatches);
  refs.undoPatchBtnEl.addEventListener("click", undoPatchApply);
}

function init() {
  state.story = storyDefaults();
  state.compiledPack = null;
  state.assistSuggestions = {};
  state.assistPatches = [];
  state.assistWarnings = [];
  state.patchHistory = [];
  state.assistInFlight = false;
  state.assistStageState = "";
  state.assistAbortController = null;
  state.assistCancelableTask = null;
  state.overviewFromExpandRows = [];
  state.overviewFromExpandSource = "";
  state.overviewFromExpandAt = 0;
  state.overviewFromExpandPending = false;
  state.entryMode = "spark";
  state.playability = null;
  state.diagnostics = {
    errors: [],
    warnings: [],
  };
  state.nextSteps = [
    "Write a seed and click Parse All Layers to auto-generate your draft.",
    "Use Undo Last Apply any time you want to revert the latest AI batch.",
    "Switch to Shape page only when you need structural fine-tuning.",
  ];
  state.ui = {
    ...(stateHelpers.initialUiState ? stateHelpers.initialUiState(readShowDebugPreference()) : {
      focus_mode: true,
      show_debug: readShowDebugPreference(),
      active_tab: "author",
      active_page: "compose",
      panels: {
        structure_open: false,
        review_advanced_open: false,
      },
    }),
  };
  setStatus("Ready. Choose Spark or Ingest, then iterate through layers and compile.", "");
  setAssistStatus("No suggestions yet.", "");
  setAssistFeedback("", "idle");
  _applyAssistStageState("");
  setAssistRetryHint("", false);
  setAssistCancelVisibility(false);
  refs.mappingsEl.textContent = "No mappings yet.";
  refs.previewEl.textContent = "Compile output will appear here.";
  refs.playabilityMetricsEl.textContent = "No playability metrics yet.";
  setPlaytestInfo("No playtest session yet.", "");
  renderDiagnosticList(refs.errorsListEl, [], "No validation errors yet.");
  renderDiagnosticList(refs.warningsListEl, [], "No warnings yet.");
  renderDiagnosticList(refs.playabilityBlockingEl, [], "No blocking playability issues.");
  renderDiagnosticList(refs.playabilityBlockingMainEl, [], "No blocking playability issues.");
  syncFocusPanelsFromState();
  renderAll();
  attachEvents();
}

return {
  init,
};
})();
