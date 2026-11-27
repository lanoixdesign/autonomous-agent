import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { SKILL_NAME_RE } from './tools.js';
import type { BrickInfo, SkillLibrary, TodoItem, TodoKind } from './types.js';

export const BRICK_ID_RE = /^[a-z0-9][a-z0-9_-]{0,47}$/;
export const BRICK_CSP =
  "sandbox allow-scripts allow-forms allow-modals; default-src 'self' data: blob:; " +
  "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
  "font-src 'self' data:; media-src 'self' data: blob:; connect-src 'none'; form-action 'none'; " +
  "frame-ancestors 'self'; base-uri 'none'";

const BRICK_MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
};

const DEFAULT_TODO_HEADER = `# TODO — Demandes & Capacités manquantes

Chaque demande de l'utilisateur que l'assistant ne sait pas encore faire est notée ici pour être programmée sous forme de brique d'interface ou de skill.

`;

function cleanInline(s: string): string {
  return String(s || '').replace(/\r?\n+/g, ' ').replace(/\s+/g, ' ').trim();
}

function slugifyId(raw: string): string {
  const map: Record<string, string> = {
    à: 'a', â: 'a', ä: 'a', á: 'a', ã: 'a', å: 'a', ç: 'c',
    é: 'e', è: 'e', ê: 'e', ë: 'e', í: 'i', ì: 'i', î: 'i', ï: 'i',
    ñ: 'n', ó: 'o', ò: 'o', ô: 'o', ö: 'o', õ: 'o', ú: 'u', ù: 'u',
    û: 'u', ü: 'u', ý: 'y', ÿ: 'y', œ: 'oe', æ: 'ae',
  };
  return (raw || '')
    .trim()
    .toLowerCase()
    .replace(/[àâäáãåçéèêëíìîïñóòôöõúùûüýÿœæ]/g, (ch) => map[ch] || ch)
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
}

export class TodoStore {
  workspace: string;
  filePath: string;

  constructor(workspace: string) {
    this.workspace = path.resolve(workspace);
    this.filePath = path.join(this.workspace, 'todo.md');
    this.ensureFile();
  }

  ensureFile(): void {
    fs.mkdirSync(this.workspace, { recursive: true });
    if (!fs.existsSync(this.filePath)) {
      fs.writeFileSync(this.filePath, DEFAULT_TODO_HEADER, 'utf-8');
    }
  }

  readRaw(): string {
    this.ensureFile();
    return fs.readFileSync(this.filePath, 'utf-8');
  }

