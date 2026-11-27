import type { IDCConfigData } from './types.js';

export const IDC_TOOL_NAME = 'idc_commit';

export function defaultIDCConfig(): IDCConfigData {
  return {
    enabled: false,
    vitality: 100,
    step_cost: 4,
    tool_cost: 3,
    token_cost: 0.5,
    collapse_threshold: 20,
    stall_limit: 3,
    commit_cost: 1,
    unknown_cost: 0.5,
    unsupported_cost: 15,
    revise_cost: 25,
    allow_revise: true,
    child_share: 0.5,
  };
}

export function validateIDCConfig(cfg: IDCConfigData): IDCConfigData {
  if (!(cfg.vitality > 0)) throw new Error('idc: vitality must be > 0');
  const nonNeg: (keyof IDCConfigData)[] = [
    'step_cost', 'tool_cost', 'token_cost', 'commit_cost',
    'unknown_cost', 'unsupported_cost', 'revise_cost', 'collapse_threshold',
  ];
  for (const k of nonNeg) {
    if ((cfg[k] as number) < 0) throw new Error(`idc: ${k} must be >= 0`);
  }
  if (cfg.collapse_threshold >= cfg.vitality) throw new Error('idc: collapse_threshold must be < vitality');
  if (cfg.stall_limit < 1) throw new Error('idc: stall_limit must be >= 1');
  if (!(cfg.child_share > 0 && cfg.child_share <= 1)) throw new Error('idc: child_share must be in (0, 1]');
  if (!(cfg.unknown_cost < cfg.unsupported_cost)) {
    throw new Error("idc: unknown_cost must be lower than unsupported_cost");
  }
  return cfg;
}

export interface IDCCommitment {
  id: string;
  kind: 'fact' | 'decision' | 'answer' | 'unknown';
  text: string;
  evidence: string[];
  supported: boolean;
  cost: number;
  revises?: string;
  agent: string;
}

