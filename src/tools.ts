import crypto from 'node:crypto';
import { exec } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { browserState, type BrowserActionResult } from './browser.js';
import { BrickLibrary, TodoStore, CommunityHub, createWorkspaceSkill } from './extensions.js';
import { matchPath } from './permissions.js';
import { redactText, scrubbedEnv } from './redact.js';
import type { MemoryEntry, MemoryStore, SkillInfo, SkillLibrary, ToolContext, ToolDef } from './types.js';

export class ToolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ToolError';
  }
}

export class FileMemory implements MemoryStore {
  root: string;
  profilePath: string;
  journalPath: string;

  constructor(root: string) {
    this.root = root;
    fs.mkdirSync(root, { recursive: true });
    this.profilePath = path.join(root, 'profile.md');
    this.journalPath = path.join(root, 'journal.jsonl');
    if (!fs.existsSync(this.profilePath)) {
      fs.writeFileSync(this.profilePath, '# Profile\n\n', 'utf-8');
    }
    if (!fs.existsSync(this.journalPath)) {
      fs.writeFileSync(this.journalPath, '', 'utf-8');
    }
  }

  status() {
    return { semantic: false, vectors: 0, model: null, error: null };
  }

  write(text: string, kind = 'note', tags: string[] = []): MemoryEntry {
    const clean = redactText(text.trim());
    if (!clean) throw new Error('empty memory');
    if (kind === 'profile') {
      fs.appendFileSync(this.profilePath, `- ${clean}\n`, 'utf-8');
      return { kind: 'profile', text: clean };
    }
    const entry: MemoryEntry = {
      id: crypto.randomUUID().replace(/-/g, '').slice(0, 8),
      ts: new Date().toISOString(),
      kind,
      tags,
      text: clean,
    };
    fs.appendFileSync(this.journalPath, JSON.stringify(entry) + '\n', 'utf-8');
    return entry;
  }

  private entries(): MemoryEntry[] {
    const out: MemoryEntry[] = [];
    if (!fs.existsSync(this.journalPath)) return out;
    for (const line of fs.readFileSync(this.journalPath, 'utf-8').split('\n')) {
      if (!line.trim()) continue;
      try {
        out.push(JSON.parse(line));
      } catch {
        // skip
      }
    }
    return out;
  }

  private profileItems(): MemoryEntry[] {
    if (!fs.existsSync(this.profilePath)) return [];
    return fs
      .readFileSync(this.profilePath, 'utf-8')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.startsWith('- '))
      .map((l) => ({ id: 'profile', kind: 'profile', text: l.slice(2).trim() }));
  }

  recall(query: string, limit = 5): MemoryEntry[] {
    const all = [...this.profileItems(), ...this.entries()];
    const words = String(query || '').toLowerCase().match(/[\w\u00c0-\u00ff]{2,}/g) || [];
    if (!words.length) return all.slice(-limit).reverse().map((e) => ({ ...e, score: 1 }));
    const scored = all
      .map((e) => {
        const low = e.text.toLowerCase();
        const hits = words.filter((w) => low.includes(w)).length;
        return { ...e, score: Math.round((hits / words.length) * 100) / 100 };
      })
      .filter((e) => (e.score ?? 0) > 0)
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    return scored.slice(0, limit);
  }

  forget(query: string): number {
    const q = query.trim().toLowerCase();
    if (!q) return 0;
    let removed = 0;
    const profLines = fs.readFileSync(this.profilePath, 'utf-8').split('\n');
    const keptProf = profLines.filter((l) => {
      if (l.trim().startsWith('- ') && l.toLowerCase().includes(q)) {
        removed += 1;
        return false;
      }
      return true;
    });
    fs.writeFileSync(this.profilePath, keptProf.join('\n'), 'utf-8');
    const keptJournal = this.entries().filter((e) => {
      if (e.id === query || e.text.toLowerCase().includes(q)) {
        removed += 1;
        return false;
      }
      return true;
    });
    fs.writeFileSync(this.journalPath, keptJournal.map((e) => JSON.stringify(e)).join('\n') + (keptJournal.length ? '\n' : ''), 'utf-8');
    return removed;
  }

  context(): string {
    const prof = this.profileItems().map((p) => `- ${p.text}`);
    const recent = this.entries().slice(-8).map((e) => `- [${e.kind}] ${e.text}`);
    return [...prof, ...recent].join('\n');
  }
}

export const SKILL_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

export function parseSkillFile(text: string): { meta: Record<string, string>; body: string } {
  const meta: Record<string, string> = {};
  let body = text;
  if (text.startsWith('---')) {
    const end = text.indexOf('\n---', 3);
    if (end !== -1) {
      const head = text.slice(3, end);
      body = text.slice(end + 4).replace(/^\n+/, '');
      for (const line of head.split(/\r?\n/)) {
        const idx = line.indexOf(':');
        if (idx !== -1) {
          const k = line.slice(0, idx).trim();
          const v = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '');
          meta[k] = v;
        }
      }
    }
  }
  return { meta, body };
}

