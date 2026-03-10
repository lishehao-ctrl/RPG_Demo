import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(SCRIPT_DIR, '..');
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..');

const DEFAULT_SUITE = path.resolve(REPO_ROOT, 'eval_data/author_play_stability_suite_v1.json');
const DEFAULT_OUTPUT = path.resolve(REPO_ROOT, 'reports/author_play_release/browser_report.json');
const DEFAULT_SCREENSHOTS = path.resolve(REPO_ROOT, 'reports/author_play_release/screenshots');
const DEFAULT_EMAIL = process.env.APP_ADMIN_BOOTSTRAP_EMAIL || 'admin@example.com';
const DEFAULT_PASSWORD = process.env.APP_ADMIN_BOOTSTRAP_PASSWORD || 'admin123456';
const MAIN_SESSION_MIN_STEPS = 8;
const MAIN_SESSION_MAX_STEPS = 12;
const BUTTON_SESSION_MIN_STEPS = 3;
const EDGE_SESSION_MIN_STEPS = 2;
const AUTHOR_RUN_TIMEOUT_MS = 180_000;
const SESSION_STEP_TIMEOUT_MS = 120_000;

const MAIN_TEXT_PROMPTS = [
  'Begin with a careful survey of the breach and stabilize the team.',
  'Trace the source of the anomaly and reduce coordination noise.',
  'Talk to the most nervous NPC and protect public trust.',
  'Help me progress while preserving trust and keeping casualties low.',
  'Push toward containment but avoid a reckless shortcut.',
  'Reassess what changed and choose the safest strategic move.',
];

function resolveRepoPath(value) {
  if (!value) {
    throw new Error('Path value is required');
  }
  return path.isAbsolute(value) ? value : path.resolve(REPO_ROOT, value);
}

function parseArgs(argv) {
  const args = {
    suiteFile: DEFAULT_SUITE,
    baseUrl: 'http://127.0.0.1:8173',
    output: DEFAULT_OUTPUT,
    screenshotsDir: DEFAULT_SCREENSHOTS,
    headed: false,
    email: DEFAULT_EMAIL,
    password: DEFAULT_PASSWORD,
  };
  for (let index = 2; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--help' || value === '-h') {
      args.help = true;
      break;
    }
    if (value === '--headed') {
      args.headed = true;
      continue;
    }
    if (value === '--suite-file') {
      args.suiteFile = resolveRepoPath(argv[++index]);
      continue;
    }
    if (value === '--base-url') {
      args.baseUrl = argv[++index];
      continue;
    }
    if (value === '--output') {
      args.output = resolveRepoPath(argv[++index]);
      continue;
    }
    if (value === '--screenshots-dir') {
      args.screenshotsDir = resolveRepoPath(argv[++index]);
      continue;
    }
    if (value === '--email') {
      args.email = argv[++index];
      continue;
    }
    if (value === '--password') {
      args.password = argv[++index];
      continue;
    }
    throw new Error(`Unknown arg: ${value}`);
  }
  return args;
}

function printHelp() {
  console.log(`usage: node frontend/scripts/author_play_release_gate.mjs [options]\n\nOptions:\n  --suite-file <path>      Path to release suite JSON\n  --base-url <url>         Frontend base URL (default: http://127.0.0.1:8173)\n  --output <path>          Output browser report JSON\n  --screenshots-dir <dir>  Directory for screenshots\n  --email <email>          Admin login email\n  --password <password>    Admin login password\n  --headed                 Run headed browser\n  -h, --help               Show this help`);
}

function commonChromePaths() {
  return [
    process.env.PLAYWRIGHT_CHROME_EXECUTABLE,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/snap/bin/chromium',
  ].filter(Boolean);
}

async function resolveChromeExecutable() {
  for (const candidate of commonChromePaths()) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {}
  }
  throw new Error('No Chrome/Chromium executable found. Set PLAYWRIGHT_CHROME_EXECUTABLE.');
}

