import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const assetsPath = path.join(__dirname, 'assets.json');
const assets = JSON.parse(fs.readFileSync(assetsPath, 'utf-8')) as {
  pages: Record<string, string>;
  i18n: Record<string, Record<string, string>>;
  langs: string[];
  theme: { CALM_CSS: string; SIMPLE_CSS: string; THEME_HEAD: string };
  pwa: {
    HEAD: string;
    REGISTER_JS: string;
    SW_JS: string;
    MANIFEST: string;
    ICON_SVG: string;
    PNG_32: string;
    PNG_180: string;
    PNG_192: string;
    PNG_512: string;
  };
};

const I18N_DATA = JSON.stringify(assets.i18n).replace(/<\//g, '<\\/');

export type PageName = 'chat' | 'dashboard' | 'connect' | 'settings' | 'welcome' | 'help' | 'dev';

export function normalizeLang(lang?: string | null): 'en' | 'fr' {
  const l = String(lang || '').trim().toLowerCase().slice(0, 2);
  return l === 'fr' ? 'fr' : 'en';
}

export function t(lang: string | null | undefined, key: string, vars: Record<string, any> = {}): string {
  const l = normalizeLang(lang);
  const dict = assets.i18n[l] || assets.i18n.en;
  let tpl = dict[key] ?? assets.i18n.en[key] ?? key;
  for (const [k, v] of Object.entries(vars)) {
    tpl = tpl.replaceAll(`{${k}}`, String(v ?? ''));
  }
  return tpl;
}

export function hasEnKey(key: string): boolean {
  return key in (assets.i18n.en || {});
}

export function detectLang(text?: string | null): 'en' | 'fr' | null {
  const s = String(text || '').toLowerCase();
  if (!s.trim()) return null;
  if (/[àâçéèêëîïôùûüœæ]/.test(s)) return 'fr';
  const frWords = (s.match(/\b(le|la|les|des|un|une|est|pour|avec|dans|sur|qui|que|pas|bonjour|merci|mon|ton|fichier|fichiers)\b/g) || []).length;
  const enWords = (s.match(/\b(the|and|for|with|that|this|from|have|hello|please|file|files|what|how|you|your)\b/g) || []).length;
  if (frWords > enWords && frWords >= 1) return 'fr';
  if (enWords > frWords && enWords >= 1) return 'en';
  return null;
}

export function languageRule(lang: string): string {
  return lang === 'fr'
    ? 'Language: ALWAYS reply in French (français), including headings and explanations.'
    : 'Language: ALWAYS reply in English.';
}

export function renderPage(
  pageName: PageName,
  lang?: string | null,
  defaultLang?: string | null,
  theme?: string | null,
  ui?: string | null
): string {
  let out = assets.pages[pageName] || assets.pages.chat;
  out = out.replace('/*I18N_DATA*/{}', I18N_DATA);
  if (defaultLang && assets.langs.includes(defaultLang)) {
    out = out.replace('const I18N_DEFAULT = null;', `const I18N_DEFAULT = "${defaultLang}";`);
  }
  const safeTheme = theme === 'auto' || theme === 'light' || theme === 'dark' ? theme : 'auto';
  let th = assets.theme.THEME_HEAD.replace('"__THEME_DEFAULT__"', JSON.stringify(safeTheme));
  th += `<script>document.documentElement.setAttribute("data-ui","${ui === 'expert' ? 'expert' : 'simple'}");</script>`;
  out = out.replace('<meta charset="utf-8">', `<meta charset="utf-8">\n${assets.pwa.HEAD}\n${th}`);
  out = out.replace('width=device-width, initial-scale=1', 'width=device-width, initial-scale=1, viewport-fit=cover');
  out = out.replace('</script></body></html>', `${assets.pwa.REGISTER_JS}\n</script></body></html>`);
  out = out.replace('</head>', `<style>${assets.theme.CALM_CSS}${assets.theme.SIMPLE_CSS}</style></head>`);
  if (lang) {
    out = out.replace('<html lang="en">', `<html lang="${normalizeLang(lang)}">`);
  }
  return out;
}

const iconCache = new Map<number, Buffer>();
function iconPng(size: number): Buffer {
  const cached = iconCache.get(size);
  if (cached) return cached;
  const b64 =
    size === 32 ? assets.pwa.PNG_32 :
    size === 180 ? assets.pwa.PNG_180 :
    size === 192 ? assets.pwa.PNG_192 :
    assets.pwa.PNG_512;
  const buf = Buffer.from(b64, 'base64');
  iconCache.set(size, buf);
  return buf;
}

export function getPwaAsset(reqPath: string): { ctype: string; body: Buffer | string; cache: string } | null {
  if (reqPath === '/manifest.webmanifest') {
    return { ctype: 'application/manifest+json; charset=utf-8', body: assets.pwa.MANIFEST, cache: 'no-cache' };
  }
  if (reqPath === '/sw.js') {
    return { ctype: 'text/javascript; charset=utf-8', body: assets.pwa.SW_JS, cache: 'no-cache' };
  }
  if (reqPath === '/icon.svg') {
    return { ctype: 'image/svg+xml; charset=utf-8', body: assets.pwa.ICON_SVG, cache: 'max-age=86400' };
  }
  const sizes: Record<string, number> = {
    '/favicon.png': 32,
    '/favicon.ico': 32,
    '/icon-192.png': 192,
    '/icon-512.png': 512,
    '/apple-touch-icon.png': 180,
  };
  if (reqPath in sizes) {
    return { ctype: 'image/png', body: iconPng(sizes[reqPath]), cache: 'max-age=86400' };
  }
  return null;
}