export class FileSkillLibrary implements SkillLibrary {
  dirs: Array<{ dir: string; source: string }>;
  skills = new Map<string, SkillInfo & { readBody: () => string }>();

  constructor(dirs: Array<{ dir: string; source: string }>) {
    this.dirs = dirs;
    this.reload();
  }

  reload(): void {
    this.skills.clear();
    for (const { dir, source } of this.dirs) {
      if (!fs.existsSync(dir)) continue;
      let entries: string[] = [];
      try {
        entries = fs.readdirSync(dir).sort();
      } catch {
        continue;
      }
      for (const sub of entries) {
        const skillFile = path.join(dir, sub, 'SKILL.md');
        if (!fs.existsSync(skillFile)) continue;
        const raw = fs.readFileSync(skillFile, 'utf-8');
        const { meta } = parseSkillFile(raw);
        const name = meta.name || sub;
        if (!SKILL_NAME_RE.test(name) || !meta.description || this.skills.has(name)) continue;
        this.skills.set(name, {
          name,
          description: meta.description,
          source,
          path: skillFile,
          readBody: () => parseSkillFile(fs.readFileSync(skillFile, 'utf-8')).body,
        });
      }
    }
  }

  listDetailed(): SkillInfo[] {
    return [...this.skills.values()]
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(({ name, description, source, path: p }) => ({ name, description, source, path: p }));
  }

  names(): string[] {
    return [...this.skills.keys()].sort();
  }

  index(): string {
    return this.listDetailed().map((s) => `- ${s.name}: ${s.description}`).join('\n');
  }

  load(name: string): string {
    const sk = this.skills.get(name);
    if (!sk) throw new Error(`unknown skill '${name}'; available: ${this.names().join(', ') || 'none'}`);
    return sk.readBody();
  }
}

function inside(root: string, target: string): boolean {
  const r = path.resolve(root);
  const t = path.resolve(target);
  return t === r || t.startsWith(r + path.sep);
}

function isProtected(ctx: ToolContext, absPath: string, root: string): boolean {
  for (const d of ctx.denyPaths) {
    if (inside(d, absPath)) return true;
  }
  if (!inside(root, absPath)) return true;
  const rel = path.relative(root, absPath).split(path.sep).join('/');
  return Boolean(rel && matchPath(rel, ctx.pathDeny));
}

function resolveWorkspacePath(ctx: ToolContext, rel: string): string {
  const root = fs.realpathSync(ctx.workspace);
  const candidate = path.resolve(root, rel || '.');
  const realParent = fs.existsSync(candidate) ? fs.realpathSync(candidate) : path.resolve(candidate);
  if (!inside(root, realParent)) {
    throw new ToolError(`path escapes the workspace: ${rel}`);
  }
  if (realParent !== root && isProtected(ctx, realParent, root)) {
    throw new ToolError(`protected file (permissions paths.deny or app data): ${rel}`);
  }
  return realParent;
}

function resolveWritablePath(ctx: ToolContext, rel: string): string {
  const p = resolveWorkspacePath(ctx, rel);
  if (ctx.writePrefix) {
    const allowedRoot = path.resolve(ctx.workspace, ctx.writePrefix);
    if (!inside(allowedRoot, p)) {
      throw new ToolError(
        `path not allowed: '${rel}': in developer mode, create and change files only in ${ctx.writePrefix}`
      );
    }
  }
  return p;
}

const SANDBOX_ALLOWED_CMDS = new Set([
  'ls', 'cat', 'head', 'tail', 'wc', 'grep', 'find', 'pwd', 'echo', 'date', 'node', 'npm', 'npx', 'tsx', 'python', 'python3', 'pytest',
]);

