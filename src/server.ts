import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import express, { type Request, type Response } from 'express';
import { browserState } from './browser.js';
import { DevError, PREVIEW_CSP } from './devmode.js';
import { BRICK_CSP } from './extensions.js';
import {
  BusyError,
  ConvError,
  FILE_DOWNLOAD_MAX,
  FILE_VIEW_MAX,
  Harness,
  MAX_TASK_CHARS,
  NEVER_REMEMBER,
  RULE_SCOPES,
  TERMINAL,
  UploadError,
  convFolderRel,
} from './harness.js';
import { defaultIDCConfig } from './idc.js';
import { KeyRouter, PROVIDERS, type KeyEntry } from './llm.js';
import { Permissions } from './permissions.js';
import { getPwaAsset, renderPage, type PageName } from './ui/render.js';
import {
  AppControl,
  SecretStore,
  SettingsError,
  UserConfig,
  applyIdc,
  applyPermissions,
  keyFormatOk,
  probeOllama,
} from './userconfig.js';

const PAGE_ROUTES: Record<string, PageName> = {
  '/': 'chat',
  '/chat': 'chat',
  '/dashboard': 'dashboard',
  '/connect': 'connect',
  '/settings': 'settings',
  '/welcome': 'welcome',
  '/help': 'help',
  '/dev': 'dev',
};

const MCP_PRESETS = {
  files: { name: { en: 'My files', fr: 'Mes fichiers' }, transport: 'stdio', needs: 'folder' },
  github: {
    name: { en: 'GitHub', fr: 'GitHub' },
    transport: 'http',
    needs: 'token',
    token_link: 'https://github.com/settings/personal-access-tokens/new',
  },
  web: { name: { en: '', fr: '' }, transport: 'http', needs: 'url' },
};

function makeEnvRouter(stateDir: string): KeyRouter | null {
  const envEntries: KeyEntry[] = [];
  const candidates: Array<[string, string, number]> = [
    ['gemini', 'GEMINI_API_KEY', 10],
    ['groq', 'GROQ_API_KEY', 20],
    ['openai', 'OPENAI_API_KEY', 30],
    ['openrouter', 'OPENROUTER_API_KEY', 40],
  ];
  for (const [prov, envVar, prio] of candidates) {
    const val = (process.env[envVar] || '').trim();
    if (val && keyFormatOk(prov, val) && !/^MY_|^YOUR_|PLACEHOLDER|DUMMY/i.test(val)) {
      const cfg = PROVIDERS[prov];
      envEntries.push({
        name: `${prov}-env`,
        categories: ['text', 'code', 'vision'],
        key_env: envVar,
        provider: prov,
        base_url: cfg.base_url,
        models: cfg.model ? { '*': cfg.model } : {},
        priority: prio,
        limits: {},
        pricing: {},
        source: 'file',
        tasks: ['general', 'research', 'writing', 'code', 'analysis'],
      });
    }
  }
  if (!envEntries.length) return null;
  return new KeyRouter(envEntries, path.join(stateDir, 'usage-env.json'));
}

function createRuntime() {
  const workspace = process.cwd();
  const stateDir = path.resolve(process.env.AGENT_STATE || path.join(workspace, '.agent'));
  fs.mkdirSync(stateDir, { recursive: true });
  browserState.setCacheDir(stateDir);

  const cfg = new UserConfig(stateDir);
  const secrets = new SecretStore(path.join(stateDir, 'secrets.json'));
  const permsPath = path.join(workspace, 'permissions.yaml');
  const perms = Permissions.load(fs.existsSync(permsPath) ? permsPath : null, false);
  applyPermissions(perms, cfg);

  const idcConfig = applyIdc(defaultIDCConfig(), cfg, false);
  const fileRouter = makeEnvRouter(stateDir);
  const control = new AppControl({
    cfg,
    secrets,
    perms,
    fileRouter,
    home: workspace,
    boot: { workspace, max_tasks: Number(cfg.get('max_tasks') || 4) },
    fallback: { provider: fileRouter ? 'env' : 'mock' },
  });

  const lang = (cfg.get('lang') as 'en' | 'fr') || 'en';
  const h = new Harness({
    workspace,
    stateDir,
    control,
    perms,
    idcConfig,
    lang,
    maxTasks: Number(cfg.get('max_tasks') || 4),
  });

  return { h, control };
}

function getCsrfToken(control: AppControl): string {
  return crypto.createHmac('sha256', control.csrfSecret).update('open').digest('hex').slice(0, 40);
}

function checkCsrf(req: Request, control: AppControl): boolean {
  const got = String(req.headers['x-csrf-token'] || '');
  const want = getCsrfToken(control);
  if (got.length !== want.length) return false;
  return crypto.timingSafeEqual(Buffer.from(got), Buffer.from(want));
}

