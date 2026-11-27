import fs from 'node:fs';
import path from 'node:path';
import { maskSecret, redactText } from './redact.js';
import { t } from './ui/render.js';
import type { ChatMessage } from './types.js';

export const USER_AGENT = 'autonomous-agent/0.9.22';

export const PROVIDERS: Record<string, { base_url: string | null; key_env: string | null; model: string | null }> = {
  groq: { base_url: 'https://api.groq.com/openai/v1', key_env: 'GROQ_API_KEY', model: 'openai/gpt-oss-20b' },
  openai: { base_url: 'https://api.openai.com/v1', key_env: 'OPENAI_API_KEY', model: 'gpt-4o-mini' },
  openrouter: { base_url: 'https://openrouter.ai/api/v1', key_env: 'OPENROUTER_API_KEY', model: 'openai/gpt-4o-mini' },
  ollama: { base_url: 'http://localhost:11434/v1', key_env: null, model: 'qwen2.5:7b' },
  gemini: { base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/', key_env: 'GEMINI_API_KEY', model: 'gemini-3.8-flash' },
  custom: { base_url: null, key_env: 'AGENT_API_KEY', model: null },
};

export const TRANSIENT = new Set([408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529]);
export const KEY_ERRORS = new Set([401, 402, 403]);
export const FINAL_CODES = new Set(['tls', 'too_large', 'daily_limit', 'key_invalid', 'model_unavailable', 'no_tools']);
export const MAX_WAIT = 60;
export const MAX_WAITS = 6;
export const MAX_WAIT_TOTAL = 300;
export const NET_RETRIES = 2;
export const NET_COOLDOWN = 5;

const TOOL_FAIL_RE = /tool_use_failed|failed to call a function|tool call validation failed|tool choice is none, but model called a tool|invalid tool call|failed to parse tool call|attempted to call tool/i;
const TOO_LARGE_RE = /request too large|reduce your message size|context_length_exceeded|maximum context length|prompt is too long|too many tokens/i;
const DAILY_RE = /per day|\((?:TPD|RPD|ASPD)\)|daily/i;
const MODEL_RE = /model_not_found|model_decommissioned|decommissioned|does not exist|not supported|no longer (?:available|supported)|unknown model|invalid model/i;
const NO_TOOLS_RE = /does not support tools/i;
const LIMIT_RE = /Limit\s+(\d+)/i;
const REQUESTED_RE = /Requested\s+(\d+)/i;
const AGAIN_RE = /try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)/i;

export class LLMError extends Error {
  status?: number;
  retry_after?: number;
  ratelimit?: Record<string, string>;
  code?: string;
  host?: string;
  model?: string;
  key_mask?: string;

  constructor(
    message: string,
    opts: {
      status?: number;
      retry_after?: number;
      ratelimit?: Record<string, string>;
      code?: string;
      host?: string;
      model?: string;
      key_mask?: string;
    } = {}
  ) {
    super(message);
    this.name = 'LLMError';
    Object.assign(this, opts);
  }
}

export function isToolFormatError(e: unknown): boolean {
  if (!(e instanceof LLMError)) return false;
  return e.code === 'tool_use_failed' || (e.status === 400 && TOOL_FAIL_RE.test(e.message));
}

export function parseDuration(v: any): number | undefined {
  if (v == null) return undefined;
  const text = String(v).trim().toLowerCase();
  if (/^\d+(?:\.\d+)?$/.test(text)) return Math.max(0, Number(text));
  const matches = [...text.matchAll(/(\d+(?:\.\d+)?)(ms|h|m|s)/g)];
  if (!matches.length) return undefined;
  const mult: Record<string, number> = { h: 3600, m: 60, s: 1, ms: 0.001 };
  return Math.round(matches.reduce((sum, m) => sum + Number(m[1]) * mult[m[2]], 0) * 1000) / 1000;
}

export function classifyHttp(status: number, detail: string): string | undefined {
  if ((status === 400 || status === 500) && NO_TOOLS_RE.test(detail)) return 'no_tools';
  if (status === 400 && TOOL_FAIL_RE.test(detail)) return 'tool_use_failed';
  if (status === 413 || ((status === 400 || status === 429) && TOO_LARGE_RE.test(detail))) return 'too_large';
  if (status === 429) {
    const lim = LIMIT_RE.exec(detail);
    const req = REQUESTED_RE.exec(detail);
    if (lim && req && Number(req[1]) > Number(lim[1]) && !DAILY_RE.test(detail)) return 'too_large';
    return DAILY_RE.test(detail) ? 'daily_limit' : 'rate_limit';
  }
  if (status === 401 || status === 402 || status === 403) return 'key_invalid';
  if (status === 404 || ((status === 400 || status === 422) && MODEL_RE.test(detail) && detail.toLowerCase().includes('model'))) {
    return 'model_unavailable';
  }
  if (status >= 500) return 'server';
  return undefined;
}