function runShell(ctx: ToolContext, cmd: string, timeoutSec: number): Promise<string> {
  if (ctx.sandboxOn()) {
    const trimmed = cmd.trim();
    if (!trimmed || /[;|&<>`$()\n\r]/.test(trimmed)) {
      throw new ToolError('sandbox: shell chaining, pipes, and redirections are blocked');
    }
    const exe = trimmed.split(/\s+/)[0];
    if (!SANDBOX_ALLOWED_CMDS.has(exe)) {
      throw new ToolError(`sandbox: command '${exe}' is not in the allowlist`);
    }
  }
  const timeout = Math.min(Math.max(1, timeoutSec), 600) * 1000;
  return new Promise((resolve, reject) => {
    exec(cmd, { cwd: ctx.workspace, timeout, env: scrubbedEnv(), maxBuffer: 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && (err as any).killed) {
        reject(new ToolError(`timeout after ${timeout / 1000}s`));
        return;
      }
      const code = err && typeof (err as any).code === 'number' ? (err as any).code : 0;
      let out = (stdout || '') + (stderr ? `\n[stderr]\n${stderr}` : '');
      if (out.length > ctx.maxOutput) {
        out = out.slice(0, ctx.maxOutput) + `\n... (${out.length - ctx.maxOutput} chars truncated)`;
      }
      resolve(`exit=${code}\n${out}`.trimEnd());
    });
  });
}

function htmlToText(raw: string): string {
  return raw
    .replace(/<(script|style)[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\n\s*\n+/g, '\n\n')
    .replace(/[ \t\r\f\v]+/g, ' ')
    .trim();
}

export function untrusted(source: string, body: string): string {
  return `<external_content source="${source}">\n${body}\n</external_content>`;
}

function formatBrowserOutput(
  ctx: ToolContext,
  res: BrowserActionResult,
  extraHeading?: string
): string {
  const controlsLines = res.controls
    .slice(0, 20)
    .map((c) => {
      const valPart = c.value !== undefined && c.value !== '' ? ` val="${c.value}"` : '';
      const optPart = c.options?.length ? ` options=[${c.options.join(', ')}]` : '';
      return `- [${c.role}] "${c.text || '(sans libellé)'}" -> selector: ${c.selector}${valPart}${optPart}`;
    })
    .join('\n');

  const scrollPct =
    res.scrollHeight > res.viewportHeight
      ? Math.round((res.scrollY / Math.max(1, res.scrollHeight - res.viewportHeight)) * 100)
      : 0;

  const bodyLines = [
    ...(extraHeading ? [extraHeading, ''] : []),
    `Title: ${res.title}`,
    `Final URL: ${res.finalUrl}`,
    `HTTP Status: ${res.status ?? 'unknown'}`,
    `Scroll: y=${res.scrollY}px / ${res.scrollHeight}px (${scrollPct}%)`,
    '',
    'Text:',
    res.paragraphs.length ? res.paragraphs.join('\n\n') : '(no readable text extracted)',
    ...(controlsLines ? ['', 'Interactive controls:', controlsLines] : []),
  ].join('\n');

  const maxBody = Math.max(500, ctx.maxOutput - 80);
  const clippedBody = bodyLines.length > maxBody ? bodyLines.slice(0, maxBody) + '\n... (truncated)' : bodyLines;
  return untrusted(res.finalUrl, clippedBody);
}

function assertAgentBrowserControl(): void {
  if (browserState.userControl) {
    throw new ToolError("L'utilisateur a actuellement pris la main sur le navigateur. Demandez-lui ou attendez qu'il rende la main.");
  }
}

export function defaultTools(): ToolDef[] {
  return [
    {
      name: 'read_file',
      description: 'Read a text file in the workspace (with line numbers).',
      category: 'read',
      subjectKind: 'path',
      subjectFn: (a) => a.path,
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string', description: 'path relative to the workspace' },
          offset: { type: 'integer', description: 'first line (1-based)' },
          limit: { type: 'integer', description: 'max lines' },
        },
        required: ['path'],
      },
      execute: (ctx, a) => {
        const p = resolveWorkspacePath(ctx, String(a.path || ''));
        if (!fs.existsSync(p) || !fs.statSync(p).isFile()) throw new ToolError(`not a file: ${a.path}`);
        const lines = fs.readFileSync(p, 'utf-8').split(/\r?\n/);
        const start = Math.max(1, Number(a.offset || 1));
        const limit = Math.max(1, Number(a.limit || 400));
        const chunk = lines.slice(start - 1, start - 1 + limit);
        let out = chunk.map((ln, i) => `${String(start + i).padStart(5, ' ')}| ${ln}`).join('\n');
        if (start - 1 + limit < lines.length) {
          out += `\n... (${lines.length} lines total, use offset to continue)`;
        }
        return out.slice(0, ctx.maxOutput) || '(empty file)';
      },
    },
    {
      name: 'list_files',
      description: 'List files under a workspace directory.',
      category: 'read',
      subjectKind: 'path',
      subjectFn: (a) => a.path,
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string', description: "directory, default '.'" },
          depth: { type: 'integer' },
        },
        required: [],
      },
      execute: (ctx, a) => {
        const p = resolveWorkspacePath(ctx, String(a.path || '.'));
        if (!fs.existsSync(p) || !fs.statSync(p).isDirectory()) throw new ToolError(`not a directory: ${a.path}`);
        const root = fs.realpathSync(ctx.workspace);
        const maxDepth = Math.max(1, Number(a.depth || 2));
        const out: string[] = [];
        const walk = (dir: string, curDepth: number) => {
          if (out.length > 500) return;
          for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((x, y) => x.name.localeCompare(y.name))) {
            if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === '__pycache__' || entry.name === '.venv') continue;
            const full = path.join(dir, entry.name);
            if (entry.isSymbolicLink()) continue;
            if (entry.isDirectory()) {
              if (curDepth < maxDepth) walk(full, curDepth + 1);
            } else if (entry.isFile()) {
              out.push(path.relative(root, full).split(path.sep).join('/'));
              if (out.length > 500) { out.push('... (truncated)'); return; }
            }
          }
        };
        walk(p, 0);
        return out.join('\n') || '(empty)';
      },
    },
    {
      name: 'search_files',
      description: 'Case-insensitive text search in workspace files.',
      category: 'read',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'text to find' },
          glob: { type: 'string', description: 'file name suffix, e.g. .ts' },
        },
        required: ['query'],
      },
      execute: (ctx, a) => {
        const needle = String(a.query || '').toLowerCase();
        const root = fs.realpathSync(ctx.workspace);
        const hits: string[] = [];
        const walk = (dir: string) => {
          if (hits.length >= 100) return;
          for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.isSymbolicLink()) continue;
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) walk(full);
            else if (entry.isFile() && !isProtected(ctx, full, root)) {
              if (a.glob && a.glob !== '*' && !entry.name.endsWith(String(a.glob).replace('*', ''))) continue;
              try {
                const lines = fs.readFileSync(full, 'utf-8').split(/\r?\n/);
                for (let i = 0; i < lines.length; i++) {
                  if (lines[i].toLowerCase().includes(needle)) {
                    hits.push(`${path.relative(root, full)}:${i + 1}: ${lines[i].trim().slice(0, 200)}`);
                    if (hits.length >= 100) { hits.push('... (truncated)'); return; }
                  }
                }
              } catch { /* ignore */ }
            }
          }
        };
        walk(root);
        return hits.join('\n') || 'no match';
      },
    },
    {
      name: 'write_file',
      description: 'Create or overwrite a file in the workspace.',
      category: 'write',
      subjectKind: 'path',
      subjectFn: (a) => a.path,
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string', description: 'path' },
          content: { type: 'string', description: 'full file content' },
        },
        required: ['path', 'content'],
      },
      execute: (ctx, a) => {
        const p = resolveWritablePath(ctx, String(a.path || ''));
        fs.mkdirSync(path.dirname(p), { recursive: true });
        const content = String(a.content ?? '');
        fs.writeFileSync(p, content, 'utf-8');
        return `wrote ${content.length} chars to ${a.path}`;
      },
    },
    {
      name: 'edit_file',
      description: 'Replace an exact text fragment in a workspace file.',
      category: 'write',
      subjectKind: 'path',
      subjectFn: (a) => a.path,
      parameters: {
        type: 'object',
        properties: {
          path: { type: 'string' },
          old: { type: 'string' },
          new: { type: 'string' },
          replace_all: { type: 'boolean' },
        },
        required: ['path', 'old', 'new'],
      },
      execute: (ctx, a) => {
        const p = resolveWritablePath(ctx, String(a.path || ''));
        if (!fs.existsSync(p) || !fs.statSync(p).isFile()) throw new ToolError(`not a file: ${a.path}`);
        const text = fs.readFileSync(p, 'utf-8');
        const oldStr = String(a.old ?? '');
        const newStr = String(a.new ?? '');
        const count = text.split(oldStr).length - 1;
        if (count === 0) throw new ToolError('`old` text not found; read the file first and copy it exactly');
        if (count > 1 && !a.replace_all) {
          throw new ToolError(`\`old\` text found ${count} times; add more context or set replace_all=true`);
        }
        const updated = a.replace_all ? text.split(oldStr).join(newStr) : text.replace(oldStr, newStr);
        fs.writeFileSync(p, updated, 'utf-8');
        return `edited ${a.path} (${a.replace_all ? count : 1} replacement(s))`;
      },
    },
    {
      name: 'shell',
      description: 'Run a shell command in the workspace (bash/sh). Secret env vars are removed.',
      category: 'execute',
      subjectKind: 'command',
      subjectFn: (a) => a.command,
      parameters: {
        type: 'object',
        properties: {
          command: { type: 'string', description: 'command line' },
          timeout: { type: ['integer', 'null'], description: 'optional, seconds' },
        },
        required: ['command'],
      },
      execute: (ctx, a) => runShell(ctx, String(a.command || ''), Number(a.timeout || ctx.shellTimeout)),
    },
    {
      name: 'web_fetch',
      description: 'Fetch a web page or API URL and return its text.',
      category: 'network',
      subjectKind: 'url',
      subjectFn: (a) => a.url,
      parameters: {
        type: 'object',
        properties: {
          url: { type: 'string', description: 'http(s) URL' },
          max_chars: { type: 'integer' },
        },
        required: ['url'],
      },
      execute: async (ctx, a) => {
        const url = String(a.url || '');
        if (!/^https?:\/\//i.test(url)) throw new ToolError('only http(s) URLs are allowed');
        const r = await fetch(url, { signal: AbortSignal.timeout(20000), headers: { 'User-Agent': 'autonomous-agent/0.9.22' } });
        const ctype = r.headers.get('content-type') || '';
        const raw = await r.text();
        const text = ctype.includes('html') ? htmlToText(raw) : raw;
        const n = Number(a.max_chars || ctx.maxOutput);
        return untrusted(url, text.slice(0, n) + (text.length > n ? '\n... (truncated)' : ''));
      },
    },
    {
      name: 'web_search',
      description: 'Best-effort web search (DuckDuckGo HTML by default).',
      category: 'network',
      subjectKind: 'url',
      subjectFn: () => process.env.AGENT_SEARCH_URL || 'https://html.duckduckgo.com/html/',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'search query' },
          limit: { type: 'integer' },
        },
        required: ['query'],
      },
      execute: async (_ctx, a) => {
        const base = process.env.AGENT_SEARCH_URL || 'https://html.duckduckgo.com/html/';
        const url = `${base}${base.includes('?') ? '&' : '?'}q=${encodeURIComponent(String(a.query || ''))}`;
        const r = await fetch(url, { signal: AbortSignal.timeout(20000), headers: { 'User-Agent': 'autonomous-agent/0.9.22' } });
        const body = await r.text();
        const results: string[] = [];
        const lim = Number(a.limit || 8);
        for (const m of body.matchAll(/<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g)) {
          const href = m[1];
          let resolved = href;
          try {
            const uddg = new URL(href, 'https://duckduckgo.com').searchParams.get('uddg');
            if (uddg) resolved = uddg;
          } catch { /* ignore */ }
          results.push(`- ${htmlToText(m[2])} — ${resolved}`);
          if (results.length >= lim) break;
        }
        if (results.length) return untrusted(`web search: ${String(a.query || '').slice(0, 80)}`, results.join('\n'));
        return 'no results (search endpoint may block automated requests; use web_fetch on a known URL)';
      },
    },
    {
      name: 'browser_navigate',
      description:
        'Open a URL in the shared persistent headless Chromium browser (Playwright) visible in the live navigation sidebar, and return page metadata, text paragraphs, and interactive element selectors.',
      category: 'network',
      subjectKind: 'url',
      subjectFn: (a) => a.url,
      parameters: {
        type: 'object',
        properties: {
          url: { type: 'string', description: 'http(s) URL to navigate to' },
          wait_ms: { type: 'integer', description: 'optional extra wait after load in ms (0-5000)' },
        },
        required: ['url'],
      },
      execute: async (ctx, a) => {
        assertAgentBrowserControl();
        const url = String(a.url || '').trim();
        if (!/^https?:\/\//i.test(url)) throw new ToolError('only http(s) URLs are allowed');
        try {
          const res = await browserState.navigate({
            url,
            source: 'agent',
            waitMs: a.wait_ms !== undefined ? Number(a.wait_ms) : undefined,
          });
          return formatBrowserOutput(ctx, res);
        } catch (e: any) {
          if (e instanceof ToolError) throw e;
          throw new ToolError(`browser_navigate failed: ${e?.message || e}`);
        }
      },
    },
    {
      name: 'browser_read',
      description:
        'Read the currently open page in the shared browser: returns title, URL, scroll position, visible text (or a specific CSS selector text), and interactive controls with CSS selectors.',
      category: 'read',
      parameters: {
        type: 'object',
        properties: {
          selector: { type: 'string', description: 'optional CSS selector to extract specific text from' },
        },
        required: [],
      },
      execute: async (ctx, a) => {
        try {
          const res = await browserState.readCurrent({
            source: 'agent',
            selector: a.selector ? String(a.selector) : undefined,
          });
          const extra = res.selectedText ? `Selected (${a.selector}):\n${res.selectedText}` : undefined;
          return formatBrowserOutput(ctx, res, extra);
        } catch (e: any) {
          if (e instanceof ToolError) throw e;
          throw new ToolError(`browser_read failed: ${e?.message || e}`);
        }
      },
    },
    {
      name: 'browser_click',
      description:
        'Click an element in the shared browser by CSS selector, visible text, or (x, y) viewport coordinates, then return updated page state.',
      category: 'network',
      parameters: {
        type: 'object',
        properties: {
          selector: { type: 'string', description: 'CSS selector of the element to click' },
          text: { type: 'string', description: 'visible text of the button/link to click if no selector' },
          x: { type: 'number', description: 'optional viewport X coordinate (0-1279)' },
          y: { type: 'number', description: 'optional viewport Y coordinate (0-799)' },
        },
        required: [],
      },
      execute: async (ctx, a) => {
        assertAgentBrowserControl();
        try {
          const res = await browserState.click({
            source: 'agent',
            selector: a.selector ? String(a.selector) : undefined,
            text: a.text ? String(a.text) : undefined,
            x: typeof a.x === 'number' ? a.x : undefined,
            y: typeof a.y === 'number' ? a.y : undefined,
          });
          return formatBrowserOutput(ctx, res);
        } catch (e: any) {
          if (e instanceof ToolError) throw e;
          throw new ToolError(`browser_click failed: ${e?.message || e}`);
        }
      },
    },
    {
      name: 'browser_type',
      description:
        'Type or fill text into an input/textarea in the shared browser (optionally focusing a CSS selector first and optionally pressing Enter).',
      category: 'network',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'text to type or fill' },
          selector: { type: 'string', description: 'optional CSS selector of input/textarea' },
          clear: { type: 'boolean', description: 'replace existing content (default true)' },
          press_enter: { type: 'boolean', description: 'press Enter after typing (default false)' },
        },
        required: ['text'],
      },
      execute: async (ctx, a) => {
        assertAgentBrowserControl();
        try {
          const res = await browserState.typeText({
            source: 'agent',
            text: String(a.text ?? ''),
            selector: a.selector ? String(a.selector) : undefined,
            clear: a.clear !== false,
            pressEnter: Boolean(a.press_enter),
          });
          return formatBrowserOutput(ctx, res);
        } catch (e: any) {
          if (e instanceof ToolError) throw e;
          throw new ToolError(`browser_type failed: ${e?.message || e}`);
        }
      },
    },
    {
      name: 'browser_select',
      description:
        'Select an option in a <select> dropdown in the shared browser by option value or visible label.',
      category: 'network',
      parameters: {
        type: 'object',
        properties: {
          selector: { type: 'string', description: 'CSS selector of the <select> element' },
          value: { type: 'string', description: 'option value attribute' },
          label: { type: 'string', description: 'visible option text label' },
        },
        required: ['selector'],
      },
      execute: async (ctx, a) => {
        assertAgentBrowserControl();
        try {
          const res = await browserState.selectOption({
            source: 'agent',
            selector: String(a.selector || ''),
            value: a.value !== undefined ? String(a.value) : undefined,
            label: a.label !== undefined ? String(a.label) : undefined,
          });
          return formatBrowserOutput(ctx, res);
        } catch (e: any) {
          if (e instanceof ToolError) throw e;
          throw new ToolError(`browser_select failed: ${e?.message || e}`);
        }
      },
    },
    {
      name: 'browser_scroll',
      description:
        'Scroll the shared browser page (down, up, top, bottom) or scroll a specific element into view, and return the updated viewport state.',
      category: 'network',
      parameters: {
        type: 'object',
        properties: {
          direction: { type: 'string', enum: ['down', 'up', 'top', 'bottom'], description: 'scroll direction' },
          amount: { type: 'integer', description: 'pixels to scroll for up/down (default 500)' },
          selector: { type: 'string', description: 'optional CSS selector to scroll into view' },
        },
        required: [],
      },
      execute: async (ctx, a) => {
        assertAgentBrowserControl();
        try {
          const res = await browserState.scroll({
            source: 'agent',
            direction: (a.direction as any) || 'down',
            amount: a.amount !== undefined ? Number(a.amount) : undefined,
            selector: a.selector ? String(a.selector) : undefined,
          });
          return formatBrowserOutput(ctx, res);
        } catch (e: any) {
          if (e instanceof ToolError) throw e;
          throw new ToolError(`browser_scroll failed: ${e?.message || e}`);
        }
      },
    },
    {
      name: 'browser_key',
      description:
        'Press a keyboard key in the shared browser (e.g. Enter, Tab, Escape, Backspace, PageDown, ArrowDown).',
      category: 'network',
      parameters: {
        type: 'object',
        properties: {
          key: { type: 'string', description: 'key name (Enter, Tab, Escape, Backspace, PageDown, ArrowDown, etc.)' },
        },
        required: ['key'],
      },
      execute: async (ctx, a) => {
        assertAgentBrowserControl();
        try {
          const res = await browserState.pressKey({
            source: 'agent',
            key: String(a.key || 'Enter'),
          });
          return formatBrowserOutput(ctx, res);
        } catch (e: any) {
          if (e instanceof ToolError) throw e;
          throw new ToolError(`browser_key failed: ${e?.message || e}`);
        }
      },
    },
    {
      name: 'memory_write',
      description: 'Save a durable note (kind: note|profile|decision|todo).',
      category: 'write',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'what to remember' },
          kind: { type: 'string', description: 'note|profile|decision|todo' },
          tags: { type: 'array', items: { type: 'string' } },
        },
        required: ['text'],
      },
      execute: (ctx, a) => {
        const kind = String(a.kind || 'note');
        if (!['note', 'profile', 'decision', 'todo'].includes(kind)) {
          throw new ToolError('kind must be note, profile, decision or todo');
        }
        const tags = Array.isArray(a.tags) ? a.tags.map(String) : [];
        return 'saved: ' + JSON.stringify(ctx.memory.write(String(a.text || ''), kind, tags));
      },
    },
    {
      name: 'memory_recall',
      description: 'Search durable memory.',
      category: 'read',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'what you are looking for' },
          limit: { type: ['integer', 'null'] },
        },
        required: [],
      },
      execute: (ctx, a) => {
        const hits = ctx.memory.recall(String(a.query || ''), Number(a.limit || 5));
        const lines = hits.map((h) => `[${h.id}] (${h.kind}, score ${h.score}) ${h.text}`);
        return lines.length ? `(keywords)\n${lines.join('\n')}` : 'nothing found';
      },
    },
    {
      name: 'memory_forget',
      description: 'Delete memory items whose id or text matches.',
      category: 'write',
      parameters: {
        type: 'object',
        properties: { query: { type: 'string', description: 'entry id or text fragment' } },
        required: ['query'],
      },
      execute: (ctx, a) => `forgot ${ctx.memory.forget(String(a.query || ''))} item(s)`,
    },
    {
      name: 'list_skills',
      description: 'List available skills (name: description).',
      category: 'read',
      parameters: { type: 'object', properties: {}, required: [] },
      execute: (ctx) => ctx.skills.index() || 'no skills installed',
    },
    {
      name: 'load_skill',
      description: 'Load the full instructions of a skill by name before following it.',
      category: 'read',
      parameters: {
        type: 'object',
        properties: { name: { type: 'string', description: 'skill name' } },
        required: ['name'],
      },
      execute: (ctx, a) => {
        try {
          return ctx.skills.load(String(a.name || ''));
        } catch (e: any) {
          throw new ToolError(e.message);
        }
      },
    },
    {
      name: 'skill_create',
      description:
        'Create or update a reusable skill in workspace skills/<name>/SKILL.md and reload the skill library immediately.',
      category: 'write',
      parameters: {
        type: 'object',
        properties: {
          name: { type: 'string', description: 'lowercase skill slug (letters, digits, hyphens, underscores)' },
          description: { type: 'string', description: 'short 1-line description of when to use this skill' },
          instructions: { type: 'string', description: 'Markdown instructions for the skill' },
        },
        required: ['name', 'description', 'instructions'],
      },
      execute: (ctx, a) => {
        try {
          const res = createWorkspaceSkill(ctx.workspace, ctx.skills, {
            name: String(a.name || ''),
            description: String(a.description || ''),
            instructions: String(a.instructions || ''),
          });
          return `Skill installed and loaded: ${res.name} (${res.relPath})`;
        } catch (e: any) {
          throw new ToolError(e?.message || String(e));
        }
      },
    },
    {
      name: 'todo_read',
      description:
        'Read todo.md containing user requests and missing capabilities the assistant does not yet know how to handle.',
      category: 'read',
      parameters: { type: 'object', properties: {}, required: [] },
      execute: (ctx) => {
        const store = ctx.todos || new TodoStore(ctx.workspace);
        const items = store.list();
        const pending = items.filter((i) => !i.done);
        const done = items.filter((i) => i.done);
        return `todo.md (${pending.length} pending, ${done.length} done)\n\n${store.readRaw()}`.slice(0, ctx.maxOutput);
      },
    },
    {
      name: 'todo_add',
      description:
        'Record a user request or missing capability in todo.md whenever the user asks for something you do not know how to do yet or a new interface component/skill to build.',
      category: 'write',
      parameters: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'concise title of the missing capability or requested feature' },
          details: { type: 'string', description: 'details of what the user requested and what is missing' },
          kind: { type: 'string', enum: ['brick', 'skill', 'both'], description: 'recommended implementation form (default: brick)' },
        },
        required: ['title'],
      },
      execute: (ctx, a) => {
        const store = ctx.todos || new TodoStore(ctx.workspace);
        try {
          const res = store.add({
            title: String(a.title || ''),
            details: a.details ? String(a.details) : '',
            kind: (a.kind as any) || 'brick',
          });
          return `${res.created ? 'Added to' : 'Already pending in'} todo.md: [${res.item.id}] ${res.item.title} (${res.item.kind})`;
        } catch (e: any) {
          throw new ToolError(e?.message || String(e));
        }
      },
    },
    {
      name: 'todo_update',
      description:
        'Update an item in todo.md (mark done after coding a brick/skill, reopen as pending, or delete).',
      category: 'write',
      parameters: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'todo item ID (e.g. todo-a1b2c3)' },
          status: { type: 'string', enum: ['done', 'pending', 'delete'], description: 'new status' },
          brick_id: { type: 'string', description: 'optional brick id created for this todo' },
          skill_name: { type: 'string', description: 'optional skill name created for this todo' },
          note: { type: 'string', description: 'optional short completion note' },
        },
        required: ['id', 'status'],
      },
      execute: (ctx, a) => {
        const store = ctx.todos || new TodoStore(ctx.workspace);
        try {
          const res = store.update(String(a.id || ''), {
            status: a.status as any,
            brickId: a.brick_id ? String(a.brick_id) : undefined,
            skillName: a.skill_name ? String(a.skill_name) : undefined,
            note: a.note ? String(a.note) : undefined,
          });
          if (res.removed) return `Removed ${a.id} from todo.md`;
          return `Updated todo.md [${res.item?.id}]: done=${res.item?.done}`;
        } catch (e: any) {
          throw new ToolError(e?.message || String(e));
        }
      },
    },
    {
      name: 'brick_list',
      description: 'List all UI component bricks currently installed in the interface.',
      category: 'read',
      parameters: { type: 'object', properties: {}, required: [] },
      execute: (ctx) => {
        const lib = ctx.bricks || new BrickLibrary(ctx.workspace);
        const list = lib.list();
        if (!list.length) return 'No UI bricks installed yet.';
        return JSON.stringify(list, null, 2).slice(0, ctx.maxOutput);
      },
    },
    {
      name: 'brick_create',
      description:
        'Create or update an interactive UI component ("brique") in bricks/<id>/ and mount it live in the user interface. Provide clean self-contained HTML/CSS/JS (dark/light friendly via CSS variables/prefers-color-scheme; optional window.parent.postMessage({type:"brick:ask",prompt:"...",send:false},"*") to send a prompt to the chat, and listen to window.addEventListener("message",e=>{if(e.data?.type==="brick:init"){...}}) for theme/lang).',
      category: 'write',
      parameters: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'lowercase slug id (e.g. pomodoro, json-formatter)' },
          name: { type: 'string', description: 'display title of the UI brick' },
          description: { type: 'string', description: 'short description of what this component does' },
          icon: { type: 'string', description: 'single emoji icon (default 🧩)' },
          html: { type: 'string', description: 'complete self-contained HTML document (<!doctype html>...) with inline CSS/JS' },
          placement: { type: 'string', enum: ['dock', 'panel'], description: 'dock (visible in main chat dock, default) or panel (drawer only)' },
          height: { type: 'integer', description: 'initial iframe height in px (140-640, default 280)' },
          todo_id: { type: 'string', description: 'optional todo.md item ID resolved by this brick' },
          skill_name: { type: 'string', description: 'optional linked skill name' },
        },
        required: ['id', 'name', 'html'],
      },
      execute: (ctx, a) => {
        const lib = ctx.bricks || new BrickLibrary(ctx.workspace);
        try {
          const brick = lib.create({
            id: String(a.id || ''),
            name: String(a.name || ''),
            description: a.description ? String(a.description) : '',
            icon: a.icon ? String(a.icon) : '🧩',
            html: String(a.html || ''),
            placement: a.placement === 'panel' ? 'panel' : 'dock',
            height: a.height !== undefined ? Number(a.height) : undefined,
            todoId: a.todo_id ? String(a.todo_id) : undefined,
            skill: a.skill_name ? String(a.skill_name) : undefined,
          });
          return `UI Brick installed in interface: ${brick.icon} ${brick.name} (id=${brick.id}, placement=${brick.placement}, url=${brick.url})`;
        } catch (e: any) {
          throw new ToolError(e?.message || String(e));
        }
      },
    },
    {
      name: 'brick_delete',
      description: 'Remove an installed UI brick component from the interface by id.',
      category: 'write',
      parameters: {
        type: 'object',
        properties: { id: { type: 'string', description: 'brick id to delete' } },
        required: ['id'],
      },
      execute: (ctx, a) => {
        const lib = ctx.bricks || new BrickLibrary(ctx.workspace);
        const ok = lib.delete(String(a.id || ''));
        if (!ok) throw new ToolError(`Brick not found: ${a.id}`);
        return `Brick removed: ${a.id}`;
      },
    },
    {
      name: 'github_publish',
      description: 'Publish a created UI brick or skill to GitHub (community registry) so other agents and users can benefit from it.',
      category: 'send',
      parameters: {
        type: 'object',
        properties: {
          kind: { type: 'string', enum: ['brick', 'skill'], description: 'item kind: brick or skill' },
          id: { type: 'string', description: 'brick id or skill name to publish' },
          repository: { type: 'string', description: 'target GitHub repository (default: lanoixdesign/autonomous-agent-hub)' },
        },
        required: ['kind', 'id'],
      },
      execute: async (ctx, a) => {
        const kind = a.kind === 'skill' ? 'skill' : 'brick';
        const id = String(a.id || '');
        const repo = a.repository ? String(a.repository) : 'lanoixdesign/autonomous-agent-hub';
        const bricksLib = ctx.bricks || new BrickLibrary(ctx.workspace);
        const community = ctx.community || new CommunityHub(ctx.workspace, path.join(ctx.workspace, '.agent'));
        try {
          const res = await community.publishToGitHub(kind, id, bricksLib, ctx.skills, undefined, repo);
          return `${res.message} (URL: ${res.url})`;
        } catch (e: any) {
          throw new ToolError(e?.message || String(e));
        }
      },
    },
  ];
}