  private parseLine(line: string, idx: number): TodoItem | null {
    const m = /^\s*-\s+\[([ xX])\]\s+(.+)$/.exec(line);
    if (!m) return null;
    const done = m[1].toLowerCase() === 'x';
    let rest = m[2].trim();

    let id = '';
    const idMatch = /^\*\*\[([a-z0-9_-]+)\]\*\*\s*/i.exec(rest) || /^`([a-z0-9_-]+)`\s*/i.exec(rest);
    if (idMatch) {
      id = idMatch[1];
      rest = rest.slice(idMatch[0].length).trim();
    } else {
      id = 'todo-' + crypto.createHash('sha1').update(`${idx}:${line}`).digest('hex').slice(0, 6);
    }

    let createdAt = '';
    const dateMatch = /^\((\d{4}-\d{2}-\d{2})\)\s*/.exec(rest);
    if (dateMatch) {
      createdAt = dateMatch[1];
      rest = rest.slice(dateMatch[0].length).trim();
    }

    let kind: TodoKind = 'brick';
    const kindMatch = /\s*·\s*`type:(brick|skill|both)`/i.exec(rest);
    if (kindMatch) {
      kind = kindMatch[1].toLowerCase() as TodoKind;
      rest = rest.replace(kindMatch[0], '').trim();
    }

    let brickId: string | undefined;
    const brickMatch = /\s*·\s*`brick:([^`]+)`/i.exec(rest);
    if (brickMatch) {
      brickId = brickMatch[1].trim();
      rest = rest.replace(brickMatch[0], '').trim();
    }

    let skillName: string | undefined;
    const skillMatch = /\s*·\s*`skill:([^`]+)`/i.exec(rest);
    if (skillMatch) {
      skillName = skillMatch[1].trim();
      rest = rest.replace(skillMatch[0], '').trim();
    }

    let note: string | undefined;
    const noteMatch = /\s*·\s*`note:([^`]+)`/i.exec(rest);
    if (noteMatch) {
      note = noteMatch[1].trim();
      rest = rest.replace(noteMatch[0], '').trim();
    }

    let title = rest;
    let details = '';
    const splitMatch = /^(?:\*\*([^*]+)\*\*|\*([^*]+)\*|([^—]+?))\s+[—–-]{1,2}\s+(.+)$/.exec(rest);
    if (splitMatch) {
      title = (splitMatch[1] || splitMatch[2] || splitMatch[3] || '').trim();
      details = splitMatch[4].trim();
    } else {
      title = rest.replace(/^\*\*|\*\*$/g, '').trim();
    }

    return {
      id,
      done,
      title,
      details,
      kind,
      createdAt,
      ...(brickId ? { brickId } : {}),
      ...(skillName ? { skillName } : {}),
      ...(note ? { note } : {}),
    };
  }

  private formatLine(item: TodoItem): string {
    const check = item.done ? 'x' : ' ';
    const dt = item.createdAt || new Date().toISOString().slice(0, 10);
    const title = cleanInline(item.title);
    const details = cleanInline(item.details);
    let line = `- [${check}] **[${item.id}]** (${dt}) **${title}**`;
    if (details) line += ` — ${details}`;
    line += ` · \`type:${item.kind || 'brick'}\``;
    if (item.brickId) line += ` · \`brick:${cleanInline(item.brickId)}\``;
    if (item.skillName) line += ` · \`skill:${cleanInline(item.skillName)}\``;
    if (item.note) line += ` · \`note:${cleanInline(item.note)}\``;
    return line;
  }

  list(): TodoItem[] {
    const raw = this.readRaw();
    const out: TodoItem[] = [];
    const lines = raw.split(/\r?\n/);
    lines.forEach((line, idx) => {
      const parsed = this.parseLine(line, idx);
      if (parsed) out.push(parsed);
    });
    return out;
  }

  add(input: { title: string; details?: string; kind?: TodoKind }): { item: TodoItem; created: boolean } {
    const title = cleanInline(input.title);
    if (!title) throw new Error('Le titre de la tâche todo.md est requis');
    const details = cleanInline(input.details || '');
    const kind: TodoKind = input.kind === 'skill' || input.kind === 'both' ? input.kind : 'brick';

    const existing = this.list().find(
      (i) => !i.done && i.title.toLowerCase() === title.toLowerCase()
    );
    if (existing) {
      return { item: existing, created: false };
    }

    const id = 'todo-' + crypto.randomBytes(3).toString('hex');
    const item: TodoItem = {
      id,
      done: false,
      title,
      details,
      kind,
      createdAt: new Date().toISOString().slice(0, 10),
    };
    const raw = this.readRaw();
    const sep = raw.endsWith('\n') || raw === '' ? '' : '\n';
    fs.writeFileSync(this.filePath, `${raw}${sep}${this.formatLine(item)}\n`, 'utf-8');
    return { item, created: true };
  }

  update(
    id: string,
    patch: { status?: 'done' | 'pending' | 'delete'; brickId?: string; skillName?: string; note?: string }
  ): { item: TodoItem | null; removed: boolean } {
    const cleanId = String(id || '').trim();
    if (!cleanId) throw new Error('Identifiant todo requis');
    const raw = this.readRaw();
    const lines = raw.split(/\r?\n/);
    let updatedItem: TodoItem | null = null;
    let found = false;
    let removed = false;

    const nextLines: string[] = [];
    lines.forEach((line, idx) => {
      const parsed = this.parseLine(line, idx);
      if (parsed && parsed.id === cleanId) {
        found = true;
        if (patch.status === 'delete') {
          removed = true;
          return;
        }
        updatedItem = {
          ...parsed,
          done: patch.status === 'done' ? true : patch.status === 'pending' ? false : parsed.done,
          ...(patch.brickId ? { brickId: patch.brickId } : {}),
          ...(patch.skillName ? { skillName: patch.skillName } : {}),
          ...(patch.note ? { note: patch.note } : {}),
        };
        nextLines.push(this.formatLine(updatedItem));
      } else {
        nextLines.push(line);
      }
    });

    if (!found) {
      throw new Error(`Élément '${cleanId}' introuvable dans todo.md`);
    }
    const content = nextLines.join('\n').replace(/\n*$/, '\n');
    fs.writeFileSync(this.filePath, content, 'utf-8');
    return { item: updatedItem, removed };
  }

  pendingContext(limit = 8): string {
    const pending = this.list().filter((i) => !i.done).slice(0, limit);
    if (!pending.length) return '';
    return pending
      .map((i) => `- [${i.id}] ${i.title}${i.details ? ` — ${i.details}` : ''} (${i.kind})`)
      .join('\n');
  }
}