export function friendlyError(e: unknown, lang = 'en', keyMask?: string): string {
  const err = e as Partial<LLMError> & { message?: string };
  const code = err?.code;
  const km = keyMask || err?.key_mask || '?';
  if (code === 'tls') return t(lang, 'err.tls');
  if (code === 'network' && String(err?.message).includes(':11434')) {
    return t(lang, 'err.ollamaDown', { host: err?.host || 'localhost' });
  }
  if (code === 'network') return t(lang, 'err.network', { host: err?.host || '?' });
  if (code === 'no_tools') return t(lang, 'err.noTools', { model: err?.model || '?' });
  if (code === 'too_large') {
    const m = LIMIT_RE.exec(String(err?.message || ''));
    return t(lang, 'err.tooLarge', { limit: m ? m[1] : '?' });
  }
  if (code === 'daily_limit') {
    if (err?.retry_after) {
      const dt = new Date(Date.now() + err.retry_after * 1000);
      const at = `${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
      return t(lang, 'err.daily', { mask: km, at });
    }
    return t(lang, 'err.dailyNoTime', { mask: km });
  }
  if (code === 'key_invalid' || code === 'keys_refused') return t(lang, 'err.keyInvalid');
  if (code === 'model_unavailable') return t(lang, 'err.model', { model: err?.model || '?' });
  if (code === 'keys_exhausted' || code === 'rate_limit') {
    const detail = String(err?.message || '').trim();
    return t(lang, 'err.busy') + (code === 'keys_exhausted' && detail ? `\n(${detail.slice(0, 400)})` : '');
  }
  return t(lang, 'err.other', { detail: String(err?.message || err).slice(0, 300) });
}

export interface LLMReply {
  message: ChatMessage;
  prompt_tokens: number;
  completion_tokens: number;
  cost: number;
  key?: string;
  key_mask?: string;
  key_task?: string;
  key_match?: boolean;
  ratelimit?: Record<string, string>;
}

export interface ChatCallerContext {
  holder?: string;
  task?: string;
  label?: string;
  signal?: AbortSignal;
  notify?: (kind: string, data: Record<string, any>) => void;
  temperature?: number;
  max_tokens?: number;
}

export interface LLMBackend {
  model: string;
  chat(messages: ChatMessage[], tools?: any[], caller?: ChatCallerContext): Promise<LLMReply>;
  releaseHolder?(holder: string): void;
}

export async function probeKey(baseUrl: string, secret?: string | null, timeoutMs = 8000): Promise<Record<string, any>> {
  const url = baseUrl.replace(/\/+$/, '') + '/models';
  const t0 = Date.now();
  const headers: Record<string, string> = { 'User-Agent': USER_AGENT, Accept: 'application/json' };
  if (secret) headers.Authorization = `Bearer ${secret}`;
  try {
    const r = await fetch(url, { method: 'GET', headers, signal: AbortSignal.timeout(timeoutMs) });
    const ms = Date.now() - t0;
    if (!r.ok) {
      const code = r.status === 401 || r.status === 403 ? 'invalid' : r.status === 404 ? 'no_models' : r.status === 429 ? 'rate_limited' : 'error';
      return { ok: code === 'no_models' || code === 'rate_limited', code, http_status: r.status, ms };
    }
    let models: number | undefined;
    try {
      const body = (await r.json()) as any;
      if (Array.isArray(body?.data)) models = body.data.length;
    } catch {
      // ignore
    }
    return { ok: true, code: 'ok', http_status: r.status, models, ms };
  } catch (e: any) {
    return { ok: false, code: 'unreachable', detail: e?.name || 'Error' };
  }
}

export class OpenAICompatible implements LLMBackend {
  baseUrl: string;
  model: string;
  private apiKey?: string | null;
  timeoutMs: number;
  temperature: number;
  retries: number;
  maxTokens?: number;

  constructor(
    baseUrl: string,
    model: string,
    apiKey?: string | null,
    opts: { timeoutMs?: number; temperature?: number; retries?: number; maxTokens?: number } = {}
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.model = model;
    this.apiKey = apiKey;
    this.timeoutMs = opts.timeoutMs ?? 120_000;
    this.temperature = opts.temperature ?? 0.2;
    this.retries = opts.retries ?? 2;
    this.maxTokens = opts.maxTokens;
  }

  async chat(messages: ChatMessage[], tools?: any[], caller?: ChatCallerContext): Promise<LLMReply> {
    const payload: Record<string, any> = {
      model: this.model,
      messages,
      temperature: caller?.temperature ?? this.temperature,
    };
    const mt = [this.maxTokens, caller?.max_tokens].filter((x): x is number => typeof x === 'number' && x > 0);
    if (mt.length) payload.max_tokens = Math.floor(Math.min(...mt));
    if (tools && tools.length) {
      payload.tools = tools;
      payload.tool_choice = 'auto';
    }
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'User-Agent': USER_AGENT,
      Accept: 'application/json',
    };
    if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`;

    let lastErr: LLMError | null = null;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      let wait = 2 ** attempt;
      try {
        const signals = [AbortSignal.timeout(this.timeoutMs)];
        if (caller?.signal) signals.push(caller.signal);
        const r = await fetch(this.baseUrl + '/chat/completions', {
          method: 'POST',
          headers,
          body: JSON.stringify(payload),
          signal: AbortSignal.any(signals),
        });
        const rl: Record<string, string> = {};
        r.headers.forEach((v, k) => {
          const lk = k.toLowerCase();
          if (lk.startsWith('x-ratelimit') || lk.startsWith('retry-after')) rl[lk] = v;
        });
        if (!r.ok) {
          const detail = (await r.text()).slice(0, 800);
          let retryAfter = r.headers.get('retry-after') ? Number(r.headers.get('retry-after')) : undefined;
          if (Number.isNaN(retryAfter)) retryAfter = undefined;
          const code = classifyHttp(r.status, detail);
          if (code === 'daily_limit' || (retryAfter === undefined && r.status === 429)) {
            const m = AGAIN_RE.exec(detail);
            if (m) retryAfter = Math.max(retryAfter || 0, parseDuration(m[1]) || 0);
          }
          let host = this.baseUrl;
          try { host = new URL(this.baseUrl).hostname; } catch { /* ignore */ }
          lastErr = new LLMError(
            `HTTP ${r.status} from ${this.baseUrl}: ${redactText(detail, this.apiKey ? [this.apiKey] : [])}`,
            { status: r.status, retry_after: retryAfter, ratelimit: rl, code, model: this.model, host }
          );
          if (!TRANSIENT.has(r.status) || (code && FINAL_CODES.has(code)) || attempt === this.retries) {
            throw lastErr;
          }
          if (retryAfter) wait = Math.min(MAX_WAIT, Math.max(0.5, retryAfter));
        } else {
          const body = (await r.json()) as any;
          const msg = body?.choices?.[0]?.message;
          if (!msg) throw new LLMError(`unexpected response: ${JSON.stringify(body).slice(0, 300)}`);
          const usage = body?.usage || {};
          const clean: ChatMessage = { role: 'assistant', content: msg.content ?? null };
          if (msg.extra_content != null) clean.extra_content = msg.extra_content;
          if (msg.reasoning_content != null) clean.reasoning_content = msg.reasoning_content;
          if (msg.reasoning != null) clean.reasoning = msg.reasoning;
          if (Array.isArray(msg.tool_calls) && msg.tool_calls.length) {
            clean.tool_calls = msg.tool_calls.map((tc: any, i: number) => {
              const { id, type: _type, function: fn, ...tcExtra } = tc || {};
              return {
                ...tcExtra,
                id: id || `call_${i}`,
                type: 'function' as const,
                function: {
                  name: fn?.name || '',
                  arguments: typeof fn?.arguments === 'string'
                    ? fn.arguments
                    : JSON.stringify(fn?.arguments || {}),
                },
              };
            });
          }
          return {
            message: clean,
            prompt_tokens: Number(usage.prompt_tokens || 0),
            completion_tokens: Number(usage.completion_tokens || 0),
            cost: 0,
            ratelimit: Object.keys(rl).length ? rl : undefined,
          };
        }
      } catch (e: any) {
        if (e instanceof LLMError) throw e;
        if (caller?.signal?.aborted) throw new LLMError('cancelled', { code: 'cancelled' });
        let host = this.baseUrl;
        try { host = new URL(this.baseUrl).hostname; } catch { /* ignore */ }
        const msg = String(e?.message || e);
        const tls = /cert|ssl|tls/i.test(msg);
        lastErr = new LLMError(`cannot reach ${this.baseUrl}: ${msg}`, {
          code: tls ? 'tls' : 'network',
          model: this.model,
          host,
        });
        if (tls || attempt >= Math.min(this.retries, NET_RETRIES)) throw lastErr;
      }
      caller?.notify?.('wait', {
        seconds: Math.round(wait * 10) / 10,
        key_mask: this.apiKey ? maskSecret(this.apiKey) : '(no key)',
        status: lastErr?.status,
        reason: lastErr?.code === 'network' ? 'network' : 'all_paused',
      });
      await sleepWithAbort(wait * 1000, caller?.signal);
    }
    throw lastErr || new LLMError('LLM call failed');
  }
}