function norm(text: string): string {
  return String(text || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

export class IDC {
  cfg: IDCConfigData;
  agentId: string;
  lang: string;
  max: number;
  spent = 0;
  reserved = 0;
  stall = 0;
  collapsed: string | null = null;
  onChange: (data: Record<string, any>) => void;
  commitments: IDCCommitment[] = [];
  private seen = new Set<string>();
  private corpus: string[] = [];

  constructor(
    cfg: IDCConfigData,
    opts: { vitality?: number; agentId?: string; lang?: string; onChange?: (data: Record<string, any>) => void; corpus?: string[] } = {}
  ) {
    this.cfg = cfg;
    this.agentId = opts.agentId || 'root';
    this.lang = opts.lang || 'en';
    this.max = opts.vitality ?? cfg.vitality;
    this.onChange = opts.onChange || (() => {});
    this.corpus = [...(opts.corpus || [])];
  }

  get vitality(): number {
    return Math.round((this.max - this.spent - this.reserved) * 10000) / 10000;
  }

  get threshold(): number {
    return Math.round(((this.cfg.collapse_threshold * this.max) / this.cfg.vitality) * 10000) / 10000;
  }

  restore(saved: any[]): void {
    this.commitments = saved.filter((c) => c && typeof c === 'object');
  }

  startTurn(userText: string): void {
    this.spent = 0;
    this.reserved = 0;
    this.stall = 0;
    this.collapsed = null;
    this.seen.clear();
    this.corpus = [userText || ''];
    this.emit();
  }

  private emit(extra: Record<string, any> = {}): void {
    this.onChange({
      vitality: this.vitality,
      max: this.max,
      threshold: this.threshold,
      reserved: this.reserved,
      stall: this.stall,
      collapsed: this.collapsed,
      commitments: this.commitments.length,
      ...extra,
    });
  }

  snapshot(): Record<string, any> {
    return {
      vitality: this.vitality,
      max: this.max,
      threshold: this.threshold,
      reserved: this.reserved,
      stall: this.stall,
      collapsed: this.collapsed,
      commitments: this.commitments.length,
    };
  }

  onStep(tokens: number): void {
    this.spent += this.cfg.step_cost + (tokens / 1000) * this.cfg.token_cost;
    this.emit();
  }

  onTool(observation: string): void {
    this.spent += this.cfg.tool_cost;
    const obs = String(observation || '');
    this.corpus.push(obs);
    const n = norm(obs);
    const isErr = obs.startsWith('ERROR:') || obs.startsWith('DENIED');
    if (isErr || !n || this.seen.has(n)) {
      this.stall += 1;
    } else {
      this.seen.add(n);
      this.stall = 0;
    }
    this.emit();
  }

  shouldCollapse(): string | null {
    if (this.vitality <= 0) return 'exhausted';
    if (this.vitality <= this.threshold) return 'vitality';
    if (this.stall >= this.cfg.stall_limit) return 'stall';
    return null;
  }

  markCollapse(why: string): void {
    this.collapsed = why;
    this.emit();
  }

  commit(args: Record<string, any>): IDCCommitment {
    const kind = String(args.kind || '') as IDCCommitment['kind'];
    if (!['fact', 'decision', 'answer', 'unknown'].includes(kind)) {
      throw new Error("kind must be fact, decision, answer or unknown");
    }
    const text = String(args.text || '').trim();
    if (!text) throw new Error('text is required');
    const evidence = Array.isArray(args.evidence) ? args.evidence.map(String).filter(Boolean) : [];
    const revises = args.revises ? String(args.revises) : undefined;
    if (revises) {
      if (!this.cfg.allow_revise) throw new Error('revisions are disabled');
      if (!this.commitments.some((c) => c.id === revises)) throw new Error(`unknown commitment ${revises}`);
    }
    const corpusNorm = norm(this.corpus.join('\n'));
    const supported =
      kind === 'unknown' ||
      (evidence.length > 0 && evidence.every((q) => corpusNorm.includes(norm(q))));
    let cost = kind === 'unknown' ? this.cfg.unknown_cost : supported ? this.cfg.commit_cost : this.cfg.unsupported_cost;
    if (revises) cost += this.cfg.revise_cost;
    this.spent += cost;
    const entry: IDCCommitment = {
      id: `c${this.commitments.length + 1}`,
      kind,
      text: text.slice(0, 1200),
      evidence: evidence.slice(0, 5),
      supported,
      cost,
      ...(revises ? { revises } : {}),
      agent: this.agentId,
    };
    this.commitments.push(entry);
    this.emit({ commit: entry });
    return entry;
  }

  recordFinal(_text: string): void {
    this.emit();
  }

  fallbackAnswer(): string {
    const ans = [...this.commitments].reverse().find((c) => c.kind === 'answer' && c.supported);
    if (ans) return ans.text;
    const facts = this.commitments.filter((c) => c.supported && c.kind !== 'unknown').map((c) => `- ${c.text}`);
    return facts.length
      ? `I don't have enough vitality to complete this, but here is what was established:\n${facts.join('\n')}`
      : "I don't know (vitality exhausted before reaching a supported answer).";
  }

  static systemRules(ctrl: IDC): string {
    return `\n[IDC Mode Active — Vitality ${ctrl.vitality}/${ctrl.max}, collapse at ${ctrl.threshold}]
- Use idc_commit(kind, text, evidence) to record verified facts, decisions, answers, or "unknown".
- Quote exact substrings from observations in evidence[]. Do not invent evidence.
- When vitality drops to ${ctrl.threshold} or below, you will be asked to give a final answer immediately without tools.\n`;
  }

  static toolSchema(): Record<string, any> {
    return {
      type: 'function',
      function: {
        name: IDC_TOOL_NAME,
        description: 'Record an append-only commitment (fact, decision, answer, unknown) with observed evidence quotes.',
        parameters: {
          type: 'object',
          properties: {
            kind: { type: 'string', enum: ['fact', 'decision', 'answer', 'unknown'] },
            text: { type: 'string' },
            evidence: { type: 'array', items: { type: 'string' } },
            revises: { type: 'string' },
          },
          required: ['kind', 'text'],
        },
      },
    };
  }
}