export class BrickLibrary {
  workspace: string;
  root: string;

  constructor(workspace: string) {
    this.workspace = path.resolve(workspace);
    this.root = path.join(this.workspace, 'bricks');
  }

  private metaPath(id: string): string {
    return path.join(this.root, id, 'brick.json');
  }

  list(): BrickInfo[] {
    if (!fs.existsSync(this.root)) return [];
    const out: BrickInfo[] = [];
    let dirs: fs.Dirent[] = [];
    try {
      dirs = fs.readdirSync(this.root, { withFileTypes: true });
    } catch {
      return [];
    }
    for (const d of dirs) {
      if (!d.isDirectory() || !BRICK_ID_RE.test(d.name)) continue;
      const dir = path.join(this.root, d.name);
      const htmlPath = path.join(dir, 'index.html');
      if (!fs.existsSync(htmlPath)) continue;
      let meta: Partial<BrickInfo> = {};
      const mp = this.metaPath(d.name);
      if (fs.existsSync(mp)) {
        try {
          meta = JSON.parse(fs.readFileSync(mp, 'utf-8'));
        } catch {
          meta = {};
        }
      }
      out.push({
        id: d.name,
        name: String(meta.name || d.name),
        description: String(meta.description || ''),
        icon: String(meta.icon || '🧩'),
        placement: meta.placement === 'panel' ? 'panel' : 'dock',
        height: Math.min(640, Math.max(140, Number(meta.height || 280))),
        enabled: meta.enabled !== false,
        ...(meta.skill ? { skill: String(meta.skill) } : {}),
        ...(meta.todoId ? { todoId: String(meta.todoId) } : {}),
        createdAt: String(meta.createdAt || new Date().toISOString()),
        updatedAt: String(meta.updatedAt || meta.createdAt || new Date().toISOString()),
        url: `/bricks/${encodeURIComponent(d.name)}/`,
      });
    }
    out.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    return out;
  }

  get(id: string): BrickInfo | null {
    const clean = String(id || '').trim();
    if (!BRICK_ID_RE.test(clean)) return null;
    return this.list().find((b) => b.id === clean) || null;
  }

