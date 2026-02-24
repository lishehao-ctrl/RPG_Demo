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
          let handled = false;
          if (onError) {
            try {
              handled = onError(error) === true;
            } catch (onErrorFailure) {
              console.error(onErrorFailure); // eslint-disable-line no-console
            }
          }
          if (handled) {
            _applyStatus("idle", defaultLabel);
            return;
          }
          _applyStatus("error", errorLabel);
          settleTimer = window.setTimeout(() => {
            _applyStatus("idle", defaultLabel);
          }, errorHoldMs);
          if (onError) return;
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
    const signal = options.signal;
    Object.keys(extraHeaders).forEach((key) => {
      headers[key] = extraHeaders[key];
    });

    let response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal,
      });
    } catch (error) {
      const isAborted = Boolean(
        error && (error.name === "AbortError" || error.code === "ABORT_ERR"),
      );
      return {
        ok: false,
        status: 0,
        data: null,
        errorType: isAborted ? "aborted" : "network",
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
    error.detail = response?.data?.detail || null;
    error.response = response;
    return error;
  }

  async function callApi(method, url, body, options = {}) {
    const response = await requestJson(method, url, body, options);
    if (!response.ok) {
      if (response.errorType === "aborted") {
        const error = new Error(`${method} ${url} canceled by user`);
        error.status = 0;
        error.code = "REQUEST_ABORTED";
        error.payload = null;
        error.response = response;
        error.errorType = "aborted";
        throw error;
      }
      throw createApiError(response, `${method} ${url}`);
    }
    return response.data;
  }

  function _parseSseBlock(block) {
    const lines = String(block || "").split("\n");
    let eventName = "message";
    const dataLines = [];
    lines.forEach((lineRaw) => {
      const line = String(lineRaw || "");
      if (!line || line.startsWith(":")) return;
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim() || "message";
        return;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    });
    return {
      event: eventName,
      dataText: dataLines.join("\n"),
    };
  }

  function _parseSsePayload(dataText) {
    const text = String(dataText || "").trim();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return { message: text };
    }
  }

  async function callApiStream(method, url, body, options = {}) {
    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const extraHeaders = options.headers || {};
    const signal = options.signal;
    const onStage = typeof options.onStage === "function" ? options.onStage : null;
    Object.keys(extraHeaders).forEach((key) => {
      headers[key] = extraHeaders[key];
    });

    let response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal,
      });
    } catch (error) {
      const isAborted = Boolean(
        error && (error.name === "AbortError" || error.code === "ABORT_ERR"),
      );
      const streamError = new Error(
        isAborted ? `${method} ${url} canceled by user` : `${method} ${url} network error`,
      );
      streamError.status = 0;
      streamError.code = isAborted ? "REQUEST_ABORTED" : "NETWORK_ERROR";
      streamError.payload = null;
      streamError.errorType = isAborted ? "aborted" : "network";
      streamError.networkError = isAborted ? null : error;
      throw streamError;
    }

    if (!response.ok) {
      const text = await response.text();
      let parsed = {};
      if (text) {
        try {
          parsed = JSON.parse(text);
        } catch {
          parsed = text;
        }
      }
      throw createApiError(
        {
          ok: false,
          status: response.status,
          data: parsed,
          errorType: null,
          networkError: null,
        },
        `${method} ${url}`,
      );
    }

    if (!response.body) {
      throw new Error(`${method} ${url} returned empty stream body`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let resultPayload = null;

    while (true) {
      const { done, value } = await reader.read();
      const chunk = decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");
      buffer += chunk;

      let boundaryIndex = buffer.indexOf("\n\n");
      while (boundaryIndex >= 0) {
        const blockRaw = buffer.slice(0, boundaryIndex).trim();
        buffer = buffer.slice(boundaryIndex + 2);
        boundaryIndex = buffer.indexOf("\n\n");
        if (!blockRaw) continue;

        const parsedBlock = _parseSseBlock(blockRaw);
        const payloadParsed = _parseSsePayload(parsedBlock.dataText);
        if (parsedBlock.event === "stage") {
          if (onStage) {
            try {
              onStage(payloadParsed);
            } catch (stageError) {
              console.error(stageError); // eslint-disable-line no-console
            }
          }
          continue;
        }
        if (parsedBlock.event === "result") {
          resultPayload = payloadParsed;
          continue;
        }
        if (parsedBlock.event === "error") {
          const status = Number(payloadParsed?.status || 503);
          const detail = payloadParsed?.detail && typeof payloadParsed.detail === "object"
            ? payloadParsed.detail
            : payloadParsed;
          throw createApiError(
            {
              ok: false,
              status,
              data: { detail },
              errorType: null,
              networkError: null,
            },
            `${method} ${url}`,
          );
        }
      }

      if (done) break;
    }

    if (resultPayload === null || typeof resultPayload !== "object") {
      throw new Error(`${method} ${url} stream ended without result event`);
    }
    return resultPayload;
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

  function createStepRetryController({ maxAttempts = 3, backoffMs = 350, onStatus, onStage } = {}) {
    const limit = Math.max(1, Number(maxAttempts || 1));
    const backoff = Math.max(1, Number(backoffMs || 1));
    const emit = typeof onStatus === "function" ? onStatus : () => {};
    const emitStage = typeof onStage === "function" ? onStage : () => {};
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

        let response = null;
        try {
          const streamResult = await callApiStream(
            "POST",
            `/sessions/${pending.sessionId}/step/stream`,
            pending.payload,
            {
              headers: { [STEP_IDEMPOTENCY_HEADER]: pending.idempotencyKey },
              onStage: (stage) => {
                emitStage(stage, { pending: _clonePending(), maxAttempts: limit, backoffMs: backoff });
              },
            },
          );
          response = {
            ok: true,
            status: 200,
            data: streamResult,
            errorType: null,
            networkError: null,
          };
        } catch (error) {
          if (String(error?.code || "") === "REQUEST_ABORTED") {
            throw error;
          }
          if (error?.errorType === "network" || error?.status === 0) {
            response = {
              ok: false,
              status: 0,
              data: null,
              errorType: "network",
              networkError: error?.networkError || error,
            };
          } else {
            response = {
              ok: false,
              status: Number(error?.status || 500),
              data: error?.payload || { detail: error?.detail || { message: String(error || "request failed") } },
              errorType: null,
              networkError: null,
            };
          }
        }

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
    callApiStream,
    listStories,
    createApiError,
    createStepRetryController,
    STEP_IDEMPOTENCY_HEADER,
  };
})();
