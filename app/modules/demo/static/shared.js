(() => {
  const STEP_IDEMPOTENCY_HEADER = "X-Idempotency-Key";

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function mustEl(id, root = document) {
    const node = root.getElementById(id);
    if (!node) {
      throw new Error(`missing required element: #${id}`);
    }
    return node;
  }

  function cloneJson(input) {
    return JSON.parse(JSON.stringify(input || {}));
  }

  function setElementMessage(targetEl, message, { hiddenClass = null } = {}) {
    const text = String(message || "").trim();
    targetEl.textContent = text;
    if (hiddenClass) {
      targetEl.classList.toggle(hiddenClass, !text);
    }
    return text;
  }

  function formatStoryPathLines(storyPath, limit = 6) {
    const rows = Array.isArray(storyPath) ? storyPath.slice(0, Math.max(0, Number(limit || 0))) : [];
    return rows.map((row) => `#${row.step}: ${row.node_id} -> ${row.choice_id}`);
  }

  function bindAsyncClick(button, handler, onError = null) {
    button.addEventListener("click", () => {
      Promise.resolve(handler()).catch((error) => {
        if (typeof onError === "function") {
          onError(error);
          return;
        }
        console.error(error); // eslint-disable-line no-console
      });
    });
  }

  function runAsyncWithSignal(button, task, options = {}) {
    if (!button || typeof button.addEventListener !== "function") {
      throw new Error("runAsyncWithSignal requires a button element.");
    }
    if (typeof task !== "function") {
      throw new Error("runAsyncWithSignal requires a task function.");
    }

    const phase2DelayMs = Math.max(0, Number(options.phase2DelayMs ?? 650));
    const successHoldMs = Math.max(0, Number(options.successHoldMs ?? 1200));
    const errorHoldMs = Math.max(0, Number(options.errorHoldMs ?? 900));
    const sendingLabel = String(options.sendingLabel || "Signal sent...");
    const waitingLabel = String(options.waitingLabel || "Model responding...");
    const successLabel = String(options.successLabel || "Response received.");
    const errorLabel = String(options.errorLabel || "Request failed.");
    const defaultLabel = String(options.defaultLabel || button.textContent || "Run");
    const onStatusChange = typeof options.onStatusChange === "function" ? options.onStatusChange : null;
    const onError = typeof options.onError === "function" ? options.onError : null;

    let waitingTimer = null;
    let settleTimer = null;
    let running = false;

    function _clearTimers() {
      if (waitingTimer) {
        window.clearTimeout(waitingTimer);
        waitingTimer = null;
      }
      if (settleTimer) {
        window.clearTimeout(settleTimer);
        settleTimer = null;
      }
    }

    function _emit(status, label) {
      if (!onStatusChange) return;
      onStatusChange(status, {
        label,
        button,
      });
    }

    function _applyStatus(status, label = "") {
      button.classList.remove("btn--loading-signal", "btn--loading-wait", "btn--success-ack");
      button.setAttribute("data-request-state", status);

      if (status === "idle") {
        button.textContent = defaultLabel;
        button.disabled = false;
        button.setAttribute("aria-busy", "false");
        _emit(status, defaultLabel);
        return;
      }

      button.textContent = String(label || "");
      button.disabled = true;

      if (status === "sending") {
        button.classList.add("btn--loading-signal");
        button.setAttribute("aria-busy", "true");
      } else if (status === "waiting") {
        button.classList.add("btn--loading-wait");
        button.setAttribute("aria-busy", "true");
      } else if (status === "success") {
        button.classList.add("btn--success-ack");
        button.setAttribute("aria-busy", "false");
      } else if (status === "error") {
        button.setAttribute("aria-busy", "false");
      }

      _emit(status, label);
    }

    button.addEventListener("click", () => {
      if (running) return;
      running = true;
      _clearTimers();
      _applyStatus("sending", sendingLabel);

      waitingTimer = window.setTimeout(() => {
        if (!running) return;
        _applyStatus("waiting", waitingLabel);
      }, phase2DelayMs);

      Promise.resolve()
        .then(() => task())
        .then(() => {
          running = false;
          _clearTimers();
          _applyStatus("success", successLabel);
          settleTimer = window.setTimeout(() => {
            _applyStatus("idle", defaultLabel);
          }, successHoldMs);
        })
        .catch((error) => {
          running = false;
          _clearTimers();
          _applyStatus("error", errorLabel);
          settleTimer = window.setTimeout(() => {
            _applyStatus("idle", defaultLabel);
          }, errorHoldMs);
          if (onError) {
            onError(error);
            return;
          }
          console.error(error); // eslint-disable-line no-console
        });
    });
  }

  function newIdempotencyKey() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `demo-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function detailCode(payload) {
    if (!payload || typeof payload !== "object") return null;
    const detail = payload.detail;
    if (detail && typeof detail === "object" && typeof detail.code === "string") {
      return detail.code;
    }
    return null;
  }

  function detailMessage(payload) {
    if (!payload) return "";
    if (typeof payload === "string") return payload;
    if (typeof payload !== "object") return String(payload);
    const detail = payload.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      if (typeof detail.message === "string") return detail.message;
      if (typeof detail.code === "string") return detail.code;
    }
    return JSON.stringify(payload);
  }

  async function requestJson(method, url, body, options = {}) {
    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const extraHeaders = options.headers || {};
    Object.keys(extraHeaders).forEach((key) => {
      headers[key] = extraHeaders[key];
    });

    let response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: null,
        errorType: "network",
        networkError: error,
      };
    }

    const text = await response.text();
    let parsed = {};
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    return {
      ok: response.ok,
      status: response.status,
      data: parsed,
      errorType: null,
      networkError: null,
    };
  }

  function createApiError(response, actionLabel = "request") {
    const status = Number(response.status || 0);
    const code = detailCode(response.data);
    const message = detailMessage(response.data) || "request failed";
    const error = new Error(`${actionLabel} failed (${status}): ${message}`);
    error.status = status;
    error.code = code;
    error.payload = response.data;
    error.response = response;
    return error;
  }

  async function callApi(method, url, body, options = {}) {
    const response = await requestJson(method, url, body, options);
    if (!response.ok) {
      throw createApiError(response, `${method} ${url}`);
    }
    return response.data;
  }

  async function listStories({ publishedOnly = true, playableOnly = true } = {}) {
    const params = new URLSearchParams();
    params.set("published_only", String(Boolean(publishedOnly)));
    params.set("playable_only", String(Boolean(playableOnly)));
    return callApi("GET", `/stories?${params.toString()}`);
  }

  function _payloadKey(payload) {
    return JSON.stringify(payload || {});
  }

  function createStepRetryController({ maxAttempts = 3, backoffMs = 350, onStatus } = {}) {
    const limit = Math.max(1, Number(maxAttempts || 1));
    const backoff = Math.max(1, Number(backoffMs || 1));
    const emit = typeof onStatus === "function" ? onStatus : () => {};
    let pending = null;

    function _clonePending() {
      return pending ? JSON.parse(JSON.stringify(pending)) : null;
    }

    function _notify() {
      emit(_clonePending(), { maxAttempts: limit, backoffMs: backoff });
    }

    function clearPending() {
      pending = null;
      _notify();
    }

    function getPending() {
      return _clonePending();
    }

    async function _runPending() {
      if (!pending) {
        throw new Error("No pending step to execute.");
      }

      while (pending.attempts < limit) {
        pending.attempts += 1;
        _notify();

        const response = await requestJson(
          "POST",
          `/sessions/${pending.sessionId}/step`,
          pending.payload,
          {
            headers: { [STEP_IDEMPOTENCY_HEADER]: pending.idempotencyKey },
          },
        );

        if (response.errorType === "network") {
          pending.lastStatus = 0;
          pending.lastErrorCode = "NETWORK_ERROR";
          pending.lastErrorMessage = String(response.networkError || "network error");
          pending.uncertain = false;
          _notify();
          if (pending.attempts < limit) {
            await sleep(backoff * pending.attempts);
            continue;
          }
          pending.uncertain = true;
          _notify();
          return {
            ok: false,
            retryable: true,
            reason: "NETWORK_ERROR",
            pending: _clonePending(),
          };
        }

        if (response.ok) {
          const result = {
            ok: true,
            data: response.data,
            meta: {
              idempotencyKey: pending.idempotencyKey,
              attempts: pending.attempts,
            },
          };
          clearPending();
          return result;
        }

        const code = detailCode(response.data);
        pending.lastStatus = Number(response.status || 0);
        pending.lastErrorCode = code;
        pending.lastErrorMessage = detailMessage(response.data);
        pending.uncertain = false;
        _notify();

        if (pending.lastStatus === 409 && code === "REQUEST_IN_PROGRESS") {
          if (pending.attempts < limit) {
            await sleep(backoff * pending.attempts);
            continue;
          }
          pending.uncertain = true;
          _notify();
          return {
            ok: false,
            retryable: true,
            reason: "REQUEST_IN_PROGRESS",
            pending: _clonePending(),
            response,
          };
        }

        const terminalSnapshot = _clonePending();
        clearPending();

        if (Number(terminalSnapshot?.lastStatus || 0) === 409 && code === "IDEMPOTENCY_KEY_REUSED") {
          return {
            ok: false,
            terminal: true,
            reason: "IDEMPOTENCY_KEY_REUSED",
            pending: terminalSnapshot,
            response,
          };
        }
        if (Number(response.status || 0) === 503 && code === "LLM_UNAVAILABLE") {
          return {
            ok: false,
            terminal: true,
            reason: "LLM_UNAVAILABLE",
            pending: terminalSnapshot,
            response,
          };
        }

        return {
          ok: false,
          terminal: true,
          reason: "HTTP_ERROR",
          pending: terminalSnapshot,
          response,
        };
      }

      pending.uncertain = true;
      _notify();
      return {
        ok: false,
        retryable: true,
        reason: "RETRY_EXHAUSTED",
        pending: _clonePending(),
      };
    }

    async function submit({ sessionId, payload }) {
      if (!sessionId) {
        throw new Error("session_id is required before step submission.");
      }
      const normalizedPayload = payload || {};
      const nextPayloadKey = _payloadKey(normalizedPayload);

      if (!pending) {
        pending = {
          sessionId,
          payload: JSON.parse(nextPayloadKey),
          payloadKey: nextPayloadKey,
          idempotencyKey: newIdempotencyKey(),
          attempts: 0,
          lastStatus: null,
          lastErrorCode: null,
          lastErrorMessage: null,
          uncertain: false,
        };
        _notify();
      } else if (pending.sessionId !== sessionId || pending.payloadKey !== nextPayloadKey) {
        const conflict = new Error("A different step action is still pending. Retry or clear the pending action first.");
        conflict.code = "PENDING_STEP_EXISTS";
        conflict.pending = _clonePending();
        throw conflict;
      } else if (pending.uncertain) {
        pending.attempts = 0;
        pending.uncertain = false;
        _notify();
      }

      return _runPending();
    }

    async function retryPending() {
      if (!pending) {
        throw new Error("No pending step to retry.");
      }
      if (pending.uncertain) {
        pending.attempts = 0;
        pending.uncertain = false;
        _notify();
      }
      return _runPending();
    }

    _notify();

    return {
      submit,
      retryPending,
      clearPending,
      getPending,
      maxAttempts: limit,
      backoffMs: backoff,
      idempotencyHeader: STEP_IDEMPOTENCY_HEADER,
    };
  }

  window.DemoShared = {
    sleep,
    mustEl,
    cloneJson,
    setElementMessage,
    formatStoryPathLines,
    bindAsyncClick,
    runAsyncWithSignal,
    newIdempotencyKey,
    detailCode,
    detailMessage,
    requestJson,
    callApi,
    listStories,
    createApiError,
    createStepRetryController,
    STEP_IDEMPOTENCY_HEADER,
  };
})();