  create(input: {
    id: string;
    name: string;
    description?: string;
    icon?: string;
    html: string;
    placement?: 'dock' | 'panel';
    height?: number;
    skill?: string;
    todoId?: string;
    files?: Record<string, string>;
  }): BrickInfo {
    const rawId = slugifyId(input.id || input.name);
    if (!BRICK_ID_RE.test(rawId)) {
      throw new Error('Identifiant de brique invalide (lettres minuscules, chiffres, - ou _)');
    }
    const html = String(input.html || '').trim();
    if (!html) throw new Error('Le code HTML de la brique est requis');

    const dir = path.join(this.root, rawId);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'index.html'), html, 'utf-8');

    if (input.files && typeof input.files === 'object') {
      for (const [relRaw, body] of Object.entries(input.files)) {
        const rel = String(relRaw || '').replace(/\\/g, '/').replace(/^\/+/, '');
        if (!rel || rel === 'brick.json' || rel.includes('..') || rel.includes('\0')) continue;
        const target = path.resolve(dir, rel);
        if (!target.startsWith(path.resolve(dir) + path.sep)) continue;
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, String(body ?? ''), 'utf-8');
      }
    }

    const prev = this.get(rawId);
    const now = new Date().toISOString();
    const placement: 'dock' | 'panel' = input.placement === 'panel' ? 'panel' : 'dock';
    const meta = {
      id: rawId,
      name: cleanInline(input.name || rawId).slice(0, 80) || rawId,
      description: cleanInline(input.description || '').slice(0, 240),
      icon: cleanInline(input.icon || '🧩').slice(0, 8) || '🧩',
      placement,
      height: Math.min(640, Math.max(140, Math.round(Number(input.height || 280)))),
      enabled: true,
      ...(input.skill ? { skill: cleanInline(input.skill) } : prev?.skill ? { skill: prev.skill } : {}),
      ...(input.todoId ? { todoId: cleanInline(input.todoId) } : prev?.todoId ? { todoId: prev.todoId } : {}),
      createdAt: prev?.createdAt || now,
      updatedAt: now,
    };
    fs.writeFileSync(this.metaPath(rawId), JSON.stringify(meta, null, 2) + '\n', 'utf-8');
    return { ...meta, url: `/bricks/${encodeURIComponent(rawId)}/` };
  }

  setEnabled(id: string, enabled: boolean): BrickInfo {
    const clean = String(id || '').trim();
    const existing = this.get(clean);
    if (!existing) throw new Error(`Brique introuvable: ${clean}`);
    const mp = this.metaPath(clean);
    const updated = {
      id: existing.id,
      name: existing.name,
      description: existing.description,
      icon: existing.icon,
      placement: existing.placement,
      height: existing.height,
      enabled: Boolean(enabled),
      ...(existing.skill ? { skill: existing.skill } : {}),
      ...(existing.todoId ? { todoId: existing.todoId } : {}),
      createdAt: existing.createdAt,
      updatedAt: new Date().toISOString(),
    };
    fs.writeFileSync(mp, JSON.stringify(updated, null, 2) + '\n', 'utf-8');
    return { ...updated, url: existing.url };
  }

  delete(id: string): boolean {
    const clean = String(id || '').trim();
    if (!BRICK_ID_RE.test(clean)) return false;
    const dir = path.join(this.root, clean);
    if (!fs.existsSync(dir)) return false;
    fs.rmSync(dir, { recursive: true, force: true });
    return true;
  }

  serveFile(id: string, rel: string): { body: Buffer; ctype: string } | null {
    const clean = String(id || '').trim();
    if (!BRICK_ID_RE.test(clean)) return null;
    const dir = path.resolve(this.root, clean);
    if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return null;
    let decoded = '';
    try {
      decoded = decodeURIComponent(rel || '');
    } catch {
      return null;
    }
    if (decoded.includes('\0') || decoded.startsWith('/') || decoded.includes('..')) return null;
    let target = decoded ? path.resolve(dir, decoded) : dir;
    if (target !== dir && !target.startsWith(dir + path.sep)) return null;
    if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
      target = path.join(target, 'index.html');
    }
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) return null;
    if (path.basename(target) === 'brick.json') return null;
    const ext = path.extname(target).toLowerCase();
    return { body: fs.readFileSync(target), ctype: BRICK_MIME[ext] || 'application/octet-stream' };
  }

  index(): string {
    const items = this.list();
    if (!items.length) return '';
    return items
      .map((b) => `- ${b.icon} ${b.id} (${b.name}${b.enabled ? '' : ', masquée'}): ${b.description}`)
      .join('\n');
  }
}

