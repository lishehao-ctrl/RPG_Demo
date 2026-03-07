import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(SCRIPT_DIR, '..');
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..');

function resolveRepoPath(value) {
  if (!value) {
    throw new Error('Path value is required');
  }
  return path.isAbsolute(value) ? value : path.resolve(REPO_ROOT, value);
}

const DEFAULT_SUITE = path.resolve(REPO_ROOT, 'eval_data/author_play_stability_suite_v1.json');
const DEFAULT_OUTPUT = path.resolve(REPO_ROOT, 'reports/author_play_release/browser_report.json');
const DEFAULT_SCREENSHOTS = path.resolve(REPO_ROOT, 'reports/author_play_release/screenshots');
const DEFAULT_EMAIL = process.env.APP_ADMIN_BOOTSTRAP_EMAIL || 'admin@example.com';
const DEFAULT_PASSWORD = process.env.APP_ADMIN_BOOTSTRAP_PASSWORD || 'admin123456';

function parseArgs(argv) {
  const args = {
    suiteFile: DEFAULT_SUITE,
    baseUrl: 'http://127.0.0.1:5173',
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
  console.log(`usage: node frontend/scripts/author_play_release_gate.mjs [options]\n\nOptions:\n  --suite-file <path>      Path to release suite JSON\n  --base-url <url>         Frontend base URL (default: http://127.0.0.1:5173)\n  --output <path>          Output browser report JSON\n  --screenshots-dir <dir>  Directory for screenshots\n  --email <email>          Admin login email\n  --password <password>    Admin login password\n  --headed                 Run headed browser\n  -h, --help               Show this help`);
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

function collectRequestLog(page, store) {
  page.removeAllListeners('response');
  page.on('response', async (response) => {
    const url = response.url();
    if (!url.includes('/stories') && !url.includes('/sessions') && !url.includes('/admin/auth/login')) {
      return;
    }
    store.push({
      url,
      status: response.status(),
      requestId: response.headers()['x-request-id'] ?? null,
    });
  });
}

async function login(page, args) {
  await page.goto(uiUrl(args.baseUrl, '/login'), { waitUntil: 'domcontentloaded' });
  await page.getByRole('textbox', { name: 'Admin Email' }).fill(args.email);
  await page.getByRole('textbox', { name: 'Access Phrase' }).fill(args.password);
  await page.getByRole('button', { name: 'Enter Author Suite' }).click();
  await page.waitForURL('**/author/stories');
}

async function generateFromAuthor(page, browserRequests, testCase, args) {
  await page.goto(uiUrl(args.baseUrl, '/author/stories'), { waitUntil: 'domcontentloaded' });
  await page.getByRole('textbox', { name: /Prompt Brief/ }).fill(testCase.kind === 'prompt' ? testCase.prompt_text : '');
  await page.getByRole('textbox', { name: /Seed Text/ }).fill(testCase.kind === 'seed' ? testCase.seed_text : '');
  await page.getByRole('textbox', { name: 'Style' }).fill(testCase.style ?? 'tense, cinematic, strategic');
  await page.getByRole('spinbutton', { name: 'Minutes' }).fill(String(testCase.target_minutes ?? 10));
  await page.getByRole('spinbutton', { name: 'NPC Count' }).fill(String(testCase.npc_count ?? 4));
  await page.getByRole('button', { name: 'Generate Draft' }).click();

  await Promise.race([
    page.waitForURL('**/author/stories/*', { timeout: 180000 }),
    page.getByText(/story generation failed|prompt_compile_failed|validation_error/i).waitFor({ timeout: 180000 }),
  ]);

  const currentUrl = page.url();
  const failed = currentUrl.endsWith('/author/stories');
  if (failed) {
    return {
      status: 'failed',
      errorText: await page.locator('body').innerText(),
      requestIds: browserRequests.splice(0),
    };
  }

  const storyId = currentUrl.split('/').pop();
  return {
    status: 'ok',
    storyId,
    requestIds: browserRequests.splice(0),
  };
}

async function publishStory(page, browserRequests, storyId, screenshotsDir, caseId) {
  await page.waitForURL(`**/author/stories/${storyId}`);
  const title = await page.getByRole('heading', { level: 2 }).first().innerText();
  await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_author.png`), fullPage: true, type: 'png' });
  await page.getByRole('button', { name: 'Publish For Play' }).click();
  await page.getByRole('button', { name: 'Open Play Library' }).waitFor({ timeout: 120000 });
  return {
    title,
    requestIds: browserRequests.splice(0),
  };
}

async function gotoPlayLibrary(page) {
  await page.getByRole('button', { name: 'Open Play Library' }).click();
  await page.waitForURL('**/play/library');
}

async function startSessionFromLibrary(page, storyId) {
  const card = page.locator('article', { hasText: storyId }).first();
  await card.getByRole('button', { name: 'Start Play Session' }).click();
  await page.waitForURL('**/play/sessions/*');
  return page.url().split('/').pop();
}

async function playMainSession(page, browserRequests, screenshotsDir, caseId) {
  await page.getByRole('textbox', { name: /Free Text Directive/ }).fill('Begin with a careful survey of the breach');
  await page.getByRole('button', { name: /Begin Session|Send Directive/ }).click();
  await page.getByText(/Turn 1/i).waitFor({ timeout: 120000 });
  const firstRouteSource = await page.locator('span').filter({ hasText: /llm/i }).first().innerText().catch(() => null);
  await page.locator('article').count();
  await page.locator('button').filter({ hasText: /\[.*\]/ }).first().click();
  await page.getByText(/Turn 2/i).waitFor({ timeout: 120000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByText(/Turn 1/i).waitFor({ timeout: 120000 });
  await page.getByText(/Turn 2/i).waitFor({ timeout: 120000 });
  await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_play.png`), fullPage: true, type: 'png' });
  return {
    status: 'ok',
    routeSourceSeen: firstRouteSource,
    requestIds: browserRequests.splice(0),
  };
}