function sleepWithAbort(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(new LLMError('cancelled', { code: 'cancelled' }));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new LLMError('cancelled', { code: 'cancelled' }));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export class MockLLM implements LLMBackend {
  model = 'mock';
  private calls = 0;

  async chat(messages: ChatMessage[]): Promise<LLMReply> {
    this.calls += 1;
    const callIdx = this.calls;
    const promptChars = messages.reduce((n, m) => n + String(m.content || '').length, 0);
    const lastUserIdx = messages.map((m) => m.role).lastIndexOf('user');
    const task = lastUserIdx >= 0 ? String(messages[lastUserIdx].content || '') : '';
    const doneTools = lastUserIdx >= 0 ? messages.slice(lastUserIdx).filter((m) => m.role === 'tool') : [];

    let msg: ChatMessage;
    if (doneTools.length === 0) {
      msg = {
        role: 'assistant',
        content: 'Plan: 1) look at the workspace 2) check memory 3) answer.',
        tool_calls: [{ id: `mock_${callIdx}_0`, type: 'function', function: { name: 'list_files', arguments: JSON.stringify({ path: '.' }) } }],
      };
    } else if (doneTools.length === 1) {
      msg = {
        role: 'assistant',
        content: null,
        tool_calls: [{ id: `mock_${callIdx}_0`, type: 'function', function: { name: 'memory_recall', arguments: JSON.stringify({ query: task.slice(0, 120) }) } }],
      };
    } else {
      const files = String(doneTools[0].content || '').split('\n').filter(Boolean);
      const mem = String(doneTools[1].content || '').slice(0, 120);
      msg = {
        role: 'assistant',
        content: `[demo] Task: ${JSON.stringify(task.slice(0, 200))}. Workspace has ${files.length} file(s): ${files.slice(0, 5).join(', ')}. Memory: ${mem}`,
      };
    }
    return {
      message: msg,
      prompt_tokens: Math.floor(promptChars / 4),
      completion_tokens: Math.floor(JSON.stringify(msg).length / 4),
      cost: 0,
    };
  }
}

