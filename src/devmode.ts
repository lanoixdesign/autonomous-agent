import { exec } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

export const KINDS = ['web', 'python'] as const;
export const PROJECTS_ROOT = 'projects';
export const PREVIEW_CSP =
  "sandbox allow-scripts allow-forms allow-modals; default-src 'self' data: blob:; " +
  "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
  "font-src 'self' data:; media-src 'self' data: blob:; connect-src 'none'; form-action 'none'; " +
  "frame-ancestors 'self'; base-uri 'none'";

export class DevError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export function slug(name: string): string {
  const map: Record<string, string> = {
    à: 'a', â: 'a', ä: 'a', á: 'a', ã: 'a', å: 'a', ç: 'c',
    é: 'e', è: 'e', ê: 'e', ë: 'e', í: 'i', ì: 'i', î: 'i', ï: 'i',
    ñ: 'n', ó: 'o', ò: 'o', ô: 'o', ö: 'o', õ: 'o', ú: 'u', ù: 'u',
    û: 'u', ü: 'u', ý: 'y', ÿ: 'y', œ: 'oe', æ: 'ae',
  };
  return (name || '')
    .trim()
    .toLowerCase()
    .replace(/[àâäáãåçéèêëíìîïñóòôöõúùûüýÿœæ]/g, (ch) => map[ch] || ch)
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
}

const TEMPLATES_TEXT: Record<'en' | 'fr', Record<string, string>> = {
  en: {
    hello: 'Hello!',
    lead: 'This page was created by your assistant. Ask it to change anything.',
    button: 'Click me',
    clicked: 'Thanks for clicking! ({n})',
    footer: 'Made with Autonomous Agent',
    py_readme: 'A small Python program.\n\nRun it: `python main.py`\nTest it: `python -m unittest`\n',
    greet: 'Hello, {name}!',
    world: 'world',
    doc: 'Return a friendly greeting.',
  },
  fr: {
    hello: 'Bonjour !',
    lead: 'Cette page a été créée par ton assistant. Demande-lui de changer ce que tu veux.',
    button: 'Clique ici',
    clicked: 'Merci pour le clic ! ({n})',
    footer: 'Fait avec Autonomous Agent',
    py_readme: 'Un petit programme Python.\n\nLancer : `python main.py`\nTester : `python -m unittest`\n',
    greet: 'Bonjour, {name} !',
    world: 'tout le monde',
    doc: 'Renvoie une salutation amicale.',
  },
};

function makeTemplate(kind: string, name: string, lang: 'en' | 'fr'): Record<string, string> {
  const t = TEMPLATES_TEXT[lang] || TEMPLATES_TEXT.en;
  if (kind === 'web') {
    return {
      'index.html': `<!doctype html>
<html lang="${lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${name}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main class="card">
    <h1>${t.hello}</h1>
    <p>${t.lead}</p>
    <button id="btn" type="button">${t.button}</button>
    <p id="out" aria-live="polite"></p>
  </main>
  <footer>${t.footer}</footer>
  <script src="script.js"></script>
</body>
</html>
`,
      'style.css': `:root { color-scheme: light dark; --bg: #f6f7fb; --fg: #1d2330; --card: #fff; --accent: #4f6bed; }
@media (prefers-color-scheme: dark) { :root { --bg: #12151c; --fg: #e8ebf2; --card: #1c212b; --accent: #8ea2ff; } }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); padding: 24px; }
.card { background: var(--card); border-radius: 16px; padding: 32px; max-width: 520px; width: 100%; box-shadow: 0 8px 30px rgba(0,0,0,.08); text-align: center; }
h1 { margin-top: 0; }
button { background: var(--accent); color: #fff; border: 0; border-radius: 999px; padding: 12px 22px; font-size: 1rem; cursor: pointer; }
footer { margin-top: 18px; opacity: .6; font-size: .85rem; }
`,
      'script.js': `let clicks = 0;
document.getElementById("btn").addEventListener("click", () => {
  clicks += 1;
  document.getElementById("out").textContent = ${JSON.stringify(t.clicked)}.replace("{n}", String(clicks));
});
`,
    };
  }
  if (kind === 'python') {
    return {
      'main.py': `def greet(name: str) -> str:\n    return f"${t.greet}"\n\nif __name__ == "__main__":\n    print(greet("${t.world}"))\n`,
      'test_main.py': `import unittest\nfrom main import greet\n\nclass GreetTest(unittest.TestCase):\n    def test_greet(self):\n        self.assertEqual(greet("Ada"), "${t.greet.replace('{name}', 'Ada')}")\n\nif __name__ == "__main__":\n    unittest.main()\n`,
      'README.md': `# ${name}\n\n${t.py_readme}`,
    };
  }
  throw new DevError('bad_kind', 'kind must be web or python');
}

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i];
    for (let k = 0; k < 8; k++) {
      c = (c >>> 1) ^ (c & 1 ? 0xedb88320 : 0);
    }
  }
  return (c ^ 0xffffffff) >>> 0;
}

