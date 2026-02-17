const state = {
  sessionId: null,
  steps: [],
  snapshots: [],
  totals: { tokensIn: 0, tokensOut: 0, totalCost: 0 },
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

function updateTokenTotals(cost) {
  const tokensIn = Number(cost.tokens_in || 0);
  const tokensOut = Number(cost.tokens_out || 0);
  const totalCost = Number(cost.total_cost || 0);
  state.totals.tokensIn += tokensIn;
  state.totals.tokensOut += tokensOut;
  state.totals.totalCost = Number((state.totals.totalCost + totalCost).toFixed(6));
  tokenTotalsEl.textContent = `in: ${state.totals.tokensIn}, out: ${state.totals.tokensOut}, cost: ${state.totals.totalCost}`;
}

function renderNarrative(narrativeText, choices) {
  narrativeTextEl.textContent = narrativeText || "(empty)";
  choiceButtonsEl.innerHTML = "";
  (choices || []).forEach((choice) => {
    const btn = document.createElement("button");
    btn.textContent = `${choice.text} (${choice.type})`;
    btn.onclick = () => sendStep({ choice_id: choice.id });
    choiceButtonsEl.appendChild(btn);
  });
}

function renderStepCard(step) {
  const card = document.createElement("div");
  card.className = "step-card";
  card.innerHTML = `
    <header>
      <span>${step.timestamp}</span>
      <span>node: ${step.node_id || "n/a"}</span>
    </header>
    <div class="meta">
      <div><strong>story_node_id</strong>: ${step.story_node_id || "n/a"}</div>
      <div><strong>provider</strong>: ${step.cost.provider || "none"}</div>
      <div><strong>tokens</strong>: ${step.cost.tokens_in || 0} in / ${step.cost.tokens_out || 0} out</div>
      <div><strong>total_cost</strong>: ${step.cost.total_cost ?? 0}</div>
      <div><strong>fallback_reasons</strong>: ${(step.fallback_reasons && step.fallback_reasons.length) ? step.fallback_reasons.join(", ") : "n/a"}</div>
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

function appendStep(raw) {
  const step = {
    timestamp: nowIso(),
    node_id: raw.node_id,
    story_node_id: raw.story_node_id,
    cost: raw.cost || { provider: "none", tokens_in: 0, tokens_out: 0, total_cost: 0 },
    fallback_reasons: raw.fallback_reasons || null,
    raw,
  };
  state.steps.push(step);
  renderStepCard(step);
  updateTokenTotals(step.cost);
}

async function createSession() {
  const storyId = el("storyId").value.trim();
  const versionRaw = el("storyVersion").value.trim();
  const body = storyId ? { story_id: storyId } : {};
  if (versionRaw) body.version = Number(versionRaw);
  const out = await callApi("POST", "/sessions", Object.keys(body).length ? body : undefined);
  setSessionId(out.id);
  state.steps = [];
  timelineEl.innerHTML = "";
  state.snapshots = [];
  updateSnapshotsDropdown();
  state.totals = { tokensIn: 0, tokensOut: 0, totalCost: 0 };
  tokenTotalsEl.textContent = "in: 0, out: 0, cost: 0";
}

async function refreshSession() {
  if (!state.sessionId) return;
  const out = await callApi("GET", `/sessions/${state.sessionId}`);
  narrativeTextEl.textContent = out.current_node ? out.current_node.narrative_text : "(no current node narrative)";
}

async function sendStep(payloadOverride) {
  if (!state.sessionId) return;
  const inputText = el("playerInput").value.trim();
  const useInputText = el("useInputText").checked;
  const payload = payloadOverride || {};
  if (!payload.choice_id && inputText) {
    if (useInputText) payload.input_text = inputText;
    else payload.player_input = inputText;
  }
  if (Object.keys(payload).length === 0) return;

  const out = await callApi("POST", `/sessions/${state.sessionId}/step`, payload);
  renderNarrative(out.narrative_text, out.choices);
  appendStep(out);
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

  replayHighlightsEl.innerHTML = `
    <div class="card__body">
      <strong>Story Path</strong>\n${storyPath || "(none)"}\n\n
      <strong>Key Decisions</strong>\n${keyDecisions || "(none)"}\n\n
      <strong>Fallback Summary</strong>\n${fallbackSummary}
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