export const TASKS = ['research', 'writing', 'code', 'analysis', 'vision', 'general'] as const;
const ROLE_WORDS: Array<[string, string[]]> = [
  ['vision', ['image', 'vision', 'photo', 'picture', 'screenshot', 'capture']],
  ['code', ['code', 'coder', 'developer', 'développeur', 'developpeur', 'programm', 'engineer', 'ingénieur', 'debug', 'script', 'test']],
  ['writing', ['writ', 'rédact', 'redact', 'draft', 'rédige', 'redige', 'author', 'auteur', 'editor', 'éditeur', 'translat', 'tradu', 'copy', 'email', 'e-mail', 'mail', 'letter', 'lettre']],
  ['analysis', ['analy', 'compar', 'evaluat', 'évalu', 'review', 'critic', 'risk', 'risque', 'data', 'donnée', 'plan', 'strateg', 'stratég', 'audit']],
  ['research', ['research', 'recherch', 'chercheur', 'search', 'find', 'collect', 'rassembl', 'summar', 'résum', 'resum', 'fact', 'fait', 'read', 'lire', 'veille', 'investigat', 'enquêt', 'source']],
];

export function roleTask(task?: string | null): string {
  const text = String(task || '').trim().toLowerCase();
  if (!text) return 'general';
  const colon = text.slice(0, 40).indexOf(':');
  const head = colon !== -1 ? text.slice(0, colon) : '';
  for (const part of [...(head ? [head] : []), text]) {
    for (const [name, words] of ROLE_WORDS) {
      if (words.some((w) => part.includes(w))) return name;
    }
  }
  return 'general';
}

