import fs from 'node:fs';
import path from 'node:path';
import type { Category, Mode } from './types.js';

export const MODES: Mode[] = ['allow', 'ask', 'deny'];
export const CATEGORIES: Category[] = ['read', 'write', 'execute', 'network', 'send', 'spend', 'delegate'];
export const YOLO_PROTECTED: Category[] = ['send', 'spend'];
export const PATTERN_ALLOW_CATEGORIES: Category[] = ['read', 'network', 'execute', 'write', 'delegate'];
export const SHELL_META = new Set(';|&<>`$()\n\r'.split(''));

export const SAFE_DEFAULTS: Record<Category, Mode> = {
  read: 'allow',
  write: 'ask',
  execute: 'ask',
  network: 'ask',
  send: 'ask',
  spend: 'deny',
  delegate: 'ask',
};

export const DEFAULT_PATH_DENY = [
  '.env', '**/.env', '.env.*', '**/*.pem', '**/*.key', '**/id_rsa*', '**/id_ed25519*',
  '.git/**', '.agent/**',
];

export const DEFAULT_COMMAND_DENY = [
  'sudo *', 'su *', '*rm -rf /*', '*rm -rf ~*', '*rm -rf /', '*mkfs*', '*dd if=*',
  '*:(){*', '*> /dev/sd*', '*curl *|*sh*', '*wget *|*sh*', '*chmod -R 777 /*',
  '*shutdown*', '*reboot*', '*git push*--force*',
];

export function fnmatchCase(text: string, pattern: string): boolean {
  let re = '^';
  for (let i = 0; i < pattern.length; i++) {
    const ch = pattern[i];
    if (ch === '*') {
      re += '.*';
    } else if (ch === '?') {
      re += '.';
    } else if ('\\^$.|+()[]{}'.includes(ch)) {
      re += '\\' + ch;
    } else {
      re += ch;
    }
  }
  re += '$';
  return new RegExp(re, 's').test(text);
}

export function matchPath(relPath: string, patterns: string[], anywhere = true): string | null {
  let rel = path.posix.normalize(relPath.replace(/\\/g, '/')).replace(/^\/+/, '').toLowerCase();
  while (rel.startsWith('./')) rel = rel.slice(2);
  const parts = rel.split('/').filter((p) => p && p !== '.');
  const suffixes = (anywhere ? parts.map((_, i) => parts.slice(i).join('/')) : [parts.join('/')]).filter(Boolean);
  if (suffixes.length === 0) suffixes.push(rel);
  const name = parts.length ? parts[parts.length - 1] : rel;

  for (const pat of patterns) {
    const low = pat.replace(/\\/g, '/').toLowerCase();
    const cands = [low];
    if (low.startsWith('**/')) cands.push(low.slice(3));
    if (low.endsWith('/**')) cands.push(low.slice(0, -3));
    for (const c of cands) {
      if (!c.includes('/') && fnmatchCase(name, c)) return pat;
      if (suffixes.some((sfx) => fnmatchCase(sfx, c))) return pat;
    }
  }
  return null;
}

export function matchDomain(host: string, patterns: string[]): boolean {
  for (const raw of patterns) {
    const pat = raw.toLowerCase().replace(/^\.+/, '');
    if (host === pat || host.endsWith('.' + pat) || fnmatchCase(host, pat)) return true;
  }
  return false;
}