export function createWorkspaceSkill(
  workspace: string,
  skillsLib: SkillLibrary,
  opts: { name: string; description: string; instructions: string }
): { name: string; relPath: string } {
  const name = slugifyId(opts.name).replace(/-/g, '-');
  if (!SKILL_NAME_RE.test(name)) {
    throw new Error('Nom de skill invalide (ex: mon-skill)');
  }
  const description = cleanInline(opts.description);
  if (!description) throw new Error('Description du skill requise');
  const instructions = String(opts.instructions || '').trim();
  if (!instructions) throw new Error('Instructions du skill requises');

  const dir = path.join(path.resolve(workspace), 'skills', name);
  fs.mkdirSync(dir, { recursive: true });
  const filePath = path.join(dir, 'SKILL.md');
  const content = `---\nname: ${name}\ndescription: ${JSON.stringify(description)}\n---\n\n${instructions}\n`;
  fs.writeFileSync(filePath, content, 'utf-8');
  skillsLib.reload();
  return { name, relPath: `skills/${name}/SKILL.md` };
}

export interface CommunityItem {
  id: string;
  type: 'brick' | 'skill';
  name: string;
  description: string;
  icon: string;
  author: string;
  version: string;
  updatedAt: string;
  html?: string;
  instructions?: string;
  files?: Record<string, string>;
  sourceUrl?: string;
}