export interface KeyEntry {
  name: string;
  categories: string[];
  key_env?: string | null;
  provider?: string;
  base_url?: string | null;
  models: Record<string, string>;
  priority: number;
  limits: Record<string, number>;
  pricing: Record<string, number>;
  secretFn?: () => string | null;
  source: 'file' | 'ui';
  tasks: string[];
}

interface KeyUsageState {
  minKey: string;
  minReq: number;
  minTok: number;
  dayKey: string;
  dayReq: number;
  dayTok: number;
  dayCost: number;
  monthKey: string;
  monthTok: number;
  monthCost: number;
}

export class KeyRouter {
  entries: KeyEntry[] = [];
  currency: string;
  usagePath?: string;
  private usage: Record<string, KeyUsageState> = {};
  private cooldownUntil = new Map<string, { until: number; refused: boolean; reason: string }>();
  private inFlight = new Map<string, number>();
  private holders = new Map<string, { key: string; label?: string; ts: number }>();
  private rates = new Map<string, Record<string, any>>();

  constructor(entries: KeyEntry[] = [], usagePath?: string, currency = '') {
    this.entries = entries;
    this.usagePath = usagePath;
    this.currency = currency;
    if (usagePath && fs.existsSync(usagePath)) {
      try {
        this.usage = JSON.parse(fs.readFileSync(usagePath, 'utf-8')) || {};
      } catch {
        this.usage = {};
      }
    }
  }

  replaceEntries(entries: KeyEntry[], currency = ''): void {
    this.entries = entries;
    this.currency = currency;
    this.cooldownUntil.clear();
  }

  keysFor(category: string): KeyEntry[] {
    return this.entries.filter((e) => e.categories.includes(category) || e.categories.includes('*'));
  }

  private getSecret(e: KeyEntry): string | null {
    if (e.secretFn) return e.secretFn();
    if (e.key_env) return process.env[e.key_env] || null;
    return null;
  }

  private needsKey(e: KeyEntry): boolean {
    if (e.provider && e.provider in PROVIDERS && PROVIDERS[e.provider].key_env === null) return false;
    return Boolean(e.secretFn || e.key_env);
  }

  private getUsage(name: string): KeyUsageState {
    const now = new Date();
    const minKey = now.toISOString().slice(0, 16);
    const dayKey = now.toISOString().slice(0, 10);
    const monthKey = now.toISOString().slice(0, 7);
    let u = this.usage[name];
    if (!u) {
      u = { minKey, minReq: 0, minTok: 0, dayKey, dayReq: 0, dayTok: 0, dayCost: 0, monthKey, monthTok: 0, monthCost: 0 };
      this.usage[name] = u;
    }
    if (u.minKey !== minKey) { u.minKey = minKey; u.minReq = 0; u.minTok = 0; }
    if (u.dayKey !== dayKey) { u.dayKey = dayKey; u.dayReq = 0; u.dayTok = 0; u.dayCost = 0; }
    if (u.monthKey !== monthKey) { u.monthKey = monthKey; u.monthTok = 0; u.monthCost = 0; }
    return u;
  }

  private saveUsage(): void {
    if (!this.usagePath) return;
    try {
      fs.mkdirSync(path.dirname(this.usagePath), { recursive: true });
      fs.writeFileSync(this.usagePath, JSON.stringify(this.usage, null, 1), { mode: 0o600 });
    } catch {
      // ignore
    }
  }

  usable(category: string): number {
    const now = Date.now() / 1000;
    return this.keysFor(category).filter((e) => {
      if (this.needsKey(e) && !this.getSecret(e)) return false;
      const cd = this.cooldownUntil.get(e.name);
      return !cd || cd.until <= now;
    }).length;
  }

  releaseHolder(holder: string): void {
    this.holders.delete(holder);
  }

  noteRate(name: string, headers: Record<string, string>): void {
    const prev = this.rates.get(name) || {};
    const next: Record<string, any> = { ...prev, ts: Date.now() / 1000 };
    if (headers['x-ratelimit-limit-tokens']) next.tokens_limit = Number(headers['x-ratelimit-limit-tokens']);
    if (headers['x-ratelimit-remaining-tokens']) next.tokens_remaining = Number(headers['x-ratelimit-remaining-tokens']);
    if (headers['x-ratelimit-limit-requests']) next.requests_limit = Number(headers['x-ratelimit-limit-requests']);
    if (headers['x-ratelimit-remaining-requests']) next.requests_remaining = Number(headers['x-ratelimit-remaining-requests']);
    this.rates.set(name, next);
  }

