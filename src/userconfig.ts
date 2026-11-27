import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { defaultIDCConfig, validateIDCConfig } from './idc.js';
import { KeyEntry, KeyRouter, PROVIDERS, TASKS, probeKey } from './llm.js';
import { CATEGORIES, MODES, Permissions, YOLO_PROTECTED } from './permissions.js';
import { maskUi } from './redact.js';
import type { Category, IDCConfigData, Mode, ProviderRecord, ThemeMode, TraceMode, UIMode } from './types.js';

export const APP_VERSION = '0.9.22';
export const SETTINGS_FILE = 'settings.json';
export const PROVIDERS_FILE = 'providers-ui.json';
export const SECRETS_FILE = 'secrets.json';
export const USAGE_FILE = 'usage-ui.json';
export const TUNNELS = ['none', 'tailscale', 'cloudflared'] as const;
export const KNOWN_CATEGORIES = ['text', 'code', 'image', 'audio_tts', 'audio_stt', 'embeddings'] as const;
export const LIMIT_FIELDS = [
  'requests_per_minute',
  'requests_per_day',
  'tokens_per_day',
  'tokens_per_month',
  'cost_per_day',
  'cost_per_month',
  'images_per_day',
  'audio_minutes_per_day',
] as const;
export const PRICING_FIELDS = ['input_per_1m', 'output_per_1m', 'per_image', 'per_audio_minute'] as const;
export const UI_MODES: UIMode[] = ['simple', 'expert'];
export const TRACE_MODES: TraceMode[] = ['simple', 'technical'];
export const THEMES: ThemeMode[] = ['auto', 'light', 'dark'];
export const MAX_PARALLEL = 8;
export const MAX_BULK = 50;
export const MAX_SECRET = 500;

export const PRESETS: Record<string, { base_url: string; model: string; key: boolean; prefix: string; keys_url: string }> = {
  groq: {
    base_url: 'https://api.groq.com/openai/v1',
    model: 'openai/gpt-oss-20b',
    key: true,
    prefix: 'gsk_',
    keys_url: 'https://console.groq.com/keys',
  },
  openai: {
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
    key: true,
    prefix: 'sk-',
    keys_url: 'https://platform.openai.com/api-keys',
  },
  openrouter: {
    base_url: 'https://openrouter.ai/api/v1',
    model: 'openai/gpt-4o-mini',
    key: true,
    prefix: 'sk-or-',
    keys_url: 'https://openrouter.ai/keys',
  },
  ollama: {
    base_url: 'http://localhost:11434/v1',
    model: 'qwen2.5:7b',
    key: false,
    prefix: '',
    keys_url: 'https://ollama.com/download',
  },
  gemini: {
    base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    model: 'gemini-3.8-flash',
    key: true,
    prefix: 'AIza',
    keys_url: 'https://aistudio.google.com/apikey',
  },
  custom: {
    base_url: '',
    model: '',
    key: true,
    prefix: '',
    keys_url: '',
  },
};

export const DEFAULTS: Record<string, any> = {
  version: 1,
  setup_done: false,
  lang: null,
  demo: false,
  idc: null,
  permissions: {},
  approval_timeout: null,
  max_tasks: null,
  workspace: null,
  currency: '',
  remote: { enabled: false, tunnel: 'none', public_url: '' },
  ui_mode: 'simple',
  trace: 'simple',
  theme: 'auto',
  sandbox: true,
  parallel: 'auto',
};

const PROVIDER_LABELS: Record<string, string> = {
  groq: 'Groq',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
  ollama: 'Ollama',
  gemini: 'Gemini',
  custom: 'Custom',
};

const FAST_WORDS = ['mini', 'nano', 'instant', 'flash', 'haiku', 'small', 'lite', '1b', '3b', '7b', '8b', '9b', 'gemma', 'free'];
const STRONG_WORDS = ['gpt-4o', 'gpt-4.1', 'gpt-5', 'o1', 'o3', 'o4', 'claude', 'sonnet', 'opus', '70b', '72b', '120b', '235b', '405b', 'large', 'pro', 'deepseek', 'coder', 'kimi', 'grok'];
const VISION_WORDS = ['gpt-4o', 'gpt-4.1', 'gpt-5', 'vision', 'claude', 'gemini', 'llava', 'pixtral', '-vl', 'grok-4'];

export const KEY_PREFIXES: Array<[string, string | null]> = [
  ['sk-or-', 'openrouter'],
  ['gsk_', 'groq'],
  ['AIza', 'gemini'],
  ['sk-ant-', null],
  ['sk-', 'openai'],
];

export class SettingsError extends Error {
  code: string;
  params: Record<string, string>;

  constructor(code: string, message = '', params: Record<string, any> = {}) {
    super(message || code.replace(/_/g, ' '));
    this.name = 'SettingsError';
    this.code = code;
    this.params = {};
    for (const [k, v] of Object.entries(params)) {
      this.params[k] = String(v);
    }
  }
}

export function detectProvider(secret?: string | null): string | null {
  const s = (secret || '').trim();
  for (const [prefix, provider] of KEY_PREFIXES) {
    if (s.startsWith(prefix)) return provider;
  }
  return null;
}

export function keyFormatOk(provider: string, secret: string): boolean {
  if (!secret || secret.length < 8 || secret.length > MAX_SECRET || /\s/.test(secret)) {
    return false;
  }
  const prefix = PRESETS[provider]?.prefix || '';
  return !prefix || secret.startsWith(prefix);
}

