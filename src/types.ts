export type Category = 'read' | 'write' | 'execute' | 'network' | 'send' | 'spend' | 'delegate';
export type Mode = 'allow' | 'ask' | 'deny';
export type UIMode = 'simple' | 'expert';
export type TraceMode = 'simple' | 'technical';
export type ThemeMode = 'auto' | 'light' | 'dark';

export interface UsageCounters {
  steps: number;
  tool_calls: number;
  tokens: number;
  cost: number;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | any[] | null;
  tool_calls?: Array<{
    id: string;
    type: 'function';
    function: { name: string; arguments: string };
    extra_content?: Record<string, any>;
    [key: string]: any;
  }>;
  tool_call_id?: string;
  extra_content?: Record<string, any>;
  [key: string]: any;
}

export interface ToolDef {
  name: string;
  description: string;
  category: Category;
  parameters: Record<string, any>;
  subjectKind?: string;
  subjectFn?: (args: Record<string, any>) => string | undefined;
  execute: (ctx: ToolContext, args: Record<string, any>) => Promise<string> | string;
}

export interface ToolContext {
  workspace: string;
  denyPaths: string[];
  pathDeny: string[];
  writePrefix?: string | null;
  taskId?: string | null;
  convDir?: string | null;
  sandboxOn: () => boolean;
  maxOutput: number;
  shellTimeout: number;
  memory: MemoryStore;
  skills: SkillLibrary;
  todos?: TodoStoreLike;
  bricks?: BrickLibraryLike;
  community?: CommunityHubLike;
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

export interface CommunityHubLike {
  sync(force?: boolean): Promise<{ items: CommunityItem[]; lastSync: string; count: number; synced: boolean }>;
  importItem(id: string, bricksLib: BrickLibraryLike, skillsLib: SkillLibrary): { ok: boolean; type: string; id: string; name: string };
  publishToGitHub(kind: 'brick' | 'skill', id: string, bricksLib: BrickLibraryLike, skillsLib: SkillLibrary, token?: string, repo?: string): Promise<{ ok: boolean; url: string; message: string }>;
}

export interface MemoryEntry {
  id?: string;
  ts?: string;
  kind: string;
  tags?: string[];
  text: string;
  score?: number;
}

export interface MemoryStore {
  write(text: string, kind?: string, tags?: string[]): MemoryEntry;
  recall(query: string, limit?: number): MemoryEntry[];
  forget(query: string): number;
  context(): string;
  status(): { semantic: boolean; vectors: number; model: string | null; error: string | null };
}

export interface SkillInfo {
  name: string;
  description: string;
  source: string;
  path: string;
}

export interface SkillLibrary {
  reload(): void;
  listDetailed(): SkillInfo[];
  names(): string[];
  index(): string;
  load(name: string): string;
}

export type TodoKind = 'brick' | 'skill' | 'both';

export interface TodoItem {
  id: string;
  done: boolean;
  title: string;
  details: string;
  kind: TodoKind;
  createdAt: string;
  brickId?: string;
  skillName?: string;
  note?: string;
}

export interface TodoStoreLike {
  filePath: string;
  readRaw(): string;
  list(): TodoItem[];
  add(input: { title: string; details?: string; kind?: TodoKind }): { item: TodoItem; created: boolean };
  update(
    id: string,
    patch: { status?: 'done' | 'pending' | 'delete'; brickId?: string; skillName?: string; note?: string }
  ): { item: TodoItem | null; removed: boolean };
  pendingContext(limit?: number): string;
}

export interface BrickInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  placement: 'dock' | 'panel';
  height: number;
  enabled: boolean;
  skill?: string;
  todoId?: string;
  createdAt: string;
  updatedAt: string;
  url: string;
}

export interface BrickLibraryLike {
  list(): BrickInfo[];
  get(id: string): BrickInfo | null;
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
  }): BrickInfo;
  setEnabled(id: string, enabled: boolean): BrickInfo;
  delete(id: string): boolean;
  index(): string;
}

export interface IDCConfigData {
  enabled: boolean;
  vitality: number;
  step_cost: number;
  tool_cost: number;
  token_cost: number;
  collapse_threshold: number;
  stall_limit: number;
  commit_cost: number;
  unknown_cost: number;
  unsupported_cost: number;
  revise_cost: number;
  allow_revise: boolean;
  child_share: number;
}

export interface AgentNodeInfo {
  id: string;
  parent: string | null;
  depth: number;
  task: string;
  status: string;
  answer: string | null;
  steps?: number;
  max_steps?: number | null;
  isolated?: boolean;
  handoff?: boolean;
  critic?: boolean;
  score?: number | null;
  role?: string;
  key?: string;
  key_mask?: string;
  key_task?: string;
  key_match?: boolean;
  keys?: string[];
  earlier?: boolean;
  turn?: number;
}

export interface TaskEvent {
  seq: number;
  ts: string;
  kind: string;
  [key: string]: any;
}

export interface ProviderRecord {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  model: string;
  categories: string[];
  priority: number;
  limits: Record<string, number>;
  pricing: Record<string, number>;
  tasks: string[];
  enabled: boolean;
  has_key?: boolean;
  created: string;
  updated: string;
}