  rateLimitTokens(name: string): number | null {
    const r = this.rates.get(name);
    return typeof r?.tokens_limit === 'number' && !Number.isNaN(r.tokens_limit) ? r.tokens_limit : null;
  }

  acquire(category: string, opts: { promptTokens?: number; holder?: string; task?: string; label?: string } = {}) {
    const now = Date.now() / 1000;
    const pool = this.keysFor(category);
    const reasons: Record<string, string> = {};
    let waitS: number | undefined;
    let allRefused = pool.length > 0;

    const candidates: Array<{ entry: KeyEntry; score: number }> = [];
    for (const e of pool) {
      const secret = this.getSecret(e);
      if (this.needsKey(e) && !secret) {
        reasons[e.name] = 'missing secret';
        allRefused = false;
        continue;
      }
      const cd = this.cooldownUntil.get(e.name);
      if (cd && cd.until > now) {
        reasons[e.name] = cd.reason;
        if (!cd.refused) {
          allRefused = false;
          const rem = cd.until - now;
          waitS = waitS === undefined ? rem : Math.min(waitS, rem);
        }
        continue;
      }
      allRefused = false;
      const u = this.getUsage(e.name);
      if (e.limits.requests_per_minute && u.minReq >= e.limits.requests_per_minute) {
        reasons[e.name] = 'RPM limit';
        waitS = waitS === undefined ? 15 : Math.min(waitS, 15);
        continue;
      }
      if (e.limits.requests_per_day && u.dayReq >= e.limits.requests_per_day) {
        reasons[e.name] = 'RPD limit';
        continue;
      }
      if (e.limits.tokens_per_day && u.dayTok + (opts.promptTokens || 0) > e.limits.tokens_per_day) {
        reasons[e.name] = 'TPD limit';
        continue;
      }
      const taskMatch = opts.task && e.tasks.includes(opts.task) ? 0 : e.tasks.length === 0 || e.tasks.includes('general') ? 1 : 2;
      const sticky = opts.holder && this.holders.get(opts.holder)?.key === e.name ? -1 : 0;
      const busy = this.inFlight.get(e.name) || 0;
      const score = sticky * 10000 + taskMatch * 1000 + busy * 100 + e.priority;
      candidates.push({ entry: e, score });
    }

    if (!candidates.length) {
      const detail = Object.entries(reasons).map(([k, v]) => `${k}: ${v}`).join('; ') || 'no key configured';
      const err = new LLMError(`no API key can serve category '${category}' (${detail})`, {
        code: allRefused ? 'keys_refused' : 'keys_exhausted',
        retry_after: waitS,
      });
      throw err;
    }

    candidates.sort((a, b) => a.score - b.score);
    const chosen = candidates[0].entry;
    const apiKey = this.getSecret(chosen);
    const model = chosen.models[category] || chosen.models['*'] || (chosen.provider ? PROVIDERS[chosen.provider]?.model : null) || '';
    const baseUrl = chosen.base_url || (chosen.provider ? PROVIDERS[chosen.provider]?.base_url : null) || '';

    this.inFlight.set(chosen.name, (this.inFlight.get(chosen.name) || 0) + 1);
    if (opts.holder) {
      this.holders.set(opts.holder, { key: chosen.name, label: opts.label, ts: now });
    }

    const releaseFlight = () => {
      const cur = this.inFlight.get(chosen.name) || 1;
      if (cur <= 1) this.inFlight.delete(chosen.name);
      else this.inFlight.set(chosen.name, cur - 1);
    };

    return {
      name: chosen.name,
      entry: chosen,
      apiKey,
      model,
      baseUrl,
      holderTask: opts.task || 'general',
      release: releaseFlight,
      commit: (pt: number, ct: number) => {
        releaseFlight();
        const u = this.getUsage(chosen.name);
        u.minReq += 1;
        u.minTok += pt + ct;
        u.dayReq += 1;
        u.dayTok += pt + ct;
        u.monthTok += pt + ct;
        const cost = ((pt * (chosen.pricing.input_per_1m || 0)) + (ct * (chosen.pricing.output_per_1m || 0))) / 1_000_000;
        u.dayCost += cost;
        u.monthCost += cost;
        this.saveUsage();
        return cost;
      },
      fail: (status?: number, retryAfter?: number) => {
        releaseFlight();
        const refused = Boolean(status && KEY_ERRORS.has(status));
        const ttl = retryAfter ?? (refused ? 600 : status === 429 ? 60 : 30);
        this.cooldownUntil.set(chosen.name, {
          until: Date.now() / 1000 + ttl,
          refused,
          reason: refused ? `HTTP ${status} refused` : `cooldown (${status || 'error'})`,
        });
      },
    };
  }

