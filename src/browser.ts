import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { matchDomain } from './permissions.js';

export interface BrowserLink {
  text: string;
  url: string;
}

export interface BrowserControl {
  tag: string;
  role: string;
  text: string;
  selector: string;
  value?: string;
  options?: string[];
}

export interface BrowserHistoryEntry {
  id: string;
  url: string;
  finalUrl: string;
  title: string;
  status: number | null;
  ts: string;
  source: 'user' | 'agent';
  shotPath: string | null;
  links: BrowserLink[];
  excerpt: string[];
  controls: BrowserControl[];
  scrollY: number;
  scrollHeight: number;
  viewportHeight: number;
}

export interface BrowserActionResult {
  title: string;
  finalUrl: string;
  status: number | null;
  paragraphs: string[];
  links: BrowserLink[];
  controls: BrowserControl[];
  entryId: string;
  scrollY: number;
  scrollHeight: number;
  viewportHeight: number;
}

export async function loadPlaywright(): Promise<any> {
  const pwPath = '/usr/local/share/bun-global/node_modules/playwright-core/index.mjs';
  const pwFallback = 'playwright-core';
  return await import(fs.existsSync(pwPath) ? pwPath : pwFallback);
}

export function findChromiumExecutable(pw: any): string | undefined {
  try {
    const defExe = pw.chromium?.executablePath?.();
    if (defExe && fs.existsSync(defExe)) return defExe;
  } catch {
    // ignore
  }
  const known = '/ms-playwright/chromium_headless_shell-1247/chrome-headless-shell-linux64/chrome-headless-shell';
  if (fs.existsSync(known)) return known;
  if (fs.existsSync('/ms-playwright')) {
    for (const dir of fs.readdirSync('/ms-playwright')) {
      const cand1 = path.join('/ms-playwright', dir, 'chrome-headless-shell-linux64', 'chrome-headless-shell');
      const cand2 = path.join('/ms-playwright', dir, 'chrome-linux64', 'chrome');
      if (fs.existsSync(cand1)) return cand1;
      if (fs.existsSync(cand2)) return cand2;
    }
  }
  return undefined;
}

class BrowserController {
  visible = true;
  userControl = false;
  history: BrowserHistoryEntry[] = [];
  cursor = -1;
  private browser: any = null;
  private context: any = null;
  private page: any = null;
  private lastStatus: number | null = null;
  private domains = new Map<string, { domain: string; count: number; last_url: string }>();
  private cacheDir = path.resolve(process.env.AGENT_STATE || path.join(process.cwd(), '.agent'), 'browser');
  private opQueue: Promise<any> = Promise.resolve();

  constructor() {
    const cleanup = () => {
      try {
        void this.browser?.close?.();
      } catch {
        // ignore
      }
    };
    process.once('exit', cleanup);
  }

  setCacheDir(stateDir: string): void {
    this.cacheDir = path.join(path.resolve(stateDir), 'browser');
  }