async function playButtonSession(page, browserRequests) {
  await page.getByRole('textbox', { name: /Free Text Directive/ }).fill('Begin with a careful survey of the breach');
  await page.getByRole('button', { name: /Begin Session|Send Directive/ }).click();
  await page.getByText(/Turn 1/i).waitFor({ timeout: 120000 });
  await page.locator('button').filter({ hasText: /\[.*\]/ }).first().click();
  await page.getByText(/Turn 2/i).waitFor({ timeout: 120000 });
  return {
    status: 'ok',
    requestIds: browserRequests.splice(0),
  };
}

async function playEdgeSession(page, browserRequests, screenshotsDir, caseId) {
  await page.getByRole('textbox', { name: /Free Text Directive/ }).fill('help me progress, I am lost, ???, preserve trust, move now');
  await page.getByRole('button', { name: /Begin Session|Send Directive/ }).click();
  await Promise.race([
    page.getByText(/Turn 1/i).waitFor({ timeout: 120000 }),
    page.getByText(/error|failed|unavailable/i).waitFor({ timeout: 120000 }),
  ]);
  const body = await page.locator('body').innerText();
  if (/error|failed|unavailable/i.test(body) && !/Turn 1/i.test(body)) {
    await page.screenshot({ path: path.join(screenshotsDir, `${caseId}_play_error.png`), fullPage: true, type: 'png' });
    return {
      status: 'failed',
      errorText: body,
      requestIds: browserRequests.splice(0),
    };
  }
  return {
    status: 'ok',
    requestIds: browserRequests.splice(0),
  };
}

async function runCase(page, testCase, screenshotsDir, args) {
  const browserRequests = [];
  collectRequestLog(page, browserRequests);
  const generation = await generateFromAuthor(page, browserRequests, testCase, args);
  if (generation.status !== 'ok') {
    return { case: testCase, generation, status: 'failed' };
  }
  const published = await publishStory(page, browserRequests, generation.storyId, screenshotsDir, testCase.id);
  await gotoPlayLibrary(page);

  const sessionResults = [];
  const sessionId = await startSessionFromLibrary(page, generation.storyId);
  sessionResults.push({ sessionType: 'main', sessionId, ...(await playMainSession(page, browserRequests, screenshotsDir, testCase.id)) });

  await page.goto(uiUrl(args.baseUrl, '/play/library'), { waitUntil: 'domcontentloaded' });
  const sessionId2 = await startSessionFromLibrary(page, generation.storyId);
  sessionResults.push({ sessionType: 'button', sessionId: sessionId2, ...(await playButtonSession(page, browserRequests)) });

  await page.goto(uiUrl(args.baseUrl, '/play/library'), { waitUntil: 'domcontentloaded' });
  const sessionId3 = await startSessionFromLibrary(page, generation.storyId);
  sessionResults.push({ sessionType: 'edge', sessionId: sessionId3, ...(await playEdgeSession(page, browserRequests, screenshotsDir, testCase.id)) });

  const passed = sessionResults.every((item) => item.status === 'ok');
  return {
    case: testCase,
    generation,
    published,
    sessions: sessionResults,
    status: passed ? 'passed' : 'failed',
  };
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    printHelp();
    return 0;
  }

  const suite = await loadSuite(args.suiteFile);
  await ensureDir(path.dirname(args.output));
  await ensureDir(args.screenshotsDir);
  const executablePath = await resolveChromeExecutable();
  const browser = await chromium.launch({ headless: !args.headed, executablePath });
  const context = await browser.newContext({ viewport: { width: 1600, height: 980 } });
  const page = await context.newPage();

  await login(page, args);

  const caseResults = [];
  for (const testCase of suite.cases) {
    caseResults.push(await runCase(page, testCase, args.screenshotsDir, args));
  }

  await browser.close();

  const summary = {
    generated_at: new Date().toISOString(),
    suite,
    status: caseResults.every((item) => item.status === 'passed') ? 'passed' : (caseResults.some((item) => item.status === 'passed') ? 'partial' : 'failed'),
    case_count: caseResults.length,
    passed_case_count: caseResults.filter((item) => item.status === 'passed').length,
    failed_case_count: caseResults.filter((item) => item.status !== 'passed').length,
    cases: caseResults,
    screenshots_dir: args.screenshotsDir,
  };

  await fs.writeFile(args.output, JSON.stringify(summary, null, 2));
  console.log(args.output);
  return summary.status === 'passed' ? 0 : 1;
}

main().then((code) => process.exit(code)).catch((error) => {
  console.error(error);
  process.exit(1);
});