function buildZip(entries: Array<{ name: string; data: Buffer }>): Buffer {
  const localParts: Buffer[] = [];
  const centralParts: Buffer[] = [];
  let offset = 0;
  for (const e of entries) {
    const nameBuf = Buffer.from(e.name, 'utf-8');
    const compressed = zlib.deflateRawSync(e.data);
    const crc = crc32(e.data);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(e.data.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28);
    localParts.push(local, nameBuf, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(e.data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);
    centralParts.push(central, nameBuf);

    offset += local.length + nameBuf.length + compressed.length;
  }
  const centralBuf = Buffer.concat(centralParts);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(centralBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  eocd.writeUInt16LE(0, 20);
  return Buffer.concat([...localParts, centralBuf, eocd]);
}

const MIME_MAP: Record<string, string> = {
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

export class Projects {
  ws: string;
  root: string;
  secret: Buffer;

  constructor(workspace: string) {
    this.ws = path.resolve(workspace);
    this.root = path.join(this.ws, PROJECTS_ROOT);
    this.secret = crypto.randomBytes(32);
  }

  path(name: string): string {
    if (!name || slug(name) !== name) throw new DevError('bad_name', 'unknown project');
    const p = path.join(this.root, name);
    if (!fs.existsSync(p) || !fs.statSync(p).isDirectory()) throw new DevError('no_project', 'unknown project');
    return p;
  }

  static kindOf(p: string): string {
    if (fs.existsSync(path.join(p, 'index.html'))) return 'web';
    if (fs.readdirSync(p).some((f) => f.endsWith('.py'))) return 'python';
    return 'other';
  }

  private filesOf(p: string): string[] {
    const out: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
        if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === '__pycache__' || entry.isSymbolicLink()) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.isFile()) out.push(full);
      }
    };
    walk(p);
    return out;
  }

  info(p: string) {
    const files = this.filesOf(p);
    const kind = Projects.kindOf(p);
    const name = path.basename(p);
    let mtime = fs.statSync(p).mtimeMs;
    let bytes = 0;
    for (const q of files) {
      const st = fs.statSync(q);
      bytes += st.size;
      if (st.mtimeMs > mtime) mtime = st.mtimeMs;
    }
    return {
      name,
      kind,
      files: files.length,
      bytes,
      mtime: Math.floor(mtime / 1000),
      path: `${PROJECTS_ROOT}/${name}`,
      list: files.slice(0, 30).map((q) => path.relative(p, q).split(path.sep).join('/')),
      preview: kind === 'web' ? this.previewUrl(name) : null,
      tests: kind === 'python' || kind === 'web',
    };
  }

  list() {
    if (!fs.existsSync(this.root)) return [];
    const items = fs
      .readdirSync(this.root, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith('.') && slug(d.name) === d.name)
      .slice(0, 200)
      .map((d) => this.info(path.join(this.root, d.name)));
    items.sort((a, b) => b.mtime - a.mtime);
    return items;
  }

  create(name: string, kind: string, lang = 'en') {
    if (!KINDS.includes(kind as any)) throw new DevError('bad_kind', 'kind must be web or python');
    const s = slug(name);
    if (!s) throw new DevError('bad_name', 'give the project a name (letters or numbers)');
    const p = path.join(this.root, s);
    if (fs.existsSync(p)) throw new DevError('exists', `a project named ${s} already exists`);
    const files = makeTemplate(kind, (name || s).trim().slice(0, 60), lang === 'fr' ? 'fr' : 'en');
    fs.mkdirSync(p, { recursive: true });
    for (const [rel, text] of Object.entries(files)) {
      fs.writeFileSync(path.join(p, rel), text, 'utf-8');
    }
    return this.info(p);
  }

  token(name: string): string {
    return crypto.createHmac('sha256', this.secret).update(`preview:${name}`).digest('hex').slice(0, 24);
  }

  previewUrl(name: string): string {
    return `/preview/${this.token(name)}/${name}/`;
  }

  previewFile(tok: string, name: string, rel: string): { body: Buffer; ctype: string } {
    if (tok !== this.token(name)) throw new DevError('no_project', 'not found');
    const p = this.path(name);
    const decoded = decodeURIComponent(rel || '');
    if (decoded.includes('\0') || decoded.startsWith('/') || decoded.includes('..')) {
      throw new DevError('not_found', 'not found');
    }
    let target = decoded ? path.resolve(p, decoded) : p;
    if (!target.startsWith(path.resolve(p))) throw new DevError('not_found', 'not found');
    if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
      target = path.join(target, 'index.html');
    }
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) throw new DevError('not_found', 'not found');
    const ext = path.extname(target).toLowerCase();
    return { body: fs.readFileSync(target), ctype: MIME_MAP[ext] || 'application/octet-stream' };
  }

  zip(name: string): { body: Buffer; filename: string } {
    const p = this.path(name);
    const files = this.filesOf(p);
    const entries = files.map((q) => ({
      name: `${name}/${path.relative(p, q).split(path.sep).join('/')}`,
      data: fs.readFileSync(q),
    }));
    return { body: buildZip(entries), filename: `${name}.zip` };
  }

  async test(name: string): Promise<Record<string, any>> {
    const p = this.path(name);
    const kind = Projects.kindOf(p);
    if (kind === 'web') {
      const files = this.filesOf(p);
      const hasIndex = fs.existsSync(path.join(p, 'index.html'));
      return {
        ok: hasIndex,
        runner: 'web-check',
        output: hasIndex ? `OK: index.html present (${files.length} files)` : 'Missing index.html',
      };
    }
    return new Promise((resolve) => {
      exec('python3 -m unittest', { cwd: p, timeout: 15000 }, (err, stdout, stderr) => {
        resolve({
          ok: !err,
          runner: 'unittest',
          output: ((stdout || '') + (stderr ? '\n' + stderr : '')).slice(0, 4000),
        });
      });
    });
  }
}

export function devRules(project: string, kind: string | null, lang = 'en'): string {
  const folder = `${PROJECTS_ROOT}/${project}/`;
  return lang === 'fr'
    ? `Mode développeur actif pour le projet "${project}" (${kind || 'web'}). Crée et modifie uniquement les fichiers dans ${folder}.`
    : `Developer mode active for project "${project}" (${kind || 'web'}). Create and edit files ONLY inside ${folder}.`;
}