async function loadSuite(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf-8'));
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

function uiUrl(baseUrl, route) {
  const normalized = baseUrl.replace(/\/$/, '');
  return `${normalized}${route}`;
}

function apiUrl(baseUrl, route) {
  const normalized = baseUrl.replace(/\/$/, '');
  return `${normalized}/api${route}`;
}

function collectRequestLog(page, store) {
  page.removeAllListeners('response');
  page.on('response', async (response) => {
    const url = response.url();
    if (!url.includes('/stories') && !url.includes('/sessions') && !url.includes('/author') && !url.includes('/admin/auth/login')) {
      return;
    }
    store.push({
      url,
      status: response.status(),
      requestId: response.headers()['x-request-id'] ?? null,
    });
  });
}

function consumeRequestLog(store) {
  return store.splice(0).map((item) => ({ ...item }));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function login(page, args) {
  await page.goto(uiUrl(args.baseUrl, '/login'), { waitUntil: 'domcontentloaded' });
  if (/\/author\//.test(page.url())) {
    await page.getByRole('heading', { name: /Story Forge/i }).waitFor({ timeout: 15000 });
    return;
  }
  await page.getByRole('textbox', { name: 'Admin Email' }).fill(args.email);
  await page.getByRole('textbox', { name: 'Access Phrase' }).fill(args.password);
  await page.getByRole('button', { name: 'Enter Author Suite' }).click();
  await Promise.race([
    page.waitForURL((url) => /\/author\//.test(url.pathname), { timeout: 20000 }),
    page.getByRole('heading', { name: /Story Forge/i }).waitFor({ timeout: 20000 }),
  ]).catch(async (error) => {
    const body = await page.locator('body').innerText().catch(() => '');
    throw new Error(`browser_login_failed: ${body || String(error)}`);
  });
}

async function apiLogin(args) {
  const response = await fetch(apiUrl(args.baseUrl, '/admin/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: args.email, password: args.password }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`api_login_failed: ${JSON.stringify(payload)}`);
  }
  return { Authorization: `Bearer ${payload.access_token}` };
}

async function pollAuthorRunViaApi(args, authHeaders, runId) {
  const start = Date.now();
  while (Date.now() - start < AUTHOR_RUN_TIMEOUT_MS) {
    const response = await fetch(apiUrl(args.baseUrl, `/author/runs/${runId}`), { headers: authHeaders });
    const payload = await response.json();
    if (!response.ok) {
      return { status: 'failed', errorText: JSON.stringify(payload) };
    }
    if (payload.status === 'review_ready' || payload.status === 'failed') {
      return payload;
    }
    await wait(2000);
  }
  return { status: 'timeout', error_message: 'author run polling timed out' };
}

async function waitForAuthorRunTerminal(page) {
  const start = Date.now();
  while (Date.now() - start < AUTHOR_RUN_TIMEOUT_MS) {
    const url = page.url();
    if (/\/author\/stories\/[^/]+\/review$/.test(url)) {
      const parts = url.split('/');
      return { status: 'review_ready', storyId: parts.at(-2) ?? null };
    }
    if (/\/author\/runs\/[^/]+$/.test(url)) {
      const body = await page.locator('body').innerText();
      if (/Run failed|Run diagnostics/i.test(body)) {
        return { status: 'failed', storyId: null, errorText: body };
      }
    }
    const body = await page.locator('body').innerText();
    if (/run failed|author run failed|prompt_compile_failed|validation_error|workflow failed/i.test(body)) {
      return { status: 'failed', storyId: null, errorText: body };
    }
    if (/Run failed|Run ready|Run review_ready|Graph running|Queued|Current node:/i.test(body)) {
      // stay on page and keep polling UI state
    }
    await wait(2000);
  }
  return { status: 'timeout', storyId: null, errorText: 'author run polling timed out' };
}

async function generateFromAuthor(page, browserRequests, testCase, args, authHeaders) {
  await page.goto(uiUrl(args.baseUrl, '/author/stories'), { waitUntil: 'domcontentloaded' });
  const rawBrief = (testCase.kind === 'prompt' ? testCase.prompt_text : testCase.seed_text) || '';
  await page.getByRole('textbox', { name: /Raw Brief/ }).fill(rawBrief);

  const createResponsePromise = page.waitForResponse((response) => response.url().includes('/author/runs') && response.request().method() === 'POST', { timeout: 30000 });
  await page.getByRole('button', { name: /Create Author Run|Running Author Graph/ }).click();
  const createResponse = await createResponsePromise;
  const created = await createResponse.json();
  if (!createResponse.ok()) {
    return {
      status: 'failed',
      authorRunStatus: 'failed',
      authorRunCurrentNode: null,
      errorText: JSON.stringify(created),
      requestIds: consumeRequestLog(browserRequests),
    };
  }

  await page.goto('about:blank');
  const terminal = await pollAuthorRunViaApi(args, authHeaders, created.run_id);
  if (terminal.status !== 'review_ready' || !created.story_id) {
    return {
      status: 'failed',
      storyId: created.story_id,
      runId: created.run_id,
      authorRunStatus: terminal.status,
      authorRunCurrentNode: terminal.current_node ?? null,
      errorText: terminal.error_message || terminal.errorText || await page.locator('body').innerText(),
      requestIds: consumeRequestLog(browserRequests),
    };
  }

  await page.goto(uiUrl(args.baseUrl, `/author/stories/${created.story_id}/review`), { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Publish For Play' }).waitFor({ timeout: 120000 });
  return {
    status: 'ok',
    storyId: created.story_id,
    runId: created.run_id,
    authorRunStatus: terminal.status,
    authorRunCurrentNode: terminal.current_node ?? null,
    requestIds: consumeRequestLog(browserRequests),
  };
}

async function publishStory(page, browserRequests, storyId, screenshotsDir, caseId) {
  await page.waitForURL((url) => /\/author\/stories\/.+\/review$/.test(url.pathname), { timeout: 120000 });
  const title = await page.getByRole('heading', { level: 2 }).first().innerText();
  await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_author_detail.png`), fullPage: true, type: 'png' });
  const publishButton = page.getByRole('button', { name: 'Publish For Play' });
  await publishButton.waitFor({ timeout: 120000 });
  await publishButton.click();
  await page.getByRole('button', { name: 'Open Play Library' }).waitFor({ timeout: 120000 });
  return {
    status: 'ok',
    title,
    requestIds: consumeRequestLog(browserRequests),
  };
}

async function gotoPlayLibrary(page) {
  await page.getByRole('button', { name: 'Open Play Library' }).click();
  await page.waitForURL('**/play/library');
}

async function startSessionFromLibrary(page, storyId) {
  const card = page.locator('article').filter({ hasText: storyId }).first();
  await card.getByRole('button', { name: 'Start Play Session' }).click();
  await page.waitForURL('**/play/sessions/*');
  return page.url().split('/').pop();
}

async function readLatestTurnState(page) {
  const panelText = await page.locator('body').innerText();
  const sceneMatch = panelText.match(/Current Turn State[\s\S]*?Scene\s+([^\n]+)/i);
  const routeMatch = panelText.match(/Current Turn State[\s\S]*?Route\s+([^\n]+)/i);
  return {
    sceneIdAfter: sceneMatch?.[1]?.trim() ?? null,
    routeSource: routeMatch?.[1]?.toLowerCase().includes('llm') ? 'llm' : routeMatch?.[1]?.toLowerCase().includes('button') ? 'button' : null,
    ended: /Session sealed|Completed/i.test(await page.locator('body').innerText()),
  };
}

async function submitTextTurn(page, text) {
  await page.getByRole('textbox', { name: /Your move/i }).fill(text);
  await page.getByRole('button', { name: /Begin Session|Send Directive/ }).click();
}

async function waitForSuggestedMoveButton(page, timeoutMs = 15000) {
  const buttons = page.getByRole('button').filter({ hasText: /Fast \/ Risky|Low Risk|Safe \/ Costly|Trace The Anomaly|Protect Civilians|Decode Control Pattern/i });
  try {
    await buttons.first().waitFor({ timeout: timeoutMs });
    return buttons.first();
  } catch {
    return null;
  }
}

async function clickSuggestedMove(page) {
  const button = await waitForSuggestedMoveButton(page, 30000);
  if (!button) {
    throw new Error('suggested_move_unavailable');
  }
  await button.click({ timeout: 30000 });
}

async function waitForTurn(page, turnNumber) {
  await Promise.race([
    page.getByText(new RegExp(`Turn ${turnNumber}`, 'i')).waitFor({ timeout: SESSION_STEP_TIMEOUT_MS }),
    page.getByText(/error|failed|unavailable/i).waitFor({ timeout: SESSION_STEP_TIMEOUT_MS }),
  ]);
}

async function reloadAndVerifyTurns(page, expectedTurns) {
  await page.reload({ waitUntil: 'domcontentloaded' });
  for (const turn of expectedTurns) {
    await page.getByText(new RegExp(`Turn ${turn}`, 'i')).waitFor({ timeout: SESSION_STEP_TIMEOUT_MS });
  }
  return true;
}

async function playMainSession(page, browserRequests, screenshotsDir, caseId) {
  const steps = [];
  const routeSources = [];
  const gatewayModes = [];
  let reloadChecksPassed = true;
  let turnNumber = 0;

  while (turnNumber < MAIN_SESSION_MAX_STEPS) {
    const stepIndex = turnNumber + 1;
    const useText = stepIndex === 1 || stepIndex === 3 || stepIndex === 5 || stepIndex === 6 || stepIndex > 6 ? stepIndex % 2 === 1 || stepIndex === 6 : false;
    if (useText) {
      const prompt = MAIN_TEXT_PROMPTS[Math.min(stepIndex - 1, MAIN_TEXT_PROMPTS.length - 1)];
      await submitTextTurn(page, prompt);
    } else {
      try {
        await clickSuggestedMove(page);
      } catch (error) {
        if (String(error).includes('suggested_move_unavailable')) {
          const fallbackPrompt = MAIN_TEXT_PROMPTS[Math.min(stepIndex - 1, MAIN_TEXT_PROMPTS.length - 1)] || 'Continue carefully and make steady progress.';
          await submitTextTurn(page, fallbackPrompt);
        } else {
          throw error;
        }
      }
    }
    turnNumber += 1;
    await waitForTurn(page, turnNumber);

    const bodyText = await page.locator('body').innerText();
    if (/error|failed|unavailable/i.test(bodyText) && !new RegExp(`Turn ${turnNumber}`, 'i').test(bodyText)) {
      await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_play_main_error.png`), fullPage: true, type: 'png' });
      return {
        status: 'failed',
        stepCount: turnNumber,
        reloadChecksPassed,
        routeSources,
        gatewayModes,
        historyTurnCount: turnNumber,
        requestIds: consumeRequestLog(browserRequests),
        steps,
        errorText: bodyText,
      };
    }

    const state = await readLatestTurnState(page);
    routeSources.push(state.routeSource);
    const gatewayMode = await page.locator('text=/worker|unknown/i').last().innerText().catch(() => null);
    gatewayModes.push(gatewayMode);
    steps.push({
      stepIndex,
      inputType: useText ? 'text' : 'button',
      routeSource: state.routeSource,
      llmGatewayMode: gatewayMode,
      sceneIdAfter: state.sceneIdAfter,
      ended: state.ended,
    });

    if (stepIndex === 3 || stepIndex === 6) {
      reloadChecksPassed = reloadChecksPassed && (await reloadAndVerifyTurns(page, Array.from({ length: turnNumber }, (_, idx) => idx + 1)));
      await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_play_main_reload_${stepIndex}.png`), fullPage: true, type: 'png' });
    }

    if (stepIndex === 4) {
      await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_play_main_mid.png`), fullPage: true, type: 'png' });
    }

    if (state.ended && stepIndex >= MAIN_SESSION_MIN_STEPS) {
      break;
    }
  }

  const historyTurnCount = await page.getByText(/Turn /i).count().catch(() => turnNumber);
  const textRouteSeen = routeSources.some((value) => value === 'llm');
  const passed = turnNumber >= MAIN_SESSION_MIN_STEPS && reloadChecksPassed && textRouteSeen;
  return {
    status: passed ? 'ok' : 'failed',
    stepCount: turnNumber,
    reloadChecksPassed,
    routeSources,
    gatewayModes,
    historyTurnCount,
    requestIds: consumeRequestLog(browserRequests),
    steps,
  };
}