  status(): Record<string, any> {
    const now = Date.now() / 1000;
    const keys = this.entries.map((e) => {
      const sec = this.getSecret(e);
      const cd = this.cooldownUntil.get(e.name);
      const cooldownS = cd && cd.until > now ? Math.ceil(cd.until - now) : 0;
      const u = this.getUsage(e.name);
      const agents: string[] = [];
      for (const [, h] of this.holders) {
        if (h.key === e.name && h.label && !agents.includes(h.label)) agents.push(h.label);
      }
      const limitsView: Record<string, any> = {};
      for (const [f, lim] of Object.entries(e.limits)) {
        const used = f === 'requests_per_minute' ? u.minReq
          : f === 'requests_per_day' ? u.dayReq
          : f === 'tokens_per_day' ? u.dayTok
          : f === 'tokens_per_month' ? u.monthTok
          : f === 'cost_per_day' ? u.dayCost
          : f === 'cost_per_month' ? u.monthCost : 0;
        limitsView[f] = { used, limit: lim, remaining: Math.max(0, lim - used) };
      }
      const rate = this.rates.get(e.name) || {
        tokens_limit: e.provider === 'groq' ? 8000 : undefined,
        tokens_remaining: e.provider === 'groq' ? Math.max(0, 8000 - u.minTok) : undefined,
        source: 'estimate',
      };
      return {
        name: e.name,
        key: this.needsKey(e) ? maskSecret(sec) : '(no key)',
        provider: e.provider,
        priority: e.priority,
        categories: e.categories,
        tasks: e.tasks,
        available: (!this.needsKey(e) || Boolean(sec)) && cooldownS === 0,
        cooldown_s: cooldownS,
        refused: Boolean(cd?.refused && cooldownS > 0),
        limits: limitsView,
        used: { requests_today: u.dayReq, tokens_today: u.dayTok, cost_today: u.dayCost },
        agents,
        in_flight: this.inFlight.get(e.name) || 0,
        rate,
      };
    });
    const categories: Record<string, number> = {};
    for (const e of this.entries) {
      for (const c of e.categories) categories[c] = (categories[c] || 0) + 1;
    }
    return { keys, categories, currency: this.currency };
  }
}

export class RoutedLLM implements LLMBackend {
  router: KeyRouter;
  category: string;
  model: string;

  constructor(router: KeyRouter, category = 'text') {
    this.router = router;
    this.category = category;
    this.model = `router:${category}`;
  }