/** Minimal YAML subset parser compatible with permissions.yaml */
function parseSimpleYaml(text: string): Record<string, any> {
  const root: Record<string, any> = {};
  const stack: Array<{ indent: number; obj: Record<string, any>; lastKey?: string }> = [{ indent: -1, obj: root }];
  for (const rawLine of text.split(/\r?\n/)) {
    const stripped = rawLine.replace(/\s+#.*$/, '').replace(/^#.*$/, '');
    if (!stripped.trim()) continue;
    const indent = rawLine.search(/\S/);
    const line = stripped.trim();

    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }
    const top = stack[stack.length - 1];
    if (line.startsWith('- ')) {
      const val = line.slice(2).trim().replace(/^['"]|['"]$/g, '');
      if (top.lastKey) {
        if (!Array.isArray(top.obj[top.lastKey])) top.obj[top.lastKey] = [];
        top.obj[top.lastKey].push(val);
      }
      continue;
    }
    const colon = line.indexOf(':');
    if (colon === -1) continue;
    const key = line.slice(0, colon).trim();
    const rest = line.slice(colon + 1).trim();
    if (!rest) {
      const child: Record<string, any> = {};
      top.obj[key] = child;
      top.lastKey = key;
      stack.push({ indent, obj: child });
    } else if (rest === '[]') {
      top.obj[key] = [];
      top.lastKey = key;
    } else if (rest === '{}') {
      top.obj[key] = {};
      top.lastKey = key;
    } else {
      const cleaned = rest.replace(/^['"]|['"]$/g, '');
      top.obj[key] = cleaned === 'true' ? true : cleaned === 'false' ? false : cleaned;
      top.lastKey = key;
    }
  }
  return root;
}

export class Permissions {
  defaults: Record<Category, Mode> = { ...SAFE_DEFAULTS };
  apiAutoGet = new Set<string>();
  tools: Record<string, Mode> = {};
  pathAllow: string[] = [];
  pathDeny: string[] = [...DEFAULT_PATH_DENY];
  commandAllow: string[] = [];
  commandDeny: string[] = [...DEFAULT_COMMAND_DENY];
  domainAllow: string[] = [];
  domainDeny: string[] = [];
  yolo = false;
  source = 'built-in safe defaults';
  idc: Record<string, any> = {};

  static load(filePath?: string | null, yolo = false): Permissions {
    const p = new Permissions();
    p.yolo = yolo;
    if (!filePath || !fs.existsSync(filePath)) return p;
    try {
      const raw = fs.readFileSync(filePath, 'utf-8');
      const data = filePath.endsWith('.json') ? JSON.parse(raw) : parseSimpleYaml(raw);
      p.source = filePath;
      if (data.defaults && typeof data.defaults === 'object') {
        for (const [k, v] of Object.entries(data.defaults)) {
          if (CATEGORIES.includes(k as Category) && MODES.includes(v as Mode)) {
            p.defaults[k as Category] = v as Mode;
          }
        }
      }
      if (data.tools && typeof data.tools === 'object') {
        for (const [k, v] of Object.entries(data.tools)) {
          if (MODES.includes(v as Mode)) p.tools[k] = v as Mode;
        }
      }
      if (data.paths?.allow && Array.isArray(data.paths.allow)) p.pathAllow = [...data.paths.allow];
      if (data.paths?.deny && Array.isArray(data.paths.deny)) p.pathDeny = [...data.paths.deny];
      if (data.commands?.allow && Array.isArray(data.commands.allow)) p.commandAllow = [...data.commands.allow];
      if (data.commands?.deny && Array.isArray(data.commands.deny)) p.commandDeny = [...data.commands.deny];
      if (data.domains?.allow && Array.isArray(data.domains.allow)) p.domainAllow = [...data.domains.allow];
      if (data.domains?.deny && Array.isArray(data.domains.deny)) p.domainDeny = [...data.domains.deny];
      if (data.idc && typeof data.idc === 'object') p.idc = { ...data.idc };
    } catch {
      // fall back to safe defaults
    }
    return p;
  }

  decide(tool: string, category: Category, subjectKind?: string, subject?: string): { mode: Mode; reason: string } {
    let mode: Mode = this.tools[tool] ?? this.defaults[category];
    let why = this.tools[tool]
      ? `tool rule '${tool}: ${this.tools[tool]}'`
      : `category default '${category}: ${this.defaults[category]}'`;

    if (subject !== undefined && subjectKind === 'path') {
      const hit = matchPath(subject, this.pathDeny);
      if (hit) return { mode: 'deny', reason: `path '${subject}' matches deny pattern '${hit}'` };
      if (this.pathAllow.length && !matchPath(subject, this.pathAllow, false)) {
        return { mode: 'deny', reason: `path '${subject}' not in paths.allow` };
      }
    } else if (subject !== undefined && subjectKind === 'command') {
      const cmd = subject.trim().replace(/\s+/g, ' ');
      const denyHit = this.commandDeny.find((pat) => fnmatchCase(cmd, pat));
      if (denyHit) return { mode: 'deny', reason: `command matches deny pattern '${denyHit}'` };
      const hasMeta = [...subject].some((c) => SHELL_META.has(c));
      const allowHit = !hasMeta ? this.commandAllow.find((pat) => fnmatchCase(cmd, pat)) : undefined;
      if (allowHit && mode === 'ask' && PATTERN_ALLOW_CATEGORIES.includes(category)) {
        return { mode: 'allow', reason: `command matches allow pattern '${allowHit}'` };
      }
    } else if (subject !== undefined && subjectKind === 'url') {
      let host = '';
      try {
        host = new URL(subject).hostname.toLowerCase();
      } catch {
        host = '';
      }
      if (matchDomain(host, this.domainDeny)) {
        return { mode: 'deny', reason: `domain '${host}' is in domains.deny` };
      }
      if (matchDomain(host, this.domainAllow) && mode === 'ask' && PATTERN_ALLOW_CATEGORIES.includes(category)) {
        return { mode: 'allow', reason: `domain '${host}' is in domains.allow` };
      }
    }

    if (mode === 'ask' && this.yolo) {
      if (YOLO_PROTECTED.includes(category)) {
        return { mode: 'ask', reason: `${why}; --yolo ignored for '${category}'` };
      }
      return { mode: 'allow', reason: `${why}; upgraded by --yolo` };
    }
    return { mode, reason: why };
  }
}