const DEFAULT_COMMUNITY_ITEMS: CommunityItem[] = [
  {
    id: 'pomodoro-timer',
    type: 'brick',
    name: 'Pomodoro Focus Timer',
    description: 'Timer Pomodoro interactif avec pauses travail/repos, notifications et thème adaptatif.',
    icon: '⏱️',
    author: 'lanoixdesign',
    version: '1.2.0',
    updatedAt: new Date().toISOString(),
    html: '<' + '!doctype html>\n' +
      '<html lang="fr">\n' +
      '<head>\n' +
      '<meta charset="utf-8">\n' +
      '<style>\n' +
      ':root{--bg:#f8f9fa;--text:#212529;--card:#ffffff;--accent:#3b82f6;--border:#dee2e6}\n' +
      '@media(prefers-color-scheme:dark){:root{--bg:#121212;--text:#e0e0e0;--card:#1e1e1e;--accent:#60a5fa;--border:#333}}\n' +
      'body{margin:0;padding:16px;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;box-sizing:border-box}\n' +
      '.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;width:100%;max-width:320px;text-align:center;box-shadow:0 4px 12px rgba(0,0,0,0.05)}\n' +
      'h2{margin:0 0 8px 0;font-size:18px}\n' +
      '.timer{font-size:42px;font-weight:700;margin:16px 0;color:var(--accent);font-variant-numeric:tabular-nums}\n' +
      '.btn{background:var(--accent);color:#fff;border:none;padding:8px 16px;border-radius:6px;font-weight:600;cursor:pointer;margin:4px}\n' +
      '.btn:hover{opacity:0.9}\n' +
      '</style>\n' +
      '</head>\n' +
      '<body>\n' +
      '<div class="card">\n' +
      '  <h2>⏱️ Pomodoro Timer</h2>\n' +
      '  <div class="timer" id="time">25:00</div>\n' +
      '  <button class="btn" id="startBtn">Démarrer</button>\n' +
      '  <button class="btn" id="resetBtn" style="background:#6c757d">Réinitialiser</button>\n' +
      '</div>\n' +
      '<script>\n' +
      'let seconds = 1500;\n' +
      'let timerId = null;\n' +
      'const timeEl = document.getElementById(\'time\');\n' +
      'const startBtn = document.getElementById(\'startBtn\');\n' +
      'function update(){\n' +
      '  const m = Math.floor(seconds/60).toString().padStart(2,\'0\');\n' +
      '  const s = (seconds%60).toString().padStart(2,\'0\');\n' +
      '  timeEl.textContent = m + \':\' + s;\n' +
      '}\n' +
      'startBtn.addEventListener(\'click\', () => {\n' +
      '  if(timerId){\n' +
      '    clearInterval(timerId);\n' +
      '    timerId = null;\n' +
      '    startBtn.textContent = \'Démarrer\';\n' +
      '  } else {\n' +
      '    startBtn.textContent = \'Pause\';\n' +
      '    timerId = setInterval(() => {\n' +
      '      if(seconds > 0) { seconds--; update(); }\n' +
      '      else { clearInterval(timerId); alert(\'Temps écoulé !\'); }\n' +
      '    }, 1000);\n' +
      '  }\n' +
      '});\n' +
      'document.getElementById(\'resetBtn\').addEventListener(\'click\', () => {\n' +
      '  if(timerId) { clearInterval(timerId); timerId = null; }\n' +
      '  seconds = 1500;\n' +
      '  startBtn.textContent = \'Démarrer\';\n' +
      '  update();\n' +
      '});\n' +
      'window.addEventListener(\'message\', e => {\n' +
      '  if(e.data?.type === \'brick:init\'){\n' +
      '    if(e.data.theme) document.documentElement.setAttribute(\'data-theme\', e.data.theme);\n' +
      '  }\n' +
      '});\n' +
      '</script>\n' +
      '</body>\n' +
      '</html>'
  },
  {
    id: 'json-formatter',
    type: 'brick',
    name: 'JSON Formatter & Validator',
    description: 'Validez, formatez et inspectez vos structures JSON en un clic avec coloration d’erreurs.',
    icon: '📋',
    author: 'community-dev',
    version: '1.0.1',
    updatedAt: new Date().toISOString(),
    html: '<' + '!doctype html>\n' +
      '<html lang="fr">\n' +
      '<head>\n' +
      '<meta charset="utf-8">\n' +
      '<style>\n' +
      ':root{--bg:#f8f9fa;--text:#212529;--card:#ffffff;--accent:#10b981;--border:#dee2e6}\n' +
      '@media(prefers-color-scheme:dark){:root{--bg:#121212;--text:#e0e0e0;--card:#1e1e1e;--accent:#34d399;--border:#333}}\n' +
      'body{margin:0;padding:12px;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;box-sizing:border-box;height:100vh;display:flex;flex-direction:column}\n' +
      'textarea{width:100%;flex:1;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px;font-family:monospace;font-size:13px;resize:none;box-sizing:border-box}\n' +
      '.bar{display:flex;gap:8px;margin-bottom:8px}\n' +
      'button{background:var(--accent);color:#fff;border:none;padding:6px 12px;border-radius:6px;font-weight:600;cursor:pointer}\n' +
      '#status{font-size:12px;color:var(--accent);align-self:center}\n' +
      '</style>\n' +
      '</head>\n' +
      '<body>\n' +
      '<div class="bar">\n' +
      '  <button id="fmt">Formater / Valider</button>\n' +
      '  <span id="status">Prêt</span>\n' +
      '</div>\n' +
      '<textarea id="box">{"exemple": true, "items": [1, 2, 3]}</textarea>\n' +
      '<script>\n' +
      'document.getElementById(\'fmt\').addEventListener(\'click\', () => {\n' +
      '  const box = document.getElementById(\'box\');\n' +
      '  const st = document.getElementById(\'status\');\n' +
      '  try {\n' +
      '    const obj = JSON.parse(box.value);\n' +
      '    box.value = JSON.stringify(obj, null, 2);\n' +
      '    st.style.color = \'var(--accent)\';\n' +
      '    st.textContent = \'JSON Valide ✓\';\n' +
      '  } catch(e) {\n' +
      '    st.style.color = \'#ef4444\';\n' +
      '    st.textContent = \'Erreur: \' + e.message;\n' +
      '  }\n' +
      '});\n' +
      '</script>\n' +
      '</body>\n' +
      '</html>'
  },
  {
    id: 'git-expert-skill',
    type: 'skill',
    name: 'git-expert',
    description: 'Skill avancé pour l’analyse de commits Git, résolution de conflits et stratégies de merge.',
    icon: '📊',
    author: 'agent-ecosystem',
    version: '1.1.0',
    updatedAt: new Date().toISOString(),
    instructions: '---\n' +
      'name: git-expert\n' +
      'description: "Expert en gestion de versions Git, analyse de diffs et résolution de conflits complexes."\n' +
      '---\n\n' +
      '# Git Expert Skill\n\n' +
      'Utilisez cet ensemble de directives pour assister l\'utilisateur dans :\n' +
      '1. L\'analyse des modifications en cours via git status et git diff.\n' +
      '2. La proposition de messages de commit clairs et standardisés (Conventional Commits).\n' +
      '3. La gestion des branches, rebases et résolution sécurisée des conflits.'
  }
];

