from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["webdemo"])


@router.get("/demo", response_class=HTMLResponse)
def demo_page() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>RPG Demo</title>
  <style>
    body { font-family: sans-serif; max-width: 900px; margin: 20px auto; padding: 0 12px; }
    .row { margin: 10px 0; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    input[type=text] { min-width: 280px; padding: 6px; }
    button { padding: 6px 10px; }
    pre { background: #111; color: #ddd; padding: 12px; min-height: 260px; overflow: auto; white-space: pre-wrap; }
    code { background: #eee; padding: 2px 4px; }
  </style>
</head>
<body>
  <h1>RPG Demo UI</h1>
  <p>Session ID: <code id=\"sessionId\">(none)</code></p>

  <div class=\"row\">
    <button id=\"createBtn\">Create session</button>
  </div>

  <div class=\"row\">
    <input id=\"stepText\" type=\"text\" placeholder=\"step text\" />
    <button id=\"stepBtn\">Step</button>
  </div>

  <div class=\"row\">
    <input id=\"snapshotName\" type=\"text\" placeholder=\"snapshot name\" value=\"manual\" />
    <button id=\"snapshotBtn\">Snapshot</button>
    <button id=\"rollbackBtn\">Rollback</button>
  </div>

  <div class=\"row\">
    <button id=\"endBtn\">End</button>
    <button id=\"replayBtn\">Replay</button>
  </div>

  <pre id=\"log\"></pre>

<script>
(function () {
  const KEY_SESSION = 'session_id';
  const KEY_SNAPSHOT = 'snapshot_id';
  const sessionEl = document.getElementById('sessionId');
  const logEl = document.getElementById('log');

  const getSession = () => localStorage.getItem(KEY_SESSION);
  const setSession = (sid) => {
    if (sid) localStorage.setItem(KEY_SESSION, sid);
    sessionEl.textContent = sid || '(none)';
  };

  function authHeaders() {
    const token = localStorage.getItem('auth_token');
    if (token) return { 'Authorization': `Bearer ${token}` };
    return { 'X-User-Id': '00000000-0000-0000-0000-000000000001' };
  }

  function appendLog(prefix, payload) {
    const line = `[${new Date().toISOString()}] ${prefix}\n${typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2)}\n\n`;
    logEl.textContent = line + logEl.textContent;
  }

  async function callApi(method, url, body) {
    const headers = { ...authHeaders() };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    const text = await res.text();
    let parsed;
    try { parsed = text ? JSON.parse(text) : {}; } catch { parsed = text; }
    if (!res.ok) throw { status: res.status, body: parsed };
    return parsed;
  }

  document.getElementById('createBtn').onclick = async () => {
    try {
      const out = await callApi('POST', '/sessions');
      setSession(out.id);
      appendLog('create', out);
    } catch (e) { appendLog('create error', e); }
  };

  document.getElementById('stepBtn').onclick = async () => {
    const sid = getSession();
    if (!sid) return appendLog('step error', 'No session_id, create session first');
    const text = document.getElementById('stepText').value || '';
    try {
      const out = await callApi('POST', `/sessions/${sid}/step`, { input_text: text });
      appendLog('step', out);
    } catch (e) { appendLog('step error', e); }
  };

  document.getElementById('snapshotBtn').onclick = async () => {
    const sid = getSession();
    if (!sid) return appendLog('snapshot error', 'No session_id, create session first');
    const name = document.getElementById('snapshotName').value || 'manual';
    try {
      const out = await callApi('POST', `/sessions/${sid}/snapshot?name=${encodeURIComponent(name)}`);
      if (out && out.snapshot_id) localStorage.setItem(KEY_SNAPSHOT, out.snapshot_id);
      appendLog('snapshot', out);
    } catch (e) { appendLog('snapshot error', e); }
  };

  document.getElementById('rollbackBtn').onclick = async () => {
    const sid = getSession();
    if (!sid) return appendLog('rollback error', 'No session_id, create session first');
    const snapshotId = localStorage.getItem(KEY_SNAPSHOT);
    if (!snapshotId) return appendLog('rollback error', 'No snapshot_id, create snapshot first');
    try {
      const out = await callApi('POST', `/sessions/${sid}/rollback?snapshot_id=${encodeURIComponent(snapshotId)}`);
      appendLog('rollback', out);
    } catch (e) { appendLog('rollback error', e); }
  };

  document.getElementById('endBtn').onclick = async () => {
    const sid = getSession();
    if (!sid) return appendLog('end error', 'No session_id, create session first');
    try {
      const out = await callApi('POST', `/sessions/${sid}/end`);
      appendLog('end', out);
    } catch (e) { appendLog('end error', e); }
  };

  document.getElementById('replayBtn').onclick = async () => {
    const sid = getSession();
    if (!sid) return appendLog('replay error', 'No session_id, create session first');
    try {
      const out = await callApi('GET', `/sessions/${sid}/replay`);
      appendLog('replay', out);
    } catch (e) { appendLog('replay error', e); }
  };

  setSession(getSession());
})();
</script>
</body>
</html>
"""
