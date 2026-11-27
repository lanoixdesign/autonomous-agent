export const MASK = '***REDACTED***';

const SECRET_RE = [
  /sk-[A-Za-z0-9_-]{12,}/g,
  /sk-or-[A-Za-z0-9_-]{12,}/g,
  /sk-ant-[A-Za-z0-9_-]{12,}/g,
  /gsk_[A-Za-z0-9]{12,}/g,
  /AIza[0-9A-Za-z_-]{20,}/g,
  /ghp_[A-Za-z0-9]{20,}/g,
  /gho_[A-Za-z0-9]{20,}/g,
  /github_pat_[A-Za-z0-9_]{20,}/g,
  /Bearer\s+[A-Za-z0-9._-]{16,}/gi,
];

const SECRET_KEYS = new Set(['key', 'api_key', 'apikey', 'token', 'secret', 'password', 'authorization']);

export function maskSecret(secret?: string | null): string {
  if (!secret) return '(not set)';
  if (secret.length <= 12) return '****';
  return `${secret.slice(0, 4)}…${secret.slice(-4)}`;
}

export function maskUi(secret?: string | null): string {
  if (!secret) return '';
  if (secret.length <= 12) return '••••';
  return `${secret.slice(0, 4)}••••${secret.slice(-4)}`;
}

export function redactText(text: string, extra: string[] = []): string {
  let out = text;
  for (const s of extra) {
    if (s && s.length >= 6) {
      out = out.split(s).join(MASK);
    }
  }
  for (const re of SECRET_RE) {
    out = out.replace(re, MASK);
  }
  return out;
}

export function redact<T>(val: T, extra: string[] = []): T {
  if (val === null || val === undefined) return val;
  if (typeof val === 'string') return redactText(val, extra) as unknown as T;
  if (Array.isArray(val)) return val.map((x) => redact(x, extra)) as unknown as T;
  if (typeof val === 'object') {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(val as Record<string, any>)) {
      if (SECRET_KEYS.has(k.toLowerCase()) && typeof v === 'string' && v.length > 0) {
        out[k] = MASK;
      } else {
        out[k] = redact(v, extra);
      }
    }
    return out as T;
  }
  return val;
}

export function shortValue<T>(val: T, maxLen = 400): T {
  if (typeof val === 'string') {
    return (val.length > maxLen ? val.slice(0, maxLen) + '…' : val) as unknown as T;
  }
  if (Array.isArray(val)) return val.map((x) => shortValue(x, maxLen)) as unknown as T;
  if (val && typeof val === 'object') {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(val as Record<string, any>)) {
      out[k] = shortValue(v, maxLen);
    }
    return out as T;
  }
  return val;
}

export function scrubbedEnv(): NodeJS.ProcessEnv {
  const out: NodeJS.ProcessEnv = {};
  for (const [k, v] of Object.entries(process.env)) {
    const up = k.toUpperCase();
    if (up.includes('KEY') || up.includes('TOKEN') || up.includes('SECRET') || up.includes('PASSWORD')) {
      continue;
    }
    out[k] = v;
  }
  return out;
}