  async chat(messages: ChatMessage[], tools?: any[], caller?: ChatCallerContext): Promise<LLMReply> {
    const estPrompt = Math.floor((JSON.stringify(messages).length + JSON.stringify(tools || []).length) / 3) + 16;
    let waits = 0;
    let netFails = 0;
    let failed: { key: string; key_mask: string; status?: number; code?: string } | null = null;
    let finalErr: LLMError | null = null;

    while (true) {
      let lease: ReturnType<KeyRouter['acquire']>;
      try {
        lease = this.router.acquire(this.category, {
          promptTokens: estPrompt,
          holder: caller?.holder,
          task: caller?.task,
          label: caller?.label,
        });
      } catch (e: any) {
        if (e instanceof LLMError && e.code === 'keys_refused') {
          caller?.notify?.('refused', {});
          throw e;
        }
        const waitS = e?.retry_after;
        if (finalErr && (!waitS || waitS > MAX_WAIT_TOTAL)) throw finalErr;
        if (!waitS || waitS > MAX_WAIT_TOTAL || waits >= MAX_WAITS) {
          caller?.notify?.('exhausted', {});
          throw e instanceof LLMError ? e : new LLMError(String(e), { code: 'keys_exhausted' });
        }
        const pause = Math.min(MAX_WAIT, Math.max(0.5, waitS));
        waits += 1;
        caller?.notify?.('wait', {
          seconds: Math.round(pause * 10) / 10,
          key_mask: failed?.key_mask,
          status: failed?.status,
          reason: failed?.code === 'network' ? 'network' : 'all_paused',
        });
        await sleepWithAbort(pause * 1000, caller?.signal);
        continue;
      }

      if (!lease.baseUrl || !lease.model) {
        lease.release();
        throw new LLMError(`key ${lease.name}: base_url and model for '${this.category}' are required`);
      }

      const keyMask = lease.apiKey ? maskSecret(lease.apiKey) : '(no key)';
      if (failed && failed.key !== lease.name) {
        const own = lease.entry.categories.includes(this.category);
        const tagged = !lease.entry.tasks.length || lease.entry.tasks.includes('general') || lease.entry.tasks.includes(lease.holderTask);
        caller?.notify?.('switch', {
          key_mask: failed.key_mask,
          to_mask: keyMask,
          status: failed.status,
          backup_kind: own && tagged ? 'same' : own ? 'other_task' : 'other_category',
        });
      }

      const client = new OpenAICompatible(lease.baseUrl, lease.model, lease.apiKey, { retries: 0 });
      try {
        const reply = await client.chat(messages, tools, caller);
        const pt = reply.prompt_tokens || estPrompt;
        const ct = reply.completion_tokens || Math.floor(JSON.stringify(reply.message).length / 3);
        if (reply.ratelimit) this.router.noteRate(lease.name, reply.ratelimit);
        const cost = lease.commit(pt, ct);
        reply.cost = cost;
        reply.key = lease.name;
        reply.key_mask = keyMask;
        reply.key_task = lease.holderTask;
        reply.key_match = Boolean(lease.holderTask && lease.entry.tasks.includes(lease.holderTask));
        if (waits > 0 || failed) caller?.notify?.('resume', { key_mask: keyMask });
        return reply;
      } catch (e: any) {
        if (e instanceof LLMError) {
          if (e.ratelimit) this.router.noteRate(lease.name, e.ratelimit);
          if (e.code === 'cancelled') { lease.release(); throw e; }
          e.key_mask = e.key_mask || keyMask;
          if (e.code === 'tls' || e.code === 'too_large' || e.code === 'model_unavailable') {
            lease.fail(e.status ?? 400);
            throw e;
          }
          if (e.status && !TRANSIENT.has(e.status) && !KEY_ERRORS.has(e.status)) {
            lease.fail(e.status);
            throw e;
          }
          if (e.code === 'network') {
            netFails += 1;
            lease.fail(undefined, NET_COOLDOWN);
            if (netFails > NET_RETRIES) throw e;
          } else if (e.code === 'daily_limit') {
            finalErr = e;
            lease.fail(429, Math.max(e.retry_after || 0, 3600));
          } else {
            lease.fail(e.status, e.retry_after);
          }
          failed = { key: lease.name, key_mask: keyMask, status: e.status, code: e.code };
          continue;
        }
        lease.fail(undefined);
        throw e;
      }
    }
  }

  releaseHolder(holder: string): void {
    this.router.releaseHolder(holder);
  }
}

function validEnvKey(provider: string, key?: string | null): boolean {
  if (!key) return false;
  const s = key.trim();
  if (!s || s.length < 12 || /\s/.test(s) || /^MY_|^YOUR_|PLACEHOLDER|DUMMY/i.test(s)) return false;
  if (provider === 'gemini') return s.startsWith('AIza');
  if (provider === 'groq') return s.startsWith('gsk_');
  if (provider === 'openrouter') return s.startsWith('sk-or-');
  if (provider === 'openai') return s.startsWith('sk-');
  return true;
}

export function makeEnvLLM(): LLMBackend {
  const explicit = (process.env.AGENT_PROVIDER || '').trim().toLowerCase();
  const provider =
    explicit ||
    (validEnvKey('gemini', process.env.GEMINI_API_KEY)
      ? 'gemini'
      : validEnvKey('groq', process.env.GROQ_API_KEY)
      ? 'groq'
      : validEnvKey('openai', process.env.OPENAI_API_KEY)
      ? 'openai'
      : validEnvKey('openrouter', process.env.OPENROUTER_API_KEY)
      ? 'openrouter'
      : 'mock');
  if (provider === 'mock') return new MockLLM();
  const cfg = PROVIDERS[provider];
  if (!cfg) return new MockLLM();
  const base = process.env.AGENT_BASE_URL || cfg.base_url;
  const model = process.env.AGENT_MODEL || cfg.model;
  const key = process.env.AGENT_API_KEY || (cfg.key_env ? process.env[cfg.key_env] : null);
  if (!base || !model || (cfg.key_env && !validEnvKey(provider, key))) return new MockLLM();
  return new OpenAICompatible(base, model, key, { retries: MAX_WAITS });
}