export class CommunityHub {
  workspace: string;
  stateDir: string;
  cachePath: string;

  constructor(workspace: string, stateDir: string) {
    this.workspace = path.resolve(workspace);
    this.stateDir = path.resolve(stateDir);
    this.cachePath = path.join(this.stateDir, 'community-registry.json');
    this.ensureCache();
  }

  ensureCache(): void {
    fs.mkdirSync(this.stateDir, { recursive: true });
    if (!fs.existsSync(this.cachePath)) {
      const data = {
        lastSync: new Date(0).toISOString(),
        items: DEFAULT_COMMUNITY_ITEMS,
      };
      fs.writeFileSync(this.cachePath, JSON.stringify(data, null, 2), 'utf-8');
    }
  }

  readCache(): { lastSync: string; items: CommunityItem[] } {
    this.ensureCache();
    try {
      return JSON.parse(fs.readFileSync(this.cachePath, 'utf-8'));
    } catch {
      return { lastSync: new Date(0).toISOString(), items: DEFAULT_COMMUNITY_ITEMS };
    }
  }

  writeCache(data: { lastSync: string; items: CommunityItem[] }): void {
    fs.mkdirSync(this.stateDir, { recursive: true });
    fs.writeFileSync(this.cachePath, JSON.stringify(data, null, 2), 'utf-8');
  }

  async sync(force = false): Promise<{ items: CommunityItem[]; lastSync: string; count: number; synced: boolean }> {
    const cache = this.readCache();
    const now = Date.now();
    const lastSyncMs = new Date(cache.lastSync || 0).getTime();
    const oneDayMs = 24 * 60 * 60 * 1000;

    if (!force && (now - lastSyncMs < oneDayMs) && cache.items.length > 0) {
      return { items: cache.items, lastSync: cache.lastSync, count: cache.items.length, synced: false };
    }

    let items = [...DEFAULT_COMMUNITY_ITEMS];
    let synced = true;

    try {
      const res = await fetch('https://raw.githubusercontent.com/lanoixdesign/autonomous-agent-hub/main/registry.json', {
        signal: AbortSignal.timeout(6000),
        headers: { 'User-Agent': 'autonomous-agent-hub-sync' }
      });
      if (res.ok) {
        const remote = await res.json();
        if (Array.isArray(remote) && remote.length > 0) {
          items = remote;
        }
      }
    } catch {
      // Offline fallback
    }

    const newSync = new Date().toISOString();
    this.writeCache({ lastSync: newSync, items });
    return { items, lastSync: newSync, count: items.length, synced };
  }

  importItem(
    id: string,
    bricksLib: BrickLibrary,
    skillsLib: SkillLibrary
  ): { ok: boolean; type: string; id: string; name: string } {
    const cleanId = String(id || '').trim();
    const cache = this.readCache();
    const item = cache.items.find((i) => i.id === cleanId);
    if (!item) {
      throw new Error('Élément communautaire \'' + cleanId + '\' introuvable');
    }

    if (item.type === 'brick') {
      if (!item.html) throw new Error('Code HTML de la brique manquant');
      bricksLib.create({
        id: item.id,
        name: item.name,
        description: item.description,
        icon: item.icon || '🧩',
        html: item.html,
        placement: 'dock',
      });
      return { ok: true, type: 'brick', id: item.id, name: item.name };
    } else if (item.type === 'skill') {
      if (!item.instructions) throw new Error('Instructions du skill manquantes');
      const targetDir = path.join(this.workspace, 'skills', item.id);
      fs.mkdirSync(targetDir, { recursive: true });
      fs.writeFileSync(path.join(targetDir, 'SKILL.md'), item.instructions, 'utf-8');
      skillsLib.reload();
      return { ok: true, type: 'skill', id: item.id, name: item.name };
    } else {
      throw new Error('Type d’élément non supporté');
    }
  }