async function playButtonSession(page, browserRequests) {
  const steps = [];
  await submitTextTurn(page, 'Begin with a careful survey of the breach');
  await waitForTurn(page, 1);
  let count = 1;
  steps.push({ stepIndex: 1, inputType: 'text' });
  while (count < BUTTON_SESSION_MIN_STEPS) {
    const button = await waitForSuggestedMoveButton(page, 15000);
    if (!button) {
      break;
    }
    await button.click({ timeout: 30000 });
    count += 1;
    await waitForTurn(page, count);
    steps.push({ stepIndex: count, inputType: 'button' });
  }
  return {
    status: 'ok',
    stepCount: count,
    reloadChecksPassed: true,
    routeSources: [],
    gatewayModes: [],
    historyTurnCount: count,
    requestIds: consumeRequestLog(browserRequests),
    steps,
  };
}

async function playEdgeSession(page, browserRequests, screenshotsDir, caseId) {
  const prompts = [
    'help me progress, I am lost, preserve trust, move now',
    'I need help but do not create more noise.',
  ];
  const steps = [];
  for (let index = 0; index < EDGE_SESSION_MIN_STEPS; index += 1) {
    await submitTextTurn(page, prompts[index]);
    await waitForTurn(page, index + 1);
    const body = await page.locator('body').innerText();
    if (/error|failed|unavailable/i.test(body) && !new RegExp(`Turn ${index + 1}`, 'i').test(body)) {
      await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_play_edge_error.png`), fullPage: true, type: 'png' });
      return {
        status: 'failed',
        stepCount: index,
        reloadChecksPassed: false,
        routeSources: [],
        gatewayModes: [],
        historyTurnCount: index,
        requestIds: consumeRequestLog(browserRequests),
        steps,
        errorText: body,
      };
    }
    const state = await readLatestTurnState(page);
    steps.push({ stepIndex: index + 1, inputType: 'text', routeSource: state.routeSource, ended: state.ended });
  }
  return {
    status: 'ok',
    stepCount: prompts.length,
    reloadChecksPassed: true,
    routeSources: steps.map((item) => item.routeSource ?? null),
    gatewayModes: [],
    historyTurnCount: prompts.length,
    requestIds: consumeRequestLog(browserRequests),
    steps,
  };
}

function buildCaseStatus({ generation, published, sessions }) {
  const failures = [];
  if (generation.status !== 'ok') failures.push('author_run_failed');
  if (published.status !== 'ok') failures.push('publish_failed');
  const mainSession = sessions.find((item) => item.sessionType === 'main');
  if (!mainSession || mainSession.status !== 'ok') failures.push('main_session_failed');
  if (mainSession && !mainSession.reloadChecksPassed) failures.push('reload_check_failed');
  if (mainSession && !(mainSession.routeSources || []).includes('llm')) failures.push('missing_llm_text_route');
  if (sessions.filter((item) => item.status === 'ok').length < 2) failures.push('insufficient_extra_session_success');
  return {
    status: failures.length === 0 ? 'passed' : 'failed',
    failures,
  };
}

async function runCase(page, testCase, screenshotsDir, args, authHeaders) {
  const browserRequests = [];
  collectRequestLog(page, browserRequests);
  const generation = await generateFromAuthor(page, browserRequests, testCase, args, authHeaders);
  if (generation.status !== 'ok') {
    return { case: testCase, generation, published: { status: 'failed' }, sessions: [], screenshots: [], ...buildCaseStatus({ generation, published: { status: 'failed' }, sessions: [] }) };
  }

  const published = await publishStory(page, browserRequests, generation.storyId, screenshotsDir, testCase.id);
  await gotoPlayLibrary(page);

  const screenshots = [
    path.join(screenshotsDir, `${testCase.id}_author_detail.png`),
  ];

  const sessions = [];
  const sessionId = await startSessionFromLibrary(page, generation.storyId);
  const mainSession = await playMainSession(page, browserRequests, screenshotsDir, testCase.id);
  sessions.push({ sessionType: 'main', sessionId, ...mainSession });
  screenshots.push(path.join(screenshotsDir, `${testCase.id}_play_main_mid.png`));
  screenshots.push(path.join(screenshotsDir, `${testCase.id}_play_main_reload_3.png`));
  screenshots.push(path.join(screenshotsDir, `${testCase.id}_play_main_reload_6.png`));

  await page.goto(uiUrl(args.baseUrl, '/play/library'), { waitUntil: 'domcontentloaded' });
  const sessionId2 = await startSessionFromLibrary(page, generation.storyId);
  sessions.push({ sessionType: 'button', sessionId: sessionId2, ...(await playButtonSession(page, browserRequests)) });

  await page.goto(uiUrl(args.baseUrl, '/play/library'), { waitUntil: 'domcontentloaded' });
  const sessionId3 = await startSessionFromLibrary(page, generation.storyId);
  sessions.push({ sessionType: 'edge', sessionId: sessionId3, ...(await playEdgeSession(page, browserRequests, screenshotsDir, testCase.id)) });

  const verdict = buildCaseStatus({ generation, published, sessions });
  return {
    case: testCase,
    author_run_status: generation.authorRunStatus,
    author_run_current_node: generation.authorRunCurrentNode,
    generation,
    publish_status: published.status,
    published,
    sessions,
    screenshots,
    ...verdict,
  };
}

function summarizeCases(caseResults) {
  return {
    generated_at: new Date().toISOString(),
    status: caseResults.every((item) => item.status === 'passed') ? 'passed' : (caseResults.some((item) => item.status === 'passed') ? 'partial' : 'failed'),
    case_count: caseResults.length,
    passed_case_count: caseResults.filter((item) => item.status === 'passed').length,
    failed_case_count: caseResults.filter((item) => item.status !== 'passed').length,
    cases: caseResults,
  };
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    printHelp();
    return 0;
  }

  await ensureDir(path.dirname(args.output));
  await ensureDir(args.screenshotsDir);
  let suite = null;
  let browser = null;
  let summary = null;
  try {
    suite = await loadSuite(args.suiteFile);
    const executablePath = await resolveChromeExecutable();
    browser = await chromium.launch({ headless: !args.headed, executablePath });
    const context = await browser.newContext({ viewport: { width: 1600, height: 980 } });
    const page = await context.newPage();

    await login(page, args);
    const authHeaders = await apiLogin(args);

    const caseResults = [];
    for (const testCase of suite.cases) {
      try {
        caseResults.push(await runCase(page, testCase, args.screenshotsDir, args, authHeaders));
      } catch (error) {
        caseResults.push({
          case: testCase,
          status: 'failed',
          failures: ['browser_runner_exception'],
          error: error instanceof Error ? error.message : String(error),
          error_stack: error instanceof Error ? (error.stack || null) : null,
        });
      }
    }

    summary = {
      suite,
      screenshots_dir: args.screenshotsDir,
      ...summarizeCases(caseResults),
    };
    await fs.writeFile(args.output, JSON.stringify(summary, null, 2));
    console.log(args.output);
    return summary.status === 'passed' ? 0 : 1;
  } catch (error) {
    summary = {
      suite,
      screenshots_dir: args.screenshotsDir,
      generated_at: new Date().toISOString(),
      status: 'failed',
      case_count: suite?.cases?.length ?? 0,
      passed_case_count: 0,
      failed_case_count: suite?.cases?.length ?? 0,
      cases: [],
      error: error instanceof Error ? error.message : String(error),
      error_stack: error instanceof Error ? (error.stack || null) : null,
    };
    await fs.writeFile(args.output, JSON.stringify(summary, null, 2));
    console.error(error);
    console.log(args.output);
    return 1;
  } finally {
    await browser?.close().catch(() => {});
  }
}

export { parseArgs, summarizeCases };

if (import.meta.url === `file://${process.argv[1]}`) {
  main().then((code) => process.exit(code)).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