function extractTaskText(data: Record<string, any>, key: string): { text?: string; error?: string } {
  let raw = data[key];
  if (raw === undefined || raw === null) {
    if (data.files) raw = '';
  }
  if (typeof raw !== 'string' || (!raw.trim() && !data.files)) {
    return { error: `'${key}' (non-empty string) is required` };
  }
  if (raw.length > MAX_TASK_CHARS) {
    return { error: `${key} too long` };
  }
  return { text: raw.trim() || 'Please look at the attached file(s).' };
}

function langArg(data: Record<string, any>): 'en' | 'fr' | null {
  const v = data.lang;
  if (typeof v !== 'string') return null;
  const two = v.slice(0, 2).toLowerCase();
  return two === 'en' || two === 'fr' ? two : null;
}

export function buildApp() {
  const { h, control } = createRuntime();
  const app = express();

  app.disable('x-powered-by');
  app.use(express.json({ limit: '64mb' }));

  // Standard security headers compatible with iframe embedding
  app.use((_req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Cache-Control', 'no-store');
    next();
  });

  // PWA assets
  app.get(
    [
      '/manifest.webmanifest',
      '/sw.js',
      '/icon.svg',
      '/favicon.png',
      '/favicon.ico',
      '/icon-192.png',
      '/icon-512.png',
      '/apple-touch-icon.png',
    ],
    (req, res) => {
      const asset = getPwaAsset(req.path);
      if (!asset) {
        res.status(404).json({ error: 'not found' });
        return;
      }
      res.setHeader('Content-Type', asset.ctype);
      res.setHeader('Cache-Control', asset.cache);
      res.send(asset.body);
    }
  );

  // HTML Pages (iframe-safe CSP without frame-ancestors 'none' or X-Frame-Options: DENY)
  app.get(['/', '/chat', '/dashboard', '/connect', '/welcome', '/help', '/dev'], (req, res) => {
    const pageName = PAGE_ROUTES[req.path] || 'chat';
    const lang = typeof req.query.lang === 'string' ? req.query.lang : null;
    const html = renderPage(pageName, lang, control.cfg.get('lang'), control.theme(), control.uiMode());
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.send(html);
  });

  app.get('/settings', (req, res) => {
    if ((req.headers.accept || '').includes('text/html')) {
      const lang = typeof req.query.lang === 'string' ? req.query.lang : null;
      const html = renderPage('settings', lang, control.cfg.get('lang'), control.theme(), control.uiMode());
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.send(html);
      return;
    }
    res.json(h.getSettings());
  });

  app.post('/settings', (req, res) => {
    try {
      res.json(h.updateSettings(req.body || {}));
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'invalid settings' });
    }
  });

  // Preview sandboxed project files
  app.get('/preview/:token/:project', (req, res) => {
    res.redirect(301, `${req.path}/`);
  });

  app.get('/preview/:token/:project/*', (req, res) => {
    const rel = String((req.params as any)[0] || '');
    try {
      const { body, ctype } = h.projects().previewFile(req.params.token, req.params.project, rel);
      res.setHeader('Content-Type', ctype);
      res.setHeader('Content-Security-Policy', PREVIEW_CSP);
      res.send(body);
    } catch (e: any) {
      if (e instanceof DevError && e.code === 'too_big') {
        res.status(413).json({ error: e.message });
      } else {
        res.status(404).setHeader('Content-Security-Policy', "sandbox; default-src 'none'").send('Not found');
      }
    }
  });

  // Auth status / login / logout (open mode when AGENT_HARNESS_TOKEN not set)
  app.get('/auth/status', (_req, res) => {
    res.json({ authenticated: true, via: 'open', remote: false, required: false, public_url: h.publicUrl });
  });
  app.post('/auth/login', (_req, res) => {
    res.json({ ok: true, required: false });
  });
  app.post('/auth/logout', (_req, res) => {
    res.json({ ok: true });
  });
  app.post('/auth/pair', (_req, res) => {
    res.status(400).json({ error: 'no token is set: nothing to pair' });
  });
  app.post('/auth/revoke-all', (_req, res) => {
    res.json({ ok: true, sessions: 0 });
  });

  // /app/* Settings & Providers UI routes
  app.get('/app/status', (_req, res) => {
    res.json({
      available: true,
      ...control.status(),
      editable: true,
      local: true,
      remote_settings: true,
      csrf: getCsrfToken(control),
    });
  });

  app.get('/app/settings', (_req, res) => {
    res.json(control.view());
  });

  app.get('/app/providers', (_req, res) => {
    res.json({ providers: control.providersView(), storage: control.secrets.backend, currency: control.router.currency });
  });

  app.get('/app/pool', (_req, res) => {
    res.json(control.poolView());
  });

  app.get('/app/mcp', (_req, res) => {
    res.json({ servers: [], presets: MCP_PRESETS, storage: control.secrets.backend });
  });

  app.get('/app/apis', (_req, res) => {
    res.json({ apis: [], storage: control.secrets.backend });
  });

  const requireCsrf = (req: Request, res: Response, next: () => void) => {
    if (!checkCsrf(req, control)) {
      res.status(403).json({ error: 'missing or invalid CSRF token (reload the page)', csrf: true, code: 'csrf' });
      return;
    }
    next();
  };

  app.post('/app/settings', requireCsrf, (req, res) => {
    try {
      res.json(control.update(req.body || {}));
    } catch (e: any) {
      res.status(400).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/setup', requireCsrf, (req, res) => {
    try {
      res.json(control.setup(req.body || {}));
    } catch (e: any) {
      res.status(400).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/providers', requireCsrf, (req, res) => {
    try {
      res.status(201).json(control.saveProvider(req.body || {}));
    } catch (e: any) {
      res.status(400).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/providers/test', requireCsrf, async (req, res) => {
    try {
      res.json(await control.testProvider(undefined, req.body || {}));
    } catch (e: any) {
      res.status(400).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/ollama/check', requireCsrf, async (req, res) => {
    const addr = typeof req.body?.address === 'string' ? req.body.address : null;
    res.json(await probeOllama(addr));
  });

  app.post('/app/providers/order', requireCsrf, (req, res) => {
    try {
      res.json({ providers: control.reorder(req.body?.ids) });
    } catch (e: any) {
      res.status(400).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/providers/bulk', requireCsrf, async (req, res) => {
    try {
      res.json(await control.bulkAdd(req.body?.text, req.body?.save !== false));
    } catch (e: any) {
      res.status(400).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/providers/propose', requireCsrf, (_req, res) => {
    res.json({ proposal: control.proposeTasks() });
  });

  app.post('/app/providers/tasks', requireCsrf, (req, res) => {
    try {
      res.json({ providers: control.setTasks(req.body?.assign) });
    } catch (e: any) {
      res.status(400).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/providers/:id', requireCsrf, (req, res) => {
    try {
      res.json(control.saveProvider(req.body || {}, String(req.params.id)));
    } catch (e: any) {
      res.status(e instanceof SettingsError ? 400 : 404).json({ error: e.message, code: e.code, params: e.params || {} });
    }
  });

  app.post('/app/providers/:id/delete', requireCsrf, (req, res) => {
    try {
      res.json(control.deleteProvider(String(req.params.id)));
    } catch (e: any) {
      res.status(404).json({ error: e.message, code: 'unknown_key' });
    }
  });

  app.post('/app/providers/:id/test', requireCsrf, async (req, res) => {
    try {
      res.json(await control.testProvider(String(req.params.id)));
    } catch (e: any) {
      res.status(404).json({ error: e.message, code: 'unknown_key' });
    }
  });

  app.post(['/app/restart', '/app/quit'], requireCsrf, (req, res) => {
    if (!control.requestStop(req.path === '/app/restart')) {
      res.status(409).json({ error: 'restart / quit is not available in this mode', code: 'no_restart' });
      return;
    }
    res.status(202).json({ ok: true, restart: req.path === '/app/restart' });
  });

  // Conversation actions
  app.get('/conv/csrf', (_req, res) => {
    res.json({ csrf: getCsrfToken(control) });
  });

  app.post('/conv/:id/pin', requireCsrf, (req, res) => {
    try {
      if (typeof req.body?.pinned !== 'boolean') {
        res.status(400).json({ error: "'pinned' must be true or false" });
        return;
      }
      res.json(h.pin(String(req.params.id), req.body.pinned).snapshot(false));
    } catch (e: any) {
      res.status(e instanceof ConvError ? e.status : 400).json({ error: e.message, code: e.code });
    }
  });

  app.post('/conv/:id/folder', requireCsrf, (req, res) => {
    const task = h.get(String(req.params.id));
    if (!task) {
      res.status(404).json({ error: 'unknown conversation', code: 'unknown' });
      return;
    }
    const rel = convFolderRel(task.id, task.dev);
    const full = path.join(h.workspace, rel);
    fs.mkdirSync(full, { recursive: true });
    res.json({ path: full, rel, opened: false });
  });

  app.post('/conv/:id/delete', requireCsrf, (req, res) => {
    try {
      const df = req.body?.delete_folder ?? false;
      if (typeof df !== 'boolean') {
        res.status(400).json({ error: "'delete_folder' must be true or false" });
        return;
      }
      res.json(h.deleteTask(String(req.params.id), df));
    } catch (e: any) {
      res.status(e instanceof ConvError ? e.status : 400).json({ error: e.message, code: e.code });
    }
  });

  // Tasks & Chat
  app.get('/tasks', (_req, res) => {
    res.json({ tasks: h.list() });
  });

  app.post('/tasks', (req, res) => {
    const data = req.body || {};
    const { text, error } = extractTaskText(data, 'task');
    if (error || !text) {
      res.status(400).json({ error: error || 'invalid task' });
      return;
    }
    if (data.idc !== undefined && data.idc !== null && typeof data.idc !== 'boolean') {
      res.status(400).json({ error: "'idc' must be true or false" });
      return;
    }
    if (data.dev !== undefined && data.dev !== null && typeof data.dev !== 'string') {
      res.status(400).json({ error: "'dev' must be a project name" });
      return;
    }
    try {
      const task = h.submit(text, data.files, { idc: data.idc, dev: data.dev, lang: langArg(data) });
      res.status(201).json(task.snapshot());
    } catch (e: any) {
      if (e instanceof DevError) res.status(404).json({ error: e.message, code: e.code });
      else if (e instanceof UploadError) res.status(e.status).json({ error: e.message });
      else if (e instanceof BusyError) res.status(409).json({ error: e.message });
      else res.status(400).json({ error: e.message });
    }
  });

  app.get('/tasks/:id', (req, res) => {
    const task = h.get(req.params.id);
    if (!task) {
      res.status(404).json({ error: 'unknown task' });
      return;
    }
    const snap = task.snapshot();
    snap.folder_path = path.join(h.workspace, snap.folder);
    res.json(snap);
  });

  app.post('/tasks/:id/messages', (req, res) => {
    const data = req.body || {};
    const { text, error } = extractTaskText(data, 'text');
    if (error || !text) {
      res.status(400).json({ error: error || 'invalid text' });
      return;
    }
    try {
      const task = h.send(req.params.id, text, data.files, langArg(data));
      res.status(202).json(task.snapshot(false));
    } catch (e: any) {
      if (e instanceof UploadError) res.status(e.status).json({ error: e.message });
      else if (e instanceof BusyError) res.status(409).json({ error: e.message });
      else res.status(404).json({ error: 'unknown task' });
    }
  });

  app.post('/tasks/:id/cancel', (req, res) => {
    const task = h.cancel(req.params.id);
    if (!task) {
      res.status(404).json({ error: 'unknown task' });
      return;
    }
    res.status(202).json(task.snapshot(false));
  });

  app.post('/tasks/:id/idc', (req, res) => {
    if (typeof req.body?.enabled !== 'boolean') {
      res.status(400).json({ error: "'enabled' (true/false) is required" });
      return;
    }
    try {
      res.json(h.setTaskIdc(req.params.id, req.body.enabled).snapshot());
    } catch (e: any) {
      if (e instanceof BusyError) res.status(409).json({ error: e.message });
      else res.status(404).json({ error: 'unknown task' });
    }
  });

  app.get('/tasks/:id/events', (req, res) => {
    const task = h.get(req.params.id);
    if (!task) {
      res.status(404).json({ error: 'unknown task' });
      return;
    }
    const since = Math.max(0, Number(req.query.since || 0) || 0);
    const { events, next } = task.eventsSince(since);
    res.json({ events, next, status: task.status });
  });

  app.get('/tasks/:id/stream', (req, res) => {
    const task = h.get(req.params.id);
    if (!task) {
      res.status(404).json({ error: 'unknown task' });
      return;
    }
    let since = 0;
    if (req.headers['last-event-id']) {
      since = (Number(req.headers['last-event-id']) || 0) + 1;
    } else if (req.query.since) {
      since = Number(req.query.since) || 0;
    }

    res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders?.();
    res.write('retry: 2000\n\n');

    const flush = () => {
      const { events, next } = task.eventsSince(since);
      for (const e of events) {
        res.write(`id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`);
      }
      since = next;
    };
    flush();

    const once = req.query.once === '1';
    if (once && TERMINAL.has(task.status)) {
      res.end();
      return;
    }

    const unsub = task.subscribe(() => {
      flush();
      if (once && TERMINAL.has(task.status)) {
        cleanup();
        res.end();
      }
    });
    const ping = setInterval(() => {
      res.write(': ping\n\n');
    }, 15_000);
    const cleanup = () => {
      unsub();
      clearInterval(ping);
    };
    req.on('close', cleanup);
  });

  app.get('/tasks/:id/graph', (req, res) => {
    const task = h.get(req.params.id);
    if (!task) {
      res.status(404).json({ error: 'unknown task' });
      return;
    }
    res.json(task.graph());
  });

  app.get('/tasks/:id/file', (req, res) => {
    const task = h.get(req.params.id);
    if (!task) {
      res.status(404).json({ error: 'unknown task' });
      return;
    }
    const rel = String(req.query.path || '');
    if (!rel || !task.graph().files.includes(rel)) {
      res.status(404).json({ error: 'not a file written in this turn' });
      return;
    }
    const root = path.resolve(h.workspace);
    const full = path.resolve(root, rel);
    if (!full.startsWith(root + path.sep) || !fs.existsSync(full) || !fs.statSync(full).isFile()) {
      res.status(404).json({ error: 'file not found' });
      return;
    }
    if (fs.statSync(full).size > FILE_VIEW_MAX) {
      res.status(413).json({ error: 'file too large to view' });
      return;
    }
    const data = fs.readFileSync(full);
    const download = req.query.download === '1';
    const safeName = path.basename(full).replace(/[^A-Za-z0-9._-]/g, '_') || 'file';
    const ext = path.extname(full).toLowerCase();
    const mimeByExt: Record<string, string> = {
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.webp': 'image/webp',
      '.gif': 'image/gif',
      '.svg': 'image/svg+xml',
    };
    const ctype = mimeByExt[ext] || (data.includes(0) ? 'application/octet-stream' : 'text/plain; charset=utf-8');
    res.setHeader('Content-Type', ctype);
    res.setHeader('Content-Disposition', `${download ? 'attachment' : 'inline'}; filename="${safeName}"`);
    res.setHeader('Content-Security-Policy', "sandbox; default-src 'none'");
    res.send(data);
  });

  app.get('/tasks/:id/export', (req, res) => {
    const task = h.get(req.params.id);
    if (!task) {
      res.status(404).json({ error: 'unknown task' });
      return;
    }
    const fmt = String(req.query.format || 'json');
    if (fmt !== 'json' && fmt !== 'md') {
      res.status(400).json({ error: 'format must be json or md' });
      return;
    }
    const lang = String(req.query.lang || 'en');
    const exp = h.exportTask(task.id, fmt, lang);
    res.setHeader('Content-Type', exp.ctype);
    res.setHeader('Content-Disposition', `attachment; filename="${exp.filename}"`);
    res.send(exp.body);
  });

  // Approvals, Rules, Stop-all
  app.get('/approvals', (req, res) => {
    res.json({ approvals: h.approvals.list(!('all' in req.query)) });
  });

  app.post('/approvals/:id', (req, res) => {
    const decision = req.body?.decision;
    const remember = req.body?.remember ?? null;
    if (decision !== 'approve' && decision !== 'deny') {
      res.status(400).json({ error: "decision must be 'approve' or 'deny'" });
      return;
    }
    if (remember !== null && (decision !== 'approve' || !(RULE_SCOPES as readonly string[]).includes(remember))) {
      res.status(400).json({ error: "remember must be 'conversation' or 'session', with approve" });
      return;
    }
    const ap0 = h.approvals.get(req.params.id);
    if (!ap0) {
      res.status(404).json({ error: 'unknown approval' });
      return;
    }
    if (remember && NEVER_REMEMBER.includes(ap0.category)) {
      res.status(400).json({ error: `'${ap0.category}' actions are always asked: they cannot be remembered` });
      return;
    }
    try {
      const { ap, rule } = h.decide(req.params.id, decision === 'approve', remember);
      res.json({ ...ap.asDict(), rule });
    } catch (e: any) {
      res.status(409).json({ error: e.message });
    }
  });

  app.get('/rules', (_req, res) => {
    res.json({ rules: h.listRules(), never_remembered: [...NEVER_REMEMBER] });
  });

  app.post('/rules/:id/revoke', (req, res) => {
    try {
      res.json(h.revokeRule(req.params.id));
    } catch {
      res.status(404).json({ error: 'unknown rule' });
    }
  });

  app.post('/stop-all', (req, res) => {
    res.json(h.stopAll(Boolean(req.body?.disable_schedules)));
  });

  // Schedules
  app.get('/schedules', (_req, res) => {
    res.json({ schedules: h.listSchedules() });
  });

  app.post('/schedules', (req, res) => {
    try {
      res.status(201).json(h.addSchedule(req.body || {}));
    } catch (e: any) {
      res.status(400).json({ error: e.message });
    }
  });

  app.post('/schedules/:id', (req, res) => {
    if (typeof req.body?.enabled !== 'boolean') {
      res.status(400).json({ error: "'enabled' (true/false) is required" });
      return;
    }
    try {
      res.json(h.updateSchedule(req.params.id, req.body.enabled));
    } catch {
      res.status(404).json({ error: 'unknown schedule' });
    }
  });

  app.post('/schedules/:id/run', (req, res) => {
    try {
      const t = h.runSchedule(req.params.id, true);
      res.status(202).json({ task: t ? t.snapshot(false) : null, skipped: t === null });
    } catch (e: any) {
      res.status(e instanceof BusyError ? 409 : 404).json({ error: e.message });
    }
  });

  app.post('/schedules/:id/delete', (req, res) => {
    try {
      res.json(h.deleteSchedule(req.params.id));
    } catch {
      res.status(404).json({ error: 'unknown schedule' });
    }
  });

  // Skills
  app.get('/skills', (_req, res) => {
    res.json({ skills: h.listSkills() });
  });

  app.post('/skills', (req, res) => {
    try {
      res.status(201).json(h.addSkill(String(req.body?.name || '').trim(), String(req.body?.content || ''), req.body?.source || 'workspace'));
    } catch (e: any) {
      res.status(400).json({ error: e.message });
    }
  });

  app.post('/skills/:name/delete', (req, res) => {
    if (h.deleteSkill(req.params.name)) {
      res.json({ ok: true });
    } else {
      res.status(404).json({ error: 'skill not found or not deletable' });
    }
  });

  // todo.md — missing capabilities backlog
  app.get('/todos', (_req, res) => {
    res.json({ items: h.todos.list(), raw: h.todos.readRaw() });
  });

  app.post('/todos', (req, res) => {
    try {
      const { item, created } = h.todos.add({
        title: String(req.body?.title || ''),
        details: req.body?.details ? String(req.body.details) : '',
        kind: req.body?.kind === 'skill' || req.body?.kind === 'both' ? req.body.kind : 'brick',
      });
      res.status(created ? 201 : 200).json({ item, created, items: h.todos.list(), raw: h.todos.readRaw() });
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'invalid todo' });
    }
  });

  app.post('/todos/:id/toggle', (req, res) => {
    try {
      const done = Boolean(req.body?.done);
      const { item } = h.todos.update(String(req.params.id || ''), { status: done ? 'done' : 'pending' });
      res.json({ item, items: h.todos.list(), raw: h.todos.readRaw() });
    } catch (e: any) {
      res.status(404).json({ error: e?.message || 'todo not found' });
    }
  });

  app.post('/todos/:id/delete', (req, res) => {
    try {
      h.todos.update(String(req.params.id || ''), { status: 'delete' });
      res.json({ ok: true, items: h.todos.list(), raw: h.todos.readRaw() });
    } catch (e: any) {
      res.status(404).json({ error: e?.message || 'todo not found' });
    }
  });

  app.post('/todos/:id/build', (req, res) => {
    try {
      const task = h.buildTodoWithAgent(String(req.params.id || ''), langArg(req.body || {}));
      res.status(201).json(task.snapshot());
    } catch (e: any) {
      res.status(e instanceof BusyError ? 409 : 404).json({ error: e?.message || 'failed to start builder agent' });
    }
  });

  // UI Bricks (self-programmed interface components)
  app.get('/bricks', (_req, res) => {
    res.json({ bricks: h.bricks.list() });
  });

  app.post('/bricks/:id/toggle', (req, res) => {
    try {
      const brick = h.bricks.setEnabled(String(req.params.id || ''), Boolean(req.body?.enabled));
      res.json({ brick, bricks: h.bricks.list() });
    } catch (e: any) {
      res.status(404).json({ error: e?.message || 'brick not found' });
    }
  });

  app.post('/bricks/:id/delete', (req, res) => {
    if (h.bricks.delete(String(req.params.id || ''))) {
      res.json({ ok: true, bricks: h.bricks.list() });
    } else {
      res.status(404).json({ error: 'brick not found' });
    }
  });

  app.get('/bricks/:id', (req, res) => {
    if (!req.path.endsWith('/')) {
      res.redirect(301, `${req.path}/`);
      return;
    }
    const file = h.bricks.serveFile(String(req.params.id || ''), '');
    if (!file) {
      res.status(404).setHeader('Content-Security-Policy', "sandbox; default-src 'none'").send('Not found');
      return;
    }
    res.setHeader('Content-Type', file.ctype);
    res.setHeader('Content-Security-Policy', BRICK_CSP);
    res.send(file.body);
  });

  app.get('/bricks/:id/*', (req, res) => {
    const rel = String((req.params as any)[0] || '');
    const file = h.bricks.serveFile(String(req.params.id || ''), rel);
    if (!file) {
      res.status(404).setHeader('Content-Security-Policy', "sandbox; default-src 'none'").send('Not found');
      return;
    }
    res.setHeader('Content-Type', file.ctype);
    res.setHeader('Content-Security-Policy', BRICK_CSP);
    res.send(file.body);
  });

  // Community Marketplace & GitHub Sync
  app.get('/community', async (_req, res) => {
    try {
      const syncRes = await h.community.sync(false);
      res.json(syncRes);
    } catch (e: any) {
      res.status(500).json({ error: e?.message || 'failed to load community' });
    }
  });

  app.post('/community/sync', async (_req, res) => {
    try {
      const syncRes = await h.community.sync(true);
      res.json(syncRes);
    } catch (e: any) {
      res.status(500).json({ error: e?.message || 'failed to sync community' });
    }
  });

  app.post('/community/import', (req, res) => {
    try {
      const result = h.community.importItem(String(req.body?.id || ''), h.bricks, h.skills);
      res.json({ ok: true, result, bricks: h.bricks.list(), skills: h.listSkills() });
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'import failed' });
    }
  });

  app.post('/bricks/:id/publish', async (req, res) => {
    try {
      const result = await h.community.publishToGitHub('brick', String(req.params.id || ''), h.bricks, h.skills, req.body?.token, req.body?.repo);
      res.json(result);
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'publish failed' });
    }
  });

  app.post('/skills/:name/publish', async (req, res) => {
    try {
      const result = await h.community.publishToGitHub('skill', String(req.params.name || ''), h.bricks, h.skills, req.body?.token, req.body?.repo);
      res.json(result);
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'publish failed' });
    }
  });

  // My Files
  app.get('/files', (_req, res) => {
    res.json({ available: true, ...h.listFiles() });
  });

  app.post('/files', (req, res) => {
    try {
      res.status(201).json({ saved: h.addFiles(req.body?.files) });
    } catch (e: any) {
      res.status(e instanceof UploadError ? e.status : 400).json({ error: e.message });
    }
  });

  app.get('/files/download', (req, res) => {
    try {
      const full = h.workspacePath(String(req.query.path || ''));
      if (fs.statSync(full).size > FILE_DOWNLOAD_MAX) {
        res.status(413).json({ error: 'file too large to download here' });
        return;
      }
      const base = path.basename(full);
      const ascii = base.replace(/[^A-Za-z0-9._-]/g, '_') || 'file';
      res.setHeader('Content-Type', 'application/octet-stream');
      res.setHeader('Content-Disposition', `attachment; filename="${ascii}"`);
      res.setHeader('Content-Security-Policy', "sandbox; default-src 'none'");
      res.send(fs.readFileSync(full));
    } catch {
      res.status(404).json({ error: 'file not found' });
    }
  });

  // Developer Mode
  app.get('/dev/projects', (_req, res) => {
    res.json({ available: true, projects: h.projects().list(), sandbox: h.sandboxOn(), python: false });
  });

  app.post('/dev/projects', (req, res) => {
    try {
      const info = h.projects().create(String(req.body?.name || ''), String(req.body?.kind || ''), String(req.body?.lang || h.lang));
      h.audit(null, { event: 'dev_create', project: info.name, kind: info.kind });
      res.status(201).json(info);
    } catch (e: any) {
      const code = e instanceof DevError ? (e.code === 'no_project' ? 404 : e.code === 'exists' ? 409 : 400) : 400;
      res.status(code).json({ error: e.message, code: e.code });
    }
  });

  app.post('/dev/test', async (req, res) => {
    try {
      const result = await h.projects().test(String(req.body?.project || ''));
      h.audit(null, { event: 'dev_test', project: req.body?.project, ok: result.ok, runner: result.runner });
      res.json(result);
    } catch (e: any) {
      res.status(e instanceof DevError && e.code === 'no_project' ? 404 : 400).json({ error: e.message, code: e.code });
    }
  });

  app.get('/dev/zip', (req, res) => {
    try {
      const { body, filename } = h.projects().zip(String(req.query.project || ''));
      h.audit(null, { event: 'dev_zip', project: filename, bytes: body.length });
      res.setHeader('Content-Type', 'application/zip');
      res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
      res.setHeader('Content-Security-Policy', "sandbox; default-src 'none'");
      res.send(body);
    } catch (e: any) {
      res.status(e instanceof DevError && (e.code === 'no_project' || e.code === 'bad_name') ? 404 : 400).json({
        error: e.message,
        code: e.code,
      });
    }
  });

  // Config, Usage, Keys, Health, Browser, Telegram
  app.get('/config', (_req, res) => {
    res.json({
      uploads: true,
      sandbox: h.sandboxOn(),
      max_upload_bytes: h.maxUploadBytes,
      max_message_bytes: h.maxMessageBytes,
    });
  });

  app.get('/usage', (_req, res) => {
    res.json(h.usage());
  });

  app.get('/keys/rate', (_req, res) => {
    res.json(h.rateView());
  });

  app.get('/keys', (_req, res) => {
    const router = h.activeRouter();
    if (!router) {
      res.json({
        mode: control.effectiveMode() === 'demo' ? 'demo' : 'single-key (.env)',
        keys: [],
        categories: {},
      });
      return;
    }
    res.json({
      mode: router === control.router ? 'settings' : 'router',
      ...router.status(),
      parallel: control.parallelLimit('text'),
    });
  });

  app.get('/health', async (req, res) => {
    const check = req.query.check === '1' || req.query.check === 'true';
    res.json(await h.health(check));
  });

  app.get('/browser/log', (_req, res) => {
    res.json(browserState.statusPayload());
  });
  app.post('/browser/navigate', async (req, res) => {
    const rawUrl = String(req.body?.url || '').trim();
    if (!rawUrl) {
      res.status(400).json({ error: 'URL requise' });
      return;
    }
    const normalized = /^https?:\/\//i.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
    try {
      await browserState.navigate({ url: normalized, source: 'user', domainDeny: h.perms.domainDeny });
      res.json(browserState.statusPayload());
    } catch (e: any) {
      const msg = e?.message || 'navigation failed';
      res.status(msg.includes('refusé') ? 403 : 400).json({ error: msg });
    }
  });
  app.post('/browser/reload', async (_req, res) => {
    try {
      await browserState.reload('user');
      res.json(browserState.statusPayload());
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'reload failed' });
    }
  });
  app.post('/browser/back', async (_req, res) => {
    await browserState.back('user');
    res.json(browserState.statusPayload());
  });
  app.post('/browser/forward', async (_req, res) => {
    await browserState.forward('user');
    res.json(browserState.statusPayload());
  });
  app.post('/browser/click', async (req, res) => {
    try {
      await browserState.click({
        source: 'user',
        x: typeof req.body?.x === 'number' ? req.body.x : undefined,
        y: typeof req.body?.y === 'number' ? req.body.y : undefined,
        selector: req.body?.selector ? String(req.body.selector) : undefined,
        text: req.body?.text ? String(req.body.text) : undefined,
        domainDeny: h.perms.domainDeny,
      });
      res.json(browserState.statusPayload());
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'click failed' });
    }
  });
  app.post('/browser/type', async (req, res) => {
    try {
      await browserState.typeText({
        source: 'user',
        text: String(req.body?.text ?? ''),
        selector: req.body?.selector ? String(req.body.selector) : undefined,
        clear: req.body?.clear === true,
        pressEnter: Boolean(req.body?.press_enter),
        domainDeny: h.perms.domainDeny,
      });
      res.json(browserState.statusPayload());
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'type failed' });
    }
  });
  app.post('/browser/key', async (req, res) => {
    try {
      await browserState.pressKey({
        source: 'user',
        key: String(req.body?.key || 'Enter'),
      });
      res.json(browserState.statusPayload());
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'key failed' });
    }
  });
  app.post('/browser/scroll', async (req, res) => {
    try {
      await browserState.scroll({
        source: 'user',
        direction: req.body?.direction || 'down',
        amount: req.body?.amount !== undefined ? Number(req.body.amount) : undefined,
      });
      res.json(browserState.statusPayload());
    } catch (e: any) {
      res.status(400).json({ error: e?.message || 'scroll failed' });
    }
  });
  app.post('/browser/control', (req, res) => {
    browserState.userControl = Boolean(req.body?.user_control);
    res.json(browserState.statusPayload());
  });
  app.get('/browser/screenshot/:id', (req, res) => {
    const buf = browserState.getShotBuffer(String(req.params.id || ''));
    if (!buf) {
      res.status(404).json({ error: 'screenshot not found' });
      return;
    }
    res.setHeader('Content-Type', 'image/png');
    res.setHeader('Content-Security-Policy', "sandbox; default-src 'none'");
    res.send(buf);
  });
  app.post('/browser/visible', (req, res) => {
    browserState.visible = Boolean(req.body?.visible);
    res.json(browserState.statusPayload());
  });
  app.post('/browser/session', async (req, res) => {
    const deleted = await browserState.clearDomainSession(String(req.body?.domain || ''));
    res.json({ deleted, ...browserState.statusPayload() });
  });

  app.post('/telegram/token', (req, res) => {
    const tok = String(req.body?.token || '').trim();
    if (tok) control.secrets.set('telegram:token', tok);
    else control.secrets.delete('telegram:token');
    res.json({ ok: true });
  });

  return app;
}

const port = Number(process.env.PORT) || 3000;
const app = buildApp();
app.listen(port, '0.0.0.0', () => {
  console.log(`Autonomous Agent running at http://0.0.0.0:${port}`);
});