  async publishToGitHub(
    kind: 'brick' | 'skill',
    id: string,
    bricksLib: BrickLibrary,
    skillsLib: SkillLibrary,
    token?: string,
    repo = 'lanoixdesign/autonomous-agent-hub'
  ): Promise<{ ok: boolean; url: string; message: string }> {
    const cleanId = String(id || '').trim();
    let payload: CommunityItem;

    if (kind === 'brick') {
      const b = bricksLib.get(cleanId);
      if (!b) throw new Error('Brique introuvable: ' + cleanId);
      const filePath = path.join(bricksLib.root, cleanId, 'index.html');
      const html = fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf-8') : '';
      payload = {
        id: b.id,
        type: 'brick',
        name: b.name,
        description: b.description,
        icon: b.icon,
        author: 'local-user',
        version: '1.0.0',
        updatedAt: b.updatedAt,
        html,
      };
    } else {
      skillsLib.reload();
      const sk = skillsLib.listDetailed().find((s) => s.name === cleanId);
      if (!sk) throw new Error('Skill introuvable: ' + cleanId);
      const instructions = fs.existsSync(sk.path) ? fs.readFileSync(sk.path, 'utf-8') : '';
      payload = {
        id: cleanId,
        type: 'skill',
        name: cleanId,
        description: sk.description,
        icon: '📚',
        author: 'local-user',
        version: '1.0.0',
        updatedAt: new Date().toISOString(),
        instructions,
      };
    }

    const githubToken = (token || process.env.GITHUB_TOKEN || '').trim();
    if (githubToken) {
      try {
        const pathInRepo = kind + 's/' + payload.id + '.json';
        const apiUri = 'https://api.github.com/repos/' + repo + '/contents/' + pathInRepo;
        let sha: string | undefined;
        const getRes = await fetch(apiUri, {
          headers: { Authorization: 'Bearer ' + githubToken, 'User-Agent': 'autonomous-agent', Accept: 'application/vnd.github+json' }
        });
        if (getRes.ok) {
          const fileData = await getRes.json();
          sha = fileData.sha;
        }

        const putRes = await fetch(apiUri, {
          method: 'PUT',
          headers: {
            Authorization: 'Bearer ' + githubToken,
            'User-Agent': 'autonomous-agent',
            'Content-Type': 'application/json',
            Accept: 'application/vnd.github+json',
          },
          body: JSON.stringify({
            message: 'Publish ' + kind + ' ' + payload.id + ' from Autonomous Agent',
            content: Buffer.from(JSON.stringify(payload, null, 2)).toString('base64'),
            ...(sha ? { sha } : {}),
          }),
        });

        if (putRes.ok) {
          return {
            ok: true,
            url: 'https://github.com/' + repo + '/blob/main/' + pathInRepo,
            message: 'Publication réussie sur le dépôt GitHub ' + repo + ' !',
          };
        }
      } catch {
        // fallback
      }
    }

    const cache = this.readCache();
    const existingIdx = cache.items.findIndex(i => i.id === payload.id && i.type === payload.type);
    if (existingIdx >= 0) {
      cache.items[existingIdx] = payload;
    } else {
      cache.items.unshift(payload);
    }
    this.writeCache(cache);

    return {
      ok: true,
      url: 'https://github.com/' + repo,
      message: 'Élément \'' + payload.id + '\' préparé et enregistré dans le registre local communautaire (prêt pour partage GitHub).',
    };
  }
}