  private withLock<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.opQueue.then(fn, fn);
    this.opQueue = run.catch(() => {});
    return run;
  }

  private async ensurePage(): Promise<any> {
    if (this.page && !this.page.isClosed?.()) {
      return this.page;
    }
    if (this.browser) {
      try {
        await this.browser.close();
      } catch {
        // ignore
      }
      this.browser = null;
      this.context = null;
      this.page = null;
    }
    const pw = await loadPlaywright();
    const executablePath = findChromiumExecutable(pw);
    this.browser = await pw.chromium.launch({
      ...(executablePath ? { executablePath } : {}),
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    });
    this.context = await this.browser.newContext({
      viewport: { width: 1280, height: 800 },
      userAgent:
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    });
    this.page = await this.context.newPage();
    this.page.on('response', (res: any) => {
      try {
        if (res.frame() === this.page.mainFrame() && res.request().isNavigationRequest()) {
          this.lastStatus = res.status();
        }
      } catch {
        // ignore
      }
    });
    return this.page;
  }

  private async settle(page: any, waitMs = 350): Promise<void> {
    try {
      await page.waitForLoadState('domcontentloaded', { timeout: 3000 });
    } catch {
      // ignore
    }
    if (waitMs > 0) {
      await page.waitForTimeout(Math.min(5000, Math.max(0, waitMs)));
    }
  }

  private async captureAndInspect(opts: {
    page: any;
    source: 'user' | 'agent';
    requestedUrl?: string;
    pushHistory?: boolean;
  }): Promise<BrowserActionResult> {
    const { page } = opts;
    fs.mkdirSync(this.cacheDir, { recursive: true });
    const cacheShotPath = path.join(
      this.cacheDir,
      `shot-${Date.now()}-${crypto.randomBytes(3).toString('hex')}.png`
    );

    await page.screenshot({
      path: cacheShotPath,
      type: 'png',
    });

    const title = (await page.title().catch(() => '')) || '(sans titre)';
    const finalUrl = page.url() || opts.requestedUrl || 'about:blank';
    const status = this.lastStatus;

    const extracted: {
      paragraphs: string[];
      links: BrowserLink[];
      controls: BrowserControl[];
      scrollY: number;
      scrollHeight: number;
      viewportHeight: number;
    } = await page.evaluate(() => {
      const paragraphs: string[] = [];
      const seenText = new Set<string>();
      for (const el of Array.from(document.querySelectorAll('h1, h2, h3, p, li, article'))) {
        const txt = (el as HTMLElement).innerText?.replace(/\s+/g, ' ').trim();
        if (txt && txt.length >= 15 && !seenText.has(txt)) {
          seenText.add(txt);
          paragraphs.push(txt);
          if (paragraphs.length >= 12) break;
        }
      }
      if (!paragraphs.length) {
        const raw = (document.body?.innerText || '').replace(/\s+\n/g, '\n').trim();
        if (raw) {
          for (const line of raw.split(/\n+/).map((x) => x.trim()).filter(Boolean).slice(0, 12)) {
            paragraphs.push(line);
          }
        }
      }

      const links: Array<{ text: string; url: string }> = [];
      const seenUrl = new Set<string>();
      for (const a of Array.from(document.querySelectorAll('a[href]'))) {
        const href = (a as HTMLAnchorElement).href;
        if (!href || !/^https?:\/\//i.test(href) || seenUrl.has(href)) continue;
        const label = ((a as HTMLElement).innerText || a.getAttribute('aria-label') || href)
          .replace(/\s+/g, ' ')
          .trim()
          .slice(0, 60);
        if (!label) continue;
        seenUrl.add(href);
        links.push({ text: label, url: href });
        if (links.length >= 14) break;
      }

      const controls: Array<{
        tag: string;
        role: string;
        text: string;
        selector: string;
        value?: string;
        options?: string[];
      }> = [];
      for (const el of Array.from(
        document.querySelectorAll('a[href], button, input, select, textarea, [role="button"]')
      )) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const style = getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none') continue;
        const tag = el.tagName.toLowerCase();
        const type = el.getAttribute('type') || '';
        const role = type ? `${tag}[${type}]` : tag;
        const label = (
          (el as HTMLElement).innerText ||
          el.getAttribute('aria-label') ||
          el.getAttribute('placeholder') ||
          el.getAttribute('title') ||
          el.getAttribute('name') ||
          (el as HTMLInputElement).value ||
          ''
        )
          .replace(/\s+/g, ' ')
          .trim()
          .slice(0, 80);

        let selector = '';
        if ((el as HTMLElement).id) {
          selector = `#${CSS.escape((el as HTMLElement).id)}`;
        } else {
          const nameAttr = el.getAttribute('name');
          const dtAttr = el.getAttribute('data-testid');
          const ariaAttr = el.getAttribute('aria-label');
          if (nameAttr && document.querySelectorAll(`${tag}[name="${CSS.escape(nameAttr)}"]`).length === 1) {
            selector = `${tag}[name="${CSS.escape(nameAttr)}"]`;
          } else if (dtAttr) {
            selector = `[data-testid="${CSS.escape(dtAttr)}"]`;
          } else if (ariaAttr && document.querySelectorAll(`${tag}[aria-label="${CSS.escape(ariaAttr)}"]`).length === 1) {
            selector = `${tag}[aria-label="${CSS.escape(ariaAttr)}"]`;
          } else {
            const parts: string[] = [];
            let cur: Element | null = el;
            while (cur && cur !== document.body && parts.length < 4) {
              if ((cur as HTMLElement).id) {
                parts.unshift(`#${CSS.escape((cur as HTMLElement).id)}`);
                break;
              }
              const cTag = cur.tagName.toLowerCase();
              const parent: Element | null = cur.parentElement;
              if (!parent) {
                parts.unshift(cTag);
                break;
              }
              const siblings = Array.from(parent.children).filter((s) => s.tagName === cur!.tagName);
              const idx = siblings.indexOf(cur) + 1;
              parts.unshift(siblings.length > 1 ? `${cTag}:nth-of-type(${idx})` : cTag);
              cur = parent;
            }
            selector = parts.join(' > ') || tag;
          }
        }

        const entry: any = {
          tag,
          role,
          text: label,
          selector,
        };
        if (tag === 'input' || tag === 'textarea') {
          if (type !== 'password') entry.value = String((el as HTMLInputElement).value || '').slice(0, 60);
        } else if (tag === 'select') {
          const sel = el as HTMLSelectElement;
          entry.value = sel.value;
          entry.options = Array.from(sel.options)
            .slice(0, 12)
            .map((o) => `${o.value}=${o.text.trim()}`);
        }
        controls.push(entry);
        if (controls.length >= 25) break;
      }

      return {
        paragraphs,
        links,
        controls,
        scrollY: Math.round(window.scrollY || 0),
        scrollHeight: Math.round(document.documentElement?.scrollHeight || document.body?.scrollHeight || 0),
        viewportHeight: Math.round(window.innerHeight || 800),
      };
    });

    const id = crypto.randomBytes(6).toString('hex');
    const prev = this.current();
    const shouldPush =
      opts.pushHistory !== undefined
        ? opts.pushHistory
        : !prev || prev.finalUrl !== finalUrl;

    const entry: BrowserHistoryEntry = {
      id,
      url: opts.requestedUrl || finalUrl,
      finalUrl,
      title,
      status,
      ts: new Date().toISOString(),
      source: opts.source,
      shotPath: cacheShotPath,
      links: extracted.links,
      excerpt: extracted.paragraphs.slice(0, 4),
      controls: extracted.controls,
      scrollY: extracted.scrollY,
      scrollHeight: extracted.scrollHeight,
      viewportHeight: extracted.viewportHeight,
    };

    if (shouldPush) {
      if (this.cursor < this.history.length - 1) {
        this.history = this.history.slice(0, this.cursor + 1);
      }
      this.history.push(entry);
      if (this.history.length > 50) this.history = this.history.slice(-50);
      this.cursor = this.history.length - 1;
    } else if (this.cursor >= 0 && this.cursor < this.history.length) {
      // Update the current entry in-place (scroll/type/click on same URL) with fresh screenshot & DOM
      this.history[this.cursor] = entry;
    } else {
      this.history.push(entry);
      this.cursor = this.history.length - 1;
    }

    try {
      const host = new URL(finalUrl).hostname.toLowerCase();
      if (host) {
        const prevDom = this.domains.get(host);
        this.domains.set(host, {
          domain: host,
          count: (prevDom?.count || 0) + 1,
          last_url: finalUrl,
        });
      }
    } catch {
      // ignore
    }

    this.pruneOldShots();

    return {
      title,
      finalUrl,
      status,
      paragraphs: extracted.paragraphs,
      links: extracted.links,
      controls: extracted.controls,
      entryId: id,
      scrollY: extracted.scrollY,
      scrollHeight: extracted.scrollHeight,
      viewportHeight: extracted.viewportHeight,
    };
  }

  private pruneOldShots(): void {
    try {
      if (!fs.existsSync(this.cacheDir)) return;
      const keep = new Set(
        this.history.map((h) => h.shotPath).filter((p): p is string => Boolean(p && p.startsWith(this.cacheDir)))
      );
      for (const f of fs.readdirSync(this.cacheDir)) {
        const full = path.join(this.cacheDir, f);
        if (f.startsWith('shot-') && f.endsWith('.png') && !keep.has(full)) {
          try {
            fs.unlinkSync(full);
          } catch {
            // ignore
          }
        }
      }
    } catch {
      // ignore
    }
  }

  private assertDomainAllowed(url: string, domainDeny: string[] = []): void {
    if (!domainDeny.length) return;
    let host = '';
    try {
      host = new URL(url).hostname.toLowerCase();
    } catch {
      return;
    }
    if (matchDomain(host, domainDeny)) {
      throw new Error(`Domaine refusé par permissions.yaml : ${host}`);
    }
  }

  async navigate(opts: {
    url: string;
    source: 'user' | 'agent';
    waitMs?: number;
    domainDeny?: string[];
  }): Promise<BrowserActionResult> {
    const clean = String(opts.url || '').trim();
    if (!/^https?:\/\//i.test(clean)) throw new Error('URL http(s) requise');
    this.assertDomainAllowed(clean, opts.domainDeny);

    return this.withLock(async () => {
      const page = await this.ensurePage();
      const response = await page.goto(clean, { waitUntil: 'domcontentloaded', timeout: 25000 });
      this.lastStatus = response ? response.status() : this.lastStatus;
      await this.settle(page, opts.waitMs ?? 400);
      const res = await this.captureAndInspect({
        page,
        source: opts.source,
        requestedUrl: clean,
        pushHistory: true,
      });
      this.assertDomainAllowed(res.finalUrl, opts.domainDeny);
      return res;
    });
  }

  async reload(source: 'user' | 'agent' = 'user'): Promise<BrowserActionResult> {
    return this.withLock(async () => {
      const page = await this.ensurePage();
      const curUrl = page.url();
      if (!curUrl || curUrl === 'about:blank') {
        throw new Error('Aucune page ouverte à recharger');
      }
      const response = await page.reload({ waitUntil: 'domcontentloaded', timeout: 25000 });
      this.lastStatus = response ? response.status() : this.lastStatus;
      await this.settle(page, 350);
      return this.captureAndInspect({
        page,
        source,
        pushHistory: false,
      });
    });
  }

  async click(opts: {
    source: 'user' | 'agent';
    selector?: string;
    text?: string;
    x?: number;
    y?: number;
    domainDeny?: string[];
  }): Promise<BrowserActionResult> {
    return this.withLock(async () => {
      const page = await this.ensurePage();
      const curUrl = page.url();
      if (!curUrl || curUrl === 'about:blank') {
        throw new Error('Aucune page ouverte. Utilisez browser_navigate d’abord.');
      }
      if (typeof opts.x === 'number' && typeof opts.y === 'number') {
        const cx = Math.max(0, Math.min(1279, Math.round(opts.x)));
        const cy = Math.max(0, Math.min(799, Math.round(opts.y)));
        await page.mouse.click(cx, cy);
      } else if (opts.selector) {
        await page.locator(opts.selector).first().click({ timeout: 8000 });
      } else if (opts.text) {
        const loc = page.getByText(opts.text, { exact: false }).first();
        await loc.click({ timeout: 8000 });
      } else {
        throw new Error('selector, text ou coordonnées (x, y) requis pour cliquer');
      }
      await this.settle(page, 450);
      const res = await this.captureAndInspect({
        page,
        source: opts.source,
      });
      this.assertDomainAllowed(res.finalUrl, opts.domainDeny);
      return res;
    });
  }

  async typeText(opts: {
    source: 'user' | 'agent';
    text: string;
    selector?: string;
    clear?: boolean;
    pressEnter?: boolean;
    domainDeny?: string[];
  }): Promise<BrowserActionResult> {
    return this.withLock(async () => {
      const page = await this.ensurePage();
      const curUrl = page.url();
      if (!curUrl || curUrl === 'about:blank') {
        throw new Error('Aucune page ouverte. Utilisez browser_navigate d’abord.');
      }
      const txt = String(opts.text ?? '');
      if (opts.selector) {
        const loc = page.locator(opts.selector).first();
        await loc.click({ timeout: 8000 });
        if (opts.clear !== false) {
          await loc.fill(txt, { timeout: 8000 });
        } else {
          await loc.type(txt, { delay: 15 });
        }
      } else {
        if (opts.clear) {
          await page.keyboard.press('ControlOrMeta+a');
          await page.keyboard.press('Backspace');
        }
        if (txt) {
          await page.keyboard.type(txt, { delay: 15 });
        }
      }
      if (opts.pressEnter) {
        await page.keyboard.press('Enter');
      }
      await this.settle(page, opts.pressEnter ? 550 : 250);
      const res = await this.captureAndInspect({
        page,
        source: opts.source,
      });
      this.assertDomainAllowed(res.finalUrl, opts.domainDeny);
      return res;
    });
  }

  async pressKey(opts: {
    source: 'user' | 'agent';
    key: string;
  }): Promise<BrowserActionResult> {
    return this.withLock(async () => {
      const page = await this.ensurePage();
      const curUrl = page.url();
      if (!curUrl || curUrl === 'about:blank') {
        throw new Error('Aucune page ouverte.');
      }
      await page.keyboard.press(String(opts.key || 'Enter'));
      await this.settle(page, 350);
      return this.captureAndInspect({
        page,
        source: opts.source,
      });
    });
  }

  async selectOption(opts: {
    source: 'user' | 'agent';
    selector: string;
    value?: string;
    label?: string;
  }): Promise<BrowserActionResult> {
    return this.withLock(async () => {
      const page = await this.ensurePage();
      const curUrl = page.url();
      if (!curUrl || curUrl === 'about:blank') {
        throw new Error('Aucune page ouverte.');
      }
      const loc = page.locator(opts.selector).first();
      if (opts.value !== undefined) {
        await loc.selectOption({ value: String(opts.value) }, { timeout: 8000 });
      } else if (opts.label !== undefined) {
        await loc.selectOption({ label: String(opts.label) }, { timeout: 8000 });
      } else {
        throw new Error('value ou label requis pour browser_select');
      }
      await this.settle(page, 300);
      return this.captureAndInspect({
        page,
        source: opts.source,
        pushHistory: false,
      });
    });
  }

  async scroll(opts: {
    source: 'user' | 'agent';
    direction?: 'down' | 'up' | 'top' | 'bottom';
    amount?: number;
    selector?: string;
  }): Promise<BrowserActionResult> {
    return this.withLock(async () => {
      const page = await this.ensurePage();
      const curUrl = page.url();
      if (!curUrl || curUrl === 'about:blank') {
        throw new Error('Aucune page ouverte.');
      }
      const dir = opts.direction || 'down';
      const amt = Math.min(4000, Math.max(50, Math.round(Number(opts.amount || 500))));
      if (opts.selector) {
        const loc = page.locator(opts.selector).first();
        await loc.scrollIntoViewIfNeeded({ timeout: 5000 });
      } else if (dir === 'top') {
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior }));
      } else if (dir === 'bottom') {
        await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' as ScrollBehavior }));
      } else {
        const delta = dir === 'up' ? -amt : amt;
        await page.mouse.wheel(0, delta);
      }
      await this.settle(page, 250);
      return this.captureAndInspect({
        page,
        source: opts.source,
        pushHistory: false,
      });
    });
  }

  async readCurrent(opts: {
    source: 'user' | 'agent';
    selector?: string;
  }): Promise<BrowserActionResult & { selectedText?: string }> {
    return this.withLock(async () => {
      const page = await this.ensurePage();
      const curUrl = page.url();
      if (!curUrl || curUrl === 'about:blank') {
        throw new Error('Aucune page ouverte. Utilisez browser_navigate d’abord.');
      }
      let selectedText: string | undefined;
      if (opts.selector) {
        selectedText = await page.locator(opts.selector).first().innerText({ timeout: 6000 });
      }
      const res = await this.captureAndInspect({
        page,
        source: opts.source,
        pushHistory: false,
      });
      return { ...res, selectedText };
    });
  }

  async back(source: 'user' | 'agent' = 'user'): Promise<BrowserHistoryEntry | null> {
    return this.withLock(async () => {
      if (this.cursor <= 0) return null;
      this.cursor -= 1;
      const target = this.history[this.cursor];
      if (this.page && !this.page.isClosed?.()) {
        try {
          const r = await this.page.goBack({ waitUntil: 'domcontentloaded', timeout: 10000 });
          if (r) {
            this.lastStatus = r.status();
            await this.settle(this.page, 300);
            await this.captureAndInspect({
              page: this.page,
              source,
              requestedUrl: target.url,
              pushHistory: false,
            });
          }
        } catch {
          // fallback to cached history entry
        }
      }
      return this.current();
    });
  }

  async forward(source: 'user' | 'agent' = 'user'): Promise<BrowserHistoryEntry | null> {
    return this.withLock(async () => {
      if (this.cursor < 0 || this.cursor >= this.history.length - 1) return null;
      this.cursor += 1;
      const target = this.history[this.cursor];
      if (this.page && !this.page.isClosed?.()) {
        try {
          const r = await this.page.goForward({ waitUntil: 'domcontentloaded', timeout: 10000 });
          if (r) {
            this.lastStatus = r.status();
            await this.settle(this.page, 300);
            await this.captureAndInspect({
              page: this.page,
              source,
              requestedUrl: target.url,
              pushHistory: false,
            });
          }
        } catch {
          // fallback to cached history entry
        }
      }
      return this.current();
    });
  }

  current(): BrowserHistoryEntry | null {
    if (this.cursor >= 0 && this.cursor < this.history.length) {
      return this.history[this.cursor];
    }
    return null;
  }

  getShotBuffer(id: string): Buffer | null {
    const item = this.history.find((h) => h.id === id) || (id === 'latest' ? this.current() : null);
    if (!item?.shotPath || !fs.existsSync(item.shotPath)) return null;
    try {
      return fs.readFileSync(item.shotPath);
    } catch {
      return null;
    }
  }

  async clearDomainSession(domain: string): Promise<boolean> {
    const clean = String(domain || '').trim().toLowerCase();
    if (!clean) return false;
    const existed = this.domains.delete(clean);
    if (this.context) {
      try {
        const all = await this.context.cookies();
        const kept = all.filter((c: any) => {
          const cd = String(c?.domain || '').replace(/^\./, '').toLowerCase();
          return cd !== clean && !cd.endsWith('.' + clean);
        });
        await this.context.clearCookies();
        if (kept.length) await this.context.addCookies(kept);
      } catch {
        // ignore
      }
    }
    return existed;
  }

  statusPayload(): Record<string, any> {
    const cur = this.current();
    return {
      visible: this.visible,
      user_control: this.userControl,
      can_back: this.cursor > 0,
      can_forward: this.cursor >= 0 && this.cursor < this.history.length - 1,
      current: cur
        ? {
            id: cur.id,
            url: cur.finalUrl,
            title: cur.title,
            status: cur.status,
            ts: cur.ts,
            source: cur.source,
            screenshot: cur.shotPath ? `/browser/screenshot/${cur.id}` : null,
            links: cur.links,
            excerpt: cur.excerpt,
            controls: cur.controls,
            scrollY: cur.scrollY,
            scrollHeight: cur.scrollHeight,
            viewportHeight: cur.viewportHeight,
          }
        : null,
      log: this.history.map((h) => ({
        id: h.id,
        ts: h.ts,
        status: h.status ?? '—',
        url: h.finalUrl,
        title: h.title,
        source: h.source,
      })),
      sessions: [...this.domains.values()],
    };
  }
}

export const browserState = new BrowserController();