function writePrivate(filePath: string, data: any): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmp = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`);
  fs.writeFileSync(tmp, JSON.stringify(data, null, 1), { mode: 0o600, encoding: 'utf-8' });
  fs.renameSync(tmp, filePath);
  try {
    fs.chmodSync(filePath, 0o600);
  } catch {
    // ignore
  }
}

function readJsonSafe<T>(filePath: string, fallback: T, backup = false): T {
  try {
    if (!fs.existsSync(filePath)) return fallback;
    const raw = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(raw) as T;
  } catch {
    if (backup && fs.existsSync(filePath)) {
      try {
        fs.renameSync(filePath, `${filePath}.broken-${Date.now()}`);
      } catch {
        // ignore
      }
    }
    return fallback;
  }
}

function cleanSettings(raw: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (k === 'lang' || k === 'workspace' || k === 'currency') {
      if (v !== null && typeof v !== 'string') continue;
    }
    out[k] = v;
  }
  return out;
}

function numVal(v: any, name: string, lo = 0, hi: number | null = null, integer = false): number {
  if (typeof v === 'boolean' || v === null || v === undefined || v === '') {
    throw new SettingsError('num_required', `${name}: a number is required`, { field: name });
  }
  const x = Number(String(v).replace(',', '.'));
  if (!Number.isFinite(x)) {
    throw new SettingsError('num_required', `${name}: a number is required`, { field: name });
  }
  if (x < lo || (hi !== null && x > hi)) {
    if (hi !== null) {
      throw new SettingsError('num_range', `${name}: must be between ${lo} and ${hi}`, { field: name, lo, hi });
    }
    throw new SettingsError('num_min', `${name}: must be >= ${lo}`, { field: name, lo });
  }
  return integer ? Math.trunc(x) : x;
}

export class SecretStore {
  filePath: string;
  private cache: Record<string, string> | null = null;

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  get backend(): string {
    return 'file';
  }

  private load(): Record<string, string> {
    if (this.cache === null) {
      const data = readJsonSafe<any>(this.filePath, {}, true);
      const sec = data && typeof data === 'object' ? data.secrets : null;
      this.cache = {};
      if (sec && typeof sec === 'object') {
        for (const [k, v] of Object.entries(sec)) {
          if (typeof v === 'string') this.cache[k] = v;
        }
      }
    }
    return this.cache;
  }

  get(sid: string): string | null {
    return this.load()[sid] ?? null;
  }

  set(sid: string, secret: string): void {
    const files = { ...this.load(), [sid]: secret };
    this.cache = files;
    writePrivate(this.filePath, { secrets: files });
  }

  delete(sid: string): void {
    const files = { ...this.load() };
    if (sid in files) {
      delete files[sid];
      this.cache = files;
      writePrivate(this.filePath, { secrets: files });
    }
  }

  has(sid: string): boolean {
    return Boolean(this.get(sid));
  }
}

export class UserConfig {
  dir: string;
  settingsPath: string;
  providersPath: string;
  data: Record<string, any>;
  providers: ProviderRecord[];

  constructor(stateDir: string) {
    this.dir = path.resolve(stateDir);
    this.settingsPath = path.join(this.dir, SETTINGS_FILE);
    this.providersPath = path.join(this.dir, PROVIDERS_FILE);
    const raw = readJsonSafe<Record<string, any>>(this.settingsPath, {}, true);
    const cleaned = raw && typeof raw === 'object' ? cleanSettings(raw) : {};
    this.data = {
      ...JSON.parse(JSON.stringify(DEFAULTS)),
      ...cleaned,
      remote: {
        ...DEFAULTS.remote,
        ...(cleaned.remote && typeof cleaned.remote === 'object' ? cleaned.remote : {}),
      },
    };
    const prov = readJsonSafe<Record<string, any>>(this.providersPath, {}, true);
    this.providers = Array.isArray(prov?.providers) ? prov.providers.filter((p) => p && typeof p === 'object') : [];
  }

  get<T = any>(key: string, fallback?: T): T {
    const v = this.data[key];
    return v === null || v === undefined ? (fallback as T) : (v as T);
  }

  save(): void {
    writePrivate(this.settingsPath, this.data);
  }

  saveProviders(): void {
    writePrivate(this.providersPath, { providers: this.providers });
  }
}

export async function probeOllama(address?: string | null, timeoutMs = 5000): Promise<Record<string, any>> {
  let base = String(address || '').trim() || 'http://localhost:11434';
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(base)) base = 'http://' + base;
  base = base.replace(/\/+$/, '');
  for (const tail of ['/v1', '/api']) {
    if (base.toLowerCase().endsWith(tail)) base = base.slice(0, -tail.length);
  }
  base = base.replace(/\/+$/, '');
  const recommended = 'qwen2.5:7b';
  const out: Record<string, any> = {
    ok: false,
    address: base,
    base_url: `${base}/v1`,
    models: [],
    recommended,
    has_recommended: false,
  };
  if (!/^https?:\/\/[^/\s]+$/i.test(base)) {
    return { ...out, code: 'bad_url' };
  }
  try {
    const r = await fetch(`${base}/api/tags`, { signal: AbortSignal.timeout(timeoutMs) });
    if (!r.ok) return { ...out, code: 'not_ollama', http_status: r.status };
    const tags = (await r.json()) as any;
    if (!tags || !Array.isArray(tags.models)) return { ...out, code: 'not_ollama' };
    const models: Array<{ name: string; size?: number; tools: boolean | null }> = [];
    for (const m of tags.models.slice(0, 30)) {
      const name = String(m?.name || m?.model || '').trim();
      if (name) models.push({ name: name.slice(0, 120), size: m?.size, tools: null });
    }
    for (const m of models.slice(0, 12)) {
      try {
        const sr = await fetch(`${base}/api/show`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: m.name }),
          signal: AbortSignal.timeout(timeoutMs),
        });
        if (sr.ok) {
          const info = (await sr.json()) as any;
          if (Array.isArray(info?.capabilities)) m.tools = info.capabilities.includes('tools');
          else if (typeof info?.template === 'string' && info.template) m.tools = info.template.includes('.Tools');
        }
      } catch {
        // ignore show errors
      }
    }
    const names = models.map((m) => m.name);
    out.models = models;
    out.has_recommended = names.includes(recommended) || names.includes(`${recommended}:latest`);
    return { ...out, ok: models.length > 0, code: models.length > 0 ? 'ok' : 'no_models' };
  } catch {
    return { ...out, code: 'unreachable' };
  }
}

export function applyPermissions(perms: Permissions, cfg: UserConfig): void {
  const saved = cfg.get<Record<string, string>>('permissions', {});
  if (!saved || typeof saved !== 'object') return;
  for (const [c, m] of Object.entries(saved)) {
    if (
      CATEGORIES.includes(c as Category) &&
      MODES.includes(m as Mode) &&
      !(YOLO_PROTECTED.includes(c as Category) && m === 'allow')
    ) {
      perms.defaults[c as Category] = m as Mode;
    }
  }
}

export function applyIdc(idcCfg: IDCConfigData, cfg: UserConfig, explicit = false): IDCConfigData {
  const saved = cfg.get<Record<string, any> | null>('idc', null);
  if (!saved || typeof saved !== 'object') return idcCfg;
  const merged = { ...idcCfg } as any;
  for (const [k, v] of Object.entries(saved)) {
    if (k in merged && !(k === 'enabled' && explicit)) {
      merged[k] = v;
    }
  }
  try {
    return validateIDCConfig(merged as IDCConfigData);
  } catch {
    return idcCfg;
  }
}

export interface HarnessLike {
  lang: 'en' | 'fr';
  maxTasks: number;
  idcConfig: IDCConfigData;
  settings: Record<string, any>;
  publicUrl: string | null;
  approvals: { timeout: number };
  updateSettings(data: Record<string, any>): Record<string, any>;
  audit(task: any, entry: Record<string, any>): void;
}

export class AppControl {
  cfg: UserConfig;
  secrets: SecretStore;
  router: KeyRouter;
  perms: Permissions | null;
  h: HarnessLike | null = null;
  fallback: Record<string, any>;
  fileRouter: KeyRouter | null;
  boot: Record<string, any>;
  tokenWhere: string | null;
  home: string;
  csrfSecret: Buffer;
  prober: (baseUrl: string, secret?: string | null) => Promise<Record<string, any>>;
  stopCb: ((restart: boolean) => void) | null = null;

  constructor(opts: {
    cfg: UserConfig;
    secrets: SecretStore;
    router?: KeyRouter;
    perms?: Permissions | null;
    fallback?: Record<string, any>;
    boot?: Record<string, any>;
    tokenWhere?: string | null;
    home?: string;
    fileRouter?: KeyRouter | null;
    prober?: (baseUrl: string, secret?: string | null) => Promise<Record<string, any>>;
  }) {
    this.cfg = opts.cfg;
    this.secrets = opts.secrets;
    this.router = opts.router || new KeyRouter([], path.join(this.cfg.dir, USAGE_FILE), this.cfg.get('currency', ''));
    this.perms = opts.perms ?? null;
    this.fallback = opts.fallback || { provider: 'mock' };
    this.boot = opts.boot || {};
    this.tokenWhere = opts.tokenWhere ?? null;
    this.home = opts.home || this.cfg.dir;
    this.fileRouter = opts.fileRouter ?? null;
    this.prober = opts.prober || ((u, s) => probeKey(u, s));
    this.csrfSecret = crypto.randomBytes(32);
    this.reloadRouter();
  }

  private needsKey(p: ProviderRecord): boolean {
    const pre = PRESETS[p.provider || 'custom'] || PRESETS.custom;
    return Boolean(pre.key) || Boolean(p.has_key);
  }

  entries(): KeyEntry[] {
    const out: KeyEntry[] = [];
    for (const p of this.cfg.providers) {
      if (p.enabled === false) continue;
      const pid = p.id;
      out.push({
        name: p.name,
        categories: Array.isArray(p.categories) && p.categories.length ? [...p.categories] : ['text'],
        provider: p.provider,
        base_url: p.base_url || null,
        models: p.model ? { '*': p.model } : {},
        priority: Number(p.priority ?? 100),
        limits: { ...(p.limits || {}) },
        pricing: { ...(p.pricing || {}) },
        secretFn: this.needsKey(p) ? () => this.secrets.get(pid) : undefined,
        source: 'ui',
        tasks: Array.isArray(p.tasks) ? p.tasks.filter((t) => (TASKS as readonly string[]).includes(t)) : [],
      });
    }
    return out;
  }

  reloadRouter(): void {
    this.router.replaceEntries(this.entries(), this.cfg.get('currency', ''));
  }

  demo(): boolean {
    return Boolean(this.cfg.get('demo'));
  }

  backendMode(category = 'text'): 'demo' | 'ui' | 'fallback' {
    if (this.demo()) return 'demo';
    if (this.router.keysFor(category).length > 0) return 'ui';
    return 'fallback';
  }

  effectiveMode(): 'demo' | 'ui' | 'fallback' {
    const m = this.backendMode('text');
    if (m === 'fallback' && !this.fileRouter && (this.fallback.provider || 'mock') === 'mock') {
      return 'demo';
    }
    return m;
  }

  firstRun(): boolean {
    return !this.cfg.get('setup_done') && this.effectiveMode() === 'demo' && !this.cfg.get('demo');
  }

  uiMode(): UIMode {
    const m = this.cfg.get<string>('ui_mode');
    return UI_MODES.includes(m as UIMode) ? (m as UIMode) : 'simple';
  }

  sandboxOn(): boolean {
    return this.uiMode() === 'simple' || this.cfg.get<boolean>('sandbox', true) !== false;
  }

  theme(): ThemeMode {
    const m = this.cfg.get<string>('theme');
    return THEMES.includes(m as ThemeMode) ? (m as ThemeMode) : 'auto';
  }

  traceMode(): TraceMode {
    const m = this.cfg.get<string>('trace');
    return TRACE_MODES.includes(m as TraceMode) ? (m as TraceMode) : 'simple';
  }

  parallelLimit(category = 'text', fallback = 3): number {
    const v = this.cfg.get('parallel', 'auto');
    if (v !== 'auto') {
      const n = Number(v);
      if (Number.isFinite(n)) return Math.max(1, Math.min(MAX_PARALLEL, Math.trunc(n)));
    }
    if (this.backendMode(category) === 'ui') {
      const n = this.router.usable(category);
      if (n > 0) return Math.min(MAX_PARALLEL, n);
    }
    return Math.max(1, fallback);
  }

  restartNeeded(): string[] {
    const out: string[] = [];
    const ws = this.cfg.get<string | null>('workspace');
    if (ws && this.boot.workspace && path.resolve(ws) !== path.resolve(String(this.boot.workspace))) {
      out.push('workspace');
    }
    const mt = this.cfg.get<number | null>('max_tasks');
    if (mt && this.boot.max_tasks && Number(mt) !== Number(this.boot.max_tasks)) {
      out.push('max_tasks');
    }
    return out;
  }

  providersView(): Array<Record<string, any>> {
    const st = new Map<string, any>();
    for (const k of this.router.status().keys || []) {
      st.set(k.name, k);
    }
    const sorted = [...this.cfg.providers].sort((a, b) => Number(a.priority ?? 100) - Number(b.priority ?? 100));
    return sorted.map((p) => {
      const secret = this.needsKey(p) ? this.secrets.get(p.id) : null;
      const s = st.get(p.name) || {};
      return {
        id: p.id,
        name: p.name,
        provider: p.provider,
        base_url: p.base_url,
        model: p.model,
        categories: p.categories,
        priority: p.priority,
        limits: p.limits,
        pricing: p.pricing,
        enabled: p.enabled,
        created: p.created,
        updated: p.updated,
        tasks: [...(p.tasks || [])],
        agents: s.agents || [],
        in_flight: s.in_flight || 0,
        key: maskUi(secret),
        has_key: Boolean(secret),
        needs_key: this.needsKey(p),
        available: p.enabled !== false ? Boolean(s.available) : false,
        cooldown_s: s.cooldown_s || 0,
        usage: s.limits || {},
        used: s.used || {},
      };
    });
  }

  status(): Record<string, any> {
    return {
      first_run: this.firstRun(),
      mode: this.effectiveMode(),
      demo: this.demo(),
      restart_needed: this.restartNeeded(),
      lang: this.cfg.get('lang'),
      version: APP_VERSION,
      ui_mode: this.uiMode(),
      trace: this.traceMode(),
      theme: this.theme(),
    };
  }

  view(): Record<string, any> {
    const h = this.h;
    const perms = this.perms;
    const idc = h ? { ...h.idcConfig, enabled: Boolean(h.settings.idc) } : defaultIDCConfig();
    return {
      version: APP_VERSION,
      lang: this.cfg.get('lang') || (h ? h.lang : 'en'),
      demo: this.demo(),
      mode: this.effectiveMode(),
      first_run: this.firstRun(),
      setup_done: Boolean(this.cfg.get('setup_done')),
      idc,
      permissions: {
        defaults: perms ? { ...perms.defaults } : {},
        tools: perms ? { ...perms.tools } : {},
        protected: [...YOLO_PROTECTED],
        categories: [...CATEGORIES],
        modes: [...MODES],
      },
      approval_timeout: h ? h.approvals.timeout : this.cfg.get('approval_timeout'),
      max_tasks: { saved: this.cfg.get('max_tasks'), active: h ? h.maxTasks : null },
      workspace: { saved: this.cfg.get('workspace'), active: this.boot.workspace || null },
      remote: {
        ...(this.cfg.get('remote') || {}),
        active: false,
        public_url: (this.cfg.get('remote') || {}).public_url || '',
        active_url: h?.publicUrl || null,
        token_from_env: this.tokenWhere === 'AGENT_HARNESS_TOKEN',
        tunnels: [...TUNNELS],
      },
      currency: this.cfg.get('currency', ''),
      ui_mode: this.uiMode(),
      trace: this.traceMode(),
      theme: this.theme(),
      parallel: {
        saved: this.cfg.get('parallel', 'auto'),
        keys: this.router.usable('text'),
        effective: this.parallelLimit('text'),
        max: MAX_PARALLEL,
      },
      tasks: [...TASKS],
      sandbox: {
        saved: Boolean(this.cfg.get('sandbox', true)),
        effective: this.sandboxOn(),
        forced: this.uiMode() === 'simple',
      },
      restart_needed: this.restartNeeded(),
      storage: this.secrets.backend,
      home: this.home,
      secrets_dir: this.cfg.dir,
      presets: { ...PRESETS },
      key_prefixes: KEY_PREFIXES.map(([a, b]) => [a, b]),
      categories: [...KNOWN_CATEGORIES],
      limit_fields: [...LIMIT_FIELDS],
      pricing_fields: [...PRICING_FIELDS],
      fallback: { provider: this.fallback.provider, file_keys: Boolean(this.fileRouter) },
      can_restart: Boolean(this.stopCb),
    };
  }

  poolView(): Record<string, any> {
    const st = this.router.status();
    const keys = (st.keys || []).map((k: any) => ({
      name: k.name,
      key: k.key,
      provider: k.provider,
      available: k.available,
      tasks: k.tasks || [],
      agents: k.agents || [],
      in_flight: k.in_flight || 0,
      cooldown_s: k.cooldown_s || 0,
      used: k.used || {},
      limits: k.limits || {},
      rate: k.rate || {},
      refused: Boolean(k.refused),
    }));
    return { keys, parallel: this.parallelLimit('text'), mode: this.effectiveMode() };
  }

  private find(pid: string): ProviderRecord {
    const hit = this.cfg.providers.find((p) => p.id === pid);
    if (!hit) throw new Error(`unknown key: ${pid}`);
    return hit;
  }

  private cleanProvider(data: Record<string, any>, old: ProviderRecord | null): { rec: Omit<ProviderRecord, 'id' | 'created' | 'updated'>; secret: string | null } {
    const provider = String(data.provider || old?.provider || 'custom').toLowerCase();
    if (!(provider in PRESETS)) {
      throw new SettingsError('bad_provider', `provider must be one of ${Object.keys(PRESETS).join(', ')}`);
    }
    const pre = PRESETS[provider];
    const name = String(data.name || old?.name || provider).trim().slice(0, 60);
    if (!/^[\w .@+-]{1,60}$/.test(name)) {
      throw new SettingsError('bad_name', 'name: letters, digits, spaces and . _ - @ + only');
    }
    if (this.cfg.providers.some((p) => p.name === name && p.id !== old?.id)) {
      throw new SettingsError('name_taken', `a key named '${name}' already exists`, { name });
    }
    let base = String(data.base_url !== undefined && data.base_url !== null ? data.base_url : old?.base_url || pre.base_url || '').trim();
    if (!base) base = pre.base_url || '';
    if (!/^https?:\/\/[^\s/]+/.test(base)) {
      throw new SettingsError('bad_url', 'base_url: an http(s) URL is required', { field: 'base_url' });
    }
    let model = String(data.model !== undefined && data.model !== null ? data.model : old?.model || pre.model || '').trim().slice(0, 200);
    if (!model) model = pre.model || '';
    if (!model) {
      throw new SettingsError('model_required', 'model: required for a custom provider');
    }
    let cats = data.categories !== undefined ? data.categories : old?.categories || ['text'];
    if (typeof cats === 'string') cats = [cats];
    if (!Array.isArray(cats) || !cats.length) {
      throw new SettingsError('no_category', 'categories: choose at least one');
    }
    const cleanCats: string[] = cats.map((c: any) => String(c).trim().toLowerCase()).filter(Boolean);
    if (!cleanCats.length || cleanCats.some((c) => !/^[a-z][a-z0-9_]{0,30}$/.test(c))) {
      throw new SettingsError('bad_category', 'categories: lowercase words (text, code, image, audio_tts...)');
    }
    cats = cleanCats;

    const limits: Record<string, number> = {};
    const rawLim = (data.limits !== undefined ? data.limits : old?.limits) || {};
    for (const [f, v] of Object.entries(rawLim)) {
      if (!(LIMIT_FIELDS as readonly string[]).includes(f)) {
        throw new SettingsError('unknown_field', `unknown limit '${f}'`, { field: f });
      }
      if (v !== null && v !== undefined && v !== '') limits[f] = numVal(v, f, 0);
    }

    const pricing: Record<string, number> = {};
    const rawPrice = (data.pricing !== undefined ? data.pricing : old?.pricing) || {};
    for (const [f, v] of Object.entries(rawPrice)) {
      if (!(PRICING_FIELDS as readonly string[]).includes(f)) {
        throw new SettingsError('unknown_field', `unknown price '${f}'`, { field: f });
      }
      if (v !== null && v !== undefined && v !== '') pricing[f] = numVal(v, f, 0);
    }
    if (Object.keys(limits).some((f) => f.startsWith('cost_')) && !Object.values(pricing).some(Boolean)) {
      throw new SettingsError('cost_needs_price', 'cost limits need a price (per 1M tokens)');
    }

    const prio = numVal(data.priority ?? old?.priority ?? (this.cfg.providers.length + 1) * 10, 'priority', 0, 100000, true);

    let secret: string | null = null;
    if (data.key !== undefined && data.key !== null) {
      if (typeof data.key !== 'string') throw new SettingsError('bad_key', 'key must be text');
      const s = data.key.trim();
      if (s && (s.length > MAX_SECRET || /\s/.test(s))) {
        throw new SettingsError('key_spaces', 'key: no spaces, at most 500 characters');
      }
      secret = s || null;
    }
    if (pre.key && !secret && !(old && this.secrets.has(old.id))) {
      throw new SettingsError('key_required', 'key: required for this provider');
    }

    let tasks = data.tasks !== undefined ? data.tasks : old?.tasks || [];
    if (typeof tasks === 'string') tasks = [tasks];
    if (!Array.isArray(tasks) || tasks.some((t) => !(TASKS as readonly string[]).includes(t))) {
      throw new SettingsError('bad_task', `tasks: choose among ${TASKS.join(', ')}`, { field: 'tasks' });
    }
    tasks = (TASKS as readonly string[]).filter((t) => tasks.includes(t));

    const enabled = data.enabled !== undefined ? Boolean(data.enabled) : old ? old.enabled !== false : true;
    return {
      rec: { name, provider, base_url: base, model, categories: cats, priority: prio, limits, pricing, tasks, enabled },
      secret,
    };
  }

  saveProvider(data: Record<string, any>, pid?: string): Record<string, any> {
    const old = pid ? this.find(pid) : null;
    const { rec, secret } = this.cleanProvider(data, old);
    const now = new Date().toISOString();
    let target: ProviderRecord;
    if (!old) {
      target = { ...rec, id: crypto.randomBytes(6).toString('hex'), created: now, updated: now };
      this.cfg.providers.push(target);
    } else {
      Object.assign(old, rec, { updated: now });
      target = old;
    }
    if (secret) this.secrets.set(target.id, secret);
    target.has_key = this.secrets.has(target.id);
    this.cfg.providers.sort((a, b) => Number(a.priority ?? 100) - Number(b.priority ?? 100));
    this.cfg.saveProviders();
    if (this.cfg.get('demo') && target.enabled) {
      this.cfg.data.demo = false;
      this.cfg.save();
    }
    this.reloadRouter();
    this.audit('settings_key_saved', {
      key: target.name,
      provider: target.provider,
      categories: target.categories,
      new: !old,
      key_changed: Boolean(secret),
    });
    return this.providersView().find((v) => v.id === target.id)!;
  }

  deleteProvider(pid: string): Record<string, any> {
    const p = this.find(pid);
    this.cfg.providers = this.cfg.providers.filter((x) => x.id !== pid);
    this.secrets.delete(pid);
    this.cfg.saveProviders();
    this.reloadRouter();
    this.audit('settings_key_deleted', { key: p.name });
    return { ok: true, id: pid };
  }

  reorder(ids: any): Array<Record<string, any>> {
    const known = this.cfg.providers.map((p) => p.id).sort();
    if (!Array.isArray(ids) || [...ids.map(String)].sort().join(',') !== known.join(',')) {
      throw new SettingsError('bad_order', 'ids: every key id, once, in the new order');
    }
    ids.forEach((pid, i) => {
      this.find(String(pid)).priority = (i + 1) * 10;
    });
    this.cfg.providers.sort((a, b) => Number(a.priority ?? 100) - Number(b.priority ?? 100));
    this.cfg.saveProviders();
    this.reloadRouter();
    return this.providersView();
  }

  async testProvider(pid?: string, data?: Record<string, any>): Promise<Record<string, any>> {
    let provider: string;
    let base: string | null = null;
    let secret: string | null = null;
    if (pid) {
      const p = this.find(pid);
      provider = p.provider || 'custom';
      base = p.base_url || null;
      secret = this.needsKey(p) ? this.secrets.get(pid) : null;
    } else {
      const d = data || {};
      provider = String(d.provider || 'custom').toLowerCase();
      if (!(provider in PRESETS)) {
        throw new SettingsError('bad_provider', `provider must be one of ${Object.keys(PRESETS).join(', ')}`);
      }
      base = String(d.base_url || PRESETS[provider].base_url || '');
      secret = String(d.key || '').trim() || null;
      if (!secret && d.id) secret = this.secrets.get(String(d.id));
    }
    const need = PRESETS[provider]?.key ?? true;
    if (need && !secret) return { ok: false, code: 'missing' };
    if (secret && !keyFormatOk(provider, secret)) {
      const other = detectProvider(secret);
      if (other && other !== provider) return { ok: false, code: 'wrong_provider', detected: other };
      return { ok: false, code: 'format' };
    }
    if ((process.env.AGENT_KEY_TEST || '').toLowerCase() === 'offline') {
      return { ok: true, code: 'offline' };
    }
    if (!base || !/^https?:\/\//i.test(base)) return { ok: false, code: 'unreachable' };
    const res = await this.prober(base, secret);
    return {
      ok: res.ok,
      code: res.code,
      ...(res.http_status !== undefined ? { http_status: res.http_status } : {}),
      ...(res.models !== undefined ? { models: res.models } : {}),
      ...(res.ms !== undefined ? { ms: res.ms } : {}),
      ...(res.detail !== undefined ? { detail: res.detail } : {}),
    };
  }

  static parseBulk(text: any): Array<Record<string, any>> {
    if (typeof text !== 'string') throw new SettingsError('bad_key', 'keys: text expected');
    const out: Array<Record<string, any>> = [];
    const seen = new Set<string>();
    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      let line = lines[i].replace(/^\ufeff/, '').trim();
      if (!line || line.startsWith('#')) continue;
      if (out.length >= MAX_BULK) {
        out.push({ line: i + 1, label: '', key: '', provider: null, code: 'too_many' });
        break;
      }
      if (line.toLowerCase().startsWith('export ')) line = line.slice(7).trim();
      const m = /^(.*?)[\s:=]*['"]?([^\s'":=]{8,})['"]?[,;]?$/.exec(line);
      const key = m ? m[2] : '';
      let label = m ? m[1].trim().replace(/^[:=\-–—'"]+|[:=\-–—'"]+$/g, '').slice(0, 60) : '';
      label = label.replace(/[^\w .@+-]/g, '').trim().slice(0, 60);
      let prov = detectProvider(key);
      const low = label.toLowerCase();
      const hinted = ['openrouter', 'groq', 'openai', 'ollama'].find((p) => low.includes(p)) || null;
      if (prov === null || (hinted === 'openrouter' && prov === 'openai')) {
        if (hinted && ['openrouter', 'groq', 'openai'].includes(hinted)) prov = hinted;
      }
      const row: Record<string, any> = { line: i + 1, label, key, provider: prov };
      if (!key || key.length > MAX_SECRET) row.code = 'format';
      else if (prov === null) row.code = 'unknown_provider';
      else if (seen.has(key)) row.code = 'duplicate';
      seen.add(key);
      out.push(row);
    }
    return out;
  }

  private uniqueName(label: string, provider: string, taken: Set<string>): string {
    let base = label && /^[\w .@+-]{1,60}$/.test(label) ? label : PROVIDER_LABELS[provider] || provider;
    if (/^(export )?[A-Z0-9_]*(API_?KEY|TOKEN|KEY)[A-Z0-9_]*$/i.test(base || '')) {
      base = PROVIDER_LABELS[provider] || provider;
    }
    let name = base.slice(0, 60);
    let i = 2;
    while (taken.has(name)) {
      name = `${base.slice(0, 55)} ${i}`;
      i += 1;
    }
    taken.add(name);
    return name;
  }

  async bulkAdd(text: any, save = true): Promise<Record<string, any>> {
    const rows = AppControl.parseBulk(text);
    if (!rows.length) throw new SettingsError('nothing', 'no key found: paste one key per line');
    const existing = new Set<string>();
    for (const p of this.cfg.providers) {
      const sec = this.needsKey(p) ? this.secrets.get(p.id) : null;
      if (sec) existing.add(sec);
    }
    const todo: Array<Record<string, any>> = [];
    for (const r of rows) {
      if (!r.code && existing.has(r.key)) r.code = 'already_saved';
      if (!r.code && !keyFormatOk(r.provider, r.key)) r.code = 'format';
      if (!r.code) todo.push(r);
    }
    await Promise.all(
      todo.map(async (r) => {
        try {
          const res = await this.testProvider(undefined, { provider: r.provider, key: r.key });
          r.ok = Boolean(res.ok);
          r.code = res.code || (r.ok ? 'ok' : 'error');
          if (res.http_status) r.http_status = res.http_status;
        } catch (e: any) {
          r.ok = false;
          r.code = 'error';
        }
      })
    );
    const saved: string[] = [];
    if (save) {
      const taken = new Set(this.cfg.providers.map((p) => p.name));
      for (const r of rows) {
        if (!r.ok) continue;
        const name = this.uniqueName(r.label, r.provider, taken);
        try {
          const v = this.saveProvider({ provider: r.provider, key: r.key, name });
          r.id = v.id;
          r.name = v.name;
          saved.push(v.id);
        } catch (e: any) {
          r.ok = false;
          r.code = e?.code || 'error';
        }
      }
    }
    const out = rows.map((r) => ({
      line: r.line,
      label: r.label || '',
      provider: r.provider,
      key: r.key ? maskUi(r.key) : '',
      ok: Boolean(r.ok),
      code: r.code || 'error',
      id: r.id,
      name: r.name,
      ...(r.http_status ? { http_status: r.http_status } : {}),
    }));
    const failed = out.filter((r) => !r.ok).length;
    this.audit('settings_keys_bulk', { lines: rows.length, saved: saved.length, failed });
    return {
      results: out,
      saved: saved.length,
      failed,
      proposal: saved.length ? this.proposeTasks() : [],
      providers: this.providersView(),
      parallel: this.parallelLimit('text'),
    };
  }

  static keyClass(provider?: string | null, model?: string | null): [number, boolean] {
    const m = (model || '').toLowerCase();
    if ((provider || '') === 'gemini' || m.startsWith('gemini')) {
      return [m.includes('lite') ? 0 : 2, true];
    }
    const free = provider === 'groq' || provider === 'ollama' || m.includes(':free');
    const vision = !free && VISION_WORDS.some((w) => m.includes(w));
    if (free) return [0, vision];
    const tail = m.split(/[/:]/).pop() || '';
    const fast = FAST_WORDS.some((w) => tail.includes(w));
    const strong = STRONG_WORDS.some((w) => m.includes(w));
    return [strong && !fast ? 2 : 1, vision];
  }

  proposeTasks(): Array<Record<string, any>> {
    const provs = this.cfg.providers.filter((p) => p.enabled !== false);
    if (!provs.length) return [];
    const cls: Record<string, [number, boolean]> = {};
    for (const p of provs) cls[p.id] = AppControl.keyClass(p.provider, p.model);
    const strengths = Object.values(cls).map((c) => c[0]);
    const lo = Math.min(...strengths);
    const hi = Math.max(...strengths);
    const plan: Record<string, string[]> = {};
    const why: Record<string, string> = {};
    for (const p of provs) plan[p.id] = [];

    if (lo !== hi) {
      for (const p of provs) {
        const s = cls[p.id][0];
        if (s === lo) {
          plan[p.id].push('research', 'analysis');
          why[p.id] = s === 0 ? 'fast_free' : 'fast';
        } else if (s === hi) {
          plan[p.id].push('writing', 'code', 'general');
          why[p.id] = 'strong';
        } else {
          plan[p.id].push('analysis', 'general');
          why[p.id] = 'middle';
        }
      }
    } else {
      const groups = ['research', 'writing', 'code', 'analysis'];
      const n = provs.length;
      groups.forEach((g, j) => {
        plan[provs[j % n].id].push(g);
      });
      provs.forEach((p, i) => {
        if (i >= groups.length || i === 0) plan[p.id].push('general');
        why[p.id] = n === 1 ? 'only' : 'spread';
      });
    }
    for (const p of provs) {
      if (cls[p.id][1]) plan[p.id].push('vision');
    }
    return provs.map((p) => {
      const secret = this.needsKey(p) ? this.secrets.get(p.id) : null;
      return {
        id: p.id,
        name: p.name,
        provider: p.provider,
        model: p.model,
        key: maskUi(secret),
        current: [...(p.tasks || [])],
        tasks: (TASKS as readonly string[]).filter((t) => plan[p.id].includes(t)),
        why: why[p.id] || 'spread',
        strength: cls[p.id][0],
      };
    });
  }

  setTasks(assign: any): Array<Record<string, any>> {
    if (!assign || typeof assign !== 'object' || Array.isArray(assign) || !Object.keys(assign).length) {
      throw new SettingsError('bad_object', 'assign: {key id: [task types]}', { field: 'assign' });
    }
    const clean: Record<string, { tasks: string[]; model: string | null }> = {};
    for (const [pid, rawVal] of Object.entries(assign)) {
      this.find(pid);
      let model: string | null = null;
      let v: any = rawVal;
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        model = v.model ?? null;
        v = v.tasks ?? [];
      }
      if (typeof v === 'string') v = [v];
      if (!Array.isArray(v) || v.some((t) => !(TASKS as readonly string[]).includes(t))) {
        throw new SettingsError('bad_task', `tasks: choose among ${TASKS.join(', ')}`, { field: 'tasks' });
      }
      if (model !== null) {
        model = String(model).trim().slice(0, 200);
        if (model && /\s/.test(model)) {
          throw new SettingsError('bad_model', 'model: no spaces', { field: 'model' });
        }
      }
      clean[pid] = {
        tasks: (TASKS as readonly string[]).filter((t) => v.includes(t)),
        model: model || null,
      };
    }
    const now = new Date().toISOString();
    for (const [pid, { tasks, model }] of Object.entries(clean)) {
      const p = this.find(pid);
      p.tasks = tasks;
      if (model) p.model = model;
      p.updated = now;
    }
    this.cfg.saveProviders();
    this.reloadRouter();
    return this.providersView();
  }

  update(data: Record<string, any>): Record<string, any> {
    if (!data || typeof data !== 'object' || !Object.keys(data).length) {
      throw new SettingsError('nothing', 'nothing to change');
    }
    const h = this.h;
    const cfg = this.cfg;
    const changes: Record<string, any> = {};

    if ('lang' in data) {
      if (data.lang !== 'en' && data.lang !== 'fr') {
        throw new SettingsError('bad_choice', 'lang must be en or fr', { field: 'lang' });
      }
      changes.lang = data.lang;
    }
    if ('demo' in data) {
      if (typeof data.demo !== 'boolean') {
        throw new SettingsError('bad_bool', 'demo must be true or false', { field: 'demo' });
      }
      changes.demo = data.demo;
    }
    for (const [k, allowed] of [
      ['ui_mode', UI_MODES],
      ['trace', TRACE_MODES],
      ['theme', THEMES],
    ] as const) {
      if (k in data) {
        if (!(allowed as readonly string[]).includes(data[k])) {
          throw new SettingsError('bad_choice', `${k} must be one of ${allowed.join(', ')}`, { field: k });
        }
        changes[k] = data[k];
      }
    }
    if ('sandbox' in data) {
      if (typeof data.sandbox !== 'boolean') {
        throw new SettingsError('bad_bool', 'sandbox must be true or false', { field: 'sandbox' });
      }
      changes.sandbox = data.sandbox;
    }
    if ('parallel' in data) {
      const v = data.parallel;
      changes.parallel = v === 'auto' || v === null || v === '' ? 'auto' : numVal(v, 'parallel', 1, MAX_PARALLEL, true);
    }
    if ('currency' in data) {
      const cur = String(data.currency || '').trim().slice(0, 8);
      if (cur && !/^[A-Za-z€$£¥ ]{1,8}$/.test(cur)) {
        throw new SettingsError('bad_currency', 'currency: up to 8 letters');
      }
      changes.currency = cur;
    }
    if ('approval_timeout' in data) {
      changes.approval_timeout = numVal(data.approval_timeout, 'approval_timeout', 10, 3600, true);
    }
    if ('max_tasks' in data) {
      changes.max_tasks = numVal(data.max_tasks, 'max_tasks', 1, 16, true);
    }
    if ('workspace' in data) {
      let ws = String(data.workspace || '').trim();
      if (ws) {
        if (!path.isAbsolute(ws)) {
          throw new SettingsError('ws_absolute', 'workspace: a full folder path is required');
        }
        ws = path.resolve(ws);
        if (ws === '/') {
          throw new SettingsError('ws_too_wide', 'workspace: choose a dedicated folder');
        }
      }
      changes.workspace = ws || null;
    }
    if ('permissions' in data) {
      const pd = data.permissions;
      if (!pd || typeof pd !== 'object' || Array.isArray(pd)) {
        throw new SettingsError('bad_object', 'permissions: {category: mode}', { field: 'permissions' });
      }
      for (const [c, m] of Object.entries(pd)) {
        if (!CATEGORIES.includes(c as Category)) {
          throw new SettingsError('unknown_field', `permissions: unknown category '${c}'`, { field: c });
        }
        if (!MODES.includes(m as Mode)) {
          throw new SettingsError('bad_choice', `permissions: invalid mode '${m}'`, { field: c });
        }
        if (YOLO_PROTECTED.includes(c as Category) && m === 'allow') {
          throw new SettingsError('perm_protected', `permissions: '${c}' can never be approved automatically (ask or deny only)`, { field: c });
        }
      }
      changes.permissions = { ...pd };
    }
    if ('idc' in data) {
      const d = data.idc;
      if (!d || typeof d !== 'object' || Array.isArray(d)) {
        throw new SettingsError('bad_object', 'idc: settings object expected', { field: 'idc' });
      }
      const base = h ? { ...h.idcConfig } : defaultIDCConfig();
      const updated = { ...base } as any;
      for (const [k, v] of Object.entries(d)) {
        if (!(k in base)) {
          throw new SettingsError('unknown_field', `idc: unknown setting '${k}'`, { field: k });
        }
        if (typeof (base as any)[k] === 'boolean') {
          if (typeof v !== 'boolean') throw new SettingsError('bad_bool', `idc: ${k} must be true or false`, { field: k });
          updated[k] = v;
        } else {
          updated[k] = numVal(v, `idc.${k}`, 0, 1e9, k === 'stall_limit');
        }
      }
      changes.idc = validateIDCConfig(updated as IDCConfigData);
    }
    if ('remote' in data) {
      const r = data.remote;
      if (!r || typeof r !== 'object' || Array.isArray(r)) {
        throw new SettingsError('bad_object', 'remote: settings object expected', { field: 'remote' });
      }
      const cur = { ...(cfg.get('remote') || {}) };
      if ('enabled' in r) {
        if (typeof r.enabled !== 'boolean') {
          throw new SettingsError('bad_bool', 'remote.enabled must be true or false', { field: 'remote.enabled' });
        }
        cur.enabled = r.enabled;
      }
      if ('tunnel' in r) {
        if (!(TUNNELS as readonly string[]).includes(r.tunnel)) {
          throw new SettingsError('bad_choice', `remote.tunnel must be one of ${TUNNELS.join(', ')}`, { field: 'remote.tunnel' });
        }
        cur.tunnel = r.tunnel;
      }
      if ('public_url' in r) {
        const u = String(r.public_url || '').trim();
        if (u && !/^https?:\/\/[^\s/]+/.test(u)) {
          throw new SettingsError('bad_url', 'remote.public_url: an http(s) address', { field: 'remote.public_url' });
        }
        cur.public_url = u;
      }
      changes.remote = cur;
    }

    for (const [k, v] of Object.entries(changes)) {
      if (k === 'idc') {
        cfg.data.idc = v;
        if (h) {
          h.idcConfig = v;
          h.updateSettings({ idc: Boolean(v.enabled) });
        }
      } else if (k === 'permissions') {
        const merged = { ...(cfg.get('permissions') || {}), ...v };
        cfg.data.permissions = merged;
        if (this.perms) Object.assign(this.perms.defaults, v);
      } else {
        cfg.data[k] = v;
      }
      if (k === 'lang' && h) h.lang = v;
      if (k === 'approval_timeout' && h) h.approvals.timeout = Number(v);
      if (k === 'currency') this.router.currency = v;
    }
    cfg.save();
    this.audit('settings_changed', { fields: Object.keys(changes).sort() });
    return this.view();
  }

  setup(data: Record<string, any>): Record<string, any> {
    const upd: Record<string, any> = {};
    if ('lang' in data) upd.lang = data.lang;
    if ('demo' in data) upd.demo = data.demo;
    if (Object.keys(upd).length) this.update(upd);
    if (data.done) {
      this.cfg.data.setup_done = true;
      this.cfg.save();
    }
    return this.status();
  }

  requestStop(restart: boolean): boolean {
    if (!this.stopCb) return false;
    this.audit(restart ? 'app_restart' : 'app_quit', {});
    const cb = this.stopCb;
    setTimeout(() => cb(restart), 300);
    return true;
  }

  private audit(event: string, extra: Record<string, any>): void {
    if (this.h) {
      try {
        this.h.audit(null, { event, agent: 'user', ...extra });
      } catch {
        // ignore
      }
    }
  }
}
